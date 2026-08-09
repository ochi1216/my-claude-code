#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
朝の一通と同じ見た目・同じOutlook送信の仕組みで、開発の途中経過を
1回だけ送るためのスクリプト。

morning_brief.py は archive フォルダのHTMLを自動で集計するが、今回のような
「今日の修正内容と検証結果」はそこに存在しないデータ（コミット履歴・
ログの集計結果）なので、別のスクリプトとして分けている。
HTMLの見た目とOutlook送信部分（resolve_self_address / deliver）は
morning_brief.py のものをそのまま再利用し、二重実装を避ける。

使い方:
    python send_dev_report.py            プレビューHTMLを書き出すだけ
    python send_dev_report.py --draft    Outlookの下書きに保存
    python send_dev_report.py --send     Outlookで実際に送信する
"""

import argparse
import os
import sys
from datetime import datetime

from morning_brief import esc, deliver


SUBJECT = "[08/09] 修正完了レポート - 成功率94%・確認画面0件"

COMPARISON_ROWS = [
    ("一昨夜（旧版）", "22%", "-", "検知できず全滅"),
    ("昨夜（中間版）", "93%", "51枚 / 64クリック", "1件（待機・再開は成功）"),
    ("本日（最新版）", "94%", "8枚 / 79クリック", "0件"),
]

TODAY_STATS = [
    ("成功率", "94%（74/79本）"),
    ("1本あたりのリクエスト数", "2.06回"),
    ("2巡目 1回で成功", "66本（84%）"),
    ("2巡目 2回で成功", "8本"),
    ("1巡目で捨てたタブ", "8枚（クリック79回中）"),
    ("確認画面（reCAPTCHA）", "0件"),
]

FAILURE_ROWS = [
    ("要約対象外（字幕データなし）", "4本"),
    ("Glasp起動失敗（本当の失敗）", "1本"),
]

TIMELINE = [
    "20:00の定時実行で確認画面(reCAPTCHA)を検知できず、8/37本しか成功しなかった。"
    "判定をページ本文からURLベースに変更し、検知したら中止ではなく待機する仕組みを導入した"
    "（人が解除すれば自動再開する）。",

    "手動での動作確認では正常に見えたが、02:00/05:00の定時チェーンが1秒で完了してしまい、"
    "要約が一度も走っていなかった。原因は \"python check_suspend_lock.py\" を call なしで"
    "裸のまま呼んでいたこと。Windowsのバッチでは call を付けずに別のバッチ/シェル形式のものを"
    "呼ぶと、制御がそちらへ移ったまま戻ってこない。対話プロンプトで直接試すと違いが分からず"
    "「正常」に見えてしまう罠だった。フルパスのpython.exe呼び出しに修正して解消した。",

    "あわせて、1巡目の「使い捨てGlaspクリック」を廃止し、タブ切替・動画読込待ち・字幕確認・"
    "一時停止のみ行う方式に変更した。捨てるGeminiセッションがほぼゼロになった。",

    "失敗理由を実態どおり記録するよう修正した。「字幕なしで要約不可」と「Glasp起動に本当に"
    "失敗」が区別できるようになった。",
]

TODO = [
    "11:30・20:00の定時実行でも同様の結果が出るか、継続確認が必要",
    "Glasp起動の本当の失敗が1本残っている（原因未特定）",
    "1巡目クリック廃止により2巡目の成功率が下がる日がないか、数日分のデータで様子を見る",
]


def build_html():
    comparison_rows_html = ''.join(
        f'<tr>'
        f'<td style="padding:6px 10px;font-weight:bold;">{esc(label)}</td>'
        f'<td style="padding:6px 10px;">{esc(rate)}</td>'
        f'<td style="padding:6px 10px;">{esc(stray)}</td>'
        f'<td style="padding:6px 10px;">{esc(challenge)}</td>'
        f'</tr>'
        for label, rate, stray, challenge in COMPARISON_ROWS
    )

    stats_rows_html = ''.join(
        f'<tr>'
        f'<td style="padding:6px 10px;color:#57606a;">{esc(label)}</td>'
        f'<td style="padding:6px 10px;font-weight:bold;">{esc(value)}</td>'
        f'</tr>'
        for label, value in TODAY_STATS
    )

    failure_rows_html = ''.join(
        f'<li style="margin:3px 0;">{esc(label)}: {esc(count)}</li>'
        for label, count in FAILURE_ROWS
    )

    timeline_html = ''.join(
        f'<li style="margin:8px 0;">{esc(item)}</li>' for item in TIMELINE
    )

    todo_html = ''.join(
        f'<li style="margin:4px 0;">{esc(item)}</li>' for item in TODO
    )

    return f"""<html><body style="font-family:'Segoe UI','Meiryo',sans-serif;
