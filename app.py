import os
import json
import tempfile
import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string, send_file
from io import BytesIO
from token_validation import validate_token_simple
from pmf_score_engine import build_scores_from_raw, calculate_pmf_score
from pdf_template_kor_v2 import generate_pmf_report_v2
from email_reporter import send_pmf_report_email
# pmf_ai_feedback_gemini 는 선택적으로 사용: generate_ai_summary 를 내부에서 try-import로 호출

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration


# =========================
# Sentry 설정 (선택사항)
# =========================
SENTRY_DSN = (os.getenv("SENTRY_DSN") or "").strip()
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=1.0,
        send_default_pii=True,
    )

app = Flask(__name__)


# =========================
# 공통 토큰 유틸
# =========================
def _get_token_from_request(req):
    t = None
    # 헤더 우선
    if "X-Access-Token" in req.headers:
        t = req.headers.get("X-Access-Token")
    # 없으면 쿼리스트링 ?token=
    if not t:
        t = req.args.get("token")
    return t


def _require_valid_token_or_403(req):
    token = _get_token_from_request(req)
    ok, info = validate_token_simple(token)
    if not ok:
        # info는 dict라고 가정: {"error": "...", ...}
        return False, info
    return True, info


# =========================
# 데이터 품질 평가 유틸
# =========================
def assess_data_quality(raw: dict):
    """
    창업자가 쓴 텍스트 응답의 '충실도'를 0~100 점으로 평가.
    - 얼마나 많은 핵심 항목에 내용을 썼는지(coverage)
    - 그 내용이 어느 정도 길이/밀도를 가지는지(richness)
    - 너무 짧거나 asdf 등 의미 없는 응답 비율(garbage_ratio)
    를 조합해서 점수를 만든다.
    """

    # 서술형 텍스트로 기대하는 주요 필드들
    text_keys = [
        "problem", "problem_intensity", "current_alternatives",
        "willingness_to_pay", "target", "beachhead_customer",
        "customer_access", "solution", "usp", "mvp_status",
        "pricing_model", "repeat_usage", "retention_signal",
        "revenue_status", "key_feedback", "market_size",
        "channels", "pmf_pull_signal", "referral_signal",
        "next_experiments", "biggest_risk", "business_item",
    ]

    total = len(text_keys)
    nonempty = 0          # 뭔가라도 쓴 필드 수
    rich = 0              # 어느 정도 길이 이상 정성스럽게 쓴 필드 수
    garbage_like = 0      # '대충 쓴 것 같다'고 판단되는 필드 수

    for k in text_keys:
        v = (raw.get(k) or "").strip()
        if not v:
            continue

        nonempty += 1

        # 어느 정도 길이가 되면 "충실한 답변"으로 가산점
        if len(v) >= 60:
            rich += 1

        lower = v.lower()

        # 아주 짧거나, 전형적인 의미 없는 입력 패턴에 패널티
        if len(v) <= 4:
            garbage_like += 1
        elif lower in ("asdf", "qwer", "test", "tt", "11", "1234", "123", "1111"):
            garbage_like += 1

    if total == 0:
        return 0, "매우 낮음"

    coverage = nonempty / total          # 얼마나 많은 필드를 썼는지
    richness = rich / total              # 그 중에서 충분히 풍부한 응답 비율

    # 기본 점수: coverage 60%, richness 40%
    score = 100 * (0.6 * coverage + 0.4 * richness)

    # 쓰긴 썼는데 의미 없는 응답(garbage)이 많으면 강한 패널티
    if nonempty > 0:
        garbage_ratio = garbage_like / max(nonempty, 1)
        score *= (1.0 - 0.7 * garbage_ratio)

    score = max(0, min(100, int(round(score))))

    if score < 25:
        label = "매우 낮음"
    elif score < 60:
        label = "보통"
    else:
        label = "높음"

    return score, label


def _adjust_pmf_score(raw_score, raw_stage, quality_score: int):
    """
    데이터 품질이 낮으면 PMF 점수를 강하게 눌러서
    엉터리 입력값에 40점 이상이 잘 안 나오도록 보정.
    """
    try:
        s = float(raw_score)
    except Exception:
        return raw_score, raw_stage

    q = max(0, min(100, int(quality_score or 0)))

    # 아주 엉망 (대부분 비어있거나 숫자만)
    if q < 20:
        return 5.0, "정보 부족 / 진단 불가 (Pre-PMF)"

    # 정보가 많이 부족
    if q < 40:
        # 최대 20점까지만
        return min(s, 20.0), "정보 부족 / Early Problem Fit"

    # 그럭저럭, 하지만 아주 신뢰하긴 어려움
    if q < 60:
        # 최대 35점 정도까지 허용
        return min(s, 35.0), "초기 탐색 / Problem Discovery"

    # 60점 이상이면, 원래 계산 점수/단계 유지
    return s, raw_stage


