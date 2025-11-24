# ACCESS TOKEN GUIDE (사용자별 기간 관리용)

## 1. 개념

- `tokens_db.json` 파일에 사용자별 토큰 정보를 저장합니다.
- 각 토큰에는 `label(이름)`, `perm(권한)`, `expires_at(만료일시)`, `active(활성 여부)`가 들어있습니다.
- 서버는 요청에 포함된 `token` 값을 보고 이 DB를 조회해 사용 가능 여부를 판단합니다.

---

## 2. 토큰 생성 (관리자용)

로컬에서 Python이 설치된 환경에서:

```bash
python token_admin.py --create --days 30 --label "A사 홍길동" --perm "trial"
```

출력 예시:

```text
TOKEN: 3f9c1c8a1b2c4d5e6f...
URL example: https://your-deployed-url/report?token=3f9c1c8a1b2c4d5e6f...
Expires at (UTC): 2025-07-31T12:34:56.789012+00:00
```

이때 `TOKEN:` 뒤에 나온 문자열을 링크에 붙여서 전달하면 됩니다.

---

## 3. 토큰 목록 조회

```bash
python token_admin.py --list
```

각 토큰의 만료일, 라벨, 권한, active 여부를 확인할 수 있습니다.

---

## 4. 토큰 회수(비활성화)

특정 토큰을 더 이상 사용하지 못하게 하려면:

```bash
python token_admin.py --revoke <TOKEN_STRING>
```

또는 `tokens_db.json` 파일에서 해당 토큰의 `"active": false` 로 직접 수정 후 서버를 재배포해도 됩니다.

---

## 5. 기간 연장

특정 토큰의 만료일을 n일 만큼 연장하려면:

```bash
python token_admin.py --extend <TOKEN_STRING> 7
```

---

## 6. Render / 서버 배포 시

- `tokens_db.json` 파일이 프로젝트 루트(app.py가 있는 위치)에 존재해야 합니다.
- 새 토큰/수정사항을 반영할 때는 `tokens_db.json` 을 갱신한 뒤 재배포하면 됩니다.
