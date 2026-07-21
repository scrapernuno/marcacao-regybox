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
HORA_ALVO = "18:25"

MODALIDADES_ACEITES = [
    "STRENGHT",
    "STRENGTH",
    "HYROX",
    "HIROX",
    "CROSSFIT",
    "OPEN",
]

MESES_PT = {
    1: "JANEIRO",
    2: "FEVEREIRO",
    3: "MARÇO",
    4: "ABRIL",
    5: "MAIO",
    6: "JUNHO",
    7: "JULHO",
    8: "AGOSTO",
    9: "SETEMBRO",
    10: "OUTUBRO",
    11: "NOVEMBRO",
    12: "DEZEMBRO",
}

PASTA_DIAGNOSTICO = Path("diagnostico_regybox")


def esperar(page, milissegundos=1500):
    page.wait_for_timeout(milissegundos)


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
        html = page.content()

        (PASTA_DIAGNOSTICO / f"{nome}.html").write_text(
            html,
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"⚠️ Falha ao guardar HTML {nome}: {exc}")

    try:
        frames = []

        for indice, frame in enumerate(page.frames):
            frames.append(
                f"FRAME {indice}\n"
                f"NOME={frame.name}\n"
                f"URL={frame.url}\n"
                f"{'-' * 80}\n"
            )

        (PASTA_DIAGNOSTICO / f"{nome}_frames.txt").write_text(
            "\n".join(frames),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"⚠️ Falha ao guardar frames {nome}: {exc}")


def preencher_primeiro_visivel(locator, valor):
    try:
        total = locator.count()
    except Exception:
        return False

    for indice in range(min(total, 30)):
        elemento = locator.nth(indice)

        try:
            if elemento.is_visible():
                elemento.fill(valor)
                return True
        except Exception:
            continue

    return False


def clicar_primeiro_visivel(locator, timeout=5000):
    try:
        total = locator.count()
    except Exception:
        return False

    for indice in range(min(total, 30)):
        elemento = locator.nth(indice)

        try:
            elemento.wait_for(
                state="visible",
                timeout=timeout,
            )

            elemento.scroll_into_view_if_needed()

            elemento.click(
                timeout=timeout,
            )

            return True

        except Exception:
            continue

    return False


def selecionar_box(page):
    print(f"🔍 A selecionar a Box: {NOME_BOX}...")

    campos = page.locator(
        "input[placeholder*='Procura' i], "
        "input[placeholder*='box' i], "
        "input[placeholder*='ginásio' i], "
        "input[type='text']"
    )

    try:
        total = campos.count()
    except Exception:
        total = 0

    for indice in range(min(total, 20)):
        campo = campos.nth(indice)

        try:
            if not campo.is_visible():
                continue

            campo.fill(NOME_BOX)
            esperar(page, 1000)

            opcoes = [
                page.get_by_text(NOME_BOX, exact=True),
                page.get_by_text(NOME_BOX, exact=False),
                page.locator(
                    f"text={NOME_BOX}"
                ),
            ]

            for opcao in opcoes:
                if clicar_primeiro_visivel(
                    opcao,
                    timeout=3000,
                ):
                    print("✅ Box selecionada.")
                    esperar(page, 1000)
                    return

        except Exception:
            continue

    print(
        "ℹ️ A Box pode já estar selecionada "
        "ou o campo não está disponível."
    )


