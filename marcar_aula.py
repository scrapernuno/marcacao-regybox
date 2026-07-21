import os
import time
import datetime
from playwright.sync_api import sync_playwright

REGYBOX_URL = "https://www.regibox.pt/app/app_nova/login.php"
NOME_BOX = "Naval Box"

USERNAME = os.environ.get("REGYBOX_USER", "")
PASSWORD = os.environ.get("REGYBOX_PASS", "")

# HORÁRIOS DA AULA NO PAINEL (18:25)
HORARIOS_TARGET = ["18:25", "18:25 - 19:25", "18:35"]
AULAS_PRIORIDADE = ["CROSSFIT", "HYROX", "HIROX", "STRENGHT", "STRENGTH", "OPEN"]

def executar_marcacao():
    agora_utc = datetime.datetime.now(datetime.timezone.utc)
    agora_pt = agora_utc + datetime.timedelta(hours=1) 
    
    data_alvo = agora_pt + datetime.timedelta(days=3)
    dia_alvo = str(data_alvo.day)
    data_formatada_iso = data_alvo.strftime("%Y-%m-%d")

    print(f"[{agora_pt.strftime('%H:%M:%S')}] 🚀 A iniciar o robô de marcação...")
    print(f"📅 Data atual PT: {agora_pt.strftime('%d/%m/%Y')}")
    print(f"📅 Data alvo (+3 dias): {data_alvo.strftime('%d/%m/%Y')} (Dia {dia_alvo})")
    print(f"⏰ Horário da aula a procurar: {HORARIOS_TARGET[0]}")

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

        # 3. PASSO 1: Abrir Aulas
        print("MAPA PASSO 1: A acionar navegação para AULAS...")
        page.evaluate("""
            try {
                if (typeof load_script === 'function') load_script('../app_nova/php/aulas/marca_aulas.php');
                if (typeof calendario_aulas === 'function') calendario_aulas();
            } catch(e) {}
        """)
        page.wait_for_timeout(3000)

        # 4. PASSO 2: Selecionar o Dia no Calendário
        print(f"📅 PASSO 2: A selecionar o dia {dia_alvo} ({data_formatada_iso})...")
        page.evaluate(f"""
            try {{
                if (typeof carrega_aulas === 'function') carrega_aulas('{data_formatada_iso}');
                if (typeof muda_dia === 'function') muda_dia('{data_formatada_iso}');
            }} catch(e) {{}}
        """)
        page.wait_for_timeout(2500)

        # Clique visual no dia no calendário
        try:
            dia_elem = page.locator(f"//span[text()='{dia_alvo}'] | //td[not(contains(@class,'disabled'))]//span[text()='{dia_alvo}']").first
            if dia_elem.is_visible(timeout=2000):
                dia_elem.click(force=True)
                print(f"✅ Clique no dia {dia_alvo} realizado!")
        except Exception:
            pass

        page.wait_for_timeout(2000)
        page.screenshot(path="ecra_regybox.png", full_page=True)

        # 5. PASSO 3: Procurar a aula (18:25) e Clicar em INSCREVER
        print("🔎 PASSO 3: A procurar a aula das 18:25 no painel...")
        aula_marcada = False

        for hora in HORARIOS_TARGET:
            if aula_marcada:
                break
            for modalidade in AULAS_PRIORIDADE:
                bloco_aula = page.locator("div, tr, li").filter(has_text=hora).filter(has_text=modalidade)

                if bloco_aula.count() > 0:
                    card = bloco_aula.first
                    card.scroll_into_view_if_needed()
                    
                    texto = card.inner_text().upper()
                    if "CANCELAR" in texto or "INSCRITO" in texto:
                        print(f"🎉 JÁ ESTÁS INSCRITO em {modalidade} ({hora})!")
                        aula_marcada = True
                        break

                    btn = card.locator("button, a, div, span").filter(has_text="INSCREVER").first
                    if btn.is_visible():
                        print(f"🎯 Botão INSCREVER encontrado para {modalidade} às {hora}! A clicar...")
                        btn.click(force=True)
                        page.wait_for_timeout(3000)
                        print(f"🎉 SUCESSO: Inscrição efetuada em {modalidade} às {hora}!")
                        aula_marcada = True
                        break

        # Backup: Qualquer botão INSCREVER que esteja na linha/bloco das 18:25
        if not aula_marcada:
            print("🔄 A procurar qualquer botão INSCREVER perto das 18:25...")
            btn_generico = page.locator("xpath=//*[contains(text(), '18:25')]/ancestor::*[position()<=4]//button[contains(., 'INSCREVER')] | //*[contains(text(), '18:25')]/ancestor::*[position()<=4]//*[contains(text(), 'INSCREVER')]").first

            if btn_generico.is_visible():
                btn_generico.scroll_into_view_if_needed()
                print("🎯 Botão INSCREVER encontrado! A clicar...")
                btn_generico.click(force=True)
                page.wait_for_timeout(3000)
                print("🎉 Inscrição efetuada com sucesso!")
                aula_marcada = True

        if not aula_marcada:
            print(f"❌ Não foi possível encontrar ou clicar no botão INSCREVER para as 18:25 no dia {dia_alvo}.")

        browser.close()

if __name__ == "__main__":
    executar_marcacao()
