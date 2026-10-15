"""
会議録画 文字起こし・要約ツール
Version: 20260716_04

.mkv形式のオンライン会議録画から音声を抽出し、文字起こし・要約(議事録化)を行う。
文字起こしは「クラウド(Gemini API)」「ローカル(faster-whisper)」をGUI上で選択できる。
要約は常にGemini APIを使用する(文字起こし後のテキストのみを送信する)。

クラウドモードは、1回のAPI呼び出しで長時間の音声全体を逐語文字起こしさせると、
出力が途中で打ち切られる(モデルの出力上限、または長い単調な書き起こしをモデルが
自主的に切り上げる挙動)ことがあるため、音声を短いチャンクに分割して順に処理する。

要約はMarkdown/JSONに加えてHTML版も生成し、処理完了時に既定のブラウザで自動的に開く。
"""

import glob
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "gemini_max_output_tokens": 8192,
    "chunk_minutes": 10,
    "language": "ja",
    "whisper_model_size": "large-v3",
    "whisper_device": "cpu",
    "whisper_compute_type": "int8",
    "output_dir": "output",
}

LANGUAGE_LABELS = {
    "ja": "日本語",
    "en": "English",
    "auto": "自動判定",
}

LANGUAGE_HINTS = {
    "ja": "この会議は主に日本語で行われています。文字起こしは日本語を基本にしてください。",
    "en": "This meeting is primarily in English. Please transcribe primarily in English.",
    "auto": "",
}

TRANSCRIBE_PROMPT_TEMPLATE = (
    "以下は会議音声の一部です。発言ごとに文字起こしをしてください。\n"
    "出力形式は1行ごとに次の形式にしてください(前置きや説明文、コードブロックは書かないこと)。\n"
    "[分:秒] 話者A: 発言内容\n"
    "話者は登場順にA, B, C...とラベル付けしてください。相槌や言い淀みも省略せず書き起こしてください。"
    "時刻はこの音声チャンクの先頭を0:00として付けてください。"
    "{language_hint}{continuity_hint}"
)

SUMMARY_PROMPT_TEMPLATE = (
    "以下は会議の文字起こしです。内容を分析し、次のキーのみを持つJSONを出力してください"
    "(JSON以外のテキストは出力しないこと)。\n"
    "{{\n"
    '  "purpose": "会議の目的(不明な場合は空文字)",\n'
    '  "participants": ["話者A", "話者B"],\n'
    '  "topics": ["主な議題・論点"],\n'
    '  "decisions": ["決定事項"],\n'
    '  "action_items": [{{"owner": "担当者(不明ならnull)", "task": "内容", "due": "期限(不明ならnull)"}}],\n'
    '  "next_todos": ["次回までのTODO"]\n'
    "}}\n\n"
    "文字起こし:\n{transcript}"
)

# Geminiの出力揺れ(コードブロック化、太字装飾、時刻の桁数、区切り文字の全角/半角)を
# 吸収するため、時刻付き行・話者付き行(時刻なし)の2段階でマッチを試みる。
CODE_FENCE_PATTERN = re.compile(r"```[a-zA-Z]*")
TIMESTAMP_LINE_PATTERN = re.compile(
    r"^[\-\*\s]*\**\[?(\d{1,3}(?::\d{2}){1,2})\]?\**\s*[:\-]?\s*"
    r"\**([^\[\]:：\*]{1,24}?)\**\s*[:：]\s*(.+)$"
)
SPEAKER_LINE_PATTERN = re.compile(r"^[\-\*\s]*\**([^\[\]:：\*]{1,24}?)\**\s*[:：]\s*(.+)$")


def load_config():
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config.update(json.load(f))
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        config["gemini_api_key"] = api_key
    return config


def format_time(seconds):
    if seconds is None:
        return None
    seconds = max(0, int(round(seconds)))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def parse_timestamp_to_seconds(timestamp_text):
    total = 0
    for part in timestamp_text.split(":"):
        total = total * 60 + int(part)
    return total


