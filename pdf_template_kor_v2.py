import os
import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ---------------------------
# 폰트 설정
#   - fonts/ 폴더 안에
#     NanumGothic.ttf
#     NanumGothicBold.ttf
#   를 넣어서 사용
# ---------------------------
BASE_DIR = os.path.dirname(__file__)
FONT_DIR = os.path.join(BASE_DIR, "fonts")

NANUM_REG = os.path.join(FONT_DIR, "NanumGothic.ttf")
NANUM_BOLD = os.path.join(FONT_DIR, "NanumGothicBold.ttf")

if not os.path.exists(NANUM_REG) or not os.path.exists(NANUM_BOLD):
    raise FileNotFoundError(
        "fonts 폴더에 NanumGothic.ttf / NanumGothicBold.ttf 파일이 있는지 확인해 주세요.\n"
        f"기대 경로: {NANUM_REG}, {NANUM_BOLD}"
    )

pdfmetrics.registerFont(TTFont("NanumGothic", NANUM_REG))
pdfmetrics.registerFont(TTFont("NanumGothicBold", NANUM_BOLD))

TITLE_FONT = "NanumGothicBold"   # 표지 큰 제목
HEADER_FONT = "NanumGothicBold"  # 섹션 제목
BODY_FONT = "NanumGothic"        # 본문


# ---------------------------
# (백업용) 데이터 품질 추정 휴리스틱
#  - app.py에서 data_quality_score/label을 안 넘겨줄 때만 사용
# ---------------------------
def _estimate_data_quality(data: dict) -> int:
    """
    텍스트 기반 핵심 필드를 간단히 스코어링해서 0~100 사이의 데이터 품질 점수로 환산.
    """
    key_fields = [
        "problem",
        "solution",
        "target",
        "pmf_pull_signal",
        "key_feedback",
    ]

    total = 0
    used = 0

    for field in key_fields:
        txt = str(data.get(field, "") or "").strip()
        if not txt:
            continue

        used += 1
        length = len(txt)
        score = 0

        # 길이에 따른 점수
        if length >= 60:
            score += 45
        elif length >= 30:
            score += 35
        elif length >= 15:
            score += 25
        else:
            score += 10

        # 숫자 비율이 너무 높으면 감점
        digits = sum(c.isdigit() for c in txt)
        letters = sum(c.isalpha() for c in txt)
        if digits > 0 and digits >= letters * 2:
            score -= 20

        total += max(score, 0)

    if used == 0:
        return 0

    raw = total / used
    return max(0, min(100, int(raw)))


def _quality_label(score: int) -> str:
    if score >= 70:
        return "높음"
    elif score >= 40:
        return "보통"
    else:
        return "낮음"


