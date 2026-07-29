"""CLIエントリポイントのテスト。

エントリポイントのファイル名は開発ルールにより yyyymmdd_NN で増えていくため、
ハードコードせず、run_weekly_pdf_diff.bat と同じ規則（ファイル名で最新を選ぶ）で
動的に読み込む。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

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


def test_analyze_writes_index_next_to_pdf_by_default(build_pdf, monkeypatch):
    pdf_path, _ = build_pdf([[("Hello Ochi San.", False), ("Work Plan", True)]])
    monkeypatch.setattr(sys, "argv", ["prog", str(pdf_path), "--expected-count", "1"])

    exit_code = cli.main()

    assert exit_code == 0
    expected_index = pdf_path.parent / "output" / f"{pdf_path.stem}_weekly_index.json"
    assert expected_index.exists()


def test_missing_pdf_arg_falls_back_to_dialog(monkeypatch, tmp_path):
    picked = tmp_path / "picked.pdf"
    picked.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(cli, "pick_pdf_via_dialog", lambda: picked)
    monkeypatch.setattr(sys, "argv", ["prog"])

    called_with = {}

    def fake_analyze(pdf_path, output_dir, expected_count):
        called_with["pdf_path"] = pdf_path
        called_with["output_dir"] = output_dir
        return 0

    monkeypatch.setattr(cli, "analyze", fake_analyze)

    exit_code = cli.main()

    assert exit_code == 0
    assert called_with["pdf_path"] == picked
    assert called_with["output_dir"] == picked.parent / "output"


def test_dialog_cancelled_returns_error(monkeypatch):
    monkeypatch.setattr(cli, "pick_pdf_via_dialog", lambda: None)
    monkeypatch.setattr(sys, "argv", ["prog"])

    exit_code = cli.main()

    assert exit_code == 1