def make_sub_progress(progress, start, end):
    """progress(0-100)のうちstart-endの範囲を、0.0-1.0のfractionで更新するコールバックを作る。"""
    def sub(fraction):
        progress(start + (end - start) * max(0.0, min(1.0, fraction)))
    return sub


# ---------------------------------------------------------------------------
# 音声抽出・分割
# ---------------------------------------------------------------------------

def extract_audio(input_path, workdir, log):
    output_path = os.path.join(workdir, "audio.wav")
    log(f"音声を抽出しています: {input_path}")
    cmd = ["ffmpeg", "-y", "-i", input_path, "-vn", "-ac", "1", "-ar", "16000", output_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpegによる音声抽出に失敗しました。ffmpegがインストールされているか確認してください。\n"
                            + result.stderr[-2000:])
    log("音声抽出が完了しました。")
    return output_path


def split_audio_into_chunks(audio_path, workdir, chunk_seconds, log):
    chunk_dir = os.path.join(workdir, "chunks")
    os.makedirs(chunk_dir, exist_ok=True)
    pattern = os.path.join(chunk_dir, "chunk_%03d.wav")
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-f", "segment", "-segment_time", str(chunk_seconds),
        "-c", "copy", pattern,
    ]
    log(f"音声を{chunk_seconds // 60}分単位のチャンクに分割しています...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("音声の分割に失敗しました。\n" + result.stderr[-2000:])
    chunk_paths = sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.wav")))
    if not chunk_paths:
        raise RuntimeError("音声の分割結果が見つかりませんでした。")
    log(f"{len(chunk_paths)}個のチャンクに分割しました。")
    return chunk_paths


# ---------------------------------------------------------------------------
# 文字起こし: クラウド(Gemini API)
# ---------------------------------------------------------------------------

def _wait_for_gemini_file_active(client, uploaded_file, log, timeout=600, interval=3):
    start = time.time()
    current = uploaded_file
    state = getattr(current.state, "name", current.state)
    while state == "PROCESSING":
        if time.time() - start > timeout:
            raise TimeoutError("Geminiでの音声ファイル処理がタイムアウトしました。")
        time.sleep(interval)
        current = client.files.get(name=uploaded_file.name)
        state = getattr(current.state, "name", current.state)
    if state == "FAILED":
        raise RuntimeError("Geminiでの音声ファイル処理に失敗しました。")
    return current


def _delete_gemini_file_quietly(client, uploaded_file):
    try:
        client.files.delete(name=uploaded_file.name)
    except Exception:
        pass


def _extract_response_text(response):
    text = getattr(response, "text", None)
    if text:
        return text
    candidates = getattr(response, "candidates", None) or []
    reasons = [str(getattr(c, "finish_reason", "")) for c in candidates if getattr(c, "finish_reason", None)]
    reason_text = ", ".join(reasons) if reasons else "不明"
    raise RuntimeError(
        f"Geminiから文字起こしのテキストが返されませんでした(finish_reason: {reason_text})。"
        "音声が長すぎるか、内容が安全フィルタに抵触した可能性があります。"
    )


def parse_transcript_response(text):
    """Geminiの文字起こし応答をセグメント列に変換する。

    形式が完全には一致しない行があっても、可能な限り情報を保持する
    (時刻+話者 → 話者のみ → 直前セグメントへの追記 → 新規セグメントの順にフォールバック)。
    """
    cleaned = CODE_FENCE_PATTERN.sub("", text).strip()
    segments = []

    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = TIMESTAMP_LINE_PATTERN.match(line)
        if match:
            timestamp_text, speaker, content = match.groups()
            segments.append({
                "start": parse_timestamp_to_seconds(timestamp_text),
                "end": None,
                "speaker": speaker.strip(),
                "text": content.strip(),
            })
            continue

        match = SPEAKER_LINE_PATTERN.match(line)
        if match:
            speaker, content = match.groups()
            segments.append({
                "start": None,
                "end": None,
                "speaker": speaker.strip(),
                "text": content.strip(),
            })
            continue

        if segments:
            segments[-1]["text"] += " " + line
        else:
            segments.append({"start": None, "end": None, "speaker": None, "text": line})

    return segments


def transcribe_with_gemini(audio_path, language, config, log, debug_dir=None, progress=None):
    from google import genai
    from google.genai import types

    api_key = config.get("gemini_api_key")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が設定されていません。config.json または環境変数を確認してください。")

    client = genai.Client(api_key=api_key)
    chunk_seconds = max(60, int(float(config.get("chunk_minutes", 10)) * 60))
    max_output_tokens = config.get("gemini_max_output_tokens", 8192)
    language_hint = LANGUAGE_HINTS.get(language, "")

    workdir = os.path.dirname(audio_path)
    chunk_paths = split_audio_into_chunks(audio_path, workdir, chunk_seconds, log)

    all_segments = []
    raw_responses = []
    prior_tail = ""

    for idx, chunk_path in enumerate(chunk_paths):
        offset = idx * chunk_seconds
        log(f"チャンク {idx + 1}/{len(chunk_paths)} をGeminiへアップロードしています...")
        uploaded = client.files.upload(file=chunk_path)
        uploaded = _wait_for_gemini_file_active(client, uploaded, log)

        continuity_hint = ""
        if prior_tail:
            continuity_hint = (
                "\nこれは会議の続きの音声チャンクです。直前のチャンク末尾の文字起こしは以下の通りです。"
                "同じ人物には同じ話者ラベル(A, B, C...)を使い続けてください。\n" + prior_tail
            )
        prompt = TRANSCRIBE_PROMPT_TEMPLATE.format(
            language_hint=(f"\n{language_hint}" if language_hint else ""),
            continuity_hint=continuity_hint,
        )

        log(f"チャンク {idx + 1}/{len(chunk_paths)} を文字起こししています...")
        response = client.models.generate_content(
            model=config.get("gemini_model", "gemini-2.5-flash"),
            contents=[uploaded, prompt],
            config=types.GenerateContentConfig(max_output_tokens=max_output_tokens),
        )
        raw_text = _extract_response_text(response)
        raw_responses.append(f"--- chunk {idx + 1}/{len(chunk_paths)} ---\n{raw_text}")

        _delete_gemini_file_quietly(client, uploaded)

        chunk_segments = parse_transcript_response(raw_text)
        for seg in chunk_segments:
            if seg["start"] is not None:
                seg["start"] += offset
        all_segments.extend(chunk_segments)

        tail_lines = segments_to_plain_text(chunk_segments).splitlines()
        prior_tail = "\n".join(tail_lines[-5:])

        if progress:
            progress((idx + 1) / len(chunk_paths))

    if debug_dir:
        try:
            debug_path = os.path.join(debug_dir, "transcript_raw_gemini_response.txt")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write("\n\n".join(raw_responses))
        except OSError:
            pass

    if not all_segments:
        raise RuntimeError("Geminiの応答を解析できませんでした(すべてのチャンクが空の応答でした)。")
    return all_segments


# ---------------------------------------------------------------------------
# 文字起こし: ローカル(faster-whisper)
# ---------------------------------------------------------------------------

def transcribe_with_whisper(audio_path, language, config, log):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisperがインストールされていません。`pip install faster-whisper`を実行してください。") from exc

    model_size = config.get("whisper_model_size", "large-v3")
    log(f"ローカルWhisperモデル({model_size})を読み込んでいます(初回はモデルのダウンロードが発生します)...")
    model = WhisperModel(
        model_size,
        device=config.get("whisper_device", "cpu"),
        compute_type=config.get("whisper_compute_type", "int8"),
    )

    whisper_language = None if language == "auto" else language
    log("ローカルで文字起こしを実行しています(話者ラベルは付与されません)...")
    raw_segments, _info = model.transcribe(audio_path, language=whisper_language, vad_filter=True)

    segments = []
    for seg in raw_segments:
        text = seg.text.strip()
        if not text:
            continue
        segments.append({"start": seg.start, "end": seg.end, "speaker": None, "text": text})
    if not segments:
        raise RuntimeError("ローカルWhisperの文字起こし結果が空でした。")
    return segments


# ---------------------------------------------------------------------------
# 文字起こし結果の保存
# ---------------------------------------------------------------------------

def _format_segment_line(seg):
    time_label = format_time(seg["start"])
    prefix = f"[{time_label}] " if time_label is not None else ""
    if seg.get("speaker"):
        prefix += f"{seg['speaker']}: "
    return prefix + seg["text"]


def segments_to_plain_text(segments):
    return "\n".join(_format_segment_line(seg) for seg in segments)


def write_transcript(segments, output_dir, source_file, mode):
    md_path = os.path.join(output_dir, "transcript.md")
    json_path = os.path.join(output_dir, "transcript.json")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 文字起こし\n\n")
        for seg in segments:
            f.write(_format_segment_line(seg) + "\n\n")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_file": source_file,
            "mode": mode,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "segments": segments,
        }, f, ensure_ascii=False, indent=2)

    return md_path, json_path


