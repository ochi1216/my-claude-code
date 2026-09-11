"""Weekly1件分の行をセクション階層のTextUnit列に変換する（IMPLEMENTATION_PLAN.md 5章）。

罫線付きの表が存在しないため、表専用のパーサーは持たず、
「見出し（Bold）＋箇条書き／番号付き／ラベル:値／通常文章」の単一モデルで扱う。
"""
import re

from models import TextUnit
from normalize import normalize_text
from pdf_reader import Line, Word, words_on_line

TOP_HEADINGS = {"Work Plan", "Weekly update", "Summary Project"}
SUB_HEADINGS = {"STR", "Reliability", "Others"}

# Thank you./Regards以降は署名ブロックとみなし、そのWeeklyの末尾まで比較対象から除外する
_STOP_MARKERS = {"thank you.", "regards"}

_EXCLUDE_EXACT = {
    "hello ochi san.",
    "please refer to my weekly report as follows.",
}

_EMAIL_HEADER_RE = re.compile(r"^(From|Sent|To|Cc|Subject):")
_ONENOTE_FOOTER_RE = re.compile(r"^\d{4}_\d{2} - \d+ ページ$")
_ONENOTE_DATE_RE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*[AP]?M?$", re.IGNORECASE)

_BULLET_RE = re.compile(r"^\s*[•・\-\*]\s*")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s*")
_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 /]{1,40}:\s")
_PROJECT_NAME_FIELD_RE = re.compile(r"^Project Name:\s*(.+)$", re.IGNORECASE)

# 継続行とみなすX座標の許容差（pt）。実PDFで、罫線のない別列の見出し
# （例: 狭い列に折り返された"Reliability"が"Reliabi"/"lity"の2行に分割される
# ケース）がY座標だけでは隣接する別列の項目と区別できず、継続行として誤って
# 結合されてしまう実例を確認したため、X座標が離れている場合は継続とみなさない。
_CONTINUATION_X_TOLERANCE = 20.0


def _is_excluded(text: str) -> bool:
    t = text.strip()
    low = t.lower()
    if low in _EXCLUDE_EXACT:
        return True
    if _EMAIL_HEADER_RE.match(t):
        return True
    if _ONENOTE_FOOTER_RE.match(t):
        return True
    if _ONENOTE_DATE_RE.match(t):
        return True
    if _TIME_RE.match(t):
        return True
    return False


def _looks_like_project_name(text: str) -> bool:
    stripped = _BULLET_RE.sub("", text).strip()
    if not stripped or stripped in TOP_HEADINGS or stripped in SUB_HEADINGS:
        return False
    if _FIELD_RE.match(stripped):
        return False
    return len(stripped) <= 60


def _classify(text: str) -> str:
    t = text.strip()
    if _BULLET_RE.match(t):
        return "bullet"
    if _NUMBERED_RE.match(t):
        return "numbered_item"
    if _FIELD_RE.match(t):
        return "field"
    return "paragraph"


def _is_new_item_start(text: str) -> bool:
    t = text.strip()
    return bool(_BULLET_RE.match(t) or _NUMBERED_RE.match(t) or _FIELD_RE.match(t))


def build_units(lines: list[Line], words: list[Word]) -> list[TextUnit]:
    units: list[TextUnit] = []
    section_path: tuple[str, ...] = ()
    in_summary_project = False
    in_weekly_update = False
    current_project: str | None = None
    skipping_signature = False
    current_unit_lines: list[Line] = []

    def flush() -> None:
        if not current_unit_lines:
            return
        raw_text = " ".join(l.text.strip() for l in current_unit_lines)
        unit_words: list[Word] = []
        for l in current_unit_lines:
            unit_words.extend(words_on_line(l, words))
        units.append(
            TextUnit(
                section_path=section_path,
                unit_type=_classify(current_unit_lines[0].text),
                raw_text=raw_text,
                normalized_text=normalize_text(raw_text),
                font_size=current_unit_lines[0].font_size,
                words=unit_words,
            )
        )
        current_unit_lines.clear()

    for line in lines:
        text = line.text.strip()

        if skipping_signature:
            continue

        if text.lower() in _STOP_MARKERS:
            flush()
            skipping_signature = True
            continue

        if _is_excluded(text):
            continue

        if line.bold and text in TOP_HEADINGS:
            flush()
            section_path = (text,)
            in_summary_project = text == "Summary Project"
            in_weekly_update = text == "Weekly update"
            current_project = None
            continue

        if text in SUB_HEADINGS and in_summary_project and current_project:
            flush()
            section_path = ("Summary Project", current_project, text)
            continue

        project_match = _PROJECT_NAME_FIELD_RE.match(text) if in_summary_project else None
        if project_match:
            flush()
            current_project = project_match.group(1).strip()
            section_path = ("Summary Project", current_project)
            current_unit_lines.append(line)  # フィールド行自体も比較対象に含める
            continue

        if line.bold and in_weekly_update and _looks_like_project_name(text):
            flush()
            current_project = _BULLET_RE.sub("", text).strip()
            section_path = ("Weekly update", current_project)
            continue

        starts_new_unit = _is_new_item_start(text) or not current_unit_lines
        if not starts_new_unit:
            last_line = current_unit_lines[-1]
            if abs(line.x0 - last_line.x0) > _CONTINUATION_X_TOLERANCE:
                starts_new_unit = True  # X座標が大きく離れており、別列の見出し等と判断

        if starts_new_unit:
            flush()
        current_unit_lines.append(line)

    flush()
    return units
