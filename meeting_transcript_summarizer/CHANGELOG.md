# Changelog

## 20260716_01

- 初版。Tkinter GUIから`.mkv`会議録画を選択し、文字起こし(クラウド: Gemini API / ローカル: faster-whisper)・要約(Gemini API、Markdown+JSON出力)を行うパイプラインを実装。
- `run_meeting_transcript_summarizer.bat` を追加。フォルダ内の最新バージョンの本体スクリプトを自動判別して起動する(バッチファイル自体はバージョンアップ時も変更不要)。
