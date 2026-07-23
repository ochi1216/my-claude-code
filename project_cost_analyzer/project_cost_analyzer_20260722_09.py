"""Project Cost Analyzer — KOB1シート（SAPプロジェクトコスト実績明細）を読み込み、
コスト分析を行うStreamlitダッシュボード。

使い方:
    streamlit run project_cost_analyzer_20260722_09.py

3つの視点をタブで切り替えて分析する:
    1. 🏛 事業部俯瞰      … 全Profit Center（R03/R04/R07/R0N/R0S/R19）を横断俯瞰（ディレクター視点）
    2. 🧭 プロジェクト深掘り … 単一プロジェクトのカルテ・バーンチャート・コスト構造（PM視点）
    3. 🔧 ファンクション横断 … 職種(Function)が全プロジェクトにどう配分されているか（ファンクションマネージャー視点）

通貨について:
    金額列 `Val/COArea Crcy` は SAP の統制領域通貨（Controlling Area Currency）で、
    Company Code横断で単一通貨に統一済み。ブック内「Cost by nature」シートが
    "Cost in $" と明示しているため、本ツールでは USD として表示する。

キャッシュについて:
    元データ（18MB前後、8万行超）のExcelパースは十数秒かかるため、パース結果を
    `.kob1_cache/` にpickle保存し、元ファイルの更新日時・サイズが変わっていなければ
    次回起動時にそこから即座に読み込む（実測: 初回15秒前後 → 再起動後2秒台）。

設定の保存について:
    サイドバーのファイルパス・フィルタ選択（Profit Center / Fiscal Year / Project status /
    グラフの積み上げ設定 など）は、スクリプトと同じフォルダの `.pca_settings.json` に
    保存し、次回起動時に前回の設定のまま復元する。
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

SHEET_NAME = "KOB1"
AMOUNT_COL = "Val/COArea Crcy"
PROJECT_COL = "Project Name"
CACHE_DIRNAME = ".kob1_cache"
SETTINGS_FILENAME = ".pca_settings.json"
CURRENCY = "USD"

DEFAULT_PATH = (
    r"C:\Users\nx023836\Documents\PythonScripts\PM_organizer\ProjectCost"
    r"\BG ICS Project cost summary_20260722.xlsm"
)

INT_COLS = ["Cost Element", "SPARC ID", "Period", "Fiscal Year", "Order Type", "S4 FSItem"]
NUMERIC_COLS = ["Total Quantity", AMOUNT_COL, "Man month"]

# 非プロジェクト費（一般R&D・EDA配賦・Sustaining等）は Project status = "Other IO"
NON_PROJECT_STATUS = "Other IO"
LABOR_CATEGORIES = ["Time Writing"]  # 内部労務
EXTERNAL_CATEGORIES = ["Material", "Service"]  # 外部購買

# コスト種別深掘り（A: 内部労務の職種軸 / B・C: 外部購買の性質軸）。
# Function/Func.CategoryはTime Writing(内部労務)行にしか値が入らず、
# FSI Description/B4P categoryは内部労務だとほぼ全件"Int chrg-Timewriting"一色（B4Pだと
# "Int chrg-Time"一色）で分解の意味が無いため、軸ごとに対象とするCost Categoryを分けている
# （実データで確認済み）。B4P categoryはFSI Descriptionより粗い分類（9種 vs 約28種）。
DRILLDOWN_AXES = {
    "Function（内部労務）": ("Function", ["Time Writing", "Tariff Delta"]),
    "Func.Category（内部労務・上位区分）": ("Func.Category", ["Time Writing", "Tariff Delta"]),
    "B4P category（外部購買・上位区分）": ("B4P category", ["Material", "Service"]),
    "FSI Description（外部購買）": ("FSI Description", ["Material", "Service"]),
}
DETAIL_TABLE_COLUMNS = [
    "Project Name", "PM", "Function", "Organization", "Resource name",
    "Cost element name", "Purchase order text", "Company Code", "Profit Center",
    "Fiscal Year", "Period", "Cost Category", AMOUNT_COL,
]
# フィルタ対象は金額列(連続値なので複数選択フィルタに不向き)を除く全列。
# 順序はDETAIL_TABLE_COLUMNS（テーブルの列順）に揃える。
DETAIL_FILTER_COLUMNS = [c for c in DETAIL_TABLE_COLUMNS if c != AMOUNT_COL]
FILTER_COLUMNS_PER_ROW = 4

# 次回起動時に復元する設定のキーと既定値（選択系ウィジェットのkeyと一致させること）
SETTINGS_DEFAULTS = {
    "s_path": DEFAULT_PATH,
    "s_profit_centers": [],
    "s_fiscal_years": [],
    "s_statuses": [],
    "s_project": None,
    "s_function": None,
    "pf_stacked": False,
    "pf_stackcol": "Cost Category",
    "bd_costcat_pie": False,
    "bd_pmcat_pie": False,
    "bd_func_pie": False,
    "bd_ce_pie": False,
    "proj_func_pie": False,
    "proj_org_pie": False,
    "proj_costcat_pie": False,
    "dd_axis": None,
    "dd_value": None,
    "pdd_axis": None,
    "pdd_value": None,
}


# --------------------------------------------------------------------------- #
# データ読み込み・キャッシュ
# --------------------------------------------------------------------------- #
def load_kob1(source) -> pd.DataFrame:
    """KOB1シートを読み込み、型を整えたDataFrameを返す（キャッシュを介さない直読み込み）。"""
    df = pd.read_excel(source, sheet_name=SHEET_NAME, engine="openpyxl")
    df = df.dropna(how="all")

    for col in INT_COLS + NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 文字列列の空文字はNaNに揃える（欠損の扱いを統一するため）
    obj_cols = df.select_dtypes(include="object").columns
    df[obj_cols] = df[obj_cols].apply(lambda s: s.where(s.astype(str).str.strip() != "", None))

    df["period_label"] = (
        df["Fiscal Year"].astype("Int64").astype(str)
        + "-"
        + df["Period"].astype("Int64").astype(str).str.zfill(2)
    )
    return df


def _cache_dir_for_source(source) -> Path:
    """ソースファイルの隣に `.kob1_cache` を置く。パス不明な場合はOS一時フォルダを使う。"""
    if isinstance(source, str) and Path(source).exists():
        return Path(source).resolve().parent / CACHE_DIRNAME
    return Path(tempfile.gettempdir()) / "project_cost_analyzer_cache"


def _cache_key_for_source(source) -> str:
    """元データが変わっていなければ同じ値になる識別子。"""
    if isinstance(source, str):
        p = Path(source)
        stat = p.stat()
        raw = f"{p.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
        return hashlib.sha256(raw.encode()).hexdigest()
    return hashlib.sha256(source.getvalue()).hexdigest()


def _cache_path_for_source(source) -> Path:
    return _cache_dir_for_source(source) / f"kob1_{_cache_key_for_source(source)}.pkl"


def _load_with_disk_cache(source, force_reload: bool = False) -> tuple[pd.DataFrame, bool]:
    """ディスクキャッシュがあればそれを読み、無ければパースしてキャッシュに保存する。"""
    cache_path = _cache_path_for_source(source)

    if not force_reload and cache_path.exists():
        return pd.read_pickle(cache_path), True

    df = load_kob1(source)

    try:
        cache_path.parent.mkdir(exist_ok=True)
        for old_file in cache_path.parent.glob("kob1_*.pkl"):
            if old_file != cache_path:
                old_file.unlink(missing_ok=True)
        df.to_pickle(cache_path)
    except OSError:
        pass  # キャッシュ保存に失敗しても分析自体は継続する

    return df, False


@st.cache_data(show_spinner="KOB1データを読み込み中...")
def _load_cached(_source, session_cache_key: str, force_reload: bool) -> tuple[pd.DataFrame, bool]:
    return _load_with_disk_cache(_source, force_reload=force_reload)


# --------------------------------------------------------------------------- #
# 設定の保存・復元（前回の設定のまま起動できるようにする）
# --------------------------------------------------------------------------- #
def _settings_path() -> Path:
    return Path(__file__).resolve().parent / SETTINGS_FILENAME


def load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    try:
        _settings_path().write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 保存に失敗しても分析は継続する


# --------------------------------------------------------------------------- #
# 集計ヘルパー
# --------------------------------------------------------------------------- #
def usd(x: float) -> str:
    return f"${x:,.0f}"


def filter_data(df: pd.DataFrame, profit_centers=None, fiscal_years=None, statuses=None) -> pd.DataFrame:
    out = df
    if profit_centers:
        out = out[out["Profit Center"].isin(profit_centers)]
    if fiscal_years:
        out = out[out["Fiscal Year"].isin(fiscal_years)]
    if statuses:
        out = out[out["Project status"].isin(statuses)]
    return out


def agg_by(df: pd.DataFrame, group_col: str, top_n: int | None = None) -> pd.DataFrame:
    sub = df.dropna(subset=[group_col])
    result = (
        sub.groupby(group_col, dropna=True)[AMOUNT_COL]
        .sum()
        .sort_values(key=lambda s: s.abs(), ascending=False)
        .reset_index()
        .rename(columns={AMOUNT_COL: "Cost"})
    )
    if top_n:
        result = result.head(top_n)
    return result


def agg_by_period(df: pd.DataFrame, stack_col: str | None = None) -> pd.DataFrame:
    """期間別コスト。stack_col指定時は (period_label, stack_col) 単位のロング形式を返す。"""
    keys = ["period_label"] + ([stack_col] if stack_col else [])
    return (
        df.dropna(subset=[stack_col] if stack_col else [])
        .groupby(keys, dropna=True)[AMOUNT_COL]
        .sum()
        .reset_index()
        .sort_values("period_label")
        .rename(columns={AMOUNT_COL: "Cost"})
    )


def project_summary(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(PROJECT_COL, dropna=True)
        .agg(
            Cost=(AMOUNT_COL, "sum"),
            PMs=("PM", lambda s: ", ".join(sorted(set(s.dropna())))),
            Status=("Project status", lambda s: ", ".join(sorted(set(s.dropna())))),
        )
        .sort_values("Cost", key=lambda s: s.abs(), ascending=False)
        .reset_index()
    )


def profit_center_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Profit Center（事業部）ごとの俯瞰サマリー。"""
    rows = []
    for pc, sub in df.groupby("Profit Center", dropna=True):
        total = sub[AMOUNT_COL].sum()
        proj = sub[sub["Project status"] != NON_PROJECT_STATUS]
        nonproj = sub[sub["Project status"] == NON_PROJECT_STATUS]
        labor = sub[sub["Cost Category"].isin(LABOR_CATEGORIES)][AMOUNT_COL].sum()
        n_proj = proj[PROJECT_COL].nunique()
        rows.append(
            {
                "Profit Center": pc,
                "総コスト(USD)": total,
                "プロジェクト費": proj[AMOUNT_COL].sum(),
                "非プロジェクト費": nonproj[AMOUNT_COL].sum(),
                "プロジェクト数": n_proj,
                "平均/プロジェクト": (proj[AMOUNT_COL].sum() / n_proj) if n_proj else 0.0,
                "内部労務比率": (labor / total) if total else 0.0,
            }
        )
    out = pd.DataFrame(rows).sort_values("総コスト(USD)", ascending=False).reset_index(drop=True)
    return out


