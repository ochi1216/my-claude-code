"""pdf_translator_20260821_01.py の Gemini プロキシ移行部分の検証テスト。

Windows / tkinter / 実際の Gemini API に依存せず検証するため、
偽の `gemini_client` を **対象モジュールのロード前に** sys.modules へ注入し、
`generate_advanced()` に渡る payload を捕捉して検証する
(HANDOVER_pdf_translator_gemini_proxy.md 第8章の手法)。

PyMuPDF (fitz) は Linux コンテナにも入るため**本物を使う**。合成PDFを実際に生成して
翻訳文の書き戻しまでエンドツーエンドで検証し、罫線の座標が翻訳前後で完全一致すること
(＝表・グラフを壊していないこと)を確認する。tkinter だけスタブ化する。

実行方法:
    pip install PyMuPDF
    python3 tests/test_pdf_translator_20260821_01.py
"""

import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import types as pytypes

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "pdf_translator_20260821_01.py")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  ({detail})" if detail else ""))


# ------------------------------------------------------------
# GUI 依存のスタブ (tkinter は apt が必要でコンテナに入らない)
# ------------------------------------------------------------
def _install_env_stubs():
    class _Anything:
        """属性アクセス・呼び出しを何でも受け付けるダミー。"""
        def __init__(self, *a, **k):
            pass

        def __call__(self, *a, **k):
            return _Anything()

        def __getattr__(self, _name):
            return _Anything()

    tk = pytypes.ModuleType("tkinter")
    for attr in ("Tk", "Toplevel", "Frame", "Label", "Button", "Entry", "Checkbutton",
                 "OptionMenu", "StringVar", "BooleanVar", "LEFT", "END"):
        setattr(tk, attr, _Anything())

    filedialog = pytypes.ModuleType("tkinter.filedialog")
    filedialog.askopenfilename = lambda *a, **k: ""

    # messagebox は「呼ばれたこと」を記録して、ガードの検証に使う
    messagebox = pytypes.ModuleType("tkinter.messagebox")
    messagebox.CALLS = []

    def _record(kind):
        def _fn(title="", message="", *a, **k):
            messagebox.CALLS.append((kind, title, message))
            return True
        return _fn

    messagebox.showerror = _record("error")
    messagebox.showwarning = _record("warning")
    messagebox.showinfo = _record("info")

    tk.filedialog = filedialog
    tk.messagebox = messagebox
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox
    return messagebox


MESSAGEBOX = _install_env_stubs()

import fitz  # noqa: E402  (スタブ注入後に読み込む)


# ------------------------------------------------------------
# 偽 gemini_client
# ------------------------------------------------------------
CAPTURED = {"calls": []}
RESPONSE = {"value": None}


def _numbered_reply(payload):
    """プロンプト中の [n] の数だけ番号付きの訳文を返す。"""
    text = payload["contents"][0]["parts"][0]["text"]
    n = text.count("[")
    lines = "\n".join(f"[{i}] 訳文{i}" for i in range(1, n + 1))
    return {"candidates": [{"content": {"parts": [{"text": lines}]}}],
            "usageMetadata": {"promptTokenCount": 123, "candidatesTokenCount": 45}}


def _fake_generate_advanced(payload, model=None, **kwargs):
    CAPTURED["calls"].append({"payload": payload, "model": model})
    if RESPONSE["value"] is not None:
        value = RESPONSE["value"]
        if callable(value):
            return value(payload)
        return value
    return _numbered_reply(payload)


