# -*- coding: utf-8 -*-
"""5ステージパイプライン用 Geminiプロンプト定数集（DESIGN_analog_ic_se_strategy_organizer.md 8章）。

全ステージ共通の約束事:
- 出力は指定JSONのみ（前置き・解説テキスト禁止）
- 事実には必ず出典・確度を明記する（rtocs_organizerの「(要確認)」より一段厳格な fact 構造。
  ic_schema.make_fact/normalize_fact 参照）
- ステージ0〜3はGoogle Search Grounding（generate_grounded_json）を使用し、
  JSONモードとは併用できないため、プロンプト側にJSON形式での出力を明記する
"""

SYSTEM_PREFIX = """あなたはアナログ・電源半導体業界に精通したシニアシステムエンジニア／競合分析の専門家です。
事実の正確性を最優先し、断定できない情報には必ずfact構造の confidence を "medium" または "low" にしてください。
出力は指定されたJSONフォーマットのみを直接出力し、前置きや解説は一切書かないでください。
JSON内の文字列にダブルクォーテーションが含まれる場合は必ずエスケープしてください。
根拠のない企業名・数値を創作しないでください。分からない場合は空文字・空配列・confidence="low"で正直に示してください。

fact構造（事実値を表す共通フォーマット）:
{{"value": <実際の値>, "unit": "<単位>", "source_type": "TI_official|third_party|llm_estimate|user_input",
  "source_detail": "<出典の詳細>", "source_url": "<出典URL>", "confidence": "high|medium|low",
  "as_of": "<YYYY-MM-DD>", "note": "<補足>"}}
"""

# ステージ0: 製品取り込み（Google Search Grounding使用）
STAGE0_PRODUCT = SYSTEM_PREFIX + """
# Task
検索機能を使って、型番「{part_number}」（Texas Instruments製）の製品情報をTI公式サイト（`site:ti.com {part_number}`
のようなクエリで検索）から調査してください。{category_hint_note}

カテゴリは以下のクローズドリストから、公式カタログ上の分類に最も近いものを1つ選んでください:
{category_list}

選んだカテゴリの比較パラメータ一覧は以下の通りです。該当する項目のみ、分かる範囲でkey_specsに埋めてください
（全項目埋める必要はありません。不明な項目は省略してよい）。
{category_params_overview}

# Output Format (JSON)
{{
  "part_number": "{part_number}",
  "manufacturer": "Texas Instruments",
  "category": <fact構造。valueはカテゴリキー文字列>,
  "product_family": "製品ファミリー名（分かれば）",
  "short_description": "製品の要点(100文字程度)",
  "applications": [<fact構造。valueはアプリケーション用途名の文字列>],
  "datasheet_url": <fact構造。valueはデータシートPDFのURL>,
  "application_notes": [{{"title": "...", "url": "...", "source_type": "TI_official", "confidence": "medium"}}],
  "key_specs": {{"<category_schemaのkey>": <fact構造>, "...": "..."}},
  "grounding_note": "検索で十分な情報が得られなかった場合の注記（問題なければ空文字）"
}}
"""

# ステージ1: 市場分析（Google Search Grounding使用）
STAGE1_MARKET = SYSTEM_PREFIX + """
# Task
以下のアプリケーション用途それぞれについて、検索機能を使って第三者調査機関
（Yole Développement, TechInsights, Omdia, S&P Global, Fortune Business Insights,
MarketsandMarkets等）が公表している市場規模・CAGRを調べてください。
TI自身が発信している成長ドライバーの主張がある場合は ti_stated_growth_driver として
別枠で保持し、第三者データと混同しないでください。

# 対象製品
型番: {part_number} / カテゴリ: {category}
アプリケーション用途: {applications_json}

# Output Format (JSON)
{{
  "market_estimates": [
    {{
      "application": "アプリケーション用途名",
      "market_size": <fact構造。valueは市場規模、unitは通貨・年を含む文字列（例: "USD Billion (2025)"）>,
      "cagr": <fact構造。valueはCAGR数値、unitは対象期間（例: "% (2025-2030)"）>,
      "ti_stated_growth_driver": <fact構造。valueはTI自身が主張する成長ドライバー（無ければvalue=""）>,
      "growth_drivers": ["成長ドライバー1", "成長ドライバー2"],
      "risks": ["リスク1"]
    }}
  ],
  "overall_market_view": "総括コメント(150文字程度)",
  "grounding_note": "十分な情報が得られなかった場合の注記（問題なければ空文字）"
}}
"""

# ステージ2: キーカスタマー推定（Google Search Grounding使用、非公開情報は扱わない）
STAGE2_KEY_CUSTOMERS = SYSTEM_PREFIX + """
# Task
非公開の顧客情報・営業情報は一切扱わないでください。以下の公開情報のみを根拠に、
「{category}」カテゴリでTI製品（型番: {part_number}）を採用する可能性が高い企業を推定してください:
- Google Patentsなどの特許引用関係
- TechInsights / System Plus Consulting 等の公開テカルダウン（分解調査）記事
- TI自身が公表した採用事例・プレスリリース・ケーススタディ

根拠のない企業名を創作しないでください。見つからない場合は無理に埋めず、空配列にしてください。

# 対象製品
型番: {part_number} / カテゴリ: {category}
アプリケーション用途: {applications_json}

# Output Format (JSON)
{{
  "estimated_key_customers": [
    {{"company": "企業名", "region": "US/EU/JP/CN/APAC_other等",
      "evidence_type": "patent_citation/teardown_report/ti_case_study等",
      "evidence_summary": "根拠の要約(100文字程度)", "evidence_source_url": "出典URL",
      "confidence": "high/medium/low"}}
  ],
  "customer_segments": ["顧客セグメントの傾向1", "傾向2"],
  "disclaimer": "本ステージは公開情報に基づく推定であり、TIとの契約関係を示すものではありません。",
  "grounding_note": "根拠が見つからなかった場合の注記（問題なければ空文字）"
}}
"""

