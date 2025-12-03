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
    "industry", "business_item",
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


def _estimate_answer_quality_internal(raw: dict) -> float:
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


def estimate_answer_quality(raw: dict) -> dict:
    """
    - 0~1 비율 (quality_ratio)
    - 0~100 점수 (quality_score)
    - 라벨(매우 낮음/낮음/보통/높음)
    """
    ratio = _estimate_answer_quality_internal(raw)
    score_100 = int(round(ratio * 100))

    if ratio < 0.25:
        label = "매우 낮음"
    elif ratio < 0.5:
        label = "낮음"
    elif ratio < 0.75:
        label = "보통"
    else:
        label = "높음"

    return {
        "quality_ratio": ratio,
        "quality_score": score_100,
        "quality_label": label,
    }


def _build_prompt(
    raw: dict,
    pmf_score,
    pmf_stage: str,
    data_quality_score: int | None,
    mode: str,
    quality_ratio: float,
) -> str:
    """
    Gemini에게 넘길 프롬프트 생성.
    HAND PARTNERS의 PMF Studio 멘토가 쓴 것 같은 톤으로 요청.
    """
    def g(key: str) -> str:
        return (raw.get(key) or "").strip()

    dq_text = "N/A" if data_quality_score is None else f"{data_quality_score}/100"

    prompt = f"""
당신은 HAND PARTNERS의 파트너이자 세계적인 초기 스타트업 투자자입니다.
지금부터 한 스타트업의 PMF 진단 결과와 설문 응답을 요약해서,
창업자가 실제로 액션을 취할 수 있는 피드백을 한국어로 작성해 주세요.

--- 시스템 정보 ---
- 프로그램: PMF Studio by HAND PARTNERS
- PMF 점수(내부 계산 값): {pmf_score}
- PMF 단계(내부 계산 값): {pmf_stage}
- 데이터 품질 점수(룰 기반 0~100): {dq_text}
- 응답 성실도(텍스트 길이/패턴 기반 0~1): {quality_ratio:.2f}
- 현재 점수 모드: {mode}

--- 스타트업 개요 ---
- 스타트업 이름: {g("startup_name")}
- 산업/분야: {g("industry")}
- 사업 아이템 소개: {g("business_item")}
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
1. 한국어로 아래의 구조마다  A4 1장 내외(약 1,500~2,000자) 분량으로 작성하되, 너무 장황하지 않고 핵심에 집중해 주세요.
2. 구조는 다음 네 부분으로 나눠서 작성하되, 마크다운(#, *, -, 번호 목록) 문법은 사용하지 말고 순수한 문장과 줄바꿈만 사용해 주세요.
   (1) 사업 아이템에 맞춰서 최신 시장/산업의 동향과 트렌드를 조사하여 설명
   (2) 현재 PMF 관점에서의 진단 설명 (문제-고객-솔루션-트랙션-채널 관점)
   (3) 지금 보이는 강점 2~3가지와 보완이 필요한 지점 2~3가지
   (4) 향후 4주 안에 반드시 검증해야 할 핵심 가설과, 실행 가능한 실험/액션 제안 3~5가지
3. 각 부분 사이는 빈 줄(줄바꿈 2번)로만 구분해 주세요.
4. 응답이 숫자 위주이거나 정보가 부족해 보이면, 그 사실을 먼저 짧게 지적하고 어떤 항목을 더 구체적으로 써야 하는지 안내해 주세요.
5. 너무 포장하지 말고, 초기 단계 스타트업을 멘토링하는 투자자의 현실적인 톤을 유지해 주세요.
"""
    return dedent(prompt)


def generate_ai_summary(
    raw: dict,
    pmf_score,
    pmf_stage: str,
    data_quality_score: int | None = None,
    mode: str = "normal",
) -> str:
    """
    Gemini API를 호출해 HAND PARTNERS 스타일의 PMF 인사이트 요약을 생성.

    - GEMINI_API_KEY가 없거나 라이브러리가 없으면 "" 반환
    - 입력이 너무 부실하거나 점수 모드가 invalid면,
      LLM 호출 없이 '더 자세히 써달라'는 안내 문구만 반환
    """
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or genai is None:
        # 설정 안 되어 있으면 그냥 빈 문자열 -> PDF에서는 룰 기반/기본 문구만 사용
        return ""

    # 내부 텍스트 기반 품질 추정
    qinfo = estimate_answer_quality(raw)
    quality_ratio = qinfo["quality_ratio"]
    quality_score_100 = qinfo["quality_score"]

    # data_quality_score가 안 들어온 경우, 텍스트 기반 점수를 그대로 사용
    dq = data_quality_score if data_quality_score is not None else quality_score_100

    # 매우 부실하거나, 이미 invalid 모드인 경우 LLM 호출 대신 안내 문구만
    if mode == "invalid" or dq < 40 or quality_ratio < 0.25:
        return (
            "현재 입력된 내용이 너무 짧거나 형식적이어서 신뢰할 만한 PMF 분석을 진행하기 어렵습니다. "
            "특히 아래 항목들을 실제 고객 사례와 숫자를 포함해 최소 3~5문장 이상으로 보완해 주시면 좋습니다.\n"
            "- 문제 정의 및 문제의 강도/빈도\n"
            "- 타겟 고객과 Beachhead 고객 설명\n"
            "- 솔루션과 USP(다른 대안과 무엇이 다른지)\n"
            "- 현재 사용자 수, 재사용/리텐션, 매출/유료 전환과 같은 검증/성과\n"
            "- 향후 4주 동안 실행하려는 실험/액션 계획\n"
            "위 항목들을 구체적으로 작성하신 뒤 PMF Studio 진단을 다시 실행하시면, "
            "훨씬 정교한 인사이트와 실행 권고를 받아보실 수 있습니다."
        )

    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(
            raw=raw,
            pmf_score=pmf_score,
            pmf_stage=pmf_stage,
            data_quality_score=dq,
            mode=mode,
            quality_ratio=quality_ratio,
        )
        resp = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
        )
        text = getattr(resp, "text", "") or ""
        return text.strip()
    except Exception:
        # 에러가 나더라도 서비스 전체가 죽지 않도록 빈 문자열 반환
        return ""
