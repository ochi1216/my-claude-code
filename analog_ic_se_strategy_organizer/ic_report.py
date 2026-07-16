# -*- coding: utf-8 -*-
"""TI製品競合分析レポートのHTML生成。

ic_engine.IcPipeline.run_pipeline() の結果dict（metadata/classifiers/content構造）から、
自己完結の1枚HTMLを生成する。
- CSSはrtocs_organizer/strategy_report.pyのカード型様式を踏襲
- fact構造（value/source_type/confidence等）はconfidenceバッジ付きで描画する
- 失敗ステージは赤カード、スキップはグレー注記で必ず描画する（部分レポート方針）
"""

import os
import re
import html
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT_DIR = os.path.join(BASE_DIR, "data", "ic_reports")

CSS = """
body { font-family: "Segoe UI", "Hiragino Sans", "Meiryo", sans-serif; background-color: #f8f9fa; color: #333; padding: 20px; }
.container { max-width: 1000px; margin: 0 auto; }
.card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-top: 4px solid #3182ce; }
.card.error { border-top-color: #e53e3e; }
.card.strategy { border-top-color: #d69e2e; background: #fffff0; }
.section-title { color: #2d3748; font-weight: 700; font-size: 1.3rem; margin-bottom: 15px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px; }
.badge { display: inline-block; padding: 4px 10px; margin: 0 5px 5px 0; background: #edf2f7; color: #4a5568; border-radius: 15px; font-size: 0.85rem; font-weight: bold; }
.badge.conf-high { background: #c6f6d5; color: #22543d; }
.badge.conf-medium { background: #feebc8; color: #7b341e; }
.badge.conf-low { background: #fed7d7; color: #822727; }
.highlight-box { background-color: #ebf8ff; border-left: 4px solid #3182ce; padding: 15px; border-radius: 4px; margin-bottom: 15px; line-height: 1.7; }
.error-box { background-color: #fff5f5; border-left: 4px solid #e53e3e; padding: 15px; border-radius: 4px; color: #c53030; }
.skip-box { background-color: #f7fafc; border-left: 4px solid #a0aec0; padding: 12px; border-radius: 4px; color: #718096; font-size: 0.9rem; }
.item { margin-bottom: 14px; line-height: 1.7; }
.item strong { color: #3182ce; }
table { border-collapse: collapse; width: 100%; margin-bottom: 15px; font-size: 0.9rem; }
th, td { border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; vertical-align: top; line-height: 1.6; }
th { background: #edf2f7; }
.cost-banner { text-align: center; padding: 10px; margin-bottom: 20px; background-color: #e0f2fe; border: 1px solid #bae6fd; border-radius: 5px; font-weight: bold; color: #0369a1; }
.note { font-size: 0.8rem; color: #718096; text-align: center; margin: 20px 0; }
.strategy-item { background: white; border: 1px solid #ecc94b; border-radius: 6px; padding: 15px; margin-bottom: 15px; }
.strategy-item h3 { color: #b7791f; margin: 0 0 10px 0; font-size: 1.05rem; }
ul { padding-left: 22px; margin: 6px 0; }
li { margin-bottom: 6px; line-height: 1.6; }
.company-block { border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; margin-bottom: 12px; }
.company-block.lookup-error { border-color: #fed7d7; background: #fff5f5; }
@media print { body { background: white; } .card { box-shadow: none; border: 1px solid #cbd5e1; } }
"""


def _e(v):
    """HTMLエスケープ（None安全）"""
    return html.escape(str(v)) if v is not None else ""


def _guard(stage_dict, body_fn):
    """error/skippedを共通処理し、正常時のみ本体HTMLを描画する"""
    if not isinstance(stage_dict, dict):
        return '<div class="skip-box">データ形式が不正です</div>'
    if "error" in stage_dict:
        return f'<div class="error-box">❌ {_e(stage_dict["error"])}</div>'
    if "skipped" in stage_dict:
        return f'<div class="skip-box">⏩ {_e(stage_dict["skipped"])}</div>'
    try:
        return body_fn(stage_dict)
    except Exception as e:
        return f'<div class="error-box">❌ 描画エラー: {_e(e)}</div>'


def _ul(items):
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in (items or [])) + "</ul>"


def _fact(f, unit_override=None):
    """fact構造({value,unit,source_type,confidence,...})を確度バッジ付きの1行HTMLにする"""
    if not isinstance(f, dict) or "value" not in f:
        return _e(f)
    value = f.get("value", "")
    unit = unit_override if unit_override is not None else f.get("unit", "")
    conf = f.get("confidence", "low")
    source = f.get("source_type", "")
    text = f"{value}{unit}" if value not in (None, "") else "—"
    url = f.get("source_url", "")
    link = f' <a href="{_e(url)}" target="_blank" rel="noopener">🔗</a>' if url else ""
    return (f'{_e(text)} <span class="badge conf-{_e(conf)}">{_e(source)}/{_e(conf)}</span>{link}')


