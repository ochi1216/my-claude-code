#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Glasp起動の計測ログ(glasp_measure.log)を集計する。

目的:
  「1巡目の無駄打ちクリックは本当に必要か」を、推測ではなく実測で判断するための材料を出す。

見たいこと:
  1. Glaspをクリックする直前に、字幕は「存在するという宣言(api)」だけだったのか、
     それとも「実際に描画された文字起こし行(seg)」まで揃っていたのか。
  2. その違いによって、2巡目の成功率／必要クリック数に差が出るか。
     → 差が出るなら、1巡目のクリックを「字幕を実体化させる待ち」に置き換えれば
        捨てGeminiセッションをゼロにできる。
        差が出ないなら、効いているのは純粋に経過時間であり、
        1巡目のクリック自体は不要ということになる。
  3. 1巡目のクリックが実際に何枚のGeminiタブを開いて捨てているか（reCAPTCHA圧の実測）。

使い方:
    python analyze_glasp_measure.py
    python analyze_glasp_measure.py --file glasp_measure.log
    python analyze_glasp_measure.py --since 2026-08-08
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

DEFAULT_LOG = "glasp_measure.log"


def parse_fields(payload):
    """key=value|key=value 形式を辞書へ。"""
    fields = {}
    for chunk in payload.split("|"):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        fields[key.strip()] = value.strip()
    return fields


def as_bool(value):
    """'True'/'False'/'None'/'' を三値で返す。判定不能はNone。"""
    if value in ("True", "true"):
        return True
    if value in ("False", "false"):
        return False
    return None


