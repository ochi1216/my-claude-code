# -*- coding: utf-8 -*-
"""RTOCS 統合マネジメントダッシュボード v20260715_05

タブ構成:
  📋 一覧・検索   … 従来機能（検索・絞り込み・HTML/PDFを開く）
  📈 傾向分析     … 全RTOCS俯瞰（業界×年、キーワード変遷、AI俯瞰総評 ほか）
  🎯 戦略分析     … 企業名を入力→9ステージ一気通貫の戦略レポートHTML生成

起動: streamlit run rtocs_dashboard_20260715_05.py

v05での変更点（strategy_engine.py / strategy_prompts.py / strategy_report.pyの更新に対応）:
  - 「アナリスト洞察・経営陣メッセージ収集」ステージを追加（会社分析→直近ニュースの直後、
    全体で8→9ステージに）。セルサイドアナリストのレーティング変更理由、決算説明会・
    投資家向け説明会でのマネジメント自身の発言、市場評価と自己認識のギャップをGoogle Search
    Groundingで検索・要約する。株価データだけでなく市場参加者の解釈を戦略提言に反映する
    ための第一歩（改善構想「5軸MECE整理」の軸1-①に対応）
"""

import os
import json
import glob
import platform
import subprocess
from collections import Counter

import pandas as pd
import streamlit as st

import rtocs_index
import strategy_engine
import strategy_report

