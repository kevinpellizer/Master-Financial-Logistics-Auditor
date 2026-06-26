import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import time
from io import BytesIO
import streamlit.components.v1 as components

# --- 1. SETUP & AUTH ---
st.set_page_config(page_title="KingsBox Audit App", layout="wide")

# Get token from environment
api_token = os.environ.get("GEMINI_API_KEY")

# Auth configuration logic
if api_token and api_token.startswith("AQ."):
    genai.configure(api_key=None) 
    os.environ["GOOGLE_API_KEY"] = api_token
else:
    genai.configure(api_key=api_token)

model = genai.GenerativeModel('gemini-1.5-flash')

# Helper functions
def parse_financial_value(val):
    try: return float(str(val).replace('€', '').replace(',', '').strip())
    except: return 0.0

def standardize_country(c):
    if not c: return "OSTALO"
    c = str(c).strip().lower()
    mapping = {"germany": "Nemčija", "italy": "Italija", "slovenia": "Slovenija", "france": "Francija", "kuwait": "Kuwait (Oxygen)", "netherlands": "Nizozemska", "spain": "Španija", "belgium": "Belgija", "switzerland": "Švica", "austria": "Avstrija", "croatia": "Hrvaška", "luxembourg": "Luksemburg"}
    return mapping.get(c, "OSTALO")

revenue_dict = {"Nemčija": 50000, "Italija": 30000, "Slovenija": 20000, "Francija": 15000, "Kuwait (Oxygen)": 10000, "OSTALO": 5000, "Nizozemska": 12000, "Španija": 8000, "Belgija": 7000, "Švica": 6000, "Avstrija": 9000, "Hrvaška": 4000, "Luksemburg": 3000}

st.title("KingsBox Logistics Auditor")
uploaded_files = st.file_uploader("Upload Invoice PDFs", type=['pdf', 'png', 'jpg'], accept_multiple_files=True)

# Session State for persistence
if 'audit_success' not in st.session_state: st.session_state.audit_success = False

if uploaded_files and st.button("Start Audit"):
    all_shipment_rows = []
    reconciliation_log = []
    progress_bar = st.progress(0)
    
    for idx, file in enumerate(uploaded_files):
        with st.spinner(f"Auditing {file.name}..."):
            success = False
            last_error = ""
            for attempt in range(3):
                try:
                    fb = file.getvalue()
                    prompt = "Extract shipments as JSON with keys: tracking_nr, country, cost. Total invoice net is invoice_net_total. Return ONLY raw JSON."
                    response = model.generate_content([prompt, {"mime_type": file.type, "data": fb}])
                    raw_text = response.text.replace("```json", "").replace("```", "").strip()
                    
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
                    
                    for s in data.get('shipments', []):
                        all_shipment_rows.append({
                            'country': standardize_country(s.get('country')),
                            'carrier': str(s.get('carrier', file.name.split('.')[0])).strip().upper(),
                            'cost': parse_financial_value(str(s.get('cost', 0))),
                            'source': file.name
                        })
                    success = True
                    break
                except Exception as e:
                    last_error = str(e)
                    time.sleep(3)
            
            if not success: st.error(f"Failed {file.name}: {last_error}")
            progress_bar.progress((idx + 1) / len(uploaded_files))

    if all_shipment_rows:
        df_master = pd.DataFrame(all_shipment_rows)
        country_costs = df_master.groupby('country')['cost'].sum().to_dict()
        carrier_costs = df_master.groupby('carrier')['cost'].sum().sort_values(ascending=False).to_dict()
        total_logistics_spend = sum(country_costs.values())
        total_global_revenue = sum(revenue_dict.values())
        avg_cost_to_serve = (total_logistics_spend / total_global_revenue * 100) if total_global_revenue > 0 else 0.0
        
        ordered_countries = ["Nemčija", "Italija", "Slovenija", "Francija", "Kuwait (Oxygen)", "OSTALO", "Nizozemska", "Španija", "Belgija", "Švica", "Avstrija", "Hrvaška", "Luksemburg"]
        chart_rev_data = [round(revenue_dict.get(c, 0.0), 2) for c in ordered_countries]
        chart_log_data = [round(country_costs.get(c, 0.0), 2) for c in ordered_countries]
        chart_carrier_labels, chart_carrier_data = list(carrier_costs.keys()), [round(v, 2) for v in carrier_costs.values()]
        
        table_rows_html = "".join([f'<tr><td>{c}</td><td class="num-col">€{revenue_dict.get(c, 0.0):,.2f}</td><td class="num-col">€{country_costs.get(c, 0.0):,.2f}</td></tr>' for c in ordered_countries])
        top_5_html = "".join([f"<tr><td>{row['carrier']}</td><td>{row['country']}</td><td class='cost-col'>€{row['cost']:,.2f}</td></tr>" for _, row in df_master.nlargest(5, 'cost').iterrows()])

        html_dashboard_code = f"""
        <!DOCTYPE html><html><head><script src="https://cdn.jsdelivr.net/npm/chart.js"></script></head>
        <body><div class="dashboard">
            <h1>KingsBox Financial Audit</h1>
            <div class="kpi-row"><div>Rev: €{total_global_revenue:,.2f}</div><div>Log: €{total_logistics_spend:,.2f}</div></div>
            <table class="data-table"><tbody>{table_rows_html}</tbody></table>
        </div></body></html>
        """
        
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer: df_master.to_excel(writer, index=False)
        st.session_state.processed_html = html_dashboard_code
        st.session_state.processed_excel = out.getvalue()
        st.session_state.reconciliation_log = reconciliation_log
        st.session_state.audit_success = True

if st.session_state.get('audit_success', False):
    st.subheader("📊 Audit Results")
    components.html(st.session_state.processed_html, height=600)
    st.download_button("Download Excel", st.session_state.processed_excel, "Audit.xlsx")