def _fact_table(fact_dict, param_labels=None):
    """{key: fact構造}の辞書をテーブルHTMLにする。param_labelsは{key: {"label":..,"unit":..}}"""
    if not fact_dict:
        return '<div class="skip-box">仕様データなし</div>'
    param_labels = param_labels or {}
    rows = ""
    for key, f in fact_dict.items():
        label = param_labels.get(key, {}).get("label", key)
        rows += f"<tr><td>{_e(label)}</td><td>{_fact(f)}</td></tr>"
    return f'<table><tr><th>項目</th><th>値（出典/確度）</th></tr>{rows}</table>'


def _sec_product(s, category_labels):
    apps_html = "".join(f"<li>{_fact(a)}</li>" for a in (s.get("applications") or []))
    notes = "".join(
        f'<li><a href="{_e(n.get("url"))}" target="_blank" rel="noopener">{_e(n.get("title"))}</a> '
        f'<span class="badge conf-{_e(n.get("confidence","low"))}">{_e(n.get("source_type",""))}</span></li>'
        for n in (s.get("application_notes") or []))
    category_val = s.get("category", {}).get("value", "") if isinstance(s.get("category"), dict) else ""
    label = category_labels.get(category_val, {}).get("label", category_val)
    return f"""
      <div class="item"><strong>型番:</strong> {_e(s.get('part_number'))}
        <span class="badge">🏭 {_e(s.get('manufacturer'))}</span>
        <span class="badge">📦 {_e(label)}</span></div>
      <div class="item"><strong>製品ファミリー:</strong> {_e(s.get('product_family'))}</div>
      <div class="highlight-box">{_e(s.get('short_description'))}</div>
      <div class="item"><strong>データシート:</strong> {_fact(s.get('datasheet_url'))}</div>
      <div class="item"><strong>アプリケーション用途:</strong><ul>{apps_html}</ul></div>
      {'<div class="item"><strong>アプリケーションノート:</strong><ul>' + notes + '</ul></div>' if notes else ''}
      <div class="item"><strong>主要仕様:</strong></div>
      {_fact_table(s.get('key_specs', {}), {p['key']: p for p in category_labels.get(category_val, {}).get('parameters', [])})}
    """


def _sec_market(s):
    rows = ""
    for m in s.get("market_estimates", []) or []:
        rows += (f"<tr><td>{_e(m.get('application'))}</td>"
                 f"<td>{_fact(m.get('market_size'))}</td>"
                 f"<td>{_fact(m.get('cagr'))}</td>"
                 f"<td>{_fact(m.get('ti_stated_growth_driver'))}</td></tr>")
    table = (f'<table><tr><th>アプリケーション</th><th>市場規模</th><th>CAGR</th>'
             f'<th>TI発信の成長ドライバー</th></tr>{rows}</table>' if rows else
             '<div class="skip-box">市場データが見つかりませんでした</div>')
    return f"""{table}<div class="highlight-box">{_e(s.get('overall_market_view'))}</div>"""


def _sec_customers(s):
    rows = "".join(
        f"""<div class="item"><strong>{_e(c.get('company'))}</strong>
            <span class="badge">{_e(c.get('region'))}</span>
            <span class="badge conf-{_e(c.get('confidence','low'))}">{_e(c.get('evidence_type'))}/{_e(c.get('confidence'))}</span><br>
            {_e(c.get('evidence_summary'))}
            {f'<a href="{_e(c.get("evidence_source_url"))}" target="_blank" rel="noopener">🔗</a>' if c.get('evidence_source_url') else ''}
        </div>"""
        for c in (s.get("estimated_key_customers") or []))
    body = rows or '<div class="skip-box">公開情報からは推定できませんでした</div>'
    segs = _ul(s.get("customer_segments"))
    disclaimer = f'<div class="skip-box">ℹ️ {_e(s.get("disclaimer"))}</div>' if s.get("disclaimer") else ""
    return f"{body}<div class='item'><strong>顧客セグメント傾向:</strong>{segs}</div>{disclaimer}"


def _sec_competitors(s, category_labels, category_key):
    params = {p['key']: p for p in category_labels.get(category_key, {}).get('parameters', [])}
    blocks = ""
    for c in s.get("competitors", []) or []:
        is_error = c.get("lookup_status") == "error"
        cls = "company-block lookup-error" if is_error else "company-block"
        if is_error:
            blocks += (f'<div class="{cls}"><strong>{_e(c.get("company"))}</strong> '
                       f'<span class="badge">{_e(c.get("region"))}</span><br>'
                       f'❌ {_e(c.get("error"))}</div>')
            continue
        gap = c.get("gap_vs_ti", {}) or {}
        blocks += f"""
          <div class="{cls}">
            <strong>{_e(c.get('company'))}</strong> <span class="badge">{_e(c.get('region'))}</span>
            <span class="badge">📎 {_e(c.get('comparable_part'))}</span>
            {_fact_table(c.get('specs', {}), params)}
            <div class="item"><strong>TIの優位点:</strong>{_ul(gap.get('advantages_of_ti'))}</div>
            <div class="item"><strong>競合の優位点:</strong>{_ul(gap.get('advantages_of_competitor'))}</div>
            <div class="highlight-box">{_e(gap.get('summary'))}</div>
          </div>"""
    return blocks or '<div class="skip-box">競合データがありません</div>'


