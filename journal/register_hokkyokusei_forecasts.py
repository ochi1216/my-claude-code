# -*- coding: utf-8 -*-
"""
register_hokkyokusei_forecasts.py
学びジャーナル - 北極星ドシエ（2026-08-09 三者照合）の統合読み6件を
forecasts.json に一括登録する（1回実行するだけ）。

読みの本文は、ChatGPT版・Claude Code版・Claude Chat版の3つのドシエを
三角測量した最終統合ドシエの第6節と同一。登録後は forecast.py の通常の
仕組み（凍結・督促・答え合わせ）にすべて委ねる。

- 実行すると6件のプレビューを表示し、Enterで登録する
- 既に同じ読み（rain本文が一致）が登録済みの場合、その読みはスキップする
  （二重実行しても重複しない）
- 登録後にこのファイルを残しておく必要はないが、消さなくても害はない

Version: 1.0.0
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import forecast

# ============================================================
# 統合読み6件（北極星ドシエ 2026-08-09 第6節）
# rain は「外れが確定する断定形」で書いてある。
# 納得できない読みは、登録前にこのリストから消してよい。
# ============================================================
READINGS = [
    {
        # 読み1【橋の着工】最重要 — 北極星仮説そのものの検証（Code-R1改）
        "domain": forecast.DOMAIN_PROJECT,
        "sky": (
            "analog_ic_scout構想は2026-07-15に設計・方針Q&Aまで完成したが、"
            "以後約1か月、実装コミットはゼロ。同期間に個人生産性ツールへは"
            "33日66バージョンの熱量が注がれた"
        ),
        "rain": (
            "2026-09-06までに、analog_ic_scout（または自分の専門領域を対象に"
            "した戦略分析の実物1本）には着手しない"
        ),
        "reason": (
            "約1か月間、優先順位の判断で毎回、確実に完成する摩擦除去系タスクが、"
            "外れうる本番より先に選ばれてきた実績があるため"
        ),
        "confidence": forecast.CONFIDENCE_LIKELY,
        "umbrella": (
            "この読みを外す（＝着工する）ことが最善の打ち手。最初の杭は"
            "ic_index.py 1本、または型番1つの手動分析1本でよい"
        ),
        "check_date": "2026-09-06",
    },
    {
        # 読み2【リージョン連携】— 北極星の仕事側の検証（Chat-仮説2）
        "domain": forecast.DOMAIN_PEOPLE,
        "sky": (
            "「大陸をまたぐグローバルリーダーが不在。各リージョンで閉じている」"
            "と自分で言語化済み。その空隙を自分が埋めるべきかは未決のまま"
        ),
        "rain": (
            "2026-08-30までに、リージョン間連携への具体的な働きかけ"
            "（越境の会議設定・提案・巻き込みのいずれか）を実行する"
        ),
        "reason": (
            "空隙の認識が言語化された直後であり、Owner不在を見つけると自ら"
            "暫定構造を作りに行く行動パターンがここでも発火すると見るため"
        ),
        "confidence": forecast.CONFIDENCE_MAYBE,
        "umbrella": "",
        "check_date": "2026-08-30",
    },
    {
        # 読み3【Owner明文化】— 動作の不変量の検証（ChatGPT-H1）
        "domain": forecast.DOMAIN_PEOPLE,
        "sky": (
            "IOクローズ後のPO発行問題、人事の責任者不在問題など、"
            "Owner不明案件が定常的に発生している"
        ),
        "rain": (
            "次にOwner不明案件が発生したとき、技術対応より先に、"
            "Owner・承認者・費用・エスカレーション経路のいずれかを明文化する"
        ),
        "reason": (
            "3年分の記録で、責任の宙吊り状態の解消が常に最初の一手だったため"
        ),
        "confidence": forecast.CONFIDENCE_ALMOST,
        "umbrella": "",
        "check_date": "2026-08-23",
    },
    {
        # 読み4【蓄積の使用】— 影（蓄積の目的化）の検証（Code-R2）
        "domain": forecast.DOMAIN_TECH,
        "sky": (
            "Ti daily digestは毎日00:03に自動生成されているが、"
            "活用された痕跡がリポジトリに無い"
        ),
        "rain": (
            "2026-08-23時点で、直近2週間分のダイジェストのうち実際の判断・"
            "提案・文書に使われたものは2件未満である"
        ),
        "reason": (
            "蓄積系ツール全般で、蓄積後の再利用の痕跡が観測されないため。"
            "蓄積自体が目的化している可能性の確認"
        ),
        "confidence": forecast.CONFIDENCE_LIKELY,
        "umbrella": (
            "×にしたい場合: digestから1件選び、実際の業務判断・提案に使ってみる"
        ),
        "check_date": "2026-08-23",
    },
    {
        # 読み5【自動化トリガー】— 動作の不変量の検証・保険（ChatGPT-H2）
        "domain": forecast.DOMAIN_TECH,
        "sky": (
            "記憶・整理・判断をツールへ外在化する行動が、2024年12月の"
            "「思いつきを記録し続ける仕組み」相談から一貫して観測されている"
        ),
        "rain": (
            "2026-08-30までに同一の手作業が3回以上発生した場合、AI・コード・"
            "テンプレートへの置換を具体的に検討し始める"
        ),
        "reason": (
            "20か月間の不変量であり、現役の反射として機能していると見るため"
        ),
        "confidence": forecast.CONFIDENCE_ALMOST,
        "umbrella": "",
        "check_date": "2026-08-30",
    },
    {
        # 読み6【承認希求の表出】— 動機層の検証（Chat-仮説4）
        "domain": forecast.DOMAIN_PEOPLE,
        "sky": (
            "「認められない不安」(2024-09)から「10年先も必要とされる人材」"
            "(2026)まで、承認・必要とされることへの希求が2年間の線として"
            "観測された"
        ),
        "rain": (
            "2026-08-30までに、承認不足への言及、または成果を見せる・伝える"
            "ための行動が、少なくとも1回表に出る"
        ),
        "reason": (
            "動機層の仮説が正しければ、3週間の観測窓で必ず行動として"
            "漏れ出すはずのため"
        ),
        "confidence": forecast.CONFIDENCE_MAYBE,
        "umbrella": "",
        "check_date": "2026-08-30",
    },
]


def register(path: str = forecast.FORECAST_PATH) -> None:
    existing_rains = {f.get("rain", "") for f in forecast.get_forecasts(path)}

    print("=" * 62)
    print(" 北極星ドシエ 統合読み6件の登録")
    print(f" 保存先: {path}")
    print("=" * 62)

    for i, r in enumerate(READINGS, 1):
        mark = "（登録済み・スキップ）" if r["rain"] in existing_rains else ""
        print(f"\n[{i}] {r['domain']} / 確認 {r['check_date']} "
              f"/ {r['confidence']}{mark}")
        print(f"    事実: {r['sky']}")
        print(f"    読み: {r['rain']}")
        print(f"    理由: {r['reason']}")
        if r["umbrella"]:
            print(f"    打ち手: {r['umbrella']}")

    to_add = [r for r in READINGS if r["rain"] not in existing_rains]
    if not to_add:
        print("\n6件すべて登録済みです。追加は行いません。")
        return

    print()
    print("-" * 62)
    print(f"上記のうち {len(to_add)} 件を登録します。")
    print("登録すると 事実・読み・理由 は凍結され、以後書き換えられません。")
    answer = input("Enterで登録 / q + Enter で中止 > ").strip().lower()
    if answer == "q":
        print("中止しました。1件も登録していません。")
        return

    added = 0
    for r in to_add:
        item = forecast.add_forecast(
            domain=r["domain"],
            sky=r["sky"],
            rain=r["rain"],
            reason=r["reason"],
            confidence=r["confidence"],
            check_date=r["check_date"],
            umbrella=r["umbrella"],
            path=path,
        )
        if item:
            added += 1
        else:
            print(f"❌ 登録に失敗しました: {r['rain'][:30]}...")

    print()
    print(f"✅ {added} 件を登録しました。")
    print("   確認期日が来ると、通常の答え合わせ督促に混ざって表示されます。")


if __name__ == "__main__":
    register()
    input("Enterキーで終了します...")
