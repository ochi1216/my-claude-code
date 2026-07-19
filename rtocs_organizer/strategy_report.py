# -*- coding: utf-8 -*-
"""戦略分析レポートのHTML生成。

strategy_engine.run_pipeline() の結果dictから、自己完結の1枚HTMLを生成する。
- CSSは既存organizerのHTMLGenerator（カード型）様式を踏襲
- 株価チャートはmatplotlib→base64 PNG埋め込み（印刷・単一ファイル配布に強い）
- 失敗ステージは赤カード、スキップはグレー注記で必ず描画する（部分レポート方針）
"""

import os
import io
import re
import json
import html
import base64
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT_DIR = os.path.join(BASE_DIR, "data", "strategy_reports")

CSS = """
body { font-family: "Segoe UI", "Hiragino Sans", "Meiryo", sans-serif; background-color: #f8f9fa; color: #333; padding: 20px; }
.container { max-width: 1000px; margin: 0 auto; }
.card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-top: 4px solid #3182ce; }
.card.error { border-top-color: #e53e3e; }
.card.strategy { border-top-color: #d69e2e; background: #fffff0; }
.section-title { color: #2d3748; font-weight: 700; font-size: 1.3rem; margin-bottom: 15px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px; }
.badge { display: inline-block; padding: 4px 10px; margin: 0 5px 5px 0; background: #edf2f7; color: #4a5568; border-radius: 15px; font-size: 0.85rem; font-weight: bold; }
.highlight-box { background-color: #ebf8ff; border-left: 4px solid #3182ce; padding: 15px; border-radius: 4px; margin-bottom: 15px; line-height: 1.7; }
.error-box { background-color: #fff5f5; border-left: 4px solid #e53e3e; padding: 15px; border-radius: 4px; color: #c53030; }
.skip-box { background-color: #f7fafc; border-left: 4px solid #a0aec0; padding: 12px; border-radius: 4px; color: #718096; font-size: 0.9rem; }
.item { margin-bottom: 14px; line-height: 1.7; }
.item strong { color: #3182ce; }
table { border-collapse: collapse; width: 100%; margin-bottom: 15px; font-size: 0.92rem; }
th, td { border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; vertical-align: top; line-height: 1.6; }
th { background: #edf2f7; }
.cost-banner { text-align: center; padding: 10px; margin-bottom: 20px; background-color: #e0f2fe; border: 1px solid #bae6fd; border-radius: 5px; font-weight: bold; color: #0369a1; }
.note { font-size: 0.8rem; color: #718096; text-align: center; margin: 20px 0; }
.strategy-item { background: white; border: 1px solid #ecc94b; border-radius: 6px; padding: 15px; margin-bottom: 15px; }
.strategy-item h3 { color: #b7791f; margin: 0 0 10px 0; font-size: 1.05rem; }
ul { padding-left: 22px; margin: 6px 0; }
li { margin-bottom: 6px; line-height: 1.6; }
img.chart { max-width: 100%; border: 1px solid #e2e8f0; border-radius: 6px; }
@media print { body { background: white; } .card { box-shadow: none; border: 1px solid #cbd5e1; } }
"""


def _e(v):
    """HTMLエスケープ（None安全）"""
    return html.escape(str(v)) if v is not None else ""


_CONF_BADGE = {
    "high": ("✅ 高", "#f0fff4", "#9ae6b4"),
    "medium": ("🟡 中", "#fffff0", "#faf089"),
    "low": ("🔴 低", "#fff5f5", "#feb2b2"),
}


def _source_badge_html(stage_dict):
    """軸4-①: 出典確度バッジ（source_confidence/source_note）。無ければ何も出さない（後方互換）。"""
    conf = stage_dict.get("source_confidence")
    note = stage_dict.get("source_note")
    if not conf and not note:
        return ""
    label, bg, border = _CONF_BADGE.get(conf, (conf or "—", "#edf2f7", "#e2e8f0"))
    note_html = f' <span style="color:#718096;font-size:0.85rem;">{_e(note)}</span>' if note else ""
    return (f'<div style="margin-top:10px;">'
            f'<span class="badge" style="background:{bg};border:1px solid {border};">出典確度: {_e(label)}</span>'
            f'{note_html}</div>')


