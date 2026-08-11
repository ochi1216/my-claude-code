
"""
YouTube Play List Set up　System

バージョンはファイル名ではなくGitで管理する。
履歴は次で追える:
    git log --follow -- Youtube_Playlist_management.py
    git blame Youtube_Playlist_management.py
    git log -L :関数名:Youtube_Playlist_management.py
"""
# [20260808] VERSION = "2026.0707_02" を削除した。
# どこからも参照されていない未使用定数で、値もファイル名の版数
# (20260806_01) と食い違ったまま放置されていた。
# 実行中のファイルを特定する用途は、バッチが出力するスクリプトの
# 更新日時ログで代替する。

import sys
import os
import time
import re
import json
import pickle
import logging
import traceback
import platform
import webbrowser
import socket
import uuid
import hashlib
from datetime import datetime, timedelta
from functools import wraps, lru_cache
from collections import defaultdict
from pathlib import Path

# ==================== 並行処理・スレッド ====================
import concurrent.futures
import threading
from threading import Lock
from queue import Queue

# ==================== GUI (Tkinter) ====================
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, simpledialog

# ==================== Selenium (ブラウザ操作) ====================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# ==================== Google API & Cloud ====================
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import BatchHttpRequest
from google.oauth2 import service_account
from google.cloud import monitoring_v3

# ==================== その他サードパーティ ====================
import requests
import httplib2
import pytz
import psutil
import dateutil.parser

# ==================== ローカルモジュール ====================
from multi_project_manager import MultiProjectManager

# ==================== 翻訳機能 (新規追加) ====================
# deep-translatorがインストールされていない場合でも動作するように配慮
try:
    from deep_translator import GoogleTranslator
    TRANSLATION_AVAILABLE = True
except ImportError:
    TRANSLATION_AVAILABLE = False

# 翻訳対象のラベルと情報を保持するグローバル辞書
# キー: video_id, 値: {label: tk.Label, title: str, ...}
translation_targets = {}






# ===== 🆕 Phase 2-1: 設定外部化システム =====

# グローバル設定データ保持変数
CONFIG_DATA = {}
CONFIG_LOADED = False

# 設定ディレクトリのパス
CONFIG_DIR = Path("config")

def _resolve_summary_output_dir():
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


# 🆕 ショート動画サマリーHTML出力先（20260707_02_01）
SUMMARY_OUTPUT_DIR = _resolve_summary_output_dir()

# 🆕 ローカル重複管理システム
registered_videos_manager = None
CACHE_ENABLED = True

# 既存のグローバル変数の後に追加
PROJECT_MANAGER = None  # MultiProjectManagerインスタンス

print("=== チャンネルルール管理ツール ===")

VERSION = "20260703_01"

# ===== データ管理関数群 =====

