"""weekly_pdf_diff CLIエントリポイント。

Phase 1〜5をすべて統合した現行版。基準日（既定2026-04-17）以降の各Weeklyを
直前の日付のWeeklyと比較し、追加・修正された文言を青太字にした別名PDFと、
差分レポート（CSV/HTML）、Weekly一覧JSONを出力する。

PDFファイルをコマンドライン引数で渡さなかった場合は、tkinter標準ライブラリの
ファイル選択ダイアログ（Windowsのエクスプローラー風の「開く」画面）を表示する。
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import fitz

from diff_engine import pair_units
from pdf_reader import Line, extract_lines, extract_words
from report import build_rows, write_csv, write_html
from render import render_diff
from sectionize import build_units
from weekly_splitter import WeeklyBoundary, find_boundaries, resolve_missing_dates

DEFAULT_EXPECTED_COUNT = 16  # 基準日より前の1件を含む実データ全体のブロック数
DEFAULT_BASELINE = date(2026, 4, 17)


def pick_pdf_via_dialog() -> Path | None:
    """ファイル選択ダイアログでPDFを選ばせる。キャンセル時はNoneを返す。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print(
            "エラー: GUIファイル選択に必要なtkinterが見つかりません。"
            " PDFファイルをバッチファイルへドラッグ&ドロップするか、"
            " コマンドライン引数としてPDFパスを渡してください。",
            file=sys.stderr,
        )
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askopenfilename(
        title="解析するWeekly Report PDFを選択してください",
        filetypes=[("PDFファイル", "*.pdf"), ("すべてのファイル", "*.*")],
    )
    root.destroy()
    return Path(selected) if selected else None


def _weekly_line_range(
    sorted_boundaries: list[WeeklyBoundary], index: int
) -> tuple[int, float, int | None, float | None]:
    """sorted_boundariesは日付昇順(古い→新しい)。PDF自体は新しいWeeklyから順に
    綴じられている（ページ番号が大きいほど古い週になる）ため、あるWeeklyの終端は
    日付が1つ「新しい」方(index+1)ではなく、1つ「古い」方(index-1、ページ番号は
    より大きい)になる。index+1を使う実装は範囲が逆転し、行のスライスが常に空に
    なる不具合の原因だった（実PDF検証で発見・修正）。"""
    b = sorted_boundaries[index]
    if index > 0:
        older = sorted_boundaries[index - 1]
        return b.start_page, b.start_y, older.start_page, older.start_y
    return b.start_page, b.start_y, None, None


def _slice_lines(
    lines: list[Line],
    start_page: int,
    start_y: float,
    end_page: int | None,
    end_y: float | None,
) -> list[Line]:
    def after_start(l: Line) -> bool:
        return l.page > start_page or (l.page == start_page and l.y0 >= start_y)

    def before_end(l: Line) -> bool:
        if end_page is None:
            return True
        return l.page < end_page or (l.page == end_page and l.y0 < end_y)

    return [l for l in lines if after_start(l) and before_end(l)]


def run(pdf_path: Path, output_dir: Path, expected_count: int, baseline: date) -> int:
    doc = fitz.open(pdf_path)
    lines = extract_lines(doc)
    words = extract_words(doc)
    boundaries = find_boundaries(lines)
    resolve_missing_dates(lines, boundaries)

    print(f"検出件数: {len(boundaries)}件")
    for b in boundaries:
        print(f"  {b.report_date}  page={b.start_page + 1}  y={round(b.start_y, 1)}")
    if len(boundaries) != expected_count:
        print(
            f"警告: 検出件数({len(boundaries)})が期待値({expected_count})と一致しません。"
            " PDF構造を確認してください。",
            file=sys.stderr,
        )

    dated = [b for b in boundaries if b.report_date is not None]
    undated_count = len(boundaries) - len(dated)
    if undated_count:
        print(f"警告: 日付を特定できなかったWeeklyが{undated_count}件あります（処理対象から除外）", file=sys.stderr)

    sorted_boundaries = sorted(dated, key=lambda b: b.report_date)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    index_path = output_dir / f"{stem}_weekly_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "date": b.report_date.isoformat(),
                    "start_page": b.start_page + 1,
                    "start_y": round(b.start_y, 1),
                }
                for b in sorted_boundaries
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Weekly一覧を書き出しました: {index_path}")

    baseline_index = next(
        (i for i, b in enumerate(sorted_boundaries) if b.report_date == baseline), None
    )
    if baseline_index is None:
        print(
            f"エラー: 基準日{baseline.isoformat()}のWeeklyが見つかりません。"
            " --baseline を確認してください。",
            file=sys.stderr,
        )
        return 1

    all_rows = []
    processed_pairs = 0
    for i in range(baseline_index + 1, len(sorted_boundaries)):
        prev_b = sorted_boundaries[i - 1]
        curr_b = sorted_boundaries[i]
        prev_lines = _slice_lines(lines, *_weekly_line_range(sorted_boundaries, i - 1))
        curr_lines = _slice_lines(lines, *_weekly_line_range(sorted_boundaries, i))

        prev_units = build_units(prev_lines, words)
        curr_units = build_units(curr_lines, words)
        diff_results = pair_units(prev_units, curr_units)

        render_diff(doc, diff_results)
        all_rows.extend(build_rows(curr_b.report_date, prev_b.report_date, diff_results))
        processed_pairs += 1
        print(f"比較完了: {prev_b.report_date} -> {curr_b.report_date}")

    print(f"比較したWeeklyペア数: {processed_pairs}")

    pdf_out_path = output_dir / f"{stem}_diff_blue_bold.pdf"
    doc.save(pdf_out_path)
    print(f"差分PDFを書き出しました: {pdf_out_path}")

    csv_path = output_dir / f"{stem}_diff_report.csv"
    html_path = output_dir / f"{stem}_diff_report.html"
    write_csv(all_rows, csv_path)
    write_html(all_rows, html_path)
    print(f"差分レポートを書き出しました: {csv_path} / {html_path}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weekly Report PDFの前週差分を青太字化する（S01時点の完全パイプライン）"
    )
    parser.add_argument(
        "pdf",
        type=Path,
        nargs="?",
        default=None,
        help="解析対象のPDFファイル（省略時はファイル選択画面を表示）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="出力先フォルダ（省略時はPDFと同じフォルダの output/）",
    )
    parser.add_argument("--expected-count", type=int, default=DEFAULT_EXPECTED_COUNT)
    parser.add_argument(
        "--baseline",
        type=date.fromisoformat,
        default=DEFAULT_BASELINE,
        help="基準日 YYYY-MM-DD（この日付のWeeklyは変更されない。既定: 2026-04-17）",
    )
    args = parser.parse_args()

    pdf_path = args.pdf
    if pdf_path is None:
        pdf_path = pick_pdf_via_dialog()
        if pdf_path is None:
            print("PDFが選択されなかったため処理を中止しました。", file=sys.stderr)
            return 1

    if not pdf_path.exists():
        print(f"エラー: PDFが見つかりません: {pdf_path}", file=sys.stderr)
        return 1

    output_dir = args.output_dir if args.output_dir is not None else pdf_path.parent / "output"
    return run(pdf_path, output_dir, args.expected_count, args.baseline)


if __name__ == "__main__":
    raise SystemExit(main())
