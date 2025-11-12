import os, pickle, json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_credentials():
    # 1) Try service account from env var (GOOGLE_SERVICE_ACCOUNT_JSON)
    sa_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if sa_json:
        info = json.loads(sa_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return creds

    # 2) Fallback to OAuth token flow using credentials.json/token.json
    creds = None
    if os.path.exists('token.json'):
        with open('token.json','rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError('credentials.json not found. See google_service_account_setup.md')
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json','wb') as f:
            pickle.dump(creds, f)
    return creds

def ensure_folder(service, folder_name):
    results = service.files().list(q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'",
                                   spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
    folder = service.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')

def upload_pdf_to_drive_with_oauth(pdf_path, product_name, folder_name='HandPartners_PMFLab_Reports'):
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)
    folder_id = ensure_folder(service, folder_name)
    file_metadata = {'name': f'[PMF Studio by HandPartners] PMF 리포트 - {product_name}.pdf', 'parents': [folder_id]}
    media = MediaFileUpload(pdf_path, mimetype='application/pdf')
    file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
    return file