# ---------------------------------------------------------
# 1. 初期設定とパス定義
# ---------------------------------------------------------
st.set_page_config(page_title="RTOCS Management", page_icon="🏢", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
HTML_DIR = os.path.join(DATA_DIR, "HTML_report")
RTOCS_PDF_DIR = os.path.join(DATA_DIR, "RTOCS_pdf")
COMMENTARY_PATH = os.path.join(DATA_DIR, "trend_commentary.json")


# ---------------------------------------------------------
# 2. データ読み込み（インデックス経由・キャッシュ）
# ---------------------------------------------------------
@st.cache_data
def load_rtocs_data():
    """rtocs_index.jsonを増分構築し、DataFrame化して返す"""
    index = rtocs_index.build_index(data_dir=DATA_DIR)
    records = index.get("records", [])

    html_files = os.listdir(HTML_DIR) if os.path.exists(HTML_DIR) else []
    pdf_files = os.listdir(RTOCS_PDF_DIR) if os.path.exists(RTOCS_PDF_DIR) else []

    rows = []
    for r in records:
        rows.append({
            "ID": r["video_id"],
            "回数": r["episode"],
            "日付": r["date"],
            "年": r["date"][:4] if len(r.get("date", "")) >= 4 else "不明",
            "企業名": r["company"],
            "業界": r["sector"],
            "サブ業界": r["niche"],
            "キーワード": ", ".join(r.get("keywords", [])),
            "_keywords": r.get("keywords", []),
            "_regions": r.get("regions", []),
            "HTMLあり": any(str(r["episode"]) in f for f in html_files) if r["episode"] else False,
            "PDFあり": any(f"_{r['video_id']}_" in f for f in pdf_files),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("日付", ascending=False).reset_index(drop=True)
    return df, index.get("built_at", ""), records


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


# ---------------------------------------------------------
# 3. メインUI
# ---------------------------------------------------------
st.title("🏢 RTOCS 統合マネジメントダッシュボード")

df, built_at, records = load_rtocs_data()

col_info, col_btn = st.columns([4, 1])
with col_info:
    st.caption(f"ケースライブラリ: {len(df)} 件（インデックス更新: {built_at[:19] if built_at else '—'}）")
with col_btn:
    if st.button("🔄 インデックス再構築"):
        rtocs_index.build_index(data_dir=DATA_DIR, force=True)
        st.cache_data.clear()
        st.rerun()

if df.empty:
    st.warning(f"データが見つかりません。先にスクレイピングを実行して data/JSON_lake にJSONを保存してください。")
    st.stop()

tab_list, tab_trend, tab_strategy = st.tabs(["📋 一覧・検索", "📈 傾向分析", "🎯 戦略分析"])

# =========================================================
# タブ1: 一覧・検索（従来機能）
# =========================================================
with tab_list:
    st.markdown("### 🔍 検索・フィルター")
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        search_query = st.text_input("企業名 または キーワードで検索", placeholder="例: トヨタ, AI, 構造改革")
    with col2:
        industry_options = ["すべて"] + sorted(df["業界"].unique().tolist())
        selected_industry = st.selectbox("業界フィルター", industry_options)
    with col3:
        st.write("ステータス絞り込み")
        req_html = st.checkbox("HTMLありのみ")
        req_pdf = st.checkbox("PDFありのみ")

    filtered_df = df.copy()
    if search_query:
        mask = filtered_df["企業名"].str.contains(search_query, case=False, na=False) | \
               filtered_df["キーワード"].str.contains(search_query, case=False, na=False)
        filtered_df = filtered_df[mask]
    if selected_industry != "すべて":
        filtered_df = filtered_df[filtered_df["業界"] == selected_industry]
    if req_html:
        filtered_df = filtered_df[filtered_df["HTMLあり"]]
    if req_pdf:
        filtered_df = filtered_df[filtered_df["PDFあり"]]

    st.markdown(f"**該当件数: {len(filtered_df)} 件**")
    display_cols = ["回数", "日付", "企業名", "業界", "サブ業界", "キーワード", "HTMLあり", "PDFあり"]
    st.dataframe(filtered_df[display_cols], width='stretch', hide_index=True)

    st.markdown("---")
    st.markdown("### 📂 ファイルを開く (ローカルアプリ連携)")
    if not filtered_df.empty:
        action_options = filtered_df.apply(
            lambda row: f"{row['回数']}回 - {row['企業名']} (ID:{row['ID']})", axis=1).tolist()
        selected_action = st.selectbox("対象企業を選択してください", action_options, key="action_selector")
        selected_id = selected_action.split("(ID:")[1].replace(")", "")
        row_data = filtered_df[filtered_df["ID"] == selected_id].iloc[0]

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🌐 HTMLレポートを開く", width='stretch',
                         disabled=not row_data["HTMLあり"], key="btn_open_html"):
                html_files = glob.glob(os.path.join(HTML_DIR, f"*{row_data['回数']}*.html"))
                if html_files:
                    open_local_file(html_files[0])
                else:
                    st.error("HTMLファイルの実体が見つかりません。")
        with col_btn2:
            if st.button("📑 RTOCS PDFを開く", width='stretch',
                         disabled=not row_data["PDFあり"], key="btn_open_pdf"):
                pdf_files = glob.glob(os.path.join(RTOCS_PDF_DIR, f"*_{selected_id}_*.pdf"))
                if pdf_files:
                    open_local_file(pdf_files[0])
                else:
                    st.error("PDFファイルの実体が見つかりません。")

# =========================================================
# タブ2: 傾向分析（俯瞰）
# =========================================================
with tab_trend:
    import plotly.express as px

    # --- 1. 業界分布 × 年 ---
    st.markdown("### 🏭 業界分布の年次推移")
    sector_year = df.groupby(["年", "業界"]).size().reset_index(name="件数")
    fig1 = px.bar(sector_year, x="年", y="件数", color="業界", barmode="stack")
    fig1.update_layout(height=420, legend=dict(font=dict(size=10)))
    st.plotly_chart(fig1, width='stretch')

    col_a, col_b = st.columns(2)

    # --- 2. キーワード頻度 top-20（年セレクタ付き） ---
    with col_a:
        st.markdown("### 🔑 キーワード頻度 Top20")
        year_options = ["全期間"] + sorted(df["年"].unique().tolist(), reverse=True)
        kw_year = st.selectbox("対象期間", year_options, key="kw_year")
        kw_df = df if kw_year == "全期間" else df[df["年"] == kw_year]
        kw_counts = Counter(kw for kws in kw_df["_keywords"] for kw in kws)
        top_kw = pd.DataFrame(kw_counts.most_common(20), columns=["キーワード", "件数"])
        if not top_kw.empty:
            fig2 = px.bar(top_kw.sort_values("件数"), x="件数", y="キーワード", orientation="h")
            fig2.update_layout(height=520)
            st.plotly_chart(fig2, width='stretch')
        else:
            st.info("キーワードデータがありません。")

    # --- 3. 地域ミックス ---
    with col_b:
        st.markdown("### 🌏 地域ミックス")
        region_counts = Counter(r for regs in df["_regions"] for r in regs)
        region_df = pd.DataFrame(region_counts.most_common(), columns=["地域", "件数"])
        if not region_df.empty:
            fig3 = px.pie(region_df, values="件数", names="地域", hole=0.4)
            fig3.update_layout(height=380)
            st.plotly_chart(fig3, width='stretch')
        else:
            st.info("地域データがありません。")

        # --- 4. 企業再訪テーブル ---
        st.markdown("### 🔁 複数回取り上げられた企業")
        revisit = df.groupby("企業名").agg(回数=("ID", "count"),
                                           取り上げ日=("日付", lambda s: ", ".join(sorted(s)))).reset_index()
        revisit = revisit[revisit["回数"] >= 2].sort_values("回数", ascending=False)
        if not revisit.empty:
            st.dataframe(revisit, width='stretch', hide_index=True)
        else:
            st.info("複数回登場した企業はありません。")

    # --- 5. キーワードトレンド線 ---
    st.markdown("### 📉 キーワードの年次トレンド比較")
    all_kw = [kw for kw, _ in Counter(
        kw for kws in df["_keywords"] for kw in kws).most_common(50)]
    picked = st.multiselect("比較するキーワードを選択（最大5つ）", all_kw, max_selections=5,
                            default=all_kw[:2] if len(all_kw) >= 2 else all_kw)
    if picked:
        trend_rows = []
        for year, g in df.groupby("年"):
            counts = Counter(kw for kws in g["_keywords"] for kw in kws)
            for kw in picked:
                trend_rows.append({"年": year, "キーワード": kw, "件数": counts.get(kw, 0)})
        trend_df = pd.DataFrame(trend_rows).sort_values("年")
        fig5 = px.line(trend_df, x="年", y="件数", color="キーワード", markers=True)
        fig5.update_layout(height=380)
        st.plotly_chart(fig5, width='stretch')

    # --- AI俯瞰総評 ---
    st.markdown("---")
    st.markdown("### 🤖 AI俯瞰総評（全ケースを一括でGeminiに読ませた講評）")

    cached = None
    if os.path.exists(COMMENTARY_PATH):
        try:
            with open(COMMENTARY_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
        except Exception:
            cached = None

    is_fresh = cached and cached.get("built_at") == built_at
    if cached:
        freshness = "（最新のインデックスに基づく）" if is_fresh else "（⚠️ インデックス更新後に再生成推奨）"
        st.caption(f"生成日時: {cached.get('generated_at','')[:19]} / コスト: 約{cached.get('cost_jpy',0)}円 {freshness}")
        st.markdown(cached.get("markdown", ""))

    btn_label = "🔁 総評を再生成する" if cached else "▶️ 総評を生成する"
    if st.button(btn_label, key="btn_commentary"):
        if not os.getenv("GEMINI_API_KEY"):
            st.error("環境変数 GEMINI_API_KEY が設定されていません。")
        else:
            with st.spinner("Geminiが全ケースを俯瞰しています..."):
                try:
                    md, cost = strategy_engine.generate_trend_commentary(records)
                    from datetime import datetime
                    with open(COMMENTARY_PATH, "w", encoding="utf-8") as f:
                        json.dump({"built_at": built_at, "markdown": md, "cost_jpy": cost,
                                   "generated_at": datetime.now().isoformat()},
                                  f, ensure_ascii=False, indent=1)
                    st.rerun()
                except Exception as e:
                    st.error(f"総評の生成に失敗しました: {e}")

# =========================================================
# タブ3: 戦略分析（一気通貫パイプライン）
# =========================================================
with tab_strategy:
    st.markdown("### 🎯 一気通貫 企業戦略分析")
    st.caption("企業名を入力すると、会社分析→株式市場→業界・競合→類似RTOCS事例→課題→戦略策定まで自動で実行し、HTMLレポートを生成します。")

    col_in, col_mode = st.columns([2, 1])
    with col_in:
        target_company = st.text_input("分析対象の企業名", placeholder="例: トヨタ自動車, 任天堂, サントリー")
    with col_mode:
        mode = st.radio("分析モード", ["通常（flash・数十円）", "ディープ（pro・数百円）"], index=0)

    if not os.getenv("GEMINI_API_KEY"):
        st.warning("⚠️ 環境変数 GEMINI_API_KEY が設定されていません。設定後に再起動してください。")

    if st.button("🚀 分析を実行", type="primary", disabled=not target_company):
        deep = mode.startswith("ディープ")
        status_boxes = {}

        with st.status("パイプラインを実行中...", expanded=True) as status:
            def progress(key, label, state):
                if state == "start":
                    st.write(f"⏳ {label} ...")
                elif state == "done":
                    st.write(f"✅ {label} 完了")
                elif state == "error":
                    st.write(f"❌ {label} 失敗（続行します）")

            try:
                engine = strategy_engine.StrategyEngine(deep=deep, data_dir=DATA_DIR,
                                                        progress_cb=progress)
                result = engine.run_pipeline(target_company)
                report_path = strategy_report.generate_strategy_report(result)
                st.session_state["last_result"] = result
                st.session_state["last_report"] = report_path
                status.update(label="✅ 分析完了", state="complete")
            except Exception as e:
                status.update(label=f"❌ 実行エラー: {e}", state="error")

    # --- 結果表示 ---
    if "last_result" in st.session_state:
        result = st.session_state["last_result"]
        report_path = st.session_state.get("last_report", "")
        costs = result.get("costs", {})

        st.markdown("---")
        st.markdown(f"#### 📄 レポート: {os.path.basename(report_path)}")
        st.caption(f"💰 コスト: ${costs.get('total_usd', 0):.4f}（約 {costs.get('total_jpy', 0):.2f} 円） / モデル: {result.get('model')}")

        strategy = result.get("stages", {}).get("strategy", {})
        if isinstance(strategy, dict) and strategy.get("executive_summary"):
            st.info(f"**エグゼクティブサマリー**\n\n{strategy['executive_summary']}")
            for i, s in enumerate(strategy.get("strategies", []), 1):
                st.markdown(f"**戦略{i}: {s.get('title', '')}**")

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            if st.button("🌐 レポートを開く", width='stretch', key="btn_open_report"):
                open_local_file(report_path)
        with col_r2:
            if report_path and os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    st.download_button("💾 レポートをダウンロード", f.read(),
                                       file_name=os.path.basename(report_path),
                                       mime="text/html", width='stretch')