# ---------------------------------------------------------------------------
# 要約(常にGemini API)
# ---------------------------------------------------------------------------

def summarize_with_gemini(transcript_text, config, log):
    from google import genai
    from google.genai import types

    api_key = config.get("gemini_api_key")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が設定されていません。config.json または環境変数を確認してください。")

    client = genai.Client(api_key=api_key)
    prompt = SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript_text)

    log("Geminiで要約(議事録)を生成しています...")
    response = client.models.generate_content(
        model=config.get("gemini_model", "gemini-2.5-flash"),
        contents=[prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(_extract_response_text(response))


def render_summary_markdown(summary):
    lines = ["# 会議要約", ""]

    lines.append("## 会議概要")
    participants = summary.get("participants") or []
    lines.append(f"- 参加者: {', '.join(participants) if participants else '不明'}")
    lines.append(f"- 目的: {summary.get('purpose') or '不明'}")
    lines.append("")

    lines.append("## 主な議題・論点")
    for topic in summary.get("topics") or []:
        lines.append(f"- {topic}")
    lines.append("")

    lines.append("## 決定事項")
    for decision in summary.get("decisions") or []:
        lines.append(f"- {decision}")
    lines.append("")

    lines.append("## アクションアイテム")
    action_items = summary.get("action_items") or []
    if action_items:
        lines.append("| 担当者 | 内容 | 期限 |")
        lines.append("| --- | --- | --- |")
        for item in action_items:
            owner = item.get("owner") or "未定"
            due = item.get("due") or "未定"
            lines.append(f"| {owner} | {item.get('task', '')} | {due} |")
    lines.append("")

    lines.append("## 次回までのTODO")
    for todo in summary.get("next_todos") or []:
        lines.append(f"- {todo}")
    lines.append("")

    return "\n".join(lines)


def render_summary_html(summary):
    def esc(value):
        return html_lib.escape(str(value)) if value else ""

    def render_list_html(items):
        if not items:
            return '<p class="empty">(なし)</p>'
        rows = "\n".join(f"  <li>{esc(item)}</li>" for item in items)
        return f"<ul>\n{rows}\n</ul>"

    participants = summary.get("participants") or []
    action_items = summary.get("action_items") or []

    action_items_html = '<p class="empty">(なし)</p>'
    if action_items:
        rows = []
        for item in action_items:
            owner = esc(item.get("owner") or "未定")
            task = esc(item.get("task") or "")
            due = esc(item.get("due") or "未定")
            rows.append(f"  <tr><td>{owner}</td><td>{task}</td><td>{due}</td></tr>")
        action_items_html = (
            "<table>\n  <tr><th>担当者</th><th>内容</th><th>期限</th></tr>\n"
            + "\n".join(rows) + "\n</table>"
        )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>会議要約</title>
<style>
  body {{
    font-family: "Segoe UI", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif;
    max-width: 800px; margin: 40px auto; padding: 0 24px 60px;
    line-height: 1.8; color: #1f2328; background: #fff;
  }}
  h1 {{ border-bottom: 3px solid #2563eb; padding-bottom: 10px; }}
  h2 {{ margin-top: 36px; color: #1e3a8a; border-left: 6px solid #2563eb; padding-left: 12px; }}
  ul {{ padding-left: 26px; }}
  li {{ margin-bottom: 6px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
  th, td {{ border: 1px solid #d0d7de; padding: 8px 12px; text-align: left; vertical-align: top; }}
  th {{ background: #f1f5f9; }}
  .meta {{ color: #444; }}
  .empty {{ color: #888; }}
</style>
</head>
<body>
<h1>会議要約</h1>

<h2>会議概要</h2>
<p class="meta">参加者: {esc(', '.join(participants)) if participants else '不明'}<br>
目的: {esc(summary.get('purpose')) or '不明'}</p>

<h2>主な議題・論点</h2>
{render_list_html(summary.get("topics") or [])}

<h2>決定事項</h2>
{render_list_html(summary.get("decisions") or [])}

<h2>アクションアイテム</h2>
{action_items_html}

<h2>次回までのTODO</h2>
{render_list_html(summary.get("next_todos") or [])}

</body>
</html>
"""


def write_summary(summary, output_dir):
    md_path = os.path.join(output_dir, "summary.md")
    json_path = os.path.join(output_dir, "summary.json")
    html_path = os.path.join(output_dir, "summary.html")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_summary_markdown(summary))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_summary_html(summary))

    return md_path, json_path, html_path


def open_in_browser(path, log):
    try:
        webbrowser.open(Path(path).resolve().as_uri())
    except Exception as exc:  # noqa: BLE001 - ブラウザが開けなくてもパイプライン自体は成功として扱う
        log(f"HTMLを自動的に開けませんでした(手動で開いてください): {exc}")


# ---------------------------------------------------------------------------
# パイプライン本体
# ---------------------------------------------------------------------------

def run_pipeline(input_path, mode, language, config, log, progress):
    workdir = tempfile.mkdtemp(prefix="meeting_transcript_")
    try:
        meeting_name = Path(input_path).stem
        run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(config.get("output_dir", "output"), f"{meeting_name}_{run_timestamp}")
        os.makedirs(output_dir, exist_ok=True)

        progress(5)
        audio_path = extract_audio(input_path, workdir, log)
        progress(20)

        if mode == "cloud":
            segments = transcribe_with_gemini(
                audio_path, language, config, log,
                debug_dir=output_dir, progress=make_sub_progress(progress, 20, 60),
            )
        else:
            segments = transcribe_with_whisper(audio_path, language, config, log)
        progress(60)

        transcript_md_path, _ = write_transcript(segments, output_dir, input_path, mode)
        log(f"文字起こしを保存しました: {transcript_md_path}")
        progress(70)

        transcript_text = segments_to_plain_text(segments)
        summary = summarize_with_gemini(transcript_text, config, log)
        progress(90)

        summary_md_path, _, summary_html_path = write_summary(summary, output_dir)
        log(f"要約を保存しました: {summary_md_path}")
        log(f"HTML版の要約を開いています: {summary_html_path}")
        open_in_browser(summary_html_path, log)
        progress(100)

        return output_dir
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("会議録画 文字起こし・要約ツール")
        self.geometry("640x560")
        self.resizable(True, True)

        self.config_data = load_config()
        self.input_path = tk.StringVar()
        self.mode = tk.StringVar(value="cloud")
        self.language = tk.StringVar(value=self.config_data.get("language", "ja"))

        self._build_widgets()

    def _build_widgets(self):
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="会議録画ファイル(.mkv):").grid(row=0, column=0, sticky="w")
        path_row = ttk.Frame(frame)
        path_row.grid(row=1, column=0, columnspan=2, sticky="we")
        path_row.columnconfigure(0, weight=1)
        ttk.Entry(path_row, textvariable=self.input_path).grid(row=0, column=0, sticky="we")
        ttk.Button(path_row, text="参照...", command=self._choose_file).grid(row=0, column=1, padx=(5, 0))

        ttk.Label(frame, text="文字起こし方式:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Radiobutton(
            frame, text="クラウド(Gemini API・簡易話者分離あり)", variable=self.mode, value="cloud"
        ).grid(row=3, column=0, sticky="w")
        ttk.Radiobutton(
            frame, text="ローカル(faster-whisper・話者ラベルなし・音声は外部送信されません)",
            variable=self.mode, value="local"
        ).grid(row=4, column=0, sticky="w")

        ttk.Label(frame, text="主な言語:").grid(row=5, column=0, sticky="w", pady=(10, 0))
        language_row = ttk.Frame(frame)
        language_row.grid(row=6, column=0, columnspan=2, sticky="w")
        for i, code in enumerate(("ja", "en", "auto")):
            ttk.Radiobutton(
                language_row, text=LANGUAGE_LABELS[code], variable=self.language, value=code
            ).grid(row=0, column=i, sticky="w", padx=(0, 10))

        self.run_button = ttk.Button(frame, text="実行", command=self._on_run)
        self.run_button.grid(row=7, column=0, pady=10, sticky="w")

        self.progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate")
        self.progress.grid(row=8, column=0, columnspan=2, sticky="we")

        ttk.Label(frame, text="ログ:").grid(row=9, column=0, sticky="w", pady=(10, 0))
        self.log_text = tk.Text(frame, height=16, state="disabled")
        self.log_text.grid(row=10, column=0, columnspan=2, sticky="nsew")
        frame.rowconfigure(10, weight=1)

    def _choose_file(self):
        path = filedialog.askopenfilename(filetypes=[("MKV files", "*.mkv"), ("All files", "*.*")])
        if path:
            self.input_path.set(path)

    def _log(self, message):
        self.after(0, self._append_log, message)

    def _append_log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_progress(self, value):
        self.after(0, lambda: self.progress.configure(value=value))

    def _on_run(self):
        input_path = self.input_path.get().strip()
        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("エラー", "会議録画ファイル(.mkv)を選択してください。")
            return
        if not self.config_data.get("gemini_api_key"):
            messagebox.showerror(
                "エラー",
                "GEMINI_API_KEY が設定されていません。文字起こし方式に関わらず、要約にはGemini APIを使用するため、"
                "config.json またはGEMINI_API_KEY環境変数を設定してください。",
            )
            return

        self.run_button.configure(state="disabled")
        self.progress.configure(value=0)

        def worker():
            try:
                output_dir = run_pipeline(
                    input_path, self.mode.get(), self.language.get(),
                    self.config_data, self._log, self._set_progress,
                )
                self._log(f"完了しました。出力先: {output_dir}")
                self.after(0, lambda: messagebox.showinfo("完了", f"処理が完了しました。\n出力先: {output_dir}"))
            except Exception as exc:  # noqa: BLE001 - GUIでユーザーにエラー内容を表示するため捕捉する
                self._log(f"エラーが発生しました: {exc}")
                self.after(0, lambda: messagebox.showerror("エラー", str(exc)))
            finally:
                self.after(0, lambda: self.run_button.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
