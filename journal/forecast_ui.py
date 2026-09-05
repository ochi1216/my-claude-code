# -*- coding: utf-8 -*-
"""
forecast_ui.py
学びジャーナル - 「読み（予測）」の入力・一覧・答え合わせ画面

画面上は 事実 / 読み / 打ち手 の3項目として扱う（空・雨・傘に対応する）。
「読み」を採っているのは、日本語として最初から外れることと採点される
ことを含んでいるため（「読みが外れた」「読みが甘かった」）。
保存側のキーは sky / rain / umbrella のままで、表示だけを切り替えている。

この機能の目的は「読みを書くこと」ではなく「後から答え合わせが必ず
行われること」なので、画面の作りも入力のしやすさより答え合わせが確実に
回ることを優先している。具体的には:

  ・確認期日の来た読みは、起動時に向こうから出てくる（ReviewWindow）
  ・○×△だけでなく「延期」「判定不能」という正直な出口を用意する
    （出口が無いと嘘をつくか無視するかになり、無視が始まると仕組みが死ぬ）
  ・外れ方は自由記述ではなく選択肢にする（「当たったが理由違い」を
    数えられるようにするため）

ダッシュボードには意図的に組み込んでいない。まだ形が固まっていない段階で
1,500行のdashboard.pyに手を入れると引き返しにくくなるため、独立した
ウィンドウとして作り、数本書いて過不足が見えてから統合を判断する。

Version: 0.1.0
"""

import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont

import forecast as fc

# ダッシュボードと同じダークテーマの配色を踏襲する
BG_COLOR = "#1a1a2e"
CARD_BG = "#232338"
LINE_COLOR = "#383850"
TEXT_COLOR = "#ffffff"
BODY_TEXT = "#ded9ec"
DIM_TEXT = "#a8a6bd"
ACCENT_COLOR = "#f4a6b8"
BUTTON_TEXT_COLOR = "#2b2b40"
ENTRY_BG = "#0f3460"
PLACEHOLDER_COLOR = "#7c86a8"
BTN_BG = "#dfeaf5"
PRIMARY_BTN_BG = "#cbb8f5"

# 領域ごとの色。あとで「どの領域の読みが当たりやすいか」を見るときに、
# 一覧上で領域を目で拾えるようにするための区別
DOMAIN_COLORS = {
    fc.DOMAIN_PROJECT: "#d9ae23",
    fc.DOMAIN_PEOPLE: "#c2399e",
    fc.DOMAIN_TECH: "#2fa84f",
}
OUTCOME_COLORS = {
    fc.OUTCOME_HIT: "#66bb6a",
    fc.OUTCOME_MISS: "#ef5350",
    fc.OUTCOME_PARTIAL: "#e0a72e",
}
DUE_COLOR = "#ef5350"

SKY_PLACEHOLDER = "何を見てそう思ったか"
RAIN_PLACEHOLDER = "「〜になる」と断定で1つだけ"
REASON_PLACEHOLDER = "なぜそう読むのか（ここが最重要）"
UMBRELLA_PLACEHOLDER = "そのとき取る手（任意）"

# 画面上の3項目の呼び名とアイコン。保存側のキー(sky/rain/umbrella)は
# 既存のforecasts.jsonとの互換のためそのままにし、表示だけを切り替える
ICON_FACT = "👁️"
ICON_READ = "🔮"
ICON_MOVE = "♟️"

# 読みに混じると外れが確定しなくなる表現。
# リスク管理なら「〜の可能性がある」で構わないが、Forecastは1つに絞った
# 瞬間に外れが確定することが存在理由なので、ヘッジや併記が入ると
# ただのリスク一覧に戻ってしまう。見つけたら気づかせる（保存は止めない）
HEDGE_PATTERNS = [
    "かもしれ", "かも知れ", "可能性", "おそれ", "恐れ", "と思う", "と思わ",
    "気がする", "ではないか", "だろうか", "見込みもある", "リスクがある",
]
MULTI_PATTERNS = ["または", "あるいは", "もしくは", " or ", "／", "／"]


def _fonts():
    return {
        "title": tkfont.Font(family="Yu Gothic UI", size=15, weight="bold"),
        "label": tkfont.Font(family="Yu Gothic UI", size=11, weight="bold"),
        "body": tkfont.Font(family="Yu Gothic UI", size=13),
        "small": tkfont.Font(family="Yu Gothic UI", size=11),
        "mono": tkfont.Font(family="Consolas", size=10),
        "chip": tkfont.Font(family="Yu Gothic UI", size=11, weight="bold"),
    }


