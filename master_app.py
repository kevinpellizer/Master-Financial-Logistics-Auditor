import streamlit as st
import google.generativeai as genai
import os
import pandas as pd
import json
import time  
from io import BytesIO
import re
import streamlit.components.v1 as components

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="Master Logistics & Margin Auditor", layout="wide", page_icon="📈")

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    st.warning("⚠️ GEMINI_API_KEY not found. Please set it in Render Environment Variables.")
else:
    genai.configure(api_key=api_key)

model = genai.GenerativeModel('gemini-2.5-flash')

st.title("📈 Master Logistics & Margin Auditor")
st.markdown("Upload your monthly documents below to automatically generate your interactive financial dashboard.")

# --- DATA PARSING ENGINES ---
COUNTRY_MAP = {
    'IT': 'Italija', 'ITA': 'Italija', 'SI': 'Slovenija', 'SVN': 'Slovenija',
    'DE': 'Nemčija', 'DEU': 'Nemčija', 'AT': 'Avstrija', 'AUT': 'Avstrija',
    'FR': 'Francija', 'FRA': 'Francija', 'ES': 'Španija', 'ESP': 'Španija',
    'NL': 'Nizozemska', 'NLD': 'Nizozemska', 'BE': 'Belgija', 'BEL': 'Belgija',
    'LU': 'Luksemburg', 'LUX': 'Luksemburg', 'CH': 'Švica', 'CHE': 'Švica',
    'HR': 'Hrvaška', 'HRV': 'Hrvaška', 'KW': 'Kuwait (Oxygen)', 'KWT': 'Kuwait (Oxygen)'
}

def standardize_country(val):
    if pd.isna(val): return "OSTALO"
    clean = str(val).strip().upper()
    
    # 🚨 NEW: RegEx engine to catch all zip code spacing variations (ES28000, ES 28000, ES-28000)
    match = re.match(r'^([A-Z]{2})[\s\-\_]*\d+', clean)
    if match:
        prefix = match.group(1)
        if prefix in COUNTRY_MAP: return COUNTRY_MAP[prefix]

    if clean in COUNTRY_MAP: return COUNTRY_MAP[clean]
    for k, v in COUNTRY_MAP.items():
        if clean == v.upper() or clean == k: return v
        
    # Aggressive Substring Matching (Slovenian + English variants)
    if any(x in clean for x in ['NEM', 'GER', 'DEU', 'DE ']): return 'Nemčija'
    if any(x in clean for x in ['ITA', 'ITALY', 'IT ']): return 'Italija'
    if any(x in clean for x in ['SLO', 'SVN', 'SLOVENIA', 'SI ']): return 'Slovenija'
    if any(x in clean for x in ['FRA', 'FRANCE', 'FR ']): return 'Francija'
    if any(x in clean for x in ['SPA', 'ESP', 'SPAIN', 'ŠPA', 'ES ']): return 'Španija'
    if any(x in clean for x in ['NIZ', 'NED', 'NLD', 'NETHERLANDS', 'NL ']): return 'Nizozemska'
    if any(x in clean for x in ['BEL', 'BELGIUM', 'BE ']): return 'Belgija'
    if any(x in clean for x in ['LUK', 'LUX', 'LUXEMBOURG', 'LU ']): return 'Luksemburg'
    if any(x in clean for x in ['SVI', 'ŠVI', 'CHE', 'SWITZERLAND', 'CH ']): return 'Švica'
    if any(x in clean for x in ['HRV', 'CRO', 'CROATIA', 'HR ']): return 'Hrvaška'
    if any(x in clean for x in ['KUV', 'KUW', 'KW']): return 'Kuwait (Oxygen)'
    if any(x in clean for x in ['AVS', 'AUT', 'AUSTRIA', 'OST', 'AT ']): return 'Avstrija'
    
    return "OSTALO"

