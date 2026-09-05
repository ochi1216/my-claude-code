# -*- coding: utf-8 -*-
"""
register_future_pull_1.py
学びジャーナル - Future Pull #1（DREAM_2031.md参照）のProof/Obstacle/
If-Then/Next 7 Daysを、既存のforecast/Actionにそのまま登録する
（1回実行するだけ）。

新しいシート・新しい機能は一切追加しない。forecast.add_forecast()と
storage.add_action()という既存の関数を、越智さんが手でforecast_ui・
Actionクイック入力から打つのと同じ内容で呼ぶだけの使い捨てスクリプト。
（journal/register_hokkyokusei_forecasts.pyと同じ方式）

内容はDREAM_2031.mdの「Future Pull #1」節、およびその後のやり取りで
越智さんご自身が書いた文言をそのまま使っている。Claude Codeが内容を
考えたり書き換えたりはしていない。

Version: 1.0.0
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import forecast
import storage

# ============================================================
# Proof（forecast.add_forecast用）
# ============================================================
PROOF = {
    "domain": forecast.DOMAIN_PROJECT,
    "sky": (
        "Future Pull #1: 仕事のダッシュボード化が実現できた世界ができた"
        "（DREAM_2031.md）"
    ),
    "rain": (
        "各ファンクションのステータスがWeeklyで、PPTの画面1枚に収まる形で"
        "ダッシュボード的に整理されている"
    ),
    "reason": (
        "Vision紐付き（Future Pull #1）。通常のForecast的中率・"
        "Brier Score・Lucky Hit判定からは目視で除外すること。"
        "SharePoint自動化のライセンス可否、手作業での構築可否が"
        "未知数のため、実現手段は断定せず状態のみを条件にしている"
    ),
    "check_date": "2026-09-10",
}

# ============================================================
# Obstacle / If-Then（storage.add_action用。IF/THEN形式で1文にする）
# ============================================================
GUARDRAILS = [
    (
        "IF SharePoint自動化がGraph API以外の方法でITからライセンスを"
        "供与されないと分かったら → THEN 代替案をPythonか何かを使って"
        "打開する"
    ),
    (
        "IF 手作業でSharePoint上に何がどこまで構築できるか見えず、"
        "検討もつかない状態になったら → THEN イメージをClaude/GPTと"
        "語り合う"
    ),
]

# ============================================================
# Next 7 Days
# ============================================================
NEXT_7_DAYS = "ダッシュボードのイメージの言語化を行う"

ACTION_TAG = "JP Site"


def register(forecast_path: str = forecast.FORECAST_PATH,
             excel_path: str = storage.EXCEL_PATH) -> None:
    print("=" * 62)
    print(" Future Pull #1 の登録（Proof / Obstacle・If-Then / Next 7 Days）")
    print("=" * 62)

    print(f"\n[1] Proof（forecasts.json: {forecast_path}）")
    print("-" * 62)
    print(f"  読み: {PROOF['rain']}")
    print(f"  確認: {PROOF['check_date']}")
    existing_rains = {f.get("rain", "") for f in forecast.get_forecasts(forecast_path)}
    if PROOF["rain"] in existing_rains:
        print("  → 既に登録済みのためスキップします。")
    else:
        item = forecast.add_forecast(
            domain=PROOF["domain"], sky=PROOF["sky"], rain=PROOF["rain"],
            reason=PROOF["reason"], check_date=PROOF["check_date"],
            path=forecast_path,
        )
        if not item:
            print("  ❌ 登録に失敗しました。")

    print(f"\n[2] Obstacle / If-Then（Actionsシート: {excel_path}）")
    print("-" * 62)
    existing_actions = {a["content"] for a in storage.get_actions(excel_path)}
    for i, text in enumerate(GUARDRAILS, 1):
        print(f"  {i}. {text}")
        if text in existing_actions:
            print("     → 既に登録済みのためスキップします。")
            continue
        ok = storage.add_action(text, tag=ACTION_TAG, path=excel_path)
        if not ok:
            print("     ❌ 登録に失敗しました。")

    print(f"\n[3] Next 7 Days（Actionsシート: {excel_path}）")
    print("-" * 62)
    print(f"  {NEXT_7_DAYS}")
    if NEXT_7_DAYS in existing_actions:
        print("  → 既に登録済みのためスキップします。")
    else:
        ok = storage.add_action(NEXT_7_DAYS, tag=ACTION_TAG, path=excel_path)
        if not ok:
            print("  ❌ 登録に失敗しました。")

    print("\n完了しました。2026-09-10に、DREAM_2031.mdの「Future Pull #1」")
    print("節に沿ってレビューしてください。")


if __name__ == "__main__":
    register()
    input("\nEnterキーで終了します...")
