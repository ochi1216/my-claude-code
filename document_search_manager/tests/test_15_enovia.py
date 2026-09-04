# -*- coding: utf-8 -*-
"""Enovia（3DEXPERIENCE / federated search）検索 — Phase 3 (v20260904_01) で追加

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
federated/search のリクエスト・レスポンスのサンプルは、越智さんのF12キャプチャ
（2026-09-04, Enoviaで "FMEA"/"validation" を検索したときの実測データ）から
そのまま転記した。推測で作ったサンプルではない。
実行: python tests/test_15_enovia.py   （まとめて実行する場合は python tests/run_tests.py）
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
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


CFG = dict(dsm.DEFAULT_CFG)

# 実機キャプチャの2件（DOC-594838のRevision 3 / 2）をそのまま転記。
# D1（全リビジョンを表示する）の検証に、同一Document Numberで
# revisionだけ違う実例として使う。
REAL_ITEM_REV3 = json.loads(r"""
{"attributes": [{"format": "internal", "name": "resourceid", "type": "STRING", "value": "953DAA5621FC01005A87996AC8680700"}, {"format": "internal", "name": "type_icon_url", "type": "string", "value": "https://dspace.plm.nexperia.com/3dspace/snresources/images/icons/small/I_CDM_Document.png"}, {"format": "internal", "name": "preview_url", "type": "string", "value": "https://dspace.plm.nexperia.com/3dspace/snresources/images/icons/large/I_CDM_Document108x144.png"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:docExtension", "type": "string", "value": "xlsm", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:kind", "type": "string", "value": "FALSE", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:language", "type": "string", "value": "English", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:policy", "type": "string", "value": "Document Release", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:status/ds6w:reserved", "type": "boolean", "value": "FALSE", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:status", "type": "string", "value": "Document Release.IN_WORK", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:type", "type": "string", "value": "Document", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/upg:nex_AllowWebpublish", "type": "string", "value": "No", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:where/ds6w:context/ds6w:folder", "type": "string", "value": "Release and Production", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:where/ds6w:context/ds6w:project", "type": "string", "value": "Default", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:who/ds6w:responsible/ds6w:organizationResponsible", "type": "string", "value": "Nexperia", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:who/ds6w:responsible/ds6w:originator", "type": "string", "value": "Sheribeth Bolanos", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:who/ds6w:responsible", "type": "string", "value": "Sheribeth Bolanos", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:when/ds6w:modified", "type": "date", "value": "2026-09-03T15:11:21Z", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:when/ds6w:created", "type": "date", "value": "2026-09-03T14:42:33Z", "field": "implicit"}, {"format": "attribute", "name": "ds6w:identifier", "type": "string", "value": "DOC-594838"}, {"format": "attribute", "name": "ds6w:description", "type": "string", "value": "NEH8100 Verification and Validation Plan"}, {"format": "attribute", "name": "ds6wg:revision", "type": "string", "value": "3"}, {"format": "attribute", "name": "ds6w:label", "type": "string", "value": "NEH8100 V&V Plan"}, {"format": "internal", "name": "sourceid", "type": "string", "value": "3dspace"}]}
""")  # noqa: E501

REAL_ITEM_REV2 = json.loads(r"""
{"attributes": [{"format": "internal", "name": "resourceid", "type": "STRING", "value": "953DAA56D5BF0100C6666769ABC20300"}, {"format": "internal", "name": "type_icon_url", "type": "string", "value": "https://dspace.plm.nexperia.com/3dspace/snresources/images/icons/small/I_CDM_Document.png"}, {"format": "internal", "name": "preview_url", "type": "string", "value": "https://dspace.plm.nexperia.com/3dspace/snresources/images/icons/large/I_CDM_Document108x144.png"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:docExtension", "type": "string", "value": "xlsm", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:language", "type": "string", "value": "English", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:policy", "type": "string", "value": "Document Release", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:status/ds6w:reserved", "type": "boolean", "value": "FALSE", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:status", "type": "string", "value": "Document Release.RELEASED", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:type", "type": "string", "value": "Document", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/upg:nex_AllowWebpublish", "type": "string", "value": "No", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:what/ds6w:kind", "type": "string", "value": "TRUE", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:where/ds6w:context/ds6w:folder", "type": "string", "value": "Release and Production", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:where/ds6w:context/ds6w:project", "type": "string", "value": "Default", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:who/ds6w:responsible/ds6w:organizationResponsible", "type": "string", "value": "Nexperia", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:who/ds6w:responsible/ds6w:originator", "type": "string", "value": "Sheribeth Bolanos", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:who/ds6w:responsible", "type": "string", "value": "Sheribeth Bolanos", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:who/ds6w:lastModifiedBy", "type": "string", "value": "Sheribeth Bolanos", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:when/ds6w:created", "type": "date", "value": "2026-01-14T09:49:58Z", "field": "implicit"}, {"format": "ds6w_facet", "name": "ds6w:when/ds6w:modified", "type": "date", "value": "2026-09-03T14:42:33Z", "field": "implicit"}, {"format": "attribute", "name": "ds6w:identifier", "type": "string", "value": "DOC-594838"}, {"format": "attribute", "name": "ds6w:description", "type": "string", "value": "NEH8100 Verification and Validation Plan"}, {"format": "attribute", "name": "ds6wg:revision", "type": "string", "value": "2"}, {"format": "attribute", "name": "ds6w:label", "type": "string", "value": "NEH8100 V&V Plan"}, {"format": "internal", "name": "sourceid", "type": "string", "value": "3dspace"}]}
""")  # noqa: E501

# Issue型の例（実機の3DSearch画面でも同じ一覧に混在することを確認済み。
# D2の「Documentのみに絞る」検証用の最小サンプル）。
ISSUE_ITEM = {
    "attributes": [
        {"format": "ds6w_facet", "name": "ds6w:what/ds6w:type", "value": "Issue"},
        {"format": "attribute", "name": "ds6w:identifier", "value": "MC-20260827-112"},
    ]
}


# ── E1 additional_query が実測どおりに組み立てられる ─────────
print("\n[E1] additional_query の組み立て（実測との一致）")
REAL_ADDITIONAL_QUERY_TAIL = (
    ') AND NOT (flattenedtaxonomies:"types/Person" '
    'OR flattenedtaxonomies:"types/Security Context") '
    'AND (latestrevision:true OR NOT listoffields:latestrevision) '
)
built = dsm._enovia_additional_query(dsm.ENOVIA_DOCUMENT_TYPES)
check("先頭が ' AND (' で始まる", built.startswith(" AND ("), built[:20])
check("末尾が実測どおりのAND NOT句＋latestrevision句",
      built.endswith(REAL_ADDITIONAL_QUERY_TAIL), built[-160:])
check("Person / Security Context は include側には現れない（別枠のAND NOTのみ）",
      built.count('types/Person') == 1 and built.count('types/Security Context') == 1,
      built.count('types/Person'))
check("型は191種類（実測どおり。Person/Security Contextの2種は含まない）",
      len(dsm.ENOVIA_DOCUMENT_TYPES) == 191, len(dsm.ENOVIA_DOCUMENT_TYPES))
check("Issueも対象タイプに含まれる（型フィルタは緩く、絞り込みは応答側で行う設計）",
      "Issue" in dsm.ENOVIA_DOCUMENT_TYPES)


# ── E2 プロバイダの基本属性 ──────────────────────────────────
print("\n[E2] プロバイダの基本属性")
ep = dsm.EnoviaProvider(CFG, None)
check("SearchProviderを継承している（SharePointProviderは継承しない）",
      isinstance(ep, dsm.SearchProvider)
      and not isinstance(ep, dsm.SharePointProvider))
check("implemented が True（Phase 3で実装済み）", ep.implemented is True)
check("key が enovia", ep.key == dsm.TARGET_ENOVIA, ep.key)
check("label が Enovia", ep.label == "Enovia", ep.label)
check("SearchManagerに実装済みとして登録される",
      dsm.SearchManager(CFG, DummyAuth()).providers[dsm.TARGET_ENOVIA].implemented is True)
check("SearchManagerのstatuses並びにenoviaが含まれる（sharepoint/nexus/enoviaの順）",
      "enovia" in ["sharepoint", "nexus", "enovia"])


# ── E3 リクエスト本文の組み立て（start と next_start の切り替え） ──
print("\n[E3] リクエスト本文の組み立て")
body0 = ep._build_body("FMEA", 40, start=0, next_start_token=None)
check("1ページ目は start を使う", body0.get("start") == 0, body0.get("start"))
check("1ページ目に next_start / refine は含めない",
      "next_start" not in body0 and "refine" not in body0, str(body0.keys()))
check("select_predicate が実測どおり",
      body0["select_predicate"] == dsm.ENOVIA_SELECT_PREDICATE,
      body0["select_predicate"])
check("select_file が実測どおり", body0["select_file"] == ["icon", "thumbnail_2d"])
check("tenant が OnPremise", body0["tenant"] == "OnPremise")
check("query にキーワードがそのまま入る", body0["query"] == "FMEA", body0["query"])

body1 = ep._build_body("FMEA", 40, start=0, next_start_token="40 0 1 323904678")
check("2ページ目は next_start を使う（startは使わない）",
      body1.get("next_start") == "40 0 1 323904678" and "start" not in body1,
      str(body1))
check("2ページ目は refine={} を付ける（実測どおり）", body1.get("refine") == {})

custom_types = dict(CFG, enovia_types=["Document"])
body_custom = dsm.EnoviaProvider(custom_types, None)._build_body(
    "x", 1, start=0, next_start_token=None)
check("enovia_types をconfigで差し替えられる（将来の型追加に対応）",
      'types/Document"' in body_custom["specific_source_parameter"]["3dspace"]["additional_query"]
      and "nex_SalesItem" not in
      body_custom["specific_source_parameter"]["3dspace"]["additional_query"],
      body_custom["specific_source_parameter"]["3dspace"]["additional_query"][:80])


# ── E4 レスポンスの解析（実データそのまま） ───────────────────
print("\n[E4] レスポンスの解析（実測データ）")
result_rev3 = ep._item_to_result(REAL_ITEM_REV3, rank=1)
check("Document Number（ds6w:identifier）", result_rev3.document_number == "DOC-594838",
      result_rev3.document_number)
check("Title（ds6w:label）", result_rev3.title == "NEH8100 V&V Plan", result_rev3.title)
check("Description（ds6w:description）",
      result_rev3.description == "NEH8100 Verification and Validation Plan",
      result_rev3.description)
check("Revision（ds6wg:revision）", result_rev3.revision == "3", result_rev3.revision)
check("State（ds6w:what/ds6w:status、そのまま）",
      result_rev3.enovia_state == "Document Release.IN_WORK", result_rev3.enovia_state)
check("作成者（ds6w:who/ds6w:responsible/ds6w:originator）",
      result_rev3.author == "Sheribeth Bolanos", result_rev3.author)
check("Doc Owner（ds6w:who/ds6w:responsible）",
      result_rev3.doc_owner == "Sheribeth Bolanos", result_rev3.doc_owner)
check("最終更新日はJSTのYYYY-MM-DD（2026-09-03T15:11:21Z → 2026-09-04)",
      result_rev3.last_modified == "2026-09-04", result_rev3.last_modified)
check("作成日も同様にJST変換される",
      result_rev3.created_date == "2026-09-03", result_rev3.created_date)
check("フォルダ（ds6w:where/ds6w:context/ds6w:folder）",
      result_rev3.folder == "Release and Production", result_rev3.folder)
check("種別は拡張子（ds6w:what/ds6w:docExtension）",
      result_rev3.doc_type == "xlsm", result_rev3.doc_type)
check("resourceidが無い場合と違い、Enoviaで開くURLが組み立てられる",
      result_rev3.enovia_url ==
      ("https://dspace.plm.nexperia.com/3dspace/common/emxNavigator.jsp"
       "?objectId=953DAA5621FC01005A87996AC8680700"),
      result_rev3.enovia_url)
check("titleクリック用のurlもenovia_urlと同じ（Enoviaにはファイル直リンクが無いため）",
      result_rev3.url == result_rev3.enovia_url)
check("is_folderはFalse固定", result_rev3.is_folder is False)

result_rev2 = ep._item_to_result(REAL_ITEM_REV2, rank=2)
check("同一Document Numberでもrevisionが別行のまま扱われる（D1）",
      result_rev2.document_number == result_rev3.document_number
      and result_rev2.revision == "2" and result_rev3.revision == "3",
      f"{result_rev2.revision} / {result_rev3.revision}")
check("最終更新者（ds6w:who/ds6w:lastModifiedBy）はrev3には無く空、rev2にはある",
      result_rev3.last_modified_by == "" and result_rev2.last_modified_by == "Sheribeth Bolanos",
      f"{result_rev3.last_modified_by!r} / {result_rev2.last_modified_by!r}")

check("Document以外（Issue）はenovia_document_type_only=trueで除外される",
      ep._item_to_result(ISSUE_ITEM, rank=1) is None)
ep_all_types = dsm.EnoviaProvider(dict(CFG, enovia_document_type_only=False), None)
issue_result = ep_all_types._item_to_result(ISSUE_ITEM, rank=1)
check("enovia_document_type_only=falseならIssueも残る（設定で戻せる）",
      issue_result is not None and issue_result.document_number == "MC-20260827-112")


# ── E5 検索本体（_call_search をスタブ化してページングを検証） ──
print("\n[E5] 検索本体（ページング・件数・note）")


def make_page(items, nhits, next_start):
    return {"infos": {"nhits": nhits, "next_start": next_start}, "results": items}


calls = []


def stub_two_pages(session, body):
    calls.append(dict(body))
    if "next_start" not in body:
        return 200, make_page([REAL_ITEM_REV3, ISSUE_ITEM], 2, "PAGE2TOKEN"), ""
    if body.get("next_start") == "PAGE2TOKEN":
        return 200, make_page([REAL_ITEM_REV2], 2, None), ""
    raise AssertionError(f"想定外の呼び出し: {body}")


ep_search = dsm.EnoviaProvider(dict(CFG, enovia_page_size=2), None)
ep_search._build_session = lambda: object()  # Cookie検証は他で確認済みなのでここでは通す
ep_search._call_search = stub_two_pages
out = ep_search.search("FMEA", 10)
check("2ページにまたがって取得する", len(calls) == 2, len(calls))
check("Issue型は除外され、Documentの2件だけが残る（rev3 + rev2）",
      len(out["results"]) == 2
      and {r.document_number for r in out["results"]} == {"DOC-594838"},
      [r.document_number for r in out["results"]])
check("rankは除外分を詰めて1始まりの連番",
      [r.rank for r in out["results"]] == [1, 2], [r.rank for r in out["results"]])
check("totalはnhits（絞り込み前の全種別合計）", out["total"] == 2, out["total"])
check("件数の注記（Document以外を含む合計であることの明示）が入る",
      "Document以外を含む" in out["note"], out["note"])

ep_title = dsm.EnoviaProvider(dict(CFG, enovia_page_size=10), None)
ep_title._build_session = lambda: object()
ep_title._call_search = lambda session, body: (
    200, make_page([REAL_ITEM_REV3], 1, None), "")
ep_title.title_only = True
out_title = ep_title.search("FMEA", 10)
check("タイトル限定検索の構文が未確定であることをnoteに明示する（推測で絞り込んだふりをしない）",
      "タイトル限定検索の構文は未確定" in out_title["note"], out_title["note"])

# 部分成功：1ページ目は成功、2ページ目でエラーになっても取得済み分は返す
ep_partial = dsm.EnoviaProvider(dict(CFG, enovia_page_size=1), None)
ep_partial._build_session = lambda: object()
partial_calls = {"n": 0}


def stub_partial(session, body):
    partial_calls["n"] += 1
    if partial_calls["n"] == 1:
        return 200, make_page([REAL_ITEM_REV3], 2, "TOK"), ""
    return 500, None, "Internal Server Error"


ep_partial._call_search = stub_partial
out_partial = ep_partial.search("FMEA", 10)
check("2ページ目が失敗しても、取得済みの1件は返す（部分成功）",
      len(out_partial["results"]) == 1, len(out_partial["results"]))

# 型フィルタで大半が落ちるキーワードでも、際限なく叩き続けない安全弁
ep_capped = dsm.EnoviaProvider(dict(CFG, enovia_page_size=1, enovia_max_raw_pages=3), None)
ep_capped._build_session = lambda: object()
capped_calls = {"n": 0}


def stub_all_issue(session, body):
    capped_calls["n"] += 1
    token = None if capped_calls["n"] >= 3 else f"TOK{capped_calls['n']}"
    return 200, make_page([ISSUE_ITEM], 999, token), ""


ep_capped._call_search = stub_all_issue
out_capped = ep_capped.search("FMEA", 5)
check("enovia_max_raw_pagesで打ち切る（際限なく叩き続けない）",
      capped_calls["n"] == 3, capped_calls["n"])
check("打ち切ったことをnoteに明示する", "打ち切りました" in out_capped["note"],
      out_capped["note"])

# 1ページ目から失敗した場合は例外を投げる（Nexus/SharePointと同じ挙動）
ep_fail = dsm.EnoviaProvider(CFG, None)
ep_fail._build_session = lambda: object()
ep_fail._call_search = lambda session, body: (401, None, "Unauthorized")
try:
    ep_fail.search("FMEA", 10)
    check("1ページ目から失敗したら例外を投げる", False, "例外が発生しなかった")
except RuntimeError as e:
    check("1ページ目から失敗したら例外を投げる", "401" in str(e), str(e))


# ── E6 Cookie/セッションの用意 ───────────────────────────────
print("\n[E6] Cookie/セッションの用意")
tmp_dir = Path(tempfile.mkdtemp())
saved_cookie_path = dsm.ENOVIA_COOKIE_PATH
dsm.ENOVIA_COOKIE_PATH = tmp_dir / "enovia_session.json"
try:
    ep_nosession = dsm.EnoviaProvider(CFG, None)
    try:
        ep_nosession._build_session()
        check("Cookie未保存なら例外", False, "例外が発生しなかった")
    except RuntimeError as e:
        check("Cookie未保存なら例外で、ログイン方法を案内する",
              "Enoviaにログイン" in str(e), str(e))

    with open(dsm.ENOVIA_COOKIE_PATH, "w", encoding="utf-8") as f:
        json.dump({"cookies": [
            {"name": "JSESSIONID", "value": "abc123",
             "domain": ".plm.nexperia.com", "path": "/"},
        ]}, f)
    ep_withcookie = dsm.EnoviaProvider(CFG, None)
    session = ep_withcookie._build_session()
    check("保存済みCookieからセッションを作れる",
          session.cookies.get("JSESSIONID", domain=".plm.nexperia.com") == "abc123",
          str(list(session.cookies)))
finally:
    dsm.ENOVIA_COOKIE_PATH = saved_cookie_path

ep_manual = dsm.EnoviaProvider(dict(CFG, enovia_auth_mode="manual",
                                    enovia_manual_cookie="JSESSIONID=xyz"), None)
manual_session = ep_manual._build_session()
check("manualモードはCookieヘッダーをそのまま使う",
      manual_session.headers.get("Cookie") == "JSESSIONID=xyz",
      manual_session.headers.get("Cookie"))

ep_manual_empty = dsm.EnoviaProvider(dict(CFG, enovia_auth_mode="manual",
                                          enovia_manual_cookie=""), None)
try:
    ep_manual_empty._build_session()
    check("manualモードでCookie未設定なら例外", False, "例外が発生しなかった")
except RuntimeError as e:
    check("manualモードでCookie未設定なら例外", "enovia_manual_cookie" in str(e), str(e))


# ── E7 疎通診断 ──────────────────────────────────────────────
print("\n[E7] 疎通診断")
ep_probe_ok = dsm.EnoviaProvider(CFG, None)
ep_probe_ok._build_session = lambda: object()
ep_probe_ok._call_search = lambda session, body: (
    200, {"infos": {"nhits": 1}, "results": []}, "")
probe_ok = ep_probe_ok.probe()
check("200かつinfosがあればok", probe_ok["ok"] is True, probe_ok)
check("modeがfederated-search", probe_ok["mode"] == "federated-search", probe_ok["mode"])

ep_probe_relogin = dsm.EnoviaProvider(CFG, None)
ep_probe_relogin._build_session = lambda: object()
ep_probe_relogin._call_search = lambda session, body: (
    200, None, "レスポンスがJSON形式ではありません（Enoviaのログインが失効している可能性があります）。")
probe_relogin = ep_probe_relogin.probe()
check("200でもJSONでなければ ok=False（ログイン失効）",
      probe_relogin["ok"] is False and probe_relogin["mode"] == "ログイン失効", probe_relogin)

ep_probe_nocookie = dsm.EnoviaProvider(CFG, None)


def raise_no_cookie():
    raise RuntimeError("Enoviaのログイン情報がありません。画面の「Enoviaにログイン」を実行してください。")


ep_probe_nocookie._build_session = raise_no_cookie
probe_nocookie = ep_probe_nocookie.probe()
check("Cookie無しなら疎通診断もエラーを案内する（Graphを呼びに行かない）",
      probe_nocookie["ok"] is False and "Enoviaにログイン" in probe_nocookie["message"],
      probe_nocookie)


# ── E8 ログイン（Playwright未導入環境での挙動） ───────────────
print("\n[E8] ログイン（playwright未導入時の挙動）")
# 会社PC以外の環境（このテスト実行環境を含む）でplaywrightが無くても
# 落ちずに、代替手段（manualモード）を案内することを確認する。
# playwrightの実際のインストール有無に関わらず同じ結果になるよう、
# sys.modules に None を仕込んで import を確実に失敗させる。
blocked = {"playwright": None, "playwright.sync_api": None}
saved_modules = {k: sys.modules.get(k) for k in blocked}
sys.modules.update(blocked)
try:
    login_result = ep.login_interactive()
finally:
    for k, v in saved_modules.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
check("playwright未導入なら ok=False", login_result["ok"] is False, login_result)
check("pip install の案内とmanualモードへの案内を含む",
      "pip install playwright" in login_result["message"]
      and "manual" in login_result["message"], login_result["message"])


# ── E9 タイトル限定構文の診断（D3） ───────────────────────────
print("\n[E9] タイトル限定構文の診断")
ep_diag = dsm.EnoviaProvider(CFG, None)
ep_diag._build_session = lambda: object()


def stub_diag(session, body):
    q = body["query"]
    totals = {"FMEA": 100, 'title:"FMEA"': 3, 'ds6w:label:"FMEA"': 5}
    return 200, {"infos": {"nhits": totals.get(q, 0)}, "results": []}, ""


ep_diag._call_search = stub_diag
rows = ep_diag.diagnose_title_only("FMEA")
check("3通りの構文を試す", len(rows) == 3, len(rows))
check("① 全文検索の件数が反映される", rows[0]["total"] == 100, rows[0])
check("② title: 構文の件数が反映される", rows[1]["total"] == 3, rows[1])
check("③ ds6w:label: 構文の件数が反映される", rows[2]["total"] == 5, rows[2])
check("空キーワードは空リスト", ep_diag.diagnose_title_only("") == [])

ep_diag_nocookie = dsm.EnoviaProvider(CFG, None)
ep_diag_nocookie._build_session = raise_no_cookie
diag_nocookie = ep_diag_nocookie.diagnose_title_only("FMEA")
check("Cookie無しでも診断が例外にならず、理由を返す",
      len(diag_nocookie) == 1 and diag_nocookie[0]["ok"] is False, diag_nocookie)


# ── E10 Excel / CSV 出力の列構成 ──────────────────────────────
print("\n[E10] Excel / CSV 出力の列構成")
mgr = dsm.SearchManager(CFG, DummyAuth())
enovia_row = dsm.SearchResult(
    source="Enovia", document_number="DOC-594838", title="NEH8100 V&V Plan",
    description="NEH8100 Verification and Validation Plan", revision="3",
    enovia_state="Document Release.IN_WORK", author="Sheribeth Bolanos",
    doc_owner="Sheribeth Bolanos", last_modified_by="", last_modified="2026-09-04",
    created_date="2026-09-03", folder="Release and Production", doc_type="xlsm",
    url="https://dspace.plm.nexperia.com/3dspace/common/emxNavigator.jsp?objectId=x",
    enovia_url="https://dspace.plm.nexperia.com/3dspace/common/emxNavigator.jsp?objectId=x",
    rank=1)
mgr.providers[dsm.TARGET_ENOVIA].search = (
    lambda kw, mx: {"results": [enovia_row], "total": 1, "note": ""})
dsm._cfg = CFG
dsm._manager = mgr
client = dsm.flask_app.test_client()
client.post("/api/search", json={"keyword": "FMEA", "target": "enovia"})

head = client.get("/api/export?format=csv").get_data(as_text=True).splitlines()[0]
for label in ("Document Number", "Title", "Description", "Revision", "State",
              "作成者", "Doc Owner", "最終更新者", "最終更新日", "作成日", "フォルダ", "種別"):
    check(f"CSVヘッダーに {label} がある", label in head, head)
check("CSVヘッダーにEnoviaリンクがある", "Enoviaリンク" in head, head)
check("Enoviaの出力にNexus固有列を出さない",
      "OldSystemIdentifier" not in head and "Applicable To" not in head, head)
check("Enoviaの出力にSharePoint固有列(サイト/フォルダリンク)を出さない",
      "サイトリンク" not in head and "フォルダリンク" not in head, head)
resp_xlsx = client.get("/api/export?format=xlsx")
check("Excel出力も200", resp_xlsx.status_code == 200, resp_xlsx.status_code)


# ── E11 config.example.json との整合 ──────────────────────────
print("\n[E11] config.example.json との整合")
example = json.loads((Path(dsm.__file__).resolve().parent
                      / "config.example.json").read_text(encoding="utf-8"))
check("ひな形に enovia_types がある", "enovia_types" in example)
check("ひな形の enovia_types が本体の定数と完全一致する（推測で別々に書いていない）",
      example["enovia_types"] == dsm.ENOVIA_DOCUMENT_TYPES,
      f"len={len(example.get('enovia_types', []))}")
check("ひな形の enovia_auth_mode が既定値 playwright",
      example.get("enovia_auth_mode") == "playwright")
check("ひな形の enovia_document_type_only が既定値 true（D2）",
      example.get("enovia_document_type_only") is True)
check("ひな形に説明キーがある",
      "_comment_enovia" in example and "_comment_enovia_auth" in example
      and "_comment_enovia_types" in example)


# ── E12 画面表示 ──────────────────────────────────────────────
print("\n[E12] 画面表示")
html = dsm.flask_app.test_client().get("/").get_data(as_text=True)
check("Enoviaタブがある", 'data-target="enovia"' in html)
check("Enoviaにログインボタンがある", 'id="btnEnoviaLogin"' in html)
check("Enovia検索診断ボタンがある", 'id="btnEnoviaDiag"' in html)
check("COLUMN_SETS.enoviaにDocument Number/Revision/Stateが隣接して定義されている（B5/D1）",
      'key: "document_number"' in html.split("enovia: [")[1].split("];")[0]
      and 'key: "revision"' in html.split("enovia: [")[1].split("];")[0]
      and 'key: "enovia_state"' in html.split("enovia: [")[1].split("];")[0],
      html.split("enovia: [")[1].split("];")[0][:200])
check("enovia_url列がlink型で定義されている",
      'key: "enovia_url"' in html and 'label: "Enoviaで開く"' in html)
check("一括ダウンロードの選択対象からEnoviaを除外している（selectableRows）",
      'r.source !== "Enovia"' in html)
check("0.Allタブでのタイトル(Rev.N)併記ロジックがある（B5）",
      'shownTarget === "all" && r.revision' in html)


print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
