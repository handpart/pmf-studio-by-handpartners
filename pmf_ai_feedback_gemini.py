# pmf_ai_feedback_gemini.py

import os
import re
from textwrap import dedent

try:
    # pip install google-genai
    from google import genai
except ImportError:
    genai = None

# 어떤 필드를 보고 "성실하게 썼는지" 평가할지 기준
KEY_FIELDS = [
    "problem", "problem_intensity", "current_alternatives", "willingness_to_pay",
    "target", "beachhead_customer", "customer_access",
    "solution", "usp", "mvp_status", "pricing_model",
    "users_count", "repeat_usage", "retention_signal",
    "revenue_status", "key_feedback",
    "market_size", "channels", "cac_ltv_estimate",
    "pmf_pull_signal", "referral_signal",
    "next_experiments", "biggest_risk",
]

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _estimate_answer_quality(raw: dict) -> float:
    """
    답변의 '성실도'를 0.0 ~ 1.0 사이 점수로 대략 계산.
    - 텍스트 길이가 너무 짧으면 낮게
    - 숫자만 가득이면 페널티
    """
    text_chunks = []
    digit_only_fields = 0

    for k in KEY_FIELDS:
        v = (raw.get(k) or "").strip()
        if not v:
            continue
        text_chunks.append(v)
        # 숫자 / %, , . / 공백만 있는 답변은 "숫자만 쓴 것"으로 취급
        if re.fullmatch(r"[0-9\s.,%]+", v):
            digit_only_fields += 1

    if not text_chunks:
        return 0.0

    merged = " ".join(text_chunks)
    total_len = len(merged)

    # 길이가 0~800자 사이면 0~1로 스케일
    base = min(1.0, total_len / 800.0)

    # 숫자만 있는 필드 비율이 높을수록 페널티
    ratio_digits = digit_only_fields / max(len(KEY_FIELDS), 1)
    penalty = ratio_digits * 0.6  # 최대 0.6까지 깎임

    score = max(0.0, base - penalty)
    return score


def _build_prompt(raw: dict, score, stage: str, quality_score: float) -> str:
    """
    Gemini에게 넘길 프롬프트 생성.
    HAND PARTNERS의 PMF Studio 멘토가 쓴 것 같은 톤으로 요청.
    """
    def g(key):
        return (raw.get(key) or "").strip()

    return dedent(f"""
    당신은 HAND PARTNERS의 파트너이자 세계적인 초기 스타트업 투자자입니다.
    지금부터 한 스타트업의 PMF 진단 결과와 설문 응답을 요약해서,
    창업자가 실제로 액션을 취할 수 있는 피드백을 한국어로 작성해 주세요.

    --- 시스템 정보 ---
    - 프로그램: PMF Studio by HAND PARTNERS
    - PMF 점수: {score}
    - PMF 단계: {stage}
    - 응답 성실도(내부 추정 지표, 0~1): {quality_score:.2f}

    --- 스타트업 개요 ---
    - 스타트업 이름: {g("startup_name")}
    - 산업/분야: {g("industry")}
    - 현재 단계: {g("startup_stage")}
    - 팀 규모: {g("team_size")}

    --- Problem / 고객 ---
    - 핵심 문제 정의: {g("problem")}
    - 문제의 강도/빈도: {g("problem_intensity")}
    - 현재 고객의 대안/경쟁 솔루션: {g("current_alternatives")}
    - 고객의 지불 의사/예산: {g("willingness_to_pay")}
    - 타겟 고객 세그먼트: {g("target")}
    - Beachhead 고객: {g("beachhead_customer")}
    - 고객 접근/확보 방법: {g("customer_access")}

    --- Solution / Value ---
    - 솔루션 요약: {g("solution")}
    - USP (차별점): {g("usp")}
    - MVP/제품 상태: {g("mvp_status")}
    - 가격/수익모델: {g("pricing_model")}

    --- Traction / Validation ---
    - 사용자 수: {g("users_count")}
    - 재사용/활성 사용자 신호: {g("repeat_usage")}
    - 리텐션/이탈 신호: {g("retention_signal")}
    - 매출/유료 전환: {g("revenue_status")}
    - 핵심 고객 피드백: {g("key_feedback")}

    --- Go-to-Market & PMF 신호 ---
    - 시장/기회: {g("market_size")}
    - 주요 유입/세일즈 채널: {g("channels")}
    - CAC/LTV 추정: {g("cac_ltv_estimate")}
    - PMF Pull Signal: {g("pmf_pull_signal")}
    - 추천/바이럴 신호: {g("referral_signal")}

    --- 다음 실행 ---
    - 다음 4주 핵심 실험/액션: {g("next_experiments")}
    - 가장 큰 리스크/가설: {g("biggest_risk")}

    --- 작성 방식 가이드 ---
    1. 한국어로 A4용지 4장 정도 분량의 내용으로 작성해 주세요.
    2. 구조는 다음 네 부분을 나눠서 작성해주세요:
       (1) 산업/분야에 대한 현황 요약
       (2) 현재 PMF 관점에서의 진단 요약
       (3) 지금 보이는 강점 2~3가지와 단점 2~3가지
       (4) 향후 4주 안에 반드시 검증해야 할 핵심 가설과 실행 제안
    3. 응답이 숫자 위주이거나 정보가 부족해 보이면,
       그 사실을 먼저 지적하고 어떤 항목을 더 구체적으로 써야 하는지 짧게 안내해 주세요.
    4. 너무 포장하지 말고, 초기 단계 스타트업을 멘토링하는 투자자의 현실적인 톤을 유지해 주세요.
    """)


def generate_ai_summary(raw: dict, score, stage: str) -> str:
    """
    Gemeni API를 호출해 HAND PARTNERS 스타일의 PMF 인사이트 요약을 생성.
    - 환경 변수 GEMINI_API_KEY가 없거나 라이브러리가 없으면 "" 반환
    - 입력이 너무 부실하면 사람이 다시 쓰도록 유도하는 메시지 반환
    """
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or genai is None:
        # 설정 안 되어 있으면 그냥 빈 문자열 -> 기존 룰 기반/기본 문구 사용
        return ""

    quality = _estimate_answer_quality(raw)

    # 응답이 너무 부실한 경우: 굳이 API 호출 안 하고 안내 문구만
    if quality < 0.25:
        return (
            "현재 입력된 내용이 너무 짧거나 숫자 위주라서 신뢰할 만한 PMF 분석을 하기 어렵습니다. "
            "특히 아래 항목들을 최소 한두 문장 이상으로 구체적으로 작성해 주세요:\n"
            "- 문제 정의 / 문제의 강도·빈도\n"
            "- 타겟 고객과 Beachhead 고객 설명\n"
            "- 솔루션과 USP(다른 대안과 무엇이 다른지)\n"
            "- 현재 사용자 수, 재사용/매출과 같은 검증/성과\n"
            "이 항목들을 보완한 뒤 다시 진단을 실행하시면 훨씬 정확한 피드백을 받으실 수 있습니다."
        )

    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(raw, score, stage, quality)
        resp = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
        )
        text = getattr(resp, "text", "") or ""
        return text.strip()
    except Exception:
        # 에러가 나더라도 서비스 전체가 죽지 않도록 빈 문자열 반환
        return ""
