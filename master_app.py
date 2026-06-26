import streamlit as st
import pandas as pd
import json
import os
import time
from io import BytesIO
import re
import base64
import requests
import streamlit.components.v1 as components

# --- 1. SETUP & AUTH ---
st.set_page_config(page_title="KingsBox Audit App", layout="wide", page_icon="📈")

api_token = os.environ.get("GEMINI_API_KEY", "").strip()

# --- 2. HELPER FUNCTIONS ---
def parse_financial_value(val):
    if pd.isna(val): return 0.0
    if isinstance(val, (int, float)): return float(val)
    clean_str = str(val).replace('€', '').replace(' ', '').replace('\xa0', '').strip()
    if not clean_str: return 0.0
    if '.' in clean_str and ',' in clean_str:
        if clean_str.rfind(',') > clean_str.rfind('.'): clean_str = clean_str.replace('.', '').replace(',', '.')
        else: clean_str = clean_str.replace(',', '')
    elif ',' in clean_str: clean_str = clean_str.replace(',', '.')
    elif '.' in clean_str:
        parts = clean_str.split('.')
        if len(parts) == 2 and len(parts[1]) == 3: clean_str = clean_str.replace('.', '')
    try: return float(clean_str)
    except: return 0.0

def standardize_country(c):
    if not c or pd.isna(c): return "OSTALO"
    c = str(c).strip().upper()
    mapping = {
        'IT': 'Italija', 'ITA': 'Italija', 'ITALY': 'Italija', 'ITALIJA': 'Italija',
        'SI': 'Slovenija', 'SVN': 'Slovenija', 'SLOVENIA': 'Slovenija', 'SLOVENIJA': 'Slovenija',
        'DE': 'Nemčija', 'DEU': 'Nemčija', 'GERMANY': 'Nemčija', 'NEMČIJA': 'Nemčija', 'NEMCIJA': 'Nemčija',
        'FR': 'Francija', 'FRA': 'Francija', 'FRANCE': 'Francija', 'FRANCIJA': 'Francija',
        'ES': 'Španija', 'ESP': 'Španija', 'SPAIN': 'Španija', 'ŠPANIJA': 'Španija', 'SPANIJA': 'Španija',
        'NL': 'Nizozemska', 'NLD': 'Nizozemska', 'NETHERLANDS': 'Nizozemska', 'NIZOZEMSKA': 'Nizozemska', 'HOLLAND': 'Nizozemska',
        'BE': 'Belgija', 'BEL': 'Belgija', 'BELGIUM': 'Belgija', 'BELGIJA': 'Belgija',
        'CH': 'Švica', 'CHE': 'Švica', 'SWITZERLAND': 'Švica', 'ŠVICA': 'Švica', 'SVICA': 'Švica',
        'AT': 'Avstrija', 'AUT': 'Avstrija', 'AUSTRIA': 'Avstrija', 'AVSTRIJA': 'Avstrija',
        'HR': 'Hrvaška', 'HRV': 'Hrvaška', 'CROATIA': 'Hrvaška', 'HRVAŠKA': 'Hrvaška', 'HRVASKA': 'Hrvaška',
        'LU': 'Luksemburg', 'LUX': 'Luksemburg', 'LUXEMBOURG': 'Luksemburg', 'LUKSEMBURG': 'Luksemburg',
        'KW': 'Kuwait (Oxygen)', 'KWT': 'Kuwait (Oxygen)', 'KUWAIT': 'Kuwait (Oxygen)', 'KUWAIT (OXYGEN)': 'Kuwait (Oxygen)'
    }
    # 1. Try exact match
    if c in mapping: return mapping[c]
    # 2. Try partial match
    for key, val in mapping.items():
        if key in c or c in key: return val
        
    return "OSTALO"

# --- 3. USER INTERFACE ---
st.title("📈 Master Logistics & Margin Auditor")

if not api_token:
    st.warning("⚠️ No API Key found. Please add GEMINI_API_KEY to your Render environment variables.")
elif api_token.startswith("AQ."):
    st.info("ℹ️ Using an AQ Session Token. Ensure it hasn't expired (they typically last 1 hour).")

st.markdown("Upload your monthly documents below to automatically generate your interactive financial dashboard.")

col_u1, col_u2, col_u3 = st.columns(3)
with col_u1:
    uploaded_couriers = st.file_uploader("1. Courier Invoices", type=['pdf', 'png', 'jpg'], accept_multiple_files=True)
with col_u2:
    uploaded_ltl = st.file_uploader("2. Heavy Freight Tracker", type=['xlsx', 'csv'])
