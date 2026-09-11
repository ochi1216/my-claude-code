# -*- coding: utf-8 -*-
"""前方一致検索・フォルダのみ検索・状態保存の不具合修正 — v20260904_01 追加分

越智さんからのフィードバック（"P01"で"P010024_Lorry"がヒットしない／
SharePointにフォルダのみを検索するチェックボックスが欲しい）への対応。

前方一致は当初「常に末尾へ*を付ける」案を検討したが、実機での実測により
短い語（"P01"等）では暴走・誤動作することが判明したため、既定オフ・
最小文字数ガード付きのオプトイン方式に変更した（DESIGN_NOTES参照）。

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_16_prefix_and_folder.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import json

ok, ng = 0, 0


def check(label, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


CFG = dict(dsm.DEFAULT_CFG)

# ── F1 _apply_prefix_wildcard（実機実測に基づく安全側の設計） ──
print("\n[F1] 前方一致の組み立て（_apply_prefix_wildcard）")
check("4文字以上の語には * を付ける",
      dsm._apply_prefix_wildcard("P010024", 4) == "P010024*",
      dsm._apply_prefix_wildcard("P010024", 4))
check("実機で暴走が確認された短い語（3文字）には * を付けない（既定4文字）",
      dsm._apply_prefix_wildcard("P01", 4) == "P01",
      dsm._apply_prefix_wildcard("P01", 4))
check("2文字の語にも付けない", dsm._apply_prefix_wildcard("P0", 4) == "P0")
check("最小文字数はconfigで変更できる",
      dsm._apply_prefix_wildcard("P01", 3) == "P01*",
      dsm._apply_prefix_wildcard("P01", 3))
check("複数語は長い語だけ個別に前方一致になる（短い語は無加工）",
      dsm._apply_prefix_wildcard("validation P01", 4) == "validation* P01",
      dsm._apply_prefix_wildcard("validation P01", 4))
check("引用符で囲まれた完全一致の指定は変更しない",
      dsm._apply_prefix_wildcard('"P01"', 4) == '"P01"',
      dsm._apply_prefix_wildcard('"P01"', 4))
check("既に*で終わる語は二重に付けない",
      dsm._apply_prefix_wildcard("validation*", 4) == "validation*",
      dsm._apply_prefix_wildcard("validation*", 4))
check("空文字は空文字のまま", dsm._apply_prefix_wildcard("", 4) == "")


# ── F2 SharePointProvider._keyword_expr との組み合わせ ────────
print("\n[F2] _keyword_expr（前方一致 × タイトル限定の組み合わせ）")
sp = dsm.SharePointProvider(CFG, DummyAuth())
check("既定（前方一致オフ）では従来どおり無加工",
      sp._keyword_expr("P01") == "P01", sp._keyword_expr("P01"))

sp.prefix_search = True
check("前方一致オンでも短い語には*を付けない（暴走対策）",
      sp._keyword_expr("P01") == "P01", sp._keyword_expr("P01"))
check("前方一致オンで十分長い語には*を付ける",
      sp._keyword_expr("P010024") == "P010024*", sp._keyword_expr("P010024"))

sp.prefix_search = True
sp.title_only = True
check("前方一致＋タイトル限定を組み合わせられる",
      sp._keyword_expr("P010024") == "title:P010024*",
      sp._keyword_expr("P010024"))
check("前方一致＋タイトル限定でも短い語は無加工（title:のみ付く）",
      sp._keyword_expr("P01") == "title:P01", sp._keyword_expr("P01"))

# config.jsonで最小文字数を変更できる
sp_custom = dsm.SharePointProvider(dict(CFG, prefix_search_min_length=3), DummyAuth())
sp_custom.prefix_search = True
check("prefix_search_min_lengthをconfigで変更できる",
      sp_custom._keyword_expr("P01") == "P01*", sp_custom._keyword_expr("P01"))

# NexusProviderはSharePointProviderを継承しているため、同じ仕組みが効く
nx = dsm.NexusProvider(CFG, DummyAuth())
nx.prefix_search = True
check("Nexusにも同じ前方一致の仕組みが効く（継承）",
      "P010024*" in nx._query_string("P010024"), nx._query_string("P010024"))

# EnoviaProviderは自前の_keyword_exprを持ち、prefix_searchを参照しない
# （構文が未確認のため、意図せず変な挙動を持ち込まないための設計）。
en = dsm.EnoviaProvider(CFG, None)
en.prefix_search = True
check("EnoviaProviderはprefix_searchの影響を受けない（自前の実装のため）",
      en._keyword_expr("P010024") == "P010024", en._keyword_expr("P010024"))


# ── F3 SearchManagerでprefix_searchが各プロバイダへ伝わる ─────
print("\n[F3] SearchManager.search() でのprefix_searchの伝播")
mgr = dsm.SearchManager(CFG, DummyAuth())
sent = {}


def stub_capture(key):
    def _search(kw, mx):
        provider = mgr.providers[key]
        sent[key] = provider.prefix_search
        return {"results": [], "total": 0, "note": ""}
    return _search


mgr.providers[dsm.TARGET_SHAREPOINT].search = stub_capture(dsm.TARGET_SHAREPOINT)
mgr.search("P010024", dsm.TARGET_SHAREPOINT, 10, prefix_search=True)
check("prefix_search=Trueがプロバイダまで伝わる", sent[dsm.TARGET_SHAREPOINT] is True)

mgr.search("P010024", dsm.TARGET_SHAREPOINT, 10, prefix_search=False)
check("prefix_search=Falseもプロバイダまで伝わる", sent[dsm.TARGET_SHAREPOINT] is False)

mgr.search("P010024", dsm.TARGET_SHAREPOINT, 10)
check("省略時はFalse（既定オフ）", sent[dsm.TARGET_SHAREPOINT] is False)


# ── F4 /api/search でprefix_searchを受け取る ──────────────────
print("\n[F4] /api/search エンドポイント")
dsm._cfg = CFG
dsm._manager = mgr
mgr.providers[dsm.TARGET_SHAREPOINT].search = stub_capture(dsm.TARGET_SHAREPOINT)
client = dsm.flask_app.test_client()

client.post("/api/search",
           json={"keyword": "P010024", "target": "sharepoint", "prefix_search": True})
check("APIのprefix_searchがプロバイダまで届く", sent[dsm.TARGET_SHAREPOINT] is True)

client.post("/api/search", json={"keyword": "P010024", "target": "sharepoint"})
check("APIでprefix_search省略時はconfigの既定値(false)が使われる",
      sent[dsm.TARGET_SHAREPOINT] is False)

cfg_default_on = dict(CFG, prefix_search_default=True)
dsm._cfg = cfg_default_on
client.post("/api/search", json={"keyword": "P010024", "target": "sharepoint"})
check("prefix_search_default=trueならAPIでも省略時にtrueになる",
      sent[dsm.TARGET_SHAREPOINT] is True)
dsm._cfg = CFG


# ── F5 状態の保存・復元（title_onlyが保存されていなかった不具合の修正） ──
print("\n[F5] /api/state の保存・復元")
dsm.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
resp = client.post("/api/state", json={
    "keyword": "P010024", "target": "sharepoint", "max_results": 25,
    "title_only": False, "prefix_search": True, "folder_only": True,
    "sort": {}, "filters": {},
})
check("状態の保存が成功する", resp.get_json().get("saved") is True)

restored = client.get("/api/state").get_json()
check("★不具合修正★ title_only が保存・復元される"
      "（既存コードでは保存対象から漏れており、画面は復元したつもりでも"
      "毎回既定値に戻っていた。今回prefix_search/folder_onlyの追加と"
      "あわせて修正した）",
      restored.get("title_only") is False, restored)
check("prefix_search が保存・復元される", restored.get("prefix_search") is True, restored)
check("folder_only が保存・復元される", restored.get("folder_only") is True, restored)


# ── F6 画面表示 ──────────────────────────────────────────────
print("\n[F6] 画面表示")
html = dsm.flask_app.test_client().get("/").get_data(as_text=True)
check("前方一致チェックボックスがある", 'id="prefixSearch"' in html)
check("フォルダのみを検索するチェックボックスがある", 'id="folderOnly"' in html)
check("フォルダのみを検索する行は既定で隠れている（SharePointタブでのみ表示）",
      'id="folderOnlyRow" hidden' in html)
check("SharePointタブ選択時だけfolderOnlyRowを表示するロジックがある",
      'folderOnlyRow").hidden = (target !== "sharepoint")' in html)
check("フォルダのみを検索するチェックの効果（種別をフォルダに絞る）が実装されている",
      'filters.doc_type = { values: ["フォルダ"] }' in html)
check("チェックボックス変更時に即座に絞り込みへ反映するロジックがある",
      'folderOnly").addEventListener("change"' in html)


print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
