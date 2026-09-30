"""ppt_translation の「画像だけのスライドの翻訳」(20260930_01 / 20260930_02) の検証テスト。

実際の Gemini・プロキシ・社内資料には一切依存しない。
- 偽の gemini_client を **対象モジュールのロード前に** sys.modules へ注入する。
- 「画像だけのスライド」は、このテストが PIL で描く合成スライド（表・帯・段落・ロゴ風の図形）。
  文字の位置（正解）が分かっているので、偽 Gemini はその正解を box_2d で返せる。
  ※ 実在の資料（社名入り等）はリポジトリに含めない。
- python-pptx は本物を使う。tkinter だけスタブ化する（GUIは別ファイル
  test_ppt_translation_image_gui_20260930.py で本物の tkinter を使って確認する）。

実行方法:
    pip install python-pptx
    python3 tests/test_ppt_translation_image_20260930.py            # 最新版(_03)を検証
    python3 tests/test_ppt_translation_image_20260930.py 02         # 重ね貼り版(_02)を検証
    python3 tests/test_ppt_translation_image_20260930.py 01         # ノート版(_01)を検証
_01 には重ね貼りが無いので、重ね貼りのテストは自動的にスキップされる。
_03 で追加した機能(文字の塊へのスナップ・太字/寄せ・確認画面の初期値・デバッグ出力)のテストは、
_03 以降のときだけ実行される。
"""

import copy
import hashlib
import importlib.util
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import types as pytypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
VERSION = sys.argv[1] if len(sys.argv) > 1 else "03"
TARGET = os.path.join(ROOT, f"ppt_translation_20260930_{VERSION}.py")
PREV_TARGET = os.path.join(ROOT, "ppt_translation_20260911_01.py")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  ({detail})" if detail else ""))


def skip(name, why):
    print(f"SKIP: {name}  ({why})")


# ------------------------------------------------------------
# tkinter スタブ
# ------------------------------------------------------------
def _install_env_stubs():
    class _Anything:
        def __init__(self, *a, **k):
            pass

        def __call__(self, *a, **k):
            return _Anything()

        def __getattr__(self, _n):
            return _Anything()

    tk = pytypes.ModuleType("tkinter")
    for attr in ("Tk", "Toplevel", "Frame", "Label", "Button", "Entry", "Checkbutton",
                 "OptionMenu", "StringVar", "BooleanVar", "LEFT", "END"):
        setattr(tk, attr, _Anything())
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
    tk.filedialog = filedialog
    tk.messagebox = messagebox
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox
    return messagebox


MESSAGEBOX = _install_env_stubs()

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Emu, Pt  # noqa: E402

# ------------------------------------------------------------
# 偽 gemini_client
# ------------------------------------------------------------
CAPTURED = {"calls": []}
RESPONDER = {"fn": None}


def _fake_generate_advanced(payload, model=None, **kwargs):
    CAPTURED["calls"].append({"payload": payload, "model": model})
    return RESPONDER["fn"](payload)


def _load(module_name, target=TARGET):
    sys.modules.pop("gemini_client", None)
    fake = pytypes.ModuleType("gemini_client")
    fake.generate_advanced = _fake_generate_advanced
    sys.modules["gemini_client"] = fake
    spec = importlib.util.spec_from_file_location(module_name, target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    stub = pytypes.ModuleType("time")
    stub.sleep = lambda _s: None
    stub.time = __import__("time").time
    mod.time = stub
    mod.gemini_client = mod._CommonGeminiClient()
    return mod


mod = _load("target_main")
HAS_OVERLAY = hasattr(mod, "_numbers_preserved")


class FakeProgress:
    class _W:
        def after(self, _ms, fn, *a):
            fn(*a)

    def __init__(self):
        self.window = self._W()
        self.updates = []
        self.closed = 0

    def update_progress(self, cur, total, status=""):
        self.updates.append((cur, total, status))

    def close(self):
        self.closed += 1


# ------------------------------------------------------------
# 合成スライド（正解の位置つき）
# ------------------------------------------------------------
def _font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


TR = {  # 訳文（日本語）
    "Executive Summary": "エグゼクティブサマリー",
    "Employee Engagement": "従業員エンゲージメント",
    "The Engagement Index is comprised of 4 questions.": "エンゲージメント指数は4つの質問で構成されています。",
    "Wellbeing": "ウェルビーイング",
    "Teamwork and Collaboration": "チームワークと協働",
    "Performance Management": "パフォーマンスマネジメント",
    "My Group": "自分のグループ",
    "Acme": "Acme",
}


def _tr(text):
    return TR.get(text, "訳文:" + text)


def make_slide_image(size=(1920, 1080), with_junk_left=False, marker=0):
    """合成スライドと、正解のブロック(px座標)を返す。
    blocks: 翻訳対象の文字。numbers: 数字だけのブロック（触ってはいけない）。"""
    W, H = size
    im = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    blocks, numbers = [], []

    def put(text, xy, font, fill, store, anchor_center_x=None):
        x, y = xy
        if anchor_center_x is not None:
            w = d.textlength(text, font=font)
            x = anchor_center_x - w / 2
        d.text((x, y), text, font=font, fill=fill)
        x0, y0, x1, y1 = d.textbbox((x, y), text, font=font)
        store.append({"text": text, "box": [x0, y0, x1, y1]})

    # 濃い帯(ヘッダー) — 白文字。帯の色は文字の色と大きく違う
    d.rectangle([0, 0, W, int(H * 0.09)], fill=(0, 112, 122))
    put("Executive Summary", (int(W * 0.02), int(H * 0.02)), _font(int(H * 0.05)), (255, 255, 255), blocks)

    # 見出し(青) と 段落(2行)
    put("Employee Engagement", (int(W * 0.03), int(H * 0.14)), _font(int(H * 0.028)), (20, 60, 160), blocks)
    put("The Engagement Index is comprised of 4 questions.",
        (int(W * 0.03), int(H * 0.20)), _font(int(H * 0.024)), (30, 30, 30), blocks)

    # 縞々の表: 行ごとに背景色が違う。左=ラベル、右=数字(触らない)
    row_h = int(H * 0.055)
    top = int(H * 0.32)
    labels = ["Wellbeing", "Teamwork and Collaboration", "Performance Management"]
    values = ["80%", "70%", "( n=5 )"]
    for i, (lab, val) in enumerate(zip(labels, values)):
        y0 = top + i * row_h
        d.rectangle([int(W * 0.03), y0, int(W * 0.47), y0 + row_h], fill=(249, 250, 249) if i % 2 == 0 else (255, 255, 255))
        put(lab, (int(W * 0.04), y0 + int(row_h * 0.2)), _font(int(H * 0.022)), (30, 30, 30), blocks)
        put(val, (int(W * 0.40), y0 + int(row_h * 0.2)), _font(int(H * 0.022)), (30, 30, 30), numbers)

    # 濃灰の帯の上の小さい見出し（中央寄せ）
    bx0, bx1 = int(W * 0.53), int(W * 0.97)
    d.rectangle([bx0, top, bx1, top + row_h], fill=(106, 106, 106))
    put("My Group", (0, top + int(row_h * 0.25)), _font(int(H * 0.02)), (20, 20, 40), blocks,
        anchor_center_x=(bx0 + bx1) / 2)

    # ロゴ風の図形(文字なし) と 固有名詞(訳さない)
    d.ellipse([int(W * 0.85), int(H * 0.15), int(W * 0.93), int(H * 0.15) + int(W * 0.08)], fill=(230, 70, 40))
    put("Acme", (int(W * 0.86), int(H * 0.30)), _font(int(H * 0.03)), (0, 112, 122), blocks)

    # スライドごとに違う画像にする目印（偽Geminiが送信画像のmd5でスライドを見分けるため）
    d.rectangle([W - 30, H - 30, W - 10, H - 10], fill=((marker * 37) % 256, (marker * 91) % 256, 200))

    if with_junk_left:  # トリミングで切り落とされる左端の文字
        put("JUNK", (int(W * 0.01), int(H * 0.60)), _font(int(H * 0.03)), (0, 0, 0), [])
    return im, blocks, numbers


def png_bytes(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def expected_response(blocks, numbers, size, crop=(0, 0, 0, 0), include_numbers=True, jitter=0, lines=None):
    """正解の位置を、トリミング後の画像に対する 0-1000 の座標に直して、Gemini の応答JSONにする。"""
    W, H = size
    l, t, r, b = crop
    cx0, cy0 = l * W, t * H
    cw, ch = W * (1 - l - r), H * (1 - t - b)
    out = []
    for blk in blocks + (numbers if include_numbers else []):
        x0, y0, x1, y1 = blk["box"]
        if x1 <= cx0 or x0 >= cx0 + cw:
            continue
        box = [round((y0 - cy0) / ch * 1000) - jitter, round((x0 - cx0) / cw * 1000) - jitter,
               round((y1 - cy0) / ch * 1000) + jitter, round((x1 - cx0) / cw * 1000) + jitter]
        is_num = blk in numbers
        out.append({"box_2d": box, "text": blk["text"],
                    "translation": blk["text"] if is_num else _tr(blk["text"]),
                    "lines": (lines or {}).get(blk["text"], 1)})
    return out


def gemini_reply(blocks_json):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(blocks_json, ensure_ascii=False)}]},
                            "finishReason": "STOP"}]}


def add_picture_slide(prs, im, left=0, top=0, width=None, height=None, crop=(0, 0, 0, 0), rotation=0):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    pic = slide.shapes.add_picture(io.BytesIO(png_bytes(im)), Emu(left), Emu(top),
                                   Emu(width if width is not None else prs.slide_width),
                                   Emu(height if height is not None else prs.slide_height))
    pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = crop
    if rotation:
        pic.rotation = rotation
    return slide, pic


def new_prs():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(11430000), Emu(6429375)
    return prs


def picture_md5(path, slide_idx=0):
    prs = Presentation(path)
    for sh in prs.slides[slide_idx].shapes:
        if sh.shape_type == 13:
            return hashlib.md5(sh.image.blob).hexdigest(), (sh.left, sh.top, sh.width, sh.height)
    return None, None


def notes_text(path, slide_idx):
    prs = Presentation(path)
    s = prs.slides[slide_idx]
    return s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""