def _to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, sheet_df in sheets.items():
            sheet_df.to_excel(writer, sheet_name=name[:31], index=False)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# 期間別コスト推移（棒グラフ、積み上げトグル対応）
# --------------------------------------------------------------------------- #
def render_period_bar(df: pd.DataFrame, key_prefix: str, default_stacked: bool) -> None:
    st.subheader("期間別コスト推移")
    c1, c2 = st.columns([1, 2])
    st.session_state.setdefault(f"{key_prefix}_stacked", default_stacked)
    stacked = c1.toggle("積み上げ表示", key=f"{key_prefix}_stacked")
    stack_col = None
    if stacked:
        stack_col = c2.selectbox(
            "積み上げの軸",
            ["Cost Category", "Profit Center", "PM cost category"],
            key=f"{key_prefix}_stackcol",
        )

    if stacked and stack_col:
        data = agg_by_period(df, stack_col=stack_col)
        fig = px.bar(data, x="period_label", y="Cost", color=stack_col, barmode="stack")
    else:
        data = agg_by_period(df)
        fig = px.bar(data, x="period_label", y="Cost")

    fig.update_layout(xaxis_title="会計年度-期", yaxis_title=f"Cost ({CURRENCY})", legend_title=stack_col or "")
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_period_chart")


def render_breakdown(df: pd.DataFrame, group_col: str, title: str, key: str, top_n: int | None = None) -> None:
    """指定軸のコスト内訳を、棒グラフ（既定）と円グラフ（トグルON）で切り替え表示する。"""
    hcol, tcol = st.columns([3, 1])
    hcol.markdown(f"##### {title}")
    st.session_state.setdefault(f"{key}_pie", False)
    as_pie = tcol.toggle("円グラフ", key=f"{key}_pie")

    data = agg_by(df, group_col, top_n=top_n)
    if data.empty:
        st.caption("表示するデータがありません。")
        return

    if as_pie:
        pos = data[data["Cost"] > 0]
        fig = px.pie(pos, names=group_col, values="Cost", hole=0.35)
        if len(pos) < len(data):
            st.caption("※ 円グラフはプラスの項目のみ表示（マイナス＝会計調整分は除外）。")
    else:
        fig = px.bar(data.sort_values("Cost"), x="Cost", y=group_col, orientation="h")
        fig.update_layout(xaxis_title=f"Cost ({CURRENCY})")
    st.plotly_chart(fig, use_container_width=True, key=f"{key}_chart")


