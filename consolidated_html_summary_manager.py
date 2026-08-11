# VERSION 20260722_02


import os
import glob
import json
import re
import time
import shutil
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# 保存期間（日数）
RETENTION_DAYS = 7

# [20260805] ダッシュボード帯(tile_html/detail_html/trend)のキャッシュスキーマバージョン。
# overview_cache_daily.json/overview_cache_weekly.jsonは「対象ウィンドウ内のファイル構成が
# 変化したか」だけでキャッシュの有効/無効を判定していたため、ファイル構成が同じまま
# _render_detail_html()等の出力形式だけを変更すると、古い形式のHTMLがそのまま
# 再利用され続けてしまう不具合があった（例: 推移グラフの.trend-bar CSSクラスを
# .trend-bar-stack/.trend-bar-unread/.trend-bar-readへ変更した際、キャッシュ済みの
# 旧HTMLが残っていたため棒グラフが見えなくなった）。
# detail_html/trendの出力形式を変更するたびにこの値をインクリメントし、
# 古いキャッシュを強制的に無効化すること。
DASHBOARD_CACHE_SCHEMA_VERSION = 2

class SummaryFolderManager:
    def __init__(self, target_folder):
        self.target_folder = target_folder
        self.output_file = os.path.join(target_folder, '_Consolidated_Manager.html')
        # [20260809] summary_database.json / overview_cache_*.json は、以前は
        # target_folder直下に平置きされていた。_Consolidated_Manager.html
        # （出力されるダッシュボード）はデータを埋め込み済みの静的HTMLで、
        # これらのJSONを実行時に読みには行かないことを確認済みのため、
        # 読み書きしているのはこのスクリプト自身だけである。target_folder
        # 直下を掃除するため、専用のjsonサブフォルダへ移す。
        self.json_dir = os.path.join(target_folder, 'json')


    def parse_youtube_card(self, card):
        item = {
            "is_error": False, "type": "youtube", "title": "", "summary": "", 
            "conclusion": "", "points": "", "thumbnail": "", "channel": "", "subscriber": "", "duration": "", "is_favorite": False, "keywords": [], "url": ""
        }
        
       
        link_tag = card.find("a", href=True)
        if link_tag:
            item["url"] = link_tag["href"]

        if "error-card" in card.get("class", []):
            item["is_error"] = True
            title_el = card.find("div", class_="video-title")
            raw_title = "".join(title_el.find_all(string=True, recursive=False)).strip() if title_el else "要約失敗"
            item["title"] = re.sub(r'^\d+[\.\s]+', '', raw_title)
            return item

        title_el = card.find("div", class_="video-title")
        raw_title = "".join(title_el.find_all(string=True, recursive=False)).strip() if title_el else ""
        item["title"] = re.sub(r'^\d+[\.\s]+', '', raw_title)

        summary_el = card.find("div", class_="one-liner-box")
        item["summary"] = summary_el.get_text(strip=True) if summary_el else ""

        conclusion_el = card.find("div", class_="conclusion-text")
        item["conclusion"] = conclusion_el.get_text(strip=True) if conclusion_el else ""

        points_el = card.find("div", class_="section-content")
        item["points"] = points_el.decode_contents() if points_el else ""

        thumb_img = card.find("img", class_="video-thumbnail-img")
        if thumb_img and "src" in thumb_img.attrs:
            item["thumbnail"] = thumb_img["src"]

        channel_div = card.find("div", class_="channel-info")
        if channel_div:
            # 登録者数情報のspanを探す
            sub_span = channel_div.find("span")
            if sub_span and "登録者数" in sub_span.get_text():
                raw_sub = sub_span.get_text(strip=True).strip("()）（")
                raw_sub = re.sub(r'登録者数\s*[:：]\s*', '', raw_sub)
                raw_sub = re.sub(r'チャンネル登録者数\s*', '', raw_sub)
                item["subscriber"] = raw_sub.strip()
                sub_span.extract()
            # 動画時間spanを取得（color:#2b6cb0 のspan）
            dur_span = channel_div.find("span", style=lambda s: s and "2b6cb0" in s)
            if dur_span:
                raw_dur = dur_span.get_text(strip=True)
                item["duration"] = raw_dur.replace("⏱", "").replace("\u23f1", "").strip()
                dur_span.extract()
            # お気に入り★spanを取得（color:#d4a017 のspan）
            fav_span = channel_div.find("span", style=lambda s: s and "d4a017" in s)
            if fav_span:
                item["is_favorite"] = True
                fav_span.extract()
            item["channel"] = channel_div.get_text(strip=True)

        kw_section = card.find("div", class_="keyword-section")
        if kw_section:
            item["keywords"] = [span.get_text(strip=True) for span in kw_section.find_all("span", class_="keyword-badge")]

        return item

    def parse_rss_card(self, card):
        item = {
            "is_error": False, "type": "rss", "title": "", "summary": "", 
            "conclusion": "", "points": "", "source": "", "category": "", 
            "author": "", "likes": "", "char_count": "", "outline": [], "keywords": [], "url": ""
        }
        
        link_tag = card.find("a", href=True)
        if link_tag:
            item["url"] = link_tag["href"]

        title_span = card.find("span", id=lambda x: x and x.startswith("t-txt-"))
        item["title"] = "".join(title_span.find_all(string=True, recursive=False)).strip() if title_span else ""

        summary_el = card.find("div", id=lambda x: x and x.startswith("s-txt-"))
        item["summary"] = summary_el.get_text(strip=True) if summary_el else ""

        conclusion_el = card.find("div", id=lambda x: x and x.startswith("c-txt-"))
        item["conclusion"] = conclusion_el.get_text(strip=True) if conclusion_el else ""

        points_el = card.find("div", id=lambda x: x and x.startswith("points-"))
        if points_el:
            item["points"] = points_el.decode_contents()

        meta_div = card.find("div", style=lambda s: s and ("flex-wrap:wrap" in s or "flex-wrap: wrap" in s))
        if meta_div:
            for span in meta_div.find_all("span"):
                b_tag = span.find("b")
                if b_tag:
                    b_text = b_tag.get_text(strip=True)
                    val = span.get_text(strip=True).replace(b_text, "").strip()
                    if "ソース" in b_text: item["source"] = val
                    elif "カテゴリ" in b_text: item["category"] = val
                    elif "作者" in b_text: item["author"] = val
                    elif "いいね" in b_text: item["likes"] = val
                    elif "文字数" in b_text: item["char_count"] = val


        kw_div = card.find("div", id=lambda x: x and x.startswith("k-txt-"))
        if kw_div:
            kw_text = kw_div.get_text(strip=True)
            item["keywords"] = [k.strip() for k in kw_text.split(",") if k.strip()]

        # 概要セクション（新フォーマット：📋 概要）
        for section in card.find_all("div", class_="section"):
            sec_title_el = section.find("div", class_="sec-title")
            if sec_title_el and "概要" in sec_title_el.get_text():
                sum_box = section.find("div", class_="sum-box")
                if sum_box:
                    items = [
                        d.get_text(strip=True).lstrip('・').strip()
                        for d in sum_box.find_all("div", class_=False)
                        if d.get_text(strip=True)
                    ]
                    item["outline"] = items
                break

        return item
        
        
        return item


    def extract_data(self):
        html_files = glob.glob(os.path.join(self.target_folder, 'summary_*.html'))
        
        # --- DB関連の設定 ---
        db_path = os.path.join(self.json_dir, "summary_database.json")
        archive_dir = os.path.join(self.target_folder, "archive")

        if not os.path.exists(archive_dir):
            try:
                os.makedirs(archive_dir)
            except Exception as e:
                print(f"[Warning] Failed to create archive directory: {e}")

        if not os.path.exists(self.json_dir):
            try:
                os.makedirs(self.json_dir)
            except Exception as e:
                print(f"[Warning] Failed to create json directory: {e}")

        # 既存DBのロード。
        # [20260809] 旧バージョンがtarget_folder直下に書いていたsummary_database.json
        # が残っている場合はそちらを読み、以後はjsonサブフォルダ側へ保存し直す
        # （移行のたびに越智さんに手でファイルを移してもらわずに済むようにするため）。
        db_data = {}
        legacy_db_path = os.path.join(self.target_folder, "summary_database.json")
        load_path = db_path if os.path.exists(db_path) else legacy_db_path
        if os.path.exists(load_path):
            try:
                with open(load_path, 'r', encoding='utf-8') as f:
                    db_data = json.load(f)
            except Exception as e:
                print(f"[Warning] Failed to read database, starting fresh: {e}")
                db_data = {}

        now = time.time()
        
        for filepath in html_files:
            filename = os.path.basename(filepath)
            if filename == os.path.basename(self.output_file):
                continue
            
            category = "UNKNOWN"
            parts = filename.split('_')
            if len(parts) >= 2:
                category = parts[1]

            mtime = os.path.getmtime(filepath)
            mtime_str = datetime.fromtimestamp(mtime).strftime('%Y/%m/%d %H:%M')
            
            file_data = {
                "filename": filename,
                "category": category,
                "mtime": mtime,
                "mtime_str": mtime_str,
                "items": []
            }

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                    
                    video_cards = soup.find_all("div", class_="video-card")
                    if video_cards:
                        for card in video_cards:
                            file_data["items"].append(self.parse_youtube_card(card))
                    else:
                        thread_cards = soup.find_all("div", class_="thread-card")
                        if thread_cards:
                            for card in thread_cards:
                                file_data["items"].append(self.parse_rss_card(card))
            except Exception as e:
                print(f"Error parsing {filename}: {e}")
                continue
            
            if file_data["items"]:
                # DBにマージ（ファイル名で上書き・追加）
                db_data[filename] = file_data
            
            # パース成功・失敗にかかわらず、ファイルをarchiveへ移動
            try:
                dest_path = os.path.join(archive_dir, filename)
                shutil.move(filepath, dest_path)
            except Exception as e:
                print(f"[Warning] Failed to move {filename} to archive (skipping): {e}")

        # DBのクリーンアップ（RETENTION_DAYS経過したものを削除）
        retention_seconds = RETENTION_DAYS * 24 * 60 * 60
        keys_to_delete = []
        for fname, fdata in db_data.items():
            if now - fdata.get("mtime", 0) > retention_seconds:
                keys_to_delete.append(fname)
        
        for k in keys_to_delete:
            del db_data[k]

        # DBのアトミック保存
        temp_db_path = db_path + ".tmp"
        try:
            with open(temp_db_path, 'w', encoding='utf-8') as f:
                json.dump(db_data, f, ensure_ascii=False)
            os.replace(temp_db_path, db_path)
            # [20260809] jsonサブフォルダへの新規保存に成功した後だけ、旧位置の
            # ファイルを消す。新規保存が失敗した場合は旧ファイルを残し、
            # データを失わないようにする。
            if load_path == legacy_db_path and os.path.exists(legacy_db_path):
                try:
                    os.remove(legacy_db_path)
                except Exception as e:
                    print(f"[Warning] Failed to remove legacy database file: {e}")
        except Exception as e:
            print(f"[Error] Failed to save database atomically: {e}")

        # archiveフォルダ内の古いファイルのお掃除
        if os.path.exists(archive_dir):
            for arch_file in os.listdir(archive_dir):
                arch_path = os.path.join(archive_dir, arch_file)
                if os.path.isfile(arch_path):
                    try:
                        file_mtime = os.path.getmtime(arch_path)
                        if now - file_mtime > retention_seconds:
                            os.remove(arch_path)
                            print(f"[Info] Deleted old archive file: {arch_file}")
                    except Exception as e:
                        print(f"[Warning] Failed to check or delete {arch_file}: {e}")

        data_list = list(db_data.values())
        data_list.sort(key=lambda x: x.get("mtime", 0), reverse=True)
        return data_list

    def _is_highlighted_item(self, item):
        """YouTubeのis_favorite、RSSの「Followed Note」カテゴリを「注目記事」として同一視する"""
        return item.get('is_favorite') is True or item.get('category') == 'Followed Note'

    def _collect_window_items(self, data_list, since_ts):
        """指定時刻以降に生成されたファイルから、エラーでないitemsを (file_data, item) のリストで返す"""
        results = []
        for fd in data_list:
            if fd.get('mtime', 0) >= since_ts:
                for it in fd.get('items', []):
                    if not it.get('is_error'):
                        results.append((fd, it))
        return results

    def _compute_daily_trend(self, data_list, now_dt, days=7):
        """
        直近days日間、暦日単位でのitem内訳を返す（古い日順）。
        既読/未読の集計はクライアント側(state.readHistory)にしか無いため、ここでは
        件数を確定させず、日付ラベルと各itemの識別子(filename/iIdx)だけを渡す。
        実際の既読/未読の色分けはJS側のrenderTrendChart()が担当する。
        """
        WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']
        target_dates = [(now_dt - timedelta(days=i)).date() for i in range(days - 1, -1, -1)]
        buckets = {d: [] for d in target_dates}
        for fd in data_list:
            mtime = fd.get('mtime', 0)
            if mtime <= 0:
                continue
            d = datetime.fromtimestamp(mtime).date()
            if d not in buckets:
                continue
            filename = fd.get('filename', '')
            for iIdx, it in enumerate(fd.get('items', [])):
                if not it.get('is_error'):
                    buckets[d].append({"filename": filename, "iIdx": iIdx})
        return [
            {"label": f"{d.month}/{d.day}({WEEKDAY_JA[d.weekday()]})", "items": buckets[d]}
            for d in target_dates
        ]

    def _render_tile_html(self, emoji, label, total):
        """ダッシュボード帯の折りたたみ時タイル（数字のみ）をHTML化する"""
        return (
            f'<span class="emoji">{emoji}</span>'
            f'<span class="meta"><span class="label">{label}</span><br>'
            f'<span class="count"><b>{total}</b>件</span></span>'
            f'<span class="chev">▼</span>'
        )

    def _render_detail_html(self, total, label, jump_hours, category_counts, highlights, has_trend=False, trend_container_id=""):
        """ダッシュボード帯の展開時詳細（集計・注目記事・推移グラフの枠）をHTML化する（Gemini不使用）"""
        html = (
            '<div class="dd-row">'
            f'<div class="dd-total">{total}<span>件・{label}</span></div>'
            f'<button class="dd-jump" data-hours="{jump_hours}" onclick="toggleDashTimeFilter({jump_hours})">この範囲だけ見る</button>'
            '</div>'
        )

        if category_counts:
            chips = "".join(
                f'<span class="chip">{cat} <b>{cnt}</b>件</span>'
                for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1])
            )
            html += f'<div class="chips">{chips}</div>'

        if has_trend:
            # 既読/未読の色分けはstate.readHistory(クライアント側のみ)が無いと出来ないため、
            # ここでは枠だけを用意し、実際のバー描画はJS側のrenderTrendChart()に委ねる。
            html += (
                '<div class="trend"><div class="trend-label">過去7日間の推移（下:既読／上:未読）</div>'
                f'<div class="trend-bars" id="{trend_container_id}"></div></div>'
            )

        if highlights:
            highlight_lines = "".join(
                f'<div class="hl-item">⭐ {it.get("title","")}</div>'
                for _, it in highlights[:10]
            )
            html += (
                f'<div class="highlights"><div class="hl-label">⭐ 注目記事 {len(highlights)}件</div>'
                f'{highlight_lines}</div>'
            )

        return html

    def _generate_ai_narrative(self, items, highlights, prompt_intro):
        """Gemini APIで注目記事優先のサンプルから横断的なトレンド解説を生成する。取得できない場合はNoneを返す"""
        try:
            from google import genai
        except ImportError:
            print("[Warning] google-genai is not installed. Skipping AI narrative.")
            return None

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[Warning] GEMINI_API_KEY is not set. Skipping AI narrative.")
            return None

        if not items:
            return None

        # 注目記事を優先し、残り枠を通常itemsで埋める（最大50件）
        highlight_ids = {id(it) for _, it in highlights}
        ordered = list(highlights) + [pair for pair in items if id(pair[1]) not in highlight_ids]
        sample = ordered[:50]

        prompt = prompt_intro + "\n\n"
        for fd, it in sample:
            prompt += f"- [{fd.get('category','')}] {it.get('title')}: {it.get('summary')}\n"

        client = genai.Client(api_key=api_key)
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config={'http_options': {'timeout': 60000}}
                )
                return self._format_narrative_html(response.text.strip())
            except Exception as e:
                print(f"[Warning] Gemini API Request failed (Attempt {attempt + 1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    print("[Info] Retrying in 2 seconds...")
                    time.sleep(2)
                else:
                    print("[Error] Gemini API narrative generation failed after retries.")
                    return None
        return None

    def _format_narrative_html(self, text):
        """マークダウン記法（**強調**・箇条書き）をHTMLタグに変換する"""
        formatted = text
        if formatted:
            formatted = re.sub(r'\*\*(.*?)\*\*', r'<span style="color:#3182ce; font-weight:bold;">\1</span>', formatted)
            formatted = formatted.replace('* ', '<br>・ ')
            formatted = formatted.replace('\n', '<br>')
        return f'<div style="margin-top:10px; padding-top:8px; border-top:1px solid #e2e8f0;">{formatted}</div>'

    def _build_period_overview(self, data_list, hours, emoji, label, jump_hours, prompt_intro,
                                cache_filename, include_trend=False):
        """
        指定時間幅（トレイリングウィンドウ）のダッシュボード帯用データ(tile_html/detail_html)を構築する(Track 0)。
        対象0件ならNoneを返す（＝そのタイルごと非表示）。
        Gemini呼び出しはコストがかかるため、ウィンドウ内のファイル構成（＝中身）が前回生成時から
        変化していなければキャッシュした結果をそのまま再利用する。
        """
        now_ts = time.time()
        now_dt = datetime.fromtimestamp(now_ts)
        since_ts = now_ts - hours * 3600

        window_files = [fd for fd in data_list if fd.get('mtime', 0) >= since_ts]
        items = self._collect_window_items(data_list, since_ts)
        if not items:
            return None

        # ウィンドウ内のファイル構成が変わったかどうかで中身の変化を判定する。
        # スキーマバージョンも含めることで、出力形式の変更時に古いキャッシュを強制的に破棄する。
        state_str = f"schema{DASHBOARD_CACHE_SCHEMA_VERSION}:" + ",".join(sorted(fd.get('filename', '') for fd in window_files))
        current_hash = hashlib.md5(state_str.encode('utf-8')).hexdigest()

        if not os.path.exists(self.json_dir):
            try:
                os.makedirs(self.json_dir)
            except Exception as e:
                print(f"[Warning] Failed to create json directory: {e}")

        cache_file = os.path.join(self.json_dir, cache_filename)
        # [20260809] 旧バージョンはtarget_folder直下に書いていた。新しい場所に
        # まだ無ければ、そちらを読む（無ければ単に「未キャッシュ」として
        # 新規生成すればよいだけなので、DBほど厳密な移行は不要）。
        legacy_cache_file = os.path.join(self.target_folder, cache_filename)
        read_from = cache_file if os.path.exists(cache_file) else legacy_cache_file
        if os.path.exists(read_from):
            try:
                with open(read_from, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    if cache_data.get("hash") == current_hash:
                        print(f"[Info] Using cached overview ({cache_filename}, unchanged).")
                        return cache_data.get("dashboard_entry")
            except Exception as e:
                print(f"[Warning] Failed to read overview cache ({cache_filename}): {e}")

        print(f"[Info] Generating new overview ({cache_filename})...")

        category_counts = {}
        highlights = []
        for fd, it in items:
            cat = fd.get('category', 'UNKNOWN')
            category_counts[cat] = category_counts.get(cat, 0) + 1
            if self._is_highlighted_item(it):
                highlights.append((fd, it))

        trend = self._compute_daily_trend(data_list, now_dt, days=7) if include_trend else None
        trend_container_id = "weeklyTrendBars" if include_trend else ""
        detail_html = self._render_detail_html(
            len(items), label, jump_hours, category_counts, highlights,
            has_trend=include_trend, trend_container_id=trend_container_id
        )
        narrative_html = self._generate_ai_narrative(items, highlights, prompt_intro)
        if not narrative_html:
            narrative_html = (
                '<div style="margin-top:8px; font-size:0.85em; color:#a0aec0;">'
                '（AI解説はGEMINI_API_KEY未設定または生成失敗のため省略されました）</div>'
            )
        detail_html += narrative_html
        detail_html += f'<div class="stale-note">最終更新 {now_dt.strftime("%m/%d %H:%M")}</div>'

        dashboard_entry = {
            "tile_html": self._render_tile_html(emoji, label, len(items)),
            "detail_html": detail_html,
            "trend": trend,
        }

        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({"hash": current_hash, "dashboard_entry": dashboard_entry}, f, ensure_ascii=False)
            if read_from == legacy_cache_file and os.path.exists(legacy_cache_file):
                try:
                    os.remove(legacy_cache_file)
                except Exception as e:
                    print(f"[Warning] Failed to remove legacy overview cache file: {e}")
        except Exception as e:
            print(f"[Warning] Failed to write overview cache ({cache_filename}): {e}")

        return dashboard_entry

    def generate_manager_html(self, data_list):
        # Track 0 (俯瞰ダッシュボード帯) の生成：直近24時間・直近7日間の2タイル
        # カード一覧(data_list)には混ぜず、専用のダッシュボード帯として別データで渡す
        daily_overview = self._build_period_overview(
            data_list, hours=24, emoji="🌟", label="直近24時間", jump_hours=24,
            prompt_intro=(
                "以下は直近24時間に追加されたニュース・動画です。"
                "複数ソースで共通して言及されているテーマを2〜3個挙げ、それぞれ1〜2文で解説してください。"
            ),
            cache_filename="overview_cache_daily.json",
        )
        weekly_overview = self._build_period_overview(
            data_list, hours=24 * 7, emoji="📅", label="直近7日間", jump_hours=24 * 7,
            prompt_intro=(
                "以下は直近7日間に追加されたニュース・動画です。"
                "この1週間で特に注目すべき流れやテーマを2〜3個挙げ、それぞれ1〜2文で解説してください。"
            ),
            cache_filename="overview_cache_weekly.json",
            include_trend=True,
        )
        dashboard_data = {"daily": daily_overview, "weekly": weekly_overview}

        # ensure_ascii=Trueにすることで非ASCII文字もエスケープし、JS埋め込み時の問題を回避
        # ただし日本語が読みにくくなるため、シングルクォートのみ \u0027 にエスケープする
        json_data_str = json.dumps(data_list, ensure_ascii=False).replace("'", r"\u0027")

        
        dashboard_data_str = json.dumps(dashboard_data, ensure_ascii=False).replace("'", r"\u0027")

        # 新関数群: r"""...""" で管理（Pythonエスケープ変換を回避）
        NEW_FUNCTIONS_JS = r"""
        // localStorageからAPIKeyを取得、なければinput UIで入力させて保存
        // iOSではprompt()がWKWebViewやローカルHTMLで動作しない場合があるため
        // モーダルUIで代替する
        function getOrAskApiKey() {
            let key = localStorage.getItem('gemini_api_key');
            if (key && key.trim() !== '') return key.trim();
            return null; // 非同期入力はshowApiKeyModalで処理
        }

        function showApiKeyModal(onSuccess) {
            // 既存モーダルがあれば除去
            const existing = document.getElementById('apiKeyModal');
            if (existing) existing.remove();

            const modal = document.createElement('div');
            modal.id = 'apiKeyModal';
            modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';
            modal.innerHTML = `
                <div style="background:white;border-radius:12px;padding:24px;width:90%;max-width:400px;box-shadow:0 4px 20px rgba(0,0,0,0.3);">
                    <div style="font-weight:bold;font-size:1.05em;margin-bottom:12px;">&#x1F511; Gemini APIキーを入力</div>
                    <div style="font-size:0.85em;color:#718096;margin-bottom:12px;">入力したキーはブラウザのlocalStorageに保存されます。</div>
                    <input id="apiKeyInput" type="password" placeholder="AIza..." style="width:100%;padding:10px;border:1px solid #cbd5e0;border-radius:8px;font-size:0.95em;box-sizing:border-box;margin-bottom:14px;">
                    <div style="display:flex;gap:10px;">
                        <button id="apiKeyCancelBtn" style="flex:1;padding:10px;border:1px solid #cbd5e0;border-radius:8px;background:#f7fafc;cursor:pointer;font-size:0.9em;">キャンセル</button>
                        <button id="apiKeySaveBtn" style="flex:2;padding:10px;border:none;border-radius:8px;background:#3182ce;color:white;cursor:pointer;font-size:0.9em;font-weight:bold;">保存して生成</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            document.getElementById('apiKeySaveBtn').addEventListener('click', () => {
                const val = document.getElementById('apiKeyInput').value.trim();
                if (!val) { alert('APIキーを入力してください。'); return; }
                localStorage.setItem('gemini_api_key', val);
                modal.remove();
                onSuccess(val);
            });
            document.getElementById('apiKeyCancelBtn').addEventListener('click', () => {
                modal.remove();
            });
            // モーダル外クリックで閉じる
            modal.addEventListener('click', (e) => {
                if (e.target === modal) modal.remove();
            });
            // iOSでキーボードが出た後にフォーカス
            setTimeout(() => { const inp = document.getElementById('apiKeyInput'); if(inp) inp.focus(); }, 100);
        }

        // RSSカードの結論・主なポイントをGemini APIでオンデマンド生成
        // URLはdata-url属性から取得（onclick内に直接埋め込まないことでエスケープ問題を回避）
        async function fetchDetailConsolidated(fIdx, iIdx) {
            const apiKey = getOrAskApiKey();
            if (!apiKey) {
                // APIキー未設定 → モーダルUIで入力を促し、入力後に再実行
                showApiKeyModal((newKey) => fetchDetailConsolidatedWithKey(fIdx, iIdx, newKey));
                return;
            }
            fetchDetailConsolidatedWithKey(fIdx, iIdx, apiKey);
        }

        async function fetchDetailConsolidatedWithKey(fIdx, iIdx, apiKey) {

            const btn = document.getElementById(`detail-btn-${fIdx}-${iIdx}`);
            if (!btn) return;
            const url = btn.getAttribute('data-url') || '';
            if (!url) { alert('記事URLが取得できませんでした。'); return; }
            btn.classList.add('loading');
            btn.textContent = '⏳ 生成中...';
            btn.disabled = true;

            const prompt = `以下のURLの記事を読み、日本語で次の2項目を出力してください。

URL: ${url}

出力形式（必ずこの形式で出力）:
[CONCLUSION]
結論テキスト（300文字以内）
[/CONCLUSION]
[POINTS]
## 見出し1
・ポイント内容（100文字程度）
・ポイント内容（100文字程度）
## 見出し2
・ポイント内容（100文字程度）
・ポイント内容（100文字程度）
## 見出し3
・ポイント内容（100文字程度）
・ポイント内容（100文字程度）
[/POINTS]
重要: ## 行は見出し、・行はその配下の箇条書きとする。番号は使わないこと。`;

            const requestBody = {
                contents: [{ parts: [{ text: prompt }] }],
                tools: [{ url_context: {} }],
                generationConfig: {
                    maxOutputTokens: 2048
                }
            };

            // モデルリスト: 高負荷時は順番にフォールバック
            const modelList = ['gemini-2.5-flash', 'gemini-2.5-flash-lite'];
            let rawText = '';
            let lastErr = null;

            for (const model of modelList) {
                const apiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
                try {
                    const resp = await fetch(apiUrl, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(requestBody)
                    });
                    if (!resp.ok) {
                        const errData = await resp.json().catch(() => ({}));
                        const errMsg = errData?.error?.message || resp.statusText;
                        if (resp.status === 503 || resp.status === 429) {
                            // 高負荷/レート制限 → 次のモデルを試す
                            lastErr = new Error(`APIエラー (${resp.status}) [${model}]: ${errMsg}`);
                            continue;
                        }
                        throw new Error(`APIエラー (${resp.status}): ${errMsg}`);
                    }
                    const data = await resp.json();
                    // Gemini 2.5系のThinkingモード対応：全partsのテキストを結合
                    // parts[0]=思考プロセス / parts[1]=実回答 の場合があるため全結合
                    rawText = (data?.candidates?.[0]?.content?.parts || [])
                        .map(p => p.text || '')
                        .join('\n');
                    lastErr = null;
                    break; // 成功
                } catch (fetchErr) {
                    if (fetchErr.message.startsWith('APIエラー') && !fetchErr.message.includes('503') && !fetchErr.message.includes('429')) {
                        throw fetchErr; // 503/429 以外は即時エラー
                    }
                    lastErr = fetchErr;
                }
            }

            if (!rawText) {
                throw lastErr || new Error('APIからの応答が空でした');
            }

            try {
                // [CONCLUSION]...[/CONCLUSION] と [POINTS]...[/POINTS] をパース
                // 正規表現を使わずindexOfベースで実装（Python/iOS正規表現エスケープ問題を回避）
                let conclusionText = '';
                let pointsRaw = '';

                const TAG_C_OPEN  = '[CONCLUSION]';
                const TAG_C_CLOSE = '[/CONCLUSION]';
                const TAG_P_OPEN  = '[POINTS]';
                const TAG_P_CLOSE = '[/POINTS]';

                const cStart = rawText.indexOf(TAG_C_OPEN);
                const cEnd   = rawText.indexOf(TAG_C_CLOSE);
                const pStart = rawText.indexOf(TAG_P_OPEN);
                const pEnd   = rawText.indexOf(TAG_P_CLOSE);

                if (cStart !== -1) {
                    const afterCOpen = cStart + TAG_C_OPEN.length;
                    if (cEnd !== -1 && cEnd > afterCOpen) {
                        conclusionText = rawText.substring(afterCOpen, cEnd).trim();
                    } else if (pStart !== -1 && pStart > afterCOpen) {
                        conclusionText = rawText.substring(afterCOpen, pStart).trim();
                    } else {
                        conclusionText = rawText.substring(afterCOpen, afterCOpen + 300).trim();
                    }
                } else {
                    // タグなし: 先頭から最初の空行まで
                    const rawLines0 = rawText.trim().split('\n');
                    const sepIdx = rawLines0.findIndex((l, i) => i > 0 && l.trim() === '');
                    conclusionText = (sepIdx > 0 ? rawLines0.slice(0, sepIdx) : rawLines0.slice(0, 3)).join(' ').trim();
                }

                if (pStart !== -1) {
                    const afterPOpen = pStart + TAG_P_OPEN.length;
                    pointsRaw = pEnd !== -1 && pEnd > afterPOpen
                        ? rawText.substring(afterPOpen, pEnd).trim()
                        : rawText.substring(afterPOpen).trim();
                }

                // 安全層: 結論テキストからタグ残渣を除去
                const tagsToRemove = ['[CONCLUSION]', '[/CONCLUSION]', '[POINTS]', '[/POINTS]'];
                tagsToRemove.forEach(tag => {
                    while (conclusionText.includes(tag)) {
                        conclusionText = conclusionText.split(tag).join('');
                    }
                });
                conclusionText = conclusionText.trim();

                // 結論エリアを更新
                const conclusionArea = document.getElementById(`conclusion-area-${fIdx}-${iIdx}`);
                if (conclusionArea) {
                    const conclusionHtml = conclusionText.split('\n').join('<br>');
                    conclusionArea.innerHTML = conclusionHtml;
                    conclusionArea.className = 'conclusion-text-unified';
                }

                // ## 見出し・箇条書き形式 → YouTube section-content 互換HTMLに変換
                // ※ item.points はページ内どこでもHTML文字列として扱われる（buildPointTitlesListの
                //    querySelectorAll('p.fw-bold')、読み上げ時のtempDiv.innerHTML経由のtextContent抽出など）ため、
                //    ここで生のMarkdown（pointsRaw）ではなく変換後のHTML（pointsHtml）を使う必要がある。
                //    pointsRawのまま読み上げに渡すと「##」が音声で「ハッシュタグ」と読まれてしまう。
                let pointsHtml = '';
                if (pointsRaw) {
                    const pointLines = pointsRaw.split('\n').filter(l => l.trim() !== '');
                    let inList = false;
                    pointLines.forEach(l => {
                        const trimmed = l.trim();
                        if (trimmed.startsWith('## ')) {
                            // 見出し行: 直前のulを閉じてから見出しpを出力
                            if (inList) { pointsHtml += '</ul>'; inList = false; }
                            const headingText = trimmed.replace(/^##\s*/, '');
                            pointsHtml += `<p class="fw-bold" style="color:#2b6cb0; font-size:1.0em; font-weight:700; margin-top:10px; margin-bottom:4px;">${headingText}</p>`;
                        } else if (trimmed.startsWith('・') || trimmed.startsWith('•') || trimmed.startsWith('-') || trimmed.match(/^[\d]+\.\s/)) {
                            // 箇条書き行: ulが未開始なら開く
                            if (!inList) { pointsHtml += '<ul class="markdown-list" style="padding-left:18px; margin-top:2px; margin-bottom:6px;">'; inList = true; }
                            const itemText = trimmed.replace(/^[・•\-]\s*|^[\d]+\.\s*/, '');
                            pointsHtml += `<li style="font-size:1.0em; line-height:1.6; color:#4a5568; margin-bottom:3px;">${itemText}</li>`;
                        } else if (trimmed.length > 0) {
                            // 見出しでも箇条書きでもない行: liとして扱う（フォールバック）
                            if (!inList) { pointsHtml += '<ul class="markdown-list" style="padding-left:18px; margin-top:2px; margin-bottom:6px;">'; inList = true; }
                            pointsHtml += `<li style="font-size:1.0em; line-height:1.6; color:#4a5568; margin-bottom:3px;">${trimmed}</li>`;
                        }
                    });
                    if (inList) { pointsHtml += '</ul>'; } // 末尾のulを閉じる
                }

                // ポイントエリアを更新（アコーディオン、初期状態：閉じた状態）
                const pointsArea = document.getElementById(`points-area-${fIdx}-${iIdx}`);
                if (pointsArea && pointsHtml) {
                    pointsArea.innerHTML = `
                        <button class="points-accordion-btn" id="points-acc-btn-${fIdx}-${iIdx}" onclick="togglePointsAccordion(${fIdx}, ${iIdx})">▶ 主なポイントを表示</button>
                        <div class="points-wrapper section-content" id="points-wrapper-${fIdx}-${iIdx}" style="display:none; padding:10px; background:#f7fafc; border-radius:5px;">${pointsHtml}</div>
                    `;
                    pointsArea.style.display = 'block';
                    openPointsAccordion(fIdx, iIdx);
                    // point-titles-divをポイント生成後に更新・表示
                    const ptDiv = document.getElementById(`point-titles-${fIdx}-${iIdx}`);
                    if (ptDiv) {
                        // ポイント生成完了後はアコーディオン内の見出しと重複するため非表示
                        ptDiv.style.display = 'none';
                    }

                }


                // flatQueue内のitemに結論・ポイントを反映（読み上げ用）
                const qData = flatQueue.find(q => q.fIdx === fIdx && q.iIdx === iIdx);
                if (qData) {
                    qData.item.conclusion = conclusionText;
                    if (pointsHtml) qData.item.points = pointsHtml;
                }

                // ボタンを「✅ 生成済み」に変更
                btn.classList.remove('loading');
                btn.classList.add('done');
                btn.textContent = '✅ 生成済み';
                btn.disabled = true;

            } catch (parseErr) {
                console.error('[fetchDetailConsolidated] Parse error:', parseErr);
                btn.classList.remove('loading');
                btn.textContent = `⚠️ エラー: ${parseErr.message}`;
                btn.style.background = '#fed7d7';
                btn.style.color = '#c53030';
                btn.style.borderColor = '#fc8181';
                btn.disabled = false;
            }
        }

        // [20260804] Mode1（▶・主なポイント本文を一時的に読み上げ）専用。
        // RSSカードでまだ主なポイントが無い場合、生成ボタン押下と同じ処理を自動で
        // バックグラウンド起動し、その完了を待てるようPromiseをMapに記録する。
        // 既に生成中/生成済み/APIキー未設定（モーダルで再生を止めないため）の場合はnullを返す。
        const rssPointsGenerationPromises = new Map();
        function triggerRssPointsGenerationIfNeeded(fIdx, iIdx) {
            const key = `${fIdx}-${iIdx}`;
            if (rssPointsGenerationPromises.has(key)) return rssPointsGenerationPromises.get(key);

            const qData = flatQueue.find(q => q.fIdx === fIdx && q.iIdx === iIdx);
            if (!qData || qData.item.type !== 'rss' || qData.item.points) return null;

            const btn = document.getElementById(`detail-btn-${fIdx}-${iIdx}`);
            if (!btn || btn.disabled || btn.classList.contains('loading')) return null;

            const apiKey = getOrAskApiKey();
            if (!apiKey) return null; // モーダル入力待ちは連続読み上げと相性が悪いため自動生成を諦める

            const promise = fetchDetailConsolidatedWithKey(fIdx, iIdx, apiKey).catch(err => {
                console.error('[Mode1 RSS auto-generate] failed:', err);
            });
            rssPointsGenerationPromises.set(key, promise);
            return promise;
        }
"""

        html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Consolidated Summary Manager</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background-color: #f0f2f5; padding-bottom: 120px; color: #333; }
        /* [20260804] パネル開閉ボタンをFAB列からヘッダー右端の常設トグルへ移設。
           左右対称に46px確保することで、再生中に見出しが「ファイル名 (n/総数件)」
           へ差し替わっても、ボタンの下に文字が潜り込まないようにしている。 */
        .app-header { background: #2b6cb0; color: white; padding: 12px 46px; text-align: center; font-weight: bold; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 4px rgba(0,0,0,0.1); font-size: 0.95rem; line-height: 1.3; display: flex; align-items: center; justify-content: center;}
        .app-header-text { word-break: break-all; }
        /* [20260805] 1行目=ファイル名、2行目=読み上げ位置、で固定表示するための子要素 */
        .header-position { display: block; font-size: 0.76rem; font-weight: 500; opacity: 0.85; margin-top: 1px; }
        .header-toggle-btn { position: absolute; right: 9px; top: 50%; transform: translateY(-50%); width: 28px; height: 24px; border-radius: 7px; background: #ffffff; color: #2b6cb0; display: flex; align-items: center; justify-content: center; box-shadow: 0 1px 3px rgba(0,0,0,0.25); cursor: pointer; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; transition: background 0.15s, transform 0.15s;}
        /* [20260808] 矢印の向きが逆だった。SVGパス(M1 1L6 6L11 1)は下向きシェブロンで、
           開いている状態で下向き・閉じている状態で上向きになっていた。
           「開＝上向き（閉じられる方向を示す）／閉＝下向き（開ける方向を示す）」へ反転する。 */
        .header-toggle-btn svg { display: block; transition: transform 0.25s ease; transform: rotate(180deg); }
        .header-toggle-btn.closed svg { transform: rotate(0deg); }
        .header-toggle-btn:hover { background: #f3f7fc; }
        .header-toggle-btn:active { transform: translateY(-50%) scale(0.94); }

        /* [20260804] ダッシュボード帯(.dash-tiles-wrap)をヘッダーと絞込パネルの間に追加。
           ヘッダー/ダッシュボード帯/絞込パネルの実高さは端末やフォント描画で変わるため、
           top位置とスクロール時のオフセットは固定px値で決め打ちせず、updateStickyOffsets()が
           実測してCSS変数(--dash-top/--panel-top/--scroll-offset)に反映する。
           ここに書くpx値はJS実行前・失敗時のフォールバックに過ぎない。 */
        .control-panel { background: white; padding: 12px 15px; position: sticky; top: var(--panel-top, 100px); z-index: 98; box-shadow: 0 2px 4px rgba(0,0,0,0.05); transition: max-height 0.3s ease-out, padding 0.3s ease-out, opacity 0.2s; overflow: hidden; max-height: 500px;}
        .control-panel.closed { max-height: 0; padding-top: 0; padding-bottom: 0; border: none; opacity: 0;}

        .dash-tiles-wrap { background: #fff; position: sticky; top: var(--dash-top, 48px); z-index: 99; border-bottom: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(0,0,0,0.05); overflow: hidden; max-height: 120px; transition: max-height 0.3s ease-out, opacity 0.2s; }
        .dash-tiles-wrap.closed { max-height: 0; opacity: 0; border: none; box-shadow: none; }
        #dashTilesWrap.closed ~ .dash-detail { max-height: 0 !important; }
        .dash-tiles { display: flex; min-height: 52px; }
        .dash-tile { flex: 1; display: flex; align-items: center; gap: 10px; padding: 11px 14px; cursor: pointer; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; border: none; background: transparent; font-family: inherit; text-align: left; transition: background 0.15s; }
        .dash-tile:empty { display: none; }
        .dash-tile:first-child { border-right: 1px solid #edf1f5; }
        .dash-tile .emoji { font-size: 1.15rem; line-height: 1; }
        .dash-tile .meta { min-width: 0; flex: 1; }
        .dash-tile .label { font-size: 0.68rem; color: #8492a6; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; }
        .dash-tile .count { font-size: 1.05rem; font-weight: 800; color: #1a202c; font-variant-numeric: tabular-nums; line-height: 1.25; }
        .dash-tile .count b { color: #2b6cb0; }
        .dash-tile .chev { color: #a0aec0; font-size: 0.7rem; transition: transform 0.2s; flex-shrink: 0; }
        .dash-tile.open .chev { transform: rotate(180deg); color: #2b6cb0; }
        .dash-tile.open { background: #ebf8ff; }

        /* [20260805] 600px固定では注目記事が多い日などに本文が収まりきらず見切れていたため、
           開いた時の上限を70vh(画面の70%)まで拡張し、それでも収まらない場合のみ
           カード内スクロールに切り替える(overflow-y:auto)。通常は最後まで表示され、
           極端に長い場合だけカード内で読める。 */
        .dash-detail { max-height: 0; overflow-x: hidden; overflow-y: auto; transition: max-height 0.3s ease; background: #fafbfc; }
        .dash-detail.open { max-height: 70vh; }
        .dash-detail:empty, .dash-detail:has(.dash-detail-inner:empty) { display: none; }
        .dash-detail-inner { padding: 14px 16px 18px; border-top: 1px solid #e2e8f0; }

        .dd-row { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; gap: 10px; }
        .dd-total { font-size: 1.5rem; font-weight: 800; color: #2b6cb0; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .dd-total span { font-size: 0.72rem; font-weight: 600; color: #8492a6; margin-left: 4px; }
        .dd-jump { font-size: 0.78rem; color: #3182ce; font-weight: 700; cursor: pointer; padding: 4px 10px; border: 1px solid #bee3f8; border-radius: 14px; background: #fff; white-space: nowrap; font-family: inherit; }
        .dd-jump:active { background: #ebf8ff; }
        .dd-jump.active { background: #3182ce; color: #fff; border-color: #3182ce; }

        .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
        .chip { display: inline-flex; align-items: center; gap: 4px; background: #ebf8ff; color: #2b6cb0; border-radius: 10px; padding: 3px 10px; font-size: 0.78rem; font-weight: 600; }
        .chip b { font-variant-numeric: tabular-nums; }

        .trend { margin-bottom: 12px; }
        .trend-label { font-size: 0.72rem; color: #8492a6; margin-bottom: 6px; font-weight: 600; }
        .trend-bars { display: flex; align-items: flex-end; gap: 5px; height: 72px; }
        .trend-bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; }
        .trend-bar-n { font-size: 0.62rem; color: #a0aec0; font-variant-numeric: tabular-nums; }
        /* [20260805] 既読(下・濃い青)/未読(上・薄い青)の積み上げ棒。renderTrendChart()がJS側で
           state.readHistoryを見ながら描画するため、既読が増えると再生成のたびに反映される。 */
        .trend-bar-stack { width: 100%; display: flex; flex-direction: column; }
        .trend-bar-unread { width: 100%; background: #a8d3f5; border-radius: 3px 3px 0 0; }
        .trend-bar-read { width: 100%; background: linear-gradient(180deg,#4299e1,#2b6cb0); border-radius: 0 0 1px 1px; }
        .trend-bar-unread.solo { border-radius: 3px 3px 1px 1px; }
        .trend-bar-read.solo { border-radius: 3px 3px 1px 1px; }
        .trend-day { font-size: 0.62rem; color: #a0aec0; white-space: nowrap; }

        .highlights { margin-bottom: 12px; }
        .hl-label { font-size: 0.72rem; color: #8492a6; margin-bottom: 5px; font-weight: 600; }
        .hl-item { font-size: 0.83rem; color: #4a5568; line-height: 1.55; }

        .stale-note { font-size: 0.72rem; color: #a0aec0; margin-top: 10px; }
        
        .control-row { display: flex; align-items: center; margin-bottom: 10px; gap: 10px; }
        .control-row:last-child { margin-bottom: 0; }
        .control-label { font-size: 0.85rem; color: #718096; white-space: nowrap; font-weight: bold; width: 45px;}
        
        .filter-tags { display: flex; gap: 6px; flex-wrap: wrap; flex-grow: 1;}
        .tag { padding: 4px 10px; background: #edf2f7; border-radius: 15px; font-size: 0.8rem; color: #4a5568; border: 1px solid #cbd5e0; cursor: pointer; user-select: none;}
        .tag.active { background: #3182ce; color: white; border-color: #3182ce; font-weight: bold; }
        .sort-select { padding: 5px; border-radius: 6px; border: 1px solid #cbd5e0; font-size: 0.85rem; flex-grow: 1; color: #2d3748;}
        
        .action-buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 5px; padding-top: 10px; border-top: 1px dashed #e2e8f0; }
        .btn-action { padding: 6px 12px; font-size: 0.8rem; border-radius: 6px; border: 1px solid #cbd5e0; background: #f7fafc; color: #4a5568; cursor: pointer; font-weight: bold;}
        .btn-action:active { background: #edf2f7; }
        .btn-toggle { background: #ebf8ff; color: #3182ce; border-color: #90cdf4; }
        .btn-toggle.on { background: #3182ce; color: white; border-color: #3182ce; }

        .file-list { padding: 15px; }
        .file-card { background: white; border-radius: 10px; padding: 15px; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); border-left: 4px solid transparent; transition: all 0.2s; scroll-margin-top: var(--scroll-offset, 252px);}
        .followed-note-card { border-left-color: #d4a017; }
        .file-card.disabled { opacity: 0.5; background: #f7fafc; }
        .file-card.all-read { background-color: #edf2f7; border-left-color: #a0aec0; }
        .file-card.all-read .file-title { color: #718096; }
        
        .card-header-row { display: flex; align-items: flex-start; gap: 12px; }
        .checkbox-container { padding-top: 2px; }
        .custom-checkbox { width: 20px; height: 20px; cursor: pointer; accent-color: #3182ce; }
        .file-info { flex-grow: 1; min-width: 0; cursor: pointer; }
        
        .file-title { font-size: 0.95rem; font-weight: 600; color: #2d3748; margin-bottom: 6px; word-break: break-all; line-height: 1.3;}
        .file-meta { font-size: 0.8rem; color: #718096; display: flex; justify-content: space-between;}
        
        .preview-area { margin-top: 12px; padding-top: 12px; border-top: 1px dashed #e2e8f0; display: none; }
        .file-card.expanded .preview-area { display: block; }
        
        .summary-item { font-size: 0.9rem; padding: 12px; border: 1px solid #e2e8f0; margin-bottom: 10px; border-radius: 8px; background: white; color: #4a5568; line-height: 1.5; scroll-margin-top: var(--scroll-offset, 262px);}
        .summary-item.active { border-color: #e53e3e; box-shadow: 0 0 8px rgba(229, 62, 62, 0.2); }
        .summary-item.error { color: #a0aec0; font-style: italic; background: #f7fafc; }
        .summary-item.read-done { background: #e2e8f0; border-color: #cbd5e0; }
        
        .info-badge { display: inline-block; padding: 2px 6px; background: #edf2f7; border-radius: 4px; font-size: 0.75rem; margin-right: 5px; margin-bottom: 5px; color: #4a5568;}
        
        /* Floating Buttons CSS */
        /* [20260804] 常用ボタン(5個)のみ常時表示にし、速度/ファイルジャンプは.more-hover-groupへ集約。
           列が短くなったことに加え、配置基準を画面縦中央から画面下部に変更し、
           上部のフィルターボタン群と物理的に重ならないようにしている。 */
        .fab-container { position: fixed; bottom: 18px; right: 10px; display: flex; flex-direction: column; gap: 10px; z-index: 1000; pointer-events: none;}
        .fab { position: relative; pointer-events: auto; width: 54px; height: 54px; border-radius: 27px; background: rgba(255, 255, 255, 0.05); color: #3182ce; border: 1px solid rgba(49, 130, 206, 0.2); box-shadow: 0 2px 8px rgba(0,0,0,0.1); display: flex; justify-content: center; align-items: center; cursor: pointer; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; font-size: 22px; transition: all 0.2s;}
        .fab::after { content: ''; position: absolute; top: -15px; right: -15px; bottom: -15px; left: -15px; border-radius: 50%; background: transparent; }
        .fab:active { transform: scale(0.95); }
        
        .fab.skip-btn { font-size: 18px; }
        .fab.skip-btn.temp { color: #3182ce; font-size: 18px; border: 2px solid #3182ce;}
        .fab.skip-btn.fixed { background: rgba(49, 130, 206, 0.4); color: white; font-size: 18px; border: none;}
        .fab.skip-btn.conclusion { color: #38a169; font-size: 18px; border: 2px solid #38a169;}

        /* [20260805] mode1クイックボタン(▶)の非アクティブ時配色。▶▶（btnSkip）と同じ配色で
           現在どちらのモードで読んでいるか見分けにくいとの指摘のため、mode1が現在アクティブで
           ない間は背景・枠線をグレーに落として目立ちを抑える。文字色(▶)は青のまま維持し、
           後ろの記号自体は判別できるようにする。アクティブ時(active-mode1クラス付与時)は
           従来の配色に戻す。IDセレクタで.fab.skip-btn.tempの配色より優先させている。 */
        #btnSkipMode1Quick { background: rgba(160, 174, 192, 0.35); border-color: #718096; }
        #btnSkipMode1Quick.active-mode1 { background: rgba(255, 255, 255, 0.05); border-color: #3182ce; }
        /* [20260808] mode3（タイトルのみ）専用クイックボタン。mode1と同じ配色ルール。
           非アクティブ時はグレーで沈め、選択中のみ通常配色に戻して現在モードが
           一目で分かるようにする。IDセレクタで .fab.skip-btn より優先させている。 */
        #btnSkipMode3Quick { background: rgba(160, 174, 192, 0.35); border-color: #718096; font-size: 16px; }
        #btnSkipMode3Quick.active-mode3 { background: rgba(255, 255, 255, 0.05); border-color: #3182ce; }

        /* Skip Mode Hover Buttons */
        .skip-hover-group { position: absolute; right: 62px; top: 50%; transform: translateY(-50%); display: flex; flex-direction: row; gap: 5px; align-items: center; opacity: 0; pointer-events: none; transition: opacity 0.18s ease; white-space: nowrap; }
        .skip-hover-group.visible { opacity: 1; pointer-events: auto; }
        .skip-hover-btn { width: 44px; height: 44px; border-radius: 22px; background: rgba(255,255,255,0.95); color: #3182ce; border: 1px solid rgba(49,130,206,0.45); box-shadow: 0 2px 8px rgba(0,0,0,0.18); display: flex; justify-content: center; align-items: center; cursor: pointer; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; font-size: 13px; font-weight: bold; transition: background 0.12s, color 0.12s; touch-action: manipulation; }
        .skip-hover-btn:active { background: #3182ce; color: white; border-color: #3182ce; }
        .skip-hover-btn.active-skip { background: #3182ce; color: white; border-color: #3182ce; }
        .skip-hover-btn.fixed-skip { background: rgba(49, 130, 206, 0.4); color: white; border-color: rgba(49, 130, 206, 0.4); }
        .skip-hover-btn.active-skip.fixed-skip { background: #3182ce; color: white; border-color: #3182ce; }
        .skip-hover-btn.conclusion-skip { background: #38a169; color: white; border-color: #38a169; }
        .skip-hover-btn.active-skip.conclusion-skip { background: #38a169; color: white; border-color: #38a169; }
        
        .fab.primary { border: 2px solid #3182ce; background: rgba(255, 255, 255, 0.05); }
        .fab.primary.playing { background: rgba(229, 62, 62, 0.6); color: white; border: none; }
        .fab.speed { font-size: 14px; font-weight: bold; overflow: visible; }
        .fab.speed.reset-flash { background: #3182ce; color: white; border-color: #3182ce; transform: scale(1.1); }
        .fab.move-fixed { background: #3182ce; color: white; border-color: #3182ce; }

        /* Speed Hover Buttons */
        .speed-hover-group { position: absolute; right: 62px; top: 50%; transform: translateY(-50%); display: flex; flex-direction: row; gap: 5px; align-items: center; opacity: 0; pointer-events: none; transition: opacity 0.18s ease; white-space: nowrap; }
        .speed-hover-group.visible { opacity: 1; pointer-events: auto; }
        .speed-hover-btn { width: 44px; height: 44px; border-radius: 22px; background: rgba(255,255,255,0.95); color: #3182ce; border: 1px solid rgba(49,130,206,0.45); box-shadow: 0 2px 8px rgba(0,0,0,0.18); display: flex; justify-content: center; align-items: center; cursor: pointer; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; font-size: 11px; font-weight: bold; transition: background 0.12s, color 0.12s; touch-action: manipulation; }
        .speed-hover-btn:active { background: #3182ce; color: white; border-color: #3182ce; }
        .speed-hover-btn.active-speed { background: #3182ce; color: white; border-color: #3182ce; }

        /* [20260804] 「•••」ボタン: 速度設定・HTMLサマリジャンプ(前/次ファイル)をまとめて格納する。
           展開方式はskip/speed-hover-groupと同じ「タップで左に横並び展開」。
           格納されたbtnSpeedは自身のspeed-hover-groupを引き続き持つため、
           •••展開後もこれまで通りタップで速度候補を選べる。 */
        .fab.more { font-size: 20px; font-weight: 800; letter-spacing: 1px; color: #718096; background: rgba(255,255,255,0.05); }
        .fab.more.open { background: #3182ce; color: white; border-color: #3182ce; }
        .more-hover-group { position: absolute; right: 62px; top: 50%; transform: translateY(-50%); display: flex; flex-direction: row; gap: 8px; align-items: center; opacity: 0; pointer-events: none; transition: opacity 0.18s ease; white-space: nowrap; }
        .more-hover-group.visible { opacity: 1; pointer-events: auto; }
        .more-hover-group .fab { width: 50px; height: 50px; }

        /* RSSカード オンデマンド生成ボタン */
        .detail-btn-consolidated { display: block; width: 100%; padding: 7px 12px; margin-bottom: 8px; font-size: 0.85rem; border-radius: 6px; border: 1px solid #d69e2e; background: #fefcbf; color: #744210; cursor: pointer; font-weight: bold; text-align: center; }
        .detail-btn-consolidated:active { background: #faf089; }
        .detail-btn-consolidated.done { background: #c6f6d5; color: #276749; border-color: #68d391; cursor: default; }
        .detail-btn-consolidated.loading { background: #bee3f8; color: #2a69ac; border-color: #90cdf4; cursor: wait; }
        .points-accordion-btn { display: block; width: 100%; padding: 5px 10px; margin-top: 6px; margin-bottom: 4px; font-size: 0.82rem; border-radius: 5px; border: 1px solid #cbd5e0; background: #f7fafc; color: #4a5568; cursor: pointer; font-weight: bold; text-align: left; }
        .points-accordion-btn:active { background: #edf2f7; }
        /* 結論テキスト統一スタイル（RSS・YouTube共通） */
        .conclusion-text-unified { font-size: 0.95em; line-height: 1.7; color: #4a5568; margin-bottom: 10px; display: block; }
        /* section-content 内見出し・リスト（YouTube HTMLサマリー構造を Manager内で正しく描画するため） */
        .section-content p.fw-bold { color: #2b6cb0; font-size: 1.0em; font-weight: 700; margin-top: 10px; margin-bottom: 4px; }
        .section-content ul { padding-left: 18px; margin-top: 2px; margin-bottom: 6px; }
        .section-content ul li { font-size: 1.0em; line-height: 1.6; color: #4a5568; margin-bottom: 3px; }
        /* ondemand生成ポイント（シンプルulのみの場合のフォールバック） */
        .points-wrapper ul { padding-left: 18px; margin: 0; }
        .points-wrapper ul li { font-size: 1.0em; line-height: 1.6; color: #4a5568; margin-bottom: 3px; }
        .point-titles-list { margin: 4px 0 8px 0; padding: 0; list-style: none; }
        .point-titles-list li { padding: 2px 0; font-size: 0.95em; line-height: 1.6; color: #2d3748; }
        .point-titles-list li::before { content: '・'; }
        /* 既読同期ボタン */
    </style>
</head>
<body>

    <div class="app-header" id="appHeader">
        <span class="app-header-text" id="appHeaderText">Summary Folder Manager</span>
        <div class="header-toggle-btn" id="btnTogglePanel" title="パネル開閉">
            <svg width="13" height="9" viewBox="0 0 12 8" fill="none"><path d="M1 1L6 6L11 1" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </div>
    </div>

    <div class="dash-tiles-wrap" id="dashTilesWrap">
        <div class="dash-tiles">
            <button class="dash-tile" id="dashTileDaily" data-target="dashDetailDaily"></button>
            <button class="dash-tile" id="dashTileWeekly" data-target="dashDetailWeekly"></button>
        </div>
    </div>
    <div class="dash-detail" id="dashDetailDaily"><div class="dash-detail-inner" id="dashDetailDailyInner"></div></div>
    <div class="dash-detail" id="dashDetailWeekly"><div class="dash-detail-inner" id="dashDetailWeeklyInner"></div></div>

    <div class="control-panel" id="controlPanel">
        <div class="control-row">
            <div class="control-label">絞込:</div>
            <div class="filter-tags" id="filterTags"></div>
        </div>
        <div class="control-row">
            <div class="control-label">並順:</div>
            <select class="sort-select" id="sortSelect">
                <option value="date_desc">更新日時 (新しい順) ▼</option>
                <option value="date_asc">更新日時 (古い順) ▲</option>
                <option value="name_asc">ファイル名 (A→Z) ▼</option>
            </select>
        </div>
        <div class="action-buttons">
            <button class="btn-action" id="btnSelectAll">✓ 全て選択</button>
            <button class="btn-action" id="bDeselectAll">◻ 全て解除</button>
            <button class="btn-action btn-toggle" id="btnToggleSelected">☑ 選択中のみ表示</button>
            <button class="btn-action btn-toggle on" id="btnToggleUnread">👁️ 未読のみ表示</button>
            <button class="btn-action" id="btnToggleAllCards">📂 全カード開く</button>
            <button class="btn-action" id="btnToggleAllPoints">📝 全ポイント開く</button>
            <button class="btn-action btn-toggle on" id="btnToggleVoice">🎙️ 高音質</button>
        </div>
    </div>

    <div class="file-list" id="fileListContainer"></div>

    <div class="fab-container">
        <div class="fab" id="btnPrev" title="前のカードへ">▲</div>
        <div class="fab skip-btn" id="btnSkipMode3Quick" title="タイトルのみ読み上げ">▶▶▶</div>
        <div class="fab skip-btn" id="btnSkip" title="スキップモード切替">
            <span id="skipModeLabel">▶▶</span>
            <div class="skip-hover-group" id="skipHoverGroup"></div>
        </div>
        <div class="fab skip-btn temp" id="btnSkipMode1Quick" title="主なポイントを読み上げ（一時的に切替）">▶</div>
        <div class="fab" id="btnNext" title="次のカードへ">▼</div>
        <div class="fab primary" id="btnPlayPause">▶️</div>
        <div class="fab more" id="btnMore" title="速度・ファイルジャンプ">•••
            <div class="more-hover-group" id="moreHoverGroup">
                <div class="fab speed" id="btnSpeed">1.5x
                    <div class="speed-hover-group" id="speedHoverGroup"></div>
                </div>
                <div class="fab" id="btnFilePrev" title="ファイル先頭/前ファイルへ">⏫</div>
                <div class="fab" id="btnFileNext" title="次のファイルへ">⏬</div>
            </div>
        </div>
    </div>

    <script>
        const ALL_DATA = {{JSON_DATA_PLACEHOLDER}};
        const DASHBOARD_DATA = {{DASHBOARD_DATA_PLACEHOLDER}};



        let state = {
            filter: 'ALL', sort: 'date_desc', showOnlySelected: false, showOnlyUnread: true, useHighQualityVoice: true, checkedFiles: {}, readHistory: {}, manualCheckedFiles: {}, dashTimeFilterHours: null
        };
        
        let filteredData = [];
        let flatQueue = []; 
        
        let currentFlatIndex = -1;
        let currentPart = ''; 
        let isPlaying = false;
        let currentUttr = null;
        let isChimePlaying = false;
        let playTimer = null;
        let pendingAutoUncheckFiles = {};
        let lastHighlightedFilename = null;
        let suppressNextHighlightScroll = false;
        let skipMode = 0; // 0: 標準(▶▶), 1: 主なポイント本文・一時(▶), 2: 主なポイント本文・固定(▶固定), 3: タイトルのみ(▶▶▶), 4: 結論読み上げ(▶緑)
        // 手動でモードを選んだ場合、同一ファイルを聴いている間 or 再生停止までapplyAutoSkipModeによる上書きを防ぐ（mode1・mode2はこのsticky機構の対象外。mode2は既存の永続固定動作、mode1は下記の専用ワンショット機構を使う）
        let skipModeManualOverride = false;
        let skipModeOverrideFilename = null;
        // mode1（ワンショット）専用: 切替直前のskipModeを退避し、1カード読了後にそのモードへ復帰する
        let skipModeBeforeOneShot = null;
        // [20260804] mode1はFABに専用クイックボタン(btnSkipMode1Quick)を新設したため、
        // このホバー一覧からは外した（クイックボタンから直接changeSkipMode(1)を呼ぶ）。
        // [20260808] mode3（タイトルのみ）も使用頻度が高いため、同様に専用クイック
        // ボタン(btnSkipMode3Quick)を新設し、この一覧から外した。
        const skipModeOptions = [
            { mode: 0, label: '▶▶', className: '' },
            { mode: 2, label: '▶', className: 'fixed-skip' },
            { mode: 4, label: '▶', className: 'conclusion-skip' }
        ];

        let isAutoMoving = false;
        let autoMoveInterval = null;
        
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
        const defaultSpeedRate = isIOS ? 1.5 : 2.0;
        let currentSpeedRate = defaultSpeedRate; 
        const speedOptions = [1.0, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 3.0, 3.1, 3.2, 3.3, 3.4, 3.5];
        // iPhone用速度候補: X1.0, X1.2, X1.5, X1.8
        const iosHoverSpeeds = [1.0, 1.2, 1.5, 1.8];
        // PC用速度候補: X1.0, X1.5, X2.0, X3.0
        const pcHoverSpeeds = [1.0, 1.5, 2.0, 3.0];
        let availableVoices = [];


        function loadState() {
            try {
                const saved = localStorage.getItem('summaryManagerState');
                if (saved) state = { ...state, ...JSON.parse(saved) };
                
                if (!state.readHistory) state.readHistory = {};
                if (!state.checkedFiles) state.checkedFiles = {};
                if (!state.manualCheckedFiles) state.manualCheckedFiles = {};

                ALL_DATA.forEach(file => {
                    if (state.checkedFiles[file.filename] === undefined) state.checkedFiles[file.filename] = true;
                });
                applyAutoUncheckedFiles();
                saveState();
            } catch (e) {}
        }

        function saveState() { localStorage.setItem('summaryManagerState', JSON.stringify(state)); }

        function isFileAllRead(file) {
            if (!file || !file.items || file.items.length === 0) return false;
            return file.items.every((_, iIdx) => state.readHistory[`${file.filename}_${iIdx}`]);
        }

        function applyAutoUncheckedFiles() {
            ALL_DATA.forEach(file => {
                if (isFileAllRead(file) && !state.manualCheckedFiles[file.filename]) {
                    state.checkedFiles[file.filename] = false;
                }
            });
        }

        function queueAutoUncheckFile(file) {
            if (!file || !file.filename) return;
            if (state.manualCheckedFiles && state.manualCheckedFiles[file.filename]) {
                delete pendingAutoUncheckFiles[file.filename];
                return;
            }
            if (state.checkedFiles[file.filename] !== false) {
                pendingAutoUncheckFiles[file.filename] = true;
            }
        }



        function finalizePendingAutoUncheckForFile(filename) {
            if (!filename) return;
            if (!pendingAutoUncheckFiles[filename]) return;
            delete pendingAutoUncheckFiles[filename];

            if (state.manualCheckedFiles && state.manualCheckedFiles[filename]) return;
            if (state.checkedFiles[filename] === false) return;

            let restoreFilename = null;
            let restoreIIdx = null;
            if (currentFlatIndex >= 0 && currentFlatIndex < flatQueue.length) {
                const currentQ = flatQueue[currentFlatIndex];
                if (currentQ) {
                    restoreIIdx = currentQ.iIdx;
                    if (currentQ.filename) {
                        restoreFilename = currentQ.filename;
                    } else if (ALL_DATA[currentQ.fIdx]) {
                        restoreFilename = ALL_DATA[currentQ.fIdx].filename;
                    }
                }
            }

            const restoreCurrentIndexAfterQueueChange = () => {
                if (restoreFilename !== null && restoreIIdx !== null) {
                    const restoredIndex = flatQueue.findIndex(q => {
                        const qFilename = q.filename || (ALL_DATA[q.fIdx] ? ALL_DATA[q.fIdx].filename : null);
                        return qFilename === restoreFilename && q.iIdx === restoreIIdx;
                    });
                    if (restoredIndex !== -1) {
                        currentFlatIndex = restoredIndex;
                        return;
                    }
                }

                if (flatQueue.length === 0) {
                    currentFlatIndex = -1;
                } else if (currentFlatIndex >= flatQueue.length) {
                    currentFlatIndex = flatQueue.length - 1;
                } else if (currentFlatIndex < 0) {
                    currentFlatIndex = 0;
                }
            };

            state.checkedFiles[filename] = false;
            const card = document.querySelector(`.file-card[data-filename="${CSS.escape(filename)}"]`);
            if (card) {
                const cb = card.querySelector('.custom-checkbox');
                if (cb) cb.checked = false;
                card.classList.add('disabled');
            }
            saveState();
            buildFlatQueue();
            restoreCurrentIndexAfterQueueChange();

            if (state.showOnlySelected) {
                setTimeout(() => {
                    applyFiltersAndSort();
                    buildFlatQueue();
                    restoreCurrentIndexAfterQueueChange();
                    updateHighlighting();
                }, 150);
            }            
        }

        function finalizePendingAutoUncheckOnFileChange(currentFilename) {
            if (!currentFilename) return;
            if (lastHighlightedFilename && lastHighlightedFilename !== currentFilename) {
                finalizePendingAutoUncheckForFile(lastHighlightedFilename);
            }
            lastHighlightedFilename = currentFilename;
        }
        
        function scrollToCurrentItem(targetEl) {
            // スクロール処理をupdateHighlightingから完全分離
            // MutationObserverによりDOM確定後に確実にスクロールを実行
            if (!targetEl) return;

            if (suppressNextHighlightScroll) {
                suppressNextHighlightScroll = false;
                return;
            }

            function doScroll(el) {
                const offset = getDynamicHeaderOffset();
                const rect = el.getBoundingClientRect();
                const targetY = window.scrollY + rect.top - offset;
                window.scrollTo({ top: targetY, behavior: 'auto' });
            }

            if (targetEl.offsetParent !== null) {
                // 表示済み → 即座にスクロール実行
                doScroll(targetEl);
            } else {
                // 非表示 → MutationObserverでDOM確定を待ってからスクロール
                // file-card の attributes/subtree変化（expanded付与・display変化）を監視
                const parent = targetEl.closest('.file-card') || document.body;
                const observer = new MutationObserver(() => {
                    if (targetEl.offsetParent !== null) {
                        observer.disconnect();
                        clearTimeout(safetyTimer);
                        doScroll(targetEl);
                    }
                });
                observer.observe(parent, { attributes: true, childList: true, subtree: true });
                // 安全装置：3秒後に自動解除（無限監視防止）
                const safetyTimer = setTimeout(() => { observer.disconnect(); }, 3000);
            }
        }

        function scrollToFirstItemInFile(fileIndex) {
            suppressNextHighlightScroll = true;
            setTimeout(() => {
                const firstItem = document.getElementById(`item-${fileIndex}-0`);
                if (firstItem) {
                    const headerOffset = getDynamicHeaderOffset();
                    const rect = firstItem.getBoundingClientRect();
                    const targetY = window.scrollY + rect.top - headerOffset - 6;
                    window.scrollTo({ top: Math.max(0, targetY), behavior: 'auto' });
                }
            }, 80);
        }

        function handleManualFileExpand(fIdx) {
            const card = document.getElementById(`file-card-${fIdx}`);
            if (!card) return;

            const willExpand = !card.classList.contains('expanded');
            toggleExpand(fIdx);

            if (willExpand) {
                scrollToFirstItemInFile(fIdx);
            }
        }

        function init() {
            loadState();
            setupVoices();
            setupUIEventListeners();
            setupDashboardPanel();
            applyFiltersAndSort();
            updateSkipBtnUI();
            // btnSpeedにはspeedHoverGroupが子要素として含まれるため、テキストノードのみ更新
            const _speedBtn = document.getElementById('btnSpeed');
            const _speedTextNodes = Array.from(_speedBtn.childNodes).filter(n => n.nodeType === Node.TEXT_NODE);
            if (_speedTextNodes.length > 0) { _speedTextNodes[0].textContent = currentSpeedRate.toFixed(1) + "x"; }
            else { _speedBtn.insertBefore(document.createTextNode(currentSpeedRate.toFixed(1) + "x"), _speedBtn.firstChild); }
            document.getElementById('sortSelect').value = state.sort;
            if (state.showOnlySelected) document.getElementById('btnToggleSelected').classList.add('on');
            if (state.showOnlyUnread) document.getElementById('btnToggleUnread').classList.add('on'); else document.getElementById('btnToggleUnread').classList.remove('on');
            updateVoiceBtnUI();
            // renderTags/renderFileListによるレイアウト確定後に実測してsticky位置を合わせる
            requestAnimationFrame(updateStickyOffsets);
        }

        function setupVoices() {
            if (window.speechSynthesis) {
                availableVoices = window.speechSynthesis.getVoices();
                window.speechSynthesis.onvoiceschanged = () => { availableVoices = window.speechSynthesis.getVoices(); };
            }
        }

        function applyFiltersAndSort() {
            let res = [...ALL_DATA];
            if (state.filter !== 'ALL') res = res.filter(d => d.category === state.filter);
            if (state.dashTimeFilterHours) {
                const cutoff = (Date.now() / 1000) - state.dashTimeFilterHours * 3600;
                res = res.filter(d => d.mtime >= cutoff);
            }
            if (state.showOnlySelected) res = res.filter(d => state.checkedFiles[d.filename]);
            if (state.showOnlyUnread) {
                res = res.filter(d => {
                    // d.items が空でない、かつ、すべて既読（readHistoryに存在する）場合は false (除外)
                    const isAllRead = d.items.length > 0 && d.items.every((_, iIdx) => state.readHistory[`${d.filename}_${iIdx}`]);
                    return !isAllRead;
                });
            }
            
            res.sort((a, b) => {
                if (state.sort === 'date_desc') return b.mtime - a.mtime;
                if (state.sort === 'date_asc') return a.mtime - b.mtime;
                if (state.sort === 'name_asc') return a.filename.localeCompare(b.filename);
                return 0;
            });
            filteredData = res;
            
            buildFlatQueue();
            renderTags();
            renderFileList();
        }

        function buildFlatQueue() {
            flatQueue = [];
            filteredData.forEach((file, fIdx) => {
                if (!state.checkedFiles[file.filename]) return;
                file.items.forEach((item, iIdx) => {
                    flatQueue.push({ file: file, item: item, fIdx: fIdx, iIdx: iIdx, is_first: (iIdx === 0), filename: file.filename });
                });
            });
        }

        function setupDashboardPanel() {
            [
                { period: 'daily', tileId: 'dashTileDaily', detailId: 'dashDetailDaily', innerId: 'dashDetailDailyInner' },
                { period: 'weekly', tileId: 'dashTileWeekly', detailId: 'dashDetailWeekly', innerId: 'dashDetailWeeklyInner' }
            ].forEach(({ period, tileId, detailId, innerId }) => {
                const data = DASHBOARD_DATA[period];
                const tileEl = document.getElementById(tileId);
                const detailEl = document.getElementById(detailId);
                if (!data) {
                    tileEl.style.display = 'none';
                    detailEl.style.display = 'none';
                    return;
                }
                tileEl.innerHTML = data.tile_html;
                document.getElementById(innerId).innerHTML = data.detail_html;
            });

            if (DASHBOARD_DATA.weekly && DASHBOARD_DATA.weekly.trend) {
                renderTrendChart(DASHBOARD_DATA.weekly.trend);
            }

            document.querySelectorAll('.dash-tile').forEach(btn => {
                btn.addEventListener('click', () => {
                    const detail = document.getElementById(btn.getAttribute('data-target'));
                    const wasOpen = btn.classList.contains('open');
                    document.querySelectorAll('.dash-tile').forEach(t => t.classList.remove('open'));
                    document.querySelectorAll('.dash-detail').forEach(d => d.classList.remove('open'));
                    if (!wasOpen) {
                        btn.classList.add('open');
                        detail.classList.add('open');
                    }
                });
            });

            updateDashJumpButtons();
        }

        // [20260805] 週次推移グラフの実描画。既読/未読はstate.readHistory(ブラウザ側のみ)に
        // しか存在しないため、Pythonが渡すのは各日のitem識別子(filename/iIdx)一覧のみで、
        // ここで実際の既読/未読カウントと積み上げ棒の描画を行う。カードを読むたびに
        // 呼び直せば、次回HTML再生成を待たずにグラフへ反映される。
        function renderTrendChart(trendBuckets) {
            const container = document.getElementById('weeklyTrendBars');
            if (!container || !trendBuckets) return;

            const MAX_BAR_HEIGHT = 52;
            const counted = trendBuckets.map(bucket => {
                let read = 0, unread = 0;
                bucket.items.forEach(({ filename, iIdx }) => {
                    if (state.readHistory[`${filename}_${iIdx}`]) read++; else unread++;
                });
                return { label: bucket.label, read, unread, total: read + unread };
            });
            const maxTotal = Math.max(0, ...counted.map(c => c.total));

            container.innerHTML = counted.map(c => {
                const totalH = maxTotal > 0 ? Math.round(c.total / maxTotal * MAX_BAR_HEIGHT) : 0;
                const readH = c.total > 0 ? Math.round(totalH * (c.read / c.total)) : 0;
                const unreadH = Math.max(0, totalH - readH);
                const soloCls = (readH === 0 || unreadH === 0) ? ' solo' : '';
                const segments =
                    (unreadH > 0 ? `<div class="trend-bar-unread${soloCls}" style="height:${unreadH}px;"></div>` : '') +
                    (readH > 0 ? `<div class="trend-bar-read${soloCls}" style="height:${readH}px;"></div>` : '');
                return (
                    '<div class="trend-bar-col">' +
                    `<span class="trend-bar-n">${c.total}</span>` +
                    `<div class="trend-bar-stack" style="height:${totalH}px;">${segments}</div>` +
                    `<span class="trend-day">${c.label}</span>` +
                    '</div>'
                );
            }).join('');
        }

        // [20260804] ヘッダー/ダッシュボード帯/絞込パネルの実高さは端末・フォント描画で変わるため、
        // sticky位置とスクロール時のオフセットをpx決め打ちにせず、実測してCSS変数へ反映する。
        // 各パネルの開閉やウィンドウリサイズで高さが変わるたびに呼び直す。
        function updateStickyOffsets() {
            const header = document.getElementById('appHeader');
            const dashWrap = document.getElementById('dashTilesWrap');
            const panel = document.getElementById('controlPanel');
            if (!header || !dashWrap || !panel) return;

            const headerH = header.offsetHeight;
            const dashVisible = dashWrap.style.display !== 'none' && !dashWrap.classList.contains('closed');
            const dashH = dashVisible ? dashWrap.offsetHeight : 0;
            const panelVisible = !panel.classList.contains('closed');
            const panelH = panelVisible ? panel.offsetHeight : 0;

            const root = document.documentElement.style;
            root.setProperty('--dash-top', headerH + 'px');
            root.setProperty('--panel-top', (headerH + dashH) + 'px');
            root.setProperty('--scroll-offset', (headerH + dashH + panelH + 10) + 'px');
        }

        let _stickyOffsetResizeTimer = null;
        window.addEventListener('resize', () => {
            clearTimeout(_stickyOffsetResizeTimer);
            _stickyOffsetResizeTimer = setTimeout(updateStickyOffsets, 150);
        });

        function toggleDashTimeFilter(hours) {
            state.dashTimeFilterHours = (state.dashTimeFilterHours === hours) ? null : hours;
            saveState();
            applyFiltersAndSort();
            updateDashJumpButtons();
        }

        function updateDashJumpButtons() {
            document.querySelectorAll('.dd-jump').forEach(btn => {
                const hours = parseInt(btn.getAttribute('data-hours'), 10);
                const active = state.dashTimeFilterHours === hours;
                btn.textContent = active ? '絞り込み解除' : 'この範囲だけ見る';
                btn.classList.toggle('active', active);
            });
        }

        function renderTags() {
            // 'ALL'はフィルタの特別値であり、実際のカテゴリ値としては現れない想定だが、
            // 万が一データ側にcategory:'ALL'が存在してもタグが重複表示されないようにする
            const categories = ['ALL', ...new Set(ALL_DATA.map(d => d.category).filter(c => c && c !== 'ALL'))];
            const container = document.getElementById('filterTags');
            container.innerHTML = '';
            categories.forEach(cat => {
                const div = document.createElement('div');
                div.className = `tag ${state.filter === cat ? 'active' : ''}`;
                div.innerText = cat;
                div.onclick = () => { state.filter = cat; saveState(); applyFiltersAndSort(); };
                container.appendChild(div);
            });
        }

        function renderFileList() {
            const container = document.getElementById('fileListContainer');
            container.innerHTML = '';
            
            filteredData.forEach((file, fIdx) => {
                const isChecked = state.checkedFiles[file.filename];
                const isAllRead = file.items.length > 0 && file.items.every((_, iIdx) => state.readHistory[`${file.filename}_${iIdx}`]);
                const card = document.createElement('div');
                card.className = `file-card ${isChecked ? '' : 'disabled'} ${isAllRead ? 'all-read' : ''}`;
                card.id = `file-card-${fIdx}`;
                
                let html = `
                    <div class="card-header-row">
                        <div class="checkbox-container">
                            <input type="checkbox" class="custom-checkbox" data-filename="${file.filename}" ${isChecked ? 'checked' : ''}>
                        </div>
                        <div class="file-info" onclick="handleManualFileExpand(${fIdx})">
                            <div class="file-title">${file.filename}</div>
                            <div class="file-meta">
                                <span>📅 ${file.mtime_str}</span>
                                <span>🏷️ ${file.items.length}件</span>
                            </div>
                        </div>
                    </div>
                    <div class="preview-area" id="preview-${fIdx}">
                `;
                
                file.items.forEach((item, iIdx) => {
                    const historyKey = `${file.filename}_${iIdx}`;
                    const isRead = state.readHistory[historyKey] ? 'read-done' : '';
                    const itemClass = item.is_error ? `summary-item error ${isRead}` : `summary-item ${isRead}`;
                    const itemId = `item-${fIdx}-${iIdx}`;
                    html += `<div class="${itemClass}" id="${itemId}">`;
                    
                    let titleHtml = item.url ? `<a href="${item.url}" target="_blank" style="color: inherit; text-decoration: none;">${iIdx+1}. ${item.title}</a>` : `${iIdx+1}. ${item.title}`;
                    
                    if(item.is_error) {
                        html += `<div>🚨 ${iIdx+1}. ${item.title} (要約失敗)</div>`;
                    } else {
                        if(item.type === 'youtube' && item.thumbnail) {
                            html += `<div style="display:flex; gap:10px; margin-bottom:10px;">
                                        <img src="${item.thumbnail}" style="width:120px; height:auto; border-radius:5px; object-fit:cover; aspect-ratio:16/9;">
                                        <div>
                                            <div style="font-weight:bold; font-size:1.05em; margin-bottom:4px;">${titleHtml}</div>
                                            <div style="font-size:0.8em; color:#718096;">
                                                ${item.duration ? `<span style="font-size:1.0em; letter-spacing:1px;">${buildDurationIndicator(item.duration)}</span> <span style="font-weight:600; color:#2b6cb0; margin-right:8px;">${item.duration}</span>` : ''}${item.is_favorite ? `<span style="color:#d4a017; font-size:1.0em; margin-right:4px;">★</span>` : ''}📺 ${item.channel} ${item.subscriber ? `<span style="background-color: #e2e8f0; color: #4a5568; padding: 2px 6px; border-radius: 4px; margin-left: 6px; font-weight: 600; font-size: 0.9em;">👥 ${item.subscriber}</span>` : ''}
                                            </div>
                                        </div>
                                     </div>`;
                        } else {
                            html += `<div style="font-weight:bold; font-size:1.05em; margin-bottom:8px;">${titleHtml}</div>`;
                            if(item.type === 'rss') {
                                html += `<div style="margin-bottom:8px;">
                                            ${item.char_count ? `<span style="font-size:1.0em; letter-spacing:1px;">${buildCharCountIndicator(item.char_count)}</span> <span style="font-weight:600; color:#2b6cb0; margin-right:8px;">${parseInt(item.char_count.replace(/,/g,'').replace(/字/g,''),10)}</span>` : ''}
                                            <span class="info-badge">🏢 ${item.source}</span>
                                            ${item.category === 'Followed Note' ? `<span class="info-badge" style="background:#d4a017; color:#fff; font-weight:500;">📁 ${item.category}</span>` : `<span class="info-badge">📁 ${item.category}</span>`}
                                            <span class="info-badge">👤 ${item.author}</span>
                                            <span class="info-badge">❤️ ${item.likes}</span>
                                         </div>`;
                            }
                        }
                        
                        if(item.keywords && item.keywords.length > 0) {
                            html += `<div style="margin-bottom:8px;">` + item.keywords.map(k => `<span class="info-badge">${k}</span>`).join('') + `</div>`;
                        }
               
                        const _isHighlight = (item.category === 'Followed Note') || (item.is_favorite === true);
                        const _borderColor = _isHighlight ? '#d4a017' : '#3182ce';
                        const _bgColor = _isHighlight ? '#fef9c3' : '#f8fafc';
                        html += `<div style="background:${_bgColor}; padding:8px; border-left:4px solid ${_borderColor}; margin-bottom:8px; font-size:0.9em;"><strong>要旨:</strong> ${item.summary}</div>`;
                        const _ptHtml = buildPointTitlesList(item.points);
                        html += `<div id="point-titles-${fIdx}-${iIdx}" style="${_ptHtml ? `background:${_bgColor}; padding:8px; border-left:4px solid ${_borderColor}; margin-bottom:8px; font-size:0.9em;` : 'display:none;'}">${_ptHtml}</div>`;
                        const _olHtml = buildOutlineList(item.outline);
                        html += `<div id="outline-titles-${fIdx}-${iIdx}" style="${_olHtml ? `background:${_bgColor}; padding:8px; border-left:4px solid ${_borderColor}; margin-bottom:8px; font-size:0.9em;` : 'display:none;'}">${_olHtml}</div>`;
              
                        if(item.type === 'rss') {
                            if(!item.conclusion) {
                                html += `<button class="detail-btn-consolidated" id="detail-btn-${fIdx}-${iIdx}" data-url="${item.url.replace(/"/g, '&quot;')}" onclick="fetchDetailConsolidated(${fIdx}, ${iIdx})">&#128269; 主なポイントを生成</button>`;
                                html += `<div id="conclusion-area-${fIdx}-${iIdx}" style="display:none;"></div>`;
                                html += `<div id="points-area-${fIdx}-${iIdx}" style="display:none;"></div>`;
                            } else {
                                html += `<div id="conclusion-area-${fIdx}-${iIdx}" class="conclusion-text-unified" style="display:none;">${item.conclusion}</div>`;
                                if(item.points) {
                                    html += `<button class="points-accordion-btn" id="points-acc-btn-${fIdx}-${iIdx}" onclick="togglePointsAccordion(${fIdx}, ${iIdx})">▶ 主なポイントを表示</button>`;
                                    html += `<div class="points-wrapper section-content" id="points-wrapper-${fIdx}-${iIdx}" style="display:none; padding:10px; background:#f7fafc; border-radius:5px; font-size:0.85em;">${item.points}</div>`;
                                }
                            }
                        } else {
                            html += `<div id="conclusion-area-${fIdx}-${iIdx}" class="conclusion-text-unified" style="display:none;">${item.conclusion}</div>`;
                            if(item.points) {
                                html += `<button class="points-accordion-btn" id="points-acc-btn-${fIdx}-${iIdx}" onclick="togglePointsAccordion(${fIdx}, ${iIdx})">▶ 主なポイントを表示</button>`;
                                html += `<div class="points-wrapper section-content" id="points-wrapper-${fIdx}-${iIdx}" style="display:none; padding:10px; background:#f7fafc; border-radius:5px; font-size:0.85em;">${item.points}</div>`;
                            }
                        }
                    }
                    html += `</div>`;
                });
                
                html += `</div>`;
                card.innerHTML = html;
                container.appendChild(card);
            });

            document.querySelectorAll('.custom-checkbox').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const fname = e.target.getAttribute('data-filename');
                    state.checkedFiles[fname] = e.target.checked;
                    if (e.target.checked) {
                        const fileObj = ALL_DATA.find(f => f.filename === fname);
                        if (fileObj && isFileAllRead(fileObj)) {
                            state.manualCheckedFiles[fname] = true;
                        }
                    } else {
                        delete state.manualCheckedFiles[fname];
                    }
                    saveState();
                    if(state.showOnlySelected) applyFiltersAndSort();
                    else {
                        const card = e.target.closest('.file-card');
                        e.target.checked ? card.classList.remove('disabled') : card.classList.add('disabled');
                        buildFlatQueue();
                    }
                });
            });
        }

        function toggleExpand(fIdx) {
            const card = document.getElementById(`file-card-${fIdx}`);
            if (card) {
                card.classList.toggle('expanded');
                if (card.classList.contains('expanded')) {
                    setTimeout(() => card.scrollIntoView({ behavior: 'auto', block: 'start' }), 100);
                }
            }
        }
        
        function togglePointWrapper(fIdx, iIdx) {
            const w = document.getElementById(`points-wrapper-${fIdx}-${iIdx}`);
            const b = w.previousElementSibling;
            if(w.style.display === 'none') {
                w.style.display = 'block'; w.classList.add('open'); b.innerText = '主なポイントを隠す';
            } else {
                w.style.display = 'none'; w.classList.remove('open'); b.innerText = '主なポイントを表示';
            }
        }
        
        
        function openPointsAccordion(fIdx, iIdx) {
            // skipMode 1/2のpoints読み上げ前にポイントを強制展開する内部ヘルパー
            const w = document.getElementById(`points-wrapper-${fIdx}-${iIdx}`);
            const b = document.getElementById(`points-acc-btn-${fIdx}-${iIdx}`);
            if (!w) return;
            if (!w.classList.contains('open')) {
                w.style.display = 'block';
                w.classList.add('open');
                if (b) b.innerText = '▼ 主なポイントを隠す';
            }
        }


        function playChime(callback) {
            isChimePlaying = true;
            const safetyTimer = setTimeout(() => {
                isChimePlaying = false;
                if (callback) callback();
            }, 700);
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                ctx.resume().then(() => {
                    const t = ctx.currentTime;
                    const osc1 = ctx.createOscillator();
                    const gain1 = ctx.createGain();
                    osc1.connect(gain1);
                    gain1.connect(ctx.destination);
                    osc1.type = 'sine';
                    osc1.frequency.setValueAtTime(660, t);
                    gain1.gain.setValueAtTime(0.3, t);
                    gain1.gain.exponentialRampToValueAtTime(0.001, t + 0.25);
                    osc1.start(t);
                    osc1.stop(t + 0.25);
                    const osc2 = ctx.createOscillator();
                    const gain2 = ctx.createGain();
                    osc2.connect(gain2);
                    gain2.connect(ctx.destination);
                    osc2.type = 'sine';
                    osc2.frequency.setValueAtTime(880, t + 0.28);
                    gain2.gain.setValueAtTime(0, t);
                    gain2.gain.setValueAtTime(0.3, t + 0.28);
                    gain2.gain.exponentialRampToValueAtTime(0.001, t + 0.55);
                    osc2.start(t);
                    osc2.stop(t + 0.6);
                    osc2.onended = () => {
                        clearTimeout(safetyTimer);
                        ctx.close();
                        isChimePlaying = false;
                        if (callback) callback();
                    };
                }).catch(e => {
                    clearTimeout(safetyTimer);
                    isChimePlaying = false;
                    if (callback) callback();
                });
            } catch(e) {
                clearTimeout(safetyTimer);
                isChimePlaying = false;
                if (callback) callback();
            }
        }


        
        function buildDurationIndicator(duration) {
            // 動画時間文字列（例: "27:35", "1:02:45"）を
            // 5段階絵文字インジケーターに変換する
            if (!duration) return '';
            const parts = duration.trim().split(':').map(Number);
            if (parts.some(isNaN)) return '';
            let totalSeconds = 0;
            if (parts.length === 3) {
                totalSeconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
            } else if (parts.length === 2) {
                totalSeconds = parts[0] * 60 + parts[1];
            } else {
                return '';
            }
            const minutes = totalSeconds / 60;
            if (minutes <= 3)  return '⬜⬜⬜⬜⬜';
            if (minutes <= 15) return '🟩⬜⬜⬜⬜';
            if (minutes <= 30) return '🟩🟩⬜⬜⬜';
            if (minutes <= 45) return '🟩🟩🟩⬜⬜';
            if (minutes <= 60) return '🟩🟩🟩🟩⬜';
            return '🟩🟩🟩🟩🟩';
        }
        
        function buildCharCountIndicator(charCount) {
            // 文字数文字列（例: "2,746字"）を
            // 6段階絵文字インジケーターに変換する
            if (!charCount) return '';
            const num = parseInt(charCount.replace(/,/g, '').replace(/字/g, '').trim(), 10);
            if (isNaN(num)) return '';
            if (num <= 1000)  return '⬜⬜⬜⬜⬜';
            if (num <= 3000)  return '🟩⬜⬜⬜⬜';
            if (num <= 6000)  return '🟩🟩⬜⬜⬜';
            if (num <= 9000)  return '🟩🟩🟩⬜⬜';
            if (num <= 12000) return '🟩🟩🟩🟩⬜';
            return '🟩🟩🟩🟩🟩';
        }
        
        function buildOutlineList(outline) {
            // RSSカードの「概要」箇条書き配列を
            // <ul class="point-titles-list"> 形式のHTML文字列に変換する
            if (!outline || outline.length === 0) return '';
            return '<ul class="point-titles-list">'
                + outline.map(item => `<li>${item}</li>`).join('')
                + '</ul>';
        }
        
        
        function buildPointTitlesList(pointsHtml) {
            // item.pointsのHTML文字列からfw-bold見出しテキストのみを抽出して
            // <ul class="point-titles-list">形式のHTML文字列を返す
            if (!pointsHtml) return '';
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = pointsHtml;
            const headings = Array.from(tempDiv.querySelectorAll('p.fw-bold'))
                .map(p => p.textContent.trim())
                .filter(t => t.length > 0);
            if (headings.length === 0) return '';
            return '<ul class="point-titles-list">'
                + headings.map(h => `<li>${h}</li>`).join('')
                + '</ul>';
        }

        // RSSアコーディオン式ポイント開閉
        function togglePointsAccordion(fIdx, iIdx) {
            const w = document.getElementById(`points-wrapper-${fIdx}-${iIdx}`);
            const b = document.getElementById(`points-acc-btn-${fIdx}-${iIdx}`);
            if (!w || !b) return;
            if (w.style.display === 'none') {
                w.style.display = 'block'; w.classList.add('open');
                b.textContent = '▼ 主なポイントを隠す';
            } else {
                w.style.display = 'none'; w.classList.remove('open');
                b.textContent = '▶ 主なポイントを表示';
            }
        }

        // __INJECT_NEW_FUNCTIONS__
        function setupUIEventListeners() {
            document.getElementById('sortSelect').addEventListener('change', (e) => {
                state.sort = e.target.value; saveState(); applyFiltersAndSort();
            });
            document.getElementById('btnSelectAll').addEventListener('click', () => {
                filteredData.forEach(f => state.checkedFiles[f.filename] = true);
                saveState(); applyFiltersAndSort();
            });
            document.getElementById('bDeselectAll').addEventListener('click', () => {
                filteredData.forEach(f => state.checkedFiles[f.filename] = false);
                saveState(); applyFiltersAndSort();
            });
            document.getElementById('btnToggleSelected').addEventListener('click', (e) => {
                state.showOnlySelected = !state.showOnlySelected;
                e.target.classList.toggle('on', state.showOnlySelected);
                saveState(); applyFiltersAndSort();
            });
            document.getElementById('btnToggleUnread').addEventListener('click', (e) => {
                state.showOnlyUnread = !state.showOnlyUnread;
                e.target.classList.toggle('on', state.showOnlyUnread);
                saveState(); applyFiltersAndSort();
            });
            
            document.getElementById('btnToggleAllCards').addEventListener('click', (e) => {
                const cards = document.querySelectorAll('.file-card:not(.disabled)');
                const isAllOpen = Array.from(cards).every(c => c.classList.contains('expanded'));
                cards.forEach(c => { if(isAllOpen) c.classList.remove('expanded'); else c.classList.add('expanded'); });
                e.target.innerText = isAllOpen ? '📂 全カード開く' : '📂 全カード閉じる';
            });

            document.getElementById('btnToggleAllPoints').addEventListener('click', (e) => {
                const wrappers = document.querySelectorAll('.points-wrapper');
                const btns = document.querySelectorAll('.points-accordion-btn');
                const isAllOpen = Array.from(wrappers).every(w => w.classList.contains('open'));
                wrappers.forEach(w => {
                    if(isAllOpen) { w.style.display = 'none'; w.classList.remove('open'); } 
                    else { w.style.display = 'block'; w.classList.add('open'); }
                });
                btns.forEach(b => b.textContent = isAllOpen ? '▶ 主なポイントを表示' : '▼ 主なポイントを隠す');
                e.target.innerText = isAllOpen ? '📝 全ポイント開く' : '📝 全ポイント閉じる';
            });
            
            let isPanelOpen = true;
            document.getElementById('btnTogglePanel').addEventListener('click', () => {
                isPanelOpen = !isPanelOpen;
                const panel = document.getElementById('controlPanel');
                const toggleBtn = document.getElementById('btnTogglePanel');
                const dashWrap = document.getElementById('dashTilesWrap');
                panel.classList.toggle('closed', !isPanelOpen);
                toggleBtn.classList.toggle('closed', !isPanelOpen);
                // [20260804] ダッシュボード帯も絞込パネルと同じアコーディオンボタンで開閉する
                dashWrap.classList.toggle('closed', !isPanelOpen);
                // 開閉に応じて各パネルの実高さが変わるため、スティッキー位置を再計測する。
                // .control-panel/.dash-tiles-wrapのmax-heightトランジションは0.3sかかるため、
                // requestAnimationFrame(=次の描画直前、トランジション開始直後)で測ると
                // 変化前とほぼ同じ高さを拾ってしまい、開閉後の位置がズレたまま固定される
                // バグの原因になっていた。トランジション完了を待ってから再計測する。
                setTimeout(updateStickyOffsets, 320);
            });
            
            document.getElementById('btnToggleVoice').addEventListener('click', (e) => {
                state.useHighQualityVoice = !state.useHighQualityVoice;
                saveState();
                updateVoiceBtnUI();
                if (isPlaying && currentUttr) {
                    currentUttr.onend = null; currentUttr.onerror = null;
                    window.speechSynthesis.cancel();
                    if(playTimer) clearTimeout(playTimer);
                    playTimer = setTimeout(() => { playCurrentPart(); }, 300);
                }
            });

            document.getElementById('btnPlayPause').addEventListener('click', () => {
                if (isPlaying) stopAllSpeech(); else startPlayback();
            });
            
            document.getElementById('btnFileNext').addEventListener('click', jumpToNextFile);
            document.getElementById('btnFilePrev').addEventListener('click', jumpToPrevFile);

            // [20260804] Mode1（主なポイント本文・一時）専用のクイックボタン。
            // ホバー一覧を開かずワンタップで切り替えられるようにした。
            // RSSカードで主なポイント未生成の場合は、ここで生成をバックグラウンド起動しておく
            // （handlePartEndで実際に読み上げる段になってから待つより早く揃う）。
            document.getElementById('btnSkipMode1Quick').addEventListener('click', () => {
                if (currentFlatIndex !== -1) {
                    const qData = flatQueue[currentFlatIndex];
                    if (qData) triggerRssPointsGenerationIfNeeded(qData.fIdx, qData.iIdx);
                }
                changeSkipMode(1);
            });

            // [20260808] Mode3（タイトルのみ）専用のクイックボタン。
            // 使用頻度が高いのに、従来はホバー一覧を開いてから選ぶ2アクションが
            // 必要だったため、ワンクリックで切り替えられるようにした。
            // 読み上げロジックは既存のmode3をそのまま使い、新規実装はしていない。
            document.getElementById('btnSkipMode3Quick').addEventListener('click', () => {
                changeSkipMode(3);
            });


            setupSkipBtn();
            setupSkipHoverBtns();
            setupSpeedBtn();
            setupSpeedHoverBtns();
            setupMoveBtns();
            setupMoreHoverBtn();

            // キーボードショートカット
            // 下キー・スペース → 次のカードへ（▼と同じ）
            // 上キー → 前のカードへ（▲と同じ）
            document.addEventListener('keydown', (e) => {
                // input・textareaにフォーカスがある場合は無効化
                const tag = document.activeElement.tagName.toLowerCase();
                if (tag === 'input' || tag === 'textarea') return;

                if (e.key === 'ArrowDown' || e.key === ' ') {
                    e.preventDefault();
                    skipToNextItem();
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    skipToPrevItem();
                }
            });
        }


            
        function updateVoiceBtnUI() {
            const btn = document.getElementById('btnToggleVoice');
            btn.classList.toggle('on', state.useHighQualityVoice);
            btn.innerText = state.useHighQualityVoice ? '🎙️ 高音質' : '🤖 標準';
        }


        // [20260804] 「•••」ボタン: 速度設定・ファイルジャンプの展開/収納のみを行う単純なトグル。
        // 内部のbtnSpeedは自身のspeed-hover-group用クリックハンドラを別途持つため、
        // ここではその伝播を止めて「•••」自体が閉じないようにするだけでよい。
        function setupMoreHoverBtn() {
            const btnMore = document.getElementById('btnMore');
            const group = document.getElementById('moreHoverGroup');
            if (!btnMore || !group) return;

            btnMore.addEventListener('click', (e) => {
                e.stopPropagation();
                if (group.contains(e.target)) return;
                const willOpen = !group.classList.contains('visible');
                group.classList.toggle('visible', willOpen);
                btnMore.classList.toggle('open', willOpen);
            });

            group.addEventListener('click', (e) => { e.stopPropagation(); });

            document.addEventListener('click', (e) => {
                if (!btnMore.contains(e.target)) {
                    group.classList.remove('visible');
                    btnMore.classList.remove('open');
                }
            });
        }

        function setupSkipBtn() {
            const btnSkip = document.getElementById('btnSkip');
            const group = document.getElementById('skipHoverGroup');
            if (!btnSkip || !group) return;

            let skipBtnTimer = null;
            let skipBtnPressed = false;
            let isResetDone = false;
            let suppressNextClick = false;

            btnSkip.oncontextmenu = function(e) { e.preventDefault(); return false; };

            btnSkip.addEventListener('pointerdown', (e) => {
                if (e.button !== 0 && e.pointerType === 'mouse') return;
                if (group.contains(e.target)) return;
                if (btnSkip.setPointerCapture) btnSkip.setPointerCapture(e.pointerId);
                skipBtnPressed = true;
                isResetDone = false;
                suppressNextClick = false;

                skipBtnTimer = setTimeout(() => {
                    if (skipBtnPressed) {
                        isResetDone = true;
                        suppressNextClick = true;
                        changeSkipMode(0);
                        closeSkipHoverGroup();
                    }
                }, 500);
            });

            btnSkip.addEventListener('pointerup', (e) => {
                if (btnSkip.releasePointerCapture) btnSkip.releasePointerCapture(e.pointerId);
                if (!skipBtnPressed) return;
                skipBtnPressed = false;
                if (skipBtnTimer) clearTimeout(skipBtnTimer);
            });

            btnSkip.addEventListener('pointercancel', (e) => {
                if (btnSkip.releasePointerCapture) btnSkip.releasePointerCapture(e.pointerId);
                skipBtnPressed = false;
                if (skipBtnTimer) clearTimeout(skipBtnTimer);
            });

            btnSkip.addEventListener('click', (e) => {
                e.stopPropagation();
                if (group.contains(e.target)) return;
                if (suppressNextClick || isResetDone) {
                    suppressNextClick = false;
                    isResetDone = false;
                    return;
                }
                toggleSkipHoverGroup();
            });

            group.addEventListener('click', (e) => {
                e.stopPropagation();
            });

            document.addEventListener('click', (e) => {
                if (!btnSkip.contains(e.target)) {
                    closeSkipHoverGroup();
                }
            });
        }




        function changeSkipMode(newMode) {
            // mode1（ワンショット）への切替: 直前のモードを退避し、1カード読了後にそこへ戻す
            if (newMode === 1) {
                if (skipMode !== 1) skipModeBeforeOneShot = skipMode;
            } else {
                // mode1以外へ手動変更した場合は、ワンショット待ちを破棄する
                skipModeBeforeOneShot = null;
            }

            skipMode = newMode;
            updateSkipBtnUI();
            updateSkipHoverBtnHighlight();

            // mode1(ワンショット)・mode2(▶固定)は対象外。
            // それ以外を手動選択した場合は、同一ファイルを聴いている間 or 停止するまで保持する
            if (newMode !== 2 && newMode !== 1) {
                skipModeManualOverride = true;
                const qData = flatQueue[currentFlatIndex];
                skipModeOverrideFilename = qData ? qData.filename : null;
            }

            stopAutoMove(); // 追加: モード切替時に自動スクロールを強制停止

            // [20260808] 読み上げ中のモード変更で、読み上げを中断してタイトルから
            // やり直す処理を廃止した。
            // 従来は speechSynthesis.cancel() のうえ currentPart を title(または
            // file_intro)へ戻していたため、タイトル読み上げ中に押すとタイトルが
            // 読み直され、要旨の途中で押しても頭まで巻き戻っていた。
            // handlePartEnd() は区切りごとに skipMode を都度参照しているので、
            // ここで何もしなければ、今読んでいる部分はそのまま最後まで読まれ、
            // 次の区切りから新しいモードが自然に適用される。
        }


        function updateSkipBtnUI() {
            const btn = document.getElementById('btnSkip');
            const label = document.getElementById('skipModeLabel');
            if (!btn || !label) return;
            btn.classList.remove('temp', 'fixed', 'conclusion');
            if (skipMode === 0) {
                label.textContent = "▶▶";
            } else if (skipMode === 1) {
                label.textContent = "▶";
                btn.classList.add('temp');
            } else if (skipMode === 2) {
                label.textContent = "▶";
                btn.classList.add('fixed');
            } else if (skipMode === 3) {
                label.textContent = "▶▶▶";
                btn.classList.add('fixed');
            } else if (skipMode === 4) {
                label.textContent = "▶";
                btn.classList.add('conclusion');
            }

            // [20260805] mode1クイックボタン(▶)の非アクティブ/アクティブ配色切替
            const quickBtn = document.getElementById('btnSkipMode1Quick');
            if (quickBtn) quickBtn.classList.toggle('active-mode1', skipMode === 1);

            // [20260808] mode3クイックボタン(▶▶▶)も同様に切り替える
            const quickBtn3 = document.getElementById('btnSkipMode3Quick');
            if (quickBtn3) quickBtn3.classList.toggle('active-mode3', skipMode === 3);
        }
    
        function applyAutoSkipMode() {
            // カード確定時にカード種別へ応じてskipModeを自動設定する
            // skipMode===2（▶固定）は手動選択の持続を優先し、自動判定を行わない
            if (skipMode === 2) return;
            // skipMode===1（ワンショット）は退避済みのモードへ復帰するまで自動上書きしない
            // （これが無いと、一時停止→再生再開時にstartPlayback/resumePlaybackが
            //   ここを呼び出し、ワンショットが読まれる前に上書きされてしまう）
            if (skipMode === 1) return;
            const qData = flatQueue[currentFlatIndex];
            if (!qData) return;
            const filename = qData.filename || '';
            // mode0/1/3を手動選択した場合、同一ファイルを聴いている間は自動判定で上書きしない
            // ファイルが切り替わったら手動固定を解除し、通常の自動判定へ戻す
            if (skipModeManualOverride) {
                if (filename === skipModeOverrideFilename) return;
                skipModeManualOverride = false;
            }
            const isFavorite = qData.item && qData.item.is_favorite === true;
            let newMode;
            // サマリーファイルをずっとmode4やmode1に固定する必要がなくなったため、V/BBTとお気に入りは
            // どちらもmode0（標準）とする。Short/Nのみ引き続きmode3（タイトルのみ）
            if (/^summary_(V|BBT)_/.test(filename)) {
                newMode = 0;
            } else if (isFavorite) {
                newMode = 0;
            } else if (/^summary_(Short|N)_/.test(filename)) {
                newMode = 3;
            } else {
                newMode = 0;
            }
            skipMode = newMode;
            updateSkipBtnUI();
        }
    

        function setupSkipHoverBtns() {
            const group = document.getElementById('skipHoverGroup');
            if (!group) return;

            group.innerHTML = '';
            skipModeOptions.forEach(opt => {
                const btn = document.createElement('div');
                btn.className = 'skip-hover-btn';
                if (opt.className) btn.classList.add(opt.className);
                btn.dataset.mode = String(opt.mode);
                btn.textContent = opt.label;
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    changeSkipMode(opt.mode);
                    closeSkipHoverGroup();
                });
                group.appendChild(btn);
            });

            updateSkipHoverBtnHighlight();
        }

        function toggleSkipHoverGroup() {
            const group = document.getElementById('skipHoverGroup');
            if (!group) return;
            updateSkipHoverBtnHighlight();
            group.classList.toggle('visible');
        }

        function closeSkipHoverGroup() {
            const group = document.getElementById('skipHoverGroup');
            if (!group) return;
            group.classList.remove('visible');
        }

        function updateSkipHoverBtnHighlight() {
            document.querySelectorAll('.skip-hover-btn').forEach(btn => {
                const mode = parseInt(btn.dataset.mode, 10);
                btn.classList.toggle('active-skip', mode === skipMode);
            });
        }


        function setupSpeedBtn() {
            const btnSpeed = document.getElementById('btnSpeed');
            let speedBtnTimer = null;
            let speedBtnPressed = false;
            let isResetDone = false;
            let suppressNextClick = false;

            btnSpeed.oncontextmenu = function(e) { e.preventDefault(); return false; };

            btnSpeed.addEventListener('pointerdown', (e) => {
                if (e.button !== 0 && e.pointerType === 'mouse') return;
                speedBtnPressed = true;
                isResetDone = false;
                suppressNextClick = false;
                
                speedBtnTimer = setTimeout(() => {
                    if (speedBtnPressed) {
                        isResetDone = true;
                        suppressNextClick = true;
                        resetSpeed();
                        closeSpeedHoverGroup();
                        btnSpeed.classList.add('reset-flash');
                        setTimeout(() => btnSpeed.classList.remove('reset-flash'), 200);
                    }
                }, 500);
            });

            btnSpeed.addEventListener('pointerup', (e) => {
                if (!speedBtnPressed) return;
                speedBtnPressed = false;
                if (speedBtnTimer) clearTimeout(speedBtnTimer);
            });

            btnSpeed.addEventListener('pointerleave', () => { 
                speedBtnPressed = false; 
                if (speedBtnTimer) clearTimeout(speedBtnTimer); 
            });

            btnSpeed.addEventListener('pointercancel', () => { 
                speedBtnPressed = false; 
                if (speedBtnTimer) clearTimeout(speedBtnTimer); 
            });

            btnSpeed.addEventListener('click', (e) => {
                e.stopPropagation();
                if (suppressNextClick || isResetDone) {
                    suppressNextClick = false;
                    isResetDone = false;
                    return;
                }
                toggleSpeedHoverGroup();
            });
        }

        function incrementSpeed() {
            let idx = speedOptions.indexOf(currentSpeedRate);
            if (idx === -1) idx = speedOptions.indexOf(defaultSpeedRate);
            idx = (idx + 1) % speedOptions.length;
            currentSpeedRate = speedOptions[idx];
            applySpeedChange();
        }

        function resetSpeed() {
            currentSpeedRate = defaultSpeedRate;
            applySpeedChange();
        }

        function applySpeedChange() {
            const btnSpeed = document.getElementById('btnSpeed');
            // innerTextを使うとspeedHoverGroupのテキストも含まれてしまうため、
            // テキストノードのみを更新する
            const textNodes = Array.from(btnSpeed.childNodes).filter(n => n.nodeType === Node.TEXT_NODE);
            if (textNodes.length > 0) {
                textNodes[0].textContent = currentSpeedRate.toFixed(1) + "x";
            } else {
                btnSpeed.insertBefore(document.createTextNode(currentSpeedRate.toFixed(1) + "x"), btnSpeed.firstChild);
            }
            updateSpeedHoverBtnHighlight();
            if (isPlaying && currentUttr) {
                currentUttr.onend = null;
                currentUttr.onerror = null;
                window.speechSynthesis.cancel();
                if(playTimer) clearTimeout(playTimer);
                playTimer = setTimeout(() => { playCurrentPart(); }, 300);
            }
        }

        function setupSpeedHoverBtns() {
            const hoverSpeeds = isIOS ? iosHoverSpeeds : pcHoverSpeeds;
            const group = document.getElementById('speedHoverGroup');
            const btnSpeed = document.getElementById('btnSpeed');
            if (!group || !btnSpeed) return;

            // ホバーボタンを生成
            group.innerHTML = '';
            hoverSpeeds.forEach(spd => {
                const btn = document.createElement('div');
                btn.className = 'speed-hover-btn';
                btn.dataset.speed = spd;
                btn.textContent = spd.toFixed(1) + 'x';
                btn.addEventListener('pointerdown', (e) => {
                    e.stopPropagation();
                });
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    currentSpeedRate = spd;
                    applySpeedChange();
                    closeSpeedHoverGroup();
                });
                group.appendChild(btn);
            });

            group.addEventListener('click', (e) => {
                e.stopPropagation();
            });

            document.addEventListener('click', (e) => {
                if (!btnSpeed.contains(e.target)) {
                    closeSpeedHoverGroup();
                }
            });

            updateSpeedHoverBtnHighlight();
        }


        function updateSpeedHoverBtnHighlight() {
            document.querySelectorAll('.speed-hover-btn').forEach(btn => {
                const spd = parseFloat(btn.dataset.speed);
                btn.classList.toggle('active-speed', Math.abs(spd - currentSpeedRate) < 0.01);
            });
        }


        function toggleSpeedHoverGroup() {
            const group = document.getElementById('speedHoverGroup');
            if (!group) return;
            updateSpeedHoverBtnHighlight();
            group.classList.toggle('visible');
        }

        function closeSpeedHoverGroup() {
            const group = document.getElementById('speedHoverGroup');
            if (!group) return;
            group.classList.remove('visible');
        }

        function setupMoveBtns() {
            const btnNext = document.getElementById('btnNext');
            const btnPrev = document.getElementById('btnPrev');

            function bindBtn(btn, direction) {
                let moveHoldTimer = null;
                let moveBtnPressed = false;
                let isLongPressTriggered = false;

                btn.oncontextmenu = function(e) { e.preventDefault(); return false; };

                btn.addEventListener('pointerdown', (e) => {
                    if (e.button !== 0 && e.pointerType === 'mouse') return;
                    if (btn.setPointerCapture) btn.setPointerCapture(e.pointerId);
                    
                    if (moveHoldTimer) clearTimeout(moveHoldTimer); // 追加: ゾンビタイマー防止

                    if (isAutoMoving) {
                        stopAutoMove();
                        moveBtnPressed = false; 
                        return; // 追加: 停止クリック時はここで処理を打ち切る
                    }

                    moveBtnPressed = true;
                    isLongPressTriggered = false;

                    moveHoldTimer = setTimeout(() => {
                        if (moveBtnPressed) {
                            isLongPressTriggered = true;
                            startAutoMove(direction, btn);
                        }
                    }, 500);
                });

                btn.addEventListener('pointerup', (e) => {
                    if (btn.releasePointerCapture) btn.releasePointerCapture(e.pointerId);
                    if (!moveBtnPressed) return; 
                    
                    moveBtnPressed = false;
                    if (moveHoldTimer) clearTimeout(moveHoldTimer);

                    if (!isLongPressTriggered) {
                        if (direction === 'next') skipToNextItem();
                        else skipToPrevItem();
                    }
                });

                const cancelHandler = (e) => {
                    if (btn.releasePointerCapture) btn.releasePointerCapture(e.pointerId);
                    moveBtnPressed = false;
                    if (moveHoldTimer) clearTimeout(moveHoldTimer);
                };
                btn.addEventListener('pointercancel', cancelHandler);
                // pointerleave はタップ時の微妙な指滑りで誤発火し、反応の悪さに直結するため削除（CSSの当たり判定拡大でカバー）
            }

            bindBtn(btnNext, 'next');
            bindBtn(btnPrev, 'prev');
        }


        function startAutoMove(direction, btnElement) {
            isAutoMoving = true;
            syncCurrentIndexToVisibleItem();
            stopAllSpeech(); 
            
            btnElement.classList.add('move-fixed');

            // 初回移動は従来どおり即時実行する
            doAutoMoveStep(direction); 

            // 次回以降は毎回 getAutoMoveDelay() を読み直して予約する
            if (isAutoMoving) {
                scheduleNextAutoMoveStep(direction);
            }
        }





        function stopAutoMove() {
            isAutoMoving = false;
            if (autoMoveInterval) clearTimeout(autoMoveInterval);
            autoMoveInterval = null;
            
            document.getElementById('btnNext').classList.remove('move-fixed');
            document.getElementById('btnPrev').classList.remove('move-fixed');
        }
        

        function getAutoMoveDelay() {
            const pcDelayMap = {
                1.0: 3000,
                1.5: 2500,
                2.0: 2000,
                3.0: 1000
            };
            const iosDelayMap = {
                1.0: 3000,
                1.2: 2500,
                1.5: 2000,
                1.8: 1500
            };
            const key = Number(currentSpeedRate.toFixed(1));
            const delayMap = isIOS ? iosDelayMap : pcDelayMap;
            return delayMap[key] || 2000;
        }


        function scheduleNextAutoMoveStep(direction) {
            if (!isAutoMoving) return;
            if (autoMoveInterval) clearTimeout(autoMoveInterval);

            autoMoveInterval = setTimeout(() => {
                doAutoMoveStep(direction);
                if (isAutoMoving) {
                    scheduleNextAutoMoveStep(direction);
                }
            }, getAutoMoveDelay());
        }

        function doAutoMoveStep(direction) {
            if (flatQueue.length === 0) {
                stopAutoMove();
                return;
            }

            let nextIndex;
            if (currentFlatIndex === -1) {
                nextIndex = direction === 'next' ? 0 : flatQueue.length - 1;
            } else {
                nextIndex = direction === 'next' ? currentFlatIndex + 1 : currentFlatIndex - 1;
            }

            // 要約失敗カード（is_error）は連続してスキップする
            // 音声読み上げ時のplayCurrentPart内is_errorチェック（advanceAuto）と同じ挙動に統一
            while (nextIndex >= 0 && nextIndex < flatQueue.length && flatQueue[nextIndex].item.is_error) {
                nextIndex = direction === 'next' ? nextIndex + 1 : nextIndex - 1;
            }

            if (nextIndex < 0 || nextIndex >= flatQueue.length) {
                stopAutoMove();
                return;
            }

            currentFlatIndex = nextIndex;
            currentPart = 'title';
            updateHighlighting();
        }
        

        function getDynamicHeaderOffset() {
            let offset = 0;
            const header = document.getElementById('appHeader');
            const panel = document.getElementById('controlPanel');
            if (header) offset += header.offsetHeight;
            if (panel) offset += panel.offsetHeight;
            return offset + 5; // 5pxの安全マージン
        }

        function syncCurrentIndexToVisibleItem() {
            let closestIdx = -1;
            let minDistance = Infinity;
            const items = document.querySelectorAll('.summary-item');
            const headerOffset = getDynamicHeaderOffset();

            items.forEach(itemEl => {
                const rect = itemEl.getBoundingClientRect();
                if (rect.bottom > headerOffset) {
                    const distance = Math.abs(rect.top - headerOffset);
                    if (distance < minDistance) {
                        minDistance = distance;
                        const parts = itemEl.id.split('-');
                        if (parts.length === 3) {
                            const fIdx = parseInt(parts[1]);
                            const iIdx = parseInt(parts[2]);
                            const qIdx = flatQueue.findIndex(q => q.fIdx === fIdx && q.iIdx === iIdx);
                            if (qIdx !== -1) {
                                closestIdx = qIdx;
                            }
                        }
                    }
                }
            });

            if (closestIdx !== -1) {
                currentFlatIndex = closestIdx;
                return true;
            }
            return false;
        }


        function startPlayback() {
            stopAutoMove(); // 追加: 音声再生開始時に自動スクロールを強制停止
            if (flatQueue.length === 0) return;

            if (syncCurrentIndexToVisibleItem()) {
                currentPart = flatQueue[currentFlatIndex].is_first ? 'file_intro' : 'title';
            } else if (currentFlatIndex === -1 || currentFlatIndex >= flatQueue.length) {
                currentFlatIndex = 0; currentPart = 'file_intro';
            }
            applyAutoSkipMode();
            isPlaying = true;
            const btn = document.getElementById('btnPlayPause');
            btn.innerText = "⏹";
            btn.classList.add('playing');
            playCurrentPart();
        }
        

        function resumePlayback() {
            stopAutoMove(); // 追加: 音声再生再開時に自動スクロールを強制停止
            if (flatQueue.length === 0) return;
            if (currentFlatIndex === -1 || currentFlatIndex >= flatQueue.length) {
                currentFlatIndex = 0; currentPart = 'file_intro';
            }
            applyAutoSkipMode();
            isPlaying = true;
            const btn = document.getElementById('btnPlayPause');
            btn.innerText = "⏹";
            btn.classList.add('playing');
            playCurrentPart();
        }


        function stopAllSpeech(skipHighlight = false) {
            isPlaying = false;
            skipModeManualOverride = false; // 再生停止時に手動固定を解除し、次回開始時は自動判定からやり直す
            if(playTimer) clearTimeout(playTimer);
            if (currentUttr) { currentUttr.onend = null; currentUttr.onerror = null; }
            window.speechSynthesis.cancel();
            const btn = document.getElementById('btnPlayPause');
            btn.innerText = "▶️";
            btn.classList.remove('playing');
            if (!skipHighlight) updateHighlighting();
        }

        function skipToNextItem() {
            if (skipMode === 1) { skipMode = (skipModeBeforeOneShot !== null) ? skipModeBeforeOneShot : 0; skipModeBeforeOneShot = null; updateSkipBtnUI(); }
            const wasPlaying = isPlaying;
            stopAllSpeech(true);
            if (currentFlatIndex === -1) {
                syncCurrentIndexToVisibleItem();
                if (currentFlatIndex !== -1) {
                    currentPart = flatQueue[currentFlatIndex].is_first ? 'file_intro' : 'title';
                    applyAutoSkipMode();
                }
                updateHighlighting();
                return;
            }
            if (flatQueue.length === 0) return;
            if (currentFlatIndex < flatQueue.length - 1) currentFlatIndex++;
            currentPart = flatQueue[currentFlatIndex].is_first ? 'file_intro' : 'title';
            applyAutoSkipMode();
            if(playTimer) clearTimeout(playTimer);
            if (wasPlaying) { playTimer = setTimeout(resumePlayback, 300); } else { updateHighlighting(); }
        }


        function skipToPrevItem() {
            if (skipMode === 1) { skipMode = (skipModeBeforeOneShot !== null) ? skipModeBeforeOneShot : 0; skipModeBeforeOneShot = null; updateSkipBtnUI(); }
            const wasPlaying = isPlaying;
            stopAllSpeech(true);
            if (currentFlatIndex === -1) {
                syncCurrentIndexToVisibleItem();
                if (currentFlatIndex !== -1) {
                    currentPart = flatQueue[currentFlatIndex].is_first ? 'file_intro' : 'title';
                    applyAutoSkipMode();
                }
                updateHighlighting();
                return;
            }
            if (flatQueue.length === 0) return;
            if (currentFlatIndex > 0) currentFlatIndex--;
            currentPart = flatQueue[currentFlatIndex].is_first ? 'file_intro' : 'title';
            applyAutoSkipMode();
            if(playTimer) clearTimeout(playTimer);
            if (wasPlaying) { playTimer = setTimeout(resumePlayback, 300); } else { updateHighlighting(); }
        }
        
        function jumpToPrevFile() {
            if (skipMode === 1) { skipMode = (skipModeBeforeOneShot !== null) ? skipModeBeforeOneShot : 0; skipModeBeforeOneShot = null; updateSkipBtnUI(); }
            const wasPlaying = isPlaying;
            stopAllSpeech(true);
            if (flatQueue.length === 0) return;
            let curr = flatQueue[currentFlatIndex] || flatQueue[0];
            
            if (curr.iIdx > 0) {
                let target = flatQueue.findIndex(q => q.fIdx === curr.fIdx && q.is_first);
                if (target !== -1) currentFlatIndex = target;
            } else {
                let target = -1;
                for (let i = currentFlatIndex - 1; i >= 0; i--) {
                    if (flatQueue[i].is_first && flatQueue[i].fIdx !== curr.fIdx) {
                        target = i; break;
                    }
                }
                if (target !== -1) currentFlatIndex = target;
                else currentFlatIndex = 0;
            }
            currentPart = 'file_intro';
            applyAutoSkipMode();
            updateHighlighting(); 
            if (wasPlaying) { playTimer = setTimeout(resumePlayback, 300); }
        }
       
        function jumpToNextFile() {
            if (skipMode === 1) { skipMode = (skipModeBeforeOneShot !== null) ? skipModeBeforeOneShot : 0; skipModeBeforeOneShot = null; updateSkipBtnUI(); }
            const wasPlaying = isPlaying;
            stopAllSpeech(true);
            if (flatQueue.length === 0) return;
            let curr = flatQueue[currentFlatIndex] || flatQueue[0];
            
            let target = -1;
            for (let i = currentFlatIndex + 1; i < flatQueue.length; i++) {
                if (flatQueue[i].is_first && flatQueue[i].fIdx !== curr.fIdx) {
                    target = i; break;
                }
            }
            if (target !== -1) {
                currentFlatIndex = target;
                currentPart = 'file_intro';
            }
            applyAutoSkipMode();
            updateHighlighting(); 
            if (wasPlaying) { playTimer = setTimeout(resumePlayback, 300); }
        }

       
        function advanceAuto() {
            if (skipMode === 1) { skipMode = (skipModeBeforeOneShot !== null) ? skipModeBeforeOneShot : 0; skipModeBeforeOneShot = null; updateSkipBtnUI(); }
            currentFlatIndex++;
            if (currentFlatIndex >= flatQueue.length) {
                stopAllSpeech(); currentFlatIndex = -1;
            } else {
                currentPart = flatQueue[currentFlatIndex].is_first ? 'file_intro' : 'title';
                applyAutoSkipMode();
                if (currentPart === 'file_intro' && isPlaying) {
                    playChime(() => {
                        if (isPlaying) playCurrentPart();
                    });
                } else {
                    playCurrentPart();
                }
            }
        }

        function playCurrentPart() {
            if (!isPlaying || currentFlatIndex === -1) return;
            if (!isChimePlaying) {
                window.speechSynthesis.cancel();
            }
            updateHighlighting();
            
            const qData = flatQueue[currentFlatIndex];
            const item = qData.item;
            let txt = "";
            
            if (currentPart === 'file_intro') {
                const fileItemCount = filteredData[qData.fIdx].items.length;
                if (currentFlatIndex === 0) {
                    txt = `それでは、${fileItemCount}件のサマリーを開始します。`;
                } else {
                    const fname = qData.filename || '';
                    const prefixMatch = fname.match(/^(summary_[^_]+(?:_[^_]+)*)_\d{8}_/);
                    const prefix = prefixMatch ? prefixMatch[1] : fname;
                    txt = `次に、${prefix}の、${fileItemCount}件のサマリーに移ります。`;
                }
            } else {
            
                if (item.is_error) {
                    advanceAuto();
                    return;
                } else {
                    if (currentPart === 'title') txt = `${qData.iIdx + 1}番。 ${item.title}`;
                    else if (currentPart === 'summary') txt = item.summary;
                    else if (currentPart === 'points') {
                        let tempDiv = document.createElement("div");
                        tempDiv.innerHTML = item.points;
                        txt = "主なポイント。 " + tempDiv.textContent;
                    }
                    else if (currentPart === 'conclusion') txt = item.conclusion ? ("結論。 " + item.conclusion) : "";
                    else if (currentPart === 'points_unavailable') txt = "主なポイントは生成されませんでした。";
                    else if (currentPart === 'point_titles') {
                        const listHtml = buildPointTitlesList(item.points);
                        let tempDiv = document.createElement("div");
                        tempDiv.innerHTML = listHtml;
                        const headings = Array.from(tempDiv.querySelectorAll('li')).map(li => li.textContent.trim());
                        txt = headings.length > 0 ? "主なポイント。 " + headings.join("、 ") : "";
                    }
                }
            }
            
            if (!txt) { handlePartEnd(); return; }
            
            // Siri等での記号による反復読み上げバグ対策
            txt = txt.replace(/[：:\\u00D7・]/g, '、');
            // Markdown見出し記号(#)対策: 「ハッシュタグ」と読まれてしまうため除去
            txt = txt.replace(/#+/g, '');

            const ut = new SpeechSynthesisUtterance(txt);
            ut.lang = 'ja-JP'; ut.rate = currentSpeedRate;
            
            if (availableVoices.length === 0) availableVoices = window.speechSynthesis.getVoices();
            const jaVoices = availableVoices.filter(v => v.lang.includes('ja'));
            if (jaVoices.length > 0) {
                if (state.useHighQualityVoice) {
                    // siri/Premium/EnhancedはmacOS/Safariの音声名。Windows(Edge/Chrome共通)の
                    // 高品質音声は「Natural」を含む名前(例: Microsoft Nanami Online (Natural))
                    // のため、この判定が無いとWindowsでは常に最後のフォールバックに落ちていた(S05)
                    let bestVoice = jaVoices.find(v => v.name.toLowerCase().includes('siri') && v.name.includes('2'));
                    if (!bestVoice) bestVoice = jaVoices.find(v => v.name.toLowerCase().includes('siri'));
                    if (!bestVoice) bestVoice = jaVoices.find(v => v.name.includes('Premium') || v.name.includes('Enhanced'));
                    if (!bestVoice) bestVoice = jaVoices.find(v => v.name.includes('Natural'));
                    ut.voice = bestVoice || jaVoices[jaVoices.length - 1];
                } else {
                    let stdVoice = jaVoices.find(v => !v.name.toLowerCase().includes('siri') && !v.name.includes('Premium') && !v.name.includes('Enhanced'));
                    ut.voice = stdVoice || jaVoices[0];
                }
            }

            // iOSのイベント重複発火バグ対策（クロージャ内ローカルフラグによる物理的ロック）
            let isHandled = false;
            ut.onend = () => { 
                if (!isHandled) { 
                    isHandled = true; 
                    if (isPlaying) handlePartEnd(); 
                } 
            };
            ut.onerror = () => { 
                if (!isHandled) { 
                    isHandled = true; 
                    if (isPlaying) handlePartEnd(); 
                } 
            };
            
            currentUttr = ut;
            window.speechSynthesis.speak(ut);
        }

        async function handlePartEnd() {
            if(playTimer) clearTimeout(playTimer);
            if (currentPart === 'file_intro') {
                if (!isChimePlaying) {
                    currentPart = 'title';
                    playTimer = setTimeout(playCurrentPart, 10);
                }
            }
            else if (currentPart === 'title') { 
                if (skipMode === 3) {
                    advanceAuto(); 
                } else {
                    currentPart = 'summary'; playTimer = setTimeout(playCurrentPart, 10); 
                }
            } 
            else if (currentPart === 'summary') {
                if (skipMode === 0) {
                    advanceAuto();
                } else if (skipMode === 3) {
                    // [20260808] タイトルのみモード。
                    // モード変更で読み上げを中断しなくなったため、要旨の途中で
                    // ▶▶▶ を押すとこの状態に到達しうる（従来はタイトルへ巻き戻って
                    // いたため発生しなかった）。末尾のelseに落ちると主なポイントを
                    // 読み始めてしまい、タイトルのみという指定に反するので、
                    // 読み終えたら次のカードへ進む。
                    advanceAuto();
                } else if (skipMode === 4) {
                    // skipMode 4: pointsではなくconclusionを読む。空なら次のカードへ
                    const qData = flatQueue[currentFlatIndex];
                    if (qData.item.conclusion) {
                        currentPart = 'conclusion'; playTimer = setTimeout(playCurrentPart, 10);
                    } else {
                        advanceAuto();
                    }
                } else if (skipMode === 1) {
                    // skipMode 1: 結論をスキップし主なポイント本文へ（存在する場合は自動展開）。
                    //             1カード読了後に元のモードへ自動復帰する一時モード。
                    // RSSカードでまだ主なポイントが未生成の場合は、自動生成を起動して完了を待つ。
                    // 待っても生成されなかった場合は専用の案内文を読み上げてから次のカードへ進む。
                    const qData = flatQueue[currentFlatIndex];
                    if (qData.item.points) {
                        openPointsAccordion(qData.fIdx, qData.iIdx);
                        currentPart = 'points'; playTimer = setTimeout(playCurrentPart, 10);
                    } else {
                        const pending = triggerRssPointsGenerationIfNeeded(qData.fIdx, qData.iIdx);
                        if (pending) {
                            await pending;
                            // 待機中に停止/モード変更/カード移動があった場合は何もしない
                            if (!isPlaying || skipMode !== 1 || flatQueue[currentFlatIndex] !== qData) return;
                            if (qData.item.points) {
                                openPointsAccordion(qData.fIdx, qData.iIdx);
                                currentPart = 'points'; playTimer = setTimeout(playCurrentPart, 10);
                            } else {
                                currentPart = 'points_unavailable'; playTimer = setTimeout(playCurrentPart, 10);
                            }
                        } else {
                            advanceAuto();
                        }
                    }
                } else {
                    // skipMode 2: 同じく主なポイント本文へ。手動選択したまま維持される固定モード。
                    const qData = flatQueue[currentFlatIndex];
                    if (qData.item.points) {
                        openPointsAccordion(qData.fIdx, qData.iIdx);
                        currentPart = 'points'; playTimer = setTimeout(playCurrentPart, 10);
                    } else {
                        advanceAuto();
                    }
                }
            }
            else if (currentPart === 'conclusion') {
                // skipMode 4でsummary読了後に遷移してくる。読了後は次のカードへ
                advanceAuto();
            }
            else if (currentPart === 'point_titles') {
                // skipMode 2でsummary読了後に遷移してくる。読了後は次のカードへ
                advanceAuto();
            }
            else if (currentPart === 'points') { advanceAuto(); }
            else if (currentPart === 'points_unavailable') { advanceAuto(); }
        }

        function updateHighlighting() {
            document.querySelectorAll('.summary-item').forEach(i => i.classList.remove('active'));
            if (currentFlatIndex >= 0 && currentFlatIndex < flatQueue.length) {
                const qData = flatQueue[currentFlatIndex];
                
                const headerText = document.getElementById('appHeaderText');
                const fileObj = filteredData[qData.fIdx];
                if (fileObj && headerText) {
                    // [20260805] ファイル名の長さによって「n/total件」が折り返されたり
                    // されなかったりして読みづらいとの指摘のため、1行目=ファイル名、
                    // 2行目=読み上げ位置、に固定フォーマット化する。
                    // 同じカードの間は再構築せず(headerKeyで判定)、ヘッダー高さが
                    // 実際に変わり得るタイミングだけsticky位置を再計測する。
                    const headerKey = `${qData.fIdx}-${qData.iIdx}`;
                    if (headerText.dataset.key !== headerKey) {
                        headerText.dataset.key = headerKey;
                        const nameSpan = document.createElement('span');
                        nameSpan.className = 'header-filename';
                        nameSpan.textContent = fileObj.filename;
                        const posSpan = document.createElement('span');
                        posSpan.className = 'header-position';
                        posSpan.textContent = `${qData.iIdx + 1}/${fileObj.items.length}件`;
                        headerText.replaceChildren(nameSpan, document.createElement('br'), posSpan);
                        requestAnimationFrame(updateStickyOffsets);
                    }
                }

                // 既読履歴の保存と適用
                const historyKey = `${fileObj.filename}_${qData.iIdx}`;
                if (!state.readHistory[historyKey]) {
                    state.readHistory[historyKey] = true;
                    saveState();
                    // 週次推移グラフの既読/未読内訳をその場で更新する
                    if (DASHBOARD_DATA.weekly && DASHBOARD_DATA.weekly.trend) {
                        renderTrendChart(DASHBOARD_DATA.weekly.trend);
                    }
                }
                
                const card = document.getElementById(`file-card-${qData.fIdx}`);

                if (card) {
                    finalizePendingAutoUncheckOnFileChange(fileObj.filename);
                    if (!card.classList.contains('expanded')) { card.classList.add('expanded'); }
                    const isAllRead = fileObj.items.length > 0 && fileObj.items.every((_, idx) => state.readHistory[`${fileObj.filename}_${idx}`]);
                    if (isAllRead) card.classList.add('all-read');
                    if (isAllRead) {
                        queueAutoUncheckFile(fileObj);
                    } else {
                        delete pendingAutoUncheckFiles[fileObj.filename];
                    }
                }                
                const itemId = `item-${qData.fIdx}-${qData.iIdx}`;
                const itemEl = document.getElementById(itemId);
                
                // --- スクロールターゲットの動的判定 ---
                let targetId = itemId;
                if (currentPart === 'points') targetId = `points-wrapper-${qData.fIdx}-${qData.iIdx}`;
                
                let targetEl = document.getElementById(targetId);
                // 要素が存在しない、または非表示の場合はカード全体にフォールバック（念のための安全装置）
                if (!targetEl || targetEl.offsetParent === null) targetEl = itemEl;

                if (itemEl) {
                    if (isPlaying) itemEl.classList.add('active');
                    itemEl.classList.add('read-done');
                    // スクロールはscrollToCurrentItemに完全委譲
                    // MutationObserverによりDOM確定後に確実に実行される
                    scrollToCurrentItem(targetEl);
                }
            }
        }

        window.onload = init;
    </script>
</body>
</html>"""
        final_html = html_content.replace('{{JSON_DATA_PLACEHOLDER}}', json_data_str)
        final_html = final_html.replace('{{DASHBOARD_DATA_PLACEHOLDER}}', dashboard_data_str)
        final_html = final_html.replace('        // __INJECT_NEW_FUNCTIONS__\n', NEW_FUNCTIONS_JS)

        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write(final_html)
        print(f"[Success] Consolidated HTML generated at: {self.output_file}")


def _resolve_target_dir():
    # youtube_summary_list.pyのOUTPUT_DIRと同じフォルダを指す必要があるため、同じ環境変数名・configキーを使う(S05)
    env_value = os.environ.get('YT_SUMMARY_OUTPUT_DIR', '').strip()
    if env_value:
        return env_value
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        config_value = str(loaded.get('paths', {}).get('output_dir', '') or '').strip()
        if config_value:
            return config_value
    except Exception:
        pass
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')


if __name__ == "__main__":
    TARGET_DIR = _resolve_target_dir()

    if not os.path.exists(TARGET_DIR):
        print(f"[Error] 指定されたフォルダが見つかりません: {TARGET_DIR}")
    else:
        print(f"Scanning directory: {TARGET_DIR}")
        manager = SummaryFolderManager(TARGET_DIR)
        extracted_data = manager.extract_data()
        
        if extracted_data:
            print(f"Extracted data from {len(extracted_data)} valid summary files.")
            manager.generate_manager_html(extracted_data)
        else:
            print("No valid summary files found.")