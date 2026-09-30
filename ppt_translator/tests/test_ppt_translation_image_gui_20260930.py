"""ppt_translation の「画像スライドの確認ダイアログ」を、本物の tkinter で動かして検証するテスト。

他のテストは tkinter をスタブ化しているが、ダイアログの操作（入力検証・キャンセル・ワーカー
スレッドから主スレッドへの依頼）は本物でないと確かめられないため、このファイルだけ別にする。
tkinter または画面(DISPLAY)が無い環境では、何もせず SKIP で正常終了する。

実行方法(画面の無いLinuxなら仮想画面で):
    xvfb-run -a python3 tests/test_ppt_translation_image_gui_20260930.py [01|02]
"""
import importlib.util
import os
import sys
import threading
import types as pytypes

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = sys.argv[1] if len(sys.argv) > 1 else "02"
TARGET = os.path.join(HERE, "..", f"ppt_translation_20260930_{VERSION}.py")

try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
except Exception as e:  # tkinter が無い / 画面が無い
    print(f"SKIP: GUIテスト全体  ({type(e).__name__}: {e})")
    sys.exit(0)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  ({detail})" if detail else ""))


fake = pytypes.ModuleType("gemini_client")
fake.generate_advanced = lambda payload, model=None, **k: {}
sys.modules["gemini_client"] = fake
spec = importlib.util.spec_from_file_location("target_gui", TARGET)
mod = importlib.util.module_from_spec(spec)
sys.modules["target_gui"] = mod
spec.loader.exec_module(mod)


def all_widgets(w):
    yield w
    for c in w.winfo_children():
        yield from all_widgets(c)


def find_dialog():
    for c in root.winfo_children():
        if isinstance(c, tk.Toplevel):
            return c
    return None


def widget_of(dialog, cls, text=None):
    for w in all_widgets(dialog):
        if isinstance(w, cls):
            if text is None or (cls is not tk.Entry and w.cget("text") == text):
                return w
    return None


def run_dialog(script, message="画像だけのスライドが 3 枚見つかりました。"):
    """ワーカースレッドから _run_on_main_thread で確認ダイアログを出し、
    主スレッド(mainloop)側で script(dialog) が操作する。戻り値: ダイアログの結果。"""
    result = {}
    parent = tk.Toplevel(root)   # 進捗ウィンドウの代わり
    parent.geometry("300x100")

    def worker():
        try:
            result["value"] = mod._run_on_main_thread(
                parent, lambda: mod._show_image_confirm_dialog(
                    parent, message, lambda s: mod.parse_slide_spec(s, 24)))
        except Exception as e:
            result["error"] = e
        finally:
            root.after(0, root.quit)

    def drive(tries=0):
        d = find_dialog_under(parent)
        if d is None:
            if tries < 100:
                root.after(50, lambda: drive(tries + 1))
            else:
                result["error"] = RuntimeError("ダイアログが出なかった")
                root.quit()
            return
        try:
            script(d)
        except Exception as e:
            result["error"] = e
            root.quit()

    threading.Thread(target=worker, daemon=True).start()
    root.after(100, drive)
    root.after(8000, root.quit)  # 念のためのタイムアウト
    root.mainloop()
    try:
        parent.destroy()
    except Exception:
        pass
    return result


def find_dialog_under(parent):
    for c in parent.winfo_children():
        if isinstance(c, tk.Toplevel):
            return c
    return None


def set_entry(dialog, value):
    for w in all_widgets(dialog):
        if isinstance(w, tk.Entry):
            w.delete(0, tk.END)
            w.insert(0, value)
            return w
    raise RuntimeError("Entryが無い")


def click(dialog, text):
    for w in all_widgets(dialog):
        if isinstance(w, tk.Button) and w.cget("text") == text:
            w.invoke()
            return
    raise RuntimeError(f"ボタン「{text}」が無い")


# 1. 「6」を入力して実行
r = run_dialog(lambda d: (set_entry(d, "6"), click(d, "実行")))
check("ダイアログ: 「6」を入れて実行すると '6' が返る", r.get("value") == "6", str(r))

