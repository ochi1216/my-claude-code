VERSION = "20260801_01_01" # 管理用定数

r"""
RSS 統合マネジメントツール（Note専用独立版）
"""
import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import webbrowser
import threading
import math
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import google.generativeai as genai
import feedparser
from playwright.sync_api import sync_playwright

# [v20260508.03追加] オンデマンド要約用ローカルAPIサーバー
ONDEMAND_API_PORT = 17320   # HTMLから呼び出すローカルポート
_ondemand_server_started = False  # 起動済みフラグ

# [v20260508.03_02追加] 英語タイトル自動翻訳（deep-translator）
try:
    from deep_translator import GoogleTranslator as _GTrans
    _TRANSLATE_AVAILABLE = True
except ImportError:
    _TRANSLATE_AVAILABLE = False


def _is_english_title(title: str) -> bool:
    """
    [v20260508.03_02追加]
    ASCII文字率に基づく英語判定。
    langdetectは短いタイトルで誤判定が多いため不使用。
    CJK文字が1字でも含まれれば非英語と判定し、
    それ以外はASCII率が70%以上なら英語とみなす。
    """
    if not title or not title.strip():
        return False
    for ch in title:
        if ord(ch) > 0x3000:  # CJK・全角記号など
            return False
    ascii_count = sum(1 for c in title if ord(c) < 128)
    return (ascii_count / len(title)) >= 0.70


def translate_title_if_english(title: str) -> str | None:
    """
    [v20260508.03_02追加]
    タイトルが英語と判定された場合に日本語翻訳文字列を返す。
    日本語・ライブラリ未インストールの場合は None を返す。
    """
    if not _TRANSLATE_AVAILABLE or not _is_english_title(title):
        return None
    try:
        translated = _GTrans(source='en', target='ja').translate(title)
        if not translated or translated.strip() == title.strip():
            return None
        return translated
    except Exception:
        return None


def translate_articles_titles(articles: list, progress_callback=None) -> None:
    """
    [v20260508.03_02追加]
    記事リスト内の英語タイトルを並列翻訳し、各記事に title_ja フィールドを追加する。
    既に title_ja がある場合はスキップ。
    """
    targets = [a for a in articles if 'title_ja' not in a]
    if not targets:
        return
    total = len(targets)
    done = [0]
    lock = threading.Lock()

    def _translate_one(article):
        ja = translate_title_if_english(article.get('title', ''))
        article['title_ja'] = ja  # None の場合は日本語記事と判断
        with lock:
            done[0] += 1
            if progress_callback:
                progress_callback(done[0], total, f"🌐 タイトル翻訳中... {done[0]}/{total}")

    with ThreadPoolExecutor(max_workers=4) as exc:
        list(exc.map(_translate_one, targets))

# セキュリティ制限対象ドメインのブラックリスト
BLOCK_DOMAINS = [
    "x.com", "twitter.com", "t.co", 
    "facebook.com", "fbcdn.net", "connect.facebook.net", "messenger.com",
    "temu.com"
]

# ============================================================
# 設定・データ管理
# ============================================================

CONFIG_FILE = "rss_manager_config.json"
HISTORY_FILE = "read_history.json"
AI_FEED_HISTORY_FILE = "ai_feed_history.json"  # [v20260508.03_03追加] AIフィード専用既読履歴
ARTICLE_DAYS_LIMIT = 7  # [v20260508.03_03追加] 全タブ共通：過去何日以内の記事のみ表示するか
KEYWORDS_FILE = "keywords.txt"
MY_KEYWORDS_FILE = "my_keywords.txt"
RECOMMEND_CONFIG_FILE = "recommend_config.json"
FOLLOWED_NOTE_FILE = "followed_note_authors.txt"  # フォローnote作者URLリスト

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "gemini_model":   "gemini-2.5-flash",
    "note_urlname":   "",        # [v20260527.01_01追加] note URLname（例: a0739635）
    "note_email":     "",        # [v20260527.01_01追加] note ログインメールアドレス
    "note_sync_mode": "merge"    # [v20260527.01_01追加] "merge"(追記のみ) or "full"(完全同期)
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                for key, value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = value
                return config
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def normalize_note_rss_url(url: str) -> str:
    """note作者URLをRSS URLへ正規化する"""
    url = url.strip()
    if not url:
        return ""
    url = url.rstrip("/")
    if url.endswith("/rss"):
        return url
    return url + "/rss"


