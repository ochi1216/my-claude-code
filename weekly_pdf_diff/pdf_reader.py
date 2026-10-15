"""PyMuPDFの薄いラッパー。ページごとの行・単語情報を抽出する。"""
from dataclasses import dataclass

import fitz


@dataclass
class Line:
    page: int  # 0-indexed
    x0: float
    y0: float
    y1: float
    text: str
    bold: bool
    font_size: float


@dataclass
class Word:
    page: int  # 0-indexed
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def _dominant_span_font_size(spans: list[dict]) -> float:
    """行内で最も文字数の多いspanのフォントサイズを返す。

    実データでは、自動採番の"1."等が本文（Arial）とは異なるフォント
    （YuGothic-Regular、微妙に異なるサイズ）で描画されており、先頭spanを
    そのまま使うと採番のサイズを本文サイズとして誤用し、太字描画時の幅計算が
    狂って隣接単語と接触する不具合を実機で確認した。
    """
    dominant_span = max(spans, key=lambda s: len(s["text"]))
    return dominant_span["size"]


def extract_lines(doc: fitz.Document) -> list[Line]:
    lines: list[Line] = []
    for page_no, page in enumerate(doc):
        text_dict = page.get_text("dict")
        for block in text_dict["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                text = "".join(span["text"] for span in line["spans"])
                if not text.strip():
                    continue
                bold = any(span["flags"] & 2**4 for span in line["spans"])
                font_size = _dominant_span_font_size(line["spans"])
                x0, y0, _, y1 = line["bbox"]
                lines.append(
                    Line(
                        page=page_no,
                        x0=x0,
                        y0=y0,
                        y1=y1,
                        text=text,
                        bold=bold,
                        font_size=font_size,
                    )
                )
    # get_text("dict")のブロック順は必ずしも視覚的な上→下順ではない
    # （実PDFで、日時スタンプが本文より先にY座標的には上にあるのに
    # ブロック順としては後に現れる例を確認済み）。ページ内はY座標で並べ替える。
    lines.sort(key=lambda line: (line.page, line.y0))
    return lines


def extract_words(doc: fitz.Document) -> list[Word]:
    words: list[Word] = []
    for page_no, page in enumerate(doc):
        for x0, y0, x1, y1, text, *_ in page.get_text("words"):
            words.append(Word(page=page_no, x0=x0, y0=y0, x1=x1, y1=y1, text=text))
    words.sort(key=lambda w: (w.page, w.y0, w.x0))
    return words


def words_on_line(line: Line, words: list[Word], y_tolerance: float = 2.0) -> list[Word]:
    """指定した行のY範囲に収まる単語を、X座標順で返す。"""
    matched = [
        w
        for w in words
        if w.page == line.page
        and w.y0 >= line.y0 - y_tolerance
        and w.y1 <= line.y1 + y_tolerance
    ]
    matched.sort(key=lambda w: w.x0)
    return matched