def efetuar_login(page):
    print("🔑 A preencher dados de acesso...")

    campo_user = page.locator(
        "input[type='email'], "
        "input[name*='user' i], "
        "input[name*='email' i], "
        "input[placeholder*='mail' i], "
        "input[placeholder*='utilizador' i]"
    )

    campo_password = page.locator(
        "input[type='password'], "
        "input[name*='pass' i], "
        "input[placeholder*='password' i], "
        "input[placeholder*='senha' i]"
    )

    if not preencher_primeiro_visivel(
        campo_user,
        USERNAME,
    ):
        raise RuntimeError(
            "Campo de utilizador/e-mail não encontrado."
        )

    if not preencher_primeiro_visivel(
        campo_password,
        PASSWORD,
    ):
        raise RuntimeError(
            "Campo de password não encontrado."
        )

    print("🚀 A efetuar Login...")

    botoes_login = page.locator(
        "button:has-text('LOGIN'), "
        "button:has-text('ENTRAR'), "
        "input[type='submit'], "
        "input[value*='LOGIN' i], "
        "input[value*='ENTRAR' i]"
    )

    clicou = clicar_primeiro_visivel(
        botoes_login,
        timeout=5000,
    )

    if not clicou:
        page.keyboard.press("Enter")

    try:
        page.wait_for_load_state(
            "domcontentloaded",
            timeout=15000,
        )
    except PlaywrightTimeoutError:
        pass

    esperar(page, 3000)

    print(f"🌐 URL após login: {page.url}")

    if "login.php" in page.url.lower():
        guardar_diagnostico(
            page,
            "erro_login",
        )

        raise RuntimeError(
            "O login não foi concluído. "
            "A página continua no formulário de login."
        )

    guardar_diagnostico(
        page,
        "02_apos_login",
    )


def abrir_aulas(page):
    print("📚 PASSO 1: A clicar em AULAS...")

    candidatos = [
        page.get_by_text(
            "AULAS",
            exact=True,
        ),
        page.get_by_role(
            "link",
            name=re.compile(
                r"^AULAS$",
                re.IGNORECASE,
            ),
        ),
        page.get_by_role(
            "button",
            name=re.compile(
                r"^AULAS$",
                re.IGNORECASE,
            ),
        ),
        page.locator(
            "a:has-text('AULAS'), "
            "button:has-text('AULAS'), "
            "[onclick*='aula' i]"
        ),
    ]

    clicou = False

    for candidato in candidatos:
        try:
            if clicar_primeiro_visivel(
                candidato,
                timeout=3000,
            ):
                clicou = True
                break
        except Exception:
            continue

    if not clicou:
        guardar_diagnostico(
            page,
            "erro_botao_aulas",
        )

        raise RuntimeError(
            "Não foi possível encontrar "
            "ou clicar em AULAS."
        )

    esperar(page, 3000)

    try:
        cabecalho = page.get_by_text(
            re.compile(
                r"AULAS DE .*20\d{2}",
                re.IGNORECASE,
            )
        ).first

        cabecalho.wait_for(
            state="visible",
            timeout=10000,
        )

    except PlaywrightTimeoutError:
        guardar_diagnostico(
            page,
            "erro_area_aulas",
        )

        raise RuntimeError(
            "A área AULAS foi clicada, "
            "mas o calendário não apareceu."
        )

    print("✅ Calendário de aulas aberto.")

    guardar_diagnostico(
        page,
        "03_calendario_aberto",
    )


