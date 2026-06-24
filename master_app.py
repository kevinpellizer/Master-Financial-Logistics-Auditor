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
    reconciliation_log = [] # 🚨 NEW: Stores data for the Math Check

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
                    
                    raw_text = response.text.strip()
                    if "
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1