def build_responder(deck_specs):
    """スライドの画像(送信JPEG)のmd5から、そのスライドの応答を引く偽Geminiを作る。"""
    table = {}
    for spec in deck_specs:
        jpeg, _ = mod._prepare_slide_image(spec["blob"], spec["crop"])
        table[hashlib.md5(jpeg).hexdigest()] = spec["reply"]

    def responder(payload):
        parts = payload["contents"][0]["parts"]
        inline = next(p["inlineData"] for p in parts if "inlineData" in p)
        import base64
        key = hashlib.md5(base64.b64decode(inline["data"])).hexdigest()
        reply = table[key]
        if callable(reply):
            return reply()
        return gemini_reply(reply)
    return responder


def run_flow(path, spec_value="", language="Japanese", m=None):
    """translate_ppt_document_thread を、確認ダイアログの答えを固定して実行する。"""
    m = m or mod
    MESSAGEBOX.CALLS.clear()
    captured = {}

    def fake_ask(pw, message, validate, initial=""):
        captured["message"] = message
        captured["validate"] = validate
        captured["initial"] = initial
        return spec_value
    m._ask_image_confirmation = fake_ask
    pw = FakeProgress()
    CAPTURED["calls"].clear()
    m.translate_ppt_document_thread(path, language, pw)
    return pw, captured


# ============================================================
# 1. 部品の単体検証
# ============================================================
# --- スライド指定 ---
check("parse_slide_spec: 空欄は None(全部)", mod.parse_slide_spec("  ", 24) is None)
check("parse_slide_spec: 単一", mod.parse_slide_spec("6", 24) == {5})
check("parse_slide_spec: 範囲と複数", mod.parse_slide_spec("1-3,5", 24) == {0, 1, 2, 4})
for bad, label in (("25", "範囲外"), ("0", "0番"), ("3-1", "逆順"), ("a", "文字"), ("1-2-3", "形式不正"), (",", "空要素のみ")):
    try:
        mod.parse_slide_spec(bad, 24)
        check(f"parse_slide_spec: {label}を弾く", False, "例外が出なかった")
    except ValueError:
        check(f"parse_slide_spec: {label}を弾く", True)

# --- 数字・記号だけのブロックを除く専用判定 ---
for t in ("80%", "60.0%", "( n=5 )", "( n=6,797 )", "65.8% (-15.8)", "1", "•", "12"):
    check(f"_has_letters: {t!r} は文字なし(除外)", mod._has_letters(t) is False)
for t in ("Favorability %", "Acme", "Top 5 Scoring Questions", "日本語のテキスト", "My Group"):
    check(f"_has_letters: {t!r} は文字あり(対象)", mod._has_letters(t) is True)
check("(参考)既存の is_translatable は '80%' を True にする=専用判定が必要な根拠",
      mod.is_translatable("80%") is True)

# --- 応答JSONの検証 ---
ok = mod._validate_image_blocks(json.dumps([
    {"box_2d": [10, 20, 30, 400], "text": "Hello", "translation": "こんにちは", "lines": 2}]))
check("_validate_image_blocks: 正常な応答", len(ok) == 1 and ok[0]["lines"] == 2 and ok[0]["box_2d"] == [10.0, 20.0, 30.0, 400.0])
check("_validate_image_blocks: 空配列は「文字なし」で例外にしない", mod._validate_image_blocks("[]") == [])
for label, raw in (("壊れたJSON", "[{"), ("配列でない", '{"a":1}'), ("文字列", '"x"')):
    try:
        mod._validate_image_blocks(raw)
        check(f"_validate_image_blocks: {label}は例外", False)
    except ValueError:
        check(f"_validate_image_blocks: {label}は例外", True)
zero = json.dumps([{"box_2d": [0, 0, 0, 0], "text": "A", "translation": "あ", "lines": 1}] * 3)
try:
    mod._validate_image_blocks(zero)
    check("_validate_image_blocks: 全ブロックの位置が0なら例外(文字なしと誤認しない)", False)
except ValueError:
    check("_validate_image_blocks: 全ブロックの位置が0なら例外(文字なしと誤認しない)", True)
mixed = mod._validate_image_blocks(json.dumps([
    {"box_2d": [0, 0, 0, 0], "text": "bad", "translation": "x", "lines": 1},
    {"box_2d": [10, 10, 50, 500], "text": "good", "translation": "良い", "lines": 1},
    {"box_2d": [10, 10], "text": "short", "translation": "x", "lines": 1},
    {"box_2d": [10, 10, 50, 500], "text": "", "translation": "x", "lines": 1}]))
check("_validate_image_blocks: 不正なブロックだけ捨てて残りを使う", [b["text"] for b in mixed] == ["good"])
clamped = mod._validate_image_blocks(json.dumps([
    {"box_2d": [-5, -5, 1200, 1300], "text": "edge", "translation": "端", "lines": 99}]))
check("_validate_image_blocks: 範囲外の座標は0-1000へ丸め、行数の異常値は1にする",
      clamped[0]["box_2d"] == [0.0, 0.0, 1000.0, 1000.0] and clamped[0]["lines"] == 1)

# --- 画像の準備 ---
big, _, _ = make_slide_image((3200, 1800))
jpeg, prepared = mod._prepare_slide_image(png_bytes(big), (0, 0, 0, 0))
check("_prepare_slide_image: 幅1600pxへ縮小しJPEGにする",
      prepared.width == 1600 and prepared.height == 900 and jpeg[:2] == b"\xff\xd8",
      f"size={prepared.size}, bytes={len(jpeg)}")
small_im, _, _ = make_slide_image((1000, 600))
_, prepared_small = mod._prepare_slide_image(png_bytes(small_im), (0, 0, 0, 0))
check("_prepare_slide_image: 小さい画像は拡大しない", prepared_small.size == (1000, 600))
_, prepared_crop = mod._prepare_slide_image(png_bytes(small_im), (0.1, 0.0, 0.2, 0.5))
check("_prepare_slide_image: トリミングを反映する(幅70%・高さ50%)", prepared_crop.size == (700, 300),
      f"size={prepared_crop.size}")
rgba = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
_, prepared_alpha = mod._prepare_slide_image(png_bytes(rgba), (0, 0, 0, 0))
check("_prepare_slide_image: 透明部分は黒でなく白にする", prepared_alpha.getpixel((10, 10)) == (255, 255, 255))

# ============================================================
# 2. シム拡張(画像の受け口)
# ============================================================
prev = _load("target_prev", PREV_TARGET)
seen = {}


def _capture_into(name):
    def f(payload, model=None):
        seen[name] = json.dumps({"payload": payload, "model": model}, sort_keys=True, ensure_ascii=False)
        return {"candidates": [{"content": {"parts": [{"text": "x"}]}}]}
    return f


