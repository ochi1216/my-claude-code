#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
PDF Gemini 翻訳ツール

version : 20260722_01
purpose : 英語PDFなどを Gemini API で翻訳し、レイアウト（位置・フォントサイズ・文字色・
          背景）をできる限り保持したまま翻訳版PDFを生成する。

設計方針:
    - UI／進捗表示／Gemini呼び出し（自動モデル検出・タイムアウト・リトライ・
      フェイルファスト・ロギング）は ppt_translation_20260309_03.py の設計を踏襲し、
      環境変数 GEMINI_API_KEY を使用する。
    - PDFにはPowerPointの「run」に相当する編集単位がないため、PyMuPDF (fitz) で
      テキストブロック単位（≒段落）に抽出・翻訳し、元のブロック矩形へ「墨消し
      （redaction）→ 背景色サンプリング→ 再配置（フォントサイズ自動縮小）」で
      書き戻す。日本語／中国語／韓国語は PyMuPDF 内蔵のCJKフォント（"japan" 等）
      を使用するため追加のフォントファイルは不要。

既知の制限:
    - スキャン画像PDF（テキストレイヤーなし）は翻訳対象を検出できない（OCR非対応）。
    - ブロック単位の翻訳のため、1つの文が複数ブロックに分割されている場合は
      文脈が失われることがある。
    - 背景色はブロック左上付近の1点サンプリングによる近似のため、グラデーション
      や画像上のテキストでは完全には一致しない場合がある。

使い方:
    1. pip install -r requirements.txt
    2. 環境変数 GEMINI_API_KEY にAPIキーを設定する
    3. python pdf_translator_20260722_01.py
    4. 「ファイル選択」からPDFを選び、翻訳先言語を選んで「翻訳開始」を押す
    5. 完了すると同じフォルダに `元ファイル名_ja.pdf`（英語翻訳なら `_en.pdf`）のように
       末尾2文字の言語コード付きで保存される
