import os
import time
import datetime
from playwright.sync_api import sync_playwright

REGYBOX_URL = "https://www.regibox.pt/app/app_nova/login.php"
AULAS_DIRECT_URL = "https://www.regibox.pt/app/app_nova/index.php?option=aulas"
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
            if campo_pesquisa.is_visible(timeout=3000):
                print(f"🔍 A selecionar a Box: {NOME_BOX}...")
                campo_pesquisa.fill(NOME_BOX)
                page.wait_for_timeout(1000)
                item_box = page.locator(f"text='{NOME_BOX}'").first
                if item_box.is_visible(timeout=2000):
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
        page.wait_for_timeout(3000)

        # 3. PASSO 1: Abrir diretamente a vista de Aulas / Calendário
        print("MAPA PASSO 1: A acionar navegação para AULAS...")
        
        # Tenta primeiro acionar as funções JavaScript nativas da app
        navegou = False
        try:
            page.evaluate("""
                if (typeof load_script === 'function') {
                    load_script('../app_nova/php/aulas/marca_aulas.php');
                } else if (typeof calendario_aulas === 'function') {
                    calendario_aulas();
                }
            """)
            page.wait_for_timeout(2000)
            navegou = True
        except Exception:
            pass

        # Se falhar, clica com força em qualquer elemento contendo AULAS ou Ícone de Calendário
        if not navegou or page.locator("text='AULAS'").count() > 0:
            try:
                elem = page.locator("div:has-text('AULAS'), .card2, [onclick*='aulas']").first
                elem.click(force=True, timeout=3000)
            except Exception:
                pass

        page.wait_for_timeout(3000)

        # 4. PASSO 2: Selecionar o dia alvo no calendário
        print(f"📅 PASSO 2: A selecionar o dia {dia_alvo} ({data_formatada_iso})...")
        
        # Executa diretamente o carregamento do dia no JS do RegyBox
        page.evaluate(f"""
            try {{
                if (typeof carrega_aulas === 'function') carrega_aulas('{data_formatada_iso}');
                if (typeof muda_dia === 'function') muda_dia('{data_formatada_iso}');
                if (typeof load_script === 'function') load_script('../app_nova/php/aulas/marca_aulas.php?data={data_formatada_iso}');
            }} catch(e) {{}}
        """)
        
        page.wait_for_timeout(2000)

        # Clique de segurança no número do dia se estiver visível no ecrã
        try:
            dia_elem = page.locator(f"//span[text()='{dia_alvo}'] | //td[not(contains(@class,'disabled'))]//span[text()='{dia_alvo}']").first
            if dia_elem.is_visible(timeout=2000):
                dia_elem.click(force=True)
                print(f"✅ Clique no dia {dia_alvo} realizado!")
        except Exception:
            pass

        page.wait_for_timeout(2000)

        # Tira screenshot do estado atual do ecrã para verificação
        page.screenshot(path="ecra_regybox.png", full_page=True)

        # 5. PASSO 3: Localizar a aula e Clicar em INSCREVER
        print(f"🔎 PASSO 3: A procurar a aula das {HORARIO_TARGET} no painel...")
        aula_marcada = False

        # Busca prioritária por modalidade
        for modalidade in AULAS_PRIORIDADE:
            if aula_marcada:
                break

            bloco_aula = page.locator("div, tr, li").filter(has_text=HORARIO_TARGET).filter(has_text=modalidade)

            if bloco_aula.count() > 0:
                card = bloco_aula.first
                card.scroll_into_view_if_needed()
                
                texto = card.inner_text().upper()
                if "CANCELAR" in texto or "INSCRITO" in texto:
                    print(f"🎉 JÁ ESTÁS INSCRITO em {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

                btn = card.locator("button, a, div, span").filter(has_text="INSCREVER").first
                if btn.is_visible():
                    print(f"🎯 Botão INSCREVER encontrado para {modalidade}! A clicar...")
                    btn.click(force=True)
                    page.wait_for_timeout(3000)
                    print(f"🎉 SUCESSO: Inscrição efetuada em {modalidade} às {HORARIO_TARGET}!")
                    aula_marcada = True
                    break

        # Busca genérica de recurso
        if not aula_marcada:
            print(f"🔄 A procurar qualquer botão INSCREVER para as {HORARIO_TARGET}...")
            btn_generico = page.locator(f"xpath=//*[contains(text(), '{HORARIO_TARGET}')]/ancestor::*[position()<=4]//button[contains(., 'INSCREVER')] | //*[contains(text(), '{HORARIO_TARGET}')]/ancestor::*[position()<=4]//*[contains(text(), 'INSCREVER')]").first

            if btn_generico.is_visible():
                btn_generico.scroll_into_view_if_needed()
                print("🎯 Botão INSCREVER encontrado! A clicar...")
                btn_generico.click(force=True)
                page.wait_for_timeout(3000)
                print("🎉 Inscrição efetuada com sucesso!")
                aula_marcada = True

        if not aula_marcada:
            print(f"❌ Não foi possível encontrar ou clicar no botão INSCREVER para as {HORARIO_TARGET} no dia {dia_alvo}.")

        browser.close()

if __name__ == "__main__":
    executar_marcacao()
