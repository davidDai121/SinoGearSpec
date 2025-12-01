import sys
import time
from playwright.sync_api import sync_playwright

def scrape(url):
    try:
        with sync_playwright() as p:
            # 1. 启动参数
            browser = p.chromium.launch(
                headless=True, 
                args=['--disable-blink-features=AutomationControlled']
            )
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            page = context.new_page()
            
            # 2. 访问网页
            # print(f"DEBUG: Navigating to {url}...", file=sys.stderr)
            page.goto(url, timeout=90000)

            # === V6.7 核心升级：等待网络空闲 ===
            # 这行代码会等待页面所有的 API 数据包都请求完毕才继续
            # 是解决“网页只有骨架没有数据”的神器
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except:
                pass # 如果超时也不要在意，继续往下走

            # 3. 智能等待元素
            try:
                page.wait_for_selector(".param-table", state="attached", timeout=15000)
            except:
                pass
            
            # 4. 增强滚动 (触发懒加载)
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(1000)
            
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            
            content = page.content()
            browser.close()
            
            # 5. 输出
            sys.stdout.reconfigure(encoding='utf-8')
            print(content)
            
    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
        scrape(target_url)
    else:
        print("ERROR: No URL provided")