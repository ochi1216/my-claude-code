"""CLIエントリポイントのテスト（main()の引数解決・GUIフォールバック部分）。

エントリポイントのファイル名は開発ルールにより yyyymmdd_NN で増えていくため、
ハードコードせず、run_weekly_pdf_diff.bat と同じ規則（ファイル名で最新を選ぶ）で
動的に読み込む。ただし、パイプラインの実処理（run()の中身）は
test_end_to_end.py で別途検証しており、ここでは main() の引数解決・
GUIフォールバックのみを対象にする。run() の関数シグネチャ自体が変わった場合は
このファイルの更新が必要になる。
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _load_latest_cli_module():
    candidates = sorted(PROJECT_DIR.glob("weekly_pdf_diff_????????_??.py"))
    assert candidates, "weekly_pdf_diff_yyyymmdd_NN.py が見つかりません"
    latest = candidates[-1]
    spec = importlib.util.spec_from_file_location(latest.stem, latest)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_latest_cli_module()


def test_missing_pdf_arg_falls_back_to_dialog(monkeypatch, tmp_path):
    picked = tmp_path / "picked.pdf"
    picked.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(cli, "pick_pdf_via_dialog", lambda: picked)
    monkeypatch.setattr(sys, "argv", ["prog"])

    called_with = {}

    def fake_run(pdf_path, output_dir, expected_count, baseline):
        called_with["pdf_path"] = pdf_path
        called_with["output_dir"] = output_dir
        called_with["baseline"] = baseline
        return 0

    monkeypatch.setattr(cli, "run", fake_run)

    exit_code = cli.main()

    assert exit_code == 0
    assert called_with["pdf_path"] == picked
    assert called_with["output_dir"] == picked.parent / "output"
    assert called_with["baseline"] == cli.DEFAULT_BASELINE


def test_dialog_cancelled_returns_error(monkeypatch):
    monkeypatch.setattr(cli, "pick_pdf_via_dialog", lambda: None)
    monkeypatch.setattr(sys, "argv", ["prog"])

    exit_code = cli.main()

    assert exit_code == 1


def test_explicit_pdf_arg_skips_dialog_and_uses_default_output_dir(monkeypatch, tmp_path):
    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(sys, "argv", ["prog", str(pdf_path)])

    def fail_if_called():
        raise AssertionError("PDFが指定されているのにダイアログが呼ばれた")

    monkeypatch.setattr(cli, "pick_pdf_via_dialog", fail_if_called)

    called_with = {}

    def fake_run(pdf_path, output_dir, expected_count, baseline):
        called_with["pdf_path"] = pdf_path
        called_with["output_dir"] = output_dir
        return 0

    monkeypatch.setattr(cli, "run", fake_run)

    exit_code = cli.main()

    assert exit_code == 0
    assert called_with["pdf_path"] == pdf_path
    assert called_with["output_dir"] == pdf_path.parent / "output"


def test_baseline_arg_is_parsed_as_date(monkeypatch, tmp_path):
    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        sys, "argv", ["prog", str(pdf_path), "--baseline", "2026-05-01"]
    )

    called_with = {}

    def fake_run(pdf_path, output_dir, expected_count, baseline):
        called_with["baseline"] = baseline
        return 0

    monkeypatch.setattr(cli, "run", fake_run)

    exit_code = cli.main()

    assert exit_code == 0
    assert called_with["baseline"] == date(2026, 5, 1)
