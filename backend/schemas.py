from __future__ import annotations

from typing import Literal
from decimal import Decimal, InvalidOperation
import re
from pydantic import BaseModel, Field, model_validator

QuestionType = Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer", "calculation"]
Difficulty = Literal["easy", "medium", "hard"]
LABELS = {"single_choice": "单选题", "multiple_choice": "多选题", "true_false": "判断题", "fill_blank": "填空题", "short_answer": "简答题", "calculation": "计算题"}


def allocate_difficulty(count: int, percentages: tuple[int, int, int]):
    if type(count) is not int or count < 0:
        raise ValueError("题数必须是非负整数")
    if len(percentages) != 3 or any(type(p) is not int or not 0 <= p <= 100 for p in percentages) or sum(percentages) != 100:
        raise ValueError("三个整数百分比必须合计 100")
    quotas = [count * p // 100 for p in percentages]
    remainders = [count * p % 100 for p in percentages]
    tie = {1: 0, 0: 1, 2: 2}
    order = sorted(range(3), key=lambda i: (-remainders[i], tie[i]))
    for i in order[:count - sum(quotas)]:
        quotas[i] += 1
    return tuple(quotas)


def candidate_score_units(previous_units: int, message: str, model_score):
    """Keep scores stable unless requested; convert displayed points to storage units in code."""
    explicit = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*分(?!钟|之)", message)
    if len(explicit) == 1:
        value = explicit[0]
    elif re.search(r"(?:分数|分值|分)\s*(?:不变|保持不变)|(?:保留|保持)[^。！？\n]{0,30}(?:分数|分值)", message) and not re.search(r"(?:分数|分值)\s*(?:请|需要|要)?\s*(?:改为|调整|增加|减少)|(?:增加|减少|提高|降低)\s*(?:\d+|[一二三四五六七八九十两半]+)\s*分", message):
        return previous_units
    elif not re.search(r"分|score|points?", message, flags=re.I):
        return previous_units
    else:
        value = model_score
    try:
        points = Decimal(str(value))
        units = points * 2
        if not points.is_finite() or not 0 < points <= 500 or units != units.to_integral_value():
            raise ValueError("补题分值须为 0.5–500 分，且以 0.5 分递增")
        return int(units)
    except (InvalidOperation, TypeError):
        raise ValueError("未能识别补题分值，请明确填写例如 5 分")


class Section(BaseModel):
    type: QuestionType
    count: int = Field(ge=0, le=50, strict=True)
    score_units: int = Field(gt=0, le=1000, strict=True)


class ExamConfig(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    total_score_units: int = Field(gt=0, le=1000, strict=True)
    duration_minutes: int = Field(gt=0, le=300, strict=True)
    sections: list[Section]
    ratios: tuple[int, int, int] = (30, 50, 20)
    requirements: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def valid(self):
        allocate_difficulty(0, self.ratios)
        if len({s.type for s in self.sections}) != len(self.sections):
            raise ValueError("题型不能重复")
        if not 1 <= sum(s.count for s in self.sections) <= 50:
            raise ValueError("总题数应为 1–50")
        if sum(s.count * s.score_units for s in self.sections) != self.total_score_units:
            raise ValueError("各题分数合计必须等于目标总分")
        return self


class Option(BaseModel):
    id: str = Field(min_length=1, max_length=10)
    text: str = Field(min_length=1)


class Rubric(BaseModel):
    text: str = Field(min_length=1)
    score_units: int = Field(gt=0, strict=True)


class Question(BaseModel):
    type: QuestionType
    difficulty: Difficulty
    score_units: int = Field(gt=0, le=1000, strict=True)
    knowledge_point: str = Field(min_length=1)
    stem: str = Field(min_length=2, max_length=12000)
    options: list[Option] = []
    answer: str | bool | list[str]
    rubric: list[Rubric] = []
    analysis: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def answer_structure(self):
        ids = [o.id for o in self.options]
        if len(ids) != len(set(ids)) or len({o.text.strip() for o in self.options}) != len(ids):
            raise ValueError("选项编号和内容不能重复")
        if self.type in ("single_choice", "multiple_choice"):
            if len(ids) < 2 or not isinstance(self.answer, list) or not set(self.answer) <= set(ids):
                raise ValueError("选择题答案必须是存在的选项 ID 数组")
            if len(set(self.answer)) != len(self.answer):
                raise ValueError("答案不能重复")
            if self.type == "single_choice" and len(self.answer) != 1:
                raise ValueError("单选题只允许一个答案")
            if self.type == "multiple_choice" and len(self.answer) < 2:
                raise ValueError("多选题至少两个正确答案")
        elif self.type == "true_false":
            if type(self.answer) is not bool:
                raise ValueError("判断题答案必须是 true 或 false")
        elif self.type == "fill_blank":
            if not isinstance(self.answer, list) or not self.answer or any(not x.strip() for x in self.answer):
                raise ValueError("填空题答案必须按空排列")
            if self.stem.count("____") != len(self.answer):
                raise ValueError("每空使用 ____，空数必须与答案数一致")
        else:
            if not isinstance(self.answer, str) or not self.answer.strip():
                raise ValueError("简答／计算题必须有参考答案")
            if sum(r.score_units for r in self.rubric) != self.score_units:
                raise ValueError("评分要点合计必须等于题目分数")
        if self.type not in ("single_choice", "multiple_choice") and self.options:
            raise ValueError("该题型不能带选择题选项")
        if self.type not in ("short_answer", "calculation") and self.rubric:
            raise ValueError("客观题不应包含主观题评分要点")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("引用不能重复")
        return self


def base_slots(config: ExamConfig):
    slots = []
    for section in config.sections:
        for difficulty, count in zip(("easy", "medium", "hard"), allocate_difficulty(section.count, config.ratios)):
            for _ in range(count):
                slots.append({"id": f"slot_{len(slots)+1}", "type": section.type, "difficulty": difficulty, "score_units": section.score_units})
    return slots
