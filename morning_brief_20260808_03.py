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

# summary_{playlist}_{YYYYMMDD_HHMMSS}.json / .html
RE_SUMMARY_JSON = re.compile(r'^summary_(.*)_(\d{8}_\d{6})\.json$')
RE_SUMMARY_HTML = re.compile(r'^summary_(.*)_(\d{8}_\d{6})\.html$')

# [20260808_02] 本体の output_format 既定値は 'html' で 'both' ではないため、
# save_json() は呼ばれずJSONは1件も出力されない（実機で確認）。
# HTMLしか無くても台帳が成立するよう、生成HTMLから直接読み取る。
# 生成側 _generate_modern_html() の実際の出力:
#   <div id="card-{i}" class="video-card" data-index="{i}">           成功
#   <div id="card-{i}" class="video-card error-card" data-index="{i}"> 失敗
#   <div class="video-title">{i}. {タイトル}</div>
RE_CARD = re.compile(r'class="video-card( error-card)?"')
RE_CARD_TITLE = re.compile(r'<div class="video-title">(.*?)</div>', re.DOTALL)
RE_TAG = re.compile(r'<[^>]+>')


# ============================================================================
# 収集
# ============================================================================
def check_output_format(config_file):
    """config.json の general.output_format を確認する。

    [20260808_03] 本体のコード既定値は 'both' に変更したが、PC上の
    config.json に古い設定が保存されているとそちらが優先され、
    JSONが出ないまま気づけない。設定変更が効いていないことを検出する。
    戻り値: (値, 警告文 or None)
    """
    if not os.path.exists(config_file):
        return None, None
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        return None, None

    value = (cfg.get('general') or {}).get('output_format')
    if value is None:
        return None, None
    if value != 'both':
        return value, (
            f"{config_file} の general.output_format が '{value}' のため、"
            "コード側の既定値('both')が上書きされています。"
            "JSONを出すには 'both' に変更してください。"
        )
    return value, None


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