def _grounding_sources_html(stage_dict):
    """検索グラウンディングが実際に参照したURL（grounding_sources、APIのメタデータ由来。
    LLM生成のURLではないためハルシネーションしない）を出典リンクとして表示する。無ければ何も出さない。
    """
    sources = stage_dict.get("grounding_sources")
    if not sources:
        return ""
    links = "".join(
        f'<a href="{_e(src.get("url"))}" target="_blank" rel="noopener noreferrer" '
        f'style="margin-right:12px;display:inline-block;">🔗 {_e(src.get("title") or src.get("domain") or src.get("url"))}</a>'
        for src in sources[:8] if src.get("url"))
    if not links:
        return ""
    return f'<div class="skip-box" style="margin-top:8px;">参照元（検索結果）: {links}</div>'


def _guard(stage_dict, body_fn):
    """error/skippedを共通処理し、正常時は本体HTML＋出典確度バッジ＋参照元リンクを描画する"""
    if not isinstance(stage_dict, dict):
        return f'<div class="skip-box">データ形式が不正です</div>'
    if "error" in stage_dict:
        return f'<div class="error-box">❌ {_e(stage_dict["error"])}</div>'
    if "skipped" in stage_dict:
        return f'<div class="skip-box">⏩ {_e(stage_dict["skipped"])}</div>'
    try:
        return body_fn(stage_dict) + _source_badge_html(stage_dict) + _grounding_sources_html(stage_dict)
    except Exception as e:
        return f'<div class="error-box">❌ 描画エラー: {_e(e)}</div>'


def _ul(items):
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in (items or [])) + "</ul>"


