# PowerPoint Translator (Gemini API)

PowerPointファイル（.pptx）をGoogle Gemini APIで翻訳し、**フォント・文字サイズ・太字・
文字色・段落の配置・表・スピーカーノートの書式をそのまま保持**したまま翻訳版を生成する
デスクトップツール（tkinter GUI）。

翻訳は「run（文字書式が同じひとかたまり）」単位で行い、run のテキストだけを差し替えるため、
スライドのレイアウトや装飾は一切変化しない。

> **フォルダ名とファイル名の接頭辞が違う点に注意。**
> フォルダは `ppt_translator`、スクリプトは `ppt_translation_yyyymmdd_NN.py`。
> 起動用バッチのワイルドカードは `ppt_translation_????????_??.py` である。

## 必要要件

- Python 3.9以上
- `python-pptx`（`requirements.txt` に記載）
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
  └── Powerpoint\
      └── ppt_translator\
          └── ppt_translation_20260812_01.py   ← ここから見て common は「2つ上」
  ```

  1つ上・2つ上・3つ上を順に探すため、移行前の置き場所（`PythonScripts\excel\`）に
  置いた場合も同じように見つかる。

- 使用モデルは **`gemini-2.5-flash` 固定**。環境変数 `GEMINI_MODEL` で変更できる。

  ```
  setx GEMINI_MODEL "gemini-2.0-flash"
  ```

  20260309_03 までは起動時に `genai.list_models()` で使用可能モデルを自動検出していたが、
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

2. `run_ppt_translator.bat` をダブルクリックする。初回は仮想環境(venv)の作成と
   依存パッケージのインストールが自動実行される（2回目以降は起動のみ）。
   フォルダ内に `ppt_translation_yyyymmdd_NN.py` が複数存在する場合は、
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

4. スクリプトを実行する（`ppt_translation_yyyymmdd_NN.py` の最新版）。

   ```
   python ppt_translation_20260812_01.py
   ```

### 使い方

1. 「ファイル選択」から翻訳したい `.pptx` を選び、翻訳先言語（日本語／英語／中国語簡体字）を
   選んで「翻訳開始」を押す。
2. 完了すると同じフォルダに `元ファイル名_gemini_japanese.pptx` のように保存される
   （英語なら `_gemini_english.pptx`、中国語簡体字なら `_gemini_chinese.pptx`）。
   元のファイルは変更されない。

## 処理の仕組み（20260812_01 時点）

1. 選択された `.pptx` を出力先へコピーし、そのコピーを `python-pptx` で開く
   （元ファイルには一切書き込まない）。
2. 全スライドを走査して、次の3か所から run 単位でテキストを集める。
   - 図形（テキストボックス・プレースホルダ）の各段落の run
   - 表のセル内の各段落の run
   - スピーカーノートの各段落の run

   このとき `is_translatable()` で、空文字・記号のみ（`•` `-` `*` 等）・数字のみ・
   2文字以下のものは翻訳対象から除外する。
3. 集めたテキストを10件ずつバッチにまとめ、Gemini APIへ並列（最大3スレッド）で
   翻訳リクエストを送信する。呼び出しは共通モジュール `gemini_client.py` 経由で行い、
   直接呼び出しが失敗した場合は自宅PCのプロキシへ自動的にフォールバックする
   （20260812_01 以降）。バッチごとに最大3回リトライし、3バッチ連続でエラーになった
   場合は処理を強制中断する（フェイルファスト）。
4. 翻訳結果は `run.text` を差し替える形で書き戻す。run の書式（サイズ・太字・色）と
   段落の配置は python-pptx 側でそのまま保持されるため、レイアウトは変化しない。
   翻訳先が日本語のときのみ、`run.font.name` を `游ゴシック` に設定する。
5. 処理の足跡と通信エラーの詳細は `translation_debug.log`（実行フォルダ）に記録され、
   コンソールにも出力される。

## 既知の制限・仕様

- **対応形式は `.pptx` のみ**（旧形式 `.ppt` は非対応）。
- 出力ファイル名は `_gemini_japanese.pptx` のように**言語名がそのまま入る**
  （`pdf_translator` の `_ja.pdf` のような2文字コードではない）。既存の運用に
  影響するため、依頼が無い限り変更しない。
- run 単位で翻訳するため、1つの文が書式の切れ目で複数 run に分割されている場合は
  文脈が失われ、不自然な訳になることがある（PowerPointの構造上の制約）。
- SmartArt・グラフ内のテキスト・画像内の文字は翻訳対象外（python-pptx から run として
  取得できないため）。
- 翻訳文が元のテキストボックスに収まりきらない場合、自動縮小は行わない。

## トラブルシューティング

- **`Gemini認証情報が設定されていません`**: `GEMINI_API_KEY` と `GEMINI_PROXY_URL` の
  どちらも設定されていない。どちらか一方を設定した後、ターミナル／コマンドプロンプトを
  **開き直してから**実行する（`setx` は起動済みのウィンドウには反映されない）。
- **`Gemini共通モジュール(gemini_client.py)を読み込めませんでした`**: エラーメッセージに
  「探索したパス」が表示されるので、そこに `gemini_client.py` を置くか、環境変数
  `GEMINI_COMMON_DIR` でフォルダを指定する。
- **翻訳の最初のバッチだけ極端に遅い**: 直接呼び出しのタイムアウト（15秒）を待ってから
  プロキシへ切り替えているため。2バッチ目以降は速くなる（仕様どおりの挙動）。
- **`対象のPowerPointファイルが別のアプリで開かれています`**: PowerPointで対象ファイルを
  閉じてから再実行する。
- **`Gemini APIへの通信が3回連続で失敗しました`**: ネットワーク接続、またはAPIの
  レート制限を確認する。詳細は `translation_debug.log` を参照。
- **`No file matching ppt_translation_yyyymmdd_NN.py was found.`**: バッチファイルと
  同じフォルダにスクリプトが無い。フォルダ名（`ppt_translator`）とファイル名の接頭辞
  （`ppt_translation`）は違うので、ファイル名を変えていないか確認する。

## テスト

```
pip install python-pptx
python3 tests/test_ppt_translation_20260812_01.py
```

実際のGemini APIには接続せず、偽の `gemini_client` を注入してpayloadを検証する。
`python-pptx` は本物を使い、合成PPTX（タイトル・本文・表・スピーカーノート）を生成して
翻訳の書き戻しまでエンドツーエンドで確認する。旧版 `ppt_translation_20260309_03.py` と
新版に同じ翻訳文を与えて出力を比較し、テキスト・書式が完全一致することも検証している。
