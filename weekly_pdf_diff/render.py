"""青太字の描画（IMPLEMENTATION_PLAN.md 6章）。

変更対象の単語だけを、背景色をサンプリングしてからredaction（正式な文字除去）で
消去し、同じ位置へ濃い青・太字で再描画する。

【redactionとリンク注釈について】
PyMuPDFの `apply_redactions()` は、redaction矩形と重なるリンク注釈も一緒に
削除してしまう（矩形の外にあるリンクは影響を受けない）。既存のハイパーリンクを
維持する要件（IMPLEMENTATION_PLAN.md 6.5節）があるため、redaction前に重なる
リンクを退避し、redaction後に同じ内容で再挿入している。
"""
import fitz

from models import DiffResult
from pdf_reader import Word

BLUE = (0x00 / 255, 0x33 / 255, 0xA0 / 255)  # #0033A0（既存リンク色#0066CCとの混同を避けるため引継ぎ資料案より濃くした）
ERASE_INSET = 0.4  # 消去矩形を文字領域よりわずかに内側に取り、罫線を壊さないようにする
MAX_FONT_SHRINK_RATIO = 0.10  # フォントサイズは最大10%まで縮小
WORD_GAP_MARGIN = 1.0  # 次の単語との間に残す最低限の隙間（pt）
BOLD_FONT = "hebo"  # Helvetica-Bold（PDF標準フォント。実データはArial系で専用Boldの埋め込みがないため代替）
BASELINE_OFFSET_RATIO = 0.2  # 単語bboxの下端からベースラインまでの簡易オフセット


def _page_fill_rects(page: fitz.Page) -> list[tuple[fitz.Rect, tuple]]:
    rects = []
    for drawing in page.get_drawings():
        fill = drawing.get("fill")
        if fill is None:
            continue
        rects.append((drawing["rect"], fill))
    return rects


def _background_color(fill_rects: list[tuple[fitz.Rect, tuple]], word_rect: fitz.Rect) -> tuple:
    center = fitz.Point((word_rect.x0 + word_rect.x1) / 2, (word_rect.y0 + word_rect.y1) / 2)
    for rect, fill in fill_rects:
        if rect.contains(center):
            return fill
    return (1, 1, 1)  # 白


def _draw_bold_text(page: fitz.Page, word_rect: fitz.Rect, text: str, font_size: float) -> None:
    size = font_size
    text_width = fitz.get_text_length(text, fontname=BOLD_FONT, fontsize=size)
    # 単語幅ぴったりまで使うと、実データにあるような狭い単語間隔（2〜3pt程度）が
    # 太字化で完全に消え、隣の単語と接触して見える不具合を実機確認で発見した。
    # 次の単語との間に最低限の隙間(WORD_GAP_MARGIN)を残すよう縮小目標を下げる。
    available = word_rect.width - WORD_GAP_MARGIN
    if available > 0 and text_width > available:
        shrunk = size * (available / text_width)
        size = max(shrunk, size * (1 - MAX_FONT_SHRINK_RATIO))

    baseline_y = word_rect.y1 - size * BASELINE_OFFSET_RATIO
    page.insert_text((word_rect.x0, baseline_y), text, fontname=BOLD_FONT, fontsize=size, color=BLUE)


def _collect_target_words(diff_results: list[DiffResult]) -> dict[int, list[tuple[Word, float]]]:
    words_by_page: dict[int, list[tuple[Word, float]]] = {}
    for result in diff_results:
        if result.change_type not in ("added", "modified"):
            continue
        curr = result.curr_unit
        if curr is None:
            continue
        target_words = curr.words if result.whole_unit else result.changed_words
        for word in target_words:
            words_by_page.setdefault(word.page, []).append((word, curr.font_size))
    return words_by_page


def _render_page(page: fitz.Page, entries: list[tuple[Word, float]]) -> None:
    fill_rects = _page_fill_rects(page)
    links_before = page.get_links()

    redact_specs: list[tuple[Word, float, fitz.Rect]] = []
    erase_rects: list[fitz.Rect] = []
    for word, font_size in entries:
        word_rect = fitz.Rect(word.x0, word.y0, word.x1, word.y1)
        bg = _background_color(fill_rects, word_rect)
        erase_rect = fitz.Rect(
            word_rect.x0 + ERASE_INSET,
            word_rect.y0 + ERASE_INSET,
            word_rect.x1 - ERASE_INSET,
            word_rect.y1 - ERASE_INSET,
        )
        page.add_redact_annot(erase_rect, fill=bg)
        erase_rects.append(erase_rect)
        redact_specs.append((word, font_size, word_rect))

    affected_links = [
        link for link in links_before if any(rect.intersects(link["from"]) for rect in erase_rects)
    ]

    page.apply_redactions()

    for link in affected_links:
        clean_link = {k: v for k, v in link.items() if k not in ("xref", "id")}
        page.insert_link(clean_link)

    for word, font_size, word_rect in redact_specs:
        _draw_bold_text(page, word_rect, word.text, font_size)


def render_diff(doc: fitz.Document, diff_results: list[DiffResult]) -> None:
    """今週側PDF(doc)に対して、追加・修正と判定された単語を青太字で描画する。

    change_type が unchanged / moved / deleted のものは描画しない
    （deletedは差分レポートにのみ記録する。IMPLEMENTATION_PLAN.md 4.4節）。
    """
    words_by_page = _collect_target_words(diff_results)
    for page_no, entries in words_by_page.items():
        _render_page(doc[page_no], entries)
