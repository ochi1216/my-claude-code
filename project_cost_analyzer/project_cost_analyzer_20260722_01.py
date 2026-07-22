"""Project Cost Analyzer — KOB1シート（SAPプロジェクトコスト実績明細）を読み込み、
プロジェクト単位のコスト分析を行うStreamlitダッシュボード。

使い方:
    streamlit run project_cost_analyzer_20260722_01.py

サイドバーでExcelファイル（.xlsm/.xlsx、KOB1シートを含むもの）をアップロードするか、
ローカルパスを指定して読み込む。
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

SHEET_NAME = "KOB1"
AMOUNT_COL = "Val/COArea Crcy"
PROJECT_COL = "Project Name"

DEFAULT_PATH = (
    r"C:\Users\nx023836\Documents\PythonScripts\PM_organizer\ProjectCost"
    r"\BG ICS Project cost summary_20260722.xlsm"
)

INT_COLS = ["Cost Element", "SPARC ID", "Period", "Fiscal Year", "Order Type", "S4 FSItem"]
NUMERIC_COLS = ["Total Quantity", AMOUNT_COL, "Man month"]


def load_kob1(source) -> pd.DataFrame:
    """KOB1シートを読み込み、型を整えたDataFrameを返す。

    source: ファイルパス(str/Path) または file-like オブジェクト。
    """
    df = pd.read_excel(source, sheet_name=SHEET_NAME, engine="openpyxl")
    df = df.dropna(how="all")

    for col in INT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 文字列列の空文字はNaNに揃える（欠損の扱いを統一するため）
    obj_cols = df.select_dtypes(include="object").columns
    df[obj_cols] = df[obj_cols].apply(lambda s: s.where(s.astype(str).str.strip() != "", None))

    df["period_label"] = (
        df["Fiscal Year"].astype("Int64").astype(str) + "-" + df["Period"].astype("Int64").astype(str).str.zfill(2)
    )
    return df


def filter_data(
    df: pd.DataFrame,
    projects: list[str] | None = None,
    fiscal_years: list[int] | None = None,
    statuses: list[str] | None = None,
    cost_categories: list[str] | None = None,
) -> pd.DataFrame:
    out = df
    if projects:
        out = out[out[PROJECT_COL].isin(projects)]
    if fiscal_years:
        out = out[out["Fiscal Year"].isin(fiscal_years)]
    if statuses:
        out = out[out["Project status"].isin(statuses)]
    if cost_categories:
        out = out[out["Cost Category"].isin(cost_categories)]
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


def agg_by_period(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("period_label", dropna=True)[AMOUNT_COL]
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
            Lines=(AMOUNT_COL, "size"),
            PMs=("PM", lambda s: ", ".join(sorted(set(s.dropna())))),
        )
        .sort_values("Cost", key=lambda s: s.abs(), ascending=False)
        .reset_index()
    )


def _to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, sheet_df in sheets.items():
            sheet_df.to_excel(writer, sheet_name=name[:31], index=False)
    return buf.getvalue()


def main() -> None:
    st.set_page_config(page_title="Project Cost Analyzer (KOB1)", layout="wide")
    st.title("Project Cost Analyzer — KOB1コスト分析")

    st.sidebar.header("データ読み込み")
    uploaded = st.sidebar.file_uploader("KOB1を含むExcelファイル (.xlsm/.xlsx)", type=["xlsm", "xlsx"])
    path_input = st.sidebar.text_input("またはローカルパスを指定", value=DEFAULT_PATH)

    source = uploaded if uploaded is not None else path_input
    if not source:
        st.info("サイドバーからファイルをアップロードするか、パスを指定してください。")
        return

    try:
        if isinstance(source, str):
            if not Path(source).exists():
                st.warning(f"ファイルが見つかりません: {source}")
                return
            df = load_kob1(source)
        else:
            df = load_kob1(source)
    except ValueError as exc:
        st.error(f"読み込みに失敗しました（KOB1シートを確認してください）: {exc}")
        return

    st.sidebar.header("フィルタ")
    all_projects = sorted(df[PROJECT_COL].dropna().unique())
    projects = st.sidebar.multiselect("Project Name", all_projects)
    fiscal_years = st.sidebar.multiselect("Fiscal Year", sorted(df["Fiscal Year"].dropna().unique().astype(int)))
    statuses = st.sidebar.multiselect("Project status", sorted(df["Project status"].dropna().unique()))
    cost_categories = st.sidebar.multiselect("Cost Category", sorted(df["Cost Category"].dropna().unique()))

    filtered = filter_data(df, projects, list(fiscal_years), statuses, cost_categories)

    if filtered.empty:
        st.warning("条件に一致する明細がありません。")
        return

    total_cost = filtered[AMOUNT_COL].sum()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("対象コスト合計", f"{total_cost:,.0f}")
    col2.metric("明細行数", f"{len(filtered):,}")
    col3.metric("対象プロジェクト数", f"{filtered[PROJECT_COL].nunique():,}")
    col4.metric("対象期間", f"{filtered['period_label'].min()} 〜 {filtered['period_label'].max()}")

    st.subheader("プロジェクト別コスト内訳")
    st.dataframe(project_summary(filtered), use_container_width=True)

    st.subheader("期間別コスト推移")
    period_df = agg_by_period(filtered)
    st.plotly_chart(px.line(period_df, x="period_label", y="Cost", markers=True), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Cost Category別")
        st.plotly_chart(px.bar(agg_by(filtered, "Cost Category"), x="Cost Category", y="Cost"), use_container_width=True)
    with c2:
        st.subheader("PM cost category別")
        st.plotly_chart(px.bar(agg_by(filtered, "PM cost category"), x="PM cost category", y="Cost"), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("Cost Element別（上位15）")
        top_elements = agg_by(filtered, "Cost element name", top_n=15)
        st.plotly_chart(px.bar(top_elements, x="Cost", y="Cost element name", orientation="h"), use_container_width=True)
    with c4:
        st.subheader("Function別")
        func_df = agg_by(filtered, "Function")
        if func_df.empty:
            st.caption("Function列が空のため表示するデータがありません。")
        else:
            st.plotly_chart(px.bar(func_df, x="Function", y="Cost"), use_container_width=True)

    st.subheader("明細データ")
    st.dataframe(filtered, use_container_width=True, height=400)

    excel_bytes = _to_excel_bytes(
        {
            "明細": filtered,
            "プロジェクト別": project_summary(filtered),
            "期間別": period_df,
        }
    )
    st.download_button(
        "分析結果をExcelでダウンロード",
        data=excel_bytes,
        file_name="project_cost_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
