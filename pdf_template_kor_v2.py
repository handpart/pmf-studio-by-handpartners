from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.units import mm
import datetime
try:
    pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
except Exception:
    pass

def generate_pmf_report_v2(data, output_path):
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title_style', parent=styles['Heading1'], fontSize=20, alignment=1, textColor=colors.HexColor('#2D89EF'))
    header_style = ParagraphStyle('header_style', parent=styles['Heading2'], fontSize=12, textColor=colors.white, backColor=colors.HexColor('#2D89EF'))
    body_style = ParagraphStyle('body_style', parent=styles['Normal'], fontSize=10, leading=14)
    today = datetime.date.today().strftime("%Y-%m-%d")
    cover = f'<para align="center"><font size=24 color="#2D89EF"><b>PMF 진단 리포트</b></font><br/><br/><font size=12>Global Scale-up Accelerator, HAND Partners</font><br/><br/>{today}</para>'
    elements.append(Paragraph(cover, body_style))
    elements.append(PageBreak())
    elements.append(Paragraph("1. 스타트업 개요", header_style))
    overview = f"• 스타트업명: {data.get('startup_name','N/A')}<br/>• PMF 점수: {data.get('pmf_score','N/A')}<br/>• 단계: {data.get('validation_stage','N/A')}"
    elements.append(Paragraph(overview, body_style))
    elements.append(Spacer(1,12))
    elements.append(Paragraph("2. 문제 정의 및 고객 페르소나", header_style))
    elements.append(Paragraph(data.get('problem',''), body_style))
    elements.append(Spacer(1,12))
    elements.append(Paragraph("3. 솔루션 및 가치 제안", header_style))
    elements.append(Paragraph(data.get('solution',''), body_style))
    elements.append(Spacer(1,12))
    elements.append(Paragraph("4. 시장 검증 데이터", header_style))
    elements.append(Paragraph(data.get('market_data',''), body_style))
    elements.append(Spacer(1,12))
    elements.append(Paragraph("5. 종합 제언", header_style))
    elements.append(Paragraph(data.get('summary',''), body_style))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#2D89EF'))
        canvas.drawString(20*mm, 10*mm, "Global Scale-up Accelerator, HAND Partners")
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
