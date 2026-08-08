
"""
YouTube Play List Set up　System
## 履歴は現バージョンより、CHANGELOG_***.mdで管理

"""
# 定数定義
VERSION = "2026.0707_02"

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

# 🆕 ショート動画サマリーHTML出力先（20260707_02_01）
SUMMARY_OUTPUT_DIR = r"C:\Users\nx023836\Nexperia\My Private - Documents\Summary"

# 🆕 ローカル重複管理システム
registered_videos_manager = None
CACHE_ENABLED = True

# 既存のグローバル変数の後に追加
PROJECT_MANAGER = None  # MultiProjectManagerインスタンス


SHORT_THRESHOLD_SECONDS = 180  # ショート動画の閾値（3分）
UNCLASSIFIED_KEYS = {"NONE", "UNCLASSIFIED", "未登録"}  # 未分類プレイリストのエイリアス



# UI選択のデフォルト値
DEFAULT_SELECTION = {
    "all": True,
    "short": True,
    "S": True,
    "A": True,
    "B": True,
    "N": True,
    "M": True,
    "L": True,
    "V": True,
    "P+": True
}



# プロジェクトIDマッピング
PROJECT_IDS = {
    'project1': 'woven-invention-463200-t6',
    'project2': 'encoded-joy-467906-p5'
}

def create_config_directory():
    """config/ディレクトリを作成"""
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        logger.info(f"🆕 設定ディレクトリ作成: {CONFIG_DIR}")
        return True
    except Exception as e:
        logger.error(f"🆕 設定ディレクトリ作成失敗: {e}")
        return False

def get_default_playlist_config():
    """プレイリスト設定のデフォルト値を返す"""
    return {
        "V": "PL0UGJjoPnxKgZaJvHD5lGzOmGnEAdrn9H",
        "S": "PL0UGJjoPnxKjT1ClcCwngoCDhModNIG3H",
        "A": "PL0UGJjoPnxKgphke6I63QVyHeToWaNSTD",
        "B": "PL0UGJjoPnxKhM3jXPMhNxONyvyZbClDuM",
        "M": "PL0UGJjoPnxKhX6NN6K5GSPCzh9H8bK1F3",
        "N": "PL0UGJjoPnxKj6T0VlBmyxVqVmBIK1h3G6",
        "P+": "PL0UGJjoPnxKggbm7xrXUJQAExVbuca8-M",
        "L": "PL0UGJjoPnxKhEsnwZqNSkcUZow4Uklz5R",
    }
def get_default_channel_rules_config():
    """チャンネルルール設定のデフォルト値を返す"""
    return {
        # プレイリストSに振り分けるキーワード
        "TED": "S",
        "Y Combinator": "S",
        
        # プレイリストAに振り分けるキーワード    
        "PIVOT": "A",
        "両学長": "A",
        "臨済宗大本山 円覚寺": "A",
        
        # プレイリストBに振り分けるキーワード
        "本のソムリエ": "B",
        "本要約チャンネル": "B",
        
        # プレイリストMに振り分けるキーワード
        "ロジャーパパ米国株投資": "M",
        "つばめ投資顧問の長期投資研究所": "M", 
        "Dan Takahashi": "M", 

        # プレイリストNに振り分けるキーワード
         
        # プレイリストLに振り分けるキーワード
        "五味やすたか": "L",
        "合気道祥平塾": "L", 
    }

def get_default_filter_config():
    """フィルタ設定のデフォルト値を返す"""
    return {
        "min_duration_seconds": 180,
        "enable_duration_filter": True,
        "show_filtered_videos": True,
        "auto_exclude_shorts": True,
        "shorts_max_seconds": 60
    }

def get_default_system_config():
    """システム設定のデフォルト値を返す"""
    return {
        "max_videos": 200,
        "max_search_videos": 300,
        "early_exit_threshold": 5,
        "max_parallel_workers": 1,
        "batch_size": 25,
        "max_retries": 2,
        "retry_delays": [0.5, 1.0],
        "timeouts": {
            "connection": 2,
            "page_load": 4,
            "element_find": 0.1,
            "navigation": 6,
            "login_check": 2
        },
        "delays": {
            "connection_stability": 0.2,
            "tab_switch": 0.1,
            "page_transition": 0.5,
            "content_load": 1.0,
            "scroll_wait": 0.3
        },
        "enhanced_duration_selectors": [
            "ytd-thumbnail-overlay-time-status-renderer span.style-scope",
            "span.ytd-thumbnail-overlay-time-status-renderer",
            ".ytd-thumbnail-overlay-time-status-renderer span"
        ],
        "quota_monitoring_enabled": True,
        "default_quota_limit": 10000,
        "auto_open_quota_page": True,
        "quota_page_url": "https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas?hl=ja&inv=1&invt=Ab4bwA&project=woven-invention-463200-t6"


    }

def get_default_video_cache_config():
    """🆕 ビデオキャッシュ設定のデフォルト値を返す"""
    return {
        "cache_enabled": True,
        "retention_days": 1,
        "cleanup_on_startup": True,
        "cleanup_on_shutdown": True,
        "fallback_to_api": True,
        "max_cache_size_mb": 50,
        "auto_cleanup_threshold": 0.8
    }

def validate_playlist_config(data):
    """プレイリスト設定の妥当性チェック"""
    try:
        if not isinstance(data, dict):
            return False
        
        # 必須プレイリストの存在確認
        required_playlists = ["S", "A", "B", "M", "N", "L"]
        for pl in required_playlists:
            if pl not in data:
                logger.warning(f"🆕 必須プレイリスト '{pl}' が設定にありません")
                return False
            
            # プレイリストIDの形式チェック（PL始まりの34文字）
            playlist_id = data[pl]
            if not isinstance(playlist_id, str) or not playlist_id.startswith("PL") or len(playlist_id) != 34:
                logger.warning(f"🆕 プレイリスト '{pl}' のIDが不正: {playlist_id}")
                return False
        
        return True
    except Exception as e:
        logger.error(f"🆕 プレイリスト設定検証エラー: {e}")
        return False

def validate_channel_rules_config(data):
    """チャンネルルール設定の妥当性チェック"""
    try:
        if not isinstance(data, dict):
            return False

        valid_playlists = ["V", "S", "A", "B", "M", "N", "P+", "L"]

        for channel_name, playlist in data.items():
            if not isinstance(channel_name, str) or not isinstance(playlist, str):
                logger.warning(f"🆕 チャンネルルール設定が不正: {channel_name} -> {playlist}")
                return False

            if playlist not in valid_playlists:
                logger.warning(f"🆕 無効なプレイリスト指定: {channel_name} -> {playlist}")
                return False

        return True
    except Exception as e:
        logger.error(f"🆕 チャンネルルール設定検証エラー: {e}")
        return False


def validate_filter_config(data):
    """フィルタ設定の妥当性チェック"""
    try:
        if not isinstance(data, dict):
            return False
        
        # 必須項目の存在確認
        required_keys = ["min_duration_seconds", "enable_duration_filter", 
                        "show_filtered_videos", "auto_exclude_shorts", "shorts_max_seconds"]
        
        for key in required_keys:
            if key not in data:
                logger.warning(f"🆕 フィルタ設定に必須項目がありません: {key}")
                return False
        
        # 数値項目の範囲チェック
        if not (0 <= data["min_duration_seconds"] <= 3600):
            logger.warning(f"🆕 min_duration_seconds が範囲外: {data['min_duration_seconds']}")
            return False
        
        if not (0 <= data["shorts_max_seconds"] <= 300):
            logger.warning(f"🆕 shorts_max_seconds が範囲外: {data['shorts_max_seconds']}")
            return False
        
        return True
    except Exception as e:
        logger.error(f"🆕 フィルタ設定検証エラー: {e}")
        return False

def validate_system_config(data):
    """システム設定の妥当性チェック"""
    try:
        if not isinstance(data, dict):
            return False
        
        # 数値範囲チェック
        numeric_checks = {
            "max_videos": (1, 1000),
            "max_search_videos": (1, 1000),
            "early_exit_threshold": (1, 50),
            "max_parallel_workers": (1, 50),
            "batch_size": (1, 100),
            "max_retries": (1, 10),
            "default_quota_limit": (1000, 100000000)
        }
        
        for key, (min_val, max_val) in numeric_checks.items():
            if key in data:
                if not (min_val <= data[key] <= max_val):
                    logger.warning(f"🆕 システム設定 '{key}' が範囲外: {data[key]}")
                    return False
        
        return True
    except Exception as e:
        logger.error(f"🆕 システム設定検証エラー: {e}")
        return False

def validate_video_cache_config(data):
    """🆕 ビデオキャッシュ設定の妥当性チェック"""
    try:
        if not isinstance(data, dict):
            return False
        
        # 必須項目の存在確認
        required_keys = ["cache_enabled", "retention_days", "cleanup_on_startup", 
                        "cleanup_on_shutdown", "fallback_to_api", "max_cache_size_mb"]
        
        for key in required_keys:
            if key not in data:
                logger.warning(f"🆕 キャッシュ設定に必須項目がありません: {key}")
                return False
        
        # 数値項目の範囲チェック
        if not (0 <= data["retention_days"] <= 30):
            logger.warning(f"🆕 retention_days が範囲外: {data['retention_days']}")
            return False
        
        if not (1 <= data["max_cache_size_mb"] <= 1000):
            logger.warning(f"🆕 max_cache_size_mb が範囲外: {data['max_cache_size_mb']}")
            return False
        
        return True
    except Exception as e:
        logger.error(f"🆕 ビデオキャッシュ設定検証エラー: {e}")
        return False

def load_playlist_config():
    """プレイリスト設定をJSONから読み込み"""
    config_file = CONFIG_DIR / "playlists.json"
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if validate_playlist_config(data):
                logger.info(f"🆕 プレイリスト設定読み込み成功: {len(data)}個")
                return data
            else:
                logger.warning("🆕 プレイリスト設定が不正、デフォルト値を使用")
        else:
            logger.info(f"🆕 プレイリスト設定ファイルなし: {config_file}")
    except Exception as e:
        logger.error(f"🆕 プレイリスト設定読み込みエラー: {e}")
    
    # フォールバック: デフォルト値を使用
    default_config = get_default_playlist_config()
    logger.info("🆕 プレイリスト設定: デフォルト値を使用")
    return default_config


def load_channel_rules_config():
    """チャンネルルール設定を読み込み"""
    config_file = CONFIG_DIR / "channel_rules.json"
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if validate_channel_rules_config(data):
                logger.info(f"🆕 チャンネルルール設定読み込み成功: {len(data)}個")
                return data
            else:
                logger.warning("🆕 チャンネルルール設定が不正、デフォルト値を使用")
        else:
            logger.info(f"🆕 チャンネルルール設定ファイルなし: {config_file}")
    except Exception as e:
        logger.error(f"🆕 チャンネルルール設定読み込みエラー: {e}")
    
    # フォールバック: デフォルト値を使用
    default_config = get_default_channel_rules_config()
    logger.info("🆕 チャンネルルール設定: デフォルト値を使用")
    return default_config
    

def load_filter_config():
    """フィルタリング設定を読み込み"""
    config_file = CONFIG_DIR / "filter_settings.json"
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if validate_filter_config(data):
                logger.info(f"🆕 フィルタ設定読み込み成功")
                return data
            else:
                logger.warning("🆕 フィルタ設定が不正、デフォルト値を使用")
        else:
            logger.info(f"🆕 フィルタ設定ファイルなし: {config_file}")
    except Exception as e:
        logger.error(f"🆕 フィルタ設定読み込みエラー: {e}")
    
    # フォールバック: デフォルト値を使用
    default_config = get_default_filter_config()
    logger.info("🆕 フィルタ設定: デフォルト値を使用")
    return default_config

def load_system_config():
    """システム設定を読み込み"""
    config_file = CONFIG_DIR / "system_config.json"
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if validate_system_config(data):
                logger.info(f"🆕 システム設定読み込み成功")
                return data
            else:
                logger.warning("🆕 システム設定が不正、デフォルト値を使用")
        else:
            logger.info(f"🆕 システム設定ファイルなし: {config_file}")
    except Exception as e:
        logger.error(f"🆕 システム設定読み込みエラー: {e}")
    
    # フォールバック: デフォルト値を使用
    default_config = get_default_system_config()
    logger.info("🆕 システム設定: デフォルト値を使用")
    return default_config

def load_video_cache_config():
    """🆕 ビデオキャッシュ設定をJSONから読み込み"""
    config_file = CONFIG_DIR / "video_cache.json"
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if validate_video_cache_config(data):
                logger.info(f"🆕 ビデオキャッシュ設定読み込み成功")
                return data
            else:
                logger.warning("🆕 ビデオキャッシュ設定が不正、デフォルト値を使用")
        else:
            logger.info(f"🆕 ビデオキャッシュ設定ファイルなし: {config_file}")
    except Exception as e:
        logger.error(f"🆕 ビデオキャッシュ設定読み込みエラー: {e}")
    
    # フォールバック: デフォルト値を使用
    default_config = get_default_video_cache_config()
    logger.info("🆕 ビデオキャッシュ設定: デフォルト値を使用")
    return default_config

def generate_default_config_files():
    """デフォルト設定ファイルを生成"""
    try:
        create_config_directory()
        
        # 各設定ファイルのパスと内容
        config_files = {
            "playlists.json": get_default_playlist_config(),
            "channel_rules.json": get_default_channel_rules_config(),
            "filter_settings.json": get_default_filter_config(),
            "system_config.json": get_default_system_config(),
            "video_cache.json": get_default_video_cache_config()  # 🆕 追加
        }
        
        created_count = 0
        for filename, content in config_files.items():
            file_path = CONFIG_DIR / filename
            if not file_path.exists():
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
                logger.info(f"🆕 デフォルト設定ファイル作成: {filename}")
                created_count += 1
            else:
                logger.info(f"🆕 設定ファイル既存: {filename}")
        
        if created_count > 0:
            logger.info(f"🆕 {created_count}個のデフォルト設定ファイルを作成しました")
        
        return True
    except Exception as e:
        logger.error(f"🆕 デフォルト設定ファイル生成エラー: {e}")
        return False

def load_all_configs():
    """全設定ファイルを一括読み込み（🆕 ビデオキャッシュ対応版）"""
    global CONFIG_DATA, CONFIG_LOADED
    
    try:
        logger.info("🆕 設定外部化システム開始")
        
        # 設定ディレクトリ作成
        create_config_directory()
        
        # 設定ファイルが存在しない場合はデフォルトファイルを生成
        generate_default_config_files()
        
        # 各設定を読み込み
        CONFIG_DATA = {
            'playlists': load_playlist_config(),
            'channel_rules': load_channel_rules_config(),
            'filter_settings': load_filter_config(),
            'system_config': load_system_config(),
            'video_cache': load_video_cache_config()  # 🆕 追加
        }
        
        CONFIG_LOADED = True
        logger.info("🆕 全設定読み込み完了")
        
        # 設定内容をサマリー表示
        summary = {
            'playlists': len(CONFIG_DATA['playlists']),
            'channel_rules': len(CONFIG_DATA['channel_rules']),
            'filter_enabled': CONFIG_DATA['filter_settings']['enable_duration_filter'],
            'quota_monitoring': CONFIG_DATA['system_config']['quota_monitoring_enabled'],
            'cache_enabled': CONFIG_DATA['video_cache']['cache_enabled']  # 🆕 追加
        }
        logger.info(f"🆕 設定サマリー: {summary}")
        
        return CONFIG_DATA
        
    except Exception as e:
        logger.error(f"🆕 設定読み込みエラー: {e}")
        CONFIG_LOADED = False
        
        # エラー時は空の設定で初期化（各関数でデフォルト値を使用）
        CONFIG_DATA = {
            'playlists': get_default_playlist_config(),
            'channel_rules': get_default_channel_rules_config(),
            'filter_settings': get_default_filter_config(),
            'system_config': get_default_system_config(),
            'video_cache': get_default_video_cache_config()  # 🆕 追加
        }
        
        return CONFIG_DATA

# 動的設定値取得関数
def get_playlist_ids():
    """現在のプレイリスト設定を取得"""
    return CONFIG_DATA.get('playlists', get_default_playlist_config())

def get_channel_keywords():
    """現在のチャンネルルール設定を取得"""
    return CONFIG_DATA.get('channel_rules', get_default_channel_rules_config())

def get_filter_settings():
    """現在のフィルタ設定を取得"""
    return CONFIG_DATA.get('filter_settings', get_default_filter_config())

def get_system_config():
    """現在のシステム設定を取得"""
    return CONFIG_DATA.get('system_config', get_default_system_config())

def get_video_cache_config():
    """🆕 現在のビデオキャッシュ設定を取得"""
    return CONFIG_DATA.get('video_cache', get_default_video_cache_config())

# ===== 🆕 ローカル重複管理システム =====

class RegisteredVideosManager:
    """🆕 登録済み動画のローカル管理システム"""



    def __init__(self, cache_file="registered_videos.json"):
        self.cache_file = Path(cache_file)
        self.file_lock = threading.Lock()  # 追加
        self.data = {
            "version": "1.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "session_id": self.generate_session_id(),
            "cleanup_policy": {
                "retention_days": 1,
                "last_cleanup": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "statistics": {
                "total_registered": 0,
                "cache_hits": 0,
                "api_calls_saved": 0
            },
            "playlists": {}
        }
        self.load_cache()
        logger.info(f"RegisteredVideosManager初期化: {self.cache_file}")
    
    
    def generate_session_id(self):
        """セッションID生成"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_part = str(uuid.uuid4())[:8]
        return f"session_{timestamp}_{random_part}"
    
    def load_cache(self):
        """キャッシュファイルを読み込み"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                
                # データ構造の検証・マージ
                if isinstance(loaded_data, dict) and "playlists" in loaded_data:
                    self.data.update(loaded_data)
                    self.data["session_id"] = self.generate_session_id()  # 新しいセッション
                    
                    # 統計情報をリセット（セッション単位）
                    if "statistics" not in self.data:
                        self.data["statistics"] = {"total_registered": 0, "cache_hits": 0, "api_calls_saved": 0}
                    self.data["statistics"]["cache_hits"] = 0
                    self.data["statistics"]["api_calls_saved"] = 0
                    
                    logger.info(f"🆕 キャッシュ読み込み成功: {len(self.data['playlists'])}プレイリスト")
                else:
                    logger.warning("🆕 キャッシュファイル形式不正、初期化")
            else:
                logger.info("🆕 キャッシュファイル新規作成")
        except Exception as e:
            logger.error(f"🆕 キャッシュ読み込みエラー: {e}")
    
    def save_cache(self):
        """キャッシュファイルに保存"""

        try:
            with self.file_lock:  # 追加
                self.data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)

            logger.debug(f"🆕 キャッシュ保存: {len(self.data['playlists'])}プレイリスト")
        except Exception as e:
            logger.error(f"🆕 キャッシュ保存エラー: {e}")
    
    def is_video_registered(self, video_id, playlist_id):
        """動画が既に登録済みかチェック（高速）"""
        try:
            if playlist_id in self.data["playlists"]:
                if video_id in self.data["playlists"][playlist_id].get("videos", {}):
                    self.data["statistics"]["cache_hits"] += 1
                    self.data["statistics"]["api_calls_saved"] += 1
                    return True
            return False
        except Exception as e:
            logger.error(f"🆕 重複チェックエラー: {e}")
            return False
    
    
    def register_video(self, video_id, playlist_id, title, channel, playlist_name=""):
        """動画登録を記録"""
        try:
            if playlist_id not in self.data["playlists"]:
                self.data["playlists"][playlist_id] = {
                    "playlist_name": playlist_name,
                    "videos": {}
                }
            
            self.data["playlists"][playlist_id]["videos"][video_id] = {
                "title": title,
                "channel": channel,
                "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "session_id": self.data["session_id"]
            }
            
            self.data["statistics"]["total_registered"] += 1
            session_total = self.data["statistics"].get("total_registered", 0)
            playlist_video_count = len(self.data["playlists"][playlist_id].get("videos", {}))
            logger.info(
                f"DEBUG_REGISTER_CACHE|video_id={video_id}|playlist_name={playlist_name}|"
                f"playlist_id={playlist_id}|session_total={session_total}|"
                f"playlist_video_count={playlist_video_count}|channel={channel}|title={title[:80]}"
            )
            
            # 定期保存（10件ごと）
            if self.data["statistics"]["total_registered"] % 10 == 0:
                self.save_cache()
                logger.info(
                    f"DEBUG_REGISTER_CACHE_SAVE|reason=every_10|video_id={video_id}|"
                    f"session_total={session_total}|cache_file={self.cache_file}"
                )
            
            logger.debug(f"🆕 動画登録記録: {title[:30]} → {playlist_name}")
        except Exception as e:
            logger.error(f"🆕 動画登録記録エラー: {e}")
    
    def cleanup_old_records(self, retention_days=None):
        """古い記録をクリーンアップ"""
        try:
            if retention_days is None:
                cache_config = get_video_cache_config()
                retention_days = cache_config.get("retention_days", 1)
            
            cutoff_time = datetime.now() - timedelta(days=retention_days)
            cutoff_str = cutoff_time.strftime("%Y-%m-%d %H:%M:%S")
            
            removed_count = 0
            for playlist_id in list(self.data["playlists"].keys()):
                playlist_data = self.data["playlists"][playlist_id]
                videos_to_remove = []
                
                for video_id, video_info in playlist_data.get("videos", {}).items():
                    registered_at = video_info.get("registered_at", "")
                    if registered_at < cutoff_str:
                        videos_to_remove.append(video_id)
                
                # 古い動画を削除
                for video_id in videos_to_remove:
                    del playlist_data["videos"][video_id]
                    removed_count += 1
                
                # 空のプレイリストを削除
                if not playlist_data.get("videos"):
                    del self.data["playlists"][playlist_id]
            
            if removed_count > 0:
                self.data["cleanup_policy"]["last_cleanup"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_cache()
                logger.info(f"🆕 クリーンアップ完了: {removed_count}件削除")
            else:
                logger.info("🆕 クリーンアップ: 削除対象なし")
            
            return removed_count
        except Exception as e:
            logger.error(f"🆕 クリーンアップエラー: {e}")
            return 0
    
    def get_cache_statistics(self):
        """キャッシュ統計情報を取得"""
        try:
            total_videos = sum(len(pl.get("videos", {})) for pl in self.data["playlists"].values())
            
            return {
                "total_playlists": len(self.data["playlists"]),
                "total_cached_videos": total_videos,
                "cache_hits": self.data["statistics"]["cache_hits"],
                "api_calls_saved": self.data["statistics"]["api_calls_saved"],
                "session_registered": self.data["statistics"]["total_registered"],
                "cache_file_size": self.get_cache_file_size()
            }
        except Exception as e:
            logger.error(f"🆕 統計情報取得エラー: {e}")
            return {}
    
    def get_cache_file_size(self):
        """キャッシュファイルサイズを取得（MB）"""
        try:
            if self.cache_file.exists():
                size_bytes = self.cache_file.stat().st_size
                size_mb = size_bytes / (1024 * 1024)
                return round(size_mb, 2)
            return 0
        except Exception:
            return 0

def local_duplicate_check(video_playlist_pairs):
    """🆕 ローカル重複チェック（APIゼロ使用）"""
    global registered_videos_manager
    
    if not registered_videos_manager:
        logger.warning("🆕 RegisteredVideosManager未初期化、API重複チェックにフォールバック")
        return video_playlist_pairs
    
    cache_config = get_video_cache_config()
    if not cache_config.get("cache_enabled", True):
        logger.info("🆕 ローカルキャッシュ無効、API重複チェックにフォールバック")
        return video_playlist_pairs
    
    logger.info(f"🆕 ローカル重複チェック開始: {len(video_playlist_pairs)}件")
    
    filtered_pairs = []
    duplicate_count = 0
    
    for video_id, playlist_id, title in video_playlist_pairs:
        if registered_videos_manager.is_video_registered(video_id, playlist_id):
            duplicate_count += 1
            logger.debug(f"🆕 ローカル重複検出: {title[:50]}")
        else:
            filtered_pairs.append((video_id, playlist_id, title))
    
    logger.info(f"🆕 ローカル重複チェック完了: {duplicate_count}件スキップ、{len(filtered_pairs)}件が対象")
    
    # API呼び出し削減効果を記録
    if duplicate_count > 0:
        logger.info(f"🆕 API削減効果: 重複チェックで{duplicate_count * 1}ユニット削減")
    
    return filtered_pairs

def update_registered_videos(video_id, playlist_id, title, channel, playlist_name=""):
    """🆕 登録成功時にローカルキャッシュを更新"""
    global registered_videos_manager
    
    if registered_videos_manager:
        registered_videos_manager.register_video(video_id, playlist_id, title, channel, playlist_name)

def cleanup_old_records(retention_days=None):
    """🆕 古い記録の自動削除"""
    global registered_videos_manager
    
    if registered_videos_manager:
        return registered_videos_manager.cleanup_old_records(retention_days)
    return 0

def get_cache_hit_stats():
    """🆕 キャッシュヒット率統計を取得"""
    global registered_videos_manager
    
    if registered_videos_manager:
        return registered_videos_manager.get_cache_statistics()
    return {}

def calculate_cache_efficiency():
    """🆕 キャッシュ効率を計算"""
    stats = get_cache_hit_stats()
    
    if not stats:
        return {"efficiency_rate": 0, "message": "キャッシュ統計なし"}
    
    cache_hits = stats.get("cache_hits", 0)
    total_checks = cache_hits + stats.get("session_registered", 0)
    
    if total_checks > 0:
        efficiency_rate = (cache_hits / total_checks) * 100
        return {
            "efficiency_rate": round(efficiency_rate, 1),
            "cache_hits": cache_hits,
            "total_checks": total_checks,
            "api_calls_saved": stats.get("api_calls_saved", 0),
            "message": f"効率率: {efficiency_rate:.1f}% ({cache_hits}/{total_checks})"
        }
    
    return {"efficiency_rate": 0, "message": "チェック実績なし"}


def is_new_quota_period():
    """リセット時刻ベースの期間判定（16:00リセット対応版）"""
    try:
        import pytz
        jst = pytz.timezone('Asia/Tokyo')
        now_jst = datetime.now(jst)
        
        # 今日のリセット時刻（JST 16:00）
        today_reset = now_jst.replace(hour=16, minute=0, second=0, microsecond=0)
        
        # 現在時刻が16:00より前なら、昨日の16:00が最後のリセット
        if now_jst < today_reset:
            last_reset = today_reset - timedelta(days=1)
        else:
            last_reset = today_reset
        
        quota_file = Path("quota_usage.json")
        
        if not quota_file.exists():
            logger.info("🆕 クォータファイル未存在: 新期間として判定")
            return True
        
        with open(quota_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        saved_reset = data.get('last_reset', None)
        
        if saved_reset:
            saved_reset_dt = datetime.fromisoformat(saved_reset)
            saved_reset_dt = jst.localize(saved_reset_dt.replace(tzinfo=None))
            
            logger.info(f"🔧 リセット時刻比較: 保存={saved_reset_dt.strftime('%m/%d %H:%M')}, 現在={last_reset.strftime('%m/%d %H:%M')}")
            
            if saved_reset_dt < last_reset:
                logger.info(f"🔧 新期間検出: リセット実行")
                return True
            else:
                logger.info(f"🔧 同じ期間: データ継続")
                return False
        else:
            # 古い形式のデータの場合は日付で判定
            saved_date = data.get('date', '')
            pst = pytz.timezone('US/Pacific')
            current_pst_date = datetime.now(pst).strftime('%Y-%m-%d')
            
            if saved_date != current_pst_date:
                logger.info(f"🔧 日付変更検出（レガシー）: リセット実行")
                return True
            else:
                logger.info(f"🔧 同じ日付（レガシー）: データ継続")
                return False
                
    except ImportError:
        # pytzなしのフォールバック
        logger.warning("pytz未インストール: 簡易判定モード")
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        quota_file = Path("quota_usage.json")
        if not quota_file.exists():
            return True
            
        with open(quota_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        saved_date = data.get('date', '')
        
        return saved_date != current_date
        
    except Exception as e:
        logger.error(f"🆕 期間判定エラー: {e}")
        return False

 
def get_google_quota_reset_time():
    """Google APIクォータの正確なリセット時刻を取得（夏時間対応）"""
    try:
        # 太平洋時間のタイムゾーン取得
        pacific_tz = pytz.timezone('US/Pacific')
        jst_tz = pytz.timezone('Asia/Tokyo')
        
        # 現在のJST時刻
        now_jst = datetime.now(jst_tz)
        
        # 太平洋時間での今日の午前0時
        now_pacific = now_jst.astimezone(pacific_tz)
        pacific_midnight = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # JSTに変換
        jst_reset_time = pacific_midnight.astimezone(jst_tz)
        
        # 現在時刻が既にリセット時刻を過ぎている場合は明日のリセット時刻
        if now_jst >= jst_reset_time:
            pacific_midnight += timedelta(days=1)
            jst_reset_time = pacific_midnight.astimezone(jst_tz)
        
        return jst_reset_time
    except Exception as e:
        logger.error(f"🆕 クォータリセット時刻取得エラー: {e}")
        # フォールバック: 現在が夏時間なら16時、標準時なら17時
        return datetime.now().replace(hour=16 if is_dst_period_simple() else 17, minute=0, second=0, microsecond=0)

def is_dst_period_simple():
    """簡易的な夏時間判定（pytzが使えない場合のフォールバック）"""
    try:
        now = datetime.now()
        year = now.year
        
        # 3月第2日曜日を計算
        march = datetime(year, 3, 1)
        march_second_sunday = march + timedelta(days=(13 - march.weekday()) % 7)
        
        # 11月第1日曜日を計算  
        november = datetime(year, 11, 1)
        november_first_sunday = november + timedelta(days=(6 - november.weekday()) % 7)
        
        return march_second_sunday <= now <= november_first_sunday
    except Exception:
        # 安全のため夏時間として扱う
        return True

def get_correct_reset_hour_jst():
    """Google APIクォータの正しいリセット時刻（JST）を取得"""
    try:
        pacific_tz = pytz.timezone('US/Pacific')
        now_pacific = datetime.now(pacific_tz)
        
        # 夏時間かどうかを判定
        is_dst = now_pacific.dst() != timedelta(0)
        
        return 16 if is_dst else 17
    except Exception:
        # pytzが使えない場合のフォールバック
        return 16 if is_dst_period_simple() else 17


def get_pacific_date_string():
    """太平洋時間の日付を取得（最終修正版）"""
    jst_now = datetime.now()
    # 現在時刻をログ出力
    logger.debug(f"JST現在時刻: {jst_now}")
    
    # JSTは太平洋夏時間(PDT)より16時間進んでいる
    pdt_now = jst_now - timedelta(hours=16)
    
    # 日付文字列を生成
    pacific_date = pdt_now.strftime('%Y-%m-%d')
    
    logger.info(f"🔧 太平洋時間日付: {pacific_date} (PDT時刻: {pdt_now.strftime('%Y-%m-%d %H:%M:%S')})")
    return pacific_date

        

def get_api_method_cost(method_name: str) -> int:
    """APIメソッドのコストを取得"""
    API_COSTS = {
        'playlistItems.list': 1,
        'playlistItems.insert': 50,
        'videos.list': 1,
        'search.list': 100,
        'channels.list': 1,
        'subscriptions.list': 1,
        'playlists.list': 1,
        'channelSections.list': 1,
        'activities.list': 1
    }
    return API_COSTS.get(method_name, 1)

def format_quota_status(used: int, limit: int) -> str:
    """クォータ状況をフォーマット"""
    percentage = (used / limit * 100) if limit > 0 else 0
    return f"{used:,}/{limit:,} ({percentage:.1f}%)"

def calculate_hours_since_last_run():
    """過去のログファイルから前回実行時刻を取得し、経過時間を計算（48時間自動削除＋24時間デフォルト版）"""
    try:
        import glob
        import os
        
        # 現在のディレクトリでログファイルを検索
        log_files = glob.glob("youtube_tool_*.log")
        
        if not log_files:
            print("過去のログファイルが見つかりません。デフォルト値を使用")
            return 24  # 🔧 修正: 4 → 24時間
        
        # 🆕 追加: 48時間より古いファイルの削除処理
        cutoff_time = datetime.now() - timedelta(hours=48)
        deleted_count = 0
        valid_log_files = []
        
        for log_file in log_files:
            try:
                # ファイル名から日時部分を抽出: youtube_tool_20250105_143022.log → 20250105_143022
                filename = os.path.basename(log_file)
                if filename.startswith("youtube_tool_") and filename.endswith(".log"):
                    datetime_str = filename[13:-4]  # "youtube_tool_" と ".log" を除去
                    
                    # 日時をdatetimeオブジェクトに変換
                    file_time = datetime.strptime(datetime_str, '%Y%m%d_%H%M%S')
                    
                    # 48時間より古いファイルかチェック
                    if file_time < cutoff_time:
                        # 古いファイルを削除
                        os.remove(log_file)
                        deleted_count += 1
                        print(f"古いログファイルを削除: {log_file} ({file_time.strftime('%Y-%m-%d %H:%M:%S')})")
                    else:
                        # 有効なファイルとして保持
                        valid_log_files.append((file_time, log_file))
                        
            except (ValueError, OSError) as e:
                print(f"ログファイル処理エラー ({log_file}): {e}")
                continue
        
        # 削除結果をログ出力
        if deleted_count > 0:
            print(f"48時間より古いログファイル {deleted_count}個を削除しました")
        
        # 有効なログファイルがない場合
        if not valid_log_files:
            print("有効なログファイルが見つかりません。デフォルト値を使用")
            return 24  # 🔧 修正: 4 → 24時間
        
        # 最新のログファイルの実行時刻を取得
        valid_log_files.sort(key=lambda x: x[0], reverse=True)
        last_run_time, last_log_file = valid_log_files[0]
        
        # 現在時刻との差を計算
        now = datetime.now()
        time_diff = now - last_run_time
        hours_since_last_run = time_diff.total_seconds() / 3600
        
        print(f"前回実行: {last_run_time.strftime('%Y-%m-%d %H:%M:%S')} ({last_log_file})")
        print(f"経過時間: {hours_since_last_run:.1f}時間")
        
        # 経過時間を適切な範囲に調整
        if hours_since_last_run < 0.1:
            return 0.1  # 最小値
        elif hours_since_last_run > 168:
            return 168  # 最大値（7日間）
        else:
            return round(hours_since_last_run, 1)  # 小数点1桁で四捨五入
            
    except Exception as e:
        print(f"前回実行時刻の計算でエラー: {e}")
        return 24  # 🔧 修正: エラー時はデフォルト値 4 → 24時間


DEFAULT_HOURS = calculate_hours_since_last_run()  # 動的計算

# ===== ログ設定（最適化版 + 設定外部化対応） =====
def setup_optimized_logging():
    """最適化されたログ設定（重要な情報のみ + 設定外部化対応）"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_filename = f"youtube_tool_{timestamp}.log"
    
    # ログフォーマット（簡潔版）
    log_format = '[%(asctime)s] %(levelname)s %(message)s'
    date_format = '%H:%M:%S'
    
    # ログ設定（INFO レベル以上のみ）
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"ログファイル: {log_filename}")
    logger.info(f"自動計算された時間設定: {DEFAULT_HOURS}時間")
    logger.info(f"🆕 設定外部化システム: 準備中")
    logger.info(f"🆕 ローカル重複管理システム: 準備中")
    return logger

# グローバルロガー
logger = setup_optimized_logging()

# ===== 🆕 QuotaMonitor クラス（設定外部化対応版） =====

class QuotaMonitor:
    """🔧 修正: APIクォータ監視クラス（夏時間対応完全版）"""
    
    def __init__(self, daily_limit=10000):
        self.daily_limit = daily_limit
        self.daily_usage = 0
        self.session_usage = 0
        self.usage_log = []
        self.usage_breakdown = defaultdict(int)  # 追加
        self.quota_file = Path("quota_usage.json")
        
        # 🔧 追加: 大幅な乖離がある場合の警告
        if self.daily_usage < 1000:  # 1000未満の場合
            logger.warning("🚨 クォータ使用量が少なすぎます")
            logger.warning("🚨 Google Cloud Consoleで実際の使用量を確認し、")
            logger.warning("🚨 必要に応じて手動調整してください")        
        
        # 既存のクォータデータを読み込み
        self.load_usage_data()
        
        logger.info(f"🆕 QuotaMonitor初期化: 制限={self.daily_limit:,}, 本日使用量={self.daily_usage}")

    def load_usage_data(self):
        """🔧 修正: 夏時間完全対応版の使用量データ読み込み"""
        try:
            if self.quota_file.exists():
                with open(self.quota_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 🆕 太平洋時間ベースでの日付チェック（完全版）
                current_pacific_date = get_pacific_date_string()
                saved_pacific_date = data.get('pacific_date', '')
                
                if saved_pacific_date == current_pacific_date:
                    # 同じクォータ期間 → データ継続
                    self.daily_usage = data.get('daily_usage', 0)
                    self.usage_log = data.get('usage_log', [])
                    logger.info(f"🆕 クォータデータ継続: 本日使用量={self.daily_usage}")
                else:
                    # 新しいクォータ期間 → リセット
                    logger.info(f"🆕 新しいクォータ期間: リセット実行")
                    logger.info(f"🆕 前回: {saved_pacific_date} → 今回: {current_pacific_date}")
                    self.daily_usage = 0
                    self.usage_log = []
                    
                    # 夏時間情報をログ出力
                    reset_hour = get_correct_reset_hour_jst()
                    is_dst = reset_hour == 16
                    timezone_name = "PDT" if is_dst else "PST"
                    logger.info(f"🆕 クォータリセット時刻詳細: {timezone_name} 00:00 → JST {reset_hour}:00")
            else:
                logger.info(f"🆕 クォータファイル新規作成")
                self.daily_usage = 0
                self.usage_log = []
                
        except Exception as e:
            logger.error(f"🔧 クォータデータ読み込みエラー: {e}")
            self.daily_usage = 0
            self.usage_log = []


    def save_usage_data(self):
        """🔧 修正: リセット時刻も保存するデータ保存（修正版）"""
        try:
            import pytz
            jst = pytz.timezone('Asia/Tokyo')
            pst = pytz.timezone('US/Pacific')
            
            now_jst = datetime.now(jst)
            now_pst = datetime.now(pst)
            
            # 最後のリセット時刻を計算
            today_reset = now_jst.replace(hour=16, minute=0, second=0, microsecond=0)
            if now_jst < today_reset:
                last_reset = today_reset - timedelta(days=1)
            else:
                last_reset = today_reset
            
            # 太平洋時間の日付
            pacific_date = now_pst.strftime('%Y-%m-%d')
            
            # 保存データ
            data = {
                'date': pacific_date,
                'total_usage': self.daily_usage,
                'session_usage': self.session_usage,  # 追加
                'last_reset': last_reset.isoformat(),
                'last_updated': now_jst.isoformat(),
                'breakdown': dict(self.usage_breakdown),
                'usage_log': self.usage_log[-100:] if self.usage_log else []  # 最新100件
            }
            
        except ImportError:
            # pytzなしの場合（既存処理）
            data = {
                'date': get_pacific_date_string(),
                'total_usage': self.daily_usage,
                'session_usage': self.session_usage,  # 追加
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'breakdown': dict(self.usage_breakdown),
                'usage_log': self.usage_log[-100:] if self.usage_log else []  # 最新100件
            }
        
        # ★★★ 重要な修正: self.usage_fileをself.quota_fileに変更 ★★★
        with open(self.quota_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 クォータデータ保存: {self.daily_usage} (日付: {data.get('date', 'N/A')})")



    def record_api_call(self, operation, cost, success=True):
        """🔧 修正: API呼び出し記録（重複防止完全版）"""
        try:
            current_time = time.time()
            
            # 🔧 修正: 短時間での重複記録を防止（より厳密に）
            if hasattr(self, '_last_record_time') and hasattr(self, '_last_record_operation'):
                time_diff = current_time - self._last_record_time
                if (time_diff < 0.1 and  # 0.1秒以内
                    operation == self._last_record_operation and  # 同じ操作
                    cost == getattr(self, '_last_record_cost', 0)):  # 同じコスト
                    logger.debug(f"🔧 重複記録をスキップ: {operation} (コスト:{cost})")
                    return
            
            # 記録情報を保存
            self._last_record_time = current_time
            self._last_record_operation = operation
            self._last_record_cost = cost
            
            if success:
                self.daily_usage += cost
                self.session_usage += cost
                self.usage_breakdown[operation] += cost
                
                # ログ出力（重要なAPIのみ）
                if cost >= 50:  # 高コストAPIのみログ出力
                    logger.info(f"🆕 高コストAPI実行: {operation} (コスト:{cost}, 累計:{self.daily_usage:,})")
                else:
                    logger.debug(f"API実行: {operation} (コスト:{cost}, 累計:{self.daily_usage:,})")
            else:
                # 失敗時もコストは消費される
                self.daily_usage += cost
                self.session_usage += cost
                logger.warning(f"API失敗: {operation} (コスト:{cost}, 累計:{self.daily_usage:,})")
            
            # 使用ログに記録
            self.usage_log.append({
                'timestamp': datetime.now().isoformat(),
                'operation': operation,
                'cost': cost,
                'success': success,
                'cumulative': self.daily_usage
            })
            
            # 重要な変更時は即座に保存
            if cost >= 50 or len(self.usage_log) % 10 == 0:
                self.save_usage_data()
            
        except Exception as e:
            logger.error(f"🔧 クォータ記録エラー: {e}")


    def get_real_quota_usage(self):
        """Google Cloud Monitoring APIから実際のクォータ使用量を取得"""
        global PROJECT_MANAGER
        
        # Multi-project使用時は内部カウンタの合計値を返す
        if PROJECT_MANAGER:
            status = PROJECT_MANAGER.get_quota_status()
            logger.info(f"📊 Multi-project quota: {status['total_used']}/{status['total_limit']}")
            return status['total_used']
        
        # 既存のCloud Monitoring API使用（単一プロジェクト）
        try:
            # サービスアカウント認証
            credentials = service_account.Credentials.from_service_account_file(
                'service-account-key.json',
                scopes=['https://www.googleapis.com/auth/monitoring.read']
            )
            
            # Monitoring クライアント作成
            client = monitoring_v3.MetricServiceClient(credentials=credentials)
            
            # プロジェクト名
            project_name = f"projects/{credentials.project_id}"
            
            # 現在時刻から1時間前までの期間を指定
            from google.protobuf import timestamp_pb2
            import time
            
            now = time.time()
            seconds = int(now)
            nanos = int((now - seconds) * 10**9)
            
            end_time = timestamp_pb2.Timestamp(seconds=seconds, nanos=nanos)
            start_time = timestamp_pb2.Timestamp(seconds=seconds-3600, nanos=nanos)
            
            # YouTube Data API v3のクォータメトリクスを取得
            interval = monitoring_v3.TimeInterval({
                "end_time": end_time,
                "start_time": start_time
            })
            
            # メトリクスフィルタ（YouTube Data API v3）
            filter_str = 'metric.type="serviceruntime.googleapis.com/api/request_count" AND resource.label.service="youtube.googleapis.com"'
            
            # メトリクスデータを取得
            results = client.list_time_series(
                request={
                    "name": project_name,
                    "filter": filter_str,
                    "interval": interval,
                    "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL
                }
            )
            
            # 使用量を集計
            total_requests = 0
            for result in results:
                for point in result.points:
                    total_requests += point.value.int64_value
            
            logger.info(f"🆕 リアルタイムクォータ取得成功: {total_requests}")
            return total_requests
            
        except FileNotFoundError:
            logger.warning("⚠️ service-account-key.json not found, using internal counter")
            # サービスアカウントキーがない場合は内部カウンタを使用
            if PROJECT_MANAGER:
                status = PROJECT_MANAGER.get_quota_status()
                return status['total_used']
            return self.daily_usage
            
        except Exception as e:
            logger.error(f"🆕 リアルタイムクォータ取得エラー: {e}")
            # エラー時もPROJECT_MANAGERがあれば内部カウンタを返す
            if PROJECT_MANAGER:
                status = PROJECT_MANAGER.get_quota_status()
                return status['total_used']
            return None


    def get_accurate_daily_usage(self):
        """正確な1日のクォータ使用量を取得"""
        # リアルタイムクォータを取得
        real_usage = self.get_real_quota_usage()
        
        if real_usage is not None:
            logger.info(f"🆕 Google Cloud実測値: {real_usage:,}クォータ")
            return real_usage
        else:
            logger.warning("🆕 リアルタイム取得失敗、ローカル値を使用")
            return self.daily_usage

    def force_sync_with_google_cloud(self):
        """🚨 Google Cloudと強制同期"""
        logger.warning("🚨 Google Cloudとの強制同期開始")
        
        # 実測値取得
        real_usage = self.get_real_quota_usage()
        
        if real_usage is not None:
            old_usage = self.daily_usage
            self.daily_usage = real_usage
            
            logger.warning(f"🔧 強制同期実行:")
            logger.warning(f"   修正前: {old_usage:,}ユニット")
            logger.warning(f"   修正後: {real_usage:,}ユニット")
            logger.warning(f"   差異: {abs(real_usage - old_usage):,}ユニット")
            
            # ファイル保存
            self.save_usage_data()
            
            return True
        else:
            logger.error("🚨 Google Cloud実測値取得失敗: 同期できません")
            return False


    def get_current_usage(self):
        """現在の使用状況を取得"""
        remaining = max(0, self.daily_limit - self.daily_usage)
        percentage = (self.daily_usage / self.daily_limit) * 100 if self.daily_limit > 0 else 0
        
        return {
            'used': self.daily_usage,
            'limit': self.daily_limit,
            'remaining': remaining,
            'percentage': percentage,
            'session_usage': self.session_usage
        }


    def manual_adjust_quota(self, actual_usage):
        """🔧 手動クォータ調整機能"""
        try:
            old_usage = self.daily_usage
            self.daily_usage = actual_usage
            
            logger.warning(f"🔧 手動クォータ調整:")
            logger.warning(f"   修正前: {old_usage:,}")
            logger.warning(f"   修正後: {actual_usage:,}")
            logger.warning(f"   差異: {abs(actual_usage - old_usage):,}")
            
            # データ保存
            self.save_usage_data()
            
            return True
            
        except Exception as e:
            logger.error(f"🔧 手動調整エラー: {e}")
            return False
            

    def check_quota_status(self):
        """クォータ状況チェック"""
        usage_info = self.get_current_usage()
        
        if usage_info['percentage'] >= 90:
            return {
                'alert_level': 'critical',
                'message': f"クォータ危険: {usage_info['used']:,}/{usage_info['limit']:,} ({usage_info['percentage']:.1f}%)"
            }
        elif usage_info['percentage'] >= 70:
            return {
                'alert_level': 'warning',
                'message': f"クォータ警告: {usage_info['used']:,}/{usage_info['limit']:,} ({usage_info['percentage']:.1f}%)"
            }
        else:
            return {
                'alert_level': 'normal',
                'message': f"クォータ使用量正常: {usage_info['used']:,}/{usage_info['limit']:,} ({usage_info['percentage']:.1f}%)"
            }

    def generate_usage_report(self):
        """使用状況レポート生成"""
        usage_info = self.get_current_usage()
        
        # 夏時間情報も含めたレポート
        reset_hour = get_correct_reset_hour_jst()
        is_dst = reset_hour == 16
        timezone_name = "PDT" if is_dst else "PST"
        
        report = f"\n🆕 【APIクォータ使用状況】\n"
        report += f"   今日の累計使用量: {usage_info['used']:,}/{usage_info['limit']:,} ({usage_info['percentage']:.1f}%)\n"
        report += f"   今回のセッション: {usage_info['session_usage']:,} ユニット使用\n"
        report += f"   残りクォータ: {usage_info['remaining']:,} ユニット\n"
        report += f"   🆕 リセット時刻: {timezone_name} 00:00 = JST {reset_hour}:00"
        
        return report
        
       

def timing_decorator(func):
    """関数の実行時間を測定するデコレータ（エラー時のみログ出力）"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            if elapsed > 2.0:  # 2秒以上の場合のみログ出力
                logger.info(f"{func.__name__} 完了 ({elapsed:.1f}秒)")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} エラー ({elapsed:.1f}秒): {e}")
            raise
    return wrapper

def safe_operation(operation_name, func, *args, **kwargs):
    """安全な操作実行（エラー時のみログ出力）"""
    try:
        result = func(*args, **kwargs)
        return result
    except Exception as e:
        logger.error(f"{operation_name} 失敗: {e}")
        return None

# グローバルクォータ監視インスタンス（設定外部化対応版）
def initialize_quota_monitor():
    """設定に基づいてクォータ監視を初期化"""
    system_config = get_system_config()
    if system_config.get('quota_monitoring_enabled', True):
        return QuotaMonitor()
    else:
        return None

# 初期化は設定読み込み後に実行
global_quota_monitor = None

print("=" * 60)
print("🚀 YouTube動画取得ツール（超高速化版 + 時間取得強化 + 3分フィルタリング + 学習機能 + APIクォータ監視 + 設定外部化 + ローカル重複管理）")
print(f"📅 起動日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"🖥️ OS: {platform.system()}")
print("🆕 設定外部化システム: 初期化中...")
print("🆕 ローカル重複管理システム: 初期化中...")
print("=" * 60)


# ===== 学習データファイル（設定外部化対応版） =====
LEARNED_CHANNELS_FILE = "learned_channels.json"

# グローバル学習データ
learned_channels = {}
favorites_set = set()

# 時間取得統計（設定外部化対応版）
duration_stats = {
    'total_attempts': 0,
    'css_success': 0,
    'selector_success': {},  # セレクター別成功数
    'failed_videos': []
}

# フィルタリング統計（設定外部化対応版）
filter_stats = {
    'total_videos': 0,
    'short_videos': 0,  # 3分以下
    'unknown_duration': 0,  # 時間不明
    'filtered_out': 0,  # フィルタで除外
    'auto_selected': 0,  # 自動選択
    'manual_required': 0  # 手動選択必要
}

# ===== 🧠 学習機能: JSONファイルの読み書き =====
def load_learned_channels():
    """学習済みチャンネルデータをJSONから読み込み"""
    global learned_channels, favorites_set

    try:
        with open(LEARNED_CHANNELS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            learned_channels = data.get('channels', {})
            favorites_set = set(data.get('favorites', []) or [])
            logger.info(f"学習データ読み込み: {len(learned_channels)}チャンネル / お気に入り: {len(favorites_set)}件")
            return learned_channels
    except FileNotFoundError:
        logger.info(f"{LEARNED_CHANNELS_FILE} が見つかりません。空の学習データで開始")
        learned_channels = {}
        favorites_set = set()
        return learned_channels
    except json.JSONDecodeError as e:
        logger.error(f"学習データJSON解析エラー: {e}")
        learned_channels = {}
        favorites_set = set()
        return learned_channels
    except Exception as e:
        logger.error(f"学習データ読み込みエラー: {e}")
        learned_channels = {}
        favorites_set = set()
        return learned_channels


def get_favorites() -> set:
    """お気に入りチャンネルセットを返す（グローバルキャッシュ利用）"""
    return favorites_set

def save_learned_channels(updated_channels=None):
    """学習済みチャンネルデータをJSONに保存"""
    global learned_channels
    
    if updated_channels is not None:
        learned_channels = updated_channels
    
    try:
        # 既存データの読み込み（channel_metadata等の未知ブロック保持）
        existing_data = {"version": "1.0", "channels": {}}
        try:
            with open(LEARNED_CHANNELS_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
            if isinstance(loaded_data, dict):
                existing_data = loaded_data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        # 既存JSON全体を保持し、channelsとlast_updatedだけを更新
        updated_data = dict(existing_data)
        updated_data["version"] = existing_data.get("version", "1.0")
        updated_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated_data["channels"] = learned_channels
        
        # ファイル保存
        with open(LEARNED_CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"学習データ保存: {len(learned_channels)}チャンネル")
        return True
        
    except Exception as e:
        logger.error(f"学習データ保存エラー: {e}")
        return False

def update_channel_metadata_from_videos(videos):
    """
    fetch_subscribed_videos() の結果全件を learned_channels.json の
    channel_metadata セクションに書き込む。
    対象: 登録・除外・短尺すべて（プレイリスト振り分け結果に依存しない）
    observed_videos は最新30件を保持。subscriber_count は上書きしない。
    """
    MAX_OBSERVED = 30

    try:
        # 既存JSONを読み込む
        existing_data = {"version": "1.0", "channels": {}, "channel_metadata": {}}
        try:
            with open(LEARNED_CHANNELS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                existing_data = loaded
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        metadata = existing_data.get("channel_metadata", {})
        observed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated_channels = set()

        for video_data in videos:
            # video_data 構造: (video_id[0], title[1], upload_time[2], duration[3], channel_name[4], ...)
            if not video_data or len(video_data) < 5:
                continue

            video_id    = video_data[0] if video_data[0] else ""
            title       = video_data[1] if video_data[1] else ""
            channel_name = video_data[4] if video_data[4] else ""

            if not channel_name:
                continue

            # channel_metadata エントリを初期化（存在しない場合）
            if channel_name not in metadata:
                metadata[channel_name] = {
                    "metrics": {},
                    "history": {
                        "last_updated": observed_at,
                        "observed_videos": []
                    }
                }

            ch_meta = metadata[channel_name]

            # metrics は既存を保持（subscriber_count を上書きしない）
            if "metrics" not in ch_meta:
                ch_meta["metrics"] = {}

            if "history" not in ch_meta:
                ch_meta["history"] = {"last_updated": observed_at, "observed_videos": []}

            observed_videos = ch_meta["history"].get("observed_videos", [])

            # video_id 重複チェック（同一動画の二重書き込みを防ぐ）
            existing_ids = {v.get("video_id", "") for v in observed_videos}
            if video_id and video_id in existing_ids:
                continue

            # 新エントリを先頭に追加（新着順）
            new_entry = {
                "observed_at": observed_at,
                "video_id":    video_id,
                "title":       title
            }
            observed_videos.insert(0, new_entry)

            # 最新30件を超えた分は末尾から削除
            if len(observed_videos) > MAX_OBSERVED:
                observed_videos = observed_videos[:MAX_OBSERVED]

            ch_meta["history"]["observed_videos"] = observed_videos
            ch_meta["history"]["last_updated"] = observed_at
            updated_channels.add(channel_name)

        existing_data["channel_metadata"] = metadata
        existing_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(LEARNED_CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ channel_metadata 更新完了: {len(updated_channels)}チャンネル / {len(videos)}件処理")

    except Exception as e:
        logger.error(f"channel_metadata 更新エラー: {e}")
        logger.error(f"エラー詳細: {traceback.format_exc()}")

# ===== 🔥 Phase 3: 時間解析システム（設定外部化対応版） =====
def parse_duration_to_seconds(duration_str):
    """
    動画時間文字列を秒数に変換
    入力例: "1:23", "12:34", "1:23:45", "時間不明"
    出力例: 83, 754, 5025, None
    """
    if not duration_str or duration_str in ["時間不明", "不明", "None", ""]:
        return None
    
    try:
        # コロン区切りの時間形式を解析
        time_parts = duration_str.split(':')
        
        if len(time_parts) == 1:
            # 秒のみ（例: "45"）
            return int(time_parts[0])
        elif len(time_parts) == 2:
            # 分:秒（例: "1:23"）
            minutes = int(time_parts[0])
            seconds = int(time_parts[1])
            return minutes * 60 + seconds
        elif len(time_parts) == 3:
            # 時:分:秒（例: "1:23:45"）
            hours = int(time_parts[0])
            minutes = int(time_parts[1])
            seconds = int(time_parts[2])
            return hours * 3600 + minutes * 60 + seconds
        else:
            return None
            
    except (ValueError, IndexError):
        # 数字変換に失敗した場合
        logger.warning(f"時間変換失敗: {duration_str}")
        return None

def is_short_video(duration_str):
    """
    動画が短時間（3分以下）かどうかを判定（設定外部化対応版）
    """
    duration_seconds = parse_duration_to_seconds(duration_str)
    
    if duration_seconds is None:
        return False  # 時間不明は短時間扱いしない
    
    filter_settings = get_filter_settings()
    min_duration = filter_settings.get("min_duration_seconds", 180)
    return duration_seconds <= min_duration

def is_youtube_shorts(duration_str):
    """
    YouTube Shortsかどうかを判定（60秒以下）（設定外部化対応版）
    """
    duration_seconds = parse_duration_to_seconds(duration_str)
    
    if duration_seconds is None:
        return False
    
    filter_settings = get_filter_settings()
    shorts_max = filter_settings.get("shorts_max_seconds", 60)
    return duration_seconds <= shorts_max

def format_duration_display(duration_str):
    """
    動画時間の表示形式を整形（短時間の場合は注釈付き）
    """
    if not duration_str or duration_str in ["時間不明", "不明", "None", ""]:
        return "⏱️ 時間不明"
    
    duration_seconds = parse_duration_to_seconds(duration_str)
    
    if duration_seconds is None:
        return f"⏱️ {duration_str}"
    
    # 短時間動画の場合は絵文字付き
    if is_youtube_shorts(duration_str):
        return f"🩳 {duration_str} (Shorts)"
    elif is_short_video(duration_str):
        return f"⚡ {duration_str} (短時間)"
    else:
        return f"🎬 {duration_str}"

# ===== 🔥 Phase 3: フィルタリングロジック統合（設定外部化対応版） =====
def apply_duration_filter(channel_name, duration_str):
    """
    チャンネル名と動画時間に基づいてフィルタリングを適用（設定外部化対応版）
    戻り値: (推奨プレイリスト, フィルタ理由, 表示タイプ)
    """
    global filter_stats
    filter_stats['total_videos'] += 1
    
    # 基本的なチャンネル振り分け
    base_playlist = get_smart_playlist_for_channel(channel_name)
    
    # 設定からフィルタ設定を取得
    filter_settings = get_filter_settings()
    
    # フィルタリングが無効の場合はそのまま返す
    if not filter_settings.get("enable_duration_filter", True):
        if base_playlist != "NONE":
            filter_stats['auto_selected'] += 1
        else:
            filter_stats['manual_required'] += 1
        return base_playlist, None, "normal"
    
    # 時間不明の場合
    if not duration_str or duration_str in ["時間不明", "不明", "None", ""]:
        filter_stats['unknown_duration'] += 1
        return base_playlist, "時間不明", "normal"
    
    # 短時間動画の判定
    if is_short_video(duration_str):
        filter_stats['short_videos'] += 1
        
        # Shortsの場合
        if is_youtube_shorts(duration_str) and filter_settings.get("auto_exclude_shorts", True):
            filter_stats['filtered_out'] += 1
            return "NONE", "YouTube Shorts", "filtered"
        
        # 3分以下の通常動画
        filter_stats['filtered_out'] += 1
        return "NONE", "3分以下", "filtered"
    
    # 通常の動画（3分超）
    if base_playlist != "NONE":
        filter_stats['auto_selected'] += 1
    else:
        filter_stats['manual_required'] += 1
    
    return base_playlist, None, "normal"

def log_filter_stats():
    """フィルタリング統計をログ出力"""
    if filter_stats['total_videos'] > 0:
        logger.info(f"フィルタリング統計:")
        logger.info(f"  総動画数: {filter_stats['total_videos']}件")
        logger.info(f"  自動選択: {filter_stats['auto_selected']}件")
        logger.info(f"  手動選択必要: {filter_stats['manual_required']}件")
        logger.info(f"  短時間動画: {filter_stats['short_videos']}件")
        logger.info(f"  フィルタ除外: {filter_stats['filtered_out']}件")
        logger.info(f"  時間不明: {filter_stats['unknown_duration']}件")

# ===== 動画時間取得の強化関数（設定外部化対応版） =====



def log_ui_selection(selection: dict, *, total_candidates: int = None, filtered_counts: dict = None):
    """
    UI選択状態をINFO中心で記録する（PIIマスクなし）
    
    Args:
        selection: {'all','short','S','A','B','N','M','L'} のTrue/False辞書
        total_candidates: UI適用対象の総件数（任意）
        filtered_counts: 除外件数の辞書（任意）
                        想定キー: 'short_excluded', 'playlist_excluded', 'unclassified_excluded'
    """
    try:
        # 1) 基本ログ
        on_keys = [k for k, v in selection.items() if v]
        off_keys = [k for k, v in selection.items() if not v]
        logger.info("=== UI選択状態 ===")
        logger.info(f"ON : {on_keys}")
        logger.info(f"OFF: {off_keys}")

        # 2) 任意の件数サマリ
        if total_candidates is not None:
            logger.info(f"候補総数: {total_candidates}件")
        if filtered_counts:
            # 主要な統計を優先表示
            primary_stats = ['short_excluded', 'playlist_excluded', 'unclassified_excluded']
            for key in primary_stats:
                if key in filtered_counts:
                    logger.info(f"{key}: {filtered_counts[key]}件")
            # その他の統計
            for k, v in filtered_counts.items():
                if k not in primary_stats:
                    logger.info(f"{k}: {v}件")

        # 3) トグル規則の検査（参考ログ）
        indiv = ['short', 'S', 'A', 'B', 'N', 'M', 'L', 'V', 'P+']
        if all(selection.get(x, False) for x in indiv) and not selection.get('all', False):
            logger.debug("個別は全ONだが 'all' がOFF → 次回トグルで同期予定")
        
        # 4) 再解析用JSON出力（DEBUG）
        logger.debug(f"UI選択JSON: {json.dumps(selection, ensure_ascii=False)}")

    except Exception as e:
        logger.error(f"log_ui_selection エラー: {e}")



def parse_duration_string(duration_text):
    """
    時間文字列を正規化して返す（強化版）
    入力例: "1:23", "12:34", "1:23:45", " 1:23 ", "1分23秒"
    出力例: "1:23", "12:34", "1:23:45"
    """
    if not duration_text:
        return None
    
    try:
        # 空白除去と基本クリーニング
        cleaned = duration_text.strip()
        
        # 日本語表記の変換
        cleaned = cleaned.replace('時間', ':').replace('分', ':').replace('秒', '')
        cleaned = cleaned.replace('時', ':').replace('分', ':')
        
        # 複数の区切り文字を統一
        cleaned = re.sub(r'[：]+', ':', cleaned)
        
        # 標準的な時間形式のパターンマッチング
        time_patterns = [
            r'^\d{1,2}:\d{2}:\d{2}$',  # 1:23:45
            r'^\d{1,2}:\d{2}$',        # 1:23
            r'^\d{1,3}$'               # 123 (秒のみ)
        ]
        
        for pattern in time_patterns:
            if re.match(pattern, cleaned):
                return cleaned
        
        # 数字のみの場合（秒として扱う）
        if cleaned.isdigit():
            seconds = int(cleaned)
            if seconds < 60:
                return f"0:{seconds:02d}"
            else:
                minutes = seconds // 60
                remaining_seconds = seconds % 60
                return f"{minutes}:{remaining_seconds:02d}"
        
        # 最後の手段：数字部分のみ抽出
        numbers = re.findall(r'\d+', cleaned)
        if len(numbers) >= 2:
            return f"{numbers[0]}:{numbers[1]}"
        elif len(numbers) == 1:
            return f"0:{numbers[0]}"
            
    except Exception as e:
        logger.error(f"時間文字列解析エラー [{duration_text}]: {e}")
    
    return None


def get_duration_with_enhanced_selectors(video_element):
    """
    強化されたセレクター群で動画時間を取得（2024年改良版）
    """
    global duration_stats
    duration_stats['total_attempts'] += 1
    
    # 設定からセレクターリストを取得（更新されたセレクター）
    system_config = get_system_config()
    selectors = system_config.get('enhanced_duration_selectors', [
        # 最新のYouTube構造に対応したセレクター
        "span.ytd-thumbnail-overlay-time-status-renderer",
        "ytd-thumbnail-overlay-time-status-renderer span.style-scope",
        "ytd-thumbnail-overlay-time-status-renderer span",
        ".badge-shape-wiz__text",  # 新しいバッジ形式
        "span[aria-label]"  # aria-label付きspan
    ])
    
    # 方法1: CSSセレクターで直接取得
    for i, selector in enumerate(selectors[:3]):  # 最初の3つのみ試行
        try:
            time_elements = video_element.find_elements(By.CSS_SELECTOR, selector)
            
            for element in time_elements:
                try:
                    # テキスト取得
                    duration_text = element.text.strip()
                    
                    # テキストが空の場合、innerTextを試行
                    if not duration_text:
                        duration_text = element.get_attribute("innerText") or ""
                        duration_text = duration_text.strip()
                    
                    if duration_text:
                        parsed_duration = parse_duration_string(duration_text)
                        if parsed_duration and re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', parsed_duration):
                            # 成功統計を記録
                            duration_stats['css_success'] += 1
                            selector_key = f"selector_{i+1}"
                            duration_stats['selector_success'][selector_key] = duration_stats['selector_success'].get(selector_key, 0) + 1
                            
                            return parsed_duration
                            
                except Exception:
                    continue
                    
        except Exception:
            continue
    
    # 方法2: aria-labelから抽出（改良版）
    try:
        # video-titleリンクからaria-labelを取得
        title_link = video_element.find_element(By.CSS_SELECTOR, "a#video-title, a#video-title-link")
        aria_label = title_link.get_attribute("aria-label")
        
        if aria_label:
            # 時間パターンを抽出（xx:xx または x:xx:xx）
            import re
            time_match = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?)', aria_label)
            if time_match:
                duration_text = time_match.group(1)
                parsed_duration = parse_duration_string(duration_text)
                if parsed_duration:
                    duration_stats['css_success'] += 1
                    duration_stats['selector_success']['aria_label'] = duration_stats['selector_success'].get('aria_label', 0) + 1
                    return parsed_duration
    except Exception:
        pass
    
    # 方法3: サムネイルのtitle属性から抽出
    try:
        thumbnail = video_element.find_element(By.CSS_SELECTOR, "ytd-thumbnail, a.ytd-thumbnail")
        title_attr = thumbnail.get_attribute("title")
        if title_attr:
            time_match = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?)', title_attr)
            if time_match:
                duration_text = time_match.group(1)
                parsed_duration = parse_duration_string(duration_text)
                if parsed_duration:
                    duration_stats['css_success'] += 1
                    duration_stats['selector_success']['thumbnail_title'] = duration_stats['selector_success'].get('thumbnail_title', 0) + 1
                    return parsed_duration
    except Exception:
        pass
    
    # すべて失敗した場合
    duration_stats['failed_videos'].append({
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'selectors_tried': len(selectors)
    })
    
    return None

def get_smart_playlist_for_channel(channel_name):
    """
    学習データ + ハードコード設定を統合したチャンネル振り分け（設定外部化対応版）
    優先順位: 1. 学習データ > 2. 設定ファイル > 3. 未設定
    """
    global learned_channels

    # 1. 学習データ優先（ユーザーの実際の判断）
    if channel_name in learned_channels:
        return learned_channels[channel_name]

    # 2. 設定ファイルのルール（既存の安定設定）
    return get_default_playlist_for_channel(channel_name)


def get_default_playlist_for_channel(channel_name):
    """設定ファイルのチャンネルルールを返す（設定外部化対応版）"""
    channel_rules = get_channel_keywords()
    for keyword, playlist in channel_rules.items():
        if keyword in channel_name:
            return playlist
    return "NONE"

def get_channel_count(videos):
    """動画リストからユニークなチャンネル数を取得"""
    channels = set()
    for video_data in videos:
        if len(video_data) >= 5:
            channels.add(video_data[4])
    return len(channels)

def show_time_and_category_dialog(auto_mode=False):
    """時間とカテゴリ選択ダイアログ（依存関係完全排除版）
    
    Args:
        auto_mode: Autoモードの初期値（デフォルトFalse）
    
    Returns:
        (hours_filter, ui_selection, project_choice, auto_enabled) または None
    """
    # デバッグログ：開始
    print(f"🔍 DEBUG: show_time_and_category_dialog 開始")
    print(f"🔍 DEBUG: auto_mode = {auto_mode}")
    
    # ★★★ グローバル変数から推奨時間を取得 ★★★
    recommended_hours = globals().get('DEFAULT_HOURS', 24.0)
    print(f"🔍 DEBUG: 推奨時間: {recommended_hours}")
    
    # ★★★ Autoモード設定のデフォルト値 ★★★
    initial_timer_seconds = 30  # デフォルト30秒
    
    # ダイアログ作成
    dialog = tk.Tk()
    dialog.title("YouTube動画取得設定")
    dialog.geometry("500x750")
    
    # 結果格納用
    result = {'values': None}
    
    # タイマー制御用変数
    auto_timer_id = None
    remaining_seconds = [initial_timer_seconds]
    
    def cancel_auto_timer(*args):
        """Autoタイマーをキャンセル"""
        nonlocal auto_timer_id
        if auto_timer_id:
            dialog.after_cancel(auto_timer_id)
            auto_timer_id = None
            if auto_var.get():
                timer_label.config(text="タイマー停止（手動操作を検出）")
    
    # メインフレーム
    main_frame = ttk.Frame(dialog, padding="20")
    main_frame.pack(fill="both", expand=True)
    
    # タイトル
    title_label = ttk.Label(
        main_frame,
        text="YouTube動画取得設定",
        font=("Meiryo", 16, "bold")
    )
    title_label.pack(pady=(0, 20))
    
    # 前回実行情報（簡易版）
    info_text = f"推奨取得時間: {recommended_hours}時間"
    info_label = ttk.Label(main_frame, text=info_text, foreground="blue")
    info_label.pack(pady=(0, 10))
    
    # 取得時間設定
    time_frame = ttk.LabelFrame(main_frame, text="取得時間設定", padding="10")
    time_frame.pack(fill="x", pady=10)
    
    ttk.Label(time_frame, text="過去").pack(side="left")
    
    # ★★★ recommended_hours を直接使用 ★★★
    print(f"🔍 DEBUG: hours_var の初期値設定: {recommended_hours}")
    hours_var = tk.DoubleVar(value=recommended_hours)
    print(f"🔍 DEBUG: hours_var.get() = {hours_var.get()}")
    
    hours_spinbox = ttk.Spinbox(
        time_frame,
        from_=0.1,
        to=24.0,
        increment=0.5,
        textvariable=hours_var,
        width=10
    )
    hours_spinbox.pack(side="left", padx=5)
    hours_spinbox.bind('<ButtonPress>', cancel_auto_timer)
    hours_spinbox.bind('<Key>', cancel_auto_timer)
    ttk.Label(time_frame, text="時間以内の動画を取得").pack(side="left")
    
    # カテゴリ選択
    category_frame = ttk.LabelFrame(main_frame, text="取得カテゴリ", padding="10")
    category_frame.pack(fill="x", pady=10)
    
    category_vars = {}
    categories = [
        ("all", "すべて"),
        ("short", "ショート動画を含む"),
        ("S", "S"),
        ("A", "A"),
        ("B", "B"),
        ("N", "N"),
        ("M", "M"),
        ("L", "L"),
        ("V", "V"),
        ("P+", "P+")
    ]

    # チェックボックス連動機能（変更なし）
    def on_all_changed():
        """「すべて」チェックボックスの変更時"""
        cancel_auto_timer()
        all_checked = category_vars["all"].get()
        for key, label in categories:
            if key != "all":
                category_vars[key].set(all_checked)

    def on_individual_changed():
        """個別チェックボックスの変更時"""
        cancel_auto_timer()
        individual_keys = [key for key, label in categories if key != "all"]
        all_checked = all(category_vars[key].get() for key in individual_keys)
        category_vars["all"].set(all_checked)

    # チェックボックス配置座標辞書（categoriesと必ず同期すること）
    grid_positions = {
        "all":   (0, 0), "short": (0, 1),
        "S":     (1, 0), "A":     (1, 1), "V":  (1, 2),
        "B":     (2, 0), "N":     (2, 1), "P+": (2, 2),
        "M":     (3, 0), "L":     (3, 1),
    }

    # チェックボックス作成
    for i, (key, label) in enumerate(categories):
        var = tk.BooleanVar(value=True)
        category_vars[key] = var

        if key == "all":
            check = ttk.Checkbutton(
                category_frame,
                text=label,
                variable=var,
                command=on_all_changed
            )
        else:
            check = ttk.Checkbutton(
                category_frame,
                text=label,
                variable=var,
                command=on_individual_changed
            )

        row, col = grid_positions[key]
        check.grid(row=row, column=col, sticky="w", padx=5, pady=2)
    
    # プロジェクト選択
    project_frame = ttk.LabelFrame(main_frame, text="APIプロジェクト", padding="10")
    project_frame.pack(fill="x", pady=10)
    
    project_var = tk.StringVar(value="auto")
    projects = [
        ("auto", "自動（クォータ状況に応じて切り替え）"),
        ("project1", "Project 1（固定）"),
        ("project2", "Project 2（固定）")
    ]
    
    for key, label in projects:
        radio = ttk.Radiobutton(project_frame, text=label, variable=project_var, value=key)
        radio.pack(anchor="w", pady=2)
        radio.bind('<ButtonPress>', cancel_auto_timer)
    
    # Autoモード設定
    auto_frame = ttk.LabelFrame(main_frame, text="実行モード", padding="10")
    auto_frame.pack(fill="x", pady=10)
    
    auto_var = tk.BooleanVar(value=auto_mode)
    auto_check = ttk.Checkbutton(
        auto_frame,
        text="Autoモード（タイマー自動進行）",
        variable=auto_var
    )
    auto_check.pack(anchor="w")
    
    # タイマー表示ラベル
    timer_label = ttk.Label(auto_frame, text="", foreground="green")
    timer_label.pack(anchor="w", pady=(5, 0))
    
    # Auto説明
    auto_desc = ttk.Label(
        auto_frame,
        text="Autoモードでは各ダイアログがタイマーで自動進行します\n手動で操作するとタイマーは停止します",
        font=("Meiryo", 9),
        foreground="gray"
    )
    auto_desc.pack(anchor="w", pady=(5, 0))
    
    def update_timer():
        """タイマーカウントダウン表示"""
        nonlocal auto_timer_id
        
        if not auto_var.get():
            timer_label.config(text="")
            return
        
        if remaining_seconds[0] > 0:
            timer_label.config(
                text=f"{remaining_seconds[0]}秒後に自動実行",
                foreground="green"
            )
            remaining_seconds[0] -= 1
            auto_timer_id = dialog.after(1000, update_timer)
        else:
            # タイムアウト：自動でOKクリック
            logger.info("Autoモード: タイマータイムアウト - 自動実行")
            ok_button.invoke()
    
    def on_auto_changed(*args):
        """Autoチェックボックス変更時"""
        if auto_var.get():
            remaining_seconds[0] = initial_timer_seconds
            update_timer()
        else:
            cancel_auto_timer()
            timer_label.config(text="")
    
    auto_var.trace('w', on_auto_changed)
    
    # ボタンフレーム
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill="x", pady=20)
    
    def on_ok():
        """OK時の処理"""
        # UI選択状態を構築
        ui_selection = {key: var.get() for key, var in category_vars.items()}
        
        result['values'] = (
            hours_var.get(),
            ui_selection,
            project_var.get(),
            auto_var.get()
        )
        
        print(f"🔍 DEBUG: OK押下時の hours_var.get() = {hours_var.get()}")
        logger.info(f"設定完了: {hours_var.get()}時間, Auto={auto_var.get()}")
        dialog.destroy()
    
    def on_cancel():
        """キャンセル時の処理"""
        result['values'] = None
        dialog.destroy()
    
    ok_button = ttk.Button(button_frame, text="OK", command=on_ok, width=15)
    ok_button.pack(side="left", padx=5)
    ok_button.bind('<ButtonPress>', cancel_auto_timer)
    
    cancel_button = ttk.Button(button_frame, text="キャンセル", command=on_cancel, width=15)
    cancel_button.pack(side="left", padx=5)
    
    # ウィンドウを中央に配置
    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
    y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
    dialog.geometry(f"+{x}+{y}")
    
    # Autoモードが有効なら初回タイマー起動
    if auto_var.get():
        dialog.after(100, update_timer)
    
    dialog.mainloop()
    
    print(f"🔍 DEBUG: ダイアログ終了 - result['values'] = {result['values']}")
    
    return result['values']


def get_time_filter():
    """GUIでフィルタリング時間を取得（デフォルト値使用）"""
    root = tk.Tk()
    root.withdraw()
    
    logger.info("時間設定ダイアログ表示")
    
    hours_input = simpledialog.askfloat(
        "時間設定", 
        f"何時間以内の動画を取得しますか？\n\n"
        f"💡 前回実行からの経過時間: {DEFAULT_HOURS}時間\n"
        f"📝 おすすめ: {DEFAULT_HOURS}\n"
        f"🔧 範囲: 0.1〜168時間",
        initialvalue=DEFAULT_HOURS,
        minvalue=0.1,
        maxvalue=168
    )
    
    root.destroy()
    
    if hours_input is None:
        logger.warning("時間設定がキャンセルされました")
        return None
    
    logger.info(f"設定時間: {hours_input}時間")
    return hours_input



# ===== Chrome接続管理（高速化版）（設定外部化対応版） =====


def check_chrome_debug_port(port=9222, timeout=3):

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        
        if result == 0:
            logger.info(f"デバッグポート{port}で既存のChrome検出")
            return True
        else:
            logger.info(f"デバッグポート{port}でChromeが見つかりません")
            return False
    except Exception as e:
        logger.debug(f"ポートチェックエラー: {e}")
        return False



def start_chrome_debug_mode():
    """デバッグモードでChromeを自動起動（修正版）"""
    import subprocess
    import platform
    
    try:
        logger.info("Chrome自動起動処理開始")
        
        # 設定から読み込み
        system_config = get_system_config()
        chrome_config = system_config.get('chrome_debug', {})
        
        # Chrome実行パスとプロファイルディレクトリ
        # [20260806] youtube_summary_list_*.py・各バッチファイルと同じプロファイルフォルダに
        # 統一する。以前は ~\Documents\ChromeDebugProfile という別フォルダがデフォルトだった
        # ため、Chromeが未起動の状態でこのツールを単体起動すると、要約コード側とは別の
        # プロファイル（別ログイン状態・別ブックマーク）でChromeが立ち上がっていた。
        if platform.system() == "Windows":
            default_chrome_path = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
            default_user_data_dir = os.path.join(
                os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                "ChromeDebugProfile_20260725"
            )
        else:
            default_chrome_path = "/usr/bin/google-chrome"
            default_user_data_dir = os.path.expanduser("~/ChromeDebugProfile")
        
        chrome_path = chrome_config.get('chrome_path', default_chrome_path)
        user_data_dir = chrome_config.get('user_data_dir', default_user_data_dir)
        debug_port = chrome_config.get('debug_port', 9222)
        
        # ユーザーデータディレクトリの作成
        os.makedirs(user_data_dir, exist_ok=True)
        
        # 既存のデバッグポートをチェック
        if check_chrome_debug_port(debug_port):
            logger.info("既にデバッグモードのChromeが起動しています")
            
            # 既存のChromeでYouTubeページを開く
            try:
                options = webdriver.ChromeOptions()
                options.add_experimental_option("debuggerAddress", f"localhost:{debug_port}")
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
                
                # YouTubeページに遷移
                current_url = driver.current_url
                if "youtube.com/feed/subscriptions" not in current_url:
                    logger.info("YouTube登録チャンネルページにアクセス")
                    driver.get("https://www.youtube.com/feed/subscriptions")
                    # ★ 待機時間を大幅に延長（2秒 -> 15秒）
                    logger.info("ページ描画待機中 (15秒)...")
                    time.sleep(15)
                else:
                    logger.info("既にYouTube登録チャンネルページを表示中")
                    # ★ 既に開いていても念のため待機
                    time.sleep(5)

                
                # driverは使い終わったので閉じる（ブラウザは閉じない）
                # driver.quit()を使うとブラウザも閉じるので注意
                
                return True
                
            except Exception as e:
                logger.warning(f"既存Chrome操作エラー: {e}")
                logger.info("既存Chromeを終了して新規起動します")
                # エラーの場合は既存Chromeを終了して新規起動
        
        # 既存のChromeプロセスを終了
        logger.info("既存のChromeプロセスを終了中...")
        if platform.system() == "Windows":
            subprocess.run("taskkill /F /IM chrome.exe", shell=True, capture_output=True)
        else:
            subprocess.run("pkill -f chrome", shell=True, capture_output=True)
        
        time.sleep(3)  # プロセス終了を待機
        
        # デバッグモードでChrome起動
        logger.info(f"デバッグモードでChrome起動中（ポート: {debug_port}）...")


        chrome_args = [
            chrome_path,
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            # [20260806] taskkill /F等で強制終了した直後に出る「ページを復元しますか？」
            # クラッシュ復元ダイアログを抑制する。
            "--disable-session-crashed-bubble",
            "--disable-dev-shm-usage",
            # "--disable-gpu",  # ★削除推奨: 描画のためにGPUが必要な場合があります
            "--no-sandbox",
            
            # ★★★ 画面OFF対策の重要フラグ追加 ★★★
            "--disable-backgrounding-occluded-windows", # ウィンドウが隠れていても処理を継続
            "--disable-background-timer-throttling",    # バックグラウンド時のタイマー制限を解除
            "--disable-renderer-backgrounding",         # レンダラーのバックグラウンド化を禁止
            "--window-size=1920,1080",                  # ウィンドウサイズを強制固定
            "--force-device-scale-factor=1",            # スケールを固定
            
            "https://www.youtube.com/feed/subscriptions"
        ]

        
        # Chromeプロセスを起動
        if platform.system() == "Windows":
            subprocess.Popen(chrome_args, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            subprocess.Popen(chrome_args)
        
        # Chrome起動を待機（長めに設定）
        logger.info("Chrome起動待機中...")
        time.sleep(5)  # 5秒→8秒に延長
        
        # 起動確認
        max_retries = 10
        for i in range(max_retries):
            if check_chrome_debug_port(debug_port):
                logger.info(f"✓ Chrome起動確認完了（試行{i+1}回目）")
                time.sleep(3)  # 追加の安定待機
                return True
            time.sleep(2)
        
        logger.error(f"Chrome起動確認タイムアウト（{max_retries}回試行）")
        return False
        
    except Exception as e:
        logger.error(f"Chrome自動起動エラー: {e}")
        return False


@timing_decorator
def get_chrome_debugger_connection():
    """Chrome DevToolsプロトコル接続を取得（自動起動対応版）"""
    
    # デバッグポートの確認
    if not check_chrome_debug_port():
        logger.info("Chromeが起動していないため、自動起動を実行")
        if not start_chrome_debug_mode():
            logger.error("Chrome自動起動に失敗しました")
            logger.error("手動でデバッグモードのChromeを起動してください:")
            logger.error("chrome.exe --remote-debugging-port=9222")
            return None
        
        # Chrome起動後の追加待機
        logger.info("Chrome起動後の安定化待機中...")
        time.sleep(3)
    else:
        logger.info("既存のデバッグモードChrome検出 - 接続を試行")
        time.sleep(2)
    
    ports = [9222, 9223, 9224, 9225]
    
    for port in ports:
        for attempt in range(3):
            try:
                logger.info(f"ポート{port}への接続試行 {attempt + 1}/3")
                
                options = webdriver.ChromeOptions()
                options.add_experimental_option("debuggerAddress", f"localhost:{port}")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                
                # Chrome Driverのバージョン自動管理
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
                
                # 接続確認（タイムアウト付き）
                driver.set_page_load_timeout(10)
                try:
                    title = driver.title
                    logger.info(f"Chrome接続成功 (ポート: {port})")
                    return driver
                    
                except Exception as test_error:
                    logger.warning(f"ポート{port}への接続は成功しましたが、操作に失敗: {test_error}")
                    driver.quit()
                    
                    if attempt < 2:
                        time.sleep(2)
                    continue
                    
            except Exception as e:
                logger.debug(f"ポート{port}への接続失敗（試行{attempt + 1}）: {e}")
                
                if attempt < 2:
                    time.sleep(2)
                continue
    
    logger.error("すべてのポートで接続に失敗しました")
    logger.error("以下を確認してください:")
    logger.error("1. Chromeがデバッグモードで起動していること")
    logger.error("2. 他のプログラムがポート9222-9225を使用していないこと")
    logger.error("3. ChromeDriverのバージョンがChromeと互換性があること")
    
    return None



def is_process_running(pid):
    """
    指定されたプロセスIDが実行中かを確認
    
    Args:
        pid (int): プロセスID
    
    Returns:
        bool: プロセスが実行中ならTrue、それ以外はFalse
    """
    try:
        # psutilでプロセスの存在を確認
        process = psutil.Process(pid)
        # プロセスが存在し、かつゾンビプロセスでないことを確認
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        # プロセスが存在しない
        return False
    except psutil.AccessDenied:
        # アクセス拒否された場合は、プロセスは存在すると判断
        # （他ユーザーのプロセスなど）
        return True
    except Exception as e:
        # その他のエラーは安全側に倒してFalseを返す
        logger.debug(f"プロセス確認エラー (PID:{pid}): {e}")
        return False



def force_cleanup_lockfile():
    """
    ロックファイルを強制的にクリーンアップ
    
    Returns:
        bool: クリーンアップ成功時True
    """
    try:
        lock_file = "youtube_tool.lock"
        if os.path.exists(lock_file):
            os.remove(lock_file)
            logger.info(f"古いロックファイルを削除しました: {lock_file}")
            return True
        return True
    except Exception as e:
        logger.error(f"ロックファイル削除エラー: {e}")
        return False



def is_process_running(pid):
    """
    指定されたプロセスIDが実行中かを確認
    
    Args:
        pid (int): プロセスID
    
    Returns:
        bool: プロセスが実行中ならTrue、それ以外はFalse
    """
    try:
        # psutilでプロセスの存在を確認
        process = psutil.Process(pid)
        # プロセスが存在し、かつゾンビプロセスでないことを確認
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        # プロセスが存在しない
        return False
    except psutil.AccessDenied:
        # アクセス拒否された場合は、プロセスは存在すると判断
        # （他ユーザーのプロセスなど）
        return True
    except Exception as e:
        # その他のエラーは安全側に倒してFalseを返す
        logger.debug(f"プロセス確認エラー (PID:{pid}): {e}")
        return False

def force_cleanup_lockfile():
    """
    ロックファイルを強制的にクリーンアップ
    
    Returns:
        bool: クリーンアップ成功時True
    """
    try:
        lock_file = "youtube_tool.lock"
        if os.path.exists(lock_file):
            os.remove(lock_file)
            logger.info(f"古いロックファイルを削除しました: {lock_file}")
            return True
        return True
    except Exception as e:
        logger.error(f"ロックファイル削除エラー: {e}")
        return False


def check_single_instance():
    """
    プログラムの多重起動をチェック（改善版）
    
    改善点：
    - 空ファイルチェック追加
    - プロセスID実在確認追加
    - タイムアウト短縮（5分→2分）
    - より堅牢なエラーハンドリング
    
    Returns:
        file handle or None: ロックファイルのハンドル（成功時）、None（多重起動検出時）
    """
    lock_file = "youtube_tool.lock"
    
    try:
        # 既存のロックファイルチェック
        if os.path.exists(lock_file):
            logger.debug(f"既存のロックファイル検出: {lock_file}")
            
            # ファイルの最終更新時刻を確認
            file_age = time.time() - os.path.getmtime(lock_file)
            
            # タイムアウト: 2分（120秒）に短縮
            LOCK_TIMEOUT = 120
            
            if file_age < LOCK_TIMEOUT:
                # ファイルが新しい場合、内容を確認
                try:
                    with open(lock_file, 'r') as f:
                        content = f.read().strip()
                    
                    # 空ファイルチェック（改善1）
                    if not content:
                        logger.warning("空のロックファイルを検出 - 前回異常終了の可能性")
                        logger.info("古いロックファイルを削除して続行します")
                        force_cleanup_lockfile()
                    else:
                        # プロセスIDの抽出
                        try:
                            old_pid = int(content)
                            
                            # プロセス存在確認（改善2）
                            if is_process_running(old_pid):
                                # プロセスが実際に実行中
                                logger.error(f"別のインスタンスが実行中です (PID: {old_pid})")
                                logger.error(f"ロックファイル経過時間: {file_age:.1f}秒")
                                return None
                            else:
                                # プロセスが存在しない = 前回異常終了
                                logger.warning(f"古いロックファイル検出 (PID: {old_pid} は存在しません)")
                                logger.info("前回のプロセスが異常終了したと判断")
                                force_cleanup_lockfile()
                        
                        except ValueError:
                            # PIDが数値でない = 破損ファイル
                            logger.warning(f"破損したロックファイル検出: 内容='{content}'")
                            force_cleanup_lockfile()
                
                except Exception as e:
                    logger.warning(f"ロックファイル読み込みエラー: {e}")
                    # 読み込みエラーの場合も削除して続行
                    force_cleanup_lockfile()
            else:
                # タイムアウト超過（120秒以上経過）
                logger.info(f"古いロックファイル検出（{file_age:.1f}秒経過）- 削除して続行")
                force_cleanup_lockfile()
        
        # 新しいロックファイルを作成
        lock_handle = open(lock_file, 'w')
        current_pid = os.getpid()
        lock_handle.write(f"{current_pid}\n")
        lock_handle.flush()  # 確実にディスクに書き込み（改善4）
        os.fsync(lock_handle.fileno())  # さらに確実に
        
        logger.info(f"ロックファイル作成成功 (PID: {current_pid})")
        return lock_handle
    
    except Exception as e:
        logger.error(f"ロックファイル処理エラー: {e}")
        # エラー時は安全側に倒して続行を許可
        logger.warning("エラーのため多重起動チェックをスキップします")
        try:
            lock_handle = open(lock_file, 'w')
            lock_handle.write(f"{os.getpid()}\n")
            lock_handle.flush()
            return lock_handle
        except:
            return True  # 最悪の場合でも起動は許可





@timing_decorator
def get_youtube_service():
    """YouTube API サービスを取得（複数プロジェクト対応版）"""
    global PROJECT_MANAGER, global_quota_monitor
    
    # Multi-project モードを試行
    try:
        if PROJECT_MANAGER is None:
            logging.info("🚀 Initializing Multi-Project Manager...")
            PROJECT_MANAGER = MultiProjectManager()
            
            # クォータ状況表示
            status = PROJECT_MANAGER.get_quota_status()
            logging.info(f"📊 Total Quota: {status['total_used']}/{status['total_limit']}")
        
        service = PROJECT_MANAGER.get_current_service()
        if service:
            # 🔧 追加: YouTube API Service作成時のクォータ記録
            if global_quota_monitor:
                global_quota_monitor.record_api_call('youtube.service.build', 1, success=True)
            return service
    except Exception as e:
        logging.warning(f"⚠️ Multi-project initialization failed: {e}")
    
    # フォールバック：従来の単一プロジェクト方式（既存コードを維持）
    creds = None
    
    # token.pickle から認証情報を読み込み
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    
    # 認証情報が無効またはトークンが無い場合
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # 🔧 追加: トークンリフレッシュ時のクォータ記録
            if global_quota_monitor:
                global_quota_monitor.record_api_call('oauth2.refresh', 1, success=True)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", ["https://www.googleapis.com/auth/youtube"])
            creds = flow.run_local_server(port=0)
            # 🔧 追加: 新規認証時のクォータ記録
            if global_quota_monitor:
                global_quota_monitor.record_api_call('oauth2.new_auth', 2, success=True)
        
        # token.pickle に保存
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    
    # 🔧 追加: YouTube API Service作成時のクォータ記録
    youtube_service = build("youtube", "v3", credentials=creds)
    if global_quota_monitor:
        global_quota_monitor.record_api_call('youtube.service.build', 1, success=True)
    
    return youtube_service




# ===== 動画取得の超高速化（設定外部化対応版） =====


@timing_decorator 
def fetch_subscribed_videos(hours_filter):
    """動画取得メイン関数（自動起動対応版 + 画面OFF診断機能付き）"""
    driver = get_chrome_debugger_connection()
    if not driver:
        logger.error("Chrome接続に失敗")
        return []
    
    # 【追加】解析用コード：画面OFF時の状態を記録して原因を特定する
    try:
        # 1. ウィンドウサイズを確認（極端に小さくなっていないか）
        size = driver.get_window_size()
        logger.info(f"🔍 解析: 現在のウィンドウサイズ: {size}")
        
        # 2. 現在のスクリーンショットを保存（真っ白/真っ黒になっていないか）
        # ※ファイル名にタイムスタンプを付与
        timestamp = datetime.now().strftime('%H%M%S')
        screenshot_path = f"debug_screen_off_{timestamp}.png"
        driver.save_screenshot(screenshot_path)
        logger.info(f"🔍 解析: スクリーンショット保存: {screenshot_path}")
        
        # 3. ページの状態を確認（hiddenになっていないか）
        visibility = driver.execute_script("return document.visibilityState;")
        logger.info(f"🔍 解析: ドキュメント表示状態: {visibility}")
        
    except Exception as e:
        logger.error(f"🔍 解析エラー: {e}")
    # 【追加ここまで】

    try:
        # Chrome自動起動時は既にYouTubeが開いているため、現在のURLを確認
        current_url = driver.current_url
        
        if "youtube.com/feed/subscriptions" not in current_url:
            logger.info("YouTube登録チャンネルページにアクセス")
            driver.get("https://www.youtube.com/feed/subscriptions")
            # ページ描画のため長めに待機 (前回分析に基づき 10秒 -> 15秒 に強化)
            logger.info("ページ描画待機中 (15秒)...")
            time.sleep(15) 
        else:
            logger.info("既にYouTube登録チャンネルページを表示中")
            # 既に開いていても、念のため少し待機 (3秒 -> 5秒 に強化)
            time.sleep(5)
        
        # ログインチェック
        if not quick_login_check(driver):
            logger.error("YouTubeにログインしていません")
            logger.error("Chromeでログインしてから再実行してください")
            return []
        
        # ページ状態のリセット（driver.refresh()は削除済み）
        # if not reset_page_state(driver):
        #     logger.warning("ページリセット失敗 - 続行")
        
        # ページ読み込み完了確認
        if not ensure_page_ready(driver, timeout=10):
            logger.warning("ページ準備確認タイムアウト - 続行")
        
        # 最小動画数の確認 (timeoutは分析に基づき30秒を維持)
        if not wait_for_minimum_videos(driver, min_count=10, timeout=30):
            logger.warning("最小動画数に達しませんでした - 利用可能な動画で続行")
            # 診断情報を収集
            collect_diagnostics(driver, "insufficient_videos")
        
        # リカバリー機能付きで動画収集実行
        def collection_with_filter(driver):
            return super_fast_video_collection_improved(driver, hours_filter)
        
        def recovery_action(driver):
            """リカバリーアクション"""
            # reset_page_state(driver)  # refresh削除済み
            ensure_page_ready(driver, timeout=5)
            wait_for_minimum_videos(driver, min_count=5, timeout=10)
        
        # リトライ機能付きで実行
        videos = retry_with_recovery(
            driver, 
            lambda d: super_fast_video_collection_improved(d, hours_filter),
            max_retries=3,
            recovery_action=recovery_action
        )
        
        if not videos:
            logger.error("全試行失敗 - 動画取得できませんでした")
        
        return videos
        
    except Exception as e:
        logger.error(f"動画取得中にエラー: {e}")
        collect_diagnostics(driver, "exception")
        return []
    finally:
        # 注意: Chromeは閉じずに維持（次回実行のため）
        logger.info("Chrome接続を維持（次回実行用）")
        # driver.quit()を実行しない




def wait_for_minimum_videos(driver, min_count=10, timeout=15):
    """最小数の動画要素が表示されるまで待機（新規追加）"""
    try:
        logger.info(f"最小{min_count}個の動画要素待機開始（最大{timeout}秒）")
        start_time = time.time()
        last_count = 0
        stable_count = 0
        
        while time.time() - start_time < timeout:
            # 複数のセレクターで動画要素を検出
            video_count = driver.execute_script("""
                const selectors = [
                    'ytd-rich-item-renderer',
                    'ytd-grid-video-renderer',
                    'ytd-video-renderer'
                ];
                const elements = new Set();
                
                selectors.forEach(selector => {
                    document.querySelectorAll(selector).forEach(el => {
                        // 有効な動画要素のみカウント
                        const link = el.querySelector('a#video-title, a#video-title-link');
                        if (link && link.href && link.href.includes('watch?v=')) {
                            elements.add(el);
                        }
                    });
                });
                
                return elements.size;
            """)
            
            logger.debug(f"現在の動画数: {video_count}")
            
            # 最小数に達した場合
            if video_count >= min_count:
                logger.info(f"✓ {video_count}個の動画要素を検出")
                return True
            
            # 動画数が安定した場合（3回連続で同じ数）
            if video_count == last_count:
                stable_count += 1
                if stable_count >= 3 and video_count > 0:
                    logger.info(f"動画数が{video_count}個で安定")
                    return True
            else:
                stable_count = 0
                last_count = video_count
            
            # まだ0個の場合は追加のスクロールを試みる
            if video_count == 0 and time.time() - start_time > 5:
                logger.debug("動画要素0個 - 軽いスクロールを実行")
                driver.execute_script("window.scrollBy(0, 500);")
            
            time.sleep(1)
        
        # タイムアウト時の最終確認
        final_count = driver.execute_script("""
            return document.querySelectorAll('ytd-rich-item-renderer, ytd-grid-video-renderer, ytd-video-renderer').length;
        """)
        
        logger.warning(f"動画要素待機タイムアウト - 最終数: {final_count}個")
        return final_count > 0  # 1個でもあればTrue
        
    except Exception as e:
        logger.error(f"動画要素待機エラー: {e}")
        return False

def ensure_page_ready(driver, timeout=10):
    """ページが完全に読み込まれたことを確認（新規追加）"""
    try:
        logger.info("ページ読み込み状態確認開始")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 1. document.readyStateチェック
                ready_state = driver.execute_script("return document.readyState")
                if ready_state != 'complete':
                    logger.debug(f"readyState: {ready_state} - 待機中...")
                    time.sleep(0.5)
                    continue
                
                # 2. YouTubeアプリの初期化確認
                yt_ready = driver.execute_script("""
                    return (typeof ytInitialData !== 'undefined' && 
                            ytInitialData !== null &&
                            document.querySelector('ytd-app') !== null &&
                            document.querySelector('ytd-browse[page-subtype="subscriptions"]') !== null);
                """)
                
                if not yt_ready:
                    logger.debug("YouTube アプリ初期化待機中...")
                    time.sleep(0.5)
                    continue
                
                # 3. 動画グリッドコンテナの存在確認
                container_exists = driver.execute_script("""
                    const containers = [
                        'ytd-rich-grid-renderer',
                        'ytd-section-list-renderer',
                        'ytd-two-column-browse-results-renderer'
                    ];
                    return containers.some(selector => document.querySelector(selector) !== null);
                """)
                
                if not container_exists:
                    logger.debug("動画コンテナ待機中...")
                    time.sleep(0.5)
                    continue
                
                # 4. ローディングスピナーが消えているか確認
                no_spinner = driver.execute_script("""
                    const spinner = document.querySelector('ytd-continuation-item-renderer paper-spinner');
                    return !spinner || spinner.style.display === 'none';
                """)
                
                if not no_spinner:
                    logger.debug("ローディング完了待機中...")
                    time.sleep(0.5)
                    continue
                
                logger.info("ページ読み込み完了確認")
                return True
                
            except Exception as e:
                logger.debug(f"状態確認中のエラー（リトライ）: {e}")
                time.sleep(0.5)
        
        logger.warning(f"ページ読み込み確認タイムアウト（{timeout}秒）")
        return False
        
    except Exception as e:
        logger.error(f"ページ読み込み確認エラー: {e}")
        return False



def reset_page_state(driver):
    """ページ状態をリセットして安定化（新規追加）"""
    try:
        logger.info("ページ状態リセット開始")
        
        # 現在のURLを保存
        current_url = driver.current_url
        
        # ページをリフレッシュ
        if "/feed/subscriptions" in current_url:
            logger.info("購読フィードをリフレッシュ")
            # driver.refresh()    # Chrome切断防止のため無効化
            time.sleep(2)
        else:
            # 一度別のページに移動してから戻る
            logger.info("ページリセット: about:blank経由")
            driver.get("about:blank")
            time.sleep(0.5)
            driver.get("https://www.youtube.com/feed/subscriptions")
            time.sleep(2)
        
        # タブにフォーカスを強制
        driver.execute_script("""
            window.focus();
            document.hasFocus = function() { return true; };
        """)
        
        # スクロール位置をトップにリセット
        driver.execute_script("window.scrollTo(0, 0);")
        
        # 前回のセッション残留要素をクリーンアップ
        driver.execute_script("""
            // 既存の処理済みマーカーを削除
            document.querySelectorAll('[data-processed]').forEach(el => {
                el.removeAttribute('data-processed');
            });
            
            // ローディング状態をクリア
            if (typeof ytInitialData !== 'undefined') {
                ytInitialData._isLoaded = true;
            }
        """)
        
        logger.info("ページ状態リセット完了")
        return True
        
    except Exception as e:
        logger.error(f"ページ状態リセットエラー: {e}")
        return False



def quick_login_check(driver):
    """高速ログイン確認（設定外部化対応版）"""
    try:
        # 設定からタイムアウト値を取得
        system_config = get_system_config()
        timeouts = system_config.get('timeouts', {})
        login_check_timeout = timeouts.get('login_check', 2)
        
        WebDriverWait(driver, login_check_timeout).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-guide-entry-renderer")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "#avatar-btn")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "yt-img-shadow#avatar"))
            )
        )
        return True
    except TimeoutException:
        return False


def js_batch_extract_videos(driver, processed_ids=None):
    """JavaScript一括実行で全動画データを高速取得（JSON転送版: タイトル・チャンネル・時間・日時取得強化）"""
    if processed_ids is None:
        processed_ids = []
    
    script = """
    const processedIds = new Set(arguments[0] || []);
    const results = [];
    const errors = [];
    
    try {
        // 全動画要素を一括取得（セレクター拡張）
        const selectors = [
            'ytd-rich-item-renderer',
            'ytd-grid-video-renderer', 
            'ytd-video-renderer',
            'ytd-compact-video-renderer',
            'ytd-rich-grid-media'
        ];
        
        const elements = document.querySelectorAll(selectors.join(','));
        
        // 要素数をログ
        console.log(`Found ${elements.length} potential video elements`);
        
        for (const elem of elements) {
            try {
                // Video ID取得用のリンク (セレクタ強化)
                let videoId = '';
                let href = '';
                
                // 複数のパターンでリンクを探索
                const linkSelectors = [
                    'a#video-title', 
                    'a#video-title-link', 
                    'ytd-thumbnail a', // グリッド表示用
                    'a#thumbnail',
                    'a.ytd-thumbnail',
                    'h3 a'
                ];
                
                for (const sel of linkSelectors) {
                    const link = elem.querySelector(sel);
                    if (link && link.href && link.href.includes('watch?v=')) {
                        href = link.href;
                        const match = href.match(/watch\\?v=([^&]+)/);
                        if (match) {
                            videoId = match[1];
                            break;
                        }
                    }
                }
                
                if (!videoId) {
                    // IDが見つからない場合は詳細を記録（デバッグ用）
                    if (elem.innerText && elem.innerText.trim().length > 0) {
                        errors.push({
                            message: 'Video ID not found',
                            element: elem.tagName,
                            textSample: elem.innerText.substring(0, 30)
                        });
                    }
                    continue;
                }
                
                if (processedIds.has(videoId)) continue;
                
                // タイトル（タイトル専用の要素から取得）
                let title = '';
                
                // タイトル取得ロジック強化
                const titleSelectors = [
                    '#video-title', 
                    '#video-title-link',
                    'a#video-title', 
                    'a#video-title-link',
                    'h3 a',
                    'yt-formatted-string#video-title'
                ];
                
                for (const sel of titleSelectors) {
                    const titleElem = elem.querySelector(sel);
                    if (titleElem) {
                        title = titleElem.textContent?.trim() || 
                               titleElem.title || 
                               titleElem.getAttribute('aria-label') || '';
                        if (title) break;
                    }
                }
                
                // 最終手段：aria-labelから取得
                if (!title) {
                    const ariaElements = elem.querySelectorAll('[aria-label]');
                    for (const ariaElem of ariaElements) {
                        const label = ariaElem.getAttribute('aria-label');
                        if (label && label.length > 10 && !label.includes('時間') && !label.includes('前')) {
                            title = label;
                            break;
                        }
                    }
                }
                
                // アップロード時間
                let uploadTime = '';
                // 修正: 新UI対応のクラス名を追加してaria-labelを取得可能にする
                const mainLink = elem.querySelector('a#video-title, a#video-title-link, a.yt-core-attributed-string__link');
                
                // 戦略1: aria-labelからの抽出（最も堅牢・グリッド表示対応）
                // 動画リンクには視覚障害者向けに全てのメタデータが含まれている
                if (mainLink) {
                    const ariaLabel = mainLink.getAttribute('aria-label') || '';
                    // "5 時間前", "5 hours ago" などのパターンを抽出
                    // PythonでのSyntaxWarning回避のためバックスラッシュをエスケープ
                    const timeRegex = /(\\d+)\\s*(分|時間|日|週|ヶ月|か月|年|minute|hour|day|week|month|year)s?\\s*(前|ago)/i;
                    const match = ariaLabel.match(timeRegex);
                    if (match) {
                        uploadTime = match[0];
                    }
                }

                // 戦略2: 従来のメタデータDOMからの取得（リスト表示等用・フォールバック）
                if (!uploadTime) {
                    // セレクタ強化: グリッド表示に対応
                    const timeElems = elem.querySelectorAll('#metadata-line span, .inline-metadata-item, span.ytd-video-meta-block, ytd-video-meta-block span');
                    for (const te of timeElems) {
                        const text = te.textContent?.trim() || '';
                        if (text.match(/前|ago|hour|day|week|month|year|時間|日|週|ヶ月|年/i)) {
                            uploadTime = text;
                            break;
                        }
                    }
                }
                
                // 戦略3: テキスト全体から正規表現で探索（最終手段）
                if (!uploadTime) {
                    const fullText = elem.innerText || '';
                    // 行ごとに分割して探索
                    const lines = fullText.split('\\n');
                    // 数字 + 単位 + 前/ago のパターン
                    const timeRegex = /(\\d+)\\s*(分|時間|日|週|ヶ月|か月|年|minute|hour|day|week|month|year)s?\\s*(前|ago)/i;
                    
                    for (const line of lines) {
                        // 配信予定は除外するが、「配信済み」は日時情報として有効なので許可する
                        if (timeRegex.test(line) && !line.includes('予定') && !line.includes('Scheduled')) {
                            uploadTime = line.trim();
                            break;
                        }
                    }
                }

                // 動画時間（複数セレクタ試行）
                let duration = '';
                const durationSelectors = [
                    'ytd-thumbnail-overlay-time-status-renderer span',
                    'span.ytd-thumbnail-overlay-time-status-renderer',
                    '.badge-shape-wiz__text',
                    'div.badge-shape-wiz__text',
                    'span.style-scope.ytd-thumbnail-overlay-time-status-renderer'
                ];
                for (const sel of durationSelectors) {
                    const dur = elem.querySelector(sel);
                    if (dur && dur.textContent) {
                        const text = dur.textContent.trim();
                        // ライブ配信や予定を除外
                        if (!text.includes('ライブ') && !text.includes('配信') && !text.includes('予定') && !text.includes('UPCOMING')) {
                            duration = text;
                            break;
                        }
                    }
                }
                
                // 動画時間フォールバック2: aria-labelから抽出
                if (!duration && mainLink) {
                    let ariaLabel = mainLink.getAttribute('aria-label') || '';
                    
                    // 誤検知を防ぐため、既に取得済みの投稿日時(uploadTime)の部分を削除して検索する
                    if (uploadTime) {
                        ariaLabel = ariaLabel.replace(uploadTime, '');
                    }
                    
                    // 時間パターン: "1時間 2分 30秒", "10 minutes, 20 seconds"
                    // 投稿日時(ago/前)と誤認しないよう、後ろにago/前が続かないものを探す(否定先読み)
                    const durRegex = /((?:\\d+\\s*(?:時間|hours?|hour)[\\s,]*?)?(?:\\d+\\s*(?:分|minutes?|minute)[\\s,]*?)?(?:\\d+\\s*(?:秒|seconds?|second)))(?!\\s*(?:ago|前))/i;
                    const matches = ariaLabel.match(durRegex);
                    
                    if (matches && matches[0]) {
                        // マッチした文字列が妥当か確認
                        duration = matches[0].trim().replace(/,$/, '');
                    }
                }
                
                // 動画時間フォールバック3: テキスト行解析 (Visual Analysis)
                // DOM構造に依存せず、見た目のテキスト行から時間形式を探す
                if (!duration) {
                    const fullText = elem.innerText || '';
                    const lines = fullText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                    // 時間パターン: 1:23, 12:34, 1:23:45
                    // 数字1-2桁 : 数字2桁 (: 数字2桁 オプション)
                    const timePattern = /^(\\d{1,2}):(\\d{2})(?::(\\d{2}))?$/;
                    
                    for (const line of lines) {
                        if (timePattern.test(line)) {
                            duration = line;
                            break;
                        }
                    }
                }

                // チャンネル名（複数セレクタ試行・強化版）
                let channel = '';
                const channelSelectors = [
                    'ytd-channel-name a',
                    '#channel-name a',
                    'a.yt-core-attributed-string__link',   // 新UI対応: 画像より特定
                    'ytd-channel-name #text-container a',  // グリッド表示用詳細
                    '#metadata ytd-channel-name a',        // メタデータ内
                    'a.yt-simple-endpoint.style-scope.yt-formatted-string', // 汎用フォーマット
                    '.ytd-channel-name',
                    'yt-formatted-string.ytd-channel-name'
                ];
                for (const sel of channelSelectors) {
                    const candidates = elem.querySelectorAll(sel);
                    for (const ch of candidates) {
                        // タイトルと同じテキストならスキップ（誤検知防止）
                        const text = ch.textContent?.trim() || '';
                        if (title && text === title) continue;
                        
                        if (text.length > 0) {
                            channel = text;
                            break;
                        }
                    }
                    if (channel) break;
                }
                
                // チャンネル名取得フォールバック: テキスト行解析 (Visual layout analysis)
                // DOM構造に依存せず、見た目の行並びから推測する
                if (!channel) {
                    const fullText = elem.innerText || '';
                    const lines = fullText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                    
                    let titleIndex = -1;
                    if (title) {
                        titleIndex = lines.indexOf(title);
                    }
                    
                    for (let i = 0; i < lines.length; i++) {
                        const line = lines[i];
                        if (line === title) continue;
                        if (line === duration) continue;
                        if (line === uploadTime) continue;
                        
                        // 時間・回数っぽい行を除外
                        if (line.match(/(\\d+|[\\d,.]+[万億KMB]?)\\s*(回視聴|views)/)) continue;
                        if (line.match(/(\\d+)\\s*(分|時間|日|週|ヶ月|か月|年|minute|hour|day|week|month|year)s?\\s*(前|ago)/)) continue;
                        
                        // タイトルより後の行で、かつ除外されなかった最初の行をチャンネルとする
                        // (通常、チャンネル名はタイトルの直下にある)
                        if (titleIndex !== -1 && i > titleIndex) {
                            channel = line;
                            break;
                        }
                    }
                }
                
                // ショート/ライブ判定
                const textContent = elem.textContent || '';
                const isShort = textContent.includes('Shorts') || 
                                textContent.includes('ショート') ||
                                elem.querySelector('ytd-thumbnail-overlay-time-status-renderer[overlay-style="SHORTS"]') !== null;
                const isLive = textContent.includes('ライブ') || 
                               textContent.includes('配信中') ||
                               textContent.includes('LIVE');
                
                // 最低限のデータがある場合のみ追加
                if (videoId && (title || channel)) {
                    results.push({
                        id: videoId,
                        title: title || 'タイトル不明',
                        channel: channel || 'チャンネル不明',
                        duration: duration,
                        uploadTime: uploadTime,
                        rawTime: uploadTime, // 調査用生データ
                        isShort: isShort,
                        isLive: isLive
                    });
                } else {
                    if (videoId) {
                        errors.push({
                            message: 'Title or Channel missing',
                            videoId: videoId,
                            hasTitle: !!title,
                            hasChannel: !!channel
                        });
                    }
                }
            } catch (e) {
                errors.push({
                    message: e.message,
                    element: elem.tagName
                });
                continue;
            }
        }
        
        // デバッグ情報を返却
        return JSON.stringify({
            success: true,
            videos: results,
            elementCount: elements.length,
            errorCount: errors.length,
            errors: errors.slice(0, 10)  // 最初のエラーを多めに返す
        });
        
    } catch (e) {
        return JSON.stringify({
            success: false,
            videos: [],
            error: e.message,
            stack: e.stack
        });
    }
    """
    
    try:
        # WebDriverのデシリアライズエラーを回避するためJSON文字列で受け取る
        import json
        raw_result = driver.execute_script(script, list(processed_ids))
        result = json.loads(raw_result) if raw_result else {}
        
        # 結果の検証とログ
        if isinstance(result, dict):
            if not result.get('success', False):
                logger.error(f"JS実行エラー: {result.get('error', 'unknown')}")
                return []
            
            videos = result.get('videos', [])
            element_count = result.get('elementCount', 0)
            error_count = result.get('errorCount', 0)
            
            if element_count > 0 and len(videos) == 0:
                logger.warning(f"要素は{element_count}個見つかりましたが、有効な動画は0個でした")
                if result.get('errors'):
                    for i, err in enumerate(result['errors'][:5]):
                        logger.debug(f"要素エラー[{i}]: {err}")
            elif error_count > 0:
                logger.debug(f"一部要素でエラー: {error_count}個")
                for i, err in enumerate(result.get('errors', [])[:3]):
                     logger.debug(f"抽出スキップ理由[{i}]: {err}")
            
            # 調査用: タイトルと取得した時間をログに出力
            if videos and len(videos) > 0:
                v = videos[0]
                logger.info(f"調査取得例: '{v.get('title', 'なし')[:20]}...' 時間='{v.get('uploadTime', 'なし')}' (raw='{v.get('rawTime', '')}')")
            
            return videos
        else:
            # 後方互換性のため、配列が返された場合
            return result if isinstance(result, list) else []
            
    except Exception as e:
        logger.error(f"js_batch_extract_videos実行エラー: {e}")
        return []




@timing_decorator
def super_fast_video_collection_improved(driver, hours_filter):
    """改善版: 安定性を重視した動画収集（無限ループ防止対策済み・短時間指定時の日時不明SKIP対応版）"""
    videos = []
    processed_ids = set()
    cutoff_time = datetime.now() - timedelta(hours=hours_filter)
    consecutive_old_videos = 0
    old_videos_threshold = 10
    consecutive_unknown_videos = 0
    unknown_videos_threshold = 100
    unknown_time_skip_enabled = hours_filter <= 12
    
    logger.info(f"動画収集開始（安定性改善版）- 過去{hours_filter}時間以内の動画を取得")
    logger.info(f"カットオフ時刻: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(
        f"DEBUG_COLLECTION_START|hours_filter={hours_filter}|"
        f"cutoff_time={cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}|"
        f"old_threshold={old_videos_threshold}|unknown_threshold={unknown_videos_threshold}|"
        f"unknown_time_policy={'SKIP' if unknown_time_skip_enabled else 'KEEP'}"
    )
    
    no_new_count = 0
    scroll_count = 0
    max_scrolls = 100
    
    # 初回取得の改善
    initial_videos = []
    for attempt in range(3):  # 3回まで試行
        initial_videos = js_batch_extract_videos(driver, processed_ids)
        if initial_videos and len(initial_videos) >= 10:
            break
        
        if attempt < 2:
            logger.warning(f"初回取得不十分（{len(initial_videos)}件） - 再試行 {attempt + 2}/3")
            time.sleep(2)
            # 軽いスクロールして再試行
            driver.execute_script("window.scrollBy(0, 300);")
            time.sleep(1)
    
    logger.info(f"初回取得: {len(initial_videos)}件")
    
    # 初回取得が極端に少ない場合の診断
    if len(initial_videos) < 5:
        logger.warning(f"⚠️ 初回取得が異常に少ない: {len(initial_videos)}件")
        diagnostics = collect_diagnostics(driver, "low_initial_fetch")
        
        # 診断結果に基づく追加対応
        if diagnostics.get("youtube_state", {}).get("isLoading"):
            logger.info("ページがまだロード中 - 追加待機")
            time.sleep(3)
            initial_videos = js_batch_extract_videos(driver, processed_ids)
            logger.info(f"追加待機後の取得: {len(initial_videos)}件")
    
    # メインループ
    while scroll_count < max_scrolls:
        new_videos = js_batch_extract_videos(driver, processed_ids)
        
        if not new_videos:
            no_new_count += 1
            if no_new_count >= 15:
                # 最終確認の改善
                logger.info("新規動画なし - 最終確認実施")
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                final_check = js_batch_extract_videos(driver, processed_ids)
                if not final_check:
                    logger.info(f"新規動画なし - 収集終了（{len(videos)}件取得済み）")
                    break
                else:
                    new_videos = final_check
                    no_new_count = 0
        else:
            no_new_count = 0
            
            # 新規動画を処理
            new_video_count = 0
            videos_in_this_batch = 0
            old_videos_in_batch = 0
            unknown_videos_in_batch = 0
            short_skip_in_batch = 0
            live_skip_in_batch = 0
            duplicate_in_batch = 0
            
            for video in new_videos:
                if video['id'] in processed_ids:
                    duplicate_in_batch += 1
                    logger.debug(
                        f"DEBUG_VIDEO_DECISION|decision=DUPLICATE_IN_SCROLL|video_id={video.get('id')}|"
                        f"title={video.get('title', '')[:80]}"
                    )
                    continue
                
                processed_ids.add(video['id'])
                videos_in_this_batch += 1
                
                # 時間パース
                raw_time = video.get('uploadTime')
                upload_time = parse_relative_time(raw_time) if raw_time else None
                video_id = video.get('id', '')
                title_for_log = video.get('title', '')[:80]
                channel_for_log = video.get('channel', '')
                duration_for_log = video.get('duration', '')
                raw_time_for_log = raw_time if raw_time else "None"
                    
                # 時間フィルタチェック
                if upload_time is None:
                    # 日時不明は、短時間指定では安全側に倒して自動登録対象から除外する
                    # ただし無限ループ防止のため、不明連続数は従来通りカウントする
                    consecutive_unknown_videos += 1
                    consecutive_old_videos = 0 # 老番カウンタはリセット
                    unknown_videos_in_batch += 1
                    
                    if unknown_time_skip_enabled:
                        logger.info(
                            f"DEBUG_VIDEO_DECISION|decision=UNKNOWN_TIME_SKIP|video_id={video_id}|"
                            f"raw_time={raw_time_for_log}|parsed_time=None|"
                            f"cutoff_time={cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}|"
                            f"hours_filter={hours_filter}|policy_threshold=12|"
                            f"duration={duration_for_log}|channel={channel_for_log}|title={title_for_log}"
                        )
                        
                        if consecutive_unknown_videos >= unknown_videos_threshold:
                            logger.warning(f"⚠️ 日時不明な動画が{unknown_videos_threshold}件連続しました。無限ループ防止のため収集を終了します。")
                            logger.info(
                                f"DEBUG_COLLECTION_ABORT|reason=unknown_time_threshold|"
                                f"unknown_threshold={unknown_videos_threshold}|collected={len(videos)}|processed={len(processed_ids)}"
                            )
                            return videos
                        
                        continue
                    
                    logger.info(
                        f"DEBUG_VIDEO_DECISION|decision=UNKNOWN_TIME_KEEP|video_id={video_id}|"
                        f"raw_time={raw_time_for_log}|parsed_time=None|"
                        f"cutoff_time={cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}|"
                        f"hours_filter={hours_filter}|policy_threshold=12|"
                        f"duration={duration_for_log}|channel={channel_for_log}|title={title_for_log}"
                    )
                    
                    if consecutive_unknown_videos >= unknown_videos_threshold:
                        logger.warning(f"⚠️ 日時不明な動画が{unknown_videos_threshold}件連続しました。無限ループ防止のため収集を終了します。")
                        logger.info(
                            f"DEBUG_COLLECTION_ABORT|reason=unknown_time_threshold|"
                            f"unknown_threshold={unknown_videos_threshold}|collected={len(videos)}|processed={len(processed_ids)}"
                        )
                        return videos
                        
                elif upload_time < cutoff_time:
                    # 日時判明かつ古い -> 古い動画としてカウント
                    consecutive_unknown_videos = 0 # 不明カウンタはリセット
                    consecutive_old_videos += 1
                    old_videos_in_batch += 1
                    logger.info(
                        f"DEBUG_VIDEO_DECISION|decision=OLD_SKIP|video_id={video_id}|"
                        f"raw_time={raw_time_for_log}|parsed_time={upload_time.strftime('%Y-%m-%d %H:%M:%S')}|"
                        f"cutoff_time={cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}|"
                        f"old_consecutive={consecutive_old_videos}|duration={duration_for_log}|"
                        f"channel={channel_for_log}|title={title_for_log}"
                    )
                        
                    # デバッグログ（最初の数件のみ、かつ日時がある場合）
                    if consecutive_old_videos <= 3 and upload_time:
                        time_diff = cutoff_time - upload_time
                        logger.debug(f"古い動画検出 [{consecutive_old_videos}件目]: {video['title'][:30]}... "
                                   f"({time_diff.total_seconds()/3600:.1f}時間前)")
                        
                    # 連続古い動画が閾値に達したら終了
                    if consecutive_old_videos >= old_videos_threshold:
                            # 修正: 処理したユニーク動画数が少ない（例:50件未満）間は、
                            # 「関連動画」などの古い動画ブロックを通過中である可能性が高いため、終了せずスキャンを継続する
                        if len(processed_ids) < 50:
                            logger.debug(f"初期スキャン期間中のため、古い動画が連続しても継続します (処理済み: {len(processed_ids)}件, 連続古い: {consecutive_old_videos}件)")
                        else:
                            logger.info(f"🔍 古い動画が{consecutive_old_videos}件連続で検出されました")
                            logger.info(f"⏰ 設定時間({hours_filter}時間)を超える動画に到達 → 収集終了")
                            logger.info(f"✅ 取得済み動画: {len(videos)}件")
                            logger.info(
                                f"DEBUG_COLLECTION_END|reason=old_threshold|collected={len(videos)}|"
                                f"processed={len(processed_ids)}|scroll_count={scroll_count}|"
                                f"old_consecutive={consecutive_old_videos}"
                            )
                            return videos
                    
                    continue  # 古い動画はスキップ
                else:
                    # 日時判明かつ新しい -> リセット
                    consecutive_unknown_videos = 0
                    consecutive_old_videos = 0
                    logger.info(
                        f"DEBUG_VIDEO_DECISION|decision=NEW_KEEP|video_id={video_id}|"
                        f"raw_time={raw_time_for_log}|parsed_time={upload_time.strftime('%Y-%m-%d %H:%M:%S')}|"
                        f"cutoff_time={cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}|"
                        f"duration={duration_for_log}|channel={channel_for_log}|title={title_for_log}"
                    )
                
                # ショート/ライブ除外
                if video.get('isShort'):
                    short_skip_in_batch += 1
                    logger.info(
                        f"DEBUG_VIDEO_DECISION|decision=SHORT_SKIP|video_id={video_id}|"
                        f"raw_time={raw_time_for_log}|duration={duration_for_log}|title={title_for_log}"
                    )
                    continue
                if video.get('isLive'):
                    live_skip_in_batch += 1
                    logger.info(
                        f"DEBUG_VIDEO_DECISION|decision=LIVE_SKIP|video_id={video_id}|"
                        f"raw_time={raw_time_for_log}|duration={duration_for_log}|title={title_for_log}"
                    )
                    continue
                
                # 動画データ作成
                video_data = (
                    video['id'],
                    video['title'],
                    upload_time or datetime.now(), # 表示用にNoneなら現在時刻を入れる
                    video['duration'] or "時間不明",
                    video['channel'] or "不明なチャンネル"
                )
                
                # デバッグログ追加
                logger.debug(f"DEBUG: video_data作成 - title={video['title'][:30]}, duration={video['duration']}")
                
                videos.append(video_data)
                new_video_count += 1
            
            # バッチ処理結果のログ
            if videos_in_this_batch > 0:
                if old_videos_in_batch > 0:
                    logger.debug(f"バッチ処理: 新規{new_video_count}件追加、"
                               f"古い動画{old_videos_in_batch}件スキップ（連続{consecutive_old_videos}件）")
                else:
                    logger.debug(f"新規{new_video_count}件追加（合計{len(videos)}件）")
        
        # 早期終了の追加条件
        if scroll_count > 5 and len(videos) == 0 and consecutive_old_videos > 5:
            logger.info(f"⚠️ 新しい動画が見つからず、古い動画のみ検出（{consecutive_old_videos}件）")
            logger.info(f"過去{hours_filter}時間以内に新しい動画がない可能性があります")
            # 診断情報を収集
            collect_diagnostics(driver, "no_recent_videos")
            break
        
        # スクロール
        driver.execute_script("window.scrollBy(0, window.innerHeight * 3);")
        time.sleep(1.5)
        scroll_count += 1
        
        # 進捗ログ（10回ごと）
        if scroll_count % 10 == 0:
            logger.info(f"収集中: {len(videos)}件取得済み（スクロール{scroll_count}回）"
                       f" | 古い動画連続: {consecutive_old_videos}件")
    
    # 収集終了時の詳細ログ
    if consecutive_old_videos > 0:
        logger.info(f"動画収集完了: {len(videos)}件（最後に{consecutive_old_videos}件の古い動画を検出）")
    else:
        logger.info(f"動画収集完了: {len(videos)}件")
    
    # 収集結果が少ない場合の診断
    if len(videos) < 10:
        logger.warning(f"収集動画数が少ない: {len(videos)}件")
        collect_diagnostics(driver, "low_video_count")
    
    return videos



def parse_relative_time(time_text):
    """相対時間をdatetimeに変換（相対時刻パターン抽出・混在文字列対策版）"""
    now = datetime.now()
    original_time_text = time_text
    
    try:
        if not time_text:
            logger.info("DEBUG_TIME_PARSE|status=empty|raw=None|parsed=None")
            return None

        time_text = str(time_text).strip()
        if not time_text:
            logger.info(f"DEBUG_TIME_PARSE|status=empty_after_strip|raw={original_time_text}|parsed=None")
            return None

        # 投稿時刻の相対表現だけを抽出する
        # 目的:
        #   - "2:42 ... 22 時間前" のような混在文字列で、動画時間の "2" を拾わない
        #   - "22 時間前", "22 時間前 に配信済み", "22 hours ago" を投稿時刻として拾う
        relative_time_patterns = [
            (
                r'(\d+)\s*(分|時間|日|週|ヶ月|か月|月|年)\s*前(?:\s*に配信済み)?',
                "jp"
            ),
            (
                r'(\d+)\s*(minute|minutes|min|mins|hour|hours|day|days|week|weeks|month|months|year|years)\s*ago',
                "en"
            )
        ]

        matches = []
        for pattern, language in relative_time_patterns:
            for match in re.finditer(pattern, time_text, flags=re.IGNORECASE):
                matches.append({
                    "start": match.start(),
                    "text": match.group(0),
                    "value": int(match.group(1)),
                    "unit_text": match.group(2).lower(),
                    "language": language
                })

        if not matches:
            logger.info(f"DEBUG_TIME_PARSE|status=no_relative_time|raw={original_time_text}|parsed=None")
            logger.debug(f"Time Parse Failed (No relative time pattern): '{time_text}' -> None")
            return None

        # YouTubeのraw文字列では、動画時間・タイトル・視聴回数の後ろに投稿時刻が来ることが多い。
        # そのため、複数候補がある場合は最後に出現した相対時刻を採用する。
        selected = sorted(matches, key=lambda item: item["start"])[-1]
        value = selected["value"]
        unit_text = selected["unit_text"]
        matched_text = selected["text"]
        result = now
        unit = "unknown"

        if unit_text in ["分", "minute", "minutes", "min", "mins"]:
            unit = "minutes"
            result = now - timedelta(minutes=value)
        elif unit_text in ["時間", "hour", "hours"]:
            unit = "hours"
            result = now - timedelta(hours=value)
        elif unit_text in ["日", "day", "days"]:
            unit = "days"
            result = now - timedelta(days=value)
        elif unit_text in ["週", "week", "weeks"]:
            unit = "weeks"
            result = now - timedelta(weeks=value)
        elif unit_text in ["ヶ月", "か月", "月", "month", "months"]:
            unit = "months_30days"
            result = now - timedelta(days=value * 30)
        elif unit_text in ["年", "year", "years"]:
            unit = "years_365days"
            result = now - timedelta(days=value * 365)
        else:
            logger.info(
                f"DEBUG_TIME_PARSE|status=unknown_unit|raw={original_time_text}|"
                f"matched={matched_text}|value={value}|unit_text={unit_text}|parsed=None"
            )
            return None
            
        logger.info(
            f"DEBUG_TIME_PARSE|status=success|raw={original_time_text}|matched={matched_text}|"
            f"value={value}|unit={unit}|parsed={result.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return result
            
    except Exception as e:
        logger.info(f"DEBUG_TIME_PARSE|status=exception|raw={original_time_text}|parsed=None|error={e}")
        logger.debug(f"Time Parse Exception: '{time_text}' -> {e}")
        return None


def collect_diagnostics(driver, phase="unknown"):
    """診断情報を収集（新規追加）"""
    try:
        logger.info(f"診断情報収集開始 - フェーズ: {phase}")
        
        diagnostics = {
            "phase": phase,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "url": driver.current_url,
            "ready_state": None,
            "youtube_state": None,
            "video_count": 0,
            "console_errors": [],
            "dom_info": {}
        }
        
        # 1. ページ状態
        diagnostics["ready_state"] = driver.execute_script("return document.readyState")
        
        # 2. YouTube特有の状態
        diagnostics["youtube_state"] = driver.execute_script("""
            return {
                hasYtInitialData: typeof ytInitialData !== 'undefined',
                hasYtdApp: document.querySelector('ytd-app') !== null,
                hasBrowse: document.querySelector('ytd-browse') !== null,
                pageType: document.querySelector('ytd-browse')?.getAttribute('page-subtype'),
                isLoading: document.querySelector('paper-spinner')?.active || false
            };
        """)
        
        # 3. 動画要素の詳細
        diagnostics["video_count"] = driver.execute_script("""
            const counts = {};
            const selectors = [
                'ytd-rich-item-renderer',
                'ytd-grid-video-renderer', 
                'ytd-video-renderer',
                'ytd-compact-video-renderer'
            ];
            
            selectors.forEach(sel => {
                counts[sel] = document.querySelectorAll(sel).length;
            });
            
            counts.total = Object.values(counts).reduce((a, b) => a + b, 0);
            return counts;
        """)
        
        # 4. コンソールエラー（ブラウザログ取得）
        try:
            for entry in driver.get_log('browser'):
                if entry['level'] in ['SEVERE', 'ERROR']:
                    diagnostics["console_errors"].append({
                        "level": entry['level'],
                        "message": entry['message'][:200]  # 最初の200文字
                    })
        except:
            pass  # ログ取得が失敗してもスキップ
        
        # 5. DOM構造の概要
        diagnostics["dom_info"] = driver.execute_script("""
            return {
                bodyClasses: document.body.className,
                mainContainerExists: document.querySelector('#primary') !== null,
                contentsExists: document.querySelector('#contents') !== null,
                scrollHeight: document.documentElement.scrollHeight,
                clientHeight: document.documentElement.clientHeight
            };
        """)
        
        # 6. スクリーンショット保存（エラー時のみ）
        if phase == "error" or diagnostics["video_count"].get("total", 0) < 5:
            try:
                screenshot_path = f"diagnostic_{phase}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                driver.save_screenshot(screenshot_path)
                diagnostics["screenshot"] = screenshot_path
                logger.info(f"スクリーンショット保存: {screenshot_path}")
            except:
                pass
        
        # 診断結果をログ出力
        logger.info(f"診断結果: ready_state={diagnostics['ready_state']}, "
                   f"動画数={diagnostics['video_count'].get('total', 0)}, "
                   f"エラー数={len(diagnostics['console_errors'])}")
        
        return diagnostics
        
    except Exception as e:
        logger.error(f"診断情報収集エラー: {e}")
        return {"error": str(e)}



def retry_with_recovery(driver, func, max_retries=3, recovery_action=None):
    """リトライとリカバリー機能（新規追加）"""
    for attempt in range(max_retries):
        try:
            logger.info(f"実行試行 {attempt + 1}/{max_retries}")
            
            # リカバリーアクションの実行（2回目以降）
            if attempt > 0 and recovery_action:
                logger.info("リカバリーアクション実行")
                recovery_action(driver)
            
            # メイン関数の実行
            result = func(driver)
            
            # 結果の検証
            if result and len(result) > 0:
                logger.info(f"✓ 成功（試行{attempt + 1}）: {len(result)}件取得")
                return result
            else:
                logger.warning(f"試行{attempt + 1}失敗: 結果が空")
                
                # 診断情報収集
                if attempt < max_retries - 1:
                    collect_diagnostics(driver, f"retry_{attempt + 1}")
                
        except Exception as e:
            logger.error(f"試行{attempt + 1}エラー: {e}")
            
            if attempt < max_retries - 1:
                collect_diagnostics(driver, f"error_{attempt + 1}")
        
        # 次の試行前の待機
        if attempt < max_retries - 1:
            wait_time = 3 * (attempt + 1)  # 段階的に待機時間を増やす
            logger.info(f"次の試行まで{wait_time}秒待機")
            time.sleep(wait_time)
    
    logger.error(f"全{max_retries}回の試行が失敗")
    collect_diagnostics(driver, "final_failure")
    return []


@timing_decorator
def super_fast_video_collection(driver, hours_filter):
    """超高速動画収集（真の原因対応版）"""
    
    videos = []
    processed_ids = set()
    cutoff_time = datetime.now() - timedelta(hours=hours_filter)
    consecutive_old_videos = 0  # 古い動画の連続数カウンター
    
    # 設定読み込み
    system_config = get_system_config()
    max_videos = system_config.get('max_videos', 500)
    
    # === 問題1: 初期ページ状態の不安定性への対処 ===
    def wait_for_page_stability(timeout=30):
        """ページが安定するまで待機"""
        logger.info("ページの安定化を待機中...")
        start_time = time.time()
        last_height = 0
        stable_count = 0
        
        while time.time() - start_time < timeout:
            try:
                current_state = driver.execute_script("""
                    return {
                        height: document.documentElement.scrollHeight,
                        url: window.location.href,
                        readyState: document.readyState,
                        hasYtdApp: document.querySelector('ytd-app') !== null,
                        hasBrowse: document.querySelector('ytd-browse') !== null
                    };
                """)
                
                # 高さが安定したらOK
                if current_state['height'] > 1000:  # 正常なYouTubeページは1000px以上
                    if current_state['height'] == last_height:
                        stable_count += 1
                        if stable_count >= 2:
                            logger.info(f"✅ ページ安定: 高さ={current_state['height']}px")
                            return True
                    else:
                        stable_count = 0
                    last_height = current_state['height']
                else:
                    logger.debug(f"ページ高さ不足: {current_state['height']}px")
                
                time.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"安定性チェックエラー: {e}")
                # エラーが出てもリトライ
                
        logger.warning("ページが安定しませんでした")
        return False
    
    # === 問題2: driver.get()の代替策 ===
    def navigate_to_subscriptions():
        """購読フィードへの安全な遷移"""
        try:
            current_url = driver.current_url
            
            # すでに購読ページならスキップ
            if "/feed/subscriptions" in current_url:
                logger.info("すでに購読ページです")
                return wait_for_page_stability()
            
            # 方法1: サイドメニューのリンクをクリック（最も安全）
            try:
                logger.info("方法1: サイドメニューから遷移")
                # メニューボタンをクリックしてサイドバーを開く
                menu_button = driver.find_element(By.CSS_SELECTOR, "#guide-button")
                menu_button.click()
                time.sleep(1)
                
                # 登録チャンネルリンクをクリック
                subs_link = driver.find_element(By.CSS_SELECTOR, 'a[href="/feed/subscriptions"]')
                subs_link.click()
                
                return wait_for_page_stability()
                
            except Exception as e1:
                logger.debug(f"方法1失敗: {e1}")
                
                # 方法2: URLバーから直接遷移（やむを得ない場合）
                try:
                    logger.info("方法2: JavaScript遷移")
                    driver.execute_script("""
                        window.location.replace('https://www.youtube.com/feed/subscriptions');
                    """)
                    time.sleep(3)
                    return wait_for_page_stability()
                    
                except Exception as e2:
                    logger.error(f"方法2も失敗: {e2}")
                    return False
                    
        except Exception as e:
            logger.error(f"遷移エラー: {e}")
            return False
    
    # === 初期化処理 ===
    logger.info("動画収集開始")
    
    # ページ遷移が必要な場合のみ実行
    current_url = driver.current_url
    if "/feed/subscriptions" not in current_url:
        if not navigate_to_subscriptions():
            logger.error("購読ページへの遷移に失敗")
            return []
    else:
        # すでに購読ページでも安定性を確認
        if not wait_for_page_stability():
            logger.warning("ページが不安定です")
    
    # === 動画収集メインループ（元のコードをベース） ===
    scroll_count = 0
    no_new_videos_count = 0
    
    while scroll_count < 50:  # スクロール回数のみで制限
        try:
            # 定期的に接続確認（10スクロールごと）
            if scroll_count > 0 and scroll_count % 10 == 0:
                try:
                    driver.execute_script("return 1;")
                except:
                    logger.error("接続が切断されました")
                    break
            
            # 動画要素取得
            video_elements = driver.find_elements(By.CSS_SELECTOR,
                "ytd-video-renderer, "
                "ytd-grid-video-renderer, "
                "ytd-rich-item-renderer")


            if not video_elements:
                no_new_videos_count += 1
                if no_new_videos_count >= 10:  # 3→10に変更
                    logger.info(f"新規動画なし {no_new_videos_count}回連続")
                    # 追加の待機とリトライ
                    if no_new_videos_count < 15:
                        time.sleep(2)  # DOM更新を待つ
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                        continue  # breakではなくcontinue
                    else:
                        logger.info("これ以上動画がありません")
                        break
            else:
                no_new_videos_count = 0

           
                
            # 動画処理（既存ロジック）
            for element in video_elements:
                try:
                    video_data = extract_video_data_fast(element)
                    if video_data:
                        vid, title, upload_time, duration, channel_name = video_data

                        if vid not in processed_ids:
                            processed_ids.add(vid)
                            
                            # 時間フィルタチェック
                            if upload_time and upload_time < cutoff_time:
                                consecutive_old_videos += 1
                                logger.debug(f"古い動画: {title[:30]} (連続{consecutive_old_videos}件)")
                                
                                # 古い動画が10件連続したら終了
                                if consecutive_old_videos >= 10:
                                    logger.info(f"古い動画が10件連続 → 収集終了（{len(videos)}件取得）")
                                    return finalize_video_list(videos)
                            else:
                                consecutive_old_videos = 0  # リセット
                                # フィルタリング処理
                            processed_ids.add(vid)
                            # ... フィルタリング処理など
                            videos.append(video_data)
                    
                # driver.execute_script("arguments[0].setAttribute('data-processed', 'true');", element)
                except:
                    pass
            
            # スクロール
            scroll_count += 1
            driver.execute_script("window.scrollBy(0, 1500);")
            time.sleep(0.5)
            
        except WebDriverException as e:
            if "invalid session id" in str(e).lower():
                logger.error("Chromeとの接続が失われました")
                break
            continue
        except Exception as e:
            logger.error(f"予期しないエラー: {e}")
            continue
    
    return finalize_video_list(videos)




def finalize_video_list(videos):
    """動画リスト最終処理（統計出力付き）"""
    logger.info(f"動画収集完了: {len(videos)}件")
    logger.info(f"チャンネル数: {get_channel_count(videos)}個")
    
    # 時間取得統計
    if duration_stats['total_attempts'] > 0:
        success_rate = (duration_stats['css_success'] / duration_stats['total_attempts']) * 100
        logger.info(f"時間取得成功率: {success_rate:.1f}% ({duration_stats['css_success']}/{duration_stats['total_attempts']})")
    
    # フィルタリング統計
    log_filter_stats()
    
    return videos



@timing_decorator
def extract_video_data_fast(element):
    """高速動画データ抽出（時間取得強化版）"""
    try:
        # 基本情報取得
        link_element = element.find_element(By.CSS_SELECTOR, "a#video-title, h3 a, .ytd-video-meta-block a")
        video_url = link_element.get_attribute("href")
        title = link_element.get_attribute("title") or link_element.text.strip()
        
        if not video_url or "watch?v=" not in video_url:
            return None
        
        video_id = video_url.split("watch?v=")[1].split("&")[0]

        # パフォーマンス最適化: 処理済みチェック
        global processed_ids  # グローバル変数を参照
        if 'processed_ids' in globals() and video_id in processed_ids:
            return None  # 既に処理済みなので早期リターン
        
        
        # チャンネル名取得
        try:
            channel_element = element.find_element(By.CSS_SELECTOR, 
                "ytd-video-meta-block #channel-name a, .ytd-channel-name a, #text a")
            channel_name = channel_element.text.strip()
        except:
            channel_name = "不明なチャンネル"
        
        # 🚀 動画時間取得（強化版）
        duration = get_duration_with_enhanced_selectors(element)
        if not duration:
            duration = "時間不明"
        
        # アップロード時間取得
        upload_time = None
        try:
            time_elements = element.find_elements(By.CSS_SELECTOR, 
                "#metadata-line span, .ytd-video-meta-block span")
            for time_element in time_elements:
                time_text = time_element.text.strip()
                if any(keyword in time_text for keyword in ["前", "時間", "日", "週", "ヶ月", "年"]):
                    upload_time = parse_relative_time(time_text)
                    break
        except:
            pass
        
        if not upload_time:
            upload_time = datetime.now()  # フォールバック
        
        return (video_id, title, upload_time, duration, channel_name)
        
    except Exception as e:
        logger.warning(f"動画データ抽出失敗: {e}")
        return None


def analyze_new_channel_assignments(selections, videos):
    """新しく手動で振り分けられたチャンネルを分析し、学習候補を抽出する"""
    global learned_channels
    
    # チャンネル名ごとの割り当て状況を収集
    # channel_assignments[チャンネル名][プレイリストID] = [video_id, ...]
    channel_assignments = defaultdict(lambda: defaultdict(list))
    
    # 元の動画リストからチャンネル情報を引き出すためのマッピング
    video_to_channel = {v[0]: v[4] for v in videos if len(v) >= 5}
    
    # 現在のGUIでの全選択状態を確認
    for vid, var in selections.items():
        playlist_key = var.get() # 'S', 'A', 'NONE' など
        if playlist_key and playlist_key != "NONE":
            channel_name = video_to_channel.get(vid)
            if channel_name:
                channel_assignments[channel_name][playlist_key].append(vid)

    # 学習が必要な新規チャンネルを特定
    new_channel_data = {}
    channel_rules = get_channel_keywords()  # 既存の固定ルール
    
    for channel_name, assignments in channel_assignments.items():
        # 以下の場合は学習対象から除外
        if channel_name in learned_channels or channel_name in channel_rules:
            continue
        
        # ユーザーが今回そのチャンネルの動画に割り当てたプレイリストの傾向を分析
        candidate_playlist = max(assignments.keys(), key=lambda k: len(assignments[k]))
        assignment_type = "single" if len(assignments) == 1 else "multiple"
        
        new_channel_data[channel_name] = {
            # 修正点: len(v) ではなく v (リスト) をそのまま渡す
            'assignments': dict(assignments), 
            'candidate': candidate_playlist,
            'type': assignment_type
        }
    
    if new_channel_data:
        logger.info(f"🧠 新規チャンネル検出: {len(new_channel_data)}件の学習候補があります。")
    return new_channel_data



def determine_learning_candidate(channel_name, assignments):
    """チャンネルの学習候補を決定"""
    if len(assignments) == 1:
        # 単一プレイリストの場合
        playlist = list(assignments.keys())[0]
        return playlist, "single"
    elif len(assignments) > 1:
        # 複数プレイリストの場合は最多を候補とする
        max_playlist = max(assignments.keys(), key=lambda k: len(assignments[k]))
        return max_playlist, "multiple"
    else:
        return None, "none"

def update_learning_data_with_decisions(learning_decisions):
    """ユーザーの学習決定（ダイアログの結果）に基づいて、データを更新・保存する"""
    global learned_channels
    
    # 再読み込みして最新の状態にする
    learned_channels = load_learned_channels()
    
    updated_count = 0
    
    for channel_name, info in learning_decisions.items():
        if info.get('action') == 'learn':
            playlist = info.get('playlist')
            if playlist:
                learned_channels[channel_name] = playlist
                updated_count += 1
                logger.info(f"✅ 学習登録完了: {channel_name} -> {playlist}")

    if updated_count > 0:
        save_learned_channels(learned_channels)
        logger.info(f"💾 {updated_count}件の新しいチャンネルルールを保存しました。")
        return True
    return False


# ===== 超高速プレイリスト管理システム（🆕 ローカル重複管理統合版） =====
class SuperFastPlaylistManager:
    """超高速プレイリスト追加マネージャー（🆕 ローカル重複管理統合版）"""


    def __init__(self, youtube_service):
        self.youtube = youtube_service
        self.stats = {
            'success': 0,
            'duplicate': 0, 
            'error': 0,
            'total': 0,
            'local_cache_hits': 0,
            'api_calls_saved': 0
        }
        self.progress_callback = None
        self.status_callback = None
        self.stats_callback = None  # ★★★ 追加 ★★★
        self.batch_lock = Lock()
        self.stats_lock = Lock()  # ★★★ 追加: 統計用のロック ★★★
        
        # 🆕 追加: クォータ監視機能
        self.quota_monitor = global_quota_monitor
        system_config = get_system_config()
        self.quota_enabled = system_config.get('quota_monitoring_enabled', True)
        
        # 🆕 追加: ローカル重複管理機能
        global registered_videos_manager
        self.cache_manager = registered_videos_manager
        cache_config = get_video_cache_config()
        self.cache_enabled = cache_config.get('cache_enabled', True)
        
        if self.quota_enabled and self.quota_monitor:
            logger.info("🆕 SuperFastPlaylistManager: クォータ監視有効")
        
        if self.cache_enabled and self.cache_manager:
            logger.info("🆕 SuperFastPlaylistManager: ローカル重複管理有効")
        
    def set_progress_callback(self, callback):
        self.progress_callback = callback



        
    def set_status_callback(self, callback):
        self.status_callback = callback

    def set_stats_callback(self, callback):
        """統計情報更新コールバックを設定"""
        self.stats_callback = callback

    def update_stats(self):
        """統計情報をUIに通知（スレッドセーフ）"""
        if self.stats_callback:
            with self.stats_lock:
                stats_copy = self.stats.copy()
            self.stats_callback(stats_copy)
    
    def update_progress(self, current, total, message=""):
        if self.progress_callback:
            self.progress_callback(current, total, message)
    
    def update_status(self, status):
        if self.status_callback:
            self.status_callback(status)

    @timing_decorator
    def add_videos_super_fast(self, video_playlist_pairs, use_batch_api=False, use_parallel=False, check_duplicates=True):
        """
        超高速動画追加処理（並列処理対応版）
        
        Args:
            video_playlist_pairs: [(video_id, playlist_id, title), ...]
            use_batch_api: バッチAPI使用（デフォルト: False）
            use_parallel: 並列処理使用（デフォルト: False）
            check_duplicates: 重複チェック実施（デフォルト: True）
        
        Returns:
            [(video_id, success), ...] 処理結果リスト
        """
        logger.info(f"処理開始: {len(video_playlist_pairs)}件の動画を処理")
        logger.info(f"🔧 処理前Video IDs: {[vid[:8] for vid, _, _ in video_playlist_pairs[:3]]}...")
        
        self.stats = {'success': 0, 'duplicate': 0, 'error': 0, 'total': len(video_playlist_pairs),
                     'local_cache_hits': 0, 'api_calls_saved': 0}
        
        original_count = len(video_playlist_pairs)
        logger.info(f"🔧 処理開始: {original_count}件")
        
        # 🔧 デバッグ: 処理前のクォータ使用量記録
        initial_quota = 0
        if self.quota_enabled and self.quota_monitor:
            initial_quota = self.quota_monitor.get_current_usage()['used']
            logger.info(f"🔧 処理開始時クォータ: {initial_quota}")
        
        # 重複チェック
        if check_duplicates and self.cache_enabled:
            logger.info(f"🔧 重複チェック前: {len(video_playlist_pairs)}件")
            video_playlist_pairs = self.fast_local_duplicate_check(video_playlist_pairs)
            logger.info(f"🔧 重複チェック後: {len(video_playlist_pairs)}件")
            
            if not video_playlist_pairs:
                logger.info("追加対象なし（全て重複）")
                return []
        
        logger.info(f"🔧 実際の処理対象: {len(video_playlist_pairs)}件")
        
        # デバッグ情報
        for i, (video_id, playlist_id, title) in enumerate(video_playlist_pairs[:5]):
            logger.info(f"🔧 処理予定 {i+1}: {title[:30]} -> {playlist_id}")
        
        if len(video_playlist_pairs) > 5:
            logger.info(f"🔧 ...他 {len(video_playlist_pairs) - 5}件")
        
        # ★★★ 修正: 処理方式の選択ロジックを実装 ★★★
        results = []
        
        try:
            if use_batch_api:
                # バッチAPI処理（現在は無効化推奨）
                logger.info("📦 バッチAPI処理モードで実行")
                results = self.batch_add_videos(video_playlist_pairs)
                
            elif use_parallel:
                # 並列処理モード（推奨）
                logger.info("⚡ 並列処理モードで実行")
                try:
                    results = self.parallel_add_videos(video_playlist_pairs)
                except Exception as e:
                    logger.error(f"並列処理エラー: {e}")
                    logger.info("🔄 順次処理へフォールバック")
                    results = self.sequential_add_videos(video_playlist_pairs)
            else:
                # 順次処理モード（安定性重視）
                logger.info("🐌 順次処理モードで実行")
                results = self.sequential_add_videos(video_playlist_pairs)
        
        except Exception as e:
            logger.error(f"処理中に予期しないエラー: {e}")
            # 最終フォールバック: 順次処理
            if not results or len(results) == 0:
                logger.info("🔄 最終フォールバック: 順次処理で再試行")
                results = self.sequential_add_videos(video_playlist_pairs)
        
        # 🔧 デバッグ: 処理後のクォータ使用量記録
        if self.quota_enabled and self.quota_monitor:
            final_quota = self.quota_monitor.get_current_usage()['used']
            actual_consumed = final_quota - initial_quota
            expected_consumed = len(video_playlist_pairs) * 50
            
            logger.info(f"🔧 処理完了時クォータ: {final_quota}")
            logger.info(f"🔧 実際の消費量: {actual_consumed}")
            logger.info(f"🔧 予想消費量: {expected_consumed}")
            
            # 重複による差分を計算
            duplicate_saved = self.stats.get('local_cache_hits', 0) * 50
            logger.info(f"🔧 重複管理による削減: {duplicate_saved}ユニット")
            
            if abs(actual_consumed - expected_consumed) > 50:
                logger.warning(f"🔧 異常検出: 予想より{actual_consumed - expected_consumed}ユニット差")
        
        return results


    def fast_local_duplicate_check(self, video_playlist_pairs):
        """🔧 修正: ローカル重複チェック（詳細ログ版）"""
        if not self.cache_manager:
            logger.warning("🆕 キャッシュマネージャー未初期化、API重複チェックにフォールバック")
            logger.info("DEBUG_DUPLICATE_SUMMARY|mode=api_fallback|reason=no_cache_manager")
            return self.fast_api_duplicate_check(video_playlist_pairs)
        
        logger.info(f"🆕 ローカル重複チェック開始: {len(video_playlist_pairs)}件")
        logger.info(
            f"DEBUG_DUPLICATE_START|mode=local_cache|target_count={len(video_playlist_pairs)}|"
            f"cache_file={getattr(self.cache_manager, 'cache_file', 'unknown')}|"
            f"cache_enabled={self.cache_enabled}"
        )
        
        filtered_pairs = []
        local_duplicate_count = 0
        cache_miss_count = 0
        sample_limit = 20
        
        # 🔧 追加: 詳細ログ
        for i, (video_id, playlist_id, title) in enumerate(video_playlist_pairs):
            is_duplicate = self.cache_manager.is_video_registered(video_id, playlist_id)
            playlist_name = self.get_playlist_name_by_id(playlist_id)
            
            if is_duplicate:
                local_duplicate_count += 1
                self.stats['local_cache_hits'] += 1
                self.stats['api_calls_saved'] += 1
                if local_duplicate_count <= sample_limit:
                    logger.info(
                        f"DEBUG_DUPLICATE_DECISION|index={i+1}|decision=CACHE_HIT|"
                        f"video_id={video_id}|playlist_name={playlist_name}|playlist_id={playlist_id}|title={title[:80]}"
                    )
                logger.debug(f"🆕 ローカル重複検出 {i+1}: {title[:30]} (ID:{video_id[:8]})")
            else:
                cache_miss_count += 1
                filtered_pairs.append((video_id, playlist_id, title))
                if cache_miss_count <= sample_limit:
                    logger.info(
                        f"DEBUG_DUPLICATE_DECISION|index={i+1}|decision=CACHE_MISS|"
                        f"video_id={video_id}|playlist_name={playlist_name}|playlist_id={playlist_id}|title={title[:80]}"
                    )
                logger.debug(f"🆕 新規対象 {len(filtered_pairs)}: {title[:30]} (ID:{video_id[:8]})")
        
        self.stats['duplicate'] += local_duplicate_count
        
        # 🔧 追加: 詳細結果ログ
        logger.info(f"🆕 ローカル重複チェック完了:")
        logger.info(f"   重複スキップ: {local_duplicate_count}件")
        logger.info(f"   処理対象: {len(filtered_pairs)}件")
        logger.info(f"   API削減効果: {local_duplicate_count}回")
        logger.info(
            f"DEBUG_DUPLICATE_SUMMARY|mode=local_cache|target_count={len(video_playlist_pairs)}|"
            f"cache_hit={local_duplicate_count}|cache_miss={cache_miss_count}|"
            f"filtered_count={len(filtered_pairs)}|sample_limit={sample_limit}"
        )
        
        # 🔧 追加: 結果検証
        if local_duplicate_count > 0:
            logger.info(f"🔧 検証: 重複チェックにより{local_duplicate_count}件をフィルタ")
        
        return filtered_pairs
        
    def fast_api_duplicate_check(self, video_playlist_pairs):
        """従来のAPI重複チェック（フォールバック用）"""
        unique_playlists = set(pair[1] for pair in video_playlist_pairs)
        existing_videos = {}
        
        # 設定から並列処理数を取得
        system_config = get_system_config()
        max_workers = min(4, len(unique_playlists))
        
        # プレイリスト別に並列で重複チェック
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_playlist = {
                executor.submit(self.get_playlist_videos, playlist_id): playlist_id 
                for playlist_id in unique_playlists
            }
            
            for future in concurrent.futures.as_completed(future_to_playlist):
                playlist_id = future_to_playlist[future]
                try:
                    videos = future.result(timeout=10)
                    existing_videos[playlist_id] = set(videos)
                except Exception as e:
                    logger.warning(f"プレイリスト {playlist_id} の重複チェック失敗: {e}")
                    existing_videos[playlist_id] = set()
        
        # 重複を除外
        filtered_pairs = []
        for video_id, playlist_id, title in video_playlist_pairs:
            if video_id not in existing_videos.get(playlist_id, set()):
                filtered_pairs.append((video_id, playlist_id, title))
            else:
                self.stats['duplicate'] += 1
                logger.info(f"API重複検出: {title[:50]}")
        
        logger.info(f"API重複チェック結果: {self.stats['duplicate']}件スキップ、{len(filtered_pairs)}件を処理対象")
        return filtered_pairs


    def get_playlist_videos(self, playlist_id):
        """プレイリストの既存動画IDを確実に取得（上限500件）"""
        try:
            video_ids = []
            # 最新のサービスを使用
            current_service = PROJECT_MANAGER.get_current_service() if PROJECT_MANAGER else self.youtube
            
            request = current_service.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50
            )
            
            while request:
                response = request.execute()
                
                # クォータ記録
                if self.quota_enabled and self.quota_monitor:
                    self.quota_monitor.record_api_call('playlistItems.list', 1)
                if PROJECT_MANAGER:
                    PROJECT_MANAGER.record_api_usage(1)
                
                for item in response['items']:
                    video_ids.append(item['contentDetails']['videoId'])
                
                # 制限を200から500に拡張
                if len(video_ids) >= 500:
                    break
                    
                request = current_service.playlistItems().list_next(request, response)
            
            logger.debug(f"プレイリスト {playlist_id} から {len(video_ids)} 件の既登録動画をロードしました")
            return video_ids
            
        except Exception as e:
            logger.warning(f"プレイリスト動画取得失敗 [{playlist_id}]: {e}")
            return []



    def sequential_add_videos(self, video_playlist_pairs):
        """順次処理（安定性重視・ログ最適化版）"""
        results = []
        total = len(video_playlist_pairs)
        
        logger.info(f"🐌 順次処理開始: {total}件")
        
        for i, (video_id, playlist_id, title) in enumerate(video_playlist_pairs):
            # 進捗更新（詳細ログは10件ごと）
            if i % 10 == 0 or i == 0 or i == total - 1:
                logger.info(f"進捗: {i+1}/{total} ({(i+1)/total*100:.0f}%)")
            
            self.update_progress(i + 1, total, f"追加中: {title[:30]}...")
            
            success = self.add_single_video(video_id, playlist_id, title)
            results.append((video_id, success))
            
            if success:
                self.stats['success'] += 1
            else:
                self.stats['error'] += 1
        
        logger.info(f"🐌 順次処理完了: 成功{self.stats['success']}件、エラー{self.stats['error']}件")
        return results


    def parallel_add_videos(self, video_playlist_pairs):
        """並列処理（高速版・スレッドセーフ版）"""
        results = []
        completed = 0
        
        # システム設定から並列ワーカー数を取得
        system_config = get_system_config()
        max_parallel_workers = system_config.get('max_parallel_workers', 8)
        
        # ワーカー数の最適化（動画数に応じて調整）
        total_videos = len(video_playlist_pairs)
        if total_videos < 20:
            actual_workers = min(4, max_parallel_workers)
        elif total_videos < 100:
            actual_workers = min(6, max_parallel_workers)
        else:
            actual_workers = max_parallel_workers
        
        logger.info(f"⚡ 並列処理開始: {total_videos}件を{actual_workers}スレッドで処理")
        
        # スレッドプールで並列実行
        with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
            # 全タスクを一括投入
            future_to_video = {
                executor.submit(self.add_single_video, video_id, playlist_id, title): (video_id, title, i)
                for i, (video_id, playlist_id, title) in enumerate(video_playlist_pairs)
            }
            
            # 完了次第結果を収集
            for future in concurrent.futures.as_completed(future_to_video):
                video_id, title, original_index = future_to_video[future]
                completed += 1
                
                # 進捗更新（5件ごと or 10%ごと）
                if completed % 5 == 0 or completed % max(1, total_videos // 10) == 0:
                    progress_pct = (completed / total_videos) * 100
                    self.update_progress(
                        completed, 
                        total_videos, 
                        f"並列処理中 ({progress_pct:.0f}%): {title[:30]}..."
                    )
                
                try:
                    # タイムアウト設定（30秒）
                    success = future.result(timeout=30)
                    results.append((video_id, success))
                    
                    # ★★★ 修正: スレッドセーフな統計更新 ★★★
                    with self.stats_lock:
                        if success:
                            self.stats['success'] += 1
                        else:
                            self.stats['error'] += 1
                    
                    # ★★★ 追加: UIへ統計を通知 ★★★
                    self.update_stats()
                        
                except concurrent.futures.TimeoutError:
                    logger.error(f"⏱️ タイムアウト [{video_id}]: {title[:30]}")
                    
                    # ★★★ 修正: スレッドセーフな統計更新 ★★★
                    with self.stats_lock:
                        self.stats['error'] += 1
                    
                    results.append((video_id, False))
                    
                    # ★★★ 追加: UIへ統計を通知 ★★★
                    self.update_stats()
                        
                except Exception as e:
                    logger.error(f"❌ 並列処理例外 [{video_id}]: {e}")
                    
                    # ★★★ 修正: スレッドセーフな統計更新 ★★★
                    with self.stats_lock:
                        self.stats['error'] += 1
                    
                    results.append((video_id, False))
                    
                    # ★★★ 追加: UIへ統計を通知 ★★★
                    self.update_stats()
        
        logger.info(f"⚡ 並列処理完了: 成功{self.stats['success']}件、エラー{self.stats['error']}件")
        return results

    
    def batch_add_videos(self, video_playlist_pairs):
        """バッチAPI処理（最高速 + 🆕 ローカル更新）"""
        results = []
        
        # 設定からバッチサイズを取得
        system_config = get_system_config()
        batch_size = system_config.get('batch_size', 25)
        
        batches = [video_playlist_pairs[i:i + batch_size] for i in range(0, len(video_playlist_pairs), batch_size)]
        
        for batch_num, batch in enumerate(batches):
            self.update_progress(batch_num * batch_size, len(video_playlist_pairs), 
                               f"バッチ処理 {batch_num + 1}/{len(batches)}")
            
            batch_results = self.process_batch(batch)
            results.extend(batch_results)
        
        return results

    def process_batch(self, batch):
        """バッチ処理実行（🆕 ローカル更新付き・クォータカウンター修正版）"""
        global PROJECT_MANAGER
        
        batch_request = BatchHttpRequest()
        batch_results = []
        
        def callback_factory(video_id, title, playlist_id):
            def callback(request_id, response, exception):
                if exception is None:
                    self.stats['success'] += 1
                    batch_results.append((video_id, True))
                    logger.info(f"バッチ成功: {title[:50]}")
                    
                    # 🆕 追加: 成功時のローカル更新
                    if self.cache_enabled and self.cache_manager:
                        channel_name = self.extract_channel_from_title(title)
                        playlist_name = self.get_playlist_name_by_id(playlist_id)
                        update_registered_videos(video_id, playlist_id, title, channel_name, playlist_name)
                    
                    # 🆕 追加: 成功時のクォータ記録
                    if self.quota_enabled and self.quota_monitor:
                        self.quota_monitor.record_api_call('playlistItems.insert', 50, success=True)
                    
                    # ★★★ 修正: PROJECT_MANAGERへの記録を追加 ★★★
                    if PROJECT_MANAGER:
                        PROJECT_MANAGER.record_api_usage(50)
                    
                else:
                    if "duplicate" in str(exception).lower():
                        self.stats['duplicate'] += 1
                        batch_results.append((video_id, True))
                        
                        # 🆕 追加: 重複も成功として記録
                        if self.quota_enabled and self.quota_monitor:
                            self.quota_monitor.record_api_call('playlistItems.insert', 50, success=True)
                        
                        # ★★★ 修正: 重複時もPROJECT_MANAGERへ記録 ★★★
                        if PROJECT_MANAGER:
                            PROJECT_MANAGER.record_api_usage(50)
                    else:
                        self.stats['error'] += 1
                        batch_results.append((video_id, False))
                        logger.error(f"バッチエラー [{video_id}]: {exception}")
                        
                        # 🆕 追加: エラー時のクォータ記録
                        if self.quota_enabled and self.quota_monitor:
                            self.quota_monitor.record_api_call('playlistItems.insert', 50, success=False)
                        
                        # ★★★ 修正: エラー時もPROJECT_MANAGERへ記録 ★★★
                        if PROJECT_MANAGER:
                            PROJECT_MANAGER.record_api_usage(50)
            return callback
        
        # バッチリクエスト構築
        for video_id, playlist_id, title in batch:
            # 動的にサービスを取得してプロジェクト切り替え
            if PROJECT_MANAGER and PROJECT_MANAGER.should_switch_project():
                PROJECT_MANAGER.switch_project()
                logger.info(f"Switched to {PROJECT_MANAGER.current_project}")
            current_service = PROJECT_MANAGER.get_current_service() if PROJECT_MANAGER else self.youtube
            request = current_service.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id
                        }
                    }
                }
            )
            batch_request.add(request, callback=callback_factory(video_id, title, playlist_id))
        
        # バッチ実行
        try:
            batch_request.execute()
        except Exception as e:
            logger.error(f"バッチ実行エラー: {e}")
            # フォールバックで個別処理
            for video_id, playlist_id, title in batch:
                success = self.add_single_video(video_id, playlist_id, title)
                batch_results.append((video_id, success))
        
        return batch_results



    def add_single_video(self, video_id, playlist_id, title, channel_name="Unknown"):
        """
        単一動画追加 + 成功時にキャッシュを即座に更新する（記憶の定着）
        """
        global PROJECT_MANAGER
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                # サービスの取得
                current_service = PROJECT_MANAGER.get_current_service() if PROJECT_MANAGER else self.youtube
                
                request = current_service.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": { "kind": "youtube#video", "videoId": video_id }
                        }
                    }
                )
                request.execute()
                
                # --- 追加：成功時のローカルキャッシュ更新 ---
                if self.cache_enabled and self.cache_manager:
                    p_name = self.get_playlist_name_by_id(playlist_id)
                    # この瞬間に「登録済み」としてファイルに書き留める
                    update_registered_videos(video_id, playlist_id, title, channel_name, p_name)

                if PROJECT_MANAGER:
                    PROJECT_MANAGER.record_api_usage(50)
                return True

            except Exception as e:
                error_msg = str(e).lower()
                
                # --- 重複エラー時の処理 ---
                if "duplicate" in error_msg:
                    logger.info(f"💡 YouTubeサーバー上で重複を確認: {title[:30]}")
                    # APIが重複と言うなら、実態に合わせてキャッシュも更新しておく
                    if self.cache_enabled and self.cache_manager:
                        p_name = self.get_playlist_name_by_id(playlist_id)
                        update_registered_videos(video_id, playlist_id, title, channel_name, p_name)
                    return True

                # --- クォータ制限 (403 quotaExceeded) ---
                if "quotaexceeded" in error_msg or "403" in error_msg:
                    if PROJECT_MANAGER:
                        logger.warning(f"⚠️ クォータ制限検出。プロジェクトを切り替えて再試行します。")
                        PROJECT_MANAGER.switch_project()
                        # サービスを再取得してリトライ
                        self.youtube = PROJECT_MANAGER.get_current_service()
                        return self.add_single_video(video_id, playlist_id, title, channel_name)
                    return False

                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
        return False


    def extract_channel_from_title(self, title):
        """🆕 タイトルからチャンネル名を推定（修正版）"""
        # この関数は使用せず、直接渡されたチャンネル名を使用
        return "チャンネル名不明"  # フォールバック用のみ
        
    def get_playlist_name_by_id(self, playlist_id):
        """🆕 プレイリストIDからプレイリスト名を取得"""
        playlist_ids = get_playlist_ids()
        for name, pid in playlist_ids.items():
            if pid == playlist_id:
                return name
        return ""


# ===== 進捗ダイアログ（高機能版 + 🆕 ローカル重複統計表示） =====
class AdvancedProgressDialog:
    """高機能進捗ダイアログ（🆕 ローカル重複統計表示版）"""
    
    def __init__(self, parent, total_items):
        self.parent = parent
        self.total_items = total_items
        self.start_time = time.time()
        
        # ダイアログ作成
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("🚀 超高速プレイリスト追加（ローカル重複管理統合版）")
        self.dialog.geometry("600x400")  # 🆕 ローカル統計のため幅・高さを拡大
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # プログレスバー
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.dialog, 
            variable=self.progress_var, 
            maximum=total_items, 
            length=500
        )
        self.progress_bar.pack(pady=10)
        
        # 進捗テキスト
        self.progress_label = tk.Label(self.dialog, text="準備中...", font=("Meiryo", 12))
        self.progress_label.pack(pady=5)
        
        # ステータス
        self.status_label = tk.Label(self.dialog, text="📍 開始準備", font=("Meiryo", 10), fg="blue")
        self.status_label.pack(pady=5)
        
        # 統計情報
        self.stats_label = tk.Label(self.dialog, text="📊 統計: 準備中", font=("Meiryo", 10))
        self.stats_label.pack(pady=5)
        
        # 🆕 追加: ローカルキャッシュ統計表示
        cache_config = get_video_cache_config()
        if cache_config.get('cache_enabled', True):
            self.cache_label = tk.Label(self.dialog, text="🆕 キャッシュ: 初期化中", font=("Meiryo", 10), fg="purple")
            self.cache_label.pack(pady=5)
        else:
            self.cache_label = None
        
        # 🆕 追加: クォータ情報表示
        system_config = get_system_config()
        if system_config.get('quota_monitoring_enabled', True):
            self.quota_label = tk.Label(self.dialog, text="🆕 クォータ: 取得中", font=("Meiryo", 10), fg="green")
            self.quota_label.pack(pady=5)
        else:
            self.quota_label = None
        
        # 経過時間
        self.time_label = tk.Label(self.dialog, text="⏱️ 経過時間: 0.0秒", font=("Meiryo", 10))
        self.time_label.pack(pady=5)
        
        # ウィンドウを中央に配置
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (self.dialog.winfo_width() // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (self.dialog.winfo_height() // 2)
        self.dialog.geometry(f"+{x}+{y}")
    
    def update_progress(self, current, total, message=""):
        """🆕 進捗更新（ローカルキャッシュ統計付き）"""
        self.progress_var.set(current)
        
        # パーセンテージ計算
        percentage = (current / total * 100) if total > 0 else 0
        
        # 経過時間と残り時間計算
        elapsed = time.time() - self.start_time
        if current > 0:
            estimated_total = elapsed * total / current
            remaining = max(0, estimated_total - elapsed)
            
            progress_text = f"📈 進捗: {current}/{total} ({percentage:.1f}%) | 残り: {remaining:.1f}秒"
        else:
            progress_text = f"📈 進捗: {current}/{total} ({percentage:.1f}%)"
        
        if message:
            progress_text += f"\n{message}"
        
        self.progress_label.config(text=progress_text)
        self.time_label.config(text=f"⏱️ 経過時間: {elapsed:.1f}秒")
        
        # 🆕 追加: ローカルキャッシュ統計更新
        if self.cache_label:
            cache_stats = get_cache_hit_stats()
            if cache_stats:
                cache_text = f"🆕 キャッシュ: ヒット{cache_stats.get('cache_hits', 0)}回 | API削減{cache_stats.get('api_calls_saved', 0)}回"
                self.cache_label.config(text=cache_text)
        
        # 🆕 追加: クォータ情報更新
        system_config = get_system_config()
        if system_config.get('quota_monitoring_enabled', True) and global_quota_monitor and self.quota_label:
            quota_status = global_quota_monitor.get_current_usage()
            quota_text = f"🆕 クォータ: {quota_status['used']:,}/{quota_status['limit']:,} ({quota_status['percentage']:.1f}%) | セッション: +{quota_status['session_usage']:,}"
            self.quota_label.config(text=quota_text)
        
        self.dialog.update()
    
    def update_status(self, status_text):
        """ステータステキストを更新"""
        self.status_label.config(text=f"📍 {status_text}")
        self.dialog.update()
    
    def update_stats(self, stats):
        """🆕 統計情報を更新（ローカルキャッシュ統計付き）"""
        stats_text = f"✅ 成功: {stats.get('success', 0)}件 | 🔄 重複: {stats.get('duplicate', 0)}件 | ❌ エラー: {stats.get('error', 0)}件"
        
        # ローカルキャッシュ統計を追加
        # if stats.get('local_cache_hits', 0) > 0:
            # stats_text += f" | 🆕 キャッシュヒット: {stats['local_cache_hits']}件"
        
        self.stats_label.config(text=stats_text)
        self.dialog.update()
    
    def close(self):
        """ダイアログを閉じる"""
        self.dialog.destroy()

# ===== 🧠 改良版学習確認ダイアログシステム（一覧表示形式）（設定外部化対応版） =====
class ImprovedLearningConfirmationDialog:
    """チャンネル学習一覧確認ダイアログ（効率化版）（設定外部化対応版）"""
    
    def __init__(self, parent, channel_data):
        self.parent = parent
        self.channel_data = channel_data
        self.learning_vars = {}  # チャンネル名 -> BooleanVar
        self.playlist_vars = {}  # チャンネル名 -> StringVar
        self.results = {}
        self.dialog = None
        
    def show_batch_confirmation_dialog(self):
        """全チャンネル一覧確認ダイアログを表示"""
        if not self.channel_data:
            return {}
        
        logger.info(f"学習一覧確認ダイアログ表示: {len(self.channel_data)}チャンネル")
        
        # メインダイアログ作成
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("🧠 チャンネル学習設定 - 一覧確認")
        self.dialog.geometry("900x750")
        self.dialog.transient(self.parent)
        self.dialog.grab_set()
        
        # ダイアログを中央に配置
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (self.dialog.winfo_width() // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (self.dialog.winfo_height() // 2)
        self.dialog.geometry(f"+{x}+{y}")
        
        # メインフレーム
        main_frame = ttk.Frame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # ヘッダー情報
        header_frame = ttk.LabelFrame(main_frame, text="📋 学習対象チャンネル概要")
        header_frame.pack(fill="x", pady=(0, 10))
        
        total_channels = len(self.channel_data)
        total_videos = sum(sum(len(videos) for videos in info['assignments'].values()) 
                          for info in self.channel_data.values())
        
        header_text = f"学習対象: {total_channels}チャンネル、{total_videos}動画\n"
        header_text += "✅ チェックしたチャンネルは次回から自動振り分けされます"
        
        ttk.Label(header_frame, text=header_text, 
                 font=("Meiryo", 11)).pack(anchor="w", padx=10, pady=10)
        
        # 一括操作ボタン
        bulk_frame = ttk.LabelFrame(main_frame, text="⚡ 一括操作")
        bulk_frame.pack(fill="x", pady=(0, 10))
        
        bulk_button_frame = ttk.Frame(bulk_frame)
        bulk_button_frame.pack(anchor="w", padx=10, pady=8)
        
        ttk.Button(bulk_button_frame, text="📚 全て学習", 
                  command=self.select_all_learning, width=12).pack(side="left", padx=(0, 5))
        ttk.Button(bulk_button_frame, text="🚫 全て非学習", 
                  command=self.deselect_all_learning, width=12).pack(side="left", padx=(0, 5))
        ttk.Button(bulk_button_frame, text="🎯 推奨のみ学習", 
                  command=self.select_recommended_only, width=15).pack(side="left")
        
        # スクロール可能なチャンネルリスト
        list_frame = ttk.LabelFrame(main_frame, text="📺 チャンネル一覧")
        list_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # リストヘッダー
        header_row_frame = ttk.Frame(list_frame)
        header_row_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(header_row_frame, text="学習", width=6, font=("Meiryo", 10, "bold")).pack(side="left")
        ttk.Label(header_row_frame, text="チャンネル名", width=35, font=("Meiryo", 10, "bold")).pack(side="left", padx=(10, 0))
        ttk.Label(header_row_frame, text="動画数", width=8, font=("Meiryo", 10, "bold")).pack(side="left")
        ttk.Label(header_row_frame, text="推奨PL", width=8, font=("Meiryo", 10, "bold")).pack(side="left")
        ttk.Label(header_row_frame, text="振り分け詳細", width=25, font=("Meiryo", 10, "bold")).pack(side="left")
        
        # セパレーター
        separator = ttk.Separator(list_frame, orient="horizontal")
        separator.pack(fill="x", padx=5, pady=(0, 5))
        
        # スクロール可能エリア
        canvas = tk.Canvas(list_frame, height=300)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind("<Configure>", 
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # チャンネル行を作成
        self.create_channel_rows(scrollable_frame)
        
        canvas.pack(side="left", fill="both", expand=True, padx=(5, 0))
        scrollbar.pack(side="right", fill="y")
        
        # マウスホイールスクロール対応
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", on_mousewheel)
        canvas.bind("<Enter>", lambda e: canvas.focus_set())
        
        # 注意事項
        warning_frame = ttk.LabelFrame(main_frame, text="⚠️ 学習時の注意")
        warning_frame.pack(fill="x", pady=(0, 10))
        
        warning_text = ("学習したチャンネルの動画は次回から自動的に指定プレイリストに振り分けられます。\n"
                       "チャンネル内の動画が必ずしも同じプレイリストに適さない場合は学習を無効にしてください。")
        
        ttk.Label(warning_frame, text=warning_text, 
                 font=("Meiryo", 10)).pack(anchor="w", padx=10, pady=8)
        
        # 最終確認ボタン
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(5, 0))
        
        ttk.Button(button_frame, text="💾 学習設定を保存", 
                  command=self.save_learning_settings, 
                  width=20).pack(side="left", padx=(0, 10))
        
        ttk.Button(button_frame, text="❌ 学習しない", 
                  command=self.cancel_learning, 
                  width=15).pack(side="left", padx=(0, 10))
        
        ttk.Button(button_frame, text="ℹ️ ヘルプ", 
                  command=self.show_help, 
                  width=10).pack(side="right")
        
        # 結果を保存する変数
        self.dialog.user_result = {}
        
        # ダイアログ終了まで待機
        self.dialog.wait_window()
        
        return getattr(self.dialog, 'user_result', {})
    
    def create_channel_rows(self, parent):
        """チャンネル行を作成"""
        row_count = 0
        
        # チャンネルを動画数順にソート（多い順）
        sorted_channels = sorted(self.channel_data.items(), 
                               key=lambda x: sum(len(videos) for videos in x[1]['assignments'].values()), 
                               reverse=True)
        
        for channel_name, info in sorted_channels:
            self.create_single_channel_row(parent, channel_name, info, row_count)
            row_count += 1
    
    def create_single_channel_row(self, parent, channel_name, info, row_index):
        """単一チャンネル行を作成（設定外部化対応版）"""
        row_frame = ttk.Frame(parent)
        row_frame.pack(fill="x", padx=2, pady=1)
        
        # 学習チェックボックス
        learn_var = tk.BooleanVar()
        # デフォルトで推奨設定（単一プレイリストの場合のみ自動チェック）
        if info['type'] == 'single':
            learn_var.set(True)
        else:
            learn_var.set(False)
        
        self.learning_vars[channel_name] = learn_var
        
        learn_check = ttk.Checkbutton(row_frame, variable=learn_var, width=6)
        learn_check.pack(side="left")
        
        # チャンネル名（短縮表示）
        display_name = channel_name[:30] + "..." if len(channel_name) > 30 else channel_name
        name_label = ttk.Label(row_frame, text=display_name, width=35, anchor="w")
        name_label.pack(side="left", padx=(10, 0))
        
        # 動画数
        total_videos = sum(len(videos) for videos in info['assignments'].values())
        count_label = ttk.Label(row_frame, text=str(total_videos), width=8, anchor="center")
        count_label.pack(side="left")
        
        # 推奨プレイリスト
        candidate = info['candidate']
        candidate_label = ttk.Label(row_frame, text=candidate, width=8, anchor="center", 
                                   font=("Meiryo", 10, "bold"))
        candidate_label.pack(side="left")
        
        # プレイリスト選択（推奨以外を選択可能）（設定外部化対応版）
        playlist_var = tk.StringVar()
        playlist_var.set(candidate)
        self.playlist_vars[channel_name] = playlist_var
        
        # 設定からプレイリスト一覧を取得
        playlist_ids = get_playlist_ids()
        playlist_combo = ttk.Combobox(row_frame, textvariable=playlist_var, 
                                    values=list(playlist_ids.keys()), 
                                    state="readonly", width=8)
        playlist_combo.pack(side="left", padx=(5, 0))
        
        # 振り分け詳細
        assignment_details = []
        for playlist, videos in info['assignments'].items():
            assignment_details.append(f"{playlist}:{len(videos)}")
        
        detail_text = ", ".join(assignment_details)
        if len(detail_text) > 25:
            detail_text = detail_text[:22] + "..."
        
        detail_label = ttk.Label(row_frame, text=detail_text, width=25, anchor="w")
        detail_label.pack(side="left", padx=(10, 0))
        
        # 学習推奨度表示
        recommendation_icon = "🎯" if info['type'] == 'single' else "⚠️"
        rec_label = ttk.Label(row_frame, text=recommendation_icon, width=3)
        rec_label.pack(side="left", padx=(5, 0))
    
    def select_all_learning(self):
        """全て学習選択"""
        for var in self.learning_vars.values():
            var.set(True)
        logger.info("一括学習選択: 全チャンネル")
    
    def deselect_all_learning(self):
        """全て非学習選択"""
        for var in self.learning_vars.values():
            var.set(False)
        logger.info("一括学習解除: 全チャンネル")
    
    def select_recommended_only(self):
        """推奨のみ学習選択"""
        count = 0
        for channel_name, var in self.learning_vars.items():
            if self.channel_data[channel_name]['type'] == 'single':
                var.set(True)
                count += 1
            else:
                var.set(False)
        
        logger.info(f"推奨のみ学習選択: {count}チャンネル")
        messagebox.showinfo("推奨選択", f"単一プレイリストの{count}チャンネルを学習対象にしました")
    
    def save_learning_settings(self):
        """学習設定を保存"""
        results = {}
        learn_count = 0
        
        for channel_name, learn_var in self.learning_vars.items():
            if learn_var.get():
                # 学習する場合
                playlist = self.playlist_vars[channel_name].get()
                results[channel_name] = {
                    'action': 'learn',
                    'playlist': playlist,
                    'channel': channel_name,
                    'assignments': self.channel_data[channel_name]['assignments']
                }
                learn_count += 1
            else:
                # 学習しない場合
                results[channel_name] = {
                    'action': 'skip',
                    'channel': channel_name
                }
        
        # 確認メッセージ
        if learn_count > 0:
            confirm_message = f"🧠 {learn_count}チャンネルを学習します。\n\n"
            confirm_message += "学習したチャンネルは次回から自動振り分けされます。\n"
            confirm_message += "よろしいですか？"
            
            if messagebox.askyesno("学習確認", confirm_message):
                self.dialog.user_result = results
                logger.info(f"学習設定保存: {learn_count}チャンネル")
                self.dialog.destroy()
        else:
            # 学習なしの場合
            if messagebox.askyesno("確認", "学習するチャンネルがありません。\nこのまま進みますか？"):
                self.dialog.user_result = {}
                self.dialog.destroy()
    
    def cancel_learning(self):
        """学習をキャンセル"""
        if messagebox.askyesno("確認", "全ての学習をスキップしますか？"):
            self.dialog.user_result = {}
            logger.info("学習設定キャンセル")
            self.dialog.destroy()
    
    def show_help(self):
        """ヘルプ表示"""
        help_text = """🧠 チャンネル学習機能について

【学習とは】
・選択したチャンネルの動画を次回から自動的に指定プレイリストに振り分ける機能

【推奨度アイコン】
🎯 = 単一プレイリスト（学習推奨）
⚠️ = 複数プレイリスト（要注意）

【操作方法】
・チェックボックス: 学習する/しないを選択
・プルダウン: 学習先プレイリストを変更可能
・一括操作: 全体または推奨のみを一括選択

【注意点】
・学習したチャンネルの全動画が自動振り分けされます
・チャンネル内の動画が多様な場合は学習を無効にしてください
・学習データは learned_channels.json に保存されます"""

        messagebox.showinfo("学習機能ヘルプ", help_text)

# ===== マウスホイールスクロール対応（改良版） =====
class ScrollHandler:
    """マウスホイールスクロール処理クラス（高速化版）"""
    
    def __init__(self, canvas):
        self.canvas = canvas
        self.os_name = platform.system()
        logger.info(f"スクロールハンドラー初期化 (OS: {self.os_name})")
    
    def bind_mousewheel_to_widget(self, widget):
        """個別ウィジェットにマウスホイールをバインド（高速版）"""
        try:
            if self.os_name == "Windows":
                widget.bind("<MouseWheel>", self.on_mousewheel)
            else:  # Linux, Mac
                widget.bind("<Button-4>", self.on_mousewheel)
                widget.bind("<Button-5>", self.on_mousewheel)
        except Exception:
            pass  # エラーは無視して継続
    
    def bind_mousewheel_recursive(self, widget):
        """再帰的に全子ウィジェットにマウスホイールをバインド（高速版）"""
        self.bind_mousewheel_to_widget(widget)
        
        try:
            for child in widget.winfo_children():
                self.bind_mousewheel_recursive(child)
        except Exception:
            pass  # 一部のウィジェットでエラーが出ても継続
    
    def on_mousewheel(self, event):
        """マウスホイールイベント処理（最適化版）"""
        try:
            # スクロール量を計算
            if self.os_name == "Windows":
                delta = -1 * (event.delta / 120)
            elif hasattr(event, 'num'):
                if event.num == 4:  # Linux/Mac 上スクロール
                    delta = -1
                elif event.num == 5:  # Linux/Mac 下スクロール
                    delta = 1
                else:
                    return
            else:
                return
            
            # スクロール実行
            self.canvas.yview_scroll(int(delta), "units")
            
        except Exception:
            pass  # エラーは無視

# ===== 🆕 クォータチェック関数（設定外部化対応版） =====
def check_quota_before_start(estimated_operations=0):
    """処理開始前のクォータチェック（設定外部化対応版）"""
    system_config = get_system_config()
    if not system_config.get('quota_monitoring_enabled', True) or not global_quota_monitor:
        return True
    
    quota_status = global_quota_monitor.check_quota_status()
    current_usage = global_quota_monitor.get_current_usage()
    
    # 予想される操作数から必要クォータを計算
    estimated_quota_needed = estimated_operations * 50  # 1操作あたり平均50ユニット
    
    if current_usage['remaining'] < estimated_quota_needed:
        logger.warning(f"🆕 クォータ不足警告: 残り{current_usage['remaining']:,}、必要{estimated_quota_needed:,}")
        return False
    
    logger.info(f"🆕 クォータチェック: {quota_status['message']}")
    return True

def generate_quota_summary_report():
    """処理完了後のクォータサマリー表示（設定外部化対応版）"""
    system_config = get_system_config()
    if not system_config.get('quota_monitoring_enabled', True) or not global_quota_monitor:
        return ""
    
    # 最終的なクォータデータを保存
    global_quota_monitor.save_usage_data()
    
    return global_quota_monitor.generate_usage_report()

def show_auto_open_settings(parent):
    """🆕 自動オープン設定ダイアログ（デフォルト有効版）"""
    try:
        system_config = get_system_config()
        current_setting = system_config.get('auto_open_quota_page', True)  # デフォルトTrue
        
        result = messagebox.askyesno(
            "クォータページ自動オープン設定",
            f"現在の設定: {'有効' if current_setting else '無効'}\n\n"
            f"コード終了時にGoogle Cloud Consoleの\n"
            f"クォータページを自動で開きますか？\n\n"
            f"💡 デフォルト: 有効（推奨）",
            default='yes' if current_setting else 'no'
        )
        
        if result != current_setting:
            if toggle_auto_open_quota_page(result):
                status_text = "有効" if result else "無効"
                messagebox.showinfo("設定完了", 
                    f"✅ 自動オープン: {status_text}に設定しました\n\n"
                    f"次回のコード終了時から反映されます")
    
    except Exception as e:
        messagebox.showerror("エラー", f"設定変更エラー: {e}")
        

def fetch_real_quota_usage(project_id=None):
    """Google Cloud実測値を取得"""
    try:
        if not project_id:
            project_id = PROJECT_IDS.get('project1')
        
        # --- 以下の行を削除またはコメントアウト ---
        # url = f"https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas?project={project_id}"
        # webbrowser.open(url) 
        # ---------------------------------------
        
        # 内部カウンタを返す
        if global_quota_monitor:
            return global_quota_monitor.daily_usage
        return 0
    except Exception as e:
        # エラー時はログを出力して0を返す
        if 'logger' in globals():
            logger.error(f"実測値取得エラー: {e}")
        else:
            print(f"実測値取得エラー: {e}")
        return 0
        

    
def auto_open_quota_page():
    """🆕 Google Cloud Consoleのクォータページを自動オープン（プロジェクト対応）"""
    try:
        # 現在のプロジェクトを取得
        current_project = 'project1'  # デフォルト
        if PROJECT_MANAGER:
            current_project = PROJECT_MANAGER.current_project
            # クォータ使用量をチェック
            status = PROJECT_MANAGER.get_quota_status()
            # project1が90%以上使用されていたらproject2を使用
            if status['projects']['project1']['percentage'] >= 90:
                current_project = 'project2'
        
        # プロジェクトIDを取得
        project_id = PROJECT_IDS.get(current_project, PROJECT_IDS['project1'])
        
        # URLを動的に生成
        url = f"https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas?hl=ja&inv=1&invt=Ab4bwA&project={project_id}"
        
        logger.info(f"🆕 Google Cloud Consoleクォータページを開いています... (Project: {current_project})")
        print(f"🌐 Google Cloud Consoleクォータページを開いています... ({current_project}: {project_id})")
        
        # ブラウザで開く
        import webbrowser
        webbrowser.open(url)
        
        # MultiProjectManagerのステータスも表示
        if PROJECT_MANAGER:
            status = PROJECT_MANAGER.get_quota_status()
            logger.info(f"📊 Multi-project quota: {status['total_used']}/{status['total_limit']}")
            
            # 各プロジェクトの状況を表示
            for pid, pinfo in status['projects'].items():
                logger.info(f"  {pid}: {pinfo['used']}/{pinfo['limit']} ({pinfo['percentage']:.0f}%)")
        
        # 実測値取得（該当プロジェクトのみ）
        real_usage = fetch_real_quota_usage(project_id)
        logger.info(f"🆕 Google Cloud実測値 ({current_project}): {real_usage:,}クォータ")
        
        print("✅ クォータページを開きました")
        logger.info(f"🆕 クォータページオープン完了 ({current_project})")
        print("💡 Google Cloud Consoleで詳細なクォータ使用状況を確認できます")
        
    except Exception as e:
        logger.error(f"🆕 クォータページオープンエラー: {e}")
        # エラー時はデフォルトURLを開く
        webbrowser.open("https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas")

def toggle_auto_open_quota_page(enable=True):
    """🆕 クォータページ自動オープンの有効/無効を切り替え"""
    try:
        import json
        from pathlib import Path
        
        config_file = Path("config/system_config.json")
        
        # 設定読み込み
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 設定更新
        config['auto_open_quota_page'] = enable
        
        # URLも確保
        if 'quota_page_url' not in config:
            config['quota_page_url'] = "https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas?hl=ja&inv=1&invt=Ab4bwA&project=woven-invention-463200-t6"
        
        # 設定保存
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        status = "有効" if enable else "無効"
        print(f"✅ クォータページ自動オープン: {status}に設定しました")
        logger.info(f"🆕 自動オープン設定変更: {status}")
        
        return True
        
    except Exception as e:
        print(f"❌ 設定変更エラー: {e}")
        logger.error(f"🆕 設定変更エラー: {e}")
        return False

def open_quota_page_manually():
    """🆕 手動でクォータページを開く"""
    try:
        print("🌐 手動でクォータページを開きます...")
        result = auto_open_quota_page()
        if not result:
            print("❌ クォータページのオープンに失敗しました")
    except Exception as e:
        print(f"❌ 手動オープンエラー: {e}")

        
# ===== 🔥 Phase 4: GUI改修と統合最適化（🆕 ローカル重複統計統合版） =====

# グローバル変数：チェックボックス状態管理
playlist_checkboxes = {}  # playlist_id -> BooleanVar
channel_checkboxes = {}   # (section_type, playlist_id, channel_name) -> BooleanVar
original_playlist_assignments = {}  # video_id -> original_playlist_id

def initialize_original_assignments(videos):
    """
    動画の元のプレイリスト割り当てを記憶
    チェックボックスを戻した時に使用
    """
    global original_playlist_assignments
    
    for video_data in videos:
        if len(video_data) >= 5:
            vid = video_data[0]
            channel_name = video_data[4]
            
            # 元の自動振り分けプレイリストを取得
            original_playlist = get_smart_playlist_for_channel(channel_name)
            original_playlist_assignments[vid] = original_playlist
            
            logger.debug(f"元の割り当て記憶: {vid[:11]} -> {original_playlist}")


def organize_videos_hierarchically(videos):
    """
    動画を3階層構造（セクション→プレイリスト→チャンネル→動画）に再編成
    
    Returns:
        {
            'filtered': {
                'S': {'channel_A': [video_data, ...], 'channel_B': [...]},
                'A': {...},
                ...
            },
            'unselected': {
                'S': {'channel_C': [...]},  # S向けだが未選択
                'A': {...},
                ...
            },
            'selected': {
                'S': {'channel_D': [...]},
                'A': {...},
                ...
            }
        }
    """
    hierarchical_structure = {
        'filtered': {},
        'unselected': {},
        'selected': {}
    }
    
    # プレイリストIDリストを取得
    playlist_ids = get_playlist_ids()
    
    # デバッグカウンタ追加
    debug_counters = {
        'total_videos': 0,
        'none_count': 0,
        'filtered_count': 0,
        'selected_count': 0
    }
    
    # 各セクションの各プレイリストを初期化
    for section_type in ['filtered', 'unselected', 'selected']:
        for playlist_name in playlist_ids.keys():
            hierarchical_structure[section_type][playlist_name] = {}
    
    # 動画を分類
    for video_data in videos:
        try:
            debug_counters['total_videos'] += 1
            
            # 動画データを解析
            if len(video_data) >= 8:
                vid, title, upload_time, duration, channel_name, playlist_suggestion, filter_reason, display_type = video_data[:8]
            elif len(video_data) >= 5:
                vid, title, upload_time, duration, channel_name = video_data[:5]
                # フィルタリングを適用して追加情報を取得
                playlist_suggestion, filter_reason, display_type = apply_duration_filter(channel_name, duration)
            else:
                continue
            
            # デバッグログ追加：未設定動画の検出
            if playlist_suggestion == "NONE":
                debug_counters['none_count'] += 1
                logger.info(f"DEBUG: 未設定動画検出 #{debug_counters['none_count']}: {title[:30]}... -> unselectedセクション")
            
            # セクションを決定
            if display_type == "filtered":
                section = 'filtered'
                debug_counters['filtered_count'] += 1
                # フィルタされた動画も元のターゲットプレイリストで分類
                target_playlist = get_smart_playlist_for_channel(channel_name)
            elif playlist_suggestion == "NONE":
                section = 'unselected'
                # 未選択でも本来のターゲットプレイリストで分類
                target_playlist = get_smart_playlist_for_channel(channel_name)
                # デバッグログ：ターゲットプレイリストも記録
                logger.debug(f"DEBUG: 未設定動画のターゲットプレイリスト: {target_playlist}")
            else:
                section = 'selected'
                debug_counters['selected_count'] += 1
                target_playlist = playlist_suggestion
            
            # チャンネルごとに動画を追加
            if target_playlist in playlist_ids:
                if channel_name not in hierarchical_structure[section][target_playlist]:
                    hierarchical_structure[section][target_playlist][channel_name] = []
                
                hierarchical_structure[section][target_playlist][channel_name].append(video_data)
            else:
                # ターゲットプレイリストが見つからない場合の処理
                logger.warning(f"DEBUG: 不明なターゲットプレイリスト: {target_playlist} for {title[:30]}")
                # NONEとして扱う
                if "NONE" not in hierarchical_structure[section]:
                    hierarchical_structure[section]["NONE"] = {}
                if channel_name not in hierarchical_structure[section]["NONE"]:
                    hierarchical_structure[section]["NONE"][channel_name] = []
                hierarchical_structure[section]["NONE"][channel_name].append(video_data)
            
        except Exception as e:
            logger.error(f"動画の階層分類エラー: {e}")
            continue
    
    # デバッグログ：分類結果のサマリー
    logger.info(f"DEBUG: 階層分類完了 - 総動画数: {debug_counters['total_videos']}, "
               f"未設定: {debug_counters['none_count']}, "
               f"フィルタ: {debug_counters['filtered_count']}, "
               f"選択済: {debug_counters['selected_count']}")
    
    # 空のプレイリスト/チャンネルを削除しない（0件表示のため）
    
    # 統計ログ
    for section_type in ['filtered', 'unselected', 'selected']:
        section_total = 0
        for playlist_name, channels in hierarchical_structure[section_type].items():
            playlist_total = sum(len(videos) for videos in channels.values())
            section_total += playlist_total
            if playlist_total > 0:
                logger.debug(f"{section_type}/{playlist_name}: {len(channels)}チャンネル, {playlist_total}動画")
        
        logger.info(f"階層構造 - {section_type}セクション: 合計{section_total}動画")
    
    return hierarchical_structure


def get_playlist_video_stats(hierarchical_data, section_type, playlist_id):
    """
    特定セクション・プレイリストの動画統計を取得
    
    Args:
        hierarchical_data: organize_videos_hierarchically()の戻り値
        section_type: 'filtered', 'unselected', 'selected'
        playlist_id: 'S', 'A', 'B', etc.
    
    Returns:
        (channel_count, video_count)
    """
    if section_type not in hierarchical_data:
        return (0, 0)
    
    if playlist_id not in hierarchical_data[section_type]:
        return (0, 0)
    
    channels = hierarchical_data[section_type][playlist_id]
    channel_count = len(channels)
    video_count = sum(len(videos) for videos in channels.values())
    
    return (channel_count, video_count)

def get_channel_video_stats(hierarchical_data, section_type, playlist_id, channel_name):
    """
    特定チャンネルの動画数を取得
    
    Returns:
        video_count
    """
    try:
        videos = hierarchical_data[section_type][playlist_id].get(channel_name, [])
        return len(videos)
    except KeyError:
        return 0

def should_playlist_be_checked(hierarchical_data, section_type, playlist_id, selections):
    """
    プレイリストチェックボックスの初期状態を決定
    配下に1つでも選択された動画があればTrue
    """
    if section_type not in hierarchical_data:
        return False
    
    if playlist_id not in hierarchical_data[section_type]:
        return False
    
    channels = hierarchical_data[section_type][playlist_id]
    
    for channel_name, videos in channels.items():
        for video_data in videos:
            vid = video_data[0]
            if vid in selections:
                selected_playlist = selections[vid].get()
                if selected_playlist == playlist_id:
                    return True
    
    return False

def should_channel_be_checked(hierarchical_data, section_type, playlist_id, channel_name, selections):
    """
    チャンネルチェックボックスの初期状態を決定
    配下に1つでも選択された動画があればTrue
    """
    try:
        videos = hierarchical_data[section_type][playlist_id].get(channel_name, [])
        
        for video_data in videos:
            vid = video_data[0]
            if vid in selections:
                selected_playlist = selections[vid].get()
                if section_type == 'selected' and selected_playlist == playlist_id:
                    return True
                elif section_type in ['unselected', 'filtered'] and selected_playlist != 'NONE':
                    # 未選択/フィルタセクションでも、何か選択されていればチェック
                    return True
        
        return False
        
    except Exception:
        return False

def update_videos_for_playlist_check(playlist_id, checked, selections, hierarchical_data, section_type):
    """
    プレイリストチェックボックスの変更を配下の全動画に反映
    
    Args:
        playlist_id: 対象プレイリストID
        checked: チェック状態 (True/False)
        selections: 動画選択状態の辞書
        hierarchical_data: 階層データ
        section_type: 'filtered', 'unselected', 'selected'
    """
    if section_type not in hierarchical_data:
        return
    
    if playlist_id not in hierarchical_data[section_type]:
        return
    
    channels = hierarchical_data[section_type][playlist_id]
    
    for channel_name, videos in channels.items():
        for video_data in videos:
            vid = video_data[0]
            if vid in selections:
                if checked:
                    # チェックされた場合：該当プレイリストに設定
                    selections[vid].set(playlist_id)
                else:
                    # チェック外された場合：未選択に設定
                    selections[vid].set("NONE")
                
                # ボタンの色を更新（update_button_colors関数が存在する場合）
                if 'update_button_colors' in globals():
                    update_button_colors(vid)

def update_videos_for_channel_check(channel_name, playlist_id, checked, selections, 
                                   hierarchical_data, section_type):
    """
    チャンネルチェックボックスの変更を配下の動画に反映
    
    Args:
        channel_name: 対象チャンネル名
        playlist_id: 親プレイリストID
        checked: チェック状態
        selections: 動画選択状態の辞書
        hierarchical_data: 階層データ
        section_type: セクションタイプ
    """
    try:
        videos = hierarchical_data[section_type][playlist_id].get(channel_name, [])
        
        for video_data in videos:
            vid = video_data[0]
            if vid in selections:
                if checked:
                    # チェックされた場合：元の自動振り分けプレイリストに戻す
                    if vid in original_playlist_assignments:
                        original_playlist = original_playlist_assignments[vid]
                        selections[vid].set(original_playlist)
                    else:
                        # フォールバック：セクションに応じた設定
                        if section_type == 'selected':
                            selections[vid].set(playlist_id)
                        else:
                            # 未選択/フィルタセクションで元が不明な場合
                            selections[vid].set(playlist_id)
                else:
                    # チェック外された場合：未選択に設定
                    selections[vid].set("NONE")
                
                # ボタンの色を更新
                if 'update_button_colors' in globals():
                    update_button_colors(vid)
                    
    except Exception as e:
        logger.error(f"チャンネルチェック更新エラー: {e}")



# ===== 🆕 Phase 3: チェックボックスイベントハンドラ =====





def on_playlist_checkbox_changed(playlist_id, section_type, hierarchical_data, selections, update_colors_func):
    """
    プレイリストレベルのチェックボックス変更イベントハンドラ
    
    Args:
        playlist_id: プレイリストID ('S', 'A', 'B', etc.)
        section_type: セクションタイプ ('filtered', 'unselected', 'selected')
        hierarchical_data: 階層データ構造
        selections: 動画選択状態辞書
        update_colors_func: ボタン色更新関数
    """
    try:
        # チェックボックスの現在の状態を取得
        checkbox_key = (section_type, playlist_id)
        if checkbox_key not in playlist_checkboxes:
            logger.error(f"プレイリストチェックボックスが見つかりません: {checkbox_key}")
            return
        
        checked = playlist_checkboxes[checkbox_key].get()
        
        logger.info(f"プレイリストチェック変更: {section_type}/{playlist_id} -> {checked}")
        
        # 配下の全チャンネルのチェックボックスを更新
        if playlist_id in hierarchical_data[section_type]:
            channels = hierarchical_data[section_type][playlist_id]
            
            for channel_name in channels.keys():
                channel_checkbox_key = (section_type, playlist_id, channel_name)
                
                # チャンネルチェックボックスが存在する場合は更新
                if channel_checkbox_key in channel_checkboxes:
                    channel_checkboxes[channel_checkbox_key].set(checked)
                    logger.debug(f"  チャンネルチェック更新: {channel_name} -> {checked}")
        
        # 配下の全動画の選択状態を更新
        update_videos_for_playlist_check(
            playlist_id, 
            checked, 
            selections, 
            hierarchical_data, 
            section_type
        )
        
        # 統計ログ
        if checked:
            channel_count, video_count = get_playlist_video_stats(
                hierarchical_data, section_type, playlist_id
            )
            logger.info(f"  プレイリスト{playlist_id}を選択: {channel_count}チャンネル, {video_count}動画")
        else:
            logger.info(f"  プレイリスト{playlist_id}の選択を解除")
        
    except Exception as e:
        logger.error(f"プレイリストチェックボックス変更エラー: {e}")
        import traceback
        logger.error(traceback.format_exc())

def on_channel_checkbox_changed(channel_name, playlist_id, section_type, 
                               hierarchical_data, selections, update_colors_func):
    """
    チャンネルレベルのチェックボックス変更イベントハンドラ
    
    Args:
        channel_name: チャンネル名
        playlist_id: 親プレイリストID
        section_type: セクションタイプ
        hierarchical_data: 階層データ構造
        selections: 動画選択状態辞書
        update_colors_func: ボタン色更新関数
    """
    try:
        # チェックボックスの現在の状態を取得
        checkbox_key = (section_type, playlist_id, channel_name)
        if checkbox_key not in channel_checkboxes:
            logger.error(f"チャンネルチェックボックスが見つかりません: {checkbox_key}")
            return
        
        checked = channel_checkboxes[checkbox_key].get()
        
        logger.info(f"チャンネルチェック変更: {section_type}/{playlist_id}/{channel_name} -> {checked}")
        
        # 配下の動画の選択状態を更新
        update_videos_for_channel_check(
            channel_name,
            playlist_id,
            checked,
            selections,
            hierarchical_data,
            section_type
        )
        
        # 親プレイリストのチェック状態を再評価
        update_parent_playlist_checkbox(
            playlist_id,
            section_type,
            hierarchical_data,
            selections
        )
        
        # 統計ログ
        video_count = get_channel_video_stats(
            hierarchical_data, section_type, playlist_id, channel_name
        )
        
        if checked:
            logger.info(f"  チャンネル「{channel_name}」を選択: {video_count}動画")
        else:
            logger.info(f"  チャンネル「{channel_name}」の選択を解除: {video_count}動画")
        
    except Exception as e:
        logger.error(f"チャンネルチェックボックス変更エラー: {e}")
        import traceback
        logger.error(traceback.format_exc())

def update_parent_playlist_checkbox(playlist_id, section_type, hierarchical_data, selections):
    """
    チャンネルチェックボックスの状態に基づいて親プレイリストのチェック状態を更新
    
    全チャンネルが未チェック → プレイリストも未チェック
    1つ以上のチャンネルがチェック → プレイリストもチェック
    """
    try:
        checkbox_key = (section_type, playlist_id)
        if checkbox_key not in playlist_checkboxes:
            return
        
        # 配下のチャンネルのチェック状態を確認
        any_checked = False
        
        if playlist_id in hierarchical_data[section_type]:
            channels = hierarchical_data[section_type][playlist_id]
            
            for channel_name in channels.keys():
                channel_checkbox_key = (section_type, playlist_id, channel_name)
                
                if channel_checkbox_key in channel_checkboxes:
                    if channel_checkboxes[channel_checkbox_key].get():
                        any_checked = True
                        break
        
        # プレイリストチェックボックスを更新（イベント発火を避けるため直接設定）
        current_state = playlist_checkboxes[checkbox_key].get()
        if current_state != any_checked:
            # 一時的にイベントハンドラを無効化
            playlist_checkboxes[checkbox_key].set(any_checked)
            logger.debug(f"親プレイリスト{playlist_id}のチェック状態を更新: {any_checked}")
    
    except Exception as e:
        logger.error(f"親プレイリストチェック更新エラー: {e}")

def create_playlist_checkbox_handler(playlist_id, section_type, hierarchical_data, 
                                    selections, update_colors_func):
    """
    プレイリストチェックボックス用のイベントハンドラを生成（クロージャ）
    
    Returns:
        イベントハンドラ関数
    """
    def handler():
        on_playlist_checkbox_changed(
            playlist_id, 
            section_type, 
            hierarchical_data, 
            selections, 
            update_colors_func
        )
    return handler

def create_channel_checkbox_handler(channel_name, playlist_id, section_type, 
                                   hierarchical_data, selections, update_colors_func):
    """
    チャンネルチェックボックス用のイベントハンドラを生成（クロージャ）
    
    Returns:
        イベントハンドラ関数
    """
    def handler():
        on_channel_checkbox_changed(
            channel_name,
            playlist_id,
            section_type,
            hierarchical_data,
            selections,
            update_colors_func
        )
    return handler

def sync_checkbox_with_video_selection(video_id, new_playlist, hierarchical_data, selections):
    """
    個別動画のラジオボタン選択変更時にチェックボックス状態を同期
    
    Args:
        video_id: 動画ID
        new_playlist: 新しく選択されたプレイリスト
        hierarchical_data: 階層データ
        selections: 選択状態辞書
    """
    try:
        # 動画が属するチャンネルとセクションを検索
        video_info = find_video_location(video_id, hierarchical_data)
        if not video_info:
            return
        
        section_type, original_playlist, channel_name = video_info
        
        # チャンネルのチェック状態を再評価
        should_check = should_channel_be_checked(
            hierarchical_data, 
            section_type, 
            original_playlist, 
            channel_name, 
            selections
        )
        
        channel_checkbox_key = (section_type, original_playlist, channel_name)
        if channel_checkbox_key in channel_checkboxes:
            current_state = channel_checkboxes[channel_checkbox_key].get()
            if current_state != should_check:
                channel_checkboxes[channel_checkbox_key].set(should_check)
                
                # 親プレイリストの状態も更新
                update_parent_playlist_checkbox(
                    original_playlist,
                    section_type,
                    hierarchical_data,
                    selections
                )
        
    except Exception as e:
        logger.error(f"チェックボックス同期エラー: {e}")

def find_video_location(video_id, hierarchical_data):
    """
    動画IDから所属セクション、プレイリスト、チャンネルを検索
    
    Returns:
        (section_type, playlist_id, channel_name) or None
    """
    for section_type in ['filtered', 'unselected', 'selected']:
        for playlist_id, channels in hierarchical_data[section_type].items():
            for channel_name, videos in channels.items():
                for video_data in videos:
                    if video_data[0] == video_id:
                        return (section_type, playlist_id, channel_name)
    
    return None

def initialize_checkbox_states(hierarchical_data, selections):
    """
    全チェックボックスの初期状態を設定
    
    Args:
        hierarchical_data: 階層データ
        selections: 現在の動画選択状態
    """
    logger.info("チェックボックス初期状態設定開始")
    
    for section_type in ['filtered', 'unselected', 'selected']:
        for playlist_id in hierarchical_data[section_type].keys():
            # プレイリストチェックボックス
            playlist_checkbox_key = (section_type, playlist_id)
            if playlist_checkbox_key in playlist_checkboxes:
                should_check = should_playlist_be_checked(
                    hierarchical_data, 
                    section_type, 
                    playlist_id, 
                    selections
                )
                playlist_checkboxes[playlist_checkbox_key].set(should_check)
                
                if should_check:
                    logger.debug(f"プレイリスト初期チェック: {section_type}/{playlist_id}")
            
            # チャンネルチェックボックス
            if playlist_id in hierarchical_data[section_type]:
                for channel_name in hierarchical_data[section_type][playlist_id].keys():
                    channel_checkbox_key = (section_type, playlist_id, channel_name)
                    if channel_checkbox_key in channel_checkboxes:
                        should_check = should_channel_be_checked(
                            hierarchical_data,
                            section_type,
                            playlist_id,
                            channel_name,
                            selections
                        )
                        channel_checkboxes[channel_checkbox_key].set(should_check)
                        
                        if should_check:
                            logger.debug(f"チャンネル初期チェック: {section_type}/{playlist_id}/{channel_name}")

# ===== Phase 3 ここまで =====



# ===== 🆕 Phase 2: 階層表示用の新GUI関数群 =====



# Duration解析のキャッシュ化
@lru_cache(maxsize=1024)
def cached_parse_duration(duration_str: str) -> int:
    """Duration文字列を秒数に変換（キャッシュ付き）"""
    try:
        return parse_duration_to_seconds(duration_str)
    except:
        return None

def filter_hierarchical_data_by_selection(hierarchical_data: dict, selection: dict) -> dict:
    """
    階層データ（filtered/unselected/selected → playlist → channel → [videos]）に
    UI選択（すべて/ショート/S/A/B/N/M/L）を適用して絞り込む。

    ルール:
      - 'short' が False のとき、SHORT_THRESHOLD_SECONDS（180秒）以下の動画を除外
      - 'all' が True のとき、プレイリストは全許可（未分類も許可）
      - 'all' が False のとき、Trueなプレイリスト（S/A/B/N/M/L）のみ残す
      - 未分類（UNCLASSIFIED_KEYS）は 'all' が True のときだけ表示
      
    Args:
        hierarchical_data: 階層構造データ
        selection: UI選択状態の辞書
        
    Returns:
        フィルタ適用後の新しい階層データ（元データは変更しない）
    """
    try:
        if not hierarchical_data:
            return hierarchical_data

        # デバッグ用：選択状態を記録
        logger.debug(f"filter_hierarchical_data - selection: {json.dumps(selection)}")

        # 許可プレイリスト集合の決定（実データのキーを基準に）
        all_playlist_keys = set()
        for section in hierarchical_data.values():
            all_playlist_keys.update(section.keys())
        
        if selection.get("all", True):
            allowed_playlists = all_playlist_keys  # すべて許可
            allow_unclassified = True
        else:
            # 個別選択モード
            allowed_playlists = {p for p in ["V", "S", "A", "B", "N", "M", "L", "P+"]
                               if selection.get(p, False)}
            allow_unclassified = False  # 個別モードでは未分類は表示しない

        # ショート動画フィルタの準備
        include_shorts = selection.get("short", True)
        
        # 新しいデータ構造を構築
        new_data = {"filtered": {}, "unselected": {}, "selected": {}}
        
        # 除外カウンタ（ログ用）
        stats = {"short_excluded": 0, "playlist_excluded": 0, "unclassified_excluded": 0}

        def playlist_allowed(pname: str) -> bool:
            """プレイリストが表示対象かを判定（未分類キー統一版）"""
            if pname in UNCLASSIFIED_KEYS:
                if not allow_unclassified:
                    stats["unclassified_excluded"] += 1
                return allow_unclassified
            return pname in allowed_playlists

        def is_short_duration(duration) -> bool:
            """動画がショート（180秒以下）かを判定（型対応版）"""
            try:
                # 1. 数値型の場合
                if isinstance(duration, (int, float)):
                    return duration <= SHORT_THRESHOLD_SECONDS
                
                # 2. 文字列型の場合
                if isinstance(duration, str):
                    if duration in ["時間不明", "不明", "None", ""]:
                        return False  # 不明な場合は除外しない
                    
                    # キャッシュ付きparse関数を使用
                    duration_seconds = cached_parse_duration(duration)
                    if duration_seconds is not None:
                        return duration_seconds <= SHORT_THRESHOLD_SECONDS
                
                # 3. その他の型または変換失敗時
                # 既存のis_short_video関数にフォールバック
                return is_short_video(duration)
                
            except Exception as e:
                logger.debug(f"Duration判定エラー: {duration}, {e}")
                return False  # エラー時は除外しない

        # セクションごとに再構築
        for section in ["filtered", "unselected", "selected"]:
            section_src = hierarchical_data.get(section, {})
            section_dst = {}

            for playlist_name, channels in section_src.items():
                # プレイリスト許可判定
                if not playlist_allowed(playlist_name):
                    # 未分類とその他を区別してカウント（二重カウント回避）
                    if playlist_name not in UNCLASSIFIED_KEYS:
                        video_count = sum(len(videos) for videos in channels.values())
                        stats["playlist_excluded"] += video_count
                    continue

                # チャンネルごとの動画をフィルタ
                new_channels = {}
                for channel_name, videos in channels.items():
                    filtered_videos = []
                    
                    for video_data in videos:
                        # video_data: [vid, title, upload_time, duration, channel, ...]
                        duration = video_data[3] if len(video_data) > 3 else None

                        # ショート動画の除外判定
                        if not include_shorts and duration is not None:
                            if is_short_duration(duration):
                                stats["short_excluded"] += 1
                                continue

                        filtered_videos.append(video_data)

                    if filtered_videos:
                        new_channels[channel_name] = filtered_videos

                if new_channels:
                    section_dst[playlist_name] = new_channels

            new_data[section] = section_dst

        # 統計ログ出力（値がある項目のみ）
        log_parts = []
        if stats["short_excluded"] > 0:
            log_parts.append(f"ショート除外 {stats['short_excluded']}件")
        if stats["playlist_excluded"] > 0:
            log_parts.append(f"プレイリスト除外 {stats['playlist_excluded']}件")
        if stats["unclassified_excluded"] > 0:
            log_parts.append(f"未分類除外 {stats['unclassified_excluded']}件")
        
        if log_parts:
            logger.info(f"UI選択によるフィルタ結果: {', '.join(log_parts)}")

        return new_data

    except Exception as e:
        logger.error(f"filter_hierarchical_data_by_selection エラー: {e}")
        logger.debug(f"selection={selection}")
        import traceback
        logger.debug(traceback.format_exc())
        # エラー時は元データをそのまま返す（安全側）
        return hierarchical_data



def create_hierarchical_display(scrollable_frame, current_row, videos, ui_selection=None,
                               selections=None, button_refs=None, base_font=None,
                               update_colors_func=None, scroll_handler=None, 
                               prefiltered=None):
    """
    3階層構造（セクション→プレイリスト→チャンネル）で動画を表示
    
    Args:
        scrollable_frame: 親フレーム
        current_row: 現在の行番号
        videos: 動画リスト
        ui_selection: UI選択状態
        selections: 選択状態の辞書
        button_refs: ボタン参照の辞書
        base_font: ベースフォント
        update_colors_func: 色更新関数
        scroll_handler: スクロールハンドラー
        prefiltered: 事前計算済みの階層データ（任意）
    """
    # グローバル変数の安全な参照
    global playlist_checkboxes, channel_checkboxes, original_playlist_assignments
    
    # ui_selectionのデフォルト値設定
    if ui_selection is None:
        ui_selection = DEFAULT_SELECTION.copy()
        logger.debug("create_hierarchical_display: デフォルトUI選択を使用")
    
    # 引数のnullチェック
    if selections is None:
        selections = {}
    if button_refs is None:
        button_refs = {}
    
    # チェックボックス辞書を初期化（存在確認付き）
    if 'playlist_checkboxes' in globals():
        playlist_checkboxes.clear()
    if 'channel_checkboxes' in globals():
        channel_checkboxes.clear()
    
    # 元の割り当てを記憶
    if callable(globals().get('initialize_original_assignments')):
        initialize_original_assignments(videos)
    
    # prefilteredが渡されていれば使用、なければ再計算
    if prefiltered is not None:
        hierarchical_data = prefiltered
        logger.debug("事前計算済みデータを使用")
    else:
        # 動画を階層構造に再編成
        hierarchical_data = organize_videos_hierarchically(videos)
        
        # UI選択フィルタ適用
        try:
            filtered_data = filter_hierarchical_data_by_selection(
                hierarchical_data, ui_selection or DEFAULT_SELECTION
            )
            hierarchical_data = filtered_data
            
            # フィルタ結果の統計（条件付きログ）
            if logger.isEnabledFor(logging.DEBUG):
                stats = {
                    "total_before": len(videos),
                    "filtered": sum(sum(len(vids) for vids in channels.values())
                                  for channels in hierarchical_data.get('filtered', {}).values()),
                    "unselected": sum(sum(len(vids) for vids in channels.values())
                                    for channels in hierarchical_data.get('unselected', {}).values()),
                    "selected": sum(sum(len(vids) for vids in channels.values())
                                  for channels in hierarchical_data.get('selected', {}).values())
                }
                stats["total_after"] = stats["filtered"] + stats["unselected"] + stats["selected"]
                logger.debug(f"UIフィルタ適用結果: {json.dumps(stats, ensure_ascii=False)}")
            
        except Exception as e:
            logger.error(f"UIフィルタ適用エラー: {e}")
            logger.debug("UIフィルタ未適用 - 元データを使用")
    
    # 設定から情報を取得
    filter_settings = get_filter_settings()
    show_filtered_videos = filter_settings.get("show_filtered_videos", True)
    
    # 1. フィルタ済み動画セクション
    if show_filtered_videos:
        filtered_total = sum(
            sum(len(videos) for videos in channels.values())
            for channels in hierarchical_data.get('filtered', {}).values()
        )
        
        if filtered_total > 0:
            # フィルタ理由に応じた見出し設定
            title = "⚡ 自動フィルタ済み"
            
            current_row = create_section_with_playlists(
                scrollable_frame, current_row, hierarchical_data, 'filtered',
                title, "#f5f5f5", "#757575",
                selections, button_refs, base_font, update_colors_func, scroll_handler
            )
    
    # 2. 未選択（要確認）セクション
    unselected_total = sum(
        sum(len(videos) for videos in channels.values())
        for channels in hierarchical_data.get('unselected', {}).values()
    )
    
    if unselected_total > 0:
        current_row = create_section_with_playlists(
            scrollable_frame, current_row, hierarchical_data, 'unselected',
            "🔴 要確認: 未選択の動画", "#ffebee", "#c62828",
            selections, button_refs, base_font, update_colors_func, scroll_handler
        )
    
    # 3. 選択済み（自動選択）セクション
    selected_total = sum(
        sum(len(videos) for videos in channels.values())
        for channels in hierarchical_data.get('selected', {}).values()
    )
    
    if selected_total > 0:
        current_row = create_section_with_playlists(
            scrollable_frame, current_row, hierarchical_data, 'selected',
            "✅ 自動選択済み: 登録予定の動画", "#e8f5e8", "#2e7d32",
            selections, button_refs, base_font, update_colors_func, scroll_handler
        )
    
    # ===== 初期表示時の同期：チェックボックスがオンなら動画も選択 =====
    for section_type in ['selected']:  # selectedセクションを優先的に処理
        if section_type not in hierarchical_data:
            continue
            
        for playlist_id in hierarchical_data[section_type].keys():
            checkbox_key = (section_type, playlist_id)
            
            # プレイリストチェックボックスがオンの場合
            if checkbox_key in playlist_checkboxes and playlist_checkboxes[checkbox_key].get():
                channels = hierarchical_data[section_type].get(playlist_id, {})
                
                for channel_name, videos in channels.items():
                    for video_data in videos:
                        vid = video_data[0]
                        if vid in selections:
                            # 動画のラジオボタンをプレイリストIDに設定
                            selections[vid].set(playlist_id)
                            
                            # ボタンの色を更新
                            if update_colors_func:
                                update_colors_func(vid)
                
                logger.debug(f"初期同期: {section_type}/{playlist_id} - {len(channels)}チャンネルの動画を選択")
    # ===== 追加部分ここまで =====
    
    return current_row


def create_section_with_playlists(scrollable_frame, current_row, hierarchical_data, section_type,
                                 section_title, bg_color, fg_color,
                                 selections, button_refs, base_font, update_colors_func, scroll_handler):
    """
    セクション内にプレイリストごとの階層表示を作成（修正版：未設定エリアの翻訳対応）
    """
    # セクション内の動画総数を計算
    section_data = hierarchical_data[section_type]
    total_videos = sum(
        sum(len(videos) for videos in channels.values())
        for channels in section_data.values()
    )
    
    if total_videos == 0:
        return current_row
    
    # セクションヘッダー
    section_header = tk.Label(
        scrollable_frame,
        text=f"{section_title} ({total_videos}件)",
        font=tkfont.Font(family="Meiryo", size=14, weight="bold"),
        bg=bg_color,
        fg=fg_color,
        relief="ridge",
        bd=2
    )
    section_header.grid(row=current_row, column=0, sticky="ew", pady=(10, 5), padx=5, ipady=8)
    scrollable_frame.grid_columnconfigure(0, weight=1)
    scroll_handler.bind_mousewheel_to_widget(section_header)
    current_row += 1
    
    # セパレーター
    separator = tk.Frame(scrollable_frame, height=3, bg=fg_color)
    separator.grid(row=current_row, column=0, sticky="ew", pady=2, padx=5)
    current_row += 1
    
    # 通常のプレイリストごとに表示（0件のプレイリストはスキップ）
    playlist_ids = get_playlist_ids()
    for playlist_id in playlist_ids.keys():
        if playlist_id not in section_data:
            continue
        
        channels = section_data[playlist_id]
        video_count = sum(len(videos) for videos in channels.values())
        
        # 0件の場合はスキップ
        if video_count == 0:
            continue
            
        channel_count = len(channels)
        
        current_row = create_playlist_subsection(
            scrollable_frame, current_row, hierarchical_data, section_type, playlist_id,
            channels, channel_count, video_count,
            selections, button_refs, base_font, bg_color, update_colors_func, scroll_handler
        )
    
    # 🆕 追加：NONEプレイリスト（未設定動画）の特別処理
    if "NONE" in section_data:
        channels = section_data["NONE"]
        video_count = sum(len(videos) for videos in channels.values())
        
        # 0件でない場合のみ表示
        if video_count > 0:
            channel_count = len(channels)
            
            # NONEプレイリスト用のヘッダーフレーム
            header_frame = tk.Frame(scrollable_frame, bg=bg_color)
            header_frame.grid(row=current_row, column=0, sticky="ew", pady=(5, 3), padx=10)
            
            # 未設定動画用のラベル（チェックボックスなし）
            none_label = tk.Label(
                header_frame,
                text=f"❓ プレイリスト未設定 ({channel_count}チャンネル, {video_count}件)",
                font=tkfont.Font(family="Meiryo", size=12, weight="bold"),
                bg=bg_color,
                fg="#ff5722",  # オレンジ色で目立たせる
                anchor="w"
            )
            none_label.pack(side="left", padx=(0, 10))
            scroll_handler.bind_mousewheel_to_widget(none_label)
            
            current_row += 1
            
            # チャンネルごとに未設定動画を表示
            for channel_name in sorted(channels.keys(), reverse=True):
                channel_videos = channels[channel_name]
                
                # チャンネルヘッダーフレーム
                channel_frame = tk.Frame(scrollable_frame, bg="#fff3e0")  # 薄いオレンジ背景
                channel_frame.grid(row=current_row, column=0, sticky="ew", pady=(3, 2), padx=20)
                
                # チャンネル名ラベル（チェックボックスなし）
                channel_label = tk.Label(
                    channel_frame,
                    text=f"  📺 {channel_name} ({len(channel_videos)}件)",
                    font=tkfont.Font(family="Meiryo", size=11),
                    bg="#fff3e0",
                    fg="#e65100"  # 濃いオレンジ文字
                )
                channel_label.pack(side="left", padx=(20, 10))
                scroll_handler.bind_mousewheel_to_widget(channel_label)
                
                current_row += 1
                
                # 各動画を表示
                for video_data in channel_videos:
                    try:
                        vid = video_data[0]
                        title = video_data[1] if len(video_data) > 1 else "タイトル不明"
                        upload_time = video_data[2] if len(video_data) > 2 else "時間不明"
                        duration = video_data[3] if len(video_data) > 3 else None
                        
                        # 動画コンテナフレーム
                        video_container = tk.Frame(scrollable_frame, bg="#fff8e1", relief="ridge", bd=1)
                        video_container.grid(row=current_row, column=0, sticky="ew", pady=2, padx=40)
                        
                        # 動画情報
                        info_frame = tk.Frame(video_container, bg="#fff8e1")
                        info_frame.pack(fill="x", padx=5, pady=(3, 0))
                        
                        # タイトル（⚠️警告アイコン付き）
                        title_text = f"⚠️ {title}"
                        title_label = tk.Label(
                            info_frame,
                            text=title_text,
                            font=base_font,
                            bg="#fff8e1",
                            fg="#d84315",  # 赤みがかったオレンジ
                            anchor="w",
                            justify="left",
                            wraplength=650
                        )
                        title_label.pack(side="top", fill="x", anchor="w")
                        scroll_handler.bind_mousewheel_to_widget(title_label)

                        # ★★★ 修正箇所: ここに翻訳ターゲット登録を追加 ★★★
                        if TRANSLATION_AVAILABLE:
                            translation_targets[vid] = {
                                'label': title_label,
                                'title': title,
                                'idx': "⚠️",  # 警告アイコンをプレフィックスとして維持
                                'time_str': "", # 時間は別ラベルなので空にする
                                'duration_display': "", # 時間は別ラベルなので空にする
                                'filter_info': ""
                            }
                        # ★★★ 修正箇所終わり ★★★
                        
                        # 時間情報
                        time_str = ""
                        if upload_time and upload_time != "時間不明":
                            try:
                                if hasattr(upload_time, 'strftime'):
                                    time_str = upload_time.strftime('[%m-%d %H:%M]')
                                else:
                                    time_str = str(upload_time)
                            except:
                                time_str = str(upload_time)
                        
                        if duration:
                            time_str += f" 📹 {duration}"
                        
                        if time_str:
                            time_label = tk.Label(
                                info_frame,
                                text=time_str,
                                font=tkfont.Font(family="Meiryo", size=9),
                                bg="#fff8e1",
                                fg="#666666",
                                anchor="w"
                            )
                            time_label.pack(side="top", fill="x", anchor="w")
                            scroll_handler.bind_mousewheel_to_widget(time_label)
                        
                        # ラジオボタン行
                        button_frame = tk.Frame(video_container, bg="#fff8e1")
                        button_frame.pack(fill="x", padx=5, pady=(0, 3), anchor="w")
                        
                        # プレイリスト選択を促すメッセージ
                        prompt_label = tk.Label(
                            button_frame,
                            text="→ プレイリストを選択してください:",
                            font=tkfont.Font(family="Meiryo", size=10, weight="bold"),
                            bg="#fff8e1",
                            fg="#ff5722"
                        )
                        prompt_label.pack(side="left", padx=(0, 10))
                        
                        # ラジオボタン作成
                        if vid not in selections:
                            selections[vid] = tk.StringVar()
                            selections[vid].set("NONE")
                        
                        if vid not in button_refs:
                            button_refs[vid] = {}
                        
                        # 未選択ボタン（デフォルト選択）
                        none_button = tk.Radiobutton(
                            button_frame,
                            text="未選択",
                            variable=selections[vid],
                            value="NONE",
                            font=base_font,
                            bg="#ffccbc",  # 薄い赤
                            selectcolor="#ff5722",
                            command=lambda v=vid: update_colors_func(v)
                        )
                        none_button.pack(side="left", padx=2)
                        button_refs[vid]["NONE"] = none_button
                        scroll_handler.bind_mousewheel_to_widget(none_button)
                        
                        # 各プレイリストのボタン（選択を促す）
                        for pl_name in ['V', 'S', 'A', 'B', 'M', 'N', 'L', 'P+']:
                            if pl_name in playlist_ids:
                                pl_button = tk.Radiobutton(
                                    button_frame,
                                    text=pl_name,
                                    variable=selections[vid],
                                    value=pl_name,
                                    font=base_font,
                                    bg="#e8e8e8",
                                    selectcolor="white",
                                    command=lambda v=vid: update_colors_func(v)
                                )
                                pl_button.pack(side="left", padx=2)
                                button_refs[vid][pl_name] = pl_button
                                scroll_handler.bind_mousewheel_to_widget(pl_button)
                        
                        current_row += 1
                        
                    except Exception as e:
                        logger.error(f"未設定動画表示エラー: {e}")
                        current_row += 1
    
    # セクション終了のセパレーター
    end_separator = tk.Frame(scrollable_frame, height=3, bg=fg_color)
    end_separator.grid(row=current_row, column=0, sticky="ew", pady=5, padx=5)
    current_row += 1
    
    return current_row


def create_channel_subsection(scrollable_frame, current_row, hierarchical_data, section_type,
                             playlist_id, channel_name, videos,
                             selections, button_refs, base_font, bg_color, update_colors_func,
                             scroll_handler, parent_playlist_checkbox_var):
    """
    チャンネルサブセクション作成（チェックボックス付き・翻訳機能対応版）
    """
    global channel_checkboxes
    
    # チャンネルヘッダーフレーム
    channel_frame = tk.Frame(scrollable_frame, bg="#f0f0f0")
    channel_frame.grid(row=current_row, column=0, sticky="ew", pady=(3, 2), padx=20)
    
    # チェックボックスの初期状態を判定（修正版）
    # selectedセクションは常にチェック
    if section_type == 'selected':
        has_selected = True
    else:
        has_selected = False
    for video_data in videos:
        vid = video_data[0]
        if vid in selections:
            current_selection = selections[vid].get()
            # NONEでなければ選択されている
            if current_selection and current_selection != "NONE":
                has_selected = True
                break
        else:
            # selectionsにない場合は、video_dataから判定
            if len(video_data) > 5:
                suggestion = video_data[5]
                if suggestion and suggestion != "NONE":
                    has_selected = True
                    break
    
    # チェックボックス変数（タプル形式のキー）
    checkbox_key = (section_type, playlist_id, channel_name)
    checkbox_var = tk.BooleanVar(value=has_selected)
    channel_checkboxes[checkbox_key] = checkbox_var
    
    # チャンネルチェックボックス
    def on_channel_check():
        on_channel_checkbox_changed(
            channel_name, playlist_id, section_type,
            hierarchical_data, selections, update_colors_func
        )
    
    channel_checkbox = tk.Checkbutton(
        channel_frame,
        text=f"  📺 {channel_name} ({len(videos)}件)",
        variable=checkbox_var,
        command=on_channel_check,
        font=tkfont.Font(family="Meiryo", size=11),
        bg="#f0f0f0",
        activebackground="#f0f0f0",
        selectcolor="white"
    )
    channel_checkbox.pack(side="left", padx=(20, 10))
    scroll_handler.bind_mousewheel_to_widget(channel_checkbox)
    
    current_row += 1
    
    # 動画をリスト表示
    for video_data in videos:
        try:
            # 動画データを解析
            vid = video_data[0]
            title = video_data[1] if len(video_data) > 1 else "タイトル不明"
            upload_time = video_data[2] if len(video_data) > 2 else "時間不明"
            duration = video_data[3] if len(video_data) > 3 else None
            channel = video_data[4] if len(video_data) > 4 else channel_name
            playlist_suggestion = video_data[5] if len(video_data) > 5 else "NONE"
            
            # 動画コンテナフレーム（縦に2段構成）
            video_container = tk.Frame(scrollable_frame, bg="white", relief="ridge", bd=1)
            video_container.grid(row=current_row, column=0, sticky="ew", pady=2, padx=40)
            
            # 上段：動画情報行（2行構成）
            info_frame = tk.Frame(video_container, bg="white")
            info_frame.pack(fill="x", padx=5, pady=(3, 0))
            
            # アップロード時間を簡略化（[mm-dd hh:mm]形式、秒なし）
            time_str = ""
            if upload_time and upload_time != "時間不明":
                try:
                    upload_str = str(upload_time).strip()
                    
                    # スペース区切りの日時形式を処理
                    if " " in upload_str:
                        date_part, time_part = upload_str.split(" ", 1)
                        # 日付から月日を抽出
                        date_parts = date_part.split("-")
                        if len(date_parts) >= 3:
                            month = date_parts[1]
                            day = date_parts[2]
                            # 時刻から時分を抽出
                            time_parts = time_part.split(":")
                            if len(time_parts) >= 2:
                                hour = time_parts[0]
                                minute = time_parts[1]
                                time_str = f"[{month}-{day} {hour}:{minute}]"
                    # T区切りのISO形式を処理
                    elif "T" in upload_str:
                        date_part, time_part = upload_str.split("T")
                        date_parts = date_part.split("-")
                        if len(date_parts) >= 3:
                            month = date_parts[1]
                            day = date_parts[2]
                        time_parts = time_part.split(":")
                        if len(time_parts) >= 2:
                            hour = time_parts[0]
                            minute = time_parts[1]
                            time_str = f"[{month}-{day} {hour}:{minute}]"
                except Exception as e:
                    logger.debug(f"時間解析エラー: {upload_time} - {e}")
                    time_str = ""
            
            # 1行目：タイトルのみ
            title_label = tk.Label(
                info_frame,
                text=title,
                font=base_font,
                bg="white",
                anchor="w",
                justify="left",
                wraplength=650
            )
            title_label.pack(side="top", fill="x", anchor="w")
            scroll_handler.bind_mousewheel_to_widget(title_label)

            # ★★★ 修正箇所: ここに翻訳ターゲット登録を追加 ★★★
            if TRANSLATION_AVAILABLE:
                translation_targets[vid] = {
                    'label': title_label,
                    'title': title,
                    'idx': None,  # アイコンなし
                    'time_str': "", # 時間は別ラベルなので空にする
                    'duration_display': "", # 時間は別ラベルなので空にする
                    'filter_info': ""
                }
            # ★★★ 修正箇所終わり ★★★
            
            # 2行目：時間情報と動画時間
            time_info_text = ""
            if time_str:
                time_info_text = time_str
            if duration:
                if time_info_text:
                    time_info_text += f" 📹 {duration}"
                else:
                    time_info_text = f"📹 {duration}"
            
            if time_info_text:
                time_label = tk.Label(
                    info_frame,
                    text=time_info_text,
                    font=tkfont.Font(family="Meiryo", size=9),
                    bg="white",
                    fg="#666666",
                    anchor="w",
                    justify="left"
                )
                time_label.pack(side="top", fill="x", anchor="w")
                scroll_handler.bind_mousewheel_to_widget(time_label)
            
            # 下段：ラジオボタン行
            button_frame = tk.Frame(video_container, bg="white")
            button_frame.pack(fill="x", padx=5, pady=(0, 3), anchor="w")
            
            # ラジオボタン作成
            if vid not in selections:
                selections[vid] = tk.StringVar()
                selections[vid].set(playlist_suggestion)
            
            if vid not in button_refs:
                button_refs[vid] = {}
            
            # 未選択ボタン
            none_button = tk.Radiobutton(
                button_frame,
                text="未選択",
                variable=selections[vid],
                value="NONE",
                font=base_font,
                bg="white",
                selectcolor="white",
                command=lambda v=vid: update_colors_func(v)
            )
            none_button.pack(side="left", padx=2)
            button_refs[vid]["NONE"] = none_button
            scroll_handler.bind_mousewheel_to_widget(none_button)
            
            # 各プレイリストのボタン（V, S, A, B, M, N, L, P+）
            playlist_ids = get_playlist_ids()
            for pl_name in ['V', 'S', 'A', 'B', 'M', 'N', 'L', 'P+']:
                if pl_name in playlist_ids:
                    pl_button = tk.Radiobutton(
                        button_frame,
                        text=pl_name,
                        variable=selections[vid],
                        value=pl_name,
                        font=base_font,
                        bg="#e8e8e8",
                        selectcolor="white",
                        command=lambda v=vid: update_colors_func(v)
                    )
                    pl_button.pack(side="left", padx=2)
                    button_refs[vid][pl_name] = pl_button
                    scroll_handler.bind_mousewheel_to_widget(pl_button)
                    
                    # 初期色設定
                    if selections[vid].get() == pl_name:
                        pl_button.configure(bg="#90EE90", selectcolor="green")
            
            current_row += 1
            
        except Exception as e:
            logger.error(f"動画表示エラー: {e}")
            current_row += 1
    
    return current_row
    



def create_playlist_subsection(scrollable_frame, current_row, hierarchical_data, section_type, playlist_id,
                              channels, channel_count, video_count,
                              selections, button_refs, base_font, bg_color, update_colors_func, scroll_handler):
    """プレイリストサブセクション作成"""
    global playlist_checkboxes
    
    # チェックボックスの初期状態を判定（完全修正版）
    has_selected = False
    for channel_name, channel_videos in channels.items():
        for video_data in channel_videos:
            vid = video_data[0]
            # まずselectionsを確認
            if vid in selections:
                current_selection = selections[vid].get()
                # このプレイリストが選択されているか確認
                if current_selection == playlist_id:
                    # selectedセクションは常にチェック
                    if section_type == 'selected':
                        has_selected = True
                    else:
                        has_selected = True
                    break
            # selectionsにない場合は、video_dataから初期値を確認
            elif len(video_data) > 5:
                suggestion = video_data[5]
                # 提案がこのプレイリストと一致するか確認
                if suggestion == playlist_id:
                    has_selected = True
                    break
        if has_selected:
            break
    
    # チェックボックス変数（タプル形式のキーを使用）
    checkbox_key = (section_type, playlist_id)
    checkbox_var = tk.BooleanVar(value=has_selected)
    playlist_checkboxes[checkbox_key] = checkbox_var
    
    # プレイリストヘッダーフレーム
    header_frame = tk.Frame(scrollable_frame, bg=bg_color)
    header_frame.grid(row=current_row, column=0, sticky="ew", pady=(5, 3), padx=10)
    
    # プレイリストチェックボックス
    def on_playlist_check():
        on_playlist_checkbox_changed(playlist_id, section_type, hierarchical_data, 
                                    selections, update_colors_func)
    
    playlist_checkbox = tk.Checkbutton(
        header_frame,
        text=f"プレイリスト {playlist_id} ({channel_count}チャンネル, {video_count}件)",
        variable=checkbox_var,
        command=on_playlist_check,
        font=tkfont.Font(family="Meiryo", size=12, weight="bold"),
        bg=bg_color,
        activebackground=bg_color,
        selectcolor="white"
    )
    playlist_checkbox.pack(side="left", padx=(0, 10))
    scroll_handler.bind_mousewheel_to_widget(playlist_checkbox)
    
    current_row += 1
    
    # チャンネルごとに表示
    if video_count > 0:
        for channel_name in sorted(channels.keys(), reverse=True):
            channel_videos = channels[channel_name]
            current_row = create_channel_subsection(
                scrollable_frame, current_row, hierarchical_data, section_type,
                playlist_id, channel_name, channel_videos,
                selections, button_refs, base_font, bg_color, update_colors_func,
                scroll_handler, checkbox_var
            )
    else:
        # 0件の場合の表示
        empty_label = tk.Label(
            scrollable_frame,
            text="（該当する動画がありません）",
            font=tkfont.Font(family="Meiryo", size=10),
            bg=bg_color,
            fg="#999999",
            anchor="w"
        )
        empty_label.grid(row=current_row, column=0, sticky="ew", pady=(2, 5), padx=60)
        scroll_handler.bind_mousewheel_to_widget(empty_label)
        current_row += 1
    
    return current_row






def create_playlist_subsection(scrollable_frame, current_row, hierarchical_data, section_type, playlist_id,
                              channels, channel_count, video_count,
                              selections, button_refs, base_font, bg_color, update_colors_func, scroll_handler):
    """プレイリストサブセクション作成"""
    global playlist_checkboxes
    
    # チェックボックスの初期状態を判定
    # selectedセクションは常にチェック
    if section_type == 'selected':
        has_selected = True
    else:
        has_selected = False
    for channel_videos in channels.values():
        for video_data in channel_videos:
            vid = video_data[0]
            if vid in selections:
                current_selection = selections[vid].get()
                if current_selection == playlist_id:
                    has_selected = True
                    break
        if has_selected:
            break
    
    # チェックボックス変数（タプル形式のキーを使用）
    checkbox_key = (section_type, playlist_id)
    checkbox_var = tk.BooleanVar(value=has_selected)
    playlist_checkboxes[checkbox_key] = checkbox_var
    
    # プレイリストヘッダーフレーム
    header_frame = tk.Frame(scrollable_frame, bg=bg_color)
    header_frame.grid(row=current_row, column=0, sticky="ew", pady=(5, 3), padx=10)
    
    # プレイリストチェックボックス
    def on_playlist_check():
        on_playlist_checkbox_changed(playlist_id, section_type, hierarchical_data, 
                                    selections, update_colors_func)
    
    playlist_checkbox = tk.Checkbutton(
        header_frame,
        text=f"プレイリスト {playlist_id} ({channel_count}チャンネル, {video_count}件)",
        variable=checkbox_var,
        command=on_playlist_check,
        font=tkfont.Font(family="Meiryo", size=12, weight="bold"),
        bg=bg_color,
        activebackground=bg_color,
        selectcolor="white"
    )
    playlist_checkbox.pack(side="left", padx=(0, 10))
    scroll_handler.bind_mousewheel_to_widget(playlist_checkbox)
    
    current_row += 1
    
    # チャンネルごとに表示
    if video_count > 0:
        for channel_name in sorted(channels.keys(), reverse=True):
            channel_videos = channels[channel_name]
            current_row = create_channel_subsection(
                scrollable_frame, current_row, hierarchical_data, section_type,
                playlist_id, channel_name, channel_videos,
                selections, button_refs, base_font, bg_color, update_colors_func,
                scroll_handler, checkbox_var
            )
    else:
        # 0件の場合の表示
        empty_label = tk.Label(
            scrollable_frame,
            text="（該当する動画がありません）",
            font=tkfont.Font(family="Meiryo", size=10),
            bg=bg_color,
            fg="#999999",
            anchor="w"
        )
        empty_label.grid(row=current_row, column=0, sticky="ew", pady=(2, 5), padx=60)
        scroll_handler.bind_mousewheel_to_widget(empty_label)
        current_row += 1
    
    return current_row


def create_hierarchical_video_item(parent, row, video_data, selections, button_refs, 
                                  base_font, bg_color, update_colors_func, scroll_handler, 
                                  section_type):
    """
    階層表示用の動画アイテム作成（翻訳機能付き版）
    """
    # メインコンテナ
    video_container = tk.Frame(parent, bg=bg_color)
    video_container.grid(row=row, column=0, sticky="ew", pady=1, padx=80)
    parent.grid_columnconfigure(0, weight=1)
    
    # video_dataからデータを抽出
    if len(video_data) >= 5:
        vid, title, upload_time, duration, channel_name = video_data[:5]
    else:
        return row + 1
    
    # 時間表示
    if upload_time:
        time_str = upload_time.strftime('%m/%d %H:%M')
    else:
        time_str = "時間不明"
    
    # 動画時間の表示
    duration_display = format_duration_display(duration)
    
    # 動画情報ラベル
    info_text = f"[{time_str}] {title} {duration_display}"
    info_label = tk.Label(
        video_container,
        text=info_text,
        font=base_font,
        bg=bg_color,
        anchor="w"
    )
    info_label.pack(fill="x", pady=(2, 1))
    
    # ★★★ 翻訳ターゲットとして登録 ★★★
    if TRANSLATION_AVAILABLE:
        translation_targets[vid] = {
            'label': info_label,
            'title': title,
            'idx': None,  # 階層表示では連番インデックスを使わないためNone
            'time_str': time_str,
            'duration_display': duration_display,
            'filter_info': ""
        }
    
    # 選択ボタンフレーム
    button_frame = tk.Frame(video_container, bg=bg_color)
    button_frame.pack(fill="x", padx=10, pady=(1, 3))
    
    # ラジオボタン処理
    if vid not in selections:
        # ユニークな名前を付与してStringVar作成
        selected = tk.StringVar(master=parent, name=f"selection_{vid}_{row}_{uuid.uuid4().hex[:4]}")
        selections[vid] = selected
        button_refs[vid] = {}
        
        # 初期選択状態を設定
        if section_type == 'filtered' or section_type == 'unselected':
            selected.set("NONE")
        else:
            selected.set(get_smart_playlist_for_channel(channel_name))
    else:
        selected = selections[vid]
    
    # ラジオボタン作成
    none_btn = tk.Radiobutton(
        button_frame,
        text="未選択",
        variable=selected,
        value="NONE",
        command=lambda v=vid: update_colors_func(v),
        font=base_font,
        bg=bg_color,
        selectcolor="white",
        indicatoron=1,
        relief="flat"
    )
    none_btn.pack(side="left", padx=(0, 8))
    
    if vid not in button_refs:
        button_refs[vid] = {}
    button_refs[vid]["NONE"] = none_btn
    
    # プレイリストボタン
    playlist_ids = get_playlist_ids()
    for pl in playlist_ids:
        pl_btn = tk.Radiobutton(
            button_frame,
            text=pl,
            variable=selected,
            value=pl,
            command=lambda v=vid: update_colors_func(v),
            font=base_font,
            bg=bg_color,
            selectcolor="white",
            indicatoron=1,
            relief="flat"
        )
        pl_btn.pack(side="left", padx=(0, 3))
        button_refs[vid][pl] = pl_btn
    
    # スクロールバインド
    widgets = [video_container, info_label, button_frame, none_btn]
    widgets.extend([button_refs[vid][pl] for pl in playlist_ids])
    
    if scroll_handler:
        for widget in widgets:
            scroll_handler.bind_mousewheel_to_widget(widget)
    
    # 初期色更新
    update_colors_func(vid)
    
    return row + 1


# ===== Phase 2 ここまで =====

def create_channel_grouped_display(scrollable_frame, current_row, unselected_videos, selected_videos, filtered_videos,
                                 selections, button_refs, base_font, update_colors_func, scroll_handler):
    """チャンネルごとにグループ化した表示を作成（フィルタリング対応版）（設定外部化対応版）"""
    
    def group_videos_by_channel(videos):
        """動画をチャンネルごとにグループ化（高速版）"""
        channel_groups = defaultdict(list)
        for video_data in videos:
            try:
                if len(video_data) >= 5:
                    channel_name = video_data[4]
                else:
                    channel_name = "不明なチャンネル"
                channel_groups[channel_name].append(video_data)
            except Exception:
                channel_groups["不明なチャンネル"].append(video_data)
        return channel_groups
    
    # 設定からフィルタ表示設定を取得
    filter_settings = get_filter_settings()
    show_filtered_videos = filter_settings.get("show_filtered_videos", True)
    
    # 🔥 フィルタ済み動画セクション（新規追加）
    if filtered_videos and show_filtered_videos:
        filtered_groups = group_videos_by_channel(filtered_videos)
        filtered_total = len(filtered_videos)
        
        # フィルタ済みセクションヘッダー
        filtered_header = tk.Label(
            scrollable_frame,
            text=f"⚡ 短時間動画: 自動フィルタ済み ({filtered_total}件、{len(filtered_groups)}チャンネル)",
            font=tkfont.Font(family="Meiryo", size=14, weight="bold"),
            bg="#f5f5f5",
            fg="#757575",
            relief="ridge",
            bd=2
        )
        filtered_header.grid(row=current_row, column=0, sticky="ew", pady=(10, 5), padx=5, ipady=8)
        scrollable_frame.grid_columnconfigure(0, weight=1)
        scroll_handler.bind_mousewheel_to_widget(filtered_header)
        current_row += 1

        # セパレーター
        separator_filtered = tk.Frame(scrollable_frame, height=3, bg="#bdbdbd")
        separator_filtered.grid(row=current_row, column=0, sticky="ew", pady=2, padx=5)
        current_row += 1

        # チャンネルごとに表示（降順）
        idx = 1
        for channel_name in sorted(filtered_groups.keys(), reverse=True):
            channel_videos = filtered_groups[channel_name]
            
            # チャンネルヘッダー
            channel_header = tk.Label(
                scrollable_frame,
                text=f"📺 {channel_name} ({len(channel_videos)}件)",
                font=tkfont.Font(family="Meiryo", size=12, weight="bold"),
                bg="#f5f5f5",
                fg="#757575",
                anchor="w",
                padx=10
            )
            channel_header.grid(row=current_row, column=0, sticky="ew", pady=(5, 2), padx=15)
            scroll_handler.bind_mousewheel_to_widget(channel_header)
            current_row += 1
            
            # チャンネル内の動画
            for video_data in channel_videos:
                current_row = create_video_item(
                    scrollable_frame, current_row, idx, video_data, 
                    selections, button_refs, base_font, "#f5f5f5", update_colors_func,
                    scroll_handler, display_type="filtered"
                )
                idx += 1

        # セパレーター
        separator_after_filtered = tk.Frame(scrollable_frame, height=3, bg="#bdbdbd")
        separator_after_filtered.grid(row=current_row, column=0, sticky="ew", pady=5, padx=5)
        current_row += 1
        
        # インデックス調整
        filtered_count = len(filtered_videos)
    else:
        filtered_count = 0

    # 未選択動画をチャンネルごとにグループ化
    if unselected_videos:
        unselected_groups = group_videos_by_channel(unselected_videos)
        unselected_total = len(unselected_videos)
        
        # 未選択セクションヘッダー
        unselected_header = tk.Label(
            scrollable_frame, 
            text=f"🔴 要確認: 未選択の動画 ({unselected_total}件、{len(unselected_groups)}チャンネル)",
            font=tkfont.Font(family="Meiryo", size=14, weight="bold"),
            bg="#ffebee",
            fg="#c62828",
            relief="ridge",
            bd=2
        )
        unselected_header.grid(row=current_row, column=0, sticky="ew", pady=(10, 5), padx=5, ipady=8)
        scrollable_frame.grid_columnconfigure(0, weight=1)
        scroll_handler.bind_mousewheel_to_widget(unselected_header)
        current_row += 1

        # セパレーター
        separator1 = tk.Frame(scrollable_frame, height=3, bg="#e57373")
        separator1.grid(row=current_row, column=0, sticky="ew", pady=2, padx=5)
        current_row += 1

        # チャンネルごとに表示（降順）
        idx = filtered_count + 1
        for channel_name in sorted(unselected_groups.keys(), reverse=True):
            channel_videos = unselected_groups[channel_name]
            
            # チャンネルヘッダー
            channel_header = tk.Label(
                scrollable_frame,
                text=f"📺 {channel_name} ({len(channel_videos)}件)",
                font=tkfont.Font(family="Meiryo", size=12, weight="bold"),
                bg="#fff3e0",
                fg="#e65100",
                anchor="w",
                padx=10
            )
            channel_header.grid(row=current_row, column=0, sticky="ew", pady=(5, 2), padx=15)
            scroll_handler.bind_mousewheel_to_widget(channel_header)
            current_row += 1
            
            # チャンネル内の動画
            for video_data in channel_videos:
                current_row = create_video_item(
                    scrollable_frame, current_row, idx, video_data, 
                    selections, button_refs, base_font, "#ffebee", update_colors_func,
                    scroll_handler
                )
                idx += 1

        # セパレーター
        separator2 = tk.Frame(scrollable_frame, height=3, bg="#e57373")
        separator2.grid(row=current_row, column=0, sticky="ew", pady=5, padx=5)
        current_row += 1

    # 選択済み動画をチャンネルごとにグループ化
    if selected_videos:
        selected_groups = group_videos_by_channel(selected_videos)
        selected_total = len(selected_videos)
        
        # 選択済みセクションヘッダー
        selected_header = tk.Label(
            scrollable_frame,
            text=f"✅ 自動選択済み: 登録予定の動画 ({selected_total}件、{len(selected_groups)}チャンネル)",
            font=tkfont.Font(family="Meiryo", size=14, weight="bold"),
            bg="#e8f5e8",
            fg="#2e7d32",
            relief="ridge",
            bd=2
        )
        selected_header.grid(row=current_row, column=0, sticky="ew", pady=(10, 5), padx=5, ipady=8)
        scroll_handler.bind_mousewheel_to_widget(selected_header)
        current_row += 1

        # セパレーター
        separator3 = tk.Frame(scrollable_frame, height=3, bg="#81c784")
        separator3.grid(row=current_row, column=0, sticky="ew", pady=2, padx=5)
        current_row += 1

        # チャンネルごとに表示（降順）
        idx = filtered_count + len(unselected_videos) + 1
        for channel_name in sorted(selected_groups.keys(), reverse=True):
            channel_videos = selected_groups[channel_name]
            
            # チャンネルヘッダー
            channel_header = tk.Label(
                scrollable_frame,
                text=f"📺 {channel_name} ({len(channel_videos)}件)",
                font=tkfont.Font(family="Meiryo", size=12, weight="bold"),
                bg="#e8f5e8",
                fg="#2e7d32",
                anchor="w",
                padx=10
            )
            channel_header.grid(row=current_row, column=0, sticky="ew", pady=(5, 2), padx=15)
            scroll_handler.bind_mousewheel_to_widget(channel_header)
            current_row += 1
            
            # チャンネル内の動画
            for video_data in channel_videos:
                current_row = create_video_item(
                    scrollable_frame, current_row, idx, video_data, 
                    selections, button_refs, base_font, "#e8f5e8", update_colors_func,
                    scroll_handler
                )
                idx += 1

    return current_row

def create_video_item(parent, row, idx, video_data, selections, button_refs, base_font, bg_color, update_colors_func, scroll_handler, display_type="normal"):
    """動画アイテムを作成する共通関数（フィルタリング対応・翻訳機能付き版）"""
    try:
        # データ構造の解析
        if len(video_data) >= 8:
            vid, title, upload_time, duration, channel_name, playlist_suggestion, filter_reason, data_display_type = video_data[:8]
            # video_dataから取得したdisplay_typeを優先
            if data_display_type:
                display_type = data_display_type
        elif len(video_data) >= 5:
            vid, title, upload_time, duration, channel_name = video_data[:5]
            playlist_suggestion = get_smart_playlist_for_channel(channel_name)
            filter_reason = None
        elif len(video_data) >= 4:
            vid, title, upload_time, duration = video_data[:4]
            channel_name = "不明なチャンネル"
            playlist_suggestion = get_smart_playlist_for_channel(channel_name)
            filter_reason = None
        elif len(video_data) == 3:
            vid, title, upload_time = video_data
            channel_name = "不明なチャンネル"
            duration = None
            playlist_suggestion = get_smart_playlist_for_channel(channel_name)
            filter_reason = None
        else:
            vid, title = video_data[:2]
            channel_name = "不明なチャンネル"
            upload_time = None
            duration = None
            playlist_suggestion = get_smart_playlist_for_channel(channel_name)
            filter_reason = None
        
        # 時間表示の生成
        if upload_time:
            time_str = upload_time.strftime('%m/%d %H:%M')
        else:
            time_str = "時間不明"
        
        # 動画時間の強化表示
        duration_display = format_duration_display(duration)
        
        # フィルタリング状態に応じた表示調整
        if display_type == "filtered":
            # フィルタ済み動画：グレーフォント
            text_color = "#757575"
            prefix_icon = "⚡"
            if filter_reason:
                filter_info = f" [{filter_reason}]"
            else:
                filter_info = " [短時間]"
        else:
            # 通常動画：通常フォント
            text_color = "black"
            prefix_icon = "🎬"
            filter_info = ""
        
        # メインコンテナ
        main_container = tk.Frame(parent, bg=bg_color)
        main_container.grid(row=row, column=0, sticky="ew", pady=1, padx=3, ipady=3)
        parent.grid_columnconfigure(0, weight=1)

        # 動画情報
        info_text = f"{idx}. [{time_str}] {title} {duration_display}{filter_info}"
        info_label = tk.Label(
            main_container, 
            text=info_text, 
            font=base_font, 
            bg=bg_color, 
            fg=text_color,  # フィルタ状態に応じた色
            anchor="w"
        )
        info_label.grid(row=0, column=0, sticky="ew", pady=(3, 1), padx=3)

        # ★★★ 翻訳ターゲットとして登録 ★★★
        if TRANSLATION_AVAILABLE:
            translation_targets[vid] = {
                'label': info_label,
                'title': title,
                'idx': idx,
                'time_str': time_str,
                'duration_display': duration_display,
                'filter_info': filter_info
            }

        # 選択ボタンフレーム
        button_frame = tk.Frame(main_container, bg=bg_color)
        button_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=(1, 3))
                
        # StringVarの取得または作成
        if vid in selections and isinstance(selections[vid], tk.StringVar):
            selected = selections[vid]
        else:
            # ユニークな名前でStringVarを作成
            selected = tk.StringVar(master=parent, name=f"selection_{vid}_{idx}")
        
        selections[vid] = selected
        button_refs[vid] = {}

        # 未選択ボタン
        none_btn = tk.Radiobutton(
            button_frame, 
            text="未選択", 
            variable=selected, 
            value="NONE", 
            command=lambda v=vid: update_colors_func(v),
            font=base_font, 
            bg=bg_color, 
            fg=text_color,  # フィルタ状態に応じた色
            selectcolor="white", 
            indicatoron=1, 
            relief="flat"
        )
        none_btn.pack(side="left", padx=(0, 8))
        button_refs[vid]["NONE"] = none_btn

        # プレイリストボタン
        playlist_ids = get_playlist_ids()
        for pl in playlist_ids:
            pl_btn = tk.Radiobutton(
                button_frame, 
                text=pl, 
                variable=selected, 
                value=pl, 
                command=lambda v=vid: update_colors_func(v),
                font=base_font, 
                bg=bg_color, 
                fg=text_color,  # フィルタ状態に応じた色
                selectcolor="white", 
                indicatoron=1, 
                relief="flat"
            )
            pl_btn.pack(side="left", padx=(0, 3))
            button_refs[vid][pl] = pl_btn
        
        # 作成したウィジェットにスクロールをバインド
        widgets_to_bind = [main_container, info_label, button_frame, none_btn]
        widgets_to_bind.extend([button_refs[vid][pl] for pl in playlist_ids])
        
        if scroll_handler:
            for widget in widgets_to_bind:
                scroll_handler.bind_mousewheel_to_widget(widget)
        
        # 初期状態でボタンの色を更新
        update_colors_func(vid)
        
        return row + 1
            
    except Exception as e:
        logger.error(f"GUI要素作成エラー (動画{idx}): {e}")
        return row + 1


# ===== GUI修正版（レイアウト最適化） =====

# グローバルUI更新キュー
ui_update_queue = Queue()
ui_worker_running = False

def start_ui_update_worker(root):
    """UI更新ワーカースレッドを起動"""
    global ui_worker_running
    
    if ui_worker_running:
        return
    
    ui_worker_running = True
    
    def ui_worker():
        while ui_worker_running:
            try:
                func, args, kwargs = ui_update_queue.get(timeout=0.1)
                if root.winfo_exists():
                    root.after(0, lambda f=func, a=args, k=kwargs: f(*a, **k))
            except:
                continue
    
    worker_thread = threading.Thread(target=ui_worker, daemon=True)
    worker_thread.start()
    logger.info("UI更新ワーカースレッド起動")

def safe_ui_update(fn, *args, **kwargs):
    """スレッドセーフなUI更新（Queue経由）"""
    ui_update_queue.put((fn, args, kwargs))



@timing_decorator
def launch_gui(videos, youtube, hours_filter, ui_selection=None, auto_mode=False):
    """GUIを起動（階層表示対応版 + UI選択フィルタ + クォータ情報表示 + Autoモード対応 + 自動翻訳対応）
    
    Args:
        videos: 表示する動画リスト
        youtube: YouTube APIサービスオブジェクト
        hours_filter: 時間フィルタ値
        ui_selection: UI選択状態の辞書（任意）
        auto_mode: Autoモード有効フラグ（デフォルト: False）
    """
    if not videos:
        logger.warning("GUIに表示する動画がありません")
        try:
            _tmp = tk.Tk()
            _tmp.withdraw()
            messagebox.showerror("エラー", f"過去{hours_filter}時間以内の動画が見つかりませんでした。", parent=_tmp)
        finally:
            try:
                _tmp.destroy()
            except:
                pass
        return
    
    # 翻訳ターゲット辞書を初期化
    translation_targets.clear()
    
    # ui_selectionのデフォルト値設定
    if ui_selection is None:
        ui_selection = DEFAULT_SELECTION.copy()
        logger.info("UI選択: デフォルト（全選択）を使用")
    
    logger.info(f"🆕 GUI起動: {len(videos)}件の動画を表示（階層表示版）")
    logger.info(f"Autoモード: {'有効' if auto_mode else '無効'}")
    
    # UI選択のログ出力
    try:
        log_ui_selection(ui_selection, total_candidates=len(videos))
    except Exception as e:
        logger.debug(f"UI選択ログ出力スキップ: {e}")
    
    root = tk.Tk()
    root.title(f"YouTube動画→プレイリスト追加（過去{hours_filter}時間） - 階層表示版")
    root.geometry("900x950")

    # フォント設定（フォールバック付き）
    try:
        base_font = tkfont.Font(family="Meiryo", size=11)
    except:
        base_font = tkfont.Font(family="TkDefaultFont", size=11)
    
    style = ttk.Style()
    style.configure("Playlist.TRadiobutton", font=base_font)
    style.configure("My.TButton", font=base_font)
    style.configure("My.TLabel", font=base_font)
    style.configure("ButtonFrame.TFrame", background="#e0e0e0")
    
    # クォータ情報パネル
    quota_panel = ttk.LabelFrame(root, text="📊 APIクォータ使用状況", padding=8)
    quota_panel.pack(fill="x", padx=8, pady=(8, 4))
    
    # クォータ情報表示用の変数
    quota_text_var = tk.StringVar()
    project_text_var = tk.StringVar()
    
    # クォータ情報を取得して表示
    def update_quota_display():
        """クォータ表示を更新"""
        try:
            if PROJECT_MANAGER:
                status = PROJECT_MANAGER.get_quota_status()
                
                # 現在のプロジェクトとモード
                current_project = status.get('current_project', 'unknown')
                current_mode = status.get('mode', 'auto')
                mode_text = "🔄 自動" if current_mode == 'auto' else "🔒 手動"
                
                # プロジェクト情報
                p1 = status['projects'].get('project1', {})
                p2 = status['projects'].get('project2', {})
                
                # メインクォータテキスト
                quota_lines = []
                
                # Helper function for progress bar
                def create_progress_bar(percentage, length=30):
                    """テキストベースのプログレスバーを生成"""
                    filled = int(length * percentage / 100)
                    bar = "█" * filled + "░" * (length - filled)
                    return f"[{bar}]"

                # Project 1
                p1_bar = create_progress_bar(p1.get('percentage', 0), 30)
                p1_text = f"P1: {p1.get('used', 0):5,}/{p1.get('limit', 10000):,} ({p1.get('percentage', 0):3.0f}%) {p1_bar}"
                if current_project == 'project1':
                    p1_text = "▶ " + p1_text
                else:
                    p1_text = "  " + p1_text
                quota_lines.append(p1_text)
                
                # Project 2
                p2_bar = create_progress_bar(p2.get('percentage', 0), 30)
                p2_text = f"P2: {p2.get('used', 0):5,}/{p2.get('limit', 10000):,} ({p2.get('percentage', 0):3.0f}%) {p2_bar}"
                if current_project == 'project2':
                    p2_text = "▶ " + p2_text
                else:
                    p2_text = "  " + p2_text
                quota_lines.append(p2_text)
                
                # 合計
                total_used = status.get('total_used', 0)
                total_limit = status.get('total_limit', 20000)
                total_percent = (total_used / total_limit * 100) if total_limit > 0 else 0
                total_bar = create_progress_bar(total_percent, 30)
                quota_lines.append(f"合計: {total_used:5,}/{total_limit:,} ({total_percent:3.0f}%) {total_bar}")
                
                quota_text_var.set("\n".join(quota_lines))
                project_text_var.set(f"現在: {current_project} ({mode_text})")
                
                # 警告色の設定
                if p1.get('percentage', 0) >= 90 or p2.get('percentage', 0) >= 90:
                    quota_label.config(foreground="red")
                elif p1.get('percentage', 0) >= 70 or p2.get('percentage', 0) >= 70:
                    quota_label.config(foreground="orange")
                else:
                    quota_label.config(foreground="green")
                    
            else:
                quota_text_var.set("クォータ情報が利用できません")
                project_text_var.set("")
                
        except Exception as e:
            logger.error(f"クォータ表示更新エラー: {e}")
            quota_text_var.set("エラー")
            project_text_var.set("")
    
    # クォータ情報ラベル
    quota_label = ttk.Label(quota_panel, textvariable=quota_text_var, 
                           font=("Courier New", 10))
    quota_label.pack(side="left", padx=(0, 20))
    
    # プロジェクト情報ラベル
    project_label = ttk.Label(quota_panel, textvariable=project_text_var,
                            font=("Meiryo", 10, "bold"))
    project_label.pack(side="left")
    
    # リフレッシュボタン
    refresh_btn = ttk.Button(quota_panel, text="🔄 更新", 
                           command=update_quota_display,
                           width=8)
    refresh_btn.pack(side="right", padx=4)
    
    # 初回表示
    update_quota_display()
    
    # selections を全動画で必ず作成（重複検知付き）
    selections = {}
    playlist_ids = get_playlist_ids()
    valid_playlist_names = set(playlist_ids.keys())
    duplicate_count = 0
    
    for video_data in videos:
        if not video_data:
            continue
        
        vid = video_data[0] if len(video_data) > 0 else None
        if not vid:
            continue
        
        # 重複video_id検知
        if vid in selections:
            logger.warning(f"重複video_id検知: {vid}")
            duplicate_count += 1
            continue
        
        # 推奨プレイリスト（なければ NONE）
        playlist_suggestion = video_data[5] if len(video_data) > 5 and video_data[5] else "NONE"
        
        # 妥当性チェック
        if playlist_suggestion in valid_playlist_names:
            value = playlist_suggestion
        else:
            value = "NONE"
        
        var = tk.StringVar(value=value)
        selections[vid] = var
        
        if value != "NONE":
            logger.debug(f"✓ 事前登録: {vid[:11]} → {value}")
    
    logger.info(f"初期化完了: {len(selections)}件の動画にStringVar設定")
    if duplicate_count > 0:
        logger.info(f"重複video_id: {duplicate_count}件")

    button_refs = {}

    # メインフレームのレイアウト構造
    main_frame = ttk.Frame(root)
    main_frame.pack(fill="both", expand=True, padx=8, pady=4)

    # スクロール可能エリア
    scroll_frame = ttk.Frame(main_frame)
    scroll_frame.pack(fill="both", expand=True)

    canvas = tk.Canvas(scroll_frame)
    scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)

    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    
    # Canvas幅に追従
    frame_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(frame_id, width=e.width))
    
    canvas.configure(yscrollcommand=scrollbar.set)

    # スクロールハンドラー設定
    scroll_handler = None
    if 'ScrollHandler' in globals():
        try:
            scroll_handler = ScrollHandler(canvas)
            if scroll_handler:
                scroll_handler.bind_mousewheel_to_widget(canvas)
        except Exception as e:
            logger.debug(f"ScrollHandler初期化スキップ: {e}")
            scroll_handler = None
    
    def on_canvas_enter(event):
        canvas.focus_set()
    
    canvas.bind("<Enter>", on_canvas_enter)

    # UIフィルタ適用前の階層データを作成
    hierarchical_data_temp = organize_videos_hierarchically(videos)
    
    # デバッグログ
    unselected_before = sum(
        sum(len(vids) for vids in channels.values())
        for channels in hierarchical_data_temp.get('unselected', {}).values()
    )
    logger.info(f"DEBUG: フィルタ前のunselected動画数: {unselected_before}")
    
    hierarchical_data_filtered = None
    
    try:
        hierarchical_data_filtered = filter_hierarchical_data_by_selection(hierarchical_data_temp, ui_selection)
        
        # フィルタ後の統計
        unselected_after = sum(
            sum(len(vids) for vids in channels.values())
            for channels in hierarchical_data_filtered.get('unselected', {}).values()
        )
        logger.info(f"DEBUG: フィルタ後のunselected動画数: {unselected_after}")
        
        filtered_count = sum(
            sum(len(vids) for vids in channels.values())
            for channels in hierarchical_data_filtered.get('filtered', {}).values()
        )
        unselected_count = unselected_after
        selected_count = sum(
            sum(len(vids) for vids in channels.values())
            for channels in hierarchical_data_filtered.get('selected', {}).values()
        )
        total_count = filtered_count + unselected_count + selected_count
        
    except Exception as e:
        on_keys = [k for k, v in ui_selection.items() if v]
        logger.error(f"統計計算エラー: {e} / videos={len(videos)} / ui_selection_on={on_keys}")
        total_count = len(videos)
        unselected_count = 0
        selected_count = 0
        filtered_count = 0
        hierarchical_data_filtered = None
    
    # ヘッダー情報
    duration_stats = globals().get('duration_stats', {'total_attempts': 0, 'css_success': 0})
    if duration_stats.get('total_attempts', 0) > 0:
        success_rate = (duration_stats.get('css_success', 0) / duration_stats['total_attempts']) * 100
        header_text = f"動画 ({total_count}件) - 時間取得率: {success_rate:.0f}%"
    else:
        header_text = f"動画 ({total_count}件)"
    
    header = ttk.Label(scrollable_frame, text=header_text, style="My.TLabel", font=("Meiryo", 12, "bold"))
    header.grid(row=0, column=0, columnspan=7, pady=(0, 8), sticky="w")

    # フィルタリング統計表示
    if total_count > 0:
        filter_summary = f"分類: ✅自動 {selected_count}件 | ❓要確認 {unselected_count}件 | ⚡除外 {filtered_count}件"
        filter_label = ttk.Label(scrollable_frame, text=filter_summary, style="My.TLabel")
        filter_label.grid(row=1, column=0, columnspan=7, pady=(0, 5), sticky="w")

    # 学習データ統計表示
    learned_channels = globals().get('learned_channels', {})
    learning_summary = f"学習: {len(learned_channels)}個"
    
    cache_config = get_video_cache_config()
    if cache_config.get('cache_enabled', True):
        cache_stats = get_cache_hit_stats() if callable(globals().get('get_cache_hit_stats')) else {}
        if cache_stats:
            learning_summary += f" | キャッシュ: {cache_stats.get('total_cached_videos', 0)}件"
    
    learning_summary += " | 設定外部化: 有効 | 階層表示: 有効"
    if auto_mode:
        learning_summary += " | Autoモード: ON"
    
    learning_label = ttk.Label(scrollable_frame, text=learning_summary, style="My.TLabel")
    learning_label.grid(row=2, column=0, columnspan=7, pady=(0, 5), sticky="w")
    current_row = 3

    def update_button_colors(video_id):
        """選択状態に応じてボタンの色を更新（クォータ更新も実行）"""
        try:
            selected_value = selections[video_id].get()
            buttons = button_refs.get(video_id, {})
            
            for button_value, button_widget in buttons.items():
                if selected_value == button_value and button_value != "NONE":
                    button_widget.configure(bg="#90EE90", selectcolor="green")
                else:
                    button_widget.configure(bg="#e8e8e8", selectcolor="white")
            
            # クォータ表示も更新
            update_quota_display()
            
        except Exception:
            pass

    # 階層表示関数を呼び出し
    current_row = create_hierarchical_display(
        scrollable_frame, current_row, videos, ui_selection,
        selections, button_refs, base_font, update_button_colors, 
        scroll_handler, prefiltered=hierarchical_data_filtered
    )

    # スクロール設定
    def setup_final_scroll():
        try:
            if scroll_handler:
                logger.info("全ウィジェットへのスクロールバインド開始")
                scroll_handler.bind_mousewheel_recursive(scrollable_frame)
                logger.info("スクロールバインド完了")
        except Exception as e:
            logger.error(f"スクロールバインドエラー: {e}")
    
    root.after(50, setup_final_scroll)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # ボタンフレームを確実に下部に配置
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(side="bottom", fill="x", pady=(8, 0))

    def submit():
        """選択された動画を登録。登録前に新規チャンネルの学習判定を割り込ませる。"""
        try:
            # --- Phase 1: 学習判定の割り込み ---
            logger.info("🔍 新規チャンネルの学習判定を開始します...")
            new_channels_info = analyze_new_channel_assignments(selections, videos)

            if new_channels_info:
                # 未登録チャンネルがある場合、学習確認ダイアログを表示
                logger.info("🧠 未登録チャンネルを確認中...")
                learning_dialog = ImprovedLearningConfirmationDialog(root, new_channels_info)
                decisions = learning_dialog.show_batch_confirmation_dialog()

                if decisions:
                    # ユーザーが「学習する」を選んだ場合、データを保存
                    update_learning_data_with_decisions(decisions)

            # --- Phase 2: 本来の登録用データ作成 ---
            # 元の動画リストからメタデータを引き出すための辞書を作成
            video_meta_lookup = {v[0]: {'title': v[1], 'upload_time': v[2], 'channel_name': v[4]}
                                for v in videos if len(v) >= 5}

            playlist_groups = defaultdict(lambda: defaultdict(list))
            total_to_add = 0

            for vid, var in selections.items():
                pl_name = var.get()
                if pl_name and pl_name != "NONE":
                    meta = video_meta_lookup.get(vid)
                    if meta:
                        playlist_groups[pl_name][meta['channel_name']].append({
                            'video_id': vid,
                            'title': meta['title'],
                            'upload_time': meta['upload_time'],
                            'channel_name': meta['channel_name'],
                            'playlist_id': get_playlist_ids().get(pl_name)
                        })
                        total_to_add += 1

            if total_to_add == 0:
                messagebox.showinfo("情報", "選択された動画がありません。", parent=root)
                return

            # ソートロジックの適用（お気に入り優先グルーピング版）
            final_ordered_list = []
            fav_set = get_favorites()
            target_order = ['V', 'S', 'A', 'B', 'M', 'N', 'L', 'P+']
            for pl_key in target_order:
                if pl_key not in playlist_groups:
                    continue
                channels_in_pl = playlist_groups[pl_key]
                # お気に入りグループ / 通常グループに二分
                fav_chs    = {ch: vl for ch, vl in channels_in_pl.items() if ch in fav_set}
                normal_chs = {ch: vl for ch, vl in channels_in_pl.items() if ch not in fav_set}
                # 通常チャンネルを先に、お気に入りチャンネルを後に登録
                # （YouTube仕様：後から追加＝上位表示のため、お気に入りが上位に来る）
                for group in (normal_chs, fav_chs):
                    if not group:
                        continue
                    sorted_channels = sorted(
                        group.keys(),
                        key=lambda ch: max(v['upload_time'] for v in group[ch]),
                        reverse=True  # 最新動画日時降順でチャンネルを並べる
                    )
                    for ch_name in sorted_channels:
                        v_list = group[ch_name]
                        # 新しいのが上に来るように、登録は古い順に行う
                        sorted_videos = sorted(v_list, key=lambda x: x['upload_time'])
                        for v_data in sorted_videos:
                            final_ordered_list.append((v_data['video_id'], v_data['playlist_id'], v_data['title']))

            # --- Phase 3: 登録実行 ---
            submit_btn.config(state='disabled')
            progress_dialog = AdvancedProgressDialog(root, total_to_add)
            super_fast_manager = SuperFastPlaylistManager(youtube)

            super_fast_manager.set_progress_callback(lambda c, t, m: safe_ui_update(progress_dialog.update_progress, c, t, m))
            super_fast_manager.set_status_callback(lambda s: safe_ui_update(progress_dialog.update_status, s))
            super_fast_manager.set_stats_callback(lambda s: safe_ui_update(progress_dialog.update_stats, s))

            def run_processing():
                super_fast_manager.add_videos_super_fast(final_ordered_list, use_parallel=False)
                safe_ui_update(lambda: messagebox.showinfo("完了", f"{total_to_add}件の処理が終了しました。"))
                safe_ui_update(root.destroy)

            threading.Thread(target=run_processing, daemon=True).start()

        except Exception as e:
            logger.error(f"Submit error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            messagebox.showerror("エラー", f"登録処理中にエラーが発生しました: {e}")
            

    # メニューバー
    menubar = tk.Menu(root)
    root.config(menu=menubar)

    file_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="ファイル", menu=file_menu)
    file_menu.add_command(label="学習データ表示", command=lambda: show_learned_channels_info(root))
    file_menu.add_separator()
    file_menu.add_command(label="キャッシュ統計", command=lambda: show_cache_statistics(root))
    file_menu.add_command(label="キャッシュクリーンアップ", command=lambda: manual_cache_cleanup(root))
    file_menu.add_separator()
    file_menu.add_command(label="設定フォルダを開く", command=lambda: open_config_directory())
    file_menu.add_command(label="設定リロード", command=lambda: reload_all_configs(root))
    file_menu.add_separator()
    file_menu.add_command(label="終了", command=root.destroy)

    tools_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="ツール", menu=tools_menu)
    tools_menu.add_command(label="クォータ使用状況", command=lambda: show_quota_status(root))
    tools_menu.add_command(label="時間統計", command=lambda: show_duration_stats(root))
    tools_menu.add_command(label="フィルタ統計", command=lambda: show_filter_stats(root))
    tools_menu.add_separator()
    tools_menu.add_command(label="🌐 クォータページを開く", command=lambda: auto_open_quota_page())
    tools_menu.add_command(label="⚙️ 自動オープン設定", command=lambda: show_auto_open_settings(root))
    tools_menu.add_separator()
    tools_menu.add_command(label="プロジェクト切り替え", 
                          command=lambda: switch_project_manually(root, update_quota_display))

    help_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="ヘルプ", menu=help_menu)
    help_menu.add_command(label="ローカル重複管理", command=lambda: show_cache_help(root))
    help_menu.add_command(label="設定外部化", command=lambda: show_config_help(root))
    help_menu.add_command(label="操作方法", command=lambda: show_help(root))
    help_menu.add_command(label="バージョン情報", command=lambda: show_version_info(root))

    # 下部ボタン
    submit_btn = ttk.Button(button_frame, text="選択した動画をプレイリストに追加", 
                           command=submit, style="My.TButton")
    submit_btn.pack(side="left", padx=(0, 8))

    cancel_btn = ttk.Button(button_frame, text="キャンセル", 
                           command=root.destroy, style="My.TButton")
    cancel_btn.pack(side="left")

    cache_btn = ttk.Button(button_frame, text="キャッシュ統計", 
                          command=lambda: show_cache_statistics(root), style="My.TButton")
    cache_btn.pack(side="right", padx=(8, 0))
    
    # クォータ更新ボタン
    quota_btn = ttk.Button(button_frame, text="クォータ更新", 
                          command=update_quota_display, style="My.TButton")
    quota_btn.pack(side="right", padx=(8, 0))

    logger.info("🆕 GUI表示完了（階層表示版＋クォータ情報＋翻訳機能）")
    
    # 定期的なクォータ更新
    def periodic_quota_update():
        try:
            if root.winfo_exists():
                update_quota_display()
                root.after(30000, periodic_quota_update)
        except:
            pass
    
    # UI更新ワーカーを起動
    start_ui_update_worker(root)

    # 翻訳ワーカー起動
    if TRANSLATION_AVAILABLE:
        logger.info("🌍 自動翻訳ワーカー起動")
        run_translation_worker(root)
    else:
        logger.info("⚠️ deep-translatorが未インストールのため翻訳機能は無効です")
    
    root.mainloop()

def switch_project_manually(parent, update_callback=None):
    """手動でプロジェクトを切り替える（新規関数）"""
    if not PROJECT_MANAGER:
        messagebox.showinfo("情報", "プロジェクトマネージャーが初期化されていません", parent=parent)
        return
    
    status = PROJECT_MANAGER.get_quota_status()
    current = status.get('current_project', 'unknown')
    mode = status.get('mode', 'auto')
    
    if mode == 'manual':
        if messagebox.askyesno("確認", 
            f"現在は手動モードで{current}が選択されています。\n"
            f"自動モードに戻しますか？", parent=parent):
            PROJECT_MANAGER.reset_to_auto()
            messagebox.showinfo("完了", "自動モードに切り替えました", parent=parent)
            if update_callback:
                update_callback()
    else:
        # プロジェクト選択ダイアログ
        choices = ['自動', 'Project 1', 'Project 2']
        from tkinter import simpledialog
        choice = simpledialog.askstring("プロジェクト選択", 
            f"現在: {current} (自動モード)\n"
            f"切り替え先を選択してください:\n"
            f"  自動 / project1 / project2", parent=parent)
        
        if choice:
            choice_lower = choice.lower()
            if choice_lower == '自動' or choice_lower == 'auto':
                PROJECT_MANAGER.reset_to_auto()
                messagebox.showinfo("完了", "自動モードに設定しました", parent=parent)
            elif 'project1' in choice_lower or '1' in choice_lower:
                PROJECT_MANAGER.set_manual_mode('project1')
                messagebox.showinfo("完了", "Project 1に固定しました", parent=parent)
            elif 'project2' in choice_lower or '2' in choice_lower:
                PROJECT_MANAGER.set_manual_mode('project2')
                messagebox.showinfo("完了", "Project 2に固定しました", parent=parent)
            
            if update_callback:
                update_callback()



# ===== 進捗ダイアログ修正版（UI最適化） =====
class AdvancedProgressDialog:
    """高機能進捗ダイアログ（UI修正版）"""
    
    def __init__(self, parent, total_items):
        self.parent = parent
        self.total_items = total_items
        self.start_time = time.time()
        
        # ダイアログ作成（🔧 修正: サイズ調整）
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("🚀 超高速プレイリスト追加")  # 🔧 修正: タイトル短縮
        self.dialog.geometry("550x350")  # 🔧 修正: サイズ最適化
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # プログレスバー
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.dialog, 
            variable=self.progress_var, 
            maximum=total_items, 
            length=450  # 🔧 修正: 幅調整
        )
        self.progress_bar.pack(pady=10)
        
        # 進捗テキスト
        self.progress_label = tk.Label(self.dialog, text="準備中...", font=("Meiryo", 11))  # 🔧 修正: フォントサイズ調整
        self.progress_label.pack(pady=5)
        
        # ステータス
        self.status_label = tk.Label(self.dialog, text="📍 開始準備", font=("Meiryo", 10), fg="blue")
        self.status_label.pack(pady=3)  # 🔧 修正: パディング調整
        
        # 統計情報
        self.stats_label = tk.Label(self.dialog, text="📊 統計: 準備中", font=("Meiryo", 10))
        self.stats_label.pack(pady=3)  # 🔧 修正: パディング調整
        
        # 🆕 ローカルキャッシュ統計表示（🔧 修正: 簡潔化）
        cache_config = get_video_cache_config()
        if cache_config.get('cache_enabled', True):
            self.cache_label = tk.Label(self.dialog, text="🆕 キャッシュ: 初期化中", font=("Meiryo", 9), fg="purple")  # 🔧 修正: フォントサイズ調整
            self.cache_label.pack(pady=2)  # 🔧 修正: パディング調整
        else:
            self.cache_label = None
        
        # 🆕 クォータ情報表示（🔧 修正: 簡潔化）
        system_config = get_system_config()
        if system_config.get('quota_monitoring_enabled', True):
            self.quota_label = tk.Label(self.dialog, text="🆕 クォータ: 取得中", font=("Meiryo", 9), fg="green")  # 🔧 修正: フォントサイズ調整
            self.quota_label.pack(pady=2)  # 🔧 修正: パディング調整
        else:
            self.quota_label = None
        
        # 経過時間
        self.time_label = tk.Label(self.dialog, text="⏱️ 経過時間: 0.0秒", font=("Meiryo", 9))  # 🔧 修正: フォントサイズ調整
        self.time_label.pack(pady=2)  # 🔧 修正: パディング調整
        
        # ウィンドウを中央に配置
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (self.dialog.winfo_width() // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (self.dialog.winfo_height() // 2)
        self.dialog.geometry(f"+{x}+{y}")
    
    def update_progress(self, current, total, message=""):
        """🆕 進捗更新（UI修正版）"""
        self.progress_var.set(current)
        
        # パーセンテージ計算
        percentage = (current / total * 100) if total > 0 else 0
        
        # 経過時間と残り時間計算
        elapsed = time.time() - self.start_time
        if current > 0:
            estimated_total = elapsed * total / current
            remaining = max(0, estimated_total - elapsed)
            
            # 🔧 修正: 表示テキスト短縮
            progress_text = f"進捗: {current}/{total} ({percentage:.1f}%) | 残り: {remaining:.1f}秒"
        else:
            progress_text = f"進捗: {current}/{total} ({percentage:.1f}%)"
        
        if message:
            # 🔧 修正: メッセージを短縮表示
            short_message = message[:50] + "..." if len(message) > 50 else message
            progress_text += f"\n{short_message}"
        
        self.progress_label.config(text=progress_text)
        self.time_label.config(text=f"⏱️ 経過: {elapsed:.1f}秒")  # 🔧 修正: テキスト短縮
        
        # 🆕 ローカルキャッシュ統計更新（🔧 修正: 簡潔化）
        if self.cache_label:
            cache_stats = get_cache_hit_stats()
            if cache_stats:
                cache_text = f"🆕 キャッシュ: ヒット{cache_stats.get('cache_hits', 0)} | API削減{cache_stats.get('api_calls_saved', 0)}"
                self.cache_label.config(text=cache_text)
        
        # 🆕 クォータ情報更新（🔧 修正: 簡潔化）
        system_config = get_system_config()
        if system_config.get('quota_monitoring_enabled', True) and global_quota_monitor and self.quota_label:
            quota_status = global_quota_monitor.get_current_usage()
            quota_text = f"🆕 クォータ: {quota_status['percentage']:.0f}% | セッション: +{quota_status['session_usage']:,}"  # 🔧 修正: 表示簡潔化
            self.quota_label.config(text=quota_text)
        
        self.dialog.update()
    
    def update_status(self, status_text):
        """ステータステキストを更新（🔧 修正: 簡潔化）"""
        # 🔧 修正: ステータステキストを短縮
        short_status = status_text[:60] + "..." if len(status_text) > 60 else status_text
        self.status_label.config(text=f"📍 {short_status}")
        self.dialog.update()
    
    def update_stats(self, stats):
        """🆕 統計情報を更新（UI修正版）"""
        # 🔧 修正: 統計表示を簡潔化
        stats_text = f"✅ 成功: {stats.get('success', 0)} | 🔄 重複: {stats.get('duplicate', 0)} | ❌ エラー: {stats.get('error', 0)}"
        
        # ローカルキャッシュ統計を追加
        if stats.get('local_cache_hits', 0) > 0:
            stats_text += f" | 🆕 キャッシュ: {stats['local_cache_hits']}"
        
        self.stats_label.config(text=stats_text)
        self.dialog.update()
    
    def close(self):
        """ダイアログを閉じる"""
        self.dialog.destroy()

# ===== 🆕 ローカル重複管理ユーティリティ関数群 =====
def show_cache_statistics(parent):
    """🆕 キャッシュ統計表示ダイアログ"""
    try:
        stats = get_cache_hit_stats()
        if not stats:
            messagebox.showinfo("キャッシュ統計", "キャッシュ統計データがありません。")
            return
        
        message = "🆕 ローカル重複管理 - キャッシュ統計\n\n"
        message += f"📊 キャッシュ概要:\n"
        message += f"  総プレイリスト数: {stats.get('total_playlists', 0)}個\n"
        message += f"  キャッシュ済み動画: {stats.get('total_cached_videos', 0)}件\n"
        message += f"  ファイルサイズ: {stats.get('cache_file_size', 0)}MB\n\n"
        
        message += f"⚡ セッション統計:\n"
        message += f"  キャッシュヒット: {stats.get('cache_hits', 0)}回\n"
        message += f"  API呼び出し削減: {stats.get('api_calls_saved', 0)}回\n"
        message += f"  新規登録: {stats.get('session_registered', 0)}件\n\n"
        
        cache_efficiency = calculate_cache_efficiency()
        message += f"📈 効率:\n"
        message += f"  {cache_efficiency.get('message', 'データなし')}"
        
        messagebox.showinfo("キャッシュ統計", message)
        
    except Exception as e:
        logger.error(f"🆕 キャッシュ統計表示エラー: {e}")
        messagebox.showerror("エラー", f"キャッシュ統計の表示中にエラーが発生しました:\n{e}")

def manual_cache_cleanup(parent):
    """🆕 手動キャッシュクリーンアップ"""
    try:
        cache_config = get_video_cache_config()
        retention_days = cache_config.get('retention_days', 1)
        
        if messagebox.askyesno("キャッシュクリーンアップ", 
            f"🆕 {retention_days}日より古いキャッシュデータを削除しますか？\n\n"
            f"この操作は元に戻せません。"):
            
            removed_count = cleanup_old_records(retention_days)
            
            if removed_count > 0:
                messagebox.showinfo("クリーンアップ完了", 
                    f"🆕 {removed_count}件の古いキャッシュデータを削除しました。")
            else:
                messagebox.showinfo("クリーンアップ完了", 
                    "🆕 削除対象のキャッシュデータはありませんでした。")
    
    except Exception as e:
        logger.error(f"🆕 手動クリーンアップエラー: {e}")
        messagebox.showerror("エラー", f"クリーンアップ中にエラーが発生しました:\n{e}")

def open_config_directory():
    """🆕 設定ディレクトリをファイルマネージャーで開く"""
    try:
        import subprocess
        import os
        
        config_path = str(CONFIG_DIR.absolute())
        
        if platform.system() == "Windows":
            os.startfile(config_path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", config_path])
        else:  # Linux
            subprocess.run(["xdg-open", config_path])
            
        logger.info(f"🆕 設定ディレクトリを開きました: {config_path}")
        
    except Exception as e:
        logger.error(f"🆕 設定ディレクトリオープンエラー: {e}")
        messagebox.showerror("エラー", f"設定ディレクトリを開けませんでした:\n{e}")

def reload_all_configs(parent):
    """🆕 設定リロード"""
    try:
        if messagebox.askyesno("設定リロード", 
            "🆕 設定ファイルを再読み込みしますか？\n\n"
            "現在のセッションデータは保持されます。"):
            
            old_config_loaded = CONFIG_LOADED
            new_config = load_all_configs()
            
            if CONFIG_LOADED:
                message = "🆕 設定リロード完了！\n\n"
                message += f"読み込み済み設定:\n"
                message += f"  プレイリスト: {len(new_config['playlists'])}個\n"
                message += f"  チャンネルルール: {len(new_config['channel_rules'])}個\n"
                message += f"  フィルタ設定: {'有効' if new_config['filter_settings']['enable_duration_filter'] else '無効'}\n"
                message += f"  キャッシュ機能: {'有効' if new_config['video_cache']['cache_enabled'] else '無効'}"
                
                messagebox.showinfo("リロード完了", message)
            else:
                messagebox.showwarning("リロード警告", 
                    "🆕 設定の再読み込みで一部エラーが発生しました。\n"
                    "デフォルト設定で継続します。")
    
    except Exception as e:
        logger.error(f"🆕 設定リロードエラー: {e}")
        messagebox.showerror("エラー", f"設定リロード中にエラーが発生しました:\n{e}")

def show_quota_status(parent):
    """🆕 クォータ使用状況表示"""
    try:
        system_config = get_system_config()
        if not system_config.get('quota_monitoring_enabled', True) or not global_quota_monitor:
            messagebox.showinfo("クォータ監視", "🆕 クォータ監視機能が無効になっています。")
            return
        
        quota_report = generate_quota_summary_report()
        if quota_report:
            messagebox.showinfo("APIクォータ使用状況", quota_report)
        else:
            messagebox.showinfo("クォータ監視", "🆕 クォータ使用データがありません。")
    
    except Exception as e:
        logger.error(f"🆕 クォータ状況表示エラー: {e}")
        messagebox.showerror("エラー", f"クォータ状況の表示中にエラーが発生しました:\n{e}")

# ===== 既存のユーティリティ関数（設定外部化対応版） =====
def show_learned_channels_info(parent):
    """学習済みチャンネル情報を表示"""
    try:
        if not learned_channels:
            messagebox.showinfo("学習情報", "🧠 学習済みチャンネルはありません。")
            return
        
        message = f"🧠 学習済みチャンネル情報 ({len(learned_channels)}個)\n\n"
        
        # プレイリスト別にグループ化（設定外部化対応版）
        playlist_ids = get_playlist_ids()
        playlist_groups = defaultdict(list)
        
        for channel, playlist in learned_channels.items():
            playlist_groups[playlist].append(channel)
        
        for playlist in sorted(playlist_groups.keys()):
            channels = sorted(playlist_groups[playlist])
            message += f"【{playlist}】 {len(channels)}チャンネル\n"
            for channel in channels[:5]:  # 最初の5個のみ表示
                message += f"  ・{channel}\n"
            if len(channels) > 5:
                message += f"  ...他{len(channels) - 5}個\n"
            message += "\n"
        
        message += "💡 これらのチャンネルの動画は次回から自動振り分けされます。"
        
        messagebox.showinfo("学習済みチャンネル", message)
        
    except Exception as e:
        logger.error(f"学習情報表示エラー: {e}")
        messagebox.showerror("エラー", f"学習情報の表示中にエラーが発生しました:\n{e}")

def show_duration_stats(parent):
    """時間取得統計を表示"""
    if duration_stats['total_attempts'] == 0:
        messagebox.showinfo("時間統計", "📈 時間取得の統計データがありません。")
        return
    
    success_rate = (duration_stats['css_success'] / duration_stats['total_attempts']) * 100
    
    message = f"📈 動画時間取得統計\n\n"
    message += f"総試行回数: {duration_stats['total_attempts']}回\n"
    message += f"成功回数: {duration_stats['css_success']}回\n"
    message += f"成功率: {success_rate:.1f}%\n\n"
    
    if duration_stats['selector_success']:
        message += "セレクター別成功数:\n"
        for selector, count in duration_stats['selector_success'].items():
            message += f"  {selector}: {count}回\n"
        message += "\n"
    
    message += f"失敗した動画: {len(duration_stats['failed_videos'])}件"
    
    messagebox.showinfo("時間取得統計", message)

def show_filter_stats(parent):
    """フィルタリング統計を表示"""
    if filter_stats['total_videos'] == 0:
        messagebox.showinfo("フィルタ統計", "⚡ フィルタリングの統計データがありません。")
        return
    
    message = f"⚡ フィルタリング統計\n\n"
    message += f"総動画数: {filter_stats['total_videos']}件\n"
    message += f"自動選択: {filter_stats['auto_selected']}件\n"
    message += f"手動選択必要: {filter_stats['manual_required']}件\n"
    message += f"短時間動画: {filter_stats['short_videos']}件\n"
    message += f"フィルタ除外: {filter_stats['filtered_out']}件\n"
    message += f"時間不明: {filter_stats['unknown_duration']}件\n\n"
    
    # 設定からフィルタ設定を表示
    filter_settings = get_filter_settings()
    message += f"現在のフィルタ設定:\n"
    message += f"  有効/無効: {'有効' if filter_settings['enable_duration_filter'] else '無効'}\n"
    message += f"  最小時間: {filter_settings['min_duration_seconds']}秒\n"
    message += f"  Shorts除外: {'有効' if filter_settings['auto_exclude_shorts'] else '無効'}"
    
    messagebox.showinfo("フィルタ統計", message)

def show_cache_help(parent):
    """🆕 ローカル重複管理ヘルプ"""
    help_text = """🆕 ローカル重複管理システムについて

【概要】
・登録済み動画をローカルファイルにキャッシュ
・API重複チェックを大幅に削減
・処理速度の向上とクォータ節約を実現

【仕組み】
1. 動画登録成功時にローカルキャッシュに記録
2. 次回実行時はキャッシュから高速重複チェック
3. APIを使わずに重複判定が可能

【メリット】
・API呼び出し回数を90-100%削減
・重複チェックが数秒→数ミリ秒に短縮
・オフラインでも重複チェック可能

【ファイル】
・registered_videos.json: キャッシュデータ
・config/video_cache.json: キャッシュ設定

【設定項目】
・cache_enabled: キャッシュ機能の有効/無効
・retention_days: データ保持期間（日数）
・cleanup_on_startup: 起動時自動クリーンアップ
・max_cache_size_mb: キャッシュファイル最大サイズ

【注意事項】
・初回実行時はキャッシュが空のため効果なし
・2回目以降から大きな効果を発揮
・設定でキャッシュを無効化可能"""

    messagebox.showinfo("ローカル重複管理ヘルプ", help_text)

def show_config_help(parent):
    """🆕 設定外部化ヘルプ"""
    help_text = """🆕 設定外部化システムについて

【概要】
・プログラムの設定をJSONファイルで管理
・コード変更なしで動作をカスタマイズ可能
・複数の設定ファイルに分類して管理

【設定ファイル一覧】
・config/playlists.json: プレイリストID設定
・config/channel_rules.json: チャンネル振り分けルール  
・config/filter_settings.json: フィルタリング設定
・config/system_config.json: システム動作設定
・config/video_cache.json: キャッシュ機能設定

【カスタマイズ方法】
1. config/フォルダの対象ファイルを編集
2. アプリケーションを再起動
3. または「設定リロード」メニューを実行

【設定例】
・プレイリストIDの変更
・チャンネル自動振り分けルールの追加
・フィルタリング時間の調整
・並列処理数の変更
・キャッシュ保持期間の変更

【メリット】
・ユーザー環境に合わせた最適化
・設定変更のためのコンパイル不要
・設定のバックアップ・共有が容易

【注意事項】
・JSON形式エラーがあると設定読み込み失敗
・エラー時はデフォルト設定で動作継続
・設定ファイルが存在しない場合は自動生成"""

    messagebox.showinfo("設定外部化ヘルプ", help_text)

def show_help(parent):
    """操作方法ヘルプ"""
    help_text = """YouTube動画プレイリスト追加ツール - 操作方法

【基本操作】
1. 取得時間を設定（推奨値が自動表示）
2. 動画リストで各動画のプレイリストを選択
3. 「プレイリストに追加」ボタンをクリック

【動画の分類】
✅ 自動選択済み: 学習データに基づく自動振り分け
❓ 要確認: 手動で選択が必要な動画
⚡ フィルタ済み: 短時間動画（自動除外）

【学習機能】
🧠 新しいチャンネルの振り分け結果から学習
・一覧確認ダイアログで学習可否を選択
・学習したチャンネルは次回から自動振り分け

【🆕 新機能】
・ローカル重複管理: API使用量大幅削減
・設定外部化: config/フォルダで設定変更可能  
・クォータ監視: API使用量をリアルタイム監視

【フィルタリング】
・3分以下の動画は自動除外
・YouTube Shorts（60秒以下）も自動除外
・設定で無効化・調整可能

【高速化機能】
・真の並列処理による高速化
・重複チェック最適化
・バッチAPI対応（安定性重視で無効化）

【トラブルシューティング】
・Chrome デバッグポート（9222-9225）で接続
・YouTube ログイン必須
・認証情報は token.pickle に保存"""

    messagebox.showinfo("操作方法", help_text)

def show_version_info(parent):
    """バージョン情報"""
    version_text = """YouTube動画プレイリスト追加ツール

バージョン: Phase 2-1完了版 + ローカル重複管理システム統合版
リリース日: 2025年8月2日

【主要機能】
✅ 超高速動画取得・処理
✅ 学習機能付きチャンネル振り分け
✅ 3分フィルタリング・YouTube Shorts除外
✅ APIクォータ監視システム
🆕 設定外部化システム
🆕 ローカル重複管理システム

【技術仕様】
・Chrome DevTools Protocol接続
・YouTube Data API v3
・真の並列処理対応
・重複チェック最適化

【🆕 新機能詳細】
・ローカル重複管理: API使用量90-100%削減
・設定外部化: config/フォルダでカスタマイズ
・クォータ監視: リアルタイム使用量追跡

開発者: Assistant
ライセンス: MIT License"""

    messagebox.showinfo("バージョン情報", version_text)


        


# ===== メイン実行部分（🆕 統合初期化版） =====
def initialize_global_systems():
    """🆕 グローバルシステムを初期化"""
    global registered_videos_manager, global_quota_monitor, CONFIG_LOADED
    
    try:
        logger.info("🆕 グローバルシステム初期化開始")
        
        # 1. 設定外部化システム初期化
        logger.info("🆕 設定外部化システム初期化中...")
        config_data = load_all_configs()
        if CONFIG_LOADED:
            logger.info("🆕 設定外部化システム初期化完了")
        else:
            logger.warning("🆕 設定外部化システム初期化部分失敗（デフォルト値使用）")
        
        # 2. ローカル重複管理システム初期化
        cache_config = get_video_cache_config()
        if cache_config.get('cache_enabled', True):
            logger.info("🆕 ローカル重複管理システム初期化中...")
            registered_videos_manager = RegisteredVideosManager()
            
            # 起動時クリーンアップ
            if cache_config.get('cleanup_on_startup', True):
                cleanup_count = cleanup_old_records()
                if cleanup_count > 0:
                    logger.info(f"🆕 起動時クリーンアップ: {cleanup_count}件削除")
            
            logger.info("🆕 ローカル重複管理システム初期化完了")
        else:
            logger.info("🆕 ローカル重複管理システム: 無効化")
            registered_videos_manager = None
        
        # 3. クォータ監視システム初期化
        system_config = get_system_config()
        if system_config.get('quota_monitoring_enabled', True):
            logger.info("🆕 クォータ監視システム初期化中...")
            global_quota_monitor = initialize_quota_monitor()
            if global_quota_monitor:
                logger.info("🆕 クォータ監視システム初期化完了")
            else:
                logger.warning("🆕 クォータ監視システム初期化失敗")
        else:
            logger.info("🆕 クォータ監視システム: 無効化")
            global_quota_monitor = None
        
        # 4. 学習システム初期化
        logger.info("🆕 学習システム初期化中...")
        global learned_channels
        load_learned_channels()
        logger.info("🆕 学習システム初期化完了")
        
        logger.info("🆕 全グローバルシステム初期化完了")
        return True
        
    except Exception as e:
        logger.error(f"🆕 グローバルシステム初期化エラー: {e}")
        return False

def cleanup_on_shutdown():
    """🆕 終了時クリーンアップ処理"""
    try:
        logger.info("🆕 終了時クリーンアップ開始")
        
        # 1. ローカル重複管理システムの終了処理
        if registered_videos_manager:
            # 終了時統計表示
            cache_stats = get_cache_hit_stats()
            if cache_stats:
                logger.info(f"🆕 セッション統計: キャッシュヒット{cache_stats.get('cache_hits', 0)}回、API削減{cache_stats.get('api_calls_saved', 0)}回")
            
            # 終了時クリーンアップ
            cache_config = get_video_cache_config()
            if cache_config.get('cleanup_on_shutdown', True):
                cleanup_count = cleanup_old_records()
                if cleanup_count > 0:
                    logger.info(f"🆕 終了時クリーンアップ: {cleanup_count}件削除")
            
            # キャッシュファイル保存
            registered_videos_manager.save_cache()
            logger.info("🆕 ローカル重複管理システム終了処理完了")
        
        # 2. クォータ監視システムの終了処理
        if global_quota_monitor:
            # 最終的なクォータ使用状況を保存
            global_quota_monitor.save_usage_data()
            logger.info("🆕 クォータ監視システム終了処理完了")
        
        # 3. 学習システムの終了処理
        save_learned_channels()
        logger.info("🆕 学習システム終了処理完了")
        
        logger.info("🆕 全システム終了処理完了")
        
    except Exception as e:
        logger.error(f"🆕 終了時クリーンアップエラー: {e}")


def generate_final_summary():
    """🆕 改善された最終サマリー表示（クォータページ自動オープン統合版）"""
    try:
        print("🆕 ===== セッション完了レポート =====")
        print(f"📅 終了時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # ローカル重複管理効果
        if registered_videos_manager:
            cache_stats = get_cache_hit_stats()
            if cache_stats.get('cache_hits', 0) > 0:
                print(f"")
                print(f"🆕 【ローカル重複管理効果】")
                print(f"   キャッシュヒット: {cache_stats['cache_hits']}回")
                print(f"   API呼び出し削減: {cache_stats['api_calls_saved']}回")
                print(f"   削減されたクォータ: 約{cache_stats['api_calls_saved'] * 51}ユニット")
        
        # APIクォータ使用状況（明確化）
        if global_quota_monitor:
            quota_status = global_quota_monitor.get_current_usage()
            session_usage = quota_status.get('session_usage', 0)
            
            print(f"")
            print(f"🆕 【APIクォータ使用状況】")
            print(f"   今日の累計使用量: {quota_status['used']:,}/{quota_status['limit']:,} ({quota_status['percentage']:.1f}%)")
            print(f"   今回のセッション: {session_usage:,} クォータ使用")
            
            if session_usage == 0:
                print(f"   🎉 ローカル重複管理により今回のAPI使用量 = 0")
            elif session_usage > 100:
                print(f"   ⚠️ 多くのクォータを使用しました - ブラウザでの確認を推奨")
            
            remaining = quota_status.get('remaining', 0)
            print(f"   残りクォータ: {remaining:,} ユニット")
        
        print("=====================================")
        
        # 🆕 追加: クォータページ自動オープン（デフォルト有効）
        print("")
        auto_open_result = auto_open_quota_page()
        
        if auto_open_result:
            print("💡 Google Cloud Consoleで詳細なクォータ使用状況を確認できます")
        else:
            print("💡 手動でGoogle Cloud Consoleクォータページを確認することをお勧めします")
        
    except Exception as e:
        logger.error(f"🆕 最終サマリー表示エラー: {e}")
        # フォールバック表示
        print("🆕 ===== 処理完了 =====")
        print(f"📅 終了時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # エラー時でもクォータページは開く（重要）
        try:
            print("🌐 エラー後のクォータページオープン...")
            auto_open_quota_page()
        except Exception:
            print("⚠️ クォータページオープンもスキップ")
            

def test_quota_and_timezone_system():
    """🔧 テスト: クォータ監視と夏時間対応システム"""
    try:
        print("🔧 ===== 夏時間対応テスト開始 =====")
        
        # 1. 夏時間対応関数のテスト
        current_pacific_date = get_pacific_date_string()
        reset_hour = get_correct_reset_hour_jst()
        is_dst = reset_hour == 16
        
        print(f"🆕 太平洋時間日付: {current_pacific_date}")
        print(f"🆕 JST リセット時刻: {reset_hour}:00")
        print(f"🆕 夏時間判定: {'夏時間(PDT)' if is_dst else '標準時(PST)'}")
        
        # 2. クォータ監視システムのテスト
        if global_quota_monitor:
            quota_status = global_quota_monitor.get_current_usage()
            print(f"🆕 現在のクォータ使用量: {quota_status['used']:,}/{quota_status['limit']:,} ({quota_status['percentage']:.1f}%)")
            
            # 残りクォータが少ない場合は警告
            if quota_status['percentage'] > 70:
                print(f"⚠️ 警告: クォータ使用量が {quota_status['percentage']:.1f}% に達しています")
                return False
        
        # 3. ローカル重複管理システムのテスト
        if registered_videos_manager:
            cache_stats = get_cache_hit_stats()
            print(f"🆕 キャッシュ統計: {cache_stats}")
        
        print("🔧 ===== システムテスト完了 =====")
        return True
        
    except Exception as e:
        print(f"🔧 テストエラー: {e}")
        return False

def safe_dry_run_test():
    """🔧 安全なドライランテスト（API呼び出しなし）"""
    try:
        print("🔧 ===== ドライランテスト開始 =====")
        
        # グローバルシステム初期化テスト
        result = initialize_global_systems()
        print(f"システム初期化: {'成功' if result else '失敗'}")
        
        # 夏時間機能テスト
        test_quota_and_timezone_system()
        
        print("🔧 ===== ドライランテスト完了 =====")
        print("✅ API呼び出しなしでシステム動作確認完了")
        
    except Exception as e:
        print(f"🔧 ドライランエラー: {e}")

def verify_actual_quota_usage():
    """🔧 実際のGoogle Cloudクォータ使用量を確認"""
    try:
        print("🔧 ===== 実際のクォータ確認テスト =====")
        
        # YouTube API認証
        youtube = get_youtube_service()
        if not youtube:
            print("❌ YouTube API認証失敗")
            return False
        
        # 小さなAPI呼び出しでテスト（1ユニット消費）
        try:
            # 軽量なAPI呼び出し（channels.list - 1ユニット）
            request = youtube.channels().list(
                part="snippet",
                mine=True
            )
            response = request.execute()
            
            print("✅ API呼び出し成功")
            print(f"🔧 チャンネル情報取得: {response.get('items', [{}])[0].get('snippet', {}).get('title', '不明')}")
            
            # クォータ監視に記録
            if global_quota_monitor:
                global_quota_monitor.record_api_call('channels.list', 1, success=True)
                quota_status = global_quota_monitor.get_current_usage()
                print(f"🔧 ローカル記録更新後: {quota_status['used']}/10,000")
            
            return True
            
        except Exception as e:
            print(f"❌ API呼び出しエラー: {e}")
            if "quota" in str(e).lower():
                print("⚠️ クォータエラー検出 - Google Cloud側でまだリセットされていない可能性")
            return False
            
    except Exception as e:
        print(f"🔧 クォータ確認テストエラー: {e}")
        return False


def show_message_box(kind, title, text):
    """メッセージボックス表示の共通関数"""
    try:
        _tmp = tk.Tk()
        _tmp.withdraw()
        if kind == "error":
            messagebox.showerror(title, text, parent=_tmp)
        elif kind == "info":
            messagebox.showinfo(title, text, parent=_tmp)
        elif kind == "warning":
            messagebox.showwarning(title, text, parent=_tmp)
        _tmp.destroy()
    except Exception:
        print(f"{title}: {text}")



# ===== 🆕 翻訳システム =====

# ===== 🆕 翻訳システム (修正版) =====

def is_japanese(text):
    """
    テキストに日本語（ひらがな・カタカナ）が含まれるか判定
    ※ 漢字(\u4E00-\u9FAF)を含めると中国語も日本語と判定されてしまうため除外
    """
    import re
    # ひらがな、カタカナのみを検出（長音記号ーも含む）
    japanese_pattern = r'[ぁ-んァ-ンー]' 
    return bool(re.search(japanese_pattern, text))

def translate_titles_parallel(short_video_list):
    """
    ショート動画リストのタイトルを並列翻訳する（20260707_02_01新規追加）
    - ThreadPoolExecutor(max_workers=3)で並列実行
    - 各翻訳呼び出しにtimeout=10秒を設定し、タイムアウト時は原題を使用
    - executor.shutdown(wait=False)によりハング中のスレッドが後続処理をブロックしない
    """
    if not TRANSLATION_AVAILABLE:
        for item in short_video_list:
            item['translated_title'] = item['title']
        return short_video_list

    def translate_one(title):
        if is_japanese(title):
            return title
        translator = GoogleTranslator(source='auto', target='ja')
        result = translator.translate(title)
        return result if result else title

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    try:
        futures = {executor.submit(translate_one, item['title']): item for item in short_video_list}
        for future, item in futures.items():
            try:
                item['translated_title'] = future.result(timeout=10)
            except concurrent.futures.TimeoutError:
                logger.warning(f"⚠️ 翻訳タイムアウト(10秒) [{item['video_id']}]: 原題を使用")
                item['translated_title'] = item['title']
            except Exception as e:
                logger.warning(f"⚠️ 翻訳処理例外 [{item['video_id']}]: {e}")
                item['translated_title'] = item['title']
    finally:
        executor.shutdown(wait=False)

    return short_video_list

def get_subscriber_count(channel_name):
    """
    チャンネルの登録者数を learned_channels.json から取得し、
    日本語表記（万人単位）の文字列に整形して返す
    （20260708_01_01新規追加）
    見つからない場合は空文字を返す
    """
    try:
        with open(LEARNED_CHANNELS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        metadata = data.get('channel_metadata', {})
        ch_data = metadata.get(channel_name, {})
        count = ch_data.get('metrics', {}).get('subscriber_count')
        if count is None:
            return ""
        if count >= 10000:
            man = count / 10000
            if man == int(man):
                return f"{int(man)}万人"
            return f"{man:.1f}万人"
        return f"{count}人"
    except Exception as e:
        logger.warning(f"⚠️ 登録者数取得エラー [{channel_name}]: {e}")
        return ""

def generate_short_video_summary_html(short_video_list):
    """
    ショート動画（3分以下・L以外は登録スキップ）の履歴HTMLを生成する
    （20260708_01_01: 統合HTMLサマリー(parse_youtube_card)準拠の構造に全面改訂）
    保存先: SUMMARY_OUTPUT_DIR
    ファイル名: summary_Short_yyyymmdd_hhmmss.html
    """
    if not short_video_list:
        return None

    try:
        os.makedirs(SUMMARY_OUTPUT_DIR, exist_ok=True)
    except Exception as e:
        logger.error(f"❌ Summaryフォルダ作成失敗: {e}")
        return None

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"summary_Short_{timestamp}.html"
    filepath = os.path.join(SUMMARY_OUTPUT_DIR, filename)

    cards_html = ""
    for i, item in enumerate(short_video_list, 1):
        video_url = f"https://www.youtube.com/watch?v={item['video_id']}"
        thumbnail_url = f"https://i.ytimg.com/vi/{item['video_id']}/mqdefault.jpg"
        pl_name = item.get('playlist_suggestion') or "NONE"
        display_title = item.get('translated_title', item['title'])
        sub_count = get_subscriber_count(item['channel_name'])

        pl_badge_html = (
            f"<span style='font-size:0.9em; color:#ffffff; font-weight:700; "
            f"background:#718096; padding:1px 8px; border-radius:4px; "
            f"margin-right:8px;'>{pl_name}</span>"
        )
        sub_html = (
            f"<span style='font-size:0.9em; color:#e53e3e; font-weight:700; "
            f"margin-left:8px;'>(登録者数: {sub_count})</span>"
        ) if sub_count else ''
        dur_html = (
            f"<span style='font-size:0.9em; color:#2b6cb0; font-weight:700; "
            f"margin-left:8px;'>&#x23F1; {item['duration_str']}</span>"
        )

        cards_html += f"""
        <div class="video-card">
            <div class="video-header-layout">
                <div class="video-thumbnail-container">
                    <img src="{thumbnail_url}" class="video-thumbnail-img" alt="Thumbnail">
                </div>
                <div class="video-meta-container">
                    <div class="video-title">{i}. {display_title}</div>
                    <div class="channel-info">{pl_badge_html}{item['channel_name']}{sub_html}{dur_html}</div>
                </div>
            </div>
            <div class="video-link-row">
                <a href="{video_url}" target="_blank" style="color:#667eea; font-weight:600; text-decoration:none;">動画を開く &#x2197;</a>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>ショート動画スキップリスト</title>
<style>
    body {{ font-family: 'Segoe UI', 'Meiryo', sans-serif; background:#f5f6fa; margin:0; padding:20px; }}
    h1 {{ color:#333; }}
    .video-card {{ background: white; border-radius: 0.5rem; padding: 2rem; margin-bottom: 2rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
    .video-header-layout {{ display: flex; gap: 20px; align-items: flex-start; }}
    .video-thumbnail-container {{ flex-shrink: 0; width: 240px; }}
    .video-thumbnail-img {{ width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); aspect-ratio: 16 / 9; object-fit: cover; }}
    .video-meta-container {{ flex-grow: 1; display: flex; flex-direction: column; justify-content: flex-start; min-height: 80px; }}
    .video-title {{ color: #2d3748; font-weight: 700; font-size: 1.4rem; margin-bottom: 0.8rem; line-height: 1.3; }}
    .channel-info {{ color: #4a5568; font-size: 0.95rem; font-weight: 600; }}
    .video-link-row {{ margin-top: 0.8rem; }}
</style>
</head>
<body>
<h1>⏱ ショート動画スキップリスト（{len(short_video_list)}件）</h1>
<p>3分以下のため自動登録をスキップした動画の一覧です（プレイリストLは対象外）。</p>
{cards_html}
</body>
</html>
"""

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"📄 ショート動画サマリーHTML生成完了: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"❌ ショート動画サマリーHTML書き込み失敗: {e}")
        return None


def run_translation_worker(root):
    """バックグラウンドでタイトルを翻訳してUIを更新（修正版）"""
    if not TRANSLATION_AVAILABLE:
        logger.warning("⚠️ deep-translatorライブラリが見つかりません。翻訳機能は無効です。")
        logger.warning("   インストールコマンド: pip install deep-translator")
        return

    def worker():
        logger.info("🌍 自動翻訳ワーカー: 処理開始...")
        translator = GoogleTranslator(source='auto', target='ja')
        
        # 辞書をコピーして反復処理
        targets = list(translation_targets.items())
        count = 0
        
        for vid, data in targets:
            try:
                original_title = data['title']
                
                # すでに日本語（ひらがな・カタカナ）が含まれている場合はスキップ
                if is_japanese(original_title):
                    continue
                
                # 翻訳実行
                try:
                    translated_text = translator.translate(original_title)
                except Exception as api_error:
                    logger.warning(f"⚠️ 翻訳APIエラー: {api_error}")
                    continue
                
                if translated_text and translated_text != original_title:
                    count += 1
                    # [訳] 翻訳タイトル の形式
                    new_title_display = f"[訳] {translated_text}"
                    
                    # UI更新（メインスレッドで実行）
                    def update_ui(d=data, t=new_title_display):
                        try:
                            if d['label'].winfo_exists():
                                idx_str = f"{d['idx']}." if d['idx'] is not None else ""
                                time_part = f"[{d['time_str']}]" if d['time_str'] else ""
                                
                                # 新しい表示テキストを作成
                                new_text = f"{idx_str} {time_part} {t} {d['duration_display']}{d['filter_info']}"
                                
                                # ラベル更新（青色に変更）
                                d['label'].config(text=new_text, fg="#0066cc")
                        except Exception as ui_e:
                            pass
                            
                    safe_ui_update(update_ui)
                    
                # API制限回避のため待機
                time.sleep(0.5) # 間隔を少し広げて安定性向上
                
            except Exception as e:
                logger.warning(f"翻訳処理例外 [{vid}]: {e}")
                continue
        
        logger.info(f"🌍 自動翻訳完了: {count}件のタイトルを翻訳しました")

    threading.Thread(target=worker, daemon=True).start()
    


@timing_decorator
def main():
    """メイン実行関数（コマンドライン引数完全対応版 + ヘッドレスモード対応）"""
    import argparse
    
    # コマンドライン引数パーサー
    parser = argparse.ArgumentParser(
        description='YouTube動画プレイリスト自動追加ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 通常モード（GUI表示）
  python script.py
  
  # ヘッドレスモード（完全自動、GUIなし）
  python script.py --headless --hours 6 --categories ALL
  
  # オートモード（GUIあり、タイマー自動進行）
  python script.py --auto --hours 2.5
  
  # プロジェクト指定
  python script.py --headless --hours 6 --project project1 --categories S A B
        """
    )
    
    parser.add_argument('--headless', action='store_true',
                       help='ヘッドレスモード（GUIなし、完全自動実行）')
    parser.add_argument('--auto', action='store_true',
                       help='オートモード（GUIあり、タイマー自動進行）')
    parser.add_argument('--hours', type=float, default=None,
                       help='取得時間（時間単位、例: 6）。未指定時は推奨値を使用')
    parser.add_argument('--project', choices=['auto', 'project1', 'project2'], 
                       default='auto',
                       help='APIプロジェクト選択（デフォルト: auto）')
    parser.add_argument('--categories', nargs='+', default=None,
                       help='取得カテゴリ（例: S A B または ALL）')
    
    args = parser.parse_args()
    
    # 多重起動チェック
    lock_handle = check_single_instance()
    if not lock_handle:
        print("エラー: プログラムは既に実行中です")
        sys.exit(1)
    
    try:
        logger.info("=" * 60)
        logger.info("🚀 YouTube動画プレイリスト自動追加ツール起動")
        
        # 実行モード判定
        if args.headless:
            logger.info("実行モード: ヘッドレス（完全自動）")
        elif args.auto:
            logger.info("実行モード: オート（タイマー自動進行）")
        else:
            logger.info("実行モード: GUI通常")
        
        logger.info("=" * 60)
        
        # 初期化処理
        initialize_global_systems()
        
        # コマンドライン引数からの設定
        if args.headless or args.auto:
            # 自動モード（ヘッドレスまたはオート）
            logger.info(f"コマンドラインモード: {'ヘッドレス' if args.headless else 'オート'}")
            
            # 推奨時間を計算
            if args.hours is not None:
                hours_filter = args.hours
                logger.info(f"取得時間: {hours_filter}時間（コマンドライン指定）")
            else:
                # last_log = get_last_log_file()
                # hours_filter = calculate_recommended_hours(last_log)
            
                # グローバル変数として計算済みの値を使用する
                hours_filter = DEFAULT_HOURS
                logger.info(f"取得時間: {hours_filter}時間（自動計算）")
            
            # UI選択を解析
            if args.categories:
                if 'all' in args.categories or 'ALL' in args.categories:
                    # 全選択
                    ui_selection = DEFAULT_SELECTION.copy()
                    logger.info(f"カテゴリ選択: すべて")
                else:
                    # カスタム選択
                    ui_selection = {k: False for k in DEFAULT_SELECTION.keys()}
                    ui_selection['all'] = False  # 「すべて」は無効
                    
                    # 指定されたカテゴリのみ有効化
                    for cat in args.categories:
                        cat_upper = cat.upper()
                        if cat_upper in ui_selection:
                            ui_selection[cat_upper] = True
                        elif cat.lower() == 'short':
                            ui_selection['short'] = True
                    
                    selected = [k for k, v in ui_selection.items() if v and k != 'all']
                    logger.info(f"カテゴリ選択: {', '.join(selected)}")
            else:
                # 未指定時はデフォルト（全選択）
                ui_selection = DEFAULT_SELECTION.copy()
                logger.info(f"カテゴリ選択: デフォルト（全選択）")
            
            project_choice = args.project
            auto_enabled = True  # 自動モードフラグ
            
        else:
            # GUIモード（通常）
            logger.info("時間とカテゴリ選択ダイアログ表示")
            result = show_time_and_category_dialog()
            if result is None:
                logger.warning("ユーザーによるキャンセル")
                return
            
            hours_filter, ui_selection, project_choice, auto_enabled = result
        
        logger.info(f"設定時間: {hours_filter}時間")
        logger.info(f"APIプロジェクト選択: {project_choice}")
        logger.info(f"Autoモード: {'有効' if auto_enabled else '無効'}")
        
        # PROJECT_MANAGERに選択を設定
        global PROJECT_MANAGER
        if PROJECT_MANAGER and project_choice != "auto":
            if project_choice == "project1":
                PROJECT_MANAGER.set_manual_mode("project1")
                logger.info("手動モード: Project1を強制使用")
            elif project_choice == "project2":
                PROJECT_MANAGER.set_manual_mode("project2")
                logger.info("手動モード: Project2を強制使用")
        else:
            logger.info("自動モード: クォータに基づくプロジェクト切り替え")
        
        # UI選択のログ出力
        on_keys = [k for k, v in ui_selection.items() if v]
        logger.info(f"UI選択: ON {len(on_keys)}/{len(ui_selection)} ({', '.join(on_keys)})")
        
        # YouTube APIサービス取得
        logger.info("YouTube API認証中...")
        youtube = get_youtube_service()
        if not youtube:
            logger.error("YouTube APIサービスの初期化に失敗")
            if not args.headless:
                show_message_box("error", "エラー", "YouTube APIサービスの初期化に失敗しました。")
            return
        
        # 動画取得
        logger.info(f"過去{hours_filter}時間以内の動画を取得開始")
        videos = fetch_subscribed_videos(hours_filter)
        
        if not videos:
            logger.warning(f"過去{hours_filter}時間以内の動画が見つかりませんでした")
            if not args.headless:
                show_message_box("info", "情報", f"過去{hours_filter}時間以内の動画が見つかりませんでした。")
            return
        
        logger.info(f"動画取得完了: {len(videos)}件")
        # channel_metadata を learned_channels.json に書き込む
        update_channel_metadata_from_videos(videos)

        # ★★★ ヘッドレスモード分岐処理 ★★★
        if args.headless:
            # 完全自動モード：GUIなしで処理
            logger.info("===== ヘッドレスモード: 自動処理開始 =====")

            # 自動的にすべての動画を適切なプレイリストに振り分け
            selected_items = []
            short_video_list = []  # 3分以下スキップ動画（L以外）の履歴（20260707_02_01）
            for video_data in videos:
                if len(video_data) >= 5:
                    vid = video_data[0]
                    title = video_data[1]
                    duration_str = video_data[3]
                    channel_name = video_data[4]

                    # 自動振り分け（学習データ + チャンネルルール）
                    playlist_suggestion = video_data[5] if len(video_data) > 5 else get_smart_playlist_for_channel(channel_name)
                    is_short = is_short_video(duration_str)

                    # プレイリストLは3分フィルタの対象外（常に登録）
                    if playlist_suggestion == "L":
                        playlist_id = get_playlist_ids().get(playlist_suggestion)
                        if playlist_id:
                            selected_items.append((vid, playlist_id, title))
                            logger.debug(f"自動選択: {title[:30]} → {playlist_suggestion}")
                        continue

                    # L以外で3分以下 → 登録スキップし、ショートリストへ記録
                    if is_short:
                        short_video_list.append({
                            'video_id': vid,
                            'title': title,
                            'duration_str': duration_str,
                            'channel_name': channel_name,
                            'playlist_suggestion': playlist_suggestion if playlist_suggestion else "NONE"
                        })
                        logger.debug(f"ショートスキップ: {title[:30]} ({duration_str}) → {playlist_suggestion}")
                        continue

                    # NONE以外は追加対象
                    if playlist_suggestion and playlist_suggestion != "NONE":
                        playlist_id = get_playlist_ids().get(playlist_suggestion)
                        if playlist_id:
                            selected_items.append((vid, playlist_id, title))
                            logger.debug(f"自動選択: {title[:30]} → {playlist_suggestion}")

            logger.info(f"自動選択完了: {len(selected_items)}件を追加対象として選択")

            # ショート動画サマリーHTML生成（プレイリスト登録処理より前に実施）
            if short_video_list:
                logger.info(f"⏱ ショートスキップ: {len(short_video_list)}件 - サマリーHTML生成を開始します")
                translate_titles_parallel(short_video_list)
                summary_path = generate_short_video_summary_html(short_video_list)
                if summary_path:
                    print(f"\n⏱ ショートスキップ: {len(short_video_list)}件 → {os.path.basename(summary_path)}生成完了")
                else:
                    print(f"\n⚠️ ショート動画サマリーHTML生成に失敗しました（{len(short_video_list)}件は登録スキップ済み）")

            if not selected_items:
                logger.warning("追加対象の動画がありません（すべて未設定またはフィルタ済み）")
                print("\n⚠️ 追加対象の動画がありませんでした")
                return

           
            # 進捗表示（コンソールのみ）
            print(f"\n{'='*60}")
            print(f"ヘッドレスモード: {len(selected_items)}件の動画をプレイリストに追加中...")
            print(f"{'='*60}\n")
            
            # 超高速マネージャー初期化
            super_fast_manager = SuperFastPlaylistManager(youtube)
            
            # コンソール進捗表示用コールバック
            def console_progress(current, total, message=""):
                percentage = (current / total * 100) if total > 0 else 0
                print(f"[{current}/{total}] ({percentage:.1f}%) {message}")
            
            def console_status(status):
                print(f"ステータス: {status}")
            
            super_fast_manager.set_progress_callback(console_progress)
            super_fast_manager.set_status_callback(console_status)
            
            # プレイリスト追加実行
            try:
                results = super_fast_manager.add_videos_super_fast(
                    selected_items,
                    use_batch_api=False,
                    use_parallel=False,
                    check_duplicates=True
                )
                
                # 結果サマリー
                success_count = super_fast_manager.stats['success']
                duplicate_count = super_fast_manager.stats['duplicate']
                error_count = super_fast_manager.stats['error']
                
                print(f"\n{'='*60}")
                print(f"✅ 処理完了")
                print(f"{'='*60}")
                print(f"新規登録: {success_count}件")
                print(f"重複スキップ: {duplicate_count}件")
                if error_count > 0:
                    print(f"エラー: {error_count}件")
                
                # プロジェクト情報
                if PROJECT_MANAGER:
                    status = PROJECT_MANAGER.get_quota_status()
                    print(f"\n使用プロジェクト: {status.get('current_project', 'unknown')}")
                
                # クォータ情報
                if global_quota_monitor:
                    quota_status = global_quota_monitor.get_current_usage()
                    print(f"APIクォータ使用: {quota_status.get('used', 0):,}/{quota_status.get('limit', 10000):,} ({quota_status.get('percentage', 0):.1f}%)")
                
                print(f"{'='*60}\n")
                
                logger.info(f"ヘッドレスモード処理完了: 新規{success_count}件、重複{duplicate_count}件、エラー{error_count}件")
                
            except Exception as e:
                logger.error(f"ヘッドレスモード処理エラー: {e}")
                logger.error(f"エラー詳細: {traceback.format_exc()}")
                print(f"\n❌ エラーが発生しました: {e}\n")
                raise
        
        else:
            # GUIモード
            logger.info("===== GUI表示開始 =====")
            launch_gui(videos, youtube, hours_filter, ui_selection, auto_mode=auto_enabled)
        
    except KeyboardInterrupt:
        logger.info("ユーザーによる中断")
    except Exception as e:
        logger.error(f"メイン処理エラー: {e}")
        logger.error(f"エラー詳細: {traceback.format_exc()}")
        if not args.headless:
            show_message_box("error", "エラー", f"処理中にエラーが発生しました:\n{e}")
    
    finally:
        # プロジェクトマネージャーを自動モードに戻す
        if PROJECT_MANAGER:
            PROJECT_MANAGER.reset_to_auto()
        
        # ロックファイルのクリーンアップ
        try:
            if lock_handle:
                if lock_handle != True:
                    try:
                        lock_handle.close()
                        logger.debug("ロックファイルハンドルをクローズしました")
                    except Exception as e:
                        logger.debug(f"ハンドルクローズエラー（無視）: {e}")
                
                lock_file = "youtube_tool.lock"
                if os.path.exists(lock_file):
                    try:
                        os.remove(lock_file)
                        logger.info("ロックファイルを正常に削除しました")
                    except Exception as e:
                        logger.warning(f"ロックファイル削除失敗: {e}")
            else:
                logger.debug("lock_handleがNone - ロックファイル削除を試行")
                force_cleanup_lockfile()
        
        except Exception as e:
            logger.error(f"ロックファイルクリーンアップエラー: {e}")
            try:
                force_cleanup_lockfile()
            except:
                pass
        
        # その他のクリーンアップ処理
        try:
            if callable(globals().get('cleanup_on_shutdown')):
                cleanup_on_shutdown()
        except Exception as e:
            logger.debug(f"クリーンアップエラー（無視）: {e}")
        
        # サマリ生成
        try:
            if callable(globals().get('generate_final_summary')):
                generate_final_summary()
        except Exception as e:
            logger.debug(f"サマリ生成エラー（無視）: {e}")
        
        logger.info("Chromeは次回実行のため維持します")
        logger.info("プログラム終了")


if __name__ == "__main__":
    try:
        # 必要なインポートの確認
        import traceback
        import sys
        
        # ログ設定
        if callable(globals().get('setup_optimized_logging')):
            setup_optimized_logging()
        
        # メイン処理実行
        main()
        
    except Exception as e:
        print(f"起動エラー: {e}")
        import traceback
        traceback.print_exc()
        import sys
        sys.exit(1)