# =========================
# OpenAI 기반 요약/코멘트 생성 (선택)
# =========================
def _llm_pmf_feedback(raw: dict, score, stage, quality_score: int):
    """
    OpenAI API를 사용해서:
    - quality_score_llm (0~100)
    - summary (요약 코멘트)
    - recommendations (전략 제언)
    - next_experiments (다음 4주 실험)
    - biggest_risk_comment (리스크에 대한 멘토 코멘트)
    을 JSON 으로 받아오는 함수.

    OPENAI_API_KEY 가 없거나, openai 패키지가 없으면 None을 리턴하고 건너뜀.
    """
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None, None, None, None, None

    try:
        from openai import OpenAI
    except ImportError:
        app.logger.error("openai 패키지가 설치되어 있지 않습니다. LLM 기반 피드백을 건너뜁니다.")
        return None, None, None, None, None

    client = OpenAI(api_key=api_key)

    import textwrap

    condensed = {
        "startup_name": raw.get("startup_name", ""),
        "industry": raw.get("industry", ""),
        "stage": raw.get("startup_stage", ""),
        "problem": raw.get("problem", ""),
        "problem_intensity": raw.get("problem_intensity", ""),
        "solution": raw.get("solution", ""),
        "target": raw.get("target", ""),
        "pmf_pull_signal": raw.get("pmf_pull_signal", ""),
        "referral_signal": raw.get("referral_signal", ""),
        "users_count": raw.get("users_count", ""),
        "revenue_status": raw.get("revenue_status", ""),
        "key_feedback": raw.get("key_feedback", ""),
        "next_experiments_user": raw.get("next_experiments", ""),
        "biggest_risk_user": raw.get("biggest_risk", ""),
    }

    user_prompt = textwrap.dedent(f"""
    너는 세계적인 스타트업 투자자이자 액셀러레이터 파트너다.
    아래는 한 스타트업이 PMF 진단 폼에 작성한 핵심 내용이다.

    이 정보를 바탕으로 다음 다섯 가지를 한국어로, 세계적인 창업 전문 멘토 톤으로 작성해라.
    - quality_score_llm: 입력의 성의/구체성을 0~100 사이 점수로 평가 (정수)
    - summary: PMF 관점 요약 (4~7문장, 너무 길지 않게)
    - recommendations: 향후 3~5개월 전략 제언 (3~5문장)
    - next_experiments: 다음 4주 동안 실행하면 좋은 실험 3~5개를 한 단락으로 정리
    - biggest_risk_comment: 가장 큰 리스크/핵심 가설에 대한 멘토 코멘트 (2~4문장)

    출력은 반드시 아래 JSON 형식 하나로만 반환해라.

    {{
      "quality_score_llm": 0~100 정수,
      "summary": "텍스트",
      "recommendations": "텍스트",
      "next_experiments": "텍스트",
      "biggest_risk_comment": "텍스트"
    }}

    --- 점수 정보 ---
    PMF 점수(보정 전): {score}
    PMF 단계(보정 전): {stage}
    데이터 품질 점수(룰 기반): {quality_score}

    --- 핵심 입력 데이터 ---
    {json.dumps(condensed, ensure_ascii=False, indent=2)}
    """)

    try:
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_PMF_MODEL", "gpt-4.1-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 세계적인 스타트업 투자자이자 엑셀러레이터 파트너다. "
                        "항상 솔직하지만 존중하는 톤을 유지하고, 실무적으로 도움이 되는 조언을 제공한다. "
                        "반드시 JSON 형식만 반환해야 한다."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        content = completion.choices[0].message.content
        obj = json.loads(content)

        q_llm = obj.get("quality_score_llm")
        summary = obj.get("summary")
        recommendations = obj.get("recommendations")
        next_experiments = obj.get("next_experiments")
        biggest_risk_comment = obj.get("biggest_risk_comment")
        return q_llm, summary, recommendations, next_experiments, biggest_risk_comment
    except Exception as e:
        app.logger.error(f"LLM PMF feedback failed: {e}")
        return None, None, None, None, None