def _sec_next_gen(s):
    items = ""
    for p in s.get("proposed_specs", []) or []:
        items += f"""
          <div class="strategy-item">
            <h3>{_e(p.get('kpi'))} <span class="badge">優先度: {_e(p.get('priority'))}</span></h3>
            <div class="item"><strong>現行TI値:</strong> {_e(p.get('current_ti_value'))} →
              <strong>提案目標値:</strong> {_e(p.get('target_value'))}</div>
            <div class="item"><strong>根拠:</strong> {_e(p.get('rationale'))}</div>
            <div class="item"><strong>埋める競合ギャップ:</strong> {_e(p.get('competitive_gap_addressed'))}</div>
            <div class="item"><strong>実現性リスク:</strong> {_e(p.get('feasibility_risk'))}</div>
          </div>"""
    features = "".join(
        f"<li><strong>{_e(f.get('feature'))}:</strong> {_e(f.get('rationale'))}"
        f"（想定用途: {_e(f.get('target_application'))}）</li>"
        for f in (s.get("new_feature_proposals") or []))
    features_html = f'<div class="item"><strong>追加機能案:</strong><ul>{features}</ul></div>' if features else ""
    closing = s.get("closing_message", "")
    closing_html = (f'<div class="highlight-box" style="border-left-color:#d69e2e;background:#fffbeb;">'
                     f'💬 {_e(closing)}</div>' if closing else "")
    return items + features_html + closing_html


def generate_ic_report(result, out_dir=None):
    """結果dict（metadata/classifiers/content構造）からHTMLレポートを生成しファイルパスを返す"""
    import ic_schema

    out_dir = out_dir or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    meta = result.get("metadata", {})
    classifiers = result.get("classifiers", {})
    content = result.get("content", {})
    costs = result.get("costs", {})
    part_number = meta.get("part_number", "Unknown")
    category_key = classifiers.get("category", "generic_analog_ic")
    mode_label = "ディープ (gemini-2.5-pro)" if meta.get("pipeline_mode") == "deep" else "通常 (gemini-2.5-flash)"
    dt = datetime.now()

    category_labels = ic_schema.load_category_schema().get("categories", {})
    category_labels[ic_schema.GENERIC_CATEGORY_KEY] = ic_schema.GENERIC_CATEGORY

    s4 = content.get("stage4_next_gen_proposal", {})
    exec_summary = s4.get("executive_summary", "") if isinstance(s4, dict) else ""
    exec_html = (f'<div class="card"><div class="section-title">📋 エグゼクティブサマリー</div>'
                 f'<div class="highlight-box">{_e(exec_summary)}</div></div>') if exec_summary else ""

    def card(title, inner, extra_class=""):
        return f'<div class="card {extra_class}"><div class="section-title">{title}</div>{inner}</div>'

    s0 = content.get("stage0_product", {})
    sections = [
        exec_html,
        card("📦 製品情報", _guard(s0, lambda s: _sec_product(s, category_labels))),
        card("📈 市場分析", _guard(content.get("stage1_market", {}), _sec_market)),
        card("🎯 キーカスタマー推定（公開情報からの推定）", _guard(content.get("stage2_key_customers", {}), _sec_customers)),
        card("⚔️ 競合IC比較", _guard(content.get("stage3_competitors", {}),
                                     lambda s: _sec_competitors(s, category_labels, category_key))),
        card("🚀 次世代スペック提案", _guard(s4, _sec_next_gen), "strategy"),
    ]

    cost_html = (f'<div class="cost-banner">💰 推定APIコスト ({_e(meta.get("model"))}): '
                 f'${costs.get("total_usd", 0):.4f}（約 {costs.get("total_jpy", 0):.2f} 円）</div>'
                 if costs else "")

    html_doc = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>競合分析レポート - {_e(part_number)}</title>
<style>{CSS}</style></head><body><div class="container">
<div class="card"><div class="section-title" style="font-size:1.5rem;border-bottom:none;">
🎯 TI製品 競合分析レポート: {_e(part_number)}</div>
<span class="badge">生成日時: {dt.strftime('%Y年%m月%d日 %H:%M')}</span>
<span class="badge">モード: {_e(mode_label)}</span>
<span class="badge">📦 {_e(category_labels.get(category_key, {}).get('label', category_key))}</span></div>
{cost_html}
{''.join(sections)}
<div class="note">本レポートはAIの検索グラウンディングおよび公開情報に基づく参考情報です（要確認）。<br>
キーカスタマー推定は非公開情報を含まず、特許引用・公開テカルダウン記事・TI公表事例のみに基づく推定です。<br>
競合他社のデータシート由来スペックは各社に著作権が帰属します。重要な意思決定の前には一次情報での確認をお願いします。</div>
</div></body></html>"""

    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", str(part_number))[:40]
    filename = f"IC_{safe_name}_{dt.strftime('%Y%m%d_%H%M%S')}.html"
    filepath = os.path.join(out_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return filepath
