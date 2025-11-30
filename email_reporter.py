import os
import base64
import requests


def send_pmf_report_email(to_email: str, pdf_path: str, startup_name: str, pmf_score, stage):
    """
    PMF 리포트 PDF를 Resend API를 통해 이메일로 전송하는 함수
    - to_email: 받는 사람 이메일
    - pdf_path: PDF 파일 경로
    - startup_name: 스타트업 이름
    - pmf_score, stage: 결과 요약용
    """

    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    from_email = (os.getenv("RESEND_FROM_EMAIL") or "").strip()

    if not api_key or not from_email or not to_email:
        raise RuntimeError("Resend 이메일 설정이 부족합니다. RESEND_API_KEY / RESEND_FROM_EMAIL / to_email 확인 필요.")

    # 이메일 본문 텍스트
    body = f"""안녕하세요,

PMF Studio by HAND PARTNERS에서 [{startup_name}]의 PMF 진단 리포트를 보내드립니다.

- PMF Score: {pmf_score}
- Stage: {stage}

첨부된 PDF 파일을 확인해 주세요.

감사합니다.
HAND PARTNERS
"""

    # PDF 파일을 Base64로 인코딩 (Resend attachments 규격)
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    filename = f"[PMF Studio] {startup_name or 'pmf_report'}.pdf"

    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": f"[PMF Studio] {startup_name or 'Startup'} PMF 리포트",
        "text": body,
        "attachments": [
            {
                "filename": filename,
                "content": pdf_b64,
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