def render_filterable_table(df: pd.DataFrame, key: str) -> None:
    """Excelライクにフィルタ・並び替えができる明細テーブル。

    「表示する列」で列を外すと、テーブル表示だけでなくフィルタ欄からもその列が連動して消える。
    フィルタの並び順は常にテーブルの列順（DETAIL_TABLE_COLUMNS）に揃える。
    """
    if df.empty:
        st.caption("表示する明細がありません。")
        return

    all_cols = [c for c in DETAIL_TABLE_COLUMNS if c in df.columns]
    visible_key = f"{key}_visible_cols"
    st.session_state.setdefault(visible_key, all_cols)
    st.session_state[visible_key] = [c for c in st.session_state[visible_key] if c in all_cols] or all_cols
    st.multiselect("表示する列（外した列はフィルタからも消えます）", all_cols, key=visible_key)
    # ウィジェットの選択順ではなく、常にテーブルの列順に揃える
    visible_cols = [c for c in all_cols if c in st.session_state[visible_key]]
    if not visible_cols:
        st.warning("表示する列を1つ以上選んでください。")
        return

    filter_cols = [c for c in DETAIL_FILTER_COLUMNS if c in visible_cols]
    with st.expander(f"🔍 フィルタ（{len(df):,}行が対象）", expanded=False):
        picks: dict[str, list] = {}
        if not filter_cols:
            st.caption("フィルタ可能な列がすべて非表示になっています。")
        for row_start in range(0, len(filter_cols), FILTER_COLUMNS_PER_ROW):
            row = filter_cols[row_start : row_start + FILTER_COLUMNS_PER_ROW]
            st_cols = st.columns(len(row))
            for c, col_name in zip(st_cols, row):
                options = sorted(df[col_name].dropna().unique())
                picks[col_name] = c.multiselect(col_name, options, key=f"{key}_filter_{col_name}")

    work = df
    for col_name, picked in picks.items():
        if picked:
            work = work[work[col_name].isin(picked)]

    sort_cols = visible_cols
    sc1, sc2 = st.columns([3, 1])
    default_sort_idx = sort_cols.index(AMOUNT_COL) if AMOUNT_COL in sort_cols else 0
    sort_col = sc1.selectbox("並び替え列", sort_cols, index=default_sort_idx, key=f"{key}_sortcol")
    ascending = sc2.toggle("昇順", value=False, key=f"{key}_asc")
    work = work.sort_values(sort_col, ascending=ascending)

    st.caption(f"表示中: {len(work):,}行 ／ 合計 {usd(work[AMOUNT_COL].sum())}")
    st.dataframe(work[visible_cols], use_container_width=True, hide_index=True, height=400)

    st.download_button(
        "この明細をExcelでダウンロード",
        data=_to_excel_bytes({"明細": work[visible_cols]}),
        file_name="cost_detail.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key}_dl",
    )