def _price_chart_b64(market_data):
    """月次終値の折れ線チャートをbase64 PNGで返す（matplotlib不在なら空文字）"""
    history = (market_data or {}).get("price_history") or []
    if len(history) < 2:
        return ""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        dates = [p["date"] for p in history]
        closes = [p["close"] for p in history]
        fig, ax = plt.subplots(figsize=(9, 3.2), dpi=110)
        ax.plot(range(len(closes)), closes, color="#3182ce", linewidth=1.8)
        ax.fill_between(range(len(closes)), closes, min(closes), alpha=0.08, color="#3182ce")
        step = max(1, len(dates) // 10)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)], fontsize=8, rotation=30)
        ax.set_title(f"Stock Price (Monthly Close, 5Y) - {market_data.get('ticker','')}", fontsize=10)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _fmt_num(v, unit=""):
    if v is None:
        return "—"
    if abs(v) >= 1e12:
        return f"{v/1e12:,.2f}兆{unit}"
    if abs(v) >= 1e8:
        return f"{v/1e8:,.0f}億{unit}"
    return f"{v:,.2f}{unit}"


def _sec_company(s):
    segs = "".join(
        f"<tr><td>{_e(x.get('segment'))}</td><td>{_e(x.get('description'))}</td>"
        f"<td>{_e(x.get('revenue_share'))}</td></tr>"
        for x in s.get("business_segments", []))
    return f"""
      <div class="item"><strong>正式社名:</strong> {_e(s.get('official_name'))}
        <span class="badge">🏢 {_e(s.get('industry_sector'))}</span>
        <span class="badge">{'上場' if s.get('is_listed') else '未上場'}</span></div>
      <div class="item"><strong>本社:</strong> {_e(s.get('headquarters'))}　<strong>設立:</strong> {_e(s.get('founded'))}</div>
      <div class="highlight-box">{_e(s.get('business_model'))}</div>
      <table><tr><th>事業セグメント</th><th>内容</th><th>売上構成比</th></tr>{segs}</table>
      <div class="item"><strong>強み:</strong>{_ul(s.get('strengths'))}</div>
      <div class="item"><strong>弱み:</strong>{_ul(s.get('weaknesses'))}</div>
      <div class="item"><strong>直近トピック:</strong>{_ul(s.get('recent_topics'))}</div>
      <div class="skip-box">確度注記: {_e(s.get('confidence_note'))}</div>
    """


_LANG_BADGE = {"en": "🇬🇧 EN", "ja": "🇯🇵 JA", "zh": "🇨🇳 ZH"}


def _sec_news(s):
    variants = s.get("name_variants", {}) or {}
    variant_badges = "".join(
        f'<span class="badge">{_LANG_BADGE.get(lang, lang.upper())}: {_e(name)}</span>'
        for lang, name in variants.items() if name)
    news_items = sorted(s.get("recent_news", []) or [], key=lambda n: n.get("date", ""), reverse=True)
    rows = "".join(
        f"""<tr><td>{_e(n.get('date'))}</td>
            <td>{_LANG_BADGE.get(n.get('language',''), _e(n.get('language')))}</td>
            <td>{_e(n.get('headline'))}<br><span style="color:#718096;font-size:0.85rem;">{_e(n.get('summary'))}</span></td>
            <td>{_e(n.get('source'))}</td></tr>"""
        for n in news_items)
    table_html = (f'<table><tr><th>日付</th><th>言語</th><th>見出し・要約</th><th>媒体</th></tr>{rows}</table>'
                  if rows else '<div class="skip-box">ニュースは見つかりませんでした</div>')
    note = s.get("recency_note", "")
    note_html = f'<div class="skip-box">ℹ️ {_e(note)}</div>' if note else ""
    return f"{variant_badges}{table_html}{note_html}"


def _sec_analyst(s):
    views = sorted(s.get("analyst_views", []) or [], key=lambda a: a.get("date", ""), reverse=True)
    view_rows = "".join(
        f"""<tr><td>{_e(v.get('date'))}</td><td>{_e(v.get('source'))}</td>
            <td>{_e(v.get('rating_or_view'))}<br><span style="color:#718096;font-size:0.85rem;">{_e(v.get('rationale'))}</span></td></tr>"""
        for v in views)
    view_html = (f'<table><tr><th>日付</th><th>アナリスト/調査会社</th><th>見解</th></tr>{view_rows}</table>'
                 if view_rows else '<div class="skip-box">アナリスト見解は見つかりませんでした</div>')

    narratives = sorted(s.get("management_narrative", []) or [], key=lambda n: n.get("date", ""), reverse=True)
    narrative_html = "".join(
        f"""<div class="item"><strong>{_e(n.get('event'))}</strong> ({_e(n.get('date'))})<br>{_e(n.get('summary'))}</div>"""
        for n in narratives) or '<div class="skip-box">経営陣メッセージは見つかりませんでした</div>'

    gap = s.get("market_expectation_gap", "")
    gap_html = f'<div class="highlight-box">💡 市場評価と自己認識のギャップ: {_e(gap)}</div>' if gap else ""
    note = s.get("recency_note", "")
    note_html = f'<div class="skip-box">ℹ️ {_e(note)}</div>' if note else ""
    return f"""<div class="item"><strong>アナリストの見解:</strong></div>{view_html}
        <div class="item" style="margin-top:10px;"><strong>経営陣自身のメッセージ:</strong></div>{narrative_html}
        {gap_html}{note_html}"""


_OUTLOOK_BADGE = {
    "強気": ("🟢 強気(上昇期待)", "#f0fff4", "#9ae6b4"),
    "中立": ("⚪ 中立", "#edf2f7", "#e2e8f0"),
    "弱気": ("🔴 弱気(下落リスク)", "#fff5f5", "#feb2b2"),
    "不透明": ("🟡 不透明", "#fffff0", "#faf089"),
}


def _outlook_badge(direction):
    for key, val in _OUTLOOK_BADGE.items():
        if key in (direction or ""):
            return val
    return (direction or "—", "#edf2f7", "#e2e8f0")


def _sec_market(s, market_data, target_company=""):
    chart = _price_chart_b64(market_data)
    chart_html = f'<img class="chart" src="data:image/png;base64,{chart}">' if chart else ""
    md = market_data or {}

    # 後方互換: 旧バージョンのdividend_yield(小数)しか無いデータでも表示できるようにする
    div_pct = md.get('dividend_yield_pct')
    if div_pct is None and md.get('dividend_yield') is not None:
        raw = md.get('dividend_yield')
        div_pct = raw * 100 if raw < 1 else raw

    metrics = f"""
      <table><tr><th>ティッカー</th><th>時価総額</th><th>PER</th><th>PBR</th><th>配当利回り</th><th>直近株価</th></tr>
      <tr><td>{_e(md.get('ticker'))}</td><td>{_fmt_num(md.get('market_cap'), md.get('currency',''))}</td>
      <td>{_fmt_num(md.get('trailing_pe'))}</td><td>{_fmt_num(md.get('price_to_book'))}</td>
      <td>{_fmt_num(div_pct,'%')}</td>
      <td>{_fmt_num(md.get('last_price'), md.get('currency',''))}</td></tr></table>
    """ if md else ""

    # ティッカー誤認防止: 取得元の企業名・出典リンクを表示し、対象企業名との一致度が低い場合は警告する
    source_html = ""
    if md.get("ticker"):
        link = (f'<a href="{_e(md.get("source_url", ""))}" target="_blank" rel="noopener noreferrer">'
                f'{_e(md.get("matched_name") or md.get("ticker"))} ({_e(md.get("ticker"))}) ↗</a>')
        if md.get("name_match_confidence") == "low":
            source_html = (f'<div class="error-box">⚠️ 取得したティッカー（{_e(md.get("ticker"))}）の企業名'
                            f'「{_e(md.get("matched_name"))}」が対象企業「{_e(target_company)}」'
                            f'と一致しない可能性があります。以下のリンクで実際の取得元を必ず確認してください: {link}</div>')
        else:
            source_html = f'<div class="skip-box">📊 データ取得元: {link}（Yahoo Finance）</div>'

    # 軸1-⑤: 財務の実行可能性データ（手元資金・負債・FCF）
    capacity = f"""
      <table><tr><th>手元資金</th><th>総負債</th><th>負債資本比率</th><th>フリーキャッシュフロー</th></tr>
      <tr><td>{_fmt_num(md.get('total_cash'), md.get('currency',''))}</td>
      <td>{_fmt_num(md.get('total_debt'), md.get('currency',''))}</td>
      <td>{_fmt_num(md.get('debt_to_equity'),'%')}</td>
      <td>{_fmt_num(md.get('free_cash_flow'), md.get('currency',''))}</td></tr></table>
    """ if md and any(md.get(k) is not None for k in
                       ("total_cash", "total_debt", "debt_to_equity", "free_cash_flow")) else ""

    # 今後の方向性（軸: 単なる現状データの説明で終わらせず、方向性・リスク・カタリストまで示す）
    outlook = s.get("outlook") or {}
    outlook_html = ""
    if outlook:
        label, bg, border = _outlook_badge(outlook.get("direction"))
        outlook_html = f"""
          <div class="item" style="margin-top:10px;"><strong>📈 今後の見立て:</strong>
            <span class="badge" style="background:{bg};border:1px solid {border};">{_e(label)}</span>
            <span class="badge">想定期間: {_e(outlook.get('time_horizon'))}</span>
          </div>
          <div class="highlight-box">{_e(outlook.get('rationale'))}</div>
        """

    risks = s.get("key_risks") or []
    risks_html = ""
    if risks:
        rows = "".join(
            f"<tr><td>{_e(r.get('risk'))}</td><td>{_e(r.get('trigger'))}</td><td>{_e(r.get('potential_impact'))}</td></tr>"
            for r in risks)
        risks_html = (f'<div class="item" style="margin-top:10px;"><strong>⚠️ 想定リスク:</strong></div>'
                      f'<table><tr><th>リスク</th><th>顕在化の条件</th><th>想定される影響</th></tr>{rows}</table>')

    catalysts = s.get("catalysts") or []
    catalysts_html = ""
    if catalysts:
        rows = "".join(
            f"<tr><td>{_e(c.get('event'))}</td><td>{_e(c.get('expected_timing'))}</td><td>{_e(c.get('potential_impact'))}</td></tr>"
            for c in catalysts)
        catalysts_html = (f'<div class="item" style="margin-top:10px;"><strong>📅 今後のカタリスト（株価を動かしうるイベント）:</strong></div>'
                          f'<table><tr><th>イベント</th><th>想定時期</th><th>想定インパクト</th></tr>{rows}</table>')

    return f"""
      {chart_html}{metrics}{source_html}{capacity}
      <div class="item"><strong>バリュエーション:</strong> {_e(s.get('valuation_view'))}</div>
      <div class="item"><strong>株価トレンド:</strong> {_e(s.get('price_trend_view'))}</div>
      <div class="item"><strong>財務健全性:</strong> {_e(s.get('financial_health'))}</div>
      <div class="highlight-box">💰 資金余力（M&A・大規模投資の裏付け）: {_e(s.get('financial_capacity_note'))}</div>
      <div class="item"><strong>市場の期待/懸念:</strong> {_e(s.get('market_expectation'))}</div>
      <div class="item"><strong>特筆指標:</strong> {_e(s.get('key_metrics_comment'))}</div>
      {outlook_html}{risks_html}{catalysts_html}
    """


def _sec_industry(s):
    ff = s.get("five_forces", {})
    ff_rows = "".join(
        f"<tr><th>{label}</th><td>{_e(ff.get(key))}</td></tr>"
        for key, label in [("rivalry", "業界内競争"), ("new_entrants", "新規参入の脅威"),
                           ("substitutes", "代替品の脅威"), ("buyer_power", "買い手の交渉力"),
                           ("supplier_power", "売り手の交渉力")])
    comp_rows = "".join(
        f"<tr><td>{_e(c.get('name'))}</td><td>{_e(c.get('positioning'))}</td>"
        f"<td>{_e(c.get('threat_level'))}</td></tr>"
        for c in s.get("competitors", []))
    return f"""
      <div class="highlight-box">{_e(s.get('industry_structure'))}</div>
      <table>{ff_rows}</table>
      <table><tr><th>競合</th><th>ポジショニング</th><th>脅威度</th></tr>{comp_rows}</table>
      <div class="item"><strong>対象企業のポジション:</strong> {_e(s.get('target_position'))}</div>
    """


_IMPACT_BADGE = {"追い風": "🟢", "逆風": "🔴", "中立": "⚪", "両面あり": "🟡"}


def _sec_macro(s):
    trends = s.get("macro_trends", []) or []
    rows = "".join(
        f"""<tr><td>{_e(t.get('category'))}</td>
            <td>{_IMPACT_BADGE.get(t.get('impact_direction',''), '')} {_e(t.get('impact_direction'))}</td>
            <td>{_e(t.get('time_horizon'))}</td>
            <td><strong>{_e(t.get('trend'))}</strong><br><span style="color:#718096;font-size:0.85rem;">{_e(t.get('summary'))}</span></td></tr>"""
        for t in trends)
    table_html = (f'<table><tr><th>カテゴリ</th><th>方向</th><th>時間軸</th><th>トレンド</th></tr>{rows}</table>'
                  if rows else '<div class="skip-box">マクロトレンドは見つかりませんでした</div>')
    shift = s.get("structural_shift_note", "")
    shift_html = f'<div class="highlight-box">🌊 {_e(shift)}</div>' if shift else ""
    note = s.get("recency_note", "")
    note_html = f'<div class="skip-box">ℹ️ {_e(note)}</div>' if note else ""
    return f"{table_html}{shift_html}{note_html}"


def _sec_cases(retrieve, cases, selected_records):
    by_id = {r["video_id"]: r for r in (selected_records or [])}
    sel_rows = ""
    for c in (retrieve or {}).get("selected_cases", []) if isinstance(retrieve, dict) else []:
        rec = by_id.get(c.get("video_id"), {})
        ep = f"#{rec.get('episode')}" if rec.get("episode") else ""
        cross_badge = ' <span class="badge" style="background:#e6fffa;border:1px solid #81e6d9;">🌉 異業種</span>' if c.get("is_cross_industry") else ""
        sel_rows += (f"<tr><td>{_e(c.get('company'))} {_e(ep)}{cross_badge}</td>"
                     f"<td>{_e(rec.get('sector'))}</td><td>{_e(c.get('reason'))}</td></tr>")
    sel_html = (f"<table><tr><th>参照RTOCS</th><th>業種</th><th>選定理由</th></tr>{sel_rows}</table>"
                if sel_rows else "")

    def body(s):
        lessons = "".join(
            f"""<div class="item"><strong>{_e(l.get('source_case'))}:</strong>
                {_e(l.get('pattern'))}<br>→ <em>{_e(l.get('application'))}</em></div>"""
            for l in s.get("lessons", []))
        return f"""{sel_html}{lessons}
          <div class="highlight-box">{_e(s.get('cross_industry_insight'))}</div>"""
    return _guard(cases, body) if isinstance(cases, dict) else sel_html


def _sec_issues(s):
    def _evidence_html(evidence):
        # 後方互換: 万一文字列で返ってきても壊れないようにする
        items = evidence if isinstance(evidence, list) else ([evidence] if evidence else [])
        return "".join(f'<div style="color:#718096;font-size:0.85rem;">・{_e(x)}</div>' for x in items)

    rows = "".join(
        f"""<div class="item"><strong>■ {_e(i.get('title'))}</strong>
            <span class="badge">緊急度: {_e(i.get('urgency'))}</span><br>
            症状: {_e(i.get('symptom'))}<br>
            根本原因: {_e(i.get('root_cause'))}<br>
            <div style="margin-top:4px;">根拠:</div>{_evidence_html(i.get('evidence'))}</div>"""
        for i in s.get("issues", []))
    return rows or '<div class="skip-box">課題データなし</div>'


_MODE_BADGE = {
    "conservative": ("🛡️ 保守的", "#e6fffa", "#81e6d9"),
    "ambitious": ("🚀 野心的", "#fef3c7", "#fde68a"),
    "disruptive": ("💥 破壊的", "#fff5f5", "#feb2b2"),
}


def _sec_strategy(s):
    items = ""
    for idx, st in enumerate(s.get("strategies", []), 1):
        refs = "".join(f'<span class="badge">📚 {_e(r)}</span>' for r in st.get("referenced_cases", []) or [])
        lens = st.get("framework_lens", "")
        lens_html = f'<span class="badge" style="background:#fef3c7;border:1px solid #fde68a;">🧭 {_e(lens)}</span>' if lens else ""
        mode = st.get("mode", "")
        mode_label, mode_bg, mode_border = _MODE_BADGE.get(mode, (mode, "#edf2f7", "#e2e8f0"))
        mode_html = f'<span class="badge" style="background:{mode_bg};border:1px solid {mode_border};">{_e(mode_label)}</span>' if mode else ""
        feasibility = st.get("feasibility_flag")
        feasibility_html = f'<div class="error-box" style="margin-top:8px;">{_e(feasibility)}</div>' if feasibility else ""
        items += f"""
          <div class="strategy-item">
            <h3>戦略{idx}: {_e(st.get('title'))}</h3>
            {mode_html}{lens_html}
            <div class="item"><strong>根拠:</strong> {_e(st.get('rationale'))}</div>
            <div class="item"><strong>最初の90日:</strong>{_ul(st.get('first_90_days'))}</div>
            {f'<div class="item"><strong>1年後のマイルストーン:</strong>{_ul(st.get("year_1_milestones"))}</div>' if st.get('year_1_milestones') else ''}
            {f'<div class="item"><strong>3年後のビジョン:</strong> {_e(st.get("year_3_vision"))}</div>' if st.get('year_3_vision') else ''}
            <div class="item"><strong>リスク:</strong> {_e(st.get('risks'))}</div>
            {refs}
            {feasibility_html}
          </div>"""
    devils_note = s.get("devils_advocate_note", "")
    devils_html = (f'<div class="error-box">😈 悪魔の代弁者: {_e(devils_note)}</div>'
                   if devils_note else "")
    closing = s.get("closing_message", "")
    closing_html = f'<div class="highlight-box" style="border-left-color:#d69e2e;background:#fffbeb;">💬 {_e(closing)}</div>' if closing else ""
    return items + devils_html + closing_html


def _sec_progress(s):
    """軸5-①: 前回分析との比較（進捗トラッキング）"""
    return f"""
      <div class="highlight-box">{_e(s.get('progress_summary'))}</div>
      <div class="item"><strong>改善・解消したと見られる点:</strong>{_ul(s.get('resolved_or_improved'))}</div>
      <div class="item"><strong>新たな/悪化した課題:</strong>{_ul(s.get('new_or_worsened_issues'))}</div>
      <div class="item"><strong>戦略の継続性:</strong> {_e(s.get('strategy_continuity'))}</div>
      <div class="highlight-box" style="border-left-color:#d69e2e;background:#fffbeb;">💡 {_e(s.get('recommendation'))}</div>
    """


def generate_strategy_report(result, out_dir=None):
    """結果dictからHTMLレポートを生成しファイルパスを返す"""
    out_dir = out_dir or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    stages = result.get("stages", {})
    company = result.get("company", "Unknown")
    s1 = stages.get("company", {})
    disp_name = s1.get("official_name", company) if isinstance(s1, dict) and "error" not in s1 else company
    mode_label = "ディープ (gemini-2.5-pro)" if result.get("mode") == "deep" else "通常 (gemini-2.5-flash)"
    costs = result.get("costs", {})
    dt = datetime.now()

    strategy = stages.get("strategy", {})
    exec_summary = strategy.get("executive_summary", "") if isinstance(strategy, dict) else ""
    exec_html = (f'<div class="card"><div class="section-title">📋 エグゼクティブサマリー</div>'
                 f'<div class="highlight-box">{_e(exec_summary)}</div></div>') if exec_summary else ""

    user_constraints = result.get("user_constraints", "")
    constraints_html = (
        f'<div class="card"><div class="section-title">📌 経営者が明示した制約条件</div>'
        f'<div class="highlight-box" style="border-left-color:#d69e2e;background:#fffbeb;">'
        f'{_e(user_constraints)}</div>'
        f'<div class="skip-box">この制約条件は課題分析・戦略策定の全ステージで必須順守として扱われています。</div>'
        f'</div>') if user_constraints else ""

    def card(title, inner, extra_class=""):
        return f'<div class="card {extra_class}"><div class="section-title">{title}</div>{inner}</div>'

    sections = [
        constraints_html,
        exec_html,
        card("🏢 会社分析", _guard(stages.get("company", {}), _sec_company)),
        card("📰 直近ニュース（英語/日本語/中国語）", _guard(stages.get("news", {}), _sec_news)),
        card("📊 アナリスト洞察・経営陣メッセージ", _guard(stages.get("analyst", {}), _sec_analyst)),
        card("🌊 マクロ・技術トレンド", _guard(stages.get("macro", {}), _sec_macro)),
        card("📈 株式市場分析", _guard(stages.get("market", {}),
                                       lambda s: _sec_market(s, result.get("market_data"), disp_name))),
        card("🌐 業界・競合分析", _guard(stages.get("industry", {}), _sec_industry)),
        card("📚 他業種RTOCS事例分析",
             _sec_cases(stages.get("retrieve", {}), stages.get("cases", {}),
                        result.get("selected_case_records"))),
        card("🔍 課題分析", _guard(stages.get("issues", {}), _sec_issues)),
        card("🎯 戦略提言（大前式）", _guard(stages.get("strategy", {}), _sec_strategy), "strategy"),
        card("📈 前回分析との比較（進捗トラッキング）", _guard(stages.get("progress", {}), _sec_progress))
        if "progress" in stages else "",
    ]

    cost_html = (f'<div class="cost-banner">💰 推定APIコスト ({_e(result.get("model"))}): '
                 f'${costs.get("total_usd", 0):.4f}（約 {costs.get("total_jpy", 0):.2f} 円）</div>'
                 if costs else "")

    html_doc = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>戦略分析レポート - {_e(disp_name)}</title>
<style>{CSS}</style></head><body><div class="container">
<div class="card"><div class="section-title" style="font-size:1.5rem;border-bottom:none;">
🎯 企業戦略分析レポート: {_e(disp_name)}</div>
<span class="badge">生成日時: {dt.strftime('%Y年%m月%d日 %H:%M')}</span>
<span class="badge">モード: {_e(mode_label)}</span></div>
{cost_html}
{''.join(sections)}
<div class="note">本レポートはAIの知識および無料公開データに基づく参考情報です（要確認）。<br>
蓄積されたRTOCSケースライブラリ（大前研一ライブ）を類推の土台として利用しています。投資判断・経営判断はご自身の責任で行ってください。</div>
</div></body></html>"""

    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", str(disp_name))[:40]
    timestamp = dt.strftime('%Y%m%d_%H%M%S')
    filename = f"Strategy_{safe_name}_{timestamp}.html"
    filepath = os.path.join(out_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_doc)

    # 軸5-①: 次回以降の進捗トラッキング（前回分析との比較）のため、構造化データもJSONで
    # サイドカー保存する（内部キー"_"始まりは除外。中間確認チェックポインで保留中の結果は
    # 呼び出し側の責務で保存しないことが多いが、保存されても後続の比較には影響しない）。
    try:
        sidecar = {k: v for k, v in result.items() if not k.startswith("_")}
        json_path = os.path.join(out_dir, f"Strategy_{safe_name}_{timestamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(sidecar, f, ensure_ascii=False, indent=1)
    except Exception:
        pass  # サイドカー保存に失敗してもHTMLレポート自体は既に生成済みなので続行

    return filepath
