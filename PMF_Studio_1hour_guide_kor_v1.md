# PMF Studio 1시간 완성 가이드 (비개발자용)


## 개요 & 목표
PMF Studio는 AI를 활용해 스타트업의 PMF를 자동으로 진단하고 리포트를 생성합니다. 본 가이드는 1시간 내 배포를 목표로 합니다.


## 준비물 체크리스트
- Google 계정
- Render 계정
- GitHub 계정
- Google Cloud Console 접근
- pmf_studio_by_handpartners_final_v1.zip (이 패키지)


## 단계별 배포
1. GitHub 저장소 생성 -> 파일 업로드
2. Render에 GitHub 연결 -> Web Service 생성
3. Google Cloud에서 서비스 계정 생성 -> JSON 키 복사
4. Render Environment에 GOOGLE_SERVICE_ACCOUNT_JSON 추가
5. Deploy 후 Live URL로 리포트 생성 테스트


## FAQ
- Build failed 시 requirements.txt 확인
- Drive 업로드 실패 시 서비스 계정 권한 확인


## 확장 팁
- Sentry 연동 권장
- 필요시 AWS/GCP로 이전 가능