def selecionar_dia_calendario(page, data_alvo):
    dia_alvo = data_alvo.day
    mes_alvo = MESES_PT[data_alvo.month]
    ano_alvo = data_alvo.year

    print(
        f"📅 PASSO 2: A selecionar o dia "
        f"{dia_alvo} no calendário..."
    )

    resultado = page.evaluate(
        """
        dia => {
            function normalizar(texto) {
                return (texto || "")
                    .replace(/\\u00a0/g, " ")
                    .replace(/\\s+/g, " ")
                    .trim();
            }

            function visivel(elemento) {
                if (!elemento) {
                    return false;
                }

                const estilo = window.getComputedStyle(elemento);
                const rect = elemento.getBoundingClientRect();

                return (
                    estilo.display !== "none" &&
                    estilo.visibility !== "hidden" &&
                    estilo.opacity !== "0" &&
                    rect.width > 0 &&
                    rect.height > 0
                );
            }

            const todos = Array.from(
                document.querySelectorAll("body *")
            );

            const candidatos = todos.filter(elemento => {
                const texto = normalizar(
                    elemento.textContent
                );

                const rect = elemento.getBoundingClientRect();

                return (
                    texto === String(dia) &&
                    visivel(elemento) &&
                    rect.left < window.innerWidth * 0.50 &&
                    rect.top > 140
                );
            });

            candidatos.sort((a, b) => {
                const rectA = a.getBoundingClientRect();
                const rectB = b.getBoundingClientRect();

                const areaA = rectA.width * rectA.height;
                const areaB = rectB.width * rectB.height;

                return areaA - areaB;
            });

            for (const candidato of candidatos) {
                const clicavel =
                    candidato.closest(
                        "button, a, td, [onclick], [role='button']"
                    ) || candidato;

                if (!visivel(clicavel)) {
                    continue;
                }

                clicavel.scrollIntoView({
                    behavior: "instant",
                    block: "center",
                    inline: "center"
                });

                clicavel.click();

                return {
                    sucesso: true,
                    tag: clicavel.tagName,
                    classe: clicavel.className || "",
                    texto: normalizar(
                        clicavel.textContent
                    )
                };
            }

            return {
                sucesso: false,
                candidatos: candidatos.length
            };
        }
        """,
        str(dia_alvo),
    )

    print(
        f"🔧 Resultado da seleção do dia: "
        f"{resultado}"
    )

    if not resultado.get("sucesso"):
        guardar_diagnostico(
            page,
            "erro_selecao_dia",
        )

        raise RuntimeError(
            f"Não foi possível clicar "
            f"no dia {dia_alvo} do calendário."
        )

    esperar(page, 3500)

    guardar_diagnostico(
        page,
        "04_dia_selecionado",
    )

    try:
        padrao_cabecalho = re.compile(
            rf"{dia_alvo}\s+DE\s+"
            rf"{re.escape(mes_alvo)}\s+DE\s+"
            rf"{ano_alvo}",
            re.IGNORECASE,
        )

        cabecalho = page.get_by_text(
            padrao_cabecalho
        ).first

        cabecalho.wait_for(
            state="visible",
            timeout=7000,
        )

        print(
            f"✅ O painel confirma "
            f"{dia_alvo} de {mes_alvo.lower()} "
            f"de {ano_alvo}."
        )

    except Exception:
        print(
            "⚠️ O cabeçalho textual da data "
            "não foi confirmado, mas o clique "
            "no calendário foi realizado."
        )

    print(
        f"✅ Dia {dia_alvo} selecionado."
    )


