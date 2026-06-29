import streamlit as st
import pandas as pd
import json
import os
import time
from io import BytesIO
import PyPDF2
from openai import OpenAI

# --- 1. SETUP ---
st.set_page_config(page_title="OpenAI PDF Extractor", layout="wide", page_icon="📄")

api_key = os.environ.get("OPENAI_API_KEY", "").strip()

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
st.title("📄 OpenAI PDF to Excel Extractor")
st.write("Upload courier invoices. OpenAI will read the text and extract it into a clean Excel file.")

if not api_key or not api_key.startswith("sk-"):
    st.error("⚠️ No valid OpenAI API Key found! Please add OPENAI_API_KEY to your Render environment variables.")

uploaded_files = st.file_uploader("Upload Courier Invoices (PDF)", type=['pdf'], accept_multiple_files=True)

# --- 3. PROCESSING ---
if st.button("Extract to Excel", type="primary") and uploaded_files and api_key.startswith("sk-"):
    all_shipments = []
    reconciliation_log = []
    progress_bar = st.progress(0)
    
    # Initialize OpenAI Client
    client = OpenAI(api_key=api_key)

    for idx, file in enumerate(uploaded_files):
        with st.spinner(f"OpenAI is reading {file.name}..."):
            try:
                # 1. Extract raw text from the PDF using PyPDF2
                pdf_reader = PyPDF2.PdfReader(file)
                pdf_text = ""
                for page in pdf_reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        pdf_text += extracted + "\n"
                
                if not pdf_text.strip():
                    st.error(f"🛑 Could not extract text from {file.name}. It might be a scanned image.")
                    continue

                # 2. Ask OpenAI to extract data from the text (using JSON mode)
                prompt = f"""
                Analyze the following text extracted from a shipping invoice. 
                Extract every individual shipment line.
                
                For each shipment, extract:
                1. tracking_nr (Številka tovornega lista)
                2. country (Prejemnik/naslov. Provide the 2-letter country code like DE, AT, CH. If not found, output the full name).
                3. cost (Total NET cost for this shipment, including base rate + surcharges. EXCLUDE VAT/DDV).
                
                Also, find the total NET invoice amount at the bottom of the document (excluding VAT/DDV).
                
                Return ONLY a JSON object matching this exact structure:
                {{
                  "invoice_net_total": 123.45,
                  "shipments": [
                    {{"tracking_nr": "12345", "country": "DE", "cost": 10.50}}
                  ]
                }}

                Invoice Text:
                {pdf_text}
                """

                response = client.chat.completions.create(
                    model="gpt-4o-mini", # Fast, incredibly smart, and very cheap
                    response_format={ "type": "json_object" }, # Guarantees perfect JSON
                    messages=[
                        {"role": "system", "content": "You are a precise data extraction assistant specializing in logistics invoices. Always output valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1
                )
                
                # 3. Parse OpenAI's JSON response
                raw_text = response.choices[0].message.content
                data = json.loads(raw_text)
                
                # 4. Process the numbers
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
                    
            except Exception as e:
                st.error(f"🛑 Error processing {file.name}: {str(e)}")
                
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
    else:
        st.warning("No data was extracted. Please verify the PDF contains text and try again.")