mod._generate_advanced = _capture_into("new")
prev._generate_advanced = _capture_into("old")
safety = [{"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}]
same = True
for kwargs in (dict(temperature=0.1, safety_settings=safety),
               dict(temperature=0.1, system_instruction="s", response_mime_type="application/json",
                    response_schema={"type": "ARRAY"}),
               dict()):
    prev._CommonGeminiClient().models.generate_content(model="m", contents="hello", config=prev._GeminiGenerateConfig(**kwargs))
    mod._CommonGeminiClient().models.generate_content(model="m", contents="hello", config=mod._GeminiGenerateConfig(**kwargs))
    same &= seen["old"] == seen["new"]
check("シム: contents が str のとき payload が直前版と完全一致(従来の翻訳に影響しない)", same)
prev._CommonGeminiClient().models.generate_content(model="m", contents="hello", config=None)
mod._CommonGeminiClient().models.generate_content(model="m", contents="hello", config=None)
check("シム: config が None でも従来と完全一致", seen["old"] == seen["new"])

mod._CommonGeminiClient().models.generate_content(
    model="gemini-2.5-flash",
    contents=[{"inlineData": {"mimeType": "image/jpeg", "data": "AAAA"}}, "translate"],
    config=mod._GeminiGenerateConfig(temperature=0, max_output_tokens=123, thinking_budget=0,
                                     response_mime_type="application/json"))
p = json.loads(seen["new"])["payload"]
check("シム: contents が list のとき画像パーツとテキストパーツになる",
      p["contents"][0]["parts"] == [{"inlineData": {"mimeType": "image/jpeg", "data": "AAAA"}}, {"text": "translate"}])
check("シム: maxOutputTokens が generationConfig に載る", p["generationConfig"]["maxOutputTokens"] == 123)
check("シム: thinkingBudget=0 が thinkingConfig に載る(0も落とさない)",
      p["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0})
mod._CommonGeminiClient().models.generate_content(model="m", contents="x", config=mod._GeminiGenerateConfig(temperature=0.1))
p2 = json.loads(seen["new"])["payload"]
check("シム: 未指定なら maxOutputTokens / thinkingConfig を載せない",
      "maxOutputTokens" not in p2["generationConfig"] and "thinkingConfig" not in p2["generationConfig"])
mod._generate_advanced = _fake_generate_advanced

# ============================================================
# 3. 対象スライドの判定
# ============================================================
prs = new_prs()
im1, blocks1, nums1 = make_slide_image()
add_picture_slide(prs, im1)                                                     # 0: 対象
s1, _ = add_picture_slide(prs, im1)                                             # 1: 対象(ページ番号だけのテキスト付き)
tb = s1.shapes.add_textbox(Emu(100), Emu(100), Emu(500000), Emu(300000)); tb.text_frame.text = "12"
add_picture_slide(prs, im1, width=int(prs.slide_width * 0.6), height=int(prs.slide_height * 0.6))   # 2: 70%未満
s3, _ = add_picture_slide(prs, im1)                                             # 3: 大きい画像が2枚
s3.shapes.add_picture(io.BytesIO(png_bytes(im1)), Emu(0), Emu(0), prs.slide_width, prs.slide_height)
add_picture_slide(prs, im1, rotation=15)                                        # 4: 回転
s5, _ = add_picture_slide(prs, im1)                                             # 5: 文字あり(英文)
tb = s5.shapes.add_textbox(Emu(100), Emu(100), Emu(5000000), Emu(300000)); tb.text_frame.text = "This slide has real text"
add_picture_slide(prs, im1, left=-int(prs.slide_width * 0.05), width=int(prs.slide_width * 1.1))    # 6: はみ出しても70%以上
found = mod.find_image_slides(prs)
check("find_image_slides: 対象は 0,1,6 の3枚", [i for i, _ in found] == [0, 1, 6], f"{[i for i, _ in found]}")
check("find_image_slides: ページ番号だけの文字は「文字なし」扱い(スライド2が対象)", 1 in [i for i, _ in found])
check("find_image_slides: 70%未満・画像2枚・回転・文字ありは対象外", not ({2, 3, 4, 5} & {i for i, _ in found}))

# ============================================================
# 4. エンドツーエンド(ノート追記)
# ============================================================
def build_deck(path, n_slides=3, with_notes_on=None, crop_slide=None):
    """n_slides枚の画像スライドの資料を作り、偽Geminiの表を返す。"""
    prs = new_prs()
    specs, truth = [], []
    for i in range(n_slides):
        crop = (0.1, 0.0, 0.0, 0.0) if i == crop_slide else (0, 0, 0, 0)
        im, blocks, nums = make_slide_image(with_junk_left=(i == crop_slide), marker=i + 1)
        slide, pic = add_picture_slide(prs, im, crop=crop)
        if with_notes_on is not None and i == with_notes_on:
            slide.notes_slide.notes_text_frame.text = "備考"   # 2文字=翻訳対象にならない短いメモ
        reply = expected_response(blocks, nums, im.size, crop)
        specs.append({"blob": png_bytes(im), "crop": crop, "reply": reply})
        truth.append((blocks, nums, im.size, crop))
    prs.save(path)
    return specs, truth


tmp = tempfile.mkdtemp()
cwd0 = os.getcwd()
os.chdir(tmp)
try:
    src = os.path.join(tmp, "deck.pptx")
    specs, truth = build_deck(src, 3, with_notes_on=1)
    RESPONDER["fn"] = build_responder(specs)
    orig_md5 = [picture_md5(src, i) for i in range(3)]
    orig_bytes = open(src, "rb").read()

    pw, cap = run_flow(src, "")
    out = os.path.join(tmp, "deck_ja.pptx")
    check("出力ファイル名が 元_ja.pptx", os.path.isfile(out))
    check("元のPPTXは変更されない", open(src, "rb").read() == orig_bytes)
    check("エラーダイアログが出ていない", not any(c[0] == "error" for c in MESSAGEBOX.CALLS), f"{MESSAGEBOX.CALLS}")
    check("確認ダイアログの文言に「画像そのものを外部AIへ送信」が明記される",
          "画像そのもの" in cap["message"] and "外部AI" in cap["message"] and "Gemini" in cap["message"])
    check("確認ダイアログの文言に「機密・個人情報」の注意がある", "機密" in cap["message"])
    check("確認ダイアログの文言に対象枚数(3枚)が出る", "3 枚" in cap["message"])
    check("Gemini呼び出しはスライド数と同じ3回(1枚1回)", len(CAPTURED["calls"]) == 3, f"{len(CAPTURED['calls'])}")

    call = CAPTURED["calls"][0]
    pl = call["payload"]
    parts = pl["contents"][0]["parts"]
    check("payload: model が明示的に渡る", call["model"] == "gemini-2.5-flash", f"{call['model']!r}")
    check("payload: 画像は image/jpeg のinlineData", parts[0]["inlineData"]["mimeType"] == "image/jpeg")
    check("payload: 画像のあとにプロンプトのテキストが続く", "text" in parts[1] and "translate" in parts[1]["text"].lower())
    check("payload: 翻訳先言語がプロンプトに入る", "Japanese" in parts[1]["text"])
    gc = pl["generationConfig"]
    check("payload: JSONモードとスキーマが載る(項目順 box_2d→text→translation→lines[→bold→align])",
          gc["responseMimeType"] == "application/json"
          and gc["responseSchema"]["items"]["propertyOrdering"]
          == (["box_2d", "text", "translation", "lines", "bold", "align"] if VERSION >= "03"
              else ["box_2d", "text", "translation", "lines"]))
    check("payload: maxOutputTokens と thinkingBudget=0(2.5-flash)", gc["maxOutputTokens"] > 0
          and gc["thinkingConfig"] == {"thinkingBudget": 0})
    check("payload: safetySettings が4カテゴリ載る", len(pl["safetySettings"]) == 4)
    check("payload: json.dumps 可能で、送る画像は約1MB未満(base64)",
          len(json.dumps(pl)) < 1_000_000, f"{len(json.dumps(pl))} bytes")
    check("プロンプトに「数字だけは返さない・ロゴ除外・固有名詞は訳さない」が入る",
          all(k in parts[1]["text"] for k in ("only numbers", "logos", "proper nouns")))

    n0 = notes_text(out, 0)
    check("スライド1: メモ欄に見出しと訳文が入る",
          "【画像内テキストの翻訳】" in n0 and "エグゼクティブサマリー" in n0 and "ウェルビーイング" in n0)
    check("メモ欄に原文も併記される", "（原文: Executive Summary）" in n0)
    check("数字だけのブロック(80%)はメモ欄に入らない", "80%" not in n0 and "n=5" not in n0)
    check("訳文が原文と同じ固有名詞(Acme)はメモ欄に入らない", "Acme" not in n0)
    n1 = notes_text(out, 1)
    check("既存のメモは消えず、区切り線のあとに追記される",
          n1.startswith("備考") and "----------" in n1 and "【画像内テキストの翻訳】" in n1)
    check("元の画像は3枚とも位置・バイト列が完全に同じ",
          [picture_md5(out, i) for i in range(3)] == orig_md5)
    check("スライド枚数は変わらない", len(Presentation(out).slides) == 3)
    check("完了ダイアログ: 翻訳したスライド3枚と「AIによる翻訳です」の注意",
          any("翻訳したスライド: 3枚" in c[2] and "確認してください" in c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"),
          f"{MESSAGEBOX.CALLS}")

    try:
        cap["validate"]("99")
        check("確認ダイアログの入力検証: 範囲外を弾く", False)
    except ValueError:
        check("確認ダイアログの入力検証: 範囲外を弾く", True)

    # --- ログに原文を書かない ---
    handlers = logging.getLogger("PPT_Translation").handlers
    log_path = next(h.baseFilename for h in handlers if hasattr(h, "baseFilename"))
    log_text = open(log_path, encoding="utf-8").read()
    secrets = ["Executive Summary", "Employee Engagement", "Wellbeing", "Performance Management", "エグゼクティブ"]
    check("ログに原文・訳文を書かない(件数とスライド番号だけ)",
          not any(s in log_text for s in secrets) and "スライド 1 成功" in log_text,
          "漏れ: " + str([s for s in secrets if s in log_text]))

    # --- 範囲指定: 2枚目だけ ---
    if os.path.exists(out):
        os.remove(out)
    pw, cap = run_flow(src, "2")
    check("範囲指定「2」: Gemini呼び出しは1回だけ", len(CAPTURED["calls"]) == 1, f"{len(CAPTURED['calls'])}")
    check("範囲指定「2」: 2枚目だけメモが付き、1枚目・3枚目には付かない",
          "【画像内テキストの翻訳】" in notes_text(out, 1)
          and "【画像内テキストの翻訳】" not in notes_text(out, 0)
          and "【画像内テキストの翻訳】" not in notes_text(out, 2))

    # --- キャンセル ---
    if os.path.exists(out):
        os.remove(out)
    pw, cap = run_flow(src, None)
    check("キャンセル: Geminiを呼ばない", len(CAPTURED["calls"]) == 0)
    check("キャンセル: 未翻訳のコピー(_ja.pptx)を残さない", not os.path.exists(out))
    check("キャンセル: 元ファイルは無傷", open(src, "rb").read() == orig_bytes)
    check("キャンセル: 進捗ウィンドウを閉じる", pw.closed >= 1)

    # --- 翻訳済みファイルを再度読み込んだ場合 ---
    # メモ欄に訳文(文字)が入っているため「文字あり」の資料として従来経路になる。
    # 画像は送らず、確認ダイアログも出ない。画像の訳が二重に書かれることはない。
    run_flow(src, "")
    twice_src = os.path.join(tmp, "twice.pptx")
    shutil.copy(out, twice_src)
    pw, cap = run_flow(twice_src, "")
    check("翻訳済みのファイルを再度読み込んでも、画像は送らず確認ダイアログも出ない(従来経路)",
          "message" not in cap
          and all("inlineData" not in json.dumps(c["payload"]) for c in CAPTURED["calls"]),
          f"{len(CAPTURED['calls'])}回")
    check("翻訳済みのファイルを再度読み込んでも、画像の訳が二重に書かれない",
          notes_text(os.path.join(tmp, "twice_ja.pptx"), 0).count("【画像内テキストの翻訳】") <= 1)
    dup_prs = Presentation(out)
    check("メモ追記の二重防止: 見出しが既にあれば追記しない",
          mod._append_image_notes(dup_prs.slides[0], mod._validate_image_blocks(json.dumps(specs[0]["reply"]))) == 0)

    # --- トリミングされた画像 ---
    crop_src = os.path.join(tmp, "crop.pptx")
    cspecs, ctruth = build_deck(crop_src, 2, crop_slide=1)
    RESPONDER["fn"] = build_responder(cspecs)
    run_flow(crop_src, "")
    crop_out = os.path.join(tmp, "crop_ja.pptx")
    n_crop = notes_text(crop_out, 1)
    check("トリミングされた画像: 切り落とされた左端の文字(JUNK)はメモに入らず、見えている文字は入る",
          "JUNK" not in n_crop and "エグゼクティブサマリー" in n_crop)

    # --- 失敗の扱い ---
    fdeck = os.path.join(tmp, "fail.pptx")
    fspecs, _ = build_deck(fdeck, 6)
    calls_by_slide = {"n": 0}

    def make_fail_from(k):
        results = []
        for i, spec in enumerate(fspecs):
            if i < k:
                results.append(spec["reply"])
            else:
                results.append(lambda: (_ for _ in ()).throw(RuntimeError("proxy down")))
        for spec, r in zip(fspecs, results):
            spec["reply"] = r
    orig_replies = [s["reply"] for s in fspecs]
    make_fail_from(2)
    RESPONDER["fn"] = build_responder(fspecs)
    mod.IMAGE_WORKERS = 1
    run_flow(fdeck, "")
    fout = os.path.join(tmp, "fail_ja.pptx")
    info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
    check("3枚連続失敗: 中断して、それまでに終わったスライド(1,2枚目)は保存する",
          os.path.exists(fout) and "【画像内テキストの翻訳】" in notes_text(fout, 0)
          and "【画像内テキストの翻訳】" in notes_text(fout, 1), info)
    check("3枚連続失敗: 失敗した3枚の番号(3,4,5)を結果に出し、中断したと知らせる",
          "3, 4, 5" in info and "中断" in info, info)
    check("3枚連続失敗: 4枚目以降はもう呼ばない(3枚目までで各3回リトライ=計2+9回)",
          len(CAPTURED["calls"]) == 2 + 9, f"{len(CAPTURED['calls'])}")
    check("失敗したスライドは無加工のまま", "【画像内テキストの翻訳】" not in notes_text(fout, 2))
    check("失敗の案内に「範囲に番号を入力して再試行」が書かれる", "再試行" in info)
    mod.IMAGE_WORKERS = 2

    # 途中だけ失敗(連続ではない) → 中断せず続行
    for spec, r in zip(fspecs, orig_replies):
        spec["reply"] = r
    fspecs[2]["reply"] = lambda: (_ for _ in ()).throw(RuntimeError("one bad slide"))
    RESPONDER["fn"] = build_responder(fspecs)
    mod.IMAGE_WORKERS = 1
    run_flow(fdeck, "")
    info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
    check("1枚だけ失敗: 中断せず残りを続け、失敗した番号(3)を結果に出す",
          "番号: 3）" in info and "中断" not in info
          and "【画像内テキストの翻訳】" in notes_text(fout, 5), info)
    mod.IMAGE_WORKERS = 2

    # --- 応答の異常 ---
    sdeck = os.path.join(tmp, "one.pptx")
    sspecs, _ = build_deck(sdeck, 1)

    def run_single(reply):
        sspecs[0]["reply"] = reply
        RESPONDER["fn"] = build_responder(sspecs)
        CAPTURED["calls"].clear()
        run_flow(sdeck, "")
        return next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")

    info = run_single([])
    check("応答が空配列: 「文字が見つからなかった」と通知し、失敗扱いにしない",
          "文字が見つからなかったスライド: 1枚" in info and "失敗" not in info, info)
    check("応答が空配列: メモ欄は作らない", "【画像内テキストの翻訳】" not in notes_text(os.path.join(tmp, "one_ja.pptx"), 0))

    info = run_single([{"box_2d": [0, 0, 0, 0], "text": "A", "translation": "あ", "lines": 1}] * 3)
    check("全ブロックの位置が0: 3回リトライして失敗として通知", len(CAPTURED["calls"]) == 3 and "失敗したスライド: 1枚" in info, info)

    seq = {"n": 0}

    def flaky():
        seq["n"] += 1
        if seq["n"] == 1:
            return {"candidates": [{"content": {"parts": [{"text": "[{\"box"}]}, "finishReason": "MAX_TOKENS"}]}
        return gemini_reply(expected_response(*truth[0][:2], truth[0][2], (0, 0, 0, 0)))
    info = run_single(flaky)
    check("途中で切れたJSON(MAX_TOKENS)は再試行して成功する", seq["n"] == 2 and "翻訳したスライド: 1枚" in info, info)

    info = run_single(lambda: {"candidates": [{"content": {"parts": []}}]})
    check("空応答(セーフティ等): 3回リトライして失敗として通知", len(CAPTURED["calls"]) == 3 and "失敗したスライド: 1枚" in info, info)

    # --- 混在資料・画像だけでない資料 ---
    mixed = new_prs()
    ms, _ = add_picture_slide(mixed, im1)
    tb = ms.shapes.add_textbox(Emu(100), Emu(100), Emu(5000000), Emu(300000)); tb.text_frame.text = "Quarterly results overview"
    add_picture_slide(mixed, im1)
    mixed_path = os.path.join(tmp, "mixed.pptx")
    mixed.save(mixed_path)

    def text_responder(payload):
        text = payload["contents"][0]["parts"][0]["text"]
        n = text.count("[")
        return {"candidates": [{"content": {"parts": [{"text": "\n".join(f"[{i}] 訳文{i}" for i in range(1, n + 1))}]}}]}
    RESPONDER["fn"] = text_responder
    pw, cap = run_flow(mixed_path, "")
    info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
    check("混在資料: 従来の翻訳が動き、確認ダイアログ(画像送信)は出ない", "message" not in cap and "翻訳項目数: 1" in info, info)
    check("混在資料: 完了メッセージに「画像だけのスライドが1枚あります(未翻訳)」と出る",
          "画像だけのスライドが 1 枚" in info and "未翻訳" in info, info)
    check("混在資料: 画像はGeminiへ送らない(文字のテキストだけ)",
          all("inlineData" not in json.dumps(c["payload"]) for c in CAPTURED["calls"]))
    check("混在資料: 従来どおり文字が書き戻される",
          Presentation(os.path.join(tmp, "mixed_ja.pptx")).slides[0].shapes[-1].text_frame.text == "訳文1")

    textonly = new_prs()
    ts = textonly.slides.add_slide(textonly.slide_layouts[6])
    tb = ts.shapes.add_textbox(Emu(100), Emu(100), Emu(5000000), Emu(300000)); tb.text_frame.text = "Only text here"
    tpath = os.path.join(tmp, "textonly.pptx"); textonly.save(tpath)
    pw, cap = run_flow(tpath, "")
    info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
    check("文字だけの資料: 完了メッセージに画像の注意書きが出ない(従来と同じ)", "画像だけ" not in info and "翻訳項目数: 1" in info, info)

    empty = new_prs(); empty.slides.add_slide(empty.slide_layouts[6])
    epath = os.path.join(tmp, "empty.pptx"); empty.save(epath)
    pw, cap = run_flow(epath, "")
    info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
    check("文字も画像も無い資料: 従来のメッセージのまま(余計な案内を出さない)",
          info == "翻訳対象のテキストが見つかりませんでした。", info)

    part = new_prs(); add_picture_slide(part, im1, width=int(part.slide_width * 0.5), height=int(part.slide_height * 0.5))
    ppath = os.path.join(tmp, "partial.pptx"); part.save(ppath)
    pw, cap = run_flow(ppath, "")
    info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
    check("画像が全面でない資料: 「対象は画面の7割以上を覆う画像」と案内して終了し、Geminiを呼ばない",
          "7割以上" in info and len(CAPTURED["calls"]) == 0, info)

    # --- 画像スライドのメモに「翻訳対象になる文章」がある資料 ---
    notes_deck = new_prs()
    ns_, _ = add_picture_slide(notes_deck, im1)
    ns_.notes_slide.notes_text_frame.text = "Please mention the survey response rate"
    add_picture_slide(notes_deck, im1)
    notes_path = os.path.join(tmp, "notesdeck.pptx"); notes_deck.save(notes_path)
    RESPONDER["fn"] = text_responder
    pw, cap = run_flow(notes_path, "")
    info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
    check("メモに文章がある画像スライド: 従来経路でメモを翻訳し、画像は送らない(確認ダイアログも出ない)",
          "message" not in cap and "翻訳項目数: 1" in info
          and all("inlineData" not in json.dumps(c["payload"]) for c in CAPTURED["calls"]), info)
    check("メモに文章がある画像スライド: 「画像だけのスライドが2枚あります(未翻訳)」と知らせる",
          "画像だけのスライドが 2 枚" in info and "未翻訳" in info, info)

    # --- 文字ありの経路が直前版と同一挙動 ---
    RESPONDER["fn"] = text_responder
    tdeck = new_prs()
    tsl = tdeck.slides.add_slide(tdeck.slide_layouts[6])
    tb = tsl.shapes.add_textbox(Emu(100), Emu(100), Emu(5000000), Emu(900000))
    tb.text_frame.text = "First paragraph of text"
    r = tb.text_frame.paragraphs[0].runs[0]; r.font.size = Pt(18); r.font.bold = True
    tsl.notes_slide.notes_text_frame.text = "Speaker notes are here"
    tdpath = os.path.join(tmp, "textdeck.pptx"); tdeck.save(tdpath)

    def text_signature(path):
        prs_ = Presentation(path)
        out_ = []
        for s in prs_.slides:
            for sh in s.shapes:
                if sh.has_text_frame:
                    for para in sh.text_frame.paragraphs:
                        for run in para.runs:
                            out_.append((run.text, run.font.size.pt if run.font.size else None, run.font.bold, run.font.name))
            if s.has_notes_slide:
                out_.append(("notes", s.notes_slide.notes_text_frame.text))
        return out_
    prev._ask_image_confirmation = lambda *a: ""
    prev.gemini_client = prev._CommonGeminiClient()
    prev._generate_advanced = _fake_generate_advanced
    shutil.copy(tdpath, os.path.join(tmp, "textdeck_prev.pptx"))
    prev.translate_ppt_document_thread(os.path.join(tmp, "textdeck_prev.pptx"), "Japanese", FakeProgress())
    mod.translate_ppt_document_thread(tdpath, "Japanese", FakeProgress())
    check("文字ありの資料: 直前版(20260911_01)と出力(文字・書式・ノート・フォント)が完全一致",
          text_signature(os.path.join(tmp, "textdeck_prev_ja.pptx")) == text_signature(os.path.join(tmp, "textdeck_ja.pptx")),
          f"{text_signature(os.path.join(tmp, 'textdeck_ja.pptx'))}")
finally:
    os.chdir(cwd0)
    shutil.rmtree(tmp, ignore_errors=True)

# ============================================================
# 5. 変更範囲(AST): 文字ありの翻訳経路が未変更であること
# ============================================================
import ast


def qualified_hashes(path):
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines()
    out = {}

    def walk(node, prefix=""):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + n.name
                out[q] = hashlib.md5("\n".join(lines[n.lineno - 1:n.end_lineno]).encode()).hexdigest()
                if isinstance(n, ast.ClassDef):
                    walk(n, q + ".")
    walk(ast.parse(src))
    return out


a, b = qualified_hashes(PREV_TARGET), qualified_hashes(TARGET)
changed = {k for k in a if k in b and a[k] != b[k]}
allowed = {"_CommonGeminiModels", "_CommonGeminiModels.generate_content", "_GeminiGenerateConfig",
           "_GeminiGenerateConfig.__init__", "translate_ppt_document_thread"}
check("AST: 直前版から変わった既存の定義は、シム(画像の受け口)と分岐点だけ", changed <= allowed, f"changed={sorted(changed)}")
for keep in ("translate_batch_gemini", "translate_super_fast_parallel", "is_translatable", "lang_to_suffix",
             "init_gemini", "check_dependencies", "select_file", "WordProgressWindow"):
    check(f"AST: {keep} は直前版と完全一致", keep in a and a[keep] == b.get(keep))

# ============================================================
# 5b. 20260930_03 で追加した部品(文字の塊へのスナップ・1行維持・確認画面の初期値・デバッグ出力)
# ============================================================
def run_v03_tests():
    from PIL import ImageChops

    # --- 応答の検証: bold / align ---
    v = mod._validate_image_blocks(json.dumps([
        {"box_2d": [10, 10, 50, 500], "text": "Head", "translation": "見出し", "lines": 1, "bold": True, "align": "center"},
        {"box_2d": [10, 10, 50, 500], "text": "Body", "translation": "本文", "lines": 1, "bold": "yes", "align": "middle"},
        {"box_2d": [10, 10, 50, 500], "text": "None", "translation": "無し", "lines": 1}]))
    check("応答の検証: bold は真偽値だけ受け取り、それ以外は False", [b["bold"] for b in v] == [True, False, False])
    check("応答の検証: align は left/center/right だけ受け取り、それ以外は left",
          [b["align"] for b in v] == ["center", "left", "left"])
    sc = mod.IMAGE_RESPONSE_SCHEMA["items"]
    check("スキーマ: bold は BOOLEAN、align は left/center/right の列挙で、必須項目",
          sc["properties"]["bold"]["type"] == "BOOLEAN" and sc["properties"]["align"]["enum"] == ["left", "center", "right"]
          and "bold" in sc["required"] and "align" in sc["required"])
    check("プロンプトに bold と align の説明が入る", "bold:" in mod._build_image_prompt("Japanese")
          and "align:" in mod._build_image_prompt("Japanese"))

    # --- 水平方向の膨らませ ---
    m0 = Image.new("L", (20, 5), 0)
    m0.putpixel((5, 2), 255); m0.putpixel((8, 2), 255)
    d = mod._dilate_horizontal(m0, 2)
    check("水平の膨らませ: 3px離れた2点(間が2px)がつながる", all(d.getpixel((x, 2)) for x in range(3, 11)))
    check("水平の膨らませ: 縦には広がらない", d.getpixel((5, 1)) == 0 and d.getpixel((5, 3)) == 0)
    m1 = Image.new("L", (10, 3), 0)
    m1.putpixel((0, 1), 255)
    d1 = mod._dilate_horizontal(m1, 3)
    check("水平の膨らませ: 画像の端で反対側へ回り込まない", d1.getpixel((9, 1)) == 0 and d1.getpixel((7, 1)) == 0)

    # --- 文字の塊へのスナップ ---
    def text_image(size=(400, 120), items=(("Hello World", (50, 40)),), fsize=26, bg=(255, 255, 255), fg=(0, 0, 0)):
        im_ = Image.new("RGB", size, bg)
        dr = ImageDraw.Draw(im_)
        boxes_ = []
        for txt, xy in items:
            dr.text(xy, txt, font=_font(fsize), fill=fg)
            boxes_.append(list(dr.textbbox(xy, txt, font=_font(fsize))))
        return im_, boxes_

    im_s, (tb_s,) = text_image()
    th = tb_s[3] - tb_s[1]
    small = [tb_s[0] + 20, tb_s[1] + 0.3 * th, tb_s[2] - 20, tb_s[3] - 0.3 * th]   # 文字より小さく内側に寄った箱
    snapped = mod._snap_to_ink(im_s, small, (255, 255, 255), 1, [0, 0, 400, 120])
    ink_truth = ImageChops.difference(im_s, Image.new("RGB", im_s.size, (255, 255, 255))).getbbox()   # 実際のインクの範囲
    pad = mod.IMAGE_SNAP_PAD_PX   # 薄いアンチエイリアスの縁(しきい値未満)は、四角の余白で覆う
    check("スナップ: 文字より小さい箱でも、実際のインクの範囲まで広がる(余白込みで縁まで覆う・3px以内)",
          snapped is not None and all(abs(a_ - b_) <= 3 for a_, b_ in zip(snapped, ink_truth))
          and snapped[0] - pad <= ink_truth[0] and snapped[1] - pad <= ink_truth[1]
          and snapped[2] + pad >= ink_truth[2] and snapped[3] + pad >= ink_truth[3], f"{snapped} vs {ink_truth}")
    check("スナップ: 文字の外(余白)まで広げすぎない(各辺6px以内)",
          snapped is not None and snapped[0] >= tb_s[0] - 6 and snapped[2] <= tb_s[2] + 6
          and snapped[1] >= tb_s[1] - 6 and snapped[3] <= tb_s[3] + 6, f"{snapped}")
    im_s2, (a_s, b_s) = text_image(size=(700, 120), items=(("Hello World", (30, 40)), ("Faraway", (520, 40))))
    box_a = [a_s[0] + 10, a_s[1] + 2, a_s[2] - 10, a_s[3] - 2]
    sn2 = mod._snap_to_ink(im_s2, box_a, (255, 255, 255), 1, [0, 0, 700, 120])
    check("スナップ: 離れた別の文字(Faraway)は巻き込まない", sn2 is not None and sn2[2] < b_s[0] - 20, f"{sn2}")
    limited = mod._snap_to_ink(im_s, small, (255, 255, 255), 1, [0, 0, tb_s[0] + 60, 120])
    check("スナップ: 上限(limit)の外には出ない", limited is not None and limited[2] <= tb_s[0] + 60, f"{limited}")
    blob = Image.new("RGB", (400, 120), (255, 255, 255))
    ImageDraw.Draw(blob).rectangle([20, 30, 380, 90], fill=(0, 0, 0))
    check("スナップ: 極端に大きい塊(棒グラフ・罫線など)は無視する",
          mod._snap_to_ink(blob, [100, 50, 140, 70], (255, 255, 255), 1, [0, 0, 400, 120]) is None)
    check("スナップ: インクが無ければ None",
          mod._snap_to_ink(Image.new("RGB", (100, 50), (255, 255, 255)), [10, 10, 60, 30], (255, 255, 255), 1, [0, 0, 100, 50]) is None)
    im_w, (tw,) = text_image(items=(("Header", (60, 40)),), fsize=30, bg=(0, 112, 122), fg=(255, 255, 255))
    hw = tw[3] - tw[1]
    sn_w = mod._snap_to_ink(im_w, [tw[0], tw[1] + 0.4 * hw, tw[2], tw[3]], (0, 112, 122), 1, [0, 0, 400, 120])
    check("スナップ: 濃い帯の上の白い文字でも、箱の上に飛び出した上部まで届く(実機で残った例)",
          sn_w is not None and sn_w[1] <= tw[1] + 1, f"{sn_w} vs {tw}")

    # --- 背景色の推定(箱が文字より小さくても、文字の色を背景と取り違えない) ---
    bar = Image.new("RGB", (420, 90), (255, 255, 255))
    dbar = ImageDraw.Draw(bar)
    dbar.rectangle([0, 0, 420, 62], fill=(0, 112, 122))
    dbar.text((20, 8), "HEADER TEXT", font=_font(38), fill=(255, 255, 255))
    tbb = dbar.textbbox((20, 8), "HEADER TEXT", font=_font(38))
    hh = tbb[3] - tbb[1]
    small_box = [tbb[0] + 6, tbb[1] + 0.3 * hh, tbb[2] - 6, tbb[3] - 0.1 * hh]   # 白い文字の中にほぼ収まる小さい箱
    bg_est = mod._estimate_background(bar, small_box)
    check("背景色の推定: 濃い帯の上の白い大きな文字で、箱が文字より小さくても、帯の色(白でなく)を返す",
          max(abs(a_ - b_) for a_, b_ in zip(bg_est, (0, 112, 122))) <= 8, f"{bg_est}")
    stripe = Image.new("RGB", (300, 90), (255, 255, 255))
    dstripe = ImageDraw.Draw(stripe)
    dstripe.rectangle([0, 30, 300, 60], fill=(249, 250, 249))
    dstripe.text((20, 36), "Label", font=_font(16), fill=(30, 30, 30))
    sb = dstripe.textbbox((20, 36), "Label", font=_font(16))
    check("背景色の推定: 縞々の行の上の文字は、その行の色を返す",
          max(abs(a_ - b_) for a_, b_ in zip(mod._estimate_background(stripe, sb), (249, 250, 249))) <= 4)

    # --- 1行維持のサイズ決定 ---
    s_single = mod._fit_font_size("ウェルビーイング", 70, 30, 10, single_line=True)
    s_multi = mod._fit_font_size("ウェルビーイング", 70, 30, 10, single_line=False)
    check("サイズ: 原文が1行なら、折り返す前に縮めて1行に収める",
          s_single is not None and mod._estimate_lines("ウェルビーイング", s_single, 70) == 1 and 7.5 <= s_single < 10,
          f"single={s_single}")
    check("サイズ: 従来(single_line=False)は大きさを優先して折り返す",
          s_multi == 10.0 and mod._estimate_lines("ウェルビーイング", s_multi, 70) == 2, f"multi={s_multi}")
    s_fallback = mod._fit_font_size("ウェルビーイング", 40, 30, 10, single_line=True)
    check("サイズ: 75%まで縮めても1行に収まらなければ、折り返しを許して従来どおり決める",
          s_fallback is not None and mod._estimate_lines("ウェルビーイング", s_fallback, 40) >= 2, f"{s_fallback}")

    # --- 確認画面の初期値・デバッグ出力 ---
    tmp3 = tempfile.mkdtemp()
    cwd3 = os.getcwd()
    os.chdir(tmp3)
    try:
        prs_i = new_prs()
        imx, bx, nx = make_slide_image(marker=1)
        add_picture_slide(prs_i, imx, width=int(prs_i.slide_width * 0.5), height=int(prs_i.slide_height * 0.5))   # 1枚目: 対象外
        imy, by, ny = make_slide_image(marker=2)
        add_picture_slide(prs_i, imy)                                                                        # 2枚目: 対象
        ipath = os.path.join(tmp3, "init.pptx"); prs_i.save(ipath)
        RESPONDER["fn"] = build_responder([{"blob": png_bytes(imy), "crop": (0, 0, 0, 0),
                                            "reply": expected_response(by, ny, imy.size)}])
        pw_i, cap_i = run_flow(ipath, "")
        check("確認画面: 初期値は、先頭の対象スライドの番号(ここでは2)", cap_i.get("initial") == "2", f"{cap_i.get('initial')!r}")
        check("確認画面: 文言に、先頭1枚が入っていることと、全部は欄を空にすることが書かれる",
              "先頭の1枚（スライド2）" in cap_i["message"] and "欄を空にして" in cap_i["message"], cap_i["message"])

        # デバッグ出力
        dpath = os.path.join(tmp3, "dbg.pptx")
        dspecs, dtruth = build_deck(dpath, 2)
        RESPONDER["fn"] = build_responder(dspecs)
        os.environ.pop(mod.IMAGE_DEBUG_ENV, None)
        run_flow(dpath, "")
        check("デバッグ出力: 環境変数が無ければ作らない", not os.path.exists(os.path.join(tmp3, "dbg_ja_boxes_debug.json")))
        os.environ[mod.IMAGE_DEBUG_ENV] = "1"
        try:
            run_flow(dpath, "")
        finally:
            os.environ.pop(mod.IMAGE_DEBUG_ENV, None)
        jpath = os.path.join(tmp3, "dbg_ja_boxes_debug.json")
        check("デバッグ出力: 環境変数 PPT_IMAGE_DEBUG_BOXES=1 で出力ファイルの隣にJSONを作る", os.path.exists(jpath))
        raw_dbg = open(jpath, encoding="utf-8").read() if os.path.exists(jpath) else ""
        data_dbg = json.loads(raw_dbg) if raw_dbg else {}
        blocks_dbg = data_dbg.get("1", {}).get("blocks", [])
        check("デバッグ出力: スライドごとにブロックの箱・行数・太字・寄せ・結果・塗った範囲が入る",
              len(blocks_dbg) > 0 and all(k in blocks_dbg[0] for k in ("box_2d", "lines", "bold", "align", "result"))
              and any(b.get("result") == "painted" and "paint_fill" in b and "font_pt" in b for b in blocks_dbg))
        leaked = [s_ for s_ in ("Executive Summary", "Wellbeing", "Employee Engagement", "エグゼクティブ", "ウェルビーイング")
                  if s_ in raw_dbg]
        check("デバッグ出力: 原文・訳文は一切含まない(文字数だけ)", not leaked and "text_len" in raw_dbg, f"含まれた文字: {leaked}")
    finally:
        os.environ.pop(mod.IMAGE_DEBUG_ENV, None)
        os.chdir(cwd3)
        shutil.rmtree(tmp3, ignore_errors=True)


if VERSION >= "03":
    run_v03_tests()
else:
    skip("20260930_03 の追加機能のテスト", "このバージョンには無い")

# ============================================================
# 6. 重ね貼り(_02 以降)
# ============================================================
def run_overlay_tests():
    import subprocess
    from lxml import etree as _et
    from pptx.oxml.ns import qn as _qn
    from pptx.util import Emu as _Emu

    def overlay_group(slide):
        for sh in slide.shapes:
            if sh.shape_type == 6 and sh.name == "翻訳オーバーレイ":   # 6 = GROUP
                return sh
        return None

    def group_pairs(group):
        rects = [s for s in group.shapes if s.name == "翻訳_背景"]
        boxes = [s for s in group.shapes if s.name == "翻訳_文字"]
        return rects, boxes

    def truth_emu(blk, size, pic, crop=(0, 0, 0, 0)):
        W, H = size
        l, t_, r, b_ = crop
        x0, y0, x1, y1 = blk["box"]
        cw, ch = W * (1 - l - r), H * (1 - t_ - b_)
        return (pic["left"] + (x0 - l * W) / cw * pic["width"], pic["top"] + (y0 - t_ * H) / ch * pic["height"],
                pic["left"] + (x1 - l * W) / cw * pic["width"], pic["top"] + (y1 - t_ * H) / ch * pic["height"])

    def rect_of(shape):
        return (shape.left, shape.top, shape.left + shape.width, shape.top + shape.height)

    def overlap_area(a, b):
        w = min(a[2], b[2]) - max(a[0], b[0])
        h = min(a[3], b[3]) - max(a[1], b[1])
        return max(0, w) * max(0, h)

    def area(a):
        return max(1, (a[2] - a[0]) * (a[3] - a[1]))

    def fill_rgb(shape):
        return tuple(shape.fill.fore_color.rgb)

    def text_of(shape):
        return shape.text_frame.text

    def pic_geom(path, idx=0):
        prs_ = Presentation(path)
        for sh in prs_.slides[idx].shapes:
            if sh.shape_type == 13:
                return {"left": sh.left, "top": sh.top, "width": sh.width, "height": sh.height}

    tmp2 = tempfile.mkdtemp()
    cwd1 = os.getcwd()
    os.chdir(tmp2)
    try:
        # ---------- 基本: 1枚の合成スライド ----------
        src2 = os.path.join(tmp2, "ov.pptx")
        specs2, truth2 = build_deck(src2, 1)
        RESPONDER["fn"] = build_responder(specs2)
        pic0 = pic_geom(src2)
        orig2 = picture_md5(src2)
        run_flow(src2, "")
        out2 = os.path.join(tmp2, "ov_ja.pptx")
        info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
        prs_out = Presentation(out2)
        slide = prs_out.slides[0]
        group = overlay_group(slide)
        blocks_t, nums_t, size_t, _crop = truth2[0]
        check("重ね貼り: グループ「翻訳オーバーレイ」が作られる", group is not None, info)
        rects, tboxes = group_pairs(group)
        eligible_texts = [b["text"] for b in blocks_t if _tr(b["text"]) != b["text"]]
        check("重ね貼り: 訳文のあるブロック(Acme除く)がすべて四角+文字のペアで重なる",
              len(rects) == len(tboxes) == len(eligible_texts),
              f"rects={len(rects)} boxes={len(tboxes)} 期待={len(eligible_texts)}")
        check("重ね貼り: 完了メッセージに重ねた個数が出る", f"訳文を重ねて貼ったブロック: {len(rects)}個" in info, info)
        check("重ね貼り: 元の画像は位置・バイト列とも完全に同じ", picture_md5(out2) == orig2)
        kids = list(slide.shapes._spTree)
        pic_i = next(i for i, e in enumerate(kids) if e.tag.endswith("}pic"))
        grp_i = next(i for i, e in enumerate(kids) if e.tag.endswith("}grpSp"))
        check("重ね貼り: グループは画像より前面(後ろ)に置かれる", grp_i > pic_i)
        check("重ね貼り: メモ欄への追記も従来どおり行われる", "【画像内テキストの翻訳】" in notes_text(out2, 0))

        by_text = {}
        for r_, tb_ in zip(rects, tboxes):
            by_text[text_of(tb_)] = (r_, tb_)
        tol = pic0["width"] * 0.002
        contain_ok, cont_detail = True, []
        for blk in blocks_t:
            tr = _tr(blk["text"])
            if tr == blk["text"]:
                continue
            r_, _tb = by_text[tr]
            te = truth_emu(blk, size_t, pic0)
            rr = rect_of(r_)
            if not (rr[0] <= te[0] + tol and rr[1] <= te[1] + tol and rr[2] >= te[2] - tol and rr[3] >= te[3] - tol):
                contain_ok = False
                cont_detail.append(blk["text"])
        check("重ね貼り: 各四角が元の文字の位置を完全に覆う(誤差なしの箱)", contain_ok, f"覆えない: {cont_detail}")

        num_overlap = [n["text"] for n in nums_t
                       for r_ in rects if overlap_area(rect_of(r_), truth_emu(n, size_t, pic0)) > 0.02 * area(truth_emu(n, size_t, pic0))]
        check("重ね貼り: 数字だけのブロック(80% / 70% / ( n=5 ))は塗らない", not num_overlap, f"{num_overlap}")
        rr_list = [rect_of(r_) for r_ in rects]
        pair_bad = [(i, j) for i in range(len(rr_list)) for j in range(i + 1, len(rr_list))
                    if overlap_area(rr_list[i], rr_list[j]) > 0.01 * min(area(rr_list[i]), area(rr_list[j]))]
        check("重ね貼り: 隣り合う四角どうしが重ならない(訳文を隠さない)", not pair_bad, f"{pair_bad}")

        def near(c1, c2, d=12):
            return all(abs(a_ - b_) <= d for a_, b_ in zip(c1, c2))
        check("背景色: 濃い帯(0,112,122)の上の文字は帯の色で塗る", near(fill_rgb(by_text[_tr("Executive Summary")][0]), (0, 112, 122)),
              f"{fill_rgb(by_text[_tr('Executive Summary')][0])}")
        check("背景色: 濃灰の帯(106,106,106)の上の文字は白い四角にならない",
              near(fill_rgb(by_text[_tr("My Group")][0]), (106, 106, 106)), f"{fill_rgb(by_text[_tr('My Group')][0])}")
        check("背景色: 縞々の行(249,250,249)の上の文字はその色で塗る",
              near(fill_rgb(by_text[_tr("Wellbeing")][0]), (249, 250, 249), 6), f"{fill_rgb(by_text[_tr('Wellbeing')][0])}")

        def color_of(tb_):
            return tuple(tb_.text_frame.paragraphs[0].runs[0].font.color.rgb)
        check("文字色: 帯の上の白い文字は白系のまま", min(color_of(by_text[_tr("Executive Summary")][1])) >= 200,
              f"{color_of(by_text[_tr('Executive Summary')][1])}")
        eb = color_of(by_text[_tr("Employee Engagement")][1])
        check("文字色: 青い見出しは青系のまま", eb[2] > eb[0] + 40, f"{eb}")

        sizes = [tb_.text_frame.paragraphs[0].runs[0].font.size.pt for tb_ in tboxes]
        check("文字サイズ: すべて下限(5.5pt)以上・40pt以下", all(5.5 <= s <= 40 for s in sizes), f"{sizes}")
        fit_ok = True
        for r_, tb_ in zip(rects, tboxes):
            run_ = tb_.text_frame.paragraphs[0].runs[0]
            w_pt = (tb_.width - tb_.text_frame.margin_left) / 12700.0
            h_pt = tb_.height / 12700.0
            n_ = mod._estimate_lines(text_of(tb_), run_.font.size.pt, w_pt)
            fit_ok &= n_ * run_.font.size.pt * 1.2 * 0.9 <= h_pt + 0.5
        check("文字サイズ: 訳文が枠に収まる(見積もり)", fit_ok)
        r0, t0 = by_text[_tr("Executive Summary")]
        rPr = t0.text_frame.paragraphs[0].runs[0]._r.get_or_add_rPr()
        check("フォント: 日本語は Yu Gothic を latin と ea(東アジア文字)の両方に指定",
              rPr.find(_qn("a:latin")).get("typeface") == "Yu Gothic" and rPr.find(_qn("a:ea")).get("typeface") == "Yu Gothic")
        check("図形: 影・既定スタイル(p:style)が付いていない", r0._element.find(_qn("p:style")) is None)
        body = t0.text_frame._txBody.find(_qn("a:bodyPr"))
        check("テキストボックス: 自動サイズ無効・折り返しあり・上下右の余白0",
              len(list(body)) == 0 and body.get("wrap") == "square"
              and t0.text_frame.margin_top == 0 and t0.text_frame.margin_bottom == 0 and t0.text_frame.margin_right == 0)
        check("文字の左端が元の文字の左端に合う(四角より右へ余白を取る)",
              t0.text_frame.margin_left >= 0)

        # ---------- 言語ごとのフォント ----------
        for lang, font in (("English", "Arial"), ("Chinese Simplified", "Microsoft YaHei")):
            run_flow(src2, "", language=lang)
            o = os.path.join(tmp2, f"ov_{'en' if lang == 'English' else 'cn'}.pptx")
            g = overlay_group(Presentation(o).slides[0])
            f_ = next((s.text_frame.paragraphs[0].runs[0].font.name for s in g.shapes if s.name == "翻訳_文字"), None) \
                if g is not None else None
            check(f"言語ごとのフォント: {lang} は {font}", f_ == font, f"{f_}")
        RESPONDER["fn"] = build_responder(specs2)

        # ---------- 数字の保存検査 ----------
        for o_, t_, exp, label in (
                ("6,797", "6797", True, "桁区切りの有無"), ("80%", "80％", True, "全角%"), ("80%", "８０%", True, "全角数字"),
                ("1.2 million sales", "売上120万", True, "million→万"), ("$3.5B", "35億ドル", True, "B→億"),
                ("10,000 units", "1万台", True, "10,000→1万"), ("2026-09-30", "2026年9月30日", True, "先頭の0"),
                ("Q3 results", "第3四半期の結果", True, "Q3"), ("no numbers here", "数字なし", True, "数字なし"),
                ("Top 5", "上位3", False, "数字が変わった"), ("n=5", "n=6", False, "数字が変わった(2)"),
                ("Score 80%", "スコア", False, "数字が消えた")):
            check(f"数字の保存検査: {label} ({o_!r} → {t_!r}) は {exp}", mod._numbers_preserved(o_, t_) is exp)

        # ---------- 枠に収まらない / 数字が変わった → 重ねずメモのみ ----------
        def reply_with(mut):
            rep = copy.deepcopy(specs2[0]["reply"])
            mut(rep)
            return rep
        def long_wellbeing(rep):
            for b in rep:
                if b["text"] == "Wellbeing":
                    b["translation"] = "とても長い訳文" * 40
        specs_nf = [dict(specs2[0], reply=reply_with(long_wellbeing))]
        RESPONDER["fn"] = build_responder(specs_nf)
        run_flow(src2, "")
        info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
        g = overlay_group(Presentation(out2).slides[0])
        check("枠に収まらないブロック: 重ねず、完了メッセージで個数を知らせる", "枠に収まらず、メモ欄のみにしたブロック: 1個" in info, info)
        check("枠に収まらないブロック: 他のブロックは重ねる", g is not None and len(group_pairs(g)[0]) == len(eligible_texts) - 1)
        check("枠に収まらないブロック: 訳文はメモ欄に全文入る", "とても長い訳文" in notes_text(out2, 0))

        def drop_number(rep):
            for b in rep:
                if b["text"].startswith("The Engagement Index"):
                    b["translation"] = "エンゲージメント指数は質問で構成されています。"
        specs_nm = [dict(specs2[0], reply=reply_with(drop_number))]
        RESPONDER["fn"] = build_responder(specs_nm)
        run_flow(src2, "")
        info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
        g = overlay_group(Presentation(out2).slides[0])
        check("数字が変わった訳: 重ねず、完了メッセージで個数を知らせる", "訳文で数字が変わっていたため、メモ欄のみにしたブロック: 1個" in info, info)
        check("数字が変わった訳: 重ねないがメモ欄には残る",
              g is not None and len(group_pairs(g)[0]) == len(eligible_texts) - 1
              and "質問で構成されています" in notes_text(out2, 0))

        # ---------- 重ねるものが1つも無ければ空のグループを残さない ----------
        only_num = [dict(specs2[0], reply=[{"box_2d": [100, 100, 150, 400], "text": "Score is 80%",
                                             "translation": "スコアは", "lines": 1}])]
        RESPONDER["fn"] = build_responder(only_num)
        run_flow(src2, "")
        check("重ねるブロックが無いスライドに空のグループを残さない", overlay_group(Presentation(out2).slides[0]) is None)

        # ---------- 重ね貼りの失敗はメモ欄だけ残して続行 ----------
        RESPONDER["fn"] = build_responder(specs2)
        real_add = mod._add_overlay_group
        mod._add_overlay_group = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("overlay boom"))
        try:
            run_flow(src2, "")
        finally:
            mod._add_overlay_group = real_add
        info = next((c[2] for c in MESSAGEBOX.CALLS if c[0] == "info"), "")
        check("重ね貼りが失敗しても、メモ欄は残り、失敗したスライドの番号を知らせる",
              "重ね貼りに失敗したスライド（メモ欄のみ）: 1" in info
              and "【画像内テキストの翻訳】" in notes_text(out2, 0)
              and overlay_group(Presentation(out2).slides[0]) is None, info)
        check("重ね貼りが失敗しても、翻訳したスライドとして数える", "翻訳したスライド: 1枚" in info, info)

        # ---------- 確認ダイアログの説明 ----------
        RESPONDER["fn"] = build_responder(specs2)
        pw, cap = run_flow(src2, "")
        check("確認ダイアログ: 重ね貼りと「選んで削除すれば元に戻る」を説明する",
              "重ねて貼ります" in cap["message"] and "削除すれば元に戻ります" in cap["message"] and "加工しません" in cap["message"],
              cap["message"])

        # ---------- 箱の誤差(σ=3/1000) があっても数字は巻き込まない ----------
        im_j, blocks_j, nums_j = make_slide_image(marker=1)
        prs_j = new_prs(); add_picture_slide(prs_j, im_j)
        jpath = os.path.join(tmp2, "jit.pptx"); prs_j.save(jpath)
        pic_j = pic_geom(jpath)
        for jit in (2, 4):
            rep_j = expected_response(blocks_j, nums_j, im_j.size, jitter=jit)
            RESPONDER["fn"] = build_responder([{"blob": png_bytes(im_j), "crop": (0, 0, 0, 0), "reply": rep_j}])
            run_flow(jpath, "")
            gj = overlay_group(Presentation(os.path.join(tmp2, "jit_ja.pptx")).slides[0])
            rj, tj = group_pairs(gj) if gj is not None else ([], [])
            bad_num = [n["text"] for n in nums_j for r_ in rj
                       if overlap_area(rect_of(r_), truth_emu(n, im_j.size, pic_j)) > 0.05 * area(truth_emu(n, im_j.size, pic_j))]
            check(f"箱の誤差(±{jit}/1000)があっても数字のブロックを塗りつぶさない", gj is not None and not bad_num, f"{bad_num}")
            rl = [rect_of(r_) for r_ in rj]
            check(f"箱の誤差(±{jit}/1000)があっても四角どうしが重ならない",
                  not [(i, j) for i in range(len(rl)) for j in range(i + 1, len(rl))
                       if overlap_area(rl[i], rl[j]) > 0.01 * min(area(rl[i]), area(rl[j]))])
            check(f"箱の誤差(±{jit}/1000)があっても、ほとんどのブロックを重ねられる(6個以上)", len(rj) >= 6, f"{len(rj)}個")

        # ---------- 20260930_03: 太字・寄せ・貼る順序・偏った箱のずれ ----------
        if VERSION >= "03":
            def with_flags(rep, flags):
                rep = copy.deepcopy(rep)
                for b in rep:
                    b.update(flags.get(b["text"], {}))
                return rep

            flag_rep = with_flags(specs2[0]["reply"], {"Executive Summary": {"bold": True},
                                                       "My Group": {"align": "center", "bold": True},
                                                       "Wellbeing": {"align": "right"}})
            RESPONDER["fn"] = build_responder([dict(specs2[0], reply=flag_rep)])
            run_flow(src2, "")
            g3 = overlay_group(Presentation(out2).slides[0])
            r3, t3 = group_pairs(g3)
            by3 = {text_of(t_): t_ for t_ in t3}

            def run_of(tb_):
                return tb_.text_frame.paragraphs[0].runs[0]
            check("太字: bold=true のブロックは太字になり、そうでないブロックは太字にならない",
                  run_of(by3[_tr("Executive Summary")]).font.bold is True
                  and run_of(by3[_tr("My Group")]).font.bold is True
                  and run_of(by3[_tr("Employee Engagement")]).font.bold is False)
            from pptx.enum.text import PP_ALIGN as _PA
            check("寄せ: center / right / left(指定なし) がそのまま段落の寄せになる",
                  by3[_tr("My Group")].text_frame.paragraphs[0].alignment == _PA.CENTER
                  and by3[_tr("Wellbeing")].text_frame.paragraphs[0].alignment == _PA.RIGHT
                  and by3[_tr("Employee Engagement")].text_frame.paragraphs[0].alignment == _PA.LEFT)
            mg = next(b for b in blocks_t if b["text"] == "My Group")
            te = truth_emu(mg, size_t, pic0)
            tbx = by3[_tr("My Group")]
            check("中央寄せ: 文字枠の中心が、元の文字の中心に合う(誤差1%以内)",
                  abs((tbx.left + tbx.width / 2) - (te[0] + te[2]) / 2) < pic0["width"] * 0.01,
                  f"枠の中心={tbx.left + tbx.width / 2:.0f} 元の中心={(te[0] + te[2]) / 2:.0f}")
            wb = next(b for b in blocks_t if b["text"] == "Wellbeing")
            te = truth_emu(wb, size_t, pic0)
            tbw = by3[_tr("Wellbeing")]
            check("右寄せ: 文字枠の右端が、元の文字の右端に合う(誤差1%以内)",
                  abs((tbw.left + tbw.width) - te[2]) < pic0["width"] * 0.01,
                  f"枠の右端={tbw.left + tbw.width:.0f} 元の右端={te[2]:.0f}")
            names = [s.name for s in g3.shapes]
            first_text = names.index("翻訳_文字")
            check("貼る順序: 四角を全部貼ってから、文字を貼る(あとの四角が先の文字を隠さない)",
                  all(n == "翻訳_背景" for n in names[:first_text]) and all(n == "翻訳_文字" for n in names[first_text:]),
                  f"{names}")

            # 偏った箱のずれ(実機で起きた種類): 箱を縦に縮める・縦にずらす・右端が短い
            def bias_reply(fn):
                rep = copy.deepcopy(specs2[0]["reply"])
                for b in rep:
                    y0, x0, y1, x1 = b["box_2d"]
                    h_ = y1 - y0
                    b["box_2d"] = fn(y0, x0, y1, x1, h_)
                return rep

            def ink_leak_pct(path):
                """元の文字のインクのうち、四角の外に残った割合(%)。幾何で測る(描画しない)。"""
                W_, H_ = size_t
                pg = pic_geom(path)
                gg = overlay_group(Presentation(path).slides[0])
                rs = [((s.left - pg["left"]) / pg["width"] * W_, (s.top - pg["top"]) / pg["height"] * H_,
                       (s.left + s.width - pg["left"]) / pg["width"] * W_, (s.top + s.height - pg["top"]) / pg["height"] * H_)
                      for s in gg.shapes if s.name == "翻訳_背景"]
                im_full = Image.open(io.BytesIO(specs2[0]["blob"])).convert("RGB")
                own = leak = 0
                for blk in blocks_t:
                    if _tr(blk["text"]) == blk["text"]:
                        continue
                    x0, y0, x1, y1 = [int(round(v)) for v in blk["box"]]
                    region = im_full.crop((x0, y0, x1, y1))
                    from collections import Counter as _C
                    bgc = _C((p_[0] // 8, p_[1] // 8, p_[2] // 8) for p_ in region.getdata()).most_common(1)[0][0]
                    bgc = tuple(v_ * 8 + 4 for v_ in bgc)
                    for k_, p_ in enumerate(region.getdata()):
                        if max(abs(p_[i_] - bgc[i_]) for i_ in range(3)) > 60:
                            x_, y_ = x0 + k_ % (x1 - x0), y0 + k_ // (x1 - x0)
                            own += 1
                            if not any(r_[0] <= x_ < r_[2] and r_[1] <= y_ < r_[3] for r_ in rs):
                                leak += 1
                return 100.0 * leak / max(1, own)

            cases = (("箱を縦に15%縮めた", lambda y0, x0, y1, x1, h_: [y0 + 0.15 * h_, x0, y1 - 0.15 * h_, x1], 2.0),
                     ("箱を縦に30%縮めた", lambda y0, x0, y1, x1, h_: [y0 + 0.30 * h_, x0, y1 - 0.30 * h_, x1], 5.0),
                     ("箱が縦に30%ずれた", lambda y0, x0, y1, x1, h_: [y0 + 0.30 * h_, x0, y1 + 0.30 * h_, x1], 5.0),
                     ("箱の右端が30%短い", lambda y0, x0, y1, x1, h_: [y0, x0, y1, x1 - 0.30 * h_], 2.0))
            for label, fn, limit in cases:
                RESPONDER["fn"] = build_responder([dict(specs2[0], reply=bias_reply(fn))])
                run_flow(src2, "")
                pct = ink_leak_pct(out2)
                check(f"偏った箱のずれ({label}): 元の文字のインクが四角の外に残る割合が{limit}%未満", pct < limit, f"{pct:.2f}%")
                gg_ = overlay_group(Presentation(out2).slides[0])
                rr_, tt_ = group_pairs(gg_)
                hdr_i = [text_of(x_) for x_ in tt_].index(_tr("Executive Summary"))
                check(f"偏った箱のずれ({label}): 濃い帯の上の白いヘッダーの四角が、帯の色のまま(白にならない)",
                      near(fill_rgb(rr_[hdr_i]), (0, 112, 122), 12), f"{fill_rgb(rr_[hdr_i])}")
            RESPONDER["fn"] = build_responder(specs2)

        # ---------- トリミングされた画像・端にずれて配置された画像 ----------
        csrc = os.path.join(tmp2, "cr.pptx")
        cspecs2, ctruth2 = build_deck(csrc, 2, crop_slide=1)
        RESPONDER["fn"] = build_responder(cspecs2)
        cpic = pic_geom(csrc, 1)
        run_flow(csrc, "")
        gc = overlay_group(Presentation(os.path.join(tmp2, "cr_ja.pptx")).slides[1])
        rc, tc = group_pairs(gc)
        cb, cn, cs, ccrop = ctruth2[1]
        bt = {text_of(t_): r_ for r_, t_ in zip(rc, tc)}
        # 左10%が切り落とされるので、完全に見えているブロック(My Group)で比べる
        visible = next(b for b in cb if b["text"] == "My Group")
        te = truth_emu(visible, cs, cpic, ccrop)
        rr = rect_of(bt[_tr(visible["text"])])
        tol2 = cpic["width"] * 0.004
        check("トリミングされた画像: 四角が、トリミング後の表示位置で元の文字を覆う",
              rr[0] <= te[0] + tol2 and rr[1] <= te[1] + tol2 and rr[2] >= te[2] - tol2 and rr[3] >= te[3] - tol2,
              f"rect={rr} truth={tuple(round(v) for v in te)}")

        offs = new_prs()
        im_o, blocks_o, nums_o = make_slide_image(marker=3)
        add_picture_slide(offs, im_o, left=int(offs.slide_width * 0.06), top=int(offs.slide_height * 0.04),
                          width=int(offs.slide_width * 0.9), height=int(offs.slide_height * 0.9))
        opath = os.path.join(tmp2, "off.pptx"); offs.save(opath)
        RESPONDER["fn"] = build_responder([{"blob": png_bytes(im_o), "crop": (0, 0, 0, 0),
                                            "reply": expected_response(blocks_o, nums_o, im_o.size)}])
        run_flow(opath, "")
        go = overlay_group(Presentation(os.path.join(tmp2, "off_ja.pptx")).slides[0])
        ro, to = group_pairs(go)
        opic = pic_geom(opath)
        bo = {text_of(t_): r_ for r_, t_ in zip(ro, to)}
        te = truth_emu(blocks_o[0], im_o.size, opic)
        rr = rect_of(bo[_tr(blocks_o[0]["text"])])
        check("縮小して端にずれて配置された画像(90%): 四角が元の文字の位置を覆う",
              rr[0] <= te[0] + tol2 and rr[1] <= te[1] + tol2 and rr[2] >= te[2] - tol2 and rr[3] >= te[3] - tol2)

        # ---------- 塗り漏れを客観的に測る(LibreOfficeで描画) ----------
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            skip("塗り漏れの描画テスト", "LibreOffice(soffice)が無い")
        else:
            real_pick = mod._pick_text_color
            mod._pick_text_color = lambda ink, bg: bg     # 訳文を背景色にして見えなくし、元の英字の残りだけを測る
            try:
                for jit, limit in ((0, 0.5), (2, 3.0)):
                    im_r, blocks_r, nums_r = make_slide_image(marker=5)
                    prs_r = new_prs(); add_picture_slide(prs_r, im_r)
                    rpath = os.path.join(tmp2, f"leak{jit}.pptx"); prs_r.save(rpath)
                    RESPONDER["fn"] = build_responder([{"blob": png_bytes(im_r), "crop": (0, 0, 0, 0),
                                                        "reply": expected_response(blocks_r, nums_r, im_r.size, jitter=jit)}])
                    run_flow(rpath, "")
                    routp = os.path.join(tmp2, f"leak{jit}_ja.pptx")
                    subprocess.run([soffice, "--headless", "--convert-to", "png", "--outdir", tmp2, routp],
                                   capture_output=True, timeout=180)
                    png = os.path.join(tmp2, f"leak{jit}_ja.png")
                    if not os.path.exists(png):
                        skip(f"塗り漏れの描画テスト(誤差{jit})", "描画に失敗")
                        continue
                    rendered = Image.open(png).convert("RGB")
                    sx, sy = rendered.width / im_r.width, rendered.height / im_r.height
                    total = leak = 0
                    for blk in blocks_r:
                        if _tr(blk["text"]) == blk["text"]:
                            continue     # 訳さないブロックは元のまま残るのが正しい
                        x0, y0, x1, y1 = blk["box"]
                        region = rendered.crop((round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy)))
                        px = list(region.getdata())
                        med = tuple(sorted(p[i] for p in px)[len(px) // 2] for i in range(3))
                        total += len(px)
                        leak += sum(1 for p in px if max(abs(p[i] - med[i]) for i in range(3)) > 40)
                    pct = 100.0 * leak / max(1, total)
                    check(f"塗り漏れ(描画して測定, 箱の誤差±{jit}/1000): 元の英字が透けて残る画素が{limit}%未満", pct < limit,
                          f"{pct:.2f}%")
            finally:
                mod._pick_text_color = real_pick
    finally:
        os.chdir(cwd1)
        shutil.rmtree(tmp2, ignore_errors=True)


if HAS_OVERLAY:
    run_overlay_tests()
else:
    skip("重ね貼りのテスト", "このバージョン(_01)には重ね貼りが無い")

print("\n" + "=" * 60)
failed = [r for r in RESULTS if not r[1]]
print(f"対象: {os.path.basename(TARGET)}")
print(f"合計 {len(RESULTS)} 項目 / 合格 {len(RESULTS) - len(failed)} / 失敗 {len(failed)}")
if failed:
    for name, _ok, detail in failed:
        print(f"  FAILED: {name}  {detail}")
sys.exit(1 if failed else 0)
