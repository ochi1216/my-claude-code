# -*- coding: utf-8 -*-
"""analog_ic_se_strategy_organizer 統合ダッシュボード v20260717_02

タブ構成:
  📦 製品登録・検索   … 型番からステージ0(製品取り込み)を実行して登録、既存ケースライブラリの検索
  📊 ポートフォリオ俯瞰 … 蓄積製品を横断した俯瞰分析（ホワイトスペース分析・カテゴリ分布・競合ギャップ・AI総評）
  🎯 製品ディープダイブ … 型番を入力→5ステージ一気通貫でHTMLレポートを生成

起動: streamlit run analog_ic_se_strategy_organizer_20260717_02.py

DESIGN_analog_ic_se_strategy_organizer.md 9章の設計に基づく実装。

本ツールは越智さん(Nexperia所属)が、TIをベンチマーク対象として対抗デバイスの企画・
将来ロードマップを検討するためのもの（config/own_company.json参照）。

v20260717_01での変更点（実機検証で判明したバグ修正）:
  - ポートフォリオ俯瞰タブで、登録済み製品に競合IC比較データが1件も無い場合
    （「ステージ0のみ実行」で登録した直後など）に
    `KeyError: '競合優位点の総数'` で画面が落ちる不具合を修正。
    空DataFrameへの列参照sort_values()を、空チェックの後に実行するよう順序を修正

v20260717_02での変更点（MECE改善検討の優先度1）:
  - 📊ポートフォリオ俯瞰タブに「🕳️ ホワイトスペース分析」セクションを追加。
    competitors_db.jsonの集計のみ（LLM呼び出し・追加コストなし）で、
    カテゴリ別の手薄度・車載クロスの手薄度・最も手薄な地域・自社(Nexperia)の
    現状ポジションを算出して可視化する（ic_schema.whitespace_analysis()）
"""

import os
import platform
import subprocess
from collections import Counter

import pandas as pd
import streamlit as st

import ic_schema
import ic_index
import ic_engine
import ic_report