def parse_financial_value(val):
    if pd.isna(val): return 0.0
    if isinstance(val, (int, float)): return float(val)
    
    clean_str = str(val).replace('€', '').replace(' ', '').replace('\xa0', '').strip()
    if not clean_str: return 0.0
    
    if '.' in clean_str and ',' in clean_str:
        if clean_str.rfind(',') > clean_str.rfind('.'):
            clean_str = clean_str.replace('.', '').replace(',', '.')
        else:
            clean_str = clean_str.replace(',', '')
    elif ',' in clean_str:
        clean_str = clean_str.replace(',', '.')
    elif '.' in clean_str:
        parts = clean_str.split('.')
        if len(parts) == 2 and len(parts[1]) == 3:
            clean_str = clean_str.replace('.', '')
            
    try:
        return float(clean_str)
    except:
        return 0.0

# --- 2. MULTI-SOURCE UPLOAD CONSOLE ---
col_u1, col_u2, col_u3 = st.columns(3)
with col_u1:
    uploaded_couriers = st.file_uploader("1. Courier Invoices", type=['pdf', 'png', 'jpg'], accept_multiple_files=True)
with col_u2:
    uploaded_ltl = st.file_uploader("2. Heavy Freight Tracker", type=['xlsx', 'csv'])
with col_u3:
    uploaded_revenue = st.file_uploader("3. Market Revenue Report", type=['xlsx', 'csv'])

