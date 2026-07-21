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
    # Garantir cálculo exato da data alvo no fuso de Portugal
    # Se UTC for diferente, ajustamos manualmente +3 dias a contar do dia atual local
    agora_utc = datetime.datetime.now(datetime.timezone.utc)
    agora_pt = agora_utc + datetime.timedelta(hours=1) # WEST (UTC+1)
    
    data_alvo = agora_pt + datetime.timedelta(days=3)
    dia_alvo = str(data_alvo.day)

    print(f"[{agora_pt.strftime('%H:%M:%S')}] 🚀 A iniciar o robô de marcação...")
    print(f"📅 Data atual PT: {agora_pt.strftime('%d/%m/%Y')}")
    print(f"📅 Data alvo (+3 dias): {data_alvo.strftime('%d/%m/%Y')} (Procurando dia {dia_alvo})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
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
                print("MAPA: A abrir calendário de aulas...")
                botao_aulas.click()
                page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Aviso navegação aulas: {e}")

        # Clicar no dia (+3 dias)
        print(f"📅 A tentar selecionar o dia {dia_alvo} no calendário...")
        try:
            # Procura o dia no calendário da aplicação
            seletor_dia = page.locator(f"xpath=//td[not(contains(@class,'disabled'))]//span[text()='{dia_alvo}'] | //div[contains(@class,'day')]//text()[normalize-space()='{dia_alvo}']/parent::*").first
            if seletor_dia.is_visible():
                seletor_dia.click(force=True)
                print(f"✅ Clique executado no dia {dia_alvo}!")
                page.wait_for_timeout(3000)
            else:
                print(f"⚠️ Dia {dia_alvo} não estava diretamente visível/clicável no calendário.")
        except Exception as e:
            print(f"⚠️ Erro ao clicar no dia: {e}")

        # Scroll para garantir que a tarde é carregada
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)

        aula_marcada = False

        # Tenta localizar a aula por prioridade
        for modalidade in AULAS_PRIORIDADE:
            if aula_marcada:
                break

            print(f"🔎 A procurar no ecrã: {modalidade} às {HORARIO_TARGET}...")

            # Procura por qualquer bloco que tenha o id feed_time_slot ou contenha o texto
            slots = page.locator("div[id*='feed_time_slot'], div.card2, div[class*='row']").filter(has_text=HORARIO_TARGET).filter(has_text=modalidade)

            if slots.count() > 0:
                slot = slots.first
                slot.scroll_into_view_if_needed()
                texto_slot = slot.inner_text().upper()

                print(f"💡 Encontrada aula de {modalidade}! Conteúdo do card:")
                print(f"--- {texto_slot.replace(chr(10), ' ')} ---")

                if "CANCELAR" in texto_slot or "INSCRITO" in texto_slot:
                    print(f"🎉 JÁ ESTÁS INSCRITO em {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

                botao = slot.locator("button[onclick*='marca_aulas.php'], button.buts_inscrever, button:has-text('INSCREVER')").first

                if botao.is_visible():
                    print(f"🎯 Botão INSCREVER visível para {modalidade}! A clicar...")
                    botao.click(force=True)
                    page.wait_for_timeout(3000)

                    conteudo_pos = page.content().lower()
                    if "cancelar" in conteudo_pos or "inscrito" in conteudo_pos or "sucesso" in conteudo_pos:
                        print(f"🎉 SUCESSO CONFIRMADO: Inscrição efetuada em {modalidade} às {HORARIO_TARGET}!")
                    else:
                        print(f"⚠️ Clique efetuado no botão de {modalidade}. Verifique no RegyBox.")
                    aula_marcada = True
                    break
                else:
                    print(f"⏳ Aula de {modalidade} localizada, mas o botão INSCREVER não está visível no card.")

        # Recurso genérico se não encontrou pela prioridade
        if not aula_marcada:
            print("🔄 A tentar encontrar QUALQUER botão INSCREVER próximo das 18:25...")
            botoes_1825 = page.locator(f"xpath=//div[contains(., '{HORARIO_TARGET}')]//button[contains(., 'INSCREVER') or contains(@class, 'buts_inscrever')]")
            if botoes_1825.count() > 0:
                print("🎯 Botão genérico das 18:25 localizado! A clicar...")
                botoes_1825.first.click(force=True)
                page.wait_for_timeout(3000)
                print("🎉 Clique de recurso executado com sucesso!")
                aula_marcada = True

        if not aula_marcada:
            print(f"❌ Não foi possível realizar a inscrição para as {HORARIO_TARGET}.")

        browser.close()

if __name__ == "__main__":
    executar_marcacao()
