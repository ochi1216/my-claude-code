#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
要約処理が「Googleの確認画面の解除待ち」で停止中かどうかを判定する。

なぜ必要か:
  確認画面を検知した実行は、その場で終了せず、人が手で解除するのを待つ。
  待っている間も 02:00 / 05:00 の定時チェーンは起動してしまうため、
  同じChrome（デバッグポート9222）を複数のプロセスが奪い合うことになる。
  さらにチェーンの Step 1 はプレイリストからの削除であり、要約が終わって
  いない動画が先に消えるおそれがある。したがって待機中は、要約だけでなく
  チェーン全体を空振りさせる必要がある。

終了コード:
  1 ... 待機中。呼び出し側は後続の処理をスキップすること
  0 ... 待機していない（または期限切れ）。通常どおり実行してよい

期限切れのロックはこのスクリプトが削除する。要約プロセスが異常終了して
ロックが残っても、期限を過ぎればチェーンは自動的に復帰する。
"""

import json
import os
import sys
import time
from datetime import datetime

LOCK_FILE = "glasp_suspended.lock"

EXIT_SUSPENDED = 1
EXIT_FREE = 0


def main():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOCK_FILE)

    if not os.path.exists(path):
        print("FREE: 待機中のプロセスはありません。")
        return EXIT_FREE

    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as error:
        # 壊れたロックで夜間のチェーンが永久に止まるほうが害が大きいため、
        # 読めないロックは削除して通常実行に倒す。
        print(f"WARN: ロックファイルを読めませんでした（{error}）。削除して続行します。")
        try:
            os.remove(path)
        except Exception:
            pass
        return EXIT_FREE

    expires_at = payload.get("expires_at", 0)
    remaining = expires_at - time.time()

    if remaining <= 0:
        print("EXPIRED: 待機の期限が過ぎています。ロックを削除して続行します。")
        try:
            os.remove(path)
        except Exception as error:
            print(f"WARN: ロックの削除に失敗しました: {error}")
        return EXIT_FREE

    suspended_at = payload.get("suspended_at", "不明")
    expires_text = payload.get("expires_at_text", "不明")
    print("SUSPENDED: 要約処理がGoogleの確認画面の解除待ちで停止中です。")
    print(f"  停止した時刻 : {suspended_at}")
    print(f"  待機の期限   : {expires_text}（あと約{int(remaining / 60)}分）")
    print(f"  PID          : {payload.get('pid', '不明')}")
    print("  Chromeに残っている確認画面のタブを手動で解除してください。")
    print("  解除すると、停止した動画から自動で再開します。")
    print(f"  現在時刻     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return EXIT_SUSPENDED


if __name__ == "__main__":
    sys.exit(main())
