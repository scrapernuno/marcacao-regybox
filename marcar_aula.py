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
    print(f"📅 Data alvo (+3 dias): {data_alvo.strftime('%d/%m/%Y')} (Dia {dia_alvo})")
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

        # 1. Selecionar Box
        try:
            campo_pesquisa = page.locator("input[placeholder*='Procura'], input[placeholder*='box'], input[type='text']").first
            if campo_pesquisa.is_visible(timeout=4000):
                print(f"🔍 A selecionar a Box: {NOME_BOX}...")
                campo_pesquisa.fill(NOME_BOX)
                page.wait_for_timeout(1000)
                item_box = page.locator(f"text='{NOME_BOX}'").first
                if item_box.is_visible(timeout=3000):
                    item_box.click()
                    page.wait_for_timeout(1000)
        except Exception as e:
            print(f"Nota box: {e}")

        # 2. Login
        print("🔑 A preencher dados de acesso...")
        page.locator("input[type='email'], input[placeholder*='e-mail'], input[name*='user']").first.fill(USERNAME)
        page.locator("input[type='password'], input[placeholder*='password'], input[name*='pass']").first.fill(PASSWORD)
        
        print("🚀 A efetuar Login...")
        try:
            page.locator("button:has-text('LOGIN'), input[value='LOGIN'], input[type='submit']").first.click(timeout=3000)
        except Exception:
            page.keyboard.press("Enter")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)

        # 3. PASSO 1 DA FOTO: Clicar no texto azul "AULAS"
        print("🗺️ PASSO 1: A clicar no texto 'AULAS'...")
        try:
            # Seleciona exatamente o elemento 'AULAS' azul que está por cima do painel
            link_aulas = page.locator("text='AULAS'").first
            link_aulas.click(force=True)
            print("✅ Clicado em AULAS com sucesso!")
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Erro ao clicar em AULAS, tentando por JavaScript: {e}")
            page.evaluate("if(typeof calendario_aulas === 'function') calendario_aulas();")
            page.wait_for_timeout(3000)

        # 4. PASSO 2 DA FOTO: Selecionar o dia do mês no calendário à esquerda
        print(f"📅 PASSO 2: A clicar no dia {dia_alvo} no calendário mensal...")
        dia_clicado = False

        # Tentar clicar no número do dia exatamente como aparece na grelha da Imagem 2
        try:
            # Procura o número do dia isolado no calendário
            seletor_numero_dia = page.locator(f"xpath=//div[contains(@class,'calendar') or contains(@class,'month') or contains(@class,'day')]//*[text()='{dia_alvo}'] | //td//*[text()='{dia_alvo}'] | //span[text()='{dia_alvo}']").first
            if seletor_numero_dia.is_visible(timeout=3000):
                seletor_numero_dia.click(force=True)
                print(f"✅ Dia {dia_alvo} clicado no calendário!")
                dia_clicado = True
        except Exception as e:
            print(f"Nota clique no dia: {e}")

        # Se o clique visual falhar, executa a função de mudança de dia via JS
        if not dia_clicado:
            print("🔄 A acionar atualização da data via instrução interna...")
            page.evaluate(f"""
                try {{
                    if (typeof carrega_aulas === 'function') carrega_aulas('{data_formatada_iso}');
                    if (typeof muda_dia === 'function') muda_dia('{data_formatada_iso}');
                }} catch(e) {{}}
            """)

        page.wait_for_timeout(2500)

        # Guardar screenshot de validação
        page.screenshot(path="ecra_regybox.png", full_page=True)

        # 5. PASSO 3 DA FOTO: Fazer scroll e encontrar o botão verde INSCREVER
        print(f"🔎 PASSO 3: A procurar a aula das {HORARIO_TARGET} no painel da direita...")
        
        aula_marcada = False

        # Tentativa 1: Procurar pelas modalidades prioritárias
        for modalidade in AULAS_PRIORIDADE:
            if aula_marcada:
                break

            # Localiza o cartão/bloco da aula que contém a hora pretendida
            cards = page.locator("div, tr, li").filter(has_text=HORARIO_TARGET).filter(has_text=modalidade)

            if cards.count() > 0:
                card = cards.first
                card.scroll_into_view_if_needed()
                page.wait_for_timeout(500)

                # Procura o botão verde INSCREVER dentro do cartão
                botao_inscrever = card.locator("button, a, div").filter(has_text="INSCREVER").first

                if botao_inscrever.is_visible():
                    print(f"🎯 Encontrado botão INSCREVER para {modalidade} ({HORARIO_TARGET})! A clicar...")
                    botao_inscrever.click(force=True)
                    page.wait_for_timeout(3000)
                    print(f"🎉 SUCESSO: Inscrição efetuada em {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

        # Tentativa 2 (Recurso): Procurar QUALQUER aula que tenha as 18:35 e o botão INSCREVER
        if not aula_marcada:
            print(f"🔄 A procurar qualquer botão INSCREVER correspondente às {HORARIO_TARGET}...")
            # XPath direto para apanhar o botão verde INSCREVER do bloco do horário pretendido
            botao_generico = page.locator(f"xpath=//*[contains(text(), '{HORARIO_TARGET}')]/ancestor::*[contains(@class,'card') or contains(@class,'box') or position()<=4]//button[contains(., 'INSCREVER')] | //*[contains(text(), '{HORARIO_TARGET}')]/ancestor::*[contains(@class,'card') or contains(@class,'box') or position()<=4]//*[contains(@class,'btn') or contains(text(), 'INSCREVER')]").first

            if botao_generico.is_visible():
                botao_generico.scroll_into_view_if_needed()
                print("🎯 Botão INSCREVER genérico encontrado! A clicar...")
                botao_generico.click(force=True)
                page.wait_for_timeout(3000)
                print("🎉 Inscrição efetuada com sucesso!")
                aula_marcada = True

        if not aula_marcada:
            print(f"❌ Não foi possível encontrar ou clicar no botão INSCREVER para as {HORARIO_TARGET} no dia {dia_alvo}.")

        browser.close()

if __name__ == "__main__":
    executar_marcacao()
