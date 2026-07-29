import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PAGE_WIDTH, PAGE_HEIGHT = 595, 842
LINE_HEIGHT = 16


@pytest.fixture
def build_pdf(tmp_path):
    """各要素 (text, bold) のリストのリスト(=ページ単位)からPDFを生成する。

    例: build_pdf([[("Hello Ochi San.", False), ("Work Plan", True)], [...]])
    戻り値は生成したPDFファイルのPathとfitz.Documentのタプル。
    """

    def _build(pages: list[list[tuple[str, bool]]]) -> tuple[Path, fitz.Document]:
        doc = fitz.open()
        for page_lines in pages:
            page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            y = 50
            for text, bold in page_lines:
                if text.isascii():
                    fontname = "hebo" if bold else "helv"
                else:
                    fontname = "japan"  # 組み込みCJKフォント（OneNote日時等の合成用）
                page.insert_text((50, y), text, fontname=fontname, fontsize=11)
                y += LINE_HEIGHT
        pdf_path = tmp_path / "synthetic.pdf"
        doc.save(pdf_path)
        return pdf_path, doc

    return _build
