import streamlit as st
import json
import re
import subprocess
import sys
import math
import time
import os
import base64
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from jinja2 import Template

# ==========================================
# 🔑 API Key (Hardcoded)
# ==========================================
HARDCODED_API_KEY = "AIzaSyDXSWRCoruhCl4_sNlywD7n-aCGiE66NNk"

# ==========================================
# 📚 Local Automotive Dictionary
# ==========================================
AUTO_DICT = {
    "厂商指导价": "MSRP", "厂商": "Manufacturer", "级别": "Class", "能源类型": "Energy Type",
    "上市时间": "Launch Date", "最大功率": "Max Power", "最大扭矩": "Max Torque",
    "发动机": "Engine", "变速箱": "Transmission", "长*宽*高": "L*W*H", "车身结构": "Body Style",
    "最高车速": "Max Speed", "官方0-100km/h加速": "0-100km/h Accel", "实测0-100km/h加速": "0-100km/h (Tested)",
    "整车质保": "Vehicle Warranty", "首任车主质保政策": "First Owner Warranty",
    "环保标准": "Emission Std", "国VI": "China VI", "国六": "China VI", "国V": "China V", "国6": "China VI",
    "排量": "Displacement", "进气形式": "Intake", "气缸数": "Cylinders",
    "涡轮增压": "Turbo", "自然吸气": "NA", "双离合": "DCT", "手自一体": "AT", "无级变速": "CVT", "固定齿比": "Fixed Gear",
    "前置前驱": "FWD", "前置四驱": "AWD/4WD", "后置后驱": "RWD", "适时四驱": "Real-time 4WD",
    "麦弗逊": "McPherson", "多连杆": "Multi-link", "双叉臂": "Double Wishbone",
    "磷酸铁锂": "LFP", "三元锂": "NMC", "纯电续航": "Range", "CLTC纯电续航": "CLTC Range",
    "快充时间": "Fast Charge Time", "慢充时间": "Slow Charge Time", "快充": "DC Charge", "慢充": "AC Charge",
    "对外放电": "V2L", "最大对外放电功率": "V2L Power",
    "前制动器": "Front Brake", "后制动器": "Rear Brake", "驻车制动": "Parking Brake",
    "通风盘式": "Ventilated Disc", "电子驻车": "EPB",
    "并线辅助": "BSD (Blind Spot)", "车道偏离预警": "LDW", "车道保持": "LKA", "主动刹车": "AEB",
    "360度全景影像": "360 Camera", "全速自适应巡航": "Full-speed ACC", "自动驻车": "Auto Hold", "上坡辅助": "HAC",
    "全景天窗": "Panoramic Sunroof", "电动天窗": "Electric Sunroof", "无钥匙进入": "Keyless Entry",
    "真皮": "Leather", "仿皮": "Faux Leather", "全液晶仪表盘": "Full LCD Cluster",
    "中控彩色液晶屏": "Center Screen", "LED日间行车灯": "LED DRL", "自动头灯": "Auto Headlights",
    "自动空调": "Auto AC", "后座出风口": "Rear Vents", "双温区": "Dual-zone",
    "WLTC纯电续航": "WLTC Range", "NEDC纯电续航": "NEDC Range" 
}

st.set_page_config(page_title="Auto Spec V12.4 (Fix WLTC)", page_icon="🛠️", layout="wide")

# Initialize Session State
if 'step' not in st.session_state: st.session_state.step = 1
if 'raw_data' not in st.session_state: st.session_state.raw_data = None
if 'processed_data' not in st.session_state: st.session_state.processed_data = None
if 'suggested_series' not in st.session_state: st.session_state.suggested_series = ""
if 'debug_logs' not in st.session_state: st.session_state.debug_logs = []

