"""excel_translation_20260817_01.py の検証テスト。

v20260817_01 の変更点: セルが複数行にわたる、またはセル自体が "1. xxx" のような
箇条書き番号を持つ場合に、翻訳が欠落・混線する不具合を修正した(実際にユーザーから
報告された事例をもとに再現・検証する)。旧版(`_20260812_01`)の「数字+ピリオドの行=
項目の境界」という行ベースの解析を、専用マーカー(`<<<ITEM n>>>`)ベースの解析へ
置き換えている。プロキシ移行そのものの検証は `test_excel_translation_20260812_01.py`
を参照(本ファイルでは重複させず、新規の解析ロジックに絞って検証する)。

Windows / Excel / 実際の Gemini API に依存せず検証するため、偽の `gemini_client` を
**対象モジュールのロード前に** sys.modules へ注入し、`generate_advanced()` に渡る
payload を捕捉して検証する(HANDOVER_onenote_gemini_proxy.md 第7章の手法)。

tkinter / pandas / openpyxl も Linux コンテナには無いためスタブ化する。

実行方法:
    python3 tests/test_excel_translation_20260817_01.py
"""

import importlib.util
import json
import os
import re
import sys
import types as pytypes

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "excel_translation_20260817_01.py")

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
_FAKE_MARKER_RE = re.compile(r'^<<<ITEM (\d+)>>>$')


