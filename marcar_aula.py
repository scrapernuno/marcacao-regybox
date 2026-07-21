import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

REGYBOX_URL = "https://www.regibox.pt/app/app_nova/login.php"
NOME_BOX = "Naval Box"

USERNAME = os.environ.get("REGYBOX_USER", "").strip()
PASSWORD = os.environ.get("REGYBOX_PASS", "").strip()

TIMEZONE = ZoneInfo("Atlantic/Madeira")
DIAS_ANTECEDENCIA = 3

# A imagem confirma que esta é a grafia apresentada pela Regibox.
MODALIDADES_ACEITES = [
    "STRENGHT",
    "STRENGTH",
    "HYROX",
    "HIROX",
    "CROSSFIT",
    "OPEN",
]

HORA_ALVO = "18:25"
PASTA_DIAGNOSTICO = Path("diagnostico_regybox")


def guardar_diagnostico(page, nome):
    PASTA_DIAGNOSTICO.mkdir(parents=True, exist_ok=True)

    try:
        page.screenshot(
            path=str(PASTA_DIAGNOSTICO / f"{nome}.png"),
            full_page=True,
        )
    except Exception as exc:
        print(f"⚠️ Falha ao guardar screenshot {nome}: {exc}")

    try:
        (PASTA_DIAGNOSTICO / f"{nome}.html").write_text(
            page.content(),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"⚠️ Falha ao guardar HTML {nome}: {exc}")


def esperar(page, milissegundos=1500):
    page.wait_for_timeout(milissegundos)


def preencher_primeiro_visivel(locator, valor):
    total = locator.count()

    for indice in range(total):
        elemento = locator.nth(indice)

        try:
            if elemento.is_visible():
                elemento.fill(valor)
                return True
        except Exception:
            continue

    return False


def clicar_primeiro_visivel(locator, timeout=5000):
    total = locator.count()

    for indice in range(total):
        elemento = locator.nth(indice)

        try:
            elemento.wait_for(state="visible", timeout=timeout)
            elemento.scroll_into_view_if_needed()
            elemento.click(timeout=timeout)
            return True
        except Exception:
            continue

    return False


def selecionar_box(page):
    print(f"🔍 A selecionar a Box: {NOME_BOX}...")

    campos = page.locator(
        "input[placeholder*='Procura' i], "
        "input[placeholder*='box' i], "
        "input[type='text']"
    )

    for indice in range(campos.count()):
        campo = campos.nth(indice)

        try:
            if not campo.is_visible():
                continue

            campo.fill(NOME_BOX)
            esperar(page, 1000)

            opcao = page.get_by_text(NOME_BOX, exact=False)

            if clicar_primeiro_visivel(opcao, timeout=3000):
                print("✅ Box selecionada.")
                esperar(page, 1000)
                return

        except Exception:
            continue

    print("ℹ️ A Box pode já estar selecionada ou o campo não está visível.")


def efetuar_login(page):
    print("🔑 A preencher dados de acesso...")

    campo_user = page.locator(
        "input[type='email'], "
        "input[name*='user' i], "
        "input[name*='email' i], "
        "input[placeholder*='mail' i]"
    )

    campo_password = page.locator(
        "input[type='password'], "
        "input[name*='pass' i]"
    )

    if not preencher_primeiro_visivel(campo_user, USERNAME):
        raise RuntimeError("Campo de utilizador/e-mail não encontrado.")

    if not preencher_primeiro_visivel(campo_password, PASSWORD):
        raise RuntimeError("Campo de password não encontrado.")

    print("🚀 A efetuar Login...")

    botoes_login = page.locator(
        "button:has-text('LOGIN'), "
        "button:has-text('ENTRAR'), "
        "input[type='submit'], "
        "input[value*='LOGIN' i], "
        "input[value*='ENTRAR' i]"
    )

    if not clicar_primeiro_visivel(botoes_login, timeout=5000):
        page.keyboard.press("Enter")

    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PlaywrightTimeoutError:
        pass

    esperar(page, 3000)

    print(f"🌐 URL após login: {page.url}")

    if "login.php" in page.url.lower():
        raise RuntimeError("O login não foi concluído. A página continua no login.")

    guardar_diagnostico(page, "02_apos_login")


