import os
import json
import tempfile
import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string
from token_validation import validate_token_simple
from pmf_score_engine import build_scores_from_raw, calculate_pmf_score
from pdf_template_kor_v2 import generate_pmf_report_v2
from pdf_to_drive_reporter import upload_pdf_to_drive_with_oauth

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
# 리포트 생성 공통 함수
# =========================
def _generate_report_and_optionally_store(raw):
    """
    raw 입력을 받아 PMF score 계산 + PDF 생성 + Drive 업로드 + 저장까지 수행
    """
    comps = build_scores_from_raw(raw)
    score, stage, comps_used = calculate_pmf_score(comps)

    pdf_data = {
        "startup_name": raw.get("startup_name", "N/A"),
        "problem": raw.get("problem", ""),
        "solution": raw.get("solution", ""),
        "target": raw.get("target", ""),
        "pmf_score": score,
        "validation_stage": stage,
        "recommendations": raw.get("recommendations", ""),
        "summary": raw.get("summary", ""),
        "market_data": raw.get("market_data", ""),
        "ai_summary": raw.get("ai_summary", ""),
        "usp": raw.get("usp", "N/A"),
    }

    # PDF 생성
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    generate_pmf_report_v2(pdf_data, tmp.name)

    drive_link = None

    # 환경변수 ENABLE_DRIVE_UPLOAD 이 "true"일 때만 업로드 시도
    enable_drive = (os.getenv("ENABLE_DRIVE_UPLOAD") or "").lower() == "true"
    if enable_drive:
        try:
            drive_resp = upload_pdf_to_drive_with_oauth(
                tmp.name, pdf_data.get("startup_name", "report")
            )
            drive_link = drive_resp.get("webViewLink") if drive_resp else None
        except Exception as e:
            app.logger.error(f"Drive upload error: {str(e)}")

    # 임시 파일 삭제
    try:
        os.remove(tmp.name)
    except Exception as e:
        app.logger.warning(f"Temporary file deletion failed: {e}")

    # 저장용 레코드 구성
    report_record = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "startup_name": pdf_data["startup_name"],
        "pmf_score": score,
        "stage": stage,
        "drive_link": drive_link,
        "raw": raw,
    }
    _store_report(report_record)

    return score, stage, drive_link


# =========================
# 기본 라우트들
# =========================
@app.route("/")
def index():
    return "PMF Studio API is running."


@app.route("/health", methods=["GET"])
def health():
    test_error = request.args.get("test_error")
    if test_error:
        raise ValueError("Sentry DSN 테스트 오류 발생")
    return jsonify({"status": "ok", "message": "PMF Studio API is running"}), 200


# =========================
# /score : JSON 기반 점수 계산
# =========================
@app.route("/score", methods=["POST"])
def score():
    """입력 데이터 기반 PMF 점수 계산 (API 용)"""
    ok, info = _require_valid_token_or_403(request)
    if not ok:
        return jsonify({"error": "token_invalid", "detail": info.get("error")}), 403

    try:
        raw = request.json or {}
        comps = build_scores_from_raw(raw)
        score, stage, comps_used = calculate_pmf_score(comps)
        return jsonify({"pmf_score": score, "stage": stage, "components": comps_used})
    except Exception as e:
        app.logger.error(f"PMF score calculation error: {str(e)}")
        raise


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
        score, stage, drive_link = _generate_report_and_optionally_store(raw)
        return jsonify({"pmf_score": score, "stage": stage, "drive_link": drive_link})
    except Exception as e:
        app.logger.error(f"Report generation error: {str(e)}")
        raise


