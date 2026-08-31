import os
import glob
import pandas as pd
from supabase import create_client
import time

# --- 1. SUPABASE CREDENTIALS ---
SUPABASE_URL = "https://ezgsojftocdjytmrcubd.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_ANON_OR_SERVICE_ROLE_KEY"

# Folder containing all your monthly CSV files
FOLDER_PATH = r"D:\Monthly cust data"

# Initialize Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def process_and_upload_file(file_path):
    file_name = os.path.basename(file_path)
    print(f"\n📄 Processing: {file_name}...")
    
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"❌ Error reading {file_name}: {e}")
        return

    # --- DATA CLEANING & SCHEMA MATCHING ---
    df['bill_date'] = pd.to_datetime(df['bill_date'], errors='coerce').dt.strftime('%Y-%m-%d')
    
    df['mobile_number'] = df['mobile_number'].fillna("No Mobile").astype(str)
    df['mobile_number'] = df['mobile_number'].str.replace(r'\.0$', '', regex=True).str.strip()
    df.loc[df['mobile_number'] == "", 'mobile_number'] = "No Mobile"
    
    df['customer_name'] = df['customer_name'].fillna("Guest").astype(str).str.strip()
    df.loc[df['customer_name'] == "", 'customer_name'] = "Guest"
    df['store'] = df['store'].fillna("Unknown").astype(str).str.strip()
    df['bill_no'] = df['bill_no'].astype(str).str.strip()
    
    # Safe numeric conversions including qty
    df['total_bill_value'] = pd.to_numeric(df['total_bill_value'], errors='coerce').fillna(0)
    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
    df['accumulated_points'] = pd.to_numeric(df['accumulated_points'], errors='coerce').fillna(0).astype(int)
    df['redeem_points'] = pd.to_numeric(df['redeem_points'], errors='coerce').fillna(0).astype(int)
    
    df = df.dropna(subset=['bill_date'])
    
    records = df.to_dict(orient='records')
    total_records = len(records)
    print(f"📊 {total_records:,} valid records ready to upload.")

    # --- BATCHED UPLOAD ---
    chunk_size = 5000
    for i in range(0, total_records, chunk_size):
        chunk = records[i:i + chunk_size]
        try:
            supabase.table("bills").insert(chunk).execute()
            uploaded_count = min(i + chunk_size, total_records)
            print(f"  ✅ Uploaded {uploaded_count:,} / {total_records:,} rows...")
        except Exception as e:
            print(f"  ❌ Error at row batch {i}: {e}")
            break
        
        time.sleep(0.3)

    print(f"🎉 Finished uploading {file_name}!")

def main():
    csv_files = glob.glob(os.path.join(FOLDER_PATH, "*.csv"))
    if not csv_files:
        print(f"⚠️ No CSV files found in {FOLDER_PATH}.")
        return
        
    print(f"🚀 Found {len(csv_files)} CSV file(s) in {FOLDER_PATH}. Starting uploads...\n")
    for file_path in csv_files:
        process_and_upload_file(file_path)
    print("\n✨ All monthly files processed successfully!")

if __name__ == "__main__":
    main()