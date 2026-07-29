"""比較用テキスト正規化（IMPLEMENTATION_PLAN.md 4章）。

原文（raw_text）は変更せず、比較専用の文字列だけをこのモジュールで作る。
改行位置・空白数・箇条書き記号・ダッシュ表記ゆれの違いは比較対象から除外する。
"""
import re
import unicodedata

_BULLET_RE = re.compile(r"^\s*[•・\-\*]\s*")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s*")
_WS_RE = re.compile(r"\s+")
_DASH_RE = re.compile(r"[‐‑‒–—―ー]")  # ハイフン各種・ダッシュ・長音記号


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.strip()
    text = _BULLET_RE.sub("", text)
    text = _NUMBERED_RE.sub("", text)
    text = _DASH_RE.sub("-", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()