"""
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import sys
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import traceback

# --- 依存関係の確認 ---
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


def check_dependencies(root_window):
    """起動時の依存関係チェック"""
    missing_libs = []
    if not HAS_GEMINI:
        missing_libs.append("google-generativeai")
    if not HAS_PYMUPDF:
        missing_libs.append("PyMuPDF")

    if missing_libs:
        error_msg = "以下のライブラリがインストールされていません:\n"
        for lib in missing_libs:
            error_msg += f"- {lib}\n"
        error_msg += "\n以下のコマンドでインストールしてください:\n"
        error_msg += f"pip install {' '.join(missing_libs)}"

        messagebox.showerror("依存関係エラー", error_msg, parent=root_window)
        return False
    return True


# --- グローバル変数（APIモデル） ---
gemini_model = None


def get_logger():
    """デバッグ用ロガーの初期化（コンソールとファイル両方に出力）"""
    logger = logging.getLogger("PDF_Translation")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler("translation_debug.log", encoding="utf-8")
        ch = logging.StreamHandler()
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", "%H:%M:%S")
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


def init_gemini(root_window):
    """Gemini APIの初期化（環境変数 GEMINI_API_KEY を使用、自動モデル検出機能付き）"""
    global gemini_model
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        messagebox.showerror("エラー",
                           "GEMINI_API_KEY が設定されていません。\n"
                           "環境変数に GEMINI_API_KEY を設定してください。", parent=root_window)
        return False

    try:
        genai.configure(api_key=api_key)

        # 使えるモデルを自動検出して404エラーを完全に防ぐ
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)

        # 優先的にFlashモデルを探す
        target_model_name = None
        for preferred in ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-pro']:
            for am in available_models:
                if preferred in am:
                    target_model_name = am
                    break
            if target_model_name:
                break

        # 見つからなければ最初のモデルを使用
        if not target_model_name and available_models:
            target_model_name = available_models[0]

        print(f"自動選択されたモデル: {target_model_name}")
        gemini_model = genai.GenerativeModel(target_model_name)
        return True
    except Exception as e:
        messagebox.showerror("API初期化エラー", f"Gemini APIの初期化に失敗しました:\n{e}", parent=root_window)
        return False


def is_translatable(text):
    """翻訳が必要なテキストかどうかを判定"""
    if not text or str(text).strip() == "":
        return False

    text_str = str(text).strip()

    if text_str in ["", "#", "-", "N/A", "NULL", "•", "◦", "▪", "**", "*", ":", "：",
                    "I.", "II.", "III.", "IV.", "V.", "VI.", "***"]:
        return False
    if text_str.replace(".", "").replace("-", "").isdigit():
        return False
    if len(text_str) <= 2:
        return False
    return True


def translate_batch_gemini(texts, target_language="Japanese", batch_idx=0, logger=None):
    """Gemini APIを使用した小バッチ翻訳（リトライ・タイムアウト機構付き）"""
    if not gemini_model or not texts:
        return texts, False

    batch_input = "\n".join([f"[{i+1}] {t}" for i, t in enumerate(texts)])

    prompt = f"""
    Task: Translate the following text into {target_language}.

    Guidelines:
    1. Maintain the exact format [number] for each translated line.
    2. Output ONLY the numbered list. No extra explanations.
    3. Keep technical terms natural.

    Source Text:
    {batch_input}
    """

    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    for attempt in range(1, 4):  # 最大3回リトライ
        try:
            if logger: logger.info(f"バッチ {batch_idx+1} 通信開始 (試行 {attempt}/3)")

            # APIタイムアウト（40秒）を設定
            response = gemini_model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(temperature=0.1),
                safety_settings=safety_settings,
                request_options={"timeout": 40}
            )
            time.sleep(1.5)

            if not response.parts:
                if logger: logger.warning(f"バッチ {batch_idx+1} 空のレスポンスを受信")
                raise ValueError("Empty response from API")

            response_text = response.text.strip()
            results = [None] * len(texts)
            lines = response_text.split('\n')

            for line in lines:
                match = re.match(r'^\[(\d+)\]\s*(.*)', line.strip())
                if match:
                    idx = int(match.group(1)) - 1
                    if 0 <= idx < len(texts):
                        results[idx] = match.group(2).strip()

            for i in range(len(results)):
                if results[i] is None:
                    results[i] = texts[i]

            if logger: logger.info(f"バッチ {batch_idx+1} 成功！")
            return results, False  # 成功（エラーフラグFalse）

        except Exception as e:
            if logger: logger.error(f"バッチ {batch_idx+1} エラー発生: {str(e)}")
            if attempt < 3:
                time.sleep(3)  # エラー時は3秒間隔で待機
            else:
                if logger: logger.error(f"バッチ {batch_idx+1} は3回失敗したためスキップします。")

    return texts, True  # 失敗（原文を返し、エラーフラグTrueを通知）


def translate_super_fast_parallel(all_texts, target_language="Japanese", max_workers=3, progress_callback=None, logger=None):
    """並列処理エンジン（コールバックと強制切断機能付き）"""
    if not all_texts:
        return []

    batch_size = 10
    chunks = [all_texts[i:i + batch_size] for i in range(0, len(all_texts), batch_size)]
    results = [None] * len(chunks)

    abort_event = threading.Event()
    consecutive_errors = 0
    processed_items = 0

    def translate_chunk(chunk_idx, chunk_texts):
        if abort_event.is_set():
            return chunk_idx, (chunk_texts, False)  # 中断フラグが立っていればスルー
        return chunk_idx, translate_batch_gemini(chunk_texts, target_language, chunk_idx, logger)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(translate_chunk, i, chunk) for i, chunk in enumerate(chunks)]

        for future in as_completed(futures):
            try:
                chunk_idx, (translated_chunk, is_error) = future.result()
                results[chunk_idx] = translated_chunk

                # エラーカウントの判定
                if is_error:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0  # 1つでも成功すればリセット

                # 3回連続エラーで即時撤退（フェイルファスト）
                if consecutive_errors >= 3:
                    abort_event.set()
                    if logger: logger.critical("【致命的エラー】3バッチ連続で通信エラー発生。処理を強制中断します。")
                    raise RuntimeError("Gemini APIへの通信が3回連続で失敗しました。\nネットワーク接続かAPI制限をご確認ください。")

                # 進捗UIの更新
                processed_items += len(chunks[chunk_idx])
                if progress_callback:
                    progress_callback(processed_items)

            except RuntimeError as e:
                raise e  # 致命的エラーはそのまま投げる
            except Exception as e:
                if logger: logger.error(f"チャンク結果取得エラー: {str(e)}")

    final_results = []
    for chunk_result in results:
        if chunk_result:
            final_results.extend(chunk_result)
        else:
            final_results.extend([""] * batch_size)

    return final_results


class PdfProgressWindow:
    """進捗表示用ウィンドウ（スレッドセーフ版）"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Gemini 翻訳進捗")
        self.window.geometry("450x180")
        self.window.resizable(False, False)

        try:
            self.window.transient(parent)
            self.window.grab_set()
        except Exception:
            pass

        self.progress_label = tk.Label(self.window, text="Gemini AI 翻訳を準備中...", font=("Arial", 11, "bold"))
        self.progress_label.pack(pady=15)

        self.status_label = tk.Label(self.window, text="処理を開始します...", font=("Arial", 9))
        self.status_label.pack(pady=5)

        self.progress_frame = tk.Frame(self.window, width=350, height=20, bg="white", relief="sunken")
        self.progress_frame.pack(pady=10)

        self.progress_bar = tk.Frame(self.progress_frame, height=18, bg="#0078D4")
        self.progress_bar.place(x=1, y=1)

        self.time_label = tk.Label(self.window, text="", font=("Arial", 8), fg="blue")
        self.time_label.pack(pady=2)

        self.start_time = time.time()

    def update_progress(self, current, total, status=""):
        # 別スレッドから安全にGUIを更新するため after を使用
        try:
            self.window.after(0, self._update_gui, current, total, status)
        except Exception:
            pass

    def _update_gui(self, current, total, status):
        try:
            percentage = int((current / total) * 100) if total > 0 else 0
            bar_width = int((current / total) * 348) if total > 0 else 0
            self.progress_bar.config(width=bar_width)

            elapsed_time = time.time() - self.start_time

            self.progress_label.config(text=f"翻訳進捗: {current}/{total} ({percentage}%)")
            if status:
                self.status_label.config(text=status)
            self.time_label.config(text=f"経過時間: {elapsed_time:.1f}s")
        except Exception:
            pass

    def close(self):
        try:
            self.window.after(0, self.window.destroy)
        except Exception:
            pass


