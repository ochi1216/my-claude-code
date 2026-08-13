# -*- coding: utf-8 -*-
"""RTOCS 統合マネジメントダッシュボード v20260719_04

タブ構成:
  📋 一覧・検索   … 従来機能（検索・絞り込み・HTML/PDFを開く）
  📈 傾向分析     … 全RTOCS俯瞰（業界×年、キーワード変遷、AI俯瞰総評 ほか）
  🎯 戦略分析     … 企業名を入力→11ステージ一気通貫の戦略レポートHTML生成＋深掘りチャット（最大5社の一括分析対応）
  🗂 分析履歴     … 過去に生成した戦略分析レポートの一覧・検索・再オープン

起動: streamlit run rtocs_dashboard_20260719_04.py

v20260719_04での変更点:
  - 【新機能】「1つの実行ボタンで最大5社まで企業分析を開始できるようにしたい」というユーザー要望に対応。
    「🎯 戦略分析」タブの企業名入力を複数行対応（1行1社、最大5社）にし、入力した全社を1回の実行ボタンで
    順番に自動分析する。重複した企業名は自動的に除去し、5社を超える入力は先頭5社のみ処理する
  - 複数社を入力した場合、「分析前に中間結果を確認する」チェックポイント機能は使用不可（自動で無効化）。
    単独企業のみの入力時は従来通りチェックポイント・深掘りチャット機能が使える
  - 一括分析の結果は、成功/失敗を含めた企業別の結果一覧（コスト・エグゼクティブサマリー・レポートを
    開く/ダウンロードするボタン）として表示される。1社が失敗しても他社の分析は継続する（部分結果を
    必ず返す既存の失敗耐性方針を、企業単位のバッチにも拡張）
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
STRATEGY_REPORTS_DIR = os.path.join(DATA_DIR, "strategy_reports")


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

tab_list, tab_trend, tab_strategy, tab_history = st.tabs(
    ["📋 一覧・検索", "📈 傾向分析", "🎯 戦略分析", "🗂 分析履歴"])

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
MAX_BATCH_COMPANIES = 5

with tab_strategy:
    st.markdown("### 🎯 一気通貫 企業戦略分析")
    st.caption("企業名を入力すると、会社分析→株式市場→業界・競合→類似RTOCS事例→課題→戦略策定まで自動で実行し、HTMLレポートを生成します。経営の制約条件を入力すると、より実行可能な提言になります。")

    company_input = st.text_area(
        f"分析対象の企業名（1行に1社、最大{MAX_BATCH_COMPANIES}社まで）",
        placeholder="トヨタ自動車\n任天堂\nサントリー",
        height=100,
        help=f"複数社を入力すると、1回の実行ボタンで最大{MAX_BATCH_COMPANIES}社まで自動的に順番に分析します。")

    _seen = set()
    companies = []
    for _line in company_input.splitlines():
        _name = _line.strip()
        if _name and _name not in _seen:
            _seen.add(_name)
            companies.append(_name)
    if len(companies) > MAX_BATCH_COMPANIES:
        st.warning(f"⚠️ {len(companies)}社入力されていますが、最大{MAX_BATCH_COMPANIES}社までです。"
                   f"先頭{MAX_BATCH_COMPANIES}社のみ分析します: {', '.join(companies[:MAX_BATCH_COMPANIES])}")
        companies = companies[:MAX_BATCH_COMPANIES]
    elif len(companies) > 1:
        st.caption(f"分析対象（{len(companies)}社）: {', '.join(companies)}")

    is_batch = len(companies) > 1
    mode = st.radio("分析モード", ["通常（flash・数十円）", "ディープ（pro・数百円）"], index=0)

    user_constraints = st.text_area(
        "経営の制約条件（任意）",
        placeholder="例: 負債covenantによりM&Aは実行不可／取締会はリスク回避的で急進的な事業売却は通らない／コア技術は外部に出せない",
        help="AIには分からない、経営者自身が知っている制約を入力すると、課題分析・戦略策定の全ステージで必須順守として扱われます。複数社を一括分析する場合は全社に共通の制約として適用されます。空欄でも実行できます。")

    use_checkpoint = st.checkbox(
        "分析前に中間結果を確認する（オプション、既定はOFF）",
        value=False,
        disabled=is_batch,
        help=("複数社の一括分析では確認チェックポイントは使用できません（自動で最後まで実行されます）。"
              if is_batch else
              "ONにすると、会社分析〜他業種事例分析までの前半ステージだけを先に実行して中間結果を表示します。"
              "内容を確認した上で、追加コメント・修正指示を入力してから課題分析・戦略策定（後半）を実行できます。"
              "OFFの場合は従来通り全ステージが自動で一気通貫実行されます。"))
    if is_batch:
        use_checkpoint = False

    if not os.getenv("GEMINI_API_KEY"):
        st.warning("⚠️ 環境変数 GEMINI_API_KEY が設定されていません。設定後に再起動してください。")

    run_label = f"🚀 {len(companies)}社の分析を実行" if is_batch else "🚀 分析を実行"
    if st.button(run_label, type="primary", disabled=not companies):
        deep = mode.startswith("ディープ")
        st.session_state.pop("checkpoint_pending", None)
        st.session_state.pop("checkpoint_engine", None)
        st.session_state.pop("last_result", None)
        st.session_state.pop("last_report", None)
        st.session_state.pop("batch_results", None)

        if not is_batch and use_checkpoint:
            # 単独企業＋確認チェックポイントON: 前半ステージのみ実行して一時停止（軸3-②、既存フロー）
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
                    paused = engine.run_pipeline(companies[0], user_constraints=user_constraints,
                                                 stop_before_issues=True)
                    st.session_state["checkpoint_pending"] = paused
                    st.session_state["checkpoint_engine"] = engine
                    status.update(label="⏸️ 前半ステージ完了（内容を確認してください）", state="complete")
                except Exception as e:
                    status.update(label=f"❌ 実行エラー: {e}", state="error")
        else:
            # 単独企業（チェックポイントOFF）／複数企業の一括分析: 1社ずつ順番に最後まで実行する
            batch_results = []
            with st.status(f"{len(companies)}社の分析を実行中..." if is_batch else "パイプラインを実行中...",
                           expanded=True) as status:
                for idx, comp in enumerate(companies, 1):
                    if is_batch:
                        st.write(f"#### ({idx}/{len(companies)}) {comp}")
                    prefix = f"[{comp}] " if is_batch else ""

                    def progress(key, label, state, _prefix=prefix):
                        if state == "start":
                            st.write(f"⏳ {_prefix}{label} ...")
                        elif state == "done":
                            st.write(f"✅ {_prefix}{label} 完了")
                        elif state == "error":
                            st.write(f"❌ {_prefix}{label} 失敗（続行します）")

                    try:
                        engine = strategy_engine.StrategyEngine(deep=deep, data_dir=DATA_DIR,
                                                                progress_cb=progress)
                        result = engine.run_pipeline(comp, user_constraints=user_constraints)
                        report_path = strategy_report.generate_strategy_report(result)
                        batch_results.append({"company": comp, "result": result,
                                              "report_path": report_path, "error": None})
                    except Exception as e:
                        batch_results.append({"company": comp, "result": None,
                                              "report_path": None, "error": str(e)})
                status.update(
                    label=f"✅ {len(companies)}社の分析が完了しました" if is_batch else "✅ 分析完了",
                    state="complete")

            if len(batch_results) == 1 and batch_results[0]["error"] is None:
                # 単独企業の場合は既存の表示・チャットUIをそのまま使う（後方互換）
                st.session_state["last_result"] = batch_results[0]["result"]
                st.session_state["last_report"] = batch_results[0]["report_path"]
                st.session_state["strategy_chat_history"] = []
            else:
                st.session_state["batch_results"] = batch_results

    # --- 確認・修正チェックポイント（軸3-②） ---
    if "checkpoint_pending" in st.session_state:
        paused = st.session_state["checkpoint_pending"]
        pstages = paused.get("stages", {})
        pcosts = paused.get("costs", {})

        st.markdown("---")
        st.markdown("#### ⏸️ 中間結果の確認（課題分析・戦略策定の前）")
        st.caption(f"💰 現時点のコスト: ${pcosts.get('total_usd', 0):.4f}（約 {pcosts.get('total_jpy', 0):.2f} 円）")

        s1 = pstages.get("company", {})
        if isinstance(s1, dict) and "error" not in s1:
            with st.expander(f"🏢 会社分析: {s1.get('official_name', '')}", expanded=True):
                st.write(s1.get("business_model", ""))
                st.write("強み: " + "、".join(s1.get("strengths", []) or []))
                st.write("弱み: " + "、".join(s1.get("weaknesses", []) or []))

        for key, icon, title in [
            ("news", "📰", "直近ニュース"), ("analyst", "📊", "アナリスト洞察"),
            ("macro", "🌊", "マクロ・技術トレンド"), ("market", "📈", "株式市場分析"),
            ("industry", "🌐", "業界・競合分析"), ("cases", "📚", "他業種RTOCS事例分析"),
        ]:
            s = pstages.get(key, {})
            with st.expander(f"{icon} {title}"):
                if isinstance(s, dict) and "error" in s:
                    st.error(s["error"])
                elif isinstance(s, dict) and "skipped" in s:
                    st.info(s["skipped"])
                else:
                    st.json(s)

        additional_note = st.text_area(
            "続行前の追加コメント・修正指示（任意）",
            key="checkpoint_note",
            placeholder="例: この事業セグメントの記載は古い。直近は海外比率が過半数を占めている点を反映してほしい",
            help="ここに入力した内容は、課題分析・戦略策定の全ステージで必須順守の制約条件として追加されます。")

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            if st.button("▶️ 後半（課題分析・戦略策定）を実行する", type="primary", width='stretch',
                        key="btn_continue_pipeline"):
                engine = st.session_state["checkpoint_engine"]
                with st.status("後半ステージを実行中...", expanded=True) as status2:
                    def progress2(key, label, state):
                        if state == "start":
                            st.write(f"⏳ {label} ...")
                        elif state == "done":
                            st.write(f"✅ {label} 完了")
                        elif state == "error":
                            st.write(f"❌ {label} 失敗（続行します）")
                    engine.progress_cb = progress2
                    try:
                        final_result = engine.continue_pipeline(paused, additional_note=additional_note)
                        report_path = strategy_report.generate_strategy_report(final_result)
                        st.session_state["last_result"] = final_result
                        st.session_state["last_report"] = report_path
                        st.session_state["strategy_chat_history"] = []
                        st.session_state.pop("checkpoint_pending", None)
                        st.session_state.pop("checkpoint_engine", None)
                        status2.update(label="✅ 分析完了", state="complete")
                        st.rerun()
                    except Exception as e:
                        status2.update(label=f"❌ 実行エラー: {e}", state="error")
        with col_c2:
            if st.button("🗑️ この中間結果を破棄する", width='stretch', key="btn_discard_checkpoint"):
                st.session_state.pop("checkpoint_pending", None)
                st.session_state.pop("checkpoint_engine", None)
                st.rerun()

    # --- 一括分析の結果表示（複数社、または失敗を含む場合） ---
    if "batch_results" in st.session_state:
        batch_results = st.session_state["batch_results"]
        st.markdown("---")
        st.markdown(f"#### 📊 一括分析結果（{len(batch_results)}社）")
        succeeded = [b for b in batch_results if b["error"] is None]
        total_cost_jpy = sum((b["result"].get("costs", {}).get("total_jpy", 0) or 0) for b in succeeded)
        st.caption(f"✅ 成功: {len(succeeded)}社 / ❌ 失敗: {len(batch_results) - len(succeeded)}社"
                   f" / 💰 バッチ全体のコスト: 約{total_cost_jpy:.2f}円")

        for b in batch_results:
            with st.expander(f"{'✅' if b['error'] is None else '❌'} {b['company']}"):
                if b["error"] is not None:
                    st.error(f"分析に失敗しました: {b['error']}")
                    continue
                result = b["result"]
                report_path = b["report_path"]
                costs = result.get("costs", {})
                st.caption(f"💰 コスト: ${costs.get('total_usd', 0):.4f}"
                           f"（約 {costs.get('total_jpy', 0):.2f} 円） / モデル: {result.get('model')}")
                strategy = result.get("stages", {}).get("strategy", {})
                if isinstance(strategy, dict) and strategy.get("executive_summary"):
                    st.info(f"**エグゼクティブサマリー**\n\n{strategy['executive_summary']}")

                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("🌐 レポートを開く", width='stretch', key=f"btn_open_batch_{b['company']}"):
                        open_local_file(report_path)
                with col_b2:
                    if report_path and os.path.exists(report_path):
                        with open(report_path, "r", encoding="utf-8") as f:
                            st.download_button("💾 ダウンロード", f.read(),
                                               file_name=os.path.basename(report_path),
                                               mime="text/html", width='stretch',
                                               key=f"btn_dl_batch_{b['company']}")
        st.caption("ℹ️ 各レポートは「🗂 分析履歴」タブからも後で見つけて開けます。")

    # --- 結果表示（単独企業） ---
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

        # --- 深掘りチャット（軸3-①） ---
        st.markdown("---")
        st.markdown("#### 💬 レポートについて質問する")
        st.caption("生成済みの分析結果を踏まえて、AIが自然文で回答します（1問ごとに追加コストが発生します）。")

        chat_key = "strategy_chat_history"
        if chat_key not in st.session_state:
            st.session_state[chat_key] = []

        for msg in st.session_state[chat_key]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        followup = st.chat_input("この分析について質問する（例: なぜ戦略2が最も重要ですか？）")
        if followup:
            st.session_state[chat_key].append({"role": "user", "content": followup})
            with st.chat_message("user"):
                st.markdown(followup)
            with st.chat_message("assistant"):
                with st.spinner("考えています..."):
                    try:
                        answer, chat_cost = strategy_engine.answer_followup_question(
                            result, followup, chat_history=st.session_state[chat_key][:-1])
                        st.markdown(answer)
                        st.caption(f"💰 追加コスト: 約{chat_cost}円")
                        st.session_state[chat_key].append({"role": "assistant", "content": answer})
                    except Exception as e:
                        st.error(f"回答に失敗しました: {e}")

# =========================================================
# タブ4: 分析履歴（過去の戦略分析レポート一覧）
# =========================================================
with tab_history:
    st.markdown("### 🗂 過去の戦略分析レポート")
    st.caption("これまでに生成した戦略分析レポートの一覧です。企業名で検索し、レポートを開く・ダウンロードできます。")

    reports = strategy_report.list_saved_reports(STRATEGY_REPORTS_DIR)
    history_query = st.text_input("企業名で検索", key="history_search", placeholder="例: トヨタ")
    if history_query:
        reports = [r for r in reports if history_query.lower() in (r.get("company") or "").lower()]

    if not reports:
        st.info("該当するレポートがありません。「🎯 戦略分析」タブで企業を分析すると、ここに一覧が追加されます。")
    else:
        st.markdown(f"**該当件数: {len(reports)} 件**")
        mode_labels = {"deep": "ディープ", "flash": "通常"}
        history_df = pd.DataFrame([{
            "企業名": r.get("company") or "不明",
            "生成日時": (r.get("generated_at") or "")[:19].replace("T", " ") or "不明",
            "モード": mode_labels.get(r.get("mode"), r.get("mode") or "—"),
            "コスト(円)": r.get("cost_jpy") if r.get("cost_jpy") is not None else "—",
            "ファイル名": r.get("filename"),
        } for r in reports])
        st.dataframe(history_df, width='stretch', hide_index=True)

        history_options = [
            f"{r.get('company') or '不明'} — {(r.get('generated_at') or '')[:19].replace('T', ' ') or '不明'} "
            f"({r.get('filename')})" for r in reports
        ]
        selected_history_idx = st.selectbox(
            "開くレポートを選択", range(len(history_options)),
            format_func=lambda i: history_options[i], key="history_selector")
        selected_report = reports[selected_history_idx]

        if selected_report.get("executive_summary"):
            st.info(f"**エグゼクティブサマリー（プレビュー）**\n\n{selected_report['executive_summary']}")
        elif selected_report.get("json_path") is None:
            st.caption("ℹ️ このレポートは構造化データ(JSON)が保存される前のバージョンで生成されたため、プレビューは表示できません。")

        col_h1, col_h2 = st.columns(2)
        with col_h1:
            if st.button("🌐 このレポートを開く", width='stretch', key="btn_open_history"):
                open_local_file(selected_report["html_path"])
        with col_h2:
            if os.path.exists(selected_report["html_path"]):
                with open(selected_report["html_path"], "r", encoding="utf-8") as f:
                    st.download_button("💾 ダウンロード", f.read(),
                                       file_name=selected_report["filename"],
                                       mime="text/html", width='stretch', key="btn_download_history")
