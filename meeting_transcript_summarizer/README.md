# 会議録画 文字起こし・要約ツール

オンライン会議の画面キャプチャー録画(.mkv)から音声を抽出し、文字起こし・要約(議事録化)を行うツール。Tkinter製のGUIから操作する。

## できること

1. `.mkv`録画から音声を抽出(ffmpeg)
2. 文字起こし(GUIのラジオボタンで方式を選択)
   - **クラウド(Gemini API)**: 簡易話者分離あり(話者A/B…)。音声がGeminiへ送信される。長時間の録画でも1回のAPI呼び出しでは出力が途中で打ち切られることがあるため、音声を`chunk_minutes`単位(既定10分)に分割して順に処理する。
   - **ローカル(faster-whisper)**: 話者ラベルなし。音声は外部に送信されない。
3. 主な言語(日本語/English/自動判定)をGUIのラジオボタンで指定可能。Geminiへのプロンプトに反映するほか、faster-whisperの`language`引数に渡すことで認識精度を高める。
4. 要約(議事録化) — 常にGemini APIを使用(文字起こし後のテキストのみ送信)
   - 会議概要・主な議題・決定事項・アクションアイテム・次回までのTODOをMarkdown・構造化データ(JSON)・HTMLの3形式で出力
   - 処理完了時、HTML版の要約を既定のブラウザで自動的に開く

## セットアップ

### 1. 依存パッケージ

```bash
pip install -r requirements.txt
```

### 2. ffmpeg

音声抽出に`ffmpeg`コマンドを使用する。事前にインストールし、PATHが通っていることを確認する。

### 3. 設定ファイル

`config.example.json`を`config.json`としてコピーし、値を編集する。

```bash
cp config.example.json config.json
```

| キー | 説明 |
| --- | --- |
| `gemini_api_key` | Gemini APIキー。環境変数`GEMINI_API_KEY`が設定されている場合はそちらが優先される |
| `gemini_model` | 文字起こし・要約に使うGeminiモデル名 |
| `gemini_max_output_tokens` | Gemini文字起こし1チャンクあたりの最大出力トークン数 |
| `chunk_minutes` | クラウドモードで音声を分割する単位(分)。長い録画で出力が途中で切れる場合はこの値を小さくする |
| `language` | 既定の主な言語(`ja`/`en`/`auto`)。GUI上でも会議ごとに変更可能 |
| `whisper_model_size` | ローカルモードで使うfaster-whisperのモデルサイズ(`large-v3`等) |
| `whisper_device` | faster-whisperの実行デバイス(`cpu`/`cuda`) |
| `whisper_compute_type` | faster-whisperの演算精度(`int8`等) |
| `output_dir` | 出力先の親ディレクトリ |

`config.json`はAPIキーを含むためGit管理対象外(`.gitignore`参照)。

## 実行方法

### Windows(バッチファイル、推奨)

`run_meeting_transcript_summarizer.bat` をダブルクリックする。フォルダ内の`meeting_transcript_summarizer_*.py`のうち、ファイル名(YYYYMMDD_連番)が最も新しいものを自動的に選んで起動するため、バージョンアップで本体スクリプトが増えてもバッチファイル自体を変更する必要はない。

### 直接起動する場合

```bash
python meeting_transcript_summarizer_20260716_04.py
```

(上記はいずれもGUIが起動する。`.mkv`ファイルを選択し、文字起こし方式(クラウド/ローカル)を選んで「実行」を押す。)

## 出力

`output/<会議ファイル名>_<実行日時>/` 配下に以下を出力する。

- `transcript.md` / `transcript.json`: 文字起こし結果
- `summary.md` / `summary.json` / `summary.html`: 要約(議事録)。`summary.html`は処理完了時に自動的にブラウザで開かれる
- `transcript_raw_gemini_response.txt`: (クラウドモードのみ)Geminiからの応答全文。文字起こしの書式に問題があった場合の確認・調整用

## 既知の制約

- 要約ステップは文字起こし方式に関わらず常にGemini APIを使用する(ローカルモードは音声のみ外部送信を避ける設計であり、テキストの要約はクラウドを利用する)。
- クラウドモードはチャンクごとに独立してGeminiへ送信するため、チャンクをまたいで話者ラベル(話者A/B…)が入れ替わる可能性がある(直前チャンク末尾の文字起こしをヒントとして渡してはいるが、完全な一致は保証されない)。
- ローカルモードでは話者分離を行わないため、発言者ラベルは付与されない。
- 会議音声・文字起こし内容には機密情報が含まれ得るため、出力ファイルの取り扱いには注意すること。
- HTML要約の自動起動は既定のブラウザに依存するため、環境によっては開かない場合がある(その場合はログに理由が表示されるので、`summary.html`を手動で開くこと)。

## バージョン管理

このプロジェクトはリポジトリ全体の開発ルール(`README.md`参照)に従う。ファイル名は`meeting_transcript_summarizer_yyyymmdd_連番.py`とし、更新時は旧バージョンを残す。変更点は`CHANGELOG.md`に記録する。
