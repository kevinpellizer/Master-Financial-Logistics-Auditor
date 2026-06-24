import streamlit as st
import google.generativeai as genai
import os
import pandas as pd
import json
import time  
from io import BytesIO
import streamlit.components.v1 as components

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="Master Logistics & Margin Auditor", layout="wide", page_icon="📈")

# Initialize Gemini API
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    st.warning("⚠️ GEMINI_API_KEY not found in environment variables. Please set it to enable PDF/Image parsing.")
else:
    genai.configure(api_key=api_key)

# Using stable production multi-modal model
model = genai.GenerativeModel('gemini-1.5-flash')

st.title("📈 Master Logistics & Margin Auditor")
st.markdown("Upload your monthly documents below to automatically generate your interactive financial dashboard.")

# --- DATA DICTIONARIES & MAPPING ---
TARGET_COUNTRIES = ["IT", "SI", "DE", "AT", "FR", "ES", "NL", "BE", "LU", "CH", "HR", "KW", "OSTALO"]
COUNTRY_MAP = {
    'IT': 'Italija', 'ITA': 'Italija',
    'SI': 'Slovenija', 'SVN': 'Slovenija',
    'DE': 'Nemčija', 'DEU': 'Nemčija',
    'AT': 'Avstrija', 'AUT': 'Avstrija',
    'FR': 'Francija', 'FRA': 'Francija',
    'ES': 'Španija', 'ESP': 'Španija',
    'NL': 'Nizozemska', 'NLD': 'Nizozemska',
    'BE': 'Belgija', 'BEL': 'Belgija',
    'LU': 'Luksemburg', 'LUX': 'Luksemburg',
    'CH': 'Švica', 'CHE': 'Švica',
    'HR': 'Hrvaška', 'HRV': 'Hrvaška',
    'KW': 'Kuwait (Oxygen)', 'KWT': 'Kuwait (Oxygen)'
}

def standardize_country(val):
    if pd.isna(val):
        return "OSTALO"
    clean = str(val).strip().upper()
    return COUNTRY_MAP.get(clean, "OSTALO")

# --- 2. MULTI-SOURCE UPLOAD CONSOLE ---
col_u1, col_u2, col_u3 = st.columns(3)

with col_u1:
    st.subheader("1. Courier Invoices")
    uploaded_couriers = st.file_uploader("Upload Courier PDFs / Images", type=['pdf', 'png', 'jpg'], accept_multiple_files=True, key="couriers")

with col_u2:
    st.subheader("2. Heavy Freight Tracker")
    uploaded_ltl = st.file_uploader("Upload Manual LTL/FTL Sheet", type=['xlsx', 'xls', 'csv'], key="ltl")

with col_u3:
    st.subheader("3. Market Revenue Report")
    uploaded_revenue = st.file_uploader("Upload Monthly Revenue Sheet", type=['xlsx', 'xls', 'csv'], key="revenue")

