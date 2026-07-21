import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


REGYBOX_URL = "https://www.regibox.pt/app/app_nova/login.php"
NOME_BOX = "Naval Box"

USERNAME = os.environ.get("REGYBOX_USER", "").strip()
PASSWORD = os.environ.get("REGYBOX_PASS", "").strip()

TIMEZONE = ZoneInfo("Atlantic/Madeira")

# A Regibox abre as inscrições com quatro dias de antecedência.
DIAS_ANTECEDENCIA = 4
HORA_ALVO = "18:25"

# Ordem obrigatória de preferência.
MODALIDADES_PRIORIDADE = [
    "HYROX",
    "HIROX",
    "CROSSFIT",
    "STRENGHT",
    "STRENGTH",
]

PASTA_DIAGNOSTICO = Path("diagnostico_regybox")


def esperar(page, milissegundos=1500):
    page.wait_for_timeout(milissegundos)


def normalizar(texto):
    return " ".join(
        (texto or "")
        .replace("\xa0", " ")
        .split()
    ).upper()


def guardar_diagnostico(page, nome):
    PASTA_DIAGNOSTICO.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        page.screenshot(
            path=str(
                PASTA_DIAGNOSTICO / f"{nome}.png"
            ),
            full_page=True,
        )
    except Exception as exc:
        print(
            f"⚠️ Não foi possível guardar "
            f"o screenshot {nome}: {exc}"
        )

    try:
        (
            PASTA_DIAGNOSTICO / f"{nome}.html"
        ).write_text(
            page.content(),
            encoding="utf-8",
        )
    except Exception as exc:
        print(
            f"⚠️ Não foi possível guardar "
            f"o HTML {nome}: {exc}"
        )

    try:
        texto = page.locator("body").inner_text()

        (
            PASTA_DIAGNOSTICO / f"{nome}.txt"
        ).write_text(
            texto,
            encoding="utf-8",
        )
    except Exception as exc:
        print(
            f"⚠️ Não foi possível guardar "
            f"o texto {nome}: {exc}"
        )


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


def selecionar_box(page):
    print(
        f"🔍 A selecionar a Box: "
        f"{NOME_BOX}..."
    )

    campos = page.locator(
        "input[placeholder*='Procura' i], "
        "input[placeholder*='box' i], "
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

            opcao = page.get_by_text(
                NOME_BOX,
                exact=False,
            )

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
        "ℹ️ A Box pode já estar selecionada."
    )


def efetuar_login(page):
    print("🔑 A preencher dados de acesso...")

    utilizador = page.locator(
        "input[type='email'], "
        "input[name*='user' i], "
        "input[name*='email' i], "
        "input[placeholder*='mail' i]"
    )

    password = page.locator(
        "input[type='password'], "
        "input[name*='pass' i]"
    )

    if not preencher_primeiro_visivel(
        utilizador,
        USERNAME,
    ):
        raise RuntimeError(
            "Campo de utilizador não encontrado."
        )

    if not preencher_primeiro_visivel(
        password,
        PASSWORD,
    ):
        raise RuntimeError(
            "Campo de password não encontrado."
        )

    print("🚀 A efetuar Login...")

    botao_login = page.locator(
        "button:has-text('LOGIN'), "
        "button:has-text('ENTRAR'), "
        "input[type='submit'], "
        "input[value*='LOGIN' i]"
    )

    if not clicar_primeiro_visivel(
        botao_login,
        timeout=5000,
    ):
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
        raise RuntimeError(
            "O login não foi concluído."
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
            "button:has-text('AULAS')"
        ),
    ]

    for candidato in candidatos:
        if clicar_primeiro_visivel(
            candidato,
            timeout=3000,
        ):
            esperar(page, 3500)

            print(
                "✅ Calendário de aulas aberto."
            )

            guardar_diagnostico(
                page,
                "03_calendario_aberto",
            )

            return

    raise RuntimeError(
        "Não foi possível clicar em AULAS."
    )