def _load_target(module_name, inject_fake=True, target=TARGET):
    """対象ファイルをロードする。inject_fake=False なら共通モジュール未配置を再現。"""
    sys.modules.pop("gemini_client", None)
    if inject_fake:
        fake = pytypes.ModuleType("gemini_client")
        fake.generate_advanced = _fake_generate_advanced
        sys.modules["gemini_client"] = fake

    spec = importlib.util.spec_from_file_location(module_name, target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _silence_sleep(mod):
    """リトライ待ち(3秒)・成功後の待ち(1.5秒)でテストが遅くならないようにする。
    対象モジュールから見える time だけを差し替え、本物の time は壊さない。"""
    stub = pytypes.ModuleType("time")
    stub.sleep = lambda _s: None
    stub.time = __import__("time").time
    mod.time = stub


# ============================================================
# 検証
# ============================================================
mod = _load_target("target_main")
_silence_sleep(mod)

check("共通モジュールを読み込めた場合 HAS_GEMINI が True", mod.HAS_GEMINI is True)
check("旧SDK(google.generativeai)への依存が無い",
      not hasattr(mod, "genai") and "google.generativeai" not in sys.modules)
check("旧SDK由来のグローバル gemini_model が残っていない",
      not hasattr(mod, "gemini_model"))



def _calls_named(path, name):
    """ソース中に「実際に呼び出している」箇所があるかをASTで調べる
    (コメント・docstringでの言及は除外する)。"""
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                return True
            if isinstance(fn, ast.Name) and fn.id == name:
                return True
    return False


check("自動モデル検出(list_models)の呼び出しが残っていない",
      not _calls_named(TARGET, "list_models"),
      "起動時のネットワークアクセスが無いこと")
check("genai.configure の呼び出しが残っていない", not _calls_named(TARGET, "configure"))

# --- init_gemini がネットワークアクセスを行わないこと -------------------
# 旧版は genai.list_models() を呼んでいたため、遮断下では必ず失敗して起動できなかった。
# ソケット生成そのものを禁止した状態で init_gemini() が成功することで、
# ネットワークアクセスが無くなったことを証明する。
os.environ["GEMINI_PROXY_URL"] = "https://example.invalid"
_real_socket = socket.socket


def _blocked_socket(*a, **k):
    raise AssertionError("init_gemini がネットワークアクセスを行った")


socket.socket = _blocked_socket
try:
    ok_init = mod.init_gemini(None)
except AssertionError as e:
    ok_init, _detail = False, str(e)
finally:
    socket.socket = _real_socket

check("init_gemini がネットワークアクセスなしで成功する", ok_init is True)
check("init_gemini がシムのクライアントを生成する",
      isinstance(mod.gemini_client, mod._CommonGeminiClient))
check("使用モデルが gemini-2.5-flash", mod.GEMINI_MODEL_NAME == "gemini-2.5-flash",
      f"model={mod.GEMINI_MODEL_NAME}")

# --- 通常の翻訳呼び出し -------------------------------------------------
CAPTURED["calls"].clear()
texts = ["Hello world", "This is a table cell"]
out, is_error = mod.translate_batch_gemini(texts, "Japanese", 0, None)

check("generate_advanced が1回呼ばれた", len(CAPTURED["calls"]) == 1,
      f"calls={len(CAPTURED['calls'])}")
check("成功時はエラーフラグが False", is_error is False)
check("response.text の解析結果が返る", out == ["訳文1", "訳文2"], f"out={out}")

call = CAPTURED["calls"][0]
payload = call["payload"]

check("model が明示的に gemini-2.5-flash で渡る", call["model"] == "gemini-2.5-flash",
      f"model={call['model']!r}")
check("payload の contents が REST 形式",
      isinstance(payload.get("contents"), list)
      and isinstance(payload["contents"][0]["parts"][0]["text"], str))
check("payload に翻訳対象テキストが [番号] 付きで含まれる",
      "[1] Hello world" in payload["contents"][0]["parts"][0]["text"]
      and "[2] This is a table cell" in payload["contents"][0]["parts"][0]["text"])
check("翻訳先言語がプロンプトに反映される",
      "Japanese" in payload["contents"][0]["parts"][0]["text"])
check("generationConfig.temperature が 0.1 で camelCase で載る",
      payload.get("generationConfig", {}).get("temperature") == 0.1,
      f"generationConfig={payload.get('generationConfig')}")
check("payload が json.dumps 可能", bool(json.dumps(payload)))

# --- safetySettings (載せ忘れると応答が空になりうる) --------------------
safety = payload.get("safetySettings")
check("safetySettings が payload に載る", isinstance(safety, list), f"safetySettings={safety}")
check("safetySettings が4カテゴリ分そのまま載る",
      isinstance(safety, list) and len(safety) == 4,
      f"len={len(safety) if isinstance(safety, list) else 'N/A'}")
check("safetySettings の全カテゴリが BLOCK_NONE",
      isinstance(safety, list)
      and all(s.get("threshold") == "BLOCK_NONE" for s in safety))
check("safetySettings のカテゴリ名が REST 形式(HARM_CATEGORY_*)",
      isinstance(safety, list)
      and {s.get("category") for s in safety} == {
          "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
          "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"},
      f"categories={[s.get('category') for s in safety] if isinstance(safety, list) else safety}")

# --- レスポンス互換契約 (.parts / .text / usage_metadata) ---------------
resp = mod._CommonGeminiResponse(
    {"candidates": [{"content": {"parts": [{"text": "hello"}]}}],
     "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}})
check("response.text が読める", resp.text == "hello")
check("response.parts が読める(空応答判定に必須)",
      resp.parts == [{"text": "hello"}], f"parts={resp.parts}")
check("response.usage_metadata が読める",
      resp.usage_metadata.prompt_token_count == 7
      and resp.usage_metadata.candidates_token_count == 3)

for label, raw in [("空dict", {}), ("candidates空", {"candidates": []}),
                   ("None", None), ("想定外の型", {"candidates": "broken"}),
                   ("parts空", {"candidates": [{"content": {"parts": []}}]})]:
    try:
        r = mod._CommonGeminiResponse(raw)
        ok = r.text == "" and r.parts == [] and r.usage_metadata.prompt_token_count == 0
    except Exception as e:
        ok, label = False, f"{label}: {e}"
    check(f"壊れたレスポンス({label})で例外を投げず parts が [] になる", ok)

# --- 空応答なら ValueError → 3回リトライ → 原文フォールバック -----------
RESPONSE["value"] = {"candidates": [{"content": {"parts": []}}]}
CAPTURED["calls"].clear()
out2, is_error2 = mod.translate_batch_gemini(["原文A", "原文B"], "Japanese", 1, None)
check("空応答のとき3回リトライする", len(CAPTURED["calls"]) == 3,
      f"calls={len(CAPTURED['calls'])}")
check("空応答のとき原文を返す", out2 == ["原文A", "原文B"], f"out={out2}")
check("空応答のときエラーフラグが True", is_error2 is True)
RESPONSE["value"] = None

# --- 通信失敗時も3回リトライして原文フォールバック ----------------------
def _raising(payload):
    raise RuntimeError("proxy down")


RESPONSE["value"] = _raising
CAPTURED["calls"].clear()
out3, is_error3 = mod.translate_batch_gemini(["原文A"], "Japanese", 2, None)
check("通信失敗時も3回リトライする", len(CAPTURED["calls"]) == 3,
      f"calls={len(CAPTURED['calls'])}")
check("通信失敗時は例外を投げず原文を返す", out3 == ["原文A"], f"out={out3}")
check("通信失敗時はエラーフラグが True", is_error3 is True)
RESPONSE["value"] = None

# --- 番号が一部欠けた応答は該当項目だけ原文 -----------------------------
RESPONSE["value"] = {"candidates": [{"content": {"parts": [{"text": "[1] OK-1"}]}}]}
out4, _ = mod.translate_batch_gemini(["原文A", "原文B"], "Japanese", 3, None)
check("欠番の項目だけ原文にフォールバックする", out4 == ["OK-1", "原文B"], f"out={out4}")
RESPONSE["value"] = None

# --- 3バッチ連続エラーでフェイルファストする(移行後も維持されているか) --
RESPONSE["value"] = _raising
try:
    mod.translate_super_fast_parallel(["a" * 5] * 40, "Japanese", max_workers=1, logger=None)
    check("3バッチ連続エラーでフェイルファストする", False, "RuntimeErrorが出なかった")
except RuntimeError as e:
    check("3バッチ連続エラーでフェイルファストする", True)
    check("フェイルファストのメッセージが従来どおり", "3回連続で失敗" in str(e), str(e))
RESPONSE["value"] = None

# --- 並列翻訳が正常系で全件返すこと -------------------------------------
res = mod.translate_super_fast_parallel(["text %d" % i for i in range(25)],
                                        "Japanese", max_workers=3, logger=None)
check("並列翻訳が入力と同じ件数を返す", len(res) == 25, f"len={len(res)}")

# --- 認証情報の判定 (プロキシURLのみ = 通ることが最重要) ----------------
_env_backup = {k: os.environ.get(k) for k in ("GEMINI_API_KEY", "GEMINI_PROXY_URL")}
for api, proxy, expected, label in [
        ("k", None, True, "APIキーのみ"),
        (None, "https://x", True, "プロキシURLのみ(プロキシ専用構成)"),
        ("k", "https://x", True, "両方"),
        (None, None, False, "どちらも未設定")]:
    for name, val in (("GEMINI_API_KEY", api), ("GEMINI_PROXY_URL", proxy)):
        os.environ.pop(name, None)
        if val:
            os.environ[name] = val
    check(f"gemini_credentials_available: {label} -> {expected}",
          mod.gemini_credentials_available() is expected)

    MESSAGEBOX.CALLS.clear()
    check(f"init_gemini: {label} -> {expected}", mod.init_gemini(None) is expected)
    if not expected:
        msg = MESSAGEBOX.CALLS[-1][2] if MESSAGEBOX.CALLS else ""
        check("未設定時のエラーが両方の環境変数を案内する",
              "GEMINI_API_KEY" in msg and "GEMINI_PROXY_URL" in msg, msg)

for k, v in _env_backup.items():
    os.environ.pop(k, None)
    if v:
        os.environ[k] = v

# --- 共通モジュール未配置時 ---------------------------------------------
mod2 = _load_target("target_no_common", inject_fake=False)
check("共通モジュール未配置なら HAS_GEMINI が False", mod2.HAS_GEMINI is False)

try:
    mod2._CommonGeminiClient().models.generate_content(model="m", contents="c")
    check("共通モジュール未配置でAI呼び出しすると RuntimeError", False, "例外が出なかった")
except RuntimeError as e:
    text = str(e)
    check("共通モジュール未配置でAI呼び出しすると RuntimeError", True)
    check("エラーに探索したパスが含まれる", "common" in text, text.splitlines()[1])
    check("エラーに GEMINI_COMMON_DIR の案内が含まれる", "GEMINI_COMMON_DIR" in text)
except Exception as e:
    check("共通モジュール未配置でAI呼び出しすると RuntimeError", False, repr(e))

MESSAGEBOX.CALLS.clear()
check("共通モジュール未配置なら check_dependencies が False",
      mod2.check_dependencies(None) is False)
check("check_dependencies のエラーが原因を説明している",
      any("gemini_client.py" in c[2] for c in MESSAGEBOX.CALLS),
      f"calls={MESSAGEBOX.CALLS}")
MESSAGEBOX.CALLS.clear()
check("共通モジュール未配置なら init_gemini も False", mod2.init_gemini(None) is False)
check("依存関係が揃っていれば check_dependencies が True",
      mod.check_dependencies(None) is True)

# --- 共通モジュールの探索 (会社PCは「2つ上」が common) ------------------
_tmp = tempfile.mkdtemp()
try:
    _common = os.path.join(_tmp, "PythonScripts", "common")
    _tool = os.path.join(_tmp, "PythonScripts", "PDF_translation", "pdf_translator")
    os.makedirs(_common)
    os.makedirs(_tool)
    with open(os.path.join(_common, "gemini_client.py"), "w", encoding="utf-8") as f:
        f.write("MARKER = 'two-up'\n\n\ndef generate_advanced(payload, model=None):\n"
                "    return {'candidates': [{'content': {'parts': [{'text': '[1] ok'}]}}]}\n")
    _copied = os.path.join(_tool, os.path.basename(TARGET))
    shutil.copy(TARGET, _copied)

    _saved_path = list(sys.path)
    mod3 = _load_target("target_two_up", inject_fake=False, target=_copied)
    check("「2つ上が common」の配置で共通モジュールを解決できる",
          mod3.HAS_GEMINI is True and mod3._COMMON_DIR == os.path.abspath(_common),
          f"COMMON_DIR={getattr(mod3, '_COMMON_DIR', None)}")
    check("探索候補に1つ上・2つ上・3つ上が含まれる",
          len(mod3._COMMON_DIR_CANDIDATES) == 3, f"{mod3._COMMON_DIR_CANDIDATES}")

    # GEMINI_COMMON_DIR による明示指定
    os.environ["GEMINI_COMMON_DIR"] = _common
    mod4 = _load_target("target_env_dir", inject_fake=False)
    check("GEMINI_COMMON_DIR で共通モジュールの場所を明示指定できる",
          mod4.HAS_GEMINI is True
          and mod4._COMMON_DIR_CANDIDATES == [_common],
          f"candidates={mod4._COMMON_DIR_CANDIDATES}")
    os.environ.pop("GEMINI_COMMON_DIR", None)
    sys.path[:] = _saved_path
finally:
    shutil.rmtree(_tmp, ignore_errors=True)
    sys.modules.pop("gemini_client", None)

# --- 未使用オプション(他ツールとの契約統一) -----------------------------
CAPTURED["calls"].clear()
sys.modules["gemini_client"] = pytypes.ModuleType("gemini_client")
cfg = mod._GeminiGenerateConfig(temperature=0.5, response_mime_type="application/json",
                                response_schema={"type": "object"},
                                system_instruction="be brief")
mod._CommonGeminiClient().models.generate_content(model="m", contents="c", config=cfg)
_p = CAPTURED["calls"][-1]["payload"]
check("responseMimeType / responseSchema が camelCase で載る",
      _p.get("generationConfig", {}).get("responseMimeType") == "application/json"
      and _p.get("generationConfig", {}).get("responseSchema") == {"type": "object"},
      f"generationConfig={_p.get('generationConfig')}")
check("systemInstruction が REST 形式で載る",
      _p.get("systemInstruction") == {"parts": [{"text": "be brief"}]},
      f"systemInstruction={_p.get('systemInstruction')}")

CAPTURED["calls"].clear()
mod._CommonGeminiClient().models.generate_content(model="m", contents="c", config=None)
check("config が None でも payload を組み立てられる",
      "generationConfig" not in CAPTURED["calls"][-1]["payload"]
      and "safetySettings" not in CAPTURED["calls"][-1]["payload"])


class _FakePydanticSchema:
    def model_dump(self, **kwargs):
        return {"type": "OBJECT", "propertyOrdering": ["a"]}


check("pydantic モデルの response_schema も dict 化できる",
      mod._schema_to_jsonable(_FakePydanticSchema()) == {"type": "OBJECT",
                                                         "propertyOrdering": ["a"]})


# ============================================================
# PDF処理のエンドツーエンド検証 (fitz は本物を使う)
#   移行で PDFレイアウト処理に一切影響が出ていないことを、合成PDFで確認する。
#   罫線の座標が翻訳前後で完全一致すれば、表・グラフを壊していない証拠になる。
# ============================================================
def _build_sample_pdf(path):
    """罫線つき表(2列×3行) ＋ 色付きの棒グラフ ＋ 自由配置の段落を含むPDFを作る。"""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    page.insert_text((60, 70), "Employee Engagement Survey Results",
                     fontsize=18, fontname="helv")
    page.insert_text((60, 100), "This paragraph describes the overall findings "
                                "of the survey conducted last quarter.",
                     fontsize=10, fontname="helv")

    # 罫線つきの表 (縦3本・横4本 => 2列 x 3行)
    x0, x1, x2 = 60, 250, 440
    ys = [140, 175, 210, 245]
    for y in ys:
        page.draw_line(fitz.Point(x0, y), fitz.Point(x2, y), width=0.8)
    for x in (x0, x1, x2):
        page.draw_line(fitz.Point(x, ys[0]), fitz.Point(x, ys[-1]), width=0.8)
    rows = [("Category", "Score"), ("Wellbeing", "66.6 percent"),
            ("Leadership", "72.1 percent")]
    for i, (left, right) in enumerate(rows):
        page.insert_text((x0 + 6, ys[i] + 22), left, fontsize=10, fontname="helv")
        page.insert_text((x1 + 6, ys[i] + 22), right, fontsize=10, fontname="helv")

    # 色付きの棒グラフ (墨消しで塗り潰されてはいけない図形)
    page.draw_rect(fitz.Rect(60, 300, 300, 320), color=None, fill=(0.1, 0.35, 0.75))
    page.draw_rect(fitz.Rect(300, 300, 380, 320), color=None, fill=(0.85, 0.2, 0.2))
    page.insert_text((60, 340), "Favorable responses increased year over year.",
                     fontsize=10, fontname="helv")

    doc.save(path)
    doc.close()


def _line_signature(path):
    """ページ内の直線・矩形の座標を、比較できる形で書き出す。"""
    doc = fitz.open(path)
    sig = []
    for page in doc:
        for d in page.get_drawings():
            for item in d.get("items", []):
                if item[0] == "l":
                    sig.append(("l", round(item[1].x, 3), round(item[1].y, 3),
                                round(item[2].x, 3), round(item[2].y, 3)))
                elif item[0] == "re":
                    r = fitz.Rect(item[1])
                    sig.append(("re", round(r.x0, 3), round(r.y0, 3),
                                round(r.x1, 3), round(r.y1, 3)))
    doc.close()
    return sorted(sig)


_pdf_dir = tempfile.mkdtemp()
try:
    src_pdf = os.path.join(_pdf_dir, "sample.pdf")
    out_pdf = os.path.join(_pdf_dir, "sample_ja.pdf")
    _build_sample_pdf(src_pdf)
    before_sig = _line_signature(src_pdf)

    doc = fitz.open(src_pdf)
    blocks = mod.extract_translatable_blocks(doc, protect_graphics=False,
                                             target_pages=None, logger=None)
    check("合成PDFから翻訳対象ブロックを抽出できる", len(blocks) > 0, f"blocks={len(blocks)}")
    check("罫線つき表がセルとして認識される",
          any(b["is_cell"] for b in blocks),
          f"cells={sum(1 for b in blocks if b['is_cell'])}")

    translated = [f"翻訳{i}" for i in range(len(blocks))]
    mod.apply_translations_to_pdf(doc, blocks, translated, "Japanese", None)
    doc.save(out_pdf, garbage=4, deflate=True)
    doc.close()

    after_sig = _line_signature(out_pdf)
    # 墨消し(redaction)は矩形を背景色で塗るため、出力には塗り矩形が増える(v08でも同じ)。
    # 判定すべきは「元からあった罫線・図形が1つも失われず、座標も動いていないこと」。
    missing = [s for s in before_sig if s not in after_sig]
    check("元の罫線・図形がすべて座標そのままで保持される(表・グラフを壊していない)",
          not missing, f"失われた図形={missing}")
    check("表の罫線7本がすべて残っている",
          sum(1 for s in after_sig if s[0] == "l") == 7,
          f"lines={sum(1 for s in after_sig if s[0] == 'l')}")

    out_text = "".join(page.get_text() for page in fitz.open(out_pdf))
    check("翻訳文がPDFへ書き戻されている", "翻訳" in out_text)

    # --- v20260821_01: 翻訳文が背景と同じ色で塗り潰されないこと ---------------
    # （日本語→英語の実データで38件発生していた最も致命的な不具合の回帰テスト）
    bad = []
    for b in blocks:
        ci = b["color"]
        tc = (((ci >> 16) & 255) / 255, ((ci >> 8) & 255) / 255, (ci & 255) / 255)
        if mod._colors_close(b["fill"], tc):
            bad.append(b["text"][:20])
    check("どのブロックも『塗り色＝文字色』にならない（翻訳文が消えない）",
          not bad, f"該当={bad}")
    check("全ブロックに背景色が事前計算されている",
          all(b.get("fill") is not None for b in blocks))

    # ページ指定翻訳 (v07機能) が移行後も動くこと
    doc = fitz.open(src_pdf)
    check("target_pages で範囲外のページを完全にスキップする",
          mod.extract_translatable_blocks(doc, target_pages={5}, logger=None) == [])
    doc.close()

    # ページ指定文字列のパース (移行と無関係だが回帰確認)
    check("parse_page_spec が範囲指定を解釈する",
          mod.parse_page_spec("1-3,5", 10) == {0, 1, 2, 4})
    check("parse_page_spec が空欄なら None(全ページ)", mod.parse_page_spec("  ", 10) is None)
    try:
        mod.parse_page_spec("1-99", 10)
        check("parse_page_spec が範囲外を弾く", False, "例外が出なかった")
    except ValueError:
        check("parse_page_spec が範囲外を弾く", True)
finally:
    shutil.rmtree(_pdf_dir, ignore_errors=True)



# ============================================================
# v20260821_01: 日本語→英語で見つかった不具合の回帰テスト
#   実データ（13ページの日本語スライドとその英訳出力）で確認した5つの原因に対応する。
# ============================================================

# --- 1. 短い日本語が『短すぎる』で除外されないこと -------------------------
for word in ("企業", "震度", "時刻", "対象", "名", "日"):
    check(f"is_translatable('{word}') が True（日本語の2文字以下は語として成立する）",
          mod.is_translatable(word) is True)
# 英語側の挙動は従来どおり（2文字以下は除外）であること
for word in ("ab", "x", "OK"):
    check(f"is_translatable('{word}') が False（英語の短い断片は従来どおり除外）",
          mod.is_translatable(word) is False)
check("_contains_cjk が日本語を検出する", mod._contains_cjk("企業のデータ") is True)
check("_contains_cjk が英語を検出しない", mod._contains_cjk("company data") is False)

# --- 2. 字送りで割れた文字列の正規化 ---------------------------------------
for raw, want, why in [
        ("当社では2 0 0 4 年から、大規模災害", "当社では2004年から、大規模災害", "日本語＋数字"),
        ("地方銀行A 行", "地方銀行A行", "日本語＋英字"),
        ("9 6 %", "96 %", "数字だけのセル"),
        ("This is normal English text", "This is normal English text", "英語は一切変えない"),
        ("I am a developer", "I am a developer", "英語の1文字単語を壊さない"),
        ("Approximately 3,100 people", "Approximately 3,100 people", "英語の数字を壊さない")]:
    got = mod._normalize_tracked_spaces(raw)
    check(f"_normalize_tracked_spaces: {why}", got == want, f"{raw!r} -> {got!r}")

# --- 3. フォントの自動切り替え --------------------------------------------
check("Latin-1に収まる英文は helv のまま",
      mod.pick_font_for_text("Plain English text", "helv") == "helv")
check("丸数字を含む場合はCJKフォントへ切り替える（'?'化の防止）",
      mod.pick_font_for_text("Situation ③", "helv") == "japan")
check("※ を含む場合もCJKフォントへ切り替える",
      mod.pick_font_for_text("※ note", "helv") == "japan")
check("太字は Helvetica-Bold(hebo) を使う",
      mod.pick_font_for_text("Bold heading", "helv", bold=True) == "hebo")
check("翻訳先が日本語のときは従来どおり japan",
      mod.pick_font_for_text("なんでも", mod.lang_to_fontname("Japanese")) == "japan")

# --- 4. 自由配置テキストの寄せ推定 ----------------------------------------
_pr = fitz.Rect(0, 0, 960, 540)
check("ページ中央にある要素は中央寄せと判定",
      mod._guess_free_alignment(fitz.Rect(292, 212, 668, 259), None, _pr)
      == fitz.TEXT_ALIGN_CENTER)
check("左端にある要素は左寄せのまま",
      mod._guess_free_alignment(fitz.Rect(40, 30, 300, 50), None, _pr)
      == fitz.TEXT_ALIGN_LEFT)
check("右端に寄っている要素は右寄せと判定",
      mod._guess_free_alignment(fitz.Rect(700, 30, 950, 50), None, _pr)
      == fitz.TEXT_ALIGN_RIGHT)

# --- 5. 同一段落の行結合 ---------------------------------------------------
def _rec(x0, y0, x1, y1, text, size=14, color=0):
    return {"block_idx": 0, "bbox": fitz.Rect(x0, y0, x1, y1), "text": text,
            "size": size, "color": color, "bold": False}

para = [[_rec(190, 277, 778, 293, "一行目")],
        [_rec(188, 302, 781, 319, "二行目")],
        [_rec(188, 327, 781, 344, "三行目")]]
merged = mod._merge_paragraph_groups([list(g) for g in para])
check("連続する同一段落の3行が1つの翻訳単位にまとまる", len(merged) == 1,
      f"groups={len(merged)}")

far = [[_rec(190, 277, 400, 293, "本文")],
       [_rec(190, 480, 400, 496, "遠く離れた別の段落")]]
check("行間が大きく離れていれば結合しない",
      len(mod._merge_paragraph_groups([list(g) for g in far])) == 2)

diff = [[_rec(190, 277, 400, 293, "見出し", size=28)],
        [_rec(190, 302, 400, 319, "本文", size=12)]]
check("フォントサイズが違えば結合しない",
      len(mod._merge_paragraph_groups([list(g) for g in diff])) == 2)

apart = [[_rec(100, 277, 300, 293, "左の列")],
         [_rec(700, 279, 900, 295, "右の列")]]
check("横に離れた別の列は結合しない",
      len(mod._merge_paragraph_groups([list(g) for g in apart])) == 2)

# --- 6. 背景色サンプリングと矩形拡張（日本語資料のレイアウトを合成して検証）---
def _build_japanese_like_pdf(path):
    """ページ全面に濃紺の縁取りがあり、中央に紺色の本文がある構成を作る。
    v20260812_01では、この構成で本文の矩形がページ端まで拡張され、縁取りの紺を
    背景と誤認して本文を紺で塗り潰していた（＝翻訳文が読めなくなっていた）。"""
    doc = fitz.open()
    page = doc.new_page(width=960, height=540)
    navy = (0.0, 0.28, 0.59)
    page.draw_rect(fitz.Rect(0, 0, 960, 540), color=None, fill=navy)      # 縁取り
    page.draw_rect(fitz.Rect(10, 9, 951, 531), color=None, fill=(1, 1, 1))  # 白の本文領域
    page.insert_text((292, 250), "能登半島地震の状況", fontsize=40,
                     fontname="japan", color=navy)
    for i, t in enumerate(["当社では大規模災害発生時に従業員の安否を",
                           "支援するサービスを提供しています。",
                           "ここでは利用状況をご報告します。"]):
        page.insert_text((190, 290 + i * 25), t, fontsize=14, fontname="japan", color=navy)
    page.insert_text((15, 537), "お客様専用の資料です", fontsize=6,
                     fontname="japan", color=(1, 1, 1))  # 紺地に白文字のフッター
    doc.save(path)
    doc.close()


_jp_dir = tempfile.mkdtemp()
try:
    jp_pdf = os.path.join(_jp_dir, "jp.pdf")
    _build_japanese_like_pdf(jp_pdf)
    jdoc = fitz.open(jp_pdf)
    jblocks = mod.extract_translatable_blocks(jdoc, protect_graphics=False,
                                              target_pages=None, logger=None)
    check("日本語PDFから翻訳対象を抽出できる", len(jblocks) > 0, f"blocks={len(jblocks)}")

    invisible = []
    for b in jblocks:
        ci = b["color"]
        tc = (((ci >> 16) & 255) / 255, ((ci >> 8) & 255) / 255, (ci & 255) / 255)
        if mod._colors_close(b["fill"], tc):
            invisible.append(b["text"][:16])
    check("紺地の縁取りがあっても『塗り色＝文字色』にならない",
          not invisible, f"該当={invisible}")

    body = [b for b in jblocks if "当社" in b["text"] or "支援" in b["text"]]
    check("白地の本文の背景は白と判定される",
          all(mod._colors_close(b["fill"], (1, 1, 1)) for b in body),
          f"fills={[tuple(round(x,2) for x in b['fill']) for b in body]}")
    check("本文の矩形が白い領域の外（縁取り）まで拡張されない",
          all(b["box_rect"].x1 <= 951.5 for b in body),
          f"x1={[round(b['box_rect'].x1) for b in body]}")

    footer = [b for b in jblocks if "お客様" in b["text"]]
    check("紺地に白文字のフッターは背景が紺と判定される（従来の正しい挙動を維持）",
          footer and mod._colors_close(footer[0]["fill"], (0.0, 0.28, 0.59)),
          f"fill={tuple(round(x,2) for x in footer[0]['fill']) if footer else None}")

    check("本文3行が1つの段落にまとまる", len(body) == 1, f"body={len(body)}")

    title = [b for b in jblocks if "能登" in b["text"]]
    check("中央にあるタイトルが中央寄せと判定される",
          title and title[0]["align"] == fitz.TEXT_ALIGN_CENTER)

    # 実際に英訳（＝日本語より長い文字列）を書き戻して、縁取りが壊れないことを確認
    before = _line_signature(jp_pdf)
    mod.apply_translations_to_pdf(
        jdoc, jblocks,
        ["Situation of the Noto Peninsula Earthquake ③ " * 2 for _ in jblocks],
        "English", None)
    jout = os.path.join(_jp_dir, "jp_en.pdf")
    jdoc.save(jout, garbage=4, deflate=True)
    jdoc.close()

    after = _line_signature(jout)
    check("英訳の書き戻し後もページの縁取り・図形が保持される",
          all(s in after for s in before), f"失われた図形={[s for s in before if s not in after]}")

    otext = "".join(p.get_text() for p in fitz.open(jout))
    check("丸数字③が '?' に化けず保持される", "③" in otext and "?" not in otext,
          f"'?'の数={otext.count('?')}")
    check("英訳がPDFへ書き戻されている", "Noto Peninsula" in otext)
finally:
    shutil.rmtree(_jp_dir, ignore_errors=True)

# ============================================================
print("\n" + "=" * 60)
failed = [r for r in RESULTS if not r[1]]
print(f"合計 {len(RESULTS)} 項目 / 合格 {len(RESULTS) - len(failed)} / 失敗 {len(failed)}")
if failed:
    for name, _ok, detail in failed:
        print(f"  FAILED: {name}  {detail}")
sys.exit(1 if failed else 0)
