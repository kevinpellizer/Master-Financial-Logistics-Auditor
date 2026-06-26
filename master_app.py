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
    
    match = re.match(r'^([A-Z]{2})[\s\-\_]*\d+', clean)
    if match:
        prefix = match.group(1)
        if prefix in COUNTRY_MAP: return COUNTRY_MAP[prefix]

    if clean in COUNTRY_MAP: return COUNTRY_MAP[clean]
    for k, v in COUNTRY_MAP.items():
        if clean == v.upper() or clean == k: return v
        
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
            
    try: return float(clean_str)
    except: return 0.0

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
    reconciliation_log = [] # Stores data for the Math Check

    # --- A: REVENUE DATA ---
    if uploaded_revenue:
        with st.spinner("Parsing revenue matrices..."):
            try:
                df_rev = pd.read_csv(uploaded_revenue) if uploaded_revenue.name.endswith('.csv') else pd.read_excel(uploaded_revenue)
                df_rev.columns = [str(c).strip().lower() for c in df_rev.columns]
                c_col = next((c for c in df_rev.columns if any(x in c for x in ['country', 'drz', 'drž', 'mkt', 'code', 'kod'])), df_rev.columns[0])
                v_col = next((c for c in df_rev.columns if any(x in c for x in ['revenue', 'promet', 'total', 'znesek', 'neto', 'eur'])), df_rev.columns[-1])
                for _, row in df_rev.iterrows():
                    revenue_dict[standardize_country(row[c_col])] += parse_financial_value(row[v_col])
            except Exception as e: st.error(f"Revenue Error: {e}")

    # --- B: LTL/FTL TRACKER ---
    if uploaded_ltl:
        with st.spinner("Extracting heavy freight entries..."):
            try:
                df_ltl = pd.read_csv(uploaded_ltl) if uploaded_ltl.name.endswith('.csv') else pd.read_excel(uploaded_ltl)
                df_ltl.columns = [str(c).strip().lower() for c in df_ltl.columns]
                c_col = next((c for c in df_ltl.columns if any(x in c for x in ['country', 'drz', 'drž', 'dest', 'kraj', 'trg'])), None)
                m_col = next((c for c in df_ltl.columns if any(x in c for x in ['carrier', 'prevoznik', 'partner', 'dostava'])), None)
                v_col = next((c for c in df_ltl.columns if any(x in c for x in ['cost', 'cena', 'znesek', 'billed', 'neto', 'eur', 'vrednost'])), None)
                if c_col and v_col:
                    for _, row in df_ltl.iterrows():
                        all_shipment_rows.append({
                            'country': standardize_country(row[c_col]),
                            'carrier': str(row[m_col]).strip().upper() if m_col and pd.notna(row[m_col]) else "MANUAL_LTL",
                            'cost': parse_financial_value(row[v_col]),
                            'source': uploaded_ltl.name
                        })
            except Exception as e: st.error(f"LTL Error: {e}")

    # --- C: COURIER INVOICES (GEMINI AI) ---
    if uploaded_couriers and api_key:
        progress_bar = st.progress(0)
        for idx, file in enumerate(uploaded_couriers):
            with st.spinner(f"AI scanning: {file.name}..."):
                try:
                    p = (
                        "Extract every single shipment line-by-line. Use ONLY these exact keys: 'tracking_nr', 'country', 'carrier', 'cost'. "
                        "The 'cost' MUST be the TOTAL NET AMOUNT. EXCLUDE VAT/Taxes. "
                        "Crucially, find the total net invoice amount at the bottom of the document and save it under the key 'invoice_net_total'. "
                        "Return strictly as a single JSON object."
                    )
                    file_bytes = file.getvalue()
                    response = model.generate_content([p, {"mime_type": file.type, "data": file_bytes}])
                    
                    # Safe multi-line string block extraction logic (Avoids Markdown copy-paste bugs)
                    raw_text = response.text.strip()
                    marker = "`" * 3
                    
                    if marker + "json" in raw_text: 
                        raw_text = raw_text.split(marker + "json")[1].split(marker)[0].strip()
                    elif marker in raw_text: 
                        raw_text = raw_text.split(marker)[1].split(marker)[0].strip()
                        
                    data = json.loads(raw_text)
                    
                    # Math Reconciliation Logic
                    file_net_total = parse_financial_value(str(data.get('invoice_net_total', 0)))
                    file_extracted_sum = sum(parse_financial_value(str(s.get('cost', 0))) for s in data.get('shipments', []))
                    reconciliation_log.append({
                        'file': file.name,
                        'invoice_total': file_net_total,
                        'extracted_sum': file_extracted_sum,
                        'diff': abs(file_net_total - file_extracted_sum)
                    })
                    
                    for s in data.get('shipments', []):
                        all_shipment_rows.append({
                            'country': standardize_country(s.get('country')),
                            'carrier': str(s.get('carrier', file.name.split('.')[0])).strip().upper(),
                            'cost': parse_financial_value(str(s.get('cost', 0))),
                            'source': file.name
                        })
                    if idx < len(uploaded_couriers) - 1: time.sleep(4)
                except Exception as e: st.error(f"AI parsing failure on {file.name}: {e}")
            progress_bar.progress((idx + 1) / len(uploaded_couriers))

    # --- 4. DATA CONSOLIDATION & HTML GENERATION ---
    if all_shipment_rows:
        df_master = pd.DataFrame(all_shipment_rows)
        
        # Visual Math Verification Dashboard
        if reconciliation_log:
            st.subheader("⚖️ AI Audit Verification (Math Check)")
            for rec in reconciliation_log:
                if rec['diff'] <= 1.00: # We allow a 1 euro tolerance for rounding
                    st.success(f"✅ **{rec['file']}**: Math checks out! (Invoice Net: €{rec['invoice_total']:,.2f} | Rows Added: €{rec['extracted_sum']:,.2f})")
                else:
                    st.error(f"⚠️ **{rec['file']}**: Discrepancy of €{rec['diff']:,.2f}! (Invoice Net: €{rec['invoice_total']:,.2f} | Rows Added: €{rec['extracted_sum']:,.2f})")
            st.divider()

        country_costs = df_master.groupby('country')['cost'].sum().to_dict()
        carrier_costs = df_master.groupby('carrier')['cost'].sum().sort_values(ascending=False).to_dict()
        
        total_logistics_spend = sum(country_costs.values())
        total_global_revenue = sum(revenue_dict.values())
        avg_cost_to_serve = (total_logistics_spend / total_global_revenue * 100) if total_global_revenue > 0 else 0.0
        
        ordered_countries = ["Nemčija", "Italija", "Slovenija", "Francija", "Kuwait (Oxygen)", "OSTALO", "Nizozemska", "Španija", "Belgija", "Švica", "Avstrija", "Hrvaška", "Luksemburg"]
        chart_rev_data = [round(revenue_dict.get(c, 0.0), 2) for c in ordered_countries]
        chart_log_data = [round(country_costs.get(c, 0.0), 2) for c in ordered_countries]
        chart_carrier_labels, chart_carrier_data = list(carrier_costs.keys()), [round(v, 2) for v in carrier_costs.values()]
        
        # Build Left Margin Table
        table_rows_html = ""
        for c in ordered_countries:
            rev, log = revenue_dict.get(c, 0.0), country_costs.get(c, 0.0)
            pct = (log / rev * 100) if rev > 0 else 0.0
            badge = "badge-green" if pct < 10 else "badge-yellow" if pct < 20 else "badge-red"
            table_rows_html += f'<tr><td>{c}</td><td class="num-col">€{rev:,.2f}</td><td class="num-col">€{log:,.2f}</td><td class="num-col"><span class="{badge}">{pct:.2f}%</span></td></tr>'

        # Build Top 5 Projects Table (Right Side)
        top_5_html = ""
        top_5_df = df_master.nlargest(5, 'cost')
        for _, row in top_5_df.iterrows():
            top_5_html += f"<tr><td>{row['carrier']}<span class='client-tag'>{row['source'].replace('.xlsx','').replace('.csv','')}</span></td><td>{row['country']}</td><td class='cost-col'>€{row['cost']:,.2f}</td></tr>"

        html_dashboard_code = f"""
        <!DOCTYPE html><html><head><script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f1f5f9; color: #1e293b; margin:0; padding:40px; }}
            .dashboard {{ max-width: 1400px; margin: 0 auto; }}
            .header {{ background: #0f172a; color: white; padding: 30px 40px; border-radius: 16px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); }}
            .header h1 {{ margin: 0 0 8px 0; font-size: 28px; }}
            .header p {{ margin: 0; color: #94a3b8; font-size: 16px; }}
            .status-badge {{ background: #10b981; color: white; padding: 8px 16px; border-radius: 20px; font-size: 14px; font-weight: bold; text-transform: uppercase; }}
            .kpi-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 25px; margin-bottom: 35px; }}
            .kpi-card {{ background: white; padding: 30px; border-radius: 16px; border-left: 6px solid #3b82f6; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
            .kpi-card h3 {{ margin: 0 0 10px 0; color: #64748b; font-size: 14px; text-transform: uppercase; }}
            .kpi-card .value {{ margin: 0; font-size: 34px; font-weight: 800; color: #0f172a; }}
            .charts-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 35px; }}
            .chart-container {{ background: white; padding: 25px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
            .chart-container h2 {{ margin: 0 0 20px 0; font-size: 16px; color: #0f172a; border-bottom: 2px solid #f1f5f9; padding-bottom: 15px; }}
            .tables-split-row {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 30px; margin-bottom: 40px; }}
            .table-container {{ background: white; padding: 30px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
            .table-container h2 {{ margin: 0 0 20px 0; font-size: 18px; border-bottom: 2px solid #f1f5f9; padding-bottom: 15px; }}
            .data-table {{ width: 100%; border-collapse: collapse; }}
            .data-table th {{ background: #f8fafc; padding: 14px; text-align: left; font-size: 12px; color: #475569; border-bottom: 2px solid #e2e8f0; text-transform: uppercase; }}
            .data-table td {{ padding: 14px; border-bottom: 1px solid #e2e8f0; font-size: 14px; font-weight: 500; }}
            .num-col {{ font-family: monospace; font-size: 14px; text-align: right; }}
            .cost-col {{ color: #dc2626; font-weight: 700; text-align: right; font-family: monospace; font-size: 15px; }}
            .badge-green {{ background: #dcfce7; color: #166534; padding: 4px 10px; border-radius: 6px; font-weight: bold; }}
            .badge-yellow {{ background: #fef9c3; color: #854d0e; padding: 4px 10px; border-radius: 6px; font-weight: bold; }}
            .badge-red {{ background: #fee2e2; color: #991b1b; padding: 4px 10px; border-radius: 6px; font-weight: bold; }}
            .client-tag {{ font-size: 11px; color: #475569; font-weight: 700; background: #f1f5f9; padding: 3px 8px; border-radius: 4px; display: block; margin-top: 4px; max-width: max-content; }}
        </style></head>
        <body>
        <div class="dashboard">
            <div class="header">
                <div><h1>KingsBox | Financial Margin Report</h1><p>Logistics Cost-to-Serve vs Revenue Analysis</p></div>
                <div class="status-badge">Auto-Generated</div>
            </div>
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
            <div class="tables-split-row">
                <div class="table-container">
                    <h2>Margin Impact Analysis (Cost-to-Serve %)</h2>
                    <table class="data-table">
                        <thead><tr><th>Market / Region</th><th style="text-align: right;">Revenue</th><th style="text-align: right;">Logistics Costs</th><th style="text-align: right;">% Share</th></tr></thead>
                        <tbody>{table_rows_html}</tbody>
                    </table>
                </div>
                <div class="table-container">
                    <h2>Top 5 High-Freight Individual Shipments</h2>
                    <table class="data-table">
                        <thead><tr><th>Carrier / Source</th><th>Country</th><th style="text-align: right;">Freight Billed</th></tr></thead>
                        <tbody>{top_5_html}</tbody>
                    </table>
                </div>
            </div>
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
        
        # Dual Export Buttons Side-by-Side
        st.subheader("📥 Export Reports")
        col_exp1, col_exp2 = st.columns(2)
        
        with col_exp1:
            out = BytesIO()
            with pd.ExcelWriter(out, engine='openpyxl') as writer:
                df_master.to_excel(writer, index=False, sheet_name='Master_Logistics_Ledger')
            st.download_button(
                label="📁 Download Raw Excel Ledger",
                data=out.getvalue(),
                file_name="Verified_Monthly_Audit.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
        with col_exp2:
            st.download_button(
                label="🌐 Download Trello HTML Dashboard",
                data=html_dashboard_code.encode('utf-8'),
                file_name="KingsBox_Monthly_Dashboard.html",
                mime="text/html",
                use_container_width=True
            )
