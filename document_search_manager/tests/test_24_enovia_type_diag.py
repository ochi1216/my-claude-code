# -*- coding: utf-8 -*-
"""Enovia型診断（S04 Phase3-0）— v20260911_03 で追加

document_search_manager: S04（Enovia検索拡張。Document以外の型も検索・表示
できるようにする）の本実装前に、まず診断機能だけを検証する。
DESIGN_NOTES.md 3-3 のS04節にある未確認事項①（型ごとに返る属性）③（英語名と
日本語ラベルの対応）④（型ごとに列構成を変えるべきか）を実測で確かめるための
`EnoviaProvider.diagnose_types()` を検証する。ネットワークには一切アクセスせず、
`_call_search` をスタブ化して検証する（tests/test_15_enovia.py と同じ方式）。
実行: python tests/test_24_enovia_type_diag.py
（まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm  # noqa: E402

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


def make_page(items, nhits, next_start):
    return {"infos": {"nhits": nhits, "next_start": next_start}, "results": items}


# Document型（属性がすべて揃っている代表例。test_15のREAL_ITEM_REV3相当を簡略化）
DOC_ITEM = {
    "attributes": [
        {"format": "internal", "name": "resourceid", "value": "RID-DOC-1"},
        {"format": "ds6w_facet", "name": "ds6w:what/ds6w:type", "value": "Document"},
        {"format": "attribute", "name": "ds6w:identifier", "value": "DOC-000001"},
        {"format": "attribute", "name": "ds6w:label", "value": "サンプル文書"},
        {"format": "attribute", "name": "ds6w:description", "value": "説明文"},
        {"format": "attribute", "name": "ds6wg:revision", "value": "1"},
        {"format": "ds6w_facet", "name": "ds6w:what/ds6w:status",
         "value": "Document Release.RELEASED"},
        {"format": "ds6w_facet", "name": "ds6w:who/ds6w:responsible/ds6w:originator",
         "value": "山田太郎"},
        {"format": "ds6w_facet", "name": "ds6w:who/ds6w:responsible", "value": "鈴木花子"},
        {"format": "ds6w_facet", "name": "ds6w:who/ds6w:lastModifiedBy", "value": "鈴木花子"},
        {"format": "ds6w_facet", "name": "ds6w:when/ds6w:modified",
         "value": "2026-09-01T00:00:00Z"},
        {"format": "ds6w_facet", "name": "ds6w:when/ds6w:created",
         "value": "2026-08-01T00:00:00Z"},
        {"format": "ds6w_facet", "name": "ds6w:where/ds6w:context/ds6w:folder",
         "value": "Release and Production"},
        {"format": "ds6w_facet", "name": "ds6w:what/ds6w:docExtension", "value": "pdf"},
    ]
}

# Project Space型（越智さんの回答で「よく使う型」に選ばれた型。属性が一部しか
# 無いことを想定した、意図的に不完全なサンプル。未確認事項①の検証用）。
PROJECT_SPACE_ITEM_1 = {
    "attributes": [
        {"format": "internal", "name": "resourceid", "value": "RID-PS-1"},
        {"format": "ds6w_facet", "name": "ds6w:what/ds6w:type", "value": "Project Space"},
        {"format": "attribute", "name": "ds6w:identifier", "value": "PS-000001"},
        {"format": "attribute", "name": "ds6w:label", "value": "サンプルプロジェクト"},
        # revision / status / description 等はProject Spaceには存在しない想定
        # （実機未確認のため、テストでは「値が無い」パターンとして表現する）。
    ]
}
PROJECT_SPACE_ITEM_2 = {
    "attributes": [
        {"format": "internal", "name": "resourceid", "value": "RID-PS-2"},
        {"format": "ds6w_facet", "name": "ds6w:what/ds6w:type", "value": "Project Space"},
        {"format": "attribute", "name": "ds6w:identifier", "value": "PS-000002"},
        {"format": "attribute", "name": "ds6w:label", "value": "サンプルプロジェクト2"},
    ]
}

# ECO型（1件のみ・resourceidを持たない想定。URLが生成できないケースの検証用）。
ECO_ITEM_NO_RESOURCEID = {
    "attributes": [
        {"format": "ds6w_facet", "name": "ds6w:what/ds6w:type", "value": "ECO"},
        {"format": "attribute", "name": "ds6w:identifier", "value": "ECO-000001"},
    ]
}


# ── T1 型ごとの件数・属性充足率・URL（正常系） ─────────────────
print("\n[T1] 型ごとの集計（件数・充足率・URL・生属性ダンプ）")

ep = dsm.EnoviaProvider(dict(CFG, enovia_page_size=10), None)
ep._build_session = lambda: object()
ep._call_search = lambda session, body: (
    200,
    make_page([DOC_ITEM, PROJECT_SPACE_ITEM_1, PROJECT_SPACE_ITEM_2,
               ECO_ITEM_NO_RESOURCEID], 4, None),
    "")

result = ep.diagnose_types("Application")
check("ok=True で返る", result.get("ok") is True, result)
check("keywordをそのまま保持する", result.get("keyword") == "Application")
check("nhitsはinfos.nhitsをそのまま転記する（サンプルの件数とは別物）",
      result.get("nhits") == 4, result.get("nhits"))
check("fetched_rawは実際に取得した件数（4件）", result.get("fetched_raw") == 4,
      result.get("fetched_raw"))
check("1ページで完結すればtruncated=False", result.get("truncated") is False)

rows = {r["type"]: r for r in result.get("rows") or []}
check("3種類の型に分類される（Document / Project Space / ECO）",
      set(rows.keys()) == {"Document", "Project Space", "ECO"}, set(rows.keys()))
check("Project Spaceは2件と集計される", rows["Project Space"]["count"] == 2,
      rows["Project Space"]["count"])
check("件数の多い順（Project Space=2が先頭）に並ぶ",
      [r["type"] for r in result["rows"]][0] == "Project Space",
      [r["type"] for r in result["rows"]])

doc_required = {r["label"]: r for r in rows["Document"]["required"]}
check("Documentは主要属性がすべて1/1で充足する",
      all(v["present"] == v["total"] == 1 for v in doc_required.values()),
      doc_required)

ps_required = {r["label"]: r for r in rows["Project Space"]["required"]}
check("Project SpaceはTitleが2/2で充足する（実際に返っている属性）",
      ps_required["Title"]["present"] == 2 and ps_required["Title"]["total"] == 2,
      ps_required["Title"])
check("Project SpaceはRevisionが0/2（未確認事項①：値を持たない属性がある）",
      ps_required["Revision"]["present"] == 0 and ps_required["Revision"]["total"] == 2,
      ps_required["Revision"])

check("Documentは emxNavigator.jsp のURLを1本生成する",
      "RID-DOC-1" in rows["Document"]["example_url"]
      and "emxNavigator.jsp" in rows["Document"]["example_url"],
      rows["Document"]["example_url"])
check("resourceidが無いECOはURLを生成しない（推測でURLを作らない）",
      rows["ECO"]["example_url"] == "", rows["ECO"]["example_url"])

check("Documentの代表1件の生属性をそのまま保持する（推測で選ばない）",
      any(a.get("name") == "ds6w:description" and a.get("value") == "説明文"
          for a in rows["Document"]["sample_attrs"]),
      rows["Document"]["sample_attrs"])


# ── T2 ページング（複数ページにまたがっても型別に集計する） ──────
print("\n[T2] 複数ページにまたがる集計")

page_calls = []


def stub_two_pages(session, body):
    page_calls.append(dict(body))
    if "next_start" not in body:
        return 200, make_page([DOC_ITEM], 5, "TOKEN2"), ""
    return 200, make_page([PROJECT_SPACE_ITEM_1], 5, None), ""


ep_pages = dsm.EnoviaProvider(dict(CFG, enovia_page_size=1), None)
ep_pages._build_session = lambda: object()
ep_pages._call_search = stub_two_pages
result_pages = ep_pages.diagnose_types("Application")
check("2ページとも取得する", len(page_calls) == 2, len(page_calls))
check("2ページ分の型が両方集計される",
      {r["type"] for r in result_pages["rows"]} == {"Document", "Project Space"},
      {r["type"] for r in result_pages["rows"]})
check("fetched_rawは2件（両ページの合計）", result_pages["fetched_raw"] == 2,
      result_pages["fetched_raw"])


# ── T3 ページ上限での打ち切り（際限なく叩き続けない） ─────────────
print("\n[T3] ページ上限での打ち切り")

capped_calls = {"n": 0}


def stub_never_ending(session, body):
    capped_calls["n"] += 1
    return 200, make_page([DOC_ITEM], 999, f"TOK{capped_calls['n']}"), ""


ep_capped = dsm.EnoviaProvider(dict(CFG, enovia_page_size=1), None)
ep_capped._build_session = lambda: object()
ep_capped._call_search = stub_never_ending
result_capped = ep_capped.diagnose_types("Application", max_pages=3)
check("max_pagesで打ち切る（既定は5だが引数で上書きできる）", capped_calls["n"] == 3,
      capped_calls["n"])
check("truncated=Trueになる（次のページがまだあるのに打ち切ったため）",
      result_capped["truncated"] is True)


# ── T4 異常系 ───────────────────────────────────────────────
print("\n[T4] 異常系")

check("キーワードが空なら ok=False で即返す（通信しない）",
      dsm.EnoviaProvider(CFG, None).diagnose_types("").get("ok") is False)

ep_fail = dsm.EnoviaProvider(CFG, None)
ep_fail._build_session = lambda: object()
ep_fail._call_search = lambda session, body: (401, None, "Unauthorized")
result_fail = ep_fail.diagnose_types("Application")
check("1ページ目から失敗すればok=Falseで、行は空",
      result_fail.get("ok") is False and result_fail.get("rows") == [],
      result_fail)
check("失敗の理由をmessageに残す（断定せず事実を明示）",
      "401" in result_fail.get("message", ""), result_fail.get("message"))


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(1 if ng else 0)