def abrir_aulas(page):
    print("📚 PASSO 1: A clicar em AULAS...")

    candidatos = [
        page.get_by_text("AULAS", exact=True),
        page.get_by_role("link", name=re.compile(r"^AULAS$", re.I)),
        page.get_by_role("button", name=re.compile(r"^AULAS$", re.I)),
        page.locator(
            "a:has-text('AULAS'), "
            "button:has-text('AULAS'), "
            "[onclick*='aula' i]"
        ),
    ]

    clicou = False

    for candidato in candidatos:
        try:
            if clicar_primeiro_visivel(candidato, timeout=3000):
                clicou = True
                break
        except Exception:
            continue

    if not clicou:
        raise RuntimeError("Não foi possível encontrar ou clicar em AULAS.")

    esperar(page, 3000)

    try:
        page.get_by_text(
            re.compile(r"AULAS DE .*20\d{2}", re.I)
        ).first.wait_for(
            state="visible",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        guardar_diagnostico(page, "erro_area_aulas")
        raise RuntimeError(
            "A área AULAS foi clicada, mas o calendário não apareceu."
        )

    print("✅ Calendário de aulas aberto.")
    guardar_diagnostico(page, "03_calendario_aberto")


def selecionar_dia_calendario(page, dia_alvo):
    print(f"📅 PASSO 2: A selecionar o dia {dia_alvo} no calendário...")

    resultado = page.evaluate(
        """
        dia => {
            const todos = Array.from(document.querySelectorAll("body *"));

            const visivel = elemento => {
                const estilo = window.getComputedStyle(elemento);
                const rect = elemento.getBoundingClientRect();

                return (
                    estilo.display !== "none" &&
                    estilo.visibility !== "hidden" &&
                    rect.width > 0 &&
                    rect.height > 0
                );
            };

            const candidatos = todos.filter(elemento => {
                const texto = (elemento.textContent || "").trim();
                const rect = elemento.getBoundingClientRect();

                return (
                    texto === String(dia) &&
                    visivel(elemento) &&
                    rect.left < window.innerWidth * 0.50 &&
                    rect.top > 150
                );
            });

            candidatos.sort((a, b) => {
                const areaA =
                    a.getBoundingClientRect().width *
                    a.getBoundingClientRect().height;

                const areaB =
                    b.getBoundingClientRect().width *
                    b.getBoundingClientRect().height;

                return areaA - areaB;
            });

            for (const candidato of candidatos) {
                const clicavel =
                    candidato.closest(
                        "button, a, td, [onclick], [role='button']"
                    ) || candidato;

                if (visivel(clicavel)) {
                    clicavel.scrollIntoView({
                        block: "center",
                        inline: "center"
                    });

                    clicavel.click();

                    return {
                        sucesso: true,
                        tag: clicavel.tagName,
                        classe: clicavel.className || "",
                        texto: (clicavel.textContent || "").trim()
                    };
                }
            }

            return {
                sucesso: false,
                candidatos: candidatos.length
            };
        }
        """,
        str(dia_alvo),
    )

    print(f"🔧 Resultado da seleção do dia: {resultado}")

    if not resultado.get("sucesso"):
        guardar_diagnostico(page, "erro_selecao_dia")
        raise RuntimeError(
            f"Não foi possível clicar no dia {dia_alvo} do calendário."
        )

    esperar(page, 3500)
    guardar_diagnostico(page, "04_dia_selecionado")

    print(f"✅ Dia {dia_alvo} selecionado.")


def encontrar_cartao_aula(page):
    print(f"🔎 PASSO 3: A procurar a aula das {HORA_ALVO}...")

    resultado = page.evaluate(
        """
        parametros => {
            const hora = parametros.hora;
            const modalidades = parametros.modalidades;

            const visivel = elemento => {
                const estilo = window.getComputedStyle(elemento);
                const rect = elemento.getBoundingClientRect();

                return (
                    estilo.display !== "none" &&
                    estilo.visibility !== "hidden" &&
                    rect.width > 0 &&
                    rect.height > 0
                );
            };

            const elementos = Array.from(
                document.querySelectorAll("body *")
            ).filter(elemento => {
                const texto = (elemento.textContent || "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toUpperCase();

                return (
                    visivel(elemento) &&
                    texto.includes(hora)
                );
            });

            for (const elementoHora of elementos) {
                let atual = elementoHora;

                for (let nivel = 0; nivel < 10 && atual; nivel++) {
                    const texto = (atual.textContent || "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toUpperCase();

                    const modalidade = modalidades.find(
                        nome => texto.includes(nome)
                    );

                    const botaoTexto = Array.from(
                        atual.querySelectorAll(
                            "button, a, input, [role='button']"
                        )
                    ).find(botao => {
                        const textoBotao = (
                            botao.innerText ||
                            botao.value ||
                            botao.getAttribute("aria-label") ||
                            ""
                        )
                            .replace(/\\s+/g, " ")
                            .trim()
                            .toUpperCase();

                        return (
                            visivel(botao) &&
                            textoBotao.includes("INSCREVER")
                        );
                    });

                    if (
                        modalidade &&
                        botaoTexto &&
                        texto.length < 1500
                    ) {
                        atual.setAttribute(
                            "data-rbx-cartao-alvo",
                            "true"
                        );

                        botaoTexto.setAttribute(
                            "data-rbx-inscrever-alvo",
                            "true"
                        );

                        atual.scrollIntoView({
                            behavior: "instant",
                            block: "center",
                            inline: "nearest"
                        });

                        return {
                            sucesso: true,
                            modalidade: modalidade,
                            texto: texto.substring(0, 500),
                            tagBotao: botaoTexto.tagName
                        };
                    }

                    atual = atual.parentElement;
                }
            }

            return {
                sucesso: false,
                elementosComHora: elementos.length
            };
        }
        """,
        {
            "hora": HORA_ALVO,
            "modalidades": MODALIDADES_ACEITES,
        },
    )

    print(f"🔧 Resultado da procura da aula: {resultado}")

    if not resultado.get("sucesso"):
        guardar_diagnostico(page, "erro_aula_nao_encontrada")

        texto_pagina = page.locator("body").inner_text()

        linhas_horarios = [
            linha.strip()
            for linha in texto_pagina.splitlines()
            if re.search(r"\d{1,2}:\d{2}", linha)
        ]

        print("🕒 Horários visíveis encontrados:")

        for linha in linhas_horarios[:50]:
            print(f"   {linha}")

        raise RuntimeError(
            f"Não foi encontrado um cartão com {HORA_ALVO} "
            "e botão INSCREVER."
        )

    esperar(page, 1000)

    print(
        f"✅ Aula encontrada: "
        f"{resultado.get('modalidade')} às {HORA_ALVO}."
    )

    guardar_diagnostico(page, "05_aula_encontrada")

    return resultado


def clicar_inscrever(page):
    print("🎯 PASSO 4: A clicar no botão INSCREVER...")

    botao = page.locator("[data-rbx-inscrever-alvo='true']").first

    try:
        botao.wait_for(state="visible", timeout=5000)
        botao.scroll_into_view_if_needed()
        esperar(page, 500)

        if not botao.is_enabled():
            raise RuntimeError(
                "O botão INSCREVER foi encontrado, mas está desativado."
            )

        botao.click(timeout=5000)

    except Exception as exc:
        guardar_diagnostico(page, "erro_clique_inscrever")
        raise RuntimeError(
            f"Falha ao clicar no botão INSCREVER: {exc}"
        ) from exc

    esperar(page, 3000)
    guardar_diagnostico(page, "06_apos_inscrever")

    print("✅ Clique no botão INSCREVER realizado.")


def verificar_resultado(page):
    texto = page.locator("body").inner_text().upper()

    indicadores_sucesso = [
        "CANCELAR",
        "DESMARCAR",
        "INSCRITO",
        "INSCRITA",
        "INSCRIÇÃO EFETUADA",
        "INSCRICAO EFETUADA",
        "EM LISTA DE ESPERA",
    ]

    for indicador in indicadores_sucesso:
        if indicador in texto:
            print(f"🎉 Inscrição confirmada: apareceu '{indicador}'.")
            return True

    # Algumas aplicações mostram uma janela de confirmação.
    botoes_confirmacao = page.locator(
        "button:has-text('CONFIRMAR'), "
        "button:has-text('SIM'), "
        "button:has-text('OK'), "
        "a:has-text('CONFIRMAR')"
    )

    if clicar_primeiro_visivel(botoes_confirmacao, timeout=2000):
        print("✅ Janela de confirmação aceite.")
        esperar(page, 2500)

        texto = page.locator("body").inner_text().upper()

        for indicador in indicadores_sucesso:
            if indicador in texto:
                print(
                    f"🎉 Inscrição confirmada: apareceu '{indicador}'."
                )
                return True

    print(
        "⚠️ O botão foi clicado, mas não apareceu uma confirmação "
        "textual inequívoca."
    )

    return True


def executar_marcacao():
    agora = datetime.now(TIMEZONE)
    data_alvo = agora + timedelta(days=DIAS_ANTECEDENCIA)
    dia_alvo = data_alvo.day

    print(
        f"[{agora.strftime('%H:%M:%S')}] "
        "🚀 A iniciar o robô de marcação..."
    )
    print(f"📅 Data atual Madeira: {agora.strftime('%d/%m/%Y')}")
    print(
        f"📅 Data alvo (+{DIAS_ANTECEDENCIA} dias): "
        f"{data_alvo.strftime('%d/%m/%Y')}"
    )
    print(f"⏰ Horário alvo: {HORA_ALVO}")

    if not USERNAME or not PASSWORD:
        print(
            "❌ REGYBOX_USER ou REGYBOX_PASS "
            "não estão configuradas nas GitHub Secrets."
        )
        return 2

    PASTA_DIAGNOSTICO.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="pt-PT",
            timezone_id="Atlantic/Madeira",
        )

        context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=True,
        )

        page = context.new_page()
        page.set_default_timeout(7000)

        page.on(
            "console",
            lambda mensagem: print(
                f"🌐 CONSOLE {mensagem.type}: {mensagem.text}"
            ),
        )

        page.on(
            "pageerror",
            lambda erro: print(f"💥 JAVASCRIPT: {erro}"),
        )

        try:
            print("🔐 A abrir a página de login...")

            page.goto(
                REGYBOX_URL,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            esperar(page, 2000)
            guardar_diagnostico(page, "01_login")

            selecionar_box(page)
            efetuar_login(page)
            abrir_aulas(page)
            selecionar_dia_calendario(page, dia_alvo)
            encontrar_cartao_aula(page)
            clicar_inscrever(page)
            verificar_resultado(page)

            print(
                f"🎉 PROCESSO CONCLUÍDO para "
                f"{data_alvo.strftime('%d/%m/%Y')} às {HORA_ALVO}."
            )

            return 0

        except Exception as exc:
            print(f"❌ ERRO: {type(exc).__name__}: {exc}")
            guardar_diagnostico(page, "99_erro_final")
            return 1

        finally:
            try:
                context.tracing.stop(
                    path=str(PASTA_DIAGNOSTICO / "trace.zip")
                )
            except Exception as exc:
                print(f"⚠️ Falha ao guardar trace: {exc}")

            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(executar_marcacao())
