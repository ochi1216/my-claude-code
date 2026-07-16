# Project Status

## 1. Project Overview

- **プロジェクト名**: 会議録画 文字起こし・要約ツール開発（meeting-recording-transcription）
- **プロジェクトの目的**: オンライン会議の画面キャプチャー録画（.mkv形式）から音声を取り出して文字起こしを行い、その内容を要約（議事録化）するツールを開発する。
- **主な利用者**: 未確認
- **実行環境**: 未確認

## 2. Repository Structure

このリポジトリは単一プロジェクト専用ではなく、複数の独立したPythonツールを収めたフラットな集合体である。本プロジェクト（会議録画の文字起こし・要約）専用のファイルは本セッション時点でまだ存在しない。

- `README.md`: リポジトリ全体の概要と開発ルール（バージョン管理・命名規則）
- `CLAUDE.md`: Claude Code Webのセッション管理ルール（本セッションで新規作成）
- `docs/PROJECT_STATUS.md`: 本ファイル。プロジェクト状態の記録
- `docs/SESSION_HISTORY.md`: セッション履歴の記録
- `docs/NEXT_TASK.md`: 次セッションへの引継ぎタスク
- `HANDOVER_youtube_summary_list.md`: youtube_summary_listプロジェクトの引継ぎ資料（別プロジェクト、本プロジェクトとは無関係）
- `youtube_summary_list_YYYYMMDD_NN.py`: YouTube動画要約ツール（別プロジェクト、本プロジェクトとは無関係）
- `po_database_organizer/`: 別プロジェクト（本プロジェクトとは無関係）
- `rtocs_organizer/`: 別プロジェクト（本プロジェクトとは無関係。Gemini API (`google-generativeai`/`google-genai`) による要約処理の実装例あり）
- `shareflex_dashboard/`: 別プロジェクト（本プロジェクトとは無関係）

本プロジェクト専用のフォルダ・ファイルは未作成。実装を開始する際は、リポジトリの慣習（ツール専用フォルダ + `README.md` + `CHANGELOG.md` + `requirements.txt` + バージョン管理された命名規則）に従うことが想定されるが、正式決定は未確認。

## 3. Current Functions

- 現時点で実装済みの機能はない（未着手）。
- 音声・動画・.mkv・ffmpeg・Whisper等の処理は、リポジトリ内に既存の実装例なし（本プロジェクトが最初の着手となる）。

## 4. Confirmed Specifications

- リポジトリ全体のバージョン管理規約（`README.md`より）:
  - ファイル命名: `ツール名_yyyymmdd_連番.py`
  - 旧バージョンファイルは削除・上書きせず併存させる
  - 各ツールフォルダに`CHANGELOG.md`を置く
- 本プロジェクト固有の仕様・設計方針（確定分）:
  - 文字起こしエンジン: Gemini API（クラウド）を採用。音声ファイルをGemini Files APIに渡し、文字起こし + 簡易話者分離を1回のプロンプトで生成する。
  - 話者分離: 簡易でよい（Gemini任せの「話者A」「話者B」等のラベル付けで十分。専用ダイアライゼーションは導入しない）。
  - 出力形式: Markdown議事録 + 構造化データ（JSON）を両方出力する（`transcript.md`/`transcript.json`, `summary.md`/`summary.json`）。
  - 機密性の高い会議向けオプション: **文字起こしのみローカル化**できるようにする。GUI上のラジオボタンで「クラウド（Gemini API）」／「ローカル（faster-whisper等）」を会議ごとに選択可能にする。要約ステップは常にGemini API（文字起こし後のテキストのみ送信）を使用し、要約自体のローカル化（ローカルLLM導入）は行わない。
  - ローカルモード時の話者ラベル: 省略可（faster-whisper単体では話者分離を行わないため、ローカルモードでは話者ラベルなしの時系列テキストとする。クラウドモードのみ簡易話者分離ラベル付き）。
  - UI形式: GUI（Tkinter）を採用。既存の`youtube_summary_list`と同様の軽量デスクトップUIとし、Streamlitは採用しない。
- 検討中の論点（未決定・将来の拡張候補）:
  - **pyannote.audio等の専用ダイアライゼーション**: 現時点では簡易分離（Gemini任せ）を採用するが、長時間・多人数会議でチャンクをまたいで話者ラベルがずれる等、精度不足が判明した場合の拡張候補として保留。pyannoteは音声の声紋（embedding）に基づきクラスタリングするため同一人物への一貫性は高いが、GPU推奨・HuggingFaceトークン管理・追加ライブラリが必要になり、かつ話者名との紐付けは別途必要。導入する場合は「pyannoteで話者境界を検出→Geminiで文字起こし」のハイブリッド構成を想定。

## 5. Current Status

- **完了済み**: セッション管理用ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md`）の初期セットアップ。リポジトリの既存慣習の調査。文字起こしエンジン・話者分離・出力形式・ローカルオプションの範囲・話者ラベル省略可否・GUIフレームワークの全設計方針についてユーザー確認済み（上記4.参照）。
- **作業中**: なし（設計方針の確認が完了し、実装着手前の状態）。
- **未着手**: 実装一式（フォルダ作成、音声抽出、Gemini/faster-whisper文字起こし、要約、Tkinter GUI）。

## 6. Known Issues

- 既知の問題: 未確認（コードが存在しないため該当なし）。
- 暫定対応: 該当なし。
- 技術的リスク: 画面キャプチャー録画（.mkv）はファイルサイズが大きくなりやすいため、音声抽出・分割処理の設計が必要になる可能性がある（未確定）。

## 7. Test and Execution

- 起動方法: 未確認（コード未実装）
- テスト方法: 未確認
- 必要な環境変数: 未確認（クラウドAPIを使う場合はAPIキー管理が必要になる見込み）
- 外部サービスへの依存: 未確認（Gemini API等の文字起こし・要約用クラウドサービスへの依存が想定されるが未確定）

## 8. Important Restrictions

- 変更禁止事項: 明示的な指示がない限り、`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/`, `youtube_summary_list_*.py`, `HANDOVER_youtube_summary_list.md` など、本プロジェクトと無関係な既存プロジェクトのファイルを変更しない。
- セキュリティ上の注意: APIキー・パスワード・認証情報等の秘密情報をコミットしない。会議音声・文字起こし内容には機密情報が含まれ得るため、出力ファイルの取り扱いにも注意する。
- 後方互換性に関する注意: 既存ツールのバージョン管理規約（旧ファイルを残す運用）を踏襲する。
