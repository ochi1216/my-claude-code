"""publish_to_iphone.bat 用の小さな補助スクリプト。

consolidated_html_summary_manager.py の標準出力ログ(引数で渡されたファイル)から
"Consolidated HTML generated at: <path>" の行を探し、パス部分だけを標準出力へ
1行で返す。見つからない場合は空文字を返す。

出力先パスをbat側で決め打ちしないためにこの間接参照を使う。パス自体に
Windowsのドライブ文字(C:)やバックスラッシュが含まれるため、batch単体の
文字列処理(:区切りのトークン化など)では確実に取り出せない。Pythonの
文字列検索に任せた方が単純で確実。
"""
import sys

MARKER = "Consolidated HTML generated at: "


def main():
    if len(sys.argv) < 2:
        print("")
        return
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        text = f.read()
    i = text.find(MARKER)
    if i < 0:
        print("")
        return
    path = text[i + len(MARKER):].splitlines()[0].strip()
    print(path)


if __name__ == "__main__":
    main()
