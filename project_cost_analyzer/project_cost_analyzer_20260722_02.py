"""Project Cost Analyzer — KOB1シート（SAPプロジェクトコスト実績明細）を読み込み、
プロジェクト単位のコスト分析を行うStreamlitダッシュボード。

使い方:
    streamlit run project_cost_analyzer_20260722_02.py

サイドバーでExcelファイル（.xlsm/.xlsx、KOB1シートを含むもの）をアップロードするか、
ローカルパスを指定して読み込む。

キャッシュについて:
    元データ（18MB前後、8万行超）のExcelパースは数十秒かかるため、パース結果を
    「元ファイルの隣（パス指定時）」または「OS一時フォルダ（アップロード時）」に
    `.kob1_cache/` としてpickle保存する。次回以降、元ファイルのパス・更新日時・
    サイズが変わっていなければ、パースをスキップしてキャッシュから即座に読み込む。
    同一Streamlitプロセス内では `st.cache_data` によりフィルタ操作のたびの
    再読み込みも避ける。元データを更新した場合は自動的にキャッシュが無効化される
    （更新日時・サイズが変わるため）。サイドバーの「キャッシュを無視して再読み込み」
    で強制的に再パースすることもできる。
"""

from __future__ import annotations

import hashlib
import io
import tempfile
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

SHEET_NAME = "KOB1"
AMOUNT_COL = "Val/COArea Crcy"
PROJECT_COL = "Project Name"
CACHE_DIRNAME = ".kob1_cache"

DEFAULT_PATH = (
    r"C:\Users\nx023836\Documents\PythonScripts\PM_organizer\ProjectCost"
    r"\BG ICS Project cost summary_20260722.xlsm"
)

INT_COLS = ["Cost Element", "SPARC ID", "Period", "Fiscal Year", "Order Type", "S4 FSItem"]
NUMERIC_COLS = ["Total Quantity", AMOUNT_COL, "Man month"]


def load_kob1(source) -> pd.DataFrame:
    """KOB1シートを読み込み、型を整えたDataFrameを返す（キャッシュを介さない直読み込み）。

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


def _cache_dir_for_source(source) -> Path:
    """ソースファイルの隣に `.kob1_cache` を置く。パス不明な場合はOS一時フォルダを使う。

    キャッシュはリポジトリ外（元データと同じ場所、またはOS一時フォルダ）に置き、
    機密データのキャッシュが誤ってGit管理下に入らないようにしている。
    """
    if isinstance(source, str) and Path(source).exists():
        return Path(source).resolve().parent / CACHE_DIRNAME
    return Path(tempfile.gettempdir()) / "project_cost_analyzer_cache"


def _cache_key_for_source(source) -> str:
    """元データが変わっていなければ同じ値になる識別子。

    パス指定時は「パス＋更新日時＋サイズ」、アップロード時は内容のハッシュを使う。
    """
    if isinstance(source, str):
        p = Path(source)
        stat = p.stat()
        raw = f"{p.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
        return hashlib.sha256(raw.encode()).hexdigest()
    return hashlib.sha256(source.getvalue()).hexdigest()


def _cache_path_for_source(source) -> Path:
    return _cache_dir_for_source(source) / f"kob1_{_cache_key_for_source(source)}.pkl"


def _load_with_disk_cache(source, force_reload: bool = False) -> tuple[pd.DataFrame, bool]:
    """ディスクキャッシュがあればそれを読み、無ければパースしてキャッシュに保存する。

    戻り値は (DataFrame, キャッシュから読んだか否か)。
    """
    cache_path = _cache_path_for_source(source)

    if not force_reload and cache_path.exists():
        return pd.read_pickle(cache_path), True

    df = load_kob1(source)

    try:
        cache_path.parent.mkdir(exist_ok=True)
        # 元データ更新等で無効になった古いキャッシュファイルが溜まらないよう、
        # 同じキャッシュフォルダ内の旧ファイルは先に削除しておく（1件あたり数十MB）
        for old_file in cache_path.parent.glob("kob1_*.pkl"):
            if old_file != cache_path:
                old_file.unlink(missing_ok=True)
        df.to_pickle(cache_path)
    except OSError:
        pass  # キャッシュ保存に失敗しても分析自体は継続する

    return df, False


@st.cache_data(show_spinner="KOB1データを読み込み中...")
def _load_cached(_source, session_cache_key: str, force_reload: bool) -> tuple[pd.DataFrame, bool]:
    # session_cache_key が実際のキャッシュ識別に使われる引数（st.cache_dataのキー）。
    # _source は先頭アンダースコアによりハッシュ対象から除外される（ファイルパス／
    # アップロードファイルはそのまま渡ってくる）。
    return _load_with_disk_cache(_source, force_reload=force_reload)


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
    force_reload = st.sidebar.checkbox("キャッシュを無視して再読み込み", value=False)

    source = uploaded if uploaded is not None else path_input
    if not source:
        st.info("サイドバーからファイルをアップロードするか、パスを指定してください。")
        return

    if isinstance(source, str) and not Path(source).exists():
        st.warning(f"ファイルが見つかりません: {source}")
        return

    session_cache_key = _cache_key_for_source(source)
    if force_reload:
        # force_reloadがONの間は毎回異なるキーにして st.cache_data 側の記憶も必ず無効化する
        session_cache_key += f":force:{time.time()}"

    try:
        df, was_cached = _load_cached(source, session_cache_key, force_reload)
    except ValueError as exc:
        st.error(f"読み込みに失敗しました（KOB1シートを確認してください）: {exc}")
        return

    cache_note = "キャッシュから読み込みました（高速）" if was_cached else "元Excelを新規にパースし、キャッシュに保存しました"
    st.sidebar.caption(f"📦 {cache_note}")
    st.sidebar.caption(f"キャッシュ保存先: `{_cache_dir_for_source(source)}`")

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
