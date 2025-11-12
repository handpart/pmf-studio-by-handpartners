from flask import Flask, request, jsonify, send_file
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
    try:
        raw = request.json or {}
        comps = build_scores_from_raw(raw)
        score, stage, comps_used = calculate_pmf_score(comps)

        pdf_data = {
            'startup_name': raw.get('startup_name','N/A'),
            'problem': raw.get('problem',''),
            'solution': raw.get('solution',''),
            'target': raw.get('target',''),
            'pmf_score': score,
            'validation_stage': stage,
            'recommendations': raw.get('recommendations',''),
            'summary': raw.get('summary',''),
            'market_data': raw.get('market_data',''),
            'ai_summary': raw.get('ai_summary',''),
            'usp': raw.get('usp','N/A')
        }

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        tmp.close()
        generate_pmf_report_v2(pdf_data, tmp.name)

        try:
            drive_resp = upload_pdf_to_drive_with_oauth(tmp.name, pdf_data.get('startup_name','report'))
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)