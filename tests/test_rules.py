import io
import zipfile

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from backend.ingestion import parse_document
from backend.schemas import allocate_difficulty, ExamConfig, Question, candidate_score_units
from backend.exports import export_docx


def test_all_difficulty_splits():
    for count in range(51):
        for easy in range(101):
            for medium in range(101 - easy):
                ratios = (easy, medium, 100 - easy - medium)
                result = allocate_difficulty(count, ratios)
                assert sum(result) == count
                assert all(q in (count*p//100, (count*p+99)//100) for q,p in zip(result,ratios))
    assert allocate_difficulty(10,(30,50,20)) == (3,5,2)
    assert allocate_difficulty(3,(30,50,20)) == (1,1,1)


def test_configuration_rejects_fractional_counts_and_total_mismatch():
    base = dict(title="Test", total_score_units=20,duration_minutes=60,sections=[dict(type="single_choice", count=2, score_units=10)])
    assert ExamConfig.model_validate(base)
    with pytest.raises(ValueError):
        ExamConfig.model_validate({**base,"total_score_units":21})
    with pytest.raises(ValueError):
        ExamConfig.model_validate({**base,"sections":[dict(type="single_choice",count=2.5,score_units=8)]})


def test_candidate_points_are_converted_by_code_and_do_not_drift():
    assert candidate_score_units(10, "保持 5 分，换成单选题", 2.5) == 10
    assert candidate_score_units(10, "保留题型和分数，把题干改为转账场景", 2.5) == 10
    assert candidate_score_units(10, "请把解释写清楚", 30) == 10
    assert candidate_score_units(10, "改成 2.5 分", 2.5) == 5
    assert candidate_score_units(10, "原来 5 分，改为 7 分", 7) == 14
    with pytest.raises(ValueError):
        candidate_score_units(10, "改成 2.3 分", 2.3)


def test_pdf_physical_page_and_scan_rejection(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600,height=800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 40 700 Td (Transactions provide atomicity.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    path=tmp_path/'text.pdf'
    writer.write(path)
    chunks=parse_document(path,'doc_a','text.pdf')
    assert chunks[0]['locator']['page_number']==1
    assert 'atomicity' in chunks[0]['text']
    writer=PdfWriter();writer.add_blank_page(width=600,height=800)
    writer.write(tmp_path/'scan.pdf')
    with pytest.raises(ValueError,match='没有可提取文字'):
        parse_document(tmp_path/'scan.pdf','doc_b','scan.pdf')


def test_docx_and_pptx_source_mapping(tmp_path):
    from scripts.create_samples import create
    create(tmp_path)
    for suffix in ('*.docx','*.pptx'):
        file=next(tmp_path.glob(suffix))
        chunks=parse_document(file,'doc_test',file.name)
        assert chunks
        for chunk in chunks:
            for segment in chunk['segments']:
                assert chunk['text'][segment['span_start']:segment['span_end']]==segment['text']
            if suffix=='*.docx':
                assert 'page_number' not in chunk['locator']
            else:
                assert chunk['locator']['slide_number']>=1


def test_student_export_has_no_teacher_fields(tmp_path):
    exam={"title":"真实导出测试","target_score_units":10,"duration_minutes":60,"questions":[{"id":"q","type":"single_choice","difficulty":"medium","score_units":10,"display_order":1,"knowledge_point":"SECRET_KNOWLEDGE","stem":"Which option is correct?","options":[{"id":"A","text":"First"},{"id":"B","text":"Second"}],"answer":["A"],"analysis":"SECRET_RATIONALE_123","rubric":[],"citations":[{"document_name":"SECRET_SOURCE_456","locator":{"kind":"pdf","page_number":9},"text":"SECRET_QUOTE_789"}]}]}
    student=tmp_path/'student.docx';teacher=tmp_path/'teacher.docx'
    export_docx(exam,student,False);export_docx(exam,teacher,True)
    with zipfile.ZipFile(student) as z:
        xml='\n'.join(z.read(n).decode('utf-8') for n in z.namelist() if n.endswith('.xml'))
    assert 'SECRET_' not in xml
    assert 'Which option is correct?' in xml
    with zipfile.ZipFile(teacher) as z:
        assert 'SECRET_RATIONALE_123' in z.read('word/document.xml').decode()
