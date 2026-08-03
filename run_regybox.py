"""Lançador compatível com a verificação inicial da Regibox.

Mantém o marcar_aula.py como autoridade funcional e acrescenta uma espera
controlada quando a Regibox apresenta a página intermédia de verificação.
"""

from __future__ import annotations

import sys
import time

import marcar_aula
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


TIMEOUT_VERIFICACAO_SEGUNDOS = 90
INTERVALO_VERIFICACAO_MS = 3000


def _normalizar(texto: str) -> str:
    return " ".join((texto or "").replace("\xa0", " ").split()).upper()


def _pagina_em_verificacao(page: Page) -> bool:
    try:
        texto = _normalizar(page.locator("body").inner_text(timeout=3000))
    except Exception:
        texto = ""

    try:
        titulo = _normalizar(page.title())
    except Exception:
        titulo = ""

    marcadores = (
        "AGUARDE ENQUANTO SUA SOLICITAÇÃO ESTÁ SENDO VERIFICADA",
        "AGUARDE ENQUANTO SUA SOLICITACAO ESTA SENDO VERIFICADA",
        "UM MOMENTO, POR FAVOR",
        "VERIFICANDO O SEU NAVEGADOR",
        "CHECKING YOUR BROWSER",
        "VERIFYING YOUR REQUEST",
    )

    return any(
        marcador in texto or marcador in titulo
        for marcador in marcadores
    )


def aguardar_verificacao_regibox(page: Page) -> None:
    limite = time.monotonic() + TIMEOUT_VERIFICACAO_SEGUNDOS
    tentativa = 0

    while _pagina_em_verificacao(page):
        tentativa += 1
        restante = int(max(0, limite - time.monotonic()))

        if restante <= 0:
            marcar_aula.guardar_pagina(page, "erro_verificacao_antibot")
            raise RuntimeError(
                "A verificação inicial da Regibox não terminou em "
                f"{TIMEOUT_VERIFICACAO_SEGUNDOS} segundos."
            )

        print(
            "⏳ A Regibox está a verificar o navegador "
            f"({tentativa}; restam cerca de {restante}s)..."
        )

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PlaywrightTimeoutError:
            pass

        page.wait_for_timeout(INTERVALO_VERIFICACAO_MS)

    print("✅ Página de verificação inicial ultrapassada.")


_selecionar_box_original = marcar_aula.selecionar_box


def selecionar_box_com_verificacao(page: Page) -> None:
    aguardar_verificacao_regibox(page)
    _selecionar_box_original(page)


marcar_aula.selecionar_box = selecionar_box_com_verificacao


if __name__ == "__main__":
    sys.exit(marcar_aula.executar())
