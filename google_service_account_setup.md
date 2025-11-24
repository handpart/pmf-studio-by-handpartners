# Google Service Account 설정 및 Render Secrets 사용 가이드 (한국어)

핵심 아이디어:
- credentials.json 파일을 직접 업로드하지 않고, 서비스 계정 키(JSON)를 Render의 Secret(환경변수)으로 등록하여 무인 인증합니다.
- 앱이 시작될 때 환경 변수에서 키(JSON)를 읽어 Google API 인증 객체를 생성합니다.

1) Google Cloud Console에서 서비스 계정 생성
   - IAM & 관리자 > 서비스 계정 > 새 서비스 계정 생성
   - 역할(Role): Project -> Editor(또는 최소한 Drive API 작업에 필요한 권한 설정)
   - 서비스 계정 키 생성(Key) -> JSON 형식 다운로드

2) JSON 내용을 Render Secret으로 저장
   - Render Dashboard -> 서비스 -> Environment -> Add Secret
   - Key 이름 예: GOOGLE_SERVICE_ACCOUNT_JSON
   - Value: (다운로드한 JSON 파일의 전체 텍스트를 붙여넣기)

3) 앱에서 환경변수로 인증 사용 (샘플 코드)
```python
import os, json
from google.oauth2.service_account import Credentials
SCOPES = ['https://www.googleapis.com/auth/drive.file']

sa_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
if sa_json:
    info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)
```
4) 장점
   - 파일 관리(credential.json) 불필요
   - CI/CD 및 자동 배포에 안전
   - Render Secrets는 UI에서 편리하게 관리 가능

5) 보안 주의사항
   - 서비스 계정 키는 매우 민감한 정보입니다. 다른 곳에 복사/유출되지 않도록 주의하세요.
   - 필요시, 서비스 계정에 최소 권한 원칙(Least Privilege) 적용하세요.