def selecionar_dia(page, data_alvo):
    data_iso = data_alvo.strftime("%Y-%m-%d")
    dia = data_alvo.day

    print(
        f"📅 PASSO 2: A selecionar "
        f"{data_iso} no calendário..."
    )

    seletor = (
        f"[onclick=\"wods_dia('{data_iso}')\"], "
        f"[onclick*=\"wods_dia('{data_iso}')\"]"
    )

    elemento = page.locator(seletor).first

    try:
        elemento.wait_for(
            state="visible",
            timeout=10000,
        )

        print(
            f"🔧 Elemento encontrado: "
            f"{elemento.get_attribute('onclick')}"
        )

        elemento.scroll_into_view_if_needed()

        elemento.click(
            timeout=7000,
            force=True,
        )

        print(
            f"✅ Dia {dia} selecionado."
        )

    except Exception as exc:
        guardar_diagnostico(
            page,
            "erro_selecao_dia",
        )

        raise RuntimeError(
            f"Não foi possível selecionar "
            f"o dia {dia}: {exc}"
        ) from exc

    esperar_lista_aulas(
        page,
        data_alvo,
    )

    guardar_diagnostico(
        page,
        "04_dia_carregado",
    )


def esperar_lista_aulas(page, data_alvo):
    data_iso = data_alvo.strftime("%Y-%m-%d")

    print(
        f"⏳ A aguardar as aulas "
        f"de {data_iso}..."
    )

    for tentativa in range(1, 21):
        esperar(page, 1000)

        resultado = page.evaluate(
            """
            hora => {
                const painel =
                    document.querySelector(
                        "#calendar-events"
                    );

                if (!painel) {
                    return {
                        painel: false,
                        hora: false,
                        cartoes: 0
                    };
                }

                const texto = (
                    painel.innerText || ""
                )
                .replace(/\\s+/g, " ")
                .toUpperCase();

                const cartoes =
                    painel.querySelectorAll(
                        ".card2, "
                        + ".round_rect_all_5, "
                        + "[class*='card']"
                    ).length;

                return {
                    painel: true,
                    hora:
                        texto.includes(hora),
                    cartoes: cartoes,
                    texto:
                        texto.substring(0, 500)
                };
            }
            """,
            HORA_ALVO,
        )

        print(
            f"🔄 Verificação {tentativa}/20: "
            f"painel={resultado.get('painel')} | "
            f"hora={resultado.get('hora')} | "
            f"cartões={resultado.get('cartoes')}"
        )

        if (
            resultado.get("painel")
            and resultado.get("hora")
        ):
            print(
                f"✅ A lista contém uma aula "
                f"às {HORA_ALVO}."
            )

            return

        if tentativa in (5, 10, 15):
            print(
                "⚠️ A repetir o clique no dia..."
            )

            try:
                data_iso = data_alvo.strftime(
                    "%Y-%m-%d"
                )

                page.locator(
                    f"[onclick*=\"wods_dia('{data_iso}')\"]"
                ).first.click(
                    force=True,
                    timeout=4000,
                )

            except Exception as exc:
                print(
                    f"⚠️ Falha ao repetir clique: "
                    f"{exc}"
                )

    guardar_diagnostico(
        page,
        "timeout_lista_aulas",
    )

    raise RuntimeError(
        f"Não apareceu uma aula às "
        f"{HORA_ALVO} no painel."
    )