def _fake_generate_advanced(payload, model=None, **kwargs):
    """既定では、プロンプト中の最初の <<<ITEM n>>> 以降だけを取り出し、マーカー行は
    そのまま、それ以外の行は "Translated: " を前置して返す(複数行・空行・セル内部の
    番号付きリストもすべてそのまま保持する = 実際のGeminiが指示どおり動いた場合の
    挙動を模する)。マーカーより前の説明文(プロンプトの指示文)は無視する。"""
    CAPTURED["calls"].append({"payload": payload, "model": model})
    if RESPONSE["value"] is not None:
        return RESPONSE["value"]

    prompt_text = payload["contents"][0]["parts"][0]["text"]
    lines = prompt_text.splitlines()
    start = next((i for i, l in enumerate(lines) if _FAKE_MARKER_RE.match(l.strip())), None)
    out_lines = []
    if start is not None:
        for line in lines[start:]:
            if _FAKE_MARKER_RE.match(line.strip()):
                out_lines.append(line.strip())
            elif line.strip():
                out_lines.append(f"Translated: {line}")
            else:
                out_lines.append(line)
    text = "\n".join(out_lines)
    return {"candidates": [{"content": {"parts": [{"text": text}]}}],
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
mod = _load_target("target_main_0817")

check("HAS_GEMINI が True", mod.HAS_GEMINI is True)

# --- 通常の翻訳呼び出し(単一行セルのみのバッチ。従来どおり動くことの確認) ---
CAPTURED["calls"].clear()
out = mod.translate_batch_parallel(["テキスト1", "テキスト2"], "English", 1)

call = CAPTURED["calls"][0]
prompt_text = call["payload"]["contents"][0]["parts"][0]["text"]

check("model が明示的に gemini-2.5-flash で渡る", call["model"] == "gemini-2.5-flash")
check("payload にマーカー付きで翻訳対象テキストが含まれる",
      "<<<ITEM 1>>>" in prompt_text and "テキスト1" in prompt_text
      and "<<<ITEM 2>>>" in prompt_text and "テキスト2" in prompt_text,
      prompt_text)
check("翻訳先言語がプロンプトに反映される", "English" in prompt_text)
check("generationConfig.temperature が 0 で載る",
      call["payload"].get("generationConfig", {}).get("temperature") == 0)
check("systemInstruction が REST 形式で載る",
      call["payload"].get("systemInstruction", {}).get("parts", [{}])[0].get("text", "")
      .startswith("You are a professional translator"))
check("payload が json.dumps 可能", bool(json.dumps(call["payload"])))
check("通常バッチの解析結果が正しく対応する",
      out == ["Translated: テキスト1", "Translated: テキスト2"], f"out={out}")

# ============================================================
# ★本題: セルが複数行 + セル自身が箇条書き番号を持つ場合(実際の報告事例)
# ============================================================
MULTI_LINE_CELL = (
    "Prevent action: \n"
    "1. increase the design margin ( trim range) for critical parameters to cover posdel inaccurate.\n"
    "2. Confirm with DBH for post-sim extracted data\n"
    "Mitigation plan: accept real-si performance or modify in re-spin"
)

# Geminiが指示どおりマーカー方式で応答した場合を模した、現実的な応答を明示的に用意する
# (この応答は _fake_generate_advanced の既定生成ロジックに頼らず、狙った内容を直接指定する)。
RESPONSE["value"] = {
    "candidates": [{"content": {"parts": [{"text": (
        "<<<ITEM 1>>>\n"
        "会議メモ訳\n"
        "<<<ITEM 2>>>\n"
        "予防措置:\n"
        "1. 重要なパラメータの設計マージン(トリム範囲)を拡大し、posdelの不正確さをカバーする。\n"
        "2. ポストシム抽出データについてDBHに確認する。\n"
        "緩和計画: 実際のシリコン性能を受け入れるか、リスピンで修正する。\n"
        "<<<ITEM 3>>>\n"
        "承認済み訳"
    )}]}}],
    "usageMetadata": {"promptTokenCount": 999, "candidatesTokenCount": 999},
}

CAPTURED["calls"].clear()
out_multiline = mod.translate_batch_parallel(
    ["会議メモ", MULTI_LINE_CELL, "承認済み"], "Japanese", 99)

sent_prompt = CAPTURED["calls"][-1]["payload"]["contents"][0]["parts"][0]["text"]
check("複数行セルの内部の番号もそのまま(改変されず)プロンプトへ渡る",
      "<<<ITEM 2>>>\nPrevent action: \n1. increase the design margin" in sent_prompt,
      sent_prompt)

check("前後の項目(単一行)がクロスコンタミネーションされない: 項目1",
      out_multiline[0] == "会議メモ訳", f"out[0]={out_multiline[0]!r}")
check("前後の項目(単一行)がクロスコンタミネーションされない: 項目3",
      out_multiline[2] == "承認済み訳", f"out[2]={out_multiline[2]!r}")

expected_item2 = (
    "予防措置:\n"
    "1. 重要なパラメータの設計マージン(トリム範囲)を拡大し、posdelの不正確さをカバーする。\n"
    "2. ポストシム抽出データについてDBHに確認する。\n"
    "緩和計画: 実際のシリコン性能を受け入れるか、リスピンで修正する。"
)
check("複数行セルの訳文が4行すべて欠落なく1項目として保持される(旧版で報告された不具合)",
      out_multiline[1] == expected_item2, f"out[1]={out_multiline[1]!r}")
check("『予防措置:』の行が欠落していない(旧版では番号なし行として消失していた)",
      "予防措置" in out_multiline[1])
check("『緩和計画』の行が欠落していない(旧版では番号なし行として消失していた)",
      "緩和計画" in out_multiline[1])
check("セル内部の番号付き行がプロンプトの外側の番号と混同されていない",
      "重要なパラメータ" in out_multiline[1] and "ポストシム抽出データ" in out_multiline[1])

RESPONSE["value"] = None

# --- マーカーがMarkdown太字で多少崩れても拾える(応答側の揺れに対する保険) ---
check("**<<<ITEM 1>>>** のような太字マーカーも認識する(_ITEM_MARKER_RE)",
      bool(mod._ITEM_MARKER_RE.match("**<<<ITEM 1>>>**")))
check("マーカーではない行は認識しない(_ITEM_MARKER_RE)",
      mod._ITEM_MARKER_RE.match("これはマーカーではありません") is None)
m12 = mod._ITEM_MARKER_RE.match("<<<ITEM 12>>>")
check("複数桁の項目番号も認識する(_ITEM_MARKER_RE)", m12 is not None and m12.group(1) == "12")

# --- 異常レスポンス時は原文へフォールバック ---
for label, bad in [("空レスポンス", {"candidates": []}),
                   ("マーカー無しテキスト",
                    {"candidates": [{"content": {"parts": [{"text": "no markers here"}]}}]})]:
    RESPONSE["value"] = bad
    out2 = mod.translate_batch_parallel(["原文A", "原文B"], "English", 2)
    check(f"{label}のとき原文を返す", out2 == ["原文A", "原文B"], f"out={out2}")
RESPONSE["value"] = None

# --- 欠けた項目は該当項目のみ原文にフォールバック ---
RESPONSE["value"] = {"candidates": [{"content": {"parts": [{"text": "<<<ITEM 1>>>\nOK-1"}]}}]}
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

# ============================================================
print("\n" + "=" * 60)
failed = [r for r in RESULTS if not r[1]]
print(f"合計 {len(RESULTS)} 項目 / 合格 {len(RESULTS) - len(failed)} / 失敗 {len(failed)}")
if failed:
    for name, _ok, detail in failed:
        print(f"  FAILED: {name}  {detail}")
sys.exit(1 if failed else 0)