def extract_translatable_blocks(doc, logger=None):
    """PDF全ページからテキストブロック（≒段落）単位で翻訳対象を抽出"""
    blocks_info = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_dict = page.get_text("dict")

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue  # 画像ブロックはスキップ

            lines = block.get("lines", [])
            if not lines:
                continue

            line_texts = []
            font_size = None
            color = 0
            for line in lines:
                spans = line.get("spans", [])
                line_text = "".join(span.get("text", "") for span in spans)
                if line_text.strip():
                    line_texts.append(line_text.strip())
                if spans and font_size is None:
                    font_size = spans[0].get("size", 11)
                    color = spans[0].get("color", 0)

            full_text = " ".join(line_texts)
            if not is_translatable(full_text):
                continue

            blocks_info.append({
                "page_index": page_index,
                "bbox": fitz.Rect(block["bbox"]),
                "text": full_text,
                "font_size": font_size or 11,
                "color": color,
            })

    if logger:
        logger.info(f"翻訳対象ブロック数: {len(blocks_info)}")
    return blocks_info


def lang_to_fontname(target_language):
    """翻訳先言語に応じたPyMuPDF内蔵CJKフォント名を返す"""
    if "Japanese" in target_language or "日本" in target_language:
        return "japan"
    if "Chinese" in target_language or "中国" in target_language:
        return "china-s"
    if "Korean" in target_language or "韓国" in target_language:
        return "korea"
    return "helv"


LANGUAGE_SUFFIX_MAP = {
    "Japanese": "ja",
    "English": "en",
    "Chinese Simplified": "zh",
    "Korean": "ko",
}


def lang_to_suffix(target_language):
    """出力ファイル名の末尾に付ける2文字言語コードを返す（例: Japanese -> ja）"""
    if target_language in LANGUAGE_SUFFIX_MAP:
        return LANGUAGE_SUFFIX_MAP[target_language]
    return target_language.strip()[:2].lower()


def sample_background_color(page, rect, logger=None):
    """ブロック左上近傍の1点をサンプリングして背景色を近似取得（失敗時は白）"""
    try:
        x0 = max(rect.x0 - 2, 0)
        y0 = max(rect.y0 - 2, 0)
        sample_rect = fitz.Rect(x0, y0, x0 + 1, y0 + 1)
        pix = page.get_pixmap(clip=sample_rect, dpi=72)
        if pix.width > 0 and pix.height > 0:
            pixel = pix.pixel(0, 0)
            r, g, b = pixel[0], pixel[1], pixel[2]
            return (r / 255, g / 255, b / 255)
    except Exception as e:
        if logger: logger.debug(f"背景色サンプリング失敗: {e}")
    return (1, 1, 1)


