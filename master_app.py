import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import re

# --- 1. SETUP ---
st.set_page_config(page_title="PDF Reader V1", layout="wide")

# Standard Authentication setup
api_token = os.environ.get("GEMINI_API_KEY", "").strip()

if api_token.startswith("AQ.") or api_token.startswith("ya29."):
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials(token=api_token)
        genai.configure(credentials=creds)
    except Exception as e:
        st.error(f"Auth Error: {e}")
else:
    genai.configure(api_key=api_token)

model = genai.GenerativeModel('gemini-1.5-flash')

# Helper to clean currency strings into floats
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
st.title("Step 1: Minimal PDF Reader")
st.write("This version only reads PDFs, extracts countries and costs, and checks the math.")

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
            
            # --- IRONCLAD JSON PARSING ---
            raw_text = response.text.strip()
            
            # Try to rip the JSON out of any markdown backticks Google might have added
            match = re.search(r'
