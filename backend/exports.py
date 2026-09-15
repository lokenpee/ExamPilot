from __future__ import annotations

import os
import re
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from backend.schemas import LABELS


# XML 1.0 rejects most C0 control characters, DEL and lone surrogates.
# Replace them with spaces so arbitrary model/course text can always be exported.
_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]")


def xml_safe(value) -> str:
    return _XML_INVALID.sub(" ", str(value))


def location_label(locator: dict):
    if locator["kind"] == "pdf":
        return f"PDF 第 {locator['page_number']} 页"
    if locator["kind"] == "pptx":
        return f"第 {locator['slide_number']} 张幻灯片"
    if "paragraph_index" in locator:
        return f"第 {locator['paragraph_index']} 段"
    return f"表 {locator['table_index']}，第 {locator['row_index']} 行第 {locator['cell_index']} 列"


def answer_text(answer):
    if type(answer) is bool:
        return "正确" if answer else "错误"
    return "；".join(answer) if isinstance(answer, list) else str(answer)


def ordered_questions(exam):
    order = list(LABELS)
    return sorted(exam["questions"], key=lambda q: (order.index(q["type"]), q["display_order"]))


def export_docx(exam: dict, path: Path, teacher: bool):
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2.2)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    style.paragraph_format.space_after = Pt(7)
    doc.add_heading(xml_safe(exam["title"]) + (" · 答案解析" if teacher else ""), 0)
    doc.add_paragraph(f"总分：{exam['target_score_units'] / 2:g} 分    考试时间：{exam['duration_minutes']} 分钟")
    if not teacher:
        doc.add_paragraph("姓名：________________    学号：________________")
    current_type = None
    for number, question in enumerate(ordered_questions(exam), 1):
        if question["type"] != current_type:
            current_type = question["type"]
            doc.add_heading(LABELS[current_type], 1)
        paragraph = doc.add_paragraph(f"{number}. {xml_safe(question['stem'])}（{question['score_units']/2:g} 分）")
        paragraph.paragraph_format.keep_with_next = True
        if teacher:
            doc.add_paragraph("答案：" + xml_safe(answer_text(question["answer"])))
            for rubric in question.get("rubric", []):
                doc.add_paragraph(f"• {xml_safe(rubric['text'])}（{rubric['score_units']/2:g} 分）")
            doc.add_paragraph("解析：" + xml_safe(question["analysis"]))
            doc.add_paragraph("知识点：" + xml_safe(question["knowledge_point"]) + "    目标难度：" + {"easy": "易", "medium": "中", "hard": "难"}[question["difficulty"]])
            for citation in question["citations"]:
                doc.add_paragraph(f"原文依据：{xml_safe(citation['document_name'])} · {location_label(citation['locator'])}\n“{xml_safe(citation['text'])}”")
        else:
            # Explicit whitelist: no answer, rationale, metadata, annotations or citations.
            for option in question.get("options", []):
                doc.add_paragraph(f"{option['id']}. {xml_safe(option['text'])}")
            if question["type"] in ("short_answer", "calculation"):
                for _ in range(4):
                    doc.add_paragraph("________________________________________________________________")
    footer = section.footer.paragraphs[0]
    footer.alignment = 1
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    doc.core_properties.title = xml_safe(exam["title"])
    doc.core_properties.author = "ExamPilot"
    doc.core_properties.comments = ""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.docx")
    doc.save(temporary)
    os.replace(temporary, path)