# --- 3. PROCESSING PIPELINE ---
if st.button("🚀 Execute Global Monthly Consolidation", type="primary", use_container_width=True):
    
    # Storage structures
    all_shipment_rows = [] # Will contain columns: country, carrier, cost, source
    revenue_dict = {name: 0.0 for name in COUNTRY_MAP.values()}
    revenue_dict["OSTALO"] = 0.0
    
    # --- STEP A: PROCESS REVENUE DATA ---
    if uploaded_revenue:
        with st.spinner("Parsing revenue matrices..."):
            try:
                if uploaded_revenue.name.endswith('.csv'):
                    df_rev = pd.read_csv(uploaded_revenue)
                else:
                    df_rev = pd.read_excel(uploaded_revenue)
                
                # Normalize column headers
                df_rev.columns = [str(c).strip().lower() for c in df_rev.columns]
                
                # Dynamic matching for country codes and values
                country_col = next((c for c in df_rev.columns if 'country' in c or 'drzava' in c or 'mkt' in c or 'code' in c or df_rev[c].astype(str).str.len().max() <= 4), df_rev.columns[0])
                value_col = next((c for c in df_rev.columns if 'revenue' in c or 'promet' in c or 'total' in c or 'znesek' in c or df_rev[c].dtype in ['float64', 'int64']), df_rev.columns[-1])
                
                for _, row in df_rev.iterrows():
                    ctry = standardize_country(row[country_col])
                    val = float(str(row[value_col]).replace('€', '').replace('.', '').replace(',', '.').strip()) if pd.notna(row[value_col]) else 0.0
                    revenue_dict[ctry] += val
                st.toast("✅ Market revenue loaded successfully!")
            except Exception as e:
                st.error(f"Error parsing Revenue sheet: {e}")
    else:
        st.info("💡 No revenue sheet uploaded. Financial tables will calculate Cost-to-Serve metrics based on zero-revenue baselines.")

    # --- STEP B: PROCESS MANUAL LTL/FTL TRACKER ---
    if uploaded_ltl:
        with st.spinner("Extracting heavy freight entries..."):
            try:
                if uploaded_ltl.name.endswith('.csv'):
                    df_ltl = pd.read_csv(uploaded_ltl)
                else:
                    df_ltl = pd.read_excel(uploaded_ltl)
                
                df_ltl.columns = [str(c).strip().lower() for c in df_ltl.columns]
                
                # Locate columns dynamically
                c_col = next((c for c in df_ltl.columns if 'country' in c or 'drzava' in c or 'dest' in c), None)
                m_col = next((c for c in df_ltl.columns if 'carrier' in c or 'prevoznik' in c), None)
                v_col = next((c for c in df_ltl.columns if 'cost' in c or 'cena' in c or 'znesek' in c), None)
                
                if c_col and v_col:
                    for _, row in df_ltl.iterrows():
                        ctry = standardize_country(row[c_col])
                        carrier = str(row[m_col]).strip().upper() if m_col and pd.notna(row[m_col]) else "MANUAL_LTL"
                        cost_val = float(str(row[v_col]).replace('€', '').replace('.', '').replace(',', '.').strip()) if pd.notna(row[v_col]) else 0.0
                        
                        all_shipment_rows.append({
                            'country': ctry,
                            'carrier': carrier,
                            'cost': cost_val,
                            'source': uploaded_ltl.name
                        })
                    st.toast("✅ Heavy LTL Freight entries merged!")
                else:
                    st.error("Could not dynamically map LTL sheet columns. Ensure headers include 'Country', 'Carrier', and 'Cost'.")
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
                        "The 'country' MUST be the 2-letter or 3-letter destination code. "
                        "The 'carrier' MUST be the name of the shipping company/courier (e.g., DHL, DPD, FedEx, BRT, GW, etc.) found on the invoice document header. "
                        "CRITICAL FOR COST: The 'cost' MUST be the TOTAL NET AMOUNT for that specific shipment row. Add the base rate plus all fuel, toll, or remote surcharges. "
                        "STRICTLY EXCLUDE any VAT / DDV / Taxes from the math. "
                        "Also find the total net invoice summary amount ('invoice_net_total'). Return strictly as a single JSON object."
                    )
                    
                    file_bytes = file.getvalue()
                    response = model.generate_content([p, {"mime_type": file.type, "data": file_bytes}])
                    
                    raw_text = response.text.replace("```json", "").replace("
```", "").strip()
                    data = json.loads(raw_text)
                    
                    shipments = data.get('shipments', [])
                    for s in shipments:
                        all_shipment_rows.append({
                            'country': standardize_country(s.get('country')),
                            'carrier': str(s.get('carrier', file.name.split('.')[0])).strip().upper(),
                            'cost': float(str(s.get('cost', 0)).replace(',', '.')),
                            'source': file.name
                        })
                        
                    # Rate limiting protection
                    if idx < len(uploaded_couriers) - 1:
                        time.sleep(4)
                except Exception as e:
                    st.error(f"AI parsing failure on {file.name}: {e}")
            progress_bar.progress((idx + 1) / len(uploaded_couriers))

    # --- 4. ENGINE MATH & CONSOLIDATION ---
    if all_shipment_rows:
        df_master = pd.DataFrame(all_shipment_rows)
        
        # Aggregate financial views
        country_costs = df_master.groupby('country')['cost'].sum().to_dict()
        carrier_costs = df_master.groupby('carrier')['cost'].sum().sort_values(ascending=False).to_dict()
        
        total_logistics_spend = sum(country_costs.values())
        total_global_revenue = sum(revenue_dict.values())
        avg_cost_to_serve = (total_logistics_spend / total_global_revenue * 100) if total_global_revenue > 0 else 0.0
        
        # Build strict country summary arrays for charting engines
        ordered_countries = ["Nemčija", "Italija", "Slovenija", "Francija", "Kuwait (Oxygen)", "OSTALO", "Nizozemska", "Španija", "Belgija", "Švica", "Avstrija", "Hrvaška", "Luksemburg"]
        chart_rev_data = [round(revenue_dict.get(c, 0.0), 2) for c in ordered_countries]
        chart_log_data = [round(country_costs.get(c, 0.0), 2) for c in ordered_countries]
        
        # Build carrier arrays
        chart_carrier_labels = list(carrier_costs.keys())
        chart_carrier_data = [round(v, 2) for v in carrier_costs.values()]
        
        # --- 5. THE DYNAMIC HTML GENERATOR ---
        # Generate table rows dynamically
        table_rows_html = ""
        for c in ordered_countries:
            rev = revenue_dict.get(c, 0.0)
            log = country_costs.get(c, 0.0)
            pct = (log / rev * 100) if rev > 0 else 0.0
            
            if pct == 0: badge = "badge-green"
            elif pct < 10: badge = "badge-green"
            elif pct < 20: badge = "badge-yellow"
            else: badge = "badge-red"
            
            table_rows_html += f"""
            <tr>
                <td>{c}</td>
                <td class="num-col">€{rev:,.2f}</td>
                <td class="num-col">€{log:,.2f}</td>
                <td class="num-col"><span class="{badge}">{pct:.2f}%</span></td>
            </tr>
            """

        html_dashboard_code = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f1f5f9; color: #1e293b; margin:0; padding:10px; }}
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
            </style>
        </head>
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
                    <thead>
                        <tr><th>Market / Region</th><th style="text-align: right;">Revenue</th><th style="text-align: right;">Logistics Costs</th><th style="text-align: right;">Cost-to-Serve %</th></tr>
                    </thead>
                    <tbody>
                        {table_rows_html}
                    </tbody>
                </table>
            </div>

            <script>
                const labels13 = {json.dumps(ordered_countries)};
                const colors13 = ['#3b82f6', '#10b981', '#6366f1', '#f59e0b', '#14b8a6', '#94a3b8', '#84cc16', '#ef4444', '#8b5cf6', '#0ea5e9', '#d946ef', '#f97316', '#f43f5e'];
                
                new Chart(document.getElementById('revChart').getContext('2d'), {{
                    type: 'pie', data: {{ labels: labels13, datasets: [{{ data: {json.dumps(chart_rev_data)}, backgroundColor: colors13, borderWidth: 1 }}] }},
                    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
                }});

                new Chart(document.getElementById('logChart').getContext('2d'), {{
                    type: 'pie', data: {{ labels: labels13, datasets: [{{ data: {json.dumps(chart_log_data)}, backgroundColor: colors13, borderWidth: 1 }}] }},
                    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
                }});

                new Chart(document.getElementById('carrierChart').getContext('2d'), {{
                    type: 'doughnut', data: {{ labels: {json.dumps(chart_carrier_labels)}, datasets: [{{ data: {json.dumps(chart_carrier_data)}, backgroundColor: ['#0f172a', '#2563eb', '#dc2626', '#16a34a', '#eab308', '#9333ea', '#0ea5e9', '#4f46e5', '#475569', '#cbd5e1'], borderWidth: 1 }}] }},
                    options: {{ responsive: true, cutout: '55%', plugins: {{ legend: {{ display: false }} }} }}
                }});
            </script>
        </body>
        </html>
        """
        
        # --- 6. RENDER INTERACTIVE VISUAL DISPLAY ---
        st.subheader("📊 Live Interactive Executive Dashboard")
        components.html(html_dashboard_code, height=950, scrolling=True)
        
        # --- 7. EXCEL EXPORT ENGINE ---
        st.subheader("📥 Data Export Services")
        
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df_master.to_excel(writer, index=False, sheet_name='Master_Logistics_Ledger')
            
            # Formulate structured analytical output dataframe
            final_summary_data = []
            for c in ordered_countries:
                rev = revenue_dict.get(c, 0.0)
                log = country_costs.get(c, 0.0)
                final_summary_data.append({
                    'Market/Region': c,
                    'Revenue (€)': rev,
                    'Logistics Cost (€)': log,
                    'Cost-to-Serve (%)': (log/rev*100) if rev > 0 else 0.0
                })
            pd.DataFrame(final_summary_data).to_excel(writer, index=False, sheet_name='Financial_Summary')
            
        st.download_button(
            label="Download Integrated Monthly Excel Audit",
            data=out.getvalue(),
            file_name="verified_monthly_logistics_audit.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    else:
        st.warning("⚠️ No data was processed. Please verify that your files contain matching columns or that the AI could extract rows correctly.")
