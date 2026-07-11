import os
import sys
import re
import json
import time
import platform
import logging
import subprocess
from datetime import datetime
from collections import OrderedDict

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import google.generativeai as genai
except ModuleNotFoundError as e:
    print(f"\n[エラー] 必要なライブラリ '{e.name}' が見つかりません。\n"
          "次のコマンドを実行してから再度実行してください:\n\n"
          "    pip install -r requirements.txt\n")
    sys.exit(1)

import tkinter as tk
from tkinter import ttk, messagebox

# ==========================================
# パス・ディレクトリ設定
# ==========================================
BASE_DIR = r"C:\Users\nx023836\Documents\PythonScripts\bbt\RTOCS_organizer"
DATA_DIR = os.path.join(BASE_DIR, "data")
TRANSCRIPT_DIR = os.path.join(DATA_DIR, "FULL_transcript")
MASTER_JSON = os.path.join(DATA_DIR, "rtocs_master.json")
CATEGORY_MAP_JSON = os.path.join(DATA_DIR, "category_map.json")
LOG_FILE = os.path.join(DATA_DIR, "execution.log")

for d in [DATA_DIR, TRANSCRIPT_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# ==========================================
# ロギング設定
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# Gemini API クラス (API v1.0 / 2.5-flash)
# ==========================================


class GeminiExtractor:
    """V17更新: JSON対応、コスト計算、動的プロンプト対応のGemini連携クラス"""


    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.error("環境変数 'GEMINI_API_KEY' が見つかりません。")
            self.model = None
        else:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
            
        self.total_cost_usd = 0.0
        self.total_cost_jpy = 0.0
        
        # ライブ用（RTOCSあり）プロンプト（V18: データレイク対応・東証33業種制約版）
        self.prompt_template_live = """# System Role
あなたはマッキンゼー出身のトップ戦略コンサルタントであり、大前研一氏の右腕（シニア・エンゲージメント・マネージャー）です。
大前氏の「RTOCS（リアルタイム・オンライン・ケーススタディ）」の講義トランスクリプト（音声書き起こし）を読み解き、多忙なエグゼクティブが3分で全体像と核心を理解できる、最高品質のエグゼクティブ・サマリーを作成してください。

# Input Data Characteristics
入力データは講義の音声書き起こしテキストです。以下の特性に注意して処理してください。
- 雑談、相槌（えー、あの等）、文脈に無関係な余談は完全にノイズとして排除すること。
- 音声認識の誤字脱字が含まれる可能性があるため、前後の文脈から正しいビジネス用語・企業名に補正して解釈すること。

# Analysis & Structuring Rules
1. 【MECEの徹底】大前氏の分析を「市場・マクロ環境」「競合優位性」「財務・ビジネスモデル」「組織・M&A戦略」などの観点から網羅的に読み解き、重複漏れなく構造化すること。
2. 【So What?の抽出】単なる事実の羅列ではなく、「大前氏ならではの独自の洞察（インサイト）」を際立たせること。
3. 【動的カテゴリ生成】対象企業や業界の抱える「本質的な課題（ボトルネック）」や「成長のドライバー」を的確に見抜き、その事象を最も鋭く表現する2〜4つの大項目（category名）を自ら名付けること。（※絶対に「市場環境」「改善案」といった汎用的で退屈な見出しにしないこと。例：「構造的赤字を生む過剰なサプライチェーン」「〇〇市場におけるゲームチェンジと覇権争い」など）

# JSON Output Constraints
以下のルールを「絶対」に遵守すること。違反はシステムエラーを引き起こします。
- 思考プロセスや前置きの解説テキストは一切出力せず、指定されたJSONフォーマットのみを直接出力すること。
- JSON内の文字列にダブルクォーテーション(`"`)が含まれる場合は、必ずエスケープ(`\"`)すること。
- 文字列内の改行は `\n` を使用し、JSONの構造を破壊しないこと。
- 【厳格な業界分類】`industry_sector` は、必ず以下の「東証33業種」の完全一致リストから対象企業に最も該当するものを「1つだけ」選択すること。勝手な用語の作成は絶対禁止。[水産・農林業, 食料品, 鉱業, 石油・石炭製品, 建設業, 金属製品, ガラス・土石製品, 繊維製品, パルプ・紙, 化学, 医薬品, ゴム製品, 輸送用機器, 鉄鋼, 非鉄金属, 機械, 電気機器, 精密機器, その他製品, 情報・通信業, サービス業, 電気・ガス業, 陸運業, 海運業, 空運業, 倉庫・運輸関連業, 卸売業, 小売業, 銀行業, 証券、商品先物取引業, 保険業, その他金融業, 不動産業]
- `industry_niche` には、その企業の具体的な事業ドメイン（例：防災・セキュリティ設備、SaaS型業務システム など）を20文字以内で簡潔に記述すること。
- 【content内の各項目】gistは100文字程度、conclusionは300文字以内を厳守すること。next_actionsは、「大前氏がこの会社の社長なら即座に実行する3つの戦略」を、具体的かつ行動を促す動詞で終わる箇条書きにすること。

# Output Format (JSON)
{
  "classifiers": {
    "company_name": "企業名",
    "industry_sector": "東証33業種から1つ",
    "industry_niche": "事業ドメイン(20文字以内)",
    "regions": ["国内", "北米", "アジア"など関連する地域],
    "strategic_keywords": ["関連キーワード1", "関連キーワード2", "関連キーワード3"]
  },
  "content": {
    "gist": "【RTOCS総括】対象企業が直面する最大の危機（または機会）と、大前氏が提示したブレイクスルーの核心（100文字程度）",
    "conclusion": "【RTOCS結論】大前氏が最終的に下した結論と、このケーススタディから日本のビジネスリーダーが学ぶべき普遍的な教訓（300文字以内）",
    "main_points": [
      { 
        "category": "講義内容から抽出した鋭い大項目A（例：ルノーとの不均衡な資本関係が招く経営の自由度喪失）", 
        "items": [
          { "sub_topic": "内容に即した中項目名（名詞止め）", "detail": "大前氏の分析詳細..." },
          { "sub_topic": "内容に即した中項目名（名詞止め）", "detail": "大前氏の分析詳細..." }
        ] 
      }
    ],
    "next_actions": [
      "1. 〇〇事業を〇〇へ売却し、調達資金を〇〇分野へのM&Aに全額投資する", 
      "2. 〇〇市場において〇〇企業と戦略的提携を結び、〇〇のシェアを奪取する", 
      "3. 〇〇中心のビジネスモデルから〇〇プラットフォーマーへと抜本的に転換する"
    ]
  }
}
"""

        # 一般番組用（RTOCSなし、カテゴリ動的生成）プロンプト（V18: データレイク対応版）
        self.prompt_template_general = """# Task
あなたは、経営コンサルタント大前研一氏の思考をトレースし、ビジネスリーダー向けにエグゼクティブ・サマリーを作成する戦略コンサルタントです。
提示された講義トランスクリプトから、以下の[Output Format]に従って、厳格なJSON形式で出力してください。

# Constraints
1. JSON内の文字列にダブルクォーテーション(`"`)が含まれる場合は、必ずエスケープ(`\"`)すること。
2. `classifiers` には、講義全体に関連する業界や地域、キーワードを配列で抽出すること。
3. 【content内の各項目】gistは講義全体で最も重要なトピックスを100文字程度で記述し、conclusionは大局的な視点での向かうべき方向性や結論を300文字以内でまとめること。
4. 【main_points】には、講義内容に基づいて論理的な大項目（category）を2〜4個、自ら生成して含めること。（※「RTOCS」や特定のコーナー名に縛られず、内容に即した汎用的な章立てにすること）
5. 「next_actions」は、ビジネスリーダーが取るべき具体的な行動指針を3つ提示すること。

# Output Format (JSON)
{
  "classifiers": {
    "industry_sector": "関連する東証33業種（該当なしの場合は「その他製品」）",
    "industry_niche": "具体的なトピック（20文字以内）",
    "regions": ["国内", "海外"など],
    "strategic_keywords": ["キーワード1", "キーワード2", "キーワード3"]
  },
  "content": {
    "gist": "今週の要旨を100文字程度で記述...",
    "conclusion": "今週の結論を300文字以内で...",
    "main_points": [
      { 
        "category": "講義内容から導き出した適切な大項目A", 
        "items": [
          { "sub_topic": "中項目名", "detail": "..." }
        ] 
      }
    ],
    "next_actions": [
      "1. 〇〇を注視する", 
      "2. 〇〇を再点検する",
      "3. 〇〇に備える"
    ]
  }
}
"""

    def get_company_name(self, context_text):
        """従来の企業名のみ抽出機能（ファイル命名用）"""
        if not self.model: return "APIキー未設定"
        
        prompt = f"以下のテキストは、BBT「大前研一ライブ」内のRTOCSコーナーの抜粋です。分析対象の「企業名」を1つだけ正確に抽出してください。解説不要。企業名のみ。【テキスト】: {context_text}"
        try:
            response = self.model.generate_content(prompt)
            if response.text:
                company = response.text.strip().replace('\n', '').replace('/', '／')
                if "できません" in company or "不明" in company: return "Unknown"
                logger.info(f"Gemini API Response (Company): {company}")
                return company
            return "Unknown"
        except Exception as e:
            logger.error(f"Gemini抽出失敗: {e}")
            return "抽出失敗"

    def generate_json_summary(self, text_content, title, is_rtocs_mode):
        """V17統合: JSONモードによる完全な要約生成とコスト計算"""
        if not self.model: return self._get_fallback_dict()
        
        try:
            logger.info("🚀 Gemini APIにJSON要約リクエストを送信中...")
            
            # プロンプトの動的切り替え
            if "大前研一ライブ" in title and is_rtocs_mode:
                prompt_instruction = self.prompt_template_live
                logger.info("  -> [大前研一ライブ] 用プロンプト（RTOCSあり）を適用します")
            else:
                prompt_instruction = self.prompt_template_general
                logger.info("  -> [一般番組] 用プロンプト（RTOCSなし）を適用します")

            final_prompt = f"{prompt_instruction}\n\n[Transcript Data]\n{text_content}"
            
            # JSONモードで呼び出し
            response = self.model.generate_content(
                final_prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            # トークン計算 (160円/$)
            t_in = getattr(response.usage_metadata, 'prompt_token_count', 0) if hasattr(response, 'usage_metadata') else 0
            t_out = getattr(response.usage_metadata, 'candidates_token_count', 0) if hasattr(response, 'usage_metadata') else 0
            cost_u = (t_in / 1_000_000 * 0.30) + (t_out / 1_000_000 * 2.50)
            self.total_cost_usd += cost_u
            self.total_cost_jpy += cost_u * 160
            logger.info(f"  -> API消費: ${cost_u:.4f} (約 {cost_u * 160:.2f}円)")
            
            if response.text:
                text = response.text.strip()
                if text.startswith('```json'): text = text[7:]
                elif text.startswith('```'): text = text[3:]
                if text.endswith('```'): text = text[:-3]
                return json.loads(text.strip())
            return self._get_fallback_dict()
            
        except Exception as e:
            logger.error(f"Gemini (JSON Summary) Error: {e}")
            return self._get_fallback_dict()

    def _get_fallback_dict(self):
        return {
            "title": "要約抽出失敗",
            "keywords": "エラー",
            "gist": "JSONの解析またはAPI呼び出しに失敗しました。",
            "conclusion": "エラーにより要約を生成できませんでした。",
            "main_points": []
        }


class HTMLGenerator:
    """V04から移植: JSON要約データを元にカード型HTMLレポートを生成するクラス"""
    
    def __init__(self, output_dirs):
        self.output_dirs = output_dirs if isinstance(output_dirs, list) else [output_dirs]
        for d in self.output_dirs:
            if not os.path.exists(d):
                os.makedirs(d)

    def sanitize_filename(self, title, max_length=50):
        try:
            if not title: return "Unknown"
            title = str(title).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
            forbidden_chars = {'/':'／', '\\':'￥', ':':'：', '*':'＊', '?':'？', '"':'”', '<':'＜', '>':'＞', '|':'｜'}
            for old, new in forbidden_chars.items():
                title = title.replace(old, new)
            return title[:max_length].strip()
        except:
            return "Unknown"


    def generate_html(self, summaries, cost_usd=0.0, cost_jpy=0.0, episode="XXXX", company="Unknown", is_rtocs_mode=True):
        """V17: HTMLファイル名の命名ルールを刷新し、日付・時間・企業名等を含める"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = company if is_rtocs_mode else "全体要約"
            safe_suffix = self.sanitize_filename(suffix)
            
            filename = f"Summary_BBT_大前研一ライブ {episode}_{timestamp}_{safe_suffix}.html"
            html_content = self.create_html_template(summaries, timestamp, cost_usd, cost_jpy)
            
            main_filepath = ""
            for i, d in enumerate(self.output_dirs):
                target_path = os.path.join(d, filename)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                if i == 0:
                    main_filepath = target_path
            
            return main_filepath
        except Exception as e:
            logger.error(f"HTML生成エラー: {e}")
            return None

    def create_html_template(self, summaries, timestamp, cost_usd, cost_jpy):
        dt = datetime.now()
        date_str = dt.strftime("%Y年%m月%d日")
        
        cost_html = ""
        if cost_usd > 0:
            cost_html = f'<div style="text-align:center; padding: 10px; margin-bottom: 20px; background-color: #e0f2fe; border: 1px solid #bae6fd; border-radius: 5px; font-weight: bold; color: #0369a1;">💰 推定APIコスト (gemini-2.5-flash): ${cost_usd:.4f} (約 {cost_jpy:.2f} 円)</div>'

        cards_html = ""
        for idx, summary in enumerate(summaries, 1):
            cards_html += self.create_summary_card(idx, summary)
        
        html_parts = []
        html_parts.append('<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">')
        html_parts.append(f'<title>BBT要約レポート - {date_str}</title>')
        html_parts.append('<style>')
        html_parts.append('body { font-family: "Segoe UI", sans-serif; background-color: #f8f9fa; color: #333; padding: 20px;}')
        html_parts.append('.container { max-width: 1000px; margin: 0 auto; }')
        html_parts.append('.video-card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-top: 4px solid #3182ce;}')
        html_parts.append('.video-title { color: #2d3748; font-weight: 700; font-size: 1.4rem; margin-bottom: 15px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px; }')
        html_parts.append('.keyword-badge { display: inline-block; padding: 4px 10px; margin: 0 5px 5px 0; background: #edf2f7; color: #4a5568; border-radius: 15px; font-size: 0.85rem; font-weight: bold; }')
        html_parts.append('.one-liner-box { background-color: #ebf8ff; border-left: 4px solid #3182ce; padding: 15px; border-radius: 4px; margin-bottom: 20px; font-size: 0.95rem; line-height: 1.6;}')
        html_parts.append('.conclusion-text { font-size: 0.95rem; line-height: 1.8; margin-bottom: 20px; }')
        html_parts.append('.section-content { margin-top: 15px; }')
        html_parts.append('.point-item { margin-bottom: 15px; line-height: 1.6; font-size: 0.95rem; }')
        html_parts.append('.collapse-button { background: #3182ce; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; }')
        html_parts.append('.collapse-content { max-height: 0; overflow: hidden; transition: max-height 0.3s; }')
        html_parts.append('.collapse-content.show { max-height: 5000px; }')
        html_parts.append('</style></head><body><div class="container">')
        html_parts.append(cost_html)
        html_parts.append(cards_html)
        html_parts.append('<script>function toggleDetails(id) { document.getElementById("details-"+id).classList.toggle("show"); }</script>')
        html_parts.append('</div></body></html>')
        
        return "\n".join(html_parts)


    def create_summary_card(self, index, summary):
        video_url = summary.get('url', '#')
        thumbnail_url = summary.get('thumbnail_url', '')
        video_id = f"video_{index}"
        
        if not summary['success']:
            error_msg = summary.get("error", "不明なエラー")
            title = summary.get("title", "不明")
            return f'<div class="video-card"><div class="video-title">{index}. {title}</div><div style="color:red;">要約失敗: {error_msg}</div></div>'
        
        sd = summary.get('summary', {})
        if not isinstance(sd, dict): sd = {}
        
        # V18 ネスト構造対応（旧フラット構造への後方互換あり）
        content = sd.get('content', sd)
        classifiers = sd.get('classifiers', sd)
        metadata = sd.get('metadata', {})

        # 表示タイトルの再構築 (配信情報を含まない綺麗な形式へ)
        episode = metadata.get('episode_no')
        company = classifiers.get('company_name')
        
        if episode and company and company != "Unknown" and company != "RTOCS未検出":
            disp_title = f"大前研一ライブ #{episode} RTOCS {company}"
        elif episode:
            disp_title = f"大前研一ライブ #{episode} (全体要約)"
        else:
            disp_title = sd.get('title', summary.get('title', '無題'))

        gist = content.get('gist', '')
        conclusion = content.get('conclusion', '')
        
        keywords_html = ""
        # 新構造のタグ処理
        if 'strategic_keywords' in classifiers:
            ind_sec = classifiers.get('industry_sector', '')
            ind_niche = classifiers.get('industry_niche', '')
            if ind_sec: keywords_html += f'<span class="keyword-badge" style="background:#e2e8f0; border:1px solid #cbd5e1;">🏢 {ind_sec}</span>'
            if ind_niche: keywords_html += f'<span class="keyword-badge" style="background:#e2e8f0; border:1px solid #cbd5e1;">🎯 {ind_niche}</span>'
            for kw in classifiers.get('strategic_keywords', []):
                keywords_html += f'<span class="keyword-badge">{kw}</span>'
        else:
            # 旧構造のキーワード処理
            keywords_str = sd.get('keywords', '')
            for kw in keywords_str.split(','):
                if kw.strip(): keywords_html += f'<span class="keyword-badge">{kw.strip()}</span>'
        
        points_html = ""
        for pt in content.get('main_points', []):
            cat = pt.get('category', 'ポイント')
            items = pt.get('items', [])
            
            style_extra = "padding-bottom: 10px; border-bottom: 1px dashed #e2e8f0;"
            if "RTOCS" in cat.upper():
                style_extra = "background-color: #ebf8ff; border-left: 4px solid #3182ce; padding: 10px; border-radius: 4px; margin-bottom: 15px;"
            
            items_html = "<ul style='padding-left: 20px; margin-top: 5px; margin-bottom: 0;'>"
            for item_text in items:
                if isinstance(item_text, dict):
                    sub = item_text.get('sub_topic', '')
                    det = item_text.get('detail', '')
                    items_html += f"<li style='margin-bottom: 8px; line-height: 1.5;'><strong style='color: #3182ce;'>{sub}:</strong> {det}</li>"
                else:
                    items_html += f"<li style='margin-bottom: 8px; line-height: 1.5;'>{item_text}</li>"
            items_html += "</ul>"
                
            points_html += f'<div class="point-item" style="{style_extra}"><strong>■ {cat}:</strong> {items_html}</div>'

        actions = content.get('next_actions', sd.get('actions', []))
        if actions:
            act_html = "<ul style='padding-left: 20px; margin-top: 5px; margin-bottom: 0;'>"
            for act in actions:
                act_html += f"<li style='margin-bottom: 8px; line-height: 1.5;'>{act}</li>"
            act_html += "</ul>"
            points_html += f'<div class="point-item" style="padding-bottom: 10px;"><strong>■ ネクストアクション:</strong> {act_html}</div>'

        thumb_html = f'<img src="{thumbnail_url}" class="video-thumbnail-img" style="width: 120px; flex-shrink: 0; aspect-ratio: 16/9; object-fit: cover; border-radius: 6px;">' if thumbnail_url else ""
        link_html = f'<div class="mt-3"><a href="{video_url}" target="_blank" style="color:#3182ce; font-weight:bold; text-decoration:none;">🌐 講義を開く</a></div>' if video_url != '#' else ""

        return f"""
            <div class="video-card" id="{video_id}">
                <div style="display: flex; gap: 15px; align-items: flex-start; margin-bottom: 15px;">
                    {thumb_html}
                    <div style="flex-grow: 1; min-width: 0;">
                        <div class="video-title" style="border-bottom: none; margin-bottom: 5px; padding-bottom: 0;">{index}. {disp_title}</div>
                        <div class="keyword-section">{keywords_html}</div>
                    </div>
                </div>
                
                <div class="one-liner-box">
                    {gist}
                </div>
                
                <div class="conclusion-text">
                    {conclusion}
                </div>
                
                <button class="collapse-button" onclick="toggleDetails('{video_id}')">主なポイントを表示</button>
                <div id="details-{video_id}" class="collapse-content">
                    <div class="section-content mt-3">
                        {points_html}
                    </div>
                </div>
                {link_html}
            </div>"""

# ==========================================
# メインロジック クラス
# ==========================================

class RTOCSManager:
    

    def __init__(self, years, limit, config=None):
        self.years = sorted(years, reverse=True)
        self.limit = 9999 if limit == "ALL" else int(limit)
        # GUIからの設定（PDFダウンロード、要約範囲）を保持
        self.config = config or {"download_pdf": False, "rtocs_only": True}
        self.driver = None
        self.gemini = GeminiExtractor()
        self.master_data = self.load_json(MASTER_JSON, [])
        self.cat_map = self.load_json(CATEGORY_MAP_JSON, {})
        # フォルダ構成の定義（原本仕様に基づく相対パス化）
        self.rtocs_dir = os.path.join(DATA_DIR, "RTOCS_transcript")
        self.pdf_dir = os.path.join(DATA_DIR, "PDF_documents")
        self.html_dir = os.path.join(DATA_DIR, "HTML_report")
        self.json_dir = os.path.join(DATA_DIR, "JSON_lake")
        self.rtocs_pdf_dir = os.path.join(DATA_DIR, "RTOCS_pdf")
        # フォルダの一括自動生成
        for d in [self.rtocs_dir, self.pdf_dir, self.html_dir, self.json_dir, self.rtocs_pdf_dir]:
            os.makedirs(d, exist_ok=True)

    def save_summary_json(self, video_id, episode, date_str, company, summary_dict):
        """V18新規: メタデータを付与してJSON_lakeに構造化保存する（エラー時は保存しない）"""
        if not summary_dict or "要約抽出失敗" in summary_dict.get("title", "") or "JSONの解析" in summary_dict.get("gist", ""):
            logger.warning(f"⚠️ エラー応答のためJSON保存をスキップします: ID {video_id}")
            return False
            
        safe_company = re.sub(r'[\\/:*?"<>|]+', '_', company)
        filename = f"RTOCS_{video_id}_{date_str}_{safe_company}.json"
        filepath = os.path.join(self.json_dir, filename)
        
        # メタデータの付与とスキーマの統合
        final_data = {
            "metadata": {
                "video_id": str(video_id),
                "episode_no": str(episode),
                "broadcast_date": str(date_str),
                "processed_timestamp": datetime.now().isoformat()
            }
        }
        final_data.update(summary_dict)
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 構造化JSONを保存しました: {filename}")
            return True
        except Exception as e:
            logger.error(f"❌ JSON保存エラー: {e}")
            return False

    def load_summary_json(self, video_id):
        """V18新規: video_idに一致するJSONファイルを読み込む"""
        try:
            files = [f for f in os.listdir(self.json_dir) if f"_{video_id}_" in f and f.endswith(".json")]
            if not files:
                return None
            filepath = os.path.join(self.json_dir, files[0])
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ JSON読み込みエラー (ID: {video_id}): {e}")
            return None


    def restore_html_from_json(self, video_id, year, url):
        """V18新規: APIを使わずに既存JSONからHTMLを復元生成する（単一責任）"""
        summary_dict = self.load_summary_json(video_id)
        if not summary_dict:
            logger.error(f"❌ JSONデータが見つからないため復元できません: ID {video_id}")
            return False

        meta = summary_dict.get("metadata", {})
        episode = meta.get("episode_no", "XXXX")
        date_str = meta.get("broadcast_date", f"{year}0000")
        
        classifiers = summary_dict.get("classifiers", {})
        company = classifiers.get("company_name", "Unknown")

        # HTMLGeneratorが期待するラッパー形式に合わせる
        full_title = f"大前研一ライブ (ID:{video_id})"
        summary_list = [{'title': full_title, 'url': url, 'thumbnail_url': "", 'summary': summary_dict, 'success': True}]

        if 'HTMLGenerator' in globals():
            html_gen = HTMLGenerator(self.html_dir)
            is_rtocs_mode = company != "Unknown" and company != "RTOCS未検出"
            html_path = html_gen.generate_html(summary_list, cost_usd=0.0, cost_jpy=0.0, episode=episode, company=company, is_rtocs_mode=is_rtocs_mode)
            logger.info(f"✅ HTMLレポートをJSONから復元しました: {os.path.basename(html_path)}")

        self.master_data.append({
            "year": year, "episode": episode, "date": date_str, "id": video_id,
            "company": company, "file": f"RTOCS_{video_id}_{date_str}_{company}.json", "thumbnail_url": "",
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"✨ 復元処理成功(API課金ゼロ): {episode}回 -> {company}")
        return True

    def load_json(self, path, default):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        return default

    def save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def connect_chrome(self):
        try:
            options = Options()
            options.add_experimental_option("debuggerAddress", "localhost:9222")
            self.driver = webdriver.Chrome(options=options)
            return True
        except Exception as e:
            logger.error(f"Chrome接続失敗 (9222ポートを確認してください): {e}")
            return False

    def get_video_list(self, year):
        if year not in self.cat_map: return []
        url = f"https://www.bbt757.com/svlAirSearch/search?subCatId={self.cat_map[year]['id']}&sortKey=DELIVERY_DATE&sortOrder=DESC"
        logger.info(f"🌐 年度ページスキャン開始: {year}")
        self.driver.get(url)
        time.sleep(5)

        for i in range(2):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)

        links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/content/']")
        video_targets = []
        seen_ids = set()
        
        for idx, link in enumerate(links):
            try:
                href = link.get_attribute("href")
                context_text = self.driver.execute_script("""
                    let el = arguments[0];
                    return (el.innerText + " " + (el.parentElement ? el.parentElement.innerText : "") + " " + (el.parentElement.parentElement ? el.parentElement.parentElement.innerText : ""));
                """, link).replace('\n', ' ')

                if "大前研一ライブ" in context_text:
                    v_id_match = re.search(r'/content/(\d+)', href)
                    if v_id_match:
                        v_id = int(v_id_match.group(1))
                        if v_id not in seen_ids:
                            video_targets.append({"id": v_id, "url": href})
                            seen_ids.add(v_id)
            except: continue

        video_targets.sort(key=lambda x: x['id'], reverse=True)
        logger.info(f"🔎 フィルタリング完了: {len(video_targets)} 件の動画を特定")
        return video_targets

    def normalize_time(self, time_str):
        if re.match(r'^\d{1,2}:\d{2}$', time_str): return f"{time_str}:00"
        elif re.match(r'^\d{1,2}:\d{2}:\d{2}$', time_str): return time_str
        return "00:00:00"




    def parse_timestamp_to_seconds(self, timestamp):
        """V17修正: 新しい字幕形式(00:00:17.400 - 00:00:17.720)に対応"""
        try:
            first_time = timestamp.split('-')[0].strip()
            first_time = first_time.split('.')[0]
            parts = first_time.split(':')
            if len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            if len(parts) == 2: return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            pass
        return 0

    def extract_timetable(self):
        """原本コード準拠：講義のタイムテーブルを抽出"""
        try:
            logger.info("タイムテーブル取得開始...")
            timetable_data = []
            selectors = [
                '[class*="playlist"]', '[class*="chapter"]', '[class*="timetable"]',
                '[class*="timeline"]', '[class*="index"]', 
                'ul li', 'ol li', '.list-item'
            ]
            for selector in selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for elem in elements:
                    text = elem.text.strip()
                    if len(text) > 20:
                        matches = re.findall(r'(\d{1,2}:\d{2}(?::\d{2})?)\s*[-:\s]*(.+)', text)
                        if len(matches) >= 3:
                            for time_str, topic_str in matches:
                                timetable_data.append({
                                    'start_time': self.normalize_time(time_str),
                                    'topic': topic_str.strip()
                                })
                            logger.info(f"タイムテーブル取得成功: {len(timetable_data)}項目")
                            return timetable_data
            logger.warning("タイムテーブルが見つかりません")
            return []
        except Exception as e:
            logger.error(f"タイムテーブル取得エラー: {e}")
            return []

    def click_subtitle_tab(self):
        """原本コード準拠：字幕タブを物理クリック"""
        try:
            selectors = ['button', 'a', 'div[role="tab"]', '[class*="tab"]']
            for selector in selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    if element.text.strip() == '字幕' and element.is_displayed():
                        pre_click_html = self.driver.page_source[:1000]
                        self.driver.execute_script("arguments[0].click();", element)
                        logger.info("字幕タブクリック成功")
                        
                        max_wait = 2
                        wait_interval = 0.5
                        total_waited = 0
                        
                        while total_waited < max_wait:
                            time.sleep(wait_interval)
                            total_waited += wait_interval
                            
                            current_html = self.driver.page_source[:1000]
                            if current_html != pre_click_html:
                                table_elements = self.driver.find_elements(
                                    By.CSS_SELECTOR, 
                                    'table tbody tr, .MuiTableRow-root'
                                )
                                if len(table_elements) > 0:
                                    logger.info(f"字幕データ読み込み確認 ({total_waited:.1f}秒)")
                                    time.sleep(1)
                                    return True
                        
                        logger.info(f"字幕タブクリック後、最大待機時間到達 ({max_wait}秒)")
                        return True
            
            logger.warning("字幕タブが見つかりません")
            return False
            
        except Exception as e:
            logger.error(f"字幕タブクリックエラー: {e}")
            return False

    def extract_transcript(self):
        """原本コード準拠：トランスクリプト抽出と重複排除"""
        try:
            logger.info("JavaScriptで全トランスクリプトを取得中...")
            all_data = self.driver.execute_script("""
                let rows = document.querySelectorAll('table tbody tr, .MuiTableRow-root');
                let result = [];
                rows.forEach(row => {
                    try {
                        let cells = row.querySelectorAll('td, .MuiTableCell-root');
                        if (cells.length >= 2) {
                            let timestamp = cells[0].textContent.trim();
                            let content = cells[1].textContent.trim();
                            if (timestamp && content && timestamp.includes(':')) {
                                result.push({timestamp: timestamp, content: content});
                            }
                        }
                    } catch (e) {}
                });
                return result;
            """)
            
            if not all_data:
                return []
            
            seen_timestamps = set()
            transcript_data = []
            
            for item in all_data:
                timestamp = item.get('timestamp', '').strip()
                content = item.get('content', '').strip()
                
                if not timestamp or not content or ':' not in timestamp:
                    continue
                
                if timestamp not in seen_timestamps:
                    transcript_data.append({'timestamp': timestamp, 'content': content})
                    seen_timestamps.add(timestamp)
            
            if transcript_data:
                transcript_data.sort(key=lambda x: self.parse_timestamp_to_seconds(x['timestamp']))
            
            logger.info(f"抽出完了: {len(transcript_data)}件")
            return transcript_data
            
        except Exception as e:
            logger.error(f"トランスクリプト抽出エラー: {e}")
            return []

    def merge_timetable_and_transcript(self, timetable, transcript):
        """全件抽出対応：目次情報とトランスクリプト全件を結合して出力する"""
        timetable_text = "【目次情報】\n"
        rtocs_start_time = None
        
        for item in timetable:
            timetable_text += f"[{item['start_time']}] {item['topic']}\n"
            if "RTOCS" in item.get('topic', '') and not rtocs_start_time:
                rtocs_start_time = item['start_time']
        
        if not rtocs_start_time: return None, "RTOCS区間が目次に見つかりません"

        transcript_text = "\n--- 字幕抽出（全件） ---\n"
        for line in transcript:
            transcript_text += f"[{line['timestamp']}] {line.get('content', '')}\n"
        
        return rtocs_start_time, timetable_text + transcript_text



    def download_and_copy_pdf(self, video_id, episode, date_str, company):
        """V18.6: PDF資料ボタンをauto-download-slide配下に限定し、字幕Excel誤取得を防止"""
        import glob
        import os
        import time
        import shutil
        import re
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.action_chains import ActionChains

        try:
            download_dir = os.path.expanduser(r"~\Downloads")
            before_all_files = set(glob.glob(os.path.join(download_dir, "*")))
            before_files = set(glob.glob(os.path.join(download_dir, "*.pdf")))
            
            target_element = None
            pdf_button_xpath = (
                "//div[contains(concat(' ', normalize-space(@class), ' '), ' auto-download-slide ')]"
                "//img[contains(concat(' ', normalize-space(@class), ' '), ' btn-slide-download ')]"
                "/ancestor::button[1]"
            )
            
            try:
                target_element = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, pdf_button_xpath))
                )
                logger.info("✅ 資料PDFボタンを特定しました: auto-download-slide > img.btn-slide-download > ancestor button")
            except Exception as e:
                logger.info(f"  -> 資料PDFダウンロードボタンなし（スキップ）: {e}")
                return False
            
            if not target_element:
                logger.info("  -> 資料ダウンロードボタンなし（スキップ）")
                return False

            try:
                actions = ActionChains(self.driver)
                actions.move_to_element(target_element).pause(0.8).click().perform()
                self.driver.execute_script("arguments[0].click();", target_element)
                logger.info("⏳ 資料PDFの物理ホバー＆クリック命令を送信しました...")
            except Exception as e:
                logger.warning(f"⚠️ ActionChainsクリックに失敗したためJSクリックへフォールバックします: {e}")
                self.driver.execute_script("arguments[0].click();", target_element)
            
            timeout = 30
            start_time = time.time()
            new_pdf = None
            unexpected_files = set()
            while time.time() - start_time < timeout:
                current_pdfs = set(glob.glob(os.path.join(download_dir, "*.pdf")))
                new_pdfs = current_pdfs - before_files
                if new_pdfs:
                    candidate = list(new_pdfs)[0]
                    try:
                        if os.path.getsize(candidate) > 0:
                            new_pdf = candidate
                            time.sleep(0.5) 
                            break
                    except OSError: pass
                
                current_all_files = set(glob.glob(os.path.join(download_dir, "*")))
                new_all_files = current_all_files - before_all_files
                unexpected_files = {
                    f for f in new_all_files
                    if not f.lower().endswith((".pdf", ".crdownload", ".tmp"))
                }
                time.sleep(1)
                
            if new_pdf:
                safe_company = re.sub(r'[\\/:*?"<>|]+', '_', company) if company else "Unknown"
                filename = f"BBT_大前研一ライブ_{episode}_{date_str}_{video_id}_{safe_company}.pdf"
                target_path = os.path.join(self.pdf_dir, filename)
                shutil.copy2(new_pdf, target_path)
                logger.info(f"✅ 資料PDFを保存しました: {filename}")
                return True # 次の抽出処理を許可
            else:
                if unexpected_files:
                    unexpected_names = [os.path.basename(f) for f in sorted(unexpected_files)]
                    logger.warning(f"⚠️ PDF以外の新規ダウンロードを検出しました。字幕Excel等の誤クリック可能性があります: {unexpected_names}")
                logger.warning(f"⚠️ {timeout}秒以内にPDFがダウンロードされませんでした。")
                return False
                
        except Exception as e:
            logger.error(f"⚠️ PDF取得プロセスエラー: {e}")
            return False

    def extract_rtocs_section(self, timetable, transcript):
        """V18: 物理マーカー（キーワード）による終了判定を最優先し、目次による途中切断を防ぐ"""
        start_time = None
        fallback_end_time = "99:99:99"
        rtocs_titles = []

        for i, item in enumerate(timetable):
            topic = item.get('topic', '')
            if "RTOCS" in topic.upper() or "リアルタイムオンラインケーススタディ" in topic:
                start_time = item['start_time']
                rtocs_titles.append(topic)
                # 目次から関連トピックを収集し、大区切りのトピックをフォールバック終了時間とする
                for j in range(i+1, len(timetable)):
                    t = timetable[j]['topic']
                    if any(x in t for x in ["RTOCS", "ライブ", "休憩", "情勢", "Break time"]):
                        fallback_end_time = timetable[j]['start_time']
                        break
                    rtocs_titles.append(t)
                break
        
        if not start_time: 
            return None, None, None

        # 1. RTOCS専用のテキスト抽出
        rtocs_only_text = "【目次情報】: " + " > ".join(rtocs_titles) + "\n\n--- 字幕抽出(RTOCS区間) ---\n"
        start_sec = self.parse_timestamp_to_seconds(start_time)
        fallback_end_sec = self.parse_timestamp_to_seconds(fallback_end_time)
        
        # マーカー用変数の準備
        rtocs_end_timestamp = None
        in_rtocs = False

        for line in transcript:
            cur_sec = self.parse_timestamp_to_seconds(line['timestamp'])
            
            # 開始時刻以降であれば抽出対象とする（上限はキーワードで打ち切るため撤廃）
            if cur_sec >= start_sec:
                if not in_rtocs: in_rtocs = True
                content = line.get('content', '')
                
                # 1. 物理マーカー（キーワード）による確実な終了判定（最優先）
                if any(k in content for k in ["Break time", "休憩", "一息入れましょう", "ブレイクタイム"]):
                    rtocs_end_timestamp = line['timestamp']
                    rtocs_only_text += f"\n(判定: キーワード「{content}」により抽出を終了しました)\n"
                    break
                
                # 2. フォールバック終了判定（キーワード未検出時の安全装置：大区切り目次から+300秒限界）
                if cur_sec > fallback_end_sec + 300:
                    rtocs_end_timestamp = line['timestamp']
                    rtocs_only_text += f"\n(判定: 終了キーワード未検出のため、目次基準の限界時間で抽出を終了しました)\n"
                    break
                    
                rtocs_only_text += f"[{line['timestamp']}] {content}\n"
        
        return start_time, rtocs_only_text, rtocs_end_timestamp


    def process_local_file(self, file_path, year, video_id, url):
        """V18更新: ローカル全件テキストから要約生成し、JSON・HTMLを保存する（神関数回避のため復元処理は分離）"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            full_title = f"大前研一ライブ (ID:{video_id})"
            company = "Unknown"
            date_str = f"{year}0000"
            
            timetable_data = []
            transcript_data = []
            in_timetable = False
            in_transcript = False
            
            # テキストファイルから目次と字幕を逆パースして配列に復元
            for line in lines:
                line_s = line.strip()
                if line_s.startswith("TITLE:"): full_title = line_s.replace("TITLE:", "").strip()
                elif line_s.startswith("COMPANY:"): company = line_s.replace("COMPANY:", "").strip()
                elif line_s.startswith("DATE:"): date_str = line_s.replace("DATE:", "").strip()
                elif line_s.startswith("【目次情報】"):
                    in_timetable = True
                    in_transcript = False
                elif line_s.startswith("--- 字幕抽出"):
                    in_timetable = False
                    in_transcript = True
                else:
                    if in_timetable:
                        m = re.match(r'\[(.*?)\]\s*(.*)', line_s)
                        if m: timetable_data.append({'start_time': m.group(1), 'topic': m.group(2)})
                    elif in_transcript:
                        m = re.match(r'\[(.*?)\]\s*(.*)', line_s)
                        if m: transcript_data.append({'timestamp': m.group(1), 'content': m.group(2)})

            if not timetable_data or not transcript_data:
                logger.warning(f"⚠️ ローカルファイルのパースに失敗しました: {file_path}")
                return False

            # V17の強力なマーカーロジックを流用してRTOCSを彫り出す
            _, combined_text = self.merge_timetable_and_transcript(timetable_data, transcript_data)
            rtocs_start_t, rtocs_text, _ = self.extract_rtocs_section(timetable_data, transcript_data)
            
            target_text_for_summary = ""
            is_rtocs_mode = False
            if self.config.get("rtocs_only", True):
                if rtocs_start_t:
                    target_text_for_summary = rtocs_text
                    is_rtocs_mode = True
                else:
                    return False
            else:
                target_text_for_summary = combined_text

            # 企業名が取得できていない場合はGeminiに再度判定させる
            if company == "Unknown" or company == "RTOCS未検出" or "Error" in company:
                company = self.gemini.get_company_name(rtocs_text) if rtocs_start_t else "RTOCS未検出"

            ep_match = re.search(r'ライブ\s*(\d+)', full_title)
            episode = ep_match.group(1) if ep_match else "XXXX"

            # RTOCS専用トランスクリプトの保存 (追加依頼1: 企業名を後ろに配置)
            rtocs_file_name = ""
            if rtocs_start_t:
                safe_company = re.sub(r'[\\/:*?"<>|]+', '_', company)
                rtocs_file_name = f"BBT_Transcript_大前研一ライブ_{episode}_{date_str}_{video_id}_{safe_company}.txt"
                with open(os.path.join(self.rtocs_dir, rtocs_file_name), "w", encoding="utf-8") as f:
                    f.write(f"TITLE: {full_title}\nID: {video_id}\nDATE: {date_str}\nCOMPANY: {company}\n\n{rtocs_text}")

            # JSON要約の生成とHTML保存
            summary_dict = {}
            if target_text_for_summary:
                summary_dict = self.gemini.generate_json_summary(target_text_for_summary, full_title, is_rtocs_mode)
                
                # V18: JSON Data Lakeへの保存を追加
                self.save_summary_json(video_id, episode, date_str, company, summary_dict)

                if 'HTMLGenerator' in globals():
                    html_gen = HTMLGenerator(self.html_dir)
                    # サムネイルは空文字で許容
                    summary_list = [{'title': full_title, 'url': url, 'thumbnail_url': "", 'summary': summary_dict, 'success': True}]
                    html_path = html_gen.generate_html(summary_list, cost_usd=self.gemini.total_cost_usd, cost_jpy=self.gemini.total_cost_jpy, episode=episode, company=company, is_rtocs_mode=is_rtocs_mode)
                    logger.info(f"✅ HTMLレポートを生成しました(ローカル): {os.path.basename(html_path)}")

            self.master_data.append({
                "year": year, "episode": episode, "date": date_str, "id": video_id,
                "company": company, "file": rtocs_file_name, "thumbnail_url": "",
                "timestamp": datetime.now().isoformat()
            })
            
            logger.info(f"✨ 高速処理成功(抽出+HTML生成): {episode}回 -> {company}")
            return True
        except Exception as e:
            logger.error(f"❌ ローカルファイル処理エラー: {e}")
            return False


    def fetch_and_save_logic(self, year, video_id):
        """V18.2統合版: 資産全件取得（Text/JSON/HTML/PDF/RTOCS-PDF）を一括完遂する"""
        try:
            WebDriverWait(self.driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "h5")))
            full_title = self.driver.find_element(By.TAG_NAME, "h5").text
            logger.info(f"🎥 処理開始: {full_title}")

            # 2. サムネイルURLの取得
            thumbnail_url = ""
            try:
                video_el = self.driver.find_element(By.TAG_NAME, 'video')
                poster = video_el.get_attribute('poster')
                if poster and poster.startswith('http'):
                    thumbnail_url = poster
                else:
                    poster_el = self.driver.find_element(By.CSS_SELECTOR, '.vjs-poster')
                    style = poster_el.get_attribute('style')
                    match = re.search(r'url\("?([^"]+)"?\)', style) if style else None
                    if match and match.group(1).startswith('http'):
                        thumbnail_url = match.group(1)
            except Exception as e:
                logger.warning(f"  -> サムネイル取得スキップ: {e}")

            # 3. 目次と字幕の抽出
            timetable_data = self.extract_timetable()
            if not timetable_data:
                logger.error("❌ 目次データの取得に失敗しました。")
                return False

            self.click_subtitle_tab()

            transcript_data = self.extract_transcript()
            # リトライロジック
            if not transcript_data and not timetable_data:
                logger.info("再試行中...")
                time.sleep(3)
                transcript_data = self.extract_transcript()

            if not transcript_data and not timetable_data:
                logger.error("❌ データが取得できませんでした（強制終了）")
                return False

            # 4. 全件データとRTOCSデータの分離
            _, combined_text = self.merge_timetable_and_transcript(timetable_data, transcript_data)
            rtocs_start_t, rtocs_text, rtocs_end_t = self.extract_rtocs_section(timetable_data, transcript_data)

            # 5. Geminiへの送信対象の決定
            target_text_for_summary = ""
            is_rtocs_mode = False

            if self.config.get("rtocs_only", True):
                if rtocs_start_t:
                    target_text_for_summary = rtocs_text
                    is_rtocs_mode = True
                    logger.info("🎯 RTOCS区間のみを要約対象に設定しました")
                else:
                    logger.warning("⚠️ RTOCS区間が見つからないため、要約処理をスキップします")
            else:
                target_text_for_summary = combined_text
                logger.info("🎯 全件を要約対象に設定しました")

            # 6. 企業名判定
            company = self.gemini.get_company_name(rtocs_text) if rtocs_start_t else "RTOCS未検出"

            ep_match = re.search(r'ライブ\s*(\d+)', full_title)
            episode = ep_match.group(1) if ep_match else "XXXX"
            date_m = re.search(r'(\d+)月(\d+)日', full_title)
            date_str = f"{year}{date_m.group(1).zfill(2)}{date_m.group(2).zfill(2)}" if date_m else f"{year}0000"

            # 7. 全件トランスクリプト保存
            full_file_name = f"BBT_Transcript_大前研一ライブ_{episode}_{date_str}_{video_id}.txt"
            with open(os.path.join(TRANSCRIPT_DIR, full_file_name), "w", encoding="utf-8") as f:
                f.write(f"TITLE: {full_title}\nID: {video_id}\nDATE: {date_str}\nCOMPANY: {company}\n\n")
                f.write("【目次情報】\n")
                for item in timetable_data:
                    f.write(f"[{item['start_time']}] {item['topic']}\n")
                f.write("\n--- 字幕抽出（全件） ---\n")
                
                rtocs_start_sec = self.parse_timestamp_to_seconds(rtocs_start_t) if rtocs_start_t else 0
                in_rtocs_block = False
                for item in transcript_data:
                    t_sec = self.parse_timestamp_to_seconds(item['timestamp'])
                    if rtocs_start_sec > 0 and t_sec >= rtocs_start_sec and not in_rtocs_block and not rtocs_end_t == item['timestamp']:
                        f.write("\n" + "="*60 + "\n【ここからRTOCS（重点分析対象）セクション】\n" + "="*60 + "\n")
                        in_rtocs_block = True
                    
                    if in_rtocs_block and rtocs_end_t and item['timestamp'] == rtocs_end_t:
                        f.write(f"[{item['timestamp']}] {item['content']}\n")
                        f.write("\n" + "="*60 + "\n【ここまでRTOCSセクション】\n" + "="*60 + "\n")
                        in_rtocs_block = False
                        continue
                    
                    f.write(f"[{item['timestamp']}] {item['content']}\n")

            # 8. RTOCS専用トランスクリプトの保存
            if rtocs_start_t:
                safe_company = re.sub(r'[\\/:*?"<>|]+', '_', company)
                rtocs_file_name = f"BBT_Transcript_大前研一ライブ_{episode}_{date_str}_{video_id}_{safe_company}.txt"
                with open(os.path.join(self.rtocs_dir, rtocs_file_name), "w", encoding="utf-8") as f:
                    f.write(f"TITLE: {full_title}\nID: {video_id}\nDATE: {date_str}\nCOMPANY: {company}\n\n{rtocs_text}")

            # 9. JSON要約の生成とHTML保存
            summary_dict = {}
            if target_text_for_summary:
                summary_dict = self.gemini.generate_json_summary(target_text_for_summary, full_title, is_rtocs_mode)
                self.save_summary_json(video_id, episode, date_str, company, summary_dict)

                if 'HTMLGenerator' in globals():
                    html_gen = HTMLGenerator(self.html_dir)
                    summary_list = [{'title': full_title, 'url': self.driver.current_url, 'thumbnail_url': thumbnail_url, 'summary': summary_dict, 'success': True}]
                    html_gen.generate_html(summary_list, cost_usd=self.gemini.total_cost_usd, cost_jpy=self.gemini.total_cost_jpy, episode=episode, company=company, is_rtocs_mode=is_rtocs_mode)
                    logger.info(f"✅ HTMLレポートを生成しました")

            # 10. PDFのスマート回収とRTOCS抽出 (メタデータ確定後に実行)
            if self.config.get("download_pdf", False):
                if self.download_and_copy_pdf(video_id, episode, date_str, company):
                    self.extract_rtocs_pdf(video_id, episode, date_str, company)

            # 11. マスターデータの更新
            self.master_data.append({
                "year": year, "episode": episode, "date": date_str, "id": video_id,
                "company": company, "file": full_file_name, "thumbnail_url": thumbnail_url,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"✨ 新規取得成功: {episode}回 -> {company}")
            return True
        except Exception as e:
            logger.error(f"❌ 内部取得エラー: {e}")
            return False


    def _retrieve_pdf_only(self, video_id, year, url):
        """V18.2: JSONからメタデータを読み込み、ブラウザを開いてPDFを回収・抽出する"""
        summary_dict = self.load_summary_json(video_id)
        if not summary_dict:
            logger.warning(f"⚠️ JSONが存在しないため、PDF単独回収用のメタデータが取得できません: ID {video_id}")
            return False
            
        meta = summary_dict.get("metadata", {})
        episode = meta.get("episode_no", "XXXX")
        date_str = meta.get("broadcast_date", f"{year}0000")
        company = summary_dict.get("classifiers", {}).get("company_name", "Unknown")

        main_handle = self.driver.current_window_handle
        try:
            self.driver.switch_to.new_window('tab')
            self.driver.get(url)
            WebDriverWait(self.driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "h5")))
            # ダウンロード成功時のみ抽出を実行
            if self.download_and_copy_pdf(video_id, episode, date_str, company):
                self.extract_rtocs_pdf(video_id, episode, date_str, company)
            return True
        except Exception as e:
            logger.error(f"❌ PDF単独回収エラー: {e}")
            return False
        finally:
            if len(self.driver.window_handles) > 1:
                self.driver.close()
            self.driver.switch_to.window(main_handle)


    def extract_rtocs_pdf(self, video_id, episode, date_str, company):
        """V18.5: 完全テキスト検索ベース(開始＆終了)による高精度抽出"""
        import fitz
        import os
        import re

        pdf_files = [f for f in os.listdir(self.pdf_dir) if f"_{video_id}_" in f and f.endswith(".pdf")]
        if not pdf_files:
            return False
            
        src_path = os.path.join(self.pdf_dir, pdf_files[0])
        safe_company = re.sub(r'[\\/:*?"<>|]+', '_', company)
        dst_filename = f"RTOCS_{episode}_{date_str}_{video_id}_{safe_company}.pdf"
        dst_path = os.path.join(self.rtocs_pdf_dir, dst_filename)

        try:
            doc = fitz.open(src_path)
            total_pages = len(doc)
            start_page, end_page = -1, -1

            # 1. 開始ページの特定: テキスト検索
            target_phrase = "Real Time Online Case Study"
            for pno in range(total_pages):
                page = doc[pno]
                text_instances = page.search_for(target_phrase)
                
                if text_instances:
                    start_page = pno
                    logger.info(f"🎯 RTOCS開始ページをテキスト検知: {pno + 1}ページ目")
                    break
            
            # 2. 終了ページの特定: フッターテキストの消失監視
            if start_page != -1:
                # 開始ページが見つかったら、そこから順方向にスキャン
                for pno in range(start_page + 1, total_pages):
                    page = doc[pno]
                    
                    # テキストレイヤーからフッター固有の文字列を検索
                    footer_hits = page.search_for("BBT大学総合研究所")
                    is_footer_present = False
                    
                    # 見つかった文字列が「ページの下半分」にあるか確認 (本文中の言及を除外)
                    for rect in footer_hits:
                        if rect.y1 > page.rect.height * 0.5:
                            is_footer_present = True
                            break
                    
                    # ページ下部にBBTの文字が存在しなければ、そこがRTOCSの終わり
                    if not is_footer_present:
                        end_page = pno - 1
                        logger.info(f"🛑 RTOCS終了地点をテキスト検知(フッター消失): {pno + 1}ページ目以降を除外")
                        break
                
                # 3. ページ抽出と保存
                if end_page == -1: 
                    # 万が一最後までフッターが消えなかった場合の保険
                    end_page = total_pages - 1
                
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
                new_doc.save(dst_path)
                new_doc.close()
                logger.info(f"📑 RTOCS部分PDFを生成しました: {dst_filename} ({end_page - start_page + 1}ページ)")
                doc.close()
                return True
            
            logger.warning(f"⚠️ キーワード '{target_phrase}' が見つかりませんでした。")
            doc.close()
            return False
            
        except Exception as e:
            logger.error(f"❌ PDF抽出エラー: {e}")
            return False

    def process(self):
        if not self.connect_chrome(): return
        processed_count = 0
        
        for year in self.years:
            if processed_count >= self.limit: break
            targets = self.get_video_list(year)
            
            for target in targets:
                if processed_count >= self.limit: break
                vid = str(target['id'])
                
                # V18 スマート・ステータス・チェック v2.0 (全6種のファイル存在チェック)
                full_files = [f for f in os.listdir(TRANSCRIPT_DIR) if f"_{vid}" in f and f.endswith(".txt")]
                full_exists = len(full_files) > 0
                rtocs_exists = any(f"_{vid}" in f for f in os.listdir(self.rtocs_dir))
                json_exists = any(f"_{vid}_" in f for f in os.listdir(self.json_dir) if f.endswith(".json"))
                html_exists = any(f"_{vid}" in f for f in os.listdir(self.html_dir))
                
                pdf_requested = self.config.get("download_pdf", False)
                pdf_exists = any(f"_{vid}_" in f for f in os.listdir(self.pdf_dir) if f.endswith(".pdf"))
                rtocs_pdf_exists = any(f"_{vid}_" in f for f in os.listdir(self.rtocs_pdf_dir))

                if full_exists:
                    full_file_path = os.path.join(TRANSCRIPT_DIR, full_files[0])
                    local_success = False
                    is_skip = False
                    
                    # 各種メタデータの取得（抽出用）
                    # JSONがあればそこから、なければファイル名等から推測
                    episode, date_str, company = "XXXX", f"{year}0000", "Unknown"
                    sum_data = self.load_summary_json(vid)
                    if sum_data:
                        meta = sum_data.get("metadata", {})
                        episode = meta.get("episode_no", episode)
                        date_str = meta.get("broadcast_date", date_str)
                        company = sum_data.get("classifiers", {}).get("company_name", company)

                    if rtocs_exists and json_exists:
                        if html_exists:
                            is_skip = True
                            local_success = True
                        else:
                            logger.info(f"🎨 HTML再生成開始(API課金ゼロ): ID {vid}")
                            local_success = self.restore_html_from_json(vid, year, target['url'])
                    else:
                        logger.info(f"⚡ ローカル高速処理(抽出/JSON生成): ID {vid}")
                        local_success = self.process_local_file(full_file_path, year, vid, target['url'])
                        
                    if local_success:
                        pdf_retrieved = False
                        # 1. PDFが不足していればブラウザで取得
                        if pdf_requested and not pdf_exists:
                            logger.info(f"📥 PDF単独回収開始: ID {vid}")
                            pdf_retrieved = self._retrieve_pdf_only(vid, year, target['url'])
                        # 2. 原本はあるが切り出しPDFがない場合、ローカルで抽出
                        elif pdf_requested and pdf_exists and not rtocs_pdf_exists:
                            logger.info(f"✂️ RTOCS部分PDFの切り出しを実行: ID {vid}")
                            self.extract_rtocs_pdf(vid, episode, date_str, company)
                            pdf_retrieved = True # カウント対象とする
                            
                        if not is_skip or pdf_retrieved:
                            processed_count += 1
                            self.save_json(MASTER_JSON, self.master_data)
                        elif is_skip and not pdf_retrieved:
                            logger.info(f"⏩ 完全スキップ(全ファイル完了済): ID {vid}")
                            
                    continue

                # FULLテキストすらない場合 -> 通常処理 (Webから新規取得)
                logger.info(f"🚀 新規タブでWeb取得開始(FULL欠落): ID {vid}")
                main_handle = self.driver.current_window_handle
                try:
                    self.driver.switch_to.new_window('tab')
                    self.driver.get(target['url'])
                    if self.fetch_and_save_logic(year, vid):
                        processed_count += 1
                        self.save_json(MASTER_JSON, self.master_data)
                except Exception as e:
                    logger.error(f"❌ タブ制御エラー: {e}")
                finally:
                    if len(self.driver.window_handles) > 1:
                        self.driver.close()
                    self.driver.switch_to.window(main_handle)

        logger.info("🏁 全工程が終了しました。")
        if platform.system() == "Windows": subprocess.run(['explorer', DATA_DIR])

