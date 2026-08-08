"""
Morning Brief - YouTube要約システム 朝の1通
VERSION 20260808_01

目的:
    夜間バッチ(02:00 / 05:00)の実行結果を、毎朝1通のメールにまとめて届ける。
    「Chromeのタブを見て実行有無を確認する」運用をやめるための実行台帳が主役。

設計方針:
    - youtube_summary_list_*.py 本体には一切手を入れない独立スクリプト。
      本スクリプトが落ちても夜間バッチには影響しない。
    - 真実の情報源は OUTPUT_DIR に残る summary_*.json。
      youtube_summary.log は FileHandler(mode='w') で毎回上書きされ、
      02:00実行分のログが05:00実行分で消えるため、台帳の根拠には使わない。
    - AI呼び出しゼロ。集計と突合だけなのでコストも失敗要因も無い。

使い方:
    # プレビュー（メールを送らずHTMLファイルに書き出す）
    python morning_brief_20260808_01.py

    # Outlookの下書きに保存
    python morning_brief_20260808_01.py --draft

    # 実際に送信（夜間バッチに組み込むのはこれ）
    python morning_brief_20260808_01.py --send

    # 集計対象の時間幅を変える（既定は12時間前まで）
    python morning_brief_20260808_01.py --hours 18 --send
"""

import os
import re
import sys
import json
import argparse
from datetime import datetime, timedelta

# ============================================================================
# 既定値（youtube_summary_list_20260808_01.py と揃えている）
# ============================================================================
DEFAULT_OUTPUT_DIR = r"C:\Users\nx023836\Nexperia\My Private - Documents\Summary"
DEFAULT_CONFIG_FILE = "config.json"
DEFAULT_LOG_FILE = "youtube_summary.log"

# 本体の ConfigManager.get_playlist_config() の既定値と同じ。
# config.json に playlists 設定があればそちらを優先する。
DEFAULT_PLAYLISTS = {
    "V":  "PL0UGJjoPnxKgZaJvHD5lGzOmGnEAdrn9H",
    "S":  "PL0UGJjoPnxKjT1ClcCwngoCDhModNIG3H",
    "A":  "PL0UGJjoPnxKgphke6I63QVyHeToWaNSTD",
    "B":  "PL0UGJjoPnxKhM3jXPMhNxONyvyZbClDuM",
    "N":  "PL0UGJjoPnxKj6T0VlBmyxVqVmBIK1h3G6",
    "M":  "PL0UGJjoPnxKhX6NN6K5GSPCzh9H8bK1F3",
}

# 異常判定のしきい値
SHORT_SUMMARY_CHARS = 300      # これ未満の要約は「中身が薄い」として警告
SLOW_PROCESSING_SEC = 55.0     # 60秒タイムアウトに張り付いた疑い

# summary_{playlist}_{YYYYMMDD_HHMMSS}.json
RE_SUMMARY_JSON = re.compile(r'^summary_(.*)_(\d{8}_\d{6})\.json$')
RE_SUMMARY_HTML = re.compile(r'^summary_(.*)_(\d{8}_\d{6})\.html$')


# ============================================================================
# 収集
# ============================================================================
def load_expected_playlists(config_file):
    """処理されるはずのプレイリスト一覧を取得する。

    config.json に設定があればそれを、無ければ本体の既定値を使う。
    ここで得た一覧が「あるべき姿」となり、実際の出力と突合して欠落を検出する。
    """
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            for key in ('playlists', 'playlist_config'):
                value = cfg.get(key)
                if isinstance(value, dict) and value:
                    return dict(value), config_file
        except Exception as e:
            print(f"[WARN] {config_file} の読み込みに失敗しました（既定値を使います）: {e}")
    return dict(DEFAULT_PLAYLISTS), "(既定値)"


