import os
import json
from datetime import datetime
import pandas as pd
from supabase import create_client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 1. Connect to Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. Fetch call logs
today_str = datetime.now().strftime("%Y-%m-%d")
response = supabase.table("call_logs").select("*").eq("call_date", today_str).execute()

if not response.data:
    print(f"No records found for {today_str}. Exporting full table backup.")
    response = supabase.table("call_logs").select("*").execute()

date_filename = f"Feedback_Report_{datetime.now().strftime('%d-%m-%Y')}.csv"
local_path = f"/tmp/{date_filename}"
df = pd.DataFrame(response.data)
df.to_csv(local_path, index=False)

# 3. Google Drive Auth
token_data = json.loads(os.environ.get("GOOGLE_DRIVE_TOKEN_JSON"))
creds = Credentials.from_authorized_user_info(token_data, scopes=['https://www.googleapis.com/auth/drive.file'])
drive_service = build('drive', 'v3', credentials=creds)

ROOT_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()

def get_or_create_folder(folder_name, parent_id=None):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    
    try:
        results = drive_service.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
    except Exception as e:
        print(f"Folder search warning: {e}")

    meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        meta['parents'] = [parent_id]
    
    return drive_service.files().create(body=meta, fields='id', supportsAllDrives=True).execute().get('id')

# Create subfolders inside ROOT_FOLDER_ID (Year -> Month)
year_folder = get_or_create_folder(datetime.now().strftime("%Y"), parent_id=ROOT_FOLDER_ID if ROOT_FOLDER_ID else None)
month_folder = get_or_create_folder(datetime.now().strftime("%B"), parent_id=year_folder)

# Upload CSV File
file_metadata = {'name': date_filename, 'parents': [month_folder]}
media = MediaFileUpload(local_path, mimetype='text/csv')
drive_service.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()

print(f"Successfully uploaded {date_filename} into Google Drive folder structure!")
