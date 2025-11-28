import os
import smtplib
import ssl
from email.message import EmailMessage


def send_pmf_report_email(to_email: str, pdf_path: str, startup_name: str, pmf_score, stage):
    """
    PMF 리포트 PDF를 이메일로 전송하는 함수
    - to_email: 받는 사람 이메일
    - pdf_path: PDF 파일 경로
    - startup_name: 스타트업 이름
    - pmf_score, stage: 결과 요약용
    """

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM") or smtp_user

    if not (smtp_host and smtp_user and smtp_pass and from_email and to_email):
        raise RuntimeError("SMTP/이메일 설정이 부족합니다. SMTP_HOST/PORT/USERNAME/PASSWORD/SMTP_FROM/to_email 확인 필요.")

    msg = EmailMessage()
    msg["Subject"] = f"[PMF Studio] {startup_name or 'Startup'} PMF 리포트"
    msg["From"] = from_email
    msg["To"] = to_email

    body = f"""안녕하세요,

PMF Studio by HAND PARTNERS에서 [{startup_name}]의 PMF 진단 리포트를 보내드립니다.

- PMF Score: {pmf_score}
- Stage: {stage}

첨부된 PDF 파일을 확인해 주세요.

감사합니다.
HAND PARTNERS
"""
    msg.set_content(body)

    # PDF 첨부
    with open(pdf_path, "rb") as f:
        data = f.read()
    filename = f"[PMF Studio] {startup_name or 'pmf_report'}.pdf"
    msg.add_attachment(data, maintype="application", subtype="pdf", filename=filename)

    # SMTP 전송
    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        # 기본: TLS 사용
        if (os.getenv("SMTP_USE_TLS") or "true").lower() == "true":
            server.starttls(context=context)
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