def encontrar_cartao_aula(page):
    print(
        f"🔎 PASSO 3: A procurar "
        f"a aula das {HORA_ALVO}..."
    )

    page.evaluate(
        """
        () => {
            document
                .querySelectorAll(
                    "[data-rbx-cartao-alvo]"
                )
                .forEach(elemento => {
                    elemento.removeAttribute(
                        "data-rbx-cartao-alvo"
                    );
                });

            document
                .querySelectorAll(
                    "[data-rbx-inscrever-alvo]"
                )
                .forEach(elemento => {
                    elemento.removeAttribute(
                        "data-rbx-inscrever-alvo"
                    );
                });
        }
        """
    )

    resultado = page.evaluate(
        """
        parametros => {
            const hora = parametros.hora.toUpperCase();

            const modalidades =
                parametros.modalidades.map(
                    valor => valor.toUpperCase()
                );

            function normalizar(texto) {
                return (texto || "")
                    .replace(/\\u00a0/g, " ")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toUpperCase();
            }

            function visivel(elemento) {
                if (!elemento) {
                    return false;
                }

                const estilo =
                    window.getComputedStyle(elemento);

                const rect =
                    elemento.getBoundingClientRect();

                return (
                    estilo.display !== "none" &&
                    estilo.visibility !== "hidden" &&
                    estilo.opacity !== "0" &&
                    rect.width > 0 &&
                    rect.height > 0
                );
            }

            const todos = Array.from(
                document.querySelectorAll("body *")
            );

            const elementosInscrever =
                todos.filter(elemento => {
                    const texto =
                        normalizar(
                            elemento.textContent
                        );

                    return (
                        visivel(elemento) &&
                        texto === "INSCREVER"
                    );
                });

            const diagnostico = [];

            for (
                const textoInscrever
                of elementosInscrever
            ) {
                const clicavel =
                    textoInscrever.closest(
                        "button, a, input, "
                        + "[role='button'], "
                        + "[onclick]"
                    ) || textoInscrever;

                let atual = clicavel;

                for (
                    let nivel = 0;
                    nivel <= 12 && atual;
                    nivel++
                ) {
                    const textoCartao =
                        normalizar(
                            atual.textContent
                        );

                    if (
                        !textoCartao ||
                        textoCartao.length > 2000
                    ) {
                        atual =
                            atual.parentElement;

                        continue;
                    }

                    const temHora =
                        textoCartao.includes(hora);

                    const modalidade =
                        modalidades.find(
                            nome =>
                                textoCartao.includes(nome)
                        );

                    diagnostico.push({
                        nivel: nivel,
                        texto:
                            textoCartao.substring(
                                0,
                                350
                            ),
                        temHora: temHora,
                        modalidade:
                            modalidade || null,
                        tagClicavel:
                            clicavel.tagName,
                        classeClicavel:
                            clicavel.className || "",
                        onclick:
                            clicavel.getAttribute(
                                "onclick"
                            ) || null
                    });

                    if (
                        temHora &&
                        modalidade
                    ) {
                        atual.setAttribute(
                            "data-rbx-cartao-alvo",
                            "true"
                        );

                        clicavel.setAttribute(
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
                            texto:
                                textoCartao.substring(
                                    0,
                                    600
                                ),
                            tagBotao:
                                clicavel.tagName,
                            classeBotao:
                                clicavel.className || "",
                            onclick:
                                clicavel.getAttribute(
                                    "onclick"
                                ) || null,
                            totalInscrever:
                                elementosInscrever.length
                        };
                    }

                    atual =
                        atual.parentElement;
                }
            }

            return {
                sucesso: false,
                totalInscrever:
                    elementosInscrever.length,
                diagnostico:
                    diagnostico.slice(0, 40)
            };
        }
        """,
        {
            "hora": HORA_ALVO,
            "modalidades": MODALIDADES_ACEITES,
        },
    )

    print(
        f"🔧 Resultado da procura da aula: "
        f"{resultado}"
    )

    if not resultado.get("sucesso"):
        guardar_diagnostico(
            page,
            "erro_aula_nao_encontrada",
        )

        print(
            "🔢 Elementos visíveis com texto "
            f"INSCREVER: "
            f"{resultado.get('totalInscrever', 0)}"
        )

        for item in resultado.get(
            "diagnostico",
            [],
        )[:20]:
            print(
                "   "
                f"Nível={item.get('nivel')} | "
                f"Hora={item.get('temHora')} | "
                f"Modalidade="
                f"{item.get('modalidade')} | "
                f"Tag={item.get('tagClicavel')} | "
                f"Classe="
                f"{item.get('classeClicavel')} | "
                f"Texto={item.get('texto')}"
            )

        try:
            texto_pagina = page.locator(
                "body"
            ).inner_text()

            linhas_horarios = [
                " ".join(linha.split())
                for linha
                in texto_pagina.splitlines()
                if re.search(
                    rf"\b{re.escape(HORA_ALVO)}\b",
                    linha,
                )
            ]

            print(
                f"🕒 Linhas com "
                f"{HORA_ALVO}:"
            )

            for linha in linhas_horarios[:30]:
                print(f"   {linha}")

        except Exception as exc:
            print(
                f"⚠️ Não foi possível listar "
                f"os horários: {exc}"
            )

        raise RuntimeError(
            f"Foi encontrada a hora "
            f"{HORA_ALVO}, mas não foi "
            "possível associá-la a um "
            "elemento INSCREVER e a uma "
            "modalidade aceite."
        )

    esperar(page, 800)

    print(
        f"✅ Aula encontrada: "
        f"{resultado.get('modalidade')} "
        f"às {HORA_ALVO}."
    )

    print(
        f"🖱️ Elemento de inscrição: "
        f"{resultado.get('tagBotao')}"
    )

    if resultado.get("classeBotao"):
        print(
            f"🎨 Classe do botão: "
            f"{resultado.get('classeBotao')}"
        )

    if resultado.get("onclick"):
        print(
            f"🔧 onclick identificado: "
            f"{resultado.get('onclick')}"
        )

    guardar_diagnostico(
        page,
        "05_aula_encontrada",
    )

    return resultado


