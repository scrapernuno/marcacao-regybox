import json
import os
import re
import smtplib
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from playwright.sync_api import (
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

REGYBOX_URL = "https://www.regibox.pt/app/app_nova/login.php"
NOME_BOX = "Naval Box"

USERNAME = os.environ.get("REGYBOX_USER", "").strip()
PASSWORD = os.environ.get("REGYBOX_PASS", "").strip()

TIMEZONE = ZoneInfo("Atlantic/Madeira")
DIAS_ANTECEDENCIA = 4
HORA_ALVO = "18:25"

# Ordem de escolha. HIROX cobre uma eventual grafia alternativa.
PRIORIDADES = [
    "HYROX",
    "HIROX",
    "STRENGHT",
    "STRENGTH",
    "CROSSFIT",
]

MAX_ESPERA_ABERTURA_SEGUNDOS = 10 * 60
INTERVALO_CONSULTA_SEGUNDOS = 1
TEMPO_EXTRA_APOS_TIMEOUT_SEGUNDOS = 90
TIMEOUT_PADRAO_MS = 10_000

PASTA_DIAGNOSTICO = Path("diagnostico_regybox")


# ============================================================
# MODELO
# ============================================================

@dataclass
class AulaVisual:
    nome: str
    inicio: str
    fim: str
    texto: str
    indice_prioridade: int
    inscrito: bool
    lista_espera: bool
    botao_reservar: bool
    botao_lista_espera: bool
    elemento_indice: int


# ============================================================
# UTILITÁRIOS
# ============================================================

def normalizar(texto: str) -> str:
    return " ".join((texto or "").replace("\xa0", " ").split())


def normalizar_upper(texto: str) -> str:
    return normalizar(texto).upper()


def prioridade(nome: str) -> int:
    nome_upper = normalizar_upper(nome)

    for indice, modalidade in enumerate(PRIORIDADES):
        if modalidade in nome_upper:
            return indice

    return 999


def preparar_diagnostico() -> None:
    PASTA_DIAGNOSTICO.mkdir(parents=True, exist_ok=True)


def guardar_texto(nome: str, conteudo: str) -> None:
    preparar_diagnostico()
    (PASTA_DIAGNOSTICO / nome).write_text(conteudo, encoding="utf-8")


def guardar_json(nome: str, conteudo) -> None:
    preparar_diagnostico()
    (PASTA_DIAGNOSTICO / nome).write_text(
        json.dumps(conteudo, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def guardar_pagina(page: Page, nome: str) -> None:
    preparar_diagnostico()

    try:
        page.screenshot(
            path=str(PASTA_DIAGNOSTICO / f"{nome}.png"),
            full_page=True,
        )
    except Exception as exc:
        print(f"⚠️ Não foi possível guardar screenshot {nome}: {exc}")

    try:
        guardar_texto(f"{nome}.html", page.content())
    except Exception as exc:
        print(f"⚠️ Não foi possível guardar HTML {nome}: {exc}")

    try:
        guardar_texto(
            f"{nome}.txt",
            page.locator("body").inner_text(timeout=5_000),
        )
    except Exception as exc:
        print(f"⚠️ Não foi possível guardar texto {nome}: {exc}")


def clicar_primeiro_visivel(
    locator: Locator,
    timeout_ms: int = 4_000,
) -> bool:
    try:
        total = locator.count()
    except Exception:
        return False

    for indice in range(min(total, 100)):
        elemento = locator.nth(indice)

        try:
            if not elemento.is_visible():
                continue

            elemento.scroll_into_view_if_needed(timeout=timeout_ms)
            elemento.click(timeout=timeout_ms, force=True)
            return True
        except Exception:
            continue

    return False


def preencher_primeiro_visivel(locator: Locator, valor: str) -> bool:
    try:
        total = locator.count()
    except Exception:
        return False

    for indice in range(min(total, 50)):
        elemento = locator.nth(indice)

        try:
            if not elemento.is_visible():
                continue

            elemento.fill(valor)
            return True
        except Exception:
            continue

    return False


# ============================================================
# EMAIL
# ============================================================

def enviar_email_confirmacao(
    aula: AulaVisual,
    data_alvo: date,
    estado: str,
) -> None:
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "").strip()
    smtp_port_texto = os.environ.get("EMAIL_SMTP_PORT", "587").strip()
    email_user = os.environ.get("EMAIL_USER", "").strip()
    email_password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    email_to = os.environ.get("EMAIL_TO", "").strip()

    if not all(
        [smtp_host, smtp_port_texto, email_user, email_password, email_to]
    ):
        print("ℹ️ Email não configurado; a marcação mantém-se válida.")
        return

    try:
        smtp_port = int(smtp_port_texto)
    except ValueError:
        print("⚠️ EMAIL_SMTP_PORT inválido; email não enviado.")
        return

    mensagem = EmailMessage()
    mensagem["Subject"] = (
        f"Regibox: {estado} — {aula.nome} às {aula.inicio}"
    )
    mensagem["From"] = email_user
    mensagem["To"] = email_to
    mensagem.set_content(
        "\n".join(
            [
                "A marcação na Regibox foi confirmada.",
                "",
                f"Estado: {estado}",
                f"Aula: {aula.nome}",
                f"Data: {data_alvo.strftime('%d/%m/%Y')}",
                f"Hora: {aula.inicio} - {aula.fim}",
                "",
                "Mensagem enviada automaticamente pelo GitHub Actions.",
            ]
        )
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as servidor:
            servidor.ehlo()
            servidor.starttls()
            servidor.ehlo()
            servidor.login(email_user, email_password)
            servidor.send_message(mensagem)

        print(f"📧 Email enviado para {email_to}.")
    except Exception as exc:
        print(
            "⚠️ A inscrição foi confirmada, mas o email falhou: "
            f"{type(exc).__name__}: {exc}"
        )


# ============================================================
# LOGIN
# ============================================================

def formulario_login_visivel(page: Page) -> bool:
    campo = page.locator("input[type='password'], input[name*='pass' i]")

    try:
        return campo.count() > 0 and campo.first.is_visible()
    except Exception:
        return False


def selecionar_box(page: Page) -> None:
    print(f"🔍 A selecionar a Box: {NOME_BOX}...")

    for tentativa in range(1, 6):
        if formulario_login_visivel(page):
            print("✅ Formulário de login já disponível.")
            return

        campos = page.locator(
            "input[placeholder*='Procura' i], "
            "input[placeholder*='Pesquisa' i], "
            "input[placeholder*='Pesquisar' i], "
            "input[placeholder*='box' i], "
            "input[type='search'], input[type='text']"
        )

        try:
            total = campos.count()
        except Exception:
            total = 0

        for indice in range(min(total, 30)):
            campo = campos.nth(indice)

            try:
                if not campo.is_visible():
                    continue

                campo.click(force=True)
                campo.fill("")
                campo.fill(NOME_BOX)
                page.wait_for_timeout(1_200)

                opcoes = page.get_by_text(NOME_BOX, exact=False)

                if clicar_primeiro_visivel(opcoes, 3_000):
                    page.wait_for_timeout(1_500)

                    if formulario_login_visivel(page):
                        print("✅ Box selecionada.")
                        return
            except Exception:
                continue

        print(f"🔄 Nova tentativa de seleção da Box ({tentativa}/5)...")
        page.reload(wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2_500)

    guardar_pagina(page, "erro_selecao_box")
    raise RuntimeError(f"Não foi possível selecionar a Box '{NOME_BOX}'.")


def autenticar(page: Page) -> None:
    print("🔐 A abrir a página de login...")
    page.goto(REGYBOX_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(4_000)

    guardar_pagina(page, "00_login_inicial")
    selecionar_box(page)

    print("🔑 A preencher os dados de acesso...")

    utilizador = page.locator(
        "input[type='email'], input[name*='user' i], "
        "input[name*='email' i], input[placeholder*='mail' i], "
        "input[placeholder*='utilizador' i], input[autocomplete='username']"
    )
    password = page.locator(
        "input[type='password'], input[name*='pass' i], "
        "input[autocomplete='current-password']"
    )

    if not preencher_primeiro_visivel(utilizador, USERNAME):
        guardar_pagina(page, "erro_utilizador")
        raise RuntimeError("Campo de utilizador/e-mail não encontrado.")

    if not preencher_primeiro_visivel(password, PASSWORD):
        guardar_pagina(page, "erro_password")
        raise RuntimeError("Campo de password não encontrado.")

    print("🚀 A efetuar login...")

    botoes = page.locator(
        "button:has-text('LOGIN'), button:has-text('ENTRAR'), "
        "input[type='submit'], input[value*='LOGIN' i], "
        "input[value*='ENTRAR' i]"
    )

    if not clicar_primeiro_visivel(botoes, 5_000):
        page.keyboard.press("Enter")

    try:
        page.wait_for_url(
            re.compile(r"/app/app_nova/index\.php", re.IGNORECASE),
            timeout=25_000,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(5_000)

    if "login.php" in page.url.lower():
        guardar_pagina(page, "erro_login")
        raise RuntimeError("O login não foi concluído.")

    print(f"✅ Login concluído: {page.url}")
    guardar_pagina(page, "01_login_concluido")


# ============================================================
# NAVEGAÇÃO PARA AULAS E DATA
# ============================================================

def abrir_aulas(page: Page) -> None:
    print("📚 A abrir AULAS...")

    seletores = [
        page.get_by_text("AULAS", exact=True),
        page.locator("a:has-text('AULAS'), button:has-text('AULAS')"),
        page.locator("[onclick*='marca_aulas.php']"),
        page.locator("[onclick*='calendario_aulas']"),
    ]

    for locator in seletores:
        if clicar_primeiro_visivel(locator, 5_000):
            page.wait_for_timeout(3_000)
            print("✅ Área de aulas aberta.")
            return

    # Último recurso: executar a função usada pela própria página.
    resultado = page.evaluate(
        """
        () => {
            try {
                if (typeof load_script === 'function') {
                    load_script('../app_nova/php/aulas/marca_aulas.php');
                    return 'load_script';
                }
                if (typeof calendario_aulas === 'function') {
                    calendario_aulas();
                    return 'calendario_aulas';
                }
            } catch (erro) {
                return 'erro:' + String(erro);
            }
            return 'indisponivel';
        }
        """
    )

    print(f"🔧 Fallback de navegação: {resultado}")
    page.wait_for_timeout(3_000)

    if "18:25" not in normalizar(page.locator("body").inner_text()):
        guardar_pagina(page, "erro_abrir_aulas")
        raise RuntimeError("Não foi possível abrir o calendário de aulas.")


def selecionar_data(page: Page, data_alvo: date) -> None:
    data_iso = data_alvo.isoformat()
    print(f"📅 A selecionar {data_iso} no calendário...")

    # Conta cartões visíveis antes da mudança. Serve apenas como diagnóstico;
    # a proteção principal contra conteúdo antigo está em inventariar_aulas(),
    # que agora ignora qualquer cartão oculto.
    try:
        visiveis_antes = page.locator(
            ".filtro0:visible, [class*='filtro']:visible, li:visible, tr:visible"
        ).count()
    except Exception:
        visiveis_antes = -1

    seletor = f"[onclick*=\"wods_dia('{data_iso}')\"]"
    elementos = page.locator(seletor)

    clicou = clicar_primeiro_visivel(elementos, 6_000)

    if not clicou:
        resultado = page.evaluate(
            """
            dataIso => {
                try {
                    if (typeof window.wods_dia === 'function') {
                        window.wods_dia(dataIso);
                        return true;
                    }
                } catch (erro) {
                    return String(erro);
                }
                return false;
            }
            """,
            data_iso,
        )

        print(f"🔧 Resultado de wods_dia: {resultado}")

        if resultado is not True:
            guardar_pagina(page, f"erro_selecionar_data_{data_iso}")
            raise RuntimeError(f"Não foi possível selecionar {data_iso}.")

    # A Regibox atualiza o painel por AJAX. Damos tempo para concluir e,
    # quando possível, aguardamos um curto período de inatividade de rede.
    try:
        page.wait_for_load_state("networkidle", timeout=4_000)
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(1_500)

    try:
        visiveis_depois = page.locator(
            ".filtro0:visible, [class*='filtro']:visible, li:visible, tr:visible"
        ).count()
    except Exception:
        visiveis_depois = -1

    print(
        f"✅ Dia {data_iso} selecionado. "
        f"Elementos visíveis antes/depois: "
        f"{visiveis_antes}/{visiveis_depois}."
    )


# ============================================================
# DESCOBERTA E MARCAÇÃO VISUAL
# ============================================================

def inventariar_aulas(page: Page) -> list[AulaVisual]:
    dados = page.evaluate(
        """
        horaAlvo => {
            function norm(valor) {
                return (valor || '').replace(/\s+/g, ' ').trim();
            }

            function visivel(el) {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && rect.width > 0
                    && rect.height > 0;
            }

            const todos = Array.from(document.querySelectorAll('div, li, tr'));
            const candidatos = todos.filter(el => {
                if (!visivel(el)) return false;

                const texto = norm(el.innerText || el.textContent);
                if (!texto.includes(horaAlvo)) return false;
                const filhosComHora = Array.from(el.children || []).filter(filho =>
                    norm(filho.innerText || filho.textContent).includes(horaAlvo)
                );
                return filhosComHora.length === 0 || el.classList.contains('filtro0');
            });

            const resultado = [];
            const vistos = new Set();

            for (const el of candidatos) {
                const card = el.closest('.filtro0, [class*="filtro"], li, tr') || el;
                if (!visivel(card)) continue;

                const texto = norm(card.innerText || card.textContent);
                if (!texto.includes(horaAlvo)) continue;

                const chave = texto.substring(0, 500);
                if (vistos.has(chave)) continue;
                vistos.add(chave);

                const acoes = Array.from(
                    card.querySelectorAll('button, a, [onclick], [role="button"]')
                ).filter(visivel);

                const reservar = acoes.some(acao => {
                    const t = norm(
                        acao.innerText
                        || acao.textContent
                        || acao.value
                        || acao.getAttribute('aria-label')
                        || acao.getAttribute('title')
                    ).toUpperCase();

                    const onclick = (acao.getAttribute('onclick') || '').toUpperCase();
                    const href = (acao.getAttribute('href') || '').toUpperCase();

                    const perigoso =
                        t.includes('CANCELAR')
                        || t.includes('CANCEL')
                        || t.includes('SAIR')
                        || t.includes('REMOVER')
                        || t.includes('APAGAR')
                        || t.includes('EXCLUIR')
                        || t.includes('ANULAR')
                        || t.includes('DESMARCAR')
                        || t.includes('LISTA DE ESPERA');

                    if (perigoso) return false;

                    return t.includes('RESERVAR')
                        || t.includes('INSCREVER')
                        || t.includes('MARCAR')
                        || onclick.includes('MARCA_AULAS')
                        || onclick.includes('RESERV')
                        || onclick.includes('INSCREV')
                        || href.includes('MARCA_AULAS')
                        || href.includes('RESERV')
                        || href.includes('INSCREV');
                });

                const listaEsperaDisponivel = acoes.some(acao => {
                    const t = norm(acao.innerText || acao.textContent).toUpperCase();
                    return t.includes('LISTA DE ESPERA')
                        || t.includes('ENTRAR NA LISTA')
                        || t.includes('ESPERA');
                });

                const textoUpper = texto.toUpperCase();

                const inscrito =
                    /JÁ\s*INSCRIT[OA]|JA\s*INSCRIT[OA]/.test(textoUpper)
                    || /RESERVA\s*CONFIRMADA/.test(textoUpper)
                    || /INSCRIÇÃO\s*CONFIRMADA|INSCRICAO\s*CONFIRMADA/.test(textoUpper);

                const espera =
                    /SAIR\s*DA\s*LISTA\s*DE\s*ESPERA/.test(textoUpper)
                    || /CANCELAR\s*(A\s*)?LISTA\s*DE\s*ESPERA/.test(textoUpper)
                    || /JÁ\s*NA\s*LISTA\s*DE\s*ESPERA|JA\s*NA\s*LISTA\s*DE\s*ESPERA/.test(textoUpper);
                const horario = texto.match(/(\d{1,2}:\d{2})\s*(?:-|>>|A)\s*(\d{1,2}:\d{2})/i);

                resultado.push({
                    texto,
                    inicio: horario ? horario[1] : horaAlvo,
                    fim: horario ? horario[2] : '',
                    reservar,
                    listaEsperaDisponivel,
                    inscrito,
                    espera,
                    html: card.outerHTML.substring(0, 4000),
                });
            }

            return resultado;
        }
        """,
        HORA_ALVO,
    )

    aulas: list[AulaVisual] = []

    for indice, item in enumerate(dados):
        texto = normalizar(item.get("texto", ""))
        nome = ""
        texto_upper = texto.upper()

        for modalidade in PRIORIDADES:
            if modalidade in texto_upper:
                nome = modalidade
                break

        if not nome:
            nome = texto.split(" ")[0] if texto else "DESCONHECIDA"

        aulas.append(
            AulaVisual(
                nome=nome,
                inicio=item.get("inicio") or HORA_ALVO,
                fim=item.get("fim") or "",
                texto=texto,
                indice_prioridade=prioridade(nome),
                inscrito=bool(item.get("inscrito")),
                lista_espera=bool(item.get("espera")),
                botao_reservar=bool(item.get("reservar")),
                botao_lista_espera=bool(item.get("listaEsperaDisponivel")),
                elemento_indice=indice,
            )
        )

    guardar_json(
        "aulas_visuais.json",
        [asdict(aula) for aula in aulas],
    )

    return aulas


def localizar_card_prioritario(page: Page, aula: AulaVisual) -> Locator:
    modalidade = aula.nome

    cards = page.locator(".filtro0, [class*='filtro'], li, tr, div").filter(
        has_text=HORA_ALVO
    )

    if modalidade and modalidade != "DESCONHECIDA":
        cards = cards.filter(has_text=modalidade)

    return cards


def clicar_reservar_no_card(page: Page, aula: AulaVisual) -> bool:
    """
    Clica exclusivamente numa ação de reserva/inscrição da aula escolhida.

    Nunca usa um botão genérico como fallback. Isto evita cliques em elementos
    alheios à reserva (por exemplo "STAR 11") e mantém bloqueadas ações
    destrutivas como CANCELAR.
    """
    cards = localizar_card_prioritario(page, aula)

    try:
        total = cards.count()
    except Exception:
        total = 0

    for indice in range(min(total, 100)):
        card = cards.nth(indice)

        try:
            texto_card = normalizar_upper(card.inner_text(timeout=2_000))
        except Exception:
            continue

        if HORA_ALVO not in texto_card:
            continue

        if aula.nome not in texto_card and aula.nome != "DESCONHECIDA":
            continue

        try:
            card.scroll_into_view_if_needed(timeout=4_000)
        except Exception:
            pass

        # Procura explicitamente RESERVAR / INSCREVER / MARCAR,
        # incluindo botões, links, inputs e elementos com onclick.
        seletores = [
            "button:has-text('RESERVAR')",
            "a:has-text('RESERVAR')",
            "[role='button']:has-text('RESERVAR')",
            "[onclick]:has-text('RESERVAR')",
            "input[type='button'][value*='RESERVAR' i]",
            "input[type='submit'][value*='RESERVAR' i]",
            "button:has-text('INSCREVER')",
            "a:has-text('INSCREVER')",
            "[role='button']:has-text('INSCREVER')",
            "[onclick]:has-text('INSCREVER')",
            "input[type='button'][value*='INSCREVER' i]",
            "input[type='submit'][value*='INSCREVER' i]",
            "button:has-text('MARCAR')",
            "a:has-text('MARCAR')",
            "[role='button']:has-text('MARCAR')",
            "[onclick]:has-text('MARCAR')",
        ]

        for seletor in seletores:
            try:
                loc = card.locator(seletor)
                qtd = loc.count()
            except Exception:
                continue

            for j in range(min(qtd, 20)):
                alvo = loc.nth(j)

                try:
                    if not alvo.is_visible():
                        continue

                    rotulo = normalizar_upper(
                        (alvo.inner_text(timeout=1_500) or "")
                        or (alvo.get_attribute("value") or "")
                        or (alvo.get_attribute("aria-label") or "")
                        or (alvo.get_attribute("title") or "")
                    )

                    proibidos = [
                        "CANCELAR",
                        "CANCEL",
                        "SAIR",
                        "REMOVER",
                        "APAGAR",
                        "EXCLUIR",
                        "ANULAR",
                        "DESMARCAR",
                        "LISTA DE ESPERA",
                    ]

                    if any(p in rotulo for p in proibidos):
                        print(f"🛑 Ação ignorada por segurança: {rotulo}")
                        continue

                    alvo.scroll_into_view_if_needed(timeout=3_000)
                    alvo.click(timeout=4_000, force=True)
                    print(
                        "🖱️ Clique efetuado na ação de reserva: "
                        f"{rotulo or '(sem texto)'}"
                    )
                    return True

                except Exception:
                    continue

        # Última tentativa: onclick/href que revele semanticamente uma reserva.
        resultado = card.evaluate(
            """
            card => {
                function norm(valor) {
                    return (valor || '').replace(/\\s+/g, ' ').trim().toUpperCase();
                }

                function visivel(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                }

                const elementos = Array.from(
                    card.querySelectorAll(
                        'button, a, [onclick], [role="button"], input[type="button"], input[type="submit"]'
                    )
                ).filter(visivel);

                const alvo = elementos.find(el => {
                    const texto = norm(
                        el.innerText
                        || el.textContent
                        || el.value
                        || el.getAttribute('aria-label')
                        || el.getAttribute('title')
                    );
                    const onclick = norm(el.getAttribute('onclick'));
                    const href = norm(el.getAttribute('href'));

                    const proibido =
                        texto.includes('CANCELAR')
                        || texto.includes('CANCEL')
                        || texto.includes('SAIR')
                        || texto.includes('REMOVER')
                        || texto.includes('APAGAR')
                        || texto.includes('EXCLUIR')
                        || texto.includes('ANULAR')
                        || texto.includes('DESMARCAR')
                        || texto.includes('LISTA DE ESPERA');

                    if (proibido) return false;

                    return texto.includes('RESERVAR')
                        || texto.includes('INSCREVER')
                        || texto.includes('MARCAR')
                        || onclick.includes('MARCA_AULAS')
                        || onclick.includes('RESERV')
                        || onclick.includes('INSCREV')
                        || href.includes('MARCA_AULAS')
                        || href.includes('RESERV')
                        || href.includes('INSCREV');
                });

                if (!alvo) {
                    return {clicou: false, texto: ''};
                }

                const textoAlvo = norm(
                    alvo.innerText
                    || alvo.textContent
                    || alvo.value
                    || alvo.getAttribute('aria-label')
                    || alvo.getAttribute('title')
                );

                alvo.scrollIntoView({block: 'center'});
                alvo.click();

                return {
                    clicou: true,
                    texto: textoAlvo || '(sem texto)'
                };
            }
            """
        )

        if isinstance(resultado, dict) and resultado.get("clicou"):
            print(
                "🖱️ Clique efetuado na ação de reserva: "
                f"{resultado.get('texto', '(sem texto)')}"
            )
            return True

    # Guarda diagnóstico para vermos exatamente os controlos existentes
    # no cartão quando a Regibox indicar que a aula está aberta.
    guardar_pagina(page, "erro_botao_reservar_nao_encontrado")
    print(
        "⚠️ Não encontrei uma ação explícita RESERVAR/INSCREVER/MARCAR "
        "no cartão da aula. Nenhum botão genérico foi clicado."
    )
    return False

def confirmar_modal(page: Page) -> None:
    """
    Confirma apenas ações positivas.
    Nunca clica em CANCELAR, SAIR, REMOVER, ANULAR, DESMARCAR
    ou outros controlos destrutivos.
    """
    page.wait_for_timeout(800)

    botoes = page.locator(
        "button:has-text('SIM'), "
        "button:has-text('CONFIRMAR'), "
        "button:has-text('OK'), "
        "button:has-text('RESERVAR'), "
        "button:has-text('INSCREVER'), "
        "a:has-text('SIM'), "
        "a:has-text('CONFIRMAR'), "
        "a:has-text('RESERVAR')"
    )

    try:
        total = botoes.count()
    except Exception:
        total = 0

    for indice in range(min(total, 50)):
        botao = botoes.nth(indice)

        try:
            if not botao.is_visible():
                continue

            texto = normalizar_upper(
                botao.inner_text(timeout=1_500)
                or botao.get_attribute("value")
                or botao.get_attribute("aria-label")
                or ""
            )

            proibidos = [
                "CANCELAR",
                "CANCEL",
                "SAIR",
                "REMOVER",
                "APAGAR",
                "EXCLUIR",
                "ANULAR",
                "DESMARCAR",
            ]

            if any(palavra in texto for palavra in proibidos):
                print(
                    f"🛑 Botão ignorado por segurança: "
                    f"{texto or '(sem texto)'}"
                )
                continue

            botao.scroll_into_view_if_needed(timeout=3_000)
            botao.click(timeout=3_000, force=True)
            print(
                f"✅ Confirmação positiva efetuada: "
                f"{texto or '(sem texto)'}"
            )
            page.wait_for_timeout(1_500)
            return

        except Exception:
            continue

    print("ℹ️ Nenhum modal de confirmação positiva encontrado.")

def confirmar_estado_visual(
    page: Page,
    aula: AulaVisual,
    timeout_segundos: int = 20,
) -> Optional[str]:
    limite = time.monotonic() + timeout_segundos

    while time.monotonic() < limite:
        cards = localizar_card_prioritario(page, aula)

        try:
            total = cards.count()
        except Exception:
            total = 0

        for indice in range(min(total, 100)):
            card = cards.nth(indice)

            try:
                texto = normalizar_upper(card.inner_text(timeout=2_000))
            except Exception:
                continue

            if HORA_ALVO not in texto:
                continue

            if any(
                marcador in texto
                for marcador in [
                    "SAIR DA LISTA DE ESPERA",
                    "CANCELAR LISTA DE ESPERA",
                    "CANCELAR A LISTA DE ESPERA",
                    "JÁ NA LISTA DE ESPERA",
                    "JA NA LISTA DE ESPERA",
                ]
            ):
                return "LISTA DE ESPERA"

            if any(
                marcador in texto
                for marcador in [
                    "JÁ INSCRITO",
                    "JA INSCRITO",
                    "JÁ INSCRITA",
                    "JA INSCRITA",
                    "RESERVA CONFIRMADA",
                    "INSCRIÇÃO CONFIRMADA",
                    "INSCRICAO CONFIRMADA",
                ]
            ):
                return "INSCRITO"

        page.wait_for_timeout(1_000)

    return None



def verificar_marcacoes_periodo(
    page: Page,
    data_inicio: date,
    data_fim: date,
) -> list[dict]:
    """
    Verifica, dia a dia, entre data_inicio e data_fim (inclusive),
    se existe alguma aula às HORA_ALVO já marcada ou em lista de espera.

    A função apenas reporta o que encontra. Não faz cancelamentos nem
    alterações às reservas existentes.
    """
    encontradas: list[dict] = []

    print(
        "🔎 A verificar marcações existentes entre "
        f"{data_inicio.strftime('%d/%m/%Y')} e "
        f"{data_fim.strftime('%d/%m/%Y')}..."
    )

    data_atual = data_inicio

    while data_atual <= data_fim:
        if data_atual.weekday() >= 5:
            print(
                f"📆 Verificação: {data_atual.strftime('%d/%m/%Y')} "
                "— fim de semana, ignorado."
            )
            data_atual += timedelta(days=1)
            continue

        print(f"📆 Verificação: {data_atual.strftime('%d/%m/%Y')}")

        try:
            selecionar_data(page, data_atual)
        except Exception as exc:
            print(
                f"⚠️ Não foi possível selecionar "
                f"{data_atual.strftime('%d/%m/%Y')}: {exc}"
            )
            data_atual += timedelta(days=1)
            continue

        page.wait_for_timeout(800)

        try:
            aulas = inventariar_aulas(page)
        except Exception as exc:
            print(
                f"⚠️ Não foi possível inventariar aulas em "
                f"{data_atual.strftime('%d/%m/%Y')}: {exc}"
            )
            data_atual += timedelta(days=1)
            continue

        aulas_hora = [
            aula
            for aula in aulas
            if aula.inicio == HORA_ALVO
        ]

        marcadas = [
            aula
            for aula in aulas_hora
            if aula.inscrito or aula.lista_espera
        ]

        if not aulas_hora:
            print(
                f"   ℹ️ Nenhuma aula às {HORA_ALVO} "
                f"em {data_atual.strftime('%d/%m/%Y')}."
            )
        elif not marcadas:
            print(
                f"   ➖ Nenhuma marcação detetada às {HORA_ALVO}."
            )
        else:
            for aula in marcadas:
                estado = (
                    "LISTA DE ESPERA"
                    if aula.lista_espera
                    else "INSCRITO"
                )

                print(
                    f"   ✅ {aula.nome} | "
                    f"{aula.inicio}-{aula.fim} | {estado}"
                )

                encontradas.append(
                    {
                        "data": data_atual.isoformat(),
                        "nome": aula.nome,
                        "inicio": aula.inicio,
                        "fim": aula.fim,
                        "estado": estado,
                    }
                )

        data_atual += timedelta(days=1)

    guardar_json(
        "marcacoes_periodo.json",
        {
            "inicio": data_inicio.isoformat(),
            "fim": data_fim.isoformat(),
            "hora": HORA_ALVO,
            "marcacoes": encontradas,
        },
    )

    if encontradas:
        print(
            f"✅ Foram encontradas {len(encontradas)} "
            "marcação(ões) no período."
        )
    else:
        print("ℹ️ Não foram encontradas marcações no período.")

    return encontradas

def aguardar_e_marcar(
    page: Page,
    data_alvo: date,
) -> tuple[AulaVisual, str, bool]:
    inicio_espera = time.monotonic()
    limite_normal = inicio_espera + MAX_ESPERA_ABERTURA_SEGUNDOS
    limite_final = limite_normal + TEMPO_EXTRA_APOS_TIMEOUT_SEGUNDOS

    tentativa = 0
    entrou_periodo_extra = False

    while time.monotonic() < limite_final:
        tentativa += 1

        aulas = inventariar_aulas(page)
        aulas_1825 = [
            aula
            for aula in aulas
            if aula.inicio == HORA_ALVO
        ]

        print(
            f"🕒 Consulta visual {tentativa}: "
            f"{len(aulas_1825)} aula(s) às {HORA_ALVO}."
        )

        for aula in aulas_1825:
            estado = (
                "INSCRITO"
                if aula.inscrito
                else "LISTA DE ESPERA"
                if aula.lista_espera
                else "ABERTA"
                if aula.botao_reservar
                else "LISTA DE ESPERA DISPONÍVEL"
                if aula.botao_lista_espera
                else "AGUARDA ABERTURA"
            )
            print(
                f"   • {aula.nome} | "
                f"{aula.inicio}-{aula.fim} | {estado}"
            )

        # Já existe uma inscrição?
        ja_inscritas = [
            aula
            for aula in aulas_1825
            if aula.inscrito or aula.lista_espera
        ]

        if ja_inscritas:
            escolhida = sorted(
                ja_inscritas,
                key=lambda aula: aula.indice_prioridade,
            )[0]

            estado = (
                "LISTA DE ESPERA"
                if escolhida.lista_espera
                else "INSCRITO"
            )

            print(
                f"🎉 Já existe marcação: "
                f"{escolhida.nome} — {estado}."
            )

            return escolhida, estado, False

        # Modalidades prioritárias disponíveis no horário alvo.
        candidatas = sorted(
            [
                aula
                for aula in aulas_1825
                if aula.indice_prioridade < 999
            ],
            key=lambda aula: aula.indice_prioridade,
        )

        abertas = [
            aula
            for aula in candidatas
            if aula.botao_reservar
        ]

        # Botão INSCREVER apareceu.
        if abertas:
            escolhida = abertas[0]

            print(
                f"🎯 RESERVA ABERTA! "
                f"A tentar {escolhida.nome} às {HORA_ALVO}..."
            )

            guardar_pagina(page, "02_antes_inscricao")

            if not clicar_reservar_no_card(page, escolhida):
                print(
                    "⚠️ O botão RESERVAR apareceu no inventário mas "
                    "não foi possível clicar. Nova tentativa..."
                )
                page.wait_for_timeout(500)
                continue

            confirmar_modal(page)

            estado = confirmar_estado_visual(
                page,
                escolhida,
                timeout_segundos=20,
            )

            guardar_pagina(page, "03_depois_inscricao")

            if estado:
                print(
                    f"🎉 CONFIRMADO: "
                    f"{estado} em {escolhida.nome}."
                )
                return escolhida, estado, True

            print(
                "⚠️ O clique foi efetuado mas o estado ainda "
                "não foi confirmado. Vou consultar novamente..."
            )
            page.wait_for_timeout(1_000)
            continue

        agora_monotonic = time.monotonic()

        # Quando termina a janela normal, continua durante um período extra.
        if agora_monotonic >= limite_normal and not entrou_periodo_extra:
            entrou_periodo_extra = True
            print(
                "⏱️ Foi atingido o limite normal de espera. "
                f"Vou continuar durante mais "
                f"{TEMPO_EXTRA_APOS_TIMEOUT_SEGUNDOS}s."
            )

        restante_total = int(max(0, limite_final - agora_monotonic))

        if entrou_periodo_extra:
            print(
                "⏳ Inscrição ainda fechada. "
                f"Período extra: restam cerca de {restante_total}s."
            )
        else:
            restante_normal = int(max(0, limite_normal - agora_monotonic))
            print(
                "⏳ Inscrição ainda fechada. "
                f"Restam cerca de {restante_normal}s "
                "até ao período extra."
            )

        # Reaplica a data para obrigar a Regibox a atualizar o painel AJAX.
        try:
            selecionar_data(page, data_alvo)
        except Exception as exc:
            print(f"⚠️ Não foi possível atualizar o dia: {exc}")

        page.wait_for_timeout(INTERVALO_CONSULTA_SEGUNDOS * 1_000)

    # O botão não apareceu nem durante a janela normal nem durante a extra.
    aulas_finais = inventariar_aulas(page)
    aulas_finais_1825 = [
        aula
        for aula in aulas_finais
        if aula.inicio == HORA_ALVO
    ]

    guardar_pagina(page, "erro_timeout_abertura")
    guardar_json(
        "timeout_abertura.json",
        {
            "data": data_alvo.isoformat(),
            "hora": HORA_ALVO,
            "tentativas": tentativa,
            "tempo_normal_segundos": MAX_ESPERA_ABERTURA_SEGUNDOS,
            "tempo_extra_segundos": TEMPO_EXTRA_APOS_TIMEOUT_SEGUNDOS,
            "aulas": [asdict(aula) for aula in aulas_finais_1825],
        },
    )

    raise RuntimeError(
        "As modalidades prioritárias foram encontradas, mas "
        "nenhum botão RESERVAR apareceu dentro do tempo limite, "
        f"incluindo os {TEMPO_EXTRA_APOS_TIMEOUT_SEGUNDOS}s extra."
    )


# ============================================================
# EXECUÇÃO
# ============================================================

def executar() -> int:
    preparar_diagnostico()

    agora = datetime.now(TIMEZONE)
    data_alvo_original = (agora + timedelta(days=DIAS_ANTECEDENCIA)).date()
    data_alvo = data_alvo_original

    # Se hoje +4 cair ao fim de semana, usa a sexta-feira imediatamente anterior.
    # Ex.: terça-feira 08/09 + 4 dias = sábado 12/09 -> alvo = sexta 11/09.
    while data_alvo.weekday() >= 5:
        data_alvo -= timedelta(days=1)

    print(
        f"[{agora.strftime('%H:%M:%S')}] "
        "🚀 A iniciar o robô Regibox 100% Playwright..."
    )
    print(f"📅 Data atual Madeira: {agora.strftime('%d/%m/%Y')}")
    print(
        f"📅 Data alvo calculada (+{DIAS_ANTECEDENCIA} dias): "
        f"{data_alvo_original.strftime('%d/%m/%Y')}"
    )
    if data_alvo != data_alvo_original:
        print(
            "📅 A data calculada cai ao fim de semana; "
            f"vou usar {data_alvo.strftime('%d/%m/%Y')}."
        )
    else:
        print(f"📅 Data alvo efetiva: {data_alvo.strftime('%d/%m/%Y')}")
    print(f"⏰ Horário alvo: {HORA_ALVO}")
    print("🏆 Prioridade: HYROX → STRENGHT → CROSSFIT")

    if not USERNAME or not PASSWORD:
        print("❌ REGYBOX_USER ou REGYBOX_PASS não estão configuradas.")
        return 2

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            locale="pt-PT",
            timezone_id="Atlantic/Madeira",
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_PADRAO_MS)

        page.on(
            "pageerror",
            lambda erro: print(f"💥 JAVASCRIPT DA REGIBOX: {erro}"),
        )

        try:
            autenticar(page)
            abrir_aulas(page)

            # Antes de tentar uma nova reserva, verifica todas as datas
            # entre hoje e +4 dias para identificar marcações já existentes.
            marcacoes_periodo = verificar_marcacoes_periodo(
                page,
                agora.date(),
                data_alvo,
            )

            marcacao_no_alvo = next(
                (
                    item
                    for item in marcacoes_periodo
                    if item["data"] == data_alvo.isoformat()
                ),
                None,
            )

            if marcacao_no_alvo:
                print(
                    "✅ Já existe uma marcação na data alvo: "
                    f"{marcacao_no_alvo['nome']} — "
                    f"{marcacao_no_alvo['estado']}."
                )

            # Volta explicitamente à data alvo antes de iniciar a lógica
            # de espera/reserva.
            selecionar_data(page, data_alvo)

            aula, estado, nova_marcacao = aguardar_e_marcar(page, data_alvo)

            if nova_marcacao:
                enviar_email_confirmacao(aula, data_alvo, estado)
            else:
                print("✅ Nenhuma nova ação necessária; email não enviado.")

            guardar_json(
                "resultado_final.json",
                {
                    "data": data_alvo.isoformat(),
                    "hora": HORA_ALVO,
                    "aula": asdict(aula),
                    "estado": estado,
                    "nova_marcacao": nova_marcacao,
                },
            )

            print(
                f"✅ PROCESSO CONCLUÍDO: {aula.nome}, "
                f"{data_alvo.strftime('%d/%m/%Y')} às {HORA_ALVO} — {estado}."
            )
            return 0

        except Exception as exc:
            erro = f"{type(exc).__name__}: {exc}"
            print(f"❌ ERRO: {erro}")
            guardar_texto("99_erro_final.txt", erro)
            guardar_pagina(page, "99_erro_final")
            return 1

        finally:
            try:
                context.tracing.stop(
                    path=str(PASTA_DIAGNOSTICO / "trace_regybox.zip")
                )
            except Exception:
                pass

            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(executar())