def load_followed_note_urls():
    """followed_note_authors.txt からnote作者URLを読み込む"""
    if not os.path.exists(FOLLOWED_NOTE_FILE):
        return []
    with open(FOLLOWED_NOTE_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def cosine_similarity(v1, v2):
    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag_v1 = math.sqrt(sum(a * a for a in v1))
    mag_v2 = math.sqrt(sum(b * b for b in v2))
    if mag_v1 == 0 or mag_v2 == 0:
        return 0.0
    return dot_product / (mag_v1 * mag_v2)


# ============================================================
# [v20260508.02追加] AI最先端フィード 固定URLリスト
# [v20260801_01修正] 毎回の読み込み量が多すぎるとの指摘を受け対応。
# 実際の ai_feed_history.json（直近1週間・606件）を分析した結果、
# arXiv 4フィード（cs.AI/cs.LG/cs.CL/cs.CV）が全体の57%(345件)を占め、
# 主要因と判明。一方 Papers with Code は同期間0件で、Windows実機での
# feedparser動作確認でも SSLV3_ALERT_HANDSHAKE_FAILURE により
# フィード自体が機能停止していることを確認した。
# ユーザー判断: 英語メディア・AI企業ブログ・日本語メディアは件数維持。
# 論文・研究は arXiv 4フィード・Papers with Code とも取得を停止し、0件とする。
# ============================================================
AI_FEED_URLS = {
    "英語メディア": [
        {"title": "TechCrunch AI",        "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
        {"title": "VentureBeat AI",        "url": "https://venturebeat.com/category/ai/feed/"},
        {"title": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/"},
        {"title": "The Verge AI",          "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
        {"title": "Wired AI",              "url": "https://www.wired.com/feed/tag/ai/latest/rss"},
    ],
    "AI企業・研究機関ブログ": [
        {"title": "OpenAI Blog",           "url": "https://openai.com/blog/rss.xml"},
        {"title": "Anthropic News",        "url": "https://www.anthropic.com/rss.xml"},
        {"title": "Google DeepMind Blog",  "url": "https://deepmind.google/blog/rss.xml"},
        {"title": "Meta AI Blog",          "url": "https://ai.meta.com/blog/rss/"},
        {"title": "Hugging Face Blog",     "url": "https://huggingface.co/blog/feed.xml"},
        {"title": "DeepLearning.AI Batch", "url": "https://www.deeplearning.ai/the-batch/feed/"},
    ],
    # [v20260801_01修正] arXiv 4フィード・Papers with Codeとも取得停止（ユーザー判断）。
    # 再開する場合は旧版 rss_organizer_20260708_02.py の同カテゴリを参照。
    "論文・研究": [],
    "日本語メディア": [
        {"title": "ITmedia AI+",           "url": "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml"},
        {"title": "Ledge.ai",              "url": "https://ledge.ai/feed"},
        {"title": "Publickey",             "url": "https://www.publickey1.jp/atom.xml"},
        {"title": "テクノエッジ",           "url": "https://www.techno-edge.net/rss20/index.rdf"},
    ],
}

# arXiv は記事数が多いため1フィードあたりの取得上限を設ける
# [v20260801_01修正] 論文・研究フィード停止に伴い現在は使用されないが、
# 再開時のために定数自体は残す
AI_FEED_ARXIV_MAX = 15  # arXiv フィードの最大取得件数

# ============================================================
# サイト別プロファイル設定
# ============================================================
SITE_CONFIG = {
    "note": {
        "url_tmpl": "https://note.com/hashtag/{kw}/rss",
        "selector": "main",
        "exclude": "",
        "is_spa": True
    },
    "Qiita": {
        "url_tmpl": "https://qiita.com/tags/{kw}/feed",
        "selector": ".it-ArticleMain_content",
        "exclude": "pre, code",
        "is_spa": True
    },
    "Zenn": {
        "url_tmpl": "https://zenn.dev/topics/{kw}/feed",
        "selector": ".znc",
        "exclude": "pre, code",
        "is_spa": True
    }
}


# ============================================================
# RSS取得・履歴管理クラス
# ============================================================

class RSSFeedManager:
    def __init__(self, history_file=HISTORY_FILE):
        self.history_file = history_file
        self.history = self._load_history()
        # [v20260508.03_03追加] AIフィード専用既読履歴
        self.ai_feed_history_file = AI_FEED_HISTORY_FILE
        self.ai_feed_history = self._load_ai_feed_history()

    def _load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
            except: pass
        return set()

    def save_history(self):
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(list(self.history), f, indent=2, ensure_ascii=False)


    def _load_ai_feed_history(self):
        """[v20260508.03_03追加] AIフィード専用既読履歴を読み込む
        [v20260529_01_03変更] 形式をURL→タイムスタンプ辞書に変更。旧リスト形式との後方互換あり"""
        if os.path.exists(self.ai_feed_history_file):
            try:
                with open(self.ai_feed_history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 旧形式（list）→新形式（dict）へ変換
                if isinstance(data, list):
                    now_str = datetime.now().isoformat()
                    return {url: now_str for url in data}
                # 新形式（dict）はそのまま返す
                if isinstance(data, dict):
                    return data
            except:
                pass
        return {}


    def save_ai_feed_history(self):
        """[v20260508.03_03追加] AIフィード専用既読履歴を保存する
        [v20260529_01_03変更] dict形式（URL→タイムスタンプ）で保存"""
        with open(self.ai_feed_history_file, 'w', encoding='utf-8') as f:
            json.dump(self.ai_feed_history, f, indent=2, ensure_ascii=False)


    def mark_ai_feed_as_read(self, urls: list):
        """[v20260508.03_03追加] AIフィード記事を既読登録して保存する
        [v20260529_01_03変更] タイムスタンプ付きdict形式で登録"""
        now_str = datetime.now().isoformat()
        for url in urls:
            self.ai_feed_history[url] = now_str
        self.save_ai_feed_history()

    def purge_ai_feed_history(self):
        """[v20260529_01_03追加] ARTICLE_DAYS_LIMIT日以上前の既読エントリを削除する"""
        from datetime import timedelta as _td
        cutoff = datetime.now() - _td(days=ARTICLE_DAYS_LIMIT)
        before_count = len(self.ai_feed_history)
        purged = {
            url: ts
            for url, ts in self.ai_feed_history.items()
            if datetime.fromisoformat(ts) >= cutoff
        }
        self.ai_feed_history = purged
        self.save_ai_feed_history()
        after_count = len(self.ai_feed_history)
        print(f"🧹 AI既読履歴パージ完了: {before_count}件 → {after_count}件"
              f"（{before_count - after_count}件削除）")

    def fetch_rss(self, keywords: list, progress_callback=None):
        """サイト単位で全キーワードを巡回取得（セキュリティフィルタ付き）"""
        if not keywords: return []
        articles = {}
        total_steps = len(SITE_CONFIG) * len(keywords)
        step = 0

        for site_name, cfg in SITE_CONFIG.items():
            for kw in keywords:
                step += 1
                if progress_callback:
                    progress_callback(f"📡 {site_name}取得中 ({step}/{total_steps}): {kw}")
                
                url = cfg["url_tmpl"].format(kw=kw)
                try:
                    d = feedparser.parse(url)
                    for entry in d.entries:
                        link = entry.link
                        if link in self.history: continue
                        
                        # 指定されたブラックリストドメインが含まれるURLはリストに追加しない
                        if any(domain in link.lower() for domain in BLOCK_DOMAINS):
                            continue
                        
                        if link in articles:
                            articles[link]['categories'].add(kw)
                        else:
                            try:
                                dt = parsedate_to_datetime(entry.published)
                                if dt.tzinfo is not None:
                                    dt = dt.replace(tzinfo=None)
                                dt_str, dt_sort = dt.strftime('%Y/%m/%d %H:%M'), dt
                            except:
                                dt_str, dt_sort = "不明", datetime.now().replace(tzinfo=None)

                            articles[link] = {
                                'url': link,
                                'title': entry.title,
                                'source': site_name,
                                'author': entry.get('author', '不明'),
                                'published_str': dt_str,
                                'published_sort': dt_sort,
                                'summary': entry.get('summary', ''),
                                'categories': {kw}
                            }
                except: pass
        
        result = [v for v in articles.values()]
        for r in result: r['categories_str'] = ", ".join(sorted(list(r['categories'])))

        # [v20260508.03_03追加] 過去ARTICLE_DAYS_LIMIT日以内の記事のみに絞り込む
        from datetime import timedelta as _td
        cutoff = datetime.now() - _td(days=ARTICLE_DAYS_LIMIT)
        result = [a for a in result if a.get('published_sort', datetime.now()) >= cutoff]

        # 初期表示のソート順をレポート生成時と同じルールに統一（カテゴリ先行）
        result.sort(key=lambda a: (
            a.get('categories_str', '').lower(),
            a.get('source', '').lower(),
            a.get('author', '').lower(),
            a.get('title', '').lower()
        ))

        return result

    def mark_as_read(self, urls: list):
        for url in urls:
            self.history.add(url)
        self.save_history()

    def fetch_followed_note_rss(self, author_urls: list, progress_callback=None):
        """フォロー作者のnote RSSだけを取得する"""
        if not author_urls:
            return []

        articles = {}
        total_steps = len(author_urls)

        for idx, author_url in enumerate(author_urls, 1):
            rss_url = normalize_note_rss_url(author_url)

            if progress_callback:
                progress_callback(f"👤 フォローnote取得中 ({idx}/{total_steps}): {rss_url}")

            try:
                d = feedparser.parse(rss_url)

                for entry in d.entries:
                    link = entry.link

                    if link in self.history:
                        continue

                    if any(domain in link.lower() for domain in BLOCK_DOMAINS):
                        continue

                    try:
                        dt = parsedate_to_datetime(entry.published)
                        if dt.tzinfo is not None:
                            dt = dt.replace(tzinfo=None)
                        dt_str, dt_sort = dt.strftime('%Y/%m/%d %H:%M'), dt
                    except:
                        dt_str, dt_sort = "不明", datetime.now().replace(tzinfo=None)

                    articles[link] = {
                        "url": link,
                        "title": entry.title,
                        "source": "note-follow",
                        "author": entry.get("author", "不明"),
                        "published_str": dt_str,
                        "published_sort": dt_sort,
                        "summary": entry.get("summary", ""),
                        "categories": {"Followed Note"},
                        "categories_str": "Followed Note"
                    }

            except Exception as e:
                print(f"RSS取得失敗: {rss_url} / {e}")

        result = list(articles.values())

        # [v20260508.03_03追加] 過去ARTICLE_DAYS_LIMIT日以内の記事のみに絞り込む
        from datetime import timedelta as _td
        cutoff = datetime.now() - _td(days=ARTICLE_DAYS_LIMIT)
        result = [a for a in result if a.get('published_sort', datetime.now()) >= cutoff]

        result.sort(
            key=lambda a: a.get("published_sort", datetime.now()),
            reverse=True
        )
        return result

    def fetch_ai_feeds(self, progress_callback=None):
        """[v20260508.02追加] AI最先端フィードを並列取得する"""
        articles = {}
        all_feeds = []
        for category, feeds in AI_FEED_URLS.items():
            for feed in feeds:
                all_feeds.append((category, feed["title"], feed["url"]))

        total = len(all_feeds)

        def fetch_one(args):
            category, feed_title, url = args
            results = []
            try:
                d = feedparser.parse(url)
                is_arxiv = "arxiv.org" in url
                entries = d.entries[:AI_FEED_ARXIV_MAX] if is_arxiv else d.entries
                for entry in entries:
                    link = getattr(entry, 'link', None)
                    if not link:
                        continue
                    # [v20260508.03_03修正] AIフィード専用既読履歴でフィルタする（note/Zenn/Qiitaとは分離）
                    if link in self.ai_feed_history:
                        continue
                    if any(domain in link.lower() for domain in BLOCK_DOMAINS):
                        continue
                    try:
                        dt = parsedate_to_datetime(entry.published)
                        if dt.tzinfo is not None:
                            dt = dt.replace(tzinfo=None)
                        dt_str, dt_sort = dt.strftime('%Y/%m/%d %H:%M'), dt
                    except:
                        dt_str, dt_sort = "不明", datetime.now().replace(tzinfo=None)
                    results.append({
                        'url': link,
                        'title': getattr(entry, 'title', '(タイトルなし)'),
                        'source': 'ai-feed',
                        'author': getattr(entry, 'author', feed_title),
                        'published_str': dt_str,
                        'published_sort': dt_sort,
                        'summary': getattr(entry, 'summary', ''),
                        'categories': {category},
                        'categories_str': category,
                        'feed_title': feed_title,
                    })
            except Exception as e:
                print(f"AI Feed取得失敗: {url} / {e}")
            return results

        done_count = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(fetch_one, args): args for args in all_feeds}
            for future in as_completed(futures):
                done_count += 1
                category, feed_title, url = futures[future]
                if progress_callback:
                    progress_callback(f"📡 AIフィード取得中 ({done_count}/{total}): {feed_title}")
                for art in future.result():
                    key = art['url']
                    if key not in articles:
                        articles[key] = art

        result = list(articles.values())

        # [v20260508.03_03追加] 過去ARTICLE_DAYS_LIMIT日以内の記事のみに絞り込む
        from datetime import timedelta as _td
        cutoff = datetime.now() - _td(days=ARTICLE_DAYS_LIMIT)
        result = [a for a in result if a.get('published_sort', datetime.now()) >= cutoff]

        # 公開日時の降順に並び替え
        result.sort(key=lambda a: a.get('published_sort', datetime.now()), reverse=True)
        return result

# ============================================================
# [v20260527.01_01追加] noteフォロー作者自動同期クラス
# ============================================================

class NoteFollowingSyncer:
    """
    [v20260527.01_01追加]
    note.com フォロー作者自動同期クラス。
    Playwright で note.com にログインし、フォロー一覧を取得して
    followed_note_authors.txt に merge または full モードで同期する。
    パスワードは Windows 資格情報マネージャー (keyring) に保存し、
    設定ファイルには平文で書かない。
    """

    KEYRING_SERVICE = "rss_organizer_note"
    # フォロー一覧ページに混入する note 公式・システム URLを除外するセット
    EXCLUDE_URLNAMES = {
        "note", "info", "terms", "signup", "login",
        "membership", "contest", "hashtag", "search",
        "category", "topics", "help-note", "pro", "premium",
    }

    def __init__(self, urlname: str, email: str):
        """
        urlname : 越智さんの note ID（例: "a0739635"）
        email   : note ログインに使うメールアドレス
        """
        self.urlname = urlname
        self.email   = email

    # ---- 資格情報管理 ----------------------------------------

    def get_password(self) -> str | None:
        """Windows 資格情報マネージャーからパスワードを取得する。未設定の場合は None を返す。"""
        try:
            import keyring
            return keyring.get_password(self.KEYRING_SERVICE, self.urlname)
        except Exception:
            return None

    def set_password(self, password: str) -> bool:
        """Windows 資格情報マネージャーにパスワードを保存する。成功で True を返す。"""
        try:
            import keyring
            keyring.set_password(self.KEYRING_SERVICE, self.urlname, password)
            return True
        except Exception:
            return False

    # ---- フォロー一覧取得 ------------------------------------

    def fetch_followings(self, headless: bool = True,
                         progress_callback=None) -> list[str]:
        """
        note.com にログインし、フォロー中作者の RSS URL リストを返す。
        戻り値 : ["https://note.com/{urlname}/rss", ...]
        例外   : ValueError（設定不足） / RuntimeError（ログイン失敗・0件取得）
        """
        import time
        from playwright.sync_api import sync_playwright

        password = self.get_password()
        if not password:
            raise ValueError(
                "noteパスワードが未設定です。\n"
                "Tab2「🔑 note認証設定」ボタンから登録してください。"
            )
        if not self.email:
            raise ValueError(
                "noteメールアドレスが未設定です。\n"
                "Tab2「🔑 note認証設定」ボタンから登録してください。"
            )

        if progress_callback:
            progress_callback("🔐 note.com にログイン中...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            try:
                # --- ログイン処理 ---
                page.goto("https://note.com/login")
                page.wait_for_load_state("domcontentloaded")
                time.sleep(1)
                page.locator('input[placeholder*="mail"]').fill(self.email)
                time.sleep(0.5)
                page.locator('input[type="password"]').fill(password)
                time.sleep(0.5)
                page.locator('button:has-text("ログイン")').click()
                try:
                    page.wait_for_url("https://note.com/", timeout=15000)
                except Exception:
                    raise RuntimeError(
                        "noteログインに失敗しました。\n"
                        "メールアドレスまたはパスワードを確認してください。"
                    )

                if progress_callback:
                    progress_callback("📋 フォロー一覧ページへ移動中...")

                # --- フォロー一覧ページへ ---
                page.goto(f"https://note.com/{self.urlname}/followings")
                page.wait_for_load_state("networkidle")
                time.sleep(2)

                # --- スクロールして全件を動的ロード ---
                prev_height = 0
                for scroll_idx in range(50):   # 最大50回スクロール（約1000人まで対応）
                    page.keyboard.press("End")
                    time.sleep(1.5)
                    current_height = page.evaluate("document.body.scrollHeight")
                    if current_height == prev_height:
                        break
                    prev_height = current_height
                    if progress_callback:
                        progress_callback(
                            f"📋 フォロー一覧読み込み中..."
                            f" (スクロール {scroll_idx + 1}回目)"
                        )

                # --- DOM からリンク一覧を抽出 ---
                # [v20260708_02_01修正] ページ全体からの無差別取得をやめ、
                # フォロー一覧本体（data-creator-list="true"）配下のみに限定する。
                # これにより「おすすめアカウント」等の誤混入を防ぐ。
                all_links: list[str] = page.evaluate(
                    "() => Array.from("
                    "document.querySelectorAll('ul[data-creator-list=\"true\"] a[href]')"
                    ").map(a => a.href)"
                )

            finally:
                browser.close()

        # --- フィルタリング ---
        exclude_full: set[str] = {f"https://note.com/{self.urlname}"}
        exclude_full |= {f"https://note.com/{u}" for u in self.EXCLUDE_URLNAMES}

        following_rss: list[str] = []
        seen: set[str] = set()
        for href in all_links:
            href = href.rstrip("/")
            if not href.startswith("https://note.com/"):
                continue
            path = href.replace("https://note.com/", "")
            # urlname のみのパス（サブパス・クエリ・フラグメント なし）
            if "/" in path or "#" in path or "?" in path or not path:
                continue
            if href in exclude_full:
                continue
            rss_url = f"{href}/rss"
            if rss_url not in seen:
                seen.add(rss_url)
                following_rss.append(rss_url)

        if len(following_rss) == 0:
            raise RuntimeError(
                "フォロー一覧が0件でした。\n"
                "noteのページ構造が変更された可能性があります。\n"
                "手動で followed_note_authors.txt を確認してください。"
            )
        return following_rss

    # ---- ファイル同期 ----------------------------------------

    def sync_to_file(self, filepath: str, mode: str = "merge",
                     headless: bool = True,
                     progress_callback=None) -> dict:
        """
        フォロー一覧を followed_note_authors.txt に同期する。
        mode="merge" : 未登録 URL のみ追記（既存エントリを保護）
        mode="full"  : API リストで完全上書き
        戻り値: {"added": int, "total": int, "backup_path": str}
        """
        new_urls = self.fetch_followings(
            headless=headless, progress_callback=progress_callback
        )

        # 既存ファイルの読み込み
        existing_urls: list[str] = []
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                existing_urls = [line.strip() for line in f if line.strip()]

        # バックアップ作成（既存エントリがある場合のみ）
        backup_path = ""
        if existing_urls:
            backup_path = filepath + ".bak"
            with open(backup_path, "w", encoding="utf-8") as f:
                for url in existing_urls:
                    f.write(url + "\n")

        # 同期ロジック
        existing_set = set(existing_urls)
        added = [u for u in new_urls if u not in existing_set]
        if mode == "merge":
            final_urls = existing_urls + added
        else:  # full
            final_urls = new_urls

        # ファイル書き込み
        with open(filepath, "w", encoding="utf-8") as f:
            for url in final_urls:
                f.write(url + "\n")

        return {
            "added":       len(added),
            "total":       len(final_urls),
            "backup_path": backup_path,
        }

# ============================================================
# AI要約クラス (Playwright搭載)
# ============================================================

class RSSSummarizer:
    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name
        self._configured = False
    
    def configure(self):
        if not self._configured and self.api_key:
            genai.configure(api_key=self.api_key)
            self._configured = True
            return True
        return self._configured


    def _fetch_web_content(self, page, url: str) -> str:
        try:
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_())
            # [v20260607_01_05修正] SPAサイトはload+2秒待機、非SPAはdomcontentloaded
            # networkidleは外部通信が途切れない場合に永久待機するため使用しない
            sel, exc, is_spa = "body", "", False
            for domain, cfg in SITE_CONFIG.items():
                if domain.lower() in url.lower():
                    sel, exc, is_spa = cfg["selector"], cfg["exclude"], cfg.get("is_spa", False)
                    break
            wait_until = "load" if is_spa else "domcontentloaded"
            page.goto(url, timeout=15000, wait_until=wait_until)
            if is_spa:
                page.wait_for_timeout(2000)

            if exc:
                page.evaluate(f'selector => {{ document.querySelectorAll(selector).forEach(el => el.remove()); }}', exc)

            text = page.locator(sel).first.inner_text()
            return f"【Web記事本文】\n{text[:15000]}"
        except Exception as e:
            return f"取得失敗: ({str(e)})"

    def summarize_article(self, page, article: dict) -> tuple:
        if not self.api_key: return self._error("APIキー未設定"), 0, 0
        try: self.configure()
        except Exception as e: return self._error(f"設定エラー: {e}"), 0, 0
        
        web_text = self._fetch_web_content(page, article['url'])
        # [v20260603_01_01追加] 本文文字数カウント（最大15,000字の参考値）
        # 取得成功時はヘッダー文字列を除いた純本文長、失敗時はNone
        article['char_count'] = (
            len(web_text) - len("【Web記事本文】\n")
            if web_text.startswith("【Web記事本文】")
            else None
        )

        try:
            page.wait_for_timeout(1500)
            meta = page.evaluate("""() => {
                let author = "", date = "", likes = "";
                let url = location.href;
                if (url.includes("note.com")) {
                    let aEl = document.querySelector('.o-noteArticleHeader__name a') || document.querySelector('.a-userProfile__name') || document.querySelector('.o-noteContentHeader__name a');
                    if (aEl) author = aEl.innerText;
                    let dEl = document.querySelector('time') || document.querySelector('.o-noteArticleHeader__date');
                    if (dEl) date = dEl.innerText;
                    let lEl = document.querySelector('.o-noteArticleHeader__likeCount') || document.querySelector('[data-v-like-count]') || document.querySelector('.a-iconAction__count') || document.querySelector('.o-noteLikeV3__count');
                    if (lEl) likes = lEl.innerText;
                } else if (url.includes("zenn.dev")) {
                    let aEl = document.querySelector('a[class*="ArticleHeader_userName"] div') || document.querySelector('a[class*="ArticleHeader_userName"]');
                    if (aEl) author = aEl.innerText;
                    let dEl = document.querySelector('span[class*="ArticleHeader_date"]') || document.querySelector('time');
                    if (dEl) date = dEl.innerText;
                    let lEl = document.querySelector('button[class*="ArticleAction_likeButton"] span');
                    if (lEl) likes = lEl.innerText;
                } else if (url.includes("qiita.com")) {
                    let aEl = document.querySelector('a[href^="/@"]');
                    if (aEl) author = aEl.innerText;
                    let dEl = document.querySelector('time')?.parentElement || document.querySelector('time');
                    if (dEl) date = dEl.innerText;
                    let lEls = Array.from(document.querySelectorAll('div, span')).filter(e => e.innerText && e.innerText.match(/^[0-9]+$/));
                    if (lEls.length > 0) likes = lEls[0].innerText; 
                }
                return {author: author, date: date, likes: likes};
            }""")
            
            if meta.get('author'): article['author'] = meta['author'].strip()
            if meta.get('date'): article['published_str'] = meta['date'].replace('\n', ' ').strip()
            if meta.get('likes'): article['likes'] = meta['likes'].strip()
        except:
            pass
        
        # [v20260508.03修正] Phase1：タイトル・要旨・キーワードのみ生成（結論・主なポイントはオンデマンドに後回し）
        prompt = f"""
        あなたは、記事や動画の作者の意図を十分くみとって、わかりやすく内容を読者に伝えることを専門としている要約のプロフェッショナルライターです。
        以下のWeb記事内容を日本語で要約し、必ず以下のJSONフォーマットで出力してください。
        高校生にでも理解できるように、専門的な用語は解説を入れるか、平易な言葉を併記してください。
        
        【記事情報】
        タイトル: {article['title']}
        概要: {article['summary']}
        
        {web_text}
        
        【JSON出力形式】
        {{
            "is_rss": true,
            "title": "記事にふさわしいタイトル",
            "summary": "全体の要旨（50文字程度。必要と判断された場合超えてもいい。）",
            "keywords": "キーワード1, キーワード2, キーワード3",
            "point_titles": ["ポイントのタイトル1", "ポイントのタイトル2", "ポイントのタイトル3"]
        }}
        """
        try:
            model = genai.GenerativeModel(self.model_name)
            res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            
            t_in = getattr(res.usage_metadata, 'prompt_token_count', 0) if hasattr(res, 'usage_metadata') else 0
            t_out = getattr(res.usage_metadata, 'candidates_token_count', 0) if hasattr(res, 'usage_metadata') else 0
            
            result = self._extract_json(res.text)
            if not result: return self._error("解析失敗"), t_in, t_out
            result['article_url'] = article['url']
            return result, t_in, t_out
        except Exception as e: return self._error(str(e)), 0, 0



    def summarize_detail_phase(self, article: dict, web_text: str) -> dict:
        """[v20260508.03追加] Phase2: 結論・主なポイントのオンデマンド生成"""
        if not self.api_key:
            return {'conclusion': 'エラー: APIキー未設定', 'main_points': []}
        try:
            self.configure()
        except Exception as e:
            return {'conclusion': f'エラー: {e}', 'main_points': []}

        prompt = f"""
        あなたは、記事や動画の作者の意図を十分くみとって、わかりやすく内容を読者に伝えることを専門としている要約のプロフェッショナルライターです。
        以下のWeb記事内容を日本語で分析し、必ず以下のJSONフォーマットで出力してください。
        高校生にでも理解できるように、専門的な用語は解説を入れるか、平易な言葉を併記してください。

        【記事情報】
        タイトル: {article.get('title', '')}
        概要: {article.get('summary', '')}

        {web_text}

        【指示】
        - conclusion: 全体の内容を俯瞰した結論を300文字程度でまとめてください。
        - main_points: 記事の主なポイントを最適な分類で3項目以上抽出してください。
          - point_title: 必ず「1. 」「2. 」のように数字とピリオドから始めるタイトル。
          - bullets: そのポイントを説明する箇条書き文を2〜3項目の配列で記載。
            各項目は100文字程度に収めてください。
            具体的なトピックス数が規定されている記事（TOP10など）は省略せず全て項目として扱う。

        【JSON出力形式】
        {{
            "conclusion": "結論（300文字程度）",
            "main_points": [
                {{
                    "point_title": "1. ポイントのタイトル",
                    "bullets": ["説明文1（100文字程度）", "説明文2（100文字程度）"]
                }}
            ]
        }}
        """
        
        try:
            model = genai.GenerativeModel(self.model_name)
            res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            result = self._extract_json(res.text)
            if not result:
                return {'conclusion': '解析失敗', 'main_points': []}
            return result
        except Exception as e:
            return {'conclusion': f'エラー: {e}', 'main_points': []}

    def summarize_multiple(self, articles: list, cb=None) -> tuple:
        results = {}
        total = len(articles)
        if total == 0: return {}, 0.0, 0.0
        
        done_count = [0]
        total_in = [0]
        total_out = [0]
        lock = threading.Lock()
        
        def worker(subset):
            if not subset: return
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                
                for a in subset:
                    url = a['url']
                    try:
                        res_data, t_in, t_out = self.summarize_article(page, a)
                        results[url] = res_data
                        with lock:
                            total_in[0] += t_in
                            total_out[0] += t_out
                    except Exception as e:
                        results[url] = self._error(str(e))
                    finally:
                        with lock:
                            done_count[0] += 1
                            if cb: cb(done_count[0], total, f"要約中... {done_count[0]}/{total}")
                browser.close()

        # [v20260607_01_01修正] threading.Thread/ThreadPoolExecutorを全廃
        # sync_playwright()はメインスレッド以外で動作不可のため
        # worker()をメインスレッドで直接順次実行する
        # 並列処理は行わず全記事を1ブロックで処理する
        worker(articles)
            
        cost_usd = (total_in[0] / 1_000_000 * 0.30) + (total_out[0] / 1_000_000 * 2.50)
        cost_jpy = cost_usd * 160
            
        return results, cost_usd, cost_jpy

    def _extract_json(self, text):
        try: data = json.loads(text)
        except:
            import re
            m = re.search(r'\{[\s\S]*\}', text)
            data = json.loads(m.group()) if m else None
        if isinstance(data, list) and len(data) > 0: return data[0]
        return data

    def _error(self, msg):
        return {'summary': f"エラー: {msg}", '_error': True}



# ============================================================
# [v20260508.03追加] オンデマンド要約用ローカルAPIサーバー
# ============================================================

def start_ondemand_api_server(summarizer: 'RSSSummarizer'):
    """
    [v20260508.03追加]
    HTMLから呼び出されるローカルFlask APIサーバーを別スレッドで起動する。
    起動済みの場合は何もしない。
    """
    global _ondemand_server_started
    if _ondemand_server_started:
        return
    _ondemand_server_started = True

    try:
        from flask import Flask, request, jsonify
        from flask_cors import CORS
    except ImportError:
        # flask-cors がない場合はインストールして再試行
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "flask", "flask-cors"], check=False)
        from flask import Flask, request, jsonify
        from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)  # ローカルHTMLファイルからのリクエストを許可

    @app.route('/detail', methods=['POST'])
    def detail():
        data = request.get_json(force=True)
        article_url  = data.get('url', '')
        article_title   = data.get('title', '')
        article_summary = data.get('summary', '')

        # Playwrightで本文を再取得
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                web_text = summarizer._fetch_web_content(page, article_url)
                browser.close()
        except Exception as e:
            web_text = f"本文取得失敗: {e}"

        article = {'title': article_title, 'summary': article_summary, 'url': article_url}
        result = summarizer.summarize_detail_phase(article, web_text)
        return jsonify(result)


    @app.route('/summarize', methods=['POST'])
    def summarize():
        """[v20260607_01_03追加] GUIモード用一括要約エンドポイント
        sync_playwright()をFlaskスレッド内で実行することでGUIスレッド制約を回避"""
        data = request.get_json(force=True)
        articles = data.get('articles', [])
        results = {}
        char_counts = {}
        total_in = 0
        total_out = 0
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                for a in articles:
                    try:
                        res_data, t_in, t_out = summarizer.summarize_article(page, a)
                        results[a['url']] = res_data
                        # [v20260607_01_06修正] char_countをレスポンスに含める
                        char_counts[a['url']] = a.get('char_count')
                        total_in += t_in
                        total_out += t_out
                    except Exception as e:
                        results[a['url']] = summarizer._error(str(e))
                browser.close()
        except Exception as e:
            for a in articles:
                if a['url'] not in results:
                    results[a['url']] = summarizer._error(str(e))
        cost_usd = (total_in / 1_000_000 * 0.30) + (total_out / 1_000_000 * 2.50)
        cost_jpy = cost_usd * 160
        return jsonify({'results': results, 'char_counts': char_counts, 'cost_usd': cost_usd, 'cost_jpy': cost_jpy})
    
    def run():
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)  # Flaskのログを抑制
        app.run(port=ONDEMAND_API_PORT, threaded=True, use_reloader=False)

    t = threading.Thread(target=run, daemon=True)
    t.start()


