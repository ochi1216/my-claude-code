# -*- coding: utf-8 -*-
"""検証ハーネス一括実行

    python tests/run_tests.py

ネットワークにも Outlook にも Graph API にもアクセスしないため、会社PC・開発環境の
どちらでもそのまま実行できる。Outlook実機の動作は、このハーネスでは検証できない
（`run_probe.bat` を会社PCで実行して確認する）。
"""
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def main():
    targets = sorted(TESTS_DIR.glob("test_*.py"))
    if not targets:
        print("❌ テストファイルが見つかりません。")
        return 1

    print("=" * 60)
    print("🧪 Mail Template Manager 検証ハーネス")
    print("=" * 60)

    total_ok = 0
    total_ng = 0
    failed = []

    for path in targets:
        result = subprocess.run([sys.executable, str(path)],
                                capture_output=True, text=True)
        output = result.stdout + result.stderr
        print(output.rstrip())

        counts = [line for line in output.splitlines()
                  if "成功 " in line and "失敗 " in line]
        if counts:
            numbers = [int(n) for n in counts[-1].replace("成功", " ")
                       .replace("失敗", " ").replace("件", " ")
                       .replace("/", " ").split() if n.isdigit()]
            ok, ng = (numbers + [0, 0])[:2]
        else:
            ok, ng = 0, 1        # 集計行が無い＝異常終了とみなす

        total_ok += ok
        total_ng += ng
        if ng or result.returncode != 0:
            failed.append(path.name)

    print("=" * 60)
    print("  合計 成功 {0} 件 / 失敗 {1} 件".format(total_ok, total_ng))
    if failed:
        print("  ❌ 失敗したファイル: {0}".format(", ".join(failed)))
    else:
        print("  ✅ すべて合格")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
