from flask import Flask, request, jsonify, send_file, render_template_string
from token_validation import validate_token_simple
from pmf_score_engine import build_scores_from_raw, calculate_pmf_score
from pdf_template_kor_v2 import generate_pmf_report_v2
from pdf_to_drive_reporter import upload_pdf_to_drive_with_oauth
import tempfile, os, json

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

# Sentry 설정
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=1.0,
        send_default_pii=True
    )

app = Flask(__name__)


def _get_token_from_request(req):
    t = None
    if 'X-Access-Token' in req.headers:
        t = req.headers.get('X-Access-Token')
    if not t:
        t = req.args.get('token')
    return t


def _require_valid_token_or_403(req):
    token = _get_token_from_request(req)
    ok, info = validate_token_simple(token)
    if not ok:
        return False, (ok, info)
    return True, (ok, info)


@app.route('/')
def index():
    return 'PMF Studio API is running.'


@app.route('/health', methods=['GET'])
def health():
    test_error = request.args.get("test_error")
    if test_error:
        raise ValueError("Sentry DSN 테스트 오류 발생")
    return jsonify({"status": "ok", "message": "PMF Studio API is running"}), 200


@app.route('/score', methods=['POST'])
def score():
    """입력 데이터 기반 PMF 점수 계산"""
    ok, info = _require_valid_token_or_403(request)
    if not ok:
        return jsonify({'error': 'token_invalid', 'detail': info[1]}), 403

    try:
        raw = request.json or {}
        comps = build_scores_from_raw(raw)
        score, stage, comps_used = calculate_pmf_score(comps)
        return jsonify({'pmf_score': score, 'stage': stage, 'components': comps_used})
    except Exception as e:
        app.logger.error(f"PMF score calculation error: {str(e)}")
        raise


@app.route('/report', methods=['POST'])
def report():
    """PDF 리포트 생성 및 Google Drive 업로드"""
    ok, info = _require_valid_token_or_403(request)
    if not ok:
        return jsonify({'error': 'token_invalid', 'detail': info[1]}), 403

    try:
        raw = request.json or {}
        comps = build_scores_from_raw(raw)
        score, stage, comps_used = calculate_pmf_score(comps)

        pdf_data = {
            'startup_name': raw.get('startup_name', 'N/A'),
            'problem': raw.get('problem', ''),
            'solution': raw.get('solution', ''),
            'target': raw.get('target', ''),
            'pmf_score': score,
            'validation_stage': stage,
            'recommendations': raw.get('recommendations', ''),
            'summary': raw.get('summary', ''),
            'market_data': raw.get('market_data', ''),
            'ai_summary': raw.get('ai_summary', ''),
            'usp': raw.get('usp', 'N/A')
        }

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        tmp.close()
        generate_pmf_report_v2(pdf_data, tmp.name)

        try:
            drive_resp = upload_pdf_to_drive_with_oauth(
                tmp.name,
                pdf_data.get('startup_name', 'report')
            )
            drive_link = drive_resp.get('webViewLink') if drive_resp else None
        except Exception as e:
            app.logger.error(f"Drive upload error: {str(e)}")
            drive_link = None

        # PDF 파일 삭제 (옵션)
        try:
            os.remove(tmp.name)
        except Exception as e:
            app.logger.warning(f"Temporary file deletion failed: {str(e)}")

        return jsonify({'pmf_score': score, 'stage': stage, 'drive_link': drive_link})
    except Exception as e:
        app.logger.error(f"Report generation error: {str(e)}")
        raise


@app.route('/tokens', methods=['GET', 'POST'])
def tokens_admin():
    import json, os
    from datetime import datetime, timedelta, timezone

    TOKENS_DB_PATH = os.environ.get('TOKENS_DB_PATH', 'tokens_db.json')

    def _load_db():
        if not os.path.exists(TOKENS_DB_PATH):
            return {}
        try:
            with open(TOKENS_DB_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_db(db):
        with open(TOKENS_DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)

    msg = None
    if request.method == 'POST':
        action = request.form.get('action')
        db = _load_db()

        if action == 'create':
            label = request.form.get('label') or ''
            perm = request.form.get('perm') or 'trial'
            days = int(request.form.get('days') or '7')

            import uuid
            token = uuid.uuid4().hex
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            db[token] = {
                'label': label,
                'perm': perm,
                'expires_at': expires_at,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'active': True
            }
            _save_db(db)
            msg = f'새 토큰 생성: {token}'

        elif action == 'revoke':
            token = request.form.get('token')
            if token in db:
                db[token]['active'] = False
                _save_db(db)
                msg = f'토큰 비활성화: {token}'
            else:
                msg = '토큰을 찾을 수 없습니다.'

    db = _load_db()
    html = '''
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
    '''

    simple_db = {}
    for k, v in db.items():
        simple_db[k] = {
            'label': v.get('label', ''),
            'perm': v.get('perm', ''),
            'expires_at': v.get('expires_at', ''),
            'active': v.get('active', True)
        }
    return render_template_string(html, db=simple_db, msg=msg)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
