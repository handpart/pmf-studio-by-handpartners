# Render 대시보드 배포 가이드 (핸드파트너스)

1) Render 접속 및 로그인 (https://render.com)
2) New -> Web Service 선택
3) GitHub repo 연결 -> Repository 선택 (pmf-studio-by-handpartners)
4) Build Command: pip install -r requirements.txt
5) Start Command: python app.py
6) Environment Variables 추가:
   - GOOGLE_SERVICE_ACCOUNT_JSON : (서비스 계정 JSON 전체)
   - SENTRY_DSN : (선택)
7) Create Web Service 클릭 -> 배포 완료
8) 배포 URL 확인 후 /health, /score, /report 엔드포인트 테스트