class _PlaceholderText(tk.Text):
    """
    複数行入力欄。空のときは薄字でプレースホルダを出す。
    読みの理由や実際どうなったかは1行に収まらないことが多いため、
    ポップアップ側のEntryではなくTextを使う。
    """

    def __init__(self, master, placeholder: str, height: int = 2, **kw):
        super().__init__(master, height=height, wrap="word", bg=ENTRY_BG,
                          fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
                          relief="flat", bd=0, padx=6, pady=4, **kw)
        self._placeholder = placeholder
        self._showing = False
        self.bind("<FocusIn>", self._on_focus_in, add="+")
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self._show_placeholder()

    def _show_placeholder(self):
        self.delete("1.0", "end")
        self.insert("1.0", self._placeholder)
        self.config(fg=PLACEHOLDER_COLOR)
        self._showing = True

    def _on_focus_in(self, _e=None):
        if self._showing:
            self.delete("1.0", "end")
            self.config(fg=TEXT_COLOR)
            self._showing = False

    def _on_focus_out(self, _e=None):
        if not super().get("1.0", "end").strip():
            self._show_placeholder()

    def value(self) -> str:
        """プレースホルダ表示中は未入力として空文字を返す。"""
        if self._showing:
            return ""
        return super().get("1.0", "end").strip()

    def set_value(self, text: str):
        self.delete("1.0", "end")
        if text:
            self.insert("1.0", text)
            self.config(fg=TEXT_COLOR)
            self._showing = False
        else:
            self._show_placeholder()


def _chip(parent, text: str, color: str, font):
    return tk.Label(parent, text=f" {text} ", bg=color, fg=TEXT_COLOR, font=font)


def _labeled(parent, text: str, font, required: bool = False):
    row = tk.Frame(parent, bg=BG_COLOR)
    row.pack(fill="x", pady=(8, 2))
    tk.Label(row, text=text, bg=BG_COLOR, fg=BODY_TEXT, font=font).pack(side="left")
    if required:
        tk.Label(row, text="必須", bg=BG_COLOR, fg=ACCENT_COLOR,
                 font=tkfont.Font(family="Yu Gothic UI", size=10)).pack(side="left", padx=(6, 0))
    return row