def parse_timestamp(stamp):
    """'YYYYMMDD_HHMMSS' を datetime に変換する。失敗時は None。"""
    try:
        return datetime.strptime(stamp, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def collect_runs(output_dir, since):
    """since 以降に出力された summary_*.json を読み、プレイリスト単位に集計する。"""
    if not os.path.isdir(output_dir):
        return None, []

    html_by_key = {}
    for name in os.listdir(output_dir):
        m = RE_SUMMARY_HTML.match(name)
        if m:
            html_by_key[(m.group(1), m.group(2))] = os.path.join(output_dir, name)

    runs = []
    problems = []
    for name in sorted(os.listdir(output_dir)):
        m = RE_SUMMARY_JSON.match(name)
        if not m:
            continue
        playlist, stamp = m.group(1), m.group(2)
        ts = parse_timestamp(stamp)
        if ts is None or ts < since:
            continue

        path = os.path.join(output_dir, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            problems.append(f"{name} を読めませんでした: {e}")
            continue

        results = data.get('results') or []
        videos = []
        for r in results:
            video = r.get('video') or {}
            summary = r.get('summary') or ""
            videos.append({
                'title': video.get('title') or '(タイトル不明)',
                'channel': video.get('channel') or '',
                'url': video.get('url') or '',
                'duration': video.get('duration') or '',
                'success': bool(r.get('success')),
                'summary_len': len(summary),
                'processing_time': float(r.get('processing_time') or 0.0),
                'error_message': r.get('error_message') or '',
                'gemini_url': r.get('gemini_url') or '',
            })

        runs.append({
            'playlist': playlist,
            'timestamp': ts,
            'json_path': path,
            'html_path': html_by_key.get((playlist, stamp), ''),
            'videos': videos,
        })

    return runs, problems


# ============================================================================
# 突合・判定
# ============================================================================
def build_ledger(expected, runs):
    """あるべきプレイリスト一覧と実際の出力を突合して実行台帳を作る。

    出力JSONが1件も無いプレイリストは「欠落」。
    2026-08-08未明の実行では S / B / M がここに該当していた
    （invalid session id で丸ごとスキップされていたが誰も気づけなかった）。
    """
    by_playlist = {}
    for run in runs:
        by_playlist.setdefault(run['playlist'], []).append(run)

    ledger = []
    for name in expected:
        entries = by_playlist.get(name, [])
        videos = [v for e in entries for v in e['videos']]
        ok = sum(1 for v in videos if v['success'])
        ng = len(videos) - ok

        if not entries:
            status = 'missing'
        elif ng:
            status = 'partial'
        else:
            status = 'ok'

        ledger.append({
            'playlist': name,
            'status': status,
            'runs': len(entries),
            'total': len(videos),
            'ok': ok,
            'ng': ng,
            'last_run': max((e['timestamp'] for e in entries), default=None),
            'html_path': next((e['html_path'] for e in reversed(entries) if e['html_path']), ''),
        })

    # 設定に無いプレイリストの出力があれば、それも台帳に載せる（見落とし防止）
    for name in sorted(set(by_playlist) - set(expected)):
        entries = by_playlist[name]
        videos = [v for e in entries for v in e['videos']]
        ok = sum(1 for v in videos if v['success'])
        ledger.append({
            'playlist': name,
            'status': 'unexpected',
            'runs': len(entries),
            'total': len(videos),
            'ok': ok,
            'ng': len(videos) - ok,
            'last_run': max((e['timestamp'] for e in entries), default=None),
            'html_path': next((e['html_path'] for e in reversed(entries) if e['html_path']), ''),
        })
    return ledger


def detect_anomalies(ledger, runs, log_file):
    """静かに壊れている箇所を洗い出す。"""
    items = []

    missing = [row['playlist'] for row in ledger if row['status'] == 'missing']
    if missing:
        items.append(
            f"プレイリスト {', '.join(missing)} の出力がありません。"
            "対象動画が無かったか、処理が丸ごとスキップされた可能性があります。"
        )

    for row in ledger:
        if row['status'] == 'unexpected':
            items.append(f"設定に無いプレイリスト {row['playlist']} の出力があります。")

    failed = [(r['playlist'], v) for r in runs for v in r['videos'] if not v['success']]
    for playlist, v in failed:
        reason = v['error_message'] or '理由不明'
        items.append(f"[{playlist}] 要約失敗: {v['title'][:40]} — {reason[:60]}")

    short = [(r['playlist'], v) for r in runs for v in r['videos']
             if v['success'] and v['summary_len'] < SHORT_SUMMARY_CHARS]
    for playlist, v in short:
        items.append(
            f"[{playlist}] 要約が短すぎます({v['summary_len']}字): {v['title'][:40]}"
        )

    # 60秒タイムアウトへの張り付きは、終了検出が効いていないサイン。
    # 2026-08-08の実機ログでは12件中12件がこの状態だった。
    slow = [(r['playlist'], v) for r in runs for v in r['videos']
            if v['processing_time'] >= SLOW_PROCESSING_SEC]
    if slow:
        items.append(
            f"要約完了の検出が効いていない可能性: {len(slow)}件が"
            f"{SLOW_PROCESSING_SEC:.0f}秒以上かかっています（タイムアウト待ちの疑い）。"
        )

    if not os.path.exists(log_file):
        items.append(f"ログファイル {log_file} が見つかりません。")

    return items


# ============================================================================
# 組み立て
# ============================================================================
def build_subject(ledger, runs):
    total_ok = sum(row['ok'] for row in ledger)
    done = sum(1 for row in ledger if row['status'] in ('ok', 'partial'))
    expected_count = sum(1 for row in ledger if row['status'] != 'unexpected')
    ng = sum(row['ng'] for row in ledger)

    head = "実行OK" if done == expected_count and not ng else "要確認"
    subject = (f"[{datetime.now():%m/%d}] {head} "
               f"{done}/{expected_count} ・ 要約{total_ok}本")
    if ng:
        subject += f" ・ 失敗{ng}本"
    return subject


def esc(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


STATUS_LABEL = {
    'ok':         ('✅', '#1a7f37'),
    'partial':    ('⚠️', '#9a6700'),
    'missing':    ('❌', '#cf222e'),
    'unexpected': ('❓', '#8250df'),
}


def build_html(ledger, runs, anomalies, since, output_dir, config_source):
    now = datetime.now()
    total_videos = sum(row['total'] for row in ledger)
    total_ok = sum(row['ok'] for row in ledger)

    rows = []
    for row in ledger:
        mark, color = STATUS_LABEL[row['status']]
        if row['status'] == 'missing':
            detail = '出力なし'
        else:
            detail = f"{row['ok']}本"
            if row['ng']:
                detail += f" / 失敗{row['ng']}本"
        last = f"{row['last_run']:%H:%M}" if row['last_run'] else '—'
        rows.append(
            f'<tr>'
            f'<td style="padding:6px 10px;font-weight:bold;">{esc(row["playlist"])}</td>'
            f'<td style="padding:6px 10px;color:{color};">{mark}</td>'
            f'<td style="padding:6px 10px;">{esc(detail)}</td>'
            f'<td style="padding:6px 10px;color:#57606a;">{esc(last)}</td>'
            f'</tr>'
        )

    if anomalies:
        anomaly_html = (
            '<div style="background:#fff8c5;border-left:4px solid #d4a72c;'
            'padding:10px 14px;margin:16px 0;">'
            '<div style="font-weight:bold;margin-bottom:6px;">要確認</div>'
            '<ul style="margin:0;padding-left:20px;">'
            + ''.join(f'<li style="margin:3px 0;">{esc(a)}</li>' for a in anomalies)
            + '</ul></div>'
        )
    else:
        anomaly_html = (
            '<div style="background:#dafbe1;border-left:4px solid #1a7f37;'
            'padding:10px 14px;margin:16px 0;">'
            '異常は検出されませんでした。</div>'
        )

    video_blocks = []
    for run in sorted(runs, key=lambda r: (r['playlist'], r['timestamp'])):
        if not run['videos']:
            continue
        lines = []
        for v in run['videos']:
            mark = '' if v['success'] else '❌ '
            title = esc(v['title'])
            link = f'<a href="{esc(v["url"])}">{title}</a>' if v['url'] else title
            meta = ' / '.join(x for x in (esc(v['channel']), esc(v['duration'])) if x)
            gemini = (f' <a href="{esc(v["gemini_url"])}" '
                      f'style="color:#8250df;">[Gemini]</a>') if v['gemini_url'] else ''
            lines.append(
                f'<li style="margin:5px 0;">{mark}{link}{gemini}'
                f'<br><span style="color:#57606a;font-size:12px;">{meta}</span></li>'
            )
        html_link = ''
        if run['html_path']:
            html_link = (f' <a href="file:///{esc(run["html_path"])}" '
                         f'style="font-size:12px;">要約HTML</a>')
        video_blocks.append(
            f'<div style="margin:14px 0;">'
            f'<div style="font-weight:bold;">{esc(run["playlist"])} '
            f'<span style="font-weight:normal;color:#57606a;font-size:12px;">'
            f'{run["timestamp"]:%m/%d %H:%M}</span>{html_link}</div>'
            f'<ul style="margin:4px 0;padding-left:20px;">{"".join(lines)}</ul></div>'
        )

    videos_html = ''.join(video_blocks) or '<p style="color:#57606a;">対象期間に新しい要約はありません。</p>'

    return f"""<html><body style="font-family:'Segoe UI','Meiryo',sans-serif;
font-size:14px;color:#1f2328;line-height:1.6;">
<div style="max-width:760px;">

<h2 style="margin:0 0 4px 0;font-size:18px;">YouTube要約 朝の1通</h2>
<div style="color:#57606a;font-size:12px;margin-bottom:16px;">
{since:%m/%d %H:%M} 〜 {now:%m/%d %H:%M} の実行結果 ／ 要約 {total_ok} / {total_videos} 本
</div>

<h3 style="font-size:15px;border-bottom:2px solid #d0d7de;padding-bottom:4px;">実行台帳</h3>
<table style="border-collapse:collapse;font-size:13px;">
<tr style="background:#f6f8fa;">
<th style="padding:6px 10px;text-align:left;">分類</th>
<th style="padding:6px 10px;text-align:left;">状態</th>
<th style="padding:6px 10px;text-align:left;">要約</th>
<th style="padding:6px 10px;text-align:left;">最終</th>
</tr>
{''.join(rows)}
</table>

{anomaly_html}

<h3 style="font-size:15px;border-bottom:2px solid #d0d7de;padding-bottom:4px;">
今朝の要約一覧</h3>
{videos_html}

<hr style="border:none;border-top:1px solid #d0d7de;margin:20px 0;">
<div style="color:#8b949e;font-size:11px;">
morning_brief_20260808_01 ／ 出力先: {esc(output_dir)} ／ プレイリスト定義: {esc(config_source)}
</div>

</div></body></html>"""


# ============================================================================
# 送信
# ============================================================================
def deliver(subject, html, mode, to_addr):
    """mode: 'file' | 'draft' | 'send'"""
    if mode == 'file':
        path = os.path.abspath(f"morning_brief_{datetime.now():%Y%m%d_%H%M%S}.html")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"[OK] プレビューを書き出しました: {path}")
        print("     内容を確認し、問題なければ --draft / --send を付けて実行してください。")
        return True

    try:
        import win32com.client
    except ImportError:
        print("[ERROR] pywin32 が見つかりません。Outlook連携には次が必要です:")
        print('        "%PYTHON_EXE%" -m pip install pywin32')
        print("        （プレビューだけなら引数なしで実行してください）")
        return False

    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem
        if to_addr:
            mail.To = to_addr
        mail.Subject = subject
        mail.HTMLBody = html
        if mode == 'send':
            mail.Send()
            print(f"[OK] 送信しました: {subject}")
        else:
            mail.Save()
            print(f"[OK] 下書きに保存しました: {subject}")
        return True
    except Exception as e:
        print(f"[ERROR] Outlook操作に失敗しました: {e}")
        return False


# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="YouTube要約システム 朝の1通")
    parser.add_argument('--hours', type=float, default=12.0,
                        help='何時間前までの出力を集計するか（既定12）')
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR,
                        help='要約の出力先フォルダ')
    parser.add_argument('--config', default=DEFAULT_CONFIG_FILE,
                        help='プレイリスト定義を読むconfig.json')
    parser.add_argument('--log-file', default=DEFAULT_LOG_FILE)
    parser.add_argument('--to', default='', help='宛先アドレス（省略時は自分の既定）')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--send', action='store_true', help='Outlookで実際に送信する')
    group.add_argument('--draft', action='store_true', help='Outlookの下書きに保存する')
    args = parser.parse_args()

    since = datetime.now() - timedelta(hours=args.hours)

    expected, config_source = load_expected_playlists(args.config)
    runs, problems = collect_runs(args.output_dir, since)

    if runs is None:
        print(f"[ERROR] 出力フォルダが見つかりません: {args.output_dir}")
        return 1

    ledger = build_ledger(expected, runs)
    anomalies = detect_anomalies(ledger, runs, args.log_file) + problems

    subject = build_subject(ledger, runs)
    html = build_html(ledger, runs, anomalies, since, args.output_dir, config_source)

    mode = 'send' if args.send else ('draft' if args.draft else 'file')
    ok = deliver(subject, html, mode, args.to)

    # 台帳の要点は標準出力にも出す（バッチのログに残るように）
    print(f"--- {subject} ---")
    for row in ledger:
        mark = STATUS_LABEL[row['status']][0]
        print(f"  {mark} {row['playlist']}: {row['ok']}本"
              + (f" / 失敗{row['ng']}本" if row['ng'] else ""))
    for a in anomalies:
        print(f"  ! {a}")

    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
