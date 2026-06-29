import streamlit as st
import pandas as pd
import json
import os
import base64
import requests

# --- 1. SETUP ---
st.set_page_config(page_title="PDF Reader V1", layout="wide")

# Get the token from Render environment
api_token = os.environ.get("GEMINI_API_KEY", "").strip()

# Helper to clean currency strings into math numbers (e.g. "1.234,56 €" -> 1234.56)
def clean_cost(val):
    try:
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
st.title("Step 1: Direct API PDF Reader")

if not api_token:
    st.warning("⚠️ No API Key found. Please add GEMINI_API_KEY to your Render environment variables.")
elif api_token.startswith("AQ."):
    st.info("ℹ️ Using an AQ Session Token. If you get a 401/403 error, your token has expired (they last 60 mins). Generate a fresh one and update Render.")

uploaded_file = st.file_uploader("Upload ONE Courier Invoice (PDF)", type=['pdf'])

# --- 3. CORE PROCESSING ---
if st.button("Process Invoice") and uploaded_file:
    with st.spinner("Talking directly to Google's servers..."):
        try:
            # 1. Convert PDF to Base64 (Safe for transit)
            pdf_bytes = uploaded_file.getvalue()
            b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
            
            # 2. Setup the Direct HTTP Request (Bypassing the buggy python library)
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
            headers = {"Content-Type": "application/json"}
            
            if api_token.startswith("AQ.") or api_token.startswith("ya29."):
                headers["Authorization"] = f"Bearer {api_token}"
            else:
                url = f"{url}?key={api_token}"
                
            prompt = """
            Analyze this shipping invoice. Extract every shipment line.
            For each shipment, extract:
            1. tracking_nr (Številka tovornega lista)
            2. country (Look at the prejemnik/naslov. Give me the 2-letter country code like DE, AT, CH, IT. If you can't find it, give the country name).
            3. cost (Total NET cost for this specific shipment, including base rate + surcharges like fuel/tolls. EXCLUDE ANY VAT/DDV).
            
            Also, find the total NET invoice amount at the bottom of the document (exclude VAT/DDV).
            
            Return ONLY a JSON object. No formatting, no markdown, just this exact structure:
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
                        {"inlineData": {"mimeType": "application/pdf", "data": b64_pdf}}
                    ]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json" # Forces Google to return raw JSON
                }
            }
            
            # 3. Fire the request
            response = requests.post(url, headers=headers, json=payload)
            
            # 4. Check for Google Errors (like expired tokens)
            if response.status_code != 200:
                st.error(f"🛑 Google API Error [{response.status_code}]")
                st.code(response.text)
                st.stop()
                
            # 5. Extract data
            resp_data = response.json()
            raw_text = resp_data['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(raw_text)
            
            # 6. Do the Math
            pdf_net_total = clean_cost(data.get('invoice_net_total', 0))
            shipments = []
            calculated_sum = 0.0
            
            for s in data.get('shipments', []):
                cost = clean_cost(s.get('cost', 0))
                calculated_sum += cost
                shipments.append({
                    "Tracking Number": str(s.get('tracking_nr', '')),
                    "Country": str(s.get('country', '')).upper(),
                    "Net Cost (€)": cost
                })
                
            df = pd.DataFrame(shipments)
            
            # --- 4. SHOW RESULTS ON SCREEN ---
            st.success("PDF processed successfully!")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Extracted Shipments")
                st.dataframe(df, use_container_width=True)
                
            with col2:
                st.subheader("Math Verification")
                diff = abs(pdf_net_total - calculated_sum)
                
                st.write(f"**Invoice Net Total (Bottom of PDF):** €{pdf_net_total:,.2f}")
                st.write(f"**Sum of Extracted Rows:** €{calculated_sum:,.2f}")
                
                if diff <= 1.00: 
                    st.success(f"✅ Math Matches! Discrepancy: €{diff:,.2f}")
                else:
                    st.error(f"⚠️ Math DOES NOT match! Discrepancy: €{diff:,.2f}")
                    
                st.subheader("Total Cost by Country")
                country_summary = df.groupby("Country")["Net Cost (€)"].sum().reset_index()
                st.dataframe(country_summary, use_container_width=True)

        except Exception as e:
            st.error(f"🛑 Application Error: {str(e)}")
