# CHANGELOG — rtocs_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [20260715_05] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_05.py`（`_04`からのコピー＋バージョン更新。`_01`〜`_04`はそのまま残置）
**変更ファイル:** `strategy_prompts.py`, `strategy_engine.py`, `strategy_report.py`, `README.md`

ツールの位置づけ再確認（RTOCSデータを真似るのではなく、他社事例研究による自社改革の創造的戦略立案支援）を踏まえたMECE改善構想（5軸: INPUT/PROCESS/OUTPUT/VALIDATION/TEMPORAL）の第1弾。**軸1「INPUT（情報収集）」の項目①**に対応:

- 「アナリスト洞察・経営陣メッセージ収集」ステージを新規追加（会社分析→直近ニュースの直後、全体で8→9ステージに）
  - セルサイドアナリストのレーティング変更・目標株価修正とその理由
  - 決算説明会(Earnings Call)・投資家向け説明会(Investor Day)でのマネジメント自身の発言
  - 市場の評価と経営陣の自己認識の間のギャップに関する所見
  - 直近ニュース収集ステージと同じgoogle-genai検索グラウンディング方式を使用
- レポートに「📊 アナリスト洞察・経営陣メッセージ」カードを新設（直近ニュースカードの直後）
- 株価の生数値だけでなく市場参加者の解釈を戦略提言に反映できるようになった（従来はyfinanceの数値とAIの知識のみに依存していた）

## [20260715_04] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_04.py`（`_03`からのコピー＋バージョン更新。`_01`〜`_03`はそのまま残置）
**変更ファイル:** `strategy_engine.py`, `requirements.txt`

実機検証で判明したバグ修正:

- 直近ニュース収集ステージが `400 google_search_retrieval is not supported. Please use google_search tool instead.` で必ず失敗する不具合を修正
  - 原因: `google-generativeai`（レガシー・Google公式に開発終了宣言済みのSDK）のグラウンディング機能は旧世代方式(`google_search_retrieval`)のみで、`gemini-2.5-flash`/`gemini-2.5-pro`が要求する新方式(`google_search`)を構成できなかった
  - 対応: ニュース収集ステージのみ、後継の統合SDK `google-genai` に切り替え、`google_search`ツールを使用するよう変更。他の7ステージ（JSONモード呼び出し）は`google-generativeai`のまま変更なし
- `requirements.txt`に`google-genai>=1.0`を追加（`google-generativeai`と共存）

## [20260715_03] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_03.py`（`_02`からのコピー＋バージョン更新。`_01`/`_02`はそのまま残置）
**変更ファイル:** `strategy_prompts.py`, `strategy_engine.py`, `strategy_report.py`

実データでの試用フィードバックに基づく改善:

- 「課題分析」カードの根拠(evidence)を単一文字列から配列スキーマに変更し、1項目ずつ改行して表示するよう修正（読点区切りで1行に詰め込まれ読みにくかった問題を解消）
- 戦略パイプラインに「直近ニュース収集」ステージを新規追加（会社分析の直後、全体で7→8ステージに）。Geminiの検索グラウンディング機能を使い、対象企業の英語・日本語・中国語（簡体字）の名称表記を自動推定した上で、直近12ヶ月以内の重要ニュース（決算・M&A・経営陣交代・規制動向・地政学リスク等）を検索・要約する。結果は課題分析・戦略策定にも自動的に反映される
- レポートに「📰 直近ニュース」カードを新設（会社分析の直後）
- 検索グラウンディングは`google-generativeai`（Google公式に非推奨化済み）のベストエフォート実装のため、モデル世代によっては機能しない可能性がある旨をREADMEに明記

## [20260715_02] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_02.py`（`_01`からのバグ修正版。`_01`はそのまま残置）

- 傾向分析タブの「キーワードの年次トレンド比較」で `NameError: name 'kw' is not defined` が発生する不具合を修正（キーワード頻度上位を取り出すリスト内包表記の誤り）
- Streamlitの `use_container_width` 非推奨引数（2025-12-31以降削除予定）を `width='stretch'` に置換

## [20260715_01] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_01.py`, `rtocs_index.py`, `strategy_engine.py`, `strategy_prompts.py`, `strategy_report.py`

- 既存の検索用ダッシュボード（`rtocs_dashboard_20260502_04.py`）を土台に、3タブ構成の統合ダッシュボードを追加
  - 📋 一覧・検索（従来機能を踏襲）
  - 📈 傾向分析: 業界分布の年次推移、キーワード頻度・トレンド、地域ミックス、複数回登場企業の一覧、AI俯瞰総評（Geminiによる全ケース横断コメント）
  - 🎯 戦略分析: 企業名を1つ入力すると、会社分析→株式市場分析(yfinance)→業界・競合分析→類似RTOCS事例選定→他業種事例分析→課題分析→戦略策定、を自動実行し1枚のHTMLレポートを生成
- `rtocs_index.py`: `data/JSON_lake` から軽量なケース一覧（`data/rtocs_index.json`）を増分構築する共通部品。傾向分析と戦略分析の類似事例検索（LLM-as-retriever方式）の両方が参照する
- コスト集計・失敗時の部分レポート継続（既存organizerと同じ方針）を踏襲

## [20260711_01] - 2026-07-11

**変更ファイル:** `rtocs_organizer_202060517_01.py` → `rtocs_organizer_20260711_01.py`（リネーム）

- ファイル名を他ツールと同じ `yyyymmdd_連番` 命名規則に統一

## [202060517_01] - 2026-07-10

**追加ファイル:** `rtocs_organizer_202060517_01.py`, `requirements.txt`, `README.md`

- `selenium` 未インストール環境で `ModuleNotFoundError` の生Tracebackが表示される問題を修正。import部分を `try/except` で囲み、`pip install -r requirements.txt` を促す日本語メッセージを表示するよう変更
- `requirements.txt`（selenium, google-generativeai, PyMuPDF）を新規追加
- セットアップ手順（Chromeのリモートデバッグ起動、GEMINI_API_KEY設定、category_map.jsonの準備）を記載したREADME.mdを新規追加
