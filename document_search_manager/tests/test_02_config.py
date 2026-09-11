# -*- coding: utf-8 -*-
"""設定の読み込みと認証情報の流用

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_02_config.py   （まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import json
import tempfile

ok, ng = 0, 0
def check(label, cond, detail=""):
    global ok, ng
    if cond: ok += 1; print(f"  OK   {label}")
    else:    ng += 1; print(f"  NG   {label}  {detail}")

tmp = Path(tempfile.mkdtemp())

def setup(own_cfg, sources):
    """own_cfg: 本ツールのconfig.json内容 / sources: {フォルダ名: 中身 or None}"""
    base = tmp / f"case{len(list(tmp.iterdir()))}"
    tool = base / "document_search_manager"; tool.mkdir(parents=True)
    if own_cfg is not None:
        (tool / "config.json").write_text(json.dumps(own_cfg), encoding="utf-8")
    for folder, content in sources.items():
        d = base / folder; d.mkdir(parents=True, exist_ok=True)
        if content is not None:
            (d / "config.json").write_text(json.dumps(content), encoding="utf-8")
    dsm.CONFIG_PATH = tool / "config.json"
    dsm.CONFIG_EXAMPLE = tool / "config.example.json"
    dsm.CREDENTIAL_SOURCES = [base / "po_database_organizer" / "config.json",
                              base / "onenote_report_generator" / "config.json"]
    return base

EXAMPLE = {"tenant_id": "", "client_id": "", "flask_port": 5020}

print("\n[C1] 越智さんの環境の再現（po も onenote も config.json 無し）")
setup(EXAMPLE, {"po_database_organizer": None, "onenote_report_generator": None})
try:
    dsm._load_config(); check("設定なしなら終了する", False, "終了しなかった")
except SystemExit:
    check("設定なしなら分かりやすく終了する", True)

print("\n[C2] po_database_organizer から借用（小文字キー）")
setup(EXAMPLE, {"po_database_organizer": {"tenant_id": "T-PO", "client_id": "C-PO"},
                "onenote_report_generator": None})
cfg = dsm._load_config()
check("poから借用", cfg["tenant_id"] == "T-PO" and cfg["client_id"] == "C-PO",
      f'{cfg["tenant_id"]}/{cfg["client_id"]}')

print("\n[C3] onenote_report_generator から借用（大文字キー）")
setup(EXAMPLE, {"po_database_organizer": None,
                "onenote_report_generator": {"TENANT_ID": "T-ON", "CLIENT_ID": "C-ON",
                                             "GEMINI_API_KEY": "secret"}})
cfg = dsm._load_config()
check("onenoteの大文字キーを認識", cfg["tenant_id"] == "T-ON" and cfg["client_id"] == "C-ON",
      f'{cfg["tenant_id"]}/{cfg["client_id"]}')
check("無関係なキーは取り込まない", "GEMINI_API_KEY" not in cfg and "gemini_api_key" not in cfg)

print("\n[C4] プレースホルダ <YOUR_...> は未設定として扱う")
setup(EXAMPLE, {"po_database_organizer": {"tenant_id": "<YOUR_TENANT_ID>",
                                          "client_id": "<YOUR_CLIENT_ID>"},
                "onenote_report_generator": {"TENANT_ID": "T-ON", "CLIENT_ID": "C-ON"}})
cfg = dsm._load_config()
check("プレースホルダを飛ばして次の候補を使う",
      cfg["tenant_id"] == "T-ON" and cfg["client_id"] == "C-ON",
      f'{cfg["tenant_id"]}/{cfg["client_id"]}')

print("\n[C5] config.json への直接記入が最優先")
setup({"tenant_id": "T-OWN", "client_id": "C-OWN"},
      {"po_database_organizer": {"tenant_id": "T-PO", "client_id": "C-PO"}})
cfg = dsm._load_config()
check("自前の値を優先", cfg["tenant_id"] == "T-OWN" and cfg["client_id"] == "C-OWN")

print("\n[C6] credentials_from で任意パスを指定")
base = setup(EXAMPLE, {"po_database_organizer": None, "onenote_report_generator": None})
other = base / "elsewhere"; other.mkdir()
(other / "config.json").write_text(json.dumps({"tenant_id": "T-ELSE", "client_id": "C-ELSE"}),
                                   encoding="utf-8")
(base / "document_search_manager" / "config.json").write_text(
    json.dumps({"tenant_id": "", "client_id": "",
                "credentials_from": str(other / "config.json")}), encoding="utf-8")
cfg = dsm._load_config()
check("credentials_from を最優先で参照",
      cfg["tenant_id"] == "T-ELSE" and cfg["client_id"] == "C-ELSE",
      f'{cfg["tenant_id"]}/{cfg["client_id"]}')

print("\n[C7] 壊れたJSONの流用元があっても止まらない")
base = setup(EXAMPLE, {"onenote_report_generator": {"TENANT_ID": "T-ON", "CLIENT_ID": "C-ON"}})
(base / "po_database_organizer").mkdir(parents=True, exist_ok=True)
(base / "po_database_organizer" / "config.json").write_text("{壊れたJSON", encoding="utf-8")
cfg = dsm._load_config()
check("壊れた候補を飛ばして次を使う", cfg["tenant_id"] == "T-ON", cfg["tenant_id"])

print("\n[C8] 片方だけ揃っている場合の合成")
setup(EXAMPLE, {"po_database_organizer": {"tenant_id": "T-PO"},
                "onenote_report_generator": {"CLIENT_ID": "C-ON"}})
cfg = dsm._load_config()
check("2つの候補から1つずつ拾って合成",
      cfg["tenant_id"] == "T-PO" and cfg["client_id"] == "C-ON",
      f'{cfg["tenant_id"]}/{cfg["client_id"]}')

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