# =========================
# 리포트 저장 함수
# - Supabase 있으면 Supabase 사용
# - 없으면 로컬 reports_db.json 사용
# =========================
def _store_report(report_record):
    """
    report_record 예시:
    {
        "id": uuid,
        "created_at": iso datetime,
        "startup_name": str,
        "pmf_score": float,
        "stage": str,
        "drive_link": str | None,
        "raw": dict
    }
    """
    sb_url = (os.getenv("SUPABASE_URL") or "").strip()
    sb_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()

    # 1) Supabase로 시도
    if sb_url and sb_key:
        try:
            import requests

            headers = {
                "apikey": sb_key,
                "Authorization": f"Bearer {sb_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            }
            url = f"{sb_url}/rest/v1/pmf_reports"
            payload = [
                {
                    "id": report_record["id"],
                    "startup_name": report_record["startup_name"],
                    "pmf_score": report_record["pmf_score"],
                    "stage": report_record["stage"],
                    "drive_link": report_record["drive_link"],
                    "raw": report_record["raw"],
                    "created_at": report_record["created_at"],
                }
            ]
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            r.raise_for_status()
            return
        except Exception as e:
            app.logger.error(f"Supabase store failed, fallback to local. {e}")

    # 2) 실패 시 로컬 JSON에 저장
    path = os.environ.get("REPORTS_DB_PATH", "reports_db.json")
    try:
        db = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                db = json.load(f) or []
        db.append(report_record)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        app.logger.error(f"Local report store failed: {e}")


# =========================
# PMF PDF에 넘길 데이터 구성 공통 함수
# =========================
def _build_pmf_pdf_data(raw: dict):
    """
    raw 입력을 받아:
    - PMF score 계산
    - 데이터 품질 평가(assess_data_quality)
    - 점수 표시 모드(pmf_score_mode) 및 안내 문구(pmf_score_note) 결정
    - Gemini 기반 ai_summary 생성 시도
    - 최종적으로 pdf_template_kor_v2.py 에 넘길 pdf_data 딕셔너리 구성

    반환값:
      (
        pdf_data,
        pmf_score_for_display,   # 화면/이메일/대시보드용 최종 점수(또는 None)
        stage,                   # 보정/모드 적용 후 단계 문자열
        pmf_score_raw,           # 원래 계산된 점수 그대로
        validation_stage_raw,    # 원래 계산된 단계 그대로
        data_quality_score,      # 0~100
        data_quality_label,      # "매우 낮음"/"보통"/"높음"
        pmf_score_mode,          # "normal" | "reference" | "invalid"
        pmf_score_note,          # 입력 데이터 부족 시 안내 문구
      )
    """

    # 1) 점수 계산 (기존 로직 그대로 활용)
    comps = build_scores_from_raw(raw)
    score, stage, comps_used = calculate_pmf_score(comps)

    pmf_score_raw = score
    validation_stage_raw = stage

    # 2) 데이터 품질 평가 (룰 기반)
    data_quality_score, data_quality_label = assess_data_quality(raw)

    # 3) 점수 모드/노트 결정
    pmf_score_mode = "normal"      # "normal" | "reference" | "invalid"
    pmf_score_note = ""
    pmf_score_for_display = None

    try:
        s_float = float(score)
        pmf_score_for_display = round(s_float, 1)
    except Exception:
        pmf_score_for_display = score

    # 데이터 품질 수준에 따른 모드 결정
    if data_quality_score < 25:
        # 거의 아무것도 안 썼거나, asdf 수준의 응답
        pmf_score_mode = "invalid"
        pmf_score_for_display = None  # 점수 숫자를 숨김
        stage = "데이터 부족(판정 불가)"
        pmf_score_note = (
            "입력된 내용이 너무 짧거나 형식적이어서, 이번 리포트에서는 PMF 점수를 산출하지 않았습니다. "
            "문제·고객·솔루션·트랙션 항목을 실제 사례와 숫자를 포함해 더 구체적으로 작성하신 뒤 "
            "다시 진단해 보시길 권장드립니다."
        )
    elif data_quality_score < 60:
        # 어느 정도는 썼지만, 완전히 신뢰하기엔 부족한 케이스
        pmf_score_mode = "reference"
        pmf_score_note = (
            "입력 데이터가 부분적으로 부족하여, 본 PMF 점수와 단계는 참고용으로 보시는 것을 권장드립니다. "
            "각 섹션에 구체적인 고객 사례와 정량 지표를 보완하면 더 정밀한 진단이 가능합니다."
        )
    else:
        # 충분히 성실하게 작성된 응답
        pmf_score_mode = "normal"
        # pmf_score_note는 빈 문자열 (필요 시 이후에 추가 가능)

    # 4) AI 요약(선택) – pmf_score_mode / data_quality에 따라 다르게
    ai_summary = (raw.get("ai_summary") or "").strip()

    if not ai_summary:
        # invalid 모드거나 데이터 품질이 매우 낮은 경우: Gemini 호출 없이 안내 문구만
        if pmf_score_mode == "invalid":
            ai_summary = (
                "현재 입력된 응답이 매우 짧거나 형식적인 문장이 많아, 신뢰할 수 있는 PMF 분석을 "
                "진행하기 어렵습니다. 각 항목에 실제 고객 상황, 사용 맥락, 숫자 기반 지표를 3~5문장 "
                "이상으로 작성해 주시면, 훨씬 정교한 인사이트를 제공해 드릴 수 있습니다."
            )
        else:
            # normal / reference 모드에서만 외부 AI(Gemini) 호출 시도
            try:
                ai_summary = generate_ai_summary(
                    raw=raw,
                    pmf_score=pmf_score_raw,
                    pmf_stage=validation_stage_raw,
                    data_quality_score=data_quality_score,
                    mode=pmf_score_mode,
                )
            except Exception as e:
                app.logger.error(f"AI summary generation failed: {e}")
                ai_summary = ""

    # 5) PDF에 넘길 데이터 구성
    pdf_data = {
        "startup_name": raw.get("startup_name", "N/A"),

        # 점수/단계 + 품질/모드 관련
        "pmf_score": pmf_score_for_display,
        "pmf_score_raw": pmf_score_raw,
        "pmf_score_mode": pmf_score_mode,
        "pmf_score_note": pmf_score_note,
        "validation_stage": stage,
        "validation_stage_raw": validation_stage_raw,
        "data_quality_score": data_quality_score,
        "data_quality_label": data_quality_label,

        # 기본 정보
        "contact_email": raw.get("contact_email", ""),
        "industry": raw.get("industry", ""),
        "business_item": raw.get("business_item", ""),
        "startup_stage": raw.get("startup_stage", ""),
        "team_size": raw.get("team_size", ""),

        # Problem / 고객
        "problem": raw.get("problem", ""),
        "problem_intensity": raw.get("problem_intensity", ""),
        "current_alternatives": raw.get("current_alternatives", ""),
        "willingness_to_pay": raw.get("willingness_to_pay", ""),
        "target": raw.get("target", ""),
        "beachhead_customer": raw.get("beachhead_customer", ""),
        "customer_access": raw.get("customer_access", ""),

        # Solution / Value
        "solution": raw.get("solution", ""),
        "usp": raw.get("usp", ""),
        "mvp_status": raw.get("mvp_status", ""),
        "pricing_model": raw.get("pricing_model", ""),

        # Traction / Validation
        "users_count": raw.get("users_count", ""),
        "repeat_usage": raw.get("repeat_usage", ""),
        "retention_signal": raw.get("retention_signal", ""),
        "revenue_status": raw.get("revenue_status", ""),
        "key_feedback": raw.get("key_feedback", ""),

        # Go-to-Market
        "market_size": raw.get("market_size", ""),
        "market_data": raw.get("market_data", ""),
        "channels": raw.get("channels", ""),
        "cac_ltv_estimate": raw.get("cac_ltv_estimate", ""),

        # PMF 신호
        "pmf_pull_signal": raw.get("pmf_pull_signal", ""),
        "referral_signal": raw.get("referral_signal", ""),

        # 종합 요약/제언 + AI 인사이트
        "summary": raw.get("summary", ""),
        "recommendations": raw.get("recommendations", ""),
        "ai_summary": ai_summary,

        # 다음 실행
        "next_experiments": raw.get("next_experiments", ""),
        "biggest_risk": raw.get("biggest_risk", ""),
    }

    return (
        pdf_data,
        pmf_score_for_display,
        stage,
        pmf_score_raw,
        validation_stage_raw,
        data_quality_score,
        data_quality_label,
        pmf_score_mode,
        pmf_score_note,
    )

def _generate_report_and_optionally_store(raw):
    """
    폼/JSON 입력(raw)을 받아:
    - PMF 점수/단계/데이터 품질 계산
    - PDF 생성
    - (필요 시) 이메일 전송
    - Supabase 또는 로컬에 리포트 저장
    """

    (
        pdf_data,
        pmf_score_for_display,
        stage,
        pmf_score_raw,
        validation_stage_raw,
        data_quality_score,
        data_quality_label,
        pmf_score_mode,
        pmf_score_note,
    ) = _build_pmf_pdf_data(raw)

    # 1) PDF 생성
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    generate_pmf_report_v2(pdf_data, tmp.name)

    # 2) 이메일 전송 시도
    to_email = raw.get("contact_email") or raw.get("email")
    email_sent = False
    email_error = None
    if to_email:
        try:
            send_pmf_report_email(
                to_email,
                tmp.name,
                pdf_data["startup_name"],
                pmf_score_for_display,
                stage,
            )
            email_sent = True
        except Exception as e:
            email_error = str(e)
            app.logger.error(f"Email send error: {e}")

    # 3) PDF 임시 파일 삭제
    try:
        os.remove(tmp.name)
    except Exception as e:
        app.logger.warning(f"Temporary file deletion failed: {e}")

    # 4) 저장용 레코드 구성
    report_record = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "startup_name": pdf_data["startup_name"],
        "pmf_score": pmf_score_for_display,
        "stage": stage,
        "drive_link": None,
        "email": to_email,
        "email_sent": email_sent,
        "email_error": email_error,
        "raw": {
            **raw,
            "pmf_score_raw": pmf_score_raw,
            "validation_stage_raw": validation_stage_raw,
            "data_quality_score": data_quality_score,
            "data_quality_label": data_quality_label,
            "pmf_score_mode": pmf_score_mode,
        },
    }
    _store_report(report_record)

    return pmf_score_for_display, stage, None, email_sent


