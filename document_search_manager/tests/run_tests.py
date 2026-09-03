# -*- coding: utf-8 -*-
"""検証ハーネス一括実行

    python tests/run_tests.py

ネットワークにも Graph API にもアクセスしないため、社内PC・開発環境のどちらでも
そのまま実行できる。ブラウザ操作テスト(ui_check.py)は Playwright が必要なため
既定では実行しない（--with-ui で追加実行する）。
"""
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def main() -> int:
    with_ui = "--with-ui" in sys.argv

    targets = sorted(TESTS_DIR.glob("test_*.py"))
    if with_ui and (TESTS_DIR / "ui_check.py").exists():
        targets.append(TESTS_DIR / "ui_check.py")

    if not targets:
        print("❌ テストファイルが見つかりません。")
        return 1

    print("=" * 60)
    print("🧪 Document Search Manager 検証ハーネス")
    print("=" * 60)

    total_ok = 0
    total_ng = 0
    failed = []

    for path in targets:
        result = subprocess.run([sys.executable, str(path)],
                                capture_output=True, text=True)
        output = result.stdout + result.stderr

        counts = [line for line in output.splitlines() if "成功 " in line and "失敗 " in line]
        if counts:
            numbers = [int(n) for n in counts[-1].replace("成功", " ")
                       .replace("失敗", " ").replace("件", " ")
                       .replace("/", " ").split() if n.isdigit()]
            ok, ng = (numbers + [0, 0])[:2]
        else:
            ok, ng = 0, 1        # 集計行が無い＝異常終了とみなす

        total_ok += ok
        total_ng += ng

        icon = "🟢" if (result.returncode == 0 and ng == 0) else "🔴"
        print(f"{icon} {path.name:<34} 成功 {ok:>3} / 失敗 {ng:>3}")

        if result.returncode != 0 or ng:
            failed.append((path.name, output))

    print("-" * 60)
    print(f"合計: 成功 {total_ok} 件 / 失敗 {total_ng} 件")

    if failed:
        print("\n❌ 失敗した項目の詳細:")
        for name, output in failed:
            print(f"\n----- {name} -----")
            for line in output.splitlines():
                if line.strip().startswith("NG") or "Error" in line or "Traceback" in line:
                    print(line)
        return 1

    print("✅ すべて合格しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