def _build_rule_based_summary(score, stage, quality_score=None):
    """
    PMF 점수 / 단계(+ 선택적으로 데이터 품질 점수)에 따라
    HAND PARTNERS 스타일의 기본 코멘트 생성
    """
    # 데이터 품질 먼저 숫자로 변환 시도
    try:
        q = float(quality_score) if quality_score is not None else None
    except Exception:
        q = None

    # 점수가 아예 없거나("산출 불가" 케이스)
    try:
        s = float(score)
    except Exception:
        base = (
            "현재 입력된 정보를 기반으로 PMF를 정성적으로 검토할 수 있는 초기 자료가 확보된 상태입니다. "
            "다만 일부 핵심 항목이 비어 있거나 매우 간략하게 작성되어 있어, 이번 리포트의 평가는 "
            "방향성 참고용으로 활용하시길 권장드립니다. "
            "문제·고객·솔루션·트랙션 항목을 실제 고객 사례와 숫자 중심으로 보완해 주시면 "
            "보다 정밀한 진단이 가능합니다."
        )
        if q is not None and q < 25:
            base += (
                " 특히, 응답이 한두 단어 수준에 그치거나 반복적인 텍스트가 많은 편이므로 "
                "각 항목당 최소 3~5문장 정도로 구체적인 맥락을 추가해 주시면 좋습니다."
            )
        return base

    stage = (stage or "").lower()

    # ===== 점수 구간별 기본 코멘트 =====
    if s < 30:
        base = (
            "현재 단계는 아직 PMF 이전(Early Problem Fit)에 가까운 상태로 보입니다. "
            "고객이 실제로 겪고 있는 구체적인 Pain을 더 깊이 정의하고, "
            "문제의 강도·빈도·대안 솔루션에 대한 정성 인터뷰를 최소 10~20건 이상 추가 확보하는 것이 중요합니다. "
            "이 시기에는 기능 개발보다 '올바른 문제 정의와 타겟 세분화'에 대부분의 에너지를 쓰는 것이 좋습니다."
        )
    elif s < 50:
        base = (
            "Problem/Solution Fit 단계에 진입한 것으로 판단됩니다. "
            "핵심 문제와 제안하는 솔루션 사이의 논리적 연결은 보이지만, 아직 고객의 반복 사용·지불 의사 측면에서 "
            "명확한 신호가 부족합니다. "
            "초기 Beachhead 세그먼트를 더 좁게 정의하고, 실제 파일럿·PoC를 통해 과금 실험과 리텐션 지표를 "
            "집중적으로 확인해보는 것을 추천드립니다."
        )
    elif s < 70:
        base = (
            "초기 PMF 신호가 일부 관찰되고 있는 단계로 보입니다. "
            "재사용·재구매, 추천, 자연 유입 등에서 긍정적인 패턴이 나타나고 있으며, "
            "이제는 채널 별 유닛 이코노믹스(CAC/LTV)를 설계하고, 스케일업 가능성이 높은 세그먼트에 "
            "집중하는 것이 중요합니다. "
            "동시에 제품 사용 데이터를 기반으로 '헤비 유저의 공통점'을 분석해 보다 선명한 ICP를 정의해 보시길 권장합니다."
        )
    else:
        base = (
            "PMF에 상당히 근접했거나 특정 세그먼트에서는 이미 PMF에 도달한 상태로 해석됩니다. "
            "이 단계에서는 무리한 기능 확장보다는, 검증된 핵심 가치 제안을 중심으로 운영 효율화와 "
            "획득 채널 확장(Performance, 파트너십, 리셀러 등)에 집중하는 전략이 효과적입니다. "
            "동시에 고객 이탈 사유와 NPS를 정기적으로 모니터링하며, PMF 상태가 유지되는지 관리하는 것이 중요합니다."
        )

    # ===== 응답 품질이 낮을 때는 톤을 조금 보수적으로 보정 =====
    if q is not None and q < 25:
        base += (
            " 다만 현재 설문 응답이 매우 간략하게 작성되어 있어, 위 평가는 방향성 참고용으로만 활용하시고 "
            "주요 항목을 보다 구체적인 예시와 데이터로 보완하신 뒤 다시 진단을 받아 보시는 것을 권장드립니다."
        )
    elif q is not None and q < 50:
        base += (
            " 응답의 세부 정보가 아직 충분히 풍부하지는 않아, 점수와 단계는 절대적인 수치라기보다 "
            "대략적인 위치를 가늠하는 용도로 활용해 주시면 좋겠습니다."
        )

    return base


def _value_or_dash(v: str):
    return v if (v and str(v).strip()) else "-"