# ==========================================
# GUI クラス
# ==========================================


class RTOCSConfigGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("BBT RTOCS Manager v09")
        self.root.geometry("520x550") # 視認性を考慮したサイズ設定
        self.selected_years = []
        self.count_limit = "1"
        # 外部ファイルから年度マップを読み込み
        with open(CATEGORY_MAP_JSON, "r", encoding="utf-8") as f: 
            self.cat_map = json.load(f)
        self.setup_ui()

    def setup_ui(self):
        """GUIのレイアウト構築。gridマネージャーを使用して3列配置を実現。"""
        main_f = ttk.Frame(self.root, padding=15)
        main_f.pack(fill="both", expand=True)
        
        # 全選択/解除の制御
        self.all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_f, text="全年度を選択 (ALL)", variable=self.all_var, 
                        command=self.toggle_all).grid(row=0, column=0, columnspan=3, sticky="w", pady=10)

        # 年度リストの3列グリッド配置
        self.year_vars = {}
        # 2026年から順に降順で並べる
        years = sorted(self.cat_map.keys(), reverse=True)
        for i, y in enumerate(years):
            v = tk.BooleanVar(value=(y == "2026"))
            self.year_vars[y] = v
            # 行と列のインデックス計算 (i=0 -> 1行0列, i=3 -> 2行0列)
            row = (i // 3) + 1
            col = i % 3
            cb = ttk.Checkbutton(main_f, text=y, variable=v)
            cb.grid(row=row, column=col, sticky="w", padx=15, pady=3)
        
        # 設定エリアとの境界線
        last_row = (len(years) // 3) + 2
        # sticky="ew" により、grid内で左右いっぱいにセパレーターを伸ばす
        ttk.Separator(main_f, orient="horizontal").grid(row=last_row, column=0, columnspan=3, sticky="ew", pady=15)
        
        # 件数設定
        ttk.Label(main_f, text="取得件数 (最新順合計)", font=("", 9, "bold")).grid(row=last_row+1, column=0, sticky="w")
        self.limit_combo = ttk.Combobox(main_f, values=["1", "2", "3", "5", "10", "20", "ALL"], state="readonly")
        self.limit_combo.set("1")
        # sticky="ew" により、コンボボックスを列の幅いっぱいに広げる
        self.limit_combo.grid(row=last_row+2, column=0, columnspan=3, sticky="ew", pady=5)
        
        # 実行ボタン
        ttk.Button(main_f, text="実行開始", command=self.start).grid(row=last_row+3, column=0, columnspan=3, pady=25)

    def toggle_all(self):
        """ALLチェックボックスの状態を全年度に波及させる"""
        state = self.all_var.get()
        for v in self.year_vars.values():
            v.set(state)



    def start(self):
        """選択された要件を確定させてウィンドウを閉じる (V17: 課金警告ポップアップ追加)"""
        import glob
        
        # 既存ファイルの件数確認と警告ポップアップ
        txt_files = glob.glob(os.path.join(TRANSCRIPT_DIR, "*.txt"))
        file_count = len(txt_files)
        
        if file_count > 0:
            msg = f"transcriptフォルダ内に {file_count} 件のテキストファイルが存在します。\nこれらを再処理すると、新たにGemini APIの課金が発生します。\n処理を続行しますか？"
            if not messagebox.askyesno("確認", msg):
                return  # NOが選択された場合は処理を中断し、ウィンドウを開いたままにする
        
        self.selected_years = [y for y, v in self.year_vars.items() if v.get()]
        self.count_limit = self.limit_combo.get()
        self.config = {
            "download_pdf": self.pdf_var.get(),
            "rtocs_only": self.rtocs_only_var.get()
        }
        self.root.destroy()

# ==========================================
# GUI クラス
# ==========================================

class RTOCSConfigGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("BBT RTOCS Manager v17")
        self.root.geometry("520x650") # オプション追加のため縦幅を拡張
        self.selected_years = []
        self.count_limit = "1"
        self.config = {"download_pdf": False, "rtocs_only": True}
        # 外部ファイルから年度マップを読み込み
        with open(CATEGORY_MAP_JSON, "r", encoding="utf-8") as f: 
            self.cat_map = json.load(f)
        self.setup_ui()

    def setup_ui(self):
        """GUIのレイアウト構築。gridマネージャーを使用して3列配置を実現。"""
        main_f = ttk.Frame(self.root, padding=15)
        main_f.pack(fill="both", expand=True)
        
        # 全選択/解除の制御
        self.all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_f, text="全年度を選択 (ALL)", variable=self.all_var, 
                        command=self.toggle_all).grid(row=0, column=0, columnspan=3, sticky="w", pady=10)

        # 年度リストの3列グリッド配置
        self.year_vars = {}
        # 2026年から順に降順で並べる
        years = sorted(self.cat_map.keys(), reverse=True)
        for i, y in enumerate(years):
            v = tk.BooleanVar(value=(y == "2026"))
            self.year_vars[y] = v
            # 行と列のインデックス計算
            row = (i // 3) + 1
            col = i % 3
            cb = ttk.Checkbutton(main_f, text=y, variable=v)
            cb.grid(row=row, column=col, sticky="w", padx=15, pady=3)
        
        # 設定エリアとの境界線
        last_row = (len(years) // 3) + 2
        ttk.Separator(main_f, orient="horizontal").grid(row=last_row, column=0, columnspan=3, sticky="ew", pady=15)
        
        # 件数設定
        ttk.Label(main_f, text="取得件数 (最新順合計)", font=("", 9, "bold")).grid(row=last_row+1, column=0, sticky="w")
        self.limit_combo = ttk.Combobox(main_f, values=["1", "2", "3", "5", "10", "20", "ALL"], state="readonly")
        self.limit_combo.set("1")
        self.limit_combo.grid(row=last_row+2, column=0, columnspan=3, sticky="ew", pady=5)
        
        # --- V17 新規追加: オプション設定エリア ---
        opt_frame = ttk.LabelFrame(main_f, text="オプション設定", padding=10)
        opt_frame.grid(row=last_row+3, column=0, columnspan=3, sticky="ew", pady=10)

        # 1. PDFダウンロード要否
        self.pdf_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="講義資料(PDF)をダウンロードする", variable=self.pdf_var).pack(anchor="w", pady=2)

        # 2. 要約範囲の選択
        self.rtocs_only_var = tk.BooleanVar(value=True)
        ttk.Radiobutton(opt_frame, text="RTOCS区間のみを要約する (標準)", variable=self.rtocs_only_var, value=True).pack(anchor="w", pady=2)
        ttk.Radiobutton(opt_frame, text="動画全体を要約する", variable=self.rtocs_only_var, value=False).pack(anchor="w", pady=2)

        # 実行ボタン
        ttk.Button(main_f, text="実行開始", command=self.start).grid(row=last_row+4, column=0, columnspan=3, pady=25)

    def toggle_all(self):
        """ALLチェックボックスの状態を全年度に波及させる"""
        state = self.all_var.get()
        for v in self.year_vars.values():
            v.set(state)

    def start(self):
        """選択された要件を確定させてウィンドウを閉じる"""
        self.selected_years = [y for y, v in self.year_vars.items() if v.get()]
        self.count_limit = self.limit_combo.get()
        self.config = {
            "download_pdf": self.pdf_var.get(),
            "rtocs_only": self.rtocs_only_var.get()
        }
        self.root.destroy()

if __name__ == "__main__":
    gui = RTOCSConfigGUI()
    gui.root.mainloop()
    if gui.selected_years:
        # V17: config辞書をマネージャーに渡す
        manager = RTOCSManager(gui.selected_years, gui.count_limit, config=gui.config)
        manager.process()