# ============================================================
# HTMLレポート生成
# ============================================================

class HTMLReportGenerator:
    def __init__(self):
        self.folder = Path(r"C:\Users\nx023836\Nexperia\My Private - Documents\Summary")
        self.folder.mkdir(parents=True, exist_ok=True)


    def generate_report(self, articles, summaries, cost_usd=0.0,
                        cost_jpy=0.0, summarizer=None, section_map=None):

        # [v20260508.03修正] オンデマンドAPIサーバーを起動（summarizerが渡された場合のみ）
        if summarizer is not None:
            start_ondemand_api_server(summarizer)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = self.folder / f"summary_RSS_{ts}.html"
        html = self._build_html(articles, summaries, cost_usd, cost_jpy, section_map)      
       # [v20260508.03修正] サロゲートペア文字や特殊文字を含む記事で発生するUnicodeEncodeErrorを回避
        html = html.encode('utf-8', errors='replace').decode('utf-8')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        return str(path)

    @staticmethod
    def _render_raw_title(a: dict) -> str:
        """
        [v20260508.03_02追加]
        カード下部の生タイトル表示用HTMLを生成する。
        英語タイトルの場合は日本語訳を青色・太字で先に表示し、
        元の英語タイトルは小さくグレーで下に併記する。
        """
        import html as html_lib
        raw = html_lib.escape(a.get('title', ''))
        title_ja = a.get('title_ja')  # None = 日本語記事 or 未翻訳
        if title_ja:
            safe_ja = html_lib.escape(title_ja)
            return (
                f'<span style="color:#1d4ed8; font-weight:bold;">🌐 {safe_ja}</span>'
                f'<br><span style="font-size:0.9em; color:#94a3b8;">{raw}</span>'
            )
        return raw


    def _card(self, a, s, index, src_class=""):
        # [v20260508.03修正] 結論・主なポイントはプレースホルダーとオンデマンドボタンに変更
        # 記事情報をJavaScriptからアクセスできるようにdata属性に埋め込む
        import html as html_lib
        safe_url     = html_lib.escape(a['url'],     quote=True)
        safe_title   = html_lib.escape(a['title'],   quote=True)
        safe_summary = html_lib.escape(a.get('summary', ''), quote=True)

        # [v20260603_01_01追加] 文字数表示文字列の生成
        char_count_val = a.get('char_count')
        char_count_str = f"{char_count_val:,}字" if char_count_val is not None else '取得不可'

        # [v20260607_01_02追加] 概要セクション：point_titlesを・付き箇条書きで表示
        # 条件①：配列チェック必須（Gemini解析失敗時はempty listにフォールバック）
        pt = s.get("point_titles", [])
        if not isinstance(pt, list):
            pt = []
        if pt:
            point_titles_html = "".join(
                f'<div style="display:flex;gap:6px;margin:4px 0;">'
                f'<span style="color:#4f72f0;flex-shrink:0;">・</span>'
                f'<span style="color:#374151;">{html_lib.escape(str(t))}</span>'
                f'</div>'
                for t in pt
            )
        else:
            point_titles_html = '<span style="color:#94a3b8;">（生成中に取得できませんでした）</span>'

        return f'''<div class="thread-card {src_class}" id="card-{index}" data-index="{index}"
                data-url="{safe_url}"
                data-title="{safe_title}"
                data-summary="{safe_summary}">
            <div class="t-head">
                <div class="t-title">📰 <span id="t-txt-{index}">{s.get("title", a['title'])}</span></div>
                <div style="display:flex; align-items:center;">
                    <button class="speak-btn" onclick="toggleSpeech({index})">\U0001F50A 読み上げ</button>
                 <a href="{a['url']}" target="_blank" class="open-link">🌐 記事表示</a>
                </div>
            </div>
            <div style="background:#f8fafc; padding:8px 15px; font-size:0.85em; color:#475569; border-bottom:1px solid #e2e8f0; display:flex; flex-wrap:wrap; gap:15px;">
                <span><b>ソース:</b> {a['source']}</span>
                <span><b>カテゴリ:</b> {a['categories_str']}</span>
                <span><b>作者:</b> {a['author']}</span>
                <span><b>いいね:</b> {a.get('likes', '0')}</span>
                <span><b>文字数:</b> {char_count_str}</span>
            </div>
            <div class="t-body">
                <div class="section"><div class="sec-title">📝 要旨</div><div class="sum-box" id="s-txt-{index}">{s.get("summary","")}</div></div>
                <div class="section"><div class="sec-title">🔑 キーワード</div><div style="padding:10px;" id="k-txt-{index}">{s.get("keywords","")}</div></div>
                <div class="section"><div class="sec-title">📋 概要</div><div class="sum-box" id="pt-txt-{index}">{point_titles_html}</div></div>
                <div class="section" id="detail-section-{index}">
                    <div class="sec-title">💡 主なポイント</div>
                    <div id="detail-content-{index}" style="display:none;">
                        <div id="points-{index}" class="points-wrapper open"></div>
                    </div>
                    <button class="detail-btn" id="detail-btn-{index}" onclick="fetchDetail({index})">\U0001F50D 主なポイントを生成</button>
                </div>
            </div>
            <div style="background:#f8fafc; padding:8px 15px; font-size:0.85em; color:#475569; border-top:1px solid #e2e8f0;">
                <b>日付:</b> {a.get('published_str', '')}<br>
                {self._render_raw_title(a)}
            </div></div>'''

    def _build_html(self, articles, summaries, cost_usd=0.0,
                    cost_jpy=0.0, section_map=None):
        total_a = len(articles)

        # [v20260527_02_01a] セクション境界インデックス計算
        _sm          = section_map or {}
        _n_tab2      = _sm.get("tab2", 0)
        _n_tab1      = _sm.get("tab1", 0)
        _n_tab3      = _sm.get("tab3", 0)
        _boundary_t1 = _n_tab2
        _boundary_t3 = _n_tab2 + _n_tab1

        def _section_header(tab_class, icon, label, count):
            return (
                f'<div class="section-header {tab_class}">'
                f'{icon}&nbsp;&nbsp;{label}'
                f'<span style="margin-left:auto;font-size:0.9rem;">{count}件</span>'
                f'</div>'
            )

        def _card_src_class(idx):
            # [v20260527_02_01a] section_map未指定（GUI手動実行）時はカラーバーなし
            if _n_tab2 == 0 and _n_tab1 == 0 and _n_tab3 == 0:
                return ""
            if idx < _boundary_t1:
                return "src-tab2"
            if idx < _boundary_t3:
                return "src-tab1"
            return "src-tab3"

        # [v20260527_02_01a] カード生成ループ（セクションヘッダー挿入・カラーバー付与）
        cards = []
        for i, a in enumerate(articles):
            card_number = i + 1
            if i == 0 and _n_tab2 > 0:
                cards.append(_section_header("tab2", "👤", "フォローNote", _n_tab2))
            elif i == _boundary_t1 and _n_tab1 > 0:
                cards.append(_section_header("tab1", "🔎", "キーワード探索", _n_tab1))
            elif i == _boundary_t3 and _n_tab3 > 0:
                cards.append(_section_header("tab3", "🤖", "AI最先端フィード", _n_tab3))
            src_class = _card_src_class(i)
            cards.append(self._card(a, summaries.get(a['url'], {}), card_number, src_class))

        cost_html = ""
        if cost_usd > 0:
            cost_html = f'<div style="text-align:center; padding: 10px; margin-bottom: 20px; background-color: #e0f2fe; border: 1px solid #bae6fd; border-radius: 5px; font-weight: bold; color: #0369a1;">💰 推定APIコスト (gemini-2.5-flash): ${cost_usd:.4f} (約 {cost_jpy:.2f} 円)</div>'
        return rf"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RSS Topic Organizer ver{VERSION}</title>