def localizar_aula_prioritaria(page):
    print(
        f"🔎 PASSO 3: A procurar aula "
        f"às {HORA_ALVO}..."
    )

    resultado = page.evaluate(
        """
        parametros => {
            const painel =
                document.querySelector(
                    "#calendar-events"
                );

            if (!painel) {
                return {
                    sucesso: false,
                    erro:
                        "#calendar-events não encontrado"
                };
            }

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
                    estilo.display !== "none"
                    && estilo.visibility !== "hidden"
                    && rect.width > 0
                    && rect.height > 0
                );
            }

            const elementosHora =
                Array.from(
                    painel.querySelectorAll("*")
                ).filter(elemento => {
                    const texto =
                        normalizar(
                            elemento.textContent
                        );

                    return (
                        visivel(elemento)
                        && texto.includes(
                            parametros.hora
                        )
                    );
                });

            const candidatos = [];

            for (
                const elementoHora
                of elementosHora
            ) {
                let atual = elementoHora;

                for (
                    let nivel = 0;
                    nivel <= 10 && atual;
                    nivel++
                ) {
                    const texto =
                        normalizar(
                            atual.textContent
                        );

                    if (
                        texto.length > 0
                        && texto.length < 1500
                    ) {
                        const modalidade =
                            parametros.prioridades.find(
                                nome =>
                                    texto.includes(nome)
                            );

                        const botao =
                            Array.from(
                                atual.querySelectorAll(
                                    "button, "
                                    + "a, "
                                    + "[role='button'], "
                                    + "[onclick]"
                                )
                            ).find(elemento => {
                                const textoBotao =
                                    normalizar(
                                        elemento.innerText
                                        || elemento.value
                                        || elemento.textContent
                                    );

                                return (
                                    visivel(elemento)
                                    && textoBotao
                                        === "INSCREVER"
                                );
                            });

                        if (
                            modalidade
                            && botao
                            && texto.includes(
                                parametros.hora
                            )
                        ) {
                            candidatos.push({
                                elemento: atual,
                                botao: botao,
                                modalidade:
                                    modalidade,
                                texto: texto
                            });

                            break;
                        }
                    }

                    atual = atual.parentElement;

                    if (
                        atual
                        && atual === painel.parentElement
                    ) {
                        break;
                    }
                }
            }

            if (candidatos.length === 0) {
                return {
                    sucesso: false,
                    erro:
                        "Nenhum cartão compatível",
                    elementosHora:
                        elementosHora.length
                };
            }

            candidatos.sort((a, b) => {
                return (
                    parametros.prioridades.indexOf(
                        a.modalidade
                    )
                    -
                    parametros.prioridades.indexOf(
                        b.modalidade
                    )
                );
            });

            const escolhido =
                candidatos[0];

            escolhido.elemento.setAttribute(
                "data-rbx-cartao-alvo",
                "true"
            );

            escolhido.botao.setAttribute(
                "data-rbx-inscrever-alvo",
                "true"
            );

            escolhido.elemento.scrollIntoView({
                behavior: "instant",
                block: "center",
                inline: "nearest"
            });

            return {
                sucesso: true,
                modalidade:
                    escolhido.modalidade,
                texto:
                    escolhido.texto.substring(
                        0,
                        600
                    ),
                tagBotao:
                    escolhido.botao.tagName,
                classeBotao:
                    escolhido.botao.className || "",
                onclick:
                    escolhido.botao.getAttribute(
                        "onclick"
                    ) || null,
                candidatos:
                    candidatos.map(item => ({
                        modalidade:
                            item.modalidade,
                        texto:
                            item.texto.substring(
                                0,
                                200
                            )
                    }))
            };
        }
        """,
        {
            "hora": HORA_ALVO,
            "prioridades":
                MODALIDADES_PRIORIDADE,
        },
    )

    print(
        f"🔧 Resultado da procura: "
        f"{resultado}"
    )

    if not resultado.get("sucesso"):
        guardar_diagnostico(
            page,
            "erro_aula_nao_encontrada",
        )

        raise RuntimeError(
            f"Não foi encontrada uma aula "
            f"prioritária às {HORA_ALVO}."
        )

    modalidade = resultado.get(
        "modalidade"
    )

    print(
        f"✅ Aula selecionada: "
        f"{modalidade} às {HORA_ALVO}."
    )

    print(
        f"📋 Cartão: "
        f"{resultado.get('texto')}"
    )

    guardar_diagnostico(
        page,
        "05_aula_encontrada",
    )

    return modalidade