def unescape_min(text):
    return (text.replace('&amp;', '&').replace('&lt;', '<')
            .replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'"))


def parse_summary_html(path):
    """生成済みの要約HTMLから動画の一覧と成否を読み取る。

    JSONが出力されていない環境（output_format='html'）でも
    実行台帳が成立するようにするための読み取り経路。
    JSONほどの情報量は無いが、台帳に必要な
    「どの分類が・いつ・何本・何本失敗したか」は取得できる。
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            html = f.read()
    except Exception:
        return None

    statuses = [bool(m.group(1)) for m in RE_CARD.finditer(html)]
    titles = [unescape_min(RE_TAG.sub('', t)).strip()
              for t in RE_CARD_TITLE.findall(html)]

    videos = []
    for idx, is_error in enumerate(statuses):
        raw = titles[idx] if idx < len(titles) else ''
        # 生成側は "1. タイトル" の形式で出力している
        title = re.sub(r'^\s*\d+\.\s*', '', raw) or '(タイトル不明)'
        videos.append({
            'title': title,
            'channel': '',
            'url': '',
            'duration': '',
            'success': not is_error,
            'summary_len': -1,        # HTML経路では取得できない
            'processing_time': 0.0,   # 同上（60秒張り付き判定は行わない）
            'error_message': '' if not is_error else '(HTMLでは理由不明)',
            'gemini_url': '',
        })
    return videos


def parse_timestamp(stamp):
    """'YYYYMMDD_HHMMSS' を datetime に変換する。失敗時は None。"""
    try:
        return datetime.strptime(stamp, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def collect_runs(output_dir, since):
    """since 以降に出力された summary_*.json を読み、プレイリスト単位に集計する。

    [20260808_02] 戻り値に scan（走査の内訳）を追加した。
    「要約0本」のとき、フォルダのパス違いなのか、命名規則の相違なのか、
    夜間バッチ自体が動いていないのかが区別できず切り分け不能だったため。
    """
    scan = {
        'dir_exists': os.path.isdir(output_dir),
        'files_total': 0,
        'json_matched': 0,
        'html_matched': 0,
        'in_window': 0,
        'newest_name': '',
        'newest_ts': None,
        'sample': [],
    }
    if not scan['dir_exists']:
        return None, [], scan

    all_names = sorted(os.listdir(output_dir))
    scan['files_total'] = len(all_names)
    scan['sample'] = [n for n in all_names if n.lower().endswith(('.json', '.html'))][-5:]

    # (playlist, stamp) -> {'json': path, 'html': path}
    found = {}
    for name in all_names:
        mj = RE_SUMMARY_JSON.match(name)
        mh = RE_SUMMARY_HTML.match(name)
        if mj:
            scan['json_matched'] += 1
            key, kind = (mj.group(1), mj.group(2)), 'json'
        elif mh:
            scan['html_matched'] += 1
            key, kind = (mh.group(1), mh.group(2)), 'html'
        else:
            continue

        ts = parse_timestamp(key[1])
        if ts is not None and (scan['newest_ts'] is None or ts > scan['newest_ts']):
            scan['newest_ts'] = ts
            scan['newest_name'] = name
        found.setdefault(key, {})[kind] = os.path.join(output_dir, name)

    runs = []
    problems = []
    for (playlist, stamp), paths in sorted(found.items(), key=lambda kv: kv[0][1]):
        ts = parse_timestamp(stamp)
        if ts is None or ts < since:
            continue
        scan['in_window'] += 1

        videos = None
        source = ''
        # JSONがあれば情報量が多いので優先。無ければHTMLから読む。
        if 'json' in paths:
            try:
                with open(paths['json'], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                videos = []
                for r in (data.get('results') or []):
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
                source = 'json'
            except Exception as e:
                problems.append(f"{os.path.basename(paths['json'])} を読めませんでした: {e}")
                videos = None

        if videos is None and 'html' in paths:
            videos = parse_summary_html(paths['html'])
            source = 'html'
            if videos is None:
                problems.append(f"{os.path.basename(paths['html'])} を読めませんでした")
                continue

        if videos is None:
            continue

        runs.append({
            'playlist': playlist,
            'timestamp': ts,
            'json_path': paths.get('json', ''),
            'html_path': paths.get('html', ''),
            'source': source,
            'videos': videos,
        })

    return runs, problems, scan


def describe_scan(scan, output_dir, since):
    """走査結果を人間が読める診断メッセージにする。"""
    lines = [f"出力フォルダ: {output_dir}"]
    if not scan['dir_exists']:
        lines.append("→ フォルダが存在しません。パスをご確認ください。")
        return lines

    lines.append(
        f"ファイル総数 {scan['files_total']} / "
        f"summary_*.json {scan['json_matched']}件 / "
        f"summary_*.html {scan['html_matched']}件 / "
        f"対象期間内 {scan['in_window']}件"
    )
    if scan['json_matched'] == 0 and scan['html_matched'] > 0:
        lines.append(
            "→ JSONが1件もありません。本体の output_format 既定値が 'html' のため "
            "save_json() が呼ばれていません。HTMLから読み取って台帳を作ります"
            "（config.json の general.output_format を 'both' にすると詳細が増えます）。"
        )
    if scan['newest_ts']:
        age = (datetime.now() - scan['newest_ts']).total_seconds() / 3600.0
        lines.append(
            f"最新の要約ファイル: {scan['newest_name']} "
            f"({scan['newest_ts']:%m/%d %H:%M} = {age:.1f}時間前)"
        )
        if scan['in_window'] == 0:
            lines.append(
                f"→ 最新でも対象期間({since:%m/%d %H:%M}以降)より古いです。"
                "夜間バッチが動いていないか、--hours を伸ばす必要があります。"
            )
    elif scan['files_total'] == 0:
        lines.append("→ フォルダが空です。夜間バッチの出力先が別の場所かもしれません。")
    else:
        lines.append(
            "→ summary_{分類}_{YYYYMMDD_HHMMSS}.json に一致するファイルがありません。"
        )
        if scan['sample']:
            lines.append("  フォルダ内の例: " + ", ".join(scan['sample']))
    return lines


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

    # summary_len が -1 の動画はHTML経路で情報が取れていないため判定対象外
    short = [(r['playlist'], v) for r in runs for v in r['videos']
             if v['success'] and 0 <= v['summary_len'] < SHORT_SUMMARY_CHARS]
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
def resolve_self_address(outlook):
    """Outlookから自分自身の送信可能なアドレスを取得する。

    環境によって取れる経路が違うため、確実なものから順に試す。
    どれも失敗した場合は空文字を返し、呼び出し側で --to を促す。
    """
    try:
        ns = outlook.GetNamespace("MAPI")
    except Exception:
        return ""

    # Exchange環境: 表示名ではなくSMTPアドレスを取る
    try:
        addr = ns.CurrentUser.AddressEntry.GetExchangeUser().PrimarySmtpAddress
        if addr:
            return str(addr)
    except Exception:
        pass

    # POP/IMAP等: 最初のアカウントのSMTPアドレス
    try:
        accounts = ns.Accounts
        if accounts.Count >= 1:
            addr = accounts.Item(1).SmtpAddress
            if addr:
                return str(addr)
    except Exception:
        pass

    # 最後の手段: CurrentUserのAddress（Exchange DN形式のこともある）
    try:
        addr = ns.CurrentUser.Address
        if addr:
            return str(addr)
    except Exception:
        pass

    return ""


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

        # [20260808_02] 宛先が空だとOutlookが
        # 「送信先を指定する必要があります」で送信を拒否する。
        # 省略時は自分自身のアドレスを解決して自分宛に送る。
        if not to_addr:
            to_addr = resolve_self_address(outlook)
            if to_addr:
                print(f"[INFO] 宛先を自分宛に設定しました: {to_addr}")
            else:
                print("[ERROR] 自分のメールアドレスを取得できませんでした。")
                print("        --to your.name@example.com のように宛先を指定してください。")
                return False

        mail = outlook.CreateItem(0)  # 0 = olMailItem
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
    runs, problems, scan = collect_runs(args.output_dir, since)

    scan_lines = describe_scan(scan, args.output_dir, since)

    fmt_value, fmt_warning = check_output_format(args.config)
    if fmt_value is not None:
        scan_lines.append(f"config.json の output_format: '{fmt_value}'")
    if fmt_warning:
        scan_lines.append("→ " + fmt_warning)

    # [20260808_02] 走査の内訳は必ず先に出す。
    # 「要約0本」の原因がパス違いなのかバッチ未実行なのかを切り分けるため。
    print("--- 走査結果 ---")
    for line in scan_lines:
        print(f"  {line}")
    print()

    if runs is None:
        print(f"[ERROR] 出力フォルダが見つかりません: {args.output_dir}")
        print("        --output-dir で正しいパスを指定してください。")
        return 1

    ledger = build_ledger(expected, runs)
    anomalies = detect_anomalies(ledger, runs, args.log_file) + problems

    # 設定が効いていない場合はメール本文にも載せる（気づけないと意味がないため）
    if fmt_warning:
        anomalies = [fmt_warning] + anomalies

    # 1件も拾えていない場合は、走査結果そのものを異常として本文に載せる
    if scan['in_window'] == 0:
        anomalies = scan_lines + anomalies

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
