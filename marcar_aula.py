import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
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
            "A página continua no formulário de login."
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
# SELECIONAR E CARREGAR O DIA
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
            const dataIso = parametros.dataIso;
            const dia = String(parametros.dia);

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

            const elementosData = Array.from(
                document.querySelectorAll(
                    `[onclick*="wods_dia"][onclick*="${dataIso}"]`
                )
            );

            for (const elementoData of elementosData) {
                const descendentes = [
                    elementoData,
                    ...Array.from(
                        elementoData.querySelectorAll("*")
                    )
                ];

                const numeroDia =
                    descendentes.find(elemento => {
                        return (
                            visivel(elemento) &&
                            normalizar(
                                elemento.textContent
                            ) === dia
                        );
                    });

                if (numeroDia) {
                    const clicavel =
                        numeroDia.closest(
                            "[onclick*='wods_dia']"
                        ) || elementoData;

                    clicavel.setAttribute(
                        "data-rbx-dia-alvo",
                        "true"
                    );

                    return {
                        sucesso: true,
                        metodo:
                            "wods_dia_numero",
                        tag:
                            clicavel.tagName,
                        texto:
                            normalizar(
                                clicavel.textContent
                            ),
                        onclick:
                            clicavel.getAttribute(
                                "onclick"
                            ) || null
                    };
                }
            }

            if (elementosData.length > 0) {
                const elemento =
                    elementosData[0];

                elemento.setAttribute(
                    "data-rbx-dia-alvo",
                    "true"
                );

                return {
                    sucesso: true,
                    metodo:
                        "wods_dia_onclick",
                    tag:
                        elemento.tagName,
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

            return {
                sucesso: false,
                totalElementosData:
                    elementosData.length
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
            f"Não foi encontrado no calendário "
            f"um elemento wods_dia para {data_iso}."
        )

    resultado_chamada = page.evaluate(
        """
        dataIso => {
            if (
                typeof window.wods_dia
                !== "function"
            ) {
                return {
                    sucesso: false,
                    erro:
                        "window.wods_dia não existe",
                    tipo:
                        typeof window.wods_dia
                };
            }

            try {
                window.wods_dia(dataIso);

                return {
                    sucesso: true,
                    metodo:
                        "window.wods_dia",
                    data: dataIso
                };

            } catch (erro) {
                return {
                    sucesso: false,
                    erro:
                        String(erro),
                    stack:
                        erro && erro.stack
                        ? String(erro.stack)
                        : null
                };
            }
        }
        """,
        data_iso,
    )

    print(
        f"🔧 Resultado de wods_dia: "
        f"{resultado_chamada}"
    )

    if not resultado_chamada.get("sucesso"):
        print(
            "⚠️ A chamada direta wods_dia falhou. "
            "A tentar clicar no elemento original..."
        )

        dia = page.locator(
            "[data-rbx-dia-alvo='true']"
        ).first

        try:
            dia.wait_for(
                state="attached",
                timeout=5000,
            )

            dia.scroll_into_view_if_needed()

            dia.click(
                timeout=5000,
                force=True,
            )

            print(
                "✅ Clique de fallback "
                "no calendário realizado."
            )

        except Exception as exc:
            guardar_diagnostico(
                page,
                "erro_chamada_wods_dia",
            )

            raise RuntimeError(
                f"Falhou wods_dia e também "
                f"o clique no dia {dia_alvo}: {exc}"
            ) from exc

    esperar_aulas_da_data(
        page,
        data_alvo,
    )

    guardar_diagnostico(
        page,
        "04_dia_carregado",
    )

    confirmar_data_carregada(
        page,
        data_alvo,
    )


def esperar_aulas_da_data(page, data_alvo):
    data_iso = data_alvo.strftime(
        "%Y-%m-%d"
    )

    print(
        f"⏳ A aguardar o carregamento "
        f"das aulas de {data_iso}..."
    )

    try:
        page.wait_for_function(
            """
            dataIso => {
                const botoes = Array.from(
                    document.querySelectorAll(
                        "[onclick*='marca_aulas.php']"
                    )
                );

                return botoes.some(elemento => {
                    const onclick =
                        elemento.getAttribute(
                            "onclick"
                        ) || "";

                    return onclick.includes(
                        `data=${dataIso}`
                    );
                });
            }
            """,
            data_iso,
            timeout=20000,
        )

    except PlaywrightTimeoutError:
        guardar_diagnostico(
            page,
            "timeout_carregamento_aulas",
        )

        diagnostico = page.evaluate(
            """
            dataIso => {
                const elementos = Array.from(
                    document.querySelectorAll(
                        "[onclick]"
                    )
                )
                .map(elemento => ({
                    tag:
                        elemento.tagName,
                    texto:
                        (
                            elemento.textContent || ""
                        )
                        .replace(/\\s+/g, " ")
                        .trim()
                        .substring(0, 180),
                    onclick:
                        (
                            elemento.getAttribute(
                                "onclick"
                            ) || ""
                        ).substring(0, 500)
                }))
                .filter(item => {
                    return (
                        item.onclick.includes(
                            dataIso
                        ) ||
                        item.onclick.includes(
                            "marca_aulas.php"
                        ) ||
                        item.onclick.includes(
                            "wods_dia"
                        )
                    );
                });

                return {
                    data:
                        dataIso,
                    elementos:
                        elementos.slice(0, 100)
                };
            }
            """,
            data_iso,
        )

        print(
            f"🔧 Diagnóstico após timeout: "
            f"{diagnostico}"
        )

        raise RuntimeError(
            f"A Regibox não terminou de carregar "
            f"as aulas de {data_iso} "
            "em 20 segundos."
        )

    esperar(
        page,
        1500,
    )

    total = page.locator(
        f"[onclick*='marca_aulas.php']"
        f"[onclick*='data={data_iso}']"
    ).count()

    print(
        f"✅ Painel carregado para {data_iso}. "
        f"Controlos associados à data: {total}."
    )


def confirmar_data_carregada(page, data_alvo):
    dia = data_alvo.day
    mes = MESES_PT[data_alvo.month]
    ano = data_alvo.year
    data_iso = data_alvo.strftime(
        "%Y-%m-%d"
    )

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

        if cabecalho.is_visible(
            timeout=3000
        ):
            print(
                f"✅ O cabeçalho confirma "
                f"{dia} de {mes.lower()} "
                f"de {ano}."
            )

            return True

    except Exception:
        pass

    controlos_data = page.locator(
        f"[onclick*='marca_aulas.php']"
        f"[onclick*='data={data_iso}']"
    )

    try:
        total = controlos_data.count()
    except Exception:
        total = 0

    if total > 0:
        print(
            f"✅ A data {data_iso} foi confirmada "
            f"através de {total} controlo(s) "
            "de aula presentes no HTML."
        )

        return True

    guardar_diagnostico(
        page,
        "erro_data_nao_confirmada",
    )

    raise RuntimeError(
        f"O calendário executou "
        f"wods_dia('{data_iso}'), "
        "mas não apareceu o cabeçalho "
        "nem qualquer controlo de aula "
        "associado à data."
    )


# ============================================================
# LOCALIZAR A AULA
# ============================================================

def localizar_aula(page, data_alvo):
    data_iso = data_alvo.strftime(
        "%Y-%m-%d"
    )

    print(
        f"🔎 PASSO 3: A procurar "
        f"a aula das {HORA_ALVO} "
        f"em {data_iso}..."
    )

    limpar_marcadores(page)

    botoes = page.locator(
        f"button.buts_inscrever"
        f"[onclick*='data={data_iso}'], "
        f"button[onclick*='marca_aulas.php']"
        f"[onclick*='data={data_iso}'], "
        f"[onclick*='marca_aulas.php']"
        f"[onclick*='data={data_iso}']"
    )

    try:
        total = botoes.count()
    except Exception:
        total = 0

    print(
        f"🔢 Possíveis botões de inscrição "
        f"encontrados: {total}"
    )

    diagnostico = []

    for indice in range(min(total, 150)):
        botao = botoes.nth(indice)

        try:
            onclick = (
                botao.get_attribute(
                    "onclick"
                )
                or ""
            )

            texto_botao = normalizar_texto(
                botao.inner_text()
            )

            classe = (
                botao.get_attribute(
                    "class"
                )
                or ""
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

        for nivel in range(0, 12):
            try:
                texto_cartao = normalizar_texto(
                    atual.inner_text(
                        timeout=1500
                    )
                )
            except Exception:
                texto_cartao = ""

            tem_hora = (
                HORA_ALVO in texto_cartao
            )

            modalidade = next(
                (
                    nome
                    for nome
                    in MODALIDADES_ACEITES
                    if nome in texto_cartao
                ),
                None,
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
                        onclick[:500],
                }
            )

            if tem_hora and modalidade:
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

                try:
                    atual.scroll_into_view_if_needed()
                except Exception:
                    pass

                url_load_script = extrair_url_load_script(
                    onclick
                )

                dados_url = analisar_url_inscricao(
                    url_load_script
                )

                print(
                    f"✅ Aula encontrada: "
                    f"{modalidade} às {HORA_ALVO}."
                )

                print(
                    f"🖱️ Texto do botão: "
                    f"{texto_botao}"
                )

                print(
                    f"🎨 Classe: {classe}"
                )

                print(
                    f"🆔 ID da aula: "
                    f"{dados_url.get('id_aula')}"
                )

                print(
                    f"📅 Data da chamada: "
                    f"{dados_url.get('data')}"
                )

                print(
                    f"🔧 URL load_script: "
                    f"{url_load_script}"
                )

                guardar_diagnostico(
                    page,
                    "05_aula_encontrada",
                )

                return {
                    "modalidade":
                        modalidade,
                    "onclick":
                        onclick,
                    "url_load_script":
                        url_load_script,
                    "id_aula":
                        dados_url.get(
                            "id_aula"
                        ),
                    "data":
                        dados_url.get(
                            "data"
                        ),
                    "source":
                        dados_url.get(
                            "source"
                        ),
                    "classe":
                        classe,
                    "texto_cartao":
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
        "erro_aula_nao_encontrada",
    )

    print(
        "📋 Diagnóstico dos candidatos:"
    )

    for item in diagnostico[:60]:
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
        f"Não foi encontrada uma aula para "
        f"{data_iso}, às {HORA_ALVO}, "
        "com uma modalidade aceite."
    )


def extrair_url_load_script(onclick):
    padroes = [
        re.compile(
            r"""load_script\(\s*['"]([^'"]+)['"]\s*,\s*['"]prov['"]\s*\)""",
            re.IGNORECASE,
        ),
        re.compile(
            r"""load_script\(\s*['"]([^'"]+)['"]""",
            re.IGNORECASE,
        ),
    ]

    for padrao in padroes:
        correspondencia = padrao.search(
            onclick or ""
        )

        if correspondencia:
            return correspondencia.group(1)

    raise RuntimeError(
        "Não foi possível extrair a URL "
        "da chamada load_script do onclick."
    )


def analisar_url_inscricao(url):
    if not url:
        raise RuntimeError(
            "A URL de inscrição está vazia."
        )

    url_absoluta = url

    if url.startswith("../"):
        url_absoluta = (
            "https://www.regibox.pt/app/"
            + url.replace("../", "", 1)
        )

    elif url.startswith("/"):
        url_absoluta = (
            "https://www.regibox.pt"
            + url
        )

    elif not url.startswith("http"):
        url_absoluta = (
            "https://www.regibox.pt/"
            + url.lstrip("/")
        )

    parsed = urlparse(
        url_absoluta
    )

    parametros = parse_qs(
        parsed.query
    )

    def primeiro(nome):
        valores = parametros.get(
            nome,
            [],
        )

        if valores:
            return valores[0]

        return None

    return {
        "id_aula":
            primeiro("id_aula"),
        "data":
            primeiro("data"),
        "source":
            primeiro("source"),
        "ano":
            primeiro("ano"),
        "id_rato":
            primeiro("id_rato"),
        "plano":
            primeiro("plano"),
        "box":
            primeiro("box"),
    }


# ============================================================
# EXECUTAR A INSCRIÇÃO
# ============================================================

def executar_inscricao_direta(
    page,
    aula,
    data_alvo,
):
    data_iso = data_alvo.strftime(
        "%Y-%m-%d"
    )

    url_load_script = aula[
        "url_load_script"
    ]

    if aula.get("data") != data_iso:
        raise RuntimeError(
            "A data extraída do botão não "
            "corresponde à data alvo. "
            f"Botão={aula.get('data')} | "
            f"Alvo={data_iso}"
        )

    if not aula.get("id_aula"):
        raise RuntimeError(
            "O id_aula não foi encontrado "
            "na chamada de inscrição."
        )

    print(
        "🎯 PASSO 4: A executar diretamente "
        "a chamada de inscrição da Regibox..."
    )

    print(
        f"🆔 id_aula={aula['id_aula']}"
    )

    print(
        f"📅 data={aula['data']}"
    )

    print(
        f"🏋️ modalidade={aula['modalidade']}"
    )

    resultado = page.evaluate(
        """
        parametros => {
            const url = parametros.url;

            if (
                typeof window.load_script
                !== "function"
            ) {
                return {
                    sucesso: false,
                    erro:
                        "window.load_script não existe",
                    tipo:
                        typeof window.load_script
                };
            }

            try {
                window.load_script(
                    url,
                    "prov"
                );

                return {
                    sucesso: true,
                    metodo:
                        "window.load_script",
                    url: url
                };

            } catch (erro) {
                return {
                    sucesso: false,
                    erro:
                        String(erro),
                    stack:
                        erro && erro.stack
                        ? String(erro.stack)
                        : null
                };
            }
        }
        """,
        {
            "url":
                url_load_script,
        },
    )

    print(
        f"🔧 Resultado da chamada direta: "
        f"{resultado}"
    )

    if not resultado.get("sucesso"):
        print(
            "⚠️ A chamada direta load_script "
            "falhou. A tentar clicar "
            "no botão original..."
        )

        fallback = page.evaluate(
            """
            () => {
                const botao =
                    document.querySelector(
                        "[data-rbx-inscrever-alvo='true']"
                    );

                if (!botao) {
                    return {
                        sucesso: false,
                        erro:
                            "Botão original não encontrado"
                    };
                }

                try {
                    botao.click();

                    return {
                        sucesso: true,
                        metodo:
                            "element.click"
                    };

                } catch (erro) {
                    return {
                        sucesso: false,
                        erro:
                            String(erro)
                    };
                }
            }
            """
        )

        print(
            f"🔧 Resultado do fallback: "
            f"{fallback}"
        )

        if not fallback.get("sucesso"):
            guardar_diagnostico(
                page,
                "erro_execucao_inscricao",
            )

            raise RuntimeError(
                "Falhou a chamada load_script "
                "e também o clique JavaScript "
                "no botão."
            )

    esperar(
        page,
        4500,
    )

    guardar_diagnostico(
        page,
        "06_apos_execucao_inscricao",
    )

    print(
        "✅ A chamada de inscrição "
        "foi executada."
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
    aula,
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
        2500,
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

    botao_alvo = page.locator(
        "[data-rbx-inscrever-alvo='true']"
    )

    try:
        total_marcador = (
            botao_alvo.count()
        )
    except Exception:
        total_marcador = -1

    try:
        visivel = (
            total_marcador > 0
            and botao_alvo.first.is_visible()
        )
    except Exception:
        visivel = False

    print(
        f"ℹ️ Botão original ainda presente: "
        f"{total_marcador}"
    )

    print(
        f"ℹ️ Botão original ainda visível: "
        f"{visivel}"
    )

    if not visivel:
        print(
            "✅ O botão INSCREVER deixou "
            "de estar visível após a chamada."
        )

        guardar_diagnostico(
            page,
            "08_acao_enviada",
        )

        return True

    guardar_diagnostico(
        page,
        "08_resultado_inconclusivo",
    )

    print(
        "⚠️ A chamada foi executada, "
        "mas não foi possível confirmar "
        "inequivocamente a resposta final."
    )

    print(
        f"ℹ️ Aula: {aula['modalidade']} | "
        f"Data: {data_alvo.strftime('%Y-%m-%d')} | "
        f"Hora: {HORA_ALVO} | "
        f"id_aula: {aula['id_aula']}"
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

            aula = localizar_aula(
                page,
                data_alvo,
            )

            executar_inscricao_direta(
                page,
                aula,
                data_alvo,
            )

            verificar_resultado(
                page,
                data_alvo,
                aula,
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