def _generate_report_for_download(raw):
    """
    폼 입력(raw)을 받아:
    - PMF 점수/단계/품질 계산
    - PDF 생성
    - 리포트 저장
    - PDF 파일 경로와 스타트업 이름 반환
    (이메일은 보내지 않음)
    """

    (
        pdf_data,
        pmf_score_for_display,
        stage,
        pmf_score_raw,
        validation_stage_raw,
        data_quality_score,
        data_quality_label,
        pmf_score_mode,
        pmf_score_note,
    ) = _build_pmf_pdf_data(raw)

    # 1) PDF 생성
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    generate_pmf_report_v2(pdf_data, tmp.name)

    # 2) 저장용 레코드 (다운로드 전용, 이메일 X)
    report_record = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "startup_name": pdf_data["startup_name"],
        "pmf_score": pmf_score_for_display,
        "stage": stage,
        "drive_link": None,
        "email": raw.get("contact_email") or raw.get("email"),
        "email_sent": False,
        "email_error": "download_only",
        "raw": {
            **raw,
            "pmf_score_raw": pmf_score_raw,
            "validation_stage_raw": validation_stage_raw,
            "data_quality_score": data_quality_score,
            "data_quality_label": data_quality_label,
            "pmf_score_mode": pmf_score_mode,
        },
    }
    _store_report(report_record)

    return pmf_score_for_display, stage, tmp.name, pdf_data["startup_name"]