class ForecastEntryWindow:
    """読みを1本書くためのフォーム。"""

    def __init__(self, root, on_saved=None, seed_umbrella: str = "",
                  seed_reason: str = ""):
        self.root = root
        self.on_saved = on_saved
        self.f = _fonts()

        self.win = tk.Toplevel(root)
        self.win.title("読みを書く")
        self.win.configure(bg=BG_COLOR)
        self.win.geometry("520x780")
        self.win.attributes("-topmost", True)
        # ヘッジ表現の警告を一度出したかどうか（2回目の保存で通す）
        self._hedge_ack = False

        self._build(seed_umbrella, seed_reason)

    def _build(self, seed_umbrella, seed_reason):
        w = self.win
        f = self.f

        tk.Label(w, text=f"{ICON_READ} 読みを書く", bg=BG_COLOR, fg=TEXT_COLOR,
                 font=f["title"]).pack(pady=(14, 2))
        tk.Label(w, text="外れが分かる形で書くこと。当たり外れより、"
                          "どういう理屈で読む癖があるかが分かることに価値があります。",
                 bg=BG_COLOR, fg=DIM_TEXT, font=f["small"],
                 wraplength=470, justify="center").pack(pady=(0, 6))

        body = tk.Frame(w, bg=BG_COLOR)
        body.pack(fill="both", expand=True, padx=24)

        # --- 領域 ---
        _labeled(body, "領域", f["label"], required=True)
        self.domain_var = tk.StringVar(value=fc.DOMAIN_PROJECT)
        drow = tk.Frame(body, bg=BG_COLOR)
        drow.pack(fill="x")
        for d in fc.DOMAINS:
            tk.Radiobutton(
                drow, text=d, value=d, variable=self.domain_var,
                bg=BG_COLOR, fg=BODY_TEXT, selectcolor=ENTRY_BG,
                activebackground=BG_COLOR, activeforeground=TEXT_COLOR,
                font=f["small"], bd=0, highlightthickness=0, cursor="hand2",
            ).pack(side="left", padx=(0, 12))

        # --- 事実 / 読み / 理由 ---
        _labeled(body, f"{ICON_FACT} 事実 ── 何を見たか", f["label"], required=True)
        self.sky = _PlaceholderText(body, SKY_PLACEHOLDER, height=2, font=f["body"])
        self.sky.pack(fill="x")

        _labeled(body, f"{ICON_READ} 読み ── この先どうなると読むか", f["label"],
                 required=True)
        tk.Label(body, text="1件につき1つ。「〜の可能性がある」ではなく"
                             "「〜になる」と言い切る（外れが確定する形にする）",
                 bg=BG_COLOR, fg=DIM_TEXT, font=f["small"],
                 wraplength=470, justify="left").pack(anchor="w")
        # 複数行のTextにすると「AまたはB」を並べて書けてしまい、
        # 何をもって外れとするかが決まらなくなる。1行のEntryにして
        # 構造的に併記できないようにする
        self.rain_var = tk.StringVar()
        self.rain = tk.Entry(body, textvariable=self.rain_var, bg=ENTRY_BG,
                              fg=PLACEHOLDER_COLOR, insertbackground=TEXT_COLOR,
                              relief="flat", font=f["body"])
        self.rain.pack(fill="x", ipady=5, pady=(2, 0))
        self.rain.insert(0, RAIN_PLACEHOLDER)
        self.rain.bind("<FocusIn>", self._rain_focus_in)
        self.rain.bind("<FocusOut>", self._rain_focus_out)

        _labeled(body, "理由 ── なぜそう読むのか", f["label"], required=True)
        self.reason = _PlaceholderText(body, REASON_PLACEHOLDER, height=3, font=f["body"])
        self.reason.pack(fill="x")
        if seed_reason:
            self.reason.set_value(seed_reason)

        # --- 確信度（任意） ---
        # 最初から必須にすると入力の心理的コストが上がって書かなくなる。
        # 空欄のまま運用してよい
        _labeled(body, "確信度（任意）", f["label"])
        self.conf_var = tk.StringVar(value="")
        crow = tk.Frame(body, bg=BG_COLOR)
        crow.pack(fill="x", pady=(2, 0))
        for c in [""] + fc.CONFIDENCE_LEVELS:
            tk.Radiobutton(
                crow, text=c or "未選択", value=c, variable=self.conf_var,
                bg=BG_COLOR, fg=BODY_TEXT, selectcolor=ENTRY_BG,
                activebackground=BG_COLOR, activeforeground=TEXT_COLOR,
                font=f["small"], bd=0, highlightthickness=0, cursor="hand2",
            ).pack(side="left", padx=(0, 10))

        # --- 確認期日 ---
        _labeled(body, "確認期日 ── この日に答え合わせをする", f["label"], required=True)
        drow2 = tk.Frame(body, bg=BG_COLOR)
        drow2.pack(fill="x")
        self.date_var = tk.StringVar(value=fc.suggest_check_date(3))
        tk.Entry(drow2, textvariable=self.date_var, bg=ENTRY_BG, fg=TEXT_COLOR,
                 insertbackground=TEXT_COLOR, relief="flat", font=f["mono"],
                 width=12).pack(side="left", ipady=3)
        # この欄がこの仕組み全体を回す要なので、入力の手間を減らす
        for label, months in (("+1ヶ月", 1), ("+3ヶ月", 3), ("+6ヶ月", 6), ("+1年", 12)):
            tk.Button(
                drow2, text=label, bg=BTN_BG, fg=BUTTON_TEXT_COLOR, relief="flat",
                font=f["small"], cursor="hand2", padx=6,
                command=lambda m=months: self.date_var.set(fc.suggest_check_date(m)),
            ).pack(side="left", padx=(6, 0))

        # --- 打ち手 ---
        _labeled(body, f"{ICON_MOVE} 打ち手 ── そのとき取る手（任意）", f["label"])
        self.umbrella = _PlaceholderText(body, UMBRELLA_PLACEHOLDER, height=2,
                                          font=f["body"])
        self.umbrella.pack(fill="x")
        if seed_umbrella:
            self.umbrella.set_value(seed_umbrella)

        # 打ち手は性質上タスクそのもの。読みの中だけに書くと実行されずに腐るため、
        # 既存のタスク一覧に送り込めるようにする（LKPTのP欄と同じ仕組み）
        self.make_task_var = tk.BooleanVar(value=bool(seed_umbrella))
        tk.Checkbutton(
            body, text="この打ち手をタスクにも追加する", variable=self.make_task_var,
            bg=BG_COLOR, fg=DIM_TEXT, selectcolor=ENTRY_BG,
            activebackground=BG_COLOR, activeforeground=BODY_TEXT,
            font=f["small"], bd=0, highlightthickness=0, cursor="hand2",
        ).pack(anchor="w", pady=(4, 0))

        self.msg = tk.Label(w, text="", bg=BG_COLOR, fg=ACCENT_COLOR,
                            font=f["small"], wraplength=470)
        self.msg.pack(pady=(6, 0))

        btns = tk.Frame(w, bg=BG_COLOR)
        btns.pack(fill="x", padx=24, pady=(6, 16))
        for col in range(2):
            btns.columnconfigure(col, weight=1, uniform="b")
        tk.Button(btns, text="保存", bg=PRIMARY_BTN_BG, fg=BUTTON_TEXT_COLOR,
                  relief="flat", font=f["label"], pady=6, cursor="hand2",
                  command=self._save).grid(row=0, column=0, sticky="ew", padx=3)
        tk.Button(btns, text="閉じる", bg=BTN_BG, fg=BUTTON_TEXT_COLOR,
                  relief="flat", font=f["label"], pady=6, cursor="hand2",
                  command=self.win.destroy).grid(row=0, column=1, sticky="ew", padx=3)

        self.win.bind("<Escape>", lambda e: self.win.destroy())

    def _rain_focus_in(self, _e=None):
        if self.rain.get() == RAIN_PLACEHOLDER:
            self.rain.delete(0, "end")
            self.rain.config(fg=TEXT_COLOR)

    def _rain_focus_out(self, _e=None):
        if not self.rain.get().strip():
            self.rain.delete(0, "end")
            self.rain.insert(0, RAIN_PLACEHOLDER)
            self.rain.config(fg=PLACEHOLDER_COLOR)

    def _rain_raw(self) -> str:
        """入力欄の中身をそのまま返す（改行の検知に使う）。"""
        if str(self.rain.cget("fg")) == PLACEHOLDER_COLOR:
            return ""
        return self.rain.get()

    def _rain_value(self) -> str:
        """
        保存する読みの文字列。Entryは手入力では改行できないが、貼り付けでは
        改行が入り得るため、必ず1行に正規化してから保存する
        （複数行のまま保存できると、実質的に併記になってしまう）。
        """
        return " ".join(self._rain_raw().split()).strip()

    def _hedges_in(self, text: str) -> list:
        """読みに含まれるヘッジ・併記の表現を拾う。"""
        found = [p for p in HEDGE_PATTERNS if p in text]
        found += [p.strip() for p in MULTI_PATTERNS if p in text]
        if "\n" in text:
            found.append("改行（複数の読み）")
        return found

    def _save(self):
        sky, rain, reason = self.sky.value(), self._rain_value(), self.reason.value()
        date_str = self.date_var.get().strip()

        missing = [n for n, v in (("事実", sky), ("読み", rain), ("理由", reason)) if not v]
        if missing:
            self.msg.config(text=f"⚠️ {' / '.join(missing)} が未入力です")
            self._hedge_ack = False
            return
        try:
            datetime.strptime(date_str, fc.DATE_FMT)
        except ValueError:
            self.msg.config(text="⚠️ 確認期日は YYYY-MM-DD の形式で入力してください")
            self._hedge_ack = False
            return

        # ヘッジや併記が入っていると外れが確定しない。保存は止めないが、
        # 一度気づかせる（気づかないまま溜まると、後で採点できなくなる）
        hedges = self._hedges_in(self._rain_raw())
        if hedges and not self._hedge_ack:
            self.msg.config(
                text=f"⚠️ 読みに「{'」「'.join(hedges[:3])}」が入っています。"
                     f"このままだと外れが確定しません。"
                     f"言い切るか、もう一度「保存」を押すとこのまま保存します。"
            )
            self._hedge_ack = True
            return

        umbrella = self.umbrella.value()
        make_task = bool(umbrella) and self.make_task_var.get()

        item = fc.add_forecast(
            self.domain_var.get(), sky, rain, reason, self.conf_var.get(),
            date_str, umbrella=umbrella, umbrella_task_created=make_task,
        )
        if item is None:
            self.msg.config(text="⚠️ 保存に失敗しました")
            return

        if make_task:
            # 既存のActionsシートの「由来」列に読みのIDを入れておくと、
            # 新しい列を足さずにタスク→読みの追跡ができる。
            # 追跡の実体はID(R-...)側なので、頭の呼び名が変わっても辿れる
            try:
                from storage import add_action
                add_action(umbrella, tag="", origin=f"読み:{item['id']}")
            except Exception as e:
                print(f"❌ 打ち手のタスク化に失敗しました: {e}")

        if self.on_saved:
            self.on_saved(item)
        self.win.destroy()


