# Word Translator (Gemini API)

Wordファイル（.docx）をGoogle Gemini APIで翻訳し、**フォント・文字サイズ・太字・文字色・
段落の配置・表の書式をそのまま保持**したまま翻訳版を生成するデスクトップツール（tkinter GUI）。

翻訳は「run（文字書式が同じひとかたまり）」単位で行い、run のテキストだけを差し替えるため、
文書のレイアウトや装飾は一切変化しない。

> **フォルダ名とファイル名の接頭辞が違う点に注意。**
> フォルダは `word_translator`、スクリプトは `word_translation_yyyymmdd_NN.py`。
> 起動用バッチのワイルドカードは `word_translation_????????_??.py` である。

## 必要要件

- Python 3.9以上
- `python-docx`（`requirements.txt` に記載）
- 共通モジュール `gemini_client.py`（[gemini-common-tools](https://github.com/ochi1216/gemini-common-tools)）
- 以下の環境変数のうち**どちらか一方以上**
  - `GEMINI_API_KEY` … Gemini APIキー（直接呼び出し用）
  - `GEMINI_PROXY_URL` … 自宅PCプロキシのURL（直接呼び出しが失敗したときのフォールバック先）

### Gemini API の呼び出し経路について（20260812_01 以降）

会社PCからGemini APIへの直接アクセスが遮断された（2026-08-10頃）ため、共通モジュール
`gemini_client.py` 経由で呼び出す方式に移行した。**まず直接呼び出しを試し、失敗したら自宅PCの
プロキシへ自動的にフォールバックする**ため、ツール側で経路を意識する必要はない。

- `gemini_client.py` は上位ディレクトリの `common` フォルダから自動的に探される
  （会社PCの配置では、本スクリプトから見て「2つ上」の `PythonScripts\common\`）。
  別の場所に置いている場合は環境変数 `GEMINI_COMMON_DIR` でフォルダを指定できる。

  ```
  PythonScripts\
  ├── common\
  │   └── gemini_client.py
  └── word\
      └── word_translator\
          └── word_translation_20260812_01.py   ← ここから見て common は「2つ上」
  ```

  1つ上・2つ上・3つ上を順に探すため、`common` を1つ上に置いた場合も同じように見つかる。

- 使用モデルは **`gemini-2.5-flash` 固定**。環境変数 `GEMINI_MODEL` で変更できる。

  ```
  setx GEMINI_MODEL "gemini-2.0-flash"
  ```

  20260306_01 までは起動時に `genai.list_models()` で使用可能モデルを自動検出していたが、
  これはネットワークアクセスを伴うため遮断下では必ず失敗し、**ツールが起動すらできなく
  なる**ため廃止した。将来モデル名が変わったときは、上の環境変数で切り替えるか
  スクリプトの `GEMINI_MODEL_NAME` を更新する。

- 遮断されている環境では、**最初のバッチだけ**直接呼び出しのタイムアウト（15秒）を待つぶん
  遅くなることがある。一度失敗すると以降はプロキシ直行になるため、2バッチ目以降は影響しない。
  **これは仕様どおりの挙動で、不具合ではない。**

## セットアップ手順

### Windows（バッチファイルで起動する場合）

1. 環境変数を設定する（コマンドプロンプトで実行後、一度開き直す）。
   **どちらか一方だけでも動作する**（プロキシ専用構成も可）。

   ```
   setx GEMINI_API_KEY "your-api-key"
   setx GEMINI_PROXY_URL "https://xxxx.ngrok-free.dev"
   ```

2. `run_word_translator.bat` をダブルクリックする。初回は仮想環境(venv)の作成と
   依存パッケージのインストールが自動実行される（2回目以降は起動のみ）。
   フォルダ内に `word_translation_yyyymmdd_NN.py` が複数存在する場合は、
   ファイル名が最も新しいもの（＝最新バージョン）を自動的に起動する。

### 手動セットアップ（macOS/Linux/Windows共通）

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. 環境変数を設定する（`GEMINI_API_KEY` / `GEMINI_PROXY_URL` のどちらか一方以上）。

   ```
   # macOS/Linux
   export GEMINI_API_KEY="your-api-key"
   export GEMINI_PROXY_URL="https://xxxx.ngrok-free.dev"

   # Windows (PowerShell)
   setx GEMINI_API_KEY "your-api-key"
   setx GEMINI_PROXY_URL "https://xxxx.ngrok-free.dev"
   ```

3. 共通モジュール `gemini_client.py` を、上位ディレクトリの `common` フォルダに配置する
   （または環境変数 `GEMINI_COMMON_DIR` で場所を指定する）。

4. スクリプトを実行する（`word_translation_yyyymmdd_NN.py` の最新版）。

   ```
   python word_translation_20260812_01.py
   ```

### 使い方

1. 「ファイル選択」から翻訳したい `.docx` を選び、翻訳先言語（日本語／英語／中国語簡体字）を
   選んで「翻訳開始」を押す。
2. 完了すると同じフォルダに `元ファイル名_gemini_japanese.docx` のように保存される
   （英語なら `_gemini_english.docx`、中国語簡体字なら `_gemini_chinese.docx`）。
   元のファイルは変更されない。

## 処理の仕組み（20260812_02 時点）

1. 選択された `.docx` を出力先へコピーし、そのコピーを `python-docx` で開く
   （元ファイルには一切書き込まない）。
2. 文書を走査して、次の2か所から run 単位でテキストを集める。
   - 本文の各段落（`doc.paragraphs`）の run
   - 表のセル内の各段落（`doc.tables`）の run

   このとき `is_translatable()` で、空文字・記号のみ（`•` `-` `*` 等）・数字のみ・
   2文字以下のものは翻訳対象から除外する。
3. 翻訳開始前に、読み込み元と保存先が別のアプリ（Wordなど）で開かれていないかを
   確認する。開かれている場合はその場で案内を出して中止する（20260812_02 以降）。
4. 集めたテキストを10件ずつバッチにまとめ、Gemini APIへ並列（最大3スレッド）で
   翻訳リクエストを送信する。呼び出しは共通モジュール `gemini_client.py` 経由で行い、
   直接呼び出しが失敗した場合は自宅PCのプロキシへ自動的にフォールバックする
   （20260812_01 以降）。バッチごとに最大3回リトライし、3バッチ連続でエラーになった
   場合は処理を強制中断する（フェイルファスト。20260812_02 以降）。
   バッチを1つ終えるごとにプログレスバーが進む。
5. 翻訳結果は `run.text` を差し替える形で書き戻す。run の書式（サイズ・太字・色）と
   段落の配置・スタイルは python-docx 側でそのまま保持されるため、レイアウトは変化しない。
   翻訳先が日本語のときのみ、`run.font.name` を `游ゴシック` に設定する。
6. 処理の足跡と通信エラーの詳細は `translation_debug.log`（実行フォルダ）に記録され、
   コンソールにも出力される（20260812_02 以降）。

## 既知の制限・仕様

**20260306_01 から続く既存の仕様**である。実機で気になったときに「更新のせいではない」と
切り分けられるよう記載しておく。

- **翻訳対象は本文の段落と表のセルのみ。** ヘッダー／フッター・脚注・テキストボックス内の
  文字は翻訳されない（`doc.paragraphs` と `doc.tables` しか走査していないため）。
- **対応形式は `.docx` のみ。** ファイル選択ダイアログの候補に `.doc` が並ぶが、
  `python-docx` は旧形式 `.doc` を開けないため、選ぶとエラーになる。
- 日本語フォントの指定は `run.font.name = '游ゴシック'` のみで、Wordの仕様上これだけでは
  日本語文字に効かない場合がある（`w:eastAsia` の設定が別途必要なため）。
- **フェイルファストで中断したとき、出力先には「翻訳前の複製」が残る。** 翻訳を始める前に
  元ファイルをコピーしてから書き換える方式のため。中途半端に翻訳された文書にはならないが、
  `_gemini_japanese.docx` が英語のまま残るので、失敗した回のファイルは削除してよい
  （PowerPoint版も同じ挙動）。
- 出力ファイル名は `_gemini_japanese.docx` のように**言語名がそのまま入る**
  （`pdf_translator` の `_ja.pdf` のような2文字コードではない）。既存の運用に影響するため、
  依頼が無い限り変更しない。
- run 単位で翻訳するため、1つの文が書式の切れ目で複数 run に分割されている場合は
  文脈が失われ、不自然な訳になることがある（Wordの構造上の制約）。

## トラブルシューティング

- **`Gemini認証情報が設定されていません`**: `GEMINI_API_KEY` と `GEMINI_PROXY_URL` の
  どちらも設定されていない。どちらか一方を設定した後、ターミナル／コマンドプロンプトを
  **開き直してから**実行する（`setx` は起動済みのウィンドウには反映されない）。
- **`Gemini共通モジュール(gemini_client.py)を読み込めませんでした`**: エラーメッセージに
  「探索したパス」が表示されるので、そこに `gemini_client.py` を置くか、環境変数
  `GEMINI_COMMON_DIR` でフォルダを指定する。
- **翻訳の最初のバッチだけ極端に遅い**: 直接呼び出しのタイムアウト（15秒）を待ってから
  プロキシへ切り替えているため。2バッチ目以降は速くなる（仕様どおりの挙動）。
- **一部の段落だけ英語のまま残る**: そのバッチが3回とも通信に失敗している。
  `translation_debug.log` に該当バッチのエラーが残っているので確認する。
- **`Gemini APIへの通信が3回連続で失敗しました`**: ネットワーク接続、またはAPIの
  レート制限を確認する。詳細は `translation_debug.log` を参照。
- **`対象のWordファイルが別のアプリで開かれています` / `以前に作成した翻訳ファイルが
  開かれています`**: 該当ファイルをWordで閉じてから再実行する。翻訳を始める前に検知
  するので、待たされることはない。
- **`No file matching word_translation_yyyymmdd_NN.py was found.`**: バッチファイルと
  同じフォルダにスクリプトが無い。フォルダ名（`word_translator`）とファイル名の接頭辞
  （`word_translation`）は違うので、ファイル名を変えていないか確認する。

## テスト

```
pip install python-docx
python3 tests/test_word_translation_20260812_02.py
python3 tests/test_word_translation_20260812_01.py
```

実際のGemini APIには接続せず、偽の `gemini_client` を注入してpayloadを検証する。
`python-docx` は本物を使い、合成DOCX（見出し・本文・書式違いの複数run・表）を生成して
翻訳の書き戻しまでエンドツーエンドで確認する。各版に同じ翻訳文を与えて出力を比較し、
`20260306_01` / `20260812_01` / `20260812_02` の3版でテキスト・書式が完全一致することも
検証している（＝更新でWord出力が変わっていないことの証拠）。