# =========================
# /report : API용 리포트 생성 (JSON POST 또는 안내)
# =========================
@app.route("/report", methods=["GET", "POST"])
def report():
    ok, info = _require_valid_token_or_403(request)
    if not ok:
        return jsonify({"error": "token_invalid", "detail": info.get("error")}), 403

    # GET 으로 직접 들어온 경우: 안내 페이지
    if request.method == "GET":
        return render_template_string(
            """
        <html>
          <head><title>PMF Studio Report API</title></head>
          <body style="max-width:720px;margin:40px auto;font-family:Arial;">
            <h2>PMF Studio Report API</h2>
            <p>이 엔드포인트는 주로 프로그램/API에서 <b>POST JSON</b>으로 사용하는 용도입니다.</p>
            <p>사람이 직접 입력해서 사용하려면 <b>/ui</b> 페이지를 이용하세요.</p>
            <hr/>
            <p>예시:</p>
            <pre>
POST /report?token=YOUR_TOKEN
Content-Type: application/json

{ ... PMF 입력 데이터 ... }
            </pre>
          </body>
        </html>
        """
        )

    # POST: JSON 기반 리포트 생성
    try:
        raw = request.json or {}
        score, stage, drive_link, email_sent = _generate_report_and_optionally_store(raw)
        return jsonify({
            "pmf_score": score,
            "stage": stage,
            "drive_link": drive_link,   # 항상 None
            "email_sent": email_sent
        })
    except Exception as e:
        app.logger.error(f"Report generation error: {str(e)}")
        raise