def render_axis_drilldown(df: pd.DataFrame, key_prefix: str = "dd") -> None:
    """内部労務(Function/Func.Category)・外部購買(B4P category/FSI Description)の深掘り＋明細。

    key_prefix: 同一画面（同一スクリプト実行）内で複数回呼び出せるよう、ウィジェットkey・
    永続化keyを呼び出し元ごとに分離するための接頭辞（例: 事業部俯瞰タブ="dd"、
    プロジェクト深掘りタブ="pdd"）。
    """
    axis_key = f"{key_prefix}_axis"
    value_key = f"{key_prefix}_value"

    st.markdown("#### コスト種別 深掘り（内部労務 / 外部購買）")
    st.caption(
        "内部労務(Time Writing)はFunction・Func.Categoryで、外部購買(Material/Service)は"
        "B4P category（粗め）・FSI Description（細かめ）で、それぞれ内訳を深掘りできます。"
    )

    axis_labels = list(DRILLDOWN_AXES.keys())
    st.session_state.setdefault(axis_key, axis_labels[0])
    if st.session_state[axis_key] not in axis_labels:
        st.session_state[axis_key] = axis_labels[0]
    axis_index = axis_labels.index(st.session_state[axis_key])
    axis_label = st.selectbox("分類軸を選択", axis_labels, index=axis_index, key=f"{axis_key}_widget")
    st.session_state[axis_key] = axis_label

    axis_col, scope_categories = DRILLDOWN_AXES[axis_label]
    scoped = df[df["Cost Category"].isin(scope_categories)].dropna(subset=[axis_col])
    if scoped.empty:
        st.caption("対象データがありません。")
        return

    render_breakdown(scoped, axis_col, f"{axis_label} 内訳", key=f"{key_prefix}_breakdown")

    values = sorted(scoped[axis_col].dropna().unique())
    if st.session_state.get(value_key) not in values:
        st.session_state[value_key] = values[0]
    value_index = values.index(st.session_state[value_key])
    picked = st.selectbox(
        f"{axis_label}の項目を選んで明細を表示", values, index=value_index, key=f"{value_key}_widget"
    )
    st.session_state[value_key] = picked

    detail = scoped[scoped[axis_col] == picked]
    st.markdown(f"##### 明細: {axis_label} = 「{picked}」")
    render_filterable_table(detail, key=f"{key_prefix}_table")


