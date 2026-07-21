import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BASE_URL = "https://www.regibox.pt/app/app_nova/"
PHP_URL = urljoin(BASE_URL, "php/")

LOGIN_URL = urljoin(
    PHP_URL,
    "login/scripts/verifica_acesso.php?lang=pt",
)

SET_SESSION_URL = urljoin(
    BASE_URL,
    "set_session.php",
)

AULAS_URL = urljoin(
    PHP_URL,
    "aulas/aulas.php",
)

USERNAME = os.environ.get("REGYBOX_USER", "").strip()
PASSWORD = os.environ.get("REGYBOX_PASS", "").strip()

# O log da Naval Box mostrou id=80.
# Pode ser substituído através de um GitHub Secret REGYBOX_BOX_ID.
BOX_ID = os.environ.get("REGYBOX_BOX_ID", "80").strip()

TIMEZONE = ZoneInfo("Atlantic/Madeira")

# As inscrições abrem com quatro dias de antecedência.
DIAS_ANTECEDENCIA = 4

HORA_ALVO = "18:25"

# Prioridade obrigatória.
PRIORIDADES = [
    "HYROX",
    "HIROX",
    "CROSSFIT",
    "STRENGHT",
    "STRENGTH",
]

TIMEOUT_SEGUNDOS = 20
PASTA_DIAGNOSTICO = Path("diagnostico_regybox")

