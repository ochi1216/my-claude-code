# fix_textcontent.py
# textContent に &#x エンティティを代入している全箇所を innerHTML に変更するスクリプト
# 使い方: python fix_textcontent.py <対象ファイルパス>

import sys
import re
import shutil
from datetime import datetime

if len(sys.argv) < 2:
    print("使い方: python fix_textcontent.py <対象ファイルパス>")
    sys.exit(1)

target = sys.argv[1]

# バックアップ作成
backup = target + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(target, backup)
print(f"[OK] バックアップ作成: {backup}")

with open(target, "r", encoding="utf-8") as f:
    lines = f.readlines()

changed = 0
for i, line in enumerate(lines):
    # &#x エンティティを含む textContent への代入のみを対象にする
    if ".textContent" in line and "= '&#x" in line:
        original = line

        # data.message を innerHTML に変更する場合は escHtml() を追加
        if "data.message" in line:
            line = line.replace(".textContent", ".innerHTML")
            line = line.replace("+ data.message", "+ escHtml(data.message)")

        # data.path を innerHTML に変更する場合は escHtml() を追加
        elif "data.path" in line:
            line = line.replace(".textContent", ".innerHTML")
            line = re.sub(r"\+ data\.path \+", "+ escHtml(data.path) +", line)
            line = re.sub(r"\+ data\.path \)",  "+ escHtml(data.path))", line)

        # それ以外は単純に textContent → innerHTML
        else:
            line = line.replace(".textContent", ".innerHTML")

        if line != original:
            lines[i] = line
            changed += 1
            print(f"  [変更] 行{i+1}: {original.strip()}")
            print(f"       → {line.strip()}")

with open(target, "w", encoding="utf-8") as f:
    f.writelines(lines)

print(f"\n[完了] {changed}行を変更しました。")

# 変更後の確認
remaining = sum(1 for l in lines if ".textContent" in l and "= '&#x" in l)
if remaining == 0:
    print("[OK] textContent = '&#x の残存: 0件（全て置換完了）")
else:
    print(f"[警告] textContent = '&#x の残存: {remaining}件（要確認）")