def clicar_inscrever(page):
    print(
        "🎯 PASSO 4: A clicar "
        "no botão INSCREVER..."
    )

    botao = page.locator(
        "[data-rbx-inscrever-alvo='true']"
    ).first

    try:
        botao.wait_for(
            state="visible",
            timeout=7000,
        )

        botao.scroll_into_view_if_needed()

        esperar(page, 700)

        try:
            texto_botao = " ".join(
                botao.inner_text().split()
            )
        except Exception:
            texto_botao = "INSCREVER"

        try:
            tag_botao = botao.evaluate(
                """
                elemento =>
                    elemento.tagName.toLowerCase()
                """
            )
        except Exception:
            tag_botao = "desconhecido"

        print(
            f"🖱️ Controlo encontrado: "
            f"<{tag_botao}> "
            f"com texto '{texto_botao}'"
        )

        try:
            botao.click(
                timeout=5000,
                force=True,
            )

            print(
                "✅ Clique Playwright executado."
            )

        except Exception as erro_playwright:
            print(
                "⚠️ Clique Playwright falhou; "
                "a tentar clique JavaScript..."
            )

            print(
                f"   Detalhe: "
                f"{erro_playwright}"
            )

            botao.evaluate(
                """
                elemento => {
                    elemento.scrollIntoView({
                        behavior: "instant",
                        block: "center",
                        inline: "nearest"
                    });

                    elemento.dispatchEvent(
                        new MouseEvent(
                            "mousedown",
                            {
                                bubbles: true,
                                cancelable: true,
                                view: window
                            }
                        )
                    );

                    elemento.dispatchEvent(
                        new MouseEvent(
                            "mouseup",
                            {
                                bubbles: true,
                                cancelable: true,
                                view: window
                            }
                        )
                    );

                    elemento.click();
                }
                """
            )

            print(
                "✅ Clique JavaScript executado."
            )

    except Exception as exc:
        guardar_diagnostico(
            page,
            "erro_clique_inscrever",
        )

        raise RuntimeError(
            f"Falha ao clicar "
            f"em INSCREVER: {exc}"
        ) from exc

    esperar(page, 3000)

    guardar_diagnostico(
        page,
        "06_apos_inscrever",
    )

    print(
        "✅ Ação INSCREVER executada."
    )


def confirmar_modal_se_necessario(page):
    print(
        "🔍 A verificar se existe "
        "janela de confirmação..."
    )

    candidatos = [
        page.get_by_role(
            "button",
            name=re.compile(
                r"CONFIRMAR|SIM|OK|ACEITAR",
                re.IGNORECASE,
            ),
        ),
        page.locator(
            "button:has-text('CONFIRMAR'), "
            "button:has-text('SIM'), "
            "button:has-text('OK'), "
            "button:has-text('ACEITAR'), "
            "a:has-text('CONFIRMAR'), "
            "[onclick]:has-text('CONFIRMAR')"
        ),
    ]

    for candidato in candidatos:
        try:
            if clicar_primeiro_visivel(
                candidato,
                timeout=2000,
            ):
                print(
                    "✅ Confirmação adicional aceite."
                )

                esperar(page, 2500)

                guardar_diagnostico(
                    page,
                    "07_apos_confirmacao",
                )

                return True

        except Exception:
            continue

    print(
        "ℹ️ Não apareceu uma janela "
        "de confirmação adicional."
    )

    return False


