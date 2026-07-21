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

    if not USERNAME or not PASSWORD:
        print("❌ ERRO CRÍTICO: As credenciais REGYBOX_USER ou REGYBOX_PASS não estão configuradas nas Secrets!")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        print("🔐 A abrir página de login...")
        page.goto(REGYBOX_URL, wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Passo 1: Selecionar a Box
        try:
            campo_pesquisa = page.locator("input[placeholder*='Procura'], input[placeholder*='box'], input[type='text']").first
            if campo_pesquisa.is_visible(timeout=5000):
                print(f"🔍 A selecionar a Box: {NOME_BOX}...")
                campo_pesquisa.fill(NOME_BOX)
                page.wait_for_timeout(1000)
                item_box = page.locator(f"text='{NOME_BOX}'").first
                if item_box.is_visible(timeout=3000):
                    item_box.click()
                    page.wait_for_timeout(1500)
        except Exception as e:
            print(f"Nota na seleção da box: {e}")

        # Passo 2: Preencher E-mail e Password
        print("🔑 A preencher dados de acesso...")
        campo_email = page.locator("input[type='email'], input[placeholder*='e-mail'], input[name*='user']").first
        campo_email.fill(USERNAME)
        
        campo_pass = page.locator("input[type='password'], input[placeholder*='password'], input[name*='pass']").first
        campo_pass.fill(PASSWORD)
        
        print("🚀 A efetuar Login...")
        try:
            page.locator("button:has-text('LOGIN'), input[value='LOGIN'], input[type='submit']").first.click(timeout=3000)
        except Exception:
            campo_pass.press("Enter")

        # Aguarda que a página pós-login carregue devidamente
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)

        # Passo 3: Navegar para AULAS/Calendário se disponível
        try:
            botao_aulas = page.locator("a[onclick*='calendario_aulas'], [id*='aulas']").first
            if botao_aulas.is_visible(timeout=3000):
                print("🗺️ A abrir calendário de aulas...")
                botao_aulas.click()
                page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Aviso navegação aulas: {e}")

        # Passo 4: Mudar para o dia alvo
        print(f"📅 A selecionar o dia {dia_alvo} ({data_formatada_iso}) no calendário...")
        
        # Tenta a navegação visual primeiro (clique no elemento da data no carrossel/calendário)
        mudou_dia_com_sucesso = False
        try:
            seletor_dia = page.locator(f"[onclick*='{data_formatada_iso}'], [data-date*='{data_formatada_iso}'], text='{dia_alvo}'").first
            if seletor_dia.is_visible(timeout=3000):
                seletor_dia.click(force=True)
                print(f"✅ Clique no dia {dia_alvo} executado via DOM!")
                mudou_dia_com_sucesso = True
        except Exception:
            pass

        # Se o clique visual falhar, executa a função JS tratada com try/catch
        if not mudou_dia_com_sucesso:
            print("🔄 A tentar alternar dia via instrução JavaScript...")
            page.evaluate(f"""
                try {{
                    if (typeof carrega_aulas === 'function') {{
                        carrega_aulas('{data_formatada_iso}');
                    }} else if (typeof muda_dia === 'function') {{
                        muda_dia('{data_formatada_iso}');
                    }}
                }} catch(e) {{
                    console.log('Erro ao mudar dia via JS:', e);
                }}
            """)

        page.wait_for_timeout(4000)

        # Rolamento para carregar os elementos
        for i in range(3):
            page.evaluate("window.scrollBy(0, 400)")
            page.wait_for_timeout(500)

        aula_marcada = False

        # Passo 5: Procurar e marcar a aula
        for modalidade in AULAS_PRIORIDADE:
            if aula_marcada:
                break

            print(f"🔎 A procurar no ecrã: {modalidade} às {HORARIO_TARGET}...")

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
                    print(f"⏳ Aula de {modalidade} localizada, mas o botão INSCREVER ainda não está disponível.")

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