HEADERS = {
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
# MODELOS
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

    @property
    def cheia(self) -> bool:
        return (
            self.ocupacao_atual is not None
            and self.capacidade_maxima is not None
            and self.ocupacao_atual >= self.capacidade_maxima
        )


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

    caminho = PASTA_DIAGNOSTICO / nome
    caminho.write_text(
        conteudo,
        encoding="utf-8",
    )


def guardar_json(nome: str, conteudo) -> None:
    preparar_diagnostico()

    caminho = PASTA_DIAGNOSTICO / nome
    caminho.write_text(
        json.dumps(
            conteudo,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


# ============================================================
# SESSÃO HTTP
# ============================================================

def criar_sessao() -> requests.Session:
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
    sessao.headers.update(HEADERS)
    sessao.mount("https://", adaptador)
    sessao.mount("http://", adaptador)

    return sessao


def validar_resposta(
    resposta: requests.Response,
    contexto: str,
) -> None:
    try:
        resposta.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"{contexto}: HTTP "
            f"{resposta.status_code}"
        ) from exc

    texto = resposta.text.lower()

    if "app/app_nova/login.php" in texto:
        raise RuntimeError(
            f"{contexto}: a Regibox devolveu "
            "a página de login; a sessão não é válida."
        )


# ============================================================
# LOGIN
# ============================================================

def extrair_cookie_regybox(
    resposta: requests.Response,
) -> Optional[str]:
    # Primeira opção: cookie enviado pelo servidor.
    cookie = resposta.cookies.get(
        "regybox_user"
    )

    if cookie:
        return unquote(cookie)

    # Segunda opção: cookie já incorporado na sessão.
    cookie = resposta.request._cookies.get(
        "regybox_user"
    )

    if cookie:
        return unquote(cookie)

    texto = resposta.text.strip()

    padroes = [
        r"regybox_user=([^&;\"'\s]+)",
        r"regybox_user%3D([^&;\"'\s]+)",
        r"(?:^|&)z=([^&]+)",
    ]

    for padrao in padroes:
        correspondencia = re.search(
            padrao,
            texto,
            flags=re.IGNORECASE,
        )

        if correspondencia:
            return unquote(
                correspondencia.group(1)
            )

    # Compatibilidade com a resposta usada por
    # implementações antigas da API.
    try:
        partes = texto.split("&")[0].split("=")

        if len(partes) >= 3:
            candidato = unquote(
                partes[2].strip()
            )

            if candidato:
                return candidato
    except Exception:
        pass

    return None


def efetuar_login(
    sessao: requests.Session,
) -> str:
    print(
        f"🔐 A autenticar na Regibox "
        f"(box_id={BOX_ID})..."
    )

    resposta = sessao.post(
        LOGIN_URL,
        data={
            "id_box": BOX_ID,
            "login": USERNAME,
            "password": PASSWORD,
        },
        timeout=TIMEOUT_SEGUNDOS,
    )

    guardar_texto(
        "01_resposta_login.txt",
        resposta.text,
    )

    resposta.raise_for_status()

    texto_normalizado = resposta.text.upper()

    if (
        "ACESSO NEGADO" in texto_normalizado
        or "ACCESS DENIED" in texto_normalizado
    ):
        raise RuntimeError(
            "A Regibox recusou o utilizador "
            "ou a password."
        )

    regybox_user = extrair_cookie_regybox(
        resposta
    )

    if not regybox_user:
        guardar_json(
            "01_cookies_login.json",
            sessao.cookies.get_dict(),
        )

        raise RuntimeError(
            "O login respondeu, mas não foi "
            "possível extrair o cookie regybox_user."
        )

    # Garantir os cookies usados pelas chamadas internas.
    sessao.cookies.set(
        "regybox_user",
        regybox_user,
        domain="www.regibox.pt",
        path="/",
    )

    sessao.cookies.set(
        "regybox_boxes",
        f"*{regybox_user}",
        domain="www.regibox.pt",
        path="/",
    )

    print("✅ Autenticação aceite.")

    print(
        "🍪 Cookies presentes: "
        + ", ".join(
            sorted(sessao.cookies.get_dict())
        )
    )

    ativar_sessao(
        sessao,
        regybox_user,
    )

    return regybox_user


def ativar_sessao(
    sessao: requests.Session,
    regybox_user: str,
) -> None:
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
        timeout=TIMEOUT_SEGUNDOS,
    )

    resposta.raise_for_status()

    guardar_texto(
        "02_resposta_set_session.html",
        resposta.text,
    )

    print("✅ Sessão interna ativada.")


# ============================================================
# OBTENÇÃO E PARSING DAS AULAS
# ============================================================

def timestamp_data(data_alvo) -> int:
    # Usar meio-dia evita alterações de dia por timezone/DST.
    instante = datetime(
        data_alvo.year,
        data_alvo.month,
        data_alvo.day,
        12,
        0,
        tzinfo=TIMEZONE,
    )

    return int(
        instante.timestamp() * 1000
    )


def obter_html_aulas(
    sessao: requests.Session,
    data_alvo,
    regybox_user: str,
) -> str:
    data_iso = data_alvo.isoformat()

    print(
        f"📡 A obter as aulas de "
        f"{data_iso} diretamente da Regibox..."
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
        timeout=TIMEOUT_SEGUNDOS,
    )

    validar_resposta(
        resposta,
        "Obtenção das aulas",
    )

    guardar_texto(
        "03_aulas_resposta.html",
        resposta.text,
    )

    print(
        f"✅ Resposta das aulas recebida "
        f"({len(resposta.text)} bytes)."
    )

    return resposta.text


def classes_do_elemento(elemento: Tag) -> set[str]:
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


def normalizar_texto(texto: str) -> str:
    return " ".join(
        (texto or "")
        .replace("\xa0", " ")
        .split()
    )


def extrair_urls_botoes(
    bloco: Tag,
) -> tuple[
    Optional[str],
    Optional[str],
]:
    url_inscrever = None
    url_cancelar = None

    for botao in bloco.find_all("button"):
        onclick = botao.get(
            "onclick",
            "",
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

            caminho = urlparse(url).path

            prefixo_permitido = (
                "/app/app_nova/php/aulas/"
            )

            if not caminho.startswith(
                prefixo_permitido
            ):
                continue

            if caminho.endswith(
                "/marca_aulas.php"
            ):
                url_inscrever = url

            elif caminho.endswith(
                "/cancela_aula.php"
            ):
                url_cancelar = url

    return (
        url_inscrever,
        url_cancelar,
    )


def extrair_data_bloco(
    bloco: Tag,
    data_fallback: str,
) -> str:
    identificador = bloco.get(
        "id",
        "",
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

    atual = int(
        correspondencia.group(1)
    )

    maxima_texto = correspondencia.group(2)

    maxima = (
        None
        if maxima_texto == "∞"
        else int(maxima_texto)
    )

    return atual, maxima


def parsear_aulas(
    html: str,
    data_alvo: str,
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

        correspondencia_hora = re.search(
            r"(\d{1,2}:\d{2})\s*-\s*"
            r"(\d{1,2}:\d{2})",
            horario,
        )

        if not correspondencia_hora:
            continue

        inicio = correspondencia_hora.group(1)
        fim = correspondencia_hora.group(2)

        ocupacao, capacidade = (
            extrair_capacidade(bloco)
        )

        (
            url_inscrever,
            url_cancelar,
        ) = extrair_urls_botoes(bloco)

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
                    r"preloader.*color-orange"
                ),
            )
        )

        aulas.append(
            Aula(
                nome=nome,
                data=extrair_data_bloco(
                    bloco,
                    data_alvo,
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

def prioridade_nome(nome: str) -> int:
    nome_normalizado = nome.upper()

    for indice, prioridade in enumerate(
        PRIORIDADES
    ):
        if prioridade in nome_normalizado:
            return indice

    return len(PRIORIDADES) + 100


def escolher_aula(
    aulas: list[Aula],
    data_alvo: str,
) -> Aula:
    aulas_horario = [
        aula
        for aula in aulas
        if aula.inicio == HORA_ALVO
    ]

    print(
        f"🕒 Aulas encontradas às "
        f"{HORA_ALVO}: "
        f"{len(aulas_horario)}"
    )

    for aula in aulas_horario:
        estado = (
            "INSCRITO"
            if aula.inscrito
            else (
                "ABERTA"
                if aula.aberta
                else "FECHADA"
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
        if prioridade_nome(aula.nome)
        < len(PRIORIDADES) + 100
    ]

    if not candidatas:
        raise RuntimeError(
            f"Não existe HYROX, CROSSFIT ou "
            f"STRENGHT às {HORA_ALVO} "
            f"em {data_alvo}."
        )

    candidatas.sort(
        key=lambda aula: prioridade_nome(
            aula.nome
        )
    )

    # Caso já esteja inscrito numa aula
    # compatível às 18:25, não tentar outra.
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
        resumo = [
            {
                "nome": aula.nome,
                "inicio": aula.inicio,
                "ocupacao": (
                    aula.ocupacao_atual,
                    aula.capacidade_maxima,
                ),
                "cheia": aula.cheia,
                "aberta": aula.aberta,
            }
            for aula in candidatas
        ]

        guardar_json(
            "05_aulas_sem_inscricao.json",
            resumo,
        )

        raise RuntimeError(
            "Foram encontradas aulas às "
            f"{HORA_ALVO}, mas nenhuma está "
            "aberta para inscrição."
        )

    escolhida = abertas[0]

    print(
        f"🏆 Aula selecionada: "
        f"{escolhida.nome} "
        f"({escolhida.inicio}-"
        f"{escolhida.fim})."
    )

    print(
        "📋 Prioridade aplicada: "
        "HYROX → CROSSFIT → STRENGHT."
    )

    return escolhida


# ============================================================
# INSCRIÇÃO
# ============================================================

def validar_url_inscricao(
    url: str,
    data_alvo: str,
) -> None:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise RuntimeError(
            "O URL de inscrição não usa HTTPS."
        )

    if parsed.netloc != "www.regibox.pt":
        raise RuntimeError(
            "O URL de inscrição aponta para "
            "um domínio inesperado."
        )

    if parsed.path != (
        "/app/app_nova/php/aulas/"
        "marca_aulas.php"
    ):
        raise RuntimeError(
            "O URL de inscrição aponta para "
            "um endpoint inesperado."
        )

    parametros = parse_qs(
        parsed.query
    )

    data_url = parametros.get(
        "data",
        [None],
    )[0]

    if (
        data_url is not None
        and data_url != data_alvo
    ):
        raise RuntimeError(
            "A data do URL de inscrição não "
            "corresponde à data alvo: "
            f"{data_url} != {data_alvo}"
        )

    if not parametros.get("id_aula"):
        raise RuntimeError(
            "O URL de inscrição não contém "
            "id_aula."
        )


def extrair_mensagem_resposta(
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

        correspondencias = [
            r"""msg_toast_icon\s*\(\s*["'](.+?)["']\s*,""",
            r"""msg_toast\s*\(\s*["'](.+?)["']""",
            r"""alert\s*\(\s*["'](.+?)["']\s*\)""",
        ]

        for padrao in correspondencias:
            correspondencia = re.search(
                padrao,
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


def executar_inscricao(
    sessao: requests.Session,
    aula: Aula,
    data_alvo: str,
) -> str:
    if aula.inscrito or aula.lista_espera:
        return (
            f"Já inscrito em {aula.nome} "
            f"às {aula.inicio}"
        )

    if not aula.url_inscrever:
        raise RuntimeError(
            "A aula selecionada não possui "
            "URL de inscrição."
        )

    validar_url_inscricao(
        aula.url_inscrever,
        data_alvo,
    )

    parsed = urlparse(
        aula.url_inscrever
    )

    parametros_seguros = parse_qs(
        parsed.query
    )

    print(
        "🎯 A enviar a inscrição diretamente "
        "para a Regibox..."
    )

    print(
        f"🆔 id_aula="
        f"{parametros_seguros.get('id_aula', ['?'])[0]}"
    )

    print(
        f"🏋️ modalidade={aula.nome}"
    )

    print(
        f"📅 data={data_alvo}"
    )

    resposta = sessao.get(
        aula.url_inscrever,
        timeout=TIMEOUT_SEGUNDOS,
    )

    validar_resposta(
        resposta,
        "Inscrição",
    )

    guardar_texto(
        "06_resposta_inscricao.html",
        resposta.text,
    )

    mensagem = extrair_mensagem_resposta(
        resposta.text
    )

    if mensagem:
        print(
            f"💬 Resposta Regibox: {mensagem}"
        )

    texto_upper = normalizar_texto(
        resposta.text
    ).upper()

    sinais_falha = [
        "ACESSO NEGADO",
        "NÃO FOI POSSÍVEL",
        "NAO FOI POSSIVEL",
        "ERRO",
        "ERROR",
        "JÁ ESTÁS INSCRITO NOUTRA",
        "JA ESTAS INSCRITO NOUTRA",
    ]

    for sinal in sinais_falha:
        if sinal in texto_upper:
            raise RuntimeError(
                "A Regibox respondeu com uma "
                f"indicação de falha: {mensagem or sinal}"
            )

    return mensagem or (
        "Pedido de inscrição aceite "
        "pela Regibox"
    )


# ============================================================
# CONFIRMAÇÃO FINAL
# ============================================================

def confirmar_inscricao(
    sessao: requests.Session,
    data_alvo,
    regybox_user: str,
    aula_escolhida: Aula,
) -> bool:
    print(
        "🔎 A confirmar a inscrição "
        "através de uma nova leitura..."
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
            == aula_escolhida.nome.upper()
        )

        mesmo_horario = (
            aula.inicio
            == aula_escolhida.inicio
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
                "lista de espera"
                if aula.lista_espera
                else "inscrito"
            )

            print(
                f"🎉 CONFIRMADO: {estado} em "
                f"{aula.nome}, às "
                f"{aula.inicio}."
            )

            guardar_json(
                "07_confirmacao_sucesso.json",
                asdict(aula),
            )

            return True

    guardar_json(
        "07_confirmacao_falhou.json",
        [
            asdict(aula)
            for aula in aulas
            if aula.inicio == HORA_ALVO
        ],
    )

    return False


# ============================================================
# EXECUÇÃO
# ============================================================

def executar() -> int:
    preparar_diagnostico()

    agora = datetime.now(TIMEZONE)
    data_alvo = (
        agora + timedelta(
            days=DIAS_ANTECEDENCIA
        )
    ).date()

    print(
        f"[{agora.strftime('%H:%M:%S')}] "
        "🚀 A iniciar o robô Regibox HTTP..."
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

    if not BOX_ID.isdigit():
        print(
            "❌ REGYBOX_BOX_ID deve ser "
            "um número."
        )

        return 2

    sessao = criar_sessao()

    try:
        regybox_user = efetuar_login(
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
                "blocos de aulas reconhecíveis."
            )

        aula = escolher_aula(
            aulas,
            data_alvo.isoformat(),
        )

        if aula.inscrito or aula.lista_espera:
            print(
                "✅ Não é necessário enviar "
                "uma nova inscrição."
            )

            guardar_json(
                "07_ja_inscrito.json",
                asdict(aula),
            )

            return 0

        mensagem = executar_inscricao(
            sessao,
            aula,
            data_alvo.isoformat(),
        )

        print(
            f"✅ Pedido enviado: {mensagem}"
        )

        if not confirmar_inscricao(
            sessao,
            data_alvo,
            regybox_user,
            aula,
        ):
            raise RuntimeError(
                "O pedido foi enviado, mas uma "
                "nova leitura não confirmou a "
                "inscrição nem a lista de espera."
            )

        print(
            "🎉 PROCESSO CONCLUÍDO: "
            f"{aula.nome}, "
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

        guardar_json(
            "99_cookies_presentes.json",
            {
                "nomes": sorted(
                    sessao.cookies.get_dict()
                )
            },
        )

        return 1

    finally:
        sessao.close()


if __name__ == "__main__":
    sys.exit(executar())