class ForecastReviewWindow:
    """
    確認期日の来た読みの答え合わせ。起動時に向こうから出てくる画面。
    人は自分から見返さないので、この画面が出ることが仕組みの肝になる。
    """

    def __init__(self, root, items: list, on_done=None, total_due: int = None):
        self.root = root
        self.items = list(items)
        self.on_done = on_done
        self.total_due = total_due if total_due is not None else len(items)
        self.index = 0
        self.f = _fonts()

        self.win = tk.Toplevel(root)
        self.win.title("読みの答え合わせ")
        self.win.configure(bg=BG_COLOR)
        self.win.geometry("520x720")
        self.win.attributes("-topmost", True)
        self.win.bind("<Escape>", lambda e: self._close())

        self.container = tk.Frame(self.win, bg=BG_COLOR)
        self.container.pack(fill="both", expand=True)
        self._render()

    def _render(self):
        for c in self.container.winfo_children():
            c.destroy()
        if self.index >= len(self.items):
            self._close()
            return

        item = self.items[self.index]
        w, f = self.container, self.f

        tk.Label(w, text=f"{ICON_READ} 今日が確認期日です", bg=BG_COLOR, fg=TEXT_COLOR,
                 font=f["title"]).pack(pady=(14, 2))
        remain = f"{self.index + 1} / {len(self.items)} 件目"
        if self.total_due > len(self.items):
            remain += f"（未記入は全部で {self.total_due} 件）"
        tk.Label(w, text=remain, bg=BG_COLOR, fg=DIM_TEXT,
                 font=f["small"]).pack(pady=(0, 8))

        card = tk.Frame(w, bg=CARD_BG)
        card.pack(fill="x", padx=24)
        head = tk.Frame(card, bg=CARD_BG)
        head.pack(fill="x", padx=12, pady=(10, 4))
        _chip(head, item["domain"], DOMAIN_COLORS.get(item["domain"], "#888888"),
              f["chip"]).pack(side="left")
        tk.Label(head, text=item["id"], bg=CARD_BG, fg=DIM_TEXT,
                 font=f["mono"]).pack(side="left", padx=(8, 0))
        tk.Label(head, text=f"確信度: {item.get('confidence', '')}", bg=CARD_BG,
                 fg=DIM_TEXT, font=f["small"]).pack(side="right")

        for label, key in ((f"{ICON_FACT} 事実", "sky"), (f"{ICON_READ} 読み", "rain"),
                           ("理由", "reason")):
            tk.Label(card, text=label, bg=CARD_BG, fg=DIM_TEXT,
                     font=f["label"]).pack(anchor="w", padx=12, pady=(6, 0))
            tk.Label(card, text=item.get(key, ""), bg=CARD_BG, fg=BODY_TEXT,
                     font=f["body"], wraplength=440, justify="left",
                     anchor="w").pack(fill="x", padx=12)

        meta = (f"書いた日 {item.get('created_at', '')} ／ "
                f"確認期日 {item.get('check_date', '')}")
        if item.get("defer_count"):
            meta += f" ／ 延期 {item['defer_count']}回"
        tk.Label(card, text=meta, bg=CARD_BG, fg=DIM_TEXT,
                 font=f["small"]).pack(anchor="w", padx=12, pady=(8, 10))

        body = tk.Frame(w, bg=BG_COLOR)
        body.pack(fill="both", expand=True, padx=24)

        # 読みの当否と理由の当否は必ず別々に採点する。
        # 「読みは当たったが理由は違った」＝たまたま当たっただけ、が最も
        # 学びが大きく、1つにまとめると見えなくなる
        self.outcome_var = tk.StringVar(value="")
        self.reason_var = tk.StringVar(value="")

        def score_row(label_text, var, hint=""):
            _labeled(body, label_text, f["label"], required=True)
            if hint:
                tk.Label(body, text=hint, bg=BG_COLOR, fg=DIM_TEXT,
                         font=f["small"], wraplength=470,
                         justify="left").pack(anchor="w")
            row = tk.Frame(body, bg=BG_COLOR)
            row.pack(fill="x", pady=(2, 0))
            for o in fc.OUTCOMES:
                tk.Radiobutton(
                    row, text=o, value=o, variable=var,
                    bg=BG_COLOR, fg=OUTCOME_COLORS.get(o, BODY_TEXT),
                    selectcolor=ENTRY_BG, activebackground=BG_COLOR,
                    activeforeground=TEXT_COLOR,
                    font=tkfont.Font(family="Yu Gothic UI", size=14, weight="bold"),
                    bd=0, highlightthickness=0, cursor="hand2",
                ).pack(side="left", padx=(0, 16))

        score_row("① 読みは当たったか", self.outcome_var)
        score_row("② 理由は合っていたか", self.reason_var,
                  "当たっていても理由が違えば、たまたま当たっただけです。"
                  "読み筋は外れたままなので次に大きく外します")

        _labeled(body, "実際に何が起きたか", f["label"])
        self.actual = _PlaceholderText(body, "事実を短く", height=2, font=f["body"])
        self.actual.pack(fill="x")

        _labeled(body, "補足（任意）", f["label"])
        self.learned = _PlaceholderText(body, "気づいたこと", height=2, font=f["body"])
        self.learned.pack(fill="x")

        self.msg = tk.Label(w, text="", bg=BG_COLOR, fg=ACCENT_COLOR,
                            font=f["small"], wraplength=470)
        self.msg.pack(pady=(6, 0))

        btns = tk.Frame(w, bg=BG_COLOR)
        btns.pack(fill="x", padx=24, pady=(6, 6))
        for col in range(2):
            btns.columnconfigure(col, weight=1, uniform="b")
        tk.Button(btns, text="記録する", bg=PRIMARY_BTN_BG, fg=BUTTON_TEXT_COLOR,
                  relief="flat", font=f["label"], pady=6, cursor="hand2",
                  command=self._resolve).grid(row=0, column=0, sticky="ew", padx=3)
        tk.Button(btns, text="あとで（延期）", bg=BTN_BG, fg=BUTTON_TEXT_COLOR,
                  relief="flat", font=f["label"], pady=6, cursor="hand2",
                  command=self._defer).grid(row=0, column=1, sticky="ew", padx=3)

        sub = tk.Frame(w, bg=BG_COLOR)
        sub.pack(fill="x", padx=24, pady=(0, 14))
        tk.Button(sub, text="判定不能として終了（前提が消えた）", bg=BG_COLOR,
                  fg=DIM_TEXT, relief="flat", font=f["small"], cursor="hand2",
                  activebackground=BG_COLOR, activeforeground=ACCENT_COLOR,
                  bd=0, highlightthickness=0,
                  command=self._unjudgeable).pack(side="left")

    def _resolve(self):
        item = self.items[self.index]
        if not self.outcome_var.get():
            self.msg.config(text="⚠️ ①読みは当たったか を選んでください")
            return
        if not self.reason_var.get():
            self.msg.config(text="⚠️ ②理由は合っていたか を選んでください")
            return
        fc.resolve_forecast(item["id"], self.outcome_var.get(), self.reason_var.get(),
                            actual=self.actual.value(), learned=self.learned.value())
        self._advance()

    def _defer(self):
        """
        まだ判定できない場合の出口。3ヶ月先に送る。
        延期回数は記録され、繰り返されるほど「反証可能な形で書けていない」
        という診断になる。
        """
        item = self.items[self.index]
        fc.defer_forecast(item["id"], fc.suggest_check_date(3))
        self._advance()

    def _unjudgeable(self):
        item = self.items[self.index]
        fc.mark_unjudgeable(item["id"], note=self.actual.value())
        self._advance()

    def _advance(self):
        self.index += 1
        self._render()

    def _close(self):
        if self.on_done:
            self.on_done()
        if self.win.winfo_exists():
            self.win.destroy()


