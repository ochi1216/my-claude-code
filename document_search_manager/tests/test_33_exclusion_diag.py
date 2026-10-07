# -*- coding: utf-8 -*-
"""除外（サイト・キーワード）の診断 — v20261007_01 で追加

document_search_manager: 「POのように同じようなファイル名が大量にあるサイトを
避けたい」（越智さんの要望、2026-10-07）ための、除外の書き方（KQLの NOT）が
実機で効くかを確かめる診断を検証する。**メイン検索には反映しない**
（本実装は診断結果を見てから、次の版）。
  - 除外語の解析（_parse_exclude_words）と KQL の組み立て（_exclusion_words_clause）
  - 診断が試す条件（基準 / A NOT path / B NOT SPSiteURL / C -path / D 語 / E 併用）
  - 「除外サイトの残り」の数え方、失敗時、入力の検査
  - /api/exclusion_diag と画面
  - メイン検索の挙動・KQLが変わっていないこと
Graph API には一切アクセスせず、スタブで検証する。
実行: python tests/test_33_exclusion_diag.py
（まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

ok, ng = 0, 0


def check(label, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


CFG = dict(dsm.DEFAULT_CFG, mcas_host="nexperia.sharepoint.com.mcas.ms")
PO = "https://nexperia.sharepoint.com/sites/PO"
LORRY = "https://nexperia.sharepoint.com/sites/P010024_Lorry"

_ORIG = {"cfg": dsm._cfg, "mgr": dsm._manager}


def raises(fn, *args):
    try:
        fn(*args)
    except ValueError as e:
        return str(e)
    return None


def hit(title, site_url, name):
    return {"resource": {"name": title + ".docx", "webUrl": site_url + "/Shared Documents/" + title + ".docx",
                         "fields": {"title": title}},
            "listItem": {"fields": {"title": title}}}


try:
    # ── T1: 除外語の解析 ──────────────────────────────────────
    print("\n[T1] _parse_exclude_words")
    p = dsm._parse_exclude_words
    check("空白区切りで複数の語に分ける", p("old draft  backup") == ["old", "draft", "backup"])
    check("引用符で囲んだ語句は1語", p('"old version" draft') == ["old version", "draft"])
    check("空・空白だけなら空の一覧", p("") == [] and p("   ") == [] and p(None) == [])
    check("同じ語は1つにまとめる", p("old Old old") == ["old", "Old"])
    check("KQLの演算子（AND OR NOT）は語として扱わず捨てる",
          p("old NOT AND or draft") == ["old", "draft"], p("old NOT AND or draft"))
    check("括弧・コロン・* ・引用符は取り除く（検索条件を壊させない）",
          p('a(b) c:d e* "f') == ["ab", "cd", "e", "f"], p('a(b) c:d e* "f'))
    check("先頭の - や + は取る（演算子として効かせない）", p("-old +draft") == ["old", "draft"])
    check("目に見えない文字（ゼロ幅スペース）は取り除く", p("ol​d") == ["old"], p("ol​d"))
    check("日本語の語も使える", p("旧版 ドラフト") == ["旧版", "ドラフト"])
    msg = raises(p, " ".join(f"w{i}" for i in range(dsm.EXCLUDE_WORDS_MAX + 1))) or ""
    check("上限を超えたら黙って切り捨てず、エラーにする",
          "最大" in msg and str(dsm.EXCLUDE_WORDS_MAX) in msg, msg)
    check("上限ちょうどは通る",
          len(p(" ".join(f"w{i}" for i in range(dsm.EXCLUDE_WORDS_MAX)))) == dsm.EXCLUDE_WORDS_MAX)

    # ── T2: KQLの組み立て ────────────────────────────────────
    print("\n[T2] _exclusion_words_clause")
    c = dsm._exclusion_words_clause
    check("タイトル限定なら NOT title:語", c(["old", "draft"], "title", True) == " NOT title:old NOT title:draft")
    check("タイトル限定オフなら NOT 語（本文も対象）", c(["old"], "title", False) == " NOT old")
    check("空白を含む語句は引用符で囲む", c(["old version"], "title", True) == ' NOT title:"old version"')
    check("語が無ければ空文字", c([], "title", True) == "")

    # ── T3: 診断が試す条件 ────────────────────────────────────
    print("\n[T3] diagnose_site_exclusion（試す条件と数え方）")
    sp = dsm.SharePointProvider(CFG, DummyAuth())
    sent = []

    def fake_call(token, query, frm=0, size=25):
        sent.append((query, size))
        has_not_path = "NOT path:" in query
        has_not_site = "NOT SPSiteURL:" in query
        has_minus = "-path:" in query
        has_word = "NOT title:" in query
        hits = []
        # 基準は PO が混ざる。A（NOT path）は効く。B は効かない（PO が残る）。
        # C は効く。D は語で減る。
        if (not has_not_path and not has_minus) or has_not_site:
            hits += [hit("PO file 1", PO, "PO"), hit("PO file 2", PO, "PO")]
        hits.append(hit("Lorry doc", LORRY, "Lorry"))
        total = 100 - (60 if (has_not_path or has_minus) else 0) - (10 if has_word else 0)
        body = {"value": [{"hitsContainers": [{"total": total, "hits": hits}]}]}
        return 200, body, ""
    sp._call_search_api = fake_call
    sp._token = lambda: "t"

    r = sp.diagnose_site_exclusion("validation", "PO", "old draft", title_only=True)
    check("成功する", r.get("ok") is True, r)
    labels = [row["label"] for row in r["rows"]]
    check("基準・A・B・C・D・E の順に試す",
          [l[:1] for l in labels] == ["基", "A", "B", "C", "D", "E"], labels)
    q = {row["label"][:1]: row["query"] for row in r["rows"]}
    check("基準は除外なし（タイトル限定の式のみ）", q["基"] == "title:validation", q["基"])
    check("A は NOT path:\"サイトURL\"（短縮名PO → /sites/PO）",
          q["A"] == f'title:validation NOT path:"{PO}"', q["A"])
    check("B は NOT SPSiteURL:（Nexusのsite方式で実績のある書き方）",
          q["B"] == f'title:validation NOT SPSiteURL:"{PO}"', q["B"])
    check("C は -path:（- 演算子）", q["C"] == f'title:validation -path:"{PO}"', q["C"])
    check("D は除外キーワード（タイトル限定）",
          q["D"] == "title:validation NOT title:old NOT title:draft", q["D"])
    check("E は A と D の併用",
          q["E"] == f'title:validation NOT path:"{PO}" NOT title:old NOT title:draft', q["E"])
    check("先頭25件を調べる（除外サイトが残っているかを数えるため）",
          all(size == 25 for _q, size in sent), sent)
    cnt = {row["label"][:1]: row["excluded_site_hits"] for row in r["rows"]}
    check("基準では除外サイトの行が2件、A・Cでは0件、Bでは2件（効いていない）と数える",
          cnt["基"] == 2 and cnt["A"] == 0 and cnt["B"] == 2 and cnt["C"] == 0, cnt)
    tot = {row["label"][:1]: row["total"] for row in r["rows"]}
    check("該当件数をそのまま並べる", tot["基"] == 100 and tot["A"] == 40, tot)
    check("先頭の数件のタイトルとサイトを返す", len(r["rows"][0]["samples"]) <= 5
          and r["rows"][0]["samples"][0]["title"], r["rows"][0]["samples"])

    # 入力の組み合わせ
    sent.clear()
    r = sp.diagnose_site_exclusion("validation", "", "old", title_only=True)
    check("除外キーワードだけなら 基準 と D だけ試す",
          [row["label"][:1] for row in r["rows"]] == ["基", "D"], [x["label"] for x in r["rows"]])
    sent.clear()
    r = sp.diagnose_site_exclusion("validation", "PO", "", title_only=True)
    check("除外サイトだけなら 基準・A・B・C",
          [row["label"][:1] for row in r["rows"]] == ["基", "A", "B", "C"])
    sent.clear()
    r = sp.diagnose_site_exclusion("validation", f"PO {LORRY}/Shared%20Documents", "", title_only=True)
    check("除外サイトは複数指定でき、URLは深くてもトップに揃える",
          r["sites"] == [PO, LORRY], r.get("sites"))
    check("複数サイトは NOT path: を連ねる",
          sent[1][0] == f'title:validation NOT path:"{PO}" NOT path:"{LORRY}"', sent[1])
    sent.clear()
    r = sp.diagnose_site_exclusion("validation", "PO", "old", title_only=False)
    check("タイトル限定オフなら、基準は語のまま・D は NOT 語（本文も対象）",
          [row["query"] for row in r["rows"] if row["label"][:1] in "基D"]
          == ["validation", "validation NOT old"], [row["query"] for row in r["rows"]])

    # 入力の検査
    check("キーワードが空ならエラー（除外だけの検索はできない）",
          sp.diagnose_site_exclusion("", "PO", "")["ok"] is False)
    check("除外サイトも除外キーワードも空ならエラー",
          sp.diagnose_site_exclusion("validation", "", "")["ok"] is False)
    sent.clear()
    r = sp.diagnose_site_exclusion("validation", 'PO" OR path:"x', "")
    check("KQLを壊す除外サイトは、Graphへ送る前に拒否する",
          r["ok"] is False and "除外サイト" in r["message"] and not sent, r)
    r = sp.diagnose_site_exclusion("validation", "https://evil.example.com/sites/x", "")
    check("社内以外のホストは拒否", r["ok"] is False and "以外" in r["message"], r)
    r = sp.diagnose_site_exclusion("validation", "a b c d e f", "")
    check("除外サイトは最大5つ", r["ok"] is False and "5" in r["message"], r)
    r = sp.diagnose_site_exclusion("validation", "PO", " ".join(f"w{i}" for i in range(11)))
    check("除外語が多すぎればエラー", r["ok"] is False and "最大" in r["message"], r)

    # 失敗の扱い
    def fail_on_a(token, query, frm=0, size=25):
        if "NOT path:" in query:
            return 400, None, "Bad request: invalid KQL"
        return fake_call(token, query, frm, size)
    sp._call_search_api = fail_on_a
    r = sp.diagnose_site_exclusion("validation", "PO", "")
    rows = {row["label"][:1]: row for row in r["rows"]}
    check("ある条件が HTTP 400 でも、診断全体は続ける（他の条件の結果も返す）",
          r["ok"] is True and rows["A"]["ok"] is False and "HTTP 400" in rows["A"]["message"]
          and rows["B"]["ok"] is True, {k: v.get("ok") for k, v in rows.items()})
    check("失敗した条件も、組み立てたKQLを残す（原因調査のため）", "NOT path:" in rows["A"]["query"])

    # mcas 経由のURLでも除外サイトを数えられる
    cfg_m = dict(CFG, rewrite_host_to_mcas=True)
    sp_m = dsm.SharePointProvider(cfg_m, DummyAuth())
    sp_m._token = lambda: "t"
    sp_m._call_search_api = fake_call
    r = sp_m.diagnose_site_exclusion("validation", "PO", "")
    check(".mcas.ms 経由の表示用URLでも、除外サイトの残りを数えられる",
          r["rows"][0]["excluded_site_hits"] == 2, r["rows"][0])

    # 診断は provider の設定を残さない
    sp.title_only, sp.prefix_search = False, True
    sp._call_search_api = fake_call
    sp.diagnose_site_exclusion("validation", "PO", "", title_only=True)
    check("診断のあと、title_only・prefix_search は元に戻る",
          sp.title_only is False and sp.prefix_search is True, (sp.title_only, sp.prefix_search))
    sp.prefix_search = False
    check("診断のあと、メイン検索のKQLは変わらない（除外は付かない）",
          sp._query_string("validation") == "validation"
          and "NOT" not in sp._query_string("validation"))
    nx = dsm.NexusProvider(CFG, DummyAuth())
    check("Nexusのクエリにも除外は付かない", "NOT" not in nx._query_string("validation"))

    # ── T4: /api/exclusion_diag ──────────────────────────────
    print("\n[T4] /api/exclusion_diag")
    dsm._cfg = CFG
    mgr = dsm.SearchManager(CFG, DummyAuth())
    sp2 = mgr.providers[dsm.TARGET_SHAREPOINT]
    sp2._token = lambda: "t"
    sp2._call_search_api = fake_call
    dsm._manager = mgr
    client = dsm.flask_app.test_client()
    body = client.post("/api/exclusion_diag", json={"keyword": "validation", "sites": "PO",
                                                    "words": "old", "title_only": True}).get_json()
    check("診断の結果を返す", body.get("ok") and len(body["rows"]) == 6, body.get("message"))
    body = client.post("/api/exclusion_diag", json={"keyword": "", "sites": "PO"}).get_json()
    check("入力が足りなければ ok=False と理由", body.get("ok") is False and body.get("message"), body)
    mgr.providers.pop(dsm.TARGET_SHAREPOINT)
    resp = client.post("/api/exclusion_diag", json={"keyword": "x", "sites": "PO"})
    check("SharePointプロバイダが無ければ 500", resp.status_code == 500)

    # ── T5: 画面 ──────────────────────────────────────────────
    print("\n[T5] 画面（除外診断の入力欄とボタン）")
    html = dsm.INDEX_HTML
    check("除外診断の行は既定で隠れ、SharePointタブでだけ出す",
          'id="exclusionDiagRow" hidden' in html
          and 'getElementById("exclusionDiagRow").hidden = (target !== "sharepoint")' in html)
    check("入力欄（除外サイト・除外キーワード）とボタンがある",
          all(x in html for x in ('id="exclSites"', 'id="exclWords"', 'id="btnExclusionDiag"')))
    check("診断はキーワード欄の語とタイトル限定の指定を使う",
          'getElementById("keyword").value.trim()' in html
          and 'title_only: document.getElementById("titleOnly").checked' in html
          and "/api/exclusion_diag" in html)
    check("診断中は他の操作と同じく、ボタンを無効にする",
          'getElementById("btnExclusionDiag").disabled = busy' in html)
    check("診断は結果の表を書き換えない（applySearchResponse を呼ばない）",
          "applySearchResponse" not in html[html.index('getElementById("btnExclusionDiag").addEventListener'):
                                            html.index('getElementById("btnExploreDiag").addEventListener')])
    check("診断のログに、組み立てたKQLと「除外サイトの行」の件数を出す",
          '"      KQL: " + row.query' in html and "除外サイトの行" in html)
    check("除外の入力は保存しない（Q4: 覚えない）",
          'exclSites' not in html[html.index("function saveState()"):html.index("// ── ヘッダー描画")]
          and 'exclWords' not in html[html.index("function saveState()"):html.index("// ── ヘッダー描画")])
    check("検索の要求（/api/search）には除外を載せない（本実装は次の版）",
          'exclude' not in html[html.index('fetch("/api/search"'):html.index('fetch("/api/search"') + 600])

finally:
    dsm._cfg, dsm._manager = _ORIG["cfg"], _ORIG["mgr"]


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(1 if ng else 0)