# 2. 空欄で実行 = 全部
r = run_dialog(lambda d: click(d, "実行"))
check("ダイアログ: 空欄で実行すると空文字(=全部)が返る", r.get("value") == "", str(r))

# 3. キャンセル
r = run_dialog(lambda d: click(d, "キャンセル"))
check("ダイアログ: キャンセルすると None が返る", "value" in r and r["value"] is None, str(r))

# 4. 閉じるボタン(×)
r = run_dialog(lambda d: d.destroy())
check("ダイアログ: ×で閉じると None が返る", "value" in r and r["value"] is None, str(r))

# 5. 不正な入力 → エラー文言が出て、ダイアログは閉じず、直せば実行できる
seen = {}


def bad_then_good(d):
    set_entry(d, "99")
    click(d, "実行")
    d.update()
    labels = [w.cget("text") for w in all_widgets(d) if isinstance(w, tk.Label)]
    seen["labels"] = labels
    seen["still_open"] = bool(d.winfo_exists())
    set_entry(d, "1-3,5")
    click(d, "実行")


r = run_dialog(bad_then_good)
check("ダイアログ: 範囲外(99)はエラー文言を出し、閉じずに再入力できる",
      seen.get("still_open") and any("範囲外" in t for t in seen.get("labels", [])), str(seen))
check("ダイアログ: 直して実行すると入力どおり '1-3,5' が返る", r.get("value") == "1-3,5", str(r))

# 6. 文言と入力欄の説明
captured = {}


def read_labels(d):
    captured["labels"] = [w.cget("text") for w in all_widgets(d) if isinstance(w, tk.Label)]
    click(d, "キャンセル")


run_dialog(read_labels, message="画像そのものを外部AI（Gemini）へ送信します。")
check("ダイアログ: 渡した文言と、範囲入力の説明(空欄=全部・例)が表示される",
      any("Gemini" in t for t in captured.get("labels", []))
      and any("空欄=全部" in t and "例" in t for t in captured.get("labels", [])), str(captured))

# 7. ワーカースレッドからの依頼で例外が起きたら呼び出し元へ伝わる
err_result = {}


def worker_err():
    try:
        mod._run_on_main_thread(root, lambda: (_ for _ in ()).throw(ValueError("boom")))
    except ValueError as e:
        err_result["e"] = str(e)
    finally:
        root.after(0, root.quit)


threading.Thread(target=worker_err, daemon=True).start()
root.after(5000, root.quit)
root.mainloop()
check("主スレッドへの依頼: 例外は呼び出し元(ワーカー)へ伝わる", err_result.get("e") == "boom", str(err_result))

# 8. 実際の進捗ウィンドウ(grab_set済みのモーダル)の上でも、_ask_image_confirmation が動く
real = {}
progress = mod.WordProgressWindow(root)


def worker_real():
    try:
        real["value"] = mod._ask_image_confirmation(
            progress, "画像だけのスライドが 24 枚見つかりました。", lambda s: mod.parse_slide_spec(s, 24))
    except Exception as e:
        real["error"] = repr(e)
    finally:
        root.after(0, root.quit)


def drive_real(tries=0):
    d = find_dialog_under(progress.window)
    if d is None:
        if tries < 100:
            root.after(50, lambda: drive_real(tries + 1))
        else:
            real["error"] = "ダイアログが出なかった"
            root.quit()
        return
    set_entry(d, "6")
    click(d, "実行")


threading.Thread(target=worker_real, daemon=True).start()
root.after(100, drive_real)
root.after(8000, root.quit)
root.mainloop()
check("実際の進捗ウィンドウの上でも確認ダイアログが出て、「6」が返る", real.get("value") == "6", str(real))
try:
    progress.window.destroy()
except Exception:
    pass

print("\n" + "=" * 60)
failed = [r for r in RESULTS if not r[1]]
print(f"合計 {len(RESULTS)} 項目 / 合格 {len(RESULTS) - len(failed)} / 失敗 {len(failed)}")
for name, _ok, detail in failed:
    print(f"  FAILED: {name}  {detail}")
sys.exit(1 if failed else 0)