class SpecLogic:
    def __init__(self, proxy_url=None):
        if proxy_url:
            os.environ['http_proxy'] = proxy_url
            os.environ['https_proxy'] = proxy_url
        self.translator = GoogleTranslator(source='auto', target='en')
        self.cache = {} 

    def log(self, message):
        st.session_state.debug_logs.append(message)
        print(message)

    def fetch_url(self, url):
        command = [sys.executable, "scraper.py", url]
        for attempt in range(2): 
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, encoding='utf-8', 
                    errors='ignore', check=False, timeout=100
                )
                output = result.stdout.strip()
                if result.stderr.strip(): 
                    self.log(f"⚠️ Scraper warning: {result.stderr.strip()}")
                
                if output.startswith("ERROR:"): raise Exception(output)
                if not output: raise Exception("Empty result")
                return output
            except Exception as e:
                if attempt == 1: raise e
                time.sleep(2)

    def smart_parse(self, content):
        if "JSON_START" in content:
            self.log("✅ Detected JSON format")
            return self.parse_json_data(content.split("JSON_START")[1].strip())
        elif "HTML_START" in content:
            self.log("⚠️ Detected HTML format (fallback)")
            return self.parse_html_data(content.split("HTML_START")[1].strip())
        else:
            try: return self.parse_json_data(content)
            except: return self.parse_html_data(content)

    def parse_json_data(self, json_content):
        data = json.loads(json_content) if isinstance(json_content, str) else json_content
        yiche = data.get("data", {})
        
        series_name = yiche.get("serialName", "")
        brand_name = yiche.get("masterName", "") 
        if not brand_name:
            brand_name = yiche.get("brandName", "")
        
        self.log(f"JSON Extracted: Brand={brand_name}, Series={series_name}")

        car_models = [f"{c.get('name','')} [{c.get('price','')}w]" if c.get('price') else c.get('name','') for c in yiche.get("carList", [])]
        specs = []
        for cat in yiche.get("baseInfoList", []) + yiche.get("configList", []):
            for param in cat.get("list", []):
                vals = []
                for vobj in param.get("valueslist", []):
                    v = vobj.get("value", "-")
                    if v is None or v == "": v = "-"
                    if str(v) == "1": v = "●"
                    if str(v) == "2": v = "○ Optional"
                    vals.append(str(v))
                if len(vals) < len(car_models): vals.extend(["-"] * (len(car_models) - len(vals)))
                specs.append({"section": cat.get("name", "General"), "label": param.get("name", ""), "row_values": vals})
        
        return {"models": car_models, "specs": specs, "series_name": series_name, "brand_name": brand_name}

    def parse_html_data(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        
        series_name = ""
        brand_name = ""
        
        bread_crumbs = soup.select(".bread-nav a")
        
        if bread_crumbs and len(bread_crumbs) >= 3:
            raw_brand = bread_crumbs[1].get_text(strip=True)
            raw_series = bread_crumbs[2].get_text(strip=True)
            
            brand_name = raw_brand.replace("品牌", "").replace("汽车", "")
            brand_name = re.sub(r"[（）\(\)]", "", brand_name)
            series_name = re.sub(r"[（）\(\)]", "", raw_series)
            self.log(f"Breadcrumb Extracted: Brand={brand_name}, Series={series_name}")
            
        else:
            title_tag = soup.find("title")
            if title_tag:
                title_text = title_tag.get_text()
                match = re.search(r'【(.*?)配置】', title_text)
                if match:
                    series_name = match.group(1)
                    series_name = series_name.replace("品牌", "")
                    series_name = re.sub(r"[（）\(\)]", "", series_name)
                    self.log(f"Title Extracted: Series={series_name}")

        seen = set()
        models = []
        for box in soup.select(".selected-car-box"):
            if 'style' in box.attrs and 'none' in box.attrs['style']: continue
            nm = box.select_one(".car-style-info") or box.select_one(".car-name")
            pr = box.select_one(".car-price")
            if nm:
                raw = str(nm.get("title") or nm.get_text(strip=True) or "")
                clean = re.sub(r'\d+(\.\d+)?(万|元).*', '', raw).strip()
                if not clean: continue
                p_txt = pr.get_text(strip=True).replace("万", "w") if pr else ""
                uid = f"{clean}_{p_txt}"
                if uid not in seen:
                    seen.add(uid)
                    models.append(f"{clean} [{p_txt}]" if p_txt else clean)
        
        if not models:
            for n in soup.select(".car-style-info, .car-name"):
                c = re.sub(r'\d+(\.\d+)?(万|元).*', '', n.get_text(strip=True)).strip()
                if c and c not in seen: seen.add(c); models.append(c)

        specs = []
        curr_sec = "Basic Info"
        for row in soup.find_all("tr"):
            if "param-carInfo" in row.get("class", []) or row.find("h3"):
                curr_sec = row.get_text(strip=True) or curr_sec
                continue
            cells = row.find_all(["td", "th"])
            if not cells: continue
            
            label = cells[0].get_text(strip=True)
            
            vals = []
            for i, c in enumerate(cells[1:]):
                if i >= len(models): break
                txt = c.get_text(strip=True)
                v = txt
                if "●" in txt: v = txt.replace("●","").strip() or "●"
                elif "icon-ok" in str(c) and not v: v = "●"
                elif not v: v = "-"
                elif "○" in txt: v = txt.replace("○","").strip() or "○"
                v = v.replace("万", "w").replace("元", "")
                v = re.sub(r'\(暂无\)', '', v)
                if "选配" in v and "Optional" not in v: v = v.replace("选配", "Optional")
                
                # --- Fix for incorrect price data in mileage/other fields ---
                # Check if value looks like a price (e.g., "Starting from 14.18w") and label is NOT price related
                if "指导价" not in label and "Price" not in label and "MSRP" not in label:
                     if re.search(r'\d+(\.\d+)?[w万]起?', v):
                         # Try to clean it or replace with '-' if it seems completely wrong
                         # For now, if it looks like price info in a non-price field, wipe it.
                         if "Range" in label or "续航" in label:
                             # Specifically for range, if it has 'w' it's likely wrong
                             if 'w' in v or '万' in v:
                                 v = "-" 

                vals.append(v)
            if vals: specs.append({"section": curr_sec, "label": label, "row_values": vals})
        
        return {"models": models, "specs": specs, "series_name": series_name, "brand_name": brand_name}

    def translate_text(self, text):
        if not text or text in ["-", "●"]: return text
        for k, v in AUTO_DICT.items():
            if k == text: return v
            if k in text: text = text.replace(k, v)
        if re.search(r'[\u4e00-\u9fa5]', text):
            if text in self.cache: return self.cache[text]
            try:
                trans = self.translator.translate(text)
                self.cache[text] = trans
                return trans
            except: return text
        return text

    def clean_name_string(self, text):
        if not text: return ""
        text = re.sub(r'\[.*?\]', '', text) 
        text = re.sub(r'\d{2,4}款', '', text)
        text = re.sub(r'(\d+\.?\d*)\s*[wW万]', '', text) 
        text = re.sub(r'^\s*(\d+\.?\d*)\s*', '', text)
        text = text.replace("起", "")
        text = re.sub(r"[（）\(\)]", "", text)
        return text.strip()

    def batch_translate(self, data, status_func, series_name_en, quotes_map):
        status_func("🚀 正在构建标准车型名称...")
        new_models = []
        quotes_list = [] 
        
        for m in data['models']:
            user_quote = quotes_map.get(m, "")
            quotes_list.append(user_quote)

            clean = self.clean_name_string(m)

            if series_name_en:
                translated_trim = self.translate_text(clean)
                translated_trim = self.clean_name_string(translated_trim)
                
                if series_name_en.lower() in translated_trim.lower():
                    pattern = re.compile(re.escape(series_name_en), re.IGNORECASE)
                    translated_trim = pattern.sub('', translated_trim).strip()
                
                ym = re.search(r'(\d{2})款', m)
                yr = f"20{ym.group(1)}" if ym else ""
                
                parts = [p for p in [yr, series_name_en, translated_trim] if p]
            else:
                full_trans = self.translate_text(clean)
                full_trans = self.clean_name_string(full_trans)
                
                ym = re.search(r'(\d{2})款', m)
                yr = f"20{ym.group(1)}" if ym else ""
                parts = [p for p in [yr, full_trans] if p]
                
            new_models.append(" ".join(parts))
            
        data['models'] = new_models
        data['model_quotes'] = quotes_list 

        specs = data['specs']
        status_func(f"🚀 正在并发翻译 {len(specs)} 条配置...")
        def proc(r):
            r['section'] = self.translate_text(r['section'])
            r['label'] = self.translate_text(r['label'])
            
            # Additional cleaning for specific rows during translation
            new_vals = []
            for v in r['row_values']:
                trans_v = self.translate_text(v)
                # Double check for price pollution in Range fields
                if "Range" in r['label'] and ("w" in trans_v or "Start" in trans_v):
                     trans_v = "-"
                new_vals.append(trans_v)
            r['row_values'] = new_vals
            return r
            
        with ThreadPoolExecutor(max_workers=10) as ex:
            data['specs'] = list(ex.map(proc, specs))
        return data

    def render_html(self, data):
        def img_b64(path):
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f"data:image/jpeg;base64,{base64.b64encode(f.read()).decode()}"
            return ""

        wc_img = img_b64("wechat.jpg")
        wa_img = img_b64("whatsapp.jpg")

        clean_models = []
        for m in data['models']:
             m = self.clean_name_string(m)
             clean_models.append(m)
             
        d_data = data.copy()
        d_data['models'] = clean_models
        
        f_specs = []
        for r in d_data['specs']:
            l = r['label'].lower()
            if any(x in l for x in ["msrp", "指导价", "price"]): continue
            r['is_diff'] = len(set(r['row_values'])) > 1
            f_specs.append(r)
        d_data['specs'] = f_specs
        
        has_quotes = False
        if 'model_quotes' in d_data:
            for q in d_data['model_quotes']:
                if q and str(q).strip(): 
                    has_quotes = True
                    break

        template = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
    body { 
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
        background-color: #f4f4f4; margin: 0; padding: 20px; 
        color: #333; font-size: 13px; 
    }

    .watermark-overlay {
        position: fixed;
        top: 0; left: 0; width: 100%; height: 100%;
        z-index: 9999;
        pointer-events: none;
        background-image: url("data:image/svg+xml,%3Csvg width='300' height='300' xmlns='http://www.w3.org/2000/svg'%3E%3Ctext x='50%25' y='50%25' font-family='Arial' font-weight='900' font-size='28' fill='rgba(0,0,0,0.06)' transform='rotate(-45 150 150)' text-anchor='middle'%3ESINO GEAR%3C/text%3E%3C/svg%3E");
        background-repeat: repeat;
    }

    .container { 
        max-width: 98%; margin: 0 auto; 
        background: #fff;
        border-top: 6px solid #00D26A; 
        box-shadow: 0 8px 20px rgba(0,0,0,0.1); 
        position: relative; 
        z-index: 1; 
    }
    
    .header { 
        background: #1a1a1a; 
        padding: 20px 30px; 
        color: #fff; 
        display: flex; 
        justify-content: space-between; 
        align-items: center; 
        border-bottom: 1px solid #333;
    }
    
    .brand-box h1 { margin: 0; font-size: 28px; font-weight: 900; letter-spacing: 2px; color: #fff; }
    .brand-box p { margin: 5px 0 0; font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; }

    .header-right { display: flex; align-items: center; gap: 25px; }
    
    .contact-info { text-align: right; }
    .contact-row { display: block; color: #00D26A; font-weight: 700; font-size: 16px; margin-bottom: 4px; }
    .contact-sub { display: block; color: #bbb; font-size: 11px; }

    .qr-group { display: flex; gap: 15px; }
    .qr-frame {
        width: 100px; height: 100px; 
        border: 4px solid #fff;
        border-radius: 8px;
        background: #fff;
        box-shadow: 0 4px 10px rgba(0,0,0,0.5);
        display: flex; align-items: center; justify-content: center;
    }
    .qr-frame img { width: 100%; height: 100%; object-fit: contain; display: block; }
    
    .table-wrapper { overflow-x: auto; width: 100%; border-top: 1px solid #eee; }
    table { width: 100%; border-collapse: collapse; min-width: 1200px; }
    
    th, td { padding: 12px 15px; border: 1px solid #e0e0e0; text-align: center; vertical-align: middle; font-size: 13px; }
    
    .label-col { 
        position: sticky; left: 0; 
        background-color: #fafafa; 
        width: 220px; min-width: 220px; 
        text-align: left; font-weight: 600; color: #444;
        z-index: 10; border-right: 2px solid #ddd; padding-left: 20px;
    }
    
    .model-header { 
        background-color: #e8f5e9; color: #111; font-weight: 700; font-size: 14px;
        height: 70px; position: sticky; top: 0; z-index: 20; border-bottom: 3px solid #00D26A; line-height: 1.4;
    }
    
    .quote-row td {
        background-color: #fff;
        color: #d32f2f;
        font-weight: 800;
        font-size: 15px;
        border-bottom: 2px solid #00D26A;
        padding: 15px;
    }
    .quote-row .label-col {
        background-color: #fff;
        color: #000;
        font-weight: 800;
        text-transform: uppercase;
    }

    .section-row td { 
        background-color: #2c3e50; color: #fff; text-align: left; font-weight: 700; 
        text-transform: uppercase; padding: 10px 20px; font-size: 14px; letter-spacing: 1px;
    }
    
    .diff { background-color: #f0fdf4 !important; }
    .diff .label-col { background-color: #f0fdf4 !important; color: #155724; border-right: 2px solid #00D26A; }
    
    .dot { color: #00D26A; font-weight: 900; font-size: 16px; margin-right: 4px; }
    .opt { color: #f39c12; font-weight: 900; font-size: 16px; margin-right: 4px; }
</style>
</head>
<body>

<div class="watermark-overlay"></div>

<div class="container">
    <div class="header">
        <div class="brand-box">
            <h1>SINO GEAR</h1>
            <p>Professional Configuration Matrix</p>
        </div>

        <div class="header-right">
            <div class="contact-info">
                <span class="contact-row">WhatsApp: +86 15555172187</span>
                <span class="contact-sub">Scan QR Code to Chat</span>
            </div>
            <div class="qr-group">
                {% if wechat_img %}
                <div class="qr-frame">
                    <img src="{{ wechat_img }}" alt="WeChat">
                </div>
                {% endif %}
                {% if whatsapp_img %}
                <div class="qr-frame">
                    <img src="{{ whatsapp_img }}" alt="WhatsApp">
                </div>
                {% endif %}
            </div>
        </div>
    </div>
    
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th class="label-col" style="background:#222; color:#fff;">Parameter</th>
                    {% for model in data.models %}
                    <th class="model-header">{{ model }}</th>
                    {% endfor %}
                </tr>
            </thead>
            <tbody>
                {% if has_quotes %}
                <tr class="quote-row">
                    <td class="label-col">QUOTATION</td>
                    {% for quote in data.model_quotes %}
                    <td>{{ quote }}</td>
                    {% endfor %}
                </tr>
                {% endif %}

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
        return Template(template).render(data=d_data, wechat_img=wc_img, whatsapp_img=wa_img, has_quotes=has_quotes)

# ================= UI =================
with st.sidebar:
    st.header("⚙️ 设置")
    st.success("API Key 已内置")
    proxy = st.text_input("网络代理")
    
    # Debug switch
    debug_mode = st.checkbox("🐞 显示调试信息 (Debug)", value=False)
    
    if st.button("🔄 重置"):
        st.session_state.step = 1; st.session_state.raw_data = None; st.session_state.suggested_series = ""; st.session_state.debug_logs=[]; st.rerun()

    if debug_mode and st.session_state.debug_logs:
        st.markdown("### Debug Logs")
        for log in st.session_state.debug_logs:
            st.text(log)

st.title("🚙 易车配置表生成器 (V12.4 Fix WLTC)")

if st.session_state.step == 1:
    url = st.text_input("🔗 易车网址", "https://car.yiche.com/songplusdm/peizhi/")
    if st.button("🚀 抓取", type="primary"):
        if not url: st.error("输入网址")
        else:
            with st.spinner("⏳ Fetching..."):
                try:
                    tool = SpecLogic(proxy)
                    st.session_state.debug_logs = [] # Clear logs
                    st.session_state.raw_data = tool.smart_parse(tool.fetch_url(url))
                    
                    if not st.session_state.raw_data['models']: st.error("No data")
                    else: 
                        # --- V12.4 Logic ---
                        detected_brand = st.session_state.raw_data.get('brand_name', '')
                        detected_series = st.session_state.raw_data.get('series_name', '')
                        
                        tool.log(f"Initial Detected: Brand='{detected_brand}', Series='{detected_series}'")

                        if not detected_brand:
                            for row in st.session_state.raw_data['specs']:
                                if row['label'].strip() in ["厂商", "Manufacturer"]:
                                    detected_brand = row['row_values'][0] 
                                    break
                        tool.log(f"Brand after rescue: '{detected_brand}'")

                        if not detected_series:
                            first_model = st.session_state.raw_data['models'][0]
                            detected_series = tool.clean_name_string(first_model)
                            tool.log(f"Fallback Series from Model Name: '{detected_series}'")

                        detected_series = tool.clean_name_string(detected_series)
                        detected_series = re.sub(r'^\s*[\d\.]+[wW万]?\s*', '', detected_series)
                        
                        tool.log(f"Series after Cleaning: '{detected_series}'")

                        if detected_brand:
                            brand_en = tool.translate_text(detected_brand).replace(" Auto", "").replace(" Automobile", "").strip()
                        else:
                            brand_en = ""
                            
                        series_en = tool.translate_text(detected_series).strip()
                        series_en = tool.clean_name_string(series_en)
                        tool.log(f"Final Translated Series: '{series_en}'")

                        if brand_en and (brand_en.lower() not in series_en.lower()):
                            final_suggestion = f"{brand_en} {series_en}".strip()
                        else:
                            final_suggestion = series_en.strip()
                            
                        st.session_state.suggested_series = final_suggestion
                        st.session_state.step = 2
                        st.rerun()
                except Exception as e: st.error(str(e))

elif st.session_state.step == 2:
    raw = st.session_state.raw_data
    all_m = raw['models']
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("##### 📝 命名优化")
    st.session_state.car_series_en = st.sidebar.text_input(
        "车系英文名 (表头)", 
        value=st.session_state.suggested_series,
        help="系统已尝试自动翻译，你可以手动修改。"
    )
    
    st.subheader("🛠️ 车型选择与单独报价")
    st.info("👇 请在下方表格的 'Quotation' 列输入每款车的价格（例如：$15,000 FOB）")

    sel = st.multiselect(f"选择车型 ({len(all_m)})", all_m, default=all_m)
    
    if not sel: 
        st.warning("至少选择一款车型！")
    else:
        quote_df = pd.DataFrame({
            "Model Name (Original)": sel,
            "Quotation": [""] * len(sel)
        })
        
        edited_df = st.data_editor(
            quote_df, 
            hide_index=True, 
            use_container_width=True,
            column_config={
                "Model Name (Original)": st.column_config.TextColumn(disabled=True),
                "Quotation": st.column_config.TextColumn("Quotation (Edit Here)")
            }
        )

        st.divider()
        st.caption("预览部分配置数据：")
        st.dataframe([{"Label": r['label'], **{m: v for m, v in zip(all_m, r['row_values']) if m in sel}} for r in raw['specs'][:3]])
        
        if st.button("✨ 生成 HTML", type="primary"):
            quotes_map = dict(zip(edited_df["Model Name (Original)"], edited_df["Quotation"]))

            idxs = [all_m.index(m) for m in sel]
            new_specs = [{"section":r['section'],"label":r['label'],"row_values":[r['row_values'][i] for i in idxs]} for r in raw['specs']]
            
            tool = SpecLogic(proxy)
            st.empty()
            try:
                st.session_state.processed_data = tool.batch_translate(
                    {"models":sel,"specs":new_specs}, 
                    lambda x:None, 
                    st.session_state.get('car_series_en',''),
                    quotes_map=quotes_map
                )
                st.session_state.step = 3; st.rerun()
            except Exception as e: st.error(str(e))

elif st.session_state.step == 3:
    tool = SpecLogic()
    html = tool.render_html(st.session_state.processed_data)
    col1, col2 = st.columns([1,4])
    with col1:
        st.download_button("📥 下载 HTML", html, "spec_sheet.html", "text/html")
    with col2:
        if st.button("⬅️ 返回修改"): st.session_state.step = 2; st.rerun()
    st.components.v1.html(html, height=800, scrolling=True)