from pathlib import Path

from docx import Document

from backend.exports import export_docx, xml_safe
from backend.ingestion import _clean_text


def _text(path: Path) -> str:
    return "\n".join(p.text for p in Document(path).paragraphs)


def test_xml_safe_replaces_control_characters():
    assert xml_safe("a\x00b\x0bc\x0cd\x1fe") == "a b c d e"
    assert _clean_text("财政学  \x0b Public Finance") == "财政学 Public Finance"


def test_export_docx_accepts_control_characters(tmp_path: Path):
    exam = {
        "title": "测试\x0b试卷",
        "target_score_units": 8,
        "duration_minutes": 10,
        "questions": [
            {
                "type": "single_choice",
                "score_units": 8,
                "stem": "题干\x00包含控制字符",
                "options": [
                    {"id": "A", "text": "选项\x0cA"},
                    {"id": "B", "text": "选项B"},
                ],
                "answer": ["A"],
                "analysis": "解析\x1f内容",
                "knowledge_point": "知识点\x0b名称",
                "difficulty": "easy",
                "display_order": 1,
                "rubric": [],
                "citations": [
                    {
                        "document_name": "资料\x0b名称",
                        "locator": {"kind": "pptx", "slide_number": 1},
                        "text": "原文\x0b内容",
                    }
                ],
            }
        ],
    }
    student = tmp_path / "student.docx"
    teacher = tmp_path / "teacher.docx"

    export_docx(exam, student, False)
    export_docx(exam, teacher, True)

    student_text = _text(student)
    teacher_text = _text(teacher)
    assert "题干 包含控制字符" in student_text
    assert "选项 A" in student_text
    assert "答案：" not in student_text and "解析：" not in student_text
    assert "答案：A" in teacher_text
    assert "解析：解析 内容" in teacher_text
    assert not any(ord(ch) < 32 and ch not in "\n\r\t" for ch in student_text + teacher_text)
