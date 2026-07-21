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

        # Scroll para carregar a lista toda
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)

        aula_marcada = False

        for modalidade in AULAS_PRIORIDADE:
            if aula_marcada:
                break

            print(f"🔎 A procurar: {modalidade} às {HORARIO_TARGET}...")

            # Procura o container div principal (id "feed_time_slot...") que contém a hora e a modalidade
            slot_xpath = f"//div[contains(@id, 'feed_time_slot') and contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{modalidade}') and contains(., '{HORARIO_TARGET}')]"
            slot = page.locator(f"xpath={slot_xpath}").first

            if slot.is_visible():
                print(f"💡 Card de {modalidade} das {HORARIO_TARGET} localizado!")
                slot.scroll_into_view_if_needed()

                texto_slot = slot.inner_text().upper()
                if "CANCELAR" in texto_slot or "INSCRITO" in texto_slot:
                    print(f"🎉 JÁ ESTÁS INSCRITO em {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

                # Procura o botão 'button' com onclick contendo marca_aulas.php dentro deste slot
                botao = slot.locator("button[onclick*='marca_aulas.php'], button.buts_inscrever, button:has-text('INSCREVER')").first

                if botao.is_visible():
                    print(f"🎯 Botão INSCREVER encontrado! A clicar...")
                    botao.click(force=True)
                    page.wait_for_timeout(3000)
                    print(f"🎉 SUCESSO: Inscrição efetuada em {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

        # Método de emergência baseado na propriedade onclick revelada pelo HTML
        if not aula_marcada:
            print("🔄 A tentar inscrição direta via seletor de emergência...")
            botao_emergencia = page.locator(f"xpath=//div[contains(., '{HORARIO_TARGET}')]//button[contains(@onclick, 'marca_aulas.php')]").first
            if botao_emergencia.is_visible():
                botao_emergencia.click(force=True)
                print(f"🎉 SUCESSO: Botão clicado via seletor direto das {HORARIO_TARGET}!")
                aula_marcada = True

        if not aula_marcada:
            print(f"❌ Não foi possível realizar a inscrição para as {HORARIO_TARGET}.")

        browser.close()

if __name__ == "__main__":
    executar_marcacao()
