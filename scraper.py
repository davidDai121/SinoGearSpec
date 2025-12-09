import sys
import json
import time
from playwright.sync_api import sync_playwright
def scrape(url):
    # 核心修复: 必须在任何打印语句或 API 监听之前设置 stdout 的编码
    sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    
    api_data = None
    
    def handle_response(response):
        nonlocal api_data
        # 监听易车配置接口
        if "config/getconfig" in response.url and response.status == 200:
            try:
                data = response.json()
                if data and "data" in data and "carList" in data["data"]:
                    api_data = data
            except:
                pass

    try:
        with sync_playwright() as p:
            # 启动浏览器 (Headless=True 效率更高)
            browser = p.chromium.launch(
                headless=True, 
                args=['--disable-blink-features=AutomationControlled']
            )
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            page = context.new_page()
            page.on("response", handle_response)
            
            page.goto(url, timeout=60000)
            
            # 滚动并等待数据加载
            try:
                page.wait_for_selector(".param-table", state="attached", timeout=15000)
            except: pass
            
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(1000)
                if api_data: break
            
            # 如果没抓到 API，最后尝试等待 3 秒
            if not api_data:
                page.wait_for_timeout(3000)
            
            content = page.content()
            browser.close()
            
            # --- 输出 ---
            if api_data:
                print("JSON_START")
                print(json.dumps(api_data, ensure_ascii=False))
            else:
                print("HTML_START")
                print(content)
            
    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
        scrape(target_url)
    else:
        print("ERROR: No URL provided")