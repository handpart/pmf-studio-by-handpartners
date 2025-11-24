# Sentry 연동 가이드 (Flask 애플리케이션)

목표: 런타임 에러, PDF 생성 실패, Drive 업로드 실패 등을 Sentry로 수집하여 실시간 모니터링 및 알림을 받음.

1) Sentry 프로젝트 생성
   - https://sentry.io 에서 조직 및 프로젝트 생성
   - 플랫폼 선택: Python
   - DSN 발급 (프로젝트 설정에서 확인)

2) Render에 SENTRY_DSN 등록
   - Render Dashboard -> Service -> Environment -> Add Secret
   - Key: SENTRY_DSN, Value: <your_sentry_dsn>

3) 앱 코드에 Sentry 초기화 (예시)
```python
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

sentry_sdk.init(
    dsn=os.environ.get('SENTRY_DSN'),
    integrations=[FlaskIntegration()],
    traces_sample_rate=0.1  # 성능 트레이싱 비율, 필요시 조정
)
```

4) 권장 알림 설정
   - Sentry에서 Slack 또는 이메일 알림 설정
   - 에러 레벨 필터링 (예: critical, error)
   - Release tagging을 통해 배포 버전별 에러 추적

5) 로깅 보완
   - Flask의 로깅을 Sentry로 포워딩하거나, Python 로거에 핸들러 추가
   - 예외 발생 시 context(요청 payload, startup name 등)를 함께 전송하면 디버깅이 쉬워집니다.
