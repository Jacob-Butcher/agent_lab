import io

from docx import Document
from docx.shared import Inches
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.util import Inches as PptxInches
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Image as ReportLabImage,
)
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)


def png_bytes(width: int = 200, height: int = 100, color=(200, 30, 30)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_docx(title: str | None = None) -> bytes:
    document = Document()
    if title:
        document.core_properties.title = title
    document.add_heading("退款政策", level=1)
    document.add_paragraph("订单签收后 7 天内可申请无理由退货。")
    document.add_paragraph("列表项", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "类型"
    table.cell(0, 1).text = "时效"
    table.cell(1, 0).text = "无理由"
    table.cell(1, 1).text = "7 天"
    document.add_picture(io.BytesIO(png_bytes()), width=Inches(2))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_empty_docx() -> bytes:
    buffer = io.BytesIO()
    Document().save(buffer)
    return buffer.getvalue()


def make_pptx(title: str | None = None, slide_count: int = 1) -> bytes:
    presentation = Presentation()
    if title:
        presentation.core_properties.title = title
    for index in range(slide_count):
        slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        slide.shapes.title.text = (
            f"售后培训 {index + 1}" if slide_count > 1 else "售后培训"
        )
        box = slide.shapes.add_textbox(
            PptxInches(1), PptxInches(1), PptxInches(4), PptxInches(1)
        )
        if index == 0:
            box.text_frame.text = "退款 3 到 7 个工作日到账。"
            table = slide.shapes.add_table(
                2, 2, PptxInches(1), PptxInches(2.5), PptxInches(4), PptxInches(1)
            ).table
            table.cell(0, 0).text = "类型"
            table.cell(0, 1).text = "时效"
            table.cell(1, 0).text = "退款"
            table.cell(1, 1).text = "7 天"
            slide.shapes.add_picture(
                io.BytesIO(png_bytes()),
                PptxInches(1),
                PptxInches(4),
                width=PptxInches(1),
            )
        else:
            box.text_frame.text = f"第 {index + 1} 页内容"
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def make_empty_pptx() -> bytes:
    buffer = io.BytesIO()
    Presentation().save(buffer)
    return buffer.getvalue()


def make_pptx_with_placeholder_picture() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[8])
    slide.shapes.title.text = "占位图"
    placeholder = next(
        shape
        for shape in slide.placeholders
        if shape.placeholder_format.type == PP_PLACEHOLDER.PICTURE
    )
    placeholder.insert_picture(io.BytesIO(png_bytes()))
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def make_pptx_with_blank_slide() -> bytes:
    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "第二页"
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def make_pdf(title: str | None = None) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=letter, title=title)
    styles = getSampleStyleSheet()
    table = Table([["Type", "Window"], ["No reason", "7 days"]])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    document.build(
        [
            Paragraph("Refund Policy", styles["Title"]),
            table,
            PageBreak(),
            Paragraph("Second page text", styles["Normal"]),
        ]
    )
    return buffer.getvalue()


def make_image_only_pdf() -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=letter)
    document.build(
        [ReportLabImage(io.BytesIO(png_bytes()), width=200, height=100)]
    )
    return buffer.getvalue()
