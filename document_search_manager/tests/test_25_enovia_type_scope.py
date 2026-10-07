# -*- coding: utf-8 -*-
"""Enovia全種別対応（S04本実装）— v20260924_01 で追加

document_search_manager: Enovia検索のスコープを3択（①Documentのみ/②よく使う型
/③全種別）にする本実装を検証する。越智さんの実機診断（2026-09-24、キーワード
"NEX13160"）で実際に取得した nex_Kit / nex_WiringDiagram の応答をそのまま
サンプルとして使う（推測では作っていない）。
ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_25_enovia_type_scope.py
（まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import inspect
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

# 実機診断（2026-09-24、"NEX13160"）の応答をそのまま転記した2件。
# フォルダ・最終更新者が構造的に空欄であることの検証（B6/enovia_type_sparse）
# にもそのまま使う。
KIT_ITEM = {
    "attributes": [
        {"name": "resourceid", "value": "B763AA56542200007C4EAD68FADD0C00"},
        {"name": "ds6w:what/ds6w:type", "value": "nex_Kit"},
        {"name": "ds6w:identifier", "value": "K-000046315"},
        {"name": "ds6w:label", "value": "K-000046315"},
        {"name": "ds6w:description", "value": "SOT8106YZ1-Cu_JCET-NEX13160/A1X/8v-200um"},
        {"name": "ds6wg:revision", "value": "2"},
        {"name": "ds6w:what/ds6w:status", "value": "nex_Superseded.SUP"},
        {"name": "ds6w:who/ds6w:responsible/ds6w:originator", "value": "KATHARINE NG"},
        {"name": "ds6w:who/ds6w:responsible", "value": "KATHARINE NG"},
        # 実機診断で「最終更新者」「フォルダ」は0/2（値なし）だった＝キー自体が無い。
        {"name": "ds6w:when/ds6w:modified", "value": "2025-09-25T08:25:06Z"},
        {"name": "ds6w:when/ds6w:created", "value": "2025-08-26T06:04:44Z"},
    ]
}

WIRING_DIAGRAM_ITEM = {
    "attributes": [
        {"name": "resourceid", "value": "953DAA5653970000261AFD6713D50000"},
        {"name": "ds6w:what/ds6w:type", "value": "nex_WiringDiagram"},
        {"name": "ds6w:identifier", "value": "WIDI-506040"},
        {"name": "ds6w:label", "value": "WIDI-506040"},
        {"name": "ds6w:description", "value": "NEX13160(F)PE-NEX13161(F)PE-NEX13241F-Q1 A0A1"},
        {"name": "ds6wg:revision", "value": "1"},
        {"name": "ds6w:what/ds6w:status", "value": "nex_Superseded.SUP"},
        {"name": "ds6w:what/ds6w:docExtension", "value": "pdf"},
        {"name": "ds6w:who/ds6w:responsible", "value": "KATHARINE NG"},
        # 実機診断で「作成者」は0/2、「フォルダ」は0/2、「最終更新者」は1/2だった。
        # この代表サンプルは「最終更新者が無い方」を転記する（sparse判定の検証用）。
        {"name": "ds6w:when/ds6w:modified", "value": "2025-07-31T02:47:50Z"},
        {"name": "ds6w:when/ds6w:created", "value": "2025-04-14T14:22:30Z"},
    ]
}

DOCUMENT_ITEM = {
    "attributes": [
        {"name": "resourceid", "value": "953DAA5621FC01005A87996AC8680700"},
        {"name": "ds6w:what/ds6w:type", "value": "Document"},
        {"name": "ds6w:identifier", "value": "DOC-594838"},
        {"name": "ds6w:label", "value": "NEH8100 V&V Plan"},
        {"name": "ds6w:where/ds6w:context/ds6w:folder", "value": "Release and Production"},
        {"name": "ds6w:who/ds6w:lastModifiedBy", "value": "Sheribeth Bolanos"},
    ]
}

PROJECT_SPACE_ITEM = {
    "attributes": [
        {"name": "resourceid", "value": "AAAA0000000000000000000000000000"},
        {"name": "ds6w:what/ds6w:type", "value": "Project Space"},
        {"name": "ds6w:identifier", "value": "PS-000123"},
        {"name": "ds6w:label", "value": "PS-000123"},
    ]
}


# ── T1: _enovia_type_label（表示ラベルの機械変換） ─────────────
print("\n[T1] Enovia型の表示ラベル変換（実機Enovia画面のType表示と一致確認済み）")
check('nex_Kit → "Kit"（実機Enovia画面のType表示と一致、2026-09-24確認）',
      dsm.EnoviaProvider._enovia_type_label("nex_Kit") == "Kit")
check('nex_WiringDiagram → "Wiring Diagram"（同上）',
      dsm.EnoviaProvider._enovia_type_label("nex_WiringDiagram") == "Wiring Diagram")
check('"Document"（nex_接頭辞なし）はそのまま',
      dsm.EnoviaProvider._enovia_type_label("Document") == "Document")
check('"Project Space"（スペース済み・接頭辞なし）はそのまま',
      dsm.EnoviaProvider._enovia_type_label("Project Space") == "Project Space")
check("空文字は空文字のまま（例外を投げない）",
      dsm.EnoviaProvider._enovia_type_label("") == "")


# ── T2: _type_allowed（スコープ3択の判定） ──────────────────
print("\n[T2] スコープ3択（document/major/all）の判定ロジック")
ep = dsm.EnoviaProvider(dict(CFG), None)

ep.type_scope = "document"
check('scope="document": Documentは許可', ep._type_allowed("Document") is True)
check('scope="document": nex_Kitは除外', ep._type_allowed("nex_Kit") is False)
check('scope="document": Project Spaceも除外', ep._type_allowed("Project Space") is False)

ep.type_scope = "major"
check('scope="major": Documentは許可', ep._type_allowed("Document") is True)
check('scope="major": Project Spaceは許可（既定のenovia_major_types）',
      ep._type_allowed("Project Space") is True)
check('scope="major": nex_Kitは除外（Document/Project Space限定）',
      ep._type_allowed("nex_Kit") is False)

ep.type_scope = "all"
check('scope="all": nex_Kitも許可', ep._type_allowed("nex_Kit") is True)
check('scope="all": nex_WiringDiagramも許可', ep._type_allowed("nex_WiringDiagram") is True)

ep.type_scope = None
check("type_scope未設定時はcfgのenovia_type_scope_default（既定document）にフォールバック",
      ep._type_allowed("Document") is True and ep._type_allowed("nex_Kit") is False)

ep_major_custom = dsm.EnoviaProvider(
    dict(CFG, enovia_major_types=["Document", "nex_Kit"]), None)
ep_major_custom.type_scope = "major"
check("enovia_major_typesをconfigで変更できる",
      ep_major_custom._type_allowed("nex_Kit") is True
      and ep_major_custom._type_allowed("Project Space") is False)


# ── T3: _item_to_result（enovia_type / enovia_type_raw / sparse） ──
print("\n[T3] _item_to_result: enovia_type系フィールドとsparse判定")
ep_all = dsm.EnoviaProvider(dict(CFG), None)
ep_all.type_scope = "all"

kit_result = ep_all._item_to_result(KIT_ITEM, rank=1)
check("Kit: enovia_type_rawが生値のまま", kit_result.enovia_type_raw == "nex_Kit")
check("Kit: enovia_typeが変換後ラベル", kit_result.enovia_type == "Kit")
check("Kit: フォルダ・最終更新者がともに空欄のためsparse=True",
      kit_result.enovia_type_sparse is True,
      (kit_result.folder, kit_result.last_modified_by))

wiring_result = ep_all._item_to_result(WIRING_DIAGRAM_ITEM, rank=2)
check("WiringDiagram: enovia_typeが変換後ラベル",
      wiring_result.enovia_type == "Wiring Diagram")
check("WiringDiagram: フォルダ・最終更新者がともに空欄のためsparse=True",
      wiring_result.enovia_type_sparse is True)
check("WiringDiagram: 種別（拡張子）列は従来どおりdocExtensionのまま（pdf）",
      wiring_result.doc_type == "pdf",
      wiring_result.doc_type)

document_result = ep_all._item_to_result(DOCUMENT_ITEM, rank=3)
check("Document: フォルダ・最終更新者のどちらかがあればsparse=False",
      document_result.enovia_type_sparse is False,
      (document_result.folder, document_result.last_modified_by))
check("Document: enovia_typeはDocumentのまま（nex_接頭辞が無いため変換不要）",
      document_result.enovia_type == "Document")


# ── T4: EnoviaProvider.search() のnote文言（スコープごとに出し分け） ──
print("\n[T4] search()のnote文言がスコープごとに異なる（M5）")


def make_page(items, nhits, next_start):
    return {"infos": {"nhits": nhits, "next_start": next_start}, "results": items}


def stub_all_types(session, body):
    return 200, make_page([KIT_ITEM, WIRING_DIAGRAM_ITEM], 4, None), ""


ep_doc_scope = dsm.EnoviaProvider(dict(CFG), None)
ep_doc_scope._build_session = lambda: object()
ep_doc_scope._call_search = stub_all_types
ep_doc_scope.type_scope = "document"
out_doc = ep_doc_scope.search("NEX13160", 10)
check("scope=document: 該当件数(4)より表の行数(0)が少ないことの注記が出る",
      "Documentのみに絞っている" in out_doc["note"], out_doc["note"])
check("scope=document: Kit/WiringDiagramは表に出ない（0件）",
      len(out_doc["results"]) == 0, len(out_doc["results"]))

ep_major_scope = dsm.EnoviaProvider(dict(CFG), None)
ep_major_scope._build_session = lambda: object()
ep_major_scope._call_search = stub_all_types
ep_major_scope.type_scope = "major"
out_major = ep_major_scope.search("NEX13160", 10)
check("scope=major: よく使う型に絞っている旨の注記が出る",
      "よく使う型" in out_major["note"], out_major["note"])

ep_all_scope = dsm.EnoviaProvider(dict(CFG), None)
ep_all_scope._build_session = lambda: object()
ep_all_scope._call_search = stub_all_types
ep_all_scope.type_scope = "all"
out_all = ep_all_scope.search("NEX13160", 10)
check("scope=all: NEX13160の実例どおりKit/WiringDiagramとも表に出る（2件）",
      len(out_all["results"]) == 2, len(out_all["results"]))
check("scope=all: 該当件数と表の行数が一致するため絞り込みの注記が出ない",
      "件数より少なくなります" not in out_all["note"], out_all["note"])


# ── T5: SearchManager.search() がtype_scopeをEnoviaProviderへ伝える ──
print("\n[T5] SearchManager.search() のtype_scope伝播")
mgr = dsm.SearchManager(dict(CFG), DummyAuth())
mgr.providers[dsm.TARGET_ENOVIA]._build_session = lambda: object()
mgr.providers[dsm.TARGET_ENOVIA]._call_search = stub_all_types

outcome_all = mgr.search("NEX13160", dsm.TARGET_ENOVIA, 10, type_scope="all")
enovia_status = next(s for s in outcome_all["statuses"] if s["key"] == dsm.TARGET_ENOVIA)
check("SearchManager経由でtype_scope=\"all\"が反映される（Kit/WiringDiagramとも2件）",
      enovia_status["count"] == 2, enovia_status)

outcome_doc = mgr.search("NEX13160", dsm.TARGET_ENOVIA, 10, type_scope="document")
enovia_status_doc = next(s for s in outcome_doc["statuses"] if s["key"] == dsm.TARGET_ENOVIA)
check("SearchManager経由でtype_scope=\"document\"が反映される（0件）",
      enovia_status_doc["count"] == 0, enovia_status_doc)

# type_scopeはEnoviaProviderにのみ意味を持つ属性。他プロバイダ（SharePoint/
# Nexus）には単に属性が付くだけで、参照されないため実害が無いはず（ネット
# ワークアクセスを避けるため、実際の検索は呼ばずクラス側の実装だけ確認する）。
check("SharePointProvider/NexusProviderはtype_scope属性を参照しない（無害）",
      "type_scope" not in inspect.getsource(dsm.SharePointProvider.search)
      and "type_scope" not in inspect.getsource(dsm.NexusProvider.search))


# ── T6: _load_config() の旧キー読み替え（B4・後方互換） ────────
print("\n[T6] config.json 旧キー enovia_document_type_only の読み替え（B4）")
tmp = Path(tempfile.mkdtemp())


def setup_config(own_cfg):
    base = tmp / f"case{len(list(tmp.iterdir()))}"
    tool = base / "document_search_manager"
    tool.mkdir(parents=True)
    (tool / "config.json").write_text(json.dumps(own_cfg), encoding="utf-8")
    dsm.CONFIG_PATH = tool / "config.json"
    dsm.CONFIG_EXAMPLE = tool / "config.example.json"
    dsm.CREDENTIAL_SOURCES = []
    return base


BASE_EXAMPLE = {"tenant_id": "T", "client_id": "C"}

setup_config(dict(BASE_EXAMPLE, enovia_document_type_only=False))
cfg_migrated_false = dsm._load_config()
check("旧キーfalse・新キー未設定 → enovia_type_scope_default=\"all\"に読み替え",
      cfg_migrated_false.get("enovia_type_scope_default") == "all",
      cfg_migrated_false.get("enovia_type_scope_default"))

setup_config(dict(BASE_EXAMPLE, enovia_document_type_only=True))
cfg_migrated_true = dsm._load_config()
check("旧キーtrue・新キー未設定 → enovia_type_scope_default=\"document\"に読み替え",
      cfg_migrated_true.get("enovia_type_scope_default") == "document")

setup_config(dict(BASE_EXAMPLE, enovia_document_type_only=False,
                  enovia_type_scope_default="major"))
cfg_explicit = dsm._load_config()
check("新キーが明示されていれば、旧キーより新キーを優先する（読み替えで上書きしない）",
      cfg_explicit.get("enovia_type_scope_default") == "major",
      cfg_explicit.get("enovia_type_scope_default"))

setup_config(dict(BASE_EXAMPLE))
cfg_default = dsm._load_config()
check("どちらのキーも無ければDEFAULT_CFGどおり既定document",
      cfg_default.get("enovia_type_scope_default") == "document")


# ── T7: 画面（HTML/JS）にスコープ選択・列・キャッシュキーが存在する ──
print("\n[T7] 画面（HTML/JS）の構造確認")
html = dsm.INDEX_HTML
check('スコープ選択欄（id="enoviaScope"）がある', 'id="enoviaScope"' in html)
check('スコープ選択行（id="enoviaScopeRow"）は既定で隠れている',
      '<div class="row" id="enoviaScopeRow" hidden>' in html)
check("スコープの3択（document/major/all）がoption値として定義されている",
      'value="document"' in html and 'value="major"' in html and 'value="all"' in html)
check("COLUMN_SETS.enoviaにenovia_type列がある",
      '{ key: "enovia_type",      label: "Enovia型",            type: "set"    }' in html)
# v20260925_03（S05本実装）で、対象サイトをキャッシュの条件に加えるため
# cacheKeyの引数が1つ増えた（typeScopeの後ろにsiteScope）。仕様変更に伴う
# 期待値の更新で、typeScopeを受け取ることに変わりはない。
check("cacheKey関数がtypeScope引数を受け取る",
      "function cacheKey(keyword, target, maxResults, titleOnly, prefixSearch, typeScope,"
      in html)
check("runSearchのfetch本文でtype_scopeを送っている", "type_scope: p.typeScope" in html)
check("saveState/restoreStateでenovia_type_scopeを保存・復元している",
      "enovia_type_scope: document.getElementById(\"enoviaScope\").value" in html
      and 's.enovia_type_scope' in html)
check("setTargetでEnoviaタブ以外はenoviaScopeRowを隠す",
      'document.getElementById("enoviaScopeRow").hidden = (target !== "enovia");' in html)
check("sparse行への注記アイコン表示ロジックがある",
      "r.enovia_type_sparse" in html)


# ── T8: CSV/Excel出力にもEnovia型列が含まれる ──────────────
print("\n[T8] エクスポート仕様（Excel/CSV）")
source = Path(dsm.__file__).read_text(encoding="utf-8")
check('エクスポートspec（Enovia専用）に"Enovia型"列が追加されている',
      '("Enovia型",        lambda r: r.enovia_type,     None),' in source)


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(0 if ng == 0 else 1)