def load_learned_channels_data():
    """学習チャンネルJSONデータ読み込み（channel_metadataも含む全データを返す）"""
    try:
        config_file = Path("learned_channels.json")
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)

            # 条件③: favorites キー欠如時は空リストをフォールバック
            raw_data["favorites"] = raw_data.get("favorites", [])

            if "channels" in raw_data:
                print(f"学習チャンネルデータ読み込み成功: {len(raw_data.get('channels', {}))}チャンネル")
                meta_count = len(raw_data.get("channel_metadata", {}))
                print(f"channel_metadata読み込み: {meta_count}チャンネル")
                fav_count = len(raw_data.get("favorites", []))
                print(f"favorites読み込み: {fav_count}件")
                return raw_data
            else:
                converted_data = {
                    "version": "1.0",
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "channels": {},
                    "channel_metadata": {},
                    "favorites": []
                }
                for channel_name, playlist in raw_data.items():
                    if isinstance(playlist, str) and playlist.strip():
                        converted_data["channels"][channel_name] = playlist.strip()
                    else:
                        print(f"警告: 無効なデータをスキップ - {channel_name}: {playlist}")
                print(f"シンプル形式から標準形式に変換: {len(converted_data['channels'])}チャンネル")
                return converted_data
        else:
            print("learned_channels.jsonが見つかりません")
            return {
                "version": "1.0",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "channels": {},
                "channel_metadata": {},
                "favorites": []
            }
    except json.JSONDecodeError as e:
        print(f"JSON形式エラー: {e}")
        messagebox.showerror("エラー", f"JSONファイルの形式が正しくありません:\n{e}")
        return {"version": "1.0", "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "channels": {}, "channel_metadata": {}, "favorites": []}
    except Exception as e:
        print(f"データ読み込みエラー: {e}")
        messagebox.showerror("エラー", f"データ読み込みに失敗しました:\n{e}")
        return {"version": "1.0", "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "channels": {}, "channel_metadata": {}, "favorites": []}


def save_learned_channels_data(data, favorites=None):
    """
    学習チャンネルJSONデータ保存。
    保存対象は channels と favorites のみ。
    既存ファイルの channel_metadata は上書きせず保持する。
    """
    try:
        if favorites is None:
            favorites = []

        config_file = Path("learned_channels.json")

        existing_metadata = {}
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            existing_metadata = existing.get("channel_metadata", {})

        save_data = {
            "version": data.get("version", "1.0"),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "channels": data.get("channels", {}),
            "channel_metadata": existing_metadata,
            "favorites": sorted(list(favorites))
        }

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        print(f"学習チャンネルデータ保存完了: {len(save_data.get('channels', {}))}チャンネル / favorites: {len(save_data['favorites'])}件")
        return True

    except Exception as e:
        print(f"データ保存エラー: {e}")
        messagebox.showerror("エラー", f"データ保存に失敗しました:\n{e}")
        return False


def backup_learned_channels():
    """学習チャンネルバックアップ作成"""
    try:
        config_file = Path("learned_channels.json")
        if config_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = Path(f"learned_channels_backup_{timestamp}.json")
            shutil.copy2(config_file, backup_file)
            print(f"バックアップ作成: {backup_file}")
            return backup_file
        return None
    except Exception as e:
        print(f"バックアップ作成エラー: {e}")
        return None


def get_default_playlist_config():
    """プレイリスト設定のデフォルト値を返す"""
    return {
        "V": "重要",
        "S": "技術",
        "A": "社会",
        "B": "資料",
        "M": "投資",
        "N": "報道",
        "L": "その他",
        "P+": "保管",
    }


# ===== チャンネルルール管理クラス =====

class ChannelRulesManager:
    def __init__(self):
        self.root = None

        # データ層（分離管理）
        self.data = {}           # channels のみ（保存対象）
        self.original_data = {}  # 変更検知用スナップショット
        self.metadata = {}       # channel_metadata（表示専用・保存しない）

        # フィルタ・検索
        self.current_filter = None
        self.search_keyword = ""

        # ページング
        self.current_page = 0
        self.items_per_page = 50   # 変更: 20 → 50

        # プレイリスト設定
        self.playlist_config = get_default_playlist_config()

        # ソート状態
        self.sort_column = None      # None / 'channel' / 'subscribers' / 'video' / 'frequency'
        self.sort_direction = None   # None / 'desc' / 'asc'

        # 選択管理（channel_name -> bool）
        self.check_states = {}
        self.show_selected_only = False

        # UI要素
        self.main_frame = None
        self.tree = None
        self.page_label = None
        self.search_entry = None
        self.page_entry = None
        self.prev_btn = None
        self.next_btn = None
        self.selected_only_btn = None

        # ポップアップ管理
        self.tooltip_window = None
        self.operation_popup = None
        self.move_dialog = None
        self.favorite_channels = set()

        # Treeview行管理（iid -> channel_name）
        self.tree_iid_map = {}
        self.tree_video_url_map = {}    # iid -> latest_video_url

        # 現在ページデータ
        self.current_channels = []

    # ===== 起動 =====

    def launch(self):
        """メイン画面起動"""
        try:
            print(f"チャンネルルール管理ツール起動中... VERSION={VERSION}")

            raw = load_learned_channels_data()

            self.data = {
                "version": raw.get("version", "1.0"),
                "last_updated": raw.get("last_updated", ""),
                "channels": raw.get("channels", {})
            }
            self.original_data = json.loads(json.dumps(self.data))

            # channel_metadata は self.metadata に独立保持
            self._load_metadata(raw)

            # favorites を self.favorite_channels に復元
            raw_favorites = raw.get("favorites", [])
            self.favorite_channels = set(raw_favorites)
            print(f"favorites復元: {len(self.favorite_channels)}件")

            if not self.data.get("channels"):
                print("学習チャンネルデータが空です")

            self.create_window()
            print("チャンネルルール管理ツール起動完了")

        except Exception as e:
            print(f"起動エラー: {e}")
            messagebox.showerror("エラー", f"ツール起動に失敗しました:\n{e}")


    def _load_metadata(self, raw_data):
        """channel_metadata を self.metadata に独立保持"""
        try:
            self.metadata = raw_data.get("channel_metadata", {})
            print(f"channel_metadata独立保持: {len(self.metadata)}チャンネル")
        except Exception as e:
            print(f"metadata読み込みエラー: {e}")
            self.metadata = {}

    # ===== データマージ・変換 =====

    def _merge_channel_metadata(self, channel_name):
        """
        チャンネル名キーで channels + channel_metadata を突合し、
        1チャンネル分の統合dictを返す（独立マージ関数）。
        """
        try:
            channels = self.data.get("channels", {})
            playlist = channels.get(channel_name, "未設定")
            meta = self.metadata.get(channel_name, {})

            metrics = meta.get("metrics", {})
            history = meta.get("history", {})
            observed_videos = history.get("observed_videos", [])

            # 最新動画タイトル・URL（observed_at 降順ソート先頭）
            latest_video_title = ""
            latest_video_url = ""
            if observed_videos:
                sorted_videos = sorted(
                    observed_videos,
                    key=lambda v: v.get("observed_at", ""),
                    reverse=True
                )
                latest_video_title = sorted_videos[0].get("title", "")
                video_id = sorted_videos[0].get("video_id", "")
                if video_id:
                    latest_video_url = f"https://www.youtube.com/watch?v={video_id}"

            # 過去7日間の更新頻度
            frequency = self._calc_frequency(observed_videos)

            return {
                "channel_name": channel_name,
                "playlist": playlist,
                "subscriber_count": metrics.get("subscriber_count", None),
                "latest_video_title": latest_video_title,
                "latest_video_url": latest_video_url,
                "frequency": frequency,
                "last_updated": history.get("last_updated", ""),
                "observed_videos": observed_videos,
                "video_store_count": len(observed_videos),
                "has_metadata": bool(meta)
            }
        except Exception as e:
            print(f"マージエラー ({channel_name}): {e}")
            return {
                "channel_name": channel_name,
                "playlist": self.data.get("channels", {}).get(channel_name, "未設定"),
                "subscriber_count": None,
                "latest_video_title": "",
                "latest_video_url": "",
                "frequency": None,
                "last_updated": "",
                "observed_videos": [],
                "video_store_count": 0,
                "has_metadata": False
            }

    def _calc_frequency(self, observed_videos):
        """過去7日間の動画件数を計算"""
        try:
            if not observed_videos:
                return None
            cutoff = datetime.now() - timedelta(days=7)
            count = 0
            for v in observed_videos:
                ts = v.get("observed_at", "")
                if ts:
                    try:
                        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                        if dt >= cutoff:
                            count += 1
                    except ValueError:
                        pass
            return count
        except Exception as e:
            print(f"頻度計算エラー: {e}")
            return None

    def _format_subscribers(self, count):
        """登録者数を K/M 表記に変換"""
        if count is None:
            return "--"
        try:
            count = int(count)
            if count >= 1_000_000:
                return f"{count / 1_000_000:.1f}M"
            elif count >= 10_000:
                return f"{count / 1_000:.1f}K"
            else:
                return f"{count:,}"
        except Exception:
            return "--"

    def _format_frequency(self, frequency):
        """更新頻度を表示形式に変換"""
        if frequency is None:
            return "--"
        return f"{frequency}本/週"

    def _truncate(self, text, max_chars):
        """
        テキストを max_chars 文字で切り詰め（全角=2文字分カウント）。
        """
        if not text:
            return ""
        count = 0
        result = []
        for ch in text:
            w = 2 if ord(ch) > 0x7F else 1
            if count + w > max_chars * 2:
                result.append("…")
                break
            result.append(ch)
            count += w
        return "".join(result)

    # ===== ウィンドウ作成 =====

    def create_window(self):
        """ウィンドウ作成"""
        try:
            self.root = tk.Toplevel()
            self.root.title(f"🎯 学習チャンネル管理ツール v{VERSION}")
            self.root.geometry("1400x900")

            self.root.update_idletasks()
            x = (self.root.winfo_screenwidth() // 2) - (self.root.winfo_width() // 2)
            y = (self.root.winfo_screenheight() // 2) - (self.root.winfo_height() // 2)
            self.root.geometry(f"+{x}+{y}")

            self.current_filter = tk.StringVar()
            self.current_filter.set("全体")

            self.main_frame = ttk.Frame(self.root)
            self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

            self.create_header()
            self.create_operation_bar()
            self.create_filter_tabs()
            self.create_search_section()
            self.create_paging_info()
            self.create_treeview()
            self.create_paging_buttons()
            self.create_operation_buttons()

            self.update_display()
            self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)

        except Exception as e:
            print(f"ウィンドウ作成エラー: {e}")
            messagebox.showerror("エラー", f"ウィンドウ作成に失敗しました:\n{e}")


    def create_header(self):
        """ヘッダー作成"""
        total_channels = len(self.data.get('channels', {}))
        meta_count = len(self.metadata)

        playlist_counts = {}
        for channel_name, playlist in self.data.get('channels', {}).items():
            playlist_counts[playlist] = playlist_counts.get(playlist, 0) + 1

        header_text = (f"🎯 学習チャンネル管理ツール v{VERSION}"
                       f"  総チャンネル数: {total_channels}個"
                       f"  メタデータ保有: {meta_count}個")
        header_label = tk.Label(
            self.main_frame, text=header_text,
            font=tkfont.Font(family="Meiryo", size=14, weight="bold"),
            bg="#e8f4fd", relief="ridge", bd=2, pady=8
        )
        header_label.pack(fill="x", pady=(0, 5))

        if playlist_counts:
            stats_frame = tk.Frame(self.main_frame, bg="#f0f8ff", relief="ridge", bd=1)
            stats_frame.pack(fill="x", pady=(0, 5))
            stats_text = "プレイリスト別:  "
            for playlist in self.playlist_config.keys():
                count = playlist_counts.get(playlist, 0)
                desc = self.playlist_config.get(playlist, playlist)
                stats_text += f"{playlist}({desc}): {count}個   "
            tk.Label(
                stats_frame, text=stats_text,
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#f0f8ff", pady=4
            ).pack()




    def create_operation_bar(self):
        """上部操作バー作成（全選択・全解除・選択のみ表示・お気に入り・反転）"""
        try:
            bar_frame = tk.Frame(self.main_frame, bg="#e8ffe8", relief="ridge", bd=1)
            bar_frame.pack(fill="x", pady=(0, 5))

            tk.Label(
                bar_frame, text="チェックボックス操作:",
                bg="#e8ffe8",
                font=tkfont.Font(family="Meiryo", size=10)
            ).pack(side="left", padx=(10, 5))

            tk.Button(
                bar_frame, text="✅ 全選択（現ページ）",
                command=self.select_current_page,
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#90EE90"
            ).pack(side="left", padx=(0, 5), pady=3)

            tk.Button(
                bar_frame, text="❌ 全解除",
                command=self.deselect_all,
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#FFB6C1"
            ).pack(side="left", padx=(0, 5), pady=3)

            tk.Button(
                bar_frame, text="🔄 選択を反転",
                command=self.toggle_selection_invert,
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#DDA0DD"
            ).pack(side="left", padx=(0, 5), pady=3)

            self.selected_only_btn = tk.Button(
                bar_frame, text="👁️ 選択のみ表示",
                command=self.toggle_selected_only,
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#87CEEB"
            )
            self.selected_only_btn.pack(side="left", padx=(0, 5), pady=3)

            tk.Button(
                bar_frame, text="★ お気に入り登録",
                command=self.execute_bulk_favorite,
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#FFD700"
            ).pack(side="left", padx=(0, 5), pady=3)

        except Exception as e:
            print(f"操作バー作成エラー: {e}")


    def toggle_selection_invert(self):
        """現在ページの選択状態を反転"""
        try:
            if not self.current_channels:
                return
            for ch in self.current_channels:
                name = ch["channel_name"]
                self.check_states[name] = not self.check_states.get(name, False)
            self.display_current_page()
            selected_count = sum(1 for v in self.check_states.values() if v)
            print(f"選択反転完了: 現在選択数={selected_count}件")
        except Exception as e:
            print(f"選択反転エラー: {e}")


    def toggle_selected_only(self):
        """選択のみ表示トグル"""
        try:
            self.show_selected_only = not self.show_selected_only
            if self.show_selected_only:
                self.selected_only_btn.config(bg="#FFA500", text="👁️ 選択のみ [ON]")
                print("選択のみ表示: ON")
            else:
                self.selected_only_btn.config(bg="#87CEEB", text="👁️ 選択のみ表示")
                print("選択のみ表示: OFF")
            self.current_page = 0
            self.update_display()
        except Exception as e:
            print(f"選択のみ表示トグルエラー: {e}")


    def create_filter_tabs(self):
        """フィルタータブ作成"""
        try:
            tab_frame = tk.Frame(self.main_frame, bg="#f0f0f0", relief="ridge", bd=1)
            tab_frame.pack(fill="x", pady=(0, 5))

            tk.Label(
                tab_frame, text="フィルタ:",
                bg="#f0f0f0",
                font=tkfont.Font(family="Meiryo", size=10)
            ).pack(side="left", padx=(10, 5))

            filter_options = ["全体", "★"] + list(self.playlist_config.keys()) + ["未設定"]

            for option in filter_options:
                if option == "★":
                    label = "★ お気に入り"
                    bg_color = "#FFD700"
                elif option == "全体":
                    label = "全体"
                    bg_color = "#f0f0f0"
                elif option == "未設定":
                    label = "未設定"
                    bg_color = "#f0f0f0"
                else:
                    desc = self.playlist_config.get(option, option)
                    label = f"{option} {desc}"
                    bg_color = "#f0f0f0"

                tk.Radiobutton(
                    tab_frame,
                    text=label,
                    variable=self.current_filter,
                    value=option,
                    command=self.on_filter_change,
                    bg=bg_color,
                    font=tkfont.Font(family="Meiryo", size=10),
                    indicatoron=True
                ).pack(side="left", padx=2, pady=3)

        except Exception as e:
            print(f"フィルタータブ作成エラー: {e}")


    def create_search_section(self):
        """検索セクション作成"""
        try:
            search_frame = tk.LabelFrame(
                self.main_frame, text="チャンネル検索",
                font=tkfont.Font(family="Meiryo", size=12, weight="bold"),
                bg="#f0f8ff", pady=5
            )
            search_frame.pack(fill="x", pady=(0, 5))

            input_frame = tk.Frame(search_frame, bg="#f0f8ff")
            input_frame.pack(fill="x", padx=10)

            tk.Label(
                input_frame, text="🔍 検索キーワード:", bg="#f0f8ff",
                font=tkfont.Font(family="Meiryo", size=10)
            ).pack(side="left", padx=(0, 5))

            self.search_entry = tk.Entry(
                input_frame, width=30,
                font=tkfont.Font(family="Meiryo", size=10)
            )
            self.search_entry.pack(side="left", padx=(0, 10))
            self.search_entry.bind("<Return>", lambda event: self.search_channels())

            tk.Button(
                input_frame, text="🔍 検索",
                command=self.search_channels,
                font=tkfont.Font(family="Meiryo", size=10), bg="#87CEEB"
            ).pack(side="left", padx=(0, 5))

            tk.Button(
                input_frame, text="❌ クリア",
                command=self.clear_search,
                font=tkfont.Font(family="Meiryo", size=10), bg="#FFB6C1"
            ).pack(side="left")

        except Exception as e:
            print(f"検索セクション作成エラー: {e}")

    def create_paging_info(self):
        """ページング情報ラベル作成"""
        paging_frame = ttk.Frame(self.main_frame)
        paging_frame.pack(fill="x", pady=(0, 3))

        self.page_label = tk.Label(
            paging_frame, text="",
            font=tkfont.Font(family="Meiryo", size=10),
            bg="#f0f8ff", relief="solid", bd=1, pady=3
        )
        self.page_label.pack(fill="x")


    def create_treeview(self):
        """ttk.Treeview テーブル作成。"""
        try:
            tree_frame = ttk.Frame(self.main_frame)
            tree_frame.pack(fill="both", expand=True)

            style = ttk.Style()
            style.configure("Treeview",
                font=("Meiryo", 11),
                rowheight=26
            )
            style.configure("Treeview.Heading",
                font=("Meiryo", 11, "bold")
            )

            columns = ("favorite", "check", "rank", "channel", "subscribers", "video", "frequency", "video_store")

            self.tree = ttk.Treeview(
                tree_frame,
                columns=columns,
                show="headings",
                selectmode="none"
            )

            # 条件①: favorite列を先頭に追加。以降の列は全てindexが+1シフト
            col_configs = [
                ("favorite",    "★",              40,  "center"),
                ("check",       "☐",              42,  "center"),
                ("rank",        "#  ▲▼",           55,  "center"),
                ("channel",     "チャンネル名 ▲▼", 200, "w"),
                ("subscribers", "👥 登録者数 ▲▼",  100, "e"),
                ("video",       "📹 最新動画 ▲▼",  230, "w"),
                ("frequency",   "🔄 更新/週 ▲▼",   90,  "center"),
                ("video_store", "📦 保有数 ▲▼",     70,  "center"),
            ]

            for col_id, heading, width, anchor in col_configs:
                self.tree.heading(
                    col_id, text=heading,
                    command=lambda c=col_id: self.on_header_click(c)
                )
                self.tree.column(col_id, width=width, anchor=anchor, stretch=False)

            vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=vsb.set)

            self.tree.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")

            self.tree.bind("<Button-1>",  self.on_tree_click)
            self.tree.bind("<Motion>",    self.on_tree_motion)
            self.tree.bind("<Leave>",     self.on_tree_leave)

            self.tree.tag_configure("checked",   background="#e8f5e9")
            self.tree.tag_configure("unchecked", background="white")
            self.tree.tag_configure("highlight", background="#ffffcc")
            self.tree.tag_configure("has_meta",  foreground="blue")
            self.tree.tag_configure("no_meta",   foreground="black")
            self.tree.tag_configure("favorite",  foreground="#B8860B")

        except Exception as e:
            print(f"Treeview作成エラー: {e}")


    def create_paging_buttons(self):
        """ページングボタン作成"""
        paging_frame = ttk.Frame(self.main_frame)
        paging_frame.pack(fill="x", pady=5)

        left_frame = ttk.Frame(paging_frame)
        left_frame.pack(side="left")

        self.prev_btn = tk.Button(
            left_frame, text="◀ 前のページ",
            command=self.prev_page,
            font=tkfont.Font(family="Meiryo", size=10)
        )
        self.prev_btn.pack(side="left", padx=(0, 10))

        self.next_btn = tk.Button(
            left_frame, text="次のページ ▶",
            command=self.next_page,
            font=tkfont.Font(family="Meiryo", size=10)
        )
        self.next_btn.pack(side="left", padx=(0, 20))

        tk.Label(
            left_frame, text="ページ:",
            font=tkfont.Font(family="Meiryo", size=10)
        ).pack(side="left", padx=(0, 5))

        self.page_entry = tk.Entry(left_frame, width=5)
        self.page_entry.pack(side="left", padx=(0, 5))

        tk.Button(
            left_frame, text="移動",
            command=self.go_to_page,
            font=tkfont.Font(family="Meiryo", size=9)
        ).pack(side="left")

    def create_operation_buttons(self):
        """操作ボタン作成（一括削除・一括移動・保存・キャンセル・終了）"""
        try:
            button_frame = ttk.Frame(self.main_frame)
            button_frame.pack(fill="x", pady=(5, 0))

            left_frame = ttk.Frame(button_frame)
            left_frame.pack(side="left")

            ttk.Button(
                left_frame, text="🗑️ 選択項目を削除",
                command=self.execute_bulk_delete, width=18
            ).pack(side="left", padx=(0, 5))

            ttk.Button(
                left_frame, text="📂 選択項目を移動",
                command=self.execute_bulk_move, width=18
            ).pack(side="left", padx=(0, 5))

            right_frame = ttk.Frame(button_frame)
            right_frame.pack(side="right")

            ttk.Button(
                right_frame, text="💾 保存",
                command=self.save_changes, width=12
            ).pack(side="left", padx=(5, 0))

            ttk.Button(
                right_frame, text="↩️ キャンセル",
                command=self.cancel_changes, width=12
            ).pack(side="left", padx=(5, 0))

            ttk.Button(
                right_frame, text="❌ 終了",
                command=self.on_window_close, width=10
            ).pack(side="left", padx=(5, 0))

        except Exception as e:
            print(f"ボタン作成エラー: {e}")


    # ===== データ取得・ソート =====


    def get_filtered_channels(self, selected_only=False):
        """フィルタ・検索・選択のみ表示・ソートを適用したチャンネルリストを返す。"""
        try:
            current_filter = self.current_filter.get()
            channels = self.data.get("channels", {})

            filtered = []
            for channel_name, playlist in channels.items():

                # ★フィルタ（条件④: 0件時は空リスト → 既存空表示処理で吸収）
                if current_filter == "★":
                    include = channel_name in self.favorite_channels
                elif current_filter == "全体":
                    include = True
                elif current_filter == "未設定":
                    include = (playlist == "未設定" or playlist not in self.playlist_config)
                else:
                    include = (playlist == current_filter)

                if include and self.search_keyword:
                    include = self.search_keyword.lower() in channel_name.lower()

                if include and selected_only:
                    include = self.check_states.get(channel_name, False)

                if include:
                    filtered.append(self._merge_channel_metadata(channel_name))

            filtered = self._sort_channels(filtered)
            return filtered

        except Exception as e:
            print(f"チャンネルフィルタエラー: {e}")
            return []


    def _sort_channels(self, channels):
        """ソートカラムと方向に従ってチャンネルリストをソート"""
        try:
            col = self.sort_column
            direction = self.sort_direction

            # デフォルト: チャンネル名A→Z
            if col is None or direction is None:
                return sorted(channels, key=lambda x: x["channel_name"].lower())

            reverse = (direction == "desc")

            def sort_key(ch):
                if col == "channel":
                    return (0, ch["channel_name"].lower())
                elif col == "subscribers":
                    v = ch.get("subscriber_count")
                    # データなしは最小値扱い（昇順:先頭 / 降順:末尾）
                    return float('-inf') if v is None else float(v)
                elif col == "video":
                    return (0, ch.get("latest_video_title", "").lower())
                elif col == "frequency":
                    v = ch.get("frequency")
                    # データなしは最小値扱い（昇順:先頭 / 降順:末尾）
                    return float('-inf') if v is None else float(v)
                elif col == "video_store":
                    v = ch.get("video_store_count")
                    # データなしは最小値扱い（昇順:先頭 / 降順:末尾）
                    return float('-inf') if v is None else float(v)
                else:
                    return (0, ch["channel_name"].lower())

            return sorted(channels, key=sort_key, reverse=reverse)

        except Exception as e:
            print(f"ソートエラー: {e}")
            return channels

    def on_header_click(self, column):
        """
        カラムヘッダークリック処理。
        降順▼ → 昇順▲ → デフォルト(None) の3段階サイクル。
        ソート変更時は1ページ目にリセット。
        """
        try:
            if column in ("check", "rank"):
                return  # チェック列・ランク列はソート対象外

            if self.sort_column != column:
                # 別カラム選択: 降順から開始
                self.sort_column = column
                self.sort_direction = "desc"
            else:
                # 同カラム: 3段階サイクル
                if self.sort_direction == "desc":
                    self.sort_direction = "asc"
                elif self.sort_direction == "asc":
                    self.sort_column = None
                    self.sort_direction = None

            self._update_header_labels()
            self.current_page = 0
            self.update_display()
            print(f"ソート変更: {self.sort_column} {self.sort_direction}")

        except Exception as e:
            print(f"ヘッダークリックエラー: {e}")

    def _update_header_labels(self):
        """ソート状態をヘッダーテキストに反映"""
        try:
            base_labels = {
                "check":       "☐",
                "rank":        "#",
                "channel":     "チャンネル名",
                "subscribers": "👥 登録者数",
                "video":       "📹 最新動画",
                "frequency":   "🔄 更新/週",
                "video_store": "📦 保有数",
            }
            for col_id, base in base_labels.items():
                if col_id in ("check", "rank"):
                    self.tree.heading(col_id, text=base)
                    continue
                if self.sort_column == col_id:
                    suffix = " ▼" if self.sort_direction == "desc" else " ▲"
                else:
                    suffix = " ▲▼"
                self.tree.heading(
                    col_id, text=base + suffix,
                    command=lambda c=col_id: self.on_header_click(c)
                )
        except Exception as e:
            print(f"ヘッダーラベル更新エラー: {e}")

    # ===== 表示更新 =====

    def update_display(self):
        """表示更新（フィルタ・ソート・ページング反映）"""
        try:
            all_channels = self.get_filtered_channels(selected_only=self.show_selected_only)

            total_channels = len(all_channels)
            total_pages = max(1, (total_channels + self.items_per_page - 1) // self.items_per_page)

            if self.current_page >= total_pages:
                self.current_page = max(0, total_pages - 1)

            start_idx = self.current_page * self.items_per_page
            end_idx = min(start_idx + self.items_per_page, total_channels)

            filter_name = self.current_filter.get()
            search_info = f" | 検索: '{self.search_keyword}'" if self.search_keyword else ""
            selected_info = " | 選択のみ表示" if self.show_selected_only else ""
            sort_info = (f" | ソート: {self.sort_column}"
                         f" {'▼' if self.sort_direction == 'desc' else '▲'}"
                         if self.sort_column else "")

            page_info = (
                f"フィルタ: {filter_name}{search_info}{selected_info}{sort_info}"
                f"  |  ページ {self.current_page + 1}/{total_pages}"
                f"  ({start_idx + 1}-{end_idx} / {total_channels}件)"
            )
            self.page_label.config(text=page_info)

            self.prev_btn.config(state="normal" if self.current_page > 0 else "disabled")
            self.next_btn.config(state="normal" if self.current_page < total_pages - 1 else "disabled")

            self.current_channels = all_channels[start_idx:end_idx]
            self.display_current_page()

        except Exception as e:
            print(f"表示更新エラー: {e}")
            messagebox.showerror("エラー", f"表示更新に失敗しました:\n{e}")



    def display_current_page(self):
        """現在ページのチャンネルを Treeview に表示"""
        try:
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            self.tree_iid_map.clear()
            self.tree_video_url_map.clear()

            if not self.current_channels:
                if self.search_keyword:
                    msg = f"検索キーワード '{self.search_keyword}' に一致するチャンネルがありません"
                elif self.show_selected_only:
                    msg = "選択中のチャンネルがありません"
                elif self.current_filter.get() == "★":
                    msg = "お気に入りチャンネルがありません"
                else:
                    msg = "表示するチャンネルがありません"
                self.tree.insert("", "end", values=(msg, "", "", "", "", "", "", ""))
                return

            global_offset = self.current_page * self.items_per_page

            for idx, ch in enumerate(self.current_channels):
                channel_name = ch["channel_name"]
                rank = global_offset + idx + 1
                checked = self.check_states.get(channel_name, False)
                is_favorite = channel_name in self.favorite_channels

                fav_char   = "★" if is_favorite else "☆"
                check_char = "☑" if checked else "☐"

                ch_display   = self._truncate(channel_name, 30)
                sub_display  = self._format_subscribers(ch.get("subscriber_count"))
                vid_display  = self._truncate(ch.get("latest_video_title", ""), 100)
                freq_display = self._format_frequency(ch.get("frequency"))
                store_count  = ch.get("video_store_count", 0)
                store_display = f"{store_count}件" if ch.get("has_metadata") else "--"

                tags = ["checked" if checked else "unchecked"]
                if self.search_keyword and self.search_keyword.lower() in channel_name.lower():
                    tags.append("highlight")
                if ch.get("has_metadata"):
                    tags.append("has_meta")
                else:
                    tags.append("no_meta")
                if is_favorite:
                    tags.append("favorite")

                iid = self.tree.insert(
                    "", "end",
                    values=(fav_char, check_char, rank, ch_display, sub_display, vid_display, freq_display, store_display),
                    tags=tuple(tags)
                )
                self.tree_iid_map[iid] = channel_name
                self.tree_video_url_map[iid] = ch.get("latest_video_url", "")

        except Exception as e:
            print(f"ページ表示エラー: {e}")





    # ===== イベント処理 =====


    def on_tree_click(self, event):
        """
        Treeview クリックイベント。
        favorite列（#1）: ★トグル
        check列（#2）   : チェック状態トグル
        channel列（#4） : 操作ポップアップ表示
        video列（#6）   : ブラウザでYouTube起動
        """
        try:
            region = self.tree.identify_region(event.x, event.y)
            if region != "cell":
                return

            col = self.tree.identify_column(event.x)
            iid = self.tree.identify_row(event.y)
            if not iid or iid not in self.tree_iid_map:
                return

            channel_name = self.tree_iid_map[iid]
            col_index = int(col.replace("#", "")) - 1   # 0-indexed

            if col_index == 0:
                # favorite列: ★トグル
                self._toggle_favorite(iid, channel_name)
            elif col_index == 1:
                # check列: チェックボックストグル
                self._toggle_check(iid, channel_name)
            elif col_index == 3:
                # channel列: 操作ポップアップ
                self.show_operation_popup(channel_name)
            elif col_index == 5:
                # video列: ブラウザでYouTube起動
                url = self.tree_video_url_map.get(iid, "")
                if url:
                    webbrowser.open(url)

        except Exception as e:
            print(f"Treeviewクリックエラー: {e}")



    def _toggle_check(self, iid, channel_name):
        """チェック状態トグルと Treeview 行の即時更新"""
        try:
            current = self.check_states.get(channel_name, False)
            new_state = not current
            self.check_states[channel_name] = new_state

            values = list(self.tree.item(iid, "values"))
            values[0] = "☑" if new_state else "☐"

            current_tags = list(self.tree.item(iid, "tags"))
            for t in ("checked", "unchecked"):
                if t in current_tags:
                    current_tags.remove(t)
            current_tags.insert(0, "checked" if new_state else "unchecked")

            self.tree.item(iid, values=values, tags=tuple(current_tags))

        except Exception as e:
            print(f"チェックトグルエラー: {e}")


    def _toggle_favorite(self, iid, channel_name):
        """★お気に入りトグルとTreeview行の即時更新"""
        try:
            if channel_name in self.favorite_channels:
                self.favorite_channels.discard(channel_name)
                new_fav = False
            else:
                self.favorite_channels.add(channel_name)
                new_fav = True

            values = list(self.tree.item(iid, "values"))
            values[0] = "★" if new_fav else "☆"

            current_tags = list(self.tree.item(iid, "tags"))
            if "favorite" in current_tags:
                current_tags.remove("favorite")
            if new_fav:
                current_tags.append("favorite")

            self.tree.item(iid, values=values, tags=tuple(current_tags))
            print(f"お気に入り{'登録' if new_fav else '解除'}: {channel_name}")

        except Exception as e:
            print(f"お気に入りトグルエラー: {e}")


    def execute_bulk_favorite(self):
        """選択チャンネルを一括でお気に入り登録"""
        try:
            selected = [ch for ch, v in self.check_states.items() if v]
            if not selected:
                messagebox.showinfo("情報", "お気に入り登録するチャンネルが選択されていません。")
                return
            for ch in selected:
                self.favorite_channels.add(ch)
            print(f"一括お気に入り登録完了: {len(selected)}件")
            messagebox.showinfo("完了", f"{len(selected)}件をお気に入りに登録しました。\n\n「💾 保存」ボタンで確定してください。")
            self.check_states.clear()
            self.update_display()
        except Exception as e:
            print(f"一括お気に入り登録エラー: {e}")
            messagebox.showerror("エラー", f"一括お気に入り登録に失敗しました:\n{e}")

    def on_tree_motion(self, event):
        """マウスホバー：動画タイトル列（#5）でOSネイティブ風ツールチップ表示"""
        try:
            region = self.tree.identify_region(event.x, event.y)
            if region != "cell":
                self.hide_tooltip()
                return

            col = self.tree.identify_column(event.x)
            col_index = int(col.replace("#", "")) - 1   # 0-indexed

            if col_index != 4:   # 動画タイトル列
                self.hide_tooltip()
                return

            iid = self.tree.identify_row(event.y)
            if not iid or iid not in self.tree_iid_map:
                self.hide_tooltip()
                return

            channel_name = self.tree_iid_map[iid]
            ch = self._merge_channel_metadata(channel_name)
            full_title = ch.get("latest_video_title", "")

            if full_title:
                self.show_tooltip(full_title, event.x_root + 12, event.y_root + 12)
            else:
                self.hide_tooltip()

        except Exception:
            self.hide_tooltip()

    def on_tree_leave(self, event):
        """マウスが Treeview を離れた際にツールチップ非表示"""
        self.hide_tooltip()

    def show_tooltip(self, text, x, y):
        """OSネイティブ風ツールチップ表示（黄色背景・黒文字）"""
        try:
            self.hide_tooltip()
            self.tooltip_window = tk.Toplevel(self.root)
            self.tooltip_window.wm_overrideredirect(True)
            self.tooltip_window.wm_geometry(f"+{x}+{y}")
            tk.Label(
                self.tooltip_window, text=text,
                background="#ffffe0", relief="solid", bd=1,
                font=tkfont.Font(family="Meiryo", size=9),
                padx=5, pady=3
            ).pack()
        except Exception:
            pass

    def hide_tooltip(self):
        """ツールチップ非表示"""
        try:
            if self.tooltip_window:
                self.tooltip_window.destroy()
                self.tooltip_window = None
        except Exception:
            pass

    # ===== 操作ポップアップ =====

    def show_operation_popup(self, channel_name):
        """
        チャンネル名列クリック時の統合操作ポップアップ。
        プレイリスト変更・削除・登録者数・動画リストを一画面に統合。
        詳細ボタンは廃止し本ウィンドウに情報を直接表示。
        """
        try:
            if self.operation_popup and self.operation_popup.winfo_exists():
                self.operation_popup.destroy()

            channels = self.data.get("channels", {})
            current_playlist = channels.get(channel_name, "未設定")
            playlist_desc = self.playlist_config.get(current_playlist, current_playlist)
            ch = self._merge_channel_metadata(channel_name)
            sub_display = self._format_subscribers(ch.get("subscriber_count"))
            freq_display = self._format_frequency(ch.get("frequency"))
            observed_videos = ch.get("observed_videos", [])

            popup = tk.Toplevel(self.root)
            popup.title(f"チャンネル操作 - {channel_name}")
            popup.geometry("600x650")
            popup.transient(self.root)
            popup.grab_set()
            popup.resizable(True, True)
            popup.minsize(500, 400)
            self.operation_popup = popup

            # ── タイトル行 ──
            tk.Label(
                popup,
                text=f"🎯  {channel_name}",
                font=tkfont.Font(family="Meiryo", size=12, weight="bold"),
                anchor="w", pady=8
            ).pack(fill="x", padx=12)

            tk.Label(
                popup,
                text=f"現在のプレイリスト:  {current_playlist} ({playlist_desc})",
                font=tkfont.Font(family="Meiryo", size=10),
                fg="blue", anchor="w"
            ).pack(fill="x", padx=12)

            # ── プレイリスト変更 ──
            pl_frame = tk.LabelFrame(
                popup, text="🎯 プレイリスト変更",
                font=tkfont.Font(family="Meiryo", size=10)
            )
            pl_frame.pack(fill="x", padx=12, pady=6)

            target_var = tk.StringVar(value="変更しない")

            tk.Radiobutton(
                pl_frame, text="変更しない",
                variable=target_var, value="変更しない",
                font=tkfont.Font(family="Meiryo", size=10)
            ).pack(side="left", padx=5)

            for pl_name in self.playlist_config.keys():
                if pl_name != current_playlist:
                    tk.Radiobutton(
                        pl_frame, text=pl_name,
                        variable=target_var, value=pl_name,
                        font=tkfont.Font(family="Meiryo", size=10)
                    ).pack(side="left", padx=4)

            # ── ボタン行（詳細ボタン廃止）──
            btn_frame = tk.Frame(popup)
            btn_frame.pack(fill="x", padx=12, pady=6)

            def apply_and_close():
                target = target_var.get()
                if target != "変更しない":
                    self.data["channels"][channel_name] = target
                    print(f"プレイリスト変更: {channel_name} → {target}")
                    self.update_display()
                popup.destroy()

            tk.Button(
                btn_frame, text="✅ 適用",
                command=apply_and_close,
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#90EE90", width=10
            ).pack(side="left", padx=(0, 5))

            tk.Button(
                btn_frame, text="🗑️ 削除",
                command=lambda: self._popup_delete(channel_name, popup),
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#ffebee", width=10
            ).pack(side="left", padx=(0, 5))

            tk.Button(
                btn_frame, text="閉じる",
                command=popup.destroy,
                font=tkfont.Font(family="Meiryo", size=10),
                width=10
            ).pack(side="left")

            # ── 登録者数・更新頻度 ──
            ttk.Separator(popup, orient="horizontal").pack(fill="x", padx=10, pady=(6, 0))

            tk.Label(
                popup,
                text=f"👥 登録者数: {sub_display}        🔄 更新頻度: {freq_display}（過去7日間）",
                font=tkfont.Font(family="Meiryo", size=10),
                anchor="w"
            ).pack(fill="x", padx=12, pady=(4, 0))

            # ── 動画リスト ──
            ttk.Separator(popup, orient="horizontal").pack(fill="x", padx=10, pady=(4, 0))

            video_count = len(observed_videos)
            tk.Label(
                popup,
                text=f"📋 取得済み動画リスト  ({video_count}件)",
                font=tkfont.Font(family="Meiryo", size=11, weight="bold"),
                anchor="w"
            ).pack(anchor="w", padx=12, pady=(4, 0))

            # スクロール可能エリア
            list_frame = tk.Frame(popup)
            list_frame.pack(fill="both", expand=True, padx=10, pady=5)

            canvas = tk.Canvas(list_frame)
            vsb = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
            inner = tk.Frame(canvas)

            inner.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            canvas.create_window((0, 0), window=inner, anchor="nw")
            canvas.configure(yscrollcommand=vsb.set)

            canvas.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")

            if observed_videos:
                sorted_videos = sorted(
                    observed_videos,
                    key=lambda v: v.get("observed_at", ""),
                    reverse=True
                )
                for v in sorted_videos:
                    video_id = v.get("video_id", "")
                    title = v.get("title", "（タイトル不明）")
                    observed_at = v.get("observed_at", "")
                    url = (f"https://www.youtube.com/watch?v={video_id}"
                           if video_id else "")

                    # 1動画1行: 日付ラベル + タイトルリンクを横並び
                    row = tk.Frame(inner)
                    row.pack(fill="x", padx=5, pady=2)

                    tk.Label(
                        row,
                        text=f"📅 {observed_at}",
                        font=tkfont.Font(family="Meiryo", size=10),
                        fg="#666666", anchor="w", width=22
                    ).pack(side="left", padx=(0, 8))

                    if url:
                        link = tk.Label(
                            row,
                            text=f"🔗 {title}",
                            font=tkfont.Font(family="Meiryo", size=10, underline=True),
                            fg="blue", cursor="hand2", anchor="w"
                        )
                        link.pack(side="left", fill="x", expand=True)
                        # ButtonRelease-1: Button-1のCanvas競合を回避（URLバグ修正）
                        link.bind("<ButtonRelease-1>", lambda e, u=url: webbrowser.open(u))
                    else:
                        tk.Label(
                            row,
                            text=f"  {title}",
                            font=tkfont.Font(family="Meiryo", size=10),
                            anchor="w"
                        ).pack(side="left", fill="x", expand=True)
            else:
                tk.Label(
                    inner,
                    text="📊  動画データ未収集",
                    font=tkfont.Font(family="Meiryo", size=11),
                    fg="#aaaaaa"
                ).pack(pady=20)

        except Exception as e:
            print(f"操作ポップアップエラー: {e}")
            messagebox.showerror("エラー", f"操作ポップアップに失敗しました:\n{e}")


    def _popup_delete(self, channel_name, popup):
        """ポップアップからのチャンネル削除"""
        try:
            if messagebox.askyesno(
                "確認",
                f"チャンネル「{channel_name}」を削除しますか？\n\n"
                "この操作は「変更を保存」するまで確定されません。",
                parent=popup
            ):
                self.delete_channel_from_data(channel_name)
                popup.destroy()
                self.update_display()
        except Exception as e:
            print(f"ポップアップ削除エラー: {e}")


    # ===== フィルタ・ページング・検索 =====

    def on_filter_change(self):
        """フィルター変更"""
        try:
            print(f"フィルター変更: {self.current_filter.get()}")
            self.current_page = 0
            self.update_display()
        except Exception as e:
            print(f"フィルター変更エラー: {e}")

    def prev_page(self):
        """前のページへ移動"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_display()

    def next_page(self):
        """次のページへ移動"""
        all_channels = self.get_filtered_channels(selected_only=self.show_selected_only)
        total_pages = max(1, (len(all_channels) + self.items_per_page - 1) // self.items_per_page)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.update_display()

    def go_to_page(self):
        """ページ直接移動"""
        try:
            page_num = int(self.page_entry.get()) - 1
            all_channels = self.get_filtered_channels(selected_only=self.show_selected_only)
            total_pages = max(1, (len(all_channels) + self.items_per_page - 1) // self.items_per_page)
            if 0 <= page_num < total_pages:
                self.current_page = page_num
                self.update_display()
            else:
                messagebox.showwarning("警告", f"ページ番号は 1-{total_pages} の範囲で入力してください。")
        except ValueError:
            messagebox.showwarning("警告", "有効なページ番号を入力してください。")

    def search_channels(self):
        """検索実行"""
        try:
            keyword = self.search_entry.get().strip()
            self.search_keyword = keyword
            self.current_page = 0
            self.update_display()
            print(f"検索実行: '{keyword}'" if keyword else "検索クリア")
        except Exception as e:
            print(f"検索実行エラー: {e}")

    def clear_search(self):
        """検索クリア"""
        try:
            self.search_entry.delete(0, tk.END)
            self.search_keyword = ""
            self.current_page = 0
            self.update_display()
        except Exception as e:
            print(f"検索クリアエラー: {e}")

    # ===== 選択操作 =====

    def select_current_page(self):
        """現在ページ全選択"""
        try:
            for ch in self.current_channels:
                self.check_states[ch["channel_name"]] = True
            self.display_current_page()
            print("現在ページ全選択完了")
        except Exception as e:
            print(f"全選択エラー: {e}")

    def deselect_all(self):
        """全選択解除（ページ横断）"""
        try:
            self.check_states.clear()
            self.display_current_page()
            print("全選択解除完了")
        except Exception as e:
            print(f"選択解除エラー: {e}")

    # ===== データ操作 =====

    def execute_bulk_delete(self):
        """一括削除実行"""
        try:
            selected = [ch for ch, v in self.check_states.items() if v]
            if not selected:
                messagebox.showinfo("情報", "削除するチャンネルが選択されていません。")
                return
            if not messagebox.askyesno(
                "確認",
                f"{len(selected)}個のチャンネルを削除しますか？\n\n"
                "この操作は「変更を保存」するまで確定されません。"
            ):
                return
            deleted = sum(1 for ch in selected if self.delete_channel_from_data(ch))
            print(f"一括削除完了: {deleted}個")
            messagebox.showinfo("完了", f"{deleted}個のチャンネルを削除しました。")
            self.check_states.clear()
            self.update_display()
        except Exception as e:
            print(f"一括削除エラー: {e}")
            messagebox.showerror("エラー", f"一括削除に失敗しました:\n{e}")


    def execute_bulk_move(self):
        """一括プレイリスト移動実行（選択チャンネルを所望プレイリストへ移動）"""
        try:
            selected = [ch for ch, v in self.check_states.items() if v]
            if not selected:
                messagebox.showinfo("情報", "移動するチャンネルが選択されていません。")
                return
            self.show_bulk_move_dialog(selected)
        except Exception as e:
            print(f"一括移動エラー: {e}")
            messagebox.showerror("エラー", f"一括移動に失敗しました:\n{e}")


    def show_bulk_move_dialog(self, selected_channels):
        """移動先プレイリスト選択ダイアログ（Toplevel・ラジオボタン方式）"""
        try:
            # 条件②: 二重起動防止
            if self.move_dialog and self.move_dialog.winfo_exists():
                self.move_dialog.lift()
                return

            dialog = tk.Toplevel(self.root)
            dialog.title("📂 プレイリスト一括移動")
            calculated_height = 220 + len(self.playlist_config) * 32
            dialog.geometry(f"420x{calculated_height}")
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.resizable(False, False)
            self.move_dialog = dialog

            tk.Label(
                dialog,
                text=f"選択チャンネル数: {len(selected_channels)} 件",
                font=tkfont.Font(family="Meiryo", size=11, weight="bold"),
                anchor="w"
            ).pack(fill="x", padx=16, pady=(14, 4))

            tk.Label(
                dialog,
                text="移動先のプレイリストを選択してください:",
                font=tkfont.Font(family="Meiryo", size=10),
                anchor="w"
            ).pack(fill="x", padx=16, pady=(0, 6))

            # 条件①: 初期値を "S"（有効なプレイリスト記号）に固定
            target_var = tk.StringVar(value="S")

            pl_frame = tk.LabelFrame(
                dialog, text="移動先プレイリスト",
                font=tkfont.Font(family="Meiryo", size=10),
                padx=10, pady=8
            )
            pl_frame.pack(fill="x", padx=16, pady=(0, 10))

            for pl_key, pl_desc in self.playlist_config.items():
                tk.Radiobutton(
                    pl_frame,
                    text=f"{pl_key}  {pl_desc}",
                    variable=target_var,
                    value=pl_key,
                    font=tkfont.Font(family="Meiryo", size=10),
                    anchor="w"
                ).pack(fill="x", pady=2)

            # ボタン行
            btn_frame = tk.Frame(dialog)
            btn_frame.pack(fill="x", padx=16, pady=(4, 12))

            def apply_move():
                target = target_var.get()
                # 条件①: 空文字・不正値ガード
                if target not in self.playlist_config:
                    messagebox.showwarning("警告", "有効なプレイリストを選択してください。", parent=dialog)
                    return
                # データ更新
                moved = 0
                for ch in selected_channels:
                    if ch in self.data.get("channels", {}):
                        self.data["channels"][ch] = target
                        moved += 1
                print(f"一括移動完了: {moved}件 → プレイリスト {target}({self.playlist_config.get(target, '')})")
                # 条件③: check_states.clear() → dialog.destroy() → update_display() の順厳守
                self.check_states.clear()
                dialog.destroy()
                self.update_display()
                messagebox.showinfo(
                    "完了",
                    f"{moved}件のチャンネルをプレイリスト {target}（{self.playlist_config.get(target, '')}）へ移動しました。\n\n「💾 保存」ボタンで確定してください。"
                )

            tk.Button(
                btn_frame, text="✅ 適用",
                command=apply_move,
                font=tkfont.Font(family="Meiryo", size=10),
                bg="#90EE90", width=12
            ).pack(side="left", padx=(0, 8))

            tk.Button(
                btn_frame, text="キャンセル",
                command=dialog.destroy,
                font=tkfont.Font(family="Meiryo", size=10),
                width=12
            ).pack(side="left")

        except Exception as e:
            print(f"移動ダイアログエラー: {e}")
            messagebox.showerror("エラー", f"移動ダイアログ表示に失敗しました:\n{e}")


    def delete_channel_from_data(self, channel_name):
        """データからチャンネル削除"""
        try:
            channels = self.data.get("channels", {})
            if channel_name in channels:
                del channels[channel_name]
                print(f"チャンネル削除成功: {channel_name}")
                return True
            return False
        except Exception as e:
            print(f"データ削除エラー: {e}")
            return False

    def save_changes(self):
        """変更保存処理"""
        try:
            backup_file = backup_learned_channels()
            if save_learned_channels_data(self.data, self.favorite_channels):
                message = "変更を保存しました。\n\n"
                if backup_file:
                    message += f"バックアップ: {backup_file.name}"
                messagebox.showinfo("保存完了", message)
                print("変更保存完了")
                self.original_data = json.loads(json.dumps(self.data))
                self.update_display()
            else:
                messagebox.showerror("エラー", "保存に失敗しました。")
        except Exception as e:
            print(f"保存エラー: {e}")
            messagebox.showerror("エラー", f"保存処理に失敗しました:\n{e}")



    def cancel_changes(self):
        """変更キャンセル"""
        try:
            if messagebox.askyesno(
                "確認", "変更をキャンセルしますか？\n\n未保存の変更は失われます。"
            ):
                self.data = json.loads(json.dumps(self.original_data))
                self.check_states.clear()
                print("変更をキャンセルしました")
                self.update_display()
        except Exception as e:
            print(f"キャンセルエラー: {e}")


    def on_window_close(self):
        """ウィンドウクローズ処理（channels のみ比較・metadata は比較対象外）"""
        try:
            if json.dumps(self.data, sort_keys=True) != json.dumps(self.original_data, sort_keys=True):
                result = messagebox.askyesnocancel(
                    "確認",
                    "未保存の変更があります。\n\n"
                    "保存してから終了しますか？\n\n"
                    "「はい」: 保存して終了\n"
                    "「いいえ」: 保存せずに終了\n"
                    "「キャンセル」: 終了しない"
                )
                if result is None:
                    return
                elif result:
                    if save_learned_channels_data(self.data, self.favorite_channels):
                        print("保存して終了")
                        self.root.quit()
                        self.root.destroy()
                    else:
                        messagebox.showerror("エラー", "保存に失敗しました。")
                        return
                else:
                    print("保存せずに終了")
                    self.root.quit()
                    self.root.destroy()
            else:
                print("変更なしで終了")
                self.root.quit()
                self.root.destroy()
        except Exception as e:
            print(f"終了処理エラー: {e}")
            self.root.quit()
            self.root.destroy()




# ===== メイン実行 =====

def main():
    try:
        print(f"学習チャンネル管理ツール開始  VERSION={VERSION}")
        root = tk.Tk()
        root.withdraw()
        manager = ChannelRulesManager()
        manager.launch()
        if manager.root:
            manager.root.mainloop()
        print("学習チャンネル管理ツール終了")
    except Exception as e:
        print(f"メインエラー: {e}")
        messagebox.showerror("エラー", f"アプリケーションエラー:\n{e}")


if __name__ == "__main__":
    main()
