import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os

# --- 1. SETUP ---
st.set_page_config(page_title="PDF Reader V1", layout="wide")

# Standard Authentication setup
api_token = os.environ.get("GEMINI_API_KEY", "").strip()
genai.configure(api_key=api_token)
model = genai.GenerativeModel('gemini-1.5-flash')

# Helper to clean currency strings into numbers (e.g. "1.234,56 €" -> 1234.56)
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
st.title("Step 1: Minimal PDF Invoice Reader")

if api_token.startswith("AQ."):
    st.error("⚠️ You are using an AQ Session Token. If this fails, the token has expired. Please get a permanent AIza key from Google AI Studio.")

uploaded_file = st.file_uploader("Upload ONE Courier Invoice (PDF)", type=['pdf'])

# --- 3. PROCESSING ---
if st.button("Process Invoice") and uploaded_file:
    with st.spinner("AI is reading the PDF line by line..."):
        try:
            prompt = """
            Analyze this shipping invoice. Extract every shipment line.
            For each shipment, extract:
            1. tracking_nr (Številka tovornega lista)
            2. country (Look at the prejemnik/naslov. Give me the 2-letter country code like DE, AT, CH, IT. If you can't find it, give the country name).
            3. cost (Total NET cost for this specific shipment, including base rate + surcharges like fuel/tolls. EXCLUDE ANY VAT/DDV).
            
            Also, find the total NET invoice amount at the bottom of the document (exclude VAT/DDV).
            
            Return ONLY a JSON object. No markdown, no text, just this exact structure:
            {
              "invoice_net_total": 123.45,
              "shipments": [
                {"tracking_nr": "12345", "country": "DE", "cost": 10.50},
                {"tracking_nr": "67890", "country": "IT", "cost": 15.00}
              ]
            }
            """
            
            # Send file to Gemini
            fb = uploaded_file.getvalue()
            response = model.generate_content([prompt, {"mime_type": "application/pdf", "data": fb}])
            
            # --- SAFEST JSON PARSING (No Regex Syntax Errors) ---
            raw_text = response.text.strip()
            
            # Find the very first { and the very last } to perfectly grab the data
            start_index = raw_text.find('{')
            end_index = raw_text.rfind('}')
            
            if start_index != -1 and end_index != -1:
                raw_text = raw_text[start_index:end_index+1]
                
            data = json.loads(raw_text)
            
            # --- CALCULATE THE MATH ---
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
            
            # --- SHOW RESULTS ON SCREEN ---
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
                
                if diff <= 1.00: # 1 euro tolerance for rounding discrepancies
                    st.success(f"✅ Math Matches! Discrepancy: €{diff:,.2f}")
                else:
                    st.error(f"⚠️ Math DOES NOT match! Discrepancy: €{diff:,.2f}")
                    
                st.subheader("Total Cost by Country")
                country_summary = df.groupby("Country")["Net Cost (€)"].sum().reset_index()
                st.dataframe(country_summary, use_container_width=True)

        except Exception as e:
            st.error(f"🛑 Error processing PDF: {str(e)}")