class ForecastListWindow:
    """読みの一覧。書いたものと、答え合わせ済みのものを並べて見る。"""

    def __init__(self, root):
        self.root = root
        self.f = _fonts()
        self.win = tk.Toplevel(root)
        self.win.title("読み一覧")
        self.win.configure(bg=BG_COLOR)
        self.win.geometry("640x720")
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        self._build()
        self.refresh()

    def _build(self):
        w, f = self.win, self.f
        head = tk.Frame(w, bg=BG_COLOR)
        head.pack(fill="x", padx=20, pady=(14, 6))
        tk.Label(head, text=f"{ICON_READ} 読み", bg=BG_COLOR, fg=TEXT_COLOR,
                 font=f["title"]).pack(side="left")
        tk.Button(head, text="＋ 新しく書く", bg=PRIMARY_BTN_BG,
                  fg=BUTTON_TEXT_COLOR, relief="flat", font=f["label"],
                  cursor="hand2", padx=10, pady=4,
                  command=self._new).pack(side="right")
        tk.Button(head, text="答え合わせ", bg=BTN_BG, fg=BUTTON_TEXT_COLOR,
                  relief="flat", font=f["label"], cursor="hand2", padx=10, pady=4,
                  command=self._review).pack(side="right", padx=(0, 8))

        self.summary = tk.Label(w, text="", bg=BG_COLOR, fg=DIM_TEXT,
                                font=f["small"], anchor="w")
        self.summary.pack(fill="x", padx=20)
        tk.Frame(w, bg=LINE_COLOR, height=1).pack(fill="x", padx=20, pady=(6, 0))

        outer = tk.Frame(w, bg=BG_COLOR)
        outer.pack(fill="both", expand=True, padx=20, pady=10)
        self.canvas = tk.Canvas(outer, bg=BG_COLOR, highlightthickness=0)
        vbar = tk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG_COLOR)
        self._win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win_id, width=e.width))
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    def refresh(self):
        for c in self.inner.winfo_children():
            c.destroy()
        f = self.f
        items = fc.get_forecasts()
        due_total = fc.count_due()

        resolved = [i for i in items if i.get("status") == fc.STATUS_RESOLVED]
        hits = sum(1 for i in resolved if i.get("outcome") == fc.OUTCOME_HIT)
        lucky = sum(1 for i in resolved if fc.is_lucky_hit(i))
        text = f"全 {len(items)}件 ／ 答え合わせ済み {len(resolved)}件"
        if resolved:
            text += f"（読み○ {hits}件）"
        if lucky:
            text += f" ／ ⚠️ たまたま当たった {lucky}件"
        if due_total:
            text += f" ／ ⚠️ 期日が来て未記入 {due_total}件"
        self.summary.config(text=text)

        if not items:
            tk.Label(self.inner, text="まだ読みを書いていません。"
                                       "「＋ 新しく書く」から1本目を書いてみてください。",
                     bg=BG_COLOR, fg=DIM_TEXT, font=f["body"]).pack(anchor="w", pady=20)
            return

        today = datetime.now().strftime(fc.DATE_FMT)
        for item in sorted(items, key=lambda i: i.get("created_at", ""), reverse=True):
            self._render_row(item, today, f)

    def _render_row(self, item, today, f):
        is_due = (item.get("status") == fc.STATUS_PENDING
                  and str(item.get("check_date", "")) <= today)

        card = tk.Frame(self.inner, bg=CARD_BG)
        card.pack(fill="x", pady=(0, 6))

        top = tk.Frame(card, bg=CARD_BG)
        top.pack(fill="x", padx=10, pady=(8, 2))
        _chip(top, item["domain"], DOMAIN_COLORS.get(item["domain"], "#888888"),
              f["chip"]).pack(side="left")
        tk.Label(top, text=item["id"], bg=CARD_BG, fg=DIM_TEXT,
                 font=f["mono"]).pack(side="left", padx=(8, 0))

        if item.get("status") == fc.STATUS_RESOLVED:
            _chip(top, item.get("outcome", "?"),
                  OUTCOME_COLORS.get(item.get("outcome"), "#888888"),
                  f["chip"]).pack(side="right")
        elif item.get("status") == fc.STATUS_UNJUDGEABLE:
            tk.Label(top, text="判定不能", bg=CARD_BG, fg=DIM_TEXT,
                     font=f["small"]).pack(side="right")
        elif is_due:
            tk.Label(top, text="● 要記入", bg=CARD_BG, fg=DUE_COLOR,
                     font=f["chip"]).pack(side="right")

        tk.Label(card, text=item.get("rain", ""), bg=CARD_BG, fg=BODY_TEXT,
                 font=f["body"], wraplength=540, justify="left",
                 anchor="w").pack(fill="x", padx=10)

        parts = [f"確認 {item.get('check_date', '')}"]
        if item.get("confidence"):
            parts.append(item["confidence"])
        if item.get("defer_count"):
            parts.append(f"延期{item['defer_count']}回")
        label = fc.describe_result(item)
        if label:
            parts.append(label)
        tk.Label(card, text=" ／ ".join(parts), bg=CARD_BG,
                 fg=DUE_COLOR if fc.is_lucky_hit(item) else DIM_TEXT,
                 font=f["small"], anchor="w").pack(fill="x", padx=10, pady=(2, 0))

        # 追記（本文は凍結されているので、訂正はすべてここに積まれる）
        for note in item.get("notes", []):
            tk.Label(card, text=f"↳ {note.get('at', '')}  {note.get('text', '')}",
                     bg=CARD_BG, fg=DIM_TEXT, font=f["small"], anchor="w",
                     wraplength=520, justify="left").pack(fill="x", padx=(22, 10))

        foot = tk.Frame(card, bg=CARD_BG)
        foot.pack(fill="x", padx=10, pady=(2, 8))
        tk.Button(foot, text="追記", bg=CARD_BG, fg=DIM_TEXT, relief="flat",
                  font=f["small"], cursor="hand2", bd=0, highlightthickness=0,
                  activebackground=CARD_BG, activeforeground=ACCENT_COLOR,
                  command=lambda i=item: self._append_note(i)).pack(side="left")
        tk.Label(foot, text="（事実・読み・理由の本文は変更できません）",
                 bg=CARD_BG, fg=LINE_COLOR, font=f["small"]).pack(side="left", padx=(8, 0))

    def _append_note(self, item):
        """
        訂正・補足を追記する小さなダイアログ。
        本文を書き換えさせないのは、後から「まあそうなると思っていた」に
        書き換わると外れが記録に残らず、この機能の目的が消えるため。
        """
        f = self.f
        dlg = tk.Toplevel(self.win)
        dlg.title("追記")
        dlg.configure(bg=BG_COLOR)
        dlg.geometry("460x300")
        dlg.attributes("-topmost", True)

        tk.Label(dlg, text=f"[{item['id']}] に追記", bg=BG_COLOR, fg=TEXT_COLOR,
                 font=f["label"]).pack(pady=(14, 2))
        tk.Label(dlg, text=item.get("rain", ""), bg=BG_COLOR, fg=BODY_TEXT,
                 font=f["body"], wraplength=410,
                 justify="left").pack(padx=24, pady=(0, 4))
        tk.Label(dlg, text="元の事実・読み・理由は変更できません。"
                            "思い直したことはここに積まれます。",
                 bg=BG_COLOR, fg=DIM_TEXT, font=f["small"], wraplength=410,
                 justify="left").pack(padx=24, pady=(0, 6))

        box = _PlaceholderText(dlg, "気づいたこと・訂正", height=5, font=f["body"])
        box.pack(fill="x", padx=24)

        msg = tk.Label(dlg, text="", bg=BG_COLOR, fg=ACCENT_COLOR, font=f["small"])
        msg.pack(pady=(4, 0))

        def save():
            text = box.value()
            if not text:
                msg.config(text="⚠️ 追記する内容を入力してください")
                return
            fc.append_note(item["id"], text)
            dlg.destroy()
            self.refresh()

        row = tk.Frame(dlg, bg=BG_COLOR)
        row.pack(fill="x", padx=24, pady=(8, 14))
        for c in range(2):
            row.columnconfigure(c, weight=1, uniform="b")
        tk.Button(row, text="追記する", bg=PRIMARY_BTN_BG, fg=BUTTON_TEXT_COLOR,
                  relief="flat", font=f["label"], pady=5, cursor="hand2",
                  command=save).grid(row=0, column=0, sticky="ew", padx=3)
        tk.Button(row, text="閉じる", bg=BTN_BG, fg=BUTTON_TEXT_COLOR,
                  relief="flat", font=f["label"], pady=5, cursor="hand2",
                  command=dlg.destroy).grid(row=0, column=1, sticky="ew", padx=3)
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _new(self):
        ForecastEntryWindow(self.root, on_saved=lambda _i: self.refresh())

    def _review(self):
        due = fc.get_due_forecasts()
        if not due:
            self.summary.config(text="確認期日が来ている読みはありません。")
            return
        ForecastReviewWindow(self.root, due, on_done=self.refresh,
                             total_due=fc.count_due())


