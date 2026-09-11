#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BBT_lecture_script_getter_20260817_01.py の Geminiプロキシ化検証テスト

共通ガイド `HANDOVER_gemini_proxy_common.md` 第8節の「偽モジュール注入による
テスト」に従い、偽の gemini_client を sys.modules へ**対象モジュールのロード前に**
注入して、generate_advanced() に渡る payload とレスポンス契約を検証する。

実行:
    python test_gemini_proxy_20260817_01.py

注意: 実機（会社PC）の共通モジュールにも自宅PCプロキシにも到達できないため、
      「プロキシ経由で実際に応答が返るところ」は本テストでは検証できない。
"""

import importlib.util
import json
import os
import sys
import types as pytypes

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "BBT_lecture_script_getter_20260817_01.py")

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f"  -- {detail}" if detail and not cond else ""))


# ==========================================================================
# 依存モジュールのスタブ（selenium / tkinter はこの環境に無いため）
# ==========================================================================
def _stub(name, **attrs):
    m = pytypes.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Any:
    """属性アクセス・呼び出し・継承の全てを受け流すダミー。"""
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k): return _Any()
    def __setattr__(self, n, v): object.__setattr__(self, n, v)


def _install_stubs():
    sel = _stub("selenium")
    sel.webdriver = _stub("selenium.webdriver", Chrome=_Any, ChromeOptions=_Any, Remote=_Any)
    _stub("selenium.webdriver.chrome")
    sel.webdriver.chrome = sys.modules["selenium.webdriver.chrome"]
    sys.modules["selenium.webdriver.chrome"].options = _stub("selenium.webdriver.chrome.options", Options=_Any)
    sys.modules["selenium.webdriver.chrome"].service = _stub("selenium.webdriver.chrome.service", Service=_Any)
    _stub("selenium.webdriver.common")
    sel.webdriver.common = sys.modules["selenium.webdriver.common"]
    sys.modules["selenium.webdriver.common"].by = _stub("selenium.webdriver.common.by", By=_Any())
    sys.modules["selenium.webdriver.common"].keys = _stub("selenium.webdriver.common.keys", Keys=_Any())
    _stub("selenium.webdriver.support")
    sel.webdriver.support = sys.modules["selenium.webdriver.support"]
    sys.modules["selenium.webdriver.support"].ui = _stub("selenium.webdriver.support.ui", WebDriverWait=_Any)
    sys.modules["selenium.webdriver.support"].expected_conditions = _stub(
        "selenium.webdriver.support.expected_conditions")
    sel.common = _stub("selenium.common")
    sys.modules["selenium.common"].exceptions = _stub(
        "selenium.common.exceptions",
        TimeoutException=type("TimeoutException", (Exception,), {}),
        NoSuchElementException=type("NoSuchElementException", (Exception,), {}),
        WebDriverException=type("WebDriverException", (Exception,), {}),
    )

    tk = _stub("tkinter", Tk=_Any, Toplevel=_Any, Frame=_Any, Label=_Any, Button=_Any,
               Entry=_Any, StringVar=_Any, BooleanVar=_Any, IntVar=_Any, Canvas=_Any,
               Scrollbar=_Any, Listbox=_Any, Checkbutton=_Any, END="end", W="w", E="e",
               N="n", S="s", BOTH="both", LEFT="left", RIGHT="right", TOP="top",
               BOTTOM="bottom", X="x", Y="y")
    tk.filedialog = _stub("tkinter.filedialog")
    tk.messagebox = _stub("tkinter.messagebox", showinfo=lambda *a, **k: None,
                          showwarning=lambda *a, **k: None, showerror=lambda *a, **k: None)
    tk.ttk = _stub("tkinter.ttk", Treeview=_Any, Frame=_Any, Label=_Any, Button=_Any,
                   Combobox=_Any, Style=_Any, Progressbar=_Any, Entry=_Any, Checkbutton=_Any)
    tk.scrolledtext = _stub("tkinter.scrolledtext", ScrolledText=_Any)


# ==========================================================================
# 偽 gemini_client
# ==========================================================================
CAPTURED = {"calls": []}
FAKE_RESPONSE = {
    "candidates": [{"content": {"parts": [{"text": '{"title": "テスト要約"}'}]}}],
    "usageMetadata": {"promptTokenCount": 123, "candidatesTokenCount": 45, "totalTokenCount": 168},
}


def _install_fake_gemini_client(response=None):
    holder = {"response": response if response is not None else FAKE_RESPONSE}

    def _fake(payload, model=None, verbose=True):
        CAPTURED["calls"].append({"payload": payload, "model": model})
        resp = holder["response"]
        if isinstance(resp, Exception):
            raise resp
        return resp

    fake = pytypes.ModuleType("gemini_client")
    fake.generate_advanced = _fake
    sys.modules["gemini_client"] = fake      # ← 対象ファイルのロードより前に注入する
    return holder


def _load_target(module_name="bbt_target"):
    spec = importlib.util.spec_from_file_location(module_name, TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# テスト本体
# ==========================================================================
def main():
    _install_stubs()
    holder = _install_fake_gemini_client()
    os.environ["GEMINI_API_KEY"] = "dummy-key-for-test"
    os.environ.pop("GEMINI_PROXY_URL", None)

    print("=" * 74)
    print(" BBT レクチャーオーガナイザー Geminiプロキシ化 検証テスト")
    print("=" * 74)

    # ---------- A. モジュールのロードとシムの存在 ----------
    print("\n[A] モジュールのロードとシムの構成")
    mod = _load_target()
    check("A-01 対象モジュールがロードできる", mod is not None)
    check("A-02 旧SDK google.generativeai を import していない",
          "google.generativeai" not in sys.modules)
    check("A-03 genai シムが定義されている", hasattr(mod, "genai"))
    check("A-04 genai.configure が存在する", callable(getattr(mod.genai, "configure", None)))
    check("A-05 genai.GenerativeModel が存在する", hasattr(mod.genai, "GenerativeModel"))
    check("A-06 genai.configure(api_key=...) が例外を出さない",
          mod.genai.configure(api_key="x") is None)
    check("A-07 gemini_credentials_available が定義されている",
          callable(getattr(mod, "gemini_credentials_available", None)))

    # ---------- B. 共通モジュールの探索パス ----------
    print("\n[B] 共通モジュールの探索パス（共通ガイド 6-(1)）")
    cands = mod._COMMON_DIR_CANDIDATES
    check("B-01 探索候補が2つ以上ある", len(cands) >= 2, str(cands))
    check("B-02 ../common が候補に含まれる",
          any(os.path.basename(c) == "common" and
              os.path.normpath(os.path.join(HERE, "..", "common")) == c for c in cands), str(cands))
    check("B-03 ../../common が候補に含まれる",
          os.path.normpath(os.path.join(HERE, "..", "..", "common")) in cands, str(cands))
    check("B-04 候補が全て sys.path に入っている", all(c in sys.path for c in cands))

    # ---------- C. payload の形（本番と同じ呼び出し） ----------
    print("\n[C] generate_advanced に渡る payload（実際の add_prompt_text 経由）")
    CAPTURED["calls"].clear()
    autom = mod.GeminiAutomator(headless_mode=False)
    check("C-01 GeminiAutomator が生成できる", autom is not None)
    check("C-02 モデル名が gemini-2.5-flash で束縛されている",
          autom.model.model_name == "gemini-2.5-flash", repr(autom.model.model_name))

    autom.text_content = "これはテスト用のトランスクリプト本文です。"
    ok = autom.add_prompt_text(autom.prompt_template_general, file_path=None)
    check("C-03 add_prompt_text が True を返す", ok is True)
    check("C-04 generate_advanced が1回だけ呼ばれた", len(CAPTURED["calls"]) == 1,
          str(len(CAPTURED["calls"])))

    call = CAPTURED["calls"][0]
    payload = call["payload"]
    check("C-05 model が明示的に渡っている（共通ガイド 6-(5)）",
          call["model"] == "gemini-2.5-flash", repr(call["model"]))
    check("C-06 payload に contents がある", "contents" in payload)
    check("C-07 contents がリスト", isinstance(payload["contents"], list))
    check("C-08 contents[0] に parts がある", "parts" in payload["contents"][0])
    parts = payload["contents"][0]["parts"]
    check("C-09 parts が1要素", len(parts) == 1, str(len(parts)))
    check("C-10 parts[0].text が『文字列』（リストが入れ子になっていない）",
          isinstance(parts[0]["text"], str), type(parts[0]["text"]).__name__)
    check("C-11 プロンプト本文が payload に載っている",
          "これはテスト用のトランスクリプト本文です。" in parts[0]["text"])
    check("C-12 アジェンダのプレースホルダが残っていない",
          "{agenda}" not in parts[0]["text"])

    # ---------- D. generationConfig の camelCase 変換 ----------
    print("\n[D] generationConfig（旧SDKの snake_case dict → REST の camelCase）")
    gc = payload.get("generationConfig", {})
    check("D-01 generationConfig が payload に載っている", bool(gc), str(gc))
    check("D-02 responseMimeType が camelCase で載っている",
          gc.get("responseMimeType") == "application/json", str(gc))
    check("D-03 snake_case のキーが残っていない",
          "response_mime_type" not in gc, str(gc))
    check("D-04 payload 全体が json.dumps 可能",
          json.dumps(payload) is not None)

    # ---------- E. レスポンス契約（response.text / usage_metadata） ----------
    print("\n[E] レスポンス契約")
    check("E-01 response.text が summary_result に入っている",
          autom.summary_result == '{"title": "テスト要約"}', repr(autom.summary_result))
    check("E-02 usage_metadata からトークンが読めコストが計上された",
          autom.total_cost_usd > 0, f"usd={autom.total_cost_usd}")
    expected = (123 / 1_000_000 * 0.30) + (45 / 1_000_000 * 2.50)
    check("E-03 コスト計算値が期待どおり（prompt=123 / candidates=45）",
          abs(autom.total_cost_usd - expected) < 1e-12,
          f"{autom.total_cost_usd} != {expected}")
    check("E-04 円換算が 160円/$ で計上されている",
          abs(autom.total_cost_jpy - expected * 160) < 1e-9)
    check("E-05 extract_summary_from_page が JSON をパースできる",
          autom.extract_summary_from_page().get("title") == "テスト要約")

    # ---------- F. シム単体（境界ケース） ----------
    print("\n[F] シム単体の境界ケース")
    m = mod.genai.GenerativeModel("gemini-2.5-pro")
    CAPTURED["calls"].clear()
    m.generate_content(["A", "B"])
    p = CAPTURED["calls"][0]["payload"]
    check("F-01 contents がリストでも parts が展開される（共通ガイド 6-(2)）",
          p["contents"][0]["parts"] == [{"text": "A"}, {"text": "B"}], str(p))
    check("F-02 別モデル名がそのまま渡る",
          CAPTURED["calls"][0]["model"] == "gemini-2.5-pro")

    CAPTURED["calls"].clear()
    mod.genai.GenerativeModel("models/gemini-2.5-flash").generate_content("x")
    check("F-03 'models/' 接頭辞が除去される",
          CAPTURED["calls"][0]["model"] == "gemini-2.5-flash",
          repr(CAPTURED["calls"][0]["model"]))

    CAPTURED["calls"].clear()
    m.generate_content("x", generation_config={
        "response_mime_type": "application/json",
        "temperature": 0.2,
        "max_output_tokens": 8192,
        "top_p": 0.9,
        "response_schema": {"type": "object"},
        "stop_sequences": ["END"],
    })
    gc2 = CAPTURED["calls"][0]["payload"]["generationConfig"]
    check("F-04 temperature がそのまま載る", gc2.get("temperature") == 0.2, str(gc2))
    check("F-05 max_output_tokens → maxOutputTokens", gc2.get("maxOutputTokens") == 8192, str(gc2))
    check("F-06 top_p → topP", gc2.get("topP") == 0.9, str(gc2))
    check("F-07 response_schema → responseSchema", gc2.get("responseSchema") == {"type": "object"}, str(gc2))
    check("F-08 stop_sequences → stopSequences", gc2.get("stopSequences") == ["END"], str(gc2))
    check("F-09 変換後も json.dumps 可能", json.dumps(CAPTURED["calls"][0]["payload"]) is not None)

    # 素のdictでなくオブジェクトで渡された場合
    class _Cfg:
        response_mime_type = "application/json"
        temperature = 0.5
    CAPTURED["calls"].clear()
    m.generate_content("x", generation_config=_Cfg())
    gc3 = CAPTURED["calls"][0]["payload"]["generationConfig"]
    check("F-10 オブジェクト形式の generation_config も変換できる",
          gc3.get("responseMimeType") == "application/json" and gc3.get("temperature") == 0.5, str(gc3))

    # response_schema が pydantic ライクなオブジェクトの場合
    class _Schema:
        def model_dump(self, **k): return {"type": "object", "from": "model_dump"}
    CAPTURED["calls"].clear()
    m.generate_content("x", generation_config={"response_schema": _Schema()})
    check("F-11 pydantic ライクな response_schema が dict 化される（共通ガイド 6-(7)）",
          CAPTURED["calls"][0]["payload"]["generationConfig"]["responseSchema"]["from"] == "model_dump")

    # generation_config なし
    CAPTURED["calls"].clear()
    m.generate_content("x")
    check("F-12 generation_config 未指定なら generationConfig を載せない",
          "generationConfig" not in CAPTURED["calls"][0]["payload"])

    # ---------- G. 壊れた/空のレスポンス ----------
    print("\n[G] 壊れた・空のレスポンス（例外を投げず失敗として扱う）")
    for label, resp in (("空dict", {}),
                        ("candidates空", {"candidates": []}),
                        ("parts欠落", {"candidates": [{"content": {}}]}),
                        ("None", None),
                        ("文字列", "unexpected")):
        holder["response"] = resp
        try:
            r = m.generate_content("x")
            check(f"G-{label} 例外を投げず text='' になる", r.text == "", repr(r.text))
            check(f"G-{label} usage_metadata が 0 で読める",
                  r.usage_metadata.prompt_token_count == 0)
        except Exception as e:
            check(f"G-{label} 例外を投げず text='' になる", False, f"{type(e).__name__}: {e}")

    holder["response"] = {"candidates": [{"content": {"parts": [{"text": ""}]}}]}
    CAPTURED["calls"].clear()
    autom2 = mod.GeminiAutomator()
    autom2.text_content = "t"
    check("G-06 空テキストなら add_prompt_text が False を返す",
          autom2.add_prompt_text(autom2.prompt_template_general) is False)

    holder["response"] = RuntimeError("プロキシ側エラー: boom")
    autom3 = mod.GeminiAutomator()
    autom3.text_content = "t"
    check("G-07 共通モジュールが例外を投げても add_prompt_text は False を返す",
          autom3.add_prompt_text(autom3.prompt_template_general) is False)
    holder["response"] = FAKE_RESPONSE

    # ---------- H. 認証情報の判定（共通ガイド 6-(3)・最重要） ----------
    print("\n[H] 認証情報ガード（共通ガイド 6-(3)）")
    saved = (os.environ.get("GEMINI_API_KEY"), os.environ.get("GEMINI_PROXY_URL"))

    def _setenv(key, proxy):
        for k, v in (("GEMINI_API_KEY", key), ("GEMINI_PROXY_URL", proxy)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    _setenv("k", None)
    check("H-01 APIキーのみ → 通す", mod.gemini_credentials_available() is True)
    _setenv(None, "https://example.ngrok-free.dev")
    check("H-02 プロキシURLのみ → 通す（プロキシ専用構成）", mod.gemini_credentials_available() is True)
    check("H-03 プロキシURLのみでも GeminiAutomator が生成できる",
          mod.GeminiAutomator() is not None)
    _setenv("k", "https://example.ngrok-free.dev")
    check("H-04 両方あり → 通す", mod.gemini_credentials_available() is True)
    _setenv(None, None)
    check("H-05 両方なし → 弾く", mod.gemini_credentials_available() is False)
    try:
        mod.GeminiAutomator()
        check("H-06 両方なしなら ValueError を投げる", False, "例外が出なかった")
    except ValueError as e:
        check("H-06 両方なしなら ValueError を投げる", True)
        check("H-07 エラー文が GEMINI_PROXY_URL を案内している", "GEMINI_PROXY_URL" in str(e), str(e))
    _setenv(*saved)

    # ---------- I. 共通モジュール未配置時のエラー（共通ガイド 6-(4)） ----------
    print("\n[I] 共通モジュール未配置時の挙動（共通ガイド 6-(4)）")
    sys.modules.pop("gemini_client", None)
    for k in list(sys.modules):
        if k.startswith("bbt_target_noc"):
            sys.modules.pop(k)
    saved_path = list(sys.path)
    sys.path[:] = [p for p in sys.path if "common" not in os.path.basename(p)]
    os.environ["GEMINI_COMMON_DIR"] = os.path.join(HERE, "__does_not_exist__")
    try:
        mod2 = _load_target("bbt_target_noc")
        check("I-01 共通モジュールが無くてもツールはロードできる（起動は止まらない）", True)
        check("I-02 import エラーが記録されている", mod2._GEMINI_CLIENT_IMPORT_ERROR is not None)
        try:
            mod2.genai.GenerativeModel("gemini-2.5-flash").generate_content("x")
            check("I-03 AI呼び出し時に RuntimeError を投げる", False, "例外が出なかった")
        except RuntimeError as e:
            msg = str(e)
            check("I-03 AI呼び出し時に RuntimeError を投げる", True)
            check("I-04 試した全候補パスがメッセージに出る",
                  all(c in msg for c in mod2._COMMON_DIR_CANDIDATES), msg)
            check("I-05 元のエラーがメッセージに出る", "元のエラー" in msg, msg)
            check("I-06 GEMINI_COMMON_DIR の案内がある", "GEMINI_COMMON_DIR" in msg, msg)
    except Exception as e:
        check("I-01 共通モジュールが無くてもツールはロードできる（起動は止まらない）",
              False, f"{type(e).__name__}: {e}")
    finally:
        os.environ.pop("GEMINI_COMMON_DIR", None)
        sys.path[:] = saved_path

    # ---------- J. パス解決（実物の gemini_client.py を置いて確認・共通ガイド第8節②） ----------
    print("\n[J] パス解決（実物の gemini_client.py を実際の配置先に置いて確認）")
    import shutil
    import tempfile
    # 実物の gemini_client.py を探す。会社PC（PythonScripts\bbt\）では ..\common に実在する。
    # 無い環境では gemini-common-tools から取得したコピーを
    # _real_gemini_client_for_test.py として本フォルダに置けば J 節が走る。
    real_client = next(
        (p for p in (os.path.normpath(os.path.join(HERE, "..", "common", "gemini_client.py")),
                     os.path.normpath(os.path.join(HERE, "..", "..", "common", "gemini_client.py")),
                     os.path.join(HERE, "_real_gemini_client_for_test.py"))
         if os.path.isfile(p)), None)
    if real_client is None:
        print("  [SKIP] 実物の gemini_client.py が見つからないため J 節をスキップします")
        print("         （..\\common に配置するか、_real_gemini_client_for_test.py を置いてください）")
    else:
        print(f"  使用する実物: {real_client}")
        tmp = tempfile.mkdtemp()
        try:
            for label, depth in (("1階層（PythonScripts\\bbt\\）", 1), ("2階層", 2)):
                root = os.path.join(tmp, f"PythonScripts_{depth}")
                common = os.path.join(root, "common")
                os.makedirs(common, exist_ok=True)
                shutil.copy(real_client, os.path.join(common, "gemini_client.py"))
                tooldir = os.path.join(root, *(["sub"] * (depth - 1)), "bbt")
                os.makedirs(tooldir, exist_ok=True)
                shutil.copy(TARGET, os.path.join(tooldir, os.path.basename(TARGET)))
                sys.modules.pop("gemini_client", None)
                for k in list(sys.modules):
                    if k.startswith("bbt_path_"):
                        sys.modules.pop(k)
                spec = importlib.util.spec_from_file_location(
                    f"bbt_path_{depth}", os.path.join(tooldir, os.path.basename(TARGET)))
                mp = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mp
                spec.loader.exec_module(mp)
                check(f"J-{depth} {label} で実物の gemini_client.py を import できる",
                      mp._GEMINI_CLIENT_IMPORT_ERROR is None and mp._generate_advanced is not None,
                      str(mp._GEMINI_CLIENT_IMPORT_ERROR))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- K. 既存機能の回帰確認（共通ガイド 第8節①） ----------
    print("\n[K] 既存機能の回帰確認（シム経由でHTMLレポートまで通す）")
    import tempfile as _tf
    holder["response"] = {
        "candidates": [{"content": {"parts": [{"text": json.dumps({
            "title": "大前研一ライブ #1234（2026年08月17日配信）",
            "keywords": "地政学, 半導体, 円安",
            "gist": "今週の要旨のテスト。",
            "conclusion": "今週の結論のテスト。",
            "main_points": [{"category": "国際情勢・地政学",
                             "items": [{"sub_topic": "中東情勢", "detail": "詳細テスト"}]}],
            "actions": ["1. 〇〇を注視する", "2. 〇〇を再点検する", "3. 〇〇に備える"],
        }, ensure_ascii=False)}]}}],
        "usageMetadata": {"promptTokenCount": 20000, "candidatesTokenCount": 3000},
    }
    CAPTURED["calls"].clear()
    a4 = mod.GeminiAutomator()
    a4.text_content = "回帰確認用トランスクリプト"
    ok4 = a4.add_prompt_text(a4.prompt_template_live)
    summary_dict = a4.extract_summary_from_page()
    check("K-01 大前研一ライブ用プロンプトで要約が成立する", ok4 is True)
    check("K-02 JSONの全キーが取り出せる",
          set(["title", "keywords", "gist", "conclusion", "main_points", "actions"])
          <= set(summary_dict), str(list(summary_dict)))
    check("K-03 トークン集計がシム経由で機能している（usage_metadata）",
          a4.total_cost_usd > 0, f"usd={a4.total_cost_usd}")

    outdir = _tf.mkdtemp()
    try:
        gen = mod.HTMLGenerator([outdir])
        summaries = [{"title": "大前研一ライブ #1234", "file": "x.txt", "url": "https://example.com",
                      "thumbnail_url": "", "lecturer_name": "大前 研一",
                      "release_date": "2026/08/17", "duration": "60分",
                      "summary": summary_dict, "success": True, "error": None}]
        path = gen.generate_html(summaries, a4.total_cost_usd, a4.total_cost_jpy)
        check("K-04 HTMLレポートが生成される", bool(path) and os.path.isfile(str(path)), str(path))
        html = open(str(path), encoding="utf-8").read()
        check("K-05 要約カードに講義タイトルが出ている", "大前研一ライブ #1234" in html)
        check("K-06 講師名・配信日・収録時間が出ている",
              "大前 研一" in html and "2026/08/17" in html and "60分" in html)
        check("K-07 コスト表示にシム経由のトークンが反映されている",
              f"${a4.total_cost_usd:.4f}" in html and a4.total_cost_usd > 0)
        check("K-08 ネクストアクションが出ている", "〇〇を注視する" in html)
    except Exception as e:
        check("K-04 HTMLレポートが生成される", False, f"{type(e).__name__}: {e}")
    finally:
        import shutil as _sh
        _sh.rmtree(outdir, ignore_errors=True)
    holder["response"] = FAKE_RESPONSE

    # ---------- 集計 ----------
    print("\n" + "=" * 74)
    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f" 結果: {passed} / {total} 項目 合格")
    if passed != total:
        print("\n 失敗した項目:")
        for name, ok, detail in _results:
            if not ok:
                print(f"   - {name}  {detail}")
    print("=" * 74)
    print("\n【本テストで検証できないこと】")
    print("  Claude Code の実行環境(Linuxコンテナ)からは、会社PCの共通モジュールにも")
    print("  自宅PCのプロキシにも到達できない。したがって『プロキシ経由で実際に")
    print("  Geminiの応答が返るところ』は原理的に検証できない。実機確認が必要。")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
