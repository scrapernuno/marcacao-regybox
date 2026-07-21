import os
import time
import datetime
from playwright.sync_api import sync_playwright

REGYBOX_URL = "https://www.regibox.pt/app/app_nova/login.php"
NOME_BOX = "Naval Box"

USERNAME = os.environ.get("REGYBOX_USER", "")
PASSWORD = os.environ.get("REGYBOX_PASS", "")

HORARIO_TARGET = "18:25"
AULAS_PRIORIDADE = ["HYROX", "HIROX", "CROSSFIT", "STRENGHT", "STRENGTH"]

def executar_marcacao():
    agora = datetime.datetime.now()
    data_alvo = agora + datetime.timedelta(days=3)
    dia_alvo = str(data_alvo.day)

    print(f"[{agora.strftime('%H:%M:%S')}] 🚀 A iniciar o robô de marcação...")
    print(f"📅 Data alvo (+3 dias): {data_alvo.strftime('%d/%m/%Y')} (Dia {dia_alvo})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("🔐 A efetuar login...")
        page.goto(REGYBOX_URL)
        page.fill("input[placeholder*='Procura']", NOME_BOX)
        page.wait_for_timeout(1000)
        page.click(f"text='{NOME_BOX}'")
        page.wait_for_timeout(1000)

        page.fill("input[placeholder*='e-mail']", USERNAME)
        page.fill("input[placeholder*='password']", PASSWORD)
        page.click("text='LOGIN'")

        page.wait_for_timeout(4000)

        # Navegar para AULAS
        try:
            botao_aulas = page.locator("a[onclick*='calendario_aulas']").first
            if botao_aulas.is_visible():
                print("🗺️ A abrir calendário de aulas...")
                botao_aulas.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass

        # Clicar no dia (+3 dias)
        print(f"📅 A selecionar o dia {dia_alvo} no calendário...")
        try:
            seletor_dia = page.locator(f"xpath=//td[not(contains(@class,'disabled'))]//span[text()='{dia_alvo}'] | //div[contains(@class,'day')]//text()[normalize-space()='{dia_alvo}']/parent::*").first
            if seletor_dia.is_visible():
                seletor_dia.click(force=True)
                print(f"✅ Dia {dia_alvo} selecionado!")
                page.wait_for_timeout(2500)
        except Exception as e:
            print(f"⚠️ Seleção de dia: {e}")

        # Rolar a página várias vezes para garantir que o bloco das 18:25 carrega totalmente na vista
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)

        aula_marcada = False

        for modalidade in AULAS_PRIORIDADE:
            if aula_marcada:
                break

            print(f"🔎 A procurar: {modalidade} às {HORARIO_TARGET}...")

            # Procura qualquer div/bloco que contenha a modalidade E a hora 18:25
            seletor_bloco = f"xpath=//div[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{modalidade}') and contains(., '{HORARIO_TARGET}')]"
            blocos = page.locator(seletor_bloco)

            if blocos.count() > 0:
                print(f"💡 Bloco de {modalidade} das {HORARIO_TARGET} localizado!")
                bloco = blocos.first
                bloco.scroll_into_view_if_needed()

                # Verifica se já está inscrito
                texto_bloco = bloco.inner_text().upper()
                if "CANCELAR" in texto_bloco or "INSCRITO" in texto_bloco:
                    print(f"🎉 JÁ ESTÁS INSCRITO em {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

                # Tenta clicar no botão INSCREVER dentro desse bloco
                botao = bloco.locator("text='INSCREVER'").first
                if not botao.is_visible():
                    botao = bloco.locator("button, a, div").filter(has_text="INSCREVER").first

                if botao.is_visible():
                    print(f"🎯 Botão INSCREVER encontrado! A clicar...")
                    botao.click(force=True)
                    page.wait_for_timeout(3000)
                    print(f"🎉 SUCESSO: Inscrição enviada para {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

        # Backup: Se o seletor por bloco falhar, tenta clicar diretamente no botão INSCREVER que esteja ao lado das 18:25
        if not aula_marcada:
            print("🔄 A tentar método de recurso (busca direta pelo botão)...")
            botao_directo = page.locator(f"xpath=//*[contains(., '{HORARIO_TARGET}')]//text()[contains(., 'INSCREVER')]/parent::* | //*[contains(., '{HORARIO_TARGET}')]//button[contains(., 'INSCREVER')]").first
            if botao_directo.is_visible():
                botao_directo.click(force=True)
                print(f"🎉 SUCESSO: Botão clicado via método direto para as {HORARIO_TARGET}!")
                aula_marcada = True

        if not aula_marcada:
            print(f"❌ Não foi possível realizar a inscrição para as {HORARIO_TARGET}.")

        browser.close()

if __name__ == "__main__":
    executar_marcacao()
