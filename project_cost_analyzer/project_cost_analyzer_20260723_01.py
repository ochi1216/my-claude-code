"""Project Cost Analyzer — KOB1シート（SAPプロジェクトコスト実績明細）を読み込み、
コスト分析を行うStreamlitダッシュボード。

使い方:
    streamlit run project_cost_analyzer_20260723_01.py

4つの視点をタブで切り替えて分析する:
    1. 🏛 事業部俯瞰      … 全Profit Center（R03/R04/R07/R0N/R0S/R19）を横断俯瞰（ディレクター視点）
    2. 🧭 プロジェクト深掘り … 単一プロジェクトのカルテ・バーンチャート・コスト構造（PM視点）
    3. 🔧 ファンクション横断 … 職種(Function)が全プロジェクトにどう配分されているか（ファンクションマネージャー視点）
    4. 📅 コスト×スケジュール … Program Pipelineシートのマイルストーン実績とコストを、
       SPARC ID（Pipeline側「SPaRC ID」）で紐付けて概観する

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
from openpyxl.utils import column_index_from_string

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

# --------------------------------------------------------------------------- #
# プロジェクトスケジュール（Program Pipelineシート）関連の定数
# --------------------------------------------------------------------------- #
# Pipelineシートは "data_YYYYMMDDHHMM" のような名前で都度スナップショットされる想定のため、
# シート名を固定せず "data_" で始まるシートを探す（複数あれば名前の降順＝最新スナップショットを使う）
PIPELINE_SHEET_PREFIX = "data_"
PIPELINE_HEADER_ROW = 8  # この行（1始まり）が列見出し
SPARC_ID_COL = "SPARC ID"  # KOB1側の列名（このIDでPipeline側「SPaRC ID」と紐付ける）

# Pipelineシート内の固定列（列番号は8行目ヘッダーの位置。ユーザー確認済みのレイアウト）
_PIPELINE_FIELD_COLS = {
    "Stage": "D",
    "NEXT milestone": "E",
    "NEXT date": "F",
    "PAST milestone": "G",
    "PAST date": "H",
    "Project ID": "J",
    "SPARC ID": "K",
    "Sub#": "L",
    "Nick Name": "N",
    "Type": "R",
    "Track": "S",
    "PM": "T",
    # IOがオープンしコストがチャージされ始める日。CO〜DMのマイルストーン25種とは別枠だが、
    # コスト×スケジュールの時系列を合わせる基点として扱う（プロジェクト深掘りタブの統合グラフ用）
    "PS": "AV",
}
_PIPELINE_MILESTONE_START_COL = "CO"
_PIPELINE_MILESTONE_END_COL = "DM"
# コストと重ねる時系列グラフからは除外する優先順位の低いサブマイルストーン
# （コスト×スケジュールタブの「マイルストーン一覧」テーブルでは引き続き全件表示する）
MILESTONE_CHART_EXCLUDE = {"FO1", "BO1", "SA1", "F FO", "F BO", "F SA"}

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

# Pipeline明細テーブルの表示列（マイルストーン列は都度PIPELINE_MILESTONE_COLSを末尾に追加する）
PIPELINE_TABLE_COLUMNS = [
    "Nick Name", "Project ID", "SPARC ID", "Sub#", "Stage", "Type", "Track", "PM",
    "PAST milestone", "PAST date", "NEXT milestone", "NEXT date",
]
PIPELINE_FILTER_COLUMNS = ["Nick Name", "Project ID", "Stage", "Type", "Track", "PM", "PAST milestone", "NEXT milestone"]

# 次回起動時に復元する設定のキーと既定値（選択系ウィジェットのkeyと一致させること）
SETTINGS_DEFAULTS = {
    "s_path": DEFAULT_PATH,
    "s_schedule_path": "",
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
    "sch_project": None,
    "sch_sparc_id": None,
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
# プロジェクトスケジュール（Program Pipelineシート）の読み込み
# --------------------------------------------------------------------------- #
def find_pipeline_sheets(source) -> list[str]:
    """"data_"で始まるシート名を、名前の降順（最新スナップショットが先頭）で返す。"""
    xls = pd.ExcelFile(source, engine="openpyxl")
    return sorted((s for s in xls.sheet_names if s.startswith(PIPELINE_SHEET_PREFIX)), reverse=True)


def load_pipeline(source, sheet_name: str) -> tuple[pd.DataFrame, list[str]]:
    """Pipelineシートを読み込み、キー列＋マイルストーン列だけの整形済みDataFrameを返す。

    列は名前ではなく列位置（列レター）で特定する（ユーザー確認済みレイアウト:
    D=Stage, E=NEXT, F=LV_date, G=PAST, H=Done, J=Project ID, K=SPaRC ID, L=Sub#,
    N=Nick Name, R=Type, S=Track, T=PM, CO〜DM=マイルストーン実績日）。
    """
    raw = pd.read_excel(source, sheet_name=sheet_name, header=PIPELINE_HEADER_ROW - 1, engine="openpyxl")

    milestone_start = column_index_from_string(_PIPELINE_MILESTONE_START_COL) - 1
    milestone_end = column_index_from_string(_PIPELINE_MILESTONE_END_COL) - 1
    milestone_cols = raw.columns[milestone_start : milestone_end + 1].tolist()

    out = pd.DataFrame(
        {
            name: raw.iloc[:, column_index_from_string(letter) - 1]
            for name, letter in _PIPELINE_FIELD_COLS.items()
        }
    )
    for col in milestone_cols:
        out[col] = raw[col]

    # Project ID・SPARC ID・Nick Nameが全て空の行（罫線のみの空行など）は除外
    out = out.dropna(subset=["Project ID", "SPARC ID", "Nick Name"], how="all").reset_index(drop=True)

    out[SPARC_ID_COL] = pd.to_numeric(out[SPARC_ID_COL], errors="coerce").astype("Int64")
    out["Sub#"] = pd.to_numeric(out["Sub#"], errors="coerce").astype("Int64")
    out["Stage"] = pd.to_numeric(out["Stage"], errors="coerce")

    # マイルストーン実績日・NEXT/PAST日付・PS(IOオープン日)は "-"（未達成）や"TBD"を含むため、
    # 日付化できない値はNaTにする
    for col in milestone_cols + ["NEXT date", "PAST date", "PS"]:
        out[col] = pd.to_datetime(out[col], errors="coerce", format="mixed")

    return out, milestone_cols


@st.cache_data(show_spinner="プロジェクトスケジュールを読み込み中...")
def _load_pipeline_cached(_source, sheet_name: str, session_cache_key: str) -> tuple[pd.DataFrame, list[str]]:
    return load_pipeline(_source, sheet_name)


def milestones_long(pipeline_row: pd.Series, milestone_cols: list[str]) -> pd.DataFrame:
    """1レコード分のマイルストーン列を「マイルストーン名・実績日」の縦持ちに変換する。"""
    data = [(m, pipeline_row[m]) for m in milestone_cols]
    out = pd.DataFrame(data, columns=["マイルストーン", "実績日"])
    out["達成"] = out["実績日"].notna()
    return out


def schedule_link_summary(cost_df: pd.DataFrame, pipeline_df: pd.DataFrame) -> pd.DataFrame:
    """KOB1側 Project Name ごとに、紐付くPipeline側SPARC ID・Nick Nameの状況をまとめる。"""
    cost_ids = cost_df.dropna(subset=[SPARC_ID_COL])
    rows = []
    for proj, sub in cost_ids.groupby(PROJECT_COL):
        ids = sorted(int(i) for i in sub[SPARC_ID_COL].dropna().unique())
        matched = pipeline_df[pipeline_df[SPARC_ID_COL].isin(ids)]
        rows.append(
            {
                PROJECT_COL: proj,
                "KOB1側SPARC ID": ", ".join(str(int(i)) for i in ids),
                "Pipeline側 紐付け件数": len(matched),
                "Pipeline側 Nick Name": ", ".join(sorted(matched["Nick Name"].dropna().unique().tolist())) or "—",
            }
        )
    return pd.DataFrame(rows).sort_values(PROJECT_COL).reset_index(drop=True)


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


def shift_period_label(period_label: str, months: int) -> str:
    """"FY-Period"形式のperiod_labelを、暦月数で`months`分だけ前後にずらす。

    会計年度の期首月が未確認のため、期＝暦1ヶ月・12期で年繰り上げという前提のみを使い、
    暦日付からの厳密な絶対変換は行わない（基点からの相対オフセットとしてのみ使う）。
    """
    fy_str, period_str = period_label.split("-")
    total = int(fy_str) * 12 + (int(period_str) - 1) + months
    new_fy, new_period0 = divmod(total, 12)
    return f"{new_fy}-{new_period0 + 1:02d}"


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


def render_breakdown(
    df: pd.DataFrame,
    group_col: str,
    title: str,
    key: str,
    top_n: int | None = None,
    other_bucket: bool = False,
) -> None:
    """指定軸のコスト内訳を、棒グラフ（既定）と円グラフ（トグルON）で切り替え表示する。

    top_n指定時、other_bucket=Trueなら上位top_n件以外を「その他」として1件に集約する
    （Falseの場合は単純に上位top_n件のみを表示し、それ以外は捨てる＝従来動作）。
    """
    hcol, tcol = st.columns([3, 1])
    hcol.markdown(f"##### {title}")
    st.session_state.setdefault(f"{key}_pie", False)
    as_pie = tcol.toggle("円グラフ", key=f"{key}_pie")

    data = agg_by(df, group_col, top_n=None)
    if data.empty:
        st.caption("表示するデータがありません。")
        return

    if top_n and len(data) > top_n:
        head = data.head(top_n)
        if other_bucket:
            rest_sum = data["Cost"].iloc[top_n:].sum()
            other_row = pd.DataFrame({group_col: ["その他"], "Cost": [rest_sum]})
            data = pd.concat([head, other_row], ignore_index=True)
        else:
            data = head

    if as_pie:
        pos = data[data["Cost"] > 0]
        # dataはCost降順で既に並んでいるので、Plotly側で再ソートさせず(sort=False)、
        # 12時位置から時計回り(direction="clockwise")に大きい順で配置する
        fig = px.pie(pos, names=group_col, values="Cost", hole=0.35)
        fig.update_traces(sort=False, direction="clockwise")
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
    st.caption(
        "※ 列を隠す場合は必ずここで操作してください。テーブル右上の目のアイコン等での列非表示は"
        "Streamlit標準機能のためこちら側の設定と連動しません。"
    )
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

    if not work.empty:
        with st.expander("📊 この明細をグラフ化", expanded=False):
            render_period_bar(work, key_prefix=f"{key}_ts", default_stacked=False)

            viz_options = [c for c in visible_cols if c in DETAIL_FILTER_COLUMNS]
            if viz_options:
                viz_key = f"{key}_viz_axis"
                st.session_state.setdefault(viz_key, viz_options[0])
                if st.session_state[viz_key] not in viz_options:
                    st.session_state[viz_key] = viz_options[0]
                viz_index = viz_options.index(st.session_state[viz_key])
                viz_axis = st.selectbox(
                    "内訳の軸を選択（棒グラフ／円グラフはグラフ側のトグルで切替）",
                    viz_options,
                    index=viz_index,
                    key=f"{viz_key}_widget",
                )
                st.session_state[viz_key] = viz_axis
                n_unique = work[viz_axis].dropna().nunique()

                if n_unique > 5:
                    topn_labels = {"上位20": 20, "上位10": 10, "上位5": 5}
                    st.session_state.setdefault(f"{key}_viz_topn", "上位10")
                    viz_topn_choice = st.radio(
                        "表示件数", list(topn_labels.keys()), horizontal=True, key=f"{key}_viz_topn"
                    )
                    viz_top_n = topn_labels[viz_topn_choice]
                else:
                    viz_top_n = None

                viz_title = f"{viz_axis}別"
                if viz_top_n and n_unique > viz_top_n:
                    viz_title += f"（上位{viz_top_n}＋その他）"
                render_breakdown(
                    work, viz_axis, viz_title, key=f"{key}_viz_breakdown", top_n=viz_top_n, other_bucket=True
                )

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


def render_pipeline_table(df: pd.DataFrame, key: str) -> None:
    """Pipeline明細（フィルタ・並び替え付き）。コスト側render_filterable_tableのPipeline版。"""
    if df.empty:
        st.caption("表示する明細がありません。")
        return

    cols = [c for c in PIPELINE_TABLE_COLUMNS if c in df.columns]
    filter_cols = [c for c in PIPELINE_FILTER_COLUMNS if c in cols]
    with st.expander(f"🔍 フィルタ（{len(df):,}件が対象）", expanded=False):
        picks: dict[str, list] = {}
        for row_start in range(0, len(filter_cols), FILTER_COLUMNS_PER_ROW):
            row = filter_cols[row_start : row_start + FILTER_COLUMNS_PER_ROW]
            st_cols = st.columns(len(row))
            for c, col_name in zip(st_cols, row):
                options = sorted(df[col_name].dropna().unique(), key=str)
                picks[col_name] = c.multiselect(col_name, options, key=f"{key}_filter_{col_name}")

    work = df
    for col_name, picked in picks.items():
        if picked:
            work = work[work[col_name].isin(picked)]

    st.caption(f"表示中: {len(work):,}件")
    disp = work[cols].copy()
    for date_col in ("PAST date", "NEXT date"):
        if date_col in disp.columns:
            disp[date_col] = disp[date_col].apply(lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "—")
    st.dataframe(disp, use_container_width=True, hide_index=True, height=360)

    st.download_button(
        "この明細をExcelでダウンロード",
        data=_to_excel_bytes({"Pipeline明細": disp}),
        file_name="schedule_pipeline_detail.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key}_dl",
    )


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


def render_cost_schedule_overlay(
    sub: pd.DataFrame, pipeline_row: pd.Series, milestone_cols: list[str]
) -> None:
    """コストのバーンチャートに、マイルストーン実績を会計期間換算で重ねた統合グラフ。

    会計年度の期首月が未確認のため、暦日付→period_labelの絶対変換はしない。
    PS（IOオープン日）を基点に「基点からの経過月数」で相対的に位置合わせする
    （SAP会計期間は1期=暦1ヶ月・連番という前提のみを使う）。PSが無いプロジェクトは、
    そのプロジェクトの最初のマイルストーン実績日を基点日付として代用する。
    表示幅トグルはこの関数のローカル表示のみに影響し、`sub`自体は変更しない
    （呼び出し元のプロジェクト深掘りタブ本体の集計・フィルタには影響させない）。
    """
    cost_periods = sorted(sub["period_label"].dropna().unique())
    if not cost_periods:
        return
    first_cost_period = cost_periods[0]

    chart_milestones = [m for m in milestone_cols if m not in MILESTONE_CHART_EXCLUDE]
    ml = milestones_long(pipeline_row, chart_milestones).dropna(subset=["実績日"])

    ps_date = pipeline_row.get("PS")
    if pd.notna(ps_date):
        anchor_date = ps_date
        anchor_label = "PS（IOオープン日）"
    elif not ml.empty:
        anchor_date = ml["実績日"].min()
        anchor_label = "最初のマイルストーン実績日（PS未記録のため代用）"
    else:
        return

    def date_to_period(d: pd.Timestamp) -> str:
        months = (d.year - anchor_date.year) * 12 + (d.month - anchor_date.month)
        return shift_period_label(first_cost_period, months)

    ml = ml.copy()
    ml["period_label"] = ml["実績日"].apply(date_to_period)

    st.markdown("###### コスト×マイルストーン 統合表示（会計年度-期を合わせて表示）")
    st.caption(
        f"基点: {anchor_label} = {anchor_date.strftime('%Y-%m-%d')} を「{first_cost_period}」に"
        "対応づけ、以降は暦1ヶ月=1期として相対的に位置合わせしています"
        "（会計年度の期首月は未確認のため厳密な絶対変換ではありません）。"
    )

    st.session_state.setdefault("proj_overlay_full_width", False)
    full_width = st.toggle(
        "マイルストーンベース表示（最後のマイルストーンまで幅を広げる）", key="proj_overlay_full_width"
    )

    ts = (
        sub.groupby("period_label")[AMOUNT_COL].sum().reset_index().sort_values("period_label")
        .rename(columns={AMOUNT_COL: "月次コスト"})
    )

    if full_width and not ml.empty:
        last_period = max(ml["period_label"].max(), ts["period_label"].max())
        # コスト実績の範囲を超える期は0円のダミー行として追加し、表示幅だけを広げる
        # （`sub`本体・他の集計には一切手を加えない）
        display_periods = sorted({p for p in ts["period_label"]} | {
            p for p in ml["period_label"] if p <= last_period
        })
        ts_disp = pd.DataFrame({"period_label": display_periods}).merge(ts, on="period_label", how="left")
        ts_disp["月次コスト"] = ts_disp["月次コスト"].fillna(0.0)
    else:
        ts_disp = ts.copy()

    ts_disp = ts_disp.sort_values("period_label").reset_index(drop=True)
    ts_disp["累計"] = ts_disp["月次コスト"].cumsum()

    visible_periods = set(ts_disp["period_label"])
    ml_visible = ml[ml["period_label"].isin(visible_periods)]

    fig = go.Figure()
    fig.add_bar(x=ts_disp["period_label"], y=ts_disp["月次コスト"], name="月次コスト")
    fig.add_scatter(x=ts_disp["period_label"], y=ts_disp["累計"], name="累計", mode="lines+markers", yaxis="y2")
    if not ml_visible.empty:
        fig.add_scatter(
            x=ml_visible["period_label"], y=[0] * len(ml_visible), mode="markers+text",
            text=ml_visible["マイルストーン"], textposition="top center",
            marker=dict(size=10, color="#2E7D32"), name="マイルストーン実績",
        )
    fig.update_layout(
        xaxis_title="会計年度-期",
        yaxis=dict(title=f"月次コスト ({CURRENCY})"),
        yaxis2=dict(title=f"累計 ({CURRENCY})", overlaying="y", side="right"),
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig, use_container_width=True, key="proj_overlay_chart")

    hidden = ml[~ml["period_label"].isin(visible_periods)]
    if not full_width and not hidden.empty:
        st.caption("※ 実コスト発生分の範囲外のマイルストーンは非表示です。上のトグルをONにすると表示されます。")


# --------------------------------------------------------------------------- #
# タブ2: プロジェクト深掘り（単一プロジェクト・カルテ）
# --------------------------------------------------------------------------- #
def tab_project(
    df: pd.DataFrame, pipeline_df: pd.DataFrame | None = None, milestone_cols: list[str] | None = None
) -> None:
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

    # コスト×スケジュール統合表示（Pipelineが読み込まれ、SPARC IDで紐付く場合のみ）
    if pipeline_df is not None and milestone_cols is not None and SPARC_ID_COL in sub.columns:
        sparc_ids = sorted(int(i) for i in sub[SPARC_ID_COL].dropna().unique())
        matched = pipeline_df[pipeline_df[SPARC_ID_COL].isin(sparc_ids)] if sparc_ids else pipeline_df.iloc[0:0]
        if not matched.empty:
            if len(matched) > 1:
                st.caption("※ SPARC IDが複数のPipelineレコードに一致したため、先頭の1件を表示しています。")
            render_cost_schedule_overlay(sub, matched.iloc[0], milestone_cols)

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
# タブ4: コスト×スケジュール（Program Pipelineマイルストーン実績）
# --------------------------------------------------------------------------- #
def tab_schedule(cost_df: pd.DataFrame, pipeline_df: pd.DataFrame | None, milestone_cols: list[str] | None) -> None:
    st.markdown("#### 📅 コスト × スケジュール（Program Pipeline マイルストーン実績）")
    st.caption(
        "サイドバーで読み込んだPipelineシートのマイルストーン実績と、KOB1コストデータを"
        "SPARC ID（Pipeline側「SPaRC ID」）で紐付けて概観します。"
    )
    if pipeline_df is None or milestone_cols is None:
        st.info("サイドバーの「プロジェクトスケジュール読み込み」からPipelineシート（Excel）を読み込んでください。")
        return
    if SPARC_ID_COL not in cost_df.columns or cost_df[SPARC_ID_COL].dropna().empty:
        st.warning("KOB1側にSPARC IDのデータがないため、コストとスケジュールを紐付けできません。")
        return

    with st.expander("🔗 紐付け状況サマリー（Project Name別）", expanded=False):
        link_summary = schedule_link_summary(cost_df, pipeline_df)
        n_matched = int((link_summary["Pipeline側 紐付け件数"] > 0).sum())
        st.caption(f"対象スコープの{len(link_summary):,}プロジェクト中、{n_matched:,}件がPipeline側と紐付きました。")
        st.dataframe(link_summary, use_container_width=True, hide_index=True, height=300)

    projects = sorted(cost_df[PROJECT_COL].dropna().unique())
    if not projects:
        st.info("対象スコープにプロジェクトがありません。")
        return
    if st.session_state.get("sch_project") not in projects:
        st.session_state["sch_project"] = projects[0]
    proj_index = projects.index(st.session_state["sch_project"])
    proj = st.selectbox("プロジェクトを選択", projects, index=proj_index, key="sch_project_widget")
    st.session_state["sch_project"] = proj

    sub = cost_df[cost_df[PROJECT_COL] == proj]
    ids = sorted(int(i) for i in sub[SPARC_ID_COL].dropna().unique())
    if not ids:
        st.info(f"「{proj}」にはKOB1側のSPARC IDが記録されていないため、スケジュールと紐付けできません。")
        return

    matched = pipeline_df[pipeline_df[SPARC_ID_COL].isin(ids)].reset_index(drop=True)
    if matched.empty:
        st.warning(f"SPARC ID（{', '.join(str(i) for i in ids)}）に一致するPipelineレコードが見つかりませんでした。")
        return

    if len(matched) > 1:
        current_ids = matched[SPARC_ID_COL].tolist()
        labels = [f"{r['Nick Name']}（SPARC ID: {r[SPARC_ID_COL]}）" for _, r in matched.iterrows()]
        st.session_state.setdefault("sch_sparc_id", int(current_ids[0]))
        if st.session_state["sch_sparc_id"] not in current_ids:
            st.session_state["sch_sparc_id"] = int(current_ids[0])
        picked_idx = current_ids.index(st.session_state["sch_sparc_id"])
        label = st.selectbox(
            "複数のPipelineレコードが見つかりました。表示するレコードを選択", labels, index=picked_idx, key="sch_sparc_id_widget"
        )
        picked_idx = labels.index(label)
        st.session_state["sch_sparc_id"] = int(matched.iloc[picked_idx][SPARC_ID_COL])
        row = matched.iloc[picked_idx]
    else:
        row = matched.iloc[0]

    st.markdown(f"##### 🧭 {row['Nick Name']}（Project ID: {row['Project ID']} ／ SPARC ID: {row[SPARC_ID_COL]}）")
    st.caption(f"PM（Pipeline側）: {row['PM'] or '—'} ／ Type: {row['Type'] or '—'} ／ Track: {row['Track'] or '—'}")

    st.markdown("###### マイルストーン実績（カレンダー日付）とコスト推移（会計年度-期）の対比")
    ml = milestones_long(row, milestone_cols)
    # 優先順位の低いサブマイルストーンはコストと重ねる時系列図からは除外する（一覧テーブルのmlは全件のまま）
    chart_milestones = [m for m in milestone_cols if m not in MILESTONE_CHART_EXCLUDE]
    achieved = ml[ml["マイルストーン"].isin(chart_milestones)].dropna(subset=["実績日"]).sort_values("実績日")
    if achieved.empty:
        st.caption("実績日が記録されているマイルストーンがありません。")
    else:
        fig_ms = go.Figure()
        fig_ms.add_scatter(
            x=achieved["実績日"], y=[0] * len(achieved), mode="markers+text",
            text=achieved["マイルストーン"], textposition="top center",
            marker=dict(size=10, color="#2E7D32"), name="達成済み",
        )
        fig_ms.add_vline(x=pd.Timestamp.now(), line_dash="dot", line_color="gray", annotation_text="本日")
        fig_ms.update_yaxes(visible=False, range=[-1, 1])
        fig_ms.update_layout(xaxis_title="マイルストーン実績日", height=220, showlegend=True)
        st.plotly_chart(fig_ms, use_container_width=True, key="sch_timeline_chart")

    ts = (
        sub.groupby("period_label")[AMOUNT_COL].sum().reset_index().sort_values("period_label")
        .rename(columns={AMOUNT_COL: "月次コスト"})
    )
    ts["累計"] = ts["月次コスト"].cumsum()
    fig_cost = go.Figure()
    fig_cost.add_bar(x=ts["period_label"], y=ts["月次コスト"], name="月次コスト")
    fig_cost.add_scatter(x=ts["period_label"], y=ts["累計"], name="累計", mode="lines+markers", yaxis="y2")
    fig_cost.update_layout(
        xaxis_title="会計年度-期",
        yaxis=dict(title=f"月次コスト ({CURRENCY})"),
        yaxis2=dict(title=f"累計 ({CURRENCY})", overlaying="y", side="right"),
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig_cost, use_container_width=True, key="sch_cost_chart")
    st.caption(
        "※ マイルストーン実績（カレンダー日付）とコスト推移（会計年度-期）は軸の単位が異なります"
        "（会計年度の期首月が未確認のため、暦日付への厳密な換算は行っていません）。両者を並べて"
        "概観する用途としてご利用ください。"
    )

    st.markdown("###### マイルストーン一覧")
    ml_disp = ml.copy()
    ml_disp["実績日"] = ml_disp["実績日"].apply(lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "未達成")
    ml_disp["達成"] = ml_disp["達成"].map({True: "✅", False: "—"})
    st.dataframe(ml_disp, use_container_width=True, hide_index=True, height=300)

    st.markdown("#### Pipeline明細一覧（全件）")
    st.caption("紐付け元プロジェクトを問わず、読み込んだPipelineシート全体を確認できます。")
    render_pipeline_table(pipeline_df, key="sch_all")


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

    # --- サイドバー: プロジェクトスケジュール（Program Pipelineシート）読み込み ---
    st.sidebar.header("プロジェクトスケジュール読み込み")
    st.sidebar.caption("現在対応形式: Pipelineシート（Excel、シート名 `data_*`）")
    sch_uploaded = st.sidebar.file_uploader(
        "Pipelineシートを含むExcelファイル (.xlsx)", type=["xlsx", "xlsm"], key="sch_uploader"
    )
    st.sidebar.text_input("またはローカルパスを指定", key="s_schedule_path")
    sch_source = sch_uploaded if sch_uploaded is not None else st.session_state["s_schedule_path"]

    pipeline_df, milestone_cols = None, None
    if sch_source and (not isinstance(sch_source, str) or Path(sch_source).exists()):
        try:
            sch_sheets = find_pipeline_sheets(sch_source)
            if not sch_sheets:
                st.sidebar.warning(f'"{PIPELINE_SHEET_PREFIX}"で始まるシートが見つかりません。')
            else:
                sch_sheet = sch_sheets[0]
                if len(sch_sheets) > 1:
                    sch_sheet = st.sidebar.selectbox("スケジュールのシート（最新が先頭）", sch_sheets, key="sch_sheet_pick")
                sch_key = _cache_key_for_source(sch_source)
                pipeline_df, milestone_cols = _load_pipeline_cached(sch_source, sch_sheet, sch_key)
                st.sidebar.caption(f"✅ 「{sch_sheet}」を読み込みました（{len(pipeline_df):,}件、マイルストーン{len(milestone_cols)}種）")
        except ValueError as exc:
            st.sidebar.warning(f"スケジュールの読み込みに失敗しました: {exc}")
    elif sch_source:
        st.sidebar.warning(f"ファイルが見つかりません: {sch_source}")

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
    t1, t2, t3, t4 = st.tabs(["🏛 事業部俯瞰", "🧭 プロジェクト深掘り", "🔧 ファンクション横断", "📅 コスト×スケジュール"])
    with t1:
        tab_portfolio(filtered, default_stacked=st.session_state.get("pf_stacked", False))
    with t2:
        tab_project(filtered, pipeline_df, milestone_cols)
    with t3:
        tab_function(filtered)
    with t4:
        tab_schedule(filtered, pipeline_df, milestone_cols)

    # 設定を保存（タブ内の選択・トグルも含めて確定した後に保存し、次回起動時に復元する）
    save_settings({k: st.session_state.get(k, default) for k, default in SETTINGS_DEFAULTS.items()})


if __name__ == "__main__":
    main()