# --- 3. PROCESSING PIPELINE ---
if st.button("🚀 Execute Global Monthly Consolidation", type="primary", use_container_width=True):
    all_shipment_rows = [] 
    revenue_dict = {name: 0.0 for name in COUNTRY_MAP.values()}
    revenue_dict["OSTALO"] = 0.0
    debug_log = []

    # --- STEP A: PROCESS REVENUE DATA ---
    if uploaded_revenue:
        with st.spinner("Parsing revenue matrices..."):
            try:
                df_rev = pd.read_csv(uploaded_revenue) if uploaded_revenue.name.endswith('.csv') else pd.read_excel(uploaded_revenue)
                df_rev.columns = [str(c).strip().lower() for c in df_rev.columns]
                
                c_col = next((c for c in df_rev.columns if any(x in c for x in ['country', 'drz', 'drž', 'mkt', 'code', 'kod'])), df_rev.columns[0])
                v_col = next((c for c in df_rev.columns if any(x in c for x in ['revenue', 'promet', 'total', 'znesek', 'neto', 'eur'])), df_rev.columns[-1])
                
                debug_log.append(f"✅ Revenue Sheet mapped - Country: [{c_col.upper()}], Value: [{v_col.upper()}]")
                
                for _, row in df_rev.iterrows():
                    ctry = standardize_country(row[c_col])
                    revenue_dict[ctry] += parse_financial_value(row[v_col])
            except Exception as e:
                st.error(f"Error parsing Revenue sheet: {e}")

    # --- STEP B: PROCESS MANUAL LTL/FTL TRACKER ---
    if uploaded_ltl:
        with st.spinner("Extracting heavy freight entries..."):
            try:
                df_ltl = pd.read_csv(uploaded_ltl) if uploaded_ltl.name.endswith('.csv') else pd.read_excel(uploaded_ltl)
                df_ltl.columns = [str(c).strip().lower() for c in df_ltl.columns]
                
                c_col = next((c for c in df_ltl.columns if any(x in c for x in ['country', 'drz', 'drž', 'dest', 'kraj', 'trg'])), None)
                m_col = next((c for c in df_ltl.columns if any(x in c for x in ['carrier', 'prevoznik', 'partner', 'dostava'])), None)
                v_col = next((c for c in df_ltl.columns if any(x in c for x in ['cost', 'cena', 'znesek', 'billed', 'neto', 'eur', 'vrednost'])), None)
                
                if c_col and v_col:
                    debug_log.append(f"✅ LTL Sheet mapped - Country: [{c_col.upper()}], Cost: [{v_col.upper()}], Carrier: [{m_col.upper() if m_col else 'NOT FOUND'}]")
                    
                    for _, row in df_ltl.iterrows():
                        all_shipment_rows.append({
                            'country': standardize_country(row[c_col]),
                            'carrier': str(row[m_col]).strip().upper() if m_col and pd.notna(row[m_col]) else "MANUAL_LTL",
                            'cost': parse_financial_value(row[v_col]),
                            'source': uploaded_ltl.name
                        })
                else:
                    st.error("Could not dynamically map LTL columns. Ensure headers clearly contain terms like 'Country', 'Carrier', and 'Cost'.")
            except Exception as e:
                st.error(f"Error parsing Heavy Freight sheet: {e}")

    # --- STEP C: PROCESS COURIER INVOICES VIA GEMINI AI ---
    if uploaded_couriers and api_key:
        progress_bar = st.progress(0)
        for idx, file in enumerate(uploaded_couriers):
            with st.spinner(f"AI scanning: {file.name}..."):
                try:
                    p = (
                        "Extract every single shipment line-by-line. Use ONLY these exact keys: 'tracking_nr', 'country', 'carrier', 'cost'. "
                        "The 'country' MUST be the destination code. The 'carrier' MUST be the shipping company. "
                        "The 'cost' MUST be the TOTAL NET AMOUNT for that shipment. EXCLUDE VAT/Taxes. "
                        "Return strictly as a single JSON object with a 'shipments' array."
                    )
                    file_bytes = file.getvalue()
                    response = model.generate_content([p, {"mime_type": file.type, "data": file_bytes}])
                    
                    raw_text = response.text.strip()
                    if "```json" in raw_text:
                        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in raw_text:
                        raw_text = raw_text.split("```")[1].split("```")[0].strip()
                        
                    data = json.loads(raw_text)
                    
                    for s in data.get('shipments', []):
                        all_shipment_rows.append({
                            'country': standardize_country(s.get('country')),
                            'carrier': str(s.get('carrier', file.name.split('.')[0])).strip().upper(),
                            'cost': parse_financial_value(str(s.get('cost', 0))),
                            'source': file.name
                        })
                    if idx < len(uploaded_couriers) - 1: time.sleep(4)
                except Exception as e:
                    st.error(f"AI parsing failure on {file.name}: {e}")
            progress_bar.progress((idx + 1) / len(uploaded_couriers))

    # --- 4. ENGINE MATH & CONSOLIDATION ---
    if all_shipment_rows:
        if debug_log:
            with st.expander("🛠️ Data Extraction Diagnostics (Check Mapped Columns)"):
                for log_msg in debug_log:
                    st.write(log_msg)
                    
        df_master = pd.DataFrame(all_shipment_rows)
        country_costs = df_master.groupby('country')['cost'].sum().to_dict()
        carrier_costs = df_master.groupby('carrier')['cost'].sum().sort_values(ascending=False).to_dict()
        
        total_logistics_spend = sum(country_costs.values())
        total_global_revenue = sum(revenue_dict.values())
        avg_cost_to_serve = (total_logistics_spend / total_global_revenue * 100) if total_global_revenue > 0 else 0.0
        
        ordered_countries = ["Nemčija", "Italija", "Slovenija", "Francija", "Kuwait (Oxygen)", "OSTALO", "Nizozemska", "Španija", "Belgija", "Švica", "Avstrija", "Hrvaška", "Luksemburg"]
        chart_rev_data = [round(revenue_dict.get(c, 0.0), 2) for c in ordered_countries]
        chart_log_data = [round(country_costs.get(c, 0.0), 2) for c in ordered_countries]
        
        chart_carrier_labels = list(carrier_costs.keys())
        chart_carrier_data = [round(v, 2) for v in carrier_costs.values()]
        
        table_rows_html = ""
        for c in ordered_countries:
            rev, log = revenue_dict.get(c, 0.0), country_costs.get(c, 0.0)
            pct = (log / rev * 100) if rev > 0 else 0.0
            badge = "badge-green" if pct < 10 else "badge-yellow" if pct < 20 else "badge-red"
            table_rows_html += f'<tr><td>{c}</td><td class="num-col">€{rev:,.2f}</td><td class="num-col">€{log:,.2f}</td><td class="num-col"><span class="{badge}">{pct:.2f}%</span></td></tr>'

        html_dashboard_code = f"""
        <!DOCTYPE html><html><head><script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f1f5f9; color: #1e293b; margin:0; padding:10px; }}
            .kpi-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 25px; }}
            .kpi-card {{ background: white; padding: 20px; border-radius: 12px; border-left: 6px solid #3b82f6; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            .kpi-card h3 {{ margin: 0 0 5px 0; color: #64748b; font-size: 13px; text-transform: uppercase; }}
            .kpi-card .value {{ margin: 0; font-size: 28px; font-weight: 800; color: #0f172a; }}
            .charts-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 25px; }}
            .chart-container {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            .chart-container h2 {{ margin: 0 0 15px 0; font-size: 15px; color: #0f172a; border-bottom: 2px solid #f1f5f9; padding-bottom: 10px; }}
            .table-container {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            .data-table {{ width: 100%; border-collapse: collapse; }}
            .data-table th {{ background: #f8fafc; padding: 12px; text-align: left; font-size: 12px; color: #475569; border-bottom: 2px solid #e2e8f0; }}
            .data-table td {{ padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 13px; font-weight: 500; }}
            .num-col {{ font-family: monospace; font-size: 14px; text-align: right; }}
            .badge-green {{ background: #dcfce7; color: #166534; padding: 3px 8px; border-radius: 4px; font-weight: bold; }}
            .badge-yellow {{ background: #fef9c3; color: #854d0e; padding: 3px 8px; border-radius: 4px; font-weight: bold; }}
            .badge-red {{ background: #fee2e2; color: #991b1b; padding: 3px 8px; border-radius: 4px; font-weight: bold; }}
        </style></head>
        <body>
            <div class="kpi-row">
                <div class="kpi-card" style="border-left-color: #10b981;"><h3>Total Global Revenue</h3><p class="value">€{total_global_revenue:,.2f}</p></div>
                <div class="kpi-card" style="border-left-color: #ef4444;"><h3>Total Logistics Spend</h3><p class="value">€{total_logistics_spend:,.2f}</p></div>
                <div class="kpi-card" style="border-left-color: #8b5cf6;"><h3>Average Cost-to-Serve</h3><p class="value">{avg_cost_to_serve:.2f}%</p></div>
            </div>
            <div class="charts-row">
                <div class="chart-container"><h2>Revenue Distribution</h2><canvas id="revChart"></canvas></div>
                <div class="chart-container"><h2>Logistics Distribution</h2><canvas id="logChart"></canvas></div>
                <div class="chart-container"><h2>Carrier Budget Allocation</h2><canvas id="carrierChart"></canvas></div>
            </div>
            <div class="table-container">
                <h2>Margin Performance Ledger</h2>
                <table class="data-table">
                    <thead><tr><th>Market / Region</th><th style="text-align: right;">Revenue</th><th style="text-align: right;">Logistics Costs</th><th style="text-align: right;">Cost-to-Serve %</th></tr></thead>
                    <tbody>{table_rows_html}</tbody>
                </table>
            </div>
            <script>
                const l13 = {json.dumps(ordered_countries)};
                const c13 = ['#3b82f6', '#10b981', '#6366f1', '#f59e0b', '#14b8a6', '#94a3b8', '#84cc16', '#ef4444', '#8b5cf6', '#0ea5e9', '#d946ef', '#f97316', '#f43f5e'];
                new Chart(document.getElementById('revChart'), {{type: 'pie', data: {{labels: l13, datasets: [{{data: {json.dumps(chart_rev_data)}, backgroundColor: c13}}]}}, options: {{plugins: {{legend: {{display: false}}}}}} }});
                new Chart(document.getElementById('logChart'), {{type: 'pie', data: {{labels: l13, datasets: [{{data: {json.dumps(chart_log_data)}, backgroundColor: c13}}]}}, options: {{plugins: {{legend: {{display: false}}}}}} }});
                new Chart(document.getElementById('carrierChart'), {{type: 'doughnut', data: {{labels: {json.dumps(chart_carrier_labels)}, datasets: [{{data: {json.dumps(chart_carrier_data)}, backgroundColor: ['#0f172a', '#2563eb', '#dc2626', '#16a34a', '#eab308', '#9333ea', '#0ea5e9', '#4f46e5', '#475569', '#cbd5e1']}}]}}, options: {{cutout: '55%', plugins: {{legend: {{display: false}}}}}} }});
            </script>
        </body></html>
        """
        st.subheader("📊 Live Interactive Executive Dashboard")
        components.html(html_dashboard_code, height=950, scrolling=True)
        
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df_master.to_excel(writer, index=False, sheet_name='Master_Logistics_Ledger')
        st.download_button("Download Integrated Monthly Excel Audit", out.getvalue(), "verified_monthly_logistics_audit.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