def apply_translations_to_pdf(doc, blocks_info, translated_texts, target_language, logger=None):
    """墨消し（redaction）→ 背景色で塗り潰し → 翻訳文を再配置（自動フォント縮小）"""
    fontname = lang_to_fontname(target_language)

    pages_items = {}
    for info, translated in zip(blocks_info, translated_texts):
        pages_items.setdefault(info["page_index"], []).append((info, translated))

    for page_index, items in pages_items.items():
        page = doc[page_index]

        # 墨消し前に背景色をサンプリングしておく
        fills = [sample_background_color(page, info["bbox"], logger) for info, _ in items]

        for (info, _translated), fill in zip(items, fills):
            page.add_redact_annot(info["bbox"], fill=fill)
        page.apply_redactions()

        for (info, translated), _fill in zip(items, fills):
            rect = info["bbox"]
            color_int = info["color"]
            text_color = (
                ((color_int >> 16) & 255) / 255,
                ((color_int >> 8) & 255) / 255,
                (color_int & 255) / 255,
            )

            fs = info["font_size"]
            inserted = False
            while fs >= 4:
                rc = page.insert_textbox(
                    rect, translated,
                    fontsize=fs, fontname=fontname,
                    color=text_color, align=0,
                )
                if rc >= 0:
                    inserted = True
                    break
                fs -= 0.5

            if not inserted:
                # 収まりきらない場合も最小サイズでベストエフォート挿入（はみ出し許容）
                page.insert_textbox(rect, translated, fontsize=4, fontname=fontname, color=text_color, align=0)
                if logger:
                    logger.warning(f"ページ{page_index+1}: ブロックが矩形に収まらずはみ出しの可能性があります。")