def as_int(value, default=-1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_records(path, since=None):
    """1行 = (timestamp, kind, fields) に分解して返す。"""
    records = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            stamp, _, rest = raw.partition("\t")
            if not rest:
                # タブ区切りが無い行（通常ログから拾った場合など）も一応受ける
                stamp, rest = "", raw
            if since and stamp and stamp[:10] < since:
                continue
            kind, _, payload = rest.partition("|")
            if not kind.startswith("GLASP_MEASURE_"):
                continue
            records.append((stamp, kind, parse_fields(payload)))
    return records


def pct(numerator, denominator):
    if not denominator:
        return "  -  "
    return f"{100.0 * numerator / denominator:5.1f}%"


def report_gate(records):
    """クリック直前のゲート内訳を、1巡目/2巡目それぞれで集計する。"""
    print("=" * 72)
    print("【1】Glaspクリック直前の字幕の状態")
    print("=" * 72)

    by_round = defaultdict(Counter)
    seg_counts = defaultdict(list)

    for _, kind, fields in records:
        if kind != "GLASP_MEASURE_GATE":
            continue
        rnd = fields.get("round", "?")
        api = as_bool(fields.get("api"))
        seg = as_bool(fields.get("seg"))
        if seg:
            category = "seg実体あり"
        elif api:
            category = "api宣言のみ"
        else:
            category = "字幕なし"
        by_round[rnd][category] += 1
        by_round[rnd]["合計"] += 1
        seg_counts[rnd].append(as_int(fields.get("seg_count"), 0))

    if not by_round:
        print("  GLASP_MEASURE_GATE 行がありません。")
        return

    for rnd in sorted(by_round):
        counter = by_round[rnd]
        total = counter["合計"]
        label = {"1": "1巡目", "2": "2巡目"}.get(rnd, f"round={rnd}")
        print(f"\n  [{label}] クリック回数 {total}")
        for category in ("seg実体あり", "api宣言のみ", "字幕なし"):
            count = counter[category]
            print(f"    {category:<12} {count:4d} 本  ({pct(count, total)})")
        counts = [c for c in seg_counts[rnd] if c > 0]
        if counts:
            counts.sort()
            median = counts[len(counts) // 2]
            print(f"    文字起こし行数（実体があった回のみ）: "
                  f"中央値 {median} / 最小 {counts[0]} / 最大 {counts[-1]}")

    print("\n  ※「api宣言のみ」は、字幕トラックが存在すると宣言されているだけで、")
    print("     文字起こし本文はまだページ上に出ていない状態。")
    print("     現在のゲートはこの状態でも通過してGlaspをクリックしている。")


def report_outcome(records):
    """ゲートの状態別に、2巡目の成功率と必要クリック数を出す。ここが本命。"""
    print()
    print("=" * 72)
    print("【2】クリック直前の状態別 × 2巡目の結果  ← 判断の本命")
    print("=" * 72)

    buckets = defaultdict(lambda: {"total": 0, "success": 0, "clicks": []})
    reasons = Counter()

    for _, kind, fields in records:
        if kind != "GLASP_MEASURE_VIDEO":
            continue
        # 2巡目時点の状態を優先。2巡目に到達していない動画は1巡目の状態で分類する。
        seg = as_bool(fields.get("r2_seg"))
        api = as_bool(fields.get("r2_api"))
        if seg is None and api is None:
            seg = as_bool(fields.get("r1_seg"))
            api = as_bool(fields.get("r1_api"))

        if seg:
            key = "seg実体あり"
        elif api:
            key = "api宣言のみ"
        elif api is None and seg is None:
            key = "状態不明"
        else:
            key = "字幕なし"

        success = as_bool(fields.get("success")) is True
        bucket = buckets[key]
        bucket["total"] += 1
        if success:
            bucket["success"] += 1
            click = as_int(fields.get("r2_click"), -1)
            if click > 0:
                bucket["clicks"].append(click)
        else:
            reason = fields.get("reason", "")
            reasons[reason if reason else "(理由なし)"] += 1

    if not buckets:
        print("  GLASP_MEASURE_VIDEO 行がありません。")
        return

    print(f"\n  {'状態':<12} {'本数':>5} {'成功':>5} {'成功率':>7}   2巡目の必要クリック数")
    print("  " + "-" * 62)
    order = ["seg実体あり", "api宣言のみ", "字幕なし", "状態不明"]
    for key in order:
        if key not in buckets:
            continue
        bucket = buckets[key]
        clicks = bucket["clicks"]
        if clicks:
            one_shot = sum(1 for c in clicks if c == 1)
            click_text = (f"1回で成功 {one_shot}/{len(clicks)} "
                          f"({pct(one_shot, len(clicks)).strip()})")
        else:
            click_text = "-"
        print(f"  {key:<12} {bucket['total']:5d} {bucket['success']:5d} "
              f"{pct(bucket['success'], bucket['total']):>7}   {click_text}")

    seg_bucket = buckets.get("seg実体あり")
    api_bucket = buckets.get("api宣言のみ")
    print()
    if seg_bucket and api_bucket and seg_bucket["total"] >= 5 and api_bucket["total"] >= 5:
        seg_rate = seg_bucket["success"] / seg_bucket["total"]
        api_rate = api_bucket["success"] / api_bucket["total"]
        diff = (seg_rate - api_rate) * 100
        print(f"  → 成功率の差: seg実体あり − api宣言のみ = {diff:+.1f} ポイント")
        if diff >= 15:
            print("     字幕の実体化が効いている可能性が高い。")
            print("     1巡目のクリックを『字幕が実体化するまで待つ』処理に置き換える案が有力。")
        elif diff <= -15:
            print("     想定と逆。字幕の実体化では説明がつかないため、別の要因を疑う必要がある。")
        else:
            print("     有意な差とは言えない。効いているのは経過時間である可能性が高く、")
            print("     その場合は1巡目のクリック自体を外しても成功率は落ちないと見込める。")
    else:
        print("  → 判定に足るサンプル数がありません（各5本以上必要）。もう1晩、計測を続けてください。")

    if reasons:
        print("\n  失敗の内訳:")
        for reason, count in reasons.most_common(10):
            print(f"    {count:4d} 本  {reason}")


def report_stray(records):
    """1巡目が実際に開いて捨てているタブ数 = reCAPTCHA圧の実測。"""
    print()
    print("=" * 72)
    print("【3】1巡目で開いて捨てているタブ数（確認画面を誘発している負荷）")
    print("=" * 72)

    batches = [f for _, kind, f in records if kind == "GLASP_MEASURE_STRAY"]
    if not batches:
        print("  GLASP_MEASURE_STRAY 行がありません。")
        return

    attempted = sum(as_int(f.get("round1_attempted"), 0) for f in batches)
    stray = sum(as_int(f.get("stray_closed"), 0) for f in batches)
    print(f"\n  バッチ数              : {len(batches)}")
    print(f"  1巡目のクリック総数   : {attempted}")
    print(f"  クリーンアップしたタブ: {stray}  ({pct(stray, attempted)})")
    print("\n  ※ここが1巡目で捨てているセッション数の実測値。")
    print("    1巡目のクリックを外せば、この分の負荷がそのまま消える。")


def main():
    parser = argparse.ArgumentParser(description="Glasp起動の計測ログを集計する")
    parser.add_argument("--file", default=DEFAULT_LOG, help=f"計測ログ (既定: {DEFAULT_LOG})")
    parser.add_argument("--since", default=None, help="この日付以降のみ集計 (YYYY-MM-DD)")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"計測ログが見つかりません: {args.file}")
        print("要約を1回実行すると、スクリプトと同じフォルダに作成されます。")
        return 1

    records = load_records(args.file, since=args.since)
    if not records:
        print(f"{args.file} に集計対象の行がありませんでした。")
        return 1

    stamps = [s for s, _, _ in records if s]
    print()
    print(f"対象ファイル: {os.path.abspath(args.file)}")
    if stamps:
        print(f"対象期間    : {min(stamps)} 〜 {max(stamps)}")
    print(f"対象行数    : {len(records)}")
    print()

    report_gate(records)
    report_outcome(records)
    report_stray(records)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
