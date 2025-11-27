import os
import pickle
import json

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.service_account import Credentials

# 최소 권한: 파일 업로드/관리
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Shared Drive(공유 드라이브) ID (없으면 My Drive 기준으로 동작)
SHARED_DRIVE_ID = os.environ.get('GOOGLE_DRIVE_SHARED_DRIVE_ID')


def get_credentials():
    """
    1) 우선순위: 환경변수 GOOGLE_SERVICE_ACCOUNT_JSON (서비스 계정)
    2) 없으면 로컬 OAuth(credentials.json + token.json) 사용
    """
    # 1) Service Account from env var (JSON string)
    sa_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if sa_json:
        info = json.loads(sa_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return creds

    # 2) Fallback: OAuth token flow (로컬 개발용)
    creds = None
    if os.path.exists('token.json'):
        with open('token.json', 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError('credentials.json not found. See google_service_account_setup.md')
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'wb') as f:
            pickle.dump(creds, f)
    return creds


def ensure_folder(service, folder_name):
    """
    Shared Drive가 설정되어 있으면 해당 Shared Drive 안에서,
    아니면 My Drive에서 folder_name 폴더를 찾아보고, 없으면 생성.
    """
    if SHARED_DRIVE_ID:
        # Shared Drive 검색
        results = service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            corpora='drive',
            driveId=SHARED_DRIVE_ID,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields='files(id, name)'
        ).execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']

        # Shared Drive에 새 폴더 생성
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [SHARED_DRIVE_ID]
        }
        folder = service.files().create(
            body=file_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()
        return folder.get('id')
    else:
        # 기존 My Drive 방식
        results = service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']

        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')


def upload_pdf_to_drive_with_oauth(pdf_path, product_name, folder_name='HandPartners_PMFLab_Reports'):
    """
    pdf_path 의 파일을 Google Drive에 업로드하고
    { id, webViewLink } 를 반환.
    Shared Drive가 설정되어 있으면 Shared Drive에 업로드.
    """
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)

    folder_id = ensure_folder(service, folder_name)

    file_metadata = {
        'name': f'[PMF Studio by HandPartners] PMF 리포트 - {product_name}.pdf',
        'parents': [folder_id]
    }

    media = MediaFileUpload(pdf_path, mimetype='application/pdf')

    if SHARED_DRIVE_ID:
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()
    else:
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

    return file
