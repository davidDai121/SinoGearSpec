import streamlit as st
import json
import re
import subprocess
import sys
import math
import time
import os
import ast 
from bs4 import BeautifulSoup
import google.generativeai as genai
from jinja2 import Template

# ==========================================
# 🔑 API Key (已内置)
# ==========================================
HARDCODED_API_KEY = "AIzaSyDXSWRCoruhCl4_sNlywD7n-aCGiE66NNk"

st.set_page_config(page_title="Auto Spec Generator V7.2", page_icon="🚗", layout="wide")

if 'step' not in st.session_state: st.session_state.step = 1
if 'raw_data' not in st.session_state: st.session_state.raw_data = None
if 'processed_data' not in st.session_state: st.session_state.processed_data = None

class SpecLogic:
    def __init__(self, proxy_url=None):
        if proxy_url:
            os.environ['http_proxy'] = proxy_url
            os.environ['https_proxy'] = proxy_url
        genai.configure(api_key=HARDCODED_API_KEY)
        self.model = genai.GenerativeModel("models/gemini-2.0-flash-lite-preview-02-05")

    def fetch_url(self, url):
        command = [sys.executable, "scraper.py", url]
        for attempt in range(2): 
            try:
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=False, timeout=100)
                output = result.stdout.strip()
                if output.startswith("ERROR:"): raise Exception(output)
                if not output: raise Exception("抓取结果为空")
                return output
            except Exception as e:
                if attempt == 1: raise e
                time.sleep(2)

    def parse_html(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        car_models = []
        seen_names = set()
        
        car_boxes = soup.select(".selected-car-box")
        if car_boxes:
            for box in car_boxes:
                if 'style' in box.attrs and 'none' in box.attrs['style']: continue
                name_node = box.select_one(".car-style-info") or box.select_one(".car-name")
                price_node = box.select_one(".car-price")
                if name_node:
                    raw_name = name_node.get("title") or name_node.get_text(strip=True)
                    clean_name = re.sub(r'\d+(\.\d+)?(万|元).*', '', raw_name).strip()
                    if not clean_name: continue
                    price = ""
                    if price_node: price = price_node.get_text(strip=True).replace("万", "w")
                    unique_id = f"{clean_name}_{price}"
                    if unique_id in seen_names: continue
                    seen_names.add(unique_id)
                    full_name = f"{clean_name} [{price}]" if price else clean_name
                    car_models.append(full_name)
        else:
            header_nodes = soup.select(".car-style-info")
            if not header_nodes: header_nodes = soup.select(".car-name")
            for node in header_nodes:
                raw_name = node.get("title") or node.get_text(strip=True)
                if not raw_name or len(raw_name) > 80: continue
                clean_name = re.sub(r'\d+(\.\d+)?(万|元).*', '', raw_name).strip()
                if clean_name and clean_name not in seen_names:
                    seen_names.add(clean_name)
                    car_models.append(clean_name)
        
        if len(car_models) > 7: car_models = car_models[:7]

        specs = []
        rows = soup.find_all("tr")
        current_section = "Basic Info"
        
        for row in rows:
            if "param-carInfo" in row.get("class", []) or row.find("h3"):
                text = row.get_text(strip=True)
                if text: current_section = text
                continue

            cells = row.find_all(["td", "th"])
            if not cells: continue
            label = cells[0].get_text(strip=True)
            
            forbidden = ["补贴", "成本", "费用", "购车", "税"]
            if any(k in label for k in forbidden): continue
            
            temp_vals = []
            data_cells = cells[1:]
            for i, cell in enumerate(data_cells):
                if i >= len(car_models): break 
                raw_text = cell.get_text(strip=True)
                val = raw_text
                if "●" in raw_text:
                    text_content = raw_text.replace("●", "").strip()
                    val = text_content if text_content else "●"
                elif "class=\"icon-ok\"" in str(cell) and not val: val = "●"
                elif not val: val = "-"
                elif "○" in raw_text:
                     text_content = raw_text.replace("○", "").strip()
                     val = f"○ {text_content}" if text_content else "○"

                val = val.replace("万", "w").replace("元", "")
                val = re.sub(r'\(暂无\)', '', val)
                if "选配" in val and "Optional" not in val: val = val.replace("选配", "Optional")
                temp_vals.append(val)

            if len(temp_vals) > 0:
                specs.append({"section": current_section, "label": label, "row_values": temp_vals})
        return {"models": car_models, "specs": specs}

    def clean_json(self, text):
        # 简单的预处理，因为这次我们强制 JSON 模式了
        text = text.replace("```json", "").replace("```", "").strip()
        try: return json.loads(text)
        except: pass
        try: return ast.literal_eval(text)
        except: return None

    def has_chinese(self, text):
        if not isinstance(text, str): return False
        return bool(re.search(r'[\u4e00-\u9fa5]', text))

    def chunk_has_chinese(self, chunk, is_models=False):
        if is_models: return any(self.has_chinese(m) for m in chunk)
        for row in chunk:
            if self.has_chinese(row['section']): return True
            if self.has_chinese(row['label']): return True
            for v in row['row_values']:
                if self.has_chinese(v): return True
        return False

    def translate_api(self, data_chunk, is_models=False, aggressive=False, log_container=None):
        tone = "Translate ALL Chinese to English." if not aggressive else "CRITICAL: TRANSLATE EVERY CHINESE CHARACTER. NO CHINESE ALLOWED."
        
        if is_models:
            prompt = f"""Task: Translate Chinese car models to English. Example: "26款 两驱版" -> "2026 RWD". Input: {json.dumps(data_chunk, ensure_ascii=False)} Output: JSON list of strings."""
        else:
            prompt = f"""Task: Translate car specs to English.
            RULES:
            1. Output STRICT JSON.
            2. Keep structure (section, label, row_values).
            3. TRANSLATE values in 'row_values' (e.g. "双温区" -> "Dual-zone").
            4. Keep symbols "●", "○", "-".
            {tone}
            Input: {json.dumps(data_chunk, ensure_ascii=False)}"""
        
        for attempt in range(3):
            try:
                # ============================================================
                # 🔥 V7.2 核心：启用 response_mime_type="application/json"
                # 这会强制模型只返回合法的 JSON，不再废话，不再出错！
                # ============================================================
                res = self.model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                
                ret = self.clean_json(res.text)
                if ret and len(ret) == len(data_chunk): return ret
                
                if log_container:
                    log_container.warning(f"⚠️ 尝试 {attempt+1} 解析失败。AI 返回: {res.text[:200]}")
                time.sleep(3)
            except Exception as e:
                if log_container: log_container.error(f"API Error: {e}")
                time.sleep(3)
        
        # 如果 3 次都失败，把原始内容打出来看看
        if log_container:
            log_container.error("❌ 该块翻译彻底失败，返回原文。")
            
        return data_chunk

    def incremental_translate(self, data, status_func, log_container):
        if self.chunk_has_chinese(data['models'], is_models=True):
            status_func("🤖 正在翻译车型名称...")
            data['models'] = self.translate_api(data['models'], is_models=True, log_container=log_container)
            time.sleep(2)
        
        all_specs = data['specs']
        translated_specs = []
        CHUNK_SIZE = 40 # 使用 Lite + JSON模式，40行非常稳
        total = math.ceil(len(all_specs) / CHUNK_SIZE)

        for i in range(total):
            chunk = all_specs[i*CHUNK_SIZE : (i+1)*CHUNK_SIZE]
            if self.chunk_has_chinese(chunk, is_models=False):
                status_func(f"🤖 翻译中: 第 {i+1}/{total} 块...")
                new_chunk = self.translate_api(chunk, is_models=False, log_container=log_container)
                
                if self.chunk_has_chinese(new_chunk, is_models=False):
                    # 如果强制 JSON 模式还是有中文，那真是见了鬼了，再试一次强力的
                    with log_container: st.warning(f"⚠️ 第 {i+1} 块仍有中文，强力重译...")
                    time.sleep(2)
                    new_chunk = self.translate_api(chunk, is_models=False, aggressive=True, log_container=log_container)
                
                translated_specs.extend(new_chunk)
                time.sleep(4) 
            else:
                translated_specs.extend(chunk)
                time.sleep(0.1)

        data['specs'] = translated_specs
        return data

    def render_html(self, data):
        clean_models = []
        for m in data['models']:
            clean_name = re.sub(r'\s*\[.*?\]', '', m)
            clean_models.append(clean_name)
        
        display_data = data.copy()
        display_data['models'] = clean_models
        
        filtered_specs = []
        for row in display_data['specs']:
            label_lower = row['label'].lower()
            if "msrp" in label_lower or "指导价" in label_lower or "price" in label_lower: continue
            try:
                unique_values = set(row['row_values'])
                row['is_diff'] = len(unique_values) > 1
            except: row['is_diff'] = False
            filtered_specs.append(row)
        
        display_data['specs'] = filtered_specs

        template = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
    body { font-family: 'Segoe UI', Roboto, sans-serif; background-color: #fff; margin: 0; padding: 20px; color: #333; font-size: 12px; }
    .container { max-width: 100%; margin: 0 auto; border-top: 5px solid #00D26A; box-shadow: 0 5px 15px rgba(0,0,0,0.08); }
    .header { background: #111; padding: 20px; color: #fff; display: flex; justify-content: space-between; align-items: center; }
    .brand { font-size: 24px; font-weight: 900; letter-spacing: 2px; }
    .table-wrapper { overflow-x: auto; width: 100%; }
    table { width: 100%; border-collapse: collapse; min-width: 1500px; }
    th, td { padding: 10px; border: 1px solid #eee; text-align: center; vertical-align: middle; }
    .label-col { position: sticky; left: 0; background-color: #f9f9f9; width: 200px; text-align: left; font-weight: 600; z-index: 10; border-right: 2px solid #ddd; padding-left:15px;}
    .model-header { background-color: #e8f5e9; color: #000; font-weight: 700; height: 60px; position: sticky; top: 0; z-index: 20; border-bottom: 2px solid #00D26A; }
    .section-row td { background-color: #222; color: #fff; text-align: left; font-weight: 700; text-transform: uppercase; padding: 8px 15px; }
    .diff { background-color: #f0fdf4 !important; }
    .diff .label-col { background-color: #f0fdf4 !important; color: #006633; border-right: 2px solid #00D26A; }
    .dot { color: #00D26A; font-weight: 900; }
    .opt { color: #f39c12; font-weight: 900; }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="brand">SINO GEAR</div>
        <div style="font-size:10px; color:#ccc;">FULL CONFIGURATION MATRIX</div>
    </div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th class="label-col" style="background:#333; color:#fff;">Parameter</th>
                    {% for model in data.models %}
                    <th class="model-header">{{ model }}</th>
                    {% endfor %}
                </tr>
            </thead>
            <tbody>
                {% set ns = namespace(current_sec = "") %}
                {% for row in data.specs %}
                    {% if row.section != ns.current_sec %}
                        <tr class="section-row"><td colspan="{{ data.models|length + 1 }}">{{ row.section }}</td></tr>
                        {% set ns.current_sec = row.section %}
                    {% endif %}
                    <tr class="{{ 'diff' if row.is_diff else '' }}">
                        <td class="label-col">{{ row.label }}</td>
                        {% for val in row['row_values'] %}
                        <td>
                            {% if val == "●" %}<span class="dot">●</span>
                            {% elif val == "○" %}<span class="opt">○</span>
                            {% elif "●" in val %}<span class="dot">●</span> {{ val|replace("●","") }}
                            {% elif "○" in val %}<span class="opt">○</span> {{ val|replace("○","") }}
                            {% else %}{{ val }}
                            {% endif %}
                        </td>
                        {% endfor %}
                    </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
</body>
</html>
        """
        return Template(template).render(data=display_data)

# ================= UI =================
with st.sidebar:
    st.header("⚙️ 设置")
    st.success("API Key 已内置")
    proxy = st.text_input("网络代理", placeholder="留空即可")
    if st.button("🔄 重置所有步骤"):
        st.session_state.step = 1
        st.session_state.raw_data = None
        st.rerun()

st.title("🚙 汽车配置表生成器 (V7.2 JSON强制版)")

if st.session_state.step == 1:
    url_input = st.text_input("🔗 易车网址", placeholder="https://car.yiche.com/jietulvxingzhecdm/peizhi/")
    
    if st.button("🚀 抓取数据", type="primary"):
        if not url_input: st.error("请输入网址")
        else:
            with st.spinner("🕷️ 正在抓取数据..."):
                try:
                    tool = SpecLogic(proxy)
                    html = tool.fetch_url(url_input)
                    st.session_state.raw_data = tool.parse_html(html)
                    if not st.session_state.raw_data['models']:
                        st.error("未识别到数据。")
                    else:
                        st.session_state.step = 2
                        st.rerun()
                except Exception as e:
                    st.error(f"错误: {e}")

elif st.session_state.step == 2:
    st.subheader("🛠️ 车型选择 (含指导价预览)")
    raw = st.session_state.raw_data
    all_models = raw['models']
    
    selected_models = st.multiselect("请选择:", all_models, default=all_models)
    
    if len(selected_models) == 0:
        st.warning("至少选一个！")
    else:
        st.info(f"已选 {len(selected_models)} 款。")
        
        preview_rows = raw['specs'][:6]
        preview_data = [{"Parameter": row['label'], **{m: v for m, v in zip(all_models, row['row_values']) if m in selected_models}} for row in preview_rows]
        st.dataframe(preview_data)

        if st.button("✨ 翻译并生成 HTML (出口模式)", type="primary"):
            indices = [all_models.index(m) for m in selected_models]
            new_specs = []
            for row in raw['specs']:
                if len(row['row_values']) >= len(all_models):
                    new_values = [row['row_values'][i] for i in indices]
                    new_specs.append({"section": row['section'], "label": row['label'], "row_values": new_values})
            
            processed = {"models": selected_models, "specs": new_specs}
            
            tool = SpecLogic(proxy)
            status = st.empty()
            log = st.expander("日志", expanded=True) # 展开日志看结果
            try:
                final_data = tool.incremental_translate(processed, lambda x: status.text(x), log)
                st.session_state.processed_data = final_data
                st.session_state.step = 3
                st.rerun()
            except Exception as e:
                st.error(f"错误: {e}")

elif st.session_state.step == 3:
    st.success("✅ 完成！")
    final_data = st.session_state.processed_data
    tool = SpecLogic()
    html = tool.render_html(final_data)
    col1, col2 = st.columns([1, 4])
    with col1:
        st.download_button("📥 下载 HTML", html, "spec_sheet.html", "text/html")
    with col2:
        if st.button("⬅️ 返回"):
            st.session_state.step = 2
            st.rerun()
    st.components.v1.html(html, height=800, scrolling=True)