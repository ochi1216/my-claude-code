"""比較・描画で使うデータモデル（IMPLEMENTATION_PLAN.md 4〜7章）。"""
from dataclasses import dataclass, field

from pdf_reader import Word


@dataclass
class TextUnit:
    section_path: tuple[str, ...]
    unit_type: str  # heading / paragraph / bullet / numbered_item / field
    raw_text: str
    normalized_text: str
    font_size: float
    words: list[Word] = field(default_factory=list)


@dataclass
class DiffResult:
    curr_unit: TextUnit | None  # Noneなら今週側に対応なし（deleted）
    prev_unit: TextUnit | None  # Noneなら前週側に対応なし（added）
    change_type: str  # unchanged / added / modified / moved / deleted
    similarity: float  # 0-100
    changed_words: list[Word]  # 単語単位で青太字化する対象（whole_unit=Trueの場合は空）
    whole_unit: bool  # Trueなら changed_words でなくunit全体を青太字化する
