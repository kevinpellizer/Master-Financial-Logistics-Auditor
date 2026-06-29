import streamlit as st
import pandas as pd
import json
import os
import base64
import requests
import time
from io import BytesIO

# --- 1. SETUP ---
st.set_page_config(page_title="PDF to Excel Extractor", layout="wide", page_icon="📄")

# Strip quotes or spaces that might have accidentally been pasted into Render
env_token = os.environ.get("GEMINI_API_KEY", "").replace('"', '').replace("'", "").strip()

def clean_cost(val):
    """Converts European currency strings to math-friendly floats"""
    try:
        if pd.isna(val) or val == "": return 0.0
        if isinstance(val, (int, float)): return float(val)
        val = str(val).replace('€', '').replace(' ', '').replace('\xa0', '').strip()
        if ',' in val and '.' in val:
            if val.rfind(',') > val.rfind('.'): 
                val = val.replace('.', '').replace(',', '.')
            else: 
                val = val.replace(',', '')
        elif ',' in val:
            val = val.replace(',', '.')
        return float(val)
    except:
        return 0.0

# --- 2. USER INTERFACE ---
st.title("📄 Step 1: PDF to Excel Extractor")

# 🚨 THE OVERRIDE BOX 🚨
st.info("💡 **Debugging Mode:** If Render is failing, paste your API key in the box below to force it to work for this session.")
manual_key = st.text_input("Paste Google API Key", type="password")

# Decide which key to use
active_key = manual_key if manual_key else env_token

if not active_key:
    st.error("⚠️ No API Key provided! Please enter one above or check your Render environment variables.")

uploaded_files = st.file_uploader("Upload Courier Invoices (PDF)", type=['pdf', 'png', 'jpg'], accept_multiple_files=True)

# --- 3. PROCESSING ---
if st.button("Extract to Excel", type="primary") and uploaded_files and active_key:
    all_shipments = []
    reconciliation_log = []
    progress_bar = st.progress(0)
    
    # Setup Direct API URL
    base_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    headers = {"Content-Type": "application/json"}
    
    # Send the key correctly as a standard API Key query parameter
    url = f"{base_url}?key={active_key}"

    for idx, file in enumerate(uploaded_files):
        with st.spinner(f"Reading {file.name}..."):
            try:
                # 1. Prepare the file
                file_bytes = file.getvalue()
                b64_file = base64.b64encode(file_bytes).decode('utf-8')
                mime_type = "application/pdf" if file.name.lower().endswith(".pdf") else file.type
                if not mime_type: mime_type = "application/pdf"
                
                # 2. Prepare the prompt and payload
                prompt = """
                Analyze this shipping invoice. Extract every individual shipment line.
                For each shipment, extract:
                1. tracking_nr (Številka tovornega lista)
                2. country (Prejemnik/naslov. Provide the 2-letter country code like DE, AT, CH. If not found, output the full name).
                3. cost (Total NET cost for this shipment, including base rate + surcharges. EXCLUDE VAT/DDV).
                
                Also, find the total NET invoice amount at the bottom of the document (excluding VAT/DDV).
                
                Return ONLY a valid JSON object matching this exact structure:
                {
                  "invoice_net_total": 123.45,
                  "shipments": [
                    {"tracking_nr": "12345", "country": "DE", "cost": 10.50}
                  ]
                }
                """
                
                payload = {
                    "contents": [{
                        "parts": [
                            {"text": prompt},
                            {"inlineData": {"mimeType": mime_type, "data": b64_file}}
                        ]
                    }],
                    "generationConfig": {
                        "responseMimeType": "application/json" 
                    },
                    "safetySettings": [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                    ]
                }
                
                # 3. Request Google API
                response = requests.post(url, headers=headers, json=payload)
                
                # 🚨 ERROR TRANSLATOR 🚨
                if response.status_code != 200:
                    st.error(f"🛑 Google API Error [{response.status_code}] on {file.name}")
                    try:
                        error_details = response.json()
                        st.warning(f"**Google says:** {error_details['error']['message']}")
                    except:
                        st.code(response.text)
                    continue
                    
                resp_data = response.json()
                
                if 'candidates' not in resp_data or not resp_data['candidates']:
                    st.error(f"🛑 Google blocked {file.name} (Likely due to privacy filters on an address).")
                    continue
                    
                # 5. Extract and clean JSON
                raw_text = resp_data['candidates'][0]['content']['parts'][0]['text']
                raw_text = raw_text.strip()
                if raw_text.startswith("```"):
                    raw_text = raw_text.replace("```json", "").replace("```", "").strip()
                    
                data = json.loads(raw_text)
                
                # 6. Process the numbers
                file_net_total = clean_cost(data.get('invoice_net_total', 0))
                file_extracted_sum = 0.0
                carrier_name = file.name.split('.')[0].upper()
                
                for s in data.get('shipments', []):
                    cost = clean_cost(s.get('cost', 0))
                    file_extracted_sum += cost
                    
                    all_shipments.append({
                        "Source File": file.name,
                        "Carrier": carrier_name,
                        "Tracking Number": str(s.get('tracking_nr', '')),
                        "Country": str(s.get('country', '')).upper(),
                        "Net Cost (€)": cost
                    })
                    
                reconciliation_log.append({
                    'file': file.name,
                    'invoice_total': file_net_total,
                    'extracted_sum': file_extracted_sum,
                    'diff': abs(file_net_total - file_extracted_sum)
                })
                
                if idx < len(uploaded_files) - 1:
                    time.sleep(3)
                    
            except Exception as e:
                st.error(f"🛑 Unexpected Error on {file.name}: {str(e)}")
                
        progress_bar.progress((idx + 1) / len(uploaded_files))

    # --- 4. SHOW RESULTS ---
    if all_shipments:
        st.success("Extraction Complete!")
        
        # Math Check Display
        st.subheader("⚖️ Math Verification")
        for rec in reconciliation_log:
            if rec['diff'] <= 1.00:
                st.success(f"✅ **{rec['file']}**: Math matches! (Invoice Net: €{rec['invoice_total']:,.2f} | Rows Extracted: €{rec['extracted_sum']:,.2f})")
            else:
                st.error(f"⚠️ **{rec['file']}**: Discrepancy of €{rec['diff']:,.2f}. (Invoice Net: €{rec['invoice_total']:,.2f} | Rows Extracted: €{rec['extracted_sum']:,.2f})")
        
        st.divider()
        
        # Data Display
        df_master = pd.DataFrame(all_shipments)
        st.subheader("📊 Extracted Data")
        st.dataframe(df_master, use_container_width=True)
        
        # Download Excel
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df_master.to_excel(writer, index=False, sheet_name='Extracted_Invoices')
            
        st.download_button(
            label="📁 Download Data to Excel",
            data=out.getvalue(),
            file_name="Extracted_Invoices.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
