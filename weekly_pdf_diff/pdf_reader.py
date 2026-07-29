"""PyMuPDFの薄いラッパー。ページごとの行情報を抽出する。"""
from dataclasses import dataclass

import fitz


@dataclass
class Line:
    page: int  # 0-indexed
    y0: float
    y1: float
    text: str
    bold: bool


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
                y0, y1 = line["bbox"][1], line["bbox"][3]
                lines.append(Line(page=page_no, y0=y0, y1=y1, text=text, bold=bold))
    # get_text("dict")のブロック順は必ずしも視覚的な上→下順ではない
    # （実PDFで、日時スタンプが本文より先にY座標的には上にあるのに
    # ブロック順としては後に現れる例を確認済み）。ページ内はY座標で並べ替える。
    lines.sort(key=lambda line: (line.page, line.y0))
    return lines
