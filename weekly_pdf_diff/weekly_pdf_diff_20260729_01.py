"""weekly_pdf_diff CLIエントリポイント。

現状（S01時点）はPhase 1（PDF読み込み・Weekly境界検出・日付解決）のみ実装済み。
差分抽出・青太字描画・レポート出力（Phase 2〜5、IMPLEMENTATION_PLAN.md参照）は
未実装のため、Weekly区切りの解析とJSON出力のみを行う。
"""
import argparse
import json
import sys
from pathlib import Path

import fitz

from pdf_reader import extract_lines
from weekly_splitter import find_boundaries, resolve_missing_dates

DEFAULT_EXPECTED_COUNT = 16  # 基準日(2026-04-17)より前の1件を含む実データ全体のブロック数


def analyze(pdf_path: Path, output_dir: Path, expected_count: int) -> int:
    doc = fitz.open(pdf_path)
    lines = extract_lines(doc)
    boundaries = find_boundaries(lines)
    resolve_missing_dates(lines, boundaries)

    print(f"検出件数: {len(boundaries)}件")
    for b in boundaries:
        print(f"  {b.report_date}  page={b.start_page + 1}  y={round(b.start_y, 1)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / f"{pdf_path.stem}_weekly_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "date": b.report_date.isoformat() if b.report_date else None,
                    "start_page": b.start_page + 1,  # 1始まり（人が読む用）
                    "start_y": round(b.start_y, 1),
                }
                for b in boundaries
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Weekly一覧を書き出しました: {index_path}")

    if len(boundaries) != expected_count:
        print(
            f"警告: 検出件数({len(boundaries)})が期待値({expected_count})と一致しません。"
            " PDF構造を確認してください。",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weekly Report PDFのWeekly区切り・日付を解析する（Phase 1のみ実装済み）"
    )
    parser.add_argument("pdf", type=Path, help="解析対象のPDFファイル")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--expected-count", type=int, default=DEFAULT_EXPECTED_COUNT)
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"エラー: PDFが見つかりません: {args.pdf}", file=sys.stderr)
        return 1

    return analyze(args.pdf, args.output_dir, args.expected_count)


if __name__ == "__main__":
    raise SystemExit(main())