def clicar_inscrever(page, modalidade):
    print(
        f"🎯 PASSO 4: A inscrever em "
        f"{modalidade}..."
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
        esperar(page, 500)

        texto_botao = normalizar(
            botao.inner_text()
        )

        print(
            f"🖱️ Botão encontrado: "
            f"{texto_botao}"
        )

        botao.click(
            timeout=7000,
            force=True,
        )

        print(
            "✅ Clique em INSCREVER executado."
        )

    except Exception as exc:
        guardar_diagnostico(
            page,
            "erro_clique_inscrever",
        )

        raise RuntimeError(
            f"Não foi possível clicar "
            f"em INSCREVER: {exc}"
        ) from exc

    esperar(page, 4000)

    confirmar_modal(page)

    guardar_diagnostico(
        page,
        "06_apos_inscricao",
    )


def confirmar_modal(page):
    candidatos = page.locator(
        "button:has-text('CONFIRMAR'), "
        "button:has-text('SIM'), "
        "button:has-text('OK'), "
        "button:has-text('ACEITAR'), "
        "a:has-text('CONFIRMAR')"
    )

    try:
        total = candidatos.count()
    except Exception:
        total = 0

    for indice in range(min(total, 20)):
        candidato = candidatos.nth(indice)

        try:
            if not candidato.is_visible():
                continue

            texto = normalizar(
                candidato.inner_text()
            )

            candidato.click(
                timeout=3000,
                force=True,
            )

            print(
                f"✅ Confirmação aceite: "
                f"{texto}"
            )

            esperar(page, 3000)
            return True

        except Exception:
            continue

    return False


def verificar_resultado(page, modalidade):
    print(
        "🔎 PASSO 5: A verificar "
        "o resultado..."
    )

    try:
        painel = page.locator(
            "#calendar-events"
        )

        texto = normalizar(
            painel.inner_text()
        )
    except Exception:
        texto = normalizar(
            page.locator("body").inner_text()
        )

    indicadores = [
        "CANCELAR",
        "DESMARCAR",
        "INSCRITO",
        "INSCRITA",
        "EM LISTA DE ESPERA",
        "LISTA DE ESPERA",
        "INSCRIÇÃO EFETUADA",
        "INSCRICAO EFETUADA",
    ]

    encontrados = [
        indicador
        for indicador in indicadores
        if indicador in texto
    ]

    if encontrados:
        print(
            "🎉 Inscrição confirmada: "
            f"{', '.join(encontrados)}"
        )

        guardar_diagnostico(
            page,
            "07_sucesso_confirmado",
        )

        return

    botao = page.locator(
        "[data-rbx-inscrever-alvo='true']"
    )

    try:
        ainda_visivel = (
            botao.count() > 0
            and botao.first.is_visible()
        )
    except Exception:
        ainda_visivel = False

    if not ainda_visivel:
        print(
            "✅ O botão INSCREVER deixou "
            "de estar visível."
        )

        guardar_diagnostico(
            page,
            "07_acao_enviada",
        )

        return

    guardar_diagnostico(
        page,
        "07_resultado_inconclusivo",
    )

    raise RuntimeError(
        f"A inscrição em {modalidade} "
        "não foi confirmada e o botão "
        "INSCREVER continua visível."
    )


def executar_marcacao():
    agora = datetime.now(TIMEZONE)

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
        f"⏰ Horário alvo: {HORA_ALVO}"
    )

    print(
        "🏆 Prioridade: "
        "HYROX → CROSSFIT → STRENGHT"
    )

    if not USERNAME or not PASSWORD:
        print(
            "❌ REGYBOX_USER ou REGYBOX_PASS "
            "não estão configuradas."
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
        page.set_default_timeout(7000)

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

        try:
            print(
                "🔐 A abrir a página de login..."
            )

            page.goto(
                REGYBOX_URL,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            esperar(page, 2000)

            guardar_diagnostico(
                page,
                "01_login",
            )

            selecionar_box(page)
            efetuar_login(page)
            abrir_aulas(page)
            selecionar_dia(page, data_alvo)

            modalidade = localizar_aula_prioritaria(
                page
            )

            clicar_inscrever(
                page,
                modalidade,
            )

            verificar_resultado(
                page,
                modalidade,
            )

            print(
                f"🎉 PROCESSO CONCLUÍDO: "
                f"{modalidade}, "
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
                    f"⚠️ Não foi possível "
                    f"guardar o trace: {exc}"
                )

            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(
        executar_marcacao()
    )
