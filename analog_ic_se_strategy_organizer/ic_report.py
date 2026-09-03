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
.comparison-scroll { overflow-x: auto; margin-bottom: 15px; }
.comparison-scroll table { min-width: 640px; }
th.proposal-col-head, td.proposal-col { background: #fffbeb; border-left: 3px solid #d69e2e; }
th.own-col-head, td.own-col { background: #ebf8ff; }
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


def _param_cell(specs, key):
    fact = (specs or {}).get(key) if specs else None
    return _fact(fact) if fact else "—"


def _sec_comparison_table(s0, s3, s4, category_def, own_name):
    """パラメータ行×企業列（TI／各競合／自社(現行)／自社提案(次世代)）の統合比較表を1つ作る。

    以前はステージ3(競合IC比較)・ステージ4(次世代スペック提案)を別々のカードで
    「企業ごとにバラバラ」に描画していたが、越智さんの要望（1テーブルで自社の
    提案が一目でわかる構造にしたい）を受けて1つの表に統合した(DESIGN 14章)。
    """
    if not isinstance(s3, dict):
        s3 = {}
    params = category_def.get("parameters", [])
    if not params:
        return '<div class="skip-box">このカテゴリの比較パラメータが未定義です</div>'

    competitors = s3.get("competitors", []) or []
    own_entries = [c for c in competitors if c.get("own_company")]
    other_entries = [c for c in competitors if not c.get("own_company")]
    own = own_entries[0] if own_entries else None
    own_label = _e(own_name) if own_name else "自社"

    ti_specs = s0.get("key_specs", {}) if isinstance(s0, dict) else {}

    proposed_by_key = {}
    if isinstance(s4, dict):
        for p in (s4.get("proposed_specs") or []):
            key = p.get("parameter_key")
            if key:
                proposed_by_key[key] = p

    header_cells = ['<th>パラメータ</th>',
                    '<th>TI<br><span style="font-weight:400;font-size:0.8em;">(ベンチマーク)</span></th>']
    col_specs = [ti_specs]
    failed_companies = []

    for c in other_entries:
        if c.get("lookup_status") == "error":
            failed_companies.append(c)
            continue
        label = _e(c.get("company", ""))
        region = _e(c.get("region", ""))
        part = _e(c.get("comparable_part", "")) or "—"
        header_cells.append(f'<th>{label}<br><span style="font-weight:400;font-size:0.8em;">'
                             f'{region} / {part}</span></th>')
        col_specs.append(c.get("specs", {}))

    if own and own.get("no_current_product"):
        header_cells.append(f'<th class="own-col-head">{own_label}（現行）<br>'
                             f'<span style="font-weight:400;font-size:0.8em;">未参入</span></th>')
        col_specs.append(None)
    elif own and own.get("lookup_status") != "error":
        part = _e(own.get("comparable_part", "")) or "—"
        header_cells.append(f'<th class="own-col-head">{own_label}（現行）<br>'
                             f'<span style="font-weight:400;font-size:0.8em;">{part}</span></th>')
        col_specs.append(own.get("specs", {}))
    else:
        header_cells.append(f'<th class="own-col-head">{own_label}（現行）<br>'
                             f'<span style="font-weight:400;font-size:0.8em;">検索失敗</span></th>')
        col_specs.append(None)

    header_cells.append(f'<th class="proposal-col-head">🏆 {own_label}提案<br>'
                         f'<span style="font-weight:400;font-size:0.8em;">次世代</span></th>')

    rows_html = ""
    for p in params:
        key = p["key"]
        label = p.get("label", key)
        cells = "".join(f"<td>{_param_cell(specs, key)}</td>" for specs in col_specs)
        prop = proposed_by_key.get(key)
        if prop:
            target = _e(prop.get("target_value", ""))
            priority = _e(prop.get("priority", ""))
            proposal_cell = (f'<td class="proposal-col"><strong>{target}</strong><br>'
                              f'<span class="badge">優先度: {priority}</span></td>')
        else:
            proposal_cell = '<td class="proposal-col">—</td>'
        rows_html += f"<tr><td>{_e(label)}</td>{cells}{proposal_cell}</tr>"

    table_html = (f'<div class="comparison-scroll"><table><tr>{"".join(header_cells)}</tr>'
                  f'{rows_html}</table></div>')

    failed_html = ""
    if failed_companies:
        names = "、".join(_e(c.get("company", "")) for c in failed_companies)
        failed_html = f'<div class="skip-box">⚠️ 検索失敗のため表に含まれていない企業: {names}</div>'

    gap_blocks = ""
    for c in other_entries:
        if c.get("lookup_status") == "error":
            continue
        gap = c.get("gap_vs_ti", {}) or {}
        if not (gap.get("advantages_of_ti") or gap.get("advantages_of_competitor") or gap.get("summary")):
            continue
        gap_blocks += f"""<div class="item"><strong>{_e(c.get('company'))}:</strong>
            TI優位点{_ul(gap.get('advantages_of_ti'))}競合優位点{_ul(gap.get('advantages_of_competitor'))}
            <em>{_e(gap.get('summary'))}</em></div>"""
    gap_html = f'<details><summary>各社の強み・弱み（詳細）</summary>{gap_blocks}</details>' if gap_blocks else ""

    s4_dict = s4 if isinstance(s4, dict) else {}
    features = "".join(
        f"<li><strong>{_e(f.get('feature'))}:</strong> {_e(f.get('rationale'))}"
        f"（想定用途: {_e(f.get('target_application'))}）</li>"
        for f in (s4_dict.get("new_feature_proposals") or []))
    features_html = (f'<div class="item"><strong>💡 追加機能案（{own_label}）:</strong>'
                      f'<ul>{features}</ul></div>') if features else ""
    closing = s4_dict.get("closing_message", "")
    closing_html = (f'<div class="highlight-box" style="border-left-color:#d69e2e;background:#fffbeb;">'
                     f'💬 {_e(closing)}</div>' if closing else "")

    return table_html + failed_html + gap_html + features_html + closing_html


def _render_comparison_section(s0, s3, s4, category_def, own_name):
    """ステージ3(競合IC比較)とステージ4(次世代スペック提案)のどちらかが失敗/スキップでも、
    使える方だけで統合比較表を描画する（部分レポート方針）。"""
    s3_ok = isinstance(s3, dict) and "error" not in s3 and "skipped" not in s3
    s4_ok = isinstance(s4, dict) and "error" not in s4 and "skipped" not in s4

    notes = ""
    if not s3_ok and isinstance(s3, dict):
        msg = s3.get("error") or s3.get("skipped")
        if msg:
            notes += f'<div class="skip-box">{"❌" if "error" in s3 else "⏩"} 競合IC比較: {_e(msg)}</div>'
    if not s4_ok and isinstance(s4, dict):
        msg = s4.get("error") or s4.get("skipped")
        if msg:
            notes += f'<div class="skip-box">{"❌" if "error" in s4 else "⏩"} 次世代スペック提案: {_e(msg)}</div>'

    if not s3_ok and not s4_ok:
        return notes or '<div class="skip-box">競合比較・次世代スペック提案のいずれも未生成です</div>'

    try:
        table = _sec_comparison_table(
            s0 if isinstance(s0, dict) else {},
            s3 if s3_ok else {}, s4 if s4_ok else {}, category_def, own_name)
    except Exception as e:
        table = f'<div class="error-box">❌ 描画エラー: {_e(e)}</div>'
    return notes + table


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
    category_def = category_labels.get(category_key, {})
    own_name = ic_schema.own_company_name()

    s4 = content.get("stage4_next_gen_proposal", {})
    exec_summary = s4.get("executive_summary", "") if isinstance(s4, dict) else ""
    exec_html = (f'<div class="card"><div class="section-title">📋 エグゼクティブサマリー'
                 f'{f" — {_e(own_name)}視点" if own_name else ""}</div>'
                 f'<div class="highlight-box">{_e(exec_summary)}</div></div>') if exec_summary else ""

    def card(title, inner, extra_class=""):
        return f'<div class="card {extra_class}"><div class="section-title">{title}</div>{inner}</div>'

    s0 = content.get("stage0_product", {})
    s3 = content.get("stage3_competitors", {})
    comparison_title = f"⚔️ 競合比較 & {own_name}提案" if own_name else "⚔️ 競合比較 & 次世代スペック提案"
    sections = [
        exec_html,
        card("📦 製品情報（TI・ベンチマーク対象）", _guard(s0, lambda s: _sec_product(s, category_labels))),
        card("📈 市場分析", _guard(content.get("stage1_market", {}), _sec_market)),
        card("🎯 キーカスタマー推定（公開情報からの推定）", _guard(content.get("stage2_key_customers", {}), _sec_customers)),
        card(comparison_title, _render_comparison_section(s0, s3, s4, category_def, own_name), "strategy"),
    ]

    cost_html = (f'<div class="cost-banner">💰 推定APIコスト ({_e(meta.get("model"))}): '
                 f'${costs.get("total_usd", 0):.4f}（約 {costs.get("total_jpy", 0):.2f} 円）</div>'
                 if costs else "")

    report_title = f"{_e(own_name)}視点: TI対抗分析レポート" if own_name else "競合分析レポート"
    html_doc = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{report_title} - {_e(part_number)}</title>
<style>{CSS}</style></head><body><div class="container">
<div class="card"><div class="section-title" style="font-size:1.5rem;border-bottom:none;">
🎯 {report_title}: {_e(part_number)}（TI, ベンチマーク対象）</div>
<span class="badge">生成日時: {dt.strftime('%Y年%m月%d日 %H:%M')}</span>
<span class="badge">モード: {_e(mode_label)}</span>
<span class="badge">📦 {_e(category_def.get('label', category_key))}</span></div>
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
