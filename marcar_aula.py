import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BASE_URL = "https://www.regibox.pt/app/app_nova/"
LOGIN_URL = urljoin(BASE_URL, "login.php")
SET_SESSION_URL = urljoin(BASE_URL, "set_session.php")
AULAS_URL = urljoin(BASE_URL, "php/aulas/aulas.php")

NOME_BOX = "Naval Box"

USERNAME = os.environ.get("REGYBOX_USER", "").strip()
PASSWORD = os.environ.get("REGYBOX_PASS", "").strip()

TIMEZONE = ZoneInfo("Atlantic/Madeira")

# A aula é procurada quatro dias depois da execução.
DIAS_ANTECEDENCIA = 4

HORA_ALVO = "18:25"

# Ordem obrigatória.
PRIORIDADES = [
    "HYROX",
    "HIROX",
    "CROSSFIT",
    "STRENGHT",
    "STRENGTH",
]

TIMEOUT_HTTP = 25
PASTA_DIAGNOSTICO = Path("diagnostico_regybox")

HEADERS_HTTP = {
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "DNT": "1",
    "Referer": BASE_URL,
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


# ============================================================
# MODELO DE AULA
# ============================================================

@dataclass
class Aula:
    nome: str
    data: str
    inicio: str
    fim: str
    ocupacao_atual: Optional[int]
    capacidade_maxima: Optional[int]
    url_inscrever: Optional[str]
    url_cancelar: Optional[str]
    inscrito: bool
    lista_espera: bool
    texto: str

    @property
    def aberta(self) -> bool:
        return bool(self.url_inscrever)


# ============================================================
# DIAGNÓSTICO
# ============================================================

def preparar_diagnostico() -> None:
    PASTA_DIAGNOSTICO.mkdir(
        parents=True,
        exist_ok=True,
    )


def guardar_texto(nome: str, conteudo: str) -> None:
    preparar_diagnostico()

    (
        PASTA_DIAGNOSTICO / nome
    ).write_text(
        conteudo,
        encoding="utf-8",
    )


def guardar_json(nome: str, conteudo) -> None:
    preparar_diagnostico()

    (
        PASTA_DIAGNOSTICO / nome
    ).write_text(
        json.dumps(
            conteudo,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def normalizar_texto(texto: str) -> str:
    return " ".join(
        (texto or "")
        .replace("\xa0", " ")
        .split()
    )


def normalizar_upper(texto: str) -> str:
    return normalizar_texto(texto).upper()


# ============================================================
# AUTENTICAÇÃO COM PLAYWRIGHT
# ============================================================

def preencher_primeiro_visivel(locator, valor: str) -> bool:
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


def clicar_primeiro_visivel(locator, timeout: int = 5000) -> bool:
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


def selecionar_box_playwright(page) -> None:
    print(
        f"🔍 A selecionar a Box: {NOME_BOX}..."
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
            page.wait_for_timeout(1000)

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
                    print("✅ Box selecionada.")
                    page.wait_for_timeout(1000)
                    return

        except Exception:
            continue

    raise RuntimeError(
        f"Não foi possível selecionar a Box "
        f"'{NOME_BOX}'."
    )


def autenticar_com_playwright() -> list[dict]:
    print(
        "🔐 A autenticar com Playwright, "
        "tal como no script anterior..."
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

        page = context.new_page()
        page.set_default_timeout(7000)

        page.on(
            "pageerror",
            lambda erro: print(
                f"💥 JAVASCRIPT DA REGIBOX: {erro}"
            ),
        )

        try:
            page.goto(
                LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            page.wait_for_timeout(2000)

            selecionar_box_playwright(page)

            print(
                "🔑 A preencher os dados de acesso..."
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

            print("🚀 A efetuar login...")

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
                page.wait_for_url(
                    re.compile(
                        r"/app/app_nova/index\.php",
                        re.IGNORECASE,
                    ),
                    timeout=20000,
                )
            except PlaywrightTimeoutError:
                try:
                    page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=5000,
                    )
                except PlaywrightTimeoutError:
                    pass

            page.wait_for_timeout(3000)

            print(
                f"🌐 URL após login: {page.url}"
            )

            if "login.php" in page.url.lower():
                page.screenshot(
                    path=str(
                        PASTA_DIAGNOSTICO
                        / "erro_login.png"
                    ),
                    full_page=True,
                )

                raise RuntimeError(
                    "O login não foi concluído."
                )

            page.screenshot(
                path=str(
                    PASTA_DIAGNOSTICO
                    / "01_login_concluido.png"
                ),
                full_page=True,
            )

            cookies = context.cookies()

            nomes_cookies = sorted(
                {
                    cookie["name"]
                    for cookie in cookies
                }
            )

            print(
                "🍪 Cookies obtidos automaticamente: "
                + ", ".join(nomes_cookies)
            )

            guardar_json(
                "01_cookies_extraidos.json",
                {
                    "nomes": nomes_cookies,
                    "quantidade": len(cookies),
                },
            )

            cookies_obrigatorios = {
                "PHPSESSID",
                "regybox_user",
            }

            faltantes = (
                cookies_obrigatorios
                - set(nomes_cookies)
            )

            if faltantes:
                raise RuntimeError(
                    "A autenticação abriu a aplicação, "
                    "mas não criou os cookies: "
                    + ", ".join(sorted(faltantes))
                )

            print(
                "✅ Autenticação Playwright concluída."
            )

            return cookies

        finally:
            context.close()
            browser.close()


# ============================================================
# TRANSFERÊNCIA DOS COOKIES PARA REQUESTS
# ============================================================

def criar_sessao_http(
    cookies_playwright: list[dict],
) -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=0.5,
        status_forcelist={
            429,
            500,
            502,
            503,
            504,
        },
        allowed_methods={
            "HEAD",
            "GET",
            "POST",
            "OPTIONS",
        },
    )

    adaptador = HTTPAdapter(
        max_retries=retry,
    )

    sessao = requests.Session()
    sessao.headers.update(HEADERS_HTTP)
    sessao.mount("https://", adaptador)
    sessao.mount("http://", adaptador)

    for cookie in cookies_playwright:
        nome = cookie.get("name")
        valor = cookie.get("value")
        dominio = cookie.get("domain")
        caminho = cookie.get("path", "/")

        if not nome or valor is None:
            continue

        kwargs = {
            "name": nome,
            "value": valor,
            "path": caminho or "/",
        }

        if dominio:
            kwargs["domain"] = dominio

        sessao.cookies.set(**kwargs)

    cookies_atuais = sessao.cookies.get_dict()

    regybox_user = cookies_atuais.get(
        "regybox_user"
    )

    if regybox_user:
        # Algumas chamadas internas esperam
        # também este cookie.
        sessao.cookies.set(
            "regybox_boxes",
            f"*{regybox_user}",
            domain="www.regibox.pt",
            path="/",
        )

    print(
        "🔄 Cookies transferidos para "
        "a sessão HTTP."
    )

    print(
        "🍪 Sessão HTTP contém: "
        + ", ".join(
            sorted(sessao.cookies.get_dict())
        )
    )

    return sessao


def ativar_sessao_http(
    sessao: requests.Session,
) -> str:
    cookies = sessao.cookies.get_dict()

    regybox_user = cookies.get(
        "regybox_user"
    )

    if not regybox_user:
        raise RuntimeError(
            "O cookie regybox_user não existe "
            "na sessão HTTP."
        )

    print(
        "🔧 A ativar a sessão interna "
        "da Naval Box..."
    )

    resposta = sessao.get(
        SET_SESSION_URL,
        params={
            "z": regybox_user,
            "y": f"*{regybox_user}",
            "ignore": "regybox.pt/app/app",
        },
        timeout=TIMEOUT_HTTP,
        allow_redirects=True,
    )

    resposta.raise_for_status()

    guardar_texto(
        "02_set_session.html",
        resposta.text,
    )

    print(
        f"✅ Sessão interna ativada "
        f"(HTTP {resposta.status_code})."
    )

    return regybox_user


# ============================================================
# CONSULTA DAS AULAS
# ============================================================

def timestamp_data(data_alvo) -> int:
    instante = datetime(
        data_alvo.year,
        data_alvo.month,
        data_alvo.day,
        0,
        0,
        0,
        tzinfo=TIMEZONE,
    )

    return int(
        instante.timestamp() * 1000
    )


def resposta_e_login(
    resposta: requests.Response,
) -> bool:
    url_final = resposta.url.lower()
    texto = resposta.text.lower()

    return (
        "login.php" in url_final
        or "app/app_nova/login.php" in texto
        or (
            "input" in texto
            and "type=\"password\"" in texto
            and "verifica_acesso" in texto
        )
    )


def obter_html_aulas(
    sessao: requests.Session,
    data_alvo,
    regybox_user: str,
) -> str:
    data_iso = data_alvo.isoformat()

    print(
        f"📡 A obter as aulas de "
        f"{data_iso} diretamente..."
    )

    resposta = sessao.get(
        AULAS_URL,
        params={
            "valor1": str(
                timestamp_data(data_alvo)
            ),
            "type": "",
            "source": "mes",
            "scroll": "s",
            "box": "",
            "plano": "0",
            "z": regybox_user,
        },
        timeout=TIMEOUT_HTTP,
        allow_redirects=True,
    )

    resposta.raise_for_status()

    guardar_texto(
        "03_aulas_resposta.html",
        resposta.text,
    )

    guardar_json(
        "03_aulas_resposta_metadata.json",
        {
            "url_final": resposta.url,
            "status": resposta.status_code,
            "historico": [
                {
                    "status": item.status_code,
                    "url": item.url,
                    "location": item.headers.get(
                        "Location"
                    ),
                }
                for item in resposta.history
            ],
            "cookies": sorted(
                sessao.cookies.get_dict()
            ),
        },
    )

    if resposta_e_login(resposta):
        raise RuntimeError(
            "A sessão autenticada pelo navegador "
            "não foi aceite na consulta das aulas."
        )

    print(
        f"✅ Aulas recebidas "
        f"({len(resposta.text)} bytes)."
    )

    return resposta.text


# ============================================================
# PARSING
# ============================================================

def classes_do_elemento(
    elemento: Tag,
) -> set[str]:
    classes = elemento.get(
        "class",
        [],
    )

    if isinstance(classes, str):
        classes = classes.split()

    return set(classes)


def encontrar_div(
    bloco: Tag,
    *,
    align: Optional[str] = None,
    classe: Optional[str] = None,
    padrao: Optional[re.Pattern] = None,
) -> Optional[Tag]:
    for elemento in bloco.find_all("div"):
        if (
            align is not None
            and elemento.get("align") != align
        ):
            continue

        if (
            classe is not None
            and classe not in classes_do_elemento(
                elemento
            )
        ):
            continue

        texto = normalizar_texto(
            elemento.get_text(
                " ",
                strip=True,
            )
        )

        if (
            padrao is not None
            and not padrao.search(texto)
        ):
            continue

        return elemento

    return None


def extrair_capacidade(
    bloco: Tag,
) -> tuple[
    Optional[int],
    Optional[int],
]:
    elemento = encontrar_div(
        bloco,
        align="center",
        classe="col",
        padrao=re.compile(
            r"\S+\s+(?:DE|OF)\s+\S+",
            flags=re.IGNORECASE,
        ),
    )

    if elemento is None:
        return None, None

    texto = normalizar_texto(
        elemento.get_text(
            " ",
            strip=True,
        )
    )

    correspondencia = re.search(
        r"(\d+)\s+(?:DE|OF)\s+(\d+|∞)",
        texto,
        flags=re.IGNORECASE,
    )

    if not correspondencia:
        return None, None

    ocupacao = int(
        correspondencia.group(1)
    )

    capacidade_texto = (
        correspondencia.group(2)
    )

    capacidade = (
        None
        if capacidade_texto == "∞"
        else int(capacidade_texto)
    )

    return ocupacao, capacidade


def extrair_urls(
    bloco: Tag,
) -> tuple[
    Optional[str],
    Optional[str],
]:
    url_inscrever = None
    url_cancelar = None

    for botao in bloco.find_all("button"):
        onclick = str(
            botao.get("onclick", "")
        )

        urls = re.findall(
            r"""[^'"\s,(]+\.php(?:\?[^'"\s,)]*)?""",
            onclick,
            flags=re.IGNORECASE,
        )

        for url_bruto in urls:
            url = urljoin(
                BASE_URL,
                url_bruto.replace(
                    "&amp;",
                    "&",
                ),
            )

            parsed = urlparse(url)

            prefixo = (
                "/app/app_nova/php/aulas/"
            )

            if not parsed.path.startswith(
                prefixo
            ):
                continue

            if parsed.path.endswith(
                "/marca_aulas.php"
            ):
                url_inscrever = url

            elif parsed.path.endswith(
                "/cancela_aula.php"
            ):
                url_cancelar = url

    return url_inscrever, url_cancelar


def extrair_data_bloco(
    bloco: Tag,
    data_fallback: str,
) -> str:
    identificador = str(
        bloco.get("id", "")
    )

    correspondencia = re.fullmatch(
        r"feed_time_slot(\d+)",
        identificador,
    )

    if not correspondencia:
        return data_fallback

    try:
        epoch = int(
            correspondencia.group(1)
        )

        return datetime.fromtimestamp(
            epoch,
            tz=TIMEZONE,
        ).date().isoformat()

    except (ValueError, OSError):
        return data_fallback


def parsear_aulas(
    html: str,
    data_fallback: str,
) -> list[Aula]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    blocos = [
        elemento
        for elemento in soup.find_all("div")
        if "filtro0" in classes_do_elemento(
            elemento
        )
    ]

    print(
        f"🧩 Blocos de aula encontrados: "
        f"{len(blocos)}"
    )

    aulas: list[Aula] = []

    for bloco in blocos:
        nome_elemento = encontrar_div(
            bloco,
            align="left",
            classe="col-50",
        )

        horario_elemento = encontrar_div(
            bloco,
            align="left",
            classe="col",
            padrao=re.compile(
                r"\b\d{1,2}:\d{2}\s*-\s*"
                r"\d{1,2}:\d{2}\b"
            ),
        )

        if (
            nome_elemento is None
            or horario_elemento is None
        ):
            continue

        nome = normalizar_texto(
            nome_elemento.get_text(
                " ",
                strip=True,
            )
        )

        horario = normalizar_texto(
            horario_elemento.get_text(
                " ",
                strip=True,
            )
        )

        correspondencia = re.search(
            r"(\d{1,2}:\d{2})\s*-\s*"
            r"(\d{1,2}:\d{2})",
            horario,
        )

        if not correspondencia:
            continue

        inicio = correspondencia.group(1)
        fim = correspondencia.group(2)

        ocupacao, capacidade = (
            extrair_capacidade(bloco)
        )

        (
            url_inscrever,
            url_cancelar,
        ) = extrair_urls(bloco)

        texto_bloco = normalizar_texto(
            bloco.get_text(
                " ",
                strip=True,
            )
        )

        inscrito = bool(
            url_cancelar
            or bloco.find(
                "div",
                class_="ok_color",
            )
        )

        lista_espera = bool(
            bloco.find(
                "div",
                class_=re.compile(
                    r"preloader.*color-orange",
                    flags=re.IGNORECASE,
                ),
            )
        )

        aulas.append(
            Aula(
                nome=nome,
                data=extrair_data_bloco(
                    bloco,
                    data_fallback,
                ),
                inicio=inicio,
                fim=fim,
                ocupacao_atual=ocupacao,
                capacidade_maxima=capacidade,
                url_inscrever=url_inscrever,
                url_cancelar=url_cancelar,
                inscrito=inscrito,
                lista_espera=lista_espera,
                texto=texto_bloco,
            )
        )

    guardar_json(
        "04_aulas_parseadas.json",
        [
            asdict(aula)
            for aula in aulas
        ],
    )

    return aulas


# ============================================================
# ESCOLHA DA AULA
# ============================================================

def prioridade(nome: str) -> int:
    nome_upper = nome.upper()

    for indice, modalidade in enumerate(
        PRIORIDADES
    ):
        if modalidade in nome_upper:
            return indice

    return 999


def escolher_aula(
    aulas: list[Aula],
    data_iso: str,
) -> Aula:
    aulas_horario = [
        aula
        for aula in aulas
        if aula.inicio == HORA_ALVO
    ]

    print(
        f"🕒 Aulas às {HORA_ALVO}: "
        f"{len(aulas_horario)}"
    )

    for aula in aulas_horario:
        estado = (
            "INSCRITO"
            if aula.inscrito
            else (
                "LISTA DE ESPERA"
                if aula.lista_espera
                else (
                    "ABERTA"
                    if aula.aberta
                    else "FECHADA"
                )
            )
        )

        print(
            f"   • {aula.nome} | "
            f"{aula.inicio}-{aula.fim} | "
            f"{aula.ocupacao_atual}/"
            f"{aula.capacidade_maxima} | "
            f"{estado}"
        )

    candidatas = [
        aula
        for aula in aulas_horario
        if prioridade(aula.nome) < 999
    ]

    if not candidatas:
        raise RuntimeError(
            f"Não existe HYROX, CROSSFIT "
            f"ou STRENGHT às {HORA_ALVO} "
            f"em {data_iso}."
        )

    candidatas.sort(
        key=lambda aula: prioridade(
            aula.nome
        )
    )

    inscritas = [
        aula
        for aula in candidatas
        if aula.inscrito
        or aula.lista_espera
    ]

    if inscritas:
        escolhida = inscritas[0]

        print(
            f"🎉 Já está inscrito em "
            f"{escolhida.nome} às "
            f"{HORA_ALVO}."
        )

        return escolhida

    abertas = [
        aula
        for aula in candidatas
        if aula.aberta
    ]

    if not abertas:
        raise RuntimeError(
            "As modalidades prioritárias foram "
            "encontradas, mas nenhuma possui "
            "botão de inscrição."
        )

    escolhida = abertas[0]

    print(
        f"🏆 Aula selecionada: "
        f"{escolhida.nome} "
        f"({escolhida.inicio}-"
        f"{escolhida.fim})."
    )

    return escolhida


# ============================================================
# INSCRIÇÃO
# ============================================================

def validar_url_inscricao(
    url: str,
    data_iso: str,
) -> None:
    parsed = urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.netloc
        != "www.regibox.pt"
    ):
        raise RuntimeError(
            "O URL de inscrição aponta para "
            "um domínio inesperado."
        )

    caminho_esperado = (
        "/app/app_nova/php/aulas/"
        "marca_aulas.php"
    )

    if parsed.path != caminho_esperado:
        raise RuntimeError(
            "O URL de inscrição aponta para "
            "um endpoint inesperado."
        )

    parametros = parse_qs(
        parsed.query
    )

    if not parametros.get("id_aula"):
        raise RuntimeError(
            "O URL não contém id_aula."
        )

    data_url = parametros.get(
        "data",
        [None],
    )[0]

    if (
        data_url
        and data_url != data_iso
    ):
        raise RuntimeError(
            f"A data do URL é {data_url}, "
            f"mas a data alvo é {data_iso}."
        )


def extrair_mensagem(
    html: str,
) -> Optional[str]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for script in soup.find_all("script"):
        texto = script.get_text(
            " ",
            strip=False,
        )

        correspondencia = re.search(
            r"""msg_toast_icon\s*\(\s*["'](.+?)["']\s*,""",
            texto,
            flags=re.IGNORECASE
            | re.DOTALL,
        )

        if correspondencia:
            return normalizar_texto(
                correspondencia.group(1)
            )

    texto = normalizar_texto(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    return texto or None


def inscrever(
    sessao: requests.Session,
    aula: Aula,
    data_iso: str,
) -> str:
    if aula.inscrito or aula.lista_espera:
        return (
            f"Já inscrito em {aula.nome}"
        )

    if not aula.url_inscrever:
        raise RuntimeError(
            "A aula selecionada não possui "
            "URL de inscrição."
        )

    validar_url_inscricao(
        aula.url_inscrever,
        data_iso,
    )

    parametros = parse_qs(
        urlparse(
            aula.url_inscrever
        ).query
    )

    print(
        "🎯 A enviar a inscrição..."
    )

    print(
        f"🆔 id_aula="
        f"{parametros.get('id_aula', ['?'])[0]}"
    )

    print(f"🏋️ modalidade={aula.nome}")
    print(f"📅 data={data_iso}")

    resposta = sessao.get(
        aula.url_inscrever,
        timeout=TIMEOUT_HTTP,
        allow_redirects=True,
    )

    resposta.raise_for_status()

    guardar_texto(
        "05_resposta_inscricao.html",
        resposta.text,
    )

    if resposta_e_login(resposta):
        raise RuntimeError(
            "A sessão expirou durante "
            "a inscrição."
        )

    mensagem = extrair_mensagem(
        resposta.text
    )

    if mensagem:
        print(
            f"💬 Resposta Regibox: "
            f"{mensagem}"
        )

    texto_upper = normalizar_upper(
        resposta.text
    )

    falhas = [
        "ACESSO NEGADO",
        "NÃO FOI POSSÍVEL",
        "NAO FOI POSSIVEL",
        "JÁ ESTÁS INSCRITO NOUTRA",
        "JA ESTAS INSCRITO NOUTRA",
    ]

    for falha in falhas:
        if falha in texto_upper:
            raise RuntimeError(
                mensagem or falha
            )

    return mensagem or (
        "Pedido aceite pela Regibox"
    )


# ============================================================
# CONFIRMAÇÃO
# ============================================================

def confirmar(
    sessao: requests.Session,
    data_alvo,
    regybox_user: str,
    escolhida: Aula,
) -> bool:
    print(
        "🔎 A confirmar a inscrição..."
    )

    time.sleep(2)

    html = obter_html_aulas(
        sessao,
        data_alvo,
        regybox_user,
    )

    aulas = parsear_aulas(
        html,
        data_alvo.isoformat(),
    )

    for aula in aulas:
        mesma_modalidade = (
            aula.nome.upper()
            == escolhida.nome.upper()
        )

        mesmo_horario = (
            aula.inicio
            == escolhida.inicio
        )

        if (
            mesma_modalidade
            and mesmo_horario
            and (
                aula.inscrito
                or aula.lista_espera
            )
        ):
            estado = (
                "LISTA DE ESPERA"
                if aula.lista_espera
                else "INSCRITO"
            )

            print(
                f"🎉 CONFIRMADO: {estado} "
                f"em {aula.nome}, "
                f"às {aula.inicio}."
            )

            guardar_json(
                "06_confirmacao.json",
                asdict(aula),
            )

            return True

    return False


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar() -> int:
    preparar_diagnostico()

    agora = datetime.now(TIMEZONE)

    data_alvo = (
        agora
        + timedelta(
            days=DIAS_ANTECEDENCIA
        )
    ).date()

    print(
        f"[{agora.strftime('%H:%M:%S')}] "
        "🚀 A iniciar o robô Regibox híbrido..."
    )

    print(
        f"📅 Data atual Madeira: "
        f"{agora.strftime('%d/%m/%Y')}"
    )

    print(
        f"📅 Data alvo (+4 dias): "
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

    sessao: Optional[
        requests.Session
    ] = None

    try:
        cookies = autenticar_com_playwright()

        sessao = criar_sessao_http(
            cookies
        )

        regybox_user = ativar_sessao_http(
            sessao
        )

        html = obter_html_aulas(
            sessao,
            data_alvo,
            regybox_user,
        )

        aulas = parsear_aulas(
            html,
            data_alvo.isoformat(),
        )

        if not aulas:
            raise RuntimeError(
                "A Regibox não devolveu "
                "aulas reconhecíveis."
            )

        escolhida = escolher_aula(
            aulas,
            data_alvo.isoformat(),
        )

        if (
            escolhida.inscrito
            or escolhida.lista_espera
        ):
            guardar_json(
                "06_ja_inscrito.json",
                asdict(escolhida),
            )

            print(
                "✅ Nenhuma nova ação necessária."
            )

            return 0

        mensagem = inscrever(
            sessao,
            escolhida,
            data_alvo.isoformat(),
        )

        print(
            f"✅ Pedido enviado: {mensagem}"
        )

        if not confirmar(
            sessao,
            data_alvo,
            regybox_user,
            escolhida,
        ):
            raise RuntimeError(
                "O pedido foi enviado, mas "
                "a nova leitura não confirmou "
                "a inscrição nem a lista de espera."
            )

        print(
            "🎉 PROCESSO CONCLUÍDO: "
            f"{escolhida.nome}, "
            f"{data_alvo.strftime('%d/%m/%Y')} "
            f"às {HORA_ALVO}."
        )

        return 0

    except Exception as exc:
        erro = (
            f"{type(exc).__name__}: {exc}"
        )

        print(f"❌ ERRO: {erro}")

        guardar_texto(
            "99_erro_final.txt",
            erro,
        )

        if sessao is not None:
            guardar_json(
                "99_sessao_http.json",
                {
                    "cookies": sorted(
                        sessao.cookies.get_dict()
                    )
                },
            )

        return 1

    finally:
        if sessao is not None:
            sessao.close()


if __name__ == "__main__":
    sys.exit(executar())
