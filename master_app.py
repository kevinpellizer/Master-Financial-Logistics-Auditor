import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import time
from io import BytesIO
import re
import streamlit.components.v1 as components

# --- 1. SETUP & AUTH ---
st.set_page_config(page_title="KingsBox Audit App", layout="wide", page_icon="📈")

# Smart Authentication: Handles both AIza API keys and AQ OAuth tokens
api_token = os.environ.get("GEMINI_API_KEY", "").strip()

if api_token.startswith("AQ.") or api_token.startswith("ya29."):
    from google.oauth2.credentials import Credentials
    creds = Credentials(token=api_token)
    genai.configure(credentials=creds)
else:
    genai.configure(api_key=api_token)

# Use the stable, fast 1.5 flash model
model = genai.GenerativeModel('gemini-1.5-flash')

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
    # 2. Try partial match (e.g., catching "DE - NEMČIJA")
    for key, val in mapping.items():
        if key in c or c in key: return val
        
    return "OSTALO"

# --- 3. USER INTERFACE ---
st.title("📈 Master Logistics & Margin Auditor")
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

    # C. Process Courier PDFs via AI (Inline Memory Mode)
    if uploaded_couriers and api_token:
        progress_bar = st.progress(0)
        
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
        
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
                    
                    fb = file.getvalue()
                    mime_type = "application/pdf" if file.name.lower().endswith(".pdf") else file.type
                    if not mime_type: mime_type = "application/pdf"
                    
                    # Send data "inline" to bypass Google Cloud Drive permissions error
                    response = model.generate_content(
                        [prompt, {"mime_type": mime_type, "data": fb}],
                        safety_settings=safety_settings
                    )
                    
                    # Clean the response manually (Stripping Markdown)
                    raw_text = response.text.strip()
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
                    st.error(f"AI parsing failure on {file.name}: {str(e)}")
                    
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
        
        # Store Everything in Memory so the buttons don't break the screen
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df_master.to_excel(writer, index=False, sheet_name='Master_Logistics_Ledger')
            
        st.session_state.processed_html = html_dashboard_code
        st.session_state.processed_excel = out.getvalue()
        st.session_state.reconciliation_log = reconciliation_log
        st.session_state.audit_success = True
    else:
        st.error("No valid shipment rows were extracted. Please check the logs.")

# --- 5. RENDER THE SECURE DISPLAY LAYER ---
if st.session_state.get('audit_success', False):
    
    if st.session_state.reconciliation_log:
        st.subheader("⚖️ AI Audit Verification (Math Check)")
        for rec in st.session_state.reconciliation_log:
            # Shortened variable names so the strings never break during copy/paste
            file_name = rec['file']
            inv_total = rec['invoice_total']
            ext_total = rec['extracted_sum']
            diff = rec['diff']
            
            if diff <= 1.00:
                st.success(f"✅ **{file_name}**: Math checks out! (Net: €{inv_total:,.2f} | Added: €{ext_total:,.2f})")
            else:
                st.error(f"⚠️ **{file_name}**: Diff of €{diff:,.2f}! (Net: €{inv_total:,.2f} | Added: €{ext_total:,.2f})")
        st.divider()

    st.subheader("📊 Live Interactive Executive Dashboard")
    components.html(st.session_state.processed_html, height=950, scrolling=True)
    
    st.subheader("📥 Export Reports")
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        st.download_button(
            label="📁 Download Raw Excel Ledger",
            data=st.session_state.processed_excel,
            file_name="Verified_Monthly_Audit.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
    with col_exp2:
        st.download_button(
            label="🌐 Download Trello HTML Dashboard",
            data=st.session_state.processed_html.encode('utf-8'),
            file_name="KingsBox_Monthly_Dashboard.html",
            mime="text/html",
            use_container_width=True
        )
