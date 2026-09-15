# -*- coding: utf-8 -*-
"""
emoji_font_preview.py
学びジャーナル - ひれぶり絵文字のフォント比較ツール

このツール単体で実行し、😄😠😢😌 が実際のWindows環境でどのフォント
指定だと一番きれいに（色つきで）表示されるかを見比べるためのもの。
本体（daily_journal_*.py）には一切影響しない、独立した確認用スクリプト。

使い方：
    "C:\\Program Files\\Python\\python.exe" emoji_font_preview.py

一番きれいに見えた列の見出し（フォント名）を教えてもらえれば、
本体側もそのフォントを使うように直せる。
"""
import tkinter as tk
from tkinter import font as tkfont

EMOTION_ICONS = ["😄", "😠", "😢", "😌"]

# Windows環境で絵文字の描画に関わりそうな候補フォントをいくつか横に並べる。
# 実際にインストールされていないフォント名を指定した場合、Windowsが
# 別のフォントへ自動的に差し替えて表示するので、「存在しない」こと自体も
# 見た目の違いとして確認できる
CANDIDATE_FONTS = [
    "Yu Gothic UI",       # 現在の本体が指定しているフォント（比較の基準）
    "Segoe UI Emoji",     # Windows標準の色つき絵文字フォント
    "Segoe UI Symbol",    # 古めの記号フォント（色つきではないことが多い）
    "Segoe UI",           # 通常のUIフォント
]

BG_COLOR = "#1a1a2e"
TEXT_COLOR = "#ffffff"
HEADER_COLOR = "#f4a6b8"


def main():
    root = tk.Tk()
    root.title("ひれぶり絵文字 フォント比較")
    root.configure(bg=BG_COLOR)

    intro = tk.Label(
        root,
        text="どの列が一番きれいに（色つきで）見えますか？\n"
             "一番良かった列の見出し（フォント名）を教えてください。",
        bg=BG_COLOR, fg=TEXT_COLOR,
        font=tkfont.Font(family="Yu Gothic UI", size=11),
        justify="left", padx=16, pady=12,
    )
    intro.grid(row=0, column=0, columnspan=len(CANDIDATE_FONTS), sticky="w")

    header_font = tkfont.Font(family="Yu Gothic UI", size=10, weight="bold")
    icon_font_size = 28

    for col, family in enumerate(CANDIDATE_FONTS):
        header = tk.Label(
            root, text=family, bg=BG_COLOR, fg=HEADER_COLOR,
            font=header_font, padx=14, pady=6,
        )
        header.grid(row=1, column=col, sticky="ew")

        icon_font = tkfont.Font(family=family, size=icon_font_size)
        for row, icon in enumerate(EMOTION_ICONS, start=2):
            label = tk.Label(
                root, text=icon, bg=BG_COLOR, fg=TEXT_COLOR,
                font=icon_font, padx=14, pady=10,
            )
            label.grid(row=row, column=col)

    root.mainloop()


if __name__ == "__main__":
    main()