def translate_pdf_document_thread(file_path, target_language, progress_window):
    """バックグラウンドで実行されるメイン処理"""
    logger = get_logger()
    doc = None
    try:
        start_total_time = time.time()
        lang_suffix = lang_to_suffix(target_language)
        output_path = os.path.splitext(file_path)[0] + f"_{lang_suffix}.pdf"

        logger.info(f"=== PDF翻訳開始: {os.path.basename(file_path)} ===")

        # ファイルロックの事前検知（読み込み元）
        try:
            with open(file_path, 'a'): pass
        except PermissionError:
            logger.error(f"[事前検知] 読み込み元ファイルがロックされています: {file_path}")
            progress_window.close()
            messagebox.showerror("ファイルエラー", "対象のPDFファイルが別のアプリで開かれています。\nファイルを閉じてから再度実行してください。")
            return

        # ファイルロックの事前検知（保存先）
        if os.path.exists(output_path):
            try:
                with open(output_path, 'a'): pass
            except PermissionError:
                logger.error(f"[事前検知] 保存先ファイルがロックされています: {output_path}")
                progress_window.close()
                messagebox.showerror("ファイルエラー", "以前に作成した翻訳ファイルが開かれています。\nファイルを閉じてから再度実行してください。")
                return

        doc = fitz.open(file_path)

        translatable_blocks = extract_translatable_blocks(doc, logger)

        if not translatable_blocks:
            doc.close()
            progress_window.close()
            messagebox.showinfo("完了", "翻訳対象のテキストが見つかりませんでした。\n（画像のみのスキャンPDFはOCR非対応のため検出できません）")
            return

        texts_only = [b["text"] for b in translatable_blocks]
        total_items = len(texts_only)
        progress_window.update_progress(0, total_items, f"Gemini APIで並列翻訳中... (0/{total_items}項目)")

        # UI更新用のコールバック関数
        def update_ui_callback(processed_count):
            progress_window.update_progress(processed_count, total_items, f"Gemini APIで並列翻訳中... ({processed_count}/{total_items}項目)")

        # ※バックグラウンドスレッドで重い通信処理を実行
        translated_texts = translate_super_fast_parallel(texts_only, target_language, max_workers=3, progress_callback=update_ui_callback, logger=logger)

        progress_window.update_progress(total_items, total_items, "翻訳結果をPDFに適用中...")
        apply_translations_to_pdf(doc, translatable_blocks, translated_texts, target_language, logger)

        progress_window.update_progress(total_items, total_items, "保存中...")

        try:
            doc.save(output_path, garbage=4, deflate=True)
        except PermissionError:
            doc.close()
            progress_window.close()
            messagebox.showerror("保存エラー", "ファイルが他のプログラム（PDF閲覧ソフトなど）で開かれています。\n閉じてから再度実行してください。")
            return
        finally:
            doc.close()
            doc = None

        progress_window.close()
        total_time = time.time() - start_total_time
        logger.info(f"=== 処理完了: 成功 ({total_time:.1f}秒) ===")

        messagebox.showinfo("完了",
                          f"レイアウト保持翻訳完了！\n"
                          f"保存先: {output_path}\n"
                          f"翻訳項目数: {len(translatable_blocks)}\n"
                          f"処理時間: {total_time:.1f}秒")

    except RuntimeError as e:
        progress_window.close()
        messagebox.showerror("通信エラー強制終了", str(e))

    except Exception as e:
        logger.error(f"予期せぬエラー: {traceback.format_exc()}")
        progress_window.close()
        messagebox.showerror("エラー", f"翻訳処理中にエラーが発生しました:\n{str(e)}")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def select_file():
    path = filedialog.askopenfilename(
        title="翻訳するPDFファイルを選択してください",
        filetypes=[("PDF files", "*.pdf")]
    )

    if not path:
        return

    lang_win = tk.Toplevel(root)
    lang_win.title("PDF翻訳設定")
    lang_win.geometry("400x250")
    lang_win.resizable(False, False)
    lang_win.transient(root)
    lang_win.grab_set()

    tk.Label(lang_win, text="翻訳先言語を選択してください", font=("Arial", 12, "bold")).pack(padx=20, pady=20)

    languages = {
        "日本語 (Japanese)": "Japanese",
        "英語 (English)": "English",
        "中国語簡体字 (Chinese)": "Chinese Simplified"
    }

    lang_var = tk.StringVar(lang_win)
    lang_var.set("日本語 (Japanese)")

    lang_menu = tk.OptionMenu(lang_win, lang_var, *languages.keys())
    lang_menu.config(font=("Arial", 10), width=25)
    lang_menu.pack(padx=20, pady=10)

    def start_translation():
        selected_language = languages[lang_var.get()]
        lang_win.destroy()

        # プログレスウィンドウを作成
        progress_window = PdfProgressWindow(root)

        # 画面をフリーズさせないために、別スレッドで翻訳処理を開始！
        thread = threading.Thread(
            target=translate_pdf_document_thread,
            args=(path, selected_language, progress_window)
        )
        thread.daemon = True
        thread.start()

    button_frame = tk.Frame(lang_win)
    button_frame.pack(pady=25)

    tk.Button(button_frame, text="翻訳開始", command=start_translation,
             bg="#0078D4", fg="white", padx=20, pady=8, font=("Arial", 11, "bold")).pack(side=tk.LEFT, padx=10)
    tk.Button(button_frame, text="キャンセル", command=lang_win.destroy,
             padx=20, pady=8, font=("Arial", 11)).pack(side=tk.LEFT, padx=10)


# --- GUI初期設定 ---
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    if not check_dependencies(root):
        sys.exit(1)

    if not init_gemini(root):
        sys.exit(1)

    root.deiconify()
    root.title("PDF Gemini 翻訳ツール")
    root.geometry("500x280")
    root.resizable(False, False)

    main_frame = tk.Frame(root)
    main_frame.pack(expand=True, fill='both', padx=20, pady=20)

    title_label = tk.Label(main_frame, text="PDF Gemini 翻訳ツール", font=("Arial", 16, "bold"))
    title_label.pack(pady=8)

    subtitle_label = tk.Label(main_frame, text="レイアウト保持版 (Gemini API)", font=("Arial", 12), fg="#0078D4")
    subtitle_label.pack(pady=2)

    desc_label = tk.Label(main_frame,
                         text="PDFファイル(.pdf)を選択して翻訳します\n"
                              "文字位置・フォントサイズ・文字色をできる限り保持",
                         font=("Arial", 10))
    desc_label.pack(pady=8)

    select_button = tk.Button(main_frame, text="ファイル選択", command=select_file,
                             font=("Arial", 12), bg="#0078D4", fg="white", padx=20, pady=10)
    select_button.pack(pady=15)

    root.mainloop()