def verificar_resultado(page):
    print(
        "🔎 PASSO 5: A verificar "
        "o resultado da inscrição..."
    )

    esperar(page, 1500)

    try:
        texto = page.locator(
            "body"
        ).inner_text().upper()
    except Exception:
        texto = ""

    indicadores_sucesso = [
        "CANCELAR",
        "DESMARCAR",
        "INSCRITO",
        "INSCRITA",
        "INSCRIÇÃO EFETUADA",
        "INSCRICAO EFETUADA",
        "EM LISTA DE ESPERA",
        "LISTA DE ESPERA",
    ]

    for indicador in indicadores_sucesso:
        if indicador in texto:
            print(
                f"🎉 Inscrição confirmada: "
                f"apareceu '{indicador}'."
            )

            guardar_diagnostico(
                page,
                "08_sucesso_confirmado",
            )

            return True

    confirmou = confirmar_modal_se_necessario(
        page
    )

    if confirmou:
        try:
            texto = page.locator(
                "body"
            ).inner_text().upper()
        except Exception:
            texto = ""

        for indicador in indicadores_sucesso:
            if indicador in texto:
                print(
                    "🎉 Inscrição confirmada "
                    f"após confirmação: "
                    f"apareceu '{indicador}'."
                )

                guardar_diagnostico(
                    page,
                    "08_sucesso_confirmado",
                )

                return True

    print(
        "⚠️ O botão INSCREVER foi clicado, "
        "mas não apareceu uma confirmação "
        "textual inequívoca."
    )

    guardar_diagnostico(
        page,
        "08_resultado_inconclusivo",
    )

    return True


def executar_marcacao():
    agora = datetime.now(
        TIMEZONE
    )

    data_alvo = agora + timedelta(
        days=DIAS_ANTECEDENCIA
    )

    print(
        f"[{agora.strftime('%H:%M:%S')}] "
        "🚀 A iniciar o robô de marcação..."
    )

    print(
        f"📅 Data atual Madeira: "
        f"{agora.strftime('%d/%m/%Y')}"
    )

    print(
        f"📅 Data alvo "
        f"(+{DIAS_ANTECEDENCIA} dias): "
        f"{data_alvo.strftime('%d/%m/%Y')}"
    )

    print(
        f"⏰ Horário alvo: "
        f"{HORA_ALVO}"
    )

    if not USERNAME or not PASSWORD:
        print(
            "❌ REGYBOX_USER ou REGYBOX_PASS "
            "não estão configuradas nas "
            "GitHub Secrets."
        )

        return 2

    PASTA_DIAGNOSTICO.mkdir(
        parents=True,
        exist_ok=True,
    )

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

        page.set_default_timeout(
            7000
        )

        page.on(
            "console",
            lambda mensagem: print(
                f"🌐 CONSOLE "
                f"{mensagem.type}: "
                f"{mensagem.text}"
            ),
        )

        page.on(
            "pageerror",
            lambda erro: print(
                f"💥 JAVASCRIPT: {erro}"
            ),
        )

        page.on(
            "requestfailed",
            lambda pedido: print(
                f"🌐 PEDIDO FALHOU: "
                f"{pedido.method} "
                f"{pedido.url} — "
                f"{pedido.failure}"
            ),
        )

        try:
            print(
                "🔐 A abrir a página "
                "de login..."
            )

            page.goto(
                REGYBOX_URL,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            esperar(
                page,
                2000,
            )

            guardar_diagnostico(
                page,
                "01_login",
            )

            selecionar_box(
                page
            )

            efetuar_login(
                page
            )

            abrir_aulas(
                page
            )

            selecionar_dia_calendario(
                page,
                data_alvo,
            )

            encontrar_cartao_aula(
                page
            )

            clicar_inscrever(
                page
            )

            verificar_resultado(
                page
            )

            print(
                "🎉 PROCESSO CONCLUÍDO "
                f"para "
                f"{data_alvo.strftime('%d/%m/%Y')} "
                f"às {HORA_ALVO}."
            )

            return 0

        except Exception as exc:
            print(
                f"❌ ERRO: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            guardar_diagnostico(
                page,
                "99_erro_final",
            )

            return 1

        finally:
            try:
                context.tracing.stop(
                    path=str(
                        PASTA_DIAGNOSTICO
                        / "trace.zip"
                    )
                )
            except Exception as exc:
                print(
                    "⚠️ Falha ao guardar "
                    f"o trace: {exc}"
                )

            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(
        executar_marcacao()
    )
