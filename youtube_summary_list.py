"""
YouTube Summary Integrated System

バージョンはファイル名ではなくGitで管理する。
履歴は次で追える:
    git log --follow -- youtube_summary_list.py
    git blame youtube_summary_list.py
    git log -L :関数名:youtube_summary_list.py
"""
import os as _os
from datetime import datetime as _datetime

# [20260808] 起動ログに出すバージョン表記。
# 従来は手書きの定数で、ファイル名の版数と食い違ったまま放置されていた
# (ファイル名が 20260806_01 でも VERSION は "20260801_03" のままだった)。
# ファイル名による版数管理を廃止したため、手書きの値は必ず陳腐化する。
# そこで、このファイル自身の更新日時から生成する。
# 常に真であり、更新を忘れることがなく、
# 「このログを出したのはどのファイルか」に確実に答えられる。
try:
    VERSION = _datetime.fromtimestamp(
        _os.path.getmtime(_os.path.abspath(__file__))
    ).strftime("%Y%m%d_%H%M")
except Exception:
    VERSION = "unknown"

# ============================================================================
# SECTION 1: IMPORTS AND CONSTANTS
# ============================================================================


import os
import time
import json
import threading
import subprocess
import platform
import re
import logging
import argparse
import psutil

from datetime import datetime, timedelta
from collections import deque
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import random

# UI関連
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

# Web自動化
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

import socket
# デフォルトのソケットタイムアウトを30秒に設定
# これにより、Seleniumの内部通信も30秒でタイムアウトするようになる
# socket.setdefaulttimeout(30)

# YouTube/API関連
from youtube_transcript_api import YouTubeTranscriptApi
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")
import google.generativeai as genai

# OpenAI (オプション)
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# 定数定義

APP_TITLE = f"YouTube Summary Integrated System v{VERSION}"
DEFAULT_MAX_VIDEOS = 10
MAX_VIDEOS_LIMIT = 5000
DEFAULT_PARALLEL_COUNT = 3
# [20260808] 20 から 10 へ変更。20本を一度に処理すると、短時間に大量の
# Geminiセッションが集中してGoogleの確認画面(reCAPTCHA)を誘発し、無人実行が
# 復旧不能になる事象が実機で発生したため。UIの初期表示値もこれに従う。
DEFAULT_GLASP_BATCH_SIZE = 10
CHANNEL_METADATA_MAX_OBSERVED_VIDEOS = 30
MAX_PARALLEL_COUNT = 10
MAX_MEMORY_MB = 8000 # システムの最大メモリ（MB）

# ファイルパス
CONFIG_FILE = "config.json"
LOG_FILE = "youtube_summary.log"
# [計測] youtube_summary.log は実行ごとに mode='w' で作り直されるため、
# 夜間の複数回の実行を横断して集計するための追記専用ファイルを別に持つ。
MEASURE_LOG_FILE = "glasp_measure.log"
# OUTPUT_DIR = Path("output")
OUTPUT_DIR = r"C:\Users\nx023836\Nexperia\My Private - Documents\Summary"
# OUTPUT_DIR.mkdir(exist_ok=True)
RATE_LIMIT_STATE_FILE = "rate_limit_state.json"

# [20260808] Googleの確認画面（BOT判定）で待機に入ったことを、後続の定時実行へ
# 伝えるためのロックファイル。待機中は02:00/05:00のチェーンを丸ごと空振りさせる
# （Step1のプレイリスト削除が先に走ると、未要約の動画が消えるおそれがあるため、
# 要約だけでなくチェーン全体を止める必要がある）。
SUSPEND_LOCK_FILE = "glasp_suspended.lock"
# 待機の打ち切り時刻（翌朝この時刻を過ぎたら諦めて正常終了する）
SUSPEND_DEADLINE_HOUR = 7
# ただし待機は最長でもこの時間まで。夜間の検知を想定した仕組みなので、
# 日中に検知したときに「翌朝7時まで24時間待つ」ことがないよう頭を押さえる。
MAX_SUSPEND_HOURS = 11
# 確認画面が解除されたかを見に行く間隔（秒）。解除の検知は、残しておいた
# 確認画面タブのURLが変わったかを読むだけなので、Googleへの追加通信は発生しない。
SUSPEND_POLL_INTERVAL = 30.0


def is_challenge_url(url: str) -> bool:
    """
    GoogleがBOT判定時に表示する確認画面のURLかどうかを、ページ本文に依らず判定する。

    実機ログ（20260808）では、Geminiへの遷移が
        https://www.google.com/sorry/index?continue=https://gemini.google.com/...
    に差し替えられていた。本文キーワードによる判定は、ページ文言が想定と違うと
    すり抜ける（実際にすり抜けて、確認画面が「ただのエラー」として扱われ、
    54回にわたり静かにリトライされ続けた）。URLは文言に左右されないため、
    こちらを一次判定とする。

    continue= パラメータに元のGemini URLが入るため、クエリ部分は見ずに
    スキーム＋ホスト＋パスだけで判定する。
    """
    if not url:
        return False
    base = str(url).split('?', 1)[0].lower()
    return '/sorry/' in base or '/recaptcha/' in base


def switch_gemini_to_fast_mode(driver):
    """
    [20260408.02] 高速モード自動切替ロジック
    Geminiタブに遷移後、画面上部に「Pro」というテキストのボタンがあればクリックし、
    ドロップダウンから「高速モード」をクリックしてモードを固定します。
    """
    try:
        from selenium.webdriver.common.by import By
        import time
        import logging
        
        # DOM描画のラグを考慮して少し待機
        time.sleep(2)
        
        # Proボタンを探す
        pro_buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Pro')]")
        switched = False
        for btn in pro_buttons:
            if btn.is_displayed():
                btn.click()
                time.sleep(1.5)  # ポップアップのアニメーション待機
                
                # 指定された正確なテキスト「高速モード」のボタンを探してクリック
                fast_buttons = driver.find_elements(By.XPATH, "//*[contains(text(), '高速モード')]")
                for f_btn in fast_buttons:
                    if f_btn.is_displayed():
                        f_btn.click()
                        switched = True
                        logger = logging.getLogger()
                        if logger.hasHandlers():
                            logger.info("⚡ Geminiを高速モードに切り替えました")
                        else:
                            print("⚡ Geminiを高速モードに切り替えました")
                        time.sleep(1)  # 切り替え反映の待機
                        break
            if switched:
                break
    except Exception as e:
        # 要素が見つからない（すでに高速モード等）場合はデバッグログだけ残して進む
        import logging
        logging.getLogger().debug(f"⚠️ モード切り替え確認をスキップしました (Proボタン非表示など): {e}")
        

def check_chrome_debug_port(port=9222, host="127.0.0.1", timeout=1.0):
    """
    [20260806] 指定ポートでChromeがデバッグモード(--remote-debugging-port)で
    待ち受けているかをTCP接続で確認する。Youtube_List_Setup系スクリプトと同じ判定方式。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def kill_target_chrome_processes(profile_name="ChromeDebugProfile"):
    """
    [20260407.01] 個別Chrome終了ロジック
    OS上の全プロセスからChromeを探し、コマンドライン引数に自動化用プロファイル(ChromeDebugProfile)が
    含まれているものだけをピンポイントでkillします。普段使いのChromeは保護されます。
    名前取得時のNoneエラー等を防ぐ安全対策(if not name)を完備しています。
    """
    import logging
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = proc.info.get('name', '')
            if not name: continue  # Noneや空文字を安全にスキップ
            name = name.lower()
            if name in ['chrome.exe', 'chromedriver.exe']:
                cmdline = proc.info.get('cmdline') or []
                # プロファイル名が含まれているか、chromedriverであれば終了させる
                if name == 'chromedriver.exe' or any(profile_name in str(arg) for arg in cmdline):
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception as e:
            # 万が一未知のプロセス情報があってもクラッシュさせない
            logging.getLogger().warning(f"プロセス終了中に無視可能なエラー: {e}")
            continue



def perform_boot_cleanup():
    """起動時の環境浄化（過剰なドライバ削除を抑制版）"""
    import shutil
    import time
    import os
    import platform
    
    print("--- 🧹 起動時クリーンアップを実行中 ---")
    
    # 1. プロセスの強制終了 (Windows) - 個別キルに変更
    if platform.system() == "Windows":
        kill_target_chrome_processes()  # [20260407.01]
    
    time.sleep(0.5) # 少しだけ待機
    print("--- クリーンアップ完了 ---\n")


class ChannelMetadataUpdater:
    """
    [20260425.01] チャンネルのメタデータ（登録者数、観測履歴など）を
    learned_channels.json の 'channel_metadata' ブロックに安全に保存する専用クラス。
    既存の 'channels' ブロック（マネジメントツール用）には一切干渉しない。
    """
    def __init__(self, json_path: str = "learned_channels.json"):
        self.json_path = Path(json_path)

    def _clean_subscriber_count(self, raw_str: str) -> Optional[int]:
        """文字列（例: '1.23万人', '8000人'）を純粋な整数に変換する"""
        if not raw_str:
            return None
        import re
        # 余計な文字を削除
        clean_str = re.sub(r'チャンネル登録者数|人|約|\s', '', raw_str)
        
        # 数値と単位（万）を抽出
        match = re.search(r'([\d\.]+)(万?)', clean_str)
        if not match:
            return None
            
        num_val = float(match.group(1))
        has_man = match.group(2) == '万'
        
        if has_man:
            return int(num_val * 10000)
        return int(num_val)


    def update_metadata(self, summary_results: List['SummaryResult']):
        """要約結果リストを受け取り、JSONを更新・保存する"""
        if not summary_results:
            return
            
        try:
            # 1. 既存データの読み込み
            data = {"version": "1.0", "channels": {}, "channel_metadata": {}}
            if self.json_path.exists():
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            if "channel_metadata" not in data:
                data["channel_metadata"] = {}
                
            metadata = data["channel_metadata"]
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            update_count = 0

            # 2. データの更新
            for result in summary_results:
                if not result.success:
                    continue
                    
                video = result.video_info
                ch_name = video.channel
                if not ch_name or ch_name == "Unknown":
                    continue

                # チャンネル枠の初期化
                if ch_name not in metadata:
                    metadata[ch_name] = {
                        "metrics": {"subscriber_count": None},
                        "history": {"last_updated": current_time, "observed_videos": []}
                    }
                
                ch_data = metadata[ch_name]
                
                # 登録者数の更新（取得できている場合のみ上書き）
                sub_val = self._clean_subscriber_count(getattr(video, 'subscriber_count', ''))
                if sub_val is not None:
                    ch_data["metrics"]["subscriber_count"] = sub_val
                
                # 動画履歴の追加（重複排除）
                history_list = ch_data["history"].get("observed_videos", [])
                video_id = video.video_id
                if not any(v.get("video_id") == video_id for v in history_list):
                    history_list.append({
                        "observed_at": current_time,
                        "video_id": video_id,
                        "title": video.title
                    })
                    # 最新N件のみ保持
                    ch_data["history"]["observed_videos"] = sorted(
                        history_list,
                        key=lambda x: x["observed_at"],
                        reverse=True
                    )[:CHANNEL_METADATA_MAX_OBSERVED_VIDEOS]
                    ch_data["history"]["last_updated"] = current_time
                    update_count += 1

            # 3. 保存
            if update_count > 0:
                with open(self.json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                log_message(f"チャンネルメタデータを保存しました（{update_count}件更新）", "INFO")
                
        except Exception as e:
            log_message(f"チャンネルメタデータ保存エラー: {e}", "ERROR")


# ============================================================================
# SECTION 2: CONFIGURATION
# ============================================================================

# モデル設定
MODEL_CONFIG = {
    'gemini-2.5-flash-lite': {
        'name': 'Gemini 2.5 Flash-Lite',
        'provider': 'google',
        'model_id': 'gemini-2.5-flash-lite',
        'cost_per_1k_input': 0.0001,  # $0.10/1M = $0.0001/1K
        'cost_per_1k_output': 0.0004,  # $0.40/1M = $0.0004/1K
        'description': '最速・最低コスト',
        'max_tokens': 1000000  # 1Mトークン
    },
    'gemini-2.5-flash': {
        'name': 'Gemini 2.5 Flash',
        'provider': 'google',
        'model_id': 'gemini-2.5-flash',
        'cost_per_1k_input': 0.00035,  # $0.35/1M (推定値)
        'cost_per_1k_output': 0.00105,  # $1.05/1M (推定値)
        'description': '高速・バランス型',
        'max_tokens': 1000000  # 1Mトークン
    },
    'gpt-4o-nano': {
        'name': 'GPT-4o Nano',
        'provider': 'openai',
        'model_id': 'gpt-4o-mini',  # 実際のモデルID
        'cost_per_1k_input': 0.00015,  # $0.15/1M
        'cost_per_1k_output': 0.0006,   # $0.60/1M
        'description': '最小・最速のGPT',
        'max_tokens': 128000  # 128Kトークン
    },
    'gpt-4o-mini': {
        'name': 'GPT-4o Mini',
        'provider': 'openai',
        'model_id': 'gpt-4o-mini',
        'cost_per_1k_input': 0.00015,  # $0.15/1M
        'cost_per_1k_output': 0.0006,   # $0.60/1M
        'description': '軽量版GPT-4o',
        'max_tokens': 128000  # 128Kトークン
    },
    'gpt-4o': {
        'name': 'GPT-4o',
        'provider': 'openai',
        'model_id': 'gpt-4o',
        'cost_per_1k_input': 0.0025,  # $2.50/1M
        'cost_per_1k_output': 0.01,    # $10.00/1M
        'description': '最高品質',
        'max_tokens': 128000  # 128Kトークン
    }
}

# デフォルト設定
DEFAULT_CONFIG = {
    'general': {
        'default_mode': 'glasp',  # 'glasp' or 'api'
        'max_videos': DEFAULT_MAX_VIDEOS,
        'auto_save': True,
        # [20260808_02] 'html' から 'both' に変更。
        # 従来はHTMLのみ出力で save_json() が一度も呼ばれておらず、
        # 機械可読な実行記録が残っていなかった（morning_brief作成時に判明）。
        # JSONには要約文字数・処理時間・GeminiチャットURLが含まれ、
        # 実行台帳や後段の差分処理がHTMLを解析せずに済む。
        # 注意: PC上の config.json に設定が保存されている場合はそちらが優先される。
        'output_format': 'both',  # 'json', 'html', 'both'
        'language': 'ja',
        'auto_mode_on_startup': False  # 新規追加：起動時に自動モードON
    },

    'glasp': {
        # [20260808] 1巡目できらきらボタンを押すかどうか。
        # False（既定）= 押さない。タブ切替・動画読込待ち・字幕確認・一時停止までは
        # 行い、クリックだけしない。捨てるためのGeminiセッションを作らないので、
        # Googleへのリクエストがほぼ半減する。
        # True = 従来動作（1巡目もクリックし、開いたタブは捨てる）。
        # 注意: PC上の config.json に設定が保存されている場合はそちらが優先される。
        'round1_click': False,
        # === 基本設定（既存値維持）===
        'retry_count': 2,
        'retry_delay': 2,
        'retry_timeout': 3,
        'batch_size': DEFAULT_GLASP_BATCH_SIZE,
        'batch_interval': 0.5,
        'cleanup_delay': 3,
        'max_batch_size': 20,
        'chrome_debug_port': 9222,
        'auto_start_chrome': False,
        
        # === タイムアウト設定（最適化）===
        'tab_generation_timeout': 5,  # Glaspタブ生成待機（2本目以降。実測: 成功時最大3.69秒）
        'tab_generation_timeout_first': 8,  # 初回動画用（実測: 成功時最大4.71秒）
        'summary_completion_timeout': 20,  # 要約完了待機（20→10秒に短縮）
        'early_failure_check': 5,
        'cdp_safe_timeout': 60, # 
        
        # === 新規追加：待機時間の最適化設定 ===
        'close_wait_time': 3,  # 失敗タブクローズ前の短い待機
        'summary_check_interval': 0.5,  # 要約チェック間隔
        
        # === 新規追加：タブプール設定 ===
        'max_youtube_tab_pool_size': 10,  # YouTubeタブの再利用プールサイズ
        
        # === フォーカス制御設定（新規）===
        'use_selenium_actions': True,  # Selenium Actions優先使用

        # === バッチ処理設定（新規）===
        'batch_delay': 2,  # バッチ間の待機時間
        
        # === Quick Check設定（既存維持）===
        'quick_check': {
            'base_wait_time': 1.0,
            'max_wait_time': 8.0,
            'wait_intervals': [1.0, 2.0, 2.0, 2.0, 1.0],
            'min_text_length': 500,
            'transcript_timeout': 5.0,
            'enable_detailed_logging': True
        }
    },
    'api': {
        'default_model': 'gemini-2.5-flash-lite',
        'parallel_count': DEFAULT_PARALLEL_COUNT,
        'timeout': 30,
        'max_retries': 3,
        'gemini_api_key': os.environ.get('GEMINI_API_KEY', ''),
        'openai_api_key': os.environ.get('OPENAI_API_KEY', '')
    },
    'rate_limit': {
        'max_requests_per_hour': 200,
        'base_delay': 1.5,
        'warning_threshold': 180,
        'burst_size': 5,
        'burst_interval': 5,
        'window_minutes': 60
    },
    'ui': {
        'window_width': 1600,   # 【修正】1000→1600px (レスポンシブUIでのボタン隠れ防止)
        'window_height': 600,
        'theme': 'default',
        'auto_scroll': True,
        'show_cost': True,
        'show_rate_limit_status': True,
        'show_batch_progress': True,  # バッチ進捗表示
        'show_tab_tracker': True  # 新規追加: タブ追跡状況表示
    },
    'output': {
        'save_transcript': False,
        'save_metadata': True,
        'group_by_channel': False,
        'html_template': 'modern'  # 'simple', 'modern', 'dashboard'
    },
    'memory': {  # 新規追加: メモリ管理設定
        'warning_threshold_mb': 4000,  # メモリ警告閾値（MB）
        'force_gc_interval': 5,  # 強制GC実行間隔（バッチ数）
        'enable_monitoring': True  # メモリ監視有効化
    }
}

# 設定管理クラス
class ConfigManager:
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()
    
    def load_config(self):
        """設定ファイルから読み込み"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self._merge_config(self.config, loaded_config)
            except Exception as e:
                print(f"設定ファイル読み込みエラー: {e}")
    
    def save_config(self):
        """設定をファイルに保存"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"設定ファイル保存エラー: {e}")
    
    def _merge_config(self, base, update):
        """設定を再帰的にマージ"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value
    
    def get(self, key_path, default=None):
        """ドット記法で設定値を取得"""
        keys = key_path.split('.')
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
    
    def set(self, key_path, value):
        """ドット記法で設定値を設定"""
        keys = key_path.split('.')
        target = self.config
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value


    def get_playlist_config(self) -> Dict[str, str]:
        """固定プレイリスト設定を取得
        
        Returns:
            Dict[str, str]: プレイリスト名とIDのマッピング
        """
        # デフォルトのプレイリスト設定
        default_playlists = {
            "V":  "PL0UGJjoPnxKgZaJvHD5lGzOmGnEAdrn9H",
            "S":  "PL0UGJjoPnxKjT1ClcCwngoCDhModNIG3H",
            "A":  "PL0UGJjoPnxKgphke6I63QVyHeToWaNSTD",
            "B":  "PL0UGJjoPnxKhM3jXPMhNxONyvyZbClDuM",
            "N":  "PL0UGJjoPnxKj6T0VlBmyxVqVmBIK1h3G6",
            "M":  "PL0UGJjoPnxKhX6NN6K5GSPCzh9H8bK1F3",
            "P+": "PL0UGJjoPnxKggbm7xrXUJQAExVbuca8-M",
            "L":  "PL0UGJjoPnxKhEsnwZqNSkcUZow4Uklz5R",
        }
        
        # 設定ファイルから読み込み（カスタマイズ可能にする場合）
        custom_playlists = self.get('playlists.fixed', {})
        
        # カスタム設定がある場合はマージ
        if custom_playlists:
            # デフォルトをベースにカスタム設定で上書き
            playlists = default_playlists.copy()
            playlists.update(custom_playlists)
            return playlists
        
        # カスタム設定がない場合はデフォルトを返す
        return default_playlists



# ============================================================================
# SECTION 3: GLOBAL STATE MANAGEMENT
# ============================================================================

# ロギング設定を最初に移動
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== 新規追加：AutoModeManager クラス ==========

class AutoModeManager:
    """自動モード管理クラス
    
    全てのダイアログとユーザー入力待ちを自動化するための管理クラス。
    Autoチェックボックスがオンの場合、すべての確認ダイアログを自動で処理。
    """
    
    def __init__(self):
        """初期化"""
        self.enabled = False  # 自動モードの有効/無効
        self.auto_delay = 5  # 自動クローズまでの待機時間（秒）
        
        # デフォルトレスポンス設定
        self.default_responses = {
            'yesno': True,        # askyesno系は常にTrue（Yes/OK）
            'okcancel': True,     # askokcancel系も常にTrue
            'choice_index': 0,    # リスト選択は最初の項目（インデックス0）
            'error_continue': True,  # エラー時も継続（致命的エラー以外）
            'warning_continue': True  # 警告時も継続
        }
        
        # ========== 新規追加：自動開始タイマー管理 ==========
        self.auto_start_timer_id = None  # 自動開始タイマーのID
        self.app_reference = None  # アプリケーションインスタンスへの参照
        
        logger.info("AutoModeManager initialized")
    
    def enable(self):
        """自動モードを有効化"""
        self.enabled = True
        logger.info("🤖 自動モード: 有効化")
        log_message("自動モードが有効化されました", "INFO")
    
    def disable(self):
        """自動モードを無効化"""
        self.enabled = False
        logger.info("👤 自動モード: 無効化")
        log_message("自動モードが無効化されました", "INFO")
        
        # ========== 新規追加：自動開始タイマーをキャンセル ==========
        self.cancel_auto_start()
    
    def is_enabled(self) -> bool:
        """自動モードが有効かチェック
        
        Returns:
            bool: 有効な場合True
        """
        return self.enabled
    
    def get_default_response(self, response_type: str):
        """指定された応答タイプのデフォルト値を取得
        
        Args:
            response_type: 応答タイプ（'yesno', 'okcancel', 'choice_index'など）
            
        Returns:
            デフォルト応答値
        """
        return self.default_responses.get(response_type, True)
    
    # ========== 新規追加：自動開始関連メソッド ==========
    
    def set_app_reference(self, app):
        """アプリケーションインスタンスへの参照を設定
        
        Args:
            app: IntegratedSummaryAppインスタンス
        """
        self.app_reference = app
    
    def schedule_auto_start(self, delay_seconds: int = None):
        """自動開始をスケジュール
        
        Args:
            delay_seconds: 遅延秒数（Noneの場合はデフォルト値使用）
        """
        if not self.app_reference:
            logger.warning("アプリ参照が未設定のため自動開始できません")
            return
        
        # 既存のタイマーをキャンセル
        self.cancel_auto_start()
        
        delay = delay_seconds if delay_seconds is not None else self.auto_delay
        delay_ms = delay * 1000  # 秒 → ミリ秒
        
        log_message(f"🤖 自動開始タイマー設定: {delay}秒後に処理を開始します", "INFO")
        
        # タイマー設定
        self.auto_start_timer_id = self.app_reference.after(
            delay_ms, 
            self.app_reference.auto_start_processing
        )
    
    def cancel_auto_start(self):
        """自動開始タイマーをキャンセル"""
        if self.auto_start_timer_id and self.app_reference:
            try:
                self.app_reference.after_cancel(self.auto_start_timer_id)
                logger.info("自動開始タイマーをキャンセルしました")
            except:
                pass
            self.auto_start_timer_id = None


# タブ追跡クラス（新規追加）
class TabTracker:
    """全タブの追跡と管理を行うクラス"""



    def __init__(self, driver=None):
        """タブトラッカーの初期化"""
        self.driver = driver  # WebDriverインスタンスを保持
        self.youtube_tabs = {}  # {video_id: tab_handle}
        self.glasp_tabs = {}    # {tab_handle: video_id}
        self.success_tabs = {}  # {video_id: tab_handle} 成功したGlaspタブ（追加）
        self.failed_tabs = []   # 失敗したタブのハンドル
        self.retry_counts = {}  # {video_id: retry_count}
        self.tab_status = {}    # {tab_handle: status} タブの状態（追加）
        logger.info("TabTracker: 初期化完了")

    

        
    def record_youtube_tab(self, video_id: str, handle: str, title: str):
        """YouTubeタブを記録"""
        self.youtube_tabs[video_id] = {
            'handle': handle,
            'title': title,
            'timestamp': time.time()
        }
        logger.info(f"YouTubeタブ記録: {video_id[:8]}... - {title[:30]}...")
    
    def record_glasp_tab(self, handle: str, video_id: str, attempt: int = 1, status: str = 'pending'):
        """Glaspタブを記録"""
        self.glasp_tabs[handle] = {
            'video_id': video_id,
            'status': status,
            'timestamp': time.time(),
            'attempt': attempt
        }
        logger.info(f"Glaspタブ記録: attempt={attempt}, video_id={video_id[:8]}..., status={status}")
    
    def mark_success(self, handle: str):
        """成功タブをマーク"""
        if handle in self.glasp_tabs:
            self.glasp_tabs[handle]['status'] = 'success'
            video_id = self.glasp_tabs[handle]['video_id']
            self.success_tabs[video_id] = handle
            logger.info(f"Glaspタブ成功: {video_id[:8]}...")
    
    def mark_failed(self, handle: str):
        """失敗タブをマーク"""
        if handle in self.glasp_tabs:
            self.glasp_tabs[handle]['status'] = 'failed'
            self.failed_tabs.append(handle)
            logger.info(f"Glaspタブ失敗: {self.glasp_tabs[handle]['video_id'][:8]}...")
    
    def get_failed_tabs(self) -> List[str]:
        """失敗タブのハンドルリストを取得"""
        return [h for h in self.failed_tabs if h in self.glasp_tabs and self.glasp_tabs[h]['status'] == 'failed']
    
    def get_success_tab_for_video(self, video_id: str) -> Optional[str]:
        """特定の動画の成功タブハンドルを取得"""
        return self.success_tabs.get(video_id)
    
    def cleanup_failed_tabs(self, driver):
        """失敗タブを一括クローズ"""
        closed_count = 0
        for handle in self.get_failed_tabs():
            try:
                driver.switch_to.window(handle)
                driver.close()
                closed_count += 1
                del self.glasp_tabs[handle]
            except Exception as e:
                logger.warning(f"タブクローズエラー: {e}")
        
        self.failed_tabs = []
        logger.info(f"失敗タブ {closed_count}個をクローズ")
        return closed_count
    
    def get_unknown_tabs(self, driver) -> List[str]:
        """未記録のタブ（漏れタブ）を検出"""
        all_handles = set(driver.window_handles)
        known_handles = set()
        
        # 既知のタブを収集
        if self.original_tab:
            known_handles.add(self.original_tab)
        
        for video_data in self.youtube_tabs.values():
            known_handles.add(video_data['handle'])
        
        known_handles.update(self.glasp_tabs.keys())
        
        # 未知のタブを返す
        unknown = list(all_handles - known_handles)
        if unknown:
            logger.warning(f"未記録タブ検出: {len(unknown)}個")
        
        return unknown



    def cleanup_unknown_tabs(self, known_handles: set) -> int:
        """未記録タブを全てクローズ（新規追加）"""
        if not self.driver:
            return 0
        
        try:
            all_handles = set(self.driver.window_handles)
            unknown_handles = all_handles - known_handles
            closed_count = 0
            
            for handle in unknown_handles:
                try:
                    self.driver.switch_to.window(handle)
                    # Glaspタブかどうか確認
                    if 'gemini.google.com' in self.driver.current_url:
                        self.driver.close()
                        closed_count += 1
                        log_message(f"未記録Glaspタブをクローズ", "INFO")
                except Exception as e:
                    log_message(f"タブクローズエラー: {e}", "WARNING")
            
            if closed_count > 0:
                log_message(f"未記録タブ {closed_count}個をクローズ完了", "SUCCESS")
            
            return closed_count
            
        except Exception as e:
            log_message(f"未記録タブクリーンアップエラー: {e}", "ERROR")
            return 0

    

    
    def get_status_summary(self) -> Dict:
        """現在の状態サマリーを取得"""
        return {
            'youtube_tabs': len(self.youtube_tabs),
            'glasp_tabs_total': len(self.glasp_tabs),
            'glasp_tabs_success': len([h for h in self.glasp_tabs if self.glasp_tabs[h]['status'] == 'success']),
            'glasp_tabs_failed': len([h for h in self.glasp_tabs if self.glasp_tabs[h]['status'] == 'failed']),
            'glasp_tabs_pending': len([h for h in self.glasp_tabs if self.glasp_tabs[h]['status'] == 'pending']),
            'success_videos': len(self.success_tabs)
        }


    def reset_batch(self):
        """バッチごとのリセット（YouTubeタブは保持）"""
        try:
            logger.info("TabTracker: バッチリセット開始")
            
            # Glaspタブと失敗タブの情報のみクリア
            self.glasp_tabs.clear()
            self.failed_tabs.clear()
            
            # YouTubeタブは保持（再利用のため）
            logger.info(f"TabTracker: YouTubeタブ {len(self.youtube_tabs)}個を保持")
            
            # リトライカウントもリセット
            self.retry_counts.clear()
            
            logger.info("TabTracker: バッチリセット完了")
            
        except Exception as e:
            logger.error(f"TabTracker: リセットエラー: {e}")



    def reset_all(self):
        """全タブ情報を完全リセット（新規追加）"""
        logger.info("TabTracker: 完全リセット開始")
        
        # すべてのトラッキング情報をクリア
        self.youtube_tabs.clear()
        self.glasp_tabs.clear()
        self.failed_tabs.clear()
        
        logger.info("TabTracker: 完全リセット完了")


# レート制限管理クラス
class RateLimiter:
    """スライディングウィンドウ方式のレート制限管理"""
    
    def __init__(self, window_minutes=60, max_requests=200):
        """
        window_minutes: 時間窓（デフォルト60分）
        max_requests: 安全マージンを持った上限（250より少なめ）
        """
        self.window = timedelta(minutes=window_minutes)
        self.max_requests = max_requests
        self.request_times = deque()
        self.session_start = datetime.now()
        self.total_session_requests = 0
        self.base_delay = 3.5  # デフォルト値を直接設定
        self.warning_threshold = 180  # デフォルト値を直接設定
        self.burst_size = 5  # デフォルト値を直接設定
        self.burst_interval = 10  # デフォルト値を直接設定
        self.current_burst = 0
        self.load_state()
    
    def load_state(self):
        """前回の状態を復元"""
        if os.path.exists(RATE_LIMIT_STATE_FILE):
            try:
                with open(RATE_LIMIT_STATE_FILE, 'r') as f:
                    state = json.load(f)
                
                # 最終リクエストから2時間以上経過？
                last_request = datetime.fromisoformat(state['last_request'])
                if datetime.now() - last_request > timedelta(hours=2):
                    # 安全にリセット
                    logger.info("2時間経過：レート制限カウンターリセット")
                else:
                    # 過去の履歴を復元
                    for timestamp_str in state.get('request_times', []):
                        timestamp = datetime.fromisoformat(timestamp_str)
                        if datetime.now() - timestamp < self.window:
                            self.request_times.append(timestamp)
                    logger.info(f"レート制限状態復元：既に{len(self.request_times)}件")
            except Exception as e:
                logger.warning(f"レート制限状態の復元失敗: {e}")
    
    def save_state(self):
        """状態を保存"""
        try:
            state = {
                'request_times': [t.isoformat() for t in list(self.request_times)[-50:]],  # 最新50件のみ保存
                'last_request': datetime.now().isoformat(),
                'total_session_requests': self.total_session_requests
            }
            with open(RATE_LIMIT_STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.warning(f"レート制限状態の保存失敗: {e}")
    
    def can_make_request(self):
        """リクエスト可能かチェック"""
        now = datetime.now()
        
        # 古いリクエストを削除（時間窓から外れたもの）
        while self.request_times and self.request_times[0] < now - self.window:
            self.request_times.popleft()
        
        # 現在の窓内のリクエスト数
        current_count = len(self.request_times)
        
        if current_count >= self.max_requests:
            # 最古のリクエストがいつ窓から外れるか計算
            wait_until = self.request_times[0] + self.window
            wait_seconds = max(0, (wait_until - now).total_seconds())
            return False, wait_seconds, current_count
        
        return True, 0, current_count
    
    def wait_if_needed(self):
        """必要に応じて待機"""
        can_request, wait_time, current_count = self.can_make_request()
        
        if not can_request:
            logger.warning(f"レート制限到達: {wait_time:.0f}秒待機が必要")
            return False, wait_time
        
        # 累積リクエスト数による段階的調整
        if current_count < 50:
            delay = self.base_delay  # 1.5秒
        elif current_count < 100:
            delay = 5  # 2秒
        elif current_count < 150:
            delay = 5  # 2.5秒
        elif current_count < self.warning_threshold:
            delay = 6.0  # 3秒（警戒域）
        else:
            delay = 8.0  # 5秒（危険域）
            logger.warning(f"⚠️ レート制限警戒域: {current_count}/{self.max_requests}")
        
        # バースト制御
        self.current_burst += 1
        if self.current_burst >= self.burst_size:
            delay += self.burst_interval
            self.current_burst = 0
            logger.info(f"バースト制御: {self.burst_interval}秒の追加待機")
        
        # ランダム性を追加（ボット検出回避）
        delay += random.uniform(0, 1)
        
        time.sleep(delay)
        return True, delay
    
    def record_request(self):
        """リクエストを記録"""
        self.request_times.append(datetime.now())
        self.total_session_requests += 1
        self.save_state()
    
    def get_current_load(self):
        """現在の負荷率を取得"""
        now = datetime.now()
        while self.request_times and self.request_times[0] < now - self.window:
            self.request_times.popleft()
        
        current_count = len(self.request_times)
        load_percentage = (current_count / self.max_requests) * 100
        return current_count, self.max_requests, load_percentage
    
    def get_status_message(self):
        """ステータスメッセージを取得"""
        current, max_req, load = self.get_current_load()
        
        if load < 50:
            status = "正常"
            emoji = "🟢"
        elif load < 75:
            status = "注意"
            emoji = "🟡"
        elif load < 90:
            status = "警告"
            emoji = "🟠"
        else:
            status = "危険"
            emoji = "🔴"
        
        return f"{emoji} レート制限: {current}/{max_req} ({load:.1f}%) - {status}"

# グローバル状態管理

class GlobalState:
    """グローバル状態管理（UI連携強化版）"""
    
    def __init__(self):
        """初期化"""
        # 処理状態
        self.processing = False
        self.cancel_flag = False
        self.skip_flag = False
        self.pause_flag = False
        
        # 進捗管理
        self.current_progress = 0
        self.total_items = 0
        self.current_batch = 0
        self.total_batches = 0
        
        # UI表示用詳細情報（新規追加）
        self.current_video_title = "待機中"
        self.detailed_status = "準備完了"
        
        # 処理結果
        self.results = []
        self.failed_items = []
        
        # タブトラッカー
        self.tab_tracker = None
        
        # レート制限
        self.rate_limiter = RateLimiter()
        
        # メモリ管理
        self.memory_warning_shown = False
        
        # コントロールウィンドウ参照
        self.control_window = None

        # サイレントモード
        self.silent_mode = False
        
        # 複数プレイリスト処理用
        self.current_playlist = None
        self.playlist_progress = {}
        self.completed_playlists = []
        
    def reset(self):
        """状態をリセット"""
        self.processing = False
        self.cancel_flag = False
        self.skip_flag = False
        self.current_progress = 0
        self.total_items = 0
        self.current_batch = 0
        self.total_batches = 0
        self.results = []
        self.failed_items = []
        self.current_video_title = "開始処理中..."
        self.detailed_status = "初期化中..."
        self.memory_warning_shown = False
    
    def update_status(self, message: str):
        """詳細ステータスを更新（ログ出力はしない軽量更新）"""
        self.detailed_status = message
    
    def set_current_video(self, title: str):
        """現在処理中の動画タイトルを更新"""
        self.current_video_title = title

    # ... (以下の既存メソッドはそのまま維持) ...
    def update_batch_progress(self, batch_idx: int, batch_total: int):
        self.current_batch = batch_idx
        self.total_batches = batch_total
    
    def get_batch_status(self) -> str:
        if self.total_batches > 0:
            return f"バッチ: {self.current_batch + 1}/{self.total_batches}"
        return ""
    
    def get_tab_tracker_status(self) -> str:
        if self.tab_tracker:
            status = self.tab_tracker.get_status_summary()
            return (f"タブ: YouTube={status['youtube_tabs']}, "
                   f"Glasp(OK={status['glasp_tabs_success']}/NG={status['glasp_tabs_failed']})")
        return ""

    def update_playlist_progress(self, playlist_name: str, status: str) -> None:
        if playlist_name:
            self.playlist_progress[playlist_name] = status
            if status == 'processing':
                self.current_playlist = playlist_name
            elif status in ['completed', 'failed']:
                if self.current_playlist == playlist_name:
                    pass 
            log_message(f"プレイリスト {playlist_name}: {status}", "INFO")

    def is_playlist_completed(self, playlist_name: str) -> bool:
        if playlist_name in self.completed_playlists: return True
        if playlist_name in self.playlist_progress:
            return self.playlist_progress[playlist_name] == 'completed'
        return False

    def mark_playlist_completed(self, playlist_name: str) -> None:
        if playlist_name not in self.completed_playlists:
            self.completed_playlists.append(playlist_name)
        self.playlist_progress[playlist_name] = 'completed'
        if self.current_playlist == playlist_name:
            self.current_playlist = None
        log_message(f"プレイリスト {playlist_name} を完了としてマーク", "SUCCESS")

# グローバルインスタンス（順序を修正）
config_manager = ConfigManager()  # 先にconfig_managerを作成
state = GlobalState()  # その後でstateを作成


# ========== 新規追加：AutoModeManagerのグローバルインスタンス ==========
auto_mode_manager = AutoModeManager()  # 自動モード管理インスタンス

# config_managerの設定値でRateLimiterを更新
state.rate_limiter.base_delay = config_manager.get('rate_limit.base_delay', 1.5)
state.rate_limiter.warning_threshold = config_manager.get('rate_limit.warning_threshold', 180)
state.rate_limiter.burst_size = config_manager.get('rate_limit.burst_size', 5)
state.rate_limiter.burst_interval = config_manager.get('rate_limit.burst_interval', 10)
state.rate_limiter.window = timedelta(minutes=config_manager.get('rate_limit.window_minutes', 60))
state.rate_limiter.max_requests = config_manager.get('rate_limit.max_requests_per_hour', 200)

# バッチサイズの設定
state.batch_size = config_manager.get('glasp.batch_size', DEFAULT_GLASP_BATCH_SIZE)


# ============================================================================
# SECTION 4: DATA MODELS
# ============================================================================



@dataclass
class VideoInfo:
    """動画情報データクラス（サムネイル・登録者数対応版）"""
    video_id: str
    url: str
    title: str = "Unknown"
    channel: str = "Unknown"
    playlist_order: int = 0
    is_current: bool = False
    duration: int = 0  # 秒
    view_count: int = 0
    upload_date: str = ""
    tab_handle: Optional[str] = None
    batch_index: int = -1  # バッチインデックス
    glasp_handles: List[str] = field(default_factory=list)  # 関連するGlaspタブハンドルのリスト
    # === 新規追加: サムネイルURL ===
    thumbnail_url: str = ""
    # === 新規追加: 登録者数 ===
    subscriber_count: str = ""
    
    def __post_init__(self):
        """初期化後の処理：サムネイルURLの自動生成"""
        # 動画IDが存在し、サムネイルURLがまだ設定されていない場合、自動生成する
        # mqdefault.jpg (320x180) は軽量でリスト表示に最適
        if self.video_id and not self.thumbnail_url:
            self.thumbnail_url = f"https://i.ytimg.com/vi/{self.video_id}/mqdefault.jpg"

    def to_dict(self) -> Dict:
        return {
            'video_id': self.video_id,
            'url': self.url,
            'title': self.title,
            'channel': self.channel,
            'playlist_order': self.playlist_order,
            'duration': self.duration,
            'view_count': self.view_count,
            'upload_date': self.upload_date,
            'batch_index': self.batch_index,
            'glasp_tab_count': len(self.glasp_handles),
            'thumbnail_url': self.thumbnail_url,
            'subscriber_count': getattr(self, 'subscriber_count', '')
        }
    
    def add_glasp_handle(self, handle: str):
        """Glaspタブハンドルを追加"""
        if handle not in self.glasp_handles:
            self.glasp_handles.append(handle)


@dataclass
class SummaryResult:
    """要約結果データクラス（Gemini URL対応版）"""
    video_info: VideoInfo
    success: bool
    summary: str = ""  # 整形済み要約（後方互換性のため維持）
    error_message: str = ""
    processing_time: float = 0.0
    model_used: str = ""
    cost: float = 0.0
    transcript_length: int = 0
    language: str = "ja"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    # 新規追加フィールド
    raw_transcript: str = ""
    raw_response: str = ""
    formatted_summary: str = ""
    batch_number: int = -1
    matched_by_title: bool = False
    glasp_handle_used: str = ""
    retry_count: int = 0
    skip_reason: str = ""
    # [20260808] 失敗の種別。'no_transcript'（字幕が無く要約できない＝再実行しても
    # 結果は変わらない）と 'failed'（Glasp起動失敗＝再実行で成功する見込みがある）を
    # 区別する。従来はどちらも同じ「Glasp起動失敗」として記録されていた。
    skip_kind: str = "failed"
    # === 新規追加: GeminiのチャットURL ===
    gemini_url: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'video': self.video_info.to_dict(),
            'success': self.success,
            'summary': self.formatted_summary if self.formatted_summary else self.summary,
            'error_message': self.error_message,
            'skip_kind': self.skip_kind,
            'processing_time': self.processing_time,
            'model_used': self.model_used,
            'cost': self.cost,
            'transcript_length': self.transcript_length,
            'language': self.language,
            'timestamp': self.timestamp,
            'batch_number': self.batch_number,
            'matched_by_title': self.matched_by_title,
            'retry_count': self.retry_count,
            'gemini_url': self.gemini_url,  # 辞書にも追加
            'has_raw_data': bool(self.raw_transcript or self.raw_response)
        }
    
    # ... (以下のメソッドは変更なし) ...
    def to_dict_full(self) -> Dict:
        # 簡略化のため省略しますが、ここにも 'gemini_url': self.gemini_url を追加してください
        d = self.to_dict()
        d.update({
            'raw_transcript': self.raw_transcript,
            'raw_response': self.raw_response,
            'glasp_handle_used': self.glasp_handle_used
        })
        return d

    def get_display_summary(self) -> str:
        if self.formatted_summary: return self.formatted_summary
        elif self.summary: return self.summary
        elif not self.success: return f"エラー: {self.error_message}"
        else: return "要約なし"
    
    def extract_keywords(self) -> List[str]:
        keywords = []
        summary_text = self.formatted_summary or self.summary
        if summary_text and 'キーワード' in summary_text:
            import re
            match = re.search(r'▪\s*キーワード[：:]\s*(.+?)(?:\n|▪|$)', summary_text)
            if match:
                keyword_str = match.group(1)
                keywords = [k.strip() for k in re.split('[,、，]', keyword_str) if k.strip()]
        return keywords
    
    def extract_title(self) -> str:
        summary_text = self.formatted_summary or self.summary
        if summary_text and 'タイトル' in summary_text:
            import re
            match = re.search(r'▪\s*タイトル[:：]\s*(.+?)(?:\n|▪|$)', summary_text)
            if match: return match.group(1).strip()
        return self.video_info.title
    
    def extract_conclusion(self) -> str:
        summary_text = self.formatted_summary or self.summary
        if summary_text and '結論' in summary_text:
            import re
            match = re.search(r'▪\s*結論[:：]\s*(.+?)(?:▪|$)', summary_text, re.DOTALL)
            if match: return match.group(1).strip()
        return ""



    def extract_main_points(self) -> List[Dict[str, str]]:
        """主なポイントを抽出して構造化（箇条書き直前行の後方参照・動的確定ロジック版）"""
        summary_text = self.formatted_summary or self.summary
        if not summary_text:
            return []
            
        import re
        points = []
        
        # セクションの開始位置を見つける
        section_start = -1
        markers = ["■ 主なポイント", "▪ 主なポイント", "■主なポイント", "まとめ：", "■ まとめ"]
        
        for marker in markers:
            pos = summary_text.find(marker)
            if pos != -1:
                section_start = pos + len(marker)
                break
                
        if section_start == -1:
            return []
            
        # 次のセクション（通常は要約終了）までのテキストを取得
        end_markers = ["■要約完了", "■ 要約完了", "■要約終了", "■ 要約終了", "</Transcript>"]
        section_end = len(summary_text)
        
        for marker in end_markers:
            pos = summary_text.find(marker, section_start)
            if pos != -1 and pos < section_end:
                section_end = pos
                
        section_text = summary_text[section_start:section_end].strip()
        
        if not section_text:
            return []
            
        # パースして構造化
        raw_lines = section_text.split('\n')
        # 空行を事前にすべて除去
        lines = [line.strip() for line in raw_lines if line.strip()]
        
        current_title = ""
        current_details = []
        
        for i, line in enumerate(lines):
            # 詳細行の判定 (・, •, ●, ○, -, *, ■ などで始まる行に対応)
            is_detail = False
            for marker in ['・', '•', '●', '○', '-', '*', '■']:
                if line.startswith(marker):
                    is_detail = True
                    break
                    
            if is_detail:
                if not current_title:
                    # 箇条書きブロックの開始：直前の行を見出しとして取得（後方参照）
                    if i > 0:
                        current_title = lines[i-1].replace('**', '').strip()
                    else:
                        current_title = "ポイント" # フォールバック
                current_details.append(line)
            else:
                # 箇条書きではない行
                # 次の行が箇条書きかどうかを先読み（Look-ahead）
                is_next_detail = False
                if i + 1 < len(lines):
                    next_line = lines[i+1]
                    for marker in ['・', '•', '●', '○', '-', '*', '■']:
                        if next_line.startswith(marker):
                            is_next_detail = True
                            break
                
                if is_next_detail:
                    # 次の行から新しい箇条書きブロックが始まるため、現在のブロックを保存して終了
                    if current_title and current_details:
                        points.append({
                            "title": current_title,
                            "details": "\n".join(current_details)
                        })
                        current_title = ""
                        current_details = []
                else:
                    # 次の行も箇条書きではない場合
                    if current_title:
                        # 既にブロック内であれば、詳細文の続き（ソフトな改行）とみなして追加
                        current_details.append(line)
                    # ブロック外（冒頭のイントロ文など）であれば何もしない（スキップ）
                
        # 最後のポイントを保存
        if current_title and current_details:
            points.append({
                "title": current_title,
                "details": "\n".join(current_details)
            })
            
        return points
    
    def calculate_quality_score(self) -> float:
        if not self.success: return 0.0
        score = 50.0
        summary_text = self.formatted_summary or self.summary
        if self.extract_title() != self.video_info.title: score += 5.0
        if self.extract_keywords(): score += 5.0
        if self.extract_conclusion(): score += 10.0
        if self.extract_main_points(): score += 10.0
        if self.processing_time > 0:
            if self.processing_time < 5: score += 10.0
            elif self.processing_time < 10: score += 7.0
            elif self.processing_time < 20: score += 5.0
            else: score += 2.0
        if summary_text:
            summary_len = len(summary_text)
            if 500 <= summary_len <= 2000: score += 10.0
            elif 300 <= summary_len < 500: score += 7.0
            elif 2000 < summary_len <= 3000: score += 7.0
            else: score += 3.0
        return min(100.0, score)


@dataclass
class ProcessConfig:
    """処理設定データクラス"""
    mode: str  # 'playlist', 'file', 'single', 'glasp', 'api'
    max_videos: int = DEFAULT_MAX_VIDEOS
    process_all: bool = False
    include_current: bool = True
    model: str = 'gemini-2.5-flash-lite'
    parallel_count: int = DEFAULT_PARALLEL_COUNT
    output_format: str = 'html'
    save_transcript: bool = False
    batch_size: int = DEFAULT_GLASP_BATCH_SIZE  # バッチサイズ
    batch_interval: int = 3  # バッチ間の待機時間
    cleanup_delay: int = 1  # クリーンアップ後の待機時間
    retry_delay: int = 2  # リトライ前の待機時間
    tab_wait_timeout: int = 20  # タブ応答待機時間（Slow Tab判定）
    browser_mode: int = 3  # 1:Chrome再起動, 2:タブ再起動, 3:タブ連続運転
    glasp_input_mode: str = 'js_click'  # 'js_click'(疑似クリック/現行) or 'trusted_mouse'(CDP本物クリック/検証用)
    headless: bool = False # ヘッドレスモード設定
    
    def validate(self) -> Tuple[bool, str]:
        """設定の妥当性を検証"""
        valid_modes = ['glasp', 'api', 'playlist', 'file', 'single']
        if self.mode not in valid_modes:
            return False, f"無効なモードです: {self.mode}"
            
        if self.max_videos < 1 or self.max_videos > MAX_VIDEOS_LIMIT:
            return False, f"動画数は1-{MAX_VIDEOS_LIMIT}の範囲で指定してください"
        if self.parallel_count < 1 or self.parallel_count > MAX_PARALLEL_COUNT:
            return False, f"並列数は1-{MAX_PARALLEL_COUNT}の範囲で指定してください"
        if self.batch_size < 1 or self.batch_size > 20:
            return False, "バッチサイズは1-20の範囲で指定してください"
            
        return True, ""
        
@dataclass
class PlaylistInfo:
    """プレイリスト情報データクラス"""
    playlist_id: str
    title: str = "Unknown Playlist"
    channel: str = "Unknown Channel"
    video_count: int = 0
    videos: List[VideoInfo] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'playlist_id': self.playlist_id,
            'title': self.title,
            'channel': self.channel,
            'video_count': self.video_count,
            'videos': [v.to_dict() for v in self.videos]
        }


        
# ============================================================================
# SECTION 5: UTILITY FUNCTIONS
# ============================================================================

def log_message(message: str, level: str = "INFO", silent_override: bool = False):
    """統一ログ出力関数"""
    if state.silent_mode and not silent_override:
        return
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    symbols = {
        "INFO": "📍",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "PROCESS": "🔄"
    }
    symbol = symbols.get(level, "📍")
    
    formatted_message = f"[{timestamp}] {symbol} {message}"
    
    # ログレベルに応じた出力
    if level == "ERROR":
        logger.error(message)
    elif level == "WARNING":
        logger.warning(message)
    else:
        logger.info(message)
    
    # コンソール出力
    print(formatted_message)
    
    return formatted_message

def perf_log(metric_name: str, start_time: float, **fields):
    """性能計測ログを固定形式で出力する（処理ロジックには影響しない）"""
    try:
        elapsed = time.time() - start_time
        field_text = "|".join([f"{key}={value}" for key, value in fields.items()])
        suffix = f"|{field_text}" if field_text else ""
        log_message(f"PERF|{metric_name}|sec={elapsed:.3f}{suffix}", "INFO")
    except Exception as e:
        log_message(f"PERF_LOG_ERROR|{metric_name}|{e}", "WARNING")

def measure_log(line: str):
    """
    [計測] Glasp起動の判定内訳を、実行をまたいで蓄積するための追記専用ログ。
    通常ログ（youtube_summary.log）は実行ごとに作り直されるため、そちらに出すと
    02:00/05:00/11:30/20:00 の各回の記録が次の回で消えてしまう。
    集計専用であり、処理の分岐には一切使用しない。
    """
    log_message(line, "INFO")
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(MEASURE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{stamp}\t{line}\n")
    except Exception as e:
        log_message(f"GLASP_MEASURE_ERROR|stage=measure_log_write|error={e}", "WARNING")

def auto_askyesno(title: str, message: str, default: bool = True) -> bool:
    """askyesnoの自動化ラッパー
    
    自動モードが有効な場合、指定秒数後に自動でdefault値を返す。
    無効な場合は通常のmessageboxを表示。
    
    Args:
        title: ダイアログタイトル
        message: メッセージ内容
        default: 自動モード時のデフォルト戻り値
        
    Returns:
        bool: ユーザーの選択またはデフォルト値
    """
    if auto_mode_manager.is_enabled():
        log_message(f"🤖 Auto-YES: {title} - {message[:50]}...", "INFO")
        return default
    else:
        return messagebox.askyesno(title, message)


def auto_askokcancel(title: str, message: str, default: bool = True) -> bool:
    """askokcancelの自動化ラッパー
    
    Args:
        title: ダイアログタイトル
        message: メッセージ内容
        default: 自動モード時のデフォルト戻り値
        
    Returns:
        bool: ユーザーの選択またはデフォルト値
    """
    if auto_mode_manager.is_enabled():
        log_message(f"🤖 Auto-OK: {title} - {message[:50]}...", "INFO")
        return default
    else:
        return messagebox.askokcancel(title, message)


def auto_showinfo(title: str, message: str):
    """showinfoの自動化ラッパー
    
    自動モードが有効な場合、ログ出力のみで即座にリターン。
    無効な場合は通常のmessageboxを表示。
    
    Args:
        title: ダイアログタイトル
        message: メッセージ内容
    """
    if auto_mode_manager.is_enabled():
        log_message(f"🤖 Auto-INFO: {title} - {message[:100]}...", "INFO")
    else:
        messagebox.showinfo(title, message)


def auto_showwarning(title: str, message: str):
    """showwarningの自動化ラッパー
    
    Args:
        title: ダイアログタイトル
        message: メッセージ内容
    """
    if auto_mode_manager.is_enabled():
        log_message(f"🤖 Auto-WARNING: {title} - {message[:100]}...", "WARNING")
    else:
        messagebox.showwarning(title, message)


def auto_showerror(title: str, message: str):
    """showerrorの自動化ラッパー
    
    Args:
        title: ダイアログタイトル
        message: メッセージ内容
    """
    if auto_mode_manager.is_enabled():
        log_message(f"🤖 Auto-ERROR: {title} - {message[:100]}...", "ERROR")
        # エラーでも自動モードでは継続（致命的エラーは別途処理）
    else:
        messagebox.showerror(title, message)


def extract_video_id(url: str) -> Optional[str]:
    """YouTube URLから動画IDを抽出"""
    if not url:
        return None
    
    # 既に動画IDの場合
    if len(url) == 11 and not url.startswith('http'):
        return url
    
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    # URLパースでの抽出
    try:
        parsed = urlparse(url)
        if 'youtube.com' in parsed.netloc:
            params = parse_qs(parsed.query)
            return params.get('v', [None])[0]
        elif 'youtu.be' in parsed.netloc:
            return parsed.path[1:].split('?')[0]
    except:
        pass
    
    return None

def extract_playlist_id(url: str) -> Optional[str]:
    """YouTube URLからプレイリストIDを抽出"""
    if not url:
        return None
    
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return params.get('list', [None])[0]
    except:
        return None

def format_duration(seconds: int) -> str:
    """秒数を時:分:秒形式に変換"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"

def parse_duration_text(text: str) -> int:
    """
    YouTubeプレイリストのDOM上の再生時間文字列を秒数(int)に変換する。
    対応形式: 'H:MM:SS' / 'M:SS'
    異常入力 ('LIVE', 'PREMIERING', '', '4K' 等) は全て 0 を返す。
    [Audit指摘対応] len(parts)==1 の場合も明示的に return 0 で保護済み。
    VERSION: 20260602_01_01
    """
    if not text:
        return 0
    parts = text.strip().split(':')
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except (ValueError, IndexError):
            return 0
    elif len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            return 0
    else:
        # len==1 または 4以上: 'LIVE' / 'PREMIERING NOW' / 空 等
        return 0


def estimate_cost(text_length: int, model_key: str) -> float:
    """テキスト長とモデルからコストを推定"""
    if model_key not in MODEL_CONFIG:
        return 0.0
    
    model = MODEL_CONFIG[model_key]
    # 簡易的なトークン数推定（日本語の場合）
    estimated_tokens = text_length / 2.5
    
    input_cost = (estimated_tokens / 1000) * model['cost_per_1k_input']
    # 出力は入力の約1/3と仮定
    output_cost = (estimated_tokens / 3000) * model['cost_per_1k_output']
    
    return input_cost + output_cost


def clean_filename(filename: str) -> str:
    """ファイル名として使用可能な文字列に変換"""
    import re
    
    # Windowsで禁止されている文字を削除
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    cleaned = re.sub(invalid_chars, '', filename)
    
    # 空白を_に置換
    cleaned = cleaned.replace(' ', '_')
    
    # 連続する_を1つに
    cleaned = re.sub(r'_{2,}', '_', cleaned)
    
    # 前後の空白・記号を削除
    cleaned = cleaned.strip('._- ')
    
    # 空文字になった場合のフォールバック
    if not cleaned:
        return 'summary'
    
    # 最大長を制限（15文字）
    return cleaned[:15]




def create_youtube_url_with_no_autoplay(url: str) -> str:
    """YouTube URLに自動再生無効パラメータを追加"""
    if "youtube.com/watch" in url:
        if "autoplay=" in url:
            url = re.sub(r'autoplay=\d+', 'autoplay=0', url)
        else:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}autoplay=0"
        
        if "start=" not in url:
            url = f"{url}&start=0"
    
    return url


def smart_sleep(seconds: float, check_interval: float = 0.1) -> bool:
    """
    ユーザー入力を監視しながら待機する（ブロッキング回避版スリープ）
    
    Args:
        seconds: 待機する総秒数
        check_interval: 入力を確認する間隔（秒）
        
    Returns:
        bool: 待機が完了したらTrue、キャンセル/スキップ等の割り込みがあればFalse
    """
    end_time = time.time() + seconds
    
    while time.time() < end_time:
        # ユーザー入力（キャンセル/スキップ）をチェック
        status = check_user_input()
        if status != 'continue':
            return False
            
        # 残り時間とインターバルの短い方を待つ
        remaining = end_time - time.time()
        if remaining <= 0:
            break
            
        sleep_time = min(remaining, check_interval)
        time.sleep(sleep_time)
        
    return True

def check_user_input() -> str:
    """ユーザー入力をチェック（ControlWindow連携強化）"""
    # ControlWindowがある場合はそのUIも更新
    # ★★★ 修正箇所: 危険な処理スレッドからのupdate()呼び出しを削除 ★★★
    if state.control_window:
        try:
            if hasattr(state.control_window, 'winfo_exists') and state.control_window.winfo_exists(): pass
        except tk.TclError:
            # ウィンドウが閉じられた場合
            state.cancel_flag = True
            state.control_window = None
    
    # フラグチェック
    if state.cancel_flag:
        return 'cancel'
    if state.skip_flag:
        return 'skip'
    
    return 'continue'


def set_silent_mode(enabled: bool):
    """サイレントモードの切り替え"""
    state.silent_mode = enabled
    if not enabled:
        log_message("ログ出力を再開しました", "INFO")

def get_optimal_parallel_count(total_videos: int) -> int:
    """処理数に応じた最適な並列数を計算"""
    if total_videos <= 5:
        return min(2, total_videos)  # 小規模：最大2並列
    elif total_videos <= 10:
        return 2  # 中規模：2並列
    else:
        return 1  # 大規模：順次処理（安全重視）

def generate_playlist_url(playlist_id: str) -> str:
    """プレイリストIDからYouTube URLを生成
    
    Args:
        playlist_id: YouTubeプレイリストID
        
    Returns:
        str: 完全なプレイリストURL
    """
    if not playlist_id:
        return ""
    
    # プレイリストIDが既にURL形式の場合はそのまま返す
    if playlist_id.startswith('http'):
        return playlist_id
    
    # プレイリストIDからURLを生成
    base_url = "https://www.youtube.com/playlist?list="
    return base_url + playlist_id

def format_playlist_name(playlist_name: str) -> str:
    """プレイリスト名を表示用にフォーマット
    
    Args:
        playlist_name: プレイリスト名（S, A, B, N, M, P+, L）
        
    Returns:
        str: フォーマット済みの表示名
    """
    # プレイリスト名のマッピング（必要に応じて拡張可能）
    name_mapping = {
        "V":  "プレイリストV",
        "S":  "プレイリストS",
        "A":  "プレイリストA",
        "B":  "プレイリストB",
        "N":  "プレイリストN",
        "M":  "プレイリストM",
        "P+": "プレイリストP+",
        "L":  "プレイリストL",
    }
    
    # マッピングがある場合は変換、なければそのまま返す
    return name_mapping.get(playlist_name, playlist_name)


# ============================================================================
# SECTION 6: BROWSER MANAGEMENT
# ============================================================================
import socket
import subprocess


class BrowserManager:
    """WebDriverのライフサイクルとタブ管理を担当するクラス"""
    
    def __init__(self):
        self.driver = None
        self.main_window_handle = None
        # [0125.02] --user-data-dirを完全に固定化し、常に同じプロファイルを使い回す
        # これにより、拡張機能の設定やログイン状態が維持される
        # self.user_data_dir = os.path.join(os.environ['USERPROFILE'], r"Documents\ChromeDebugProfile")
        self.user_data_dir = os.path.join(os.environ['LOCALAPPDATA'], "ChromeDebugProfile_20260725")


    def _try_attach_existing_chrome(self, debug_port: int) -> bool:
        """
        [20260806] Youtube_List_Setup系スクリプト（プレイリスト登録/削除）と同じ方式で、
        既にデバッグモードで起動しているChrome（run_youtube_summary_auto.bat等が用意したもの）
        へ接続を試みる。成功すればkill_target_chrome_processes()や新規起動を一切行わず、
        ログイン状態・拡張機能設定を保ったまま利用できる。
        ポートが開いていない、または接続後の生存確認に失敗した場合はFalseを返し、
        呼び出し元は従来の新規起動フローへフォールバックする。
        """
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.common.exceptions import WebDriverException, InvalidSessionIdException

        if not check_chrome_debug_port(debug_port):
            log_message(f"デバッグポート{debug_port}で待ち受けているChromeが見つかりません（新規起動へフォールバック）", "INFO")
            return False

        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"localhost:{debug_port}")
            # [20260807] 旧・chromedriver起動方式では options.page_load_strategy='eager' を
            # 指定していたが、アタッチ方式に統一した際に抜け落ちていた。'normal'のままだと
            # driver.get()がGeminiのようなストリーミング系ページで完全ロードを待ち続け、
            # 余計な待ちやタイムアウトの原因になるため復元する。
            options.page_load_strategy = 'eager'
            # [20260807] 新規起動側と同じ理由でChromeDriverManager().install()を使い、
            # 接続先Chromeとバージョンが合ったchromedriverを明示的に取得する。
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30.0)
            driver.implicitly_wait(5.0)

            # 生存確認（新規起動時と同じ基準）
            handles = driver.window_handles
            if not handles:
                raise WebDriverException("既存Chrome接続後の生存確認失敗: window_handles が空です")
            main_handle = driver.current_window_handle
            if not main_handle:
                raise WebDriverException("既存Chrome接続後の生存確認失敗: current_window_handle が空です")

            self.driver = driver
            self.main_window_handle = main_handle
            log_message(f"✅ 既存のデバッグ用Chrome(ポート{debug_port})に接続しました（新規起動をスキップ）", "SUCCESS")
            return True

        except (InvalidSessionIdException, WebDriverException, Exception) as e:
            log_message(f"既存Chromeへの接続に失敗しました（新規起動へフォールバック）: {e}", "WARNING")
            return False

    def init_chrome_driver(self, debug_mode: bool = True, is_auto_mode: bool = False, force_new_session: bool = False) -> bool:
        """Chrome Driverの初期化（タイムアウトとリトライ、ポート競合対策付き）"""
        profile_name = os.path.basename(self.user_data_dir)
        debug_port = config_manager.get('glasp.chrome_debug_port', 9222)

        # [20260806] バッチファイルが用意した既存のデバッグ用Chromeへの接続を優先する。
        # 従来は無条件でkill_target_chrome_processes()して自前のChromeを新規起動していたため、
        # ログイン済み・安定動作中のChromeを毎回強制終了してしまい、ログイン状態のリセットや
        # Google自動操作検知の誘発につながっていた（プレイリスト登録/削除スクリプトは
        # 既存Chromeへの接続方式のため、この問題が起きていなかった）。
        # force_new_session=True（force_restart_browser経由）の場合は、呼び出し元が
        # 既にプロセスをkillした直後なので、接続を試みず従来通り新規起動する。
        if not force_new_session:
            if self._try_attach_existing_chrome(debug_port):
                return True

        # [0210.02] ChromeDebugProfileのロックファイル解除（物理）
        def cleanup_lock_files():
            lock_file = os.path.join(self.user_data_dir, "SingletonLock")
            try:
                if os.path.exists(lock_file):
                    os.remove(lock_file)
                    log_message(f"🧹 ロックファイルを削除しました: {lock_file}", "INFO")
            except Exception as e:
                log_message(f"⚠️ ロックファイル削除失敗: {e}", "WARNING")

        # [20260807] Chrome実行ファイルパスの解決。Youtube_List_Setup系・各バッチ
        # ファイルと同じ2箇所を確認する。
        def resolve_chrome_path():
            candidates = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            for candidate in candidates:
                if os.path.exists(candidate):
                    return candidate
            return candidates[0]

        max_retries = 3 if not is_auto_mode else 5

        # [20260807] 従来はwebdriver.Chrome(options=...)に--user-data-dirを渡し、
        # chromedriver自身にChromeプロセスを起動させていたが、この方式はChrome
        # 151系で「unknown error: unable to discover open window in chrome」を
        # 高確率で起こすことが実機ログで確認された。安定動作しているYoutube_List_Setup
        # 系の登録コードは、常にChromeを素のsubprocess.Popenで別プロセスとして起動し、
        # デバッグポートが応答するようになってからdebuggerAddressで後付けアタッチする
        # 方式を使っており、この方式では同エラーが発生していない。
        # ここでも同じ方式（起動はsubprocess、接続は_try_attach_existing_chrome()）に
        # 統一する。
        for attempt in range(max_retries):
            try:
                if self.driver:
                    try:
                        self.driver.quit()
                    except Exception as e:
                        log_message(f"既存Driverのquit()に失敗しましたが参照を破棄します: {e}", "WARNING")
                    finally:
                        self.driver = None
                        self.main_window_handle = None

                if platform.system() != "Windows":
                    raise Exception("この新規起動フォールバックはWindows専用です")

                # 自動モード、またはリトライ時は既存プロセスを終了してから起動し直す
                if is_auto_mode or attempt > 0:
                    log_message("🤖 クリーンな環境を作るため対象Chromeを終了します", "WARNING")
                    kill_target_chrome_processes(profile_name)  # [20260407.01] 個別キル
                    time.sleep(1)

                cleanup_lock_files()
                log_message(f"Chrome Driver初期化中 (Attempt {attempt + 1}/{max_retries})", "INFO")

                chrome_path = resolve_chrome_path()
                chrome_args = [
                    chrome_path,
                    f"--remote-debugging-port={debug_port}",
                    f"--user-data-dir={self.user_data_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    # [20260725.01] Googleの自動操作ブラウザ検知（サインイン拒否）対策
                    "--disable-blink-features=AutomationControlled",
                    # [20260806] Chromeをkill -9相当で強制終了した直後の起動時に出る
                    # 「ページを復元しますか？」クラッシュ復元ダイアログを抑制する。
                    "--disable-session-crashed-bubble",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    # [20260807] 旧・chromedriver起動方式では指定していたが、subprocess起動へ
                    # 移行した際に抜け落ちていたフラグ群。翻訳バーや既定アプリのUIが混ざると
                    # document.body.innerTextの末尾が変わり、要約終了タグの検出を妨げうる。
                    "--disable-features=Translate",
                    "--metrics-recording-only",
                    "--disable-default-apps",
                    "--no-proxy-server",
                    # [20260807] 画面OFF・ウィンドウ非表示時でも描画を維持する（登録コードと同じ）。
                    "--disable-backgrounding-occluded-windows",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    # [20260807] レイアウトを固定し、ウィンドウ幅によってGeminiのUI構成
                    # （＝innerTextに含まれる文字列）が変わらないようにする。登録コードと同じ。
                    "--window-size=1920,1080",
                    "--force-device-scale-factor=1",
                ]
                subprocess.Popen(chrome_args, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

                # デバッグポートが応答するまで待機
                port_ready = False
                for _ in range(15):
                    time.sleep(2)
                    if check_chrome_debug_port(debug_port):
                        port_ready = True
                        break

                if not port_ready:
                    raise Exception(f"Chrome起動後、デバッグポート{debug_port}が応答しませんでした")

                time.sleep(2)  # 安定化待機

                if self._try_attach_existing_chrome(debug_port):
                    if debug_mode:
                        log_message("Chrome Driver (Debug Profile) を起動しました（生存確認OK）", "SUCCESS")
                    return True

                raise Exception("新規起動したChromeへの接続(attach)に失敗しました")

            except Exception as e:
                log_message(f"Chrome Driver初期化エラー (Attempt {attempt + 1}): {e}", "ERROR")
                try:
                    if self.driver:
                        self.driver.quit()
                except:
                    pass
                self.driver = None
                self.main_window_handle = None
                if platform.system() == "Windows":
                    kill_target_chrome_processes(profile_name)
                time.sleep(3)

        return False

    def force_restart_browser(self, is_auto_mode: bool = False) -> bool:
        """ブラウザを強制再起動する"""
        log_message("🔄 ブラウザの強制再起動シーケンスを開始します", "WARNING")
        profile_name = os.path.basename(self.user_data_dir)
        
        try:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception as e:
                    log_message(f"通常のquit()に失敗しました (無視します): {e}", "DEBUG")
                finally:
                    self.driver = None
                    self.main_window_handle = None
            
            if platform.system() == "Windows":
                log_message("OSコマンドでChrome/Chromedriverプロセスを強制終了中...", "INFO")
                kill_target_chrome_processes(profile_name)  # [20260407.01] 個別キル
                
            time.sleep(5) 

            log_message("🔄 新しいセッションでブラウザを再起動します...", "INFO")
            success = self.init_chrome_driver(debug_mode=True, is_auto_mode=is_auto_mode, force_new_session=True)
            
            if success:
                log_message("✅ ブラウザの強制再起動に成功しました", "SUCCESS")
            else:
                log_message("❌ ブラウザの強制再起動に失敗しました", "ERROR")
                
            return success
            
        except Exception as e:
            log_message(f"❌ 強制再起動シーケンス中に致命的なエラー: {e}", "ERROR")
            self.driver = None
            self.main_window_handle = None
            return False

    def cleanup(self):
        """リソースの解放"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
        
        if platform.system() == "Windows":
             kill_target_chrome_processes()  # [20260407.01] 個別キル

    # 互換性のためのラッパー
    def switch_to_tab(self, handle):
        try:
            self.driver.switch_to.window(handle)
            return True
        except:
            return False

    def switch_or_create_tab(self, url: str) -> bool:
        return self.navigate_with_cleanup(self.main_window_handle, url)

    def navigate_to_url(self, handle: str, url: str) -> bool:
        try:
            self.driver.switch_to.window(handle)
            self.driver.get(url)
            return True
        except Exception as e:
            log_message(f"URLナビゲーションエラー: {e}", "ERROR")
            return False

    def close_tab(self, handle):
        try:
            self.driver.switch_to.window(handle)
            self.driver.close()
            # main_window_handleを更新
            if self.driver.window_handles:
                self.main_window_handle = self.driver.window_handles[0]
                self.driver.switch_to.window(self.main_window_handle)
        except:
            pass

    def find_youtube_playlist_tabs(self, skip_preview_tabs: bool = False) -> List[Tuple[str, str, str]]:
        tabs = []
        if not self.driver: return tabs
        
        try:
            original = self.driver.current_window_handle
            handles = self.driver.window_handles
            
            for handle in handles:
                try:
                    self.driver.switch_to.window(handle)
                    url = self.driver.current_url
                    title = self.driver.title
                    
                    if "youtube.com" in url and "list=" in url:
                        if skip_preview_tabs and "youtube.com/watch" in url:
                            continue
                        tabs.append((handle, title, url))
                except:
                    continue
                    
            try:
                self.driver.switch_to.window(original)
            except:
                if handles: self.driver.switch_to.window(handles[0])
        except:
            pass
            
        return tabs



    def create_new_tab(self, url): 
        if self.driver: 
            self.driver.switch_to.new_window('tab')
            self.driver.get(url)
            

    def navigate_with_cleanup(self, handle, url):
        try:
            self.driver.switch_to.window(handle)
            self.driver.get(url)
            self.main_window_handle = handle
            return True
        except Exception as e:
            log_message(f"タブ再利用ナビゲーションに失敗: {e}", "ERROR")
            return False


    def get_memory_usage(self) -> float:
        """
        [VERSION 20260414.03] 正しいクラス内に再配置
        Chrome（およびその子プロセス）のメモリ使用量(MB)を安全に取得する。
        """
        try:
            import psutil
            total_memory_mb = 0.0
            
            # 現在のPythonプロセスのすべての子プロセス（Chrome等）を走査
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            
            for child in children:
                try:
                    if "chrome" in child.name().lower():
                        mem_info = child.memory_info()
                        total_memory_mb += mem_info.rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
                    
            return total_memory_mb
        except Exception as e:
            log_message(f"メモリ取得エラー(非FATAL): {e}", "DEBUG")
            return 0.0
            
# ============================================================================
# SECTION 7: YOUTUBE OPERATIONS
# ============================================================================

class YouTubeHandler:
    """YouTube操作ハンドラー"""
    
    def __init__(self, driver: Optional[webdriver.Chrome] = None):
        self.driver = driver



    def get_playlist_videos_selenium(self, playlist_url: str, 
                                        max_count: int = 20,
                                        include_current: bool = True,
                                        process_all: bool = False) -> List[VideoInfo]:
            """Seleniumを使用してプレイリストから動画情報を取得（無限スクロール対応・自動復旧版）"""
            if not self.driver:
                log_message("WebDriverが初期化されていません", "ERROR")
                return []
            
            try:
                if hasattr(self.driver.command_executor, '_client_config'):
                    self.driver.command_executor._client_config.timeout = 60.0
                elif hasattr(self.driver.command_executor, 'set_timeout'):
                    self.driver.command_executor.set_timeout(60.0)
                log_message("通信タイムアウトを一時的に60秒に延長しました", "DEBUG")
            except Exception as e:
                log_message(f"タイムアウト設定の変更に失敗（続行します）: {e}", "WARNING")

            videos = []
            
            try:
                current_url = self.driver.current_url
                current_video_id = extract_video_id(current_url)
                
                playlist_id = extract_playlist_id(playlist_url)
                if not playlist_id:
                    log_message("プレイリストIDが取得できません", "ERROR")
                    return []
                
                playlist_page_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                
                if playlist_id in current_url and "playlist" in current_url:
                    log_message(f"既存のプレイリストページを使用: {playlist_id}", "INFO")
                else:
                    log_message(f"プレイリストページに移動: {playlist_page_url}", "PROCESS")
                    # [20260414.03] 通信切断エラー時の自動リロードロジック
                    for nav_attempt in range(3):
                        try:
                            self.driver.get(playlist_page_url)
                            time.sleep(2)
                            
                            # エラー画面検知 (chrome-error:// または ERR_CONNECTION_CLOSED)
                            current_u = self.driver.current_url
                            page_src = self.driver.page_source.lower()
                            
                            if "chrome-error://" in current_u or "err_connection_closed" in page_src or "このサイトにアクセスできません" in page_src:
                                log_message(f"⚠️ 通信切断エラーを検知しました (試行 {nav_attempt+1}/3)。5秒後に自動リロードします...", "WARNING")
                                time.sleep(5)
                                continue
                                
                            break # 正常な場合はループを抜ける
                        except Exception as nav_e:
                            log_message(f"⚠️ ページ移動中にエラー発生 (試行 {nav_attempt+1}/3): {nav_e}", "WARNING")
                            time.sleep(5)
                
                try:
                    log_message("ページの状態を確認中 (最大60秒待機)...", "PROCESS")
                    
                    WebDriverWait(self.driver, 60).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    
                    empty_text = "この再生リストには動画がありません"
                    WebDriverWait(self.driver, 60).until(
                        lambda d: d.find_elements(By.TAG_NAME, "ytd-playlist-video-renderer") or \
                                  d.find_elements(By.ID, "video-title") or \
                                  d.find_elements(By.XPATH, f"//*[text()='{empty_text}']") or \
                                  d.find_elements(By.TAG_NAME, "ytd-message-renderer") or \
                                  d.find_elements(By.CSS_SELECTOR, "#contents > ytd-alert-renderer")
                    )
                    
                    if process_all:
                        log_message("全件取得モード: 動画リストをスクロールして読み込み中...", "PROCESS")
                        last_count = 0
                        no_change_count = 0
                        
                        while True:
                            self.driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
                            time.sleep(2.0)
                            
                            current_count = self.driver.execute_script("return document.querySelectorAll('ytd-playlist-video-renderer').length")
                            
                            if current_count == last_count:
                                no_change_count += 1
                                if no_change_count >= 3:
                                    break
                            else:
                                no_change_count = 0
                                log_message(f"  ...読み込み済み: {current_count}件", "DEBUG")
                            
                            last_count = current_count
                            
                            if current_count >= MAX_VIDEOS_LIMIT:
                                log_message(f"上限({MAX_VIDEOS_LIMIT}件)に達したためスクロールを中断します", "WARNING")
                                break

                    time.sleep(3)
                    
                    empty_elements = self.driver.find_elements(By.XPATH, f"//*[text()='{empty_text}']")
                    if empty_elements:
                        time.sleep(2)
                        has_videos_check = self.driver.find_elements(By.TAG_NAME, "ytd-playlist-video-renderer")
                        if not has_videos_check:
                            log_message(f"「{empty_text}」を検出しました。即時スキップします。", "WARNING")
                            return [] 

                    has_videos = self.driver.find_elements(By.TAG_NAME, "ytd-playlist-video-renderer") or \
                                 self.driver.find_elements(By.ID, "video-title")
                    
                    if has_videos:
                        log_message("動画リストの読み込みを確認しました", "SUCCESS")
                    else:
                        log_message("プレイリストが空、または利用不可のメッセージを確認しました", "WARNING")
                    
                except TimeoutException:
                    log_message("⚠️ ページの読み込みがタイムアウトしました（60秒）。要素が検出できません。", "WARNING")
                
                script = f"""
                const items = document.querySelectorAll('ytd-playlist-video-renderer');
                const results = [];
                const currentVideoId = '{current_video_id}';
                let currentIndex = 0;
                let foundCurrent = false;
                
                for (let i = 0; i < items.length; i++) {{
                    const item = items[i];
                    const aTag = item.querySelector('#video-title');
                    if (!aTag) continue;
                    
                    const href = aTag.href;
                    const urlParams = new URLSearchParams(new URL(href).search);
                    const videoId = urlParams.get('v');
                    
                    if (videoId === currentVideoId) {{
                        currentIndex = i;
                        foundCurrent = true;
                        break;
                    }}
                }}
                
                let startIndex = foundCurrent ? currentIndex : 0;
                if (foundCurrent && !{str(include_current).lower()}) {{
                    startIndex = currentIndex + 1;
                }}
                
                for (let i = startIndex; i < items.length; i++) {{
                    const item = items[i];
                    const aTag = item.querySelector('#video-title');
                    if (!aTag) continue;
                    
                    const href = aTag.href;
                    const title = aTag.title || aTag.textContent || 'タイトル不明';
                    
                    let channel = 'Unknown';
                    try {{
                        const channelElement = item.querySelector('#channel-name a');
                        if (channelElement) {{
                            channel = channelElement.textContent.trim();
                        }}
                    }} catch(e) {{}}
                    
                    const urlParams = new URLSearchParams(new URL(href).search);
                    const videoId = urlParams.get('v');
                    
                    const isCurrent = (videoId === currentVideoId);
                    
                    if (videoId) {{
                        let durationText = '';
                        try {{
                            const durEl = item.querySelector(
                                'ytd-thumbnail-overlay-time-status-renderer span#text, ' +
                                '#overlays ytd-thumbnail-overlay-time-status-renderer span'
                            );
                            if (durEl) {{
                                durationText = durEl.textContent.trim();
                            }}
                        }} catch(e) {{}}

                        results.push({{
                            video_id: videoId,
                            url: href,
                            title: title,
                            channel: channel,
                            playlist_order: i,
                            is_current: isCurrent,
                            actual_index: i - startIndex,
                            duration_text: durationText
                        }});
                    }}
                }}
                
                return {{
                    results: results,
                    found_current: foundCurrent,
                    current_index: currentIndex,
                    start_index: startIndex
                }};
                """
                
                response = self.driver.execute_script(script)
                video_data = response.get('results', [])
                found_current = response.get('found_current', False)
                current_index = response.get('current_index', 0)
                
                if not found_current and current_video_id:
                    if len(video_data) > 0:
                        log_message(f"警告: 現在の動画がプレイリストに見つかりません。先頭から処理します。", "WARNING")
                elif len(video_data) > 0:
                    log_message(f"プレイリスト内の位置 {current_index + 1} から処理開始", "INFO")
                
                effective_max = len(video_data) if process_all else min(max_count, len(video_data))
                
                for i, data in enumerate(video_data[:effective_max]):
                    video = VideoInfo(
                        video_id=data['video_id'],
                        url=data['url'],
                        title=data['title'],
                        channel=data['channel'],
                        playlist_order=data['playlist_order'],
                        is_current=data.get('is_current', False),
                        duration=parse_duration_text(data.get('duration_text', ''))
                    )
                    videos.append(video)
                    
                    if i < 5 or i % 50 == 0 or i == effective_max - 1:
                        if video.is_current:
                            log_message(f"動画追加 ({i+1}/{effective_max}): [現在] {video.title[:50]}...", "SUCCESS")
                        else:
                            log_message(f"動画追加 ({i+1}/{effective_max}): {video.title[:50]}...", "SUCCESS")
                
                log_message(f"プレイリストから{len(videos)}個の動画を取得", "SUCCESS")
                
            except Exception as e:
                log_message(f"プレイリスト取得エラー: {e}", "ERROR")
                
            finally:
                try:
                    if hasattr(self.driver.command_executor, '_client_config'):
                        self.driver.command_executor._client_config.timeout = 60.0
                    elif hasattr(self.driver.command_executor, 'set_timeout'):
                        self.driver.command_executor.set_timeout(60.0)
                    log_message("通信タイムアウトを標準(60秒)に戻しました", "DEBUG")
                except Exception as e:
                    log_message(f"タイムアウト設定の復元に失敗: {e}", "WARNING")
            
            return videos


    def get_transcript(self, video_id: str, 
                      preferred_languages: List[str] = ['ja', 'en']) -> Tuple[Optional[str], str]:
        """動画のトランスクリプトを取得（修正版）"""
        
        log_message(f"[DEBUG] トランスクリプト取得開始: video_id={video_id}", "INFO")
        
        # レート制限チェック
        can_proceed, wait_time = state.rate_limiter.wait_if_needed()
        if not can_proceed:
            log_message(f"レート制限により{wait_time:.0f}秒待機が必要です", "ERROR")
            return None, ''
        
        try:
            # インスタンスベースAPIの使用（v1.2.0以降必須）
            log_message("[DEBUG] インスタンスベースAPIで試行", "INFO")
            api = YouTubeTranscriptApi()
            
            # fetch()メソッドを使用（新API）
            for lang in preferred_languages:
                try:
                    log_message(f"[DEBUG] 言語{lang}で取得試行", "INFO")
                    
                    # fetch()はFetchedTranscriptオブジェクトを返す
                    transcript = api.fetch(video_id, languages=[lang])
                    
                    # FetchedTranscriptはイテレート可能
                    text_parts = []
                    for item in transcript:
                        # 属性アクセス（辞書アクセスではない）
                        if hasattr(item, 'text'):
                            text_parts.append(item.text)
                        else:
                            # フォールバック（念のため）
                            text_parts.append(str(item))
                    
                    text = " ".join(text_parts)
                    
                    # レート制限カウンターを記録
                    state.rate_limiter.record_request()
                    
                    log_message(f"[DEBUG] 取得成功: {len(text)}文字", "SUCCESS")
                    return text, lang
                    
                except AttributeError as e:
                    log_message(f"[DEBUG] AttributeError（APIバージョン不一致の可能性）: {e}", "ERROR")
                    
                    # list()メソッドを試す（新API）
                    try:
                        transcript_list = api.list(video_id)
                        
                        # 手動作成字幕を優先
                        try:
                            transcript = transcript_list.find_manually_created_transcript([lang])
                        except:
                            # 自動生成字幕にフォールバック
                            transcript = transcript_list.find_generated_transcript([lang])
                        
                        # fetchして内容を取得
                        fetched = transcript.fetch()
                        text_parts = []
                        for item in fetched:
                            if hasattr(item, 'text'):
                                text_parts.append(item.text)
                            elif isinstance(item, dict) and 'text' in item:
                                text_parts.append(item['text'])
                        
                        text = " ".join(text_parts)
                        
                        # レート制限カウンターを記録
                        state.rate_limiter.record_request()
                        
                        log_message(f"[DEBUG] list()経由で取得成功: {len(text)}文字", "SUCCESS")
                        return text, lang
                        
                    except Exception as e2:
                        log_message(f"[DEBUG] list()メソッドも失敗: {e2}", "ERROR")
                        
                except Exception as e:
                    log_message(f"[DEBUG] 言語{lang}で失敗: {e}", "WARNING")
                    
                    # エラーメッセージから制限を検出
                    error_str = str(e).lower()
                    if any(x in error_str for x in ['too many requests', 'rate limit', '429']):
                        log_message("⚠️ YouTubeレート制限検出！", "ERROR")
                        # より長い待機
                        time.sleep(10)
                    
                    continue
            
            # すべての言語で失敗した場合
            log_message(f"[DEBUG] すべての言語で取得失敗", "ERROR")
            return None, ''
            
        except Exception as e:
            log_message(f"[DEBUG] 予期しないエラー: {e}", "ERROR")
            
            # TranscriptsDisabledもIPブロックの可能性がある
            if 'disabled' in str(e).lower():
                log_message("⚠️ IPブロックの可能性（TranscriptsDisabled偽装）", "WARNING")
                # 1回だけリトライ
                time.sleep(5)
                try:
                    api = YouTubeTranscriptApi()
                    transcript = api.fetch(video_id, languages=preferred_languages)
                    text_parts = []
                    for item in transcript:
                        if hasattr(item, 'text'):
                            text_parts.append(item.text)
                    text = " ".join(text_parts)
                    state.rate_limiter.record_request()
                    return text, preferred_languages[0]
                except:
                    pass
            
            return None, ''


    def wait_for_youtube_video_ready(self, timeout: int = 15, is_first_run: bool = False) -> bool:
        """[0214.03] YouTubeプレイヤーの準備完了を期限付きで厳密に監視（DOM優先・API依存撤廃版）"""
        
        # 上位層からの指定を尊重しつつ、初回のみ下限保証（必要なら）
        effective_timeout = timeout
        if is_first_run and timeout < 20:
            effective_timeout = 20 # 初回の下限保証
            
        start_time = time.time()
        end_time = start_time + effective_timeout
        
        # [0210.18] ゾンビ化対策: 状態確認中は通信タイムアウトも短縮する
        original_timeout = 60.0
        temp_timeout = float(effective_timeout)
        
        try:
            # WebDriverの通信設定を変更
            try:
                if hasattr(self.driver.command_executor, '_client_config'):
                    self.driver.command_executor._client_config.timeout = temp_timeout
                elif hasattr(self.driver, 'command_executor'):
                    self.driver.command_executor.set_timeout(temp_timeout)
            except: pass
            log_message(f"動画プレイヤーの準備を監視中 (期限: {effective_timeout}秒, 通信TO: {temp_timeout}s)...", "DEBUG")
            
            while time.time() < end_time:
                try:
                    # [2026.0214.03] 修正: API呼び出し(execute_script)を削除し、DOM検索のみに一本化
                    # これにより、JSエンジンが重い場合やAPIが特定のステートで固まっている場合でも
                    # 「見た目」が表示されていれば即座に通過できる。
                    
                    # タイトル要素の出現（DOM構築の証拠）
                    # [2026.0214.01] YouTube仕様変更対応: yt-formatted-string を追加
                    title_present = len(self.driver.find_elements(By.CSS_SELECTOR, "h1.ytd-video-primary-info-renderer, h1.ytd-watch-metadata, #title h1, yt-formatted-string.ytd-watch-metadata")) > 0
                    
                    # [2026.0214.03] API依存撤廃: タイトルが見えていれば(DOM構築完了していれば)操作可能とみなす
                    if title_present:
                        elapsed = time.time() - start_time
                        # 成功ログ
                        log_message(f"✅ 物理証拠を確認：動画準備完了 (DOM検出優先, Time:{elapsed:.1f}s)", "SUCCESS")
                        return True
                        
                except Exception as e:
                    # [0210.18] 通信タイムアウト系エラーは即座にFATAL扱いにする（即時介錯）
                    # 単なる読み込み遅延ではなく、メモリ参照すらできない＝ブラウザ死亡とみなす
                    err_str = str(e).lower()
                    if any(k in err_str for k in ["timed out", "httpconnectionpool", "max retries exceeded", "connection refused"]):
                        log_message(f"🚨 監視中に通信途絶(Zombie)を検知: {err_str}", "ERROR")
                        raise Exception(f"FATAL: Browser Freeze Detected during wait: {err_str}")
                    
                    # その他のJSエラー等は無視してリトライ
                    pass
                
                # スマートスリープ (期限を超過しないように待つ)
                remaining = end_time - time.time()
                if remaining <= 0:
                    break
                    
                # 最大1秒待つが、残り時間がそれ以下なら残り時間だけ待つ
                time.sleep(min(1.0, remaining))
                
        except Exception as e:
            # FATALはそのまま上に投げる（上位で再起動させるため）
            if "FATAL" in str(e):
                raise e
            log_message(f"監視設定エラー: {e}", "WARNING")
            
        finally:
            # [0210.18] 通信タイムアウトを必ず復元
            # ここで戻さないと、後の get() などが短時間でタイムアウトしてしまう
            try:
                if hasattr(self.driver.command_executor, '_client_config'):
                    self.driver.command_executor._client_config.timeout = original_timeout
                elif hasattr(self.driver, 'command_executor'):
                    self.driver.command_executor.set_timeout(original_timeout)
            except:
                pass
            
        # タイムアウト
        total_elapsed = time.time() - start_time
        log_message(f"⚠️ 動画プレイヤーの状態が確定しませんでしたが、見切りで続行します (経過: {total_elapsed:.1f}s / 期限: {effective_timeout}s)", "WARNING")
        
        return False

    def pause_video(self, **kwargs):
        """
        [2026.0210.06] 動画を一時停止させ、騒音とストリーミング負荷をカットする。
        事後の状態確認を廃止し、命令送信の成功をもって完了とする。
        """
        try:
            # YouTube Player APIを直接制御
            # 状態更新のラグ（数ミリ〜数百ミリ秒）を待たずに次へ進むため、事後チェックは行わない
            self.driver.execute_script("""
                const player = document.getElementById('movie_player') || document.querySelector('.html5-video-player');
                if (player && typeof player.pauseVideo === 'function') {
                    player.pauseVideo();
                }
            """)
            # 命令が送れたこと自体が成功（物理的な停止はブラウザ側のラグに任せる）
            log_message("🔇 動画を一時停止しました（騒音・負荷軽減）", "DEBUG")
            return True
        except Exception as e:
            # 停止そのものが失敗しても、本質的な要約処理を止めるべきではないためエラーは投げない
            log_message(f"一時停止コマンド送信スキップ: {e}", "DEBUG")
            return True


    def process_videos(self, videos: List[VideoInfo], 
                       config: ProcessConfig,
                       playlist_id: Optional[str] = None) -> List[SummaryResult]:
        """Glaspを使用して動画を処理（10本リミッター＆構造修正版）"""
        import traceback
        all_results = []
        batch_size = config.batch_size
        log_message(f"=== Glaspバッチ処理開始: {len(videos)}個の動画 ===", "INFO")
        
        try:
            total_batches = (len(videos) + batch_size - 1) // batch_size
            state.total_batches = total_batches
            start_idx = 0
            batch_idx = 0
            retry_count_for_current_batch = 0
            processed_count_since_restart = 0 
            
            while start_idx < len(videos):
                if check_user_input() == 'cancel': break
                
                # [2026.0214.02] 10本リミッター：制限解除によるメモリ増大に対応
                # 動画データを読み込むため、こまめな再起動でメモリリークを防ぐ
                if processed_count_since_restart >= 10:
                    log_message("🧹 10本リミッター: メモリ浄化のためブラウザを再起動します", "PROCESS")
                    if self.browser.force_restart_browser(is_auto_mode=auto_mode_manager.is_enabled()):
                        self.driver = self.browser.driver
                        self.tab_tracker = TabTracker() 
                        self.is_first_run_in_session = True
                        # [0210.16] 再起動時はプールもクリアしてゾンビハンドルを排除
                        self.youtube_tabs_pool = []
                        processed_count_since_restart = 0
                        time.sleep(3)
                
                end_idx = min(start_idx + batch_size, len(videos))
                batch_videos = videos[start_idx:end_idx]
                state.update_batch_progress(batch_idx, total_batches)
                
                try:
                    batch_results = self._process_batch(batch_videos, batch_idx, config, playlist_id)
                    all_results.extend(batch_results)
                    start_idx = end_idx
                    batch_idx += 1
                    processed_count_since_restart += len(batch_videos)
                    retry_count_for_current_batch = 0
                    
                except Exception as e:
                    log_message(f"🚨 バッチ処理例外:\n{traceback.format_exc()}", "ERROR")
                    if "FATAL" in str(e):
                        if self.browser.force_restart_browser(is_auto_mode=auto_mode_manager.is_enabled()):
                            self.driver = self.browser.driver
                            self.is_first_run_in_session = True
                            # 再起動したのでプールクリア
                            self.youtube_tabs_pool = []
                        retry_count_for_current_batch += 1
                        if retry_count_for_current_batch >= 2:
                            start_idx = end_idx
                            batch_idx += 1
                            retry_count_for_current_batch = 0
                        continue
                    else:
                        start_idx = end_idx
                        batch_idx += 1
                        continue
        except Exception as e:
            log_message(f"全体例外: {e}", "ERROR")
        finally:
            if not playlist_id: self._final_cleanup()
            return all_results

    def clear_youtube_video_resources(self, timeout: int = 3) -> bool:
        """YouTube動画のメモリリソースを完全に解放（タイムアウト付き）
        
        Args:
            timeout: タイムアウト秒数（デフォルト3秒）
        
        Returns:
            bool: 成功した場合True
        """
        if not self.driver:
            return False
        
        import threading
        
        result = [False]
        exception = [None]
        
        def execute_clear():
            try:
                self.driver.execute_script("""
                    // すべての動画要素を停止＋リソース解放
                    document.querySelectorAll('video').forEach(video => {
                        video.pause();
                        video.removeAttribute('src');
                        video.load();
                        
                        // イベントリスナーも削除
                        video.onloadedmetadata = null;
                        video.onloadeddata = null;
                        video.oncanplay = null;
                        video.oncanplaythrough = null;
                    });
                    
                    // すべての音声要素も停止
                    document.querySelectorAll('audio').forEach(audio => {
                        audio.pause();
                        audio.removeAttribute('src');
                        audio.load();
                    });
                    
                    // YouTubeプレイヤーのキャッシュをクリア
                    if (window.ytplayer && window.ytplayer.config) {
                        window.ytplayer.config.args = {};
                    }
                """)
                result[0] = True
            except Exception as e:
                exception[0] = e
        
        # 別スレッドで実行
        thread = threading.Thread(target=execute_clear)
        thread.start()
        thread.join(timeout=timeout)
        
        # タイムアウトチェック
        if thread.is_alive():
            log_message(f"clear_youtube_video_resources: タイムアウト（{timeout}秒）", "WARNING")
            return False
        
        # 例外が発生した場合
        if exception[0]:
            log_message(f"clear_youtube_video_resources エラー: {exception[0]}", "WARNING")
            return False
        
        return result[0]

# ============================================================================
# SECTION 8: GLASP ENGINE
# ============================================================================




class GlaspEngine:

    def __init__(self, browser_manager: BrowserManager):
        """GlaspBatchProcessor初期化（タブプール初期化付き）"""
        self.browser = browser_manager
        self.tab_tracker = TabTracker()
        self.original_tab = None
        
        # === YouTubeタブプールの初期化 ===
        self.youtube_tabs_pool = []
        
        # プレイリストタブの保存用
        self.playlist_tab_handle = None
        
        if self.driver:
            self.original_tab = self.driver.current_window_handle
        
        # ========== 動的タイムアウト管理 ==========
        self.current_base_timeout = 60.0
        self.min_timeout = 60.0
        self.max_timeout = 60.0
        self.timeout_extension = 0.0
        self.reset_threshold_ratio = 0.75
        
        # ========== 初回実行フラグ ==========
        self.is_first_run_in_session = True
        
        log_message("GlaspBatchProcessor初期化完了", "INFO")

    @property
    def driver(self):
        """常に最新のブラウザドライバを返す（ゾンビ参照防止）"""
        return self.browser.driver if self.browser else None

    def _ensure_tab_ready(self, tab_handle: str, timeout: int = 20) -> bool:
        """タブが操作可能になるまでDOM状態を監視する"""
        try:
            self.driver.switch_to.window(tab_handle)
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "ytd-app"))
            )
            time.sleep(2)
            log_message(f"タブの準備完了を確認: {tab_handle[:8]}...", "DEBUG")
            return True
        except Exception as e:
            log_message(f"タブ準備確認タイムアウト/エラー: {e}", "WARNING")
            return False

    def process_multiple_playlists(self, playlist_configs: Dict[str, str], 
                                  selected_playlists: List[str],
                                  config: ProcessConfig) -> Dict[str, List[SummaryResult]]:
        """複数プレイリストを処理（ブラウザ挙動モード対応版）"""
        all_results = {}
        log_message(f"=== 複数プレイリスト処理開始: {len(selected_playlists)}個 ===", "INFO")
        
        for playlist_index, playlist_name in enumerate(selected_playlists):
            if check_user_input() == 'cancel':
                log_message("処理がキャンセルされました", "WARNING")
                break
            
            playlist_id = playlist_configs.get(playlist_name)
            if not playlist_id:
                log_message(f"プレイリスト {playlist_name} のIDが見つかりません", "ERROR")
                continue
            
            log_message(f"=== プレイリスト {playlist_name} ({playlist_index + 1}/{len(selected_playlists)}) 処理開始 ===", "INFO")
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            
            try:
                log_message("🔄 プレイリスト開始のためブラウザをリセットします...", "PROCESS")
                if not self.browser.force_restart_browser(is_auto_mode=True):
                    log_message("⚠️ ブラウザのリセットに失敗しましたが、続行を試みます", "WARNING")

                youtube_handler = YouTubeHandler(self.driver)
                videos = youtube_handler.get_playlist_videos_selenium(
                    playlist_url,
                    config.max_videos,
                    config.include_current,
                    config.process_all
                )
                
                if not videos:
                    log_message(f"プレイリスト {playlist_name} に動画が見つかりません", "WARNING")
                    continue
                
                # 単一プレイリスト処理へ委譲
                results = self.process_single_playlist(videos, config, playlist_id=playlist_name)
                all_results[playlist_name] = results
                log_message(f"プレイリスト {playlist_name} 処理完了", "SUCCESS")
                
            except Exception as e:
                log_message(f"プレイリスト {playlist_name} 処理エラー: {e}", "ERROR")
                continue
        
        log_message("全プレイリスト処理後の最終クリーンアップ", "INFO")
        try:
            self.browser.force_restart_browser(is_auto_mode=True)
        except: pass
        
        log_message(f"=== 全プレイリスト処理完了 ===", "SUCCESS")
        return all_results

    def process_single_playlist(self, videos: List[VideoInfo], config: ProcessConfig, playlist_id: str = None) -> List[SummaryResult]:
        """単一プレイリスト内の動画を処理（二重ループ削除・一元化版）"""
        log_message(f"処理対象: {len(videos)}件の動画", "INFO")
        
        # [20260420.01] 古いバッチループを削除し、安定動作している process_videos へ処理を完全委譲
        results = self.process_videos(videos, config, playlist_id=playlist_id)
        
        # レポート生成
        if results:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "playlist"
            if playlist_id:
                safe_name = "".join([c for c in playlist_id if c.isalnum() or c in (' ', '-', '_')]).strip()
            
            output_dir = globals().get('OUTPUT_DIR', 'output')
            filename = f"summary_{safe_name}_{timestamp}.{config.output_format}"
            output_path = os.path.join(output_dir, filename)
            
            try:
                output_gen = OutputGenerator()
                if config.output_format in ['html', 'both']:
                    output_gen.generate_html(results, playlist_id=playlist_id or "Single Playlist")
                if config.output_format in ['json', 'both']:
                    output_gen.save_json(results, playlist_id=playlist_id)
                log_message(f"レポート生成: {output_path}", "INFO")
            except Exception as e:
                log_message(f"レポート生成エラー: {e}", "ERROR")

        return results

    def process_videos(self, videos: List[VideoInfo], 
                       config: ProcessConfig,
                       playlist_id: Optional[str] = None) -> List[SummaryResult]:
        """Glaspを使用して動画を処理（一本化版）"""
        import traceback
        all_results = []
        batch_size = config.batch_size
        log_message(f"=== Glaspバッチ処理開始: {len(videos)}個の動画 (バッチサイズ: {batch_size}) ===", "INFO")

        try:
            total_batches = (len(videos) + batch_size - 1) // batch_size
            state.total_batches = total_batches
            start_idx = 0
            batch_idx = 0
            retry_count_for_current_batch = 0
            # [S03十七訂] 40本ごとのメモリ浄化用ブラウザ再起動リミッターは撤去した。
            # 再起動直後に2巡目の最初の1本がGlaspに一切反応してもらえない現象が
            # 実機ログで確認されたため、越智さんの指示により定期的な予防的再起動を
            # やめている。致命的エラー時の再起動（FATAL発生時、下記except節）は維持。

            while start_idx < len(videos):
                if check_user_input() == 'cancel': break

                end_idx = min(start_idx + batch_size, len(videos))
                batch_videos = videos[start_idx:end_idx]
                state.update_batch_progress(batch_idx, total_batches)

                log_message(f"=== バッチ {batch_idx + 1}/{total_batches} 開始 ({len(batch_videos)}個の動画) ===", "PROCESS")

                try:
                    batch_results = self._process_batch(batch_videos, batch_idx, config, playlist_id)
                    all_results.extend(batch_results)
                    start_idx = end_idx
                    batch_idx += 1
                    retry_count_for_current_batch = 0
                    
                    if len(videos) > 0:
                        state.current_progress = min(start_idx, len(videos))
                    
                except Exception as e:
                    log_message(f"🚨 バッチ処理例外:\n{traceback.format_exc()}", "ERROR")
                    if "FATAL" in str(e):
                        if self.browser.force_restart_browser(is_auto_mode=auto_mode_manager.is_enabled()):
                            self.is_first_run_in_session = True
                            self.youtube_tabs_pool = []
                        retry_count_for_current_batch += 1
                        if retry_count_for_current_batch >= 2:
                            start_idx = end_idx
                            batch_idx += 1
                            retry_count_for_current_batch = 0
                        continue
                    else:
                        start_idx = end_idx
                        batch_idx += 1
                        continue
        except Exception as e:
            log_message(f"全体例外: {e}", "ERROR")
        finally:
            if not playlist_id: self._final_cleanup()
            return all_results


    def _cleanup_stray_glasp_tabs(self, protected_handles: set) -> int:
        """
        [S03再々修正・第4版] 1巡目(トリガー)完了直後に呼び出し、動画視聴タブ
        （youtube.com/watch）以外の全タブ（直前のクリックで偶然開いてしまった、
        文字起こしが入っていないプレーンなGeminiタブ、Chromeの初期タブ
        (chrome://new-tab-page/ 等、見た目はGoogle検索画面)、プレイリスト
        タブ等）を閉じてクリーンな状態に戻す。
        越智さんの実機観察により、こうしたタブは待っても文字起こしが入ることは
        なく、2巡目で別の動画のタブと誤認され、実体のないタブを掴んだまま何も
        進まなくなることが確認されたため、「youtube.com/watchの動画タブかどうか」
        だけを判定基準とし、それ以外は種類を問わず無条件でクローズする。
        以前のバージョンではself.main_window_handleを保護対象に含めていたが、
        これがChrome起動直後の初期タブ(chrome://new-tab-page/)のままになって
        いるケースで「消えないGoogle画面」として残り続ける不具合の原因になって
        いたため、メインタブという理由での例外は廃止した。
        プレイリストタブは全動画のURLを事前に一括取得済みのため、バッチ処理中に
        再度参照する必要はなく、閉じても後続処理に影響しない
        （cleanup_playlist_tabsは見つからない場合も正常に動作する）。
        protected_handlesに含まれるタブ（動画タブ本体・既に確定済みのGeminiタブ）
        は対象外。
        """
        closed_count = 0
        try:
            current_handles = list(self.driver.window_handles)
        except Exception:
            return 0

        for handle in current_handles:
            if handle in protected_handles:
                continue
            try:
                self.driver.switch_to.window(handle)
                current_url = (self.driver.current_url or "").lower()
            except Exception:
                continue
            if "youtube.com/watch" not in current_url:
                try:
                    self.driver.close()
                    closed_count += 1
                    log_message(
                        f"GLASP_STRAY_TAB_CLEANUP|handle={str(handle)[:8]}|url={current_url[:120]}",
                        "INFO"
                    )
                except Exception as e:
                    log_message(f"GLASP_STRAY_TAB_CLEANUP_ERROR|handle={str(handle)[:8]}|error={e}", "WARNING")

        # main_window_handleがクリーンアップで閉じられた可能性があるため、
        # 生存している動画タブを優先して新しいメインタブとして採用し直す
        try:
            remaining_handles = self.driver.window_handles
            main_handle = getattr(self, 'main_window_handle', None)
            if not main_handle or main_handle not in remaining_handles:
                fallback_handle = next((h for h in protected_handles if h in remaining_handles), None)
                if not fallback_handle and remaining_handles:
                    fallback_handle = remaining_handles[0]
                if fallback_handle:
                    self.main_window_handle = fallback_handle
                    main_handle = fallback_handle
            if main_handle and main_handle in remaining_handles:
                self.driver.switch_to.window(main_handle)
        except Exception:
            pass

        return closed_count

    def _write_suspend_lock(self, deadline_ts: float, reason: str) -> None:
        """待機中であることを、後続の定時実行へ伝えるロックファイルを書く。"""
        try:
            payload = {
                'pid': _os.getpid(),
                'reason': reason,
                'suspended_at': _datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'expires_at': deadline_ts,
                'expires_at_text': _datetime.fromtimestamp(deadline_ts).strftime('%Y-%m-%d %H:%M:%S'),
            }
            with open(SUSPEND_LOCK_FILE, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            log_message(f"SUSPEND_LOCK_WRITTEN|file={SUSPEND_LOCK_FILE}|expires={payload['expires_at_text']}", "INFO")
        except Exception as e:
            log_message(f"SUSPEND_LOCK_WRITE_ERROR|error={e}", "WARNING")

    def _clear_suspend_lock(self) -> None:
        """待機の終了時にロックファイルを必ず消す。"""
        try:
            if _os.path.exists(SUSPEND_LOCK_FILE):
                _os.remove(SUSPEND_LOCK_FILE)
                log_message("SUSPEND_LOCK_CLEARED", "INFO")
        except Exception as e:
            log_message(f"SUSPEND_LOCK_CLEAR_ERROR|error={e}", "WARNING")

    def _suspend_until_challenge_cleared(self, protected_handles: set) -> bool:
        """
        Googleの確認画面を検知したとき、処理を止めて人が解除するのを待つ。

        確認画面を突破する処理は一切行わない。解除は越智さんが手で行う前提であり、
        ここでやるのは次の3つだけである。
          1. これ以上Glaspを叩かない（叩き続けると状況が悪化するだけ）
          2. 溜まったタブを片付け、確認画面のタブを1枚だけ画面に残す
             （朝いちばんに目に入るようにするため）
          3. その1枚のURLが変わるのを待つ。解除するとGoogleが continue= 先の
             Geminiへ遷移させるので、URLを読むだけで解除が分かる。
             Googleへの追加リクエストは発生しない。

        戻り値: True=解除を確認した（処理を続行してよい） / False=期限切れ
        """
        now = time.time()
        deadline_dt = _datetime.fromtimestamp(now).replace(
            hour=SUSPEND_DEADLINE_HOUR, minute=0, second=0, microsecond=0
        )
        if deadline_dt.timestamp() <= now:
            deadline_dt = deadline_dt + timedelta(days=1)
        deadline_ts = min(deadline_dt.timestamp(), now + MAX_SUSPEND_HOURS * 3600)
        deadline_dt = _datetime.fromtimestamp(deadline_ts)

        log_message("=" * 60, "ERROR")
        log_message("🛑 Googleの確認画面（reCAPTCHA等）を検知しました。", "ERROR")
        log_message("   自動での突破は行いません。処理を中断して待機します。", "ERROR")
        log_message(f"   Chromeに確認画面のタブを1枚残します。手動で解除してください。", "ERROR")
        log_message(f"   解除を確認しだい、中断した動画から自動で再開します。", "ERROR")
        log_message(f"   待機の期限: {deadline_dt.strftime('%Y-%m-%d %H:%M:%S')}", "ERROR")
        log_message("=" * 60, "ERROR")
        measure_log(f"GLASP_MEASURE_SUSPEND|event=start|deadline={deadline_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        # --- 確認画面タブを1枚だけ残し、他の余計なタブは閉じる ---
        sensor_handle = None
        try:
            for handle in list(self.driver.window_handles):
                if handle in protected_handles:
                    continue
                try:
                    self.driver.switch_to.window(handle)
                    url = self.driver.current_url or ""
                except Exception:
                    continue
                if is_challenge_url(url) and sensor_handle is None:
                    sensor_handle = handle
                    continue
                if "youtube.com/watch" not in url.lower():
                    try:
                        self.driver.close()
                    except Exception:
                        pass
        except Exception as e:
            log_message(f"SUSPEND_TAB_TIDY_ERROR|error={e}", "WARNING")

        if sensor_handle:
            try:
                self.driver.switch_to.window(sensor_handle)
            except Exception:
                sensor_handle = None
        log_message(f"SUSPEND_SENSOR_TAB|handle={str(sensor_handle)[:8] if sensor_handle else 'none'}", "INFO")

        self._write_suspend_lock(deadline_ts, "google_challenge")

        try:
            while time.time() < deadline_ts:
                if check_user_input() == 'cancel':
                    log_message("待機中にユーザーによる中止を検知しました", "WARNING")
                    measure_log("GLASP_MEASURE_SUSPEND|event=cancelled")
                    return False

                if not smart_sleep(SUSPEND_POLL_INTERVAL):
                    if state.cancel_flag:
                        measure_log("GLASP_MEASURE_SUSPEND|event=cancelled")
                        return False
                    # 待機中のスキップ操作は、再開後の処理へ持ち越さない
                    state.skip_flag = False

                current_url = None
                try:
                    handles = self.driver.window_handles
                    if sensor_handle and sensor_handle in handles:
                        self.driver.switch_to.window(sensor_handle)
                        current_url = self.driver.current_url or ""
                    else:
                        # 監視用タブが閉じられていた場合のみ、こちらから1回だけ
                        # Geminiを開いて状態を確かめ直す（これが唯一の追加通信）。
                        self.driver.switch_to.new_window('tab')
                        sensor_handle = self.driver.current_window_handle
                        self.driver.get("https://gemini.google.com/app")
                        current_url = self.driver.current_url or ""
                        log_message(f"SUSPEND_SENSOR_TAB_REOPENED|handle={str(sensor_handle)[:8]}", "INFO")
                except Exception as e:
                    log_message(f"SUSPEND_POLL_ERROR|error={type(e).__name__}:{str(e)[:120]}", "WARNING")
                    continue

                if current_url and not is_challenge_url(current_url):
                    remaining = int((deadline_ts - time.time()) / 60)
                    log_message("✅ 確認画面の解除を確認しました。処理を再開します。", "SUCCESS")
                    log_message(f"SUSPEND_CLEARED|url={current_url[:120]}|remaining_min={remaining}", "INFO")
                    measure_log(f"GLASP_MEASURE_SUSPEND|event=cleared|url={current_url[:80]}")
                    try:
                        if sensor_handle and sensor_handle in self.driver.window_handles:
                            self.driver.switch_to.window(sensor_handle)
                            self.driver.close()
                    except Exception:
                        pass
                    # 監視用タブを閉じた直後は、どのタブも選択されていない状態に
                    # なりうるため、生存しているタブへ明示的に戻しておく。
                    try:
                        alive = self.driver.window_handles
                        main_handle = getattr(self, 'main_window_handle', None)
                        if not main_handle or main_handle not in alive:
                            main_handle = next((h for h in protected_handles if h in alive), None)
                            if not main_handle and alive:
                                main_handle = alive[0]
                            if main_handle:
                                self.main_window_handle = main_handle
                        if main_handle:
                            self.driver.switch_to.window(main_handle)
                    except Exception as e:
                        log_message(f"SUSPEND_RESTORE_WINDOW_ERROR|error={e}", "WARNING")
                    return True

            log_message("⏰ 待機の期限に達しました。今回の実行は終了します。", "WARNING")
            measure_log("GLASP_MEASURE_SUSPEND|event=deadline")
            return False
        finally:
            self._clear_suspend_lock()

    def _batch_send_ctrl_x(self, video_tabs: List[Dict], config: ProcessConfig = None) -> List[Dict]:
        """
        [ADR-0001、S03五訂] Glasp起動処理を2ラウンド構成で実行する。

        1巡目(トリガー): まだ確定していない全動画に対して、Glasp起動ボタンを1回クリック
                        するだけを順番に行う。検出は待たない（即座に次の動画へ）。
                        文字起こしがまだ生成されていない時点でこのクリックを行うと、
                        一定確率で「文字起こしが入らないプレーンなGeminiタブ」だけが
                        開いてしまうことがあり、そのタブはいくら待っても要約が始まらない
                        ことが分かっている。この1巡目のクリック結果は2巡目では一切
                        再利用しない（意図的に使い捨てる）。
        （1巡目と2巡目の間）: 動画視聴タブ以外の全タブをクリーンアップする。これにより、
                            1巡目のクリックで偶然開いてしまった可能性のあるプレーンな
                            Geminiタブ（および Chrome起動直後の初期タブ等）を一掃し、
                            2巡目を「動画タブのみ」の状態から始められるようにする。
        2巡目(Gemini起動確認): 1巡目を通過した動画を順番に、1本ずつ以下を行う
                            （1巡目のクリック結果とは独立に、ここで新たにクリックし直す）。
                              (1) 動画タブに切り替える
                              (2) 1秒待機する
                              (3) きらきらボタンを押す
                              (4) 新しいGeminiタブが出現するのを最大tab_gen_timeout秒
                                  （0.5秒間隔）待ち、出現すればgemini.google.comである
                                  ことを確認して即座に抜ける
                              (5) tab_gen_timeout秒経っても出現しなければ、もう1回だけ
                                  (3)からやり直す。それでもダメならこの動画は
                                  「タブ未出現」で確定失敗とし、次の動画へ進む
                              (6) タブが見つかったら_confirm_glasp_success（高速チェック
                                  3秒＋詳細チェック最大8秒）で送信成功を確認する。
                                  失敗した場合はここでは再試行せず確定失敗とする
                            （動画1本あたり2巡目内でのクリックは最大2回まで）。

        失敗時にdriver.refresh()（動画タブの再読み込み）は行わない（文字起こし生成を
        最初からやり直させてしまうため、越智さんのご指摘により廃止）。

        戻り値の各dictのキー構成・video_tabsと同じ順序は現行(20260801_03)と完全互換（呼び出し側は無改修）。
        """
        results_by_index: Dict[int, Dict] = {}
        log_message(f"Glasp起動処理開始: {len(video_tabs)}タブ", "PROCESS")

        skipped_count = 0
        MAX_ROUND2_ATTEMPTS = 2  # 2巡目内でのきらきらボタンは動画1本あたり最大2回（1回目＋リトライ1回）
        GENERIC_FAIL_MSG = "Glasp起動失敗（Ctrl+X不発またはタイムアウト）"

        # [20260808] 1巡目のきらきらクリックをやめ、「クリックせずに整えるだけ」にする。
        #
        # 経緯: 1巡目のクリックは、Glaspに文字起こしを読み込ませるための助走として
        # 意図的に入れていたもので、その結果のGeminiタブは捨てていた。しかし実測で
        # 1巡目64クリックに対し51枚のタブが実際に開いており（8割）、Googleへの
        # リクエストを実質倍増させていた。同日中に確認画面(reCAPTCHA)が2回出ており、
        # 無関係とは考えにくい。
        #
        # 一方、2巡目は52本中44本が1回目のクリックで成功している。助走として効いて
        # いるのはクリックそのものではなく、タブを開いてから2巡目までに流れる時間の
        # 可能性が高い。そこで1巡目からクリックだけを外し、タブ切替・動画読込待ち・
        # 一時停止・字幕確認はそのまま残す。時間の経過は維持したまま、捨てるだけの
        # Geminiセッションをゼロにする。
        #
        # config.json の glasp.round1_click を true にすれば従来動作に戻せる。
        round1_prepare_only = not bool(config_manager.get('glasp.round1_click', False))
        log_message(
            f"GLASP_ROUND1_MODE|prepare_only={round1_prepare_only}|"
            f"note={'クリックせず準備のみ' if round1_prepare_only else '従来どおりクリックする'}",
            "INFO"
        )

        slow_tab_threshold = config.tab_wait_timeout if config else 10.0
        input_mode = config.glasp_input_mode if config else 'js_click'

        tab_gen_timeout = (
            config_manager.get("glasp.tab_generation_timeout_first", 8)
            if self.is_first_run_in_session
            else config_manager.get("glasp.tab_generation_timeout", 5)
        )
        if self.is_first_run_in_session:
            log_message(f"📢 初回/復帰直後のため、動画読み込み待機時間を {tab_gen_timeout}秒 に延長します", "INFO")

        original_socket_timeout = 60.0
        temp_socket_timeout = 15.0

        def _measure_video(item: Dict, success: bool, r2_click: Optional[int], reason: str = ""):
            """
            [計測] 動画1本の最終結果を、1巡目/2巡目それぞれのゲート判定内訳と
            突き合わせて1行にまとめる。「api宣言だけで通過した動画」と
            「文字起こし行の実体まで揃っていた動画」で、2巡目の成功率および
            必要クリック数に差が出るかを見るための材料。集計専用で、
            処理の分岐には一切使用しない。
            """
            try:
                g1 = item.get('gate_r1') or {}
                g2 = item.get('gate_r2') or {}
                measure_log(
                    "GLASP_MEASURE_VIDEO|"
                    f"video_idx={item.get('playlist_position')}|"
                    f"video_id={str(item.get('video_id_for_log', ''))[:12]}|"
                    f"success={bool(success)}|"
                    f"r2_click={'-' if r2_click is None else r2_click + 1}|"
                    f"r1_api={g1.get('api')}|r1_seg={g1.get('seg')}|r1_seg_count={g1.get('seg_count')}|"
                    f"r1_seg_len={g1.get('seg_len')}|"
                    f"r2_api={g2.get('api')}|r2_seg={g2.get('seg')}|r2_seg_count={g2.get('seg_count')}|"
                    f"r2_seg_len={g2.get('seg_len')}|"
                    f"reason={str(reason)[:60]}"
                )
            except Exception as measure_error:
                log_message(f"GLASP_MEASURE_ERROR|stage=video_line|error={measure_error}", "WARNING")

        def _finalize_success(item: Dict, glasp_handle: str, retry_count: int):
            _measure_video(item, True, retry_count)
            perf_log(
                "glasp_video_total",
                item['video_total_start'],
                video_idx=item['playlist_position'],
                video_id=item['video_id_for_log'][:12],
                success=True,
                retry_count=retry_count
            )
            log_message(f"動画{item['playlist_position']}: Glasp起動成功", "SUCCESS")
            results_by_index[item['index']] = {
                'video_info': item['video_info'],
                'success': True,
                'glasp_handle': glasp_handle,
                'processing_time': time.time() - item['video_total_start'],
                'retry_count': retry_count,
                'error': '',
                'skipped': False,
                'skip_reason': None
            }

        def _finalize_failure(item: Dict, error_msg: str, skip_kind: str = 'failed'):
            """
            [20260808] 第2引数に必ずGENERIC_FAIL_MSGを渡していたため、字幕が無くて
            要約できない動画も「Glasp起動失敗（Ctrl+X不発またはタイムアウト）」として
            記録されていた。要約対象外の動画と、本当に失敗した動画が区別できず、
            朝の一通でも同じ「失敗」として並んでいた。実際の理由を渡す。

            skip_kind:
              'no_transcript' … 字幕が無く、そもそも要約できない（再実行しても同じ）
              'failed'        … Glaspの起動に失敗した（再実行で成功する見込みがある）
            """
            nonlocal skipped_count
            _measure_video(item, False, None, error_msg)
            level = "INFO" if skip_kind == 'no_transcript' else "WARNING"
            label = "要約対象外" if skip_kind == 'no_transcript' else "処理失敗"
            log_message(f"動画{item['playlist_position']}: {label}: {error_msg}", level)
            perf_log(
                "glasp_video_total",
                item['video_total_start'],
                video_idx=item['playlist_position'],
                video_id=item['video_id_for_log'][:12],
                success=False,
                skip_kind=skip_kind,
                reason=str(error_msg)[:80]
            )
            results_by_index[item['index']] = {
                'video_info': item['video_info'],
                'success': False,
                'error': error_msg,
                'skipped': True,
                'skip_reason': error_msg,
                'skip_kind': skip_kind,
                'processing_time': time.time() - item['video_total_start'],
                'retry_count': MAX_ROUND2_ATTEMPTS - 1
            }
            skipped_count += 1

        def _classify_trigger_failure(trig: Dict) -> Tuple[str, str]:
            """
            _trigger_glasp_click の恒久的失敗から、記録すべき理由と種別を決める。
            字幕データなしは「再実行しても結果が変わらない」ため、失敗とは区別する。
            """
            reason = str((trig or {}).get('error') or '').strip()
            if not reason:
                return GENERIC_FAIL_MSG, 'failed'
            if '字幕' in reason:
                return f"要約対象外: {reason}", 'no_transcript'
            return reason, 'failed'

        try:
            if hasattr(self.driver.command_executor, '_client_config'):
                self.driver.command_executor._client_config.timeout = temp_socket_timeout
            elif hasattr(self.driver, 'command_executor'):
                self.driver.command_executor.set_timeout(temp_socket_timeout)
        except:
            pass

        cancelled = False
        # バッチ全体で共有する「既に他の動画に割り当て済みのGeminiタブ」の集合。
        # 生成が遅い動画のタブが後から出現した際、別の動画がそれを誤って
        # 自分のものと拾ってしまわないようにするための保険（本来は2巡目を1本ずつ
        # きちんと待つ構成にしたことで発生しにくくなっているはずだが、念のため維持）。
        claimed_handles: set = set()
        # 動画タブ自体は「予期しないGeminiタブ」クリーンアップの対象外として保護する
        video_tab_handles: set = {t.get('tab_handle') for t in video_tabs if t.get('tab_handle')}

        # 初期リスト構築（動画情報欠損・タブ生成失敗は現行同様その場で確定させる）
        pending: List[Dict] = []
        for i, tab_info in enumerate(video_tabs):
            video_info_obj = tab_info.get('video_info')
            if not video_info_obj:
                results_by_index[i] = {
                    'video_info': None,
                    'success': False,
                    'error': '動画情報欠損',
                    'skipped': True,
                    'processing_time': 0,
                    'retry_count': 0
                }
                skipped_count += 1
                continue

            if not tab_info.get('tab_handle') and not self.is_first_run_in_session:
                results_by_index[i] = {
                    'video_info': video_info_obj,
                    'success': False,
                    'error': 'タブ生成失敗（ハンドルなし）',
                    'skipped': True,
                    'processing_time': 0,
                    'retry_count': 0
                }
                skipped_count += 1
                continue

            pending.append({
                'index': i,
                'tab_info': tab_info,
                'video_info': video_info_obj,
                'video_id_for_log': getattr(video_info_obj, 'video_id', ''),
                'playlist_position': getattr(video_info_obj, 'playlist_order', 0) + 1,
                'video_total_start': time.time(),
            })

        try:
            # === 1巡目: トリガー（クリックのみ、待たない。結果は2巡目では使い捨てる） ===
            candidate_items: List[Dict] = []
            for i, item in enumerate(pending):
                if check_user_input() == 'cancel':
                    cancelled = True
                    break

                if item.get('video_info'):
                    state.set_current_video(item['video_info'].title)
                    state.update_status(f"Glaspトリガー中... ({i+1}/{len(pending)})")

                if not smart_sleep(0.5):
                    if state.cancel_flag:
                        cancelled = True
                        break
                    if state.skip_flag:
                        state.skip_flag = False
                        perf_log(
                            "glasp_video_total",
                            item['video_total_start'],
                            video_idx=item['playlist_position'],
                            video_id=item['video_id_for_log'][:12],
                            success=False,
                            reason="user_skip"
                        )
                        results_by_index[item['index']] = {'video_info': item['video_info'], 'success': False, 'skipped': True, 'error': 'ユーザーによるスキップ', 'processing_time': 0, 'retry_count': 0}
                        continue

                try:
                    trig = self._trigger_glasp_click(
                        item['tab_info'], item['playlist_position'], attempt_index=0,
                        timeout_threshold=slow_tab_threshold, input_mode=input_mode,
                        round_label="1", prepare_only=round1_prepare_only
                    )
                except Exception as e:
                    error_msg = str(e)
                    item['gate_r1'] = dict(getattr(self, '_last_transcript_measure', None) or {})
                    if "FATAL" in error_msg:
                        raise Exception(error_msg)
                    candidate_items.append(item)
                    continue

                item['gate_r1'] = dict(getattr(self, '_last_transcript_measure', None) or {})

                if not trig['ok'] and trig.get('permanent'):
                    fail_msg, fail_kind = _classify_trigger_failure(trig)
                    _finalize_failure(item, fail_msg, fail_kind)
                    continue

                # 送信できた場合・できなかった場合のいずれも、このクリック自体は
                # 2巡目では使い捨てる（before_handles/trigger_methodは保持しない）
                candidate_items.append(item)

            if not cancelled:
                # 1巡目のクリックで偶然開いてしまった「予期しないタブ」
                # （文字起こしが入っていないプレーンなGeminiタブ、Chrome起動直後の
                # 初期タブ等）を、2巡目に入る前にクリーンアップする。越智さんの
                # 実機観察により、文字起こしが未生成の時点でクリックすると、一定
                # 確率でこうした「何も始まらないプレーンなタブ」だけが開いてしまう
                # ことが分かっているため、2巡目を動画タブのみのクリーンな状態から
                # 始められるようにする（S03五訂）。main_window_handleという理由
                # だけでの例外は設けない（初期タブがmain_window_handleのまま
                # クリーンアップされずに残り続ける不具合の原因になっていたため）。
                protected_handles = video_tab_handles | claimed_handles
                stray_closed = self._cleanup_stray_glasp_tabs(protected_handles)
                if stray_closed:
                    log_message(f"予期しないGeminiタブを{stray_closed}個クリーンアップしました", "INFO")

                # [計測] 1巡目のクリックが実際に何枚のタブを開いてしまったか。
                # 「1巡目で捨てているGeminiセッション数」の実測値であり、
                # 確認画面(reCAPTCHA)を誘発している負荷量の見積もりに使う。
                measure_log(
                    "GLASP_MEASURE_STRAY|"
                    f"round1_prepare_only={round1_prepare_only}|"
                    f"round1_attempted={len(pending)}|round1_candidates={len(candidate_items)}|"
                    f"stray_closed={stray_closed}"
                )

                # [S03十七訂] クリーンアップ直後、2巡目の最初の1本だけクリックは
                # 成功してもGeminiタブが一切出現しない、という現象が実機ログで
                # 確認された。クリーンアップ直後は状態がまだ落ち着いていない
                # 可能性を考慮し、2巡目に入る前に短い追加の間を置く。
                if not smart_sleep(2.0):
                    cancelled = True

            # === 2巡目: Gemini起動確認（動画ごとに独立して「切替→待機→クリック→タブ出現待ち」、S03十六訂） ===
            # [S03十六訂] パートA/B 2パス化（S03十四訂）は、複数動画のクリックを
            # 待たずに連続実行した結果、各動画のbefore_handlesスナップショットが
            # 「自分をクリックする直前」の状態にしかならず、パートBに入った時点で
            # 他の動画のGeminiタブまで「自分の新しいタブの候補」に見えてしまう
            # 問題が実機ログ（multiple_new_handlesで最大7枚同時検出）で確認された。
            # window_handlesの並び順に頼った取り違え防止は確実性を保証できない
            # （動画Aの要約として動画Bの内容が記録されるリスクがある）ため、
            # 安全性を優先し、動画ごとに完結する逐次処理へ戻す。
            for i, item in enumerate(candidate_items):
                if cancelled:
                    break
                if check_user_input() == 'cancel':
                    _finalize_failure(item, "ユーザーによる中止", 'cancelled')
                    cancelled = True
                    break

                if item.get('video_info'):
                    state.set_current_video(item['video_info'].title)
                    state.update_status(f"Geminiタブ起動確認中... ({i+1}/{len(candidate_items)})")

                try:
                    self.driver.switch_to.window(item['tab_info']['tab_handle'])
                except Exception:
                    pass
                if not smart_sleep(0.5):
                    _finalize_failure(item, "ユーザーによる中止", 'cancelled')
                    cancelled = True
                    break

                finalized = False
                for r2_attempt in range(MAX_ROUND2_ATTEMPTS):
                    try:
                        trig = self._trigger_glasp_click(
                            item['tab_info'], item['playlist_position'], attempt_index=r2_attempt,
                            timeout_threshold=slow_tab_threshold, input_mode=input_mode,
                            round_label="2"
                        )
                    except Exception as e:
                        error_msg = str(e)
                        item['gate_r2'] = dict(getattr(self, '_last_transcript_measure', None) or {})
                        if "FATAL" in error_msg:
                            raise Exception(error_msg)
                        continue

                    item['gate_r2'] = dict(getattr(self, '_last_transcript_measure', None) or {})

                    if not trig['ok']:
                        if trig.get('permanent'):
                            fail_msg, fail_kind = _classify_trigger_failure(trig)
                            _finalize_failure(item, fail_msg, fail_kind)
                            finalized = True
                            break
                        continue

                    wait_result = self._wait_for_new_glasp_handle(
                        item['tab_info'], trig['before_handles'], claimed_handles, item['playlist_position'],
                        r2_attempt, trig['trigger_method'], tab_gen_timeout=tab_gen_timeout
                    )
                    if not wait_result['handle']:
                        continue  # タブ未出現 → リトライ予算があれば(3)からやり直す

                    try:
                        conf = self._confirm_glasp_success(
                            item['tab_info'], wait_result['handle'], item['playlist_position'], r2_attempt
                        )
                    except Exception as e:
                        error_msg = str(e)
                        # [20260808] 確認画面は「中止」ではなく「待機」で扱う。
                        # 人が解除するまで止まり、解除を確認したら同じ動画から続行する。
                        # 解除されないまま期限が来た場合だけ、従来どおり中止する。
                        if "CHALLENGE_DETECTED" in error_msg:
                            if self._suspend_until_challenge_cleared(
                                protected_handles=video_tab_handles | claimed_handles
                            ):
                                continue
                            raise Exception(error_msg)
                        if "FATAL" in error_msg:
                            raise Exception(error_msg)
                        conf = {'success': False}

                    if conf['success']:
                        _finalize_success(item, wait_result['handle'], retry_count=r2_attempt)
                        finalized = True
                        break
                    # タブは出たが要約開始の確認に失敗 → リトライ予算があれば、
                    # もう一度動画タブに戻ってきらきらを押し直す（S03八訂）。
                    continue

                if not finalized:
                    _finalize_failure(item, GENERIC_FAIL_MSG)

            # キャンセル、または動画情報欠損等で残った動画は打ち切り（現行の「未処理動画には結果を残さない」挙動を踏襲）
        finally:
            try:
                if hasattr(self.driver.command_executor, '_client_config'):
                    self.driver.command_executor._client_config.timeout = original_socket_timeout
                elif hasattr(self.driver, 'command_executor'):
                    self.driver.command_executor.set_timeout(original_socket_timeout)
            except:
                pass

        results = [results_by_index[i] for i in range(len(video_tabs)) if i in results_by_index]

        if skipped_count > 0:
            log_message(f"=== スキップ・失敗統計 ===", "INFO")
            log_message(f"  - {skipped_count}個の動画がスキップまたは失敗しました", "INFO")

        if self.is_first_run_in_session:
            self.is_first_run_in_session = False
            log_message("初回バッチ完了: 次回より待機時間を短縮(15秒)します", "DEBUG")

        return results

    def _open_video_tabs(self, videos: List[VideoInfo]) -> List[Dict]:
        """動画タブを一括で開く（Selenium new_window方式・2パス化版、S03九訂）。
        1パス目で全動画のタブを開いて遷移だけ済ませ（待たない）、2パス目で
        一時停止・記録を行う。1パス目の間、Chrome側では他タブの読み込みが
        バックグラウンドで並行して進むため、2パス目に戻ってきた頃には
        読み込みが進んでいる分だけ待ち時間が縮む想定（越智さんの実機ログ分析
        より、固定sleep(1.5)と無意味なタブ切替往復が1本あたり計約3.5秒の
        無駄になっていたため、あわせて削除）。"""
        tabs_data = []

        def _safe_handles():
            try:
                return self.driver.window_handles
            except Exception as e:
                log_message(f"TAB_OPEN_DIAG_ERROR|stage=safe_handles|error={type(e).__name__}:{e}", "WARNING")
                return []

        def _safe_current_handle():
            try:
                return self.driver.current_window_handle
            except Exception as e:
                return f"ERROR:{type(e).__name__}"

        def _log_tab_open_diag(stage: str, video: Optional[VideoInfo] = None, handle: str = ""):
            try:
                handles = _safe_handles()
                current_handle = _safe_current_handle()
                alive = handle in handles if handle else None
                current_url = ""
                current_title = ""
                try:
                    current_url = self.driver.current_url
                    current_title = self.driver.title
                except Exception as page_error:
                    current_url = f"ERROR:{type(page_error).__name__}"
                    current_title = ""
                video_id = getattr(video, 'video_id', '') if video else ''
                log_message(
                    f"TAB_OPEN_DIAG|stage={stage}|video={video_id[:12]}|handle={str(handle)[:8]}|alive={alive}|handles_count={len(handles)}|current={str(current_handle)[:8]}|url={current_url[:120]}|title={current_title[:80]}",
                    "INFO"
                )
            except Exception as e:
                log_message(f"TAB_OPEN_DIAG_ERROR|stage={stage}|error={type(e).__name__}:{e}", "WARNING")

        try:
            original_handle = self.driver.current_window_handle
        except:
            original_handle = None

        _log_tab_open_diag("start", None, original_handle or "")
        
        # === 1パス目: 全動画のタブを開いて遷移だけ済ませる（待たない） ===
        opened = []
        for i, video in enumerate(videos):
            if check_user_input() == 'cancel':
                break

            try:
                before_handles = set(_safe_handles())
                _log_tab_open_diag("before_new_window", video, "")

                self.driver.switch_to.new_window('tab')
                new_tab_handle = self.driver.current_window_handle
                new_handles = self.driver.window_handles
                new_count = len(set(new_handles) - before_handles)
                _log_tab_open_diag("after_new_window", video, new_tab_handle)
                log_message(
                    f"TAB_OPEN_DIAG|stage=new_window_delta|video={video.video_id[:12]}|new_count={new_count}|before={len(before_handles)}|after={len(new_handles)}|handle={str(new_tab_handle)[:8]}",
                    "INFO"
                )

                target_url = create_youtube_url_with_no_autoplay(video.url)
                self.driver.get(target_url)
                _log_tab_open_diag("after_driver_get", video, new_tab_handle)

                opened.append({'video_info': video, 'tab_handle': new_tab_handle, 'playlist_order': i})

            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ["read timed out", "httpconnectionpool", "max retries exceeded", "no such window", "invalid session id"]):
                    fatal_msg = f"FATAL: タブ作成中に致命的異常を検知: {err_str}"
                    log_message(f"🚨 {fatal_msg}", "ERROR")
                    raise Exception(fatal_msg)
                log_message(f"タブ作成エラー(index={i}, 非FATAL): {e}", "ERROR")
                _log_tab_open_diag("tab_create_exception", video, "")

        # === 2パス目: 各タブに戻り、一時停止・記録を行う ===
        # （1パス目の間にChrome側で他タブの読み込みが並行して進んでいる想定）
        for entry in opened:
            if check_user_input() == 'cancel':
                break

            video = entry['video_info']
            new_tab_handle = entry['tab_handle']
            try:
                self.driver.switch_to.window(new_tab_handle)
                _log_tab_open_diag("after_switch_back_to_new_tab", video, new_tab_handle)

                self.driver.execute_script("""
                    document.querySelectorAll('video').forEach(v => { v.pause(); v.load(); });
                    document.querySelectorAll('audio').forEach(a => { a.pause(); a.load(); });
                """)
                _log_tab_open_diag("after_media_pause_load", video, new_tab_handle)

                tabs_data.append({
                    'video_info': video,
                    'tab_handle': new_tab_handle,
                    'playlist_order': entry['playlist_order'],
                    'status': 'opened'
                })

                self.tab_tracker.record_youtube_tab(video.video_id, new_tab_handle, video.title)
                log_message(f"動画タブ作成成功: {video.title[:30]}...", "DEBUG")
                _log_tab_open_diag("after_append_tabs_data", video, new_tab_handle)

            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ["read timed out", "httpconnectionpool", "max retries exceeded", "no such window", "invalid session id"]):
                    fatal_msg = f"FATAL: タブ作成中に致命的異常を検知: {err_str}"
                    log_message(f"🚨 {fatal_msg}", "ERROR")
                    raise Exception(fatal_msg)
                log_message(f"タブ作成エラー(index={entry['playlist_order']}, 非FATAL): {e}", "ERROR")
                _log_tab_open_diag("tab_create_exception", video, "")

        if original_handle:
            try:
                self.driver.switch_to.window(original_handle)
            except:
                pass

        for idx, tab_info in enumerate(tabs_data, start=1):
            _log_tab_open_diag("final_tabs_data_alive_check", tab_info.get('video_info'), tab_info.get('tab_handle', ''))
            log_message(
                f"TAB_OPEN_DIAG|stage=final_tabs_data_summary|idx={idx}|total={len(tabs_data)}|handle={str(tab_info.get('tab_handle', ''))[:8]}|video={getattr(tab_info.get('video_info'), 'video_id', '')[:12]}",
                "INFO"
            )
            
        return tabs_data

    def _reuse_video_tabs(self, batch_videos: List[VideoInfo]) -> List[Dict]:
        """プール内のタブを再利用"""
        video_tabs = []
        try:
            current_handles = set(self.driver.window_handles)
            valid_pool = []
            dead_count = 0
            for handle in self.youtube_tabs_pool:
                if handle in current_handles:
                    valid_pool.append(handle)
                else:
                    dead_count += 1
            if dead_count > 0:
                log_message(f"♻️ プール内から無効なタブ {dead_count}個 を除去しました", "WARNING")
            self.youtube_tabs_pool = valid_pool
        except Exception as e:
            log_message(f"タブプール診断中にエラー(無視): {e}", "WARNING")

        log_message(f"♻️ モード3: 動画タブの再利用を開始します (必要数: {len(batch_videos)} / プール数: {len(self.youtube_tabs_pool)})", "INFO")
        
        for i, video in enumerate(batch_videos):
            if not self.youtube_tabs_pool: break
            handle = self.youtube_tabs_pool.pop(0)
            try:
                self.driver.switch_to.window(handle)
                self.driver.get(video.url)
                video_tabs.append({'video_info': video, 'tab_handle': handle})
            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ["read timed out", "httpconnectionpool", "max retries exceeded", "no such window"]):
                    fatal_msg = f"FATAL: タブ再利用中に致命的異常を検知: {err_str}"
                    log_message(f"🚨 {fatal_msg}", "ERROR")
                    raise Exception(fatal_msg)
                log_message(f"タブ再利用中にエラー発生(非FATAL): {e}", "ERROR")
                continue
        return video_tabs

    def _cleanup_batch_tabs(self, video_tabs: List[Dict], glasp_results: List[Dict], browser_mode: int):
        """バッチ終了時のクリーンアップ"""
        if browser_mode == 3:
            for tab in video_tabs:
                h = tab.get('tab_handle')
                if h and h not in self.youtube_tabs_pool:
                    self.youtube_tabs_pool.append(h)
            log_message(f"♻️ モード3: {len(video_tabs)}個の動画タブをプールに返却しました（現在合計: {len(self.youtube_tabs_pool)}）", "DEBUG")
        else:
            for tab in video_tabs:
                h = tab.get('tab_handle')
                if not h: continue
                try:
                    if self.driver and h in self.driver.window_handles:
                        self.driver.switch_to.window(h)
                        self.driver.close()
                except Exception: pass

        for glasp_res in glasp_results:
            h = glasp_res.get('glasp_handle')
            if not h: continue
            try:
                if self.driver and h in self.driver.window_handles:
                    self.driver.switch_to.window(h)
                    self.driver.close()
            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ["read timed out", "httpconnectionpool", "max retries exceeded"]):
                    log_message(f"🚨 クリーンアップ中に通信異常(非致命的として続行): {err_str}", "WARNING")

        try:
            if self.driver:
                all_h = self.driver.window_handles
                if not hasattr(self, 'main_window_handle') or not self.main_window_handle or self.main_window_handle not in all_h:
                    if all_h: self.main_window_handle = all_h[0]
                if self.main_window_handle:
                    self.driver.switch_to.window(self.main_window_handle)
        except Exception: pass


    def _check_transcript_availability(self, tab_handle: str) -> Tuple[bool, str]:
        """トランスクリプト存在確認（タブ生存診断ログ追加版）"""
        original_timeout = 60.0
        temp_timeout = 15.0

        def _safe_handles():
            try:
                return self.driver.window_handles
            except Exception as e:
                log_message(f"TRANSCRIPT_DIAG_ERROR|stage=safe_handles|error={type(e).__name__}:{e}", "WARNING")
                return []

        def _safe_current_handle():
            try:
                return self.driver.current_window_handle
            except Exception as e:
                return f"ERROR:{type(e).__name__}"

        def _log_transcript_diag(stage: str, attempt: int = 0, result: Optional[Dict] = None, note: str = ""):
            try:
                handles = _safe_handles()
                current_handle = _safe_current_handle()
                alive = tab_handle in handles if tab_handle else None
                current_url = ""
                current_title = ""
                try:
                    current_url = self.driver.current_url
                    current_title = self.driver.title
                except Exception as page_error:
                    current_url = f"ERROR:{type(page_error).__name__}"
                    current_title = ""

                available = ""
                reason = ""
                if isinstance(result, dict):
                    available = str(result.get("available", ""))
                    reason = str(result.get("reason", ""))

                log_message(
                    f"TRANSCRIPT_DIAG|stage={stage}|attempt={attempt}|handle={str(tab_handle)[:8]}|alive={alive}|handles_count={len(handles)}|current={str(current_handle)[:8]}|available={available}|reason={reason[:60]}|note={note[:80]}|url={current_url[:120]}|title={current_title[:80]}",
                    "INFO"
                )
            except Exception as e:
                log_message(f"TRANSCRIPT_DIAG_ERROR|stage={stage}|error={type(e).__name__}:{e}", "WARNING")

        # [計測] 直近のゲート判定の内訳を保持する。呼び出し側（_trigger_glasp_click）が
        # 動画番号と紐付けてGLASP_MEASURE_GATE行として出力するための受け渡し用。
        # 判定ロジックそのものには影響しない。
        self._last_transcript_measure: Dict = {'captured': False}

        _log_transcript_diag("start")
        try:
            try:
                if hasattr(self.driver.command_executor, '_client_config'):
                    self.driver.command_executor._client_config.timeout = temp_timeout
                elif hasattr(self.driver, 'command_executor'):
                    self.driver.command_executor.set_timeout(temp_timeout)
                _log_transcript_diag("after_timeout_shortened", note=f"temp_timeout={temp_timeout}")
            except Exception as timeout_error:
                _log_transcript_diag("timeout_shortening_error", note=str(timeout_error))

            _log_transcript_diag("before_switch_to_video_tab")
            self.driver.switch_to.window(tab_handle)
            _log_transcript_diag("after_switch_to_video_tab")

            for attempt in range(1, 3):
                _log_transcript_diag("before_transcript_script", attempt=attempt)
                result = self.driver.execute_script("""
                    const captions = window.ytInitialPlayerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
                    const hasApiCaptions = captions && captions.length > 0;
                    const segs = document.querySelectorAll('ytd-transcript-segment-renderer');
                    const hasTranscriptSegments = segs.length > 0;
                    // --- ここから下は計測用の付加情報。available/reason の算出には関与しない ---
                    let segTextLength = 0;
                    try {
                        const sampleMax = Math.min(segs.length, 40);
                        for (let i = 0; i < sampleMax; i++) {
                            segTextLength += ((segs[i].innerText) || '').length;
                        }
                    } catch (e) { segTextLength = -1; }
                    let panelOpen = false;
                    try {
                        panelOpen = !!document.querySelector('ytd-transcript-renderer');
                    } catch (e) { panelOpen = false; }
                    return {
                        available: hasApiCaptions || hasTranscriptSegments,
                        reason: hasApiCaptions ? 'API確認OK' : (hasTranscriptSegments ? 'UI要素検出' : '未検出'),
                        measureApiCaptions: !!hasApiCaptions,
                        measureSegments: !!hasTranscriptSegments,
                        measureSegmentCount: segs.length,
                        measureSegmentTextLength: segTextLength,
                        measurePanelPresent: panelOpen,
                        measureTrackCount: captions ? captions.length : 0
                    };
                """)
                _log_transcript_diag("after_transcript_script", attempt=attempt, result=result)

                # [計測] 判定の内訳を記録する（判定そのものは上のJSの available をそのまま使う）
                try:
                    if isinstance(result, dict):
                        self._last_transcript_measure = {
                            'captured': True,
                            'gate_attempt': attempt,
                            'available': bool(result.get('available')),
                            'api': bool(result.get('measureApiCaptions')),
                            'seg': bool(result.get('measureSegments')),
                            'seg_count': result.get('measureSegmentCount', -1),
                            'seg_len': result.get('measureSegmentTextLength', -1),
                            'panel': bool(result.get('measurePanelPresent')),
                            'tracks': result.get('measureTrackCount', -1),
                        }
                except Exception as measure_error:
                    log_message(f"GLASP_MEASURE_ERROR|stage=gate_capture|error={measure_error}", "WARNING")

                if result['available']:
                    _log_transcript_diag("return_available_true", attempt=attempt, result=result)
                    return True, result['reason']

                if attempt == 1 and not result['available']:
                    try:
                        _log_transcript_diag("before_transcript_button_search", attempt=attempt, result=result)
                        buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[aria-label*='文字起こし'], button[aria-label*='Transcript']")
                        clicked = False
                        for btn in buttons:
                            if btn.is_displayed():
                                btn.click()
                                clicked = True
                                break
                        _log_transcript_diag("after_transcript_button_search", attempt=attempt, result=result, note=f"buttons={len(buttons)},clicked={clicked}")
                    except Exception as button_error:
                        _log_transcript_diag("transcript_button_search_error", attempt=attempt, result=result, note=str(button_error))
                    time.sleep(0.5)

            _log_transcript_diag("return_no_transcript", attempt=2, note="字幕データなし")
            return False, "字幕データなし"
        except Exception as e:
            _log_transcript_diag("exception", note=str(e))
            err_str = str(e).lower()
            if any(k in err_str for k in ["read timed out", "timed out", "httpconnectionpool", "max retries exceeded"]):
                fatal_msg = f"FATAL: トランスクリプト確認中に通信途絶(15s): {err_str}"
                log_message(f"🚨 {fatal_msg}", "ERROR")
                raise Exception(fatal_msg)
            log_message(f"トランスクリプト確認エラー(非FATAL): {e}", "WARNING")
            return False, str(e)
        finally:
            try:
                if hasattr(self.driver.command_executor, '_client_config'):
                    self.driver.command_executor._client_config.timeout = original_timeout
                elif hasattr(self.driver, 'command_executor'):
                    self.driver.command_executor.set_timeout(original_timeout)
                _log_transcript_diag("finally_timeout_restored", note=f"original_timeout={original_timeout}")
            except Exception as restore_error:
                log_message(f"TRANSCRIPT_DIAG_ERROR|stage=finally_timeout_restore_error|error={type(restore_error).__name__}:{restore_error}", "WARNING")

    def _get_chrome_main_memory(self) -> float:
        import psutil
        try:
            max_memory = 0
            for proc in psutil.process_iter(['name', 'memory_info']):
                try:
                    if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                        memory_mb = proc.info['memory_info'].rss / 1024 / 1024
                        if memory_mb > max_memory: max_memory = memory_mb
                except: continue
            return max_memory
        except: return 0

    def _restart_chrome_if_memory_high(self) -> bool:
        main_memory = self._get_chrome_main_memory()
        if main_memory > 5000:
            log_message(f"⚠️ メモリ超過（{main_memory:.1f}MB） - Chrome再起動", "WARNING")
            try:
                self.driver.quit()
                time.sleep(3)
                import psutil
                for proc in psutil.process_iter(['name']):
                    try:
                        if 'chrome' in proc.info['name'].lower(): proc.kill()
                    except: pass
                time.sleep(3)
                self.driver = self.browser.driver
                return True
            except Exception as e:
                raise
        return False


    def _quick_success_check(self) -> bool:
        """Glaspタブ早期成功判定

        [S03十訂] 実機ログで、本来11秒前後（高速チェック3秒+本関数最大8秒）で
        終わるはずの確認処理が37〜43秒かかるケースが見つかった。sleep()の合計
        だけでは説明できない差分のため、Selenium経由のブラウザ呼び出し
        （find_elements/execute_script）自体が特定のタブでだけ遅くなっている
        疑いがある。原因特定のため、各呼び出しの所要時間をPERFログに残す。
        あわせて、経過時間の合計がmax_total_waitを超えたら、固定回数の
        wait_intervalsを消化しきる前に打ち切る安全弁を追加する
        （個々の呼び出しがブロックしている間は止められないが、遅い呼び出しが
        複数回積み重なって際限なく伸びるのは防げる）。
        """
        func_start_time = time.time()
        max_total_wait = 15.0
        try:
            if 'gemini.google.com' not in self.driver.current_url:
                return False

            config_quick = config_manager.get('glasp.quick_check', {})
            wait_intervals = config_quick.get('wait_intervals', [1.0, 2.0, 2.0, 2.0, 1.0])

            for iteration_index, wait_time in enumerate(wait_intervals):
                if check_user_input() == 'cancel':
                    return False

                elapsed_so_far = time.time() - func_start_time
                if elapsed_so_far > max_total_wait:
                    log_message(
                        f"QUICK_CHECK_WALLCLOCK_ABORT|elapsed={elapsed_so_far:.3f}|max_total_wait={max_total_wait}|iteration={iteration_index}",
                        "WARNING"
                    )
                    return False

                # [S03十二訂] 従来はfind_elements()で吹き出し/入力欄を検索していたが、
                # driver.implicitly_wait(5.0)の影響で、一致する要素が無いたびに毎回
                # 5秒ブロックしていたことが計測ログで判明した（本関数がループする
                # たびに積み重なり、確認処理全体が37〜43秒ハングする原因になっていた）。
                # 同じ「プロンプト分割エラー」検知は本ファイル内の別箇所（要約完了待ち
                # ロジック）で既にexecute_script(querySelectorAll)方式に置き換え済みで、
                # 暗黙の待機の影響を受けない。ここも同じ方式に統一する。
                prompt_scan_start = time.time()
                try:
                    split_error_probe = self.driver.execute_script("""
                        function textOf(el) {
                            return (el.innerText || el.value || '').trim();
                        }
                        const userMsgs = Array.from(document.querySelectorAll(".user-query, [data-test-id='user-query'], .message-user, .query-text"));
                        const inputAreas = Array.from(document.querySelectorAll("div[contenteditable='true'], #text-input, textarea"));
                        const checkContents = userMsgs.map(el => [textOf(el), "吹き出し"])
                            .concat(inputAreas.map(el => [textOf(el), "入力欄"]));
                        const tags = ["<ContentTitle>", "<Transcript>", "URL:", "http"];
                        for (const [text, source] of checkContents) {
                            if (!text) continue;
                            for (const tag of tags) {
                                if (text.startsWith(tag)) {
                                    return { hit: true, tag: tag, source: source };
                                }
                            }
                        }
                        return { hit: false };
                    """)
                    if isinstance(split_error_probe, dict) and split_error_probe.get('hit'):
                        log_message(
                            f"⚠️ Gemini入力異常({split_error_probe.get('source')})検知: '{split_error_probe.get('tag')}'。即時復帰します。",
                            "WARNING"
                        )
                        raise Exception("Gemini Prompt Split Error")
                except Exception as e:
                    if "Gemini Prompt Split Error" in str(e):
                        raise e
                finally:
                    perf_log("quick_check_prompt_scan", prompt_scan_start, iteration=iteration_index)

                time.sleep(wait_time)

                dom_probe_start = time.time()
                check_result = self.driver.execute_script("""
                    const bodyText = document.body ? document.body.innerText : '';
                    const lowerText = bodyText.toLowerCase();

                    const inputAreas = Array.from(document.querySelectorAll('div[contenteditable="true"], #text-input, textarea'));
                    const inputText = inputAreas.map(el => (el.innerText || el.value || '')).join('\\n');

                    const hasPromptInInput =
                        inputText.includes('<Transcript>') ||
                        inputText.includes('</Transcript>') ||
                        inputText.includes('<ContentTitle>') ||
                        inputText.includes('URL:') ||
                        inputText.includes('http');

                    const hasTranscriptInPage =
                        bodyText.includes('</Transcript>') ||
                        bodyText.includes('<Transcript>');

                    const hasTranscript = hasTranscriptInPage || hasPromptInInput;

                    // [20260808] 「私はロボットではありません」等の確認画面の検知。
                    // 突破は行わない（そういう性質のものではない）。検知したら
                    // 呼び出し側が処理全体を速やかに中止するための信号として返す。
                    // 無人実行中に出た場合、叩き続けると状況が悪化するだけなので、
                    // 早く諦めて次の実行時刻に回す方が安全である。
                    const challengeMarkers = [
                        'recaptcha', 'ロボットではありません', "i'm not a robot",
                        '通常と異なるトラフィック', 'unusual traffic',
                        'システムによって', 'verify it', 'ご本人確認', '本人確認'
                    ];
                    const hasChallenge =
                        challengeMarkers.some(k => lowerText.includes(k.toLowerCase())) ||
                        document.querySelector('iframe[src*="recaptcha"]') !== null ||
                        document.querySelector('iframe[title*="reCAPTCHA"]') !== null;

                    const criticalErrors = ['error occurred', 'something went wrong', 'エラーが発生', '生成に失敗'];
                    const ambiguousErrors = ['failed', '失敗しました', '利用できません', 'try again', 'もう一度', '再試行'];

                    let hasError = criticalErrors.some(k => lowerText.includes(k.toLowerCase()));
                    if (!hasError && !hasTranscript) {
                        hasError = ambiguousErrors.some(k => lowerText.includes(k.toLowerCase()));
                    }

                    const hasLoadingIndicator =
                        lowerText.includes('generating') ||
                        lowerText.includes('生成中') ||
                        document.querySelector('[aria-label*="Stop"]') !== null ||
                        document.querySelector('[aria-label*="停止"]') !== null ||
                        document.querySelector('[aria-busy="true"]') !== null;

                    // [20260807] プロンプトが指示する終了マーカーは「■要約完了」。
                    // 「■要約終了」しか見ていなかったため両方を許容する。
                    const normBodyText = bodyText.replace(/[ 　]/g, '');
                    const rawSummaryPattern =
                        bodyText.includes('■ タイトル') ||
                        bodyText.includes('▪ タイトル') ||
                        normBodyText.includes('■要約完了') ||
                        normBodyText.includes('■要約終了');

                    const hasSummaryPattern =
                        rawSummaryPattern &&
                        !hasPromptInInput &&
                        bodyText.length >= 300;

                    let kicked = false;
                    let kickMethod = '';

                    function isClickableButton(btn) {
                        if (!btn) return false;
                        const ariaDisabled = btn.getAttribute('aria-disabled') === 'true';
                        const rect = btn.getBoundingClientRect();
                        return !btn.disabled && !ariaDisabled && rect.width > 0 && rect.height > 0;
                    }

                    function findSendButton() {
                        const selectors = [
                            'button[aria-label*="プロンプトを送信"]',
                            'button[aria-label*="送信"]',
                            'button[aria-label*="Send"]',
                            'button[aria-label*="send"]'
                        ];

                        for (const selector of selectors) {
                            const btn = document.querySelector(selector);
                            if (isClickableButton(btn)) {
                                return { button: btn, method: selector };
                            }
                        }

                        const iconSelectors = [
                            'mat-icon[fonticon="arrow_upward"]',
                            'mat-icon[data-mat-icon-name="arrow_upward"]',
                            'mat-icon[fonticon="send"]',
                            'mat-icon[data-mat-icon-name="send"]'
                        ];

                        for (const selector of iconSelectors) {
                            const icon = document.querySelector(selector);
                            const btn = icon ? icon.closest('button') : null;
                            if (isClickableButton(btn)) {
                                return { button: btn, method: selector };
                            }
                        }

                        return { button: null, method: 'not_found' };
                    }

                    if (hasTranscript && !hasLoadingIndicator && !hasSummaryPattern && !hasError) {
                        const found = findSendButton();
                        if (found.button) {
                            found.button.click();
                            kicked = true;
                            kickMethod = found.method;
                        }
                    }

                    const inputClearedAndGenerating =
                        hasTranscriptInPage &&
                        !hasPromptInInput &&
                        hasLoadingIndicator;

                    return {
                        hasError: hasError,
                        hasChallenge: hasChallenge,
                        hasTranscript: hasTranscript,
                        hasTranscriptInPage: hasTranscriptInPage,
                        hasPromptInInput: hasPromptInInput,
                        rawSummaryPattern: rawSummaryPattern,
                        hasSummaryPattern: hasSummaryPattern,
                        hasLoadingIndicator: hasLoadingIndicator,
                        inputClearedAndGenerating: inputClearedAndGenerating,
                        kicked: kicked,
                        kickMethod: kickMethod,
                        bodyLength: bodyText.length,
                        inputLength: inputText.length,
                        // [20260808] 判定が外れたときに「そのページに何が書いてあったか」を
                        // 追えるようにする。20260808はこれが無かったため、確認画面が
                        // エラー扱いされた理由を後から特定できなかった。
                        bodyTextSample: bodyText.slice(0, 200).replace(/\\s+/g, ' ')
                    };
                """)
                perf_log("quick_check_dom_probe", dom_probe_start, iteration=iteration_index)

                # [20260808] 確認画面（reCAPTCHA等）を検知したら、処理全体を中止する。
                # 無人実行中は誰も応答できないため、叩き続けても状況が悪化するだけで
                # あり、アカウントへの負荷も増す。FATALとして送出し、上位で
                # 「今回は諦めて次の実行時刻に回す」判断ができるようにする。
                if check_result.get('hasChallenge', False):
                    raise Exception(
                        "FATAL: CHALLENGE_DETECTED: Googleの確認画面（reCAPTCHA等）が"
                        "表示されました。自動での続行は行いません。"
                    )

                if check_result['hasError']:
                    # [20260808] ここで静かにFalseを返していたため、確認画面が
                    # 「ただのエラー」として処理され、原因が分からないまま
                    # リトライが繰り返された。何を見てエラーと判断したのかを残す。
                    log_message(
                        "QUICK_SUCCESS_ERROR_EXIT|"
                        f"bodyLength={check_result.get('bodyLength', 0)}|"
                        f"inputLength={check_result.get('inputLength', 0)}|"
                        f"hasChallenge={check_result.get('hasChallenge')}|"
                        f"body='{str(check_result.get('bodyTextSample', ''))[:200]}'",
                        "WARNING"
                    )
                    return False

                if (
                    check_result.get('rawSummaryPattern', False)
                    and check_result.get('hasPromptInInput', False)
                    and not check_result.get('hasSummaryPattern', False)
                ):
                    log_message(
                        f"QUICK_SUCCESS_BLOCKED|reason=summary_pattern_inside_input_prompt|hasPromptInInput={check_result.get('hasPromptInInput')}|bodyLength={check_result.get('bodyLength', 0)}|inputLength={check_result.get('inputLength', 0)}",
                        "WARNING"
                    )

                if check_result['hasSummaryPattern']:
                    log_message("QUICK_SUCCESS_RETURN|reason=summary_pattern", "INFO")
                    return True

                if check_result['kicked']:
                    log_message(
                        f"GEMINI_SEND_BUTTON_CLICKED|source=quick_success_check|method={check_result.get('kickMethod', '')}|inputLength={check_result.get('inputLength', 0)}",
                        "INFO"
                    )
                    log_message("QUICK_SUCCESS_RETURN|reason=send_button_clicked", "INFO")
                    return True

                if check_result.get('inputClearedAndGenerating', False):
                    log_message("QUICK_SUCCESS_RETURN|reason=input_cleared_and_generation_started", "INFO")
                    return True

                if check_result['hasTranscript']:
                    log_message(
                        f"QUICK_SUCCESS_WAIT|reason=pending_prompt_or_not_generating|hasPromptInInput={check_result.get('hasPromptInInput')}|hasLoadingIndicator={check_result.get('hasLoadingIndicator')}|bodyLength={check_result.get('bodyLength', 0)}|inputLength={check_result.get('inputLength', 0)}",
                        "INFO"
                    )
                    continue

            return False

        except Exception as e:
            if "Gemini Prompt Split Error" in str(e):
                raise e
            return False

    def _emergency_cleanup(self):
        log_message("🚨 緊急クリーンアップ発動: プロセス強制終了", "WARNING")
        try:
            kill_target_chrome_processes()
            log_message("⚔️ OSコマンドでChrome関連プロセスを強制終了しました", "PROCESS")
        except: pass
        try: self.driver = None
        except: pass
        time.sleep(5.0)


    def _trigger_glasp_click(self, tab_info: Dict, playlist_position: int, attempt_index: int,
                              timeout_threshold: float = 10.0, input_mode: str = 'js_click',
                              round_label: str = "?", prepare_only: bool = False) -> Dict:
        """
        [ADR-0001、S03再修正] Glasp起動の「クリック処理」のみを行う（タブ準備確認〜きらきらボタンクリックまで）。
        Geminiタブの検出待ちは行わない（検出は_wait_for_new_glasp_handle/_confirm_glasp_successへ分離）。

        戻り値:
          {'ok': True, 'before_handles': set, 'trigger_method': str}
              … クリック送信まで成功。before_handlesを_wait_for_new_glasp_handleに渡すこと。
          {'ok': False, 'permanent': True, 'error': str}
              … 字幕データなし等、リトライしても無駄な恒久的失敗（現行仕様と同じ扱い）。
          {'ok': False, 'permanent': False, 'error': str, 'needs_refresh': bool}
              … リトライ可能な失敗（診断用フラグ。S03再修正でrefreshは廃止したため
                 呼び出し側では使用しない）。
        FATAL（通信途絶等）を検知した場合はそのままraiseして上位に伝播する（現行仕様を踏襲）。
        """
        import time
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.keys import Keys

        video_info_obj = tab_info.get('video_info') if isinstance(tab_info, dict) else None
        video_id_for_log = getattr(video_info_obj, 'video_id', '') if video_info_obj else ''

        def _perf_step(step_name: str, start_time: float, **fields):
            """Glasp起動内の工程別PERFログを出力する（診断専用・処理ロジック非変更）。"""
            try:
                perf_log(
                    "glasp_step",
                    start_time,
                    video_idx=playlist_position,
                    video_id=video_id_for_log[:12],
                    attempt=attempt_index + 1,
                    step=step_name,
                    **fields
                )
            except Exception as e:
                log_message(f"PERF_STEP_ERROR|video_idx={playlist_position}|step={step_name}|error={e}", "WARNING")

        def _safe_window_handles():
            try:
                return self.driver.window_handles
            except:
                return []

        # [計測] 前の動画の判定内訳が残ったまま次の動画の記録として拾われないよう、
        # クリック処理に入る時点で必ず初期化する（判定ロジックには無関係）。
        self._last_transcript_measure = {'captured': False}

        click_phase_start = time.time()
        try:
            step_start = time.time()
            self.driver.switch_to.window(tab_info["tab_handle"])
            video_tab_ready = False
            ready_reason = "timeout"
            wait_elapsed = 0.0
            tab_ready_start = time.time()
            while time.time() - tab_ready_start < 4.0:
                wait_elapsed = time.time() - tab_ready_start
                try:
                    ready_result = self.driver.execute_script("""
                        const readyState = document.readyState || '';
                        const videoCount = document.querySelectorAll('video').length;
                        const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
                        const bodyLength = bodyText.trim().length;
                        const hasOwner = !!document.querySelector('#owner, #owner-sub-count');
                        const hasPlayer = !!document.querySelector('#movie_player, ytd-player, video');
                        document.querySelectorAll('video').forEach(v => { if (!v.paused) v.pause(); });
                        return {
                            readyState: readyState,
                            videoCount: videoCount,
                            bodyLength: bodyLength,
                            hasOwner: hasOwner,
                            hasPlayer: hasPlayer
                        };
                    """)
                    if isinstance(ready_result, dict):
                        if ready_result.get("videoCount", 0) > 0 or ready_result.get("hasPlayer") or ready_result.get("bodyLength", 0) > 300:
                            video_tab_ready = True
                            ready_reason = f"dom_ready:{ready_result}"
                            break
                        if ready_result.get("readyState") == "complete" and ready_result.get("bodyLength", 0) > 100:
                            video_tab_ready = True
                            ready_reason = f"document_complete:{ready_result}"
                            break
                except Exception as tab_ready_error:
                    ready_reason = f"check_error:{type(tab_ready_error).__name__}:{str(tab_ready_error)[:80]}"
                time.sleep(0.2)
            _perf_step(
                "video_tab_switch",
                step_start,
                handle=str(tab_info.get("tab_handle", ""))[:8],
                handles_count=len(_safe_window_handles()),
                ready=bool(video_tab_ready),
                ready_reason=str(ready_reason)[:160],
                wait_elapsed=round(wait_elapsed, 3)
            )

            if time.time() - click_phase_start > timeout_threshold:
                raise Exception("Slow Tab Detected (Click Phase)")

            step_start = time.time()
            has_transcript, reason = self._check_transcript_availability(tab_info["tab_handle"])

            # [計測] 「字幕が存在するという宣言(api)だけで通過したのか、
            #   実際に描画された文字起こし行(seg)まで揃って通過したのか」を1行で記録する。
            #   Glaspをクリックする直前の状態であり、後段のGeminiが空になる現象との
            #   相関を見るための材料。判定・分岐には一切使用しない。
            try:
                m = getattr(self, '_last_transcript_measure', None) or {}
                if isinstance(tab_info, dict):
                    tab_info['last_gate_measure'] = dict(m)
                measure_log(
                    "GLASP_MEASURE_GATE|"
                    f"round={round_label}|attempt={attempt_index + 1}|"
                    f"video_idx={playlist_position}|video_id={video_id_for_log[:12]}|"
                    f"pass={bool(has_transcript)}|api={m.get('api')}|seg={m.get('seg')}|"
                    f"seg_count={m.get('seg_count')}|seg_len={m.get('seg_len')}|"
                    f"panel={m.get('panel')}|tracks={m.get('tracks')}|"
                    f"gate_attempt={m.get('gate_attempt')}|captured={m.get('captured', False)}"
                )
            except Exception as measure_error:
                log_message(f"GLASP_MEASURE_ERROR|stage=gate_log|error={measure_error}", "WARNING")

            if not has_transcript:
                _perf_step("video_ready_check", step_start, success=False, reason=reason)
                log_message(f"動画{playlist_position}: {reason} - Glaspスキップ", "INFO")
                _perf_step("trigger_total", click_phase_start, success=False, reason="no_transcript")
                return {'ok': False, 'permanent': True, 'error': reason}

            wait_time = 60 if (self.is_first_run_in_session and attempt_index == 0) else 15
            youtube_handler = YouTubeHandler(self.driver)
            video_ready = youtube_handler.wait_for_youtube_video_ready(timeout=wait_time)
            refreshed = False
            if not video_ready:
                try:
                    self.driver.refresh()
                    refreshed = True
                    self._ensure_tab_ready(tab_info["tab_handle"], timeout=wait_time)
                    video_ready = youtube_handler.wait_for_youtube_video_ready(timeout=wait_time)
                except:
                    pass
            _perf_step(
                "video_ready_check",
                step_start,
                success=bool(video_ready),
                wait_time=wait_time,
                refreshed=refreshed
            )
            if not video_ready:
                raise Exception(f"動画読み込み未完了 (待機: {wait_time}秒)")

            step_start = time.time()
            sub_status = "not_run"
            sub_text = ""
            try:
                sub_script = """
                    const el = document.querySelector('#owner-sub-count');
                    if (!el) return { status: 'missing', text: '' };
                    const text = el.innerText || '';
                    if (text.trim() === '') return { status: 'empty', text: text };
                    return { status: 'success', text: text.trim() };
                """
                sub_result = self.driver.execute_script(sub_script)
                if isinstance(sub_result, dict):
                    sub_status = sub_result.get('status', 'unknown')
                    sub_text = sub_result.get('text', '')
                    log_message(f"  ∟ [DEBUG] 登録者数DOM状態: status={sub_status}, text='{sub_text}'", "DEBUG")
                    if sub_status == 'success' and video_info_obj and not getattr(video_info_obj, 'subscriber_count', ''):
                        video_info_obj.subscriber_count = sub_text
            except Exception as e:
                sub_status = "js_error"
                log_message(f"  ∟ [DEBUG] 登録者数取得JSエラー: {e}", "DEBUG")
            _perf_step(
                "subscriber_dom_check",
                step_start,
                status=sub_status,
                has_text=bool(sub_text)
            )

            step_start = time.time()
            already_paused = False
            pre_pause_status = "unknown"
            pre_pause_sleep = 0.0
            try:
                pause_state = self.driver.execute_script("""
                    const videos = Array.from(document.querySelectorAll('video'));
                    if (videos.length === 0) {
                        return { status: 'no_video', paused: false, count: 0 };
                    }
                    const anyPlaying = videos.some(v => !v.paused);
                    const allPaused = videos.every(v => v.paused);
                    return {
                        status: 'success',
                        paused: allPaused,
                        anyPlaying: anyPlaying,
                        count: videos.length
                    };
                """)
                if isinstance(pause_state, dict):
                    already_paused = bool(pause_state.get("paused", False))
                    pre_pause_status = str(pause_state)
                else:
                    pre_pause_status = f"unexpected:{pause_state}"
            except Exception as pause_state_error:
                pre_pause_status = f"check_error:{type(pause_state_error).__name__}:{str(pause_state_error)[:80]}"

            if not already_paused:
                pre_pause_sleep = 2.0
                smart_sleep(2.0)

            pause_success = youtube_handler.pause_video(timeout=30)
            _perf_step(
                "video_pause",
                step_start,
                success=bool(pause_success),
                already_paused=bool(already_paused),
                pre_pause_sleep=pre_pause_sleep,
                pre_pause_status=str(pre_pause_status)[:160]
            )
            if not pause_success:
                raise Exception("動画制御不能（pause失敗）")

            # [20260808] prepare_only は1巡目用。ここまで（タブ切替・動画読込待ち・
            # 字幕確認・一時停止）は行い、Glaspのきらきらボタンだけ押さずに戻る。
            # 捨てるためのGeminiセッションを作らないようにするのが目的で、
            # 2巡目までに時間を置くという1巡目本来の効果はそのまま残る。
            if prepare_only:
                _perf_step("trigger_total", click_phase_start, success=True, reason="prepare_only")
                return {'ok': True, 'prepared': True, 'before_handles': set(), 'trigger_method': 'none'}

            before_handles = set(_safe_window_handles())
            step_start = time.time()
            trigger_setting = str(config_manager.get("glasp.trigger_method", "auto")).strip().lower()

            if trigger_setting not in ["auto", "cdp_button", "cdp_ctrl_x", "selenium_ctrl_x"]:
                log_message(
                    f"GLASP_TRIGGER_DIAG|stage=invalid_setting|value={trigger_setting}|fallback=auto",
                    "WARNING"
                )
                trigger_setting = "auto"

            ctrl_x_method = "cdp_button"
            glasp_trigger_method = "unknown"
            click_value = False
            try:
                def _send_cdp_button() -> bool:
                    click_result = self.driver.execute_cdp_cmd("Runtime.evaluate", {
                        "expression": """
                            (function() {
                                function findBtn(root) {
                                    const svg = root.querySelector('svg.lucide-sparkles');
                                    if (svg) return svg.closest('button');
                                    return null;
                                }
                                let target = findBtn(document);
                                if (!target) {
                                    for (const node of document.querySelectorAll('*')) {
                                        if (node.shadowRoot) { target = findBtn(node.shadowRoot); if (target) break; }
                                    }
                                }
                                if (target) { target.click(); return true; }
                                return false;
                            })()
                        """, "returnByValue": True
                    })
                    return bool(click_result.get('result', {}).get('value', False))

                def _send_cdp_mouse_click() -> bool:
                    point_result = self.driver.execute_cdp_cmd("Runtime.evaluate", {
                        "expression": """
                            (function() {
                                function findBtn(root) {
                                    const svg = root.querySelector('svg.lucide-sparkles');
                                    if (svg) return svg.closest('button');
                                    return null;
                                }
                                let target = findBtn(document);
                                if (!target) {
                                    for (const node of document.querySelectorAll('*')) {
                                        if (node.shadowRoot) { target = findBtn(node.shadowRoot); if (target) break; }
                                    }
                                }
                                if (!target) return null;
                                target.scrollIntoView({block: 'center', inline: 'center'});
                                const r = target.getBoundingClientRect();
                                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                            })()
                        """, "returnByValue": True
                    })
                    point = point_result.get('result', {}).get('value')
                    if not point:
                        return False
                    x, y = point['x'], point['y']
                    self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
                    self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
                    self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
                    return True

                def _send_selenium_ctrl_x():
                    self.browser.bring_chrome_to_front()
                    actions = ActionChains(self.driver)
                    try:
                        actions.move_to_element(self.driver.find_element(By.TAG_NAME, "body")).click().perform()
                    except:
                        pass
                    for _ in range(2):
                        actions.key_down(Keys.CONTROL).send_keys('x').key_up(Keys.CONTROL).perform()
                        time.sleep(0.1)

                def _send_cdp_ctrl_x():
                    for _ in range(2):
                        self.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": 2, "windowsVirtualKeyCode": 88, "nativeVirtualKeyCode": 88, "unmodifiedText": "x", "text": "x"})
                        self.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": 2, "windowsVirtualKeyCode": 88, "nativeVirtualKeyCode": 88, "unmodifiedText": "x", "text": "x"})
                        time.sleep(0.1)

                if trigger_setting == "cdp_button":
                    ctrl_x_method = "cdp_button"
                    click_value = _send_cdp_button()
                elif trigger_setting == "selenium_ctrl_x":
                    ctrl_x_method = "selenium_ctrl_x"
                    _send_selenium_ctrl_x()
                elif trigger_setting == "cdp_ctrl_x":
                    ctrl_x_method = "cdp_ctrl_x"
                    _send_cdp_ctrl_x()
                else:
                    if input_mode == 'trusted_mouse':
                        ctrl_x_method = "cdp_mouse"
                        click_value = _send_cdp_mouse_click()
                    else:
                        ctrl_x_method = "cdp_button"
                        click_value = _send_cdp_button()
                    if not click_value:
                        ctrl_x_method = "cdp_ctrl_x"
                        _send_cdp_ctrl_x()

                glasp_trigger_method = ctrl_x_method
                _perf_step(
                    "ctrl_x_send",
                    step_start,
                    method=ctrl_x_method,
                    cdp_button=bool(click_value),
                    trigger_method=glasp_trigger_method,
                    trigger_setting=trigger_setting,
                    handles_count_before_send=len(before_handles),
                    handles_count_after_send=len(_safe_window_handles())
                )
            except Exception as e_cdp:
                _perf_step("ctrl_x_send", step_start, success=False, error=str(e_cdp)[:80])
                if any(k in str(e_cdp).lower() for k in ["read timed out", "timed out", "httpconnectionpool", "max retries exceeded"]):
                    raise Exception(f"FATAL: 操作中に通信途絶(Zombie/15s)を検知: {e_cdp}")
                raise e_cdp

            return {'ok': True, 'before_handles': before_handles, 'trigger_method': glasp_trigger_method}

        except Exception as e:
            error_msg = str(e)
            if "FATAL" in error_msg:
                _perf_step("trigger_total", click_phase_start, success=False, reason=error_msg[:80])
                raise e
            needs_refresh = ("Gemini Prompt Split Error" in error_msg) or ("Slow Tab Detected" in error_msg)
            _perf_step("trigger_total", click_phase_start, success=False, reason=error_msg[:80])
            return {'ok': False, 'permanent': False, 'error': error_msg, 'needs_refresh': needs_refresh}

    def _wait_for_new_glasp_handle(self, tab_info: Dict, before_handles: set, claimed_handles: set,
                                    playlist_position: int, attempt_index: int, glasp_trigger_method: str,
                                    tab_gen_timeout: float) -> Dict:
        """
        [ADR-0001, S03再修正] 「新しいGeminiタブが出てきたか」だけを判定する軽量チェック。
        送信成功判定（_confirm_glasp_success、数秒〜数十秒かかる）は含まない。

        越智さんのローカル実行結果(S03初版)で、「新しいタブか」の判定をbefore_handlesとの
        差分だけで行っていたため、トリガーラウンドで全動画を待たずにクリックした結果、
        まだ実際には存在しないタブが後から出現した際、複数の動画が同じタブを
        自分のものと誤認する不具合が確認された。
        「クリック直後にその場で短時間確認する」対策(S03再修正・第1版)だけでは、
        生成が遅い動画のタブが後から出現した際に、たまたま同時に検出処理をしていた
        別の動画がそのタブを拾ってしまう抜け道が残っていた（実機ログで、10本中
        複数本が同一のGeminiタブを共有してしまう事例を確認）。
        対策として、claimed_handles(バッチ全体で共有する「既に他の動画に割り当て
        済みのハンドル」の集合)を導入し、たとえ自分のbefore_handlesに含まれない
        新規タブであっても、既に他の動画が使用中であれば候補から除外する。

        戻り値:
          {'handle': str}  … 新しいGemini/GoogleタブのSelenium window handle
          {'handle': None} … tab_gen_timeout以内に見つからなかった
        """
        import time

        video_info_obj = tab_info.get('video_info') if isinstance(tab_info, dict) else None
        video_id_for_log = getattr(video_info_obj, 'video_id', '') if video_info_obj else ''

        def _perf_step(step_name: str, start_time: float, **fields):
            """Glasp起動内の工程別PERFログを出力する（診断専用・処理ロジック非変更）。"""
            try:
                perf_log(
                    "glasp_step",
                    start_time,
                    video_idx=playlist_position,
                    video_id=video_id_for_log[:12],
                    attempt=attempt_index + 1,
                    step=step_name,
                    **fields
                )
            except Exception as e:
                log_message(f"PERF_STEP_ERROR|video_idx={playlist_position}|step={step_name}|error={e}", "WARNING")

        def _safe_window_handles():
            try:
                return self.driver.window_handles
            except:
                return []

        # 検出待ちの間、表示上どの動画を確認中か分かるように、自分の動画タブに
        # 一度切り替えてから待機する。切り替えないと、直前に確認していた別の
        # 動画のGeminiタブに表示が残ったままになり、越智さんの実機観察で
        # 「今どの動画を待っているか分からない」という指摘があったための対応。
        try:
            self.driver.switch_to.window(tab_info["tab_handle"])
        except Exception:
            pass

        step_start = time.time()
        start_wait = time.time()
        glasp_handle = None
        detected_handle = ""
        candidate_handle = None
        candidate_first_seen_sec = None
        url_ready_sec = None
        last_diag_second = -1

        while time.time() - start_wait < tab_gen_timeout:
            elapsed = time.time() - start_wait
            current_handles = _safe_window_handles()
            new_handles = [h for h in current_handles if h not in before_handles and h not in claimed_handles]

            if candidate_handle and candidate_handle not in current_handles:
                log_message(
                    f"GLASP_DETECT_DIAG|stage=candidate_lost|video_idx={playlist_position}|method={glasp_trigger_method}|handle={str(candidate_handle)[:8]}|elapsed={elapsed:.3f}|handles_count={len(current_handles)}",
                    "WARNING"
                )
                candidate_handle = None

            if not candidate_handle and new_handles:
                candidate_handle = new_handles[0]
                candidate_first_seen_sec = elapsed
                log_message(
                    f"GLASP_DETECT_DIAG|stage=handle_first_seen|video_idx={playlist_position}|method={glasp_trigger_method}|handle={str(candidate_handle)[:8]}|elapsed={elapsed:.3f}|new_handles={len(new_handles)}|handles_count={len(current_handles)}",
                    "INFO"
                )
                # [S03十五訂] 「1回のクリックのはずが、複数枚のGeminiタブが同時に
                # 出現しているように見える」という実機での目視報告を受け、原因調査用に
                # 新規ハンドルが2枚以上同時に検出された場合は一覧を残す（診断専用）。
                if len(new_handles) > 1:
                    log_message(
                        f"GLASP_DETECT_DIAG|stage=multiple_new_handles|video_idx={playlist_position}|method={glasp_trigger_method}|elapsed={elapsed:.3f}|new_handles_list={[str(h)[:8] for h in new_handles]}",
                        "WARNING"
                    )

            if candidate_handle:
                try:
                    self.driver.switch_to.window(candidate_handle)
                    current_url = self.driver.current_url or ""
                    current_url_lower = current_url.lower()
                    if "gemini" in current_url_lower or "google" in current_url_lower:
                        glasp_handle = candidate_handle
                        detected_handle = glasp_handle
                        url_ready_sec = elapsed
                        log_message(
                            f"GLASP_DETECT_DIAG|stage=url_ready|video_idx={playlist_position}|method={glasp_trigger_method}|handle={str(glasp_handle)[:8]}|elapsed={elapsed:.3f}|first_seen={candidate_first_seen_sec}|url={current_url[:120]}",
                            "INFO"
                        )
                        break

                    elapsed_second = int(elapsed)
                    if elapsed_second != last_diag_second:
                        last_diag_second = elapsed_second
                        log_message(
                            f"GLASP_DETECT_DIAG|stage=url_not_ready|video_idx={playlist_position}|method={glasp_trigger_method}|handle={str(candidate_handle)[:8]}|elapsed={elapsed:.3f}|url={current_url[:120]}",
                            "INFO"
                        )
                except Exception as detect_error:
                    log_message(
                        f"GLASP_DETECT_DIAG|stage=candidate_check_error|video_idx={playlist_position}|method={glasp_trigger_method}|handle={str(candidate_handle)[:8]}|elapsed={elapsed:.3f}|error={type(detect_error).__name__}:{str(detect_error)[:120]}",
                        "WARNING"
                    )

            time.sleep(0.5)  # チェック間隔: 開始から0.5秒ごと固定（越智さん指示・S03四訂）

        _perf_step(
            "glasp_tab_detect",
            step_start,
            success=bool(glasp_handle),
            timeout=tab_gen_timeout,
            handle=str(detected_handle)[:8],
            handles_count=len(_safe_window_handles()),
            trigger_method=glasp_trigger_method,
            first_seen=candidate_first_seen_sec,
            url_ready=url_ready_sec
        )

        if glasp_handle:
            claimed_handles.add(glasp_handle)
            self.tab_tracker.record_glasp_tab(glasp_handle, tab_info["video_info"].video_id, attempt_index + 1, "pending")
        return {'handle': glasp_handle}

    def _confirm_glasp_success(self, tab_info: Dict, glasp_handle: str, playlist_position: int,
                                attempt_index: int) -> Dict:
        """
        [ADR-0001, S03再修正] 既に判明済みのGeminiタブに対して、送信成功判定のみを行う
        （タブの新規検出は_wait_for_new_glasp_handleで完了済み）。
        数秒〜数十秒かかる可能性がある処理のため、_wait_for_new_glasp_handleとは別に
        検出＆リトライラウンド側で明示的に呼び出すこと（トリガーラウンドの高速な巡回を妨げないため）。

        戻り値:
          {'success': True}
          {'success': False}
        「Gemini Prompt Split Error」由来の例外はそのままraiseする
        （呼び出し側で、ハンドルが生きていれば再クリックのみで再試行し、リフレッシュは行わないこと）。
        """
        import time

        video_info_obj = tab_info.get('video_info') if isinstance(tab_info, dict) else None
        video_id_for_log = getattr(video_info_obj, 'video_id', '') if video_info_obj else ''

        def _perf_step(step_name: str, start_time: float, **fields):
            """Glasp起動内の工程別PERFログを出力する（診断専用・処理ロジック非変更）。"""
            try:
                perf_log(
                    "glasp_step",
                    start_time,
                    video_idx=playlist_position,
                    video_id=video_id_for_log[:12],
                    attempt=attempt_index + 1,
                    step=step_name,
                    **fields
                )
            except Exception as e:
                log_message(f"PERF_STEP_ERROR|video_idx={playlist_position}|step={step_name}|error={e}", "WARNING")

        def _fast_glasp_ready_check() -> Tuple[bool, str]:
            """
            Glasp/Geminiタブの早期成功判定。
            Geminiタブ検出直後に、最大3秒だけ送信ボタンのenabled状態を短周期監視し、
            クリック可能になった瞬間に送信する。
            3秒以内に送信できない場合はFalseを返し、従来の _quick_success_check() へフォールバックする。
            """
            try:
                current_url = self.driver.current_url or ""
                current_url_lower = current_url.lower()
                # [20260808] "google" を含むだけで通していたため、確認画面
                # （www.google.com/sorry/...）も正常なGeminiタブとして扱われ、
                # 3秒×54回を無駄に待っていた。確認画面は明示的に弾く。
                if is_challenge_url(current_url):
                    return False, "challenge_page"
                url_ok = ("gemini" in current_url_lower) or ("google" in current_url_lower)
                if not url_ok:
                    return False, "url_not_ready"

                max_fast_wait = 3.0
                fast_interval = 0.2
                fast_wait_start = time.time()
                last_dom_result = None

                log_message(
                    f"FAST_SEND_BUTTON_WAIT_START|max_wait={max_fast_wait:.1f}|interval={fast_interval:.1f}",
                    "INFO"
                )

                # [S03十訂] 実機で本関数込みの確認処理全体が想定(3秒)を大幅に超えて
                # 37〜43秒かかるケースが見つかったため、原因特定用にexecute_script
                # 1回ごとの所要時間をPERFログに残す。
                fast_iteration_index = 0
                while time.time() - fast_wait_start < max_fast_wait:
                    elapsed = time.time() - fast_wait_start
                    fast_dom_call_start = time.time()
                    dom_result = self.driver.execute_script("""
                        const inputAreas = Array.from(document.querySelectorAll('div[contenteditable="true"], #text-input, textarea'));
                        const inputText = inputAreas.map(el => (el.innerText || el.value || '')).join('\\n');

                        const hasPromptInInput =
                            inputText.includes('<Transcript>') ||
                            inputText.includes('</Transcript>') ||
                            inputText.includes('<ContentTitle>') ||
                            inputText.includes('URL:') ||
                            inputText.includes('http');

                        function buttonState(btn) {
                            if (!btn) {
                                return { exists: false, clickable: false, disabled: null, ariaDisabled: null, width: 0, height: 0 };
                            }
                            const rect = btn.getBoundingClientRect();
                            const ariaDisabled = btn.getAttribute('aria-disabled') === 'true';
                            const disabled = !!btn.disabled;
                            const clickable = !disabled && !ariaDisabled && rect.width > 0 && rect.height > 0;
                            return {
                                exists: true,
                                clickable: clickable,
                                disabled: disabled,
                                ariaDisabled: ariaDisabled,
                                width: Math.round(rect.width),
                                height: Math.round(rect.height)
                            };
                        }

                        function findSendButton() {
                            const selectors = [
                                'button[aria-label*="プロンプトを送信"]',
                                'button[aria-label*="送信"]',
                                'button[aria-label*="Send"]',
                                'button[aria-label*="send"]'
                            ];

                            for (const selector of selectors) {
                                const btn = document.querySelector(selector);
                                const state = buttonState(btn);
                                if (state.exists) {
                                    return { button: btn, method: selector, state: state };
                                }
                            }

                            const iconSelectors = [
                                'mat-icon[fonticon="arrow_upward"]',
                                'mat-icon[data-mat-icon-name="arrow_upward"]',
                                'mat-icon[fonticon="send"]',
                                'mat-icon[data-mat-icon-name="send"]'
                            ];

                            for (const selector of iconSelectors) {
                                const icon = document.querySelector(selector);
                                const btn = icon ? icon.closest('button') : null;
                                const state = buttonState(btn);
                                if (state.exists) {
                                    return { button: btn, method: selector, state: state };
                                }
                            }

                            return {
                                button: null,
                                method: 'not_found',
                                state: { exists: false, clickable: false, disabled: null, ariaDisabled: null, width: 0, height: 0 }
                            };
                        }

                        const found = findSendButton();
                        let clicked = false;
                        if (hasPromptInInput && found.button && found.state.clickable) {
                            found.button.click();
                            clicked = true;
                        }

                        return {
                            clicked: clicked,
                            method: found.method,
                            hasPromptInInput: hasPromptInInput,
                            inputLength: inputText.length,
                            buttonExists: found.state.exists,
                            buttonClickable: found.state.clickable,
                            buttonDisabled: found.state.disabled,
                            buttonAriaDisabled: found.state.ariaDisabled,
                            buttonWidth: found.state.width,
                            buttonHeight: found.state.height
                        };
                    """)
                    perf_log("fast_check_dom_probe", fast_dom_call_start, iteration=fast_iteration_index)
                    last_dom_result = dom_result

                    if isinstance(dom_result, dict) and dom_result.get("clicked"):
                        log_message(
                            f"FAST_SEND_BUTTON_CLICKED|elapsed={elapsed:.3f}|method={dom_result.get('method', '')}|inputLength={dom_result.get('inputLength', 0)}",
                            "INFO"
                        )
                        return True, f"fast_send_button_clicked:{dom_result}"

                    fast_iteration_index += 1
                    time.sleep(fast_interval)

                log_message(
                    f"FAST_SEND_BUTTON_TIMEOUT|elapsed={time.time() - fast_wait_start:.3f}|last={last_dom_result}",
                    "INFO"
                )
                return False, f"fast_send_button_timeout:{last_dom_result}"

            except Exception as e:
                return False, f"fast_check_error:{type(e).__name__}:{e}"

        

        try:
            self.driver.switch_to.window(glasp_handle)
        except Exception as e:
            log_message(f"GLASP_CONFIRM_DIAG|stage=switch_error|video_idx={playlist_position}|handle={str(glasp_handle)[:8]}|error={type(e).__name__}:{str(e)[:120]}", "WARNING")
            return {'success': False}

        # [20260808] 確認画面の一次判定はURLで行う。
        # ここより先（_fast_glasp_ready_check / _quick_success_check）はページ本文の
        # 文言に依存した判定であり、20260808の実機では文言が想定と異なったため
        # すり抜けて「ただのエラー」として54回リトライされ続けた。URLは文言に
        # 左右されないので、本文を読む前に確定させる。
        try:
            confirm_url = self.driver.current_url or ""
        except Exception:
            confirm_url = ""
        if is_challenge_url(confirm_url):
            log_message(
                f"CHALLENGE_URL_DETECTED|video_idx={playlist_position}|handle={str(glasp_handle)[:8]}|url={confirm_url[:160]}",
                "ERROR"
            )
            measure_log(f"GLASP_MEASURE_CHALLENGE|video_idx={playlist_position}|url={confirm_url[:120]}")
            raise Exception(
                "FATAL: CHALLENGE_DETECTED: Googleの確認画面（reCAPTCHA等）が"
                "表示されました。自動での続行は行いません。"
            )

        step_start = time.time()
        fast_success, fast_reason = _fast_glasp_ready_check()
        if fast_success:
            quick_success = True
            success_method = "fast_url_dom"
        else:
            quick_success = self._quick_success_check()
            success_method = "quick_success_check"

        _perf_step(
            "glasp_success_check",
            step_start,
            success=bool(quick_success),
            handle=str(glasp_handle)[:8],
            method=success_method,
            fast_reason=str(fast_reason)[:120]
        )
        if quick_success:
            self.tab_tracker.mark_success(glasp_handle)
            tab_info["video_info"].add_glasp_handle(glasp_handle)
            return {'success': True}

        return {'success': False}

    def cleanup_playlist_tabs(self) -> None:
        """プレイリスト完了時のタブクリーンアップ"""
        log_message("=== プレイリスト完了時のタブクリーンアップ開始（プレイリストタブは保持）===", "INFO")
        if self.playlist_tab_handle:
            try:
                if self.playlist_tab_handle not in self.driver.window_handles: self.playlist_tab_handle = None
            except: self.playlist_tab_handle = None
        if not self.playlist_tab_handle:
            self.playlist_tab_handle = self._find_playlist_tab()
        
        protected_tabs = set([self.playlist_tab_handle]) if self.playlist_tab_handle else set()
        current_handles = self.driver.window_handles.copy()

        # [20260808] クローズ対象の判定。
        # 動画タブ(youtube.com/watch)は「夜間の自動実行が走ったか目視確認する」
        # ために残す方針だが、全部残すとChromeが処理不能になる。実機ログで
        # 動画タブが 13 → 17 → 32 枚と解放されずに積み上がり、タブ切り替えだけで
        # 41.7秒、chromedriverとの通信が60秒でタイムアウト(FATAL)し、
        # 「Slow Tab Detected」で全動画が要約失敗する事象が発生した。
        # YouTubeの視聴ページは1枚あたりの負荷が大きいため、残す枚数に上限を設ける。
        # KEEP_VIDEO_TABS を増やすほど実行痕跡は残るが、Chromeが重くなる。
        # 0 にすれば従来どおり全て閉じる（実行確認は朝の1通の実行台帳で行う）。
        KEEP_VIDEO_TABS = 3

        handles_to_close = []
        video_handles = []
        for handle in current_handles:
            if handle in protected_tabs:
                continue
            try:
                self.driver.switch_to.window(handle)
                url = self.driver.current_url
            except Exception:
                continue
            if 'gemini.google.com' in url:
                handles_to_close.append(handle)
            elif 'youtube.com/watch' in url:
                video_handles.append(handle)

        # 新しい方(window_handlesの後ろ)から KEEP_VIDEO_TABS 枚だけ残し、
        # それより古い動画タブは閉じる。
        keep_video = video_handles[-KEEP_VIDEO_TABS:] if KEEP_VIDEO_TABS > 0 else []
        handles_to_close.extend(h for h in video_handles if h not in keep_video)
        kept_video_tabs = len(keep_video)

        # [20260807] 全ウィンドウを閉じるとChromeプロセス自体が終了し、次の
        # プレイリスト先頭で invalid session id となって例外ハンドラへ落ち、
        # 「ブラウザ強制リセット＋そのプレイリストのスキップ」が発生していた
        # （実機ログでプレイリストS/B/Mが未処理のまま飛ばされていた）。
        # 生き残るタブが1つも無くなる場合は、閉じる前に空タブを確保する。
        if handles_to_close and len(handles_to_close) >= len(current_handles):
            try:
                self.browser.create_new_tab("about:blank")
                log_message("Chrome終了防止用の空タブを1つ作成しました", "INFO")
            except Exception as e:
                log_message(f"⚠️ 生存用タブの作成に失敗しました: {e}", "WARNING")

        closed_count = 0
        for handle in handles_to_close:
            try:
                self.driver.switch_to.window(handle)
                self.driver.close()
                closed_count += 1
            except Exception: pass
        self.youtube_tabs_pool = []
        # [20260807] クローズ直後はdriverの現在ウィンドウが閉じたタブを指したままになる。
        # プレイリストタブが無い場合も、必ず生き残っているタブへ切り替えておく。
        try:
            remaining = self.driver.window_handles
            if self.playlist_tab_handle and self.playlist_tab_handle in remaining:
                self.driver.switch_to.window(self.playlist_tab_handle)
            elif remaining:
                self.driver.switch_to.window(remaining[0])
            else:
                log_message("⚠️ クリーンアップ後に残ったタブがありません", "WARNING")
        except Exception as e:
            log_message(f"⚠️ クリーンアップ後のタブ切り替えに失敗しました: {e}", "WARNING")
        try:
            remaining_total = len(self.driver.window_handles)
        except Exception:
            remaining_total = -1
        log_message(
            f"プレイリストタブクリーンアップ完了: {closed_count}個をクローズ / "
            f"動画タブ {kept_video_tabs}個を実行確認用に保持 / 残タブ合計 {remaining_total}枚",
            "SUCCESS"
        )
        # [20260808] タブが増え続けるとChromeが処理不能になり全動画が失敗する。
        # 気づけるよう、残タブが多い場合は警告を出す。
        if remaining_total >= 15:
            log_message(
                f"⚠️ 残タブが{remaining_total}枚あります。Chromeの応答が遅くなり "
                f"要約が失敗しやすくなります（cleanup_playlist_tabs の KEEP_VIDEO_TABS を確認）",
                "WARNING"
            )

    def _find_playlist_tab(self) -> Optional[str]:
        if not self.driver: return None
        try:
            current_handle = self.driver.current_window_handle
            for handle in self.driver.window_handles:
                try:
                    self.driver.switch_to.window(handle)
                    if '/playlist?list=' in self.driver.current_url or 'youtube.com/playlist' in self.driver.current_url:
                        try: self.driver.switch_to.window(current_handle)
                        except: pass
                        return handle
                except: continue
            try: self.driver.switch_to.window(current_handle)
            except: pass
            return None
        except: return None

    def reset_for_new_playlist(self):
        log_message("次のプレイリストのための初期化開始", "INFO")
        self.is_first_run_in_session = True
        self.youtube_tabs_pool = []
        self.playlist_tab_handle = None
        import time
        time.sleep(1) 
        if hasattr(self, 'tab_tracker') and self.tab_tracker: self.tab_tracker.reset_all()
        try:
            memory_mb = self.browser.get_memory_usage()
            if memory_mb > 1500: log_message(f"⚠️ ブラウザのメモリ使用量が高めです: {memory_mb:.1f}MB", "WARNING")
        except: pass
        try:
            if self.driver and len(self.driver.window_handles) == 0:
                self.browser.create_new_tab("about:blank")
                self.main_window_handle = self.driver.current_window_handle
        except: pass

    def _final_cleanup(self):
        if self.youtube_tabs_pool:
            for tab_info in self.youtube_tabs_pool:
                try: self.browser.close_tab(tab_info['tab_handle'])
                except: pass
            self.youtube_tabs_pool = []

    def wait_for_glasp_completion(self, timeout: float = 30.0) -> bool:
        js_check_script = """
        return (function() {
            const fullText = document.body ? (document.body.innerText || '') : '';
            const hasWaitingText = ['お待ちください', '生成中', 'Generating', 'Loading', '処理中'].some(p => fullText.includes(p));
            const hasLoadingElement = ['[class*="loading"]', '[class*="spinner"]', '[class*="gemini"]', '[aria-busy="true"]'].some(s => document.querySelector(s));
            const hasAnimation = Array.from(document.querySelectorAll('*')).some(el => { const s = window.getComputedStyle(el); return s.animation && s.animation !== 'none'; });
            const transcriptEndIndex = fullText.indexOf('</Transcript>');
            let summaryText = '';
            if (transcriptEndIndex !== -1) { summaryText = fullText.substring(transcriptEndIndex + 13).trim(); } 
            else { const lastIndex = Math.max(fullText.lastIndexOf('■ タイトル'), fullText.lastIndexOf('▪ タイトル')); if (lastIndex > 0) summaryText = fullText.substring(lastIndex); }
            const sections = { title: summaryText.includes('タイトル'), keywords: summaryText.includes('キーワード'), conclusion: summaryText.includes('結論'), points: summaryText.includes('主なポイント') };
            const completedCount = Object.values(sections).filter(v => v).length;
            const isGenerating = hasWaitingText || hasLoadingElement || hasAnimation;
            return { ready: completedCount >= 3 && summaryText.length > 300 && !isGenerating, isGenerating: isGenerating, summaryLength: summaryText.length, completedSections: completedCount };
        })();
        """
        start_time = time.time()
        last_summary_length = 0
        no_progress_count = 0
        generation_detected = False
        
        while True:
            current_time = time.time() - start_time
            if current_time > min(timeout * 2, 120): break
            try:
                result = self.driver.execute_script(js_check_script)
                if result.get('isGenerating', False):
                    generation_detected = True
                    no_progress_count = 0
                    if generation_detected and current_time < timeout: timeout = max(timeout, current_time + 20)
                    time.sleep(1.0); continue
                if result.get('ready', False): return True
                
                summary_length = result.get('summaryLength', 0)
                if summary_length > last_summary_length:
                    no_progress_count = 0; last_summary_length = summary_length
                else: no_progress_count += 1
                
                if no_progress_count > 20:
                    if summary_length > 200: return False
                    elif not generation_detected: return False
                
                if current_time >= timeout: return summary_length > 100
                time.sleep(0.5)
            except:
                if current_time >= timeout: return False
                time.sleep(1.0)
        return False

    def _debug_dom_state(self) -> dict:
        return {}

    def _extract_glasp_summary(self, glasp_handle: Optional[str], video_index: int = 0, batch_size: int = 1) -> Tuple[Optional[str], Optional[str]]:
        if not glasp_handle or not self.driver:
            return None, None

        try:
            self.last_summary_extract_fail_fast = False
            self.last_summary_extract_fail_fast_reason = ""
            self.driver.switch_to.window(glasp_handle)

            fast_mode_switch_start = time.time()
            if not hasattr(self, "fast_mode_switch_completed"):
                self.fast_mode_switch_completed = False

            if not self.fast_mode_switch_completed:
                log_message(
                    f"FAST_MODE_SWITCH|action=run|video_index={video_index}|batch_size={batch_size}",
                    "INFO"
                )
                switch_gemini_to_fast_mode(self.driver)
                self.fast_mode_switch_completed = True
                log_message(
                    f"FAST_MODE_SWITCH|action=done|video_index={video_index}|sec={time.time() - fast_mode_switch_start:.3f}",
                    "INFO"
                )
            else:
                log_message(
                    f"FAST_MODE_SWITCH|action=skip|reason=already_completed|video_index={video_index}|batch_size={batch_size}",
                    "INFO"
                )

            base_timeout = self.current_base_timeout
            start_time = time.time()
            phase1_result = self._wait_for_completion_phase1(base_timeout, start_time, video_index, batch_size)
            actual_time = time.time() - start_time
            gemini_url = None
            
            if phase1_result['success']:
                self._update_timeout_after_success(actual_time, base_timeout * self.reset_threshold_ratio, False)
                summary_text = self._extract_summary_text()
                if summary_text:
                    gemini_url = self.driver.current_url
                return summary_text, gemini_url

            if phase1_result.get('fail_fast', False):
                self.last_summary_extract_fail_fast = True
                self.last_summary_extract_fail_fast_reason = phase1_result.get('reason', 'phase1_fail_fast')
                log_message(
                    f"SUMMARY_PHASE2_SKIP|reason=phase1_fail_fast|video_index={video_index}|elapsed={actual_time:.3f}|final_length={phase1_result.get('final_length', 0)}|detail={phase1_result.get('reason', '')}",
                    "WARNING"
                )
                return None, None
            
            if actual_time >= self.max_timeout:
                return None, None
            
            remaining_time = min(base_timeout + self.timeout_extension, self.max_timeout) - actual_time
            if remaining_time > 0:
                phase2_result = self._wait_for_completion_phase2(remaining_time, time.time(), video_index, batch_size)
                if phase2_result['success']:
                    self._update_timeout_after_success(time.time() - start_time, base_timeout * self.reset_threshold_ratio, True)
                    summary_text = self._extract_summary_text()
                    if summary_text:
                        gemini_url = self.driver.current_url
                    return summary_text, gemini_url

            return None, None

        except Exception as e:
            log_message(f"❌ 抽出エラー: {e}", "ERROR")
            return None, None



    def _process_batch(self, batch_videos: List[VideoInfo], batch_idx: int, config: ProcessConfig, playlist_id: Optional[str] = None) -> List[SummaryResult]:
        """
        [20260511_01_02] 有効版: バッチ処理の実行、PERFログ、TAB_HEALTHログ、メタデータ自動保存。
        処理ロジック・sleep・timeout・retry・ChromeOptionsは変更しない。
        """
        batch_perf_start = time.time()
        results = []
        glasp_results = []
        video_tabs = []
        phase1_retry_queue = []
        if not self.driver:
            return results

        def log_tab_health(stage: str, tabs: Optional[List[Dict]] = None):
            """タブハンドルの生存状態をログ出力する（診断専用・処理ロジック非変更）。"""
            try:
                handles = self.driver.window_handles if self.driver else []
                current_handle = ""
                try:
                    current_handle = self.driver.current_window_handle if self.driver else ""
                except Exception as current_error:
                    current_handle = f"ERROR:{type(current_error).__name__}"

                target_tabs = tabs if tabs is not None else []
                if not target_tabs:
                    log_message(
                        f"TAB_HEALTH|stage={stage}|batch={batch_idx + 1}|handles_count={len(handles)}|current={str(current_handle)[:8]}",
                        "INFO"
                    )
                    return

                for idx, tab_info in enumerate(target_tabs, start=1):
                    handle = tab_info.get('tab_handle', '') if isinstance(tab_info, dict) else ''
                    video_info = tab_info.get('video_info') if isinstance(tab_info, dict) else None
                    video_id = getattr(video_info, 'video_id', '') if video_info else ''
                    alive = handle in handles
                    log_message(
                        f"TAB_HEALTH|stage={stage}|batch={batch_idx + 1}|idx={idx}|video={video_id[:12]}|handle={str(handle)[:8]}|alive={alive}|handles_count={len(handles)}|current={str(current_handle)[:8]}",
                        "INFO"
                    )
            except Exception as e:
                log_message(f"TAB_HEALTH_ERROR|stage={stage}|batch={batch_idx + 1}|error={e}", "WARNING")

        try:
            current_handles = self.driver.window_handles
            if not hasattr(self, 'main_window_handle') or not self.main_window_handle or self.main_window_handle not in current_handles:
                if current_handles:
                    self.main_window_handle = current_handles[0]
            if self.main_window_handle:
                self.driver.switch_to.window(self.main_window_handle)
            log_tab_health("after_main_window_sync")
        except Exception as e:
            log_message(f"TAB_HEALTH|stage=main_window_sync_error|batch={batch_idx + 1}|error={e}", "WARNING")

        self.tab_tracker.reset_batch()
        log_tab_health("after_tab_tracker_reset")

        try:
            tab_prepare_start = time.time()
            tab_mode = "reuse" if config.browser_mode == 3 and self.youtube_tabs_pool else "open"
            if config.browser_mode == 3 and self.youtube_tabs_pool:
                log_tab_health("before_reuse_video_tabs", self.youtube_tabs_pool)
                video_tabs = self._reuse_video_tabs(batch_videos)
            else:
                video_tabs = self._open_video_tabs(batch_videos)
            perf_log(
                "batch_tab_prepare",
                tab_prepare_start,
                batch=batch_idx + 1,
                videos=len(batch_videos),
                tabs=len(video_tabs),
                mode=tab_mode
            )
            log_tab_health("after_tab_prepare", video_tabs)
        except Exception as e:
            if "FATAL" in str(e):
                self._emergency_cleanup()
                self.youtube_tabs_pool = []
                self.main_window_handle = None
                raise
            log_message(f"TAB_HEALTH|stage=tab_prepare_exception|batch={batch_idx + 1}|error={e}", "WARNING")
            return results

        if not video_tabs:
            perf_log("batch_no_tabs", batch_perf_start, batch=batch_idx + 1, videos=len(batch_videos))
            log_tab_health("no_video_tabs")
            return results

        for tab_info in video_tabs:
            video = tab_info['video_info']
            self.tab_tracker.record_youtube_tab(video.video_id, tab_info['tab_handle'], video.title)
        log_tab_health("after_record_youtube_tabs", video_tabs)

        try:
            glasp_launch_start = time.time()
            log_tab_health("before_batch_send_ctrl_x", video_tabs)
            try:
                glasp_results = self._batch_send_ctrl_x(video_tabs, config)
            except Exception as e:
                if "FATAL" in str(e):
                    self._emergency_cleanup()
                    self.youtube_tabs_pool = []
                    self.main_window_handle = None
                    raise
                log_message(f"TAB_HEALTH|stage=batch_send_ctrl_x_exception|batch={batch_idx + 1}|error={e}", "WARNING")
                glasp_results = []
            perf_log(
                "batch_glasp_launch",
                glasp_launch_start,
                batch=batch_idx + 1,
                videos=len(batch_videos),
                glasp_results=len(glasp_results)
            )
            log_tab_health("after_batch_send_ctrl_x", video_tabs)

            summary_extract_start = time.time()
            for i, glasp_result in enumerate(glasp_results):
                has_summary_extraction_error = False

                video_info = glasp_result.get('video_info')
                if not video_info:
                    continue

                video_info.batch_index = batch_idx
                if playlist_id and hasattr(video_info, '__dict__'):
                    video_info.playlist_id = playlist_id

                try:
                    if glasp_result['success']:
                        summary_text, gemini_url = self._extract_glasp_summary(glasp_handle=glasp_result.get('glasp_handle'), video_index=i, batch_size=len(batch_videos))
                        matched_by_title = False
                        if summary_text:
                            extracted_title = self._extract_video_title_from_glasp(summary_text)
                            if extracted_title and video_info.title:
                                matched_by_title = self._match_titles(extracted_title, video_info.title)

                        formatted_summary = summary_text if summary_text else "要約取得失敗"
                        if not summary_text:
                            has_summary_extraction_error = True

                        retry_video_tab = None
                        if has_summary_extraction_error and getattr(self, "last_summary_extract_fail_fast", False):
                            retry_video_id = getattr(video_info, "video_id", "")
                            retry_video_tab = next(
                                (
                                    tab for tab in video_tabs
                                    if getattr(tab.get('video_info'), "video_id", "") == retry_video_id
                                ),
                                None
                            )
                            phase1_retry_queue.append({
                                "result_index": len(results),
                                "glasp_result": glasp_result,
                                "video_info": video_info,
                                "video_tab": retry_video_tab,
                                "video_index": i,
                                "reason": getattr(self, "last_summary_extract_fail_fast_reason", "phase1_fail_fast")
                            })
                            log_message(
                                f"PHASE1_RETRY_QUEUE_ADD|batch={batch_idx + 1}|video_index={i}|video_id={retry_video_id[:12]}|reason={getattr(self, 'last_summary_extract_fail_fast_reason', 'phase1_fail_fast')}|has_video_tab={retry_video_tab is not None}",
                                "WARNING"
                            )

                        result = SummaryResult(
                            video_info=video_info, success=not has_summary_extraction_error,
                            summary=formatted_summary, formatted_summary=formatted_summary, raw_response=summary_text if summary_text else "",
                            model_used="Glasp (Gemini)", processing_time=glasp_result.get('processing_time', 0),
                            transcript_length=len(summary_text) if summary_text else 0, batch_number=batch_idx,
                            matched_by_title=matched_by_title, glasp_handle_used=glasp_result.get('glasp_handle', ''),
                            retry_count=glasp_result.get('retry_count', 0), skip_reason="", gemini_url=gemini_url
                        )
                    else:
                        skip_reason_final = glasp_result.get('skip_reason', 'スキップ') if glasp_result.get('skipped', False) else glasp_result.get('error', 'Unknown error')
                        result = SummaryResult(
                            video_info=video_info, success=False, error_message=glasp_result.get('error', 'Unknown error'),
                            model_used="Glasp", processing_time=glasp_result.get('processing_time', 0), batch_number=batch_idx,
                            retry_count=glasp_result.get('retry_count', 0), skip_reason=skip_reason_final,
                            # [20260808] 字幕が無くて要約できない動画と、Glaspの起動に
                            # 失敗した動画を、後段（HTML・朝の一通）で区別できるようにする。
                            skip_kind=glasp_result.get('skip_kind', 'failed')
                        )
                    results.append(result)
                    state.current_progress += 1
                except Exception as e:
                    results.append(SummaryResult(video_info=video_info, success=False, error_message=f"処理エラー: {str(e)}", model_used="Glasp", processing_time=glasp_result.get('processing_time', 0), batch_number=batch_idx, skip_reason=""))
                    state.current_progress += 1
            if phase1_retry_queue:
                retry_batch_start = time.time()
                log_message(
                    f"PHASE1_RETRY_BATCH_START|batch={batch_idx + 1}|count={len(phase1_retry_queue)}",
                    "WARNING"
                )

                for retry_item in phase1_retry_queue:
                    retry_video_info = retry_item.get("video_info")
                    retry_video_tab = retry_item.get("video_tab")
                    retry_video_index = retry_item.get("video_index", 0)
                    retry_video_id = getattr(retry_video_info, "video_id", "") if retry_video_info else ""
                    result_index = retry_item.get("result_index")

                    if not retry_video_info or not retry_video_tab:
                        log_message(
                            f"PHASE1_RETRY_FINAL_FAIL|batch={batch_idx + 1}|video_index={retry_video_index}|video_id={retry_video_id[:12]}|reason=missing_video_info_or_tab",
                            "WARNING"
                        )
                        continue

                    log_message(
                        f"PHASE1_RETRY_START|batch={batch_idx + 1}|video_index={retry_video_index}|video_id={retry_video_id[:12]}|retry=1",
                        "PROCESS"
                    )

                    try:
                        retry_glasp_results = self._batch_send_ctrl_x([retry_video_tab], config)
                        glasp_results.extend(retry_glasp_results)

                        if not retry_glasp_results or not retry_glasp_results[0].get('success'):
                            retry_error = retry_glasp_results[0].get('error', 'retry_glasp_launch_failed') if retry_glasp_results else 'retry_glasp_launch_no_result'
                            log_message(
                                f"PHASE1_RETRY_FINAL_FAIL|batch={batch_idx + 1}|video_index={retry_video_index}|video_id={retry_video_id[:12]}|reason={retry_error}",
                                "WARNING"
                            )
                            continue

                        retry_glasp_result = retry_glasp_results[0]
                        retry_summary_text, retry_gemini_url = self._extract_glasp_summary(
                            glasp_handle=retry_glasp_result.get('glasp_handle'),
                            video_index=retry_video_index,
                            batch_size=len(batch_videos)
                        )

                        if not retry_summary_text:
                            log_message(
                                f"PHASE1_RETRY_FINAL_FAIL|batch={batch_idx + 1}|video_index={retry_video_index}|video_id={retry_video_id[:12]}|reason=summary_extract_failed_after_retry",
                                "WARNING"
                            )
                            continue

                        retry_matched_by_title = False
                        retry_extracted_title = self._extract_video_title_from_glasp(retry_summary_text)
                        if retry_extracted_title and retry_video_info.title:
                            retry_matched_by_title = self._match_titles(retry_extracted_title, retry_video_info.title)

                        retry_count_total = (
                            retry_item.get("glasp_result", {}).get('retry_count', 0)
                            + retry_glasp_result.get('retry_count', 0)
                            + 1
                        )

                        results[result_index] = SummaryResult(
                            video_info=retry_video_info, success=True,
                            summary=retry_summary_text, formatted_summary=retry_summary_text, raw_response=retry_summary_text,
                            model_used="Glasp (Gemini)", processing_time=retry_glasp_result.get('processing_time', 0),
                            transcript_length=len(retry_summary_text), batch_number=batch_idx,
                            matched_by_title=retry_matched_by_title, glasp_handle_used=retry_glasp_result.get('glasp_handle', ''),
                            retry_count=retry_count_total, skip_reason="", gemini_url=retry_gemini_url
                        )

                        log_message(
                            f"PHASE1_RETRY_SUCCESS|batch={batch_idx + 1}|video_index={retry_video_index}|video_id={retry_video_id[:12]}|retry_count={retry_count_total}",
                            "SUCCESS"
                        )

                    except Exception as retry_error:
                        if "FATAL" in str(retry_error):
                            raise
                        log_message(
                            f"PHASE1_RETRY_FINAL_FAIL|batch={batch_idx + 1}|video_index={retry_video_index}|video_id={retry_video_id[:12]}|reason={str(retry_error)[:120]}",
                            "WARNING"
                        )

                perf_log(
                    "phase1_retry_batch",
                    retry_batch_start,
                    batch=batch_idx + 1,
                    retry_count=len(phase1_retry_queue),
                    results=len(results)
                )

            perf_log(
                "batch_summary_extract",
                summary_extract_start,
                batch=batch_idx + 1,
                glasp_results=len(glasp_results),
                results=len(results)
            )

            try:
                metadata_start = time.time()
                if any(r.success for r in results):
                    metadata_updater = ChannelMetadataUpdater()
                    metadata_updater.update_metadata(results)
                perf_log("batch_metadata_update", metadata_start, batch=batch_idx + 1, results=len(results))
            except Exception as e:
                log_message(f"メタデータ連携エラー（非致命的）: {e}", "WARNING")

        finally:
            cleanup_start = time.time()
            log_tab_health("before_cleanup_batch_tabs", video_tabs)
            self._cleanup_batch_tabs(video_tabs, glasp_results, config.browser_mode)
            log_tab_health("after_cleanup_batch_tabs")
            perf_log("batch_cleanup", cleanup_start, batch=batch_idx + 1, tabs=len(video_tabs), glasp_results=len(glasp_results))
            perf_log("batch_total", batch_perf_start, batch=batch_idx + 1, videos=len(batch_videos), results=len(results))

        return results

    def _wait_for_completion_phase1(self, timeout: float, start_time: float, video_index: int, batch_size: int) -> Dict:
        last_summary_length = 0
        input_error_count = 0
        # [20260807] 「■要約終了が画面に出ているのに検出されない」事象の原因を特定するための
        # 診断ログ。hasEndTagはsummaryTextの末尾100文字しか見ないため、要約の後ろに
        # GeminiのUI文言などが付くと検出できない。実際の末尾を定期的に記録して確認する。
        last_diag_time = 0.0

        log_message(
            f"SUMMARY_WAIT_START|phase=1|video_index={video_index}|batch_size={batch_size}|timeout={timeout}",
            "INFO"
        )
        
        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time
            try:
                page_status = self.driver.execute_script("""
                    return (function() {
                        const fullText = document.body ? (document.body.innerText || '') : '';

                        let transcriptEnd = Math.max(
                            fullText.lastIndexOf('</Transcript>'),
                            fullText.lastIndexOf('</transcript>')
                        );

                        const summaryText = transcriptEnd > -1
                            ? fullText.substring(transcriptEnd + 13).trim()
                            : '';

                        const titleIndex = summaryText.indexOf('■ タイトル');
                        const actualSummaryText = titleIndex > -1
                            ? summaryText.substring(titleIndex).trim()
                            : '';

                        const tail100 = summaryText.slice(-100);
                        // [20260807] プロンプト(_create_prompt)の出力形式例が指示している
                        // 終了マーカーは「■要約完了」だが、ここでは「■要約終了」しか見て
                        // いなかったため、Geminiが指示どおり出力しても永久に検出されず、
                        // 毎回タイムアウト(60秒)まで待っていた。extract_section側の
                        // end_markersと同じく、完了/終了の両方と全角スペース有無を許容する。
                        const normTail100 = tail100.replace(/[ 　]/g, '');
                        const hasEndTag = normTail100.includes('■要約完了') || normTail100.includes('■要約終了');

                        const hasConclusion = summaryText.includes('■ 結論');
                        const hasMainPoints = summaryText.includes('■ 主なポイント');
                        const hasTitle = summaryText.includes('■ タイトル');
                        const hasKeywords = summaryText.includes('■ キーワード');
                        const completedSections = [hasTitle, hasKeywords, hasConclusion, hasMainPoints].filter(Boolean).length;

                        const animatedCount = Array.from(document.querySelectorAll('*')).filter(el => {
                            const style = window.getComputedStyle(el);
                            const animationName = style.animationName || '';
                            const animationDuration = style.animationDuration || '';
                            return animationName !== 'none' && animationDuration !== '0s';
                        }).length;

                        const hasAnimation = animatedCount > 0;
                        const inputArea = document.querySelector('div[contenteditable="true"], #text-input, textarea');
                        const inputText = inputArea ? (inputArea.innerText || inputArea.value || '') : '';
                        const hasSplitError = inputText.includes('<Transcript>');

                        return {
                            hasEndTag: hasEndTag,
                            pageTextLength: fullText.length,
                            summaryTextLength: summaryText.length,
                            actualSummaryLength: actualSummaryText.length,
                            summaryLength: actualSummaryText.length,
                            tail100: tail100.replace(/\\r/g, '\\\\r').replace(/\\n/g, '\\\\n'),
                            hasAnimation: hasAnimation,
                            animatedCount: animatedCount,
                            completedSections: completedSections,
                            hasConclusion: hasConclusion,
                            hasMainPoints: hasMainPoints,
                            hasSplitError: hasSplitError
                        };
                    })();
                """)
                
                if page_status.get('hasSplitError', False):
                    input_error_count += 1
                    if input_error_count >= 2:
                        raise Exception("RETRY: Gemini Prompt Split Error")
                else:
                    input_error_count = 0

                current_length = page_status.get('summaryLength', 0)

                # [20260807] 15秒ごとに末尾100文字を記録する診断ログ。
                # ■要約終了が画面に出ているのに検出されない場合、この記録に
                # 要約終了タグの後ろへ何が付いているかが残る。
                if elapsed - last_diag_time >= 15.0:
                    last_diag_time = elapsed
                    log_message(
                        f"SUMMARY_WAIT_DIAG|phase=1|video_index={video_index}|elapsed={elapsed:.1f}"
                        f"|length={current_length}|sections={page_status.get('completedSections', 0)}"
                        f"|animatedCount={page_status.get('animatedCount', -1)}"
                        f"|tail100={page_status.get('tail100', '')}",
                        "INFO"
                    )

                if page_status.get('hasEndTag', False):
                    log_message(
                        f"SUMMARY_END_TAG_FOUND|phase=1|video_index={video_index}|elapsed={elapsed:.3f}|length={current_length}|tail100={page_status.get('tail100', '')}",
                        "INFO"
                    )
                    log_message(
                        f"Phase1完了: ■要約終了検出 ({elapsed:.1f}秒, {current_length}文字)",
                        "SUCCESS"
                    )
                    return {'success': True, 'final_length': current_length}

                if (
                    elapsed >= 10.0
                    and page_status.get('actualSummaryLength', 0) < 300
                    and page_status.get('completedSections', 0) == 0
                    and not page_status.get('hasEndTag', False)
                ):
                    log_message(
                        f"SUMMARY_FAIL_FAST|phase=1|video_index={video_index}|elapsed={elapsed:.3f}|pageTextLength={page_status.get('pageTextLength', 0)}|summaryTextLength={page_status.get('summaryTextLength', 0)}|actualSummaryLength={page_status.get('actualSummaryLength', 0)}|completedSections={page_status.get('completedSections', 0)}|tail100={page_status.get('tail100', '')}",
                        "WARNING"
                    )
                    return {
                        'success': False,
                        'final_length': current_length,
                        'fail_fast': True,
                        'reason': 'no_summary_text_after_10s'
                    }

                if (
                    current_length >= 300
                    and page_status.get('completedSections', 0) >= 3
                    and page_status.get('hasConclusion', False)
                    and page_status.get('hasMainPoints', False)
                    and not page_status.get('hasAnimation', True)
                ):
                    log_message(
                        f"Phase1完了: アニメーション停止バックアップ ({elapsed:.1f}秒, {current_length}文字, sections={page_status.get('completedSections', 0)})",
                        "SUCCESS"
                    )
                    return {'success': True, 'final_length': current_length}

                last_summary_length = current_length

            except Exception as e:
                if any(k in str(e).lower() for k in ["read timed out", "timed out", "httpconnectionpool", "max retries exceeded"]):
                    raise Exception(f"FATAL: Communication Lost during Wait: {e}")
                if "FATAL" in str(e) or "RETRY" in str(e):
                    raise e
            
            time.sleep(0.5)
        
        log_message(
            f"SUMMARY_PHASE1_TIMEOUT_RETURN|video_index={video_index}|success={last_summary_length >= 300}|length={last_summary_length}",
            "WARNING"
        )
        return {'success': last_summary_length >= 300, 'final_length': last_summary_length}

    def _wait_for_completion_phase2(self, timeout: float, start_time: float, video_index: int, batch_size: int) -> Dict:
        last_summary_length = 0

        log_message(
            f"SUMMARY_WAIT_START|phase=2|video_index={video_index}|batch_size={batch_size}|timeout={timeout}",
            "INFO"
        )
        
        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time
            
            try:
                page_text = self.driver.execute_script("""
                    return (function() {
                        const fullText = document.body ? (document.body.innerText || '') : '';
                        const transcriptEnd = fullText.indexOf('</Transcript>');
                        let summaryText = transcriptEnd > -1 ? fullText.substring(transcriptEnd + 13) : '';
                        const tail50 = summaryText.trim().slice(-50);
                        // [20260807] phase1と同じ理由で「■要約完了」も許容する。
                        const normTail50 = tail50.replace(/[ 　]/g, '');
                        const hasEndTag = normTail50.includes('■要約完了') || normTail50.includes('■要約終了');
                        const hasConclusion = summaryText.includes('■ 結論');
                        const hasMainPoints = summaryText.includes('■ 主なポイント');
                        const hasTitle = summaryText.includes('■ タイトル');
                        const hasKeywords = summaryText.includes('■ キーワード');
                        const completedSections = [hasTitle, hasKeywords, hasConclusion, hasMainPoints].filter(Boolean).length;
                        const animatedCount = Array.from(document.querySelectorAll('*')).filter(el => {
                            const style = window.getComputedStyle(el);
                            const animationName = style.animationName || '';
                            const animationDuration = style.animationDuration || '';
                            return animationName !== 'none' && animationDuration !== '0s';
                        }).length;
                        const hasAnimation = animatedCount > 0;
                        let titleIdx = summaryText.indexOf('■ タイトル');
                        let actualLength = titleIdx > -1 ? summaryText.substring(titleIdx).length : summaryText.length;
                        return {
                            hasEndTag: hasEndTag,
                            hasConclusion: hasConclusion,
                            hasMainPoints: hasMainPoints,
                            completedSections: completedSections,
                            hasAnimation: hasAnimation,
                            animatedCount: animatedCount,
                            summaryLength: actualLength,
                            tail50: tail50,
                            transcriptFound: transcriptEnd > -1
                        };
                    })();
                """)

                current_length = page_text['summaryLength']

                if page_text.get('hasEndTag', False):
                    log_message(
                        f"SUMMARY_END_TAG_FOUND|phase=2|video_index={video_index}|elapsed={elapsed:.3f}|length={current_length}|tail50={page_text.get('tail50', '')}",
                        "INFO"
                    )
                    log_message(
                        f"Phase2完了: ■要約終了検出 (延長+{elapsed:.1f}秒, {current_length}文字)",
                        "SUCCESS"
                    )
                    return {'success': True, 'final_length': current_length}

                if (
                    current_length >= 300
                    and page_text.get('completedSections', 0) >= 3
                    and page_text.get('hasConclusion', False)
                    and page_text.get('hasMainPoints', False)
                    and not page_text.get('hasAnimation', True)
                ):
                    log_message(
                        f"Phase2完了: アニメーション停止バックアップ (延長+{elapsed:.1f}秒, {current_length}文字, sections={page_text.get('completedSections', 0)})",
                        "SUCCESS"
                    )
                    return {'success': True, 'final_length': current_length}

                last_summary_length = current_length

            except Exception as e:
                if any(k in str(e).lower() for k in ["read timed out", "timed out", "httpconnectionpool", "max retries exceeded"]):
                    raise Exception(f"FATAL: Communication Lost during Phase2 Wait: {e}")
                if "FATAL" in str(e) or "RETRY" in str(e):
                    raise e
            
            time.sleep(0.5)
        
        return {'success': False, 'final_length': last_summary_length}

    def _update_timeout_after_success(self, actual_time: float, reset_threshold: float, extended: bool):
        if actual_time <= reset_threshold: self.current_base_timeout = self.min_timeout
        elif extended: self.current_base_timeout = min(self.current_base_timeout + self.timeout_extension, self.max_timeout)

    def _update_timeout_after_failure(self):
        self.current_base_timeout = min(self.current_base_timeout + self.timeout_extension, self.max_timeout)

    def _extract_summary_text(self) -> Optional[str]:
        try:
            time.sleep(0.5)
            extraction_result = self.driver.execute_script("""
                function isSummaryLike(text) {
                    const norm = text.replace(/[ 　]/g, '');
                    return (norm.includes('■タイトル') || norm.includes('▪タイトル')) && (norm.includes('■結論') || norm.includes('▪結論') || norm.includes('まとめ'));
                }
                const candidateSelectors = ['.model-response-text', 'message-content', '[data-message-id]', 'div[role="article"]', '.markdown'];
                let bestText = '';
                for (const selector of candidateSelectors) {
                    const elements = document.querySelectorAll(selector);
                    if (elements.length > 0) {
                        const text = elements[elements.length - 1].innerText || '';
                        if (isSummaryLike(text) && !text.includes('依頼内容：')) { bestText = text; break; }
                    }
                }
                if (!bestText) {
                    const messages = document.querySelectorAll('message-content, [data-message-id], .markdown, div[role="article"]');
                    for (let i = messages.length - 1; i >= 0; i--) {
                        const content = messages[i].innerText || '';
                        const normContent = content.replace(/[ 　]/g, '');
                        if ((normContent.includes('■タイトル') || normContent.includes('▪タイトル')) && !content.includes('#依頼内容') && !content.includes('<Transcript>')) {
                            bestText = content; break;
                        }
                    }
                }
                return { text: bestText };
            """)
            extracted_text = extraction_result.get('text', '')
            if extracted_text and len(extracted_text) > 100: return self._clean_extracted_text(extracted_text)
            
            full_text = self.driver.execute_script("return document.body ? document.body.innerText : '';")
            if full_text and len(full_text) > 200: return self._clean_extracted_text(full_text)
            return None
        except: return None

    def _clean_extracted_text(self, text: str) -> str:
        if not text: return ""
        for marker in ['#####', '-----', '<Task>']:
            if marker in text: text = text.split(marker)[0]
        unwanted_lines = ["Gemini は不正確な情報を表示する", "生成された回答を再確認", "Google で検索", "回答を書き換える", "共有", "ソース", "詳細情報"]
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line_str = line.strip()
            if not line_str:
                cleaned_lines.append(line_str)
                continue
            if not any(unwanted in line_str for unwanted in unwanted_lines):
                cleaned_lines.append(line_str)
        return '\n'.join(cleaned_lines).strip()

    def _extract_by_markers_js(self, full_text: str) -> Optional[str]:
        import re
        try:
            search_text = full_text
            for marker in ["</Transcript>", "-----ここまで出力形式例", "#####ここからが、ほしい文章の内容"]:
                pos = full_text.rfind(marker)
                if pos != -1:
                    search_text = full_text[pos + len(marker):]
                    break
            matches = list(re.finditer(r'^\s*■?\s*タイトル\s*[:：]?', search_text, re.MULTILINE))
            if not matches: return None
            start_pos = matches[-1].start()
            end_match = re.search(r'^\s*■?\s*要約(?:終了|完了)', search_text[start_pos:], re.MULTILINE)
            extracted = search_text[start_pos:start_pos + end_match.end()] if end_match else search_text[start_pos:]
            extracted = extracted.strip()
            return extracted if len(extracted) >= 100 else None
        except: return None

    def _extract_video_title_from_glasp(self, summary_text: str) -> Optional[str]:
        if not summary_text: return None
        import re
        for pattern in [r'■\s*タイトル[:：]\s*(.+?)(?:\n|■|▪|$)', r'▪\s*タイトル[:：]\s*(.+?)(?:\n|■|▪|$)']:
            match = re.search(pattern, summary_text)
            if match: return re.sub(r'[\[\]【】《》]', '', match.group(1).strip())
        return None
    
    def _match_titles(self, title1: str, title2: str) -> bool:
        if not title1 or not title2: return False
        import re
        norm1 = re.sub(r'\s+', '', re.sub(r'[^\w\s]', '', title1.lower()))
        norm2 = re.sub(r'\s+', '', re.sub(r'[^\w\s]', '', title2.lower()))
        if norm1 == norm2: return True
        if len(norm1) > 0 and len(norm2) > 0:
            if norm1 in norm2 or norm2 in norm1: return True
            if min(len(norm1), len(norm2)) / max(len(norm1), len(norm2)) > 0.8: return True
        return False
 
# ============================================================================
# SECTION 9: API ENGINE
# ============================================================================

class APIEngine:
    """API処理エンジン（Gemini/OpenAI）"""



    def __init__(self, youtube_handler=None):
        self.youtube_handler = youtube_handler or YouTubeHandler()
        self.rate_limiter = RateLimiter()
        
        # [20260408.13] log_to_ui の安全な定義（フォールバック）
        # UIからコールバックが渡されるまでの間、または渡されなかった場合に
        # AttributeError にならないよう、標準のログ関数に逃がす
        if not hasattr(self, 'log_to_ui'):
            self.log_to_ui = lambda msg, level="INFO": log_message(msg, level)
    
    def _init_apis(self):
        """APIの初期化"""
        # Gemini API
        gemini_key = config_manager.get('api.gemini_api_key')
        if gemini_key:
            genai.configure(api_key=gemini_key)
            log_message("Gemini API初期化完了", "SUCCESS")
        
        # OpenAI API
        if OPENAI_AVAILABLE:
            openai_key = config_manager.get('api.openai_api_key')
            if openai_key:
                openai.api_key = openai_key
                log_message("OpenAI API初期化完了", "SUCCESS")


    def process_videos(self, videos: List[VideoInfo], 
                       config: ProcessConfig,
                       playlist_id: Optional[str] = None) -> List[SummaryResult]:
        """Glaspを使用して動画を処理（リミッター＆構造修正・動的プロパティ対応版＋敗者復活戦追加）"""
        import traceback
        results_dict = {}
        failed_videos = []
        batch_size = config.batch_size
        log_message(f"=== Glaspバッチ処理開始: {len(videos)}個の動画 ===", "INFO")
        
        try:
            total_batches = (len(videos) + batch_size - 1) // batch_size
            state.total_batches = total_batches
            start_idx = 0
            batch_idx = 0
            retry_count_for_current_batch = 0
            processed_count_since_restart = 0 
            
            # 1. 通常のバッチ処理ループ
            while start_idx < len(videos):
                if check_user_input() == 'cancel': break
                
                # リミッター：メモリ浄化のためブラウザを再起動
                if processed_count_since_restart >= 30: # 10本か30本かは状況に合わせて
                    log_message("🧹 リミッター: メモリ浄化のためブラウザを再起動します", "PROCESS")
                    if self.browser.force_restart_browser(is_auto_mode=auto_mode_manager.is_enabled()):
                        # self.driver = ... の代入は @property 化されたため削除済み
                        self.tab_tracker = TabTracker() 
                        self.is_first_run_in_session = True
                        self.youtube_tabs_pool = []
                        processed_count_since_restart = 0
                        time.sleep(3)
                
                end_idx = min(start_idx + batch_size, len(videos))
                batch_videos = videos[start_idx:end_idx]
                state.update_batch_progress(batch_idx, total_batches)
                
                try:
                    batch_results = self._process_batch(batch_videos, batch_idx, config, playlist_id)
                    for res in batch_results:
                        results_dict[res.video_info.video_id] = res
                        if not res.success:
                            failed_videos.append(res.video_info)
                            
                    start_idx = end_idx
                    batch_idx += 1
                    processed_count_since_restart += len(batch_videos)
                    retry_count_for_current_batch = 0
                    
                except Exception as e:
                    log_message(f"🚨 バッチ処理例外:\n{traceback.format_exc()}", "ERROR")
                    if "FATAL" in str(e):
                        if self.browser.force_restart_browser(is_auto_mode=auto_mode_manager.is_enabled()):
                            # self.driver = ... の代入は @property 化されたため削除済み
                            self.is_first_run_in_session = True
                            self.youtube_tabs_pool = []
                        retry_count_for_current_batch += 1
                        if retry_count_for_current_batch >= 2:
                            start_idx = end_idx
                            batch_idx += 1
                            retry_count_for_current_batch = 0
                        continue
                    else:
                        start_idx = end_idx
                        batch_idx += 1
                        continue

            # 2. 敗者復活戦（リトライループ）
            if failed_videos and check_user_input() != "cancel":
                log_message(f"=== 敗者復活戦を開始します（対象: {len(failed_videos)}件） ===", "INFO")
                state.update_status(f"敗者復活戦を実行中... (対象: {len(failed_videos)}件)")
                
                # プログレスバーの超過を防ぐため、失敗した件数分だけ進捗を戻す
                state.current_progress = max(0, state.current_progress - len(failed_videos))
                
                # ゾンビタブ対策: ブラウザを強制再起動して完全にクリーンな状態を作る
                log_message("🧹 敗者復活戦の前にブラウザを再起動し、クリーンな状態にします", "PROCESS")
                if self.browser.force_restart_browser(is_auto_mode=auto_mode_manager.is_enabled()):
                    self.tab_tracker = TabTracker() 
                    self.is_first_run_in_session = True
                    self.youtube_tabs_pool = []
                    time.sleep(3)

                retry_batch_idx = batch_idx + 1
                for i in range(0, len(failed_videos), batch_size):
                    if check_user_input() == "cancel": break
                    batch = failed_videos[i:i + batch_size]
                    
                    retry_results = self._process_batch(batch, retry_batch_idx + (i // batch_size), config, playlist_id)
                    
                    for res in retry_results:
                        results_dict[res.video_info.video_id] = res

        except Exception as e:
            log_message(f"全体例外: {e}", "ERROR")
        finally:
            if not playlist_id: self._final_cleanup()
            
            # 3. 最終出力の整理（元の順序にソート）
            final_results = list(results_dict.values())
            original_order = {v.video_id: idx for idx, v in enumerate(videos)}
            final_results.sort(key=lambda x: original_order.get(x.video_info.video_id, 9999))
            
            return final_results

    def _process_single_video(self, video: VideoInfo, 
                             config: ProcessConfig) -> SummaryResult:
        """単一動画の処理（標準ライブラリ準拠・自動リトライ対応版）"""
        start_time = time.time()
        
        try:
            # 公式ライブラリの標準仕様に完全準拠
            from youtube_transcript_api import YouTubeTranscriptApi
            
            try:
                # ユーザーの最新の修正に従い、委譲されたHandlerから取得する（VERSION 20260410.01-02 準拠）
                # ※ここが get_transcript(video.video_id) で動いているという前提を維持します
                transcript, language = self.youtube_handler.get_transcript(video.video_id)
            except Exception as api_e:
                # Cookie読み込みエラーや、字幕がそもそも存在しない場合のエラーハンドリング
                if hasattr(self, 'log_to_ui'):
                    self.log_to_ui(f"字幕取得APIエラー ({video.video_id}): {api_e}", "WARNING")
                transcript = None
                language = ''
            
            if not transcript:
                return SummaryResult(
                    video_info=video,
                    success=False,
                    error_message="トランスクリプト取得失敗（字幕なし、またはCookieエラー）",
                    model_used=config.model,
                    processing_time=time.time() - start_time
                )
            
            # 文字数制限（モデルに応じて調整）
            max_chars = MODEL_CONFIG[config.model].get('max_tokens', 8192) * 2
            original_transcript = transcript  # 元のトランスクリプトを保存
            if len(transcript) > max_chars:
                transcript = transcript[:max_chars]
                if hasattr(self, 'log_to_ui'):
                    self.log_to_ui(f"トランスクリプトを{max_chars}文字に切り詰めました", "INFO")
            
            # プロンプト生成
            prompt = self._create_prompt(transcript)
            
            # 要約生成（生レスポンスを取得）
            raw_response = None
            model_config = MODEL_CONFIG.get(config.model)
            
            # [20260410.03] リトライ付きの安全なラッパー経由で呼び出し
            raw_response = self._generate_with_retry(model_config['provider'], prompt, model_config['model_id'])
            
            if not raw_response:
                return SummaryResult(
                    video_info=video,
                    success=False,
                    error_message="要約生成失敗（リトライ上限到達または致命的エラー）",
                    model_used=config.model,
                    raw_transcript=original_transcript,
                    processing_time=time.time() - start_time
                )
            
            # 要約部分のみを抽出
            formatted_summary = self.extract_summary_from_response(raw_response)
            
            # コスト計算
            cost = estimate_cost(len(transcript), config.model)
            
            return SummaryResult(
                video_info=video,
                success=True,
                summary=formatted_summary,  # 後方互換性のため
                raw_transcript=original_transcript,
                raw_response=raw_response,
                formatted_summary=formatted_summary,
                model_used=config.model,
                cost=cost,
                transcript_length=len(original_transcript),
                language=language,
                processing_time=time.time() - start_time
            )
            
        except Exception as e:
            error_msg = str(e)
            
            # レート制限エラーの検出
            if any(x in error_msg.lower() for x in ['rate limit', 'too many', '429']):
                error_msg = "YouTubeレート制限エラー - しばらく待ってから再試行してください"
            
            return SummaryResult(
                video_info=video,
                success=False,
                error_message=error_msg,
                model_used=config.model,
                processing_time=time.time() - start_time
            )


    def _generate_with_retry(self, provider: str, prompt: str, model_id: str) -> Optional[str]:
        """
        API呼び出しをバックオフ付きでリトライ実行する安全なラッパー
        [20260410.03] 追加：429および500系エラー時に最大3回のリトライを行う
        """
        import time
        max_retries = 3
        wait_times = [15, 30, 60]
        
        for attempt in range(max_retries + 1):
            try:
                # プロバイダーに応じた既存メソッドの呼び出し
                if provider == 'google':
                    response = self._generate_with_gemini(prompt, model_id)
                elif provider == 'openai':
                    response = self._generate_with_openai(prompt, model_id)
                else:
                    return None
                
                # APIが正常に応答した場合（エラーが起きていなければループを抜けて返す）
                if response:
                    return response
                
                # もし内部で例外が握りつぶされて None が返った場合は、
                # エラー詳細が不明なためリトライせず即時終了（安全側へ倒す）
                return None

            except Exception as e:
                error_msg = str(e).lower()
                is_retryable = False
                
                # 429 レート制限 または 500番台 サーバーエラーの判定
                if any(code in error_msg for code in ['429', 'too many', 'rate limit', 'quota', '500', '502', '503', '504']):
                    is_retryable = True
                    
                if is_retryable and attempt < max_retries:
                    wait_time = wait_times[attempt]
                    # UX対応: ログに警告を出力
                    if hasattr(self, 'log_to_ui'):
                        self.log_to_ui(f"API制限/サーバー高負荷を検出。{wait_time}秒待機して再試行します ({attempt + 1}/{max_retries}回目): {e}", "WARNING")
                    
                    # 割り込み可能なスリープ（Interruptible Sleep）
                    for _ in range(wait_time):
                        cancel_requested = False
                        try:
                            # 既存のグローバル関数・状態からユーザーのキャンセルを監視（推測を排した安全なチェック）
                            if 'check_user_input' in globals() and globals()['check_user_input']() == 'cancel':
                                cancel_requested = True
                            elif 'state' in globals() and hasattr(globals()['state'], 'is_running') and not globals()['state'].is_running:
                                cancel_requested = True
                        except Exception:
                            pass # キャンセル判定機構がない場合は無視して待機続行
                        
                        if cancel_requested:
                            if hasattr(self, 'log_to_ui'):
                                self.log_to_ui("待機中にユーザーからキャンセルが要求されました。リトライを中止します。", "WARNING")
                            return None
                        
                        time.sleep(1)
                    continue # 待機完了後、次のリトライループへ進む
                else:
                    # リトライ対象外のエラー（400番台など）、またはリトライ上限到達
                    if hasattr(self, 'log_to_ui'):
                        self.log_to_ui(f"APIエラー（リトライ不可または上限到達）: {e}", "ERROR")
                    return None
                    
        return None

    def _generate_with_gemini(self, prompt: str, model_id: str) -> Optional[str]:
        """Gemini APIで要約生成"""
        try:
            model = genai.GenerativeModel(model_id)
            response = model.generate_content(prompt)
            
            # 生のレスポンステキストを取得
            raw_text = response.text
            
            # ログ出力（デバッグ用）
            log_message(f"Gemini応答取得: {len(raw_text)}文字", "INFO")
            
            return raw_text  # 生のテキストを返す（抽出は_generate_summaryで行う）
            
        except Exception as e:
            log_message(f"Gemini API エラー: {e}", "ERROR")
            return None
    
    def _generate_with_openai(self, prompt: str, model_id: str) -> Optional[str]:
        """OpenAI APIで要約生成"""
        if not OPENAI_AVAILABLE:
            log_message("OpenAI APIが利用できません", "ERROR")
            return None
        
        try:
            response = openai.ChatCompletion.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "あなたは動画内容を的確に要約する専門家です。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.7
            )
            
            # 生のレスポンステキストを取得
            raw_text = response.choices[0].message.content
            
            # ログ出力（デバッグ用）
            log_message(f"OpenAI応答取得: {len(raw_text)}文字", "INFO")
            
            return raw_text  # 生のテキストを返す（抽出は_generate_summaryで行う）
            
        except Exception as e:
            log_message(f"OpenAI API エラー: {e}", "ERROR")
            return None


    def extract_summary_from_response(self, response_text: str) -> str:
        """API応答から要約部分のみを抽出（■と▪両対応版）"""
        if not response_text:
            return ""
        
        import re
        
        # まず</Transcript>を探して、それ以降を対象にする
        search_text = response_text
        if '</Transcript>' in response_text:
            idx = response_text.find('</Transcript>')
            search_text = response_text[idx + len('</Transcript>'):]
        elif '</transcript>' in response_text.lower():
            # 小文字版も念のためチェック
            idx = response_text.lower().find('</transcript>')
            search_text = response_text[idx + 13:]  # len('</transcript>') = 13
        
        # search_textから「タイトル」を探す（■と▪の両方）
        title_match_square = '■ タイトル' in search_text
        title_match_bullet = '▪ タイトル' in search_text
        
        if title_match_square or title_match_bullet:
            # タイトルの開始位置を見つける
            idx_square = search_text.find('■ タイトル') if title_match_square else -1
            idx_bullet = search_text.find('▪ タイトル') if title_match_bullet else -1
            
            # 最初に見つかった方を使用
            if idx_square >= 0 and (idx_bullet < 0 or idx_square < idx_bullet):
                idx = idx_square
            elif idx_bullet >= 0:
                idx = idx_bullet
            else:
                idx = -1
            
            if idx >= 0:
                summary_text = search_text[idx:].strip()
                
                # 次のプロンプトマーカーがあれば、そこまでを取得
                end_markers = ['#####', '-----', '<Task>', '<ContentTitle>']
                for marker in end_markers:
                    if marker in summary_text:
                        end_idx = summary_text.find(marker)
                        summary_text = summary_text[:end_idx].strip()
                        break
                
                # Glasp/GeminiのUI要素を削除
                summary_text = OutputGenerator.clean_glasp_artifacts(summary_text)
                
                # フォーマットの統一性確認（■と▪の両方をチェック）
                required_keywords = ['タイトル', '要旨', 'キーワード', '結論', '主なポイント']
                missing_sections = []
                for keyword in required_keywords:
                    if not (f'■ {keyword}' in summary_text or f'▪ {keyword}' in summary_text):
                        missing_sections.append(keyword)
                
                if missing_sections:
                    log_message(f"警告: 要約に不足セクション: {', '.join(missing_sections)}", "WARNING")
                
                return summary_text
        
        # フォールバック: パターンマッチング（■と▪の両方）
        patterns = [
            r'([■▪]\s*タイトル[：:].+?)(?:#{5}|$)',
            r'---\s*(?:ここから)?.*?\n([■▪].+?)(?:---|\Z)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, search_text, re.DOTALL)
            if match:
                result = match.group(1).strip()
                # UI要素を削除
                result = OutputGenerator.clean_glasp_artifacts(result)
                return result
        
        # 最終フォールバック: ■または▪で始まる最後のセクションを探す
        if '■' in search_text or '▪' in search_text:
            sections = search_text.split('\n\n')
            for section in reversed(sections):
                if section.strip().startswith('■') or section.strip().startswith('▪'):
                    result = section.strip()
                    # UI要素を削除
                    result = OutputGenerator.clean_glasp_artifacts(result)
                    return result
        
        # 何も見つからない場合は空文字列を返す
        return ""



    
    def _create_prompt(self, transcript: str) -> str:
        """要約生成用プロンプト"""
        return f"""
#依頼内容：
あなたは、記事や動画の作者の意図を十分くみとって、わかりやすく内容を読者に伝えることを専門としている要約のプロフェッショナルライターです。

以下の指示にしたがって、文章を日本語で要約します。
それぞれの内容は、段階的にキャンバスではなくチャット上で日本語で説明して下さい。
高校生にでも理解できるように、専門的な用語は解説を入れるか、平易な言葉を併記するようにしてください。
下記内容以外の受け答えや、作業をスタートするにあたっての会話を出力する必要はありません。

#1 全体の内容を俯瞰した上で、この記事にふさわしいタイトルを記載して下さい。
#2 全体の内容を要約し、50文字以内で簡潔な「要旨」を記載してください。
#3  全体の内容を俯瞰した上で、300文字程度でこの記事関する結論をまとめてください。
#4 この記事にTagを付ける事を目的として記事の内容に関連するキーワードを３つ以上抽出して、箇条書きではなく、コンマで区切って","提示して下さい。
#5 最後に、記事の内容をマークアップ形式でまとめます。
   主なポイントを最適な分類を行ってください。
　主なポイントは、箇条書きで３項目以上で構成して下さい。
    主なポイントの分類として必要な場合は、個数に上限は設定しません。
　例えば、今週のTOP10や、本日の20選など、具体的なトピックスの数が規定されている場合は、それらを省略することなく項目として扱ってください。
各ポイントは、そのタイトルとは別に、できるだけシンプルに要約するために100文字程度の箇条書きの文章で説明してください。
100文字程度の文章で説明するために、 出力前に必ず文章の文字数をカウントして100文字を超えている場合は、
100文字程度に収まるように推敲をくりかえして下さい。必要に応じて箇条書きの文章をわけてもよいです。

#### 出力形式例
---
■タイトル：[タイトル]
■要旨：[50文字以内の要旨の内容]
■キーワード：[キーワード1, キーワード2, キーワード3]
■結論：
[結論の内容]

▪ 主なポイント：
1. **[ポイント1のタイトル]**
   ・[ポイント1の説明文1]
   ・[ポイント1の説明文2]

2. **[ポイント2のタイトル]**
   ・[ポイント2の説明文1]
   ・[ポイント2の説明文2]

3. **[ポイント3のタイトル]**
   ・[ポイント3の説明文1]
   ・[ポイント3の説明文2]

■要約完了
---

#####ここからが、要約してほしい文章の内容
{transcript}
"""

# ============================================================================
# SECTION 10: OUTPUT GENERATION
# ============================================================================


class OutputGenerator:
    """出力生成クラス"""

    @staticmethod
    def convert_markdown_to_html(markdown_text: str) -> str:
        """マークダウン形式をHTMLに変換"""
        if not markdown_text:
            return ""
        
        import re
        
        # タイトルとキーワードの行を削除
        markdown_text = re.sub(r'^[▪■]\s*タイトル[:：].*$\n?', '', markdown_text, flags=re.MULTILINE)
        markdown_text = re.sub(r'^[▪■]\s*キーワード[:：].*$\n?', '', markdown_text, flags=re.MULTILINE)
        markdown_text = re.sub(r'^[▪■]\s*要旨[:：].*$\n?', '', markdown_text, flags=re.MULTILINE)
        
        # HTMLエスケープ
        html_text = markdown_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # 太字の変換
        html_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_text)
        
        # 改行を<br>に変換
        html_text = re.sub(r'(?<!>)\n(?!<)', '<br>\n', html_text)
        
        return f'<div class="markdown-content" style="line-height: 1.8;">{html_text}</div>'



    @staticmethod
    def format_text(text: str) -> str:
        """テキストをHTML形式に整形（太字変換・広範なリスト記号対応・青色強調準備）"""
        if not text:
            return ""
        
        import re
        
        lines = text.split('\n')
        html_lines = []
        in_list = False
        
        for line in lines:
            stripped = line.strip()
            
            # リスト項目の検出 (*, -, ・, •, ●, ○ で始まる行) -> 小項目
            if stripped.startswith(('* ', '- ', '・', '•', '●', '○')):
                if not in_list:
                    html_lines.append('<ul class="markdown-list">')
                    in_list = True
                
                # 対応する箇条書き記号をきれいに削除してリスト化
                content = re.sub(r'^[\*\-・•●○]\s*', '', stripped)
                html_lines.append(f'<li>{content}</li>')
            else:
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                
                if stripped: 
                    # マークダウンの太字をHTMLタグに変換
                    stripped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)

                    # 数字付き見出し (例: "1. 導入") -> 中項目
                    # 青色 (#0056b3) で強調表示
                    if re.match(r'^\d+\.', stripped):
                        html_lines.append(f'<p class="fw-bold mt-3 mb-1" style="color:#2b6cb0; font-size:1.05em;">{stripped}</p>')
                    else:
                        html_lines.append(f'<p>{stripped}</p>')
        
        if in_list:
            html_lines.append('</ul>')
            
        return "\n".join(html_lines)

    @staticmethod
    def extract_section(text: str, pattern: str) -> str:
        """正規表現でセクションを抽出するヘルパー"""
        import re
        if not text: return ""
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip().replace('**', '')
        return ""


    @staticmethod
    def clean_glasp_artifacts(text: str) -> str:
        """GlaspのUI要素を削除"""
        if not text: return text
        import re
        unwanted_patterns = [
            r'^YouTube\s*$', r'^Gemini.*$', r'^コピー\s*$', r'^Copy\s*$',
            r'^再生成\s*$', r'^共有\s*$', r'^Share\s*$', r'^戻る\s*$', r'^次へ\s*$'
        ]
        for pattern in unwanted_patterns:
            text = re.sub(pattern, '', text, flags=re.MULTILINE | re.IGNORECASE)
        return text.strip()

    @staticmethod
    def save_json(results: List[SummaryResult], playlist_id: Optional[str] = None) -> str:
        """結果をJSON形式で保存"""
        if not results: return ""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"summary_{playlist_id}_{timestamp}.json" if playlist_id else f"summary_{timestamp}.json"
        # [20260809] HTMLと違いJSONはConsolidated Manager(RSS側)のarchive移動対象
        # 外で、OUTPUT_DIR直下に際限なく溜まり続けていた。jsonサブフォルダへ出す。
        # morning_brief.py側は既にos.walkで再帰的に走査しているため、
        # このサブフォルダに置いても集計から漏れない。
        json_dir = os.path.join(OUTPUT_DIR, "json")
        try:
            os.makedirs(json_dir, exist_ok=True)
        except Exception:
            json_dir = OUTPUT_DIR
        filepath = os.path.join(json_dir, filename)
        data = {
            "processing_date": datetime.now().isoformat(),
            "results": [r.to_dict_full() for r in results]
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log_message(f"JSON保存完了: {filepath}", "SUCCESS")
        return filepath

    @staticmethod
    def generate_html(results: List[SummaryResult], template: str = 'modern', playlist_id: Optional[str] = None) -> str:
        """HTML形式でレポートを生成"""
        if not results: return None
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename_prefix = clean_filename(playlist_id[:30]) if playlist_id else "summary"
        filename = f'summary_{filename_prefix}_{timestamp}.html'
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        if template == 'modern':
            html_content = OutputGenerator._generate_modern_html(results)
        else:
            html_content = OutputGenerator._generate_simple_html(results)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        log_message(f"HTMLレポート生成: {filepath}", "INFO")
        return filepath




    @staticmethod
    def _generate_modern_html(results: List[SummaryResult]) -> str:
        """モダンなHTMLテンプレート（登録者数表示追加版・スマホタップ最適化版）"""
        dt = datetime.now()
        date_str = dt.strftime("%Y年%m月%d日")
        time_str = dt.strftime("%H:%M")
        total_count = len(results)
        success_count = sum(1 for r in results if r.success)
        # [20260701_01_01] お気に入りチャンネルを読み込む（★マーク表示用）
        try:
            with open("learned_channels.json", 'r', encoding='utf-8') as _fav_f:
                favorites_set = set(json.load(_fav_f).get('favorites', []) or [])
        except Exception:
            favorites_set = set()
        # [20260711_01] お気に入りチャンネルの動画を先頭に配置（各グループ内はプレイリスト順を維持）
        results = sorted(results, key=lambda r: 0 if r.video_info.channel in favorites_set else 1)
        html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>要約レポート - {date_str}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ font-family: "Segoe UI", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif; background-color: #f8f9fa; color: #333; padding-bottom: 80px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 2rem; margin-bottom: 2rem; border-radius: 0 0 1rem 1rem; }}
        .stats-card {{ background: white; border-radius: 0.5rem; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .video-card {{ scroll-margin-top: 20px; background: white; border-radius: 0.5rem; padding: 2rem; margin-bottom: 2rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1); position: relative; border: 2px solid transparent; }}
        .video-card.active-card {{ border: 2px solid #667eea; }}
        .video-header-layout {{ display: flex; gap: 20px; margin-bottom: 1.0rem; align-items: flex-start; }}
        .video-thumbnail-container {{ flex-shrink: 0; width: 240px; }}
        .video-thumbnail-img {{ width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); aspect-ratio: 16 / 9; object-fit: cover; }}
        .video-meta-container {{ flex-grow: 1; display: flex; flex-direction: column; justify-content: flex-start; min-height: 80px; }}
        @media (max-width: 768px) {{
            .video-card {{ padding: 1.2rem; }}
            .video-header-layout {{ flex-direction: row; gap: 15px; }}
            .video-thumbnail-container {{ width: 120px; }}
            .video-title {{ font-size: 1.1rem !important; line-height: 1.3; }}
        }}
        .video-title {{ color: #2d3748; font-weight: 700; font-size: 1.4rem; margin-bottom: 0.8rem; line-height: 1.3; }}
        .channel-info {{ color: #4a5568; font-size: 0.95rem; font-weight: 600; }}
        .one-liner-box {{ background-color: #f0f7ff; border-left: 5px solid #3182ce; padding: 10px 15px; border-radius: 4px; color: #2c5282; font-weight: 600; font-size: 1.0rem; line-height: 1.5; margin-bottom: 1.2rem; }}
        .conclusion-text {{ font-size: 1.05rem; line-height: 1.8; color: #4a5568; margin-bottom: 1.5rem; }}
        .keyword-badge {{ display: inline-block; padding: 0.35rem 0.8rem; margin: 0.25rem 0.25rem 0.25rem 0; background: #edf2f7; color: #4a5568; border-radius: 9999px; font-size: 0.9rem; font-weight: 600; }}
        .collapse-button {{ background: #667eea; color: white; border: none; padding: 0.6rem 1.5rem; border-radius: 0.5rem; cursor: pointer; transition: background 0.2s; }}
        .collapse-content {{ max-height: 0; overflow: hidden; transition: max-height 0.3s ease-out; }}
        .collapse-content.show {{ max-height: 10000px; transition: max-height 0.5s ease-in; }}
        .speak-btn {{ white-space: nowrap; height: fit-content; }}
        
        .nav-fab-container {{ position: fixed; top: 50%; right: 20px; transform: translateY(-50%); display: flex; flex-direction: column; gap: 15px; z-index: 1000; pointer-events: none; }}
        .nav-fab-btn {{ pointer-events: auto; width: 56px; height: 56px; border-radius: 50%; background-color: rgba(0, 0, 0, 0.05); border: 1px solid rgba(0, 0, 0, 0.05); color: #667eea; text-shadow: 1px 1px 0 #fff, -1px 1px 0 #fff, 1px -1px 0 #fff, -1px -1px 0 #fff, 0 2px 5px rgba(0,0,0,0.3); font-size: 32px; cursor: pointer; display: flex; align-items: center; justify-content: center; user-select: none; -webkit-user-select: none; touch-action: manipulation; -webkit-tap-highlight-color: transparent; }}
        .nav-indicator {{ pointer-events: auto; background: rgba(0, 0, 0, 0.4); color: white; padding: 2px 8px; border-radius: 10px; text-align: center; font-size: 0.8rem; margin-bottom: 5px; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <div id="top-header" class="header text-center" data-index="0">
            <h1>要約レポート</h1>
            <p class="mb-0">生成日時: {date_str} {time_str}</p>
        </div>
        <div class="row mb-4">
            <div class="col-md-6"><div class="stats-card text-center"><h3>{total_count}</h3><p class="text-muted mb-0">総件数</p></div></div>
            <div class="col-md-6"><div class="stats-card text-center"><h3>{success_count}</h3><p class="text-muted mb-0">成功</p></div></div>
        </div>
        <div id="videoContainer">
"""
        for i, result in enumerate(results, 1):
            video = result.video_info
            card_id = f"card-{i}"
            video_id = f"video_{i}"
            
            video_link = f'<a href="{video.url}" target="_blank" style="color:#667eea; font-weight:600; text-decoration:none;">動画を開く &#x2197;</a>' if video.url else ""
            gemini_url = getattr(result, 'gemini_url', '')
            gemini_link = f'<a href="{gemini_url}" target="_blank" style="color:#8e44ad; font-weight:600; text-decoration:none; margin-left:20px;">Geminiで開く &#x2197;</a>' if gemini_url else ""

            if not result.success:
                # [20260808] 属性名の誤りを修正。SummaryResultが持つのは
                # error_message であり error_msg ではないため、getattrは常に
                # 既定値の'要約失敗'を返し、実際の失敗理由は毎回捨てられていた。
                # 1日30本以上の失敗が「要約失敗」の一語だけで記録されており、
                # 原因の切り分けが不可能な状態だった。
                # skip_reason にも理由が入る経路があるため、順に拾う。
                error_msg = (getattr(result, 'error_message', '')
                             or getattr(result, 'skip_reason', '')
                             or '要約失敗（理由の記録なし）')
                html += f"""
            <div id="{card_id}" class="video-card error-card" data-index="{i}">
                <div class="video-title">{i}. {video.title}</div>
                <div class="alert alert-danger mt-3">{error_msg}</div>
                <div class="mt-3">
                    {video_link}
                    {gemini_link}
                </div>
            </div>"""
                continue
                
            summary_text = result.formatted_summary or result.summary
            
            ai_title = OutputGenerator.extract_section(summary_text, r'(?:^|\n)\s*[■▪\-*]?\s*(?:\*\*)?タイトル(?:\*\*)?[:：]?\s*(.*?)(?=(?:^|\n)\s*[■▪]|$)')
            display_title = ai_title if ai_title else video.title
            one_liner = OutputGenerator.extract_section(summary_text, r'(?:^|\n)\s*[■▪\-*]?\s*(?:\*\*)?(?:要旨|一行要約|要約)(?:\*\*)?[:：]?\s*(.*?)(?=(?:^|\n)\s*[■▪]|$)')
            conclusion = OutputGenerator.extract_section(summary_text, r'(?:^|\n)\s*[■▪\-*]?\s*(?:\*\*)?結論(?:\*\*)?[:：]?\s*(.*?)(?=(?:^|\n)\s*[■▪]|$)')
            
            kw_list = getattr(result, 'keywords', [])
            if not kw_list and summary_text:
                kw_str = OutputGenerator.extract_section(summary_text, r'(?:^|\n)\s*[■▪\-*]?\s*(?:\*\*)?キーワード(?:\*\*)?[:：]?\s*(.*?)(?=(?:^|\n)\s*[■▪]|$)')
                if kw_str:
                    kw_list = [k.strip() for k in kw_str.replace('、', ',').replace('　', ',').replace(' ', ',').split(',') if k.strip()]
                    
            kw_html = "".join([f'<span class="keyword-badge">{kw}</span>' for kw in kw_list])
            
            points_html = ""
            points_data = result.extract_main_points()
            if points_data:
                for point in points_data:
                    points_html += f'<p class="fw-bold mt-3 mb-1" style="color:#2b6cb0; font-size:1.05em;">{point["title"]}</p>'
                    points_html += OutputGenerator.format_text(point["details"])
            else:
                points_text = OutputGenerator.extract_section(summary_text, r'(?:^|\n)\s*[■▪\-*]?\s*(?:\*\*)?主なポイント(?:\*\*)?[:：]?\s*(.*?)(?=(?:^|\n)\s*[■▪]要約終了|\Z)')
                points_html = OutputGenerator.format_text(points_text)
            
            # [20260602_01_01] 登録者数 + 再生時間の表示を組み立て
            sub_count = getattr(video, 'subscriber_count', '')
            dur_sec = getattr(video, 'duration', 0)
            dur_str = format_duration(dur_sec) if dur_sec > 0 else ''
            sub_html = (
                f"<span style='font-size:0.9em; color:#e53e3e; font-weight:700; "
                f"margin-left:8px;'>(登録者数: {sub_count})</span>"
            ) if sub_count else ''
            dur_html = (
                f"<span style='font-size:0.9em; color:#2b6cb0; font-weight:700; "
                f"margin-left:8px;'>&#x23F1; {dur_str}</span>"
            ) if dur_str else ''
            fav_html = (
                "<span style='color:#d4a017; font-size:1.0em; margin-right:4px;'>★</span>"
            ) if video.channel in favorites_set else ''
            channel_display = f"{fav_html}{video.channel}{sub_html}{dur_html}"
            
            html += f"""
            <div id="{card_id}" class="video-card" data-index="{i}">
                <div class="video-header-layout">
                    <div class="video-thumbnail-container">
                        <img src="{video.thumbnail_url}" class="video-thumbnail-img" alt="Thumbnail">
                    </div>
                    <div class="video-meta-container" style="width: 100%;">
                        <div class="video-title" id="t-txt-{i}">{i}. {display_title}</div>
                        <div class="d-flex justify-content-between align-items-center">
                            <div class="channel-info">{channel_display}</div>
                            <button id="btn-speak-{i}" class="btn btn-sm btn-outline-primary speak-btn" onclick="toggleSpeech({i})">🔊 読み上げ</button>
                        </div>
                    </div>
                </div>
                <div class="one-liner-box" id="s-txt-{i}">{one_liner}</div>
                <div class="keyword-section mb-3">{kw_html}</div>
                <div class="channel-info" style="margin-bottom: 0.8rem;">{video.title}</div>
                <div class="conclusion-text" id="c-txt-{i}">{OutputGenerator.format_text(conclusion)}</div>
                <button class="collapse-button" onclick="toggleDetails('{video_id}')">主なポイントを表示</button>
                <div id="details-{video_id}" class="collapse-content">
                    <div id="points-{i}" class="section-content mt-3">{points_html}</div>
                </div>
                <div class="mt-3">
                    {video_link}
                    {gemini_link}
                </div>
            </div>"""

        html += f"""
        </div>
    </div>
    <div class="nav-fab-container">
        <div id="navIndicator" class="nav-indicator">Top</div>
        <button id="btnSkip" class="nav-fab-btn" style="font-size: 20px; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; touch-action: manipulation;" oncontextmenu="return false;">⏩</button>
        <button onclick="changeSpeed()" class="nav-fab-btn" id="btnSpeed" style="font-size: 16px; font-weight: bold;">--x</button>
        <button onclick="scrollToPrev()" class="nav-fab-btn" id="btnPrev">▲</button>
        <button onclick="scrollToNext()" class="nav-fab-btn" id="btnNext">▼</button>
        <button onclick="stopAllSpeech()" class="nav-fab-btn" id="btnStopSpeech" style="display: none; background-color: #ffcccc; color: #dc3545; font-size: 24px; border: 1px solid #dc3545;">⏹</button>
    </div>

    <script>
    function toggleDetails(id) {{ 
        const el = document.getElementById("details-" + id);
        el.classList.toggle("show"); 
        const btn = event.target;
        btn.textContent = el.classList.contains("show") ? "主なポイントを隠す" : "主なポイントを表示";
    }}

    let currentIndex = 0; const totalCount = {total_count}; let isAutoScrolling = false;
    let currentUttr = null; let isPlayingContinuous = false; let currentPart = 'main';
    let isSkipMode = true;
    let isTempNormal = false;

    let speedOptions = [1.5, 2.0, 3.0, 3.5];
    let currentSpeedRate = 1.5;
    const ua = navigator.userAgent;
    const isPC = /Windows|Macintosh|Linux/.test(ua) && !/iPhone|iPad|iPod|Android/.test(ua);
    if (isPC) {{
        currentSpeedRate = 3.0;
    }}

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
                btn.style.backgroundColor = "#667eea";
                btn.style.color = "white";
            }} else {{
                btn.style.backgroundColor = "";
                btn.style.color = "";
            }}
        }}
    }}

    function safeCancel() {{
        if (currentUttr) {{
            currentUttr.onend = null;
            currentUttr.onerror = null;
        }}
        window.speechSynthesis.cancel();
    }}

    function changeSpeed() {{
        let idx = speedOptions.indexOf(currentSpeedRate); idx = (idx + 1) % speedOptions.length; currentSpeedRate = speedOptions[idx];
        document.getElementById('btnSpeed').innerText = currentSpeedRate.toFixed(1) + "x";
        if (window.speechSynthesis.speaking) {{ 
            const activeIdx = currentUttr.articleIdx; const wasContinuous = isPlayingContinuous; 
            safeCancel(); 
            setTimeout(() => {{ isPlayingContinuous = wasContinuous; playPart(activeIdx, currentPart); }}, 300); 
        }}
    }}

    function toggleSpeech(idx) {{
        if (window.speechSynthesis.speaking && currentUttr && currentUttr.articleIdx === idx) {{ stopAllSpeech(); return; }}
        isPlayingContinuous = true; playPart(idx, 'main');
    }}

    function playPart(idx, part) {{
        safeCancel();
        currentPart = part; let txt = "";
        try {{
            if (part === 'main') {{
                txt = document.getElementById('t-txt-'+idx).innerText + "。　　" + document.getElementById('s-txt-'+idx).innerText + "。";
            }} else if (part === 'conclusion') {{
                txt = document.getElementById('c-txt-'+idx).innerText + "。";
            }} else if (part === 'points') {{
                txt = "主なポイント、　　" + document.getElementById('points-'+idx).innerText;
            }}
        }} catch(e) {{ moveToNextCard(idx); return; }}
        const ut = new SpeechSynthesisUtterance(txt); ut.lang = 'ja-JP'; ut.rate = currentSpeedRate; ut.articleIdx = idx;
        
        ut.onend = () => {{
            updateBtns(null); if (!isPlayingContinuous) return;
            if (part === 'main') {{
                if (isSkipMode) {{
                    moveToNextCard(idx);
                }} else {{
                    setTimeout(() => playPart(idx, 'conclusion'), 100);
                }}
            }} else if (part === 'conclusion') {{
                const col = document.getElementById('details-video_'+idx);
                if (col && col.classList.contains('show')) {{ setTimeout(() => playPart(idx, 'points'), 100); }}
                else {{ moveToNextCard(idx); }}
            }} else {{ moveToNextCard(idx); }}
        }};
        ut.onerror = () => {{ updateBtns(null); isPlayingContinuous = false; }};
        
        currentUttr = ut; window.speechSynthesis.speak(ut); updateBtns(idx);
    }}

    function moveToNextCard(idx) {{
        if (isTempNormal) {{
            isSkipMode = true;
            isTempNormal = false;
            updateSkipBtnUI();
        }}
        if (isPlayingContinuous && idx < totalCount) {{
            let next = idx + 1; scrollToCard(next); setTimeout(() => playPart(next, 'main'), 600);
        }} else {{ stopAllSpeech(); }}
    }}

    function stopAllSpeech() {{ isPlayingContinuous = false; safeCancel(); updateBtns(null); }}

    function updateBtns(playingIdx) {{
        document.querySelectorAll('.speak-btn').forEach(b => {{
            const i = parseInt(b.id.match(/\\d+/)[0]);
            if(i === playingIdx) {{ b.innerHTML = "⏹ 停止"; b.classList.add('btn-danger', 'text-white'); }} 
            else {{ b.innerHTML = "🔊 読み上げ"; b.classList.remove('btn-danger', 'text-white'); }}
        }});
        document.getElementById('btnStopSpeech').style.display = playingIdx ? 'flex' : 'none';
    }}

    function scrollToCard(index) {{
        if (index < 0 || index > totalCount) return;
        isAutoScrolling = true;
        if (index === 0) {{ window.scrollTo({{ top: 0, behavior: 'auto' }}); }}
        else {{ document.getElementById('card-' + index).scrollIntoView({{behavior: 'auto', block: 'start'}}); }}
        currentIndex = index; updateNavState(); setTimeout(() => {{ isAutoScrolling = false; }}, 800);
    }}

    function scrollToNext() {{ 
        if (currentIndex < totalCount) {{
            let n = currentIndex + 1; if(isPlayingContinuous) {{ safeCancel(); }}
            scrollToCard(n); if(isPlayingContinuous) {{ setTimeout(() => playPart(n, 'main'), 600); }}
        }} 
    }}

    function scrollToPrev() {{ 
        if (currentIndex > 0) {{
            let p = currentIndex - 1; if(isPlayingContinuous) {{ safeCancel(); }}
            scrollToCard(p); 
            if(isPlayingContinuous) {{
                if(p > 0) {{ setTimeout(() => playPart(p, 'main'), 600); }} else {{ stopAllSpeech(); }}
            }}
        }} 
    }}

    function updateNavState() {{
        document.getElementById('navIndicator').textContent = currentIndex === 0 ? "Top" : currentIndex + " / " + totalCount;
        document.querySelectorAll('.video-card').forEach(c => c.classList.remove('active-card'));
        if (currentIndex > 0) {{ document.getElementById('card-' + currentIndex).classList.add('active-card'); }}
    }}

    document.addEventListener('DOMContentLoaded', () => {{
        const btn = document.getElementById('btnSpeed');
        if(btn) btn.innerText = currentSpeedRate.toFixed(1) + "x";

        const obs = new IntersectionObserver((es) => {{
            if (isAutoScrolling) return;
            es.forEach(e => {{ if (e.isIntersecting) {{ currentIndex = parseInt(e.target.getAttribute('data-index') || 0); updateNavState(); }} }});
            if (window.scrollY < 50) {{ currentIndex = 0; updateNavState(); }}
        }}, {{ threshold: 0.1, rootMargin: "-40% 0px -40% 0px" }});
        document.querySelectorAll('.video-card, .header').forEach(el => obs.observe(el));
        
        window.addEventListener('scroll', () => {{
            if (isAutoScrolling) return;
            if (window.scrollY < 50 && currentIndex !== 0) {{ currentIndex = 0; updateNavState(); }}
        }});
        
        if (window.scrollY < 50) {{ currentIndex = 0; updateNavState(); }}

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

            btnSkip.addEventListener('pointerleave', (e) => {{
                skipBtnPressed = false;
                if (skipBtnTimer) clearTimeout(skipBtnTimer);
            }});
            btnSkip.addEventListener('pointercancel', (e) => {{
                skipBtnPressed = false;
                if (skipBtnTimer) clearTimeout(skipBtnTimer);
            }});
        }}
    }});
    </script>
</body></html>"""
        return html

# ============================================================================
# SECTION 11: UI COMPONENTS
# ============================================================================


class AutoTabSelectionDialog(tk.Toplevel):
    """プレイリストタブ選択ダイアログ（自動選択対応版）
    
    自動モードが有効な場合、5秒後に最初の項目を自動選択してクローズ。
    """
    
    def __init__(self, parent, playlist_tabs: List[Tuple[str, str, str]]):
        """初期化
        
        Args:
            parent: 親ウィンドウ
            playlist_tabs: プレイリストタブのリスト [(handle, title, url), ...]
        """
        super().__init__(parent)
        
        self.playlist_tabs = playlist_tabs
        self.selected_tab = None
        self.auto_timer_id = None
        
        self.title("プレイリスト選択")
        self.geometry("600x400")
        self.transient(parent)
        self.grab_set()
        
        # 中央配置
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_width()) // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
        
        self.setup_ui()
        
        # 自動モードチェック
        if auto_mode_manager.is_enabled():
            self.start_auto_timer()
    
    def setup_ui(self):
        """UI構築"""
        # ラベル
        label_text = "処理するプレイリストを選択してください："
        if auto_mode_manager.is_enabled():
            label_text += "\n（自動モード：5秒後に最初の項目を自動選択）"
        
        label = ttk.Label(self, text=label_text, font=("Arial", 11))
        label.pack(pady=10)
        
        # リストボックスフレーム
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.listbox = tk.Listbox(frame, font=("Arial", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        
        # リストアイテム追加
        for i, (handle, title, url) in enumerate(self.playlist_tabs):
            display_title = title[:60] + "..." if len(title) > 60 else title
            display_text = f"{i+1}. {display_title}"
            self.listbox.insert(tk.END, display_text)
            
            playlist_id = extract_playlist_id(url)
            if playlist_id:
                self.listbox.insert(tk.END, f"     List: {playlist_id[:30]}...")
            self.listbox.insert(tk.END, "")
        
        # デフォルト選択
        self.listbox.selection_set(0)
        
        # ボタンフレーム
        button_frame = ttk.Frame(self)
        button_frame.pack(pady=10)
        
        ttk.Button(button_frame, text="選択", command=self.on_select, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="キャンセル", command=self.on_cancel, width=15).pack(side=tk.LEFT, padx=5)
        
        # イベントバインド
        self.listbox.bind('<Double-Button-1>', lambda e: self.on_select())
        self.bind('<Return>', lambda e: self.on_select())
        self.bind('<Escape>', lambda e: self.on_cancel())
    
    def start_auto_timer(self):
        """自動選択タイマー開始"""
        delay_ms = auto_mode_manager.auto_delay * 1000  # 秒 → ミリ秒
        log_message(f"🤖 プレイリスト自動選択: {auto_mode_manager.auto_delay}秒後に最初の項目を選択", "INFO")
        self.auto_timer_id = self.after(delay_ms, self.auto_select)
    
    def auto_select(self):
        """自動選択実行"""
        if self.playlist_tabs:
            self.selected_tab = self.playlist_tabs[0]  # 最初の項目を選択
            log_message(f"🤖 自動選択完了: {self.selected_tab[1][:50]}...", "SUCCESS")
            self.destroy()
    
    def on_select(self):
        """選択ボタン処理"""
        # 自動タイマーをキャンセル
        if self.auto_timer_id:
            self.after_cancel(self.auto_timer_id)
        
        selection = self.listbox.curselection()
        if selection:
            actual_index = selection[0] // 3
            if actual_index < len(self.playlist_tabs):
                self.selected_tab = self.playlist_tabs[actual_index]
                self.destroy()
    
    def on_cancel(self):
        """キャンセルボタン処理"""
        # 自動タイマーをキャンセル
        if self.auto_timer_id:
            self.after_cancel(self.auto_timer_id)
        
        self.destroy()
    
    def get_selected(self) -> Optional[Tuple[str, str, str]]:
        """選択結果を取得
        
        Returns:
            選択されたタブ情報、またはNone
        """
        return self.selected_tab


class IntegratedSummaryApp(tk.Tk):
    """メインアプリケーションUI"""
    def __init__(self, args=None):
        """初期化
        
        Args:
            args: コマンドライン引数（argparse.Namespace）
        """
        super().__init__()
        
        # ========== 新規追加：コマンドライン引数を保存 ==========
        self.args = args if args else argparse.Namespace(
            auto=False,
            playlists=None,
            mode=None,
            model=None,
            processing_mode=None,
            batch_size=None,
            debug=False
        )
        
        self.title(APP_TITLE)
        # ★修正: 設定項目追加に伴い縦幅を拡張(固定値)
        self.geometry("680x920")
        
        # UI変数（コマンドライン引数で上書き可能）
        self.processing_mode_var = tk.StringVar(
            value=self.args.processing_mode if self.args.processing_mode else "multiple"
        )
        self.mode_var = tk.StringVar(
            value=self.args.mode if self.args.mode else config_manager.get('general.default_mode')
        )
        self.url_var = tk.StringVar()
        self.max_videos_var = tk.IntVar(value=config_manager.get('general.max_videos'))
        self.process_all_var = tk.BooleanVar(value=False)
        self.model_var = tk.StringVar(
            value=self.args.model if self.args.model else config_manager.get('api.default_model')
        )
        self.parallel_var = tk.IntVar(value=config_manager.get('api.parallel_count'))
        self.output_format_var = tk.StringVar(value=config_manager.get('general.output_format'))
        
        # プレイリスト選択変数（コマンドライン引数で上書き可能）
        self.playlist_vars = {
            "V":  tk.BooleanVar(value=True),   # 標準ON
            "S":  tk.BooleanVar(value=True),   # 標準ON
            "A":  tk.BooleanVar(value=True),   # 標準ON
            "B":  tk.BooleanVar(value=True),   # 標準ON
            "N":  tk.BooleanVar(value=True),   # 標準ON
            "M":  tk.BooleanVar(value=True),   # 標準ON
            "P+": tk.BooleanVar(value=False),  # 標準OFF（意図的）
        }
        
        # コマンドライン引数でプレイリストが指定されている場合
        if self.args.playlists:
            # 全てOFFにしてから指定されたもののみON
            for key in self.playlist_vars.keys():
                self.playlist_vars[key].set(False)
            for playlist in self.args.playlists:
                if playlist in self.playlist_vars:
                    self.playlist_vars[playlist].set(True)
        
        # ALLチェックボックス用の変数（P+がデフォルトOFFのため起動時はFalse）
        self.all_playlists_var = tk.BooleanVar(value=False)
        
        # ALLチェックボックス用の変数を追加
        self.all_playlists_var = tk.BooleanVar(value=False)
        
        # ========== 新規追加：自動モード変数（コマンドライン引数で上書き）==========
        self.auto_mode_var = tk.BooleanVar(value=self.args.auto)
        
        # コマンドライン引数で--autoが指定されている場合はAutoModeManagerも有効化
        if self.args.auto:
            auto_mode_manager.enable()
            logger.info("コマンドライン引数により自動モード有効化")
        
        # 処理関連
        self.browser_manager = None
        self.process_thread = None
        self.rate_limiter = state.rate_limiter
        self.control_window = None
        
        # バッチサイズ変数（コマンドライン引数で上書き可能）
        self.batch_size_var = tk.IntVar(
            value=self.args.batch_size if self.args.batch_size else config_manager.get('glasp.batch_size', DEFAULT_GLASP_BATCH_SIZE)
        )
        
        self.setup_ui()
        self.update_ui_by_mode()
        
        # AutoModeManagerへの参照設定
        auto_mode_manager.set_app_reference(self)
        
        # 起動時の自動モードチェック（UIが完全に構築された後）
        self.after(100, self.check_auto_start_on_launch)
        
        # ウィンドウ終了時の処理
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        
    def setup_ui(self):
        """UI構築"""
        # メニューバー
        self.setup_menu()
        
        # メインコンテナ
        main_container = ttk.Frame(self, padding="10")
        main_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # グリッド設定
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        main_container.columnconfigure(0, weight=1)
        
        # 各セクション
        self.setup_mode_frame(main_container)
        self.setup_playlist_selection_frame(main_container)
        self.setup_settings_frame(main_container)
        self.setup_progress_frame(main_container)
        self.setup_control_buttons(main_container)

    def setup_menu(self):
        """メニューバー設定"""
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        
        # ファイルメニュー
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="ファイル", menu=file_menu)
        file_menu.add_command(label="設定を保存", command=self.save_settings)
        file_menu.add_command(label="設定を読込", command=self.load_settings)
        file_menu.add_separator()
        file_menu.add_command(label="終了", command=self.on_closing)
        
        # ツールメニュー
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="ツール", menu=tools_menu)
        tools_menu.add_command(label="Chromeデバッグモード起動", command=self.start_chrome_debug)
        tools_menu.add_command(label="出力フォルダを開く", command=self.open_output_folder)
        tools_menu.add_separator()
        tools_menu.add_command(label="レポート動画管理", command=self.open_report_video)
        tools_menu.add_separator()
        tools_menu.add_command(label="レート制限状態確認", command=self.show_rate_limit_status)
        tools_menu.add_command(label="メモリ使用状況", command=self.show_memory_status)
        tools_menu.add_command(label="タブ追跡状況", command=self.show_tab_tracker_status)
        
        # ヘルプメニュー
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)
        help_menu.add_command(label="使い方", command=self.show_help)
        help_menu.add_command(label="バージョン情報", command=self.show_about)

    def setup_mode_frame(self, parent):
        """処理モード選択セクション"""
        frame = ttk.LabelFrame(parent, text="処理モード", padding="10")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        
        # 処理モード選択（単一/複数）
        process_mode_frame = ttk.Frame(frame)
        process_mode_frame.grid(row=0, column=0, columnspan=2, pady=5)
        
        ttk.Radiobutton(process_mode_frame, text="📄 単一プレイリスト処理", 
                       variable=self.processing_mode_var, value="single",
                       command=self.update_ui_by_mode).pack(side=tk.LEFT, padx=10)
        
        ttk.Radiobutton(process_mode_frame, text="📚 複数プレイリスト処理", 
                       variable=self.processing_mode_var, value="multiple",
                       command=self.update_ui_by_mode).pack(side=tk.LEFT, padx=10)
        
        # エンジンモード選択
        engine_frame = ttk.Frame(frame)
        engine_frame.grid(row=1, column=0, columnspan=2, pady=5)
        
        ttk.Radiobutton(engine_frame, text="🚀 API直接処理（高速・低コスト）", 
                       variable=self.mode_var, value="api",
                       command=self.update_ui_by_mode).pack(side=tk.LEFT, padx=10)
        
        ttk.Radiobutton(engine_frame, text="🌐 Glasp拡張機能（ブラウザ連携）", 
                       variable=self.mode_var, value="glasp",
                       command=self.update_ui_by_mode).pack(side=tk.LEFT, padx=10)
        
        # モード説明
        self.mode_description = ttk.Label(frame, text="", foreground="gray")
        self.mode_description.grid(row=2, column=0, columnspan=2, pady=5)


    def setup_playlist_selection_frame(self, parent):
        """プレイリスト選択セクション"""
        self.playlist_frame = ttk.LabelFrame(parent, text="プレイリスト選択", padding="10")
        self.playlist_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        # チェックボックス配置
        checkbox_frame = ttk.Frame(self.playlist_frame)
        checkbox_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # ALLチェックボックス（変数を使用するように修正）
        all_checkbox = ttk.Checkbutton(
            checkbox_frame, 
            text="ALL",
            variable=self.all_playlists_var,  # 変数を追加
            command=self.toggle_all_playlists
        )
        all_checkbox.grid(row=0, column=0, padx=5, pady=2)
        
        # 個別プレイリストチェックボックス
        col = 1
        for name, var in self.playlist_vars.items():
            ttk.Checkbutton(checkbox_frame, text=name, variable=var).grid(
                row=0, column=col, padx=5, pady=2)
            col += 1
        
        # 単一プレイリスト用URL入力（非表示で保持）
        self.single_playlist_frame = ttk.Frame(self.playlist_frame)
        
        ttk.Label(self.single_playlist_frame, text="YouTube URL:").grid(row=0, column=0, sticky=tk.W)
        url_entry = ttk.Entry(self.single_playlist_frame, textvariable=self.url_var, width=70)
        url_entry.grid(row=0, column=1, padx=5, sticky=(tk.W, tk.E))
        ttk.Button(self.single_playlist_frame, text="📋 貼り付け", 
                  command=self.paste_url).grid(row=0, column=2, padx=5)
        self.single_playlist_frame.columnconfigure(1, weight=1)


    def setup_settings_frame(self, parent):
        """設定セクション"""
        self.settings_frame = ttk.LabelFrame(parent, text="詳細設定", padding="10")
        self.settings_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        
        # 共通設定
        common_frame = ttk.Frame(self.settings_frame)
        common_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 処理動画数（単一プレイリスト用）
        self.video_count_frame = ttk.Frame(common_frame)
        self.video_count_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E))
        
        ttk.Label(self.video_count_frame, text="処理動画数:").grid(row=0, column=0, sticky=tk.W)
        
        videos_frame = ttk.Frame(self.video_count_frame)
        videos_frame.grid(row=0, column=1, sticky=tk.W)
        
        ttk.Spinbox(videos_frame, from_=1, to=MAX_VIDEOS_LIMIT, 
                   textvariable=self.max_videos_var, width=10).pack(side=tk.LEFT)
        
        ttk.Checkbutton(videos_frame, text="プレイリスト全体を処理", 
                        variable=self.process_all_var).pack(side=tk.LEFT, padx=(20, 0))
        
        # バッチサイズ設定
        batch_frame = ttk.Frame(common_frame)
        batch_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(batch_frame, text="バッチサイズ:").grid(row=0, column=0, sticky=tk.W)
        
        # [20260808] ここで batch_size_var を作り直すと、__init__ で反映済みの
        # コマンドライン引数 --batch-size が上書きされて失われる。
        # 実際、run_youtube_summary_auto.bat は --batch-size 1 を渡しているのに
        # 設定値の20が使われ、20本を一度に開いてChromeとGeminiに負荷が集中していた
        # （実機ログでSプレイリストが videos=20 の1バッチになっていることを確認）。
        # 既に存在する場合は作り直さず、そのまま使う。
        if not hasattr(self, 'batch_size_var'):
            self.batch_size_var = tk.IntVar(
                value=config_manager.get('glasp.batch_size', DEFAULT_GLASP_BATCH_SIZE))
        batch_spinbox = ttk.Spinbox(batch_frame, from_=1, to=20,
                                   textvariable=self.batch_size_var, width=10)
        batch_spinbox.grid(row=0, column=1, padx=5, sticky=tk.W)
        
        batch_info_label = ttk.Label(batch_frame, 
                                    text="(Glaspモード: 一度に処理する動画数)",
                                    foreground="gray")
        batch_info_label.grid(row=0, column=2, padx=5)

        # 待機時間設定
        wait_frame = ttk.Frame(self.settings_frame)
        wait_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(wait_frame, text="リトライ待機:").pack(side=tk.LEFT)
        retry_entry = ttk.Entry(wait_frame, width=5)
        retry_entry.insert(0, str(config_manager.get('glasp.retry_delay', 2)))
        retry_entry.pack(side=tk.LEFT, padx=5)
        ttk.Label(wait_frame, text="秒").pack(side=tk.LEFT)
        
        # タブ応答待機設定
        ttk.Label(wait_frame, text="  タブ応答待機:").pack(side=tk.LEFT, padx=(10, 0))
        self.tab_wait_var = tk.IntVar(value=20)
        tab_wait_entry = ttk.Entry(wait_frame, textvariable=self.tab_wait_var, width=5)
        tab_wait_entry.pack(side=tk.LEFT, padx=5)
        ttk.Label(wait_frame, text="秒 (調子が悪い時は増やす)").pack(side=tk.LEFT)
        
        # Glasp設定フレーム
        self.glasp_settings_frame = ttk.Frame(self.settings_frame)
        
        # ブラウザ挙動設定: 実質的にUIから変更されないため非表示化し、内部固定値とする（3=タブ連続運転/高速）
        self.browser_mode_var = tk.IntVar(value=3)

        # Glasp起動方式（クリック方式の切替: JS疑似クリック vs CDP本物クリック）
        input_mode_frame = ttk.LabelFrame(self.settings_frame, text="Glasp起動方式（クリック方式）", padding=5)
        input_mode_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        self.input_mode_var = tk.StringVar(value='js_click')
        ttk.Radiobutton(input_mode_frame, text="疑似クリック (JS / 現行)", variable=self.input_mode_var, value='js_click').pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(input_mode_frame, text="本物クリック (CDPマウス / 検証用)", variable=self.input_mode_var, value='trusted_mouse').pack(side=tk.LEFT, padx=5)

        # API設定フレーム
        self.api_settings_frame = ttk.Frame(self.settings_frame)
        self.api_settings_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # モデル選択
        ttk.Label(self.api_settings_frame, text="AIモデル:").grid(row=0, column=0, sticky=tk.W)
        
        model_combo = ttk.Combobox(self.api_settings_frame, textvariable=self.model_var, 
                                  width=30, state="readonly")
        model_combo['values'] = list(MODEL_CONFIG.keys())
        model_combo.grid(row=0, column=1, padx=5, sticky=tk.W)
        model_combo.bind('<<ComboboxSelected>>', self.on_model_change)
        
        self.model_info_label = ttk.Label(self.api_settings_frame, text="", foreground="gray")
        self.model_info_label.grid(row=0, column=2, padx=5)
        
        # 並列処理数
        ttk.Label(self.api_settings_frame, text="同時処理数:").grid(row=1, column=0, sticky=tk.W)
        
        parallel_frame = ttk.Frame(self.api_settings_frame)
        parallel_frame.grid(row=1, column=1, columnspan=2, sticky=(tk.W, tk.E))
        
        parallel_scale = ttk.Scale(parallel_frame, from_=1, to=MAX_PARALLEL_COUNT,
                                  variable=self.parallel_var, orient=tk.HORIZONTAL, 
                                  length=200)
        parallel_scale.pack(side=tk.LEFT)
        
        self.parallel_label = ttk.Label(parallel_frame, text="3")
        self.parallel_label.pack(side=tk.LEFT, padx=5)
        
        parallel_scale.bind('<Motion>', lambda e: self.parallel_label.config(
            text=str(int(self.parallel_var.get()))))
        
        # レート制限設定
        rate_limit_frame = ttk.Frame(self.api_settings_frame)
        rate_limit_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(rate_limit_frame, text="レート制限:").grid(row=0, column=0, sticky=tk.W)
        self.rate_limit_label = ttk.Label(rate_limit_frame, text="", foreground="blue")
        self.rate_limit_label.grid(row=0, column=1, padx=5, sticky=tk.W)
        
        ttk.Button(rate_limit_frame, text="状態確認", 
                  command=self.show_rate_limit_status).grid(row=0, column=2, padx=5)
        
        # 出力形式: 実質的にUIから変更されないため非表示化し、内部固定値とする（html固定）
        # self.output_format_var 自体は save_results()/設定保存で参照されるため維持

    def setup_progress_frame(self, parent):
        """進捗表示セクション"""
        frame = ttk.LabelFrame(parent, text="処理進捗", padding="10")
        frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        # レート制限状態表示
        self.rate_status_frame = ttk.Frame(frame)
        self.rate_status_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.rate_status_label = ttk.Label(self.rate_status_frame, text="", font=("Arial", 10, "bold"))
        self.rate_status_label.pack(side=tk.LEFT, padx=5)
        
        # タブ追跡状態表示
        self.tab_tracker_frame = ttk.Frame(frame)
        self.tab_tracker_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.tab_tracker_label = ttk.Label(self.tab_tracker_frame, text="", font=("Arial", 9))
        self.tab_tracker_label.pack(side=tk.LEFT, padx=5)
        
        # プレイリスト進捗（複数モード用）
        self.playlist_progress_frame = ttk.Frame(frame)
        self.playlist_progress_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.playlist_progress_label = ttk.Label(self.playlist_progress_frame, text="", font=("Arial", 10, "bold"))
        self.playlist_progress_label.pack(side=tk.LEFT, padx=5)
        
        # 動画進捗バー
        self.progress_bar = ttk.Progressbar(frame, mode='determinate')
        self.progress_bar.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=5)
        
        # ステータスラベル
        self.status_label = ttk.Label(frame, text="待機中...")
        self.status_label.grid(row=4, column=0, sticky=tk.W)
        
        # ログテキスト
        log_frame = ttk.Frame(frame)
        log_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        self.log_text = tk.Text(log_frame, height=10, width=80)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", 
                                 command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        parent.rowconfigure(3, weight=1)
        
        # レート制限状態の定期更新
        self.update_rate_limit_display()
        
        # ★★★ 新規追加: UI更新タイマーを起動 ★★★
        self.start_ui_polling()


    def start_ui_polling(self, interval_ms: int = 200):
        """UIの定期的更新を開始（スレッド安全な方法）"""
        self.update_ui_from_state()
        self.after(interval_ms, self.start_ui_polling)


    def update_ui_from_state(self):
        """GlobalStateから最新情報を取得してUIに反映（クラッシュ対策版）"""
        # ウィンドウ本体が破棄されていたら即座にリターン
        if not self.winfo_exists():
            return
            
        try:
            # プレイリスト名
            if state.current_playlist:
                self.playlist_label.config(text=f"【{state.current_playlist}】処理中")
            else:
                self.playlist_label.config(text="単一/未定")
                
            # 進捗
            if state.total_items > 0:
                self.progress_text_label.config(text=f"{state.current_progress} / {state.total_items}")
                self.progress_bar['maximum'] = state.total_items
                self.progress_bar['value'] = state.current_progress
            
            # バッチ情報
            batch_status = state.get_batch_status()
            if batch_status:
                self.batch_label.config(text=batch_status)
                
            # 動画タイトル
            current_title = state.current_video_title
            if len(current_title) > 40:
                current_title = current_title[:40] + "..."
            self.video_label.config(text=current_title)
            
            # 詳細ステータス
            self.status_detail_label.config(text=state.detailed_status)

            # ボタン状態のリセット
            if not state.skip_flag and self.skip_button['text'] != "⏭️ スキップ":
                self.skip_button.config(text="⏭️ スキップ", state="normal", bg="#4CAF50")
                
            if not state.cancel_flag and self.stop_button['text'] != "⏹️ 停止":
                self.stop_button.config(text="⏹️ 停止", state="normal", bg="#f44336")
                
        except (tk.TclError, AttributeError):
            # 更新中にウィンドウが閉じられた場合は静かに終了
            pass

    def setup_control_buttons(self, parent):
        """制御ボタン"""
        frame = ttk.Frame(parent)
        frame.grid(row=4, column=0, pady=10)
        
        # ========== 既存ボタン ==========
        self.start_button = ttk.Button(frame, text="▶️ 処理開始", 
                                      command=self.start_processing)
        self.start_button.grid(row=0, column=0, padx=5)
        
        self.stop_button = ttk.Button(frame, text="⏹️ 停止", 
                                     command=self.stop_processing, state='disabled')
        self.stop_button.grid(row=0, column=1, padx=5)
        
        self.save_button = ttk.Button(frame, text="💾 結果保存", 
                                     command=self.save_results, state='disabled')
        self.save_button.grid(row=0, column=2, padx=5)
        
        ttk.Separator(frame, orient='vertical').grid(row=0, column=3, sticky='ns', padx=10)
        
        self.exit_button = ttk.Button(frame, text="🚪 終了", 
                                     command=self.on_closing)
        self.exit_button.grid(row=0, column=4, padx=5)
        
        # ========== 新規追加：自動モードチェックボックス ==========
        ttk.Separator(frame, orient='vertical').grid(row=0, column=5, sticky='ns', padx=10)
        
        # 自動モードチェックボックス
        self.auto_mode_checkbox = ttk.Checkbutton(
            frame, 
            text="🤖 Auto（全自動モード）", 
            variable=self.auto_mode_var,
            command=self.toggle_auto_mode
        )
        self.auto_mode_checkbox.grid(row=0, column=6, padx=5)
        
        # 自動モード説明ラベル（グレー文字）
        auto_info_label = ttk.Label(
            frame, 
            text="※ 全ダイアログを5秒で自動処理",
            foreground="gray",
            font=("Arial", 8)
        )
        auto_info_label.grid(row=0, column=7, padx=5)




    def toggle_auto_mode(self):
        """自動モードのON/OFF切り替え"""
        if self.auto_mode_var.get():
            # 自動モード有効化
            auto_mode_manager.enable()
            self.log_to_ui("🤖 自動モード有効化：すべてのダイアログを自動処理します", "INFO")
            
            # 確認ダイアログ（自動ラッパー使用）
            auto_showinfo(
                "自動モード", 
                "自動モードが有効化されました。\n\n"
                f"{auto_mode_manager.auto_delay}秒後に自動で処理を開始します。\n"
                "すべての確認ダイアログも自動処理されます。"
            )
            
            # ========== 新規追加：処理中でなければ自動開始タイマーを設定 ==========
            if not state.processing:
                auto_mode_manager.schedule_auto_start()
            else:
                self.log_to_ui("処理中のため、次回から自動開始が適用されます", "INFO")
        else:
            # 自動モード無効化
            auto_mode_manager.disable()
            self.log_to_ui("👤 自動モード無効化：通常の手動操作に戻ります", "INFO")



    def check_auto_start_on_launch(self):
        """起動時に自動モードがONなら自動開始をスケジュール
        
        起動後の初期化完了時に呼ばれる。
        Autoチェックボックスが既にONの場合、自動で処理を開始する。
        """
        if self.auto_mode_var.get():
            self.log_to_ui("🤖 起動時に自動モードが有効です", "INFO")
            self.log_to_ui(f"🤖 {auto_mode_manager.auto_delay}秒後に自動で処理を開始します...", "INFO")
            
            # 自動開始をスケジュール
            auto_mode_manager.schedule_auto_start()
        else:
            self.log_to_ui("手動モードで起動しました", "INFO")



    def auto_start_processing(self):
        """自動的に処理を開始
        
        自動モードタイマーから呼ばれる。
        処理モード（単一/複数）に応じて適切な処理を開始する。
        """
        if not auto_mode_manager.is_enabled():
            # 自動モードが無効化されている場合はスキップ
            self.log_to_ui("自動モードが無効化されたため、自動開始をキャンセルしました", "WARNING")
            return
        
        if state.processing:
            # 既に処理中の場合はスキップ
            self.log_to_ui("既に処理中のため、自動開始をスキップしました", "WARNING")
            return
        
        self.log_to_ui("🤖 自動処理を開始します...", "SUCCESS")
        
        # 処理モードに応じて開始
        processing_mode = self.processing_mode_var.get()
        
        if processing_mode == "single":
            # 単一プレイリスト処理
            self.log_to_ui("🤖 単一プレイリストモードで自動開始", "INFO")
            self.start_single_processing()
        else:
            # 複数プレイリスト処理
            self.log_to_ui("🤖 複数プレイリストモードで自動開始", "INFO")
            self.start_multiple_processing()

    
    def update_ui_by_mode(self):
        """モードに応じてUIを更新"""
        processing_mode = self.processing_mode_var.get()
        engine_mode = self.mode_var.get()
        
        # 処理モードによる表示切替
        if processing_mode == "single":
            self.playlist_frame.grid_remove()
            for child in self.playlist_frame.winfo_children():
                child.grid_remove()
            self.single_playlist_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
            self.video_count_frame.grid()
            self.playlist_progress_frame.grid_remove()
        else:
            self.single_playlist_frame.grid_remove()
            self.playlist_frame.grid()
            for child in self.playlist_frame.winfo_children():
                if child != self.single_playlist_frame:
                    child.grid()
            self.video_count_frame.grid_remove()
            self.playlist_progress_frame.grid()
        
        # エンジンモードによる表示切替
        if engine_mode == "api":
            self.mode_description.config(text="YouTube Transcript API + AI APIを使用した直接処理")
            self.api_settings_frame.grid()
            self.glasp_settings_frame.grid_remove()
        else:
            self.mode_description.config(text="Chrome拡張機能Glaspを使用したブラウザ連携処理")
            self.api_settings_frame.grid_remove()
            self.glasp_settings_frame.grid()
        
        self.on_model_change()



    def toggle_all_playlists(self):
        """全プレイリスト選択/解除"""
        # ALLチェックボックスの現在の状態を取得
        all_selected = self.all_playlists_var.get()
        
        # すべての個別プレイリストを同じ状態に設定
        for var in self.playlist_vars.values():
            var.set(all_selected)

        
    
    def get_selected_playlists(self) -> List[str]:
        """選択されたプレイリストのリストを取得"""
        return [name for name, var in self.playlist_vars.items() if var.get()]
    
    def on_model_change(self, event=None):
        """モデル変更時の処理"""
        model = self.model_var.get()
        if model in MODEL_CONFIG:
            info = MODEL_CONFIG[model]
            self.model_info_label.config(
                text=f"{info['description']} (入力: ${info['cost_per_1k_input']}/1K, 出力: ${info['cost_per_1k_output']}/1K)"
            )


    def update_rate_limit_display(self):
        """レート制限状態の表示を更新"""
        if config_manager.get('ui.show_rate_limit_status', True):
            status_msg = self.rate_limiter.get_status_message()
            self.rate_status_label.config(text=status_msg)
            
            current, max_req, load = self.rate_limiter.get_current_load()
            if load < 50:
                self.rate_status_label.config(foreground="green")
            elif load < 75:
                self.rate_status_label.config(foreground="orange")
            else:
                self.rate_status_label.config(foreground="red")
            
            self.rate_limit_label.config(text=f"{current}/{max_req} ({load:.1f}%)")
        
        if config_manager.get('ui.show_tab_tracker', True):
            tab_status = state.get_tab_tracker_status()
            self.tab_tracker_label.config(text=tab_status)
        
        # プレイリスト進捗更新（複数モード時）
        if hasattr(state, 'current_playlist') and state.current_playlist:
            playlist_status = f"プレイリスト: {state.current_playlist}"
            if hasattr(state, 'playlist_progress'):
                completed = [p for p, status in state.playlist_progress.items() if status == 'completed']
                playlist_status += f" (完了: {len(completed)}/{len(state.playlist_progress)})"
            self.playlist_progress_label.config(text=playlist_status)


    def log_to_ui(self, message: str, level: str = "INFO"):
        """統一ログ出力関数"""
        if state.silent_mode and not silent_override:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        symbols = {
            "INFO": "📍",
            "SUCCESS": "✅",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "PROCESS": "🔄"
        }
        symbol = symbols.get(level, "📍")
        
        formatted_message = f"[{timestamp}] {symbol} {message}"
        
        # ログレベルに応じた出力
        if level == "ERROR":
            logger.error(message)
        elif level == "WARNING":
            logger.warning(message)
        else:
            logger.info(message)
        
        # コンソール出力
        print(formatted_message)
        
        # ★★★ 修正箇所: 進捗バーとControlWindowの更新ロジックを削除（update_ui_from_stateに移動） ★★★
        
        if "レート制限" in message:
            if "警戒域" in message or "危険" in message:
                auto_showwarning("レート制限警告", 
                    "レート制限の上限に近づいています。\n"
                    "処理速度が自動的に調整されます。"
                )
        
        if "メモリ使用量警告" in message:
            if not state.memory_warning_shown:
                state.memory_warning_shown = True
                result = auto_askyesno("メモリ警告", 
                    "メモリ使用量が高くなっています。\n"
                    "処理を続行しますか？",
                    default=True)
                if not result:
                    state.cancel_flag = True


    def check_memory_usage(self) -> bool:
        """メモリ使用状況をチェック"""
        if not self.browser_manager or not self.browser_manager.driver:
            return True
        
        memory_mb = self.browser_manager.get_memory_usage()
        threshold = config_manager.get('memory.warning_threshold_mb', 1000)
        
        if memory_mb > threshold:
            self.log_to_ui(f"⚠️ メモリ使用量警告: {memory_mb:.1f}MB (閾値: {threshold}MB)", "WARNING")
            
            if not state.memory_warning_shown:
                state.memory_warning_shown = True
                result = messagebox.askyesno("メモリ警告", 
                    f"メモリ使用量が{memory_mb:.1f}MBに達しました。\n"
                    f"（警告閾値: {threshold}MB）\n\n"
                    "処理を続行しますか？")
                if not result:
                    return False
        
        return True


    def show_rate_limit_status(self):
        """レート制限状態の詳細表示"""
        current, max_req, load = self.rate_limiter.get_current_load()
        
        status_text = f"""
    レート制限状態
    ────────────────────

    現在のリクエスト数: {current}
    最大リクエスト数: {max_req}
    使用率: {load:.1f}%

    セッション開始: {self.rate_limiter.session_start.strftime('%H:%M:%S')}
    セッション累計: {self.rate_limiter.total_session_requests}

    推奨事項:
    """
        
        if load < 50:
            status_text += "• 正常範囲です。安全に処理を続行できます。"
        elif load < 75:
            status_text += "• 注意域です。処理速度が自動調整されています。"
        elif load < 90:
            status_text += "• 警戒域です。処理速度を大幅に制限しています。"
        else:
            status_text += "• 危険域です！まもなくレート制限に到達します。\n• 処理を一時停止することを推奨します。"
        
        auto_showinfo("レート制限状態", status_text)



    def show_memory_status(self):
        """メモリ使用状況の詳細表示"""
        if self.browser_manager and self.browser_manager.driver:
            memory_mb = self.browser_manager.get_memory_usage()
            threshold = config_manager.get('memory.warning_threshold_mb', 1000)
            
            status_text = f"""
    メモリ使用状況
    ────────────────────

    現在の使用量: {memory_mb:.1f} MB
    警告閾値: {threshold} MB
    使用率: {memory_mb/threshold*100:.1f}%

    タブ状況:
    {state.get_tab_tracker_status()}

    推奨事項:
    """
            
            if memory_mb < threshold * 0.5:
                status_text += "• 正常範囲です。"
            elif memory_mb < threshold * 0.8:
                status_text += "• 注意が必要です。定期的なクリーンアップが実行されています。"
            else:
                status_text += "• メモリ使用量が高いです。\n• 処理数を減らすか、バッチサイズを小さくすることを推奨します。"
            
            auto_showinfo("メモリ使用状況", status_text)
        else:
            auto_showinfo("メモリ使用状況", "ブラウザが起動していません。")



    def show_tab_tracker_status(self):
        """タブ追跡状況の詳細表示"""
        if state.tab_tracker:
            status = state.tab_tracker.get_status_summary()
            
            status_text = f"""
    タブ追跡状況
    ────────────────────

    YouTubeタブ: {status['youtube_tabs']}個
    Glaspタブ（合計）: {status['glasp_tabs_total']}個
      - 成功: {status['glasp_tabs_success']}個
      - 失敗: {status['glasp_tabs_failed']}個
      - 待機中: {status['glasp_tabs_pending']}個

    成功した動画数: {status['success_videos']}個

    現在のバッチ: {state.current_batch + 1}/{state.total_batches}
    処理進捗: {state.current_progress}/{state.total_items}
    """
            
            auto_showinfo("タブ追跡状況", status_text)
        else:
            auto_showinfo("タブ追跡状況", "タブ追跡が初期化されていません。")


    def start_processing(self):
        """処理開始"""
        if state.processing:
            messagebox.showwarning("警告", "既に処理中です")
            return
        
        processing_mode = self.processing_mode_var.get()
        
        if processing_mode == "single":
            # 単一プレイリスト処理
            self.start_single_processing()
        else:
            # 複数プレイリスト処理
            self.start_multiple_processing()


    def start_single_processing(self):
        """単一プレイリスト処理開始（常に新規タブを作成して開始するバージョン）"""
        
        # 1. 処理モードと設定の基本チェック
        processing_mode = self.processing_mode_var.get()
        engine_mode = self.mode_var.get()
        
        if engine_mode == "glasp" and self.batch_size_var.get() < 1:
            auto_showerror("設定エラー", "バッチサイズは1以上に設定してください。")
            return

        # 2. ブラウザマネージャーの準備
        if not self.browser_manager:
            self.browser_manager = BrowserManager()

        driver_alive = False
        if self.browser_manager.driver:
            try:
                _ = self.browser_manager.driver.window_handles
                driver_alive = True
            except:
                self.browser_manager.driver = None

        # 3. ドライバの初期化
        if not driver_alive:
            self.log_to_ui("Chromeが起動していないため、起動します...", "INFO")
            if not self.browser_manager.init_chrome_driver(debug_mode=True):
                if not self.browser_manager.init_chrome_driver(debug_mode=False):
                    auto_showerror("エラー", "Chromeの起動に失敗しました。")
                    return
            time.sleep(2) # 起動待ち
        else:
            self.log_to_ui("既存のChrome接続を使用して処理を開始します", "INFO")
        
        # 4. URLの確認と処理対象の決定
        url = self.url_var.get().strip()
        
        if not url:
            # URLが空の場合、既存タブから検出を試みる（フォールバック）
            self.log_to_ui("URLが未入力のため、既存タブから検出を試みます...", "PROCESS")
            playlist_tabs = self.browser_manager.find_youtube_playlist_tabs()
            
            if not playlist_tabs:
                auto_showwarning("警告", "処理対象のURLが未入力で、プレイリストタブも見つかりませんでした。\nURLを入力するか、プレイリストを開いてください。")
                return
            
            if len(playlist_tabs) == 1:
                selected_tab = playlist_tabs[0]
                url = selected_tab[2]  # ★修正: 変数更新漏れを修正
                self.url_var.set(url)  # UIにも反映
                self.log_to_ui(f"プレイリストを1件検出しました。URLを上書きします: {selected_tab[2][:50]}...", "INFO")
            else:
                self.log_to_ui(f"{len(playlist_tabs)}個のプレイリスト候補が見つかりました。対象を選択してください。", "INFO")
                selected_tab = self.show_tab_selection_dialog(playlist_tabs)
            
                if not selected_tab:
                    self.log_to_ui("URLの決定がキャンセルされました", "WARNING")
                    return
            
                handle, title, url = selected_tab
                self.url_var.set(url) # UIにも設定を戻す
                self.log_to_ui(f"対象プレイリストURLを決定: {url[:50]}...", "SUCCESS")

        # ★追加: URL形式のサニタイズ（https補完）
        if url and not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            self.log_to_ui(f"URL形式を補正しました: {url[:50]}...", "DEBUG")

        # 5. 設定の読み込みと検証
        config = ProcessConfig(
            mode=engine_mode,
            max_videos=self.max_videos_var.get(),
            process_all=self.process_all_var.get(),
            model=self.model_var.get(),
            parallel_count=self.parallel_var.get(),
            output_format=self.output_format_var.get(),
            batch_size=self.batch_size_var.get(),
            retry_delay=config_manager.get('glasp.retry_delay', 2),
            tab_wait_timeout=self.tab_wait_var.get(),
            browser_mode=self.browser_mode_var.get(),
            glasp_input_mode=self.input_mode_var.get()
        )
        
        valid, error = config.validate()
        if not valid:
            auto_showerror("設定エラー", error)
            return
        
        # 6. レート制限の最終チェック
        current, max_req, load = self.rate_limiter.get_current_load()
        if load > 90:
            result = auto_askyesno("レート制限警告", 
                f"レート制限使用率が{load:.1f}%に達しています。\n処理を続行しますか？",
                default=True)
            if not result:
                return
        
        # 7. 処理の実行準備
        self.show_control_window()
        
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.save_button.config(state='disabled')
        self.progress_bar['value'] = 0
        self.log_text.delete(1.0, tk.END)
        
        self.update_rate_limit_display()
        
        # 8. 常に新しいタブを開いて処理を開始
        try:
            self.browser_manager.create_new_tab(url)
            self.log_to_ui(f"✅ 新しいタブで処理開始: {url[:50]}...", "SUCCESS")
        except Exception as e:
            auto_showerror("エラー", f"新しいタブの作成に失敗しました:\n{e}")
            self.stop_processing()
            return

        # 9. ワーカースレッドの起動
        self.process_thread = threading.Thread(
            target=self.run_processing,
            args=(url, config), # URLと設定を渡す
            daemon=True
        )
        self.process_thread.start()


    def start_multiple_processing(self):
        """複数プレイリスト処理開始"""
        selected_playlists = self.get_selected_playlists()
        
        if not selected_playlists:
            auto_showwarning("警告", "処理するプレイリストを選択してください")
            return
        
        # 確認ダイアログ
        playlist_names = ", ".join(selected_playlists)
        result = auto_askyesno("確認", 
            f"以下のプレイリストを処理します:\n{playlist_names}\n\n"
            f"合計 {len(selected_playlists)} 個のプレイリスト\n"
            "続行しますか？",
            default=True)
        if not result:
            return
        
        config = ProcessConfig(
            mode=self.mode_var.get(),
            max_videos=MAX_VIDEOS_LIMIT,
            process_all=True,
            model=self.model_var.get(),
            parallel_count=self.parallel_var.get(),
            output_format=self.output_format_var.get(),
            batch_size=self.batch_size_var.get() if hasattr(self, 'batch_size_var') else DEFAULT_GLASP_BATCH_SIZE,
            retry_delay=config_manager.get('glasp.retry_delay', 2),
            tab_wait_timeout=self.tab_wait_var.get(),
            browser_mode=self.browser_mode_var.get(),
            glasp_input_mode=self.input_mode_var.get() # ★追加
        )
        
        valid, error = config.validate()
        if not valid:
            auto_showerror("設定エラー", error)
            return
        
        # コントロールウィンドウ表示
        self.show_control_window()
        
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.save_button.config(state='disabled')
        self.progress_bar['value'] = 0
        self.log_text.delete(1.0, tk.END)
        
        self.update_rate_limit_display()
        
        self.process_thread = threading.Thread(
            target=self.process_with_multiple_playlists,
            args=(selected_playlists, config),
            daemon=True
        )
        self.process_thread.start()

    
    def show_control_window(self):
        """コントロールウィンドウを表示"""
        if self.control_window:
            self.control_window.destroy()
        
        self.control_window = ProcessControlWindow(self)
        state.control_window = self.control_window


    def process_with_multiple_playlists(self, playlist_names: List[str], config: ProcessConfig):
        """複数プレイリストを処理（自動モード対応強化版・バッチ連動・自己修復機能付き）"""
        try:
            state.reset()
            state.processing = True
            
            # 自動モードかどうかの判定
            is_auto = auto_mode_manager.is_enabled()
            
            playlist_config = config_manager.get_playlist_config()
            
            if not hasattr(state, 'completed_playlists'):
                state.completed_playlists = []
            
            state.playlist_progress = {name: 'pending' for name in playlist_names}

            # ブラウザ初期化
            if not self.browser_manager:
                self.browser_manager = BrowserManager()
            
            if not self.browser_manager.init_chrome_driver(debug_mode=True, is_auto_mode=is_auto):
                raise Exception("Chrome初期化に失敗しました")
            
            # 最初のタブを保護する処理
            initial_tab_ready = False
            for init_tab_attempt in range(2):
                try:
                    time.sleep(1)
                    if not self.browser_manager.driver:
                        raise Exception("WebDriverが存在しません")
                    
                    self.log_to_ui(
                        f"🚀 ブラウザ初期化完了確認: 初期タブを準備します "
                        f"(Attempt {init_tab_attempt + 1}/2)",
                        "INFO"
                    )
                    
                    handles = self.browser_manager.driver.window_handles
                    if not handles:
                        raise Exception("window_handles が空です")
                    
                    current_handle = self.browser_manager.driver.current_window_handle
                    if not current_handle:
                        raise Exception("current_window_handle が取得できません")
                    
                    self.browser_manager.main_window_handle = current_handle
                    
                    if len(handles) == 1:
                        self.browser_manager.create_new_tab("about:blank")
                        handles = self.browser_manager.driver.window_handles
                        if not handles:
                            raise Exception("作業用タブ作成後に window_handles が空です")
                    
                    initial_tab_ready = True
                    self.log_to_ui("✅ 初期タブ制御が完了しました", "INFO")
                    break
                
                except Exception as e:
                    self.log_to_ui(
                        f"初期タブ制御エラー: {e}",
                        "WARNING"
                    )
                    if init_tab_attempt == 0:
                        self.log_to_ui(
                            "🔄 初期タブ制御に失敗したため、ブラウザを1回だけ再起動します",
                            "WARNING"
                        )
                        if not self.browser_manager.force_restart_browser(is_auto_mode=is_auto):
                            raise Exception("初期タブ制御後のブラウザ再起動に失敗しました")
                        continue
                    raise Exception(f"初期タブ制御に失敗しました: {e}")
            
            if not initial_tab_ready:
                raise Exception("初期タブ制御に失敗しました")

            glasp_engine = None
            if config.mode == "glasp":
                glasp_engine = GlaspEngine(self.browser_manager)

            all_results = []
            
            for playlist_index, playlist_name in enumerate(playlist_names):
                if state.cancel_flag:
                    break
                
                # プレイリスト切り替え時の状態リセット（最初以外）
                # [S03十七訂] ブラウザの強制再起動は行わない。再起動直後に
                # 2巡目の最初の1本がGlaspに一切反応してもらえない現象が
                # 実機ログで確認されたため、越智さんの指示により撤去した。
                if playlist_index > 0:
                    if glasp_engine:
                        glasp_engine.reset_for_new_playlist()
                        try:
                            if len(self.browser_manager.driver.window_handles) == 1:
                                self.browser_manager.create_new_tab("about:blank")
                        except: pass

                if playlist_name in state.completed_playlists:
                    self.log_to_ui(f"プレイリスト {playlist_name} はスキップ（完了済み）", "INFO")
                    continue
                
                state.current_progress = 0
                self.progress_bar['value'] = 0
                
                playlist_id = playlist_config.get(playlist_name)
                if not playlist_id:
                    self.log_to_ui(f"プレイリスト {playlist_name} のIDが見つかりません", "ERROR")
                    continue
                
                playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                
                self.log_to_ui(f"=== プレイリスト {playlist_name} ({playlist_index + 1}/{len(playlist_names)}) 処理開始 ===", "INFO")
                state.current_playlist = playlist_name
                state.playlist_progress[playlist_name] = 'processing'
                
                playlist_results = []
                
                try:
                    if config.mode == "glasp" and glasp_engine:
                        playlist_results = self.process_with_glasp(playlist_url, config)

                        # [20260808] 従来は「最後のプレイリスト以外」だけクリーンアップ
                        # していたため、プレイリストを1個だけ実行した場合
                        # (playlist_index=0, len=1 → 0 < 0 が偽) は一度も走らず、
                        # Geminiタブが開きっぱなしになっていた。最後のプレイリストでも
                        # 実行するようにする（動画タブは保持されるので実行痕跡は残る）。
                        glasp_engine.cleanup_playlist_tabs()
                    else:
                        playlist_results = self.process_with_api(playlist_url, config)
                    
                    # 結果保存
                    if playlist_results:
                        self._save_playlist_results(playlist_results, playlist_name, config)
                        state.current_progress = state.total_items
                        all_results.extend(playlist_results)
                        
                        if any(not r.success for r in playlist_results):
                            state.playlist_progress[playlist_name] = 'completed_with_errors'
                            self.log_to_ui(f"プレイリスト {playlist_name} 完了（一部エラーあり）", "WARNING")
                        else:
                            state.playlist_progress[playlist_name] = 'completed'
                            state.completed_playlists.append(playlist_name)
                            self.log_to_ui(f"プレイリスト {playlist_name} 完了", "SUCCESS")
                    else:
                        self.log_to_ui(f"プレイリスト {playlist_name} の結果が空でした", "WARNING")
                        state.playlist_progress[playlist_name] = 'failed'
                    
                except Exception as e:
                    self.log_to_ui(f"プレイリスト {playlist_name} 処理エラー: {e}", "ERROR")

                    if playlist_results:
                        self.log_to_ui("途中経過の保存を試みます...", "WARNING")
                        self._save_playlist_results(playlist_results, playlist_name, config)
                        all_results.extend(playlist_results)
                        state.playlist_progress[playlist_name] = 'completed_with_errors'

                    state.playlist_progress[playlist_name] = 'failed'

                    # [20260808] 確認画面(reCAPTCHA)を検知した場合は、実行全体を中止する。
                    # ここで continue すると次のプレイリストへ進み、そちらでも同じ確認画面に
                    # 突き当たる。実機では、止まったのはGeminiだけで処理は次の動画へ移り、
                    # 結果としてすべての動画タブが確認画面の状態になっていった。
                    # 叩き続けても解除されず、無人実行では誰も応答できないため、
                    # ここで打ち切って次の実行時刻(1日4回)に委ねる。
                    if "CHALLENGE_DETECTED" in str(e):
                        self.log_to_ui(
                            "🛑 Googleの確認画面を検知したため、残りのプレイリストを含めて"
                            "今回の実行を中止します。次の実行時刻に自動で再挑戦します。",
                            "ERROR"
                        )
                        state.playlist_progress[playlist_name] = 'aborted_challenge'
                        break


                    if self.browser_manager:
                        self.log_to_ui("⚠️ エラー発生のため、次のプレイリストに向けてブラウザを強制リセットします", "WARNING")
                        self.browser_manager.force_restart_browser(is_auto_mode=is_auto)
                        if config.mode == "glasp" and glasp_engine:
                            glasp_engine.reset_for_new_playlist()
                    continue
            
            state.results = all_results
            completed = [p for p, status in state.playlist_progress.items() if status in ['completed', 'completed_with_errors']]
            failed = [p for p, status in state.playlist_progress.items() if status == 'failed']
            
            self.log_to_ui(f"=== 全プレイリスト処理完了 ===", "SUCCESS")
            self.log_to_ui(f"成功: {len(completed)}個", "SUCCESS")
            if failed:
                self.log_to_ui(f"失敗: {len(failed)}個 ({', '.join(failed)})", "ERROR")
            
            if all_results:
                try:
                    output_gen = OutputGenerator()
                    pass 
                except:
                    pass

            # ==========================================
            # 全処理完了後にHTML統合バッチを起動
            # ==========================================
            self._run_consolidation_batch()

        except Exception as e:
            self.log_to_ui(f"複数プレイリスト処理全体でのエラー: {e}", "ERROR")
            import traceback
            self.log_to_ui(traceback.format_exc(), "DEBUG")
        
        finally:
            state.processing = False
            state.current_playlist = None
            self.start_button.config(state='normal')
            self.stop_button.config(state='disabled')
            if state.results:
                self.save_button.config(state='normal')
            
            if self.control_window:
                self.control_window.destroy()
                self.control_window = None
            
            if auto_mode_manager.is_enabled():
                delay_seconds = 3
                self.log_to_ui(f"🤖 自動モード：処理完了。{delay_seconds}秒後に全プロセスを終了します...", "INFO")
                self.update()
                time.sleep(delay_seconds)
                self.auto_close_application()


    def _run_consolidation_batch(self):
        """
        [VERSION 20260412.01]
        処理完了後にHTML統合バッチを非同期（別ウィンドウ）で起動する
        """
        import subprocess
        import os
        
        batch_path = r"C:\Users\nx023836\Documents\PythonScripts\RSS\start_consolidated_HTML_summary_manager.bat"
        
        self.log_to_ui("🔄 HTML統合バッチの起動準備中...", "INFO")
        
        if not os.path.exists(batch_path):
            self.log_to_ui(f"⚠️ 統合バッチが見つかりません。パスを確認してください: {batch_path}", "WARNING")
            return
            
        try:
            # subprocess.Popenで非同期起動。startコマンドを使うことで独立したウィンドウで実行
            subprocess.Popen(f'start "" "{batch_path}"', shell=True)
            self.log_to_ui("✅ HTML統合バッチをバックグラウンドで起動しました", "SUCCESS")
        except Exception as e:
            self.log_to_ui(f"🚨 バッチ起動エラー: {e}", "ERROR")

    def run_processing(self, url: str, config: ProcessConfig):
        """メイン処理スレッド（スタックトレース最終保護版）"""
        import traceback
        try:
            state.reset()
            state.processing = True
            self.log_to_ui(f"処理開始: {config.mode}モード", "INFO")
            
            if config.mode == "glasp":
                results = self.process_with_glasp(url, config)
            else:
                results = self.process_with_api(url, config)
            
            state.results = results
            if results and config_manager.get('general.auto_save'):
                self.save_results()
            self.log_to_ui("処理完了", "SUCCESS")
            
        except Exception as e:
            # スレッド全体が止まるようなエラー（予期せぬクラッシュ）を最後に救済
            self.log_to_ui(f"スレッド実行エラー: {e}", "ERROR")
            self.log_to_ui(f"致命的スタックトレース:\n{traceback.format_exc()}", "ERROR")
            auto_showerror("エラー", f"処理中に致命的なエラーが発生しました:\n{e}")

        finally:
            state.processing = False
            self.start_button.config(state='normal')
            self.stop_button.config(state='disabled')
            if state.results:
                self.save_button.config(state='normal')
            if self.control_window:
                self.control_window.destroy()
                self.control_window = None
            if auto_mode_manager.is_enabled():
                self.after(3000, self.auto_close_application)
        

    def process_with_glasp(self, url: str, config: ProcessConfig) -> List[SummaryResult]:
        """Glaspモードで処理（スタックトレース取得対応版）"""
        import traceback
        total_start = time.time()
        if not self.browser_manager:
            self.browser_manager = BrowserManager()
            if not self.browser_manager.init_chrome_driver():
                raise Exception("Chrome初期化に失敗しました")
        
        try:
            youtube_handler = YouTubeHandler(self.browser_manager.driver)
            playlist_fetch_start = time.time()
            videos = youtube_handler.get_playlist_videos_selenium(
                url, 
                config.max_videos,
                config.include_current,
                config.process_all
            )
            perf_log(
                "playlist_fetch",
                playlist_fetch_start,
                videos=len(videos) if videos else 0,
                process_all=config.process_all
            )
            
            if not videos:
                raise Exception("動画が見つかりませんでした")
            
            state.total_items = len(videos)
            self.progress_bar['maximum'] = state.total_items
            
            glasp_engine = GlaspEngine(self.browser_manager)
            
            # 進捗更新表示
            def update_ui():
                self.progress_bar['value'] = state.current_progress
                self.update()

            glasp_process_start = time.time()
            results = glasp_engine.process_videos(videos, config)
            perf_log(
                "glasp_engine_process",
                glasp_process_start,
                videos=len(videos),
                results=len(results) if results else 0
            )
            
            state.current_progress = state.total_items
            update_ui()
            perf_log(
                "process_with_glasp_total",
                total_start,
                videos=len(videos),
                results=len(results) if results else 0
            )
            return results
            
        except Exception as e:
            # UIログにスタックトレースを流し込む
            self.log_to_ui(f"Glaspメイン処理で例外発生: {e}", "ERROR")
            self.log_to_ui(f"詳細スタックトレース:\n{traceback.format_exc()}", "ERROR")
            raise e

    def process_with_api(self, url: str, config: ProcessConfig) -> List[SummaryResult]:
        """APIモードで処理"""
        # 既存のprocess_with_apiメソッドをそのまま使用
        videos = []
        
        video_id = extract_video_id(url)
        playlist_id = extract_playlist_id(url)
        
        if playlist_id:
            if not self.browser_manager:
                self.browser_manager = BrowserManager()
                
            if not self.browser_manager.driver:
                self.log_to_ui("Chrome WebDriverを初期化します...", "INFO")
                if not self.browser_manager.init_chrome_driver(debug_mode=True):
                    if not self.browser_manager.init_chrome_driver(debug_mode=False):
                        raise Exception("Chrome初期化に失敗しました")
            else:
                self.log_to_ui("既存のChrome接続を使用します", "INFO")
            
            youtube_handler = YouTubeHandler(self.browser_manager.driver)
            videos = youtube_handler.get_playlist_videos_selenium(
                url,
                config.max_videos,
                config.include_current,
                config.process_all
            )
            
        elif video_id:
            videos = [VideoInfo(
                video_id=video_id,
                url=url,
                title="動画"
            )]
        
        if not videos:
            raise Exception("動画が見つかりませんでした")
        
        state.total_items = len(videos)
        self.progress_bar['maximum'] = state.total_items
        
        def update_progress():
            self.progress_bar['value'] = state.current_progress
            self.status_label.config(text=f"処理中: {state.current_progress}/{state.total_items}")
            percentage = (state.current_progress / state.total_items * 100) if state.total_items > 0 else 0
            self.log_to_ui(f"進捗: {percentage:.1f}% ({state.current_progress}/{state.total_items})", "INFO")
            self.update()
        
        api_engine = APIEngine()
        
        gemini_key = config_manager.get('api.gemini_api_key')
        openai_key = config_manager.get('api.openai_api_key')
        
        if config.model in MODEL_CONFIG:
            model_provider = MODEL_CONFIG[config.model]['provider']
            if model_provider == 'google' and not gemini_key:
                raise Exception("Gemini APIキーが設定されていません。環境変数GEMINI_API_KEYを設定してください。")
            elif model_provider == 'openai' and not openai_key:
                raise Exception("OpenAI APIキーが設定されていません。環境変数OPENAI_API_KEYを設定してください。")
        
        self.log_to_ui(f"=== API処理開始: {len(videos)}個の動画 ===", "INFO")
        self.log_to_ui(f"使用モデル: {config.model}", "INFO")
        
        optimal_parallel = get_optimal_parallel_count(len(videos))
        actual_parallel = min(optimal_parallel, config.parallel_count)
        self.log_to_ui(f"並列処理数: {actual_parallel}（最適化済み）", "INFO")
        
        self.log_to_ui(self.rate_limiter.get_status_message(), "INFO")
        
        results = []
        with ThreadPoolExecutor(max_workers=actual_parallel) as executor:
            futures = []
            
            for i, video in enumerate(videos):
                if check_user_input() == 'cancel':
                    break
                
                if i > 0 and i % self.rate_limiter.burst_size == 0:
                    wait_time = self.rate_limiter.burst_interval
                    self.log_to_ui(f"バースト制御: {wait_time}秒待機", "INFO")
                    time.sleep(wait_time)
                
                future = executor.submit(api_engine._process_single_video, video, config)
                futures.append((future, video))
            
            for future, video in futures:
                if check_user_input() == 'cancel':
                    break
                
                try:
                    result = future.result(timeout=30)
                    results.append(result)
                    
                    state.current_progress += 1
                    update_progress()
                    
                    if result.success:
                        self.log_to_ui(
                            f"✅ 完了: {video.title[:50]}... "
                            f"(処理時間: {result.processing_time:.1f}秒)",
                            "SUCCESS"
                        )
                    else:
                        self.log_to_ui(
                            f"❌ 失敗: {video.title[:50]}... "
                            f"({result.error_message})",
                            "ERROR"
                        )
                    
                    if state.current_progress % 5 == 0:
                        self.log_to_ui(self.rate_limiter.get_status_message(), "INFO")
                    
                except Exception as e:
                    self.log_to_ui(f"処理エラー: {e}", "ERROR")
                    results.append(SummaryResult(
                        video_info=video,
                        success=False,
                        error_message=str(e),
                        model_used=config.model
                    ))
                    state.current_progress += 1
                    update_progress()
        
        success_count = sum(1 for r in results if r.success)
        total_cost = sum(r.cost for r in results)
        
        self.log_to_ui(f"=== API処理完了 ===", "SUCCESS")
        self.log_to_ui(f"成功: {success_count}/{len(results)}", "INFO")
        self.log_to_ui(f"推定コスト: ${total_cost:.4f} (約{total_cost*150:.3f}円)", "INFO")
        self.log_to_ui(self.rate_limiter.get_status_message(), "INFO")
        
        return results
    
    def stop_processing(self):
        """処理停止"""
        if state.processing:
            state.cancel_flag = True
            self.log_to_ui("処理を停止しています...", "WARNING")

    def save_results(self):
        """結果保存"""
        if not state.results:
            auto_showwarning("警告", "保存する結果がありません")
            return
        
        output_format = self.output_format_var.get()
        output_gen = OutputGenerator()
        
        try:
            if output_format in ['json', 'both']:
                json_file = output_gen.save_json(state.results)
                self.log_to_ui(f"JSON保存: {json_file}", "SUCCESS")
            
            if output_format in ['html', 'both']:
                # デバッグ情報追加
                import traceback
                try:
                    html_file = output_gen.generate_html(state.results)
                    self.log_to_ui(f"HTML生成: {html_file}", "SUCCESS")
                    
                    import webbrowser
                    webbrowser.open(html_file)
                except AttributeError as ae:
                    self.log_to_ui(f"AttributeError: {str(ae)}", "ERROR")
                    self.log_to_ui(f"詳細: {traceback.format_exc()}", "ERROR")
                    raise
            
        except Exception as e:
            auto_showerror("保存エラー", f"保存中にエラーが発生しました:\n{e}")

    

    def show_tab_selection_dialog(self, playlist_tabs: List[Tuple[str, str, str]]) -> Optional[Tuple[str, str, str]]:
        """複数のプレイリストタブから選択するダイアログを表示
        
        自動モード対応版：AutoTabSelectionDialogを使用
        """
        if not playlist_tabs:
            return None
        
        if len(playlist_tabs) == 1:
            log_message("プレイリストタブが1つのため自動選択", "INFO")
            return playlist_tabs[0]
        
        # AutoTabSelectionDialogを使用
        dialog = AutoTabSelectionDialog(self, playlist_tabs)
        dialog.wait_window()
        
        return dialog.get_selected()


    
    def paste_url(self):
        """クリップボードからURL貼り付け"""
        try:
            url = self.clipboard_get()
            self.url_var.set(url)
        except:
            pass


    def save_settings(self):
        """設定を保存"""
        config_manager.set('general.default_mode', self.mode_var.get())
        config_manager.set('general.max_videos', self.max_videos_var.get())
        config_manager.set('api.default_model', self.model_var.get())
        config_manager.set('api.parallel_count', self.parallel_var.get())
        config_manager.set('general.output_format', self.output_format_var.get())
        config_manager.save_config()
        auto_showinfo("保存完了", "設定を保存しました")

    def load_settings(self):
        """設定を読込"""
        config_manager.load_config()
        self.mode_var.set(config_manager.get('general.default_mode'))
        self.max_videos_var.set(config_manager.get('general.max_videos'))
        self.model_var.set(config_manager.get('api.default_model'))
        self.parallel_var.set(config_manager.get('api.parallel_count'))
        self.output_format_var.set(config_manager.get('general.output_format'))
        self.update_ui_by_mode()
        auto_showinfo("読込完了", "設定を読み込みました")


    def start_chrome_debug(self):
        """Chromeデバッグモード起動（アプリ連携修正版）"""
        # 既存のマネージャーがあればクリーンアップ
        if self.browser_manager:
            try:
                self.browser_manager.cleanup()
            except:
                pass
        
        # 新しいマネージャーを作成してアプリに登録
        self.browser_manager = BrowserManager()
        
        # ブラウザ起動
        if self.browser_manager.init_chrome_driver(debug_mode=True):
            auto_showinfo("成功", 
                "Chromeを起動しました。\n\n"
                "1. このChromeでYouTubeのプレイリストを開いてください。\n"
                "2. 準備ができたら、アプリの「処理開始」ボタンを押してください。\n"
                "   (URL欄が空でも、開いているタブから自動検出します)")
        else:
            auto_showerror("エラー", "Chrome起動に失敗しました")
            self.browser_manager = None


    def open_report_video(self):
        """レポート内の動画をChromeで開く"""
        if not state.results:
            auto_showwarning("警告", "処理済みの動画がありません。\nまず動画を処理してください。")
            return
        
        success_results = [r for r in state.results if r.success]
        if not success_results:
            auto_showwarning("警告", "表示可能な動画がありません。")
            return
        
        dialog = tk.Toplevel(self)
        dialog.title("動画を選択")
        dialog.geometry("700x500")
        dialog.transient(self)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - dialog.winfo_width()) // 2
        y = (dialog.winfo_screenheight() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        label = ttk.Label(dialog, text="Chromeで開く動画を選択してください：", 
                         font=("Arial", 11))
        label.pack(pady=10)
        
        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        listbox = tk.Listbox(frame, font=("Arial", 10))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.configure(yscrollcommand=scrollbar.set)
        
        video_urls = []
        for i, result in enumerate(success_results):
            video = result.video_info
            summary_title = result.extract_title()
            
            display_text = f"{i+1}. {summary_title[:60]}..."
            listbox.insert(tk.END, display_text)
            
            if video.channel != "Unknown":
                listbox.insert(tk.END, f"     📺 {video.channel}")
            
            listbox.insert(tk.END, f"     ⏱️ {result.processing_time:.1f}秒 | 🤖 {result.model_used}")
            
            if result.matched_by_title:
                listbox.insert(tk.END, f"     ✅ タイトル照合成功")
            
            listbox.insert(tk.END, "")
            
            video_urls.append(video.url)
        
        if listbox.size() > 0:
            listbox.selection_set(0)
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        
        def on_open():
            selection = listbox.curselection()
            if selection:
                actual_index = selection[0] // 4
                if actual_index < len(video_urls):
                    url = video_urls[actual_index]
                    dialog.destroy()
                    self.open_video_in_chrome(url)
        
        def on_open_all():
            if len(video_urls) > 5:
                result = auto_askyesno("確認", 
                    f"{len(video_urls)}個の動画をすべて開きます。\n"
                    "多数のタブが開かれます。続行しますか？",
                    default=True)
                if not result:
                    return
            
            dialog.destroy()
            for url in video_urls:
                self.open_video_in_chrome(url)
                time.sleep(0.5)
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="開く", command=on_open, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="すべて開く", command=on_open_all, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="キャンセル", command=on_cancel, width=15).pack(side=tk.LEFT, padx=5)
        
        listbox.bind('<Double-Button-1>', lambda e: on_open())
        
        dialog.bind('<Return>', lambda e: on_open())
        dialog.bind('<Escape>', lambda e: on_cancel())
        
        dialog.wait_window()


    def open_video_in_chrome(self, url: str):
        """指定したURLをChromeで開く"""
        try:
            if not self.browser_manager:
                self.browser_manager = BrowserManager()
            
            if not self.browser_manager.driver:
                self.log_to_ui("Chrome接続を確認中...", "INFO")
                if not self.browser_manager.init_chrome_driver(debug_mode=True):
                    if not self.browser_manager.init_chrome_driver(debug_mode=False):
                        auto_showerror("エラー", "Chromeに接続できませんでした。")
                        return
            
            success = self.browser_manager.switch_or_create_tab(url)
            
            if success:
                self.log_to_ui(f"動画を開きました: {url[:50]}...", "SUCCESS")
                self.browser_manager.bring_chrome_to_front()
            else:
                self.log_to_ui(f"動画を開けませんでした: {url[:50]}...", "ERROR")
                
        except Exception as e:
            self.log_to_ui(f"動画を開く際にエラー: {e}", "ERROR")
            auto_showerror("エラー", f"動画を開けませんでした:\n{e}")


    
    def open_output_folder(self):
        """出力フォルダを開く"""
        import os
        import subprocess
        
        if platform.system() == "Windows":
            os.startfile(OUTPUT_DIR)
        elif platform.system() == "Darwin":
            subprocess.call(["open", OUTPUT_DIR])
        else:
            subprocess.call(["xdg-open", OUTPUT_DIR])


    def show_help(self):
        """ヘルプ表示"""
        help_text = """
    YouTube Summary Integrated System - 使い方

    1. 処理モードを選択
       - 単一プレイリスト: 1つのプレイリストを処理
       - 複数プレイリスト: 複数の固定プレイリストを一括処理

    2. 処理エンジンを選択
       - API直接処理: 高速・低コスト
       - Glasp拡張機能: ブラウザ連携

    3. 設定を調整
       - バッチサイズ（Glaspモードのみ）
       - AIモデル（APIモードのみ）
       - 並列処理数（APIモードのみ）

    4. 処理開始をクリック

    5. 結果を保存
       - JSON形式
       - HTML形式（ブラウザで表示）

    自動モード（Auto）：
    - すべての確認ダイアログを自動処理
    - プレイリスト選択も自動
    - 完全無人実行が可能

    レート制限について：
    - 1時間あたり200リクエストが上限
    - 自動的に処理速度が調整されます
    - 状態はツール→レート制限状態確認で確認

    メモリ管理について：
    - 自動的にタブのクリーンアップが実行されます
    - メモリ使用量が高い場合は警告が表示されます
    """
        auto_showinfo("使い方", help_text)


    def show_about(self):
        """バージョン情報表示"""
        about_text = f"""
    YouTube Summary Integrated System
    Version {VERSION}

    統合型YouTube要約システム
    Glasp/API デュアルエンジン対応
    複数プレイリスト一括処理対応
    レート制限管理機能搭載
    タブ追跡機能強化版
    自動モード搭載（完全無人実行対応）

    © 2024 - All rights reserved
    """
        auto_showinfo("バージョン情報", about_text)


    def auto_close_application(self):
            """自動モード時のアプリケーション自動終了"""
            if not auto_mode_manager.is_enabled():
                self.log_to_ui("自動終了がキャンセルされました（手動モードに変更）", "WARNING")
                return
            
            try:
                self.log_to_ui("🤖 自動モード：アプリケーションを終了します", "SUCCESS")
                logger.info("=== 自動モード：正常終了 ===")
                
                # 設定保存
                if config_manager.get('general.auto_save'):
                    config_manager.save_config()
                
                # レート制限状態保存
                state.rate_limiter.save_state()
                
                # ブラウザクリーンアップ
                if self.browser_manager:
                    self.browser_manager.cleanup()
                
                # アプリケーション終了 (修正: quitを追加してループを抜ける)
                self.quit()    # <--- 【追加】mainloopを停止
                self.destroy() # <--- ウィンドウを破棄
                
            except Exception as e:
                logger.error(f"自動終了エラー: {e}")
                # エラーでも強制終了
                try:
                    self.quit()
                    self.destroy()
                except:
                    pass


    def on_closing(self):
        """アプリケーション終了時の処理"""
        if state.processing:
            if auto_askokcancel("確認", "処理中ですが終了しますか？", default=False):
                state.cancel_flag = True
                time.sleep(1)
            else:
                return  # 終了をキャンセル
        
        if self.browser_manager:
            self.browser_manager.cleanup()
        
        if config_manager.get('general.auto_save'):
            config_manager.save_config()
        
        state.rate_limiter.save_state()
        
        # 終了処理 (修正: quitを追加してループを抜ける)
        self.quit()    # <--- 【追加】mainloopを停止
        self.destroy() # <--- ウィンドウを破棄


    def _save_playlist_results(self, results, playlist_name, config):
        """結果保存の共通メソッド"""
        try:
            output_gen = OutputGenerator()
            if config.output_format in ['json', 'both']:
                json_file = output_gen.save_json(results, playlist_id=playlist_name)
                self.log_to_ui(f"JSON保存: {json_file}", "SUCCESS")
            
            if config.output_format in ['html', 'both']:
                html_file = output_gen.generate_html(results, playlist_id=playlist_name)
                self.log_to_ui(f"HTML生成: {html_file}", "SUCCESS")
        except Exception as e:
            self.log_to_ui(f"結果保存エラー: {e}", "ERROR")



class ProcessControlWindow(tk.Toplevel):
    """処理制御ウィンドウ（リアルタイムモニター版）"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self.title("処理制御パネル")
        self.geometry("450x550") # 少し縦長に
        self.resizable(False, False)
        
        # 常に前面表示
        self.attributes('-topmost', True)
        
        # 位置設定（画面右下）
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = screen_width - 500
        y = screen_height - 600
        self.geometry(f"+{x}+{y}")
        
        # UI構築
        self.setup_ui()
        
        # ポーリング開始（0.5秒ごとに更新）
        self.start_polling()
        
        # ウィンドウが閉じられた時の処理
        self.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def setup_ui(self):
        """UI構築（詳細情報対応）"""
        main_frame = ttk.Frame(self, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 1. プレイリスト情報
        ttk.Label(main_frame, text="現在のプレイリスト:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.playlist_label = ttk.Label(main_frame, text="-", font=("Arial", 11), foreground="blue")
        self.playlist_label.pack(anchor=tk.W, pady=(0, 10))
        
        # 2. 進捗状況
        progress_frame = ttk.LabelFrame(main_frame, text="全体進捗", padding="10")
        progress_frame.pack(fill=tk.X, pady=5)
        
        self.progress_text_label = ttk.Label(progress_frame, text="0 / 0", font=("Arial", 14, "bold"))
        self.progress_text_label.pack()
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=5)
        
        self.batch_label = ttk.Label(progress_frame, text="バッチ待機中", font=("Arial", 9), foreground="gray")
        self.batch_label.pack()

        # 3. 現在の作業詳細
        status_frame = ttk.LabelFrame(main_frame, text="現在の状況", padding="10")
        status_frame.pack(fill=tk.X, pady=10)
        
        self.video_label = ttk.Label(status_frame, text="待機中...", font=("Arial", 10, "bold"), wraplength=400)
        self.video_label.pack(anchor=tk.W, fill=tk.X)
        
        self.status_detail_label = ttk.Label(status_frame, text="準備完了", font=("Arial", 9), foreground="#555")
        self.status_detail_label.pack(anchor=tk.W, pady=(5, 0))
        
        # 4. コントロールボタン
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=15, fill=tk.X)
        
        # スキップボタン（緑）
        self.skip_button = tk.Button(button_frame, text="⏭️ スキップ", 
                                     command=self.request_skip,
                                     bg="#4CAF50", fg="white",
                                     font=("Arial", 11, "bold"),
                                     width=15, height=2)
        self.skip_button.pack(side=tk.LEFT, padx=5, expand=True)
        
        # 停止ボタン（赤）
        self.stop_button = tk.Button(button_frame, text="⏹️ 停止", 
                                    command=self.request_stop,
                                    bg="#f44336", fg="white",
                                    font=("Arial", 11, "bold"),
                                    width=15, height=2)
        self.stop_button.pack(side=tk.RIGHT, padx=5, expand=True)


    def start_polling(self):
        """定期的にGlobalStateを読みに行き、画面を更新する（プル型更新）"""
        if not self.winfo_exists():
            return
            
        try:
            self.update_ui_from_state() 
        except Exception:
            pass
            
        # 500ms後に再実行（自己ポーリングを復活）
        self.after(500, self.start_polling)



    def update_ui_from_state(self):
        """GlobalStateから最新情報を取得してUIに反映"""
        # プレイリスト
        if state.current_playlist:
            self.playlist_label.config(text=f"【{state.current_playlist}】処理中")
        else:
            self.playlist_label.config(text="単一/未定")
            
        # 進捗
        if state.total_items > 0:
            self.progress_text_label.config(text=f"{state.current_progress} / {state.total_items}")
            self.progress_bar['maximum'] = state.total_items
            self.progress_bar['value'] = state.current_progress
        
        # バッチ情報
        batch_status = state.get_batch_status()
        if batch_status:
            self.batch_label.config(text=batch_status)
            
        # 動画タイトル
        current_title = state.current_video_title
        if len(current_title) > 40:
            current_title = current_title[:40] + "..."
        self.video_label.config(text=current_title)
        
        # 詳細ステータス
        self.status_detail_label.config(text=state.detailed_status)
        
        # ★★★ 修正箇所2: 無限再帰の原因となる self.update() または self.after() の呼び出しを削除 ★★★
        # ProcessControlWindowは、IntegratedSummaryAppからのafter()呼び出しのみに依存する

        # ボタン状態のリセット（フラグが回収されたら元に戻す）
        if not state.skip_flag and self.skip_button['text'] != "⏭️ スキップ":
            self.skip_button.config(text="⏭️ スキップ", state="normal", bg="#4CAF50")
            
        if not state.cancel_flag and self.stop_button['text'] != "⏹️ 停止":
            self.stop_button.config(text="⏹️ 停止", state="normal", bg="#f44336")


    def request_skip(self):
        """スキップ要求"""
        state.skip_flag = True
        # 即時フィードバック
        self.skip_button.config(text="要求中...", state="disabled", bg="#81C784")
        self.status_detail_label.config(text="スキップ要求を受け付けました...")
        log_message("UI: スキップボタンが押されました", "WARNING")
    
    def request_stop(self):
        """停止要求"""
        state.cancel_flag = True
        # 即時フィードバック
        self.stop_button.config(text="停止中...", state="disabled", bg="#E57373")
        self.status_detail_label.config(text="停止処理を実行中です...")
        log_message("UI: 停止ボタンが押されました", "WARNING")

    def on_close(self):
        """ウィンドウが閉じられた時"""
        # 親ウィンドウに通知せず、単に非表示にするか、停止とみなすか
        # ここでは停止扱いにする
        if state.processing:
            if messagebox.askyesno("確認", "処理を停止して閉じますか？"):
                state.cancel_flag = True
                self.destroy()
        else:
            self.destroy()

    # 互換性のためのダミーメソッド（旧コードからの呼び出しエラー防止）
    def update_status(self, message, current, total):
        pass


# ============================================================================
# SECTION 12: MAIN PROCESSING LOGIC
# ============================================================================

def parse_arguments():
    """コマンドライン引数をパース
    
    Returns:
        argparse.Namespace: パース済み引数
    """

    
    parser = argparse.ArgumentParser(
        description=f'{APP_TITLE} - YouTube動画を自動要約',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 通常起動
  python %(prog)s
  
  # 自動モードで起動（起動後5秒で自動開始）
  python %(prog)s --auto
  
  # 自動モード + 特定プレイリストを処理
  python %(prog)s --auto --playlists S A B
  
  # 自動モード + APIモード指定
  python %(prog)s --auto --mode api --model gemini-2.5-flash-lite
        """
    )
    
    # 自動モードフラグ
    parser.add_argument(
        '--auto',
        action='store_true',
        help='自動モードで起動（起動後5秒で処理開始、すべてのダイアログを自動処理）'
    )
    
    # プレイリスト指定（オプション）
    parser.add_argument(
        '--playlists',
        nargs='+',
        choices=['V', 'S', 'A', 'B', 'N', 'M', 'P+', 'L'],
        help='処理するプレイリストを指定（複数指定可）例: --playlists S A B'
    )
    
    # 処理モード指定（オプション）
    parser.add_argument(
        '--mode',
        choices=['glasp', 'api'],
        help='処理エンジンを指定（glasp: ブラウザ連携, api: API直接処理）'
    )
    
    # AIモデル指定（オプション）
    parser.add_argument(
        '--model',
        choices=list(MODEL_CONFIG.keys()),
        help='使用するAIモデルを指定（APIモード時のみ有効）'
    )
    
    # 処理モード：単一/複数（オプション）
    parser.add_argument(
        '--processing-mode',
        choices=['single', 'multiple'],
        help='処理モードを指定（single: 単一プレイリスト, multiple: 複数プレイリスト）'
    )
    
    # バッチサイズ（オプション）
    parser.add_argument(
        '--batch-size',
        type=int,
        choices=range(1, 21),
        metavar='1-20',
        help='バッチサイズを指定（Glaspモード時、1-20の範囲）'
    )
    
    # デバッグモード（オプション）
    parser.add_argument(
        '--debug',
        action='store_true',
        help='デバッグモードで起動（詳細ログを出力）'
    )
    
    # バージョン情報
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {VERSION}'
    )
    
    return parser.parse_args()


def main():
    """メインエントリーポイント"""
    try:
        # ========== 新規追加：起動時クリーンアップ（毎回新品にする） ==========
        # これを入れることで、前回のゾンビプロセスや壊れたドライバを確実に始末してから開始する
        perform_boot_cleanup()

        # ========== 新規追加：コマンドライン引数パース ==========
        args = parse_arguments()
        
        # デバッグモード設定
        if args.debug:
            logger.setLevel(logging.DEBUG)
            logger.debug("デバッグモード有効")
        
        # ログ開始
        logger.info(f"=== {APP_TITLE} 起動 ===")
        
        # ========== 新規追加：アプリケーション起動（引数渡し）==========
        app = IntegratedSummaryApp(args)
        app.mainloop()
        
        logger.info("=== アプリケーション正常終了 ===")
        
    except KeyboardInterrupt:
        # ユーザーによる中断（Ctrl+C）は正常終了とみなしてエラーを出さない
        print("\nユーザーにより処理が中断されました。")
        logger.info("ユーザーにより処理が中断されました。")
        
    except Exception as e:
        logger.error(f"致命的エラー: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 自動モードでもエラーは表示（ただし自動クローズ）
        try:
            from tkinter import messagebox
            messagebox.showerror("エラー", f"アプリケーションエラー:\n{e}")
        except:
            pass
    
    finally:
        # レート制限状態を保存
        if state.rate_limiter:
            state.rate_limiter.save_state()
        
        # プロセスを確実に終了させる
        import sys
        sys.exit(0)

            
# ============================================================================
# SECTION 13: MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()