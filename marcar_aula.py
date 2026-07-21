import os
import time
import datetime
from playwright.sync_api import sync_playwright

REGYBOX_URL = "https://www.regibox.pt/app/app_nova/login.php"
NOME_BOX = "Naval Box"

USERNAME = os.environ.get("REGYBOX_USER", "")
PASSWORD = os.environ.get("REGYBOX_PASS", "")

HORARIO_TARGET = "18:35"
AULAS_PRIORIDADE = ["HYROX", "HIROX", "CROSSFIT", "STRENGHT", "STRENGTH"]

def executar_marcacao():
    agora_utc = datetime.datetime.now(datetime.timezone.utc)
    agora_pt = agora_utc + datetime.timedelta(hours=1) 
    
    data_alvo = agora_pt + datetime.timedelta(days=3)
    dia_alvo = str(data_alvo.day)
    data_formatada_iso = data_alvo.strftime("%Y-%m-%d")

    print(f"[{agora_pt.strftime('%H:%M:%S')}] 🚀 A iniciar o robô de marcação...")
    print(f"📅 Data atual PT: {agora_pt.strftime('%d/%m/%Y')}")
    print(f"📅 Data alvo (+3 dias): {data_alvo.strftime('%d/%m/%Y')} (Procurando dia {dia_alvo})")
    print(f"⏰ Horário pretendido: {HORARIO_TARGET}")

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
                print("🗺️ A abrir calendário de aulas...")
                botao_aulas.click()
                page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Aviso navegação aulas: {e}")

        # Avançar dia / Mudar data no RegyBox
        print(f"📅 A selecionar o dia {dia_alvo} ({data_formatada_iso}) no calendário...")
        
        # Tenta disparar a função interna de carregar aulas do dia no RegyBox
        page.evaluate(f"""
            if (typeof carrega_aulas === 'function') {{
                carrega_aulas('{data_formatada_iso}');
            }} else if (typeof muda_dia === 'function') {{
                muda_dia('{data_formatada_iso}');
            }}
        """)
        page.wait_for_timeout(2000)

        # Tentar clicar no botão do dia ou na seta de avançar (se a função JS não existir)
        try:
            seletor_dia = page.locator(f"[onclick*='{data_formatada_iso}'], [data-date*='{data_formatada_iso}']").first
            if seletor_dia.is_visible(timeout=2000):
                seletor_dia.click(force=True)
                print(f"✅ Clique no elemento do dia {dia_alvo} executado!")
            else:
                # Se o dia não está visível, clica no botão '>' de avançar dia/semana
                seta_avancar = page.locator("i.fa-chevron-right, i.fa-angle-right, .next, [onclick*='proximo']").first
                if seta_avancar.is_visible(timeout=2000):
                    print("➡️ A clicar na seta para avançar o calendário...")
                    seta_avancar.click(force=True)
                    page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Nota navegação: {e}")

        page.wait_for_timeout(3000)

        # Fazer vários scrollings suaves para forçar o carregamento do feed de aulas (lazy loading)
        for i in range(3):
            page.evaluate("window.scrollBy(0, 400)")
            page.wait_for_timeout(500)

        aula_marcada = False

        # Procurar a aula por prioridade
        for modalidade in AULAS_PRIORIDADE:
            if aula_marcada:
                break

            print(f"🔎 A procurar no ecrã: {modalidade} às {HORARIO_TARGET}...")

            # Pesquisa flexível no DOM do RegyBox
            slots = page.locator("div, tr, li").filter(has_text=HORARIO_TARGET).filter(has_text=modalidade)

            if slots.count() > 0:
                slot = slots.first
                slot.scroll_into_view_if_needed()
                texto_slot = slot.inner_text().upper()

                print(f"💡 Encontrada aula de {modalidade} ({HORARIO_TARGET})!")

                if "CANCELAR" in texto_slot or "INSCRITO" in texto_slot:
                    print(f"🎉 JÁ ESTÁS INSCRITO em {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

                botao = slot.locator("button, a, input[type='button']").filter(has_text="INSCREVER").first

                if botao.is_visible():
                    print(f"🎯 Botão INSCREVER visível para {modalidade}! A clicar...")
                    botao.click(force=True)
                    page.wait_for_timeout(3000)

                    conteudo_pos = page.content().lower()
                    if "cancelar" in conteudo_pos or "inscrito" in conteudo_pos or "sucesso" in conteudo_pos:
                        print(f"🎉 SUCESSO CONFIRMADO: Inscrição efetuada em {modalidade} às {HORARIO_TARGET}!")
                    else:
                        print(f"⚠️ Clique efetuado no botão de {modalidade}. Verifica na app.")
                    aula_marcada = True
                    break
                else:
                    print(f"⏳ Aula de {modalidade} localizada, mas o botão INSCREVER ainda não está disponível/visível.")

        # Recurso de emergência se não encontrou pela prioridade
        if not aula_marcada:
            print(f"🔄 A tentar encontrar QUALQUER botão INSCREVER próximo das {HORARIO_TARGET}...")
            botoes_alvo = page.locator(f"xpath=//*[contains(text(), '{HORARIO_TARGET}')]/ancestor::div[contains(@class,'card') or contains(@class,'row') or contains(@class,'slot') or contains(@id,'slot') or position()<=3]//button[contains(., 'INSCREVER') or contains(., 'Inscrever')]")
            if botoes_alvo.count() > 0:
                print(f"🎯 Botão das {HORARIO_TARGET} localizado! A clicar...")
                botoes_alvo.first.click(force=True)
                page.wait_for_timeout(3000)
                print("🎉 Clique de recurso executado com sucesso!")
                aula_marcada = True

        if not aula_marcada:
            print(f"❌ Não foi possível realizar a inscrição para as {HORARIO_TARGET} no dia {dia_alvo}.")

        browser.close()

if __name__ == "__main__":
    executar_marcacao()