# ---------------------------------------------------------
# 1. 初期設定とパス定義
# ---------------------------------------------------------
st.set_page_config(page_title="Analog IC SE Strategy Organizer", page_icon="🔬", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
IC_REPORTS_DIR = os.path.join(DATA_DIR, "ic_reports")
PORTFOLIO_COMMENTARY_PATH = os.path.join(DATA_DIR, "portfolio_commentary.json")

CATEGORY_SCHEMA = ic_schema.load_category_schema()
CATEGORY_OPTIONS = [(None, "（自動判定）")] + [
    (key, cat.get("label", key)) for key, cat in CATEGORY_SCHEMA.get("categories", {}).items()
]
CATEGORY_LABELS = {key: cat.get("label", key) for key, cat in CATEGORY_SCHEMA.get("categories", {}).items()}
CATEGORY_LABELS[ic_schema.GENERIC_CATEGORY_KEY] = ic_schema.GENERIC_CATEGORY["label"]


# ---------------------------------------------------------
# 2. データ読み込み（インデックス経由・キャッシュ）
# ---------------------------------------------------------
@st.cache_data
def load_ic_data():
    """ic_index.jsonを増分構築し、DataFrame化して返す"""
    index = ic_index.build_index(data_dir=DATA_DIR)
    records = index.get("records", [])
    rows = []
    for r in records:
        status = r.get("stage_status", {})
        done_count = sum(1 for v in status.values() if v == "done")
        rows.append({
            "型番": r["part_number"],
            "カテゴリ": CATEGORY_LABELS.get(r["category"], r["category"]),
            "_category_key": r["category"],
            "メーカー": r["manufacturer"],
            "主要アプリケーション": ", ".join(r.get("applications", [])[:2]),
            "解析日時": r.get("analyzed_at", ""),
            "ステージ完了": f"{done_count}/5",
            "_stage_status": status,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("解析日時", ascending=False).reset_index(drop=True)
    return df, index.get("built_at", ""), records


@st.cache_data
def load_portfolio_details(built_at):
    """ポートフォリオ俯瞰タブ用: 全製品のフルJSONを読み込む（built_atが変わるまでキャッシュ）"""
    index = ic_index.load_index(data_dir=DATA_DIR)
    details = []
    for r in index.get("records", []):
        full = ic_index.load_full_case(r["part_number"], data_dir=DATA_DIR)
        if full:
            details.append(full)
    return details


def open_local_file(filepath):
    """OSに応じてローカルファイルを開く"""
    if not os.path.exists(filepath):
        st.toast(f"⚠️ ファイルが見つかりません: {os.path.basename(filepath)}", icon="❌")
        return
    try:
        if platform.system() == "Windows":
            os.startfile(filepath)
        elif platform.system() == "Darwin":
            subprocess.call(("open", filepath))
        else:
            subprocess.call(("xdg-open", filepath))
        st.toast(f"✅ 開きました: {os.path.basename(filepath)}", icon="🚀")
    except Exception as e:
        st.error(f"ファイルを開けませんでした: {e}")


def run_and_save(part_number, category_hint, deep, competitor_mode, only_stage0=False):
    """パイプラインを実行し、product_lakeに保存する。結果dictを返す"""
    status_area = st.status("パイプラインを実行中...", expanded=True)

    def progress(key, label, state):
        if state == "start":
            status_area.write(f"⏳ {label} ...")
        elif state == "done":
            status_area.write(f"✅ {label} 完了")
        elif state == "error":
            status_area.write(f"❌ {label} 失敗（続行します）")

    engine = ic_engine.IcPipeline(deep=deep, data_dir=DATA_DIR, progress_cb=progress,
                                   competitor_mode=competitor_mode)
    result = engine.run_pipeline(part_number, category_hint=category_hint, only_stage0=only_stage0)
    ic_index.save_product_case(result, data_dir=DATA_DIR)
    status_area.update(label="✅ 完了", state="complete")
    st.cache_data.clear()
    return result


# ---------------------------------------------------------
# 3. メインUI
# ---------------------------------------------------------
st.title("🔬 Analog IC SE Strategy Organizer")
st.caption("TI製品を型番1つから、市場分析・キーカスタマー推定・競合IC比較・次世代スペック提案まで一気通貫でまとめるツール")

if not os.getenv("GEMINI_API_KEY"):
    st.warning("⚠️ 環境変数 GEMINI_API_KEY が設定されていません。設定後にアプリを再起動してください。")

df, built_at, records = load_ic_data()
competitors_summary = ic_schema.competitors_summary()

col_info, col_btn = st.columns([4, 1])
with col_info:
    st.caption(f"分析済み製品: {len(df)} 件（インデックス更新: {built_at[:19] if built_at else '—'}）／"
               f"競合企業DB: {competitors_summary['total_companies']} 社（確認日: {competitors_summary['as_of']}）")
with col_btn:
    if st.button("🔄 インデックス再構築"):
        ic_index.build_index(data_dir=DATA_DIR, force=True)
        st.cache_data.clear()
        st.rerun()

tab_register, tab_portfolio, tab_deepdive = st.tabs(["📦 製品登録・検索", "📊 ポートフォリオ俯瞰", "🎯 製品ディープダイブ"])

# =========================================================
# タブ1: 製品登録・検索
# =========================================================
with tab_register:
    st.markdown("### ➕ 新規製品登録（ステージ0のみ）")
    st.caption("型番を入力してカテゴリ・主要仕様を軽量に確認します。フル解析は🎯製品ディープダイブタブで実行してください。")

    col_in, col_cat = st.columns([2, 1])
    with col_in:
        reg_part_number = st.text_input("型番", placeholder="例: TPS62840", key="reg_part_number")
    with col_cat:
        reg_category = st.selectbox("カテゴリ（手動指定、任意）", CATEGORY_OPTIONS,
                                     format_func=lambda x: x[1], key="reg_category")[0]

    if st.button("▶️ ステージ0のみ実行", disabled=not reg_part_number, key="btn_stage0"):
        result = run_and_save(reg_part_number, reg_category, deep=False,
                               competitor_mode="normal", only_stage0=True)
        s0 = result.get("content", {}).get("stage0_product", {})
        if "error" in s0:
            st.error(f"ステージ0が失敗しました: {s0['error']}")
            st.info("カテゴリを手動選択のうえ、再度実行してください。")
        else:
            cat_key = result["classifiers"]["category"]
            st.success(f"登録完了: {reg_part_number} （カテゴリ: {CATEGORY_LABELS.get(cat_key, cat_key)}）")

    st.markdown("---")
    st.markdown("### 🔍 検索・フィルター")
    col1, col2 = st.columns([2, 1])
    with col1:
        search_query = st.text_input("型番 または アプリケーションで検索",
                                      placeholder="例: TPS, IoT, Battery", key="search_query")
    with col2:
        cat_filter_options = ["すべて"] + sorted(df["カテゴリ"].unique().tolist()) if not df.empty else ["すべて"]
        selected_category = st.selectbox("カテゴリフィルター", cat_filter_options)

    filtered_df = df.copy()
    if not filtered_df.empty:
        if search_query:
            mask = (filtered_df["型番"].str.contains(search_query, case=False, na=False) |
                    filtered_df["主要アプリケーション"].str.contains(search_query, case=False, na=False))
            filtered_df = filtered_df[mask]
        if selected_category != "すべて":
            filtered_df = filtered_df[filtered_df["カテゴリ"] == selected_category]

    st.markdown(f"**該当件数: {len(filtered_df)} 件**")
    if filtered_df.empty:
        st.info("分析済み製品がまだありません。上の「ステージ0のみ実行」または🎯製品ディープダイブタブから登録してください。")
    else:
        display_cols = ["型番", "カテゴリ", "メーカー", "主要アプリケーション", "解析日時", "ステージ完了"]
        st.dataframe(filtered_df[display_cols], width="stretch", hide_index=True)

# =========================================================
# タブ2: ポートフォリオ俯瞰
# =========================================================
with tab_portfolio:
    st.markdown("### 🏢 競合企業データベースの概況")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 地域別 競合企業数")
        region_df = pd.DataFrame(
            [{"地域": k, "社数": v} for k, v in competitors_summary["region_counts"].items()])
        if not region_df.empty:
            import plotly.express as px
            fig_region = px.pie(region_df, values="社数", names="地域", hole=0.4)
            fig_region.update_layout(height=340)
            st.plotly_chart(fig_region, width="stretch")
    with col_b:
        st.markdown("#### カテゴリ別 主要(●)/限定(△)企業数")
        cat_rows = []
        for key, counts in competitors_summary["category_counts"].items():
            cat_rows.append({"カテゴリ": CATEGORY_LABELS.get(key, key), "主要(●)": counts["primary"],
                              "限定(△)": counts["limited"]})
        cat_df = pd.DataFrame(cat_rows)
        if not cat_df.empty:
            import plotly.express as px
            fig_cat = px.bar(cat_df, x="カテゴリ", y=["主要(●)", "限定(△)"], barmode="stack")
            fig_cat.update_layout(height=340, xaxis_tickangle=-30)
            st.plotly_chart(fig_cat, width="stretch")

    st.markdown("---")

    st.markdown("### 🕳️ ホワイトスペース分析（競合データのみで算出、追加コストなし）")
    own_name = ic_schema.own_company_name()
    st.caption(
        "各カテゴリの「主要(●)/限定(△)企業の少なさ」を手薄度として算出しています。値が高いほど、"
        "まだ本気で作っている競合が少なく企画の余地が大きいカテゴリです。「手薄度(車載限定)」は、"
        "そのカテゴリの主要/限定企業のうち車載対応企業が占める割合の低さ（＝車載版だけが手薄）を示します。"
        + (f" 自社（{own_name}）の現状ポジションも併記します。" if own_name else ""))

    ws_results = ic_schema.whitespace_analysis()
    OWN_STATUS_LABELS = {"primary": "● 主要プレイヤー", "limited": "△ 限定的", "none": "— 未参入"}
    ws_df = pd.DataFrame([{
        "カテゴリ": r["label"],
        "手薄度(全体)": r["whitespace_score"],
        "手薄度(車載限定)": r["automotive_whitespace_score"],
        "主要(●)": r["primary_count"],
        "限定(△)": r["limited_count"],
        "未確認(—)": r["none_count"],
        "最も手薄な地域": r["weakest_region"],
        "自社の現状": (OWN_STATUS_LABELS.get(r["own_company_status"], "—")
                    if r["own_company_status"] is not None else "（自社未設定）"),
    } for r in ws_results])

    col_ws1, col_ws2 = st.columns([3, 2])
    with col_ws1:
        import plotly.express as px
        fig_ws = px.bar(ws_df, x="カテゴリ", y=["手薄度(全体)", "手薄度(車載限定)"], barmode="group")
        fig_ws.update_layout(height=380, xaxis_tickangle=-30, yaxis_title="手薄度スコア(0〜1)")
        st.plotly_chart(fig_ws, width="stretch")
    with col_ws2:
        st.dataframe(ws_df, width="stretch", hide_index=True)

    st.markdown("#### 💡 企画優先度の高い候補（手薄度上位5カテゴリ）")
    priority_lines = []
    for r in ws_results[:5]:
        status = r["own_company_status"]
        if status == "none":
            tag = "★新規参入候補（自社未参入・市場全体も手薄）"
        elif status == "limited":
            tag = "▲拡張候補（自社は限定的関与・市場全体も手薄）"
        elif status == "primary":
            tag = "◎独走候補（自社は既に主要プレイヤー・先行者優位を活かせる）"
        else:
            tag = "（自社ポジション未設定。config/own_company.jsonを確認してください）"
        priority_lines.append(f"- **{r['label']}**（手薄度 {r['whitespace_score']:.2f}）: {tag}")
    st.markdown("\n".join(priority_lines))

    st.markdown("---")

    if df.empty:
        st.info("分析済み製品がまだないため、製品ポートフォリオの俯瞰はまだ表示できません。"
                 "📦製品登録・検索タブまたは🎯製品ディープダイブタブから製品を登録してください。")
    else:
        details = load_portfolio_details(built_at)

        st.markdown("### 📦 分析済み製品ポートフォリオ")
        col_c, col_d = st.columns(2)

        with col_c:
            st.markdown("#### カテゴリ別 製品登録数")
            cat_counts = Counter(CATEGORY_LABELS.get(r["category"], r["category"]) for r in records)
            cat_count_df = pd.DataFrame(cat_counts.most_common(), columns=["カテゴリ", "件数"])
            if not cat_count_df.empty:
                import plotly.express as px
                fig_pc = px.bar(cat_count_df, x="カテゴリ", y="件数")
                fig_pc.update_layout(height=340, xaxis_tickangle=-30)
                st.plotly_chart(fig_pc, width="stretch")

        with col_d:
            st.markdown("#### 次世代スペック提案の優先度分布")
            priority_counts = Counter()
            for d in details:
                s4 = d.get("content", {}).get("stage4_next_gen_proposal", {})
                for spec in (s4.get("proposed_specs", []) if isinstance(s4, dict) else []):
                    priority_counts[spec.get("priority", "不明")] += 1
            pr_df = pd.DataFrame(priority_counts.most_common(), columns=["優先度", "件数"])
            if not pr_df.empty:
                import plotly.express as px
                fig_pr = px.bar(pr_df, x="優先度", y="件数")
                fig_pr.update_layout(height=340)
                st.plotly_chart(fig_pr, width="stretch")
            else:
                st.info("次世代スペック提案データがまだありません。")

        st.markdown("#### ⚔️ 競合ギャップが大きい製品ランキング")
        gap_rows = []
        for d in details:
            part_number = d.get("metadata", {}).get("part_number", "")
            s3 = d.get("content", {}).get("stage3_competitors", {})
            competitors = s3.get("competitors", []) if isinstance(s3, dict) else []
            gap_count = sum(len(c.get("gap_vs_ti", {}).get("advantages_of_competitor", []))
                             for c in competitors if c.get("lookup_status") != "error")
            if competitors:
                gap_rows.append({"型番": part_number, "競合優位点の総数": gap_count,
                                  "比較対象企業数": len(competitors)})
        gap_df = pd.DataFrame(gap_rows)
        if not gap_df.empty:
            gap_df = gap_df.sort_values("競合優位点の総数", ascending=False)
            st.dataframe(gap_df, width="stretch", hide_index=True)
        else:
            st.info("競合IC比較データがまだありません（「ステージ0のみ実行」で登録した製品は"
                     "競合IC比較を行っていないため対象外です。🎯製品ディープダイブタブでフル解析すると表示されます）。")

        # --- AI俯瞰総評 ---
        st.markdown("---")
        st.markdown("### 🤖 AI俯瞰総評（分析済み製品と競合DBを一括でGeminiに読ませた講評）")

        import json as _json
        cached = None
        if os.path.exists(PORTFOLIO_COMMENTARY_PATH):
            try:
                with open(PORTFOLIO_COMMENTARY_PATH, "r", encoding="utf-8") as f:
                    cached = _json.load(f)
            except Exception:
                cached = None

        is_fresh = cached and cached.get("built_at") == built_at
        if cached:
            freshness = "（最新のインデックスに基づく）" if is_fresh else "（⚠️ インデックス更新後に再生成推奨）"
            st.caption(f"生成日時: {cached.get('generated_at', '')[:19]} / "
                       f"コスト: 約{cached.get('cost_jpy', 0)}円 {freshness}")
            st.markdown(cached.get("markdown", ""))

        btn_label = "🔁 総評を再生成する" if cached else "▶️ 総評を生成する"
        if st.button(btn_label, key="btn_commentary"):
            if not os.getenv("GEMINI_API_KEY"):
                st.error("環境変数 GEMINI_API_KEY が設定されていません。")
            else:
                with st.spinner("Geminiが全ケースを俯瞰しています..."):
                    try:
                        from datetime import datetime
                        md, cost = ic_engine.generate_portfolio_commentary(records, competitors_summary)
                        os.makedirs(DATA_DIR, exist_ok=True)
                        with open(PORTFOLIO_COMMENTARY_PATH, "w", encoding="utf-8") as f:
                            _json.dump({"built_at": built_at, "markdown": md, "cost_jpy": cost,
                                        "generated_at": datetime.now().isoformat()},
                                       f, ensure_ascii=False, indent=1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"総評の生成に失敗しました: {e}")

# =========================================================
# タブ3: 製品ディープダイブ（一気通貫パイプライン）
# =========================================================
with tab_deepdive:
    st.markdown("### 🎯 一気通貫 TI製品競合分析")
    st.caption("型番を入力すると、製品取り込み→市場分析→キーカスタマー推定→競合IC比較→次世代スペック提案まで自動実行し、"
               "HTMLレポートを生成します。")

    col_in, col_cat2, col_mode = st.columns([2, 1, 1])
    with col_in:
        deep_part_number = st.text_input("分析対象の型番", placeholder="例: TPS62840", key="deep_part_number")
    with col_cat2:
        deep_category = st.selectbox("カテゴリ（手動指定、任意）", CATEGORY_OPTIONS,
                                      format_func=lambda x: x[1], key="deep_category")[0]
    with col_mode:
        deep_mode = st.radio("分析モード", ["通常（flash）", "ディープ（pro）"], index=0, key="deep_mode")

    competitor_mode_label = st.radio(
        "競合IC比較の範囲",
        ["通常モード（地域代表1社ずつ、計4社程度）", "フルモード（該当カテゴリの主要/限定 全社）"],
        index=0, key="competitor_mode_label")
    competitor_mode = "full" if competitor_mode_label.startswith("フル") else "normal"

    if not os.getenv("GEMINI_API_KEY"):
        st.warning("⚠️ 環境変数 GEMINI_API_KEY が設定されていません。設定後に再起動してください。")

    if st.button("🚀 分析を実行", type="primary", disabled=not deep_part_number, key="btn_run_deepdive"):
        deep = deep_mode.startswith("ディープ")
        result = run_and_save(deep_part_number, deep_category, deep=deep,
                               competitor_mode=competitor_mode, only_stage0=False)
        report_path = ic_report.generate_ic_report(result, out_dir=IC_REPORTS_DIR)
        st.session_state["last_result"] = result
        st.session_state["last_report"] = report_path

    # --- 結果表示 ---
    if "last_result" in st.session_state:
        result = st.session_state["last_result"]
        report_path = st.session_state.get("last_report", "")
        costs = result.get("costs", {})
        meta = result.get("metadata", {})

        st.markdown("---")
        st.markdown(f"#### 📄 レポート: {os.path.basename(report_path)}")
        st.caption(f"💰 コスト: ${costs.get('total_usd', 0):.4f}（約 {costs.get('total_jpy', 0):.2f} 円） / "
                   f"モデル: {meta.get('model')} / ステージ状況: {meta.get('stage_status')}")

        s4 = result.get("content", {}).get("stage4_next_gen_proposal", {})
        if isinstance(s4, dict) and s4.get("executive_summary"):
            st.info(f"**エグゼクティブサマリー**\n\n{s4['executive_summary']}")
            for spec in s4.get("proposed_specs", [])[:3]:
                st.markdown(f"**{spec.get('kpi', '')}**（優先度: {spec.get('priority', '')}）: "
                             f"{spec.get('current_ti_value', '')} → {spec.get('target_value', '')}")

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            if st.button("🌐 レポートを開く", width="stretch", key="btn_open_report"):
                open_local_file(report_path)
        with col_r2:
            if report_path and os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    st.download_button("💾 レポートをダウンロード", f.read(),
                                        file_name=os.path.basename(report_path),
                                        mime="text/html", width="stretch")
