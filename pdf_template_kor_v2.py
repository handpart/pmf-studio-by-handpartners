from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.units import mm
import datetime


# 한글 폰트 등록 (ReportLab 내장 CJK 폰트)
try:
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    BASE_FONT = "HYSMyeongJo-Medium"
except Exception:
    # 혹시 실패해도 기본 폰트로 동작은 하게
    BASE_FONT = "Helvetica"


def generate_pmf_report_v2(data, output_path):
    """
    data: dict
      - startup_name, pmf_score, validation_stage
      - problem, solution, target, market_data, summary
      - usp, ai_summary, recommendations 등
    """
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    elements = []

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "title_style",
        parent=styles["Heading1"],
        fontName=BASE_FONT,
        fontSize=22,
        leading=28,
        alignment=1,
        textColor=colors.HexColor("#2D89EF"),
    )

    header_style = ParagraphStyle(
        "header_style",
        parent=styles["Heading2"],
        fontName=BASE_FONT,
        fontSize=12,
        leading=16,
        textColor=colors.white,
        backColor=colors.HexColor("#2D89EF"),
        spaceBefore=12,
        spaceAfter=6,
        leftIndent=0,
        rightIndent=0,
        padding=4,
    )

    body_style = ParagraphStyle(
        "body_style",
        parent=styles["Normal"],
        fontName=BASE_FONT,
        fontSize=10,
        leading=14,
    )

    small_style = ParagraphStyle(
        "small_style",
        parent=styles["Normal"],
        fontName=BASE_FONT,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#555555"),
    )

    # -------------------------
    # 1) 표지
    # -------------------------
    today = datetime.date.today().strftime("%Y-%m-%d")
    startup_name = data.get("startup_name", "N/A")

    cover_html = f"""
    <para align="center">
      <font size=24 color="#2D89EF"><b>PMF 진단 리포트</b></font><br/><br/>
      <font size=14><b>{startup_name}</b></font><br/><br/>
      <font size=11>Global Scale-up Accelerator, HAND Partners</font><br/><br/>
      <font size=10>{today}</font>
    </para>
    """

    elements.append(Paragraph(cover_html, body_style))
    elements.append(Spacer(1, 40))
    elements.append(Paragraph(
        "이 리포트는 HAND PARTNERS의 PMF Studio 진단 프레임워크를 기반으로, "
        "현재 스타트업의 Problem–Solution Fit 및 초기 PMF 신호를 정량·정성적으로 해석한 결과입니다.",
        small_style,
    ))
    elements.append(PageBreak())

    # -------------------------
    # 2) 스타트업 개요
    # -------------------------
    elements.append(Paragraph("1. 스타트업 개요", header_style))

    pmf_score = data.get("pmf_score", "N/A")
    validation_stage = data.get("validation_stage", "N/A")
    industry = data.get("industry", "")
    stage_label = data.get("startup_stage", "")

    overview_html = f"""
    • 스타트업명: <b>{startup_name}</b><br/>
    • PMF 점수: <b>{pmf_score}</b><br/>
    • PMF 단계: <b>{validation_stage}</b><br/>
    • 현재 단계(창업 단계): {stage_label or '-'}<br/>
    • 산업/분야: {industry or '-'}
    """
    elements.append(Paragraph(overview_html, body_style))
    elements.append(Spacer(1, 12))

    # -------------------------
    # 3) 문제 정의 및 고객 페르소나
    # -------------------------
    elements.append(Paragraph("2. 문제 정의 및 고객 페르소나", header_style))

    problem = data.get("problem", "") or "입력된 문제 정의가 없습니다."
    target = data.get("target", "") or "입력된 타겟 고객 정보가 없습니다."
    problem_intensity = data.get("problem_intensity", "")
    current_alternatives = data.get("current_alternatives", "")
    willingness_to_pay = data.get("willingness_to_pay", "")

    section2_html = f"""
    <b>핵심 문제 정의</b><br/>{problem}<br/><br/>
    <b>문제의 강도/빈도</b><br/>{problem_intensity or '-'}<br/><br/>
    <b>현재 고객의 대안/경쟁 솔루션</b><br/>{current_alternatives or '-'}<br/><br/>
    <b>고객의 지불 의사/예산</b><br/>{willingness_to_pay or '-'}<br/><br/>
    <b>핵심 타겟 고객 세그먼트</b><br/>{target}
    """
    elements.append(Paragraph(section2_html, body_style))
    elements.append(Spacer(1, 12))

    # -------------------------
    # 4) 솔루션 및 가치 제안
    # -------------------------
    elements.append(Paragraph("3. 솔루션 및 가치 제안", header_style))

    solution = data.get("solution", "") or "입력된 솔루션 설명이 없습니다."
    usp = data.get("usp", "") or "입력된 차별화 요소가 없습니다."
    pricing_model = data.get("pricing_model", "")
    mvp_status = data.get("mvp_status", "")

    section3_html = f"""
    <b>솔루션 요약</b><br/>{solution}<br/><br/>
    <b>USP (차별 포인트)</b><br/>{usp}<br/><br/>
    <b>MVP/제품 상태</b><br/>{mvp_status or '-'}<br/><br/>
    <b>가격/수익모델</b><br/>{pricing_model or '-'}
    """
    elements.append(Paragraph(section3_html, body_style))
    elements.append(Spacer(1, 12))

    # -------------------------
    # 5) 시장 검증 / 트랙션
    # -------------------------
    elements.append(Paragraph("4. 시장 검증 및 Traction", header_style))

    market_data = data.get("market_data", "") or data.get("market_size", "") or ""
    users_count = data.get("users_count", "")
    repeat_usage = data.get("repeat_usage", "")
    revenue_status = data.get("revenue_status", "")
    key_feedback = data.get("key_feedback", "")
    ai_summary = data.get("ai_summary", "")

    section4_html = f"""
    <b>시장/기회 관련 정보</b><br/>{market_data or '-'}<br/><br/>
    <b>현재 사용자 수 및 주요 지표</b><br/>
    - 사용자 수: {users_count or '-'}<br/>
    - 재사용/활성 사용자 신호: {repeat_usage or '-'}<br/>
    - 매출/유료 전환 현황: {revenue_status or '-'}<br/><br/>
    <b>핵심 고객 피드백</b><br/>{key_feedback or '-'}<br/><br/>
    <b>AI 기반 PMF 인사이트 요약</b><br/>{ai_summary or '-'}
    """
    elements.append(Paragraph(section4_html, body_style))
    elements.append(Spacer(1, 12))

    # -------------------------
    # 6) 종합 제언 및 다음 스텝
    # -------------------------
    elements.append(Paragraph("5. 종합 제언 및 다음 스텝", header_style))

    summary = data.get("summary", "")  # 내부에서 만든 종합 요약
    recommendations = data.get("recommendations", "")
    next_experiments = data.get("next_experiments", "")
    biggest_risk = data.get("biggest_risk", "")

    if not summary and not recommendations:
        summary_text = "입력된 종합 요약/제언이 없습니다. 향후 HAND PARTNERS 멘토링 세션을 통해 보완하시는 것을 권장합니다."
    else:
        summary_text = summary or recommendations

    section5_html = f"""
    <b>HAND PARTNERS PMF 종합 코멘트</b><br/>{summary_text}<br/><br/>
    <b>다음 4주 핵심 실행/실험 계획</b><br/>{next_experiments or '-'}<br/><br/>
    <b>가장 큰 리스크/검증해야 할 가설</b><br/>{biggest_risk or '-'}
    """
    elements.append(Paragraph(section5_html, body_style))

    # -------------------------
    # 푸터
    # -------------------------
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#2D89EF"))
        canvas.drawString(20 * mm, 10 * mm, "Global Scale-up Accelerator, HAND Partners")
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