# --------------------------------------------------------------------------- #
# タブ1: 事業部俯瞰（全Profit Center）
# --------------------------------------------------------------------------- #
def tab_portfolio(df: pd.DataFrame, default_stacked: bool) -> None:
    st.markdown("#### 事業部（Profit Center）別サマリー")
    summary = profit_center_summary(df)
    disp = summary.copy()
    for c in ["総コスト(USD)", "プロジェクト費", "非プロジェクト費", "平均/プロジェクト"]:
        disp[c] = disp[c].map(usd)
    disp["内部労務比率"] = summary["内部労務比率"].map(lambda x: f"{x:.0%}")
    st.dataframe(disp, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 事業部別 総コスト")
        fig = px.bar(summary, x="Profit Center", y="総コスト(USD)")
        fig.update_layout(yaxis_title=f"Cost ({CURRENCY})")
        st.plotly_chart(fig, use_container_width=True, key="pf_total_by_pc_chart")
    with c2:
        st.markdown("##### プロジェクト費 vs 非プロジェクト費")
        melt = summary.melt(
            id_vars="Profit Center",
            value_vars=["プロジェクト費", "非プロジェクト費"],
            var_name="区分",
            value_name="Cost",
        )
        fig = px.bar(melt, x="Profit Center", y="Cost", color="区分", barmode="stack")
        fig.update_layout(yaxis_title=f"Cost ({CURRENCY})")
        st.plotly_chart(fig, use_container_width=True, key="pf_proj_vs_nonproj_chart")

    render_period_bar(df, key_prefix="pf", default_stacked=default_stacked)

    st.markdown("#### コスト内訳（多軸・棒グラフ / 円グラフ切替）")
    b1, b2 = st.columns(2)
    with b1:
        render_breakdown(df, "Cost Category", "Cost Category別", key="bd_costcat")
        render_breakdown(df, "Function", "Function別", key="bd_func")
    with b2:
        render_breakdown(df, "PM cost category", "PM cost category別", key="bd_pmcat")
        render_breakdown(df, "Cost element name", "Cost Element別（上位15）", key="bd_ce", top_n=15)

    render_axis_drilldown(df)

    st.markdown("#### プロジェクト別コスト内訳（対象スコープ全体）")
    ps = project_summary(df)
    ps_disp = ps.copy()
    ps_disp["Cost"] = ps_disp["Cost"].map(usd)
    st.dataframe(ps_disp, use_container_width=True, hide_index=True, height=360)

    st.download_button(
        "俯瞰結果をExcelでダウンロード",
        data=_to_excel_bytes({"事業部別": summary, "プロジェクト別": ps, "期間別": agg_by_period(df)}),
        file_name="project_cost_portfolio.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# --------------------------------------------------------------------------- #
# タブ2: プロジェクト深掘り（単一プロジェクト・カルテ）
# --------------------------------------------------------------------------- #
def tab_project(df: pd.DataFrame) -> None:
    projects = sorted(df[PROJECT_COL].dropna().unique())
    if not projects:
        st.info("対象スコープにプロジェクトがありません。")
        return

    # 前回選択したプロジェクトが対象内にあれば維持、無ければ先頭
    if st.session_state.get("s_project") not in projects:
        st.session_state["s_project"] = projects[0]
    # ウィジェット自体のkeyはs_projectと分け、indexを明示的に計算する。
    # （options配列がrerunごとに再生成されるため、st.session_state[key]による復元だけだと
    # プルダウンの表示ラベルが最初の選択肢のまま更新されないStreamlit側の癖を避けるため）
    proj_index = projects.index(st.session_state["s_project"])
    proj = st.selectbox("プロジェクトを選択", projects, index=proj_index, key="s_project_widget")
    st.session_state["s_project"] = proj

    sub = df[df[PROJECT_COL] == proj]
    total = sub[AMOUNT_COL].sum()
    labor = sub[sub["Cost Category"].isin(LABOR_CATEGORIES)][AMOUNT_COL].sum()
    orgs = sorted(sub["Organization"].dropna().unique())
    pms = sorted(sub["PM"].dropna().unique())

    st.markdown(f"### 📋 {proj}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("累計コスト", usd(total))
    m2.metric("内部労務比率", f"{(labor/total):.0%}" if total else "—")
    m3.metric("参加組織数", f"{len(orgs)}")
    m4.metric("対象期間", f"{sub['period_label'].min()} 〜 {sub['period_label'].max()}")
    st.caption(f"PM: {', '.join(pms) if pms else '—'} ／ 参加組織: {', '.join(orgs) if orgs else '—'}")

    # バーンチャート（月次バー + 累計ライン）
    st.markdown("#### バーンチャート（月次コスト と 累計）")
    ts = (
        sub.groupby("period_label")[AMOUNT_COL].sum().reset_index().sort_values("period_label")
        .rename(columns={AMOUNT_COL: "月次コスト"})
    )
    ts["累計"] = ts["月次コスト"].cumsum()

    fig = go.Figure()
    fig.add_bar(x=ts["period_label"], y=ts["月次コスト"], name="月次コスト")
    fig.add_scatter(x=ts["period_label"], y=ts["累計"], name="累計", mode="lines+markers", yaxis="y2")
    fig.update_layout(
        xaxis_title="会計年度-期",
        yaxis=dict(title=f"月次コスト ({CURRENCY})"),
        yaxis2=dict(title=f"累計 ({CURRENCY})", overlaying="y", side="right"),
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig, use_container_width=True, key="proj_burn_chart")
    if (ts["月次コスト"] < 0).any():
        st.caption("⚠️ マイナスの期は会計調整（accrual戻し等）を含みます。")

    # コスト構造
    c1, c2 = st.columns(2)
    with c1:
        render_breakdown(sub, "Function", "Function別", key="proj_func")
    with c2:
        render_breakdown(sub, "Organization", "組織(Organization)別", key="proj_org")

    # 内部労務 vs 外部購買
    render_breakdown(sub, "Cost Category", "コスト種別（内部労務 vs 外部購買）", key="proj_costcat")

    # コスト種別 深掘り（このプロジェクトに絞った上でFunction/Func.Category/B4P category/
    # FSI Descriptionで深掘り＋フィルタ・並び替え付き明細）
    render_axis_drilldown(sub, key_prefix="pdd")

    # 外部購買明細（PO単位）
    st.markdown("#### 外部購買 明細（PO単位）")
    po = (
        sub[sub["Cost Category"].isin(EXTERNAL_CATEGORIES)]
        .dropna(subset=["Purchase order text"])
        .groupby("Purchase order text")[AMOUNT_COL]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={AMOUNT_COL: "Cost", "Purchase order text": "Purchase Order"})
    )
    if po.empty:
        st.caption("PO単位で識別できる外部購買明細がありません。")
    else:
        po_disp = po.copy()
        po_disp["Cost"] = po_disp["Cost"].map(usd)
        st.dataframe(po_disp, use_container_width=True, hide_index=True, height=260)

    # 工数投下（FY2026のみ）
    st.markdown("#### 工数投下（Man month / FY2026）")
    mm = sub.dropna(subset=["Man month"])
    if mm.empty or mm["Man month"].sum() == 0:
        st.caption("このプロジェクトには工数(Man month)データがありません（工数はFY2026以降のみ記録）。")
    else:
        mmf = (
            mm.dropna(subset=["Function"]).groupby("Function")["Man month"].sum()
            .sort_values(ascending=False).reset_index()
        )
        st.plotly_chart(
            px.bar(mmf, x="Man month", y="Function", orientation="h"),
            use_container_width=True,
            key="proj_manmonth_chart",
        )


# --------------------------------------------------------------------------- #
# タブ3: ファンクション横断
# --------------------------------------------------------------------------- #
def tab_function(df: pd.DataFrame) -> None:
    functions = sorted(df["Function"].dropna().unique())
    if not functions:
        st.info("対象スコープにFunctionデータがありません。")
        return

    if st.session_state.get("s_function") not in functions:
        st.session_state["s_function"] = functions[0]
    func_index = functions.index(st.session_state["s_function"])
    func = st.selectbox("Function（職種）を選択", functions, index=func_index, key="s_function_widget")
    st.session_state["s_function"] = func

    sub = df[df["Function"] == func]
    total = sub[AMOUNT_COL].sum()
    mm_total = sub["Man month"].sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("このFunctionの総コスト", usd(total))
    m2.metric("投下プロジェクト数", f"{sub[PROJECT_COL].nunique()}")
    m3.metric("総工数(FY2026, MM)", f"{mm_total:.1f}" if pd.notna(mm_total) else "—")

    st.markdown("#### プロジェクト別のチャージ（コスト）")
    byproj = (
        sub.groupby(PROJECT_COL)
        .agg(Cost=(AMOUNT_COL, "sum"), ManMonth=("Man month", "sum"))
        .sort_values("Cost", ascending=False)
        .reset_index()
    )
    top = byproj.head(20)
    st.plotly_chart(
        px.bar(top, x="Cost", y=PROJECT_COL, orientation="h"),
        use_container_width=True,
        key="func_byproj_chart",
    )

    byproj_disp = byproj.copy()
    byproj_disp["Cost"] = byproj_disp["Cost"].map(usd)
    byproj_disp["ManMonth"] = byproj_disp["ManMonth"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "—")
    st.dataframe(byproj_disp, use_container_width=True, hide_index=True, height=300)

    st.markdown("#### リソース（担当者）別（FY2026）")
    res = sub.dropna(subset=["Resource name"])
    res = res[res["Man month"].notna()]
    if res.empty:
        st.caption("担当者別の工数データがありません（FY2026以降のみ記録）。")
    else:
        byres = (
            res.groupby("Resource name")
            .agg(Cost=(AMOUNT_COL, "sum"), ManMonth=("Man month", "sum"))
            .sort_values("ManMonth", ascending=False)
            .reset_index()
        )
        byres_disp = byres.copy()
        byres_disp["Cost"] = byres_disp["Cost"].map(usd)
        byres_disp["ManMonth"] = byres_disp["ManMonth"].map(lambda x: f"{x:.2f}")
        st.dataframe(byres_disp, use_container_width=True, hide_index=True, height=300)


# --------------------------------------------------------------------------- #
# メイン
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(page_title="Project Cost Analyzer (KOB1)", layout="wide")
    st.title("Project Cost Analyzer — KOB1コスト分析")
    st.sidebar.caption(f"🗂 実行中のファイル: `{Path(__file__).name}`")

    # 設定の復元（初回のみ session_state に流し込む）
    if "_seeded" not in st.session_state:
        saved = load_settings()
        merged = {**SETTINGS_DEFAULTS, **{k: v for k, v in saved.items() if k in SETTINGS_DEFAULTS}}
        for k, v in merged.items():
            st.session_state[k] = v
        st.session_state["_seeded"] = True

    # --- サイドバー: データ読み込み ---
    st.sidebar.header("データ読み込み")
    uploaded = st.sidebar.file_uploader("KOB1を含むExcelファイル (.xlsm/.xlsx)", type=["xlsm", "xlsx"])
    st.sidebar.text_input("またはローカルパスを指定", key="s_path")
    force_reload = st.sidebar.checkbox("キャッシュを無視して再読み込み", value=False)

    source = uploaded if uploaded is not None else st.session_state["s_path"]
    if not source:
        st.info("サイドバーからファイルをアップロードするか、パスを指定してください。")
        return
    if isinstance(source, str) and not Path(source).exists():
        st.warning(f"ファイルが見つかりません: {source}")
        return

    session_cache_key = _cache_key_for_source(source)
    if force_reload:
        session_cache_key += f":force:{time.time()}"

    try:
        df, was_cached = _load_cached(source, session_cache_key, force_reload)
    except ValueError as exc:
        st.error(f"読み込みに失敗しました（KOB1シートを確認してください）: {exc}")
        return

    st.sidebar.caption("📦 " + ("キャッシュから読み込みました（高速）" if was_cached else "元Excelを新規パースし保存しました"))

    # --- サイドバー: 全体フィルタ（永続化） ---
    st.sidebar.header("フィルタ")
    all_pc = sorted(df["Profit Center"].dropna().unique())
    all_fy = sorted(df["Fiscal Year"].dropna().unique().astype(int).tolist())
    all_status = sorted(df["Project status"].dropna().unique())

    # 保存値を現在の選択肢と突き合わせて健全化（データが変わっても壊れないように）
    st.session_state["s_profit_centers"] = [x for x in st.session_state.get("s_profit_centers", []) if x in all_pc]
    st.session_state["s_fiscal_years"] = [x for x in st.session_state.get("s_fiscal_years", []) if x in all_fy]
    st.session_state["s_statuses"] = [x for x in st.session_state.get("s_statuses", []) if x in all_status]

    st.sidebar.multiselect("Profit Center（事業部）", all_pc, key="s_profit_centers")
    st.sidebar.multiselect("Fiscal Year", all_fy, key="s_fiscal_years")
    st.sidebar.multiselect("Project status", all_status, key="s_statuses")

    filtered = filter_data(
        df,
        st.session_state["s_profit_centers"],
        st.session_state["s_fiscal_years"],
        st.session_state["s_statuses"],
    )
    if filtered.empty:
        st.warning("条件に一致する明細がありません。フィルタを見直してください。")
        return

    # --- サマリーカード（対象プロジェクト数 / 対象総コスト(USD) / 対象期間） ---
    c1, c2, c3 = st.columns(3)
    c1.metric("対象プロジェクト数", f"{filtered[PROJECT_COL].nunique():,}")
    c2.metric(f"対象総コスト（{CURRENCY}）", usd(filtered[AMOUNT_COL].sum()))
    c3.metric("対象期間", f"{filtered['period_label'].min()} 〜 {filtered['period_label'].max()}")

    # --- タブ ---
    t1, t2, t3 = st.tabs(["🏛 事業部俯瞰", "🧭 プロジェクト深掘り", "🔧 ファンクション横断"])
    with t1:
        tab_portfolio(filtered, default_stacked=st.session_state.get("pf_stacked", False))
    with t2:
        tab_project(filtered)
    with t3:
        tab_function(filtered)

    # 設定を保存（タブ内の選択・トグルも含めて確定した後に保存し、次回起動時に復元する）
    save_settings({k: st.session_state.get(k, default) for k, default in SETTINGS_DEFAULTS.items()})


if __name__ == "__main__":
    main()