font-size:14px;color:#1f2328;line-height:1.6;">
<div style="max-width:760px;">

<h2 style="margin:0 0 4px 0;font-size:18px;">YouTube要約 修正完了レポート</h2>
<div style="color:#57606a;font-size:12px;margin-bottom:16px;">
本日実施した修正・検証の結果まとめ
</div>

<div style="background:#dafbe1;border-left:4px solid #1a7f37;
padding:10px 14px;margin:16px 0;">
過去数か月で最も良好な結果でした。成功率94%・確認画面0件・失敗理由の分離表示。
</div>

<h3 style="font-size:15px;border-bottom:2px solid #d0d7de;padding-bottom:4px;">
昨夜からの経緯</h3>
<ol style="margin:8px 0;padding-left:20px;">
{timeline_html}
</ol>

<h3 style="font-size:15px;border-bottom:2px solid #d0d7de;padding-bottom:4px;">
本日08:42〜09:02の実行結果（修正後、初の完走）</h3>
<table style="border-collapse:collapse;font-size:13px;margin-bottom:12px;">
{stats_rows_html}
</table>
<div style="font-size:13px;">
失敗の内訳:
<ul style="margin:4px 0;padding-left:20px;">
{failure_rows_html}
</ul>
</div>

<h3 style="font-size:15px;border-bottom:2px solid #d0d7de;padding-bottom:4px;">
比較</h3>
<table style="border-collapse:collapse;font-size:13px;">
<tr style="background:#f6f8fa;">
<th style="padding:6px 10px;text-align:left;">実行</th>
<th style="padding:6px 10px;text-align:left;">成功率</th>
<th style="padding:6px 10px;text-align:left;">1巡目で捨てたタブ</th>
<th style="padding:6px 10px;text-align:left;">確認画面</th>
</tr>
{comparison_rows_html}
</table>

<div style="background:#fff8c5;border-left:4px solid #d4a72c;
padding:10px 14px;margin:16px 0;">
<div style="font-weight:bold;margin-bottom:6px;">未確認・今後の課題</div>
<ul style="margin:0;padding-left:20px;">
{todo_html}
</ul>
</div>

<hr style="border:none;border-top:1px solid #d0d7de;margin:20px 0;">
<div style="color:#8b949e;font-size:11px;">
send_dev_report ／ 開発セッションでの修正・検証結果の1回限りの報告
</div>

</div></body></html>"""


def main():
    parser = argparse.ArgumentParser(description="YouTube要約システム 修正完了レポート")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--send', action='store_true', help='Outlookで実際に送信する')
    group.add_argument('--draft', action='store_true', help='Outlookの下書きに保存する')
    parser.add_argument('--to', default='', help='宛先（省略時は自分宛）')
    args = parser.parse_args()

    mode = 'send' if args.send else ('draft' if args.draft else 'file')
    html = build_html()

    if mode == 'file':
        # deliver()の'file'モードは "morning_brief_*.html" 固定の名前で書き出す
        # （毎朝の本物のダイジェストと紛らわしくなる）ため、プレビューだけは
        # ここで別名にして書き出す。draft/sendはOutlook側の処理でありファイル名
        # の問題がないため、そちらはdeliver()にそのまま任せる。
        path = os.path.abspath(f"dev_report_{datetime.now():%Y%m%d_%H%M%S}.html")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"[OK] プレビューを書き出しました: {path}")
        print("     内容を確認し、問題なければ --draft / --send を付けて実行してください。")
        return 0

    ok = deliver(SUBJECT, html, mode, args.to)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
