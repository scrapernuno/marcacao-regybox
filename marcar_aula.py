import os
import time
import datetime
from playwright.sync_api import sync_playwright

REGYBOX_URL = "https://www.regibox.pt/app/app_nova/login.php"
BASE_URL = "https://www.regibox.pt/app/app_nova/index.php"
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
                page.wait_for_timeout(2000)
        except Exception as e:
            print(f"⚠️ Seleção de dia: {e}")

        # Faz scroll até ao fim da lista para carregar os horários do fim do dia
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        # Tentar Inscrição por ordem de prioridade
        aula_marcada = False

        for modalidade in AULAS_PRIORIDADE:
            if aula_marcada:
                break

            print(f"🔎 A verificar prioridade: {modalidade} às {HORARIO_TARGET}...")

            bloco_aula = page.locator("xpath=//*[contains(@class,'card') or contains(@class,'aula') or contains(@class,'row') or self::div]").filter(has_text=modalidade).filter(has_text=HORARIO_TARGET).first

            if bloco_aula.count() > 0:
                # Faz scroll até ao bloco da aula encontrada
                bloco_aula.scroll_into_view_if_needed()
                botao_inscrever = bloco_aula.locator("*:has-text('INSCREVER')").first

                if botao_inscrever.is_visible():
                    print(f"🎯 Aula de {modalidade} das {HORARIO_TARGET} aberta! A clicar em INSCREVER...")
                    botao_inscrever.click(force=True)
                    page.wait_for_timeout(3000)

                    conteudo = page.content()
                    if "sucesso" in conteudo.lower() or "marcada" in conteudo.lower() or "cancelar" in conteudo.lower() or "estás inscrito" in conteudo.lower():
                        print(f"🎉 SUCESSO: Inscrição garantida na aula de {modalidade} às {HORARIO_TARGET}!")
                    else:
                        print(f"⚠️ Botão clicado para {modalidade}!")
                    aula_marcada = True
                else:
                    print(f"⏳ Aula de {modalidade} encontrada, mas o botão INSCREVER não está ativo.")

        if not aula_marcada:
            print(f"❌ Nenhuma aula das {HORARIO_TARGET} com inscrições abertas para o dia {dia_alvo}.")

        browser.close()

if __name__ == "__main__":
    executar_marcacao()