def generate_pmf_report_v2(data, output_path):
    """
    PMF 리포트 PDF 생성
    data: app.py에서 전달한 pdf_data 딕셔너리
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
    )

    elements = []
    styles = getSampleStyleSheet()

    # ---------- 스타일 ----------
    # 표지용 스타일들 (템플릿 커버 레이아웃 참고)
    cover_top_style = ParagraphStyle(
        "cover_top_style",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=11,
        leading=10,
        alignment=0,  # 왼쪽 정렬
        textColor=colors.HexColor("#666666"),
        spaceAfter=1,
    )

    cover_mid_style = ParagraphStyle(
        "cover_mid_style",
        parent=styles["Normal"],
        fontName=HEADER_FONT,
        fontSize=14,
        leading=14,
        alignment=0,
        textColor=colors.HexColor("#1F4E79"),
        spaceAfter=40,
    )

    title_style = ParagraphStyle(
        "title_style",
        parent=styles["Heading1"],
        fontName=TITLE_FONT,
        fontSize=40,
        leading=60,
        alignment=1,  # 왼쪽 정렬 (표지 메인 타이틀)
        textColor=colors.HexColor("#1F4E79"),
        spaceBefore=27,
        spaceAfter=40,
    )

    cover_info_style = ParagraphStyle(
        "cover_info_style",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=11,
        leading=15,
        alignment=0,
        textColor=colors.HexColor("#333333"),
        spaceBefore=30,
        spaceAfter=4,
    )

    cover_body_style = ParagraphStyle(
        "cover_body_style",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=10.5,
        leading=15,
        alignment=0,  # 왼쪽 정렬
        textColor=colors.HexColor("#666666"),
        spaceAfter=14,
    )

    section_title_style = ParagraphStyle(
        "section_title_style",
        parent=styles["Heading2"],
        fontName=HEADER_FONT,
        fontSize=13,
        leading=18,
        textColor=colors.white,
        backColor=colors.HexColor("#2D89EF"),
        spaceBefore=10,
        spaceAfter=6,
        leftIndent=0,
        rightIndent=0,
        borderPadding=(3, 4, 3),
    )

    body_style = ParagraphStyle(
        "body_style",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#222222"),
    )

    small_style = ParagraphStyle(
        "small_style",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#777777"),
    )

    # ---------- 점수/품질/기본 정보 ----------
    pmf_score = data.get("pmf_score", None)
    pmf_score_raw = data.get("pmf_score_raw", pmf_score)
    pmf_score_mode = data.get("pmf_score_mode", "normal")
    pmf_score_note = data.get("pmf_score_note", "")
    validation_stage = data.get("validation_stage", "N/A")
    validation_stage_raw = data.get("validation_stage_raw", validation_stage)

    data_quality_score = data.get("data_quality_score", None)
    data_quality_label = data.get("data_quality_label", None)

    # app.py에서 품질 정보를 넘겨주지 않은 경우에만 백업 휴리스틱 사용
    if data_quality_score is None or not data_quality_label:
        backup_q = _estimate_data_quality(data)
        data_quality_score = backup_q
        data_quality_label = _quality_label(backup_q)

    startup_name = data.get("startup_name", "N/A")
    industry = data.get("industry", "")
    business_item = data.get("business_item", "")
    stage_label = data.get("startup_stage", "")
    team_size = data.get("team_size", "")
    contact_email = data.get("contact_email", "")

    # ---------- 1. 표지 ----------
    today = datetime.date.today().strftime("%Y-%m-%d")

    # 상단 여백 (템플릿 느낌을 위해 조금 넉넉하게)
    elements.append(Spacer(1, 70))

    # 상단 기관/프로그램 정보
    elements.append(Paragraph("Global Scale-up Accelerator, HAND Partners", cover_top_style))
    elements.append(Paragraph("PMF Studio 진단 프레임워크 기반 분석 리포트", cover_mid_style))

    elements.append(Spacer(1, 35))

    # 메인 타이틀
    elements.append(Paragraph("PMF 진단 리포트", title_style))
    elements.append(Spacer(1, 15))

    # 기업명 / 작성일자
    info_html = f"""
    <b>기업명 :</b> {startup_name}<br/>
    <b>작성일자 :</b> {today}
    """
    elements.append(Paragraph(info_html, cover_info_style))
    elements.append(Spacer(1, 30))

    # 소개 문단 (템플릿 텍스트와 동일한 메시지)
    intro_text = (
        "이 리포트는 HAND PARTNERS의 PMF Studio를 통해 수집된 정보를 바탕으로, "
        "현재 스타트업의 Problem–Solution Fit 및 PMF 신호를 정량·정성적으로 해석한 결과입니다. "
        "각 섹션은 문제–고객–솔루션–트랙션–Go-to-Market 관점에서 핵심 인사이트를 제공하며, "
        "다음 단계 실행을 위한 실질적인 논의 기반으로 활용할 수 있습니다."
    )
    elements.append(Paragraph(intro_text, cover_body_style))
    elements.append(PageBreak())

    # ---------- 2. 스타트업 개요 ----------
    elements.append(Paragraph("1. 스타트업 개요", section_title_style))

    # PMF 점수 표시 문구
    if pmf_score is None or pmf_score_mode == "invalid":
        pmf_score_line = "점수 산출 불가 (데이터 부족)"
    else:
        if pmf_score_mode == "reference":
            pmf_score_line = f"{pmf_score}점 (참고용)"
        else:
            pmf_score_line = f"{pmf_score}점"

    # 데이터 품질 표시 문구
    if data_quality_score is not None and data_quality_label:
        quality_line = f"{data_quality_label} (Data Quality Score: {data_quality_score}/100)"
    else:
        quality_line = "-"

    overview_html = f"""
    <b>• 스타트업명:</b> {startup_name}<br/>
    <b>• PMF 점수:</b> {pmf_score_line}<br/>
    <b>• PMF 단계:</b> {validation_stage}<br/>
    <b>• 입력 데이터 신뢰도:</b> {quality_line}<br/>
    <b>• 현재 단계(창업 단계):</b> {_value_or_dash(stage_label)}<br/>
    <b>• 산업/분야:</b> {_value_or_dash(industry)}<br/>
    <b>• 사업 아이템 소개:</b> {_value_or_dash(business_item)}<br/>
    <b>• 팀 규모:</b> {_value_or_dash(team_size)}<br/>
    <b>• 리포트 수신 이메일:</b> {_value_or_dash(contact_email)}
    """
    elements.append(Paragraph(overview_html, body_style))
    elements.append(Spacer(1, 8))

    if pmf_score_note:
        elements.append(Paragraph(pmf_score_note, small_style))
        elements.append(Spacer(1, 6))

    # ---------- 3. 문제 정의 및 고객 ----------
    elements.append(Paragraph("2. 문제 정의 및 고객 페르소나", section_title_style))

    problem = data.get("problem", "")
    problem_intensity = data.get("problem_intensity", "")
    current_alternatives = data.get("current_alternatives", "")
    willingness_to_pay = data.get("willingness_to_pay", "")
    target = data.get("target", "")
    beachhead_customer = data.get("beachhead_customer", "")
    customer_access = data.get("customer_access", "")

    section2_html = f"""
    <b>2-1) 핵심 문제 정의</b><br/>- {_value_or_dash(problem)}<br/><br/>
    <b>2-2) 문제의 강도/빈도</b><br/>- {_value_or_dash(problem_intensity)}<br/><br/>
    <b>2-3) 현재 고객의 대안/경쟁 솔루션</b><br/>- {_value_or_dash(current_alternatives)}<br/><br/>
    <b>2-4) 고객의 지불 의사/예산</b><br/>- {_value_or_dash(willingness_to_pay)}<br/><br/>
    <b>2-5) 핵심 타겟 고객 세그먼트</b><br/>- {_value_or_dash(target)}<br/><br/>
    <b>2-6) 가장 먼저 공략할 Beachhead 고객</b><br/>- {_value_or_dash(beachhead_customer)}<br/><br/>
    <b>2-7) 고객에 접근/확보할 수 있는 이유와 방법</b><br/>- {_value_or_dash(customer_access)}
    """
    elements.append(Paragraph(section2_html, body_style))
    elements.append(Spacer(1, 10))

    # ---------- 4. 솔루션 및 가치 제안 ----------
    elements.append(Paragraph("3. 솔루션 및 가치 제안", section_title_style))

    solution = data.get("solution", "")
    usp = data.get("usp", "")
    mvp_status = data.get("mvp_status", "")
    pricing_model = data.get("pricing_model", "")

    section3_html = f"""
    <b>3-1) 솔루션 요약</b><br/> - {_value_or_dash(solution)}<br/><br/>
    <b>3-2) USP (차별 포인트)</b><br/> - {_value_or_dash(usp)}<br/><br/>
    <b>3-3) MVP/제품 상태</b><br/> - {_value_or_dash(mvp_status)}<br/><br/>
    <b>3-4) 가격/수익모델</b><br/> - {_value_or_dash(pricing_model)}
    """
    elements.append(Paragraph(section3_html, body_style))
    elements.append(Spacer(1, 10))

    # ---------- 5. 시장 검증 및 Traction ----------
    elements.append(Paragraph("4. 시장 검증 및 Traction", section_title_style))

    market_size = data.get("market_size", "") or data.get("market_data", "")
    users_count = data.get("users_count", "")
    repeat_usage = data.get("repeat_usage", "")
    retention_signal = data.get("retention_signal", "")
    revenue_status = data.get("revenue_status", "")
    key_feedback = data.get("key_feedback", "")

    section4_html = f"""
    <b>4-1) 시장/기회 관련 정보</b><br/> - {_value_or_dash(market_size)}<br/><br/>
    <b>4-2) 현재 사용자 수 및 주요 지표</b><br/>
    - 사용자 수 : {_value_or_dash(users_count)}<br/>
    - 재사용/활성 사용자 신호 : {_value_or_dash(repeat_usage)}<br/>
    - 리텐션/이탈 관련 신호 : {_value_or_dash(retention_signal)}<br/>
    - 매출/유료 전환 현황 : {_value_or_dash(revenue_status)}<br/><br/>
    <b>4-3) 핵심 고객 피드백</b><br/> - {_value_or_dash(key_feedback)}
    """
    elements.append(Paragraph(section4_html, body_style))
    elements.append(Spacer(1, 10))

    # ---------- 6. Go-to-Market 및 PMF 신호 ----------
    elements.append(Paragraph("5. Go-to-Market 및 PMF 신호", section_title_style))

    channels = data.get("channels", "")
    cac_ltv_estimate = data.get("cac_ltv_estimate", "")
    pmf_pull_signal = data.get("pmf_pull_signal", "")
    referral_signal = data.get("referral_signal", "")

    section5_html = f"""
    <b>5-1) 주요 유입/세일즈 채널</b><br/> - {_value_or_dash(channels)}<br/><br/>
    <b>5-2) CAC/LTV 추정치(대략)</b><br/> - {_value_or_dash(cac_ltv_estimate)}<br/><br/>
    <b>5-3) PMF Pull Signal (없으면 큰일 나는 반응/사례)</b><br/> - {_value_or_dash(pmf_pull_signal)}<br/><br/>
    <b>5-4) 추천/바이럴 신호</b><br/> - {_value_or_dash(referral_signal)}
    """
    elements.append(Paragraph(section5_html, body_style))
    elements.append(Spacer(1, 10))

    # ---------- 7. AI 기반 PMF 인사이트 요약 ----------
    elements.append(Paragraph("6. 응답 기반 PMF 인사이트 요약", section_title_style))

    ai_summary = data.get("ai_summary", "")
    if ai_summary:
        # 줄바꿈을 PDF용 <br/>로 변환
        ai_html = (
            ai_summary.replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\n", "<br/>")
        )
    else:
        ai_html = "-"

    section6_html = f"""
    <b>6-1) PMF 인사이트 코멘트</b><br/> - {ai_html}
    """
    elements.append(Paragraph(section6_html, body_style))
    elements.append(Spacer(1, 10))

    # ---------- 8. 종합 제언 및 다음 스텝 ----------
    elements.append(Paragraph("7. HAND PARTNERS PMF 종합 코멘트 및 다음 스텝", section_title_style))

    summary = data.get("summary", "")
    recommendations = data.get("recommendations", "")
    next_experiments = data.get("next_experiments", "")
    biggest_risk = data.get("biggest_risk", "")

    # 1) 사용자가 summary/recommendations를 직접 넣은 경우 우선 사용
    if summary or recommendations:
        summary_text = summary or recommendations
    else:
        # 2) 비어 있으면 PMF 점수/단계/품질을 기반으로 규칙 기반 코멘트 생성
        summary_text = _build_rule_based_summary(
            pmf_score_raw,
            validation_stage_raw,
            data_quality_score,
        )

    section7_html = f"""
    <b>7-1) 다음 4주 핵심 실행/실험 계획</b><br/> - {_value_or_dash(next_experiments)}<br/><br/>
    <b>7-2) 가장 큰 리스크/검증해야 할 가설</b><br/> - {_value_or_dash(biggest_risk)}<br/><br/>
    <b>7-3) HAND PARTNERS PMF 종합 코멘트</b><br/> - {summary_text}<br/><br/>
    """
    elements.append(Paragraph(section7_html, body_style))

    # ---------- 푸터 ----------
    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(BODY_FONT, 8)
        canvas.setFillColor(colors.HexColor("#2D89EF"))
        canvas.drawString(20 * mm, 10 * mm, "Global Scale-up Accelerator, HAND Partners")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