<style>
:root {{ --primary:#2563eb; --bg:#f3f4f6; }}
body {{ font-family:'Segoe UI',sans-serif; background:var(--bg); color:#333; margin:0; padding:20px; }}
.container {{ max-width:1200px; margin:0 auto; padding-bottom: 80px; }}
.header {{ background:linear-gradient(135deg,var(--primary),#1d4ed8); color:#fff; padding:20px; border-radius:10px; margin-bottom:20px; scroll-margin-top: 20px; }}
.stat-card {{ background:#fff; padding:15px; border-radius:8px; text-align:center; box-shadow:0 1px 3px rgba(0,0,0,0.1); display:inline-block; width:200px; margin-right:10px; }}
.stat-val {{ font-size:24px; font-weight:bold; color:var(--primary); }}
.header-btn {{ background: rgba(255,255,255,0.2); border: 1px solid #fff; color: #fff; padding: 5px 15px; border-radius: 5px; cursor: pointer; margin-left: 10px; font-size: 0.9em; transition: 0.2s; }}
.header-btn:hover {{ background: rgba(255,255,255,0.4); }}
.header-actions {{ display:flex; justify-content:space-between; align-items:flex-end; }}
.thread-card {{ background:#fff; margin-bottom:20px; border-radius:10px; border-top:4px solid var(--primary); box-shadow:0 1px 3px rgba(0,0,0,0.1); overflow:hidden; scroll-margin-top: 20px; transition: border-color 0.3s, box-shadow 0.3s; }}
.active-card {{ border: 2px solid var(--primary); box-shadow: 0 0 10px rgba(37, 99, 235, 0.3); }}
.t-head {{ padding:15px; border-bottom:1px solid #eee; display:flex; justify-content:space-between; align-items:center; }}
.t-title {{ font-weight:bold; font-size:18px; flex:1; }}
.t-body {{ padding:20px; }}
.section {{ margin-bottom:20px; }}
.sec-title {{ font-weight:bold; border-bottom:2px solid #eee; margin-bottom:10px; color:#555; }}
.sum-box {{ background:#f8fafc; padding:15px; border-radius:6px; }}
.open-link {{ color:#2563eb; text-decoration:none; margin-left:10px; font-size:0.8em; font-weight:bold; padding: 5px 10px; background: #e0e7ff; border-radius: 5px; }}
.points-btn {{ width:100%; background:#737be4; color:white; border:none; padding:10px; border-radius:8px; cursor:pointer; margin-bottom:10px; }}
.points-wrapper {{ max-height:0; overflow:hidden; transition: max-height 0.4s ease-out; }}
.points-wrapper.open {{ max-height: 2000px; }}
.speak-btn {{ background: #10b981; color: white; border: none; padding: 5px 12px; border-radius: 5px; cursor: pointer; font-size: 0.8em; font-weight: bold; margin-left: 10px; }}
.speak-btn.playing {{ background: #ef4444; }}
.nav-fab-container {{ position: fixed; top: 50%; right: 20px; transform: translateY(-50%); display: flex; flex-direction: column; gap: 15px; z-index: 1000; pointer-events: none; }}
.nav-fab-btn {{ pointer-events: auto; width: 56px; height: 56px; border-radius: 50%; background-color: rgba(0, 0, 0, 0.05); border: 1px solid rgba(0, 0, 0, 0.05); color: var(--primary); font-size: 32px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }}
.nav-fab-btn:active {{ background-color: rgba(37, 99, 235, 0.2); transform: scale(0.95); }}
.nav-fab-btn.disabled {{ color: rgba(150, 150, 150, 0.5); cursor: default; pointer-events: none; }}
.nav-indicator {{ pointer-events: auto; background: rgba(0, 0, 0, 0.4); color: white; padding: 2px 8px; border-radius: 10px; text-align: center; font-size: 0.8rem; margin-bottom: 5px; font-weight: bold; }}
.nav-fab-btn.stop-speech {{ background-color: #ef4444; color: white; display: none; }}
.nav-fab-btn.stop-speech.show {{ display: flex; }}
.nav-fab-btn.speed-btn {{ font-size: 16px; font-weight: bold; }}

@media (max-width: 600px) {{
    body {{ font-size: 16px; padding: 10px; }}
    .container {{ padding-bottom: 100px; }}
    .header-actions {{ flex-direction: column; align-items: stretch; gap: 15px; }}
    .stats-container {{ display: flex; justify-content: space-between; width: 100%; gap: 5px; }}
    .stat-card {{ width: 32%; padding: 10px 2px; margin-right: 0; box-sizing: border-box; }}
    .stat-val {{ font-size: 18px; }}
    .stat-card div:last-child {{ font-size: 11px; }}
    .thread-card {{ margin-bottom: 15px; scroll-margin-top: 70px; }}
    .t-head {{ padding: 12px; flex-direction: column; gap: 8px; }}
    .t-title {{ font-size: 1.15em; line-height: 1.4; }}
    .nav-fab-btn {{ width: 60px; height: 60px; font-size: 28px; opacity: unset; }}
    .nav-fab-container {{ right: 10px; gap: 10px; }}
    .nav-indicator {{ font-size: 0.95rem; padding: 4px 8px; }}
}}

/* 追従スクロール時の上部余白確保 */
[id^="t-txt-"] {{ display: inline-block; scroll-margin-top: 90px; }}
[id^="s-txt-"], [id^="c-txt-"], [id^="points-"] {{ scroll-margin-top: 90px; }}
/* [v20260508.03追加] オンデマンド要約ボタン */
.detail-btn {{ width:100%; background:#f59e0b; color:white; border:none; padding:10px; border-radius:8px; cursor:pointer; margin-top:8px; font-weight:bold; font-size:0.9em; }}
.detail-btn:hover {{ background:#d97706; }}
.detail-btn:disabled {{ background:#d1d5db; color:#9ca3af; cursor:not-allowed; }}
.detail-btn.done {{ background:#10b981; }}
/* [v20260527_02_01追加] セクションヘッダー */
        .section-header {{
            display: flex;
            align-items: center;
            padding: 14px 24px;
            margin: 32px 0 16px 0;
            border-radius: 10px;
            font-size: 1.1rem;
            font-weight: bold;
            letter-spacing: 0.05em;
        }}
        .section-header.tab2 {{
            background: linear-gradient(90deg, #1e3a5f 0%, #1a1a2e 100%);
            border-left: 5px solid #3b82f6;
            color: #93c5fd;
        }}
        .section-header.tab1 {{
            background: linear-gradient(90deg, #14532d 0%, #1a1a2e 100%);
            border-left: 5px solid #22c55e;
            color: #86efac;
        }}
        .section-header.tab3 {{
            background: linear-gradient(90deg, #3b0764 0%, #1a1a2e 100%);
            border-left: 5px solid #a855f7;
            color: #d8b4fe;
        }}
        /* [v20260527_02_01追加] カードカラーバー */
        .thread-card.src-tab2 {{ border-left: 4px solid #3b82f6; }}
        .thread-card.src-tab1 {{ border-left: 4px solid #22c55e; }}
        .thread-card.src-tab3 {{ border-left: 4px solid #a855f7; }}
</style>
<script>
const ONDEMAND_PORT = {ONDEMAND_API_PORT};
let currentIndex = 0; 
const totalCount = {total_a}; 
let isAutoScrolling = false;
let currentUttr = null;
let isPlayingContinuous = false; 
let currentPart = 'title'; 
let isSkipMode = true; 
let isTempNormal = false; 

let availableVoices = [];
if (window.speechSynthesis) {{
    availableVoices = window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {{
        availableVoices = window.speechSynthesis.getVoices();
    }};
}}

const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
let currentSpeedRate = isIOS ? 1.5 : 3.0; 
const speedOptions = [1.5, 2.0, 2.5, 3.0]; 

function updateSkipBtnUI() {{
    const btn = document.getElementById('btnSkip');
    if (!btn) return;
    if (isSkipMode) {{
        btn.innerText = "⏩";
        btn.style.backgroundColor = "";
        btn.style.color = "";
    }} else {{
        btn.innerText = "▶️";
        if (!isTempNormal) {{
            btn.style.backgroundColor = "var(--primary)";
            btn.style.color = "white";
        }} else {{
            btn.style.backgroundColor = "";
            btn.style.color = "";
        }}
    }}
}}

function changeSpeed() {{
    let idx = speedOptions.indexOf(currentSpeedRate);
    idx = (idx + 1) % speedOptions.length;
    currentSpeedRate = speedOptions[idx];
    const btn = document.getElementById('btnSpeed');
    if (btn) btn.innerText = currentSpeedRate.toFixed(1) + "x";

    if (currentUttr && window.speechSynthesis.speaking) {{
        const activeIdx = currentUttr.articleIdx;
        const wasContinuous = isPlayingContinuous;
        const resumePart = currentPart;
        window.speechSynthesis.cancel();
        currentUttr = null; 
        setTimeout(() => {{
            isPlayingContinuous = wasContinuous;
            playPart(activeIdx, resumePart);
        }}, 300);
    }}
}}

function toggleSpeech(idx) {{
    if (window.speechSynthesis.speaking && currentUttr && currentUttr.articleIdx === idx) {{
        isPlayingContinuous = false;
        window.speechSynthesis.cancel();
        updateBtns(null);
        return;
    }}
    isPlayingContinuous = true; 
    playPart(idx, 'title');
}}

function playPart(idx, part) {{
    window.speechSynthesis.cancel();
    currentPart = part;
    let txt = "";
    let targetId = "";
    
    if (part === 'title') {{
        txt = document.getElementById('t-txt-'+idx).innerText;
        targetId = 't-txt-'+idx;
    }} else if (part === 'summary') {{
        txt = document.getElementById('s-txt-'+idx).innerText;
        targetId = 's-txt-'+idx;
    }} else if (part === 'conclusion') {{
        txt = document.getElementById('c-txt-'+idx).innerText;
        targetId = 'c-txt-'+idx;
    }} else if (part === 'points') {{
        const w = document.getElementById('points-'+idx);
        if (w) {{ txt = w.innerText; targetId = 'points-'+idx; }}
    }}
    
    if (!txt) {{
        moveToNextCard(idx);
        return;
    }}
    
    const targetEl = document.getElementById(targetId);
    if (targetEl) targetEl.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    
    const ut = new SpeechSynthesisUtterance(txt);
    ut.lang = 'ja-JP'; 
    ut.rate = currentSpeedRate; 
    ut.articleIdx = idx;
    
    if (availableVoices.length === 0) {{
        availableVoices = window.speechSynthesis.getVoices();
    }}
    const jaVoices = availableVoices.filter(v => v.lang.includes('ja'));
    if (jaVoices.length > 0) {{
        let bestVoice = jaVoices.find(v => v.name.toLowerCase().includes('siri') && v.name.includes('2'));
        if (!bestVoice) bestVoice = jaVoices.find(v => v.name.toLowerCase().includes('siri'));
        if (!bestVoice) bestVoice = jaVoices.find(v => v.name.includes('Premium') || v.name.includes('Enhanced'));
        
        if (bestVoice) {{
            ut.voice = bestVoice;
        }} else {{
            ut.voice = jaVoices[jaVoices.length - 1]; 
        }}
    }}
    
    ut.onend = () => {{
        updateBtns(null);
        if (!isPlayingContinuous) return;
        
        if (part === 'title') {{
            setTimeout(() => playPart(idx, 'summary'), 100);
        }} else if (part === 'summary') {{
            if (isSkipMode) {{
                moveToNextCard(idx);
            }} else {{
                setTimeout(() => playPart(idx, 'conclusion'), 100);
            }}
        }} else if (part === 'conclusion') {{
            const w = document.getElementById('points-'+idx);
            if (w && w.classList.contains('open')) {{
                setTimeout(() => playPart(idx, 'points'), 100);
            }} else {{
                moveToNextCard(idx);
            }}
        }} else if (part === 'points') {{
            moveToNextCard(idx);
        }}
    }};
    ut.onerror = () => {{ updateBtns(null); isPlayingContinuous = false; }};
    
    currentUttr = ut;
    window.speechSynthesis.speak(ut);
    updateBtns(idx);
}}

function moveToNextCard(idx) {{
    if (isTempNormal) {{
        isSkipMode = true;
        isTempNormal = false;
        updateSkipBtnUI();
    }}
    if (isPlayingContinuous && idx < totalCount) {{
        const nextIdx = idx + 1;
        scrollToCard(nextIdx); 
        setTimeout(() => playPart(nextIdx, 'title'), 600);
    }} else {{
        isPlayingContinuous = false; 
        updateBtns(null);
    }}
}}

function stopAllSpeech() {{
    isPlayingContinuous = false;
    window.speechSynthesis.cancel();
    updateBtns(null);
}}

function updateBtns(playingIdx) {{
    document.querySelectorAll('.speak-btn').forEach(b => {{
        const i = parseInt(b.getAttribute('onclick').match(/\d+/)[0]);
        if(i === playingIdx) {{
            b.innerText = "⏹ 停止"; b.classList.add('playing');
        }} else {{
            b.innerText = "🔊 読み上げ"; b.classList.remove('playing');
        }}
    }});
    
    const globalStop = document.getElementById('btnStopSpeech');
    if (globalStop) {{
        if (playingIdx !== null) {{
            globalStop.classList.add('show');
        }} else if (!isPlayingContinuous) {{
            globalStop.classList.remove('show');
        }}
    }}
}}

function updateNavState() {{
    const btnPrev = document.getElementById('btnPrev'); 
    const btnNext = document.getElementById('btnNext');
    if(btnPrev) btnPrev.classList.toggle('disabled', currentIndex <= 0);
    if(btnNext) btnNext.classList.toggle('disabled', currentIndex >= totalCount);
    const indicator = document.getElementById('navIndicator');
    if(indicator) {{ indicator.textContent = currentIndex === 0 ? "Top" : currentIndex + " / " + totalCount; }}
    document.querySelectorAll('.thread-card').forEach(c => c.classList.remove('active-card'));
    if (currentIndex > 0) {{ 
        const activeCard = document.getElementById('card-' + currentIndex); 
        if (activeCard) activeCard.classList.add('active-card'); 
    }}
}}

function togglePoints(btn, idx) {{
    const w = document.getElementById('points-'+idx);
    const isOpen = w.classList.toggle('open');
    btn.innerText = isOpen ? "主なポイントを隠す" : "主なポイントを表示";
}}

// [v20260508.03追加] オンデマンド要約: 結論・主なポイントをローカルAPIから取得して表示
async function fetchDetail(idx) {{
    const card = document.getElementById('card-' + idx);
    const btn  = document.getElementById('detail-btn-' + idx);
    if (!card || !btn) return;

    const url     = card.dataset.url;
    const title   = card.dataset.title;
    const summary = card.dataset.summary;

    btn.disabled = true;
    btn.innerText = '⏳ AIがポイントを生成中...';

    try {{
        const res = await fetch(`http://127.0.0.1:${{ONDEMAND_PORT}}/detail`, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{ url, title, summary }})
        }});
        if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
        const data = await res.json();

        // [v20260607_01_02修正] conclusion完全非表示・main_pointsのみ展開
        // c-txt-{{idx}}はHTML上に存在しないため操作しない（条件②対応）
        const pEl = document.getElementById('points-' + idx);

        // [v20260529_01_01] YouTube要約スタイル: 色付きタイトル＋・付き箇条書き
        if (pEl && data.main_points && data.main_points.length > 0) {{
            pEl.innerHTML = data.main_points.map(p => {{
                const title = p.point_title || '';
                // bullets配列対応（旧descriptionフォールバックあり）
                const bullets = Array.isArray(p.bullets)
                    ? p.bullets
                    : (p.description ? [p.description] : []);
                const bulletHtml = bullets.map(b =>
                    `<div style="display:flex;gap:6px;margin:4px 0;">` +
                    `<span style="color:#4f72f0;flex-shrink:0;">・</span>` +
                    `<span style="color:#374151;">${{b}}</span>` +
                    `</div>`
                ).join('');
                return (
                    `<div style="margin-bottom:14px;">` +
                    `<div style="color:#4f72f0;font-weight:bold;font-size:0.97rem;` +
                    `margin-bottom:6px;">` +
                    `${{title}}</div>` +
                    `${{bulletHtml}}` +
                    `</div>`
                );
            }}).join('');
        }}

        // プレースホルダーを隠してコンテンツを表示
        const placeholder = document.getElementById('detail-placeholder-' + idx);
        const content     = document.getElementById('detail-content-' + idx);
        if (placeholder) placeholder.style.display = 'none';
        if (content)     content.style.display = 'block';

        btn.innerText = '✅ 生成済み';
        btn.classList.add('done');

    }} catch(e) {{
        btn.disabled = false;
        btn.innerText = '⚠️ エラー（再試行）';
        console.error('fetchDetail error:', e);
    }}
}}

function toggleAllPoints(show) {{
    const wrappers = document.querySelectorAll('.points-wrapper');
    const btns = document.querySelectorAll('.points-btn');
    wrappers.forEach(w => w.classList.toggle('open', show));
    btns.forEach(b => b.innerText = show ? "主なポイントを隠す" : "主なポイントを表示");
}}

function scrollToCard(index) {{
    if (index < 0 || index > totalCount || isAutoScrolling) return;
    isAutoScrolling = true;
    if (index === 0) {{ window.scrollTo({{ top: 0, behavior: 'smooth' }}); }} 
    else {{ 
        const target = document.getElementById('card-' + index); 
        if (target) {{ target.scrollIntoView({{ behavior: 'smooth', block: 'start' }}); }} 
    }}
    currentIndex = index; updateNavState(); 
    setTimeout(() => {{ isAutoScrolling = false; }}, 200);
}}

function navWithSpeech(targetIdx) {{
    if (targetIdx < 0 || targetIdx > totalCount) return;
    const wasPlaying = isPlayingContinuous || (window.speechSynthesis.speaking && currentUttr !== null);
    if (wasPlaying) {{
        isPlayingContinuous = false;
        window.speechSynthesis.cancel();
    }}
    scrollToCard(targetIdx);
    if (wasPlaying && targetIdx > 0) {{
        setTimeout(() => {{
            isPlayingContinuous = true;
            playPart(targetIdx, 'title');
        }}, 600);
    }}
}}

function scrollToNext() {{ 
    let baseIdx = ((isPlayingContinuous || window.speechSynthesis.speaking) && currentUttr !== null) ? currentUttr.articleIdx : currentIndex;
    navWithSpeech(baseIdx + 1); 
}}
function scrollToPrev() {{ 
    let baseIdx = ((isPlayingContinuous || window.speechSynthesis.speaking) && currentUttr !== null) ? currentUttr.articleIdx : currentIndex;
    navWithSpeech(baseIdx - 1); 
}}

document.addEventListener('DOMContentLoaded', function() {{
    updateNavState();
    updateSkipBtnUI();
    const btnSkip = document.getElementById('btnSkip');
    if (btnSkip) {{
        let skipBtnPressed = false;
        let skipBtnTimer = null;
        let ignoreNextUp = false;

        btnSkip.addEventListener('pointerdown', (e) => {{
            if (e.button !== 0 && e.pointerType === 'mouse') return;
            skipBtnPressed = true;
            ignoreNextUp = false;
            if (isSkipMode) {{
                skipBtnTimer = setTimeout(() => {{
                    if (skipBtnPressed) {{
                        isSkipMode = false;
                        isTempNormal = false;
                        updateSkipBtnUI();
                        ignoreNextUp = true;
                    }}
                }}, 500);
            }}
        }});

        btnSkip.addEventListener('pointerup', (e) => {{
            if (!skipBtnPressed) return;
            skipBtnPressed = false;
            if (skipBtnTimer) clearTimeout(skipBtnTimer);
            if (!ignoreNextUp) {{
                if (isSkipMode) {{
                    isSkipMode = false;
                    isTempNormal = true;
                }} else {{
                    isSkipMode = true;
                    isTempNormal = false;
                }}
                updateSkipBtnUI();
            }}
            ignoreNextUp = false;
        }});

        btnSkip.addEventListener('pointerleave', (e) => {{ skipBtnPressed = false; if (skipBtnTimer) clearTimeout(skipBtnTimer); }});
        btnSkip.addEventListener('pointercancel', (e) => {{ skipBtnPressed = false; if (skipBtnTimer) clearTimeout(skipBtnTimer); }});
    }}

    const btnSpeed = document.getElementById('btnSpeed');
    if (btnSpeed) btnSpeed.innerText = currentSpeedRate.toFixed(1) + "x";
    
    const observer = new IntersectionObserver((entries) => {{
        if (isAutoScrolling) return;
        let visibleEntries = entries.filter(e => e.isIntersecting);
        if (visibleEntries.length > 0) {{
            const entry = visibleEntries[0];
            const index = parseInt(entry.target.getAttribute('data-index'));
            setTimeout(() => {{ 
                if (!isAutoScrolling) {{ 
                    const header = document.getElementById('top-header');
                    if (header && header.getBoundingClientRect().top >= -100) {{ 
                        currentIndex = 0; 
                    }} else {{ 
                        currentIndex = index; 
                    }} 
                    updateNavState(); 
                }} 
            }}, 200);
        }}
    }}, {{ threshold: 0.1, rootMargin: "-40% 0px -40% 0px" }});
    const header = document.getElementById('top-header'); 
    if(header) observer.observe(header);
    document.querySelectorAll('.thread-card').forEach(card => observer.observe(card));
}});
</script>
</head><body>
<div class="container">
    <div id="top-header" class="header" data-index="0">
        <h1>📰 RSS Topic Organizer ver{VERSION}</h1>
        <div>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>
    
    {cost_html}
    
    <div class="header-actions">
        <div class="stats-container">
            <div class="stat-card" style="width: auto; padding: 15px 30px;">
                <div class="stat-val">{total_a}</div><div>Collected Articles</div>
            </div>
            <div style="display: flex; align-items: center;">
                <button class="header-btn" onclick="toggleAllPoints(true)">すべて表示</button>
                <button class="header-btn" onclick="toggleAllPoints(false)">すべて隠す</button>
            </div>
        </div>
    </div>
    <br>
    
    {''.join(cards)}
</div>

<div class="nav-fab-container">
    <div id="navIndicator" class="nav-indicator">Top</div>
    <button id="btnSkip" class="nav-fab-btn" title="スキップモード切替（長押しで永続通常モード）" style="font-size: 24px; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; touch-action: manipulation;" oncontextmenu="return false;">⏩</button>
    <button onclick="changeSpeed()" class="nav-fab-btn speed-btn" id="btnSpeed" title="読み上げ速度変更">3.0x</button>
    <button onclick="scrollToPrev()" class="nav-fab-btn" id="btnPrev">▲</button>
    <button onclick="scrollToNext()" class="nav-fab-btn" id="btnNext">▼</button>
    <button onclick="stopAllSpeech()" class="nav-fab-btn stop-speech" id="btnStopSpeech" title="読み上げ全停止">⏹</button>
</div>
</body></html>"""


# ============================================================
# GUI クラス ＆ ステルス自動実行
# ============================================================

class RSSManagerGUI:
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"RSS Topics Organizer ver{VERSION}")
        self.root.geometry("1000x800")
        
        self.config = load_config()
        self.feed_manager = RSSFeedManager()
        self.summarizer = RSSSummarizer(self.config.get("gemini_api_key", ""), self.config.get("gemini_model", "gemini-2.5-flash"))
        self.reporter = HTMLReportGenerator()
        
        self.articles = []
        self.selected = set()
        self.last_recommended_urls = set()
        self.last_recommended_iids = [] # 追加: 絞り込み表示用のIID記憶
        
        self.var_display_mode = tk.StringVar(value="all")
        
        self.recommend_config = self._load_recommend_config()
        if self.config.get("gemini_api_key"):
            genai.configure(api_key=self.config.get("gemini_api_key"))
            
        self._ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        # [v20260508.03_02追加] 起動時に翻訳ライブラリの状態をステータスバーに表示
        if _TRANSLATE_AVAILABLE:
            self.root.after(500, lambda: self.lbl_stat.config(
                text=f"Ready (ver{VERSION}) | 🌐 タイトル自動翻訳: 有効"
            ))
        else:
            self.root.after(500, lambda: self.lbl_stat.config(
                text=f"Ready (ver{VERSION}) | ⚠️ 翻訳機能無効 (未インストール: pip install deep-translator)"
            ))

    def _load_recommend_config(self):
        default_config = {"threshold": 0.65, "phrases": ["具体的な失敗と教訓", "ツールの比較と検証"], "negative_phrases": []}
        if os.path.exists(RECOMMEND_CONFIG_FILE):
            try:
                with open(RECOMMEND_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    default_config["threshold"] = loaded.get("threshold", 0.65)
                    default_config["phrases"] = loaded.get("phrases", default_config["phrases"])
                    default_config["negative_phrases"] = loaded.get("negative_phrases", [])
            except: pass
        return default_config

    def _save_recommend_config(self):
        if os.path.exists(RECOMMEND_CONFIG_FILE):
            try:
                with open(RECOMMEND_CONFIG_FILE, 'r', encoding='utf-8') as src:
                    content = src.read()
                with open(RECOMMEND_CONFIG_FILE + ".bak", 'w', encoding='utf-8') as dst:
                    dst.write(content)
            except Exception as e:
                print(f"Backup failed: {e}")
                
        with open(RECOMMEND_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.recommend_config, f, ensure_ascii=False, indent=4)

    def _ui(self):
        menu = tk.Menu(self.root)
        self.root.config(menu=menu)
        sm = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="設定", menu=sm)
        sm.add_command(label="APIキー", command=self._set_api)

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # --- 取得入口タブ（キーワード探索 / フォローnote） ---
        tab_notebook = ttk.Notebook(main)
        tab_notebook.pack(fill=tk.X, pady=(0, 5))

        tab_kw = ttk.Frame(tab_notebook)
        tab_follow = ttk.Frame(tab_notebook)
        tab_ai = ttk.Frame(tab_notebook)  # [v20260508.02追加]
        tab_notebook.add(tab_kw, text="🔎 キーワード探索")
        tab_notebook.add(tab_follow, text="👤 フォローnote")
        tab_notebook.add(tab_ai, text="🤖 AI最先端フィード")  # [v20260508.02追加]

        self._build_keyword_tab(tab_kw)
        self._build_followed_note_tab(tab_follow)
        self._build_ai_feed_tab(tab_ai)  # [v20260508.02追加]

        # --- 共通フィルタ・表示モード行 ---
        hf = ttk.Frame(main)
        hf.pack(fill=tk.X, pady=(0, 5))

        self.var_filter_all = tk.BooleanVar(value=True)
        self.var_filter_note = tk.BooleanVar(value=True)
        self.var_filter_zenn = tk.BooleanVar(value=True)
        self.var_filter_qiita = tk.BooleanVar(value=True)
        self.var_filter_ai_feed = tk.BooleanVar(value=True)  # [v20260508.02追加]

        cf = ttk.Frame(hf)
        cf.pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(cf, text="All", variable=self.var_filter_all, command=self._on_filter_all_change).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(cf, text="note", variable=self.var_filter_note, command=self._on_filter_source_change).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(cf, text="Zenn", variable=self.var_filter_zenn, command=self._on_filter_source_change).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(cf, text="Qiita", variable=self.var_filter_qiita, command=self._on_filter_source_change).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(cf, text="🤖AIフィード", variable=self.var_filter_ai_feed, command=self._on_filter_source_change).pack(side=tk.LEFT, padx=2)  # [v20260508.02追加]

        df = ttk.Frame(hf)
        df.pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(df, text="◉すべて", variable=self.var_display_mode, value="all", command=self._update_list).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(df, text="🌟おすすめ", variable=self.var_display_mode, value="recommended", command=self._update_list).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(df, text="☑選択済", variable=self.var_display_mode, value="selected", command=self._update_list).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(df, text="☐未選択", variable=self.var_display_mode, value="unselected", command=self._update_list).pack(side=tk.LEFT, padx=2)

        sf = ttk.Frame(hf)
        sf.pack(side=tk.LEFT, padx=15)
        self.lbl_counts = ttk.Label(sf, text="note: 0 | Zenn: 0 | Qiita: 0 (Total: 0)", font=("", 9))
        self.lbl_counts.pack(anchor="w")
        self.lbl_sel_count = ttk.Label(sf, text="0 件選択中", font=("", 9, "bold"), foreground="#2563eb")
        self.lbl_sel_count.pack(anchor="w")

        # --- リコメンドフレーズ管理ボタン ---
        pf = ttk.Frame(main)
        pf.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(pf, text="⚙️ リコメンドフレーズ管理（抽出・除外）", command=self._open_phrase_manager).pack(side=tk.LEFT)

        # --- 共通記事一覧 ---
        lf = ttk.LabelFrame(main, text="📋 抽出記事一覧", padding=5)
        lf.pack(fill=tk.BOTH, expand=True)

        cols = ("sel", "src", "cat", "title", "author", "date")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings")
        self.tree.tag_configure("checked", background="#b3d9ff")
        # [v20260508.03_02追加] 翻訳済み英語タイトルを青色で表示
        self.tree.tag_configure("translated", foreground="#1d4ed8")

        self.tree.heading("sel", text="✓", command=lambda: self._sort_tree("sel", False)); self.tree.column("sel", width=40, anchor="center")
        self.tree.heading("src", text="ソース", command=lambda: self._sort_tree("src", False)); self.tree.column("src", width=80, anchor="center")
        self.tree.heading("cat", text="キーワード", command=lambda: self._sort_tree("cat", False)); self.tree.column("cat", width=150)
        self.tree.heading("title", text="記事タイトル", command=lambda: self._sort_tree("title", False)); self.tree.column("title", width=500)
        self.tree.heading("author", text="作者", command=lambda: self._sort_tree("author", False)); self.tree.column("author", width=150)
        self.tree.heading("date", text="投稿日", command=lambda: self._sort_tree("date", False)); self.tree.column("date", width=150, anchor="center")

        sc = ttk.Scrollbar(lf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sc.set)
        sc.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.bind("<ButtonRelease-1>", self._click)
        self.tree.bind("<Double-1>", self._open_browser_double_click)

        # --- 共通ボタン行 ---
        bf = ttk.Frame(main)
        bf.pack(fill=tk.X, pady=10)
        ttk.Button(bf, text="🧹 全レポート既読", command=self._mark_all_read).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bf, text="☑ 全選択", command=self._all).pack(side=tk.LEFT)
        ttk.Button(bf, text="☐ 解除", command=self._none).pack(side=tk.LEFT, padx=15)
        # おすすめ抽出のUIコントロール
        self.var_rec_mode = tk.StringVar(value="absolute")
        self.var_rec_top_n = tk.IntVar(value=50)

        ttk.Radiobutton(bf, text="絶対評価", variable=self.var_rec_mode, value="absolute").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(bf, text="相対評価(上位", variable=self.var_rec_mode, value="relative").pack(side=tk.LEFT, padx=2)
        ttk.Entry(bf, textvariable=self.var_rec_top_n, width=4).pack(side=tk.LEFT)
        ttk.Label(bf, text="件)").pack(side=tk.LEFT, padx=(0, 10))

        self.btn_recommend = ttk.Button(bf, text="🌟 おすすめ抽出", command=self._apply_recommendation)
        self.btn_recommend.pack(side=tk.LEFT, padx=5)

        self.btn_gen = ttk.Button(bf, text="📊 レポート出力", command=self._gen, state="disabled")
        self.btn_gen.pack(side=tk.RIGHT)
        self.btn_read = ttk.Button(bf, text="📩 既読にする (一覧から削除)", command=self._mark_read, state="disabled")
        self.btn_read.pack(side=tk.RIGHT, padx=10)

        self.lbl_stat = ttk.Label(self.root, text=f"Ready (ver{VERSION})", relief="sunken")
        self.lbl_stat.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_keyword_tab(self, parent):
        """Tab1: キーワード探索用UI"""
        frame = ttk.Frame(parent, padding=8)
        frame.pack(fill=tk.X)
        self.btn_fetch = ttk.Button(frame, text="🔄 最新RSSを取得", command=self._fetch_rss)
        self.btn_fetch.pack(side=tk.LEFT)
        ttk.Label(frame, text="  キーワード管理ダイアログからキーワードを選択して取得します。").pack(side=tk.LEFT, padx=5)


    def _build_followed_note_tab(self, parent):
        """Tab2: フォローnote用UI"""
        frame = ttk.Frame(parent, padding=8)
        frame.pack(fill=tk.X)
        self.btn_fetch_followed = ttk.Button(
            frame,
            text="👤 フォローnote取得",
            command=self._fetch_followed_note
        )
        self.btn_fetch_followed.pack(side=tk.LEFT)
        ttk.Button(
            frame,
            text="📝 フォロー作者URL管理",
            command=self._open_followed_note_manager
        ).pack(side=tk.LEFT, padx=10)
        self.btn_sync_note = ttk.Button(         # [v20260527.01_01追加]
            frame,
            text="🔄 noteフォロー自動同期",
            command=self._sync_note_followings
        )
        self.btn_sync_note.pack(side=tk.LEFT, padx=10)
        ttk.Button(                              # [v20260527.01_01追加]
            frame,
            text="🔑 note認証設定",
            command=self._open_note_credential_dialog
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(
            frame,
            text="followed_note_authors.txt に登録したnote作者RSSを取得します。"
        ).pack(side=tk.LEFT, padx=5)

    def _build_ai_feed_tab(self, parent):
        """[v20260508.02追加] Tab3: AI最先端フィード用UI"""
        frame = ttk.Frame(parent, padding=8)
        frame.pack(fill=tk.X)
        self.btn_fetch_ai = ttk.Button(
            frame,
            text="🤖 AI最先端フィード取得",
            command=self._fetch_ai_feeds
        )
        self.btn_fetch_ai.pack(side=tk.LEFT)

        # フィード一覧ボタン
        ttk.Button(
            frame,
            text="📊 フィード一覧",
            command=self._show_ai_feed_list
        ).pack(side=tk.LEFT, padx=10)

        # フィード構成説明ラベル
        # [v20260801_01修正] 空カテゴリ(論文・研究)を表示から除外し、
        # arXiv未登録時は上限件数の注記を出さないようにする
        categories = ", ".join(k for k, v in AI_FEED_URLS.items() if v)
        total_feeds = sum(len(v) for v in AI_FEED_URLS.values())
        has_arxiv = any("arxiv.org" in f["url"] for feeds in AI_FEED_URLS.values() for f in feeds)
        arxiv_note = f" arXivは最新{AI_FEED_ARXIV_MAX}件に制限。" if has_arxiv else ""
        ttk.Label(
            frame,
            text=f"計{total_feeds}フィード（{categories}）を並列取得します。{arxiv_note}"
        ).pack(side=tk.LEFT, padx=5)

    def _show_ai_feed_list(self):
        """[v20260508.02追加] AIフィード一覧ダイアログ"""
        dialog = tk.Toplevel(self.root)
        dialog.title("AI最先端フィード一覧")
        dialog.geometry("700x500")
        dialog.transient(self.root)

        cols = ("category", "title", "url")
        tree = ttk.Treeview(dialog, columns=cols, show="headings")
        tree.heading("category", text="カテゴリ")
        tree.column("category", width=150)
        tree.heading("title", text="フィード名")
        tree.column("title", width=200)
        tree.heading("url", text="RSS URL")
        tree.column("url", width=320)

        for category, feeds in AI_FEED_URLS.items():
            for feed in feeds:
                tree.insert("", "end", values=(category, feed["title"], feed["url"]))

        sb = ttk.Scrollbar(dialog, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Button(dialog, text="閉じる", command=dialog.destroy).pack(pady=5)

    def _fetch_ai_feeds(self):
        """[v20260508.02追加] AI最先端フィード取得開始"""
        self._start_fetch_ai_feeds()

    def _start_fetch_ai_feeds(self):
        """[v20260508.02追加] 別スレッドでAIフィードRSSを取得する"""
        self.btn_fetch_ai.config(state="disabled")
        self.lbl_stat.config(text="AI最先端フィード RSS取得中...")
        self.var_display_mode.set("all")

        def task():
            try:
                def cb(msg):
                    self.root.after(0, lambda m=msg: self.lbl_stat.config(text=m))

                new_articles = self.feed_manager.fetch_ai_feeds(progress_callback=cb)

                self.articles = new_articles
                self.selected.clear()
                self.last_recommended_iids = []
                self.last_recommended_urls.clear()

                def update_ui():
                    self._update_list()
                    self.lbl_stat.config(
                        text=f"AI最先端フィード取得完了: {len(new_articles)}件"
                    )

                self.root.after(0, update_ui)

                # [v20260508.03_02追加] 英語タイトルを別スレッドで翻訳し、完了後に一覧を再描画
                self._start_translate_titles(new_articles)

            except Exception as e:
                self.root.after(
                    0,
                    lambda err=e: messagebox.showerror("Error", str(err))
                )
            finally:
                self.root.after(
                    0,
                    lambda: self.btn_fetch_ai.config(state="normal")
                )

        threading.Thread(target=task, daemon=True).start()


    def _open_note_credential_dialog(self):
        """[v20260527.01_01追加] note 認証設定ダイアログ（urlname / email / password / mode）"""
        dialog = tk.Toplevel(self.root)
        dialog.title("note 認証設定")
        dialog.geometry("440x290")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text="note.com ログイン情報を設定します。",
            padding=10
        ).pack(fill=tk.X)
        ttk.Label(
            dialog,
            text="パスワードは Windows 資格情報マネージャーに保存されます（config.json には書きません）。",
            foreground="#666666"
        ).pack(fill=tk.X, padx=10)

        form = ttk.Frame(dialog, padding=10)
        form.pack(fill=tk.X)

        ttk.Label(form, text="note urlname:").grid(
            row=0, column=0, sticky="e", pady=4
        )
        var_urlname = tk.StringVar(value=self.config.get("note_urlname", ""))
        ttk.Entry(form, textvariable=var_urlname, width=30).grid(
            row=0, column=1, padx=8, pady=4
        )

        ttk.Label(form, text="メールアドレス:").grid(
            row=1, column=0, sticky="e", pady=4
        )
        var_email = tk.StringVar(value=self.config.get("note_email", ""))
        ttk.Entry(form, textvariable=var_email, width=30).grid(
            row=1, column=1, padx=8, pady=4
        )

        ttk.Label(form, text="パスワード:").grid(
            row=2, column=0, sticky="e", pady=4
        )
        var_pw = tk.StringVar()
        _tmp = NoteFollowingSyncer(
            self.config.get("note_urlname", ""),
            self.config.get("note_email", "")
        )
        if _tmp.get_password():
            var_pw.set("●●●●●●●●")  # 登録済みの場合はダミー表示
        ttk.Entry(
            form, textvariable=var_pw, show="*", width=30
        ).grid(row=2, column=1, padx=8, pady=4)

        ttk.Label(form, text="同期モード:").grid(
            row=3, column=0, sticky="e", pady=4
        )
        var_mode = tk.StringVar(value=self.config.get("note_sync_mode", "merge"))
        mode_frame = ttk.Frame(form)
        mode_frame.grid(row=3, column=1, sticky="w", padx=8, pady=4)
        ttk.Radiobutton(
            mode_frame, text="merge（追記のみ・推奨）",
            variable=var_mode, value="merge"
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            mode_frame, text="full（完全同期）",
            variable=var_mode, value="full"
        ).pack(side=tk.LEFT, padx=10)

        def save():
            urlname = var_urlname.get().strip()
            email   = var_email.get().strip()
            pw      = var_pw.get()
            mode    = var_mode.get()
            if not urlname or not email:
                messagebox.showerror(
                    "入力エラー",
                    "urlname とメールアドレスは必須です。",
                    parent=dialog
                )
                return
            self.config["note_urlname"]   = urlname
            self.config["note_email"]     = email
            self.config["note_sync_mode"] = mode
            save_config(self.config)
            if pw and pw != "●●●●●●●●":
                _s = NoteFollowingSyncer(urlname, email)
                if not _s.set_password(pw):
                    messagebox.showwarning(
                        "警告",
                        "パスワードの保存に失敗しました。\n"
                        "keyring が正常にインストールされているか確認してください。",
                        parent=dialog
                    )
                    return
            messagebox.showinfo(
                "保存完了", "note 認証設定を保存しました。",
                parent=dialog
            )
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(
            btn_frame, text="キャンセル", command=dialog.destroy
        ).pack(side=tk.RIGHT)
        ttk.Button(
            btn_frame, text="保存", command=save
        ).pack(side=tk.RIGHT, padx=10)

    def _sync_note_followings(self):
        """[v20260527.01_01追加] noteフォロー自動同期 GUI イベントハンドラ"""
        urlname = self.config.get("note_urlname", "")
        email   = self.config.get("note_email",   "")

        if not urlname or not email:
            messagebox.showinfo(
                "設定が必要です",
                "先に「🔑 note認証設定」ボタンから\n"
                "urlname・メールアドレス・パスワードを登録してください。"
            )
            self._open_note_credential_dialog()
            return

        syncer = NoteFollowingSyncer(urlname, email)
        if not syncer.get_password():
            messagebox.showinfo(
                "パスワード未設定",
                "note パスワードが未登録です。\n"
                "「🔑 note認証設定」から設定してください。"
            )
            self._open_note_credential_dialog()
            return

        mode = self.config.get("note_sync_mode", "merge")
        self.btn_sync_note.config(state="disabled")
        self.lbl_stat.config(text="🔄 noteフォロー同期中...")

        def task():
            try:
                def cb(msg):
                    self.root.after(
                        0, lambda m=msg: self.lbl_stat.config(text=m)
                    )

                result = syncer.sync_to_file(
                    filepath=FOLLOWED_NOTE_FILE,
                    mode=mode,
                    headless=False,
                    progress_callback=cb,
                )
                added  = result["added"]
                total  = result["total"]
                backup = result["backup_path"]
                backup_msg = (
                    f"\n（バックアップ: {os.path.basename(backup)}）"
                    if backup else ""
                )
                msg = (
                    f"✅ 同期完了\n\n"
                    f"新規追加: {added}件\n"
                    f"合計登録数: {total}件{backup_msg}"
                )

                def update_ui():
                    self.lbl_stat.config(
                        text=f"noteフォロー同期完了: 新規{added}件追加 / 合計{total}件"
                    )
                    messagebox.showinfo("noteフォロー同期完了", msg)

                self.root.after(0, update_ui)

            except Exception as e:
                err_msg = str(e)
                self.root.after(
                    0,
                    lambda m=err_msg: messagebox.showerror("同期エラー", m)
                )
                self.root.after(
                    0,
                    lambda: self.lbl_stat.config(text=f"Ready (ver{VERSION})")
                )
            finally:
                self.root.after(
                    0,
                    lambda: self.btn_sync_note.config(state="normal")
                )

        threading.Thread(target=task, daemon=True).start()


    def _open_followed_note_manager(self):
        """フォロー作者URL管理ダイアログ"""
        dialog = tk.Toplevel(self.root)
        dialog.title("フォロー作者URL管理")
        dialog.geometry("500x450")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="note作者URLを1行1URLで登録してください。", padding=10).pack(fill=tk.X)

        text_frame = ttk.Frame(dialog)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        txt = tk.Text(text_frame, yscrollcommand=scrollbar.set, wrap=tk.NONE)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=txt.yview)

        # 既存内容を読み込んで表示
        existing_urls = load_followed_note_urls()
        for url in existing_urls:
            txt.insert(tk.END, url + "\n")

        def save_urls():
            content = txt.get("1.0", tk.END)
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            with open(FOLLOWED_NOTE_FILE, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
            messagebox.showinfo("保存完了", f"{len(lines)}件のURLを保存しました。", parent=dialog)
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="キャンセル", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="保存", command=save_urls).pack(side=tk.RIGHT, padx=10)

    def _fetch_followed_note(self):
        """フォローnote取得開始"""
        author_urls = load_followed_note_urls()
        if not author_urls:
            messagebox.showinfo(
                "info",
                "followed_note_authors.txt にnote作者URLを登録してください。"
            )
            return
        self._start_fetch_followed_note(author_urls)

    def _start_fetch_followed_note(self, author_urls):
        """別スレッドでフォローnote RSSを取得する"""
        self.btn_fetch_followed.config(state="disabled")
        self.lbl_stat.config(text="フォローnote RSS取得中...")
        self.var_display_mode.set("all")

        def task():
            try:
                def cb(msg):
                    self.root.after(0, lambda m=msg: self.lbl_stat.config(text=m))

                new_articles = self.feed_manager.fetch_followed_note_rss(
                    author_urls=author_urls,
                    progress_callback=cb
                )

                self.articles = new_articles
                self.selected.clear()
                self.last_recommended_iids = []
                self.last_recommended_urls.clear()

                def update_ui():
                    self._update_list()
                    self.lbl_stat.config(
                        text=f"フォローnote取得完了: {len(new_articles)}件"
                    )

                self.root.after(0, update_ui)

                # [v20260508.03_02追加] 英語タイトルを別スレッドで翻訳し、完了後に一覧を再描画
                self._start_translate_titles(new_articles)

            except Exception as e:
                self.root.after(
                    0,
                    lambda err=e: messagebox.showerror("Error", str(err))
                )
            finally:
                self.root.after(
                    0,
                    lambda: self.btn_fetch_followed.config(state="normal")
                )

        threading.Thread(target=task, daemon=True).start()

    def _open_phrase_manager(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("リコメンドフレーズ管理")
        dialog.geometry("550x550")
        dialog.transient(self.root)
        dialog.grab_set()
        
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        tab_pos = ttk.Frame(notebook)
        tab_neg = ttk.Frame(notebook)
        notebook.add(tab_pos, text="🟢 抽出フレーズ")
        notebook.add(tab_neg, text="🔴 除外フレーズ")
        
        style = ttk.Style()
        style.configure("White.TFrame", background="white")
        
        def build_tab(parent_frame, config_key):
            list_frame = ttk.Frame(parent_frame)
            list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            
            canvas = tk.Canvas(list_frame, bg="white")
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas, style="White.TFrame")
            
            scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            vars_dict = {}
            
            def refresh_list():
                for widget in scrollable_frame.winfo_children():
                    widget.destroy()
                vars_dict.clear()
                
                phrases = self.recommend_config.get(config_key, [])
                for p in phrases:
                    var = tk.BooleanVar(value=False)
                    vars_dict[p] = var
                    chk = ttk.Checkbutton(scrollable_frame, text=p, variable=var, style="TCheckbutton")
                    try: chk.config(background="white")
                    except: pass
                    chk.pack(anchor="w", padx=10, pady=5)
            
            refresh_list()
            
            ctrl_frame = ttk.Frame(parent_frame)
            ctrl_frame.pack(fill=tk.X, pady=5)
            
            def select_all(state):
                for var in vars_dict.values():
                    var.set(state)
            
            ttk.Button(ctrl_frame, text="☑ 全選択", command=lambda: select_all(True)).pack(side=tk.LEFT, padx=2)
            ttk.Button(ctrl_frame, text="☐ 全解除", command=lambda: select_all(False)).pack(side=tk.LEFT, padx=2)
            
            def delete_selected():
                selected = [p for p, var in vars_dict.items() if var.get()]
                if not selected: return
                if not messagebox.askyesno("確認", f"{len(selected)}件のフレーズを削除しますか？\n（削除後は自動保存され、直ちに反映されます）", parent=dialog): return
                
                if not messagebox.askyesno("再確認", "⚠️ 本当に削除してもよろしいですか？\n（削除前の状態は「.bak」ファイルとしてバックアップされます）", parent=dialog): return
                
                current = self.recommend_config.get(config_key, [])
                self.recommend_config[config_key] = [p for p in current if p not in selected]
                self._save_recommend_config()
                refresh_list()
            
            ttk.Button(ctrl_frame, text="🗑️ 削除", command=delete_selected).pack(side=tk.RIGHT, padx=2)
            
            add_frame = ttk.Frame(parent_frame)
            add_frame.pack(fill=tk.X, pady=5)
            
            entry = ttk.Entry(add_frame)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            
            def add_phrase():
                new_p = entry.get().strip()
                current = self.recommend_config.get(config_key, [])
                if not new_p or new_p in current: return
                
                current.append(new_p)
                self.recommend_config[config_key] = current
                self._save_recommend_config()
                refresh_list()
                entry.delete(0, tk.END)
                
            ttk.Button(add_frame, text="➕ 追加", command=add_phrase).pack(side=tk.RIGHT)
            entry.bind("<Return>", lambda e: add_phrase())
            
        build_tab(tab_pos, "phrases")
        build_tab(tab_neg, "negative_phrases")
        ttk.Button(dialog, text="閉じる", command=dialog.destroy).pack(pady=10)

    def _calc_recommendations(self, articles_list, mode="absolute", top_n=50):
        phrases = self.recommend_config.get("phrases", [])
        negative_phrases = self.recommend_config.get("negative_phrases", [])
        threshold = self.recommend_config.get("threshold", 0.65)
        if not phrases or not articles_list:
            return []

        phrase_emb_res = genai.embed_content(model="models/gemini-embedding-001", content=phrases)
        phrase_vectors = phrase_emb_res['embedding'] if isinstance(phrase_emb_res['embedding'][0], list) else [phrase_emb_res['embedding']]
        
        titles = [a['title'] for a in articles_list]
        title_emb_res = genai.embed_content(model="models/gemini-embedding-001", content=titles)
        article_vectors = title_emb_res['embedding'] if isinstance(title_emb_res['embedding'][0], list) else [title_emb_res['embedding']]
        
        neg_vectors = []
        if negative_phrases:
            neg_emb_res = genai.embed_content(model="models/gemini-embedding-001", content=negative_phrases)
            neg_vectors = neg_emb_res['embedding'] if isinstance(neg_emb_res['embedding'][0], list) else [neg_emb_res['embedding']]
            
        scored_candidates = []
        for i, a_vec in enumerate(article_vectors):
            max_sim = max(cosine_similarity(a_vec, p_vec) for p_vec in phrase_vectors)
            
            # ネガティブ除外チェック
            if neg_vectors:
                max_neg_sim = max(cosine_similarity(a_vec, n_vec) for n_vec in neg_vectors)
                if max_neg_sim >= threshold:
                    continue
                    
            scored_candidates.append((i, max_sim))
            
        if mode == "absolute":
            return [str(idx) for idx, sim in scored_candidates if sim >= threshold]
        else:
            # 相対評価（Top N件）
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            return [str(idx) for idx, sim in scored_candidates[:top_n]]

    def _apply_recommendation(self):
        if not self.articles: return
        if not self.config.get("gemini_api_key"):
            messagebox.showerror("Error", "APIキーが設定されていません。")
            return
            
        mode = self.var_rec_mode.get()
        top_n = self.var_rec_top_n.get()
        
        def task():
            self.root.after(0, lambda: self.btn_recommend.config(state="disabled"))
            self.root.after(0, lambda: self.lbl_stat.config(text="AIがおすすめ記事を判定中..."))
            try:
                if not self.recommend_config.get("phrases"):
                    self.root.after(0, lambda: messagebox.showinfo("Info", "学習データがありません。「設定」から学習を実行してください。"))
                    return
                
                recommended_iids = self._calc_recommendations(self.articles, mode=mode, top_n=top_n)
                self.root.after(0, lambda: self._apply_recommendation_result(recommended_iids, show_msg=True))
            except Exception as e:
                self.root.after(0, lambda err=e: messagebox.showerror("Error", f"判定中にエラーが発生しました:\n{err}"))
            finally:
                self.root.after(0, lambda: self.btn_recommend.config(state="normal"))
                self.root.after(0, lambda: self.lbl_stat.config(text=f"Ready (ver{VERSION})"))
        threading.Thread(target=task, daemon=True).start()

    def _apply_recommendation_result(self, recommended_iids, show_msg=True):
        self.last_recommended_iids = recommended_iids
        self.last_recommended_urls.clear()
        
        # ユーザーが手動で選ぶため、自動チェックはしない
        self.selected.clear() 
        
        for iid in recommended_iids:
            url = self.articles[int(iid)]['url']
            self.last_recommended_urls.add(url)
            
        if recommended_iids:
            self.var_display_mode.set("recommended")
        else:
            self.var_display_mode.set("all")
            
        self._update_list()
        if show_msg:
            messagebox.showinfo("完了", f"{len(recommended_iids)}件のおすすめ記事を抽出しました。\n（※自動チェックはされません。ご自身で確認してチェックを入れてください）")

    def _start_translate_titles(self, articles: list) -> None:
        """
        [v20260508.03_02修正]
        記事リストの英語タイトルを別スレッドでシリアル翻訳する。
        全件翻訳完了後に一覧を一度だけ再描画する。
        """
        if not _TRANSLATE_AVAILABLE:
            return

        def _do_translate():
            targets = [a for a in articles if 'title_ja' not in a]
            total = len(targets)
            if total == 0:
                return

            for i, article in enumerate(targets, 1):
                ja = translate_title_if_english(article.get('title', ''))
                article['title_ja'] = ja
                msg = f"🌐 タイトル翻訳中... {i}/{total}"
                self.root.after(0, lambda m=msg: self.lbl_stat.config(text=m))

            # 全件翻訳完了後に一度だけ一覧を再描画
            self.root.after(0, self._update_list)
            self.root.after(0, lambda: self.lbl_stat.config(
                text=f"🌐 タイトル翻訳完了 ({total}件)"
            ))

        threading.Thread(target=_do_translate, daemon=True).start()

    def _on_filter_all_change(self):
        state = self.var_filter_all.get()
        self.var_filter_note.set(state)
        self.var_filter_zenn.set(state)
        self.var_filter_qiita.set(state)
        self.var_filter_ai_feed.set(state)  # [v20260508.02追加]
        self._update_list()

    def _on_filter_source_change(self):
        # [v20260508.02修正] AIフィードフィルタをAll判定に含める
        all_checked = (self.var_filter_note.get() and self.var_filter_zenn.get()
                       and self.var_filter_qiita.get() and self.var_filter_ai_feed.get())
        self.var_filter_all.set(all_checked)
        self._update_list()

    def _update_list(self):
        self.tree.delete(*self.tree.get_children())
        active_sources = {
            "note": self.var_filter_note.get(),
            "Zenn": self.var_filter_zenn.get(),
            "Qiita": self.var_filter_qiita.get(),
            "ai-feed": self.var_filter_ai_feed.get(),  # [v20260508.02追加]
        }
        
        visible_iids = set()
        mode = self.var_display_mode.get()
        
        for i, a in enumerate(self.articles):
            src = a.get('source', '')
            # note-follow はフィルタ対象外（常に表示）、その他は既存フィルタを適用
            if src != "note-follow" and src in active_sources and not active_sources[src]:
                continue
                
            iid = str(i)
            
            # フィルタリング条件
            if mode == "selected" and iid not in self.selected:
                continue
            elif mode == "unselected" and iid in self.selected:
                continue
            elif mode == "recommended" and iid not in self.last_recommended_iids:
                continue
                
            visible_iids.add(iid)
            
            sel_char = "☑" if iid in self.selected else "☐"
            # [v20260508.03_02修正] 英語タイトルは日本語訳を一覧に表示し、青色タグを適用
            title_ja = a.get('title_ja')
            display_title = title_ja if title_ja else a['title']
            if iid in self.selected:
                tags = ("checked",)
            elif title_ja:
                tags = ("translated",)
            else:
                tags = ()
            
            self.tree.insert("", "end", iid=iid, values=(
                sel_char, 
                a['source'],
                a['categories_str'], 
                display_title, 
                a['author'],
                a['published_str']
            ), tags=tags)
            
        self._chk_btns()
        self._update_stats_display()

    def _update_stats_display(self):
        # [v20260508.02修正] AIフィードカウントを追加
        counts = {"note": 0, "Qiita": 0, "Zenn": 0, "ai-feed": 0}
        total = 0
        for child in self.tree.get_children():
            src = self.tree.set(child, "src")
            if src in counts:
                counts[src] += 1
            total += 1
        
        stats_text = (f"note: {counts['note']} | Zenn: {counts['Zenn']} | "
                      f"Qiita: {counts['Qiita']} | 🤖AI: {counts['ai-feed']} (Total: {total})")
        self.lbl_counts.config(text=stats_text)
        
        sel_count = len(self.selected)
        self.lbl_sel_count.config(text=f"{sel_count} 件選択中")

    def _start_fetch(self, keywords):
        self.btn_fetch.config(state="disabled")
        self.lbl_stat.config(text="RSS情報取得中...")
        
        self.var_filter_note.set(True)
        self.var_filter_zenn.set(True)
        self.var_filter_qiita.set(True)
        self.var_filter_all.set(True)
        self.var_display_mode.set("all")
        
        def task():
            try:
                def cb(msg):
                    self.root.after(0, lambda m=msg: self.lbl_stat.config(text=m))
                
                new_articles = self.feed_manager.fetch_rss(keywords=keywords, progress_callback=cb)
                self.articles = new_articles
                
                if not new_articles:
                    self.root.after(0, lambda: self.lbl_stat.config(text="Ready"))
                    self.root.after(0, lambda: messagebox.showinfo("info", "新しい記事は見つかりませんでした。"))
                    return
                
                self.root.after(0, lambda: self.lbl_stat.config(text="AIがおすすめ記事を判定中..."))
                
                recommended_iids = []
                if self.config.get("gemini_api_key"):
                    try:
                        mode = self.var_rec_mode.get()
                        top_n = self.var_rec_top_n.get()
                        recommended_iids = self._calc_recommendations(new_articles, mode=mode, top_n=top_n)
                    except Exception as e:
                        print(f"Recommend error: {e}")
                
                def update_ui():
                    self._apply_recommendation_result(recommended_iids, show_msg=False)
                    self.lbl_stat.config(text=f"取得・判定完了 ({len(new_articles)}件中 {len(recommended_iids)}件おすすめ)")
                
                self.root.after(0, update_ui)

                # [v20260508.03_02追加] 英語タイトルを別スレッドで翻訳し、完了後に一覧を再描画
                self._start_translate_titles(new_articles)

            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda m=err_msg: messagebox.showerror("Error", m))
            finally:
                self.root.after(0, lambda: self.btn_fetch.config(state="normal"))
        
        threading.Thread(target=task, daemon=True).start()

    def _fetch_rss(self):
        self._show_keyword_dialog()

    def _show_keyword_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("キーワード管理・選択")
        dialog.geometry("450x600")
        dialog.transient(self.root)
        dialog.grab_set() 

        ttk.Label(dialog, text="取得するキーワードを選択し、整理してください。", padding=10).pack(fill=tk.X)

        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        canvas = tk.Canvas(list_frame, bg="white")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        style = ttk.Style()
        style.configure("White.TFrame", background="white")
        scrollable_frame = ttk.Frame(canvas, style="White.TFrame")

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.kw_vars = {}

        def refresh_list():
            for widget in scrollable_frame.winfo_children(): widget.destroy()
            self.kw_vars.clear()
            
            my_kws = []
            if os.path.exists(MY_KEYWORDS_FILE):
                with open(MY_KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                    my_kws = [line.strip() for line in f if line.strip()]
                    
            extracted_kws = []
            if os.path.exists(KEYWORDS_FILE):
                with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                    extracted_kws = [line.strip() for line in f if line.strip()]
                    
            existing_set = set(my_kws)
            new_kws = [kw for kw in extracted_kws if kw not in existing_set]
            
            if my_kws:
                lbl = ttk.Label(scrollable_frame, text="【既存キーワード】(チェックして削除可能)", font=("", 10, "bold"), background="white")
                lbl.pack(anchor="w", pady=(5, 5), fill=tk.X)
                for kw in my_kws:
                    var = tk.BooleanVar(value=True)
                    self.kw_vars[kw] = var
                    chk = ttk.Checkbutton(scrollable_frame, text=kw, variable=var, style="TCheckbutton")
                    try: chk.config(background="white")
                    except: pass
                    chk.pack(anchor="w", padx=15, pady=2)
                    
            if new_kws:
                lbl = ttk.Label(scrollable_frame, text="【新規抽出キーワード】(追加分)", font=("", 10, "bold"), background="white")
                lbl.pack(anchor="w", pady=(15, 5), fill=tk.X)
                for kw in new_kws:
                    var = tk.BooleanVar(value=False)
                    self.kw_vars[kw] = var
                    chk = ttk.Checkbutton(scrollable_frame, text=kw, variable=var, style="TCheckbutton")
                    try: chk.config(background="white")
                    except: pass
                    chk.pack(anchor="w", padx=15, pady=2)
                    
            if not my_kws and not new_kws:
                ttk.Label(scrollable_frame, text="キーワードが見つかりません。", background="white").pack(anchor="w", padx=15)
                
        refresh_list()
        
        ctrl_frame = ttk.Frame(dialog)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=5)
        
        def select_all(state):
            for var in self.kw_vars.values(): var.set(state)
        ttk.Button(ctrl_frame, text="☑ 全選択", command=lambda: select_all(True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl_frame, text="☐ 全解除", command=lambda: select_all(False)).pack(side=tk.LEFT, padx=2)
        
        def delete_selected():
            selected = [kw for kw, var in self.kw_vars.items() if var.get()]
            if not selected: return
            if not messagebox.askyesno("確認", f"選択した{len(selected)}件のキーワードを削除しますか？\n（即時保存されます）", parent=dialog): return
            
            if not messagebox.askyesno("再確認", "⚠️ 本当に削除してもよろしいですか？\n（削除前の状態は「.bak」ファイルとしてバックアップされます）", parent=dialog): return
            
            current = []
            if os.path.exists(MY_KEYWORDS_FILE):
                with open(MY_KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                    current = [line.strip() for line in f if line.strip()]
                with open(MY_KEYWORDS_FILE + ".bak", 'w', encoding='utf-8') as f:
                    for kw in current: f.write(f"{kw}\n")
                    
            new_list = [kw for kw in current if kw not in selected]
            with open(MY_KEYWORDS_FILE, 'w', encoding='utf-8') as f:
                for kw in new_list: f.write(f"{kw}\n")
                
            if os.path.exists(KEYWORDS_FILE):
                with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                    ext_kws = [line.strip() for line in f if line.strip()]
                with open(KEYWORDS_FILE + ".bak", 'w', encoding='utf-8') as f:
                    for kw in ext_kws: f.write(f"{kw}\n")
                    
                new_ext = [kw for kw in ext_kws if kw not in selected]
                with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
                    for kw in new_ext: f.write(f"{kw}\n")
            refresh_list()
            
        ttk.Button(ctrl_frame, text="🗑️ 削除", command=delete_selected).pack(side=tk.RIGHT, padx=2)
        
        add_frame = ttk.Frame(dialog)
        add_frame.pack(fill=tk.X, padx=10, pady=5)
        entry = ttk.Entry(add_frame); entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        def add_keyword():
            new_kw = entry.get().strip()
            if not new_kw: return
            current = []
            if os.path.exists(MY_KEYWORDS_FILE):
                with open(MY_KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                    current = [line.strip() for line in f if line.strip()]
            if new_kw in current: return
            current.append(new_kw)
            with open(MY_KEYWORDS_FILE, 'w', encoding='utf-8') as f:
                for kw in current: f.write(f"{kw}\n")
            refresh_list()
            entry.delete(0, tk.END)
        ttk.Button(add_frame, text="➕ 追加", command=add_keyword).pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: add_keyword())

        def on_start():
            selected_kws = [kw for kw, var in self.kw_vars.items() if var.get()]
            if not selected_kws:
                messagebox.showinfo("info", "取得するキーワードが選択されていません。", parent=dialog)
                return
            
            current = []
            if os.path.exists(MY_KEYWORDS_FILE):
                with open(MY_KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                    current = [line.strip() for line in f if line.strip()]
            
            for kw in selected_kws:
                if kw not in current:
                    current.append(kw)
                    
            with open(MY_KEYWORDS_FILE, 'w', encoding='utf-8') as f:
                for kw in current:
                    f.write(f"{kw}\n")
            
            dialog.destroy()
            self._start_fetch(selected_kws)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="キャンセル", command=dialog.destroy).pack(side=tk.RIGHT, padx=10)
        ttk.Button(btn_frame, text="取得開始", command=on_start).pack(side=tk.RIGHT)

    def _chk_btns(self):
        s = "normal" if self.selected else "disabled"
        self.btn_gen.config(state=s)
        self.btn_read.config(state=s)
        self._update_stats_display()

    def _click(self, e):
        item_id = self.tree.identify_row(e.y)
        if not item_id: return
        
        if item_id in self.selected:
            self.selected.remove(item_id)
            self.tree.set(item_id, "sel", "☐")
            self.tree.item(item_id, tags=())
        else:
            self.selected.add(item_id)
            self.tree.set(item_id, "sel", "☑")
            self.tree.item(item_id, tags=("checked",))
        self._chk_btns()

    def _open_browser_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            idx = int(item)
            url = self.articles[idx]['url']
            webbrowser.open(url)

    def _all(self):
        for i in self.tree.get_children():
            self.selected.add(i)
            self.tree.set(i, "sel", "☑"); self.tree.item(i, tags=("checked",))
        self._chk_btns()
    
    def _none(self):
        for i in self.tree.get_children():
            if i in self.selected:
                self.selected.remove(i)
            self.tree.set(i, "sel", "☐"); self.tree.item(i, tags=())
        self._chk_btns()

    def _sort_tree(self, col, reverse):
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        items.sort(reverse=reverse)
        for index, (val, k) in enumerate(items):
            self.tree.move(k, "", index)
        
        self._update_stats_display()
        self.tree.heading(col, command=lambda: self._sort_tree(col, not reverse))

    def _mark_read(self):
        if not messagebox.askyesno("確認", "選択した記事を既読（次回から非表示）にしますか？"): return
        sel_articles = [self.articles[int(i)] for i in self.selected]
        urls_to_mark = [a['url'] for a in sel_articles]
        # [v20260508.03_03修正] AIフィード記事は専用履歴に登録、それ以外は通常履歴に登録
        ai_urls = [a['url'] for a in sel_articles if a.get('source') == 'ai-feed']
        other_urls = [a['url'] for a in sel_articles if a.get('source') != 'ai-feed']
        if ai_urls:
            self.feed_manager.mark_ai_feed_as_read(ai_urls)
        if other_urls:
            self.feed_manager.mark_as_read(other_urls)
        
        new_articles = []
        for i, a in enumerate(self.articles):
            if str(i) not in self.selected:
                new_articles.append(a)
        self.articles = new_articles
        self.selected.clear()
        self._update_list()
        self.lbl_stat.config(text=f"{len(urls_to_mark)}件を既読にしました。")

    def _mark_all_read(self, silent=False):
        if not self.articles:
            if not silent: messagebox.showinfo("Info", "一覧に記事がありません。")
            return
            
        if not silent:
            if not messagebox.askyesno("確認", "取得した全記事を既読にしてリストから一括削除しますか？"): return
            
        urls_to_mark = [a['url'] for a in self.articles]
        # [v20260508.03_03修正] AIフィード記事は専用履歴に登録、それ以外は通常履歴に登録
        ai_urls = [a['url'] for a in self.articles if a.get('source') == 'ai-feed']
        other_urls = [a['url'] for a in self.articles if a.get('source') != 'ai-feed']
        if ai_urls:
            self.feed_manager.mark_ai_feed_as_read(ai_urls)
        if other_urls:
            self.feed_manager.mark_as_read(other_urls)

        self.articles = []
        self.selected.clear()
        self._update_list()
        if not silent:
            self.lbl_stat.config(text=f"全{len(urls_to_mark)}件を既読にしました。")
    def _gen(self):
        self.lbl_stat.config(text="要約レポート生成中...")
        self.btn_gen.config(state="disabled")
        # [v20260607_01_04修正] /summarize呼び出し前にFlaskサーバーを先行起動
        # 2秒sleepでFlask listen状態への到達を保証する
        # 2回目以降は_ondemand_server_startedフラグで即座にreturnするため無駄なsleepなし
        start_ondemand_api_server(self.summarizer)
        import time
        time.sleep(2)
        sel_articles = [self.articles[int(i)] for i in self.selected]
        
  
        sel_articles.sort(key=lambda a: (
            a.get('categories_str', '').lower(),
            a.get('source', '').lower(),
            a.get('author', '').lower(),
            a.get('title', '').lower()
        ))
        
        # 実際に読んだ記事
        read_titles = [a['title'] for a in sel_articles]
        
        removed_titles = []
        if self.last_recommended_urls:
            selected_urls = {a['url'] for a in sel_articles}
            # AIがおすすめしたが、ユーザーが選ばなかった（スルーした）記事＝ノイズ
            removed_urls = self.last_recommended_urls - selected_urls
            all_url_to_title = {a['url']: a['title'] for a in self.articles}
            removed_titles = [all_url_to_title.get(u, "") for u in removed_urls if u in all_url_to_title]
        
        def task():
            def cb(done, total, msg):
                self.root.after(0, lambda: self.lbl_stat.config(text=msg))

            # [v20260607_01_03修正] /summarizeエンドポイント経由でFlaskサーバーに委譲
            # sync_playwright()制約をFlaskスレッド内で実行することで回避
            try:
                import requests as _requests
            except ImportError:
                import subprocess as _sp, sys as _sys
                _sp.run([_sys.executable, "-m", "pip", "install", "requests"], check=False)
                import requests as _requests
            # [v20260607_01_03修正] datetimeオブジェクトをJSON変換可能な文字列に変換
            import copy
            articles_for_json = copy.deepcopy(sel_articles)
            for a in articles_for_json:
                for k, v in a.items():
                    if hasattr(v, 'isoformat'):
                        a[k] = v.isoformat()
                if 'categories' in a and isinstance(a['categories'], set):
                    a['categories'] = list(a['categories'])
                    
            self.root.after(0, lambda: self.lbl_stat.config(text="要約中... (Flaskサーバー経由)"))
            try:
                resp = _requests.post(
                    f"http://127.0.0.1:{ONDEMAND_API_PORT}/summarize",
                    json={"articles": articles_for_json},
                    timeout=600
                )
                resp.raise_for_status()
                resp_data = resp.json()
                summaries_data = resp_data.get('results', {})
                cost_usd = resp_data.get('cost_usd', 0.0)
                cost_jpy = resp_data.get('cost_jpy', 0.0)
                    
            except Exception as e:
                self.root.after(0, lambda err=e: messagebox.showerror(
                    "要約エラー", f"Flaskサーバーへの接続に失敗しました:\n{err}"
                ))
                self.root.after(0, lambda: self.btn_gen.config(state="normal"))
                return

            # [v20260607_01_06修正] char_countをFlaskコピーから呼び出し元sel_articlesへ書き戻す
            char_counts = resp_data.get('char_counts', {})
            for a in sel_articles:
                if a['url'] in char_counts:
                    a['char_count'] = char_counts[a['url']]

            # [v20260508.03修正] summarizerを渡してオンデマンドAPIサーバーを起動
            path = self.reporter.generate_report(
                sel_articles,
                summaries_data,
                cost_usd=cost_usd,
                cost_jpy=cost_jpy,
                summarizer=self.summarizer
            )
            webbrowser.open(path)

            # 手動実行で、おすすめ機能を使用しており、かつデータがある場合のみ対照学習を実行
            if self.last_recommended_urls and (read_titles or removed_titles):
                self._learn_from_feedback(read_titles, removed_titles)

            # HTML出力完了後に統合バッチを起動
            import subprocess
            try:
                batch_path = r"C:\Users\nx023836\Documents\PythonScripts\RSS\start_consolidated_HTML_summary_manager.bat"
                subprocess.Popen(batch_path, shell=True)
            except Exception as e:
                print(f"Batch execution error: {e}")

            if cost_usd > 0:
                stat_msg = f"レポート出力完了 (推定コスト: ${cost_usd:.4f} / 約{cost_jpy:.2f}円)"
            else:
                stat_msg = "レポート出力完了"

            self.root.after(0, lambda: self.lbl_stat.config(text=stat_msg))
            self.root.after(0, lambda: self.btn_gen.config(state="normal"))

        # [v20260607_01_03修正] Flaskサーバー経由のためthreading.Threadで非同期実行可能
        import threading
        threading.Thread(target=task, daemon=True).start()


    def _learn_from_feedback(self, read_titles, removed_titles):
        try:
            current_phrases = self.recommend_config.get("phrases", [])
            current_negatives = self.recommend_config.get("negative_phrases", [])
            
            prompt = f"""あなたはAIレコメンドエンジンのチューナーです。
以下の現在の設定をベースに、ユーザーが「最終的に読んだ記事」と「おすすめされたがスルーした記事（優先度負け・ノイズ）」の差分を対照学習（Contrastive Learning）し、リストをアップデートしてください。

【ルール】
・「読んだ記事」の特徴を「抽出フレーズ」に追加・洗練させてください。
・「スルーした記事」の特徴（タイパが悪い、興味から外れるノイズ）を言語化し、「除外フレーズ」に追加してください。
・大幅な削除は避け、微調整にとどめてください。
・出力は必ず以下のJSON形式のみとしてください。Markdown記号は不要です。
{{ "phrases": ["フレーズ1"], "negative_phrases": ["除外1"] }}

【現在の抽出フレーズ】\n{current_phrases}
【現在の除外フレーズ】\n{current_negatives}

【ユーザーが読んだ記事（正解）】\n{chr(10).join(read_titles) if read_titles else "なし"}
【おすすめされたがスルーした記事（ノイズ）】\n{chr(10).join(removed_titles) if removed_titles else "なし"}
"""
            model = genai.GenerativeModel("gemini-2.5-flash")
            res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            
            # 安定したJSONパース（表示バグ回避のためバッククォートを直接書かずに処理）
            text = res.text.strip()
            md_fence = chr(96) * 3  # バッククォート3つを生成
            
            if text.startswith(f'{md_fence}json'): 
                text = text[7:]
            elif text.startswith(md_fence): 
                text = text[3:]
                
            if text.endswith(md_fence): 
                text = text[:-3]
                
            new_data = json.loads(text.strip())
            
            new_phrases = new_data.get("phrases", current_phrases)
            new_negatives = new_data.get("negative_phrases", current_negatives)
            
            # 差分表示用
            old_p_set = set(current_phrases)
            new_p_set = set(new_phrases)
            added_p = new_p_set - old_p_set
            
            old_n_set = set(current_negatives)
            new_n_set = set(new_negatives)
            added_n = new_n_set - old_n_set

            if not added_p and not added_n:
                print("Learning completed: No changes in phrases.")
                return

            self.recommend_config["phrases"] = new_phrases
            self.recommend_config["negative_phrases"] = new_negatives
            self._save_recommend_config()
            
            msg_parts = [f"あなたの選択（読んだ{len(read_titles)}件 / スルー{len(removed_titles)}件）の差分を学習し、フィルターを進化させました。\n"]
            if added_p:
                msg_parts.append("🟢 追加された抽出条件:")
                for p in added_p: msg_parts.append(f"  [+] {p}")
            if added_n:
                msg_parts.append("🔴 追加された除外条件:")
                for p in added_n: msg_parts.append(f"  [-] {p}")
                
            msg = "\n".join(msg_parts)
            self.root.after(0, lambda: messagebox.showinfo("🧠 AI対照学習完了", msg))
        except Exception as e:
            print(f"Learning error: {e}")
            


    def _set_api(self):
        d = tk.Toplevel(self.root)
        d.title("API Key Config")
        ttk.Label(d, text="Gemini API Key:").pack(padx=10, pady=(10,0))
        e = ttk.Entry(d, width=50); e.pack(padx=10, pady=5)
        e.insert(0, self.config['gemini_api_key'])
        def save():
            self.config['gemini_api_key'] = e.get()
            save_config(self.config)
            self.summarizer.api_key = e.get()
            d.destroy()
        ttk.Button(d, text="Save", command=save).pack(pady=10)


    def _run_auto(self):
        """コマンドライン起動用のステルス全自動実行メソッド"""
        import sys
        import os
        import webbrowser
        import subprocess

        # [v20260527.01_01追加] Step 0: noteフォロー自動同期（urlname設定済みの場合のみ）
        _note_urlname = self.config.get("note_urlname", "")
        _note_email   = self.config.get("note_email",   "")
        if _note_urlname and _note_email:
            print("🔄 [Step 0] noteフォロー同期開始...")
            try:
                _syncer = NoteFollowingSyncer(_note_urlname, _note_email)
                if _syncer.get_password():
                    _result = _syncer.sync_to_file(
                        filepath=FOLLOWED_NOTE_FILE,
                        mode=self.config.get("note_sync_mode", "merge"),
                        headless=True,
                        progress_callback=lambda msg: print(f"  {msg}"),
                    )
                    print(
                        f"✅ noteフォロー同期完了: "
                        f"新規{_result['added']}件 / 合計{_result['total']}件"
                    )
                else:
                    print("⚠️ noteパスワード未設定のためStep 0をスキップします")
            except Exception as _e:
                print(f"⚠️ noteフォロー同期エラー（処理継続）: {_e}")
        else:
            print("ℹ️ note_urlname未設定のためStep 0をスキップします")

        # [v20260527_02_01] Step 1: Tab2 フォローNote 全件取得
        print("👤 [Step 1] Tab2 フォローNote取得開始...")
        articles_tab2 = []
        author_urls = load_followed_note_urls()
        if author_urls:
            try:
                articles_tab2 = self.feed_manager.fetch_followed_note_rss(
                    author_urls=author_urls,
                    progress_callback=lambda msg: print(f"  {msg}"),
                )

                # [v20260527_02_03] 作者グループ化→投稿日時降順（2パス安定ソート）
                # Pass1: 投稿日時 降順
                articles_tab2.sort(
                    key=lambda a: a.get("published_sort", datetime.min),
                    reverse=True
                )
                # Pass2: 作者名 昇順（安定ソートにより作者内の日時順が保持される）
                articles_tab2.sort(
                    key=lambda a: a.get("author", "不明").lower()
                )
                
                print(f"✅ Tab2取得完了: {len(articles_tab2)}件")
            except Exception as _e:
                print(f"⚠️ Tab2取得エラー（処理継続）: {_e}")
        else:
            print("ℹ️ followed_note_authors.txt が空のためTab2をスキップします")

        # [v20260527_02_01] Step 2: Tab1 全件取得→Tab2重複除去→リコメンド上位50件
        print("🔎 [Step 2] Tab1 キーワード探索開始...")
        articles_tab1 = []
        my_kws = []
        if os.path.exists(MY_KEYWORDS_FILE):
            with open(MY_KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                my_kws = [line.strip() for line in f if line.strip()]

        if not my_kws:
            print("ℹ️ my_keywords.txt が空のためTab1をスキップします")
        else:
            if not self.config.get("gemini_api_key"):
                print("Auto-run aborted: API Key is not configured.")
                sys.exit(0)

            # Tab1 全件取得
            raw_tab1 = self.feed_manager.fetch_rss(
                keywords=my_kws,
                progress_callback=lambda msg: print(f"  {msg}"),
            )
            print(f"  Tab1 RSS取得: {len(raw_tab1)}件")

            # Tab2重複除去
            tab2_urls = {a['url'] for a in articles_tab2}
            raw_tab1_deduped = [
                a for a in raw_tab1 if a['url'] not in tab2_urls
            ]
            print(f"  Tab2重複除去後: {len(raw_tab1_deduped)}件")

            if not raw_tab1_deduped:
                print("ℹ️ Tab1: 重複除去後0件のためリコメンドをスキップします")
            else:
                # リコメンド上位50件（相対評価）
                try:
                    rec_iids = self._calc_recommendations(
                        raw_tab1_deduped, mode="relative", top_n=50
                    )
                    articles_tab1 = [raw_tab1_deduped[int(i)] for i in rec_iids]
                    # カテゴリ+ソース順ソート
                    articles_tab1.sort(key=lambda a: (
                        a.get('categories_str', '').lower(),
                        a.get('source', '').lower(),
                        a.get('author', '').lower(),
                        a.get('title', '').lower()
                    ))
                    print(f"✅ Tab1完了: リコメンド{len(articles_tab1)}件")
                except Exception as _e:
                    print(f"⚠️ Tab1リコメンドエラー（処理継続）: {_e}")

        # [v20260529_01_03追加] Step 2.5: AI既読履歴の自動パージ
        print("🧹 [Step 2.5] AI既読履歴パージ開始...")
        self.feed_manager.purge_ai_feed_history()

        # [v20260527_02_01] Step 3: Tab3 AI最先端フィード 全件取得
        print("🤖 [Step 3] Tab3 AI最先端フィード取得開始...")
        articles_tab3 = []

        try:
            articles_tab3 = self.feed_manager.fetch_ai_feeds(
                progress_callback=lambda msg: print(f"  {msg}"),
            )
            # [v20260527_02_03] categories_str→feed_title→投稿日時降順（3パス安定ソート）
            # Pass1: 投稿日時 降順
            articles_tab3.sort(
                key=lambda a: a.get("published_sort", datetime.min),
                reverse=True
            )
            # Pass2: feed_title 昇順（安定ソートにより各feed_title内の日時順が保持される）
            articles_tab3.sort(
                key=lambda a: a.get("feed_title", "").lower()
            )
            # Pass3: categories_str 昇順（安定ソートにより各カテゴリ内のfeed_title順が保持される）
            articles_tab3.sort(
                key=lambda a: a.get("categories_str", "").lower()
            )
            print(f"✅ Tab3取得完了: {len(articles_tab3)}件")
        except Exception as _e:
            print(f"⚠️ Tab3取得エラー（処理継続）: {_e}")

        # [v20260527_02_01] Step 4: 統合（Tab2→Tab1→Tab3の順で結合）
        print("🔗 [Step 4] 統合開始...")
        final_articles = articles_tab2 + articles_tab1 + articles_tab3
        self.articles  = final_articles

        if not final_articles:
            print("Auto-run completed: No articles found in any tab.")
            sys.exit(0)

        print(
            f"✅ 統合完了: Tab2={len(articles_tab2)}件 / "
            f"Tab1={len(articles_tab1)}件 / "
            f"Tab3={len(articles_tab3)}件 / "
            f"合計={len(final_articles)}件"
        )

        # [v20260527_02_01] Step 5: 要約レポート生成
        # section_map をレポートジェネレーターに渡してセクション区切りを生成する
        print("📊 [Step 5] 要約レポート生成開始...")
        section_map = {
            "tab2": len(articles_tab2),
            "tab1": len(articles_tab1),
            "tab3": len(articles_tab3),
        }

        summarize_result = self.summarizer.summarize_multiple(final_articles)
        if isinstance(summarize_result, tuple) and len(summarize_result) == 3:
            res_dict, cost_usd, cost_jpy = summarize_result
        else:
            res_dict, cost_usd, cost_jpy = summarize_result, 0.0, 0.0

        path = self.reporter.generate_report(
            final_articles,
            res_dict,
            cost_usd=cost_usd,
            cost_jpy=cost_jpy,
            summarizer=self.summarizer,
            section_map=section_map,      # [v20260527_02_01追加]
        )

        # Step 6: ブラウザを開く
        webbrowser.open(path)

        # Step 7: 自動既読化
        ai_urls    = [a['url'] for a in final_articles if a.get('source') == 'ai-feed']
        other_urls = [a['url'] for a in final_articles if a.get('source') != 'ai-feed']
        if ai_urls:
            self.feed_manager.mark_ai_feed_as_read(ai_urls)
        if other_urls:
            self.feed_manager.mark_as_read(other_urls)

        print(
            f"Auto-run completed: {len(final_articles)}件処理 / "
            f"Cost: ${cost_usd:.4f}"
        )

        # Step 8: 統合バッチ起動
        try:
            batch_path = r"C:\Users\nx023836\Documents\PythonScripts\RSS\start_consolidated_HTML_summary_manager.bat"
            subprocess.Popen(batch_path, shell=True)
        except Exception as e:
            print(f"Batch execution error: {e}")

        # Step 9: 終了
        sys.exit(0)

    def _on_closing(self):
        if self.articles:
            res = messagebox.askyesno("確認", "終了します。\n一覧にある全レポートを既読にしますか？")
            if res:
                self._mark_all_read(silent=True)
        self.root.destroy()

# ============================================================
# メイン実行ブロック
# ============================================================
if __name__ == "__main__":
    import sys
    root = tk.Tk()
    app = RSSManagerGUI(root)
    
    # -auto 引数がある場合はGUIを隠してステルス実行
    if "-auto" in sys.argv:
        root.withdraw()
        # Tkinterの初期化完了後に非同期でRPAプロセスを開始
        root.after(100, app._run_auto)
        
    root.mainloop()

            