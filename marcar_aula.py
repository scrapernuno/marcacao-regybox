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


# ============================================================
# CONFIGURAÇÃO
# ============================================================

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


# ============================================================
# FUNÇÕES GERAIS
# ============================================================

def esperar(page, milissegundos=1500):
    page.wait_for_timeout(milissegundos)


def normalizar_texto(texto):
    return " ".join((texto or "").replace("\xa0", " ").split()).upper()


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
        html = page.content()

        (
            PASTA_DIAGNOSTICO / f"{nome}.html"
        ).write_text(
            html,
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

    try:
        frames = []

        for indice, frame in enumerate(page.frames):
            frames.append(
                f"FRAME={indice}\n"
                f"NOME={frame.name}\n"
                f"URL={frame.url}\n"
                f"{'-' * 80}\n"
            )

        (
            PASTA_DIAGNOSTICO
            / f"{nome}_frames.txt"
        ).write_text(
            "\n".join(frames),
            encoding="utf-8",
        )
    except Exception as exc:
        print(
            f"⚠️ Não foi possível guardar "
            f"os frames {nome}: {exc}"
        )


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


def limpar_marcadores(page):
    page.evaluate(
        """
        () => {
            const atributos = [
                "data-rbx-dia-alvo",
                "data-rbx-cartao-alvo",
                "data-rbx-inscrever-alvo"
            ];

            for (const atributo of atributos) {
                document
                    .querySelectorAll(`[${atributo}]`)
                    .forEach(elemento => {
                        elemento.removeAttribute(atributo);
                    });
            }
        }
        """
    )


# ============================================================
# LOGIN
# ============================================================

def selecionar_box(page):
    print(
        f"🔍 A selecionar a Box: "
        f"{NOME_BOX}..."
    )

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

            esperar(
                page,
                1000,
            )

            opcoes = [
                page.get_by_text(
                    NOME_BOX,
                    exact=True,
                ),
                page.get_by_text(
                    NOME_BOX,
                    exact=False,
                ),
            ]

            for opcao in opcoes:
                if clicar_primeiro_visivel(
                    opcao,
                    timeout=3000,
                ):
                    print(
                        "✅ Box selecionada."
                    )

                    esperar(
                        page,
                        1000,
                    )

                    return True

        except Exception:
            continue

    print(
        "ℹ️ A Box pode já estar selecionada "
        "ou o campo de pesquisa não está disponível."
    )

    return False


def efetuar_login(page):
    print(
        "🔑 A preencher dados de acesso..."
    )

    campo_utilizador = page.locator(
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
        campo_utilizador,
        USERNAME,
    ):
        raise RuntimeError(
            "Campo de utilizador/e-mail "
            "não encontrado."
        )

    if not preencher_primeiro_visivel(
        campo_password,
        PASSWORD,
    ):
        raise RuntimeError(
            "Campo de password não encontrado."
        )

    print(
        "🚀 A efetuar Login..."
    )

    botoes_login = page.locator(
        "button:has-text('LOGIN'), "
        "button:has-text('ENTRAR'), "
        "input[type='submit'], "
        "input[value*='LOGIN' i], "
        "input[value*='ENTRAR' i]"
    )

    if not clicar_primeiro_visivel(
        botoes_login,
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

    esperar(
        page,
        3000,
    )

    print(
        f"🌐 URL após login: {page.url}"
    )

    if "login.php" in page.url.lower():
        guardar_diagnostico(
            page,
            "erro_login",
        )

        raise RuntimeError(
            "O login não foi concluído. "
            "A página continua no login."
        )

    guardar_diagnostico(
        page,
        "02_apos_login",
    )


# ============================================================
# ABRIR ÁREA DE AULAS
# ============================================================

def abrir_aulas(page):
    print(
        "📚 PASSO 1: A clicar em AULAS..."
    )

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

    esperar(
        page,
        3500,
    )

    try:
        page.get_by_text(
            re.compile(
                r"AULAS DE .*20\d{2}",
                re.IGNORECASE,
            )
        ).first.wait_for(
            state="visible",
            timeout=10000,
        )

    except PlaywrightTimeoutError:
        guardar_diagnostico(
            page,
            "erro_calendario",
        )

        raise RuntimeError(
            "A área AULAS foi clicada, "
            "mas o calendário não apareceu."
        )

    print(
        "✅ Calendário de aulas aberto."
    )

    guardar_diagnostico(
        page,
        "03_calendario_aberto",
    )


# ============================================================
# SELECIONAR DIA
# ============================================================

def selecionar_dia_calendario(page, data_alvo):
    dia_alvo = data_alvo.day
    data_iso = data_alvo.strftime("%Y-%m-%d")

    print(
        f"📅 PASSO 2: A selecionar o dia "
        f"{dia_alvo} no calendário..."
    )

    limpar_marcadores(page)

    resultado = page.evaluate(
        """
        parametros => {
            const dia = String(parametros.dia);
            const dataIso = parametros.dataIso;

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

            const seletoresData = [
                `[data-date="${dataIso}"]`,
                `[data-day="${dataIso}"]`,
                `[data-value="${dataIso}"]`,
                `[value="${dataIso}"]`,
                `[onclick*="${dataIso}"]`,
                `[href*="${dataIso}"]`
            ];

            for (const seletor of seletoresData) {
                const elementos = Array.from(
                    document.querySelectorAll(seletor)
                );

                for (const elemento of elementos) {
                    const rect =
                        elemento.getBoundingClientRect();

                    if (
                        visivel(elemento) &&
                        rect.left <
                            window.innerWidth * 0.60
                    ) {
                        elemento.setAttribute(
                            "data-rbx-dia-alvo",
                            "true"
                        );

                        return {
                            sucesso: true,
                            metodo: "data-completa",
                            tag: elemento.tagName,
                            classe:
                                elemento.className || "",
                            texto:
                                normalizar(
                                    elemento.textContent
                                ),
                            onclick:
                                elemento.getAttribute(
                                    "onclick"
                                ) || null
                        };
                    }
                }
            }

            const todos = Array.from(
                document.querySelectorAll("body *")
            );

            const candidatos = todos.filter(
                elemento => {
                    const texto =
                        normalizar(
                            elemento.textContent
                        );

                    const rect =
                        elemento.getBoundingClientRect();

                    return (
                        texto === dia &&
                        visivel(elemento) &&
                        rect.left <
                            window.innerWidth * 0.60 &&
                        rect.top > 120
                    );
                }
            );

            candidatos.sort((a, b) => {
                const rectA =
                    a.getBoundingClientRect();

                const rectB =
                    b.getBoundingClientRect();

                const areaA =
                    rectA.width * rectA.height;

                const areaB =
                    rectB.width * rectB.height;

                return areaA - areaB;
            });

            for (const candidato of candidatos) {
                let atual = candidato;

                for (
                    let nivel = 0;
                    nivel <= 6 && atual;
                    nivel++
                ) {
                    const estilo =
                        window.getComputedStyle(atual);

                    const pareceClicavel =
                        atual.hasAttribute("onclick") ||
                        typeof atual.onclick ===
                            "function" ||
                        estilo.cursor === "pointer" ||
                        [
                            "BUTTON",
                            "A",
                            "TD",
                            "LI",
                            "SPAN"
                        ].includes(atual.tagName);

                    if (
                        visivel(atual) &&
                        pareceClicavel
                    ) {
                        atual.setAttribute(
                            "data-rbx-dia-alvo",
                            "true"
                        );

                        return {
                            sucesso: true,
                            metodo:
                                "numero-calendario",
                            tag: atual.tagName,
                            classe:
                                atual.className || "",
                            texto:
                                normalizar(
                                    atual.textContent
                                ),
                            nivel: nivel,
                            cursor: estilo.cursor,
                            onclick:
                                atual.getAttribute(
                                    "onclick"
                                ) || null
                        };
                    }

                    atual = atual.parentElement;
                }
            }

            if (candidatos.length > 0) {
                candidatos[0].setAttribute(
                    "data-rbx-dia-alvo",
                    "true"
                );

                return {
                    sucesso: true,
                    metodo: "numero-direto",
                    tag:
                        candidatos[0].tagName,
                    classe:
                        candidatos[0].className || "",
                    texto:
                        normalizar(
                            candidatos[0].textContent
                        )
                };
            }

            return {
                sucesso: false,
                candidatos:
                    candidatos.length
            };
        }
        """,
        {
            "dia": dia_alvo,
            "dataIso": data_iso,
        },
    )

    print(
        f"🔧 Elemento do dia encontrado: "
        f"{resultado}"
    )

    if not resultado.get("sucesso"):
        guardar_diagnostico(
            page,
            "erro_dia_nao_encontrado",
        )

        raise RuntimeError(
            f"Não foi encontrado o dia "
            f"{dia_alvo} no calendário."
        )

    dia = page.locator(
        "[data-rbx-dia-alvo='true']"
    ).first

    try:
        dia.wait_for(
            state="visible",
            timeout=5000,
        )

        dia.scroll_into_view_if_needed()

        dia.click(
            timeout=5000,
            force=True,
        )

        print(
            "✅ Clique no dia realizado."
        )

    except Exception as erro_click:
        print(
            "⚠️ O clique normal no dia falhou. "
            "A tentar clique JavaScript..."
        )

        print(
            f"   Detalhe: {erro_click}"
        )

        dia.evaluate(
            """
            elemento => {
                elemento.scrollIntoView({
                    behavior: "instant",
                    block: "center",
                    inline: "center"
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
            "✅ Clique JavaScript no dia realizado."
        )

    esperar(
        page,
        4000,
    )

    guardar_diagnostico(
        page,
        "04_apos_clique_dia",
    )

    confirmar_data_carregada(
        page,
        data_alvo,
    )


def confirmar_data_carregada(page, data_alvo):
    dia = data_alvo.day
    mes = MESES_PT[data_alvo.month]
    ano = data_alvo.year
    data_iso = data_alvo.strftime("%Y-%m-%d")

    padrao_cabecalho = re.compile(
        rf"\b{dia}\s+DE\s+"
        rf"{re.escape(mes)}\s+DE\s+"
        rf"{ano}\b",
        re.IGNORECASE,
    )

    try:
        cabecalho = page.get_by_text(
            padrao_cabecalho
        ).first

        cabecalho.wait_for(
            state="visible",
            timeout=4000,
        )

        print(
            f"✅ O painel confirma "
            f"{dia} de {mes.lower()} de {ano}."
        )

        return True

    except Exception:
        pass

    botoes_data = page.locator(
        f"button.buts_inscrever"
        f"[onclick*='data={data_iso}'], "
        f"button[onclick*='marca_aulas.php']"
        f"[onclick*='data={data_iso}']"
    )

    try:
        total = botoes_data.count()
    except Exception:
        total = 0

    if total > 0:
        print(
            f"✅ Data {data_iso} confirmada "
            f"através de {total} botão(ões) "
            "de inscrição existentes no HTML."
        )

        return True

    print(
        "⚠️ O cabeçalho do dia não foi confirmado. "
        "A pesquisa continuará diretamente pelos "
        "botões cujo onclick contém a data alvo."
    )

    return False


# ============================================================
# LOCALIZAR A AULA
# ============================================================

def localizar_botao_por_data_hora(
    page,
    data_alvo,
):
    data_iso = data_alvo.strftime(
        "%Y-%m-%d"
    )

    print(
        f"🔎 PASSO 3: A procurar "
        f"a aula das {HORA_ALVO} "
        f"em {data_iso}..."
    )

    limpar_marcadores(page)

    seletores = [
        (
            "button.buts_inscrever"
            f"[onclick*='data={data_iso}']"
        ),
        (
            "button[onclick*='marca_aulas.php']"
            f"[onclick*='data={data_iso}']"
        ),
        (
            f"[onclick*='data={data_iso}']"
            ":has-text('INSCREVER')"
        ),
    ]

    candidatos = None
    seletor_usado = None

    for seletor in seletores:
        locator = page.locator(seletor)

        try:
            total = locator.count()
        except Exception:
            total = 0

        print(
            f"🔧 Seletor '{seletor}' encontrou "
            f"{total} elemento(s)."
        )

        if total > 0:
            candidatos = locator
            seletor_usado = seletor
            break

    if candidatos is None:
        guardar_diagnostico(
            page,
            "erro_sem_botoes_data",
        )

        listar_botoes_inscrever(
            page
        )

        raise RuntimeError(
            f"Não foram encontrados botões "
            f"INSCREVER associados à data "
            f"{data_iso}."
        )

    total_candidatos = candidatos.count()

    print(
        f"🔢 Candidatos para {data_iso}: "
        f"{total_candidatos}"
    )

    print(
        f"🔧 Seletor utilizado: "
        f"{seletor_usado}"
    )

    diagnostico = []

    for indice in range(
        min(total_candidatos, 100)
    ):
        botao = candidatos.nth(indice)

        try:
            onclick = (
                botao.get_attribute(
                    "onclick"
                )
                or ""
            )

            classe = (
                botao.get_attribute(
                    "class"
                )
                or ""
            )

            texto_botao = normalizar_texto(
                botao.inner_text()
            )

        except Exception as exc:
            diagnostico.append(
                {
                    "indice": indice,
                    "erro": str(exc),
                }
            )

            continue

        atual = botao

        for nivel in range(0, 11):
            try:
                texto_cartao = normalizar_texto(
                    atual.inner_text(
                        timeout=1500
                    )
                )
            except Exception:
                texto_cartao = ""

            modalidade = next(
                (
                    nome
                    for nome
                    in MODALIDADES_ACEITES
                    if nome in texto_cartao
                ),
                None,
            )

            tem_hora = (
                HORA_ALVO in texto_cartao
            )

            diagnostico.append(
                {
                    "indice": indice,
                    "nivel": nivel,
                    "hora": tem_hora,
                    "modalidade": modalidade,
                    "texto":
                        texto_cartao[:400],
                    "onclick":
                        onclick[:400],
                    "classe": classe,
                    "texto_botao":
                        texto_botao,
                }
            )

            if tem_hora and modalidade:
                try:
                    atual.evaluate(
                        """
                        elemento => {
                            elemento.setAttribute(
                                "data-rbx-cartao-alvo",
                                "true"
                            );
                        }
                        """
                    )

                    botao.evaluate(
                        """
                        elemento => {
                            elemento.setAttribute(
                                "data-rbx-inscrever-alvo",
                                "true"
                            );
                        }
                        """
                    )

                    atual.scroll_into_view_if_needed()

                except Exception:
                    pass

                print(
                    f"✅ Aula encontrada: "
                    f"{modalidade} às "
                    f"{HORA_ALVO}."
                )

                print(
                    f"🖱️ Texto do botão: "
                    f"{texto_botao}"
                )

                print(
                    f"🎨 Classe: {classe}"
                )

                print(
                    f"🔧 onclick: "
                    f"{onclick[:500]}"
                )

                guardar_diagnostico(
                    page,
                    "05_aula_encontrada",
                )

                return {
                    "modalidade":
                        modalidade,
                    "onclick": onclick,
                    "classe": classe,
                    "texto":
                        texto_cartao,
                }

            try:
                atual = atual.locator(
                    "xpath=.."
                )
            except Exception:
                break

    guardar_diagnostico(
        page,
        "erro_aula_nao_associada",
    )

    print(
        "📋 Diagnóstico dos candidatos:"
    )

    for item in diagnostico[:50]:
        if "erro" in item:
            print(
                f"   Índice={item['indice']} | "
                f"Erro={item['erro']}"
            )
            continue

        print(
            "   "
            f"Índice={item['indice']} | "
            f"Nível={item['nivel']} | "
            f"Hora={item['hora']} | "
            f"Modalidade="
            f"{item['modalidade']} | "
            f"Texto={item['texto']}"
        )

    raise RuntimeError(
        f"Foram encontrados botões para "
        f"{data_iso}, mas nenhum cartão "
        f"associou simultaneamente "
        f"{HORA_ALVO} a uma modalidade aceite."
    )


def listar_botoes_inscrever(page):
    try:
        botoes = page.locator(
            "button.buts_inscrever, "
            "button:has-text('INSCREVER'), "
            "[onclick*='marca_aulas.php']"
        )

        total = botoes.count()

        print(
            f"🔎 Total geral de possíveis "
            f"botões INSCREVER: {total}"
        )

        for indice in range(min(total, 50)):
            botao = botoes.nth(indice)

            try:
                texto = normalizar_texto(
                    botao.inner_text()
                )

                onclick = (
                    botao.get_attribute(
                        "onclick"
                    )
                    or ""
                )

                print(
                    f"   [{indice}] "
                    f"Texto={texto} | "
                    f"onclick={onclick[:500]}"
                )

            except Exception as exc:
                print(
                    f"   [{indice}] "
                    f"Erro={exc}"
                )

    except Exception as exc:
        print(
            f"⚠️ Não foi possível listar "
            f"os botões: {exc}"
        )


# ============================================================
# CLICAR EM INSCREVER
# ============================================================

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
            state="attached",
            timeout=7000,
        )

        botao.scroll_into_view_if_needed()

        esperar(
            page,
            700,
        )

        texto = normalizar_texto(
            botao.inner_text()
        )

        onclick = (
            botao.get_attribute(
                "onclick"
            )
            or ""
        )

        disabled = botao.get_attribute(
            "disabled"
        )

        print(
            f"🖱️ Botão encontrado: "
            f"'{texto}'"
        )

        print(
            f"🔧 onclick: {onclick[:500]}"
        )

        print(
            f"🚫 Atributo disabled: "
            f"{disabled}"
        )

        if disabled is not None:
            guardar_diagnostico(
                page,
                "botao_desativado",
            )

            raise RuntimeError(
                "O botão INSCREVER está "
                "marcado como disabled."
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
                "⚠️ O clique Playwright falhou. "
                "A tentar clique JavaScript..."
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
            f"Falha ao clicar em "
            f"INSCREVER: {exc}"
        ) from exc

    esperar(
        page,
        4000,
    )

    guardar_diagnostico(
        page,
        "06_apos_clique_inscrever",
    )


# ============================================================
# CONFIRMAÇÃO
# ============================================================

def confirmar_modal_se_existir(page):
    print(
        "🔍 A verificar se existe "
        "confirmação adicional..."
    )

    candidatos = page.locator(
        "button:has-text('CONFIRMAR'), "
        "button:has-text('SIM'), "
        "button:has-text('OK'), "
        "button:has-text('ACEITAR'), "
        "a:has-text('CONFIRMAR'), "
        "[onclick]:has-text('CONFIRMAR')"
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

            texto = normalizar_texto(
                candidato.inner_text()
            )

            candidato.click(
                timeout=3000,
                force=True,
            )

            print(
                f"✅ Confirmação adicional "
                f"aceite: {texto}"
            )

            esperar(
                page,
                3000,
            )

            guardar_diagnostico(
                page,
                "07_apos_confirmacao",
            )

            return True

        except Exception:
            continue

    print(
        "ℹ️ Não apareceu uma confirmação "
        "adicional."
    )

    return False


def verificar_resultado(
    page,
    data_alvo,
    modalidade,
):
    print(
        "🔎 PASSO 5: A verificar "
        "o resultado da inscrição..."
    )

    confirmar_modal_se_existir(
        page
    )

    esperar(
        page,
        2000,
    )

    try:
        texto_pagina = normalizar_texto(
            page.locator(
                "body"
            ).inner_text()
        )
    except Exception:
        texto_pagina = ""

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

    encontrados = [
        indicador
        for indicador
        in indicadores_sucesso
        if indicador in texto_pagina
    ]

    if encontrados:
        print(
            "🎉 Confirmação encontrada: "
            f"{', '.join(encontrados)}"
        )

        guardar_diagnostico(
            page,
            "08_sucesso_confirmado",
        )

        return True

    data_iso = data_alvo.strftime(
        "%Y-%m-%d"
    )

    botao_original = page.locator(
        "[data-rbx-inscrever-alvo='true']"
    )

    try:
        total_original = (
            botao_original.count()
        )
    except Exception:
        total_original = -1

    botoes_data = page.locator(
        f"button.buts_inscrever"
        f"[onclick*='data={data_iso}']"
    )

    try:
        total_data = botoes_data.count()
    except Exception:
        total_data = -1

    print(
        f"ℹ️ Marcador do botão original "
        f"ainda presente: {total_original}"
    )

    print(
        f"ℹ️ Botões INSCREVER restantes "
        f"para {data_iso}: {total_data}"
    )

    print(
        "⚠️ O clique foi executado, mas "
        "a página não apresentou uma "
        "confirmação textual inequívoca."
    )

    print(
        f"✅ A ação foi enviada para "
        f"{modalidade}, em {data_iso}, "
        f"às {HORA_ALVO}."
    )

    guardar_diagnostico(
        page,
        "08_resultado_inconclusivo",
    )

    return True


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

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

            aula = localizar_botao_por_data_hora(
                page,
                data_alvo,
            )

            clicar_inscrever(
                page
            )

            verificar_resultado(
                page,
                data_alvo,
                aula["modalidade"],
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
                    f"⚠️ Não foi possível "
                    f"guardar o trace: {exc}"
                )

            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(
        executar_marcacao()
    )