# =========================
# /ui : 사용자 입력 폼 (웹 UI)
# =========================
@app.route("/ui", methods=["GET", "POST"])
def ui_form():
    ok, info = _require_valid_token_or_403(request)
    if not ok:
        return jsonify({"error": "token_invalid", "detail": info.get("error")}), 403

    token = _get_token_from_request(request)

    # GET: 질문지 폼 렌더링
    if request.method == "GET":
        return render_template_string(
            """
        <html>
        <head>
            <title>PMF Studio by HAND PARTNERS</title>
            <meta name="viewport" content="width=device-width, initial-scale=1" />
        </head>
        <body style="max-width:820px;margin:40px auto;font-family:Arial;line-height:1.5;">
            <h1>PMF Studio</h1>
            <p><b>Powered by HAND PARTNERS</b> · Global Scale-up Accelerator</p>
            <hr/>

            <form method="post">
                <input type="hidden" name="token" value="{{token}}"/>

                <h3>A. 기본 정보</h3>
                <label>스타트업 이름</label><br/>
                <input name="startup_name" style="width:100%;padding:8px"/><br/><br/>

                <label>산업/분야</label><br/>
                <input name="industry" placeholder="예: B2B SaaS, 바이오, 커머스" style="width:100%;padding:8px"/><br/><br/>

                <label>현재 단계</label><br/>
                <select name="startup_stage" style="width:100%;padding:8px">
                    <option value="idea">아이디어</option>
                    <option value="mvp">MVP</option>
                    <option value="early_revenue">초기 매출</option>
                    <option value="scaling">스케일업</option>
                </select><br/><br/>

                <label>팀 규모</label><br/>
                <input name="team_size" type="number" min="1" style="width:100%;padding:8px"/><br/><br/>


                <h3>B. Problem (문제)</h3>
                <label>핵심 문제 정의</label><br/>
                <textarea name="problem" rows="4" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>문제의 강도/빈도 (고객에게 얼마나 자주/크게 발생?)</label><br/>
                <textarea name="problem_intensity" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>고객이 현재 쓰는 대안/경쟁 솔루션</label><br/>
                <textarea name="current_alternatives" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>고객의 지불 의사/예산 존재 여부</label><br/>
                <textarea name="willingness_to_pay" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>C. Target Customer (고객)</h3>
                <label>핵심 타겟 고객 세그먼트</label><br/>
                <textarea name="target" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>가장 먼저 공략할 Beachhead 고객</label><br/>
                <textarea name="beachhead_customer" rows="2" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>고객에 접근/확보할 수 있는 이유와 방법</label><br/>
                <textarea name="customer_access" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>D. Solution / Value (해결책/가치)</h3>
                <label>제품/솔루션 요약</label><br/>
                <textarea name="solution" rows="4" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>USP (차별 포인트)</label><br/>
                <textarea name="usp" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>MVP/제품 상태</label><br/>
                <textarea name="mvp_status" rows="2" placeholder="예: 베타 출시, 기능 3개 완료" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>가격/수익모델</label><br/>
                <textarea name="pricing_model" rows="2" placeholder="예: 월 구독, 거래수수료, 라이선스" style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>E. Traction / Validation (검증/성과)</h3>
                <label>현재 사용자 수</label><br/>
                <input name="users_count" style="width:100%;padding:8px"/><br/><br/>

                <label>활성 사용자 / 재사용률 신호</label><br/>
                <textarea name="repeat_usage" rows="2" placeholder="예: 주간 재사용 40%, 반복 구매 발생" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>리텐션/이탈 관련 신호</label><br/>
                <textarea name="retention_signal" rows="2" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>매출/유료 전환 현황</label><br/>
                <textarea name="revenue_status" rows="2" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>고객 피드백 핵심 요약</label><br/>
                <textarea name="key_feedback" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>F. Go-to-Market (시장/확장)</h3>
                <label>시장 크기/기회</label><br/>
                <textarea name="market_size" rows="2" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>주요 유입/세일즈 채널</label><br/>
                <textarea name="channels" rows="2" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>CAC/LTV 추정치(대략)</label><br/>
                <textarea name="cac_ltv_estimate" rows="2" placeholder="예: CAC 3만원, LTV 30만원" style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>G. PMF 신호</h3>
                <label>PMF Pull Signal (없으면 큰일 나는 반응/사례)</label><br/>
                <textarea name="pmf_pull_signal" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>추천/바이럴 신호</label><br/>
                <textarea name="referral_signal" rows="2" style="width:100%;padding:8px"></textarea><br/><br/>


                <h3>H. 다음 실행</h3>
                <label>다음 4주 핵심 실험/액션</label><br/>
                <textarea name="next_experiments" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>

                <label>가장 큰 리스크/가설</label><br/>
                <textarea name="biggest_risk" rows="3" style="width:100%;padding:8px"></textarea><br/><br/>


                <button type="submit" style="padding:12px 18px;font-size:16px;">
                    PMF 리포트 생성
                </button>
            </form>
        </body>
        </html>
        """,
            token=token,
        )

    # POST: 폼 입력 내용을 raw dict에 그대로 담아서 사용
    raw = {k: request.form.get(k) for k in request.form.keys()}

    score, stage, drive_link = _generate_report_and_optionally_store(raw)

    return render_template_string(
        """
    <html>
    <head><title>PMF Studio Result</title></head>
    <body style="max-width:820px;margin:40px auto;font-family:Arial;">
      <h2>PMF 진단 결과</h2>
      <p><b>PMF Score:</b> {{score}}</p>
      <p><b>Stage:</b> {{stage}}</p>
      {% if drive_link %}
        <p><a href="{{drive_link}}" target="_blank">Google Drive 리포트 열기</a></p>
      {% else %}
        <p>Drive 업로드 링크가 없습니다.</p>
      {% endif %}
      <hr/>
      <a href="/ui?token={{token}}">다시 진단하기</a>
    </body>
    </html>
    """,
        score=score,
        stage=stage,
        drive_link=drive_link,
        token=token,
    )


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