def open_forecast_list(root):
    """一覧を開く（ポップアップのボタンから呼ぶ）。"""
    return ForecastListWindow(root)


def open_forecast_entry(root, seed_umbrella: str = "", seed_reason: str = ""):
    """読みの入力フォームを開く（タスクからの流し込みにも使う）。"""
    return ForecastEntryWindow(root, seed_umbrella=seed_umbrella,
                                seed_reason=seed_reason)


def prompt_due_forecasts_if_needed(root) -> bool:
    """
    起動時に呼ぶ。確認期日の来た読みがあり、今日まだ督促していなければ
    答え合わせ画面を出す。出したらTrueを返す。

    人は自分から見返さないので、向こうから出てくる必要がある。
    ただし毎時のポップアップに混ぜると1日11回になって無視されるため、
    1日1回・古い順に最大MAX_DUE_PROMPT件だけに抑える。
    """
    try:
        if not fc.should_prompt_today():
            return False
        due = fc.get_due_forecasts()
        if not due:
            return False
        fc.mark_prompted_today()
        ForecastReviewWindow(root, due, total_due=fc.count_due())
        print(f"{ICON_READ} 確認期日の来た読みを {len(due)}件 提示しました。")
        return True
    except Exception as e:
        # 督促で落ちて本体の起動を妨げないようにする
        print(f"⚠️ 読みの督促に失敗しました: {e}")
        return False
