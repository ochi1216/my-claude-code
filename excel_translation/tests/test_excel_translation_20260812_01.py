"""excel_translation_20260812_01.py の Gemini プロキシ移行部分の検証テスト。

Windows / Excel / 実際の Gemini API に依存せず検証するため、
偽の `gemini_client` を **対象モジュールのロード前に** sys.modules へ注入し、
`generate_advanced()` に渡る payload を捕捉して検証する
(HANDOVER_onenote_gemini_proxy.md 第7章の手法)。

tkinter / pandas / openpyxl も Linux コンテナには無いためスタブ化する。

実行方法:
    python3 tests/test_excel_translation_20260812_01.py
"""

import importlib.util
import json
import os
import sys
import types as pytypes

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "excel_translation_20260812_01.py")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  ({detail})" if detail else ""))


# ------------------------------------------------------------
# GUI / Excel 依存のスタブ
# ------------------------------------------------------------
def _install_env_stubs():
    """tkinter・pandas を最低限のスタブへ差し替える。
    openpyxl は対象側が try/except で受けているため未導入のままでよい。"""
    class _Anything:
        """属性アクセス・呼び出しを何でも受け付けるダミー。"""
        def __init__(self, *a, **k):
            pass

        def __call__(self, *a, **k):
            return _Anything()

        def __getattr__(self, _name):
            return _Anything()

    tk = pytypes.ModuleType("tkinter")
    for attr in ("Tk", "Toplevel", "Frame", "Label", "Button", "Entry", "Listbox",
                 "Checkbutton", "OptionMenu", "LabelFrame", "StringVar",
                 "BooleanVar", "MULTIPLE", "END", "LEFT"):
        setattr(tk, attr, _Anything())
    tk.font = pytypes.ModuleType("tkinter.font")

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
    messagebox.askwarning = _record("askwarning")

    tk.filedialog = filedialog
    tk.messagebox = messagebox
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox
    sys.modules["tkinter.font"] = tk.font

    pd = pytypes.ModuleType("pandas")
    pd.isna = lambda v: v is None
    pd.notna = lambda v: v is not None
    pd.read_excel = lambda *a, **k: {}
    pd.ExcelFile = _Anything()
    sys.modules["pandas"] = pd

    return messagebox


MESSAGEBOX = _install_env_stubs()


# ------------------------------------------------------------
# 偽 gemini_client
# ------------------------------------------------------------
CAPTURED = {"calls": []}
RESPONSE = {"value": None}


def _fake_generate_advanced(payload, model=None, **kwargs):
    CAPTURED["calls"].append({"payload": payload, "model": model})
    if RESPONSE["value"] is not None:
        return RESPONSE["value"]
    # 呼ばれた項目数どおりの番号付きリストを返す
    n = len(payload["contents"][0]["parts"][0]["text"].splitlines())
    lines = "\n".join(f"{i}. Translated {i}" for i in range(1, n + 1))
    return {"candidates": [{"content": {"parts": [{"text": lines}]}}],
            "usageMetadata": {"promptTokenCount": 123, "candidatesTokenCount": 45}}


