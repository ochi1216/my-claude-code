# -*- coding: utf-8 -*-
"""Nexus（Shareflex品質文書サイト）検索 — v20260903_09 で追加

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
Graph を呼ぶ経路は必ずスタブに差し替える。
実行: python tests/test_09_nexus.py   （まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth, DSM_FILENAME  # noqa: E402

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
SCOPE = "https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd/Documents"

# ── N1 検索範囲URLの組み立て ─────────────────────────────────
print("\n[N1] KQLに渡す検索範囲URLの組み立て（_nexus_scope_url）")
check("サイトURLのホスト＋サーバー相対パスから絶対URLを組み立てる",
      dsm._nexus_scope_url(CFG) == SCOPE, dsm._nexus_scope_url(CFG))

cfg_abs = dict(CFG, nexus_folder_path="https://other.example.com/sites/X/Docs/")
check("フォルダパスが絶対URLならそれを優先（末尾の / は落とす）",
      dsm._nexus_scope_url(cfg_abs) == "https://other.example.com/sites/X/Docs",
      dsm._nexus_scope_url(cfg_abs))

cfg_nofolder = dict(CFG, nexus_folder_path="")
check("フォルダパスが空ならサイトURLで代用",
      dsm._nexus_scope_url(cfg_nofolder)
      == "https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd",
      dsm._nexus_scope_url(cfg_nofolder))

check("サイトURLが空なら空文字（設定不足として扱わせる）",
      dsm._nexus_scope_url(dict(CFG, nexus_site_url="")) == "")
check("サイトURLが不正なら空文字",
      dsm._nexus_scope_url(dict(CFG, nexus_site_url="not-a-url")) == "",
      dsm._nexus_scope_url(dict(CFG, nexus_site_url="not-a-url")))

# ── N2 プロバイダの基本属性 ──────────────────────────────────
print("\n[N2] プロバイダの基本属性")
nx = dsm.NexusProvider(CFG, DummyAuth())
check("SharePointProviderを継承して実装を再利用している",
      isinstance(nx, dsm.SharePointProvider))
check("implemented が True（Phase 2で実装済み）", nx.implemented is True)
check("key が nexus", nx.key == dsm.TARGET_NEXUS, nx.key)
check("label が Nexus", nx.label == "Nexus", nx.label)
check("SearchManagerに実装済みとして登録される",
      dsm.SearchManager(CFG, DummyAuth()).providers[dsm.TARGET_NEXUS].implemented is True)

# ── N3 KQL（検索範囲の限定） ─────────────────────────────────
print("\n[N3] 検索範囲を限定するKQL")
q = nx._query_string("validation")
check("キーワードをそのまま先頭に置く", q.startswith("validation "), q)
check("path: でNexusフォルダに限定する", f'path:"{SCOPE}"' in q, q)
check("SharePoint側はKQLを付けない（従来どおり）",
      dsm.SharePointProvider(CFG, DummyAuth())._query_string("validation") == "validation")

nx_nocfg = dsm.NexusProvider(dict(CFG, nexus_site_url="", nexus_folder_path=""),
                             DummyAuth())
check("設定不足のときはキーワードだけにする（不正なKQLを作らない）",
      nx_nocfg._query_string("validation") == "validation",
      nx_nocfg._query_string("validation"))

# 実際に検索を回したときに、KQLが Graph 呼び出しへ渡ることを確認する
sent = []


def stub_call(token, query_string, frm, size):
    sent.append(query_string)
    return 200, {"value": [{"hitsContainers": [{
        "total": 1,
        "hits": [{"resource": {"webUrl": SCOPE + "/spec.pdf"}}],
        "moreResultsAvailable": False,
    }]}]}, ""


nx_run = dsm.NexusProvider(CFG, DummyAuth())
nx_run._mode = "search-api"
nx_run._call_search_api = stub_call
out = nx_run.search("validation", 10)
check("検索実行時にKQLがGraph呼び出しへ渡る",
      len(sent) == 1 and sent[0] == f'validation path:"{SCOPE}"', str(sent))
check("結果のソースが Nexus", out["results"][0].source == "Nexus",
      out["results"][0].source)
check("結果が Nexus配下と判定される", out["results"][0].is_nexus_path is True)
check("タイトルをURLから復元（SharePoint側のパーサを再利用）",
      out["results"][0].title == "spec.pdf", out["results"][0].title)

# ── N4 疎通診断 ──────────────────────────────────────────────
print("\n[N4] 疎通診断")
nx_probe = dsm.NexusProvider(CFG, DummyAuth())
nx_probe._call_search_api = lambda token, q, frm, size: (200, {}, "")
probe_ok = nx_probe.probe()
check("200なら ok=True / mode=search-api", probe_ok["ok"] is True
      and probe_ok["mode"] == "search-api", json.dumps(probe_ok, ensure_ascii=False))
check("成功メッセージがNexus向けの文面", "Nexus" in probe_ok["message"],
      probe_ok["message"])

nx_denied = dsm.NexusProvider(CFG, DummyAuth())
nx_denied._call_search_api = lambda token, q, frm, size: (403, None, "Forbidden")
probe_403 = nx_denied.probe()
check("403ならNexusサイト単位検索へ切り替える",
      probe_403["ok"] is True and probe_403["mode"] == "site-drive",
      json.dumps(probe_403, ensure_ascii=False))
check("フォールバック先はNexusサイト1件",
      nx_denied._fallback_sites() == [CFG["nexus_site_url"]],
      str(nx_denied._fallback_sites()))

probe_cfg = dsm.NexusProvider(dict(CFG, nexus_site_url="", nexus_folder_path=""),
                              DummyAuth()).probe()
check("設定不足なら Graph を呼ばずに『設定不足』を返す",
      probe_cfg["ok"] is False and probe_cfg["mode"] == "設定不足",
      json.dumps(probe_cfg, ensure_ascii=False))

# ── N5 Nexus固有の列（nexus_extra_fields） ───────────────────
print("\n[N5] Nexus固有の列の要求と、拒否されたときの段階的な縮退")
check("既定では標準の search_fields と同じ",
      dsm.NexusProvider(CFG, DummyAuth())._search_fields() == list(CFG["search_fields"]))

cfg_extra = dict(CFG, nexus_extra_fields=["DocumentNumber", "Department", "title"])
nx_extra = dsm.NexusProvider(cfg_extra, DummyAuth())
fields = nx_extra._search_fields()
check("設定した固有列が末尾に追加される",
      fields[-2:] == ["DocumentNumber", "Department"], str(fields))
check("標準の列と重複する名前は追加しない（大小文字を無視）",
      sum(1 for f in fields if f.lower() == "title") == 1, str(fields))

check("1段階目の縮退で固有列だけを落とす",
      nx_extra._degrade_fields() is True and nx_extra._search_fields()
      == list(CFG["search_fields"]), str(nx_extra._search_fields()))
check("1段階目では標準の列を捨てない（タイトルが取れなくならない）",
      nx_extra._fields_disabled is False)
check("2段階目の縮退で fields 自体を落とす",
      nx_extra._degrade_fields() is True and nx_extra._fields_disabled is True)
check("3回目は縮退できないので False", nx_extra._degrade_fields() is False)

# HTTP 400 を受けたときに、実際に固有列だけを落として再試行すること
requested = []


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}
        self.text = "Bad Request: invalid field"

    def json(self):
        return self._payload


def fake_post(url, headers=None, json=None, timeout=None):
    body = json["requests"][0]
    requested.append(list(body.get("fields") or []))
    if "DocumentNumber" in (body.get("fields") or []):
        return FakeResp(400)
    return FakeResp(200, {"value": [{"hitsContainers": [
        {"total": 1, "hits": [{"resource": {"webUrl": SCOPE + "/a.docx"}}],
         "moreResultsAvailable": False}]}]})


nx_400 = dsm.NexusProvider(cfg_extra, DummyAuth())
orig_post = dsm.http_req.post
dsm.http_req.post = fake_post
try:
    status, body, err = nx_400._call_search_api("tok", "validation", 0, 10)
    check("400を受けて再試行し成功する", status == 200, f"{status} {err}")
    check("1回目は固有列あり", "DocumentNumber" in requested[0], str(requested[0]))
    check("2回目は固有列だけを外して標準の列は残す",
          requested[1] == list(CFG["search_fields"]), str(requested[1]))
finally:
    dsm.http_req.post = orig_post

# ── N6 Nexusサイト外の結果を混ぜない（保険） ─────────────────
print("\n[N6] path: 絞り込みが効かなかった場合の保険")


def stub_mixed(token, query_string, frm, size):
    return 200, {"value": [{"hitsContainers": [{
        "total": 3,
        "hits": [
            {"resource": {"webUrl": SCOPE + "/in1.pdf"}},
            {"resource": {"webUrl": "https://nexperia.sharepoint.com/sites/Other/x.pdf"}},
            {"resource": {"webUrl": SCOPE + "/in2.pdf"}},
        ],
        "moreResultsAvailable": False,
    }]}]}, ""


nx_mix = dsm.NexusProvider(CFG, DummyAuth())
nx_mix._mode = "search-api"
nx_mix._call_search_api = stub_mixed
mixed = nx_mix.search("validation", 10)
check("Nexusサイト外の行を除外する", len(mixed["results"]) == 2,
      str([r.url for r in mixed["results"]]))
check("除外後もrankが1始まりの連番",
      [r.rank for r in mixed["results"]] == [1, 2],
      str([r.rank for r in mixed["results"]]))
check("除外したことを note に明示する（黙って消さない）",
      "1 件を除外" in mixed["note"], mixed["note"])

# ── N7 SharePointとの重複排除 ────────────────────────────────
print("\n[N7] SharePoint側との重複排除")
rows = [
    dsm.SearchResult(source="SharePoint", title="a", is_nexus_path=False),
    dsm.SearchResult(source="SharePoint", title="b", is_nexus_path=True),
    dsm.SearchResult(source="Nexus", title="b", is_nexus_path=True),
]
mgr = dsm.SearchManager(CFG, DummyAuth())
check("既定の設定が dedupe_nexus_from_sharepoint=true",
      CFG["dedupe_nexus_from_sharepoint"] is True)

kept, exc = mgr._dedupe(list(rows), nexus_searched=True)
check("Nexusを検索したときはSharePoint側のNexus文書を除外",
      len(kept) == 2 and exc == 1, f"{len(kept)}/{exc}")
kept_off, exc_off = mgr._dedupe(list(rows), nexus_searched=False)
check("Nexusを検索していないときは除外しない（取りこぼしを防ぐ）",
      len(kept_off) == 3 and exc_off == 0, f"{len(kept_off)}/{exc_off}")

# 実際の検索経路でも同じになること（両系統ともスタブ）
def stub_provider(source, is_nexus):
    return lambda kw, mx: {"results": [dsm.SearchResult(
        source=source, title="dup", url="https://x/dup.pdf",
        is_nexus_path=is_nexus)], "total": 1, "note": ""}


mgr.providers[dsm.TARGET_SHAREPOINT].search = stub_provider("SharePoint", True)
mgr.providers[dsm.TARGET_NEXUS].search = stub_provider("Nexus", True)

res_all = mgr.search("validation", dsm.TARGET_ALL, 10)
check("0.All ではSharePoint側の重複を除外する",
      len(res_all["results"]) == 1 and res_all["excluded_nexus"] == 1,
      json.dumps([r.source for r in res_all["results"]]))
check("残るのはNexus側の行", res_all["results"][0].source == "Nexus")

res_sp = mgr.search("validation", dsm.TARGET_SHAREPOINT, 10)
check("1.SharePoint 単独ではNexus文書を消さない",
      len(res_sp["results"]) == 1 and res_sp["excluded_nexus"] == 0,
      json.dumps([r.source for r in res_sp["results"]]))

mgr_off = dsm.SearchManager(dict(CFG, dedupe_nexus_from_sharepoint=False), DummyAuth())
kept_cfgoff, exc_cfgoff = mgr_off._dedupe(list(rows), nexus_searched=True)
check("設定でfalseにすれば除外しない",
      len(kept_cfgoff) == 3 and exc_cfgoff == 0, f"{len(kept_cfgoff)}/{exc_cfgoff}")

# ── N8 設定ファイルのひな形 ──────────────────────────────────
print("\n[N8] config.example.json との整合")
example = json.loads((Path(dsm.__file__).resolve().parent
                      / "config.example.json").read_text(encoding="utf-8"))
check("ひな形に nexus_extra_fields がある", "nexus_extra_fields" in example)
check("ひな形の nexus_extra_fields は空（存在未確認の列を既定で要求しない）",
      example["nexus_extra_fields"] == [], str(example.get("nexus_extra_fields")))
check("ひな形の dedupe_nexus_from_sharepoint が true",
      example["dedupe_nexus_from_sharepoint"] is True)
check("ひな形の説明キーがある",
      "_comment_nexus_extra_fields" in example and "_comment_dedupe" in example)

# ── N9 画面表示 ──────────────────────────────────────────────
print("\n[N9] 画面表示")
dsm._cfg = CFG
dsm._manager = mgr
html = dsm.flask_app.test_client().get("/").get_data(as_text=True)
VERSION = DSM_FILENAME.replace("document_search_manager_", "").replace(".py", "")
check(f"版数表示が v{VERSION}", f"v{VERSION} (" in html, VERSION)
# v10 でラジオボタンからタブに変更した
check("Nexusタブがある", 'data-target="nexus"' in html)
check("除外件数を画面に出す仕組みが残っている", "excluded_nexus" in html)

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