with col_u3:
    uploaded_revenue = st.file_uploader("3. Market Revenue Report", type=['xlsx', 'csv'])

# Session State for persistence
if 'audit_success' not in st.session_state: 
    st.session_state.audit_success = False

# --- 4. CORE PROCESSING PIPELINE ---
if st.button("🚀 Execute Global Monthly Consolidation", type="primary", use_container_width=True):
    all_shipment_rows = []
    reconciliation_log = []
    
    # Initialize revenue tracking
    ordered_countries = ["Nemčija", "Italija", "Slovenija", "Francija", "Kuwait (Oxygen)", "OSTALO", "Nizozemska", "Španija", "Belgija", "Švica", "Avstrija", "Hrvaška", "Luksemburg"]
    revenue_dict = {name: 0.0 for name in ordered_countries}

    # A. Process Revenue Data
    if uploaded_revenue:
        with st.spinner("Parsing revenue matrices..."):
            try:
                df_rev = pd.read_csv(uploaded_revenue) if uploaded_revenue.name.endswith('.csv') else pd.read_excel(uploaded_revenue)
                df_rev.columns = [str(c).strip().lower() for c in df_rev.columns]
                c_col = next((c for c in df_rev.columns if any(x in c for x in ['country', 'drz', 'drž', 'mkt', 'code'])), df_rev.columns[0])
                v_col = next((c for c in df_rev.columns if any(x in c for x in ['revenue', 'promet', 'total', 'znesek', 'neto', 'eur'])), df_rev.columns[-1])
                for _, row in df_rev.iterrows():
                    country_name = standardize_country(row[c_col])
                    if country_name not in revenue_dict: revenue_dict[country_name] = 0.0
                    revenue_dict[country_name] += parse_financial_value(row[v_col])
            except Exception as e: st.error(f"Revenue Error: {e}")

    # B. Process LTL Data
    if uploaded_ltl:
        with st.spinner("Extracting heavy freight entries..."):
            try:
                df_ltl = pd.read_csv(uploaded_ltl) if uploaded_ltl.name.endswith('.csv') else pd.read_excel(uploaded_ltl)
                df_ltl.columns = [str(c).strip().lower() for c in df_ltl.columns]
                c_col = next((c for c in df_ltl.columns if any(x in c for x in ['country', 'drz', 'drž', 'dest', 'kraj'])), None)
                m_col = next((c for c in df_ltl.columns if any(x in c for x in ['carrier', 'prevoznik', 'partner'])), None)
                v_col = next((c for c in df_ltl.columns if any(x in c for x in ['cost', 'cena', 'znesek', 'neto', 'eur'])), None)
                if c_col and v_col:
                    for _, row in df_ltl.iterrows():
                        all_shipment_rows.append({
                            'country': standardize_country(row[c_col]),
                            'carrier': str(row[m_col]).strip().upper() if m_col and pd.notna(row[m_col]) else "MANUAL_LTL",
                            'cost': parse_financial_value(row[v_col]),
                            'source': uploaded_ltl.name
                        })
            except Exception as e: st.error(f"LTL Error: {e}")

    # C. Process Courier PDFs via DIRECT REST API (Bypassing Python Library entirely)
    if uploaded_couriers and api_token:
        progress_bar = st.progress(0)
        
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
        headers = {"Content-Type": "application/json"}
        
        # Smart Auth Routing
        if api_token.startswith("AQ.") or api_token.startswith("ya29."):
            headers["Authorization"] = f"Bearer {api_token}"
        else:
            url += f"?key={api_token}"
            
        for idx, file in enumerate(uploaded_couriers):
            with st.spinner(f"AI scanning: {file.name}..."):
                try:
                    prompt = """
                    Extract every shipment line-by-line. 
                    Calculate the TOTAL NET AMOUNT for each row (Base rate + all surcharges like fuel, remote area, tolls).
                    EXCLUDE ANY VAT/DDV/TAX.
                    Also find the total net invoice amount at the bottom of the document.
                    
                    Return ONLY a JSON object with this exact structure:
                    {
                        "invoice_net_total": float,
                        "shipments": [
                            {"tracking_nr": "string", "country": "string (2 letter code if possible)", "carrier": "string", "cost": float}
                        ]
                    }
                    """
                    
                    # Convert PDF to Base64 for safe inline transit
                    fb = file.getvalue()
                    b64_pdf = base64.b64encode(fb).decode('utf-8')
                    mime_type = "application/pdf" if file.name.lower().endswith(".pdf") else file.type
                    if not mime_type: mime_type = "application/pdf"
                    
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt},
                                {"inlineData": {"mimeType": mime_type, "data": b64_pdf}}
                            ]
                        }],
                        "safetySettings": [
                            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                        ]
                    }
                    
                    # Direct HTTP Request
                    response = requests.post(url, headers=headers, json=payload)
                    
                    if response.status_code != 200:
                        raise Exception(f"Google API Error [{response.status_code}]: {response.text}")
                        
                    resp_data = response.json()
                    
                    if 'candidates' not in resp_data or not resp_data['candidates']:
                        raise Exception(f"Google returned an empty response. It likely blocked the file. Full output: {resp_data}")
                        
                    # Extract the text and clean it
                    raw_text = resp_data['candidates'][0]['content']['parts'][0]['text'].strip()
                    if raw_text.startswith("```"):
                        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
                        
                    data = json.loads(raw_text)
                    
                    # Math Reconciliation
                    file_net_total = parse_financial_value(str(data.get('invoice_net_total', 0)))
                    file_extracted_sum = sum(parse_financial_value(str(s.get('cost', 0))) for s in data.get('shipments', []))
                    
                    reconciliation_log.append({
                        'file': file.name,
                        'invoice_total': file_net_total,
                        'extracted_sum': file_extracted_sum,
                        'diff': abs(file_net_total - file_extracted_sum)
                    })
                    
                    carrier_name = file.name.split('.')[0].upper()
                    for s in data.get('shipments', []):
                        all_shipment_rows.append({
                            'country': standardize_country(s.get('country')),
                            'carrier': str(s.get('carrier', carrier_name)).strip().upper(),
                            'cost': parse_financial_value(str(s.get('cost', 0))),
                            'source': file.name
                        })
                        
                    # Anti-Spam Pause
                    if idx < len(uploaded_couriers) - 1: time.sleep(12)
                        
                except Exception as e:
                    # Detailed Error Catcher
                    st.error(f"🛑 AI parsing failure on **{file.name}**")
                    st.code(f"Details:\n{str(e)}")
                    
            progress_bar.progress((idx + 1) / len(uploaded_couriers))

    # --- 5. DASHBOARD GENERATION ---
    if all_shipment_rows:
        df_master = pd.DataFrame(all_shipment_rows)
        country_costs = df_master.groupby('country')['cost'].sum().to_dict()
        carrier_costs = df_master.groupby('carrier')['cost'].sum().sort_values(ascending=False).to_dict()
        
        total_logistics_spend = sum(country_costs.values())
        total_global_revenue = sum(revenue_dict.values())
        avg_cost_to_serve = (total_logistics_spend / total_global_revenue * 100) if total_global_revenue > 0 else 0.0
        
        chart_rev_data = [round(revenue_dict.get(c, 0.0), 2) for c in ordered_countries]
        chart_log_data = [round(country_costs.get(c, 0.0), 2) for c in ordered_countries]
        chart_carrier_labels, chart_carrier_data = list(carrier_costs.keys()), [round(v, 2) for v in carrier_costs.values()]
        
        table_rows_html = ""
        for c in ordered_countries:
            rev, log = revenue_dict.get(c, 0.0), country_costs.get(c, 0.0)
            pct = (log / rev * 100) if rev > 0 else 0.0
            badge = "badge-green" if pct < 10 else "badge-yellow" if pct < 20 else "badge-red"
            table_rows_html += f'<tr><td>{c}</td><td class="num-col">€{rev:,.2f}</td><td class="num-col">€{log:,.2f}</td><td class="num-col"><span class="{badge}">{pct:.2f}%</span></td></tr>'

        top_5_html = ""
        top_5_df = df_master.nlargest(5, 'cost')
        for _, row in top_5_df.iterrows():
            top_5_html += f"<tr><td>{row['carrier']}<span class='client-tag'>{row['source'].replace('.xlsx','').replace('.csv','')}</span></td><td>{row['country']}</td><td class='cost-col'>€{row['cost']:,.2f}</td></tr>"

        html_dashboard_code = f"""
        <!DOCTYPE html><html><head><script src="[https://cdn.jsdelivr.net/npm/chart.js](https://cdn.jsdelivr.net/npm/chart.js)"></script>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f1f5f9; color: #1e293b; margin:0; padding:40px; }}
            .dashboard {{ max-width: 1400px; margin: 0 auto; }}
            .header {{ background: #0f172a; color: white; padding: 30px 40px; border-radius: 16px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); }}
            .header h1 {{ margin: 0 0 8px 0; font-size:
