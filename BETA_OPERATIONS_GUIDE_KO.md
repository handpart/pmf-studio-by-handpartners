# HAND Partners PMF Studio 베타 운영 가이드

## 1. 개요
- 이 문서는 PMF Studio by HandPartners를 베타 형태로 외부 파트너/창업팀에게 제공할 때의 운영 절차를 정리합니다.

## 2. 역할
- PMF Studio 운영 담당자: 토큰 발급/관리, 문의 응대
- 액셀러레이팅 담당자: 결과 리포트 해석 및 피드백 코칭

## 3. 기본 플로우
1) 내부에서 베타 대상 리스트 확정
2) 각 대상별로 `token_admin.py` 또는 `/tokens` 페이지에서 토큰 생성
3) 이메일(또는 카카오톡, 슬랙)으로 개별 링크 발송
4) 사용 기간 종료 후, 필요 시 연장/회수 처리

## 4. 토큰 발급 정책 예시
- 일반 창업팀: 30일 trial (perm = "trial")
- 포트폴리오사: 90일 full (perm = "full")
- 내부 팀: 무기한 (perm = "internal", expires_at 먼 미래)

## 5. 만료/회수 정책
- 기간 만료 후 연장 요청 시, 토큰 연장 또는 신규 토큰 발급
- 악용 또는 오남용 발생 시, 해당 토큰 즉시 revoke 처리

## 6. 커뮤니케이션 템플릿
- 별도의 email_templates_beta.md 참고