def _load_target(module_name, inject_fake=True):
    """対象ファイルをロードする。inject_fake=False なら共通モジュール未配置を再現。"""
    sys.modules.pop("gemini_client", None)
    if inject_fake:
        fake = pytypes.ModuleType("gemini_client")
        fake.generate_advanced = _fake_generate_advanced
        sys.modules["gemini_client"] = fake

    spec = importlib.util.spec_from_file_location(module_name, TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ============================================================
# 検証
# ============================================================
mod = _load_target("target_main")

check("共通モジュールを読み込めた場合 HAS_GEMINI が True", mod.HAS_GEMINI is True)
check("旧SDK(google.generativeai)への依存が無い",
      not hasattr(mod, "genai") and "google.generativeai" not in sys.modules)

# --- 通常の翻訳呼び出し ---
CAPTURED["calls"].clear()
out = mod.translate_batch_parallel(["テキスト1", "テキスト2"], "English", 1)

check("generate_advanced が1回呼ばれた", len(CAPTURED["calls"]) == 1,
      f"calls={len(CAPTURED['calls'])}")

call = CAPTURED["calls"][0]
payload = call["payload"]

check("model が明示的に gemini-2.5-flash で渡る", call["model"] == "gemini-2.5-flash",
      f"model={call['model']!r}")
check("payload の contents が REST 形式",
      isinstance(payload.get("contents"), list)
      and isinstance(payload["contents"][0]["parts"][0]["text"], str))
check("payload に翻訳対象テキストが含まれる",
      "1. テキスト1" in payload["contents"][0]["parts"][0]["text"]
      and "2. テキスト2" in payload["contents"][0]["parts"][0]["text"])
check("翻訳先言語がプロンプトに反映される",
      "English" in payload["contents"][0]["parts"][0]["text"])
check("generationConfig.temperature が 0 で載る",
      payload.get("generationConfig", {}).get("temperature") == 0,
      f"generationConfig={payload.get('generationConfig')}")
check("systemInstruction が REST 形式で載る",
      payload.get("systemInstruction", {}).get("parts", [{}])[0].get("text", "")
      .startswith("You are a professional translator"),
      f"systemInstruction={payload.get('systemInstruction')}")
check("payload が json.dumps 可能", bool(json.dumps(payload)))
check("response.text の解析結果が返る", out == ["Translated 1", "Translated 2"], f"out={out}")

# --- レスポンス互換契約 ---
resp = mod._CommonGeminiResponse(
    {"candidates": [{"content": {"parts": [{"text": "hello"}]}}],
     "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}})
check("response.text が読める", resp.text == "hello")
check("response.usage_metadata が読める",
      resp.usage_metadata.prompt_token_count == 7
      and resp.usage_metadata.candidates_token_count == 3)

for label, raw in [("空dict", {}), ("candidates空", {"candidates": []}),
                   ("None", None), ("想定外の型", {"candidates": "broken"})]:
    try:
        r = mod._CommonGeminiResponse(raw)
        ok = r.text == "" and r.usage_metadata.prompt_token_count == 0
    except Exception as e:
        ok, label = False, f"{label}: {e}"
    check(f"壊れたレスポンス({label})で例外を投げない", ok)

# --- 異常レスポンス時は原文へフォールバック ---
for label, bad in [("空レスポンス", {"candidates": []}),
                   ("番号無しテキスト",
                    {"candidates": [{"content": {"parts": [{"text": "no numbers"}]}}]})]:
    RESPONSE["value"] = bad
    out2 = mod.translate_batch_parallel(["原文A", "原文B"], "English", 2)
    check(f"{label}のとき原文を返す", out2 == ["原文A", "原文B"], f"out={out2}")
RESPONSE["value"] = None

# --- 部分的に欠けた番号は該当項目のみ原文 ---
RESPONSE["value"] = {"candidates": [{"content": {"parts": [{"text": "1. OK-1"}]}}]}
out3 = mod.translate_batch_parallel(["原文A", "原文B"], "English", 3)
check("欠番の項目だけ原文にフォールバックする", out3 == ["OK-1", "原文B"], f"out={out3}")
RESPONSE["value"] = None

# --- 呼び出し側の例外は原文フォールバック(翻訳全体を落とさない) ---
def _raising(payload, model=None, **kwargs):
    raise RuntimeError("proxy down")

_saved = sys.modules["gemini_client"].generate_advanced
sys.modules["gemini_client"].generate_advanced = _raising
mod._generate_advanced = _raising
out4 = mod.translate_batch_parallel(["原文A"], "English", 4)
check("通信失敗時も例外を投げず原文を返す", out4 == ["原文A"], f"out={out4}")
mod._generate_advanced = _saved
sys.modules["gemini_client"].generate_advanced = _saved

# --- 認証情報の判定 ---
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
    check(f"check_api_key: {label} -> {expected}", mod.check_api_key() is expected)
    if not expected:
        msg = MESSAGEBOX.CALLS[-1][2] if MESSAGEBOX.CALLS else ""
        check("未設定時のエラーが両方の環境変数を案内する",
              "GEMINI_API_KEY" in msg and "GEMINI_PROXY_URL" in msg)

for k, v in _env_backup.items():
    os.environ.pop(k, None)
    if v:
        os.environ[k] = v

# --- 共通モジュール未配置時 ---
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

# このコンテナには openpyxl も無く、先に openpyxl 側の分岐で return してしまうため、
# Gemini 側の分岐だけを検証できるよう openpyxl は導入済み扱いにする
# (会社PCでは openpyxl はインストール済みのため、こちらが実際の経路になる)。
mod2.HAS_OPENPYXL = True
MESSAGEBOX.CALLS.clear()
check("共通モジュール未配置なら check_dependencies が False", mod2.check_dependencies() is False)
check("check_dependencies のエラーが原因を説明している",
      any("gemini_client.py" in c[2] for c in MESSAGEBOX.CALLS),
      f"calls={MESSAGEBOX.CALLS}")

# openpyxl も共通モジュールも揃っていれば True になること
mod.HAS_OPENPYXL = True
check("依存関係が揃っていれば check_dependencies が True", mod.check_dependencies() is True)

# --- 未使用オプション(他ツールとの契約統一) ---
CAPTURED["calls"].clear()
cfg = mod._GeminiGenerateConfig(temperature=0.5, response_mime_type="application/json",
                                response_schema={"type": "object"})
mod._CommonGeminiClient().models.generate_content(model="m", contents="c", config=cfg)
gc = CAPTURED["calls"][-1]["payload"].get("generationConfig", {})
check("responseMimeType / responseSchema が camelCase で載る",
      gc.get("responseMimeType") == "application/json"
      and gc.get("responseSchema") == {"type": "object"}, f"generationConfig={gc}")

CAPTURED["calls"].clear()
mod._CommonGeminiClient().models.generate_content(model="m", contents="c", config=None)
check("config が None でも payload を組み立てられる",
      "generationConfig" not in CAPTURED["calls"][-1]["payload"])


class _FakePydanticSchema:
    def model_dump(self, **kwargs):
        return {"type": "OBJECT", "propertyOrdering": ["a"]}


check("pydantic モデルの response_schema も dict 化できる",
      mod._schema_to_jsonable(_FakePydanticSchema()) == {"type": "OBJECT",
                                                         "propertyOrdering": ["a"]})

# ============================================================
print("\n" + "=" * 60)
failed = [r for r in RESULTS if not r[1]]
print(f"合計 {len(RESULTS)} 項目 / 合格 {len(RESULTS) - len(failed)} / 失敗 {len(failed)}")
if failed:
    for name, _ok, detail in failed:
        print(f"  FAILED: {name}  {detail}")
sys.exit(1 if failed else 0)