# ステージ3: 競合IC比較（会社1社ごとにGoogle Search Groundingで個別呼び出し）
STAGE3_COMPETITOR = SYSTEM_PREFIX + """
# Task
検索機能を使って、{company}（{region}、{company_type}）の製品ラインアップから、
TI製品「{part_number}」（カテゴリ: {category}、主要仕様: {ti_key_specs_summary}）と
最も比較可能な近似品番を1つ検索してください。

以下のパラメータ一覧に沿って、分かる範囲でspecsを埋めてください（不明な項目は省略可）:
{category_params_overview}

TI製品と比較した際の優位点・劣位点も簡潔にまとめてください。

# Output Format (JSON)
{{
  "company": "{company}",
  "region": "{region}",
  "comparable_part": "最も近い競合品番（見つからなければ空文字）",
  "specs": {{"<category_schemaのkey>": <fact構造>, "...": "..."}},
  "gap_vs_ti": {{
    "advantages_of_ti": ["TI製品が優れている点1"],
    "advantages_of_competitor": ["競合製品が優れている点1"],
    "summary": "総括(80文字程度)"
  }},
  "source_url": "参照した製品ページ・データシートURL",
  "grounding_note": "十分な情報が得られなかった場合の注記（問題なければ空文字）"
}}
"""

# ステージ4: 対抗デバイス スペック提案（JSONモード、grounding不要 = 既存事実の統合のため）
#
# 本ツールの主語は自社「{own_company}」である。TIはあくまでベンチマーク対象（打ち破るべき相手）で
# あり、他の競合企業は市場理解のための参考情報にすぎない。「TIが次に何を作るべきか」ではなく
# 「自社がTI・他競合の双方に勝つために何を作るべきか」を提案すること。
STAGE4_NEXT_GEN = SYSTEM_PREFIX + """
# Task
これまでの市場分析・キーカスタマー推定・競合IC比較の結果を統合し、自社「{own_company}」が
TI製品「{part_number}」（カテゴリ: {category}、TIはベンチマーク対象）および他の競合企業を
上回るために開発すべきデバイスのスペック・追加機能を、根拠・実現性リスク・優先度付きで
提案してください。target_valueは「TIに勝てば十分」ではなく、ステージ3の競合IC比較に
登場した**全企業（TI含む）の中で最も優れた値を上回る**ことを狙って設定してください。
自社に現行対抗品が無いカテゴリの場合は、新規参入する場合に狙うべき目標値として提案してください。

各提案のparameter_keyは、必ず下記パラメータ一覧のkeyのいずれか1つを使ってください
（比較表の行と突き合わせるため、自由な名称は使わないこと）。

# このカテゴリの比較パラメータ一覧
{category_params_overview}

# ステージ0: 製品情報（TI）
{stage0_json}

# ステージ1: 市場分析
{stage1_json}

# ステージ2: キーカスタマー推定
{stage2_json}

# ステージ3: 競合IC比較（自社「{own_company}」の現状を含む）
{stage3_json}

# Output Format (JSON)
{{
  "executive_summary": "自社「{own_company}」の経営者が3分で理解できる全体総括(300文字以内)。"
                        "TI・競合に対してどう勝つかを明確に述べること",
  "proposed_specs": [
    {{
      "parameter_key": "上記パラメータ一覧のkeyのいずれか1つ",
      "kpi_label": "そのパラメータの日本語ラベル(パラメータ一覧のlabelと一致させる)",
      "current_ti_value": "現行TI製品の値",
      "target_value": "自社が狙うべき提案目標値(TI・全競合の最良値を上回る値)",
      "rationale": "根拠(どの分析結果に基づくか)(150文字程度)",
      "competitive_gap_addressed": "どの競合(TI含む)とのギャップを埋める・上回るか",
      "feasibility_risk": "実現性リスク(100文字程度)",
      "priority": "高/中/低"
    }}
  ],
  "new_feature_proposals": [
    {{"feature": "追加機能案", "rationale": "根拠", "target_application": "想定用途"}}
  ],
  "closing_message": "越智さんへの締めの一言(100文字程度)"
}}
提案は3〜5件程度にまとめてください。
"""

# ポートフォリオ俯瞰タブ用: 蓄積製品を横断したAI総評（JSONモード、grounding不要）
PORTFOLIO_COMMENTARY = SYSTEM_PREFIX + """
# Task
以下は分析済みTI製品のケースライブラリ一覧（1行=1製品）と、越智さんが調査した競合企業データベースの
サマリーです。ポートフォリオ全体を俯瞰し、シニアシステムエンジニア向けの「傾向総評」をMarkdown形式で
書いてください。

必ず含める観点:
1. カテゴリの偏り: どの製品カテゴリが多く/少なく分析されているか
2. 競合ギャップの傾向: どのカテゴリ・地域の競合が手薄/強いか
3. 次世代スペック提案の傾向: 優先度の高いKPIに共通するパターン
4. 今後分析すべき製品・カテゴリの提案

# 分析済み製品ケースライブラリ
{case_index}

# 競合企業データベース サマリー
{competitor_summary}

# Output Format (JSON)
{{
  "commentary_markdown": "Markdown形式の総評(見出し##を使い、800〜1500文字程度)"
}}
"""
