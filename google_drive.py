import os
import io

from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow

TOKEN = 'login_files/token.json'
CREDENTIALS = 'login_files/credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def authenticate_drive_api():
    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)

    try:
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN, 'w') as token:
                token.write(creds.to_json())

    except RefreshError:
        print("⚠️  Invalid or expired token detected. Removing old token and retrying...")
        if os.path.exists(TOKEN):
            os.remove(TOKEN)
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN, 'w') as token:
            token.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)

def list_files_in_folder(service, folder_id):
    files, page_token = [], None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces='drive',
            fields='nextPageToken, files(id, name)',
            pageToken=page_token
        ).execute()
        files.extend(response.get('files', []))
        page_token = response.get('nextPageToken', None)
        if not page_token:
            break
    return files

def download_file(service, file_id, file_name, save_path, progress_callback=None):
    os.makedirs(save_path, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(os.path.join(save_path, file_name), 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status and progress_callback:
            percent = int(status.progress() * 100)
            progress_callback(percent)