# =========================
# /ui : 사용자 입력 폼 (웹 UI) – 예시/안내 추가 버전
# =========================
@app.route("/ui", methods=["GET", "POST"])
def ui_form():
    ok, info = _require_valid_token_or_403(request)
    if not ok:
        return jsonify({"error": "token_invalid", "detail": info.get("error")}), 403

    token = _get_token_from_request(request)

    # GET: 질문지 폼 렌더링
    if request.method == "GET":
        return render_template_string("""
        <html>
        <head>
            <title>PMF Studio by HAND PARTNERS</title>
            <meta name="viewport" content="width=device-width, initial-scale=1" />
        </head>
        <body style="max-width:820px;margin:40px auto;font-family:Arial;line-height:1.5;">
            <h1>PMF Studio</h1>
            <p><b>Powered by HAND PARTNERS</b> · Global Scale-up Accelerator</p>
            <hr/>
            <p style="font-size:13px;color:#555;">
              각 문항은 <b>3~5문장 이상</b> 성의 있게 작성해주실수록 진단과 피드백의 정확도가 높아집니다.
              숫자나 키워드만 나열하기보다는, 실제 상황·사례·지표를 간단히 함께 적어주시면 좋습니다.
            </p>

            <form method="post">
                <input type="hidden" name="token" value="{{token}}"/>

                <h3>A. 기본 정보</h3>
                <label>리포트를 받을 이메일 주소</label><br/>
                <input name="contact_email" type="email"
                       placeholder="예: founder@startup.com"
                       style="width:100%;padding:8px"/><br/><br/>

                <label>스타트업 이름</label><br/>
                <input name="startup_name"
                       placeholder="예: 핸드파트너스 PMF 스튜디오"
                       style="width:100%;padding:8px"/><br/><br/>

                <label>산업/분야</label><br/>
                <input name="industry"
                       placeholder="예: B2B SaaS, 리테일 테크, 헬스케어, 교육, 커머스 등"
                       style="width:100%;padding:8px"/><br/><br/>

                <label>사업 아이템 소개</label><br/>
                <textarea name="business_item" rows="3" style="width:100%;padding:8px"
                       placeholder="예: 국내 초기 창업자를 대상으로, 사업계획서 작성과 시장 검증을 단계별로 안내해 주는 온라인 PMF 진단·코칭 플랫폼입니다."></textarea><br/><br/>

                <label>현재 단계</label><br/>
                <select name="startup_stage" style="width:100%;padding:8px">
                    <option value="idea">아이디어 (문제/해결 가설만 존재)</option>
                    <option value="mvp">MVP (초기 고객 테스트 중)</option>
                    <option value="early_revenue">초기 매출 (소규모 유료 고객 보유)</option>
                    <option value="scaling">스케일업 (재사용/매출 성장 중)</option>
                </select><br/><br/>

                <label>팀 규모</label><br/>
                <input name="team_size" type="number" min="1"
                       placeholder="예: 3"
                       style="width:100%;padding:8px"/><br/><br/>


                <h3>B. Problem (문제)</h3>
                <label>핵심 문제 정의</label><br/>
                <textarea name="problem" rows="4"
                          placeholder="예: 국내 중소 제조사는 고객사 주문·생산·재고 데이터를 엑셀과 카톡으로 관리하고 있어, 실시간 재고 파악과 수요 예측이 거의 불가능합니다. 그 결과, 과잉 생산·재고 부족이 반복되고 있고 의사결정이 항상 뒤늦게 이뤄집니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>문제의 강도/빈도 (고객에게 얼마나 자주/크게 발생?)</label><br/>
                <textarea name="problem_intensity" rows="3"
                          placeholder="예: 월 평균 2~3회 이상 납기 지연이 발생하고 있고, 매출의 약 5~10% 수준이 재고/반품 손실로 사라진다고 응답했습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>고객이 현재 쓰는 대안/경쟁 솔루션</label><br/>
                <textarea name="current_alternatives" rows="3"
                          placeholder="예: 엑셀, 카카오톡/이메일, 기본 ERP 모듈 등. 대부분 부분적으로만 사용하고 있으며, 현장에서는 여전히 수기로 보완하고 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>고객의 지불 의사/예산 존재 여부</label><br/>
                <textarea name="willingness_to_pay" rows="3"
                          placeholder="예: 월 30~50만원 수준의 구독료는 충분히 지불할 의사가 있다고 응답했으며, 연 매출 100억 이상 제조사는 더 높은 예산을 고려하고 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>C. Target Customer (고객)</h3>
                <label>핵심 타겟 고객 세그먼트</label><br/>
                <textarea name="target" rows="3"
                          placeholder="예: 연 매출 50~300억 규모의 국내 중소 제조사 중, OEM/ODM 수주 비중이 높은 기업을 1차 타겟으로 삼고 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>가장 먼저 공략할 Beachhead 고객</label><br/>
                <textarea name="beachhead_customer" rows="2"
                          placeholder="예: 수도권 지역의 전자/부품 제조사 20곳을 1차 Beachhead로 설정했습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>고객에 접근/확보할 수 있는 이유와 방법</label><br/>
                <textarea name="customer_access" rows="3"
                          placeholder="예: 기존 컨설팅 네트워크, 산업별 협회, ERP 파트너사와의 제휴를 통해 결정권자와 직접 미팅을 만들 수 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>D. Solution / Value (해결책/가치)</h3>
                <label>제품/솔루션 요약</label><br/>
                <textarea name="solution" rows="4"
                          placeholder="예: 주문·생산·재고 데이터를 한 화면에서 통합 관리하고, 간단한 입력만으로 생산 계획과 안전 재고를 추천해 주는 웹 기반 SaaS 입니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>USP (차별 포인트)</label><br/>
                <textarea name="usp" rows="3"
                          placeholder="예: 국내 중소 제조사에 특화된 템플릿과 KPI, 도입 후 2주 내 온보딩, 현장 작업자도 모바일에서 쉽게 사용할 수 있는 UX를 강점으로 합니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>MVP/제품 상태</label><br/>
                <textarea name="mvp_status" rows="2"
                          placeholder="예: 알파 버전은 3개 고객사에 PoC로 설치되어 있고, 핵심 기능 3개(주문 관리, 생산 일정, 재고 알림)가 동작 중입니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>가격/수익모델</label><br/>
                <textarea name="pricing_model" rows="2"
                          placeholder="예: 공장 수 기준 월 구독(기본 30만원) + 필요 시 온보딩 컨설팅 패키지 과금 모델을 고려하고 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>E. Traction / Validation (검증/성과)</h3>
                <label>현재 사용자 수</label><br/>
                <input name="users_count"
                       placeholder="예: PoC 3곳 / 유료 고객 1곳 / 월간 활성 사용자 40명 수준"
                       style="width:100%;padding:8px"/><br/><br/>

                <label>활성 사용자 / 재사용률 신호</label><br/>
                <textarea name="repeat_usage" rows="2"
                          placeholder="예: 메인 기능의 주간 재사용률이 60% 수준이며, 주요 담당자는 하루에 3~4번 로그인합니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>리텐션/이탈 관련 신호</label><br/>
                <textarea name="retention_signal" rows="2"
                          placeholder="예: PoC 고객 중 1곳은 6개월째 꾸준히 사용 중이고, 기능 보완을 요청하고 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>매출/유료 전환 현황</label><br/>
                <textarea name="revenue_status" rows="2"
                          placeholder="예: PoC 3곳 중 1곳이 유료로 전환하여 월 50만원을 지불하고 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>고객 피드백 핵심 요약</label><br/>
                <textarea name="key_feedback" rows="3"
                          placeholder="예: '이전보다 재고 관련 회의 시간이 절반으로 줄었다', '납기 지연 리스크를 미리 볼 수 있어 좋다' 등 정성 피드백이 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>F. Go-to-Market (시장/확장)</h3>
                <label>시장 크기/기회</label><br/>
                <textarea name="market_size" rows="2"
                          placeholder="예: 국내 중소 제조사 대상 TAM을 연 매출 1조~2조 수준으로 추정하고 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>주요 유입/세일즈 채널</label><br/>
                <textarea name="channels" rows="2"
                          placeholder="예: 산업별 전시회, 협회 세미나, 기존 컨설팅 고객사 레퍼런스를 주요 채널로 사용합니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>CAC/LTV 추정치(대략)</label><br/>
                <textarea name="cac_ltv_estimate" rows="2"
                          placeholder="예: 현재 PoC 기준 CAC는 약 30만원, 예상 LTV는 36개월 기준 500~700만원 수준으로 가정합니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>G. PMF 신호</h3>
                <label>PMF Pull Signal (없으면 큰일 나는 반응/사례)</label><br/>
                <textarea name="pmf_pull_signal" rows="3"
                          placeholder="예: 한 고객사는 '이제 이 툴이 없으면 다시 엑셀로 돌아갈 수 없다'고 말하며, 기능 장애 발생 시 바로 연락을 줍니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>추천/바이럴 신호</label><br/>
                <textarea name="referral_signal" rows="2"
                          placeholder="예: 기존 고객이 같은 협회 회원사 2곳을 소개해 주었고, 현재 미팅을 진행 중입니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>H. 다음 실행</h3>
                <label>다음 4주 핵심 실험/액션</label><br/>
                <textarea name="next_experiments" rows="3"
                          placeholder="예: (1) 기존 PoC 3곳의 유료 전환 조건 정리 (2) 전시회 리드 20곳 대상 데모 세션 진행 (3) 핵심 리텐션 기능 정의 및 사용 데이터 분석"
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <label>가장 큰 리스크/가설</label><br/>
                <textarea name="biggest_risk" rows="3"
                          placeholder="예: 실제로는 ERP 벤더가 동일한 문제를 더 싸게 해결해 줄 수 있다는 리스크, 현장 작업자의 사용 저항이 크다는 리스크 등이 있습니다."
                          style="width:100%;padding:8px"></textarea><br/><br/>

                <!-- 버튼 두 개: 보기/이메일, PDF 바로 다운로드 -->
                <button type="submit" name="submit_mode" value="view"
                        style="padding:12px 18px;font-size:16px;margin-right:8px;">
                    결과 화면 보기 / 이메일로 받기
                </button>
                <button type="submit" name="submit_mode" value="download"
                        style="padding:12px 18px;font-size:16px;">
                    PDF 바로 다운로드
                </button>

            </form>
        </body>
        </html>
        """, token=token)

    # POST: 폼 입력을 raw dict로 구성
    raw = {k: request.form.get(k) for k in request.form.keys()}
    contact_email = raw.get("contact_email")
    submit_mode = request.form.get("submit_mode") or "view"

    # 1) PDF 바로 다운로드 모드
    if submit_mode == "download":
        score, stage, pdf_path, startup_name = _generate_report_for_download(raw)

        pdf_io = BytesIO()
        with open(pdf_path, "rb") as f:
            pdf_io.write(f.read())
        pdf_io.seek(0)

        try:
            os.remove(pdf_path)
        except Exception as e:
            app.logger.warning(f"Temporary file deletion failed (download): {e}")

        filename = f"[PMF Studio] {startup_name or 'pmf_report'}.pdf"
        return send_file(
            pdf_io,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    # 2) 기본 모드: 이메일 + 화면 결과
    score, stage, drive_link, email_sent = _generate_report_and_optionally_store(raw)

    return render_template_string("""
    <html>
    <head><title>PMF Studio Result</title></head>
    <body style="max-width:820px;margin:40px auto;font-family:Arial;">
      <h2>PMF 진단 결과</h2>
      <p><b>PMF Score:</b> {{score}}</p>
      <p><b>Stage:</b> {{stage}}</p>

      {% if email_sent and contact_email %}
        <p>입력하신 이메일 주소 <b>{{contact_email}}</b> 로 PMF 리포트를 전송했습니다.</p>
      {% else %}
        <p>이메일 발송 설정이 활성화되지 않았거나 오류가 발생하여, 화면에만 결과를 표시합니다.</p>
      {% endif %}

      <hr/>
      <a href="/ui?token={{token}}">다시 진단하기</a>
    </body>
    </html>
    """,
    score=score,
    stage=stage,
    token=token,
    contact_email=contact_email,
    email_sent=email_sent)


# =========================
# /tokens : 토큰 관리 (JSON 로컬)
# =========================
@app.route("/tokens", methods=["GET", "POST"])
def tokens_admin():
    from datetime import timedelta

    TOKENS_DB_PATH = os.environ.get("TOKENS_DB_PATH", "tokens_db.json")

    def _load_db():
        if not os.path.exists(TOKENS_DB_PATH):
            return {}
        try:
            with open(TOKENS_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_db(db):
        with open(TOKENS_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)

    msg = None
    if request.method == "POST":
        action = request.form.get("action")
        db = _load_db()
        if action == "create":
            label = request.form.get("label") or ""
            perm = request.form.get("perm") or "trial"
            days = int(request.form.get("days") or "7")
            import uuid as _uuid

            token = _uuid.uuid4().hex
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            db[token] = {
                "label": label,
                "perm": perm,
                "expires_at": expires_at,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "active": True,
            }
            _save_db(db)
            msg = f"새 토큰 생성: {token}"
        elif action == "revoke":
            token = request.form.get("token")
            if token in db:
                db[token]["active"] = False
                _save_db(db)
                msg = f"토큰 비활성화: {token}"
            else:
                msg = "토큰을 찾을 수 없습니다."

    db = _load_db()
    simple_db = {}
    for k, v in db.items():
        simple_db[k] = {
            "label": v.get("label", ""),
            "perm": v.get("perm", ""),
            "expires_at": v.get("expires_at", ""),
            "active": v.get("active", True),
        }

    html = """
    <html>
    <head><title>PMF Studio Token Admin</title></head>
    <body>
      <h1>PMF Studio Token Admin</h1>
      <p style="color:red;">경고: 이 페이지는 인증이 없으므로 외부에 노출하지 마세요.</p>
      {% if msg %}<p><b>{{ msg }}</b></p>{% endif %}

      <h2>토큰 생성</h2>
      <form method="post">
        <input type="hidden" name="action" value="create">
        Label/이름: <input type="text" name="label"><br>
        권한(perm): <input type="text" name="perm" value="trial"><br>
        유효기간(일): <input type="number" name="days" value="7"><br>
        <button type="submit">토큰 생성</button>
      </form>

      <h2>토큰 목록</h2>
      <table border="1" cellpadding="4">
        <tr><th>Token</th><th>Label</th><th>Perm</th><th>Expires</th><th>Active</th></tr>
        {% for t, r in db.items() %}
          <tr>
            <td style="font-size:10px;">{{ t }}</td>
            <td>{{ r.label }}</td>
            <td>{{ r.perm }}</td>
            <td>{{ r.expires_at }}</td>
            <td>{{ r.active }}</td>
          </tr>
        {% endfor %}
      </table>

      <h2>토큰 회수(비활성화)</h2>
      <form method="post">
        <input type="hidden" name="action" value="revoke">
        Token: <input type="text" name="token" size="64">
        <button type="submit">비활성화</button>
      </form>
    </body>
    </html>
    """
    return render_template_string(html, db=simple_db, msg=msg)


# =========================
# /dashboard : 내부용 리포트 조회
# =========================
@app.route("/dashboard", methods=["GET"])
def dashboard():
    # 간단한 내부 인증: ?pw= 에 ADMIN_PASSWORD 환경변수와 일치해야 함
    admin_pw = (os.getenv("ADMIN_PASSWORD") or "").strip()
    pw = request.args.get("pw", "")
    if admin_pw and pw != admin_pw:
        return "Unauthorized", 401

    reports = []

    sb_url = (os.getenv("SUPABASE_URL") or "").strip()
    sb_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()

    # 1) Supabase에서 읽기 시도
    if sb_url and sb_key:
        try:
            import requests

            headers = {
                "apikey": sb_key,
                "Authorization": f"Bearer {sb_key}",
            }
            url = f"{sb_url}/rest/v1/pmf_reports?select=*&order=created_at.desc&limit=200"
            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            reports = r.json()
        except Exception as e:
            app.logger.error(f"Supabase read failed, fallback to local. {e}")

    # 2) 실패 시 로컬 JSON 사용
    if not reports:
        path = os.environ.get("REPORTS_DB_PATH", "reports_db.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                reports = json.load(f) or []

    return render_template_string(
        """
    <html>
    <head>
      <title>PMF Reports Dashboard</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
    </head>
    <body style="max-width:1000px;margin:40px auto;font-family:Arial;">
      <h1>PMF Reports Dashboard</h1>
      <p>Powered by HAND PARTNERS</p>
      <table border="1" cellpadding="6" cellspacing="0" style="width:100%;font-size:14px;">
        <tr>
          <th>생성일</th>
          <th>스타트업</th>
          <th>PMF Score</th>
          <th>Stage</th>
          <th>Drive Link</th>
        </tr>
        {% for r in reports %}
        <tr>
          <td>{{ r.created_at }}</td>
          <td>{{ r.startup_name }}</td>
          <td>{{ r.pmf_score }}</td>
          <td>{{ r.stage }}</td>
          <td>
            {% if r.drive_link %}
              <a href="{{ r.drive_link }}" target="_blank">열기</a>
            {% else %}
              -
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </table>
    </body>
    </html>
    """,
        reports=reports,
    )


# =========================
# 메인 실행
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
