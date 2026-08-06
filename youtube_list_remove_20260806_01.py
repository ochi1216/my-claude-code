import asyncio
import tkinter as tk
from tkinter import messagebox, simpledialog
from playwright.async_api import async_playwright
import threading
import time
import logging
import re
import os
import subprocess
from typing import List, Optional, Dict, Any
import json
from dataclasses import dataclass
import gc
import psutil
import sys
import warnings
import argparse  # 引数処理用に追加

# 安全なログ設定
def setup_logging():
    """安全なログ設定を行う"""
    try:
        # 既存のハンドラーをクリア
        logger = logging.getLogger(__name__)
        
        # 既存のハンドラーを安全に削除
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # ルートロガーのハンドラーもクリア（重複を避けるため）
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 新しいログ設定
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('youtube_manager.log', encoding='utf-8')
            ],
            force=True  # 既存の設定を強制的に上書き
        )
        
        return logging.getLogger(__name__)
        
    except Exception as e:
        # ログ設定に失敗した場合の最小限の設定
        print(f"ログ設定エラー: {e}")
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)

# ログ設定を実行
logger = setup_logging()

@dataclass
class SelectorCache:
    """成功したセレクターをキャッシュする"""
    playlist_name_selector: Optional[str] = None
    menu_button_selector: Optional[str] = None
    remove_button_selector: Optional[str] = None
    video_count_selector: Optional[str] = None

@dataclass
class BatchConfig:
    """バッチ処理設定"""
    batch_size: int = 10
    max_memory_mb: int = 500
    refresh_interval: int = 2  # バッチ何回毎にページリフレッシュ
    base_wait_time: float = 0.3
    max_wait_time: float = 0.8


class YouTubePlaylistManager:
    
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.cancel_operation = False
        self.cancel_window = None
        self.selector_cache = SelectorCache()
        self.batch_config = BatchConfig()
        
        # 新規追加: プログレス表示とリソース管理
        self.setup_progress_display()
        self.setup_resource_monitoring()
        
        # 統計情報
        self.stats = {
            'total_processed': 0,
            'batch_count': 0,
            'refresh_count': 0,
            'memory_warnings': 0
        }
    
    def setup_progress_display(self):
        """プログレス表示の初期化"""
        self.start_time = time.time()
        self.last_progress_time = 0
        self.quiet_mode = False
    
    def setup_resource_monitoring(self):
        """リソース監視の初期化"""
        self.initial_memory = self.get_current_memory_usage()
        self.max_memory_seen = self.initial_memory
        self.health_check_interval = 5  # 5回に1回ヘルスチェック
        
    def get_current_memory_usage(self) -> float:
        """現在のメモリ使用量をMB単位で取得"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            return memory_info.rss / 1024 / 1024  # MB
        except Exception as e:
            logger.debug(f"メモリ使用量取得エラー: {e}")
            return 0.0

    def check_browser_health(self) -> Dict[str, Any]:
        """ブラウザプロセスの健康状態をチェック"""
        try:
            current_memory = self.get_current_memory_usage()
            self.max_memory_seen = max(self.max_memory_seen, current_memory)
            
            memory_increase = current_memory - self.initial_memory
            memory_threshold_exceeded = current_memory > self.batch_config.max_memory_mb
            
            # Chrome プロセスの確認
            chrome_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    if 'chrome' in proc.info['name'].lower():
                        chrome_memory = proc.info['memory_info'].rss / 1024 / 1024
                        chrome_processes.append({
                            'pid': proc.info['pid'],
                            'memory_mb': chrome_memory
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            total_chrome_memory = sum(p['memory_mb'] for p in chrome_processes)
            
            health_status = {
                'healthy': not memory_threshold_exceeded,
                'current_memory_mb': current_memory,
                'memory_increase_mb': memory_increase,
                'max_memory_seen_mb': self.max_memory_seen,
                'chrome_process_count': len(chrome_processes),
                'total_chrome_memory_mb': total_chrome_memory,
                'threshold_exceeded': memory_threshold_exceeded,
                'recommendation': 'continue'
            }
            
            if memory_threshold_exceeded:
                health_status['recommendation'] = 'refresh_needed'
                self.stats['memory_warnings'] += 1
                logger.warning(f"メモリ使用量が閾値を超過: {current_memory:.1f}MB > {self.batch_config.max_memory_mb}MB")
            
            return health_status
            
        except Exception as e:
            logger.error(f"ブラウザヘルスチェックエラー: {e}")
            return {
                'healthy': True,  # エラー時は継続と判定
                'error': str(e),
                'recommendation': 'continue'
            }

    def cleanup_dom_references(self):
        """DOM要素参照の明示的解放とガベージコレクション"""
        try:
            # セレクターキャッシュは保持（パフォーマンス維持）
            
            # 統計情報以外の一時的な属性をクリア
            temp_attrs = ['last_video_elements', 'current_batch_elements', 'temp_selectors']
            for attr in temp_attrs:
                if hasattr(self, attr):
                    setattr(self, attr, None)
            
            # 強制ガベージコレクション
            collected = gc.collect()
            
            logger.debug(f"DOM参照クリーンアップ完了: {collected}個のオブジェクトを回収")
            
        except Exception as e:
            logger.debug(f"DOM参照クリーンアップエラー: {e}")

    def get_dynamic_wait_time(self, operation_count: int, base_time: float = None) -> float:
        """処理回数に応じた動的待機時間の計算"""
        if base_time is None:
            base_time = self.batch_config.base_wait_time
        
        # 処理回数が増えるにつれて待機時間を延長（負荷軽減）
        if operation_count <= 5:
            multiplier = 1.0
        elif operation_count <= 15:
            multiplier = 1.2
        elif operation_count <= 30:
            multiplier = 1.5
        else:
            multiplier = 2.0
        
        calculated_time = base_time * multiplier
        return min(calculated_time, self.batch_config.max_wait_time)

    def set_quiet_mode(self, quiet: bool = True):
        """静かなモードを設定（重要な情報のみ表示）"""
        self.quiet_mode = quiet
        if quiet:
            # ログレベルをWARNING以上に設定
            logger.setLevel(logging.WARNING)
        else:
            logger.setLevel(logging.INFO)

    def clean_video_title(self, raw_text: str, max_length: int = 30) -> str:
        """動画タイトルをクリーンアップして表示用に整形"""
        if not raw_text:
            return "タイトル取得不可"
        
        # 改行文字、タブ、余分な空白を除去
        cleaned = re.sub(r'\s+', ' ', raw_text.strip())
        
        # 特殊文字や記号を除去（再生マークなど）
        cleaned = re.sub(r'[▶️⏸️⏯️⏹️]', '', cleaned)
        
        # 時間表記を除去（例：8:15, 17:13など）
        cleaned = re.sub(r'\d+:\d+', '', cleaned)
        
        # "再生中"などのステータステキストを除去
        cleaned = re.sub(r'(再生中|再生|一時停止)', '', cleaned)
        
        # 再度空白を整理
        cleaned = ' '.join(cleaned.split())
        
        # 長さ制限
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length-3] + "..."
        
        return cleaned if cleaned else "タイトル不明"

    def show_progress_bar(self, current: int, total: int, prefix: str = "進捗") -> str:
        """プログレスバーを生成"""
        percentage = (current / total) * 100 if total > 0 else 0
        bar_length = 30
        filled_length = int(bar_length * current // total) if total > 0 else 0
        bar = '█' * filled_length + '-' * (bar_length - filled_length)
        return f"{prefix}: |{bar}| {current}/{total} ({percentage:.1f}%)"

    def show_batch_progress(self, batch_num: int, total_batches: int, items_in_batch: int, batch_size: int) -> str:
        """バッチ進捗バーを生成"""
        batch_percentage = (batch_num / total_batches) * 100 if total_batches > 0 else 0
        item_percentage = (items_in_batch / batch_size) * 100 if batch_size > 0 else 0
        
        return f"バッチ {batch_num}/{total_batches} ({batch_percentage:.1f}%) | バッチ内 {items_in_batch}/{batch_size} ({item_percentage:.1f}%)"

    def print_section_header(self, title: str, char: str = "="):
        """セクションヘッダーを表示"""
        print(f"\n{char * 50}")
        print(f" {title}")
        print(f"{char * 50}")

    def print_deletion_progress(self, current: int, total: int, video_title: str):
        """削除進捗を美しく表示"""
        # プログレスバー
        progress_bar = self.show_progress_bar(current, total, "削除進捗")
        
        # 経過時間
        elapsed = time.time() - self.start_time
        avg_time_per_deletion = elapsed / current if current > 0 else 0
        estimated_remaining = avg_time_per_deletion * (total - current)
        
        # クリーンなタイトル
        clean_title = self.clean_video_title(video_title)
        
        print(f"\r{progress_bar}", end="", flush=True)
        
        # 詳細情報は1秒に1回だけ表示
        current_time = time.time()
        if current_time - self.last_progress_time >= 1.0:
            print(f"\n  削除中: {clean_title}")
            print(f"  経過時間: {elapsed:.1f}秒 | 残り予想: {estimated_remaining:.1f}秒")
            self.last_progress_time = current_time

    def print_batch_summary(self, batch_num: int, batch_success: int, batch_total: int, elapsed: float):
        """バッチ処理結果のサマリーを表示"""
        print(f"\n📦 バッチ {batch_num} 完了:")
        print(f"  ✅ 成功: {batch_success}/{batch_total} 件")
        print(f"  ⏱️  処理時間: {elapsed:.1f}秒")
        if batch_success > 0:
            print(f"  📈 平均処理時間: {elapsed/batch_success:.1f}秒/件")

    def print_final_summary(self, deleted_count: int, total_requested: int, elapsed_time: float):
        """最終結果のサマリーを表示"""
        self.print_section_header("削除処理完了", "✅")
        print(f"✅ 削除完了: {deleted_count}/{total_requested} 件")
        print(f"⏱️  処理時間: {elapsed_time:.1f}秒")
        if deleted_count > 0:
            print(f"📈 平均処理時間: {elapsed_time/deleted_count:.1f}秒/件")
        
        # リソース使用統計
        print(f"\n📊 処理統計:")
        print(f"  🔄 バッチ処理回数: {self.stats['batch_count']}")
        print(f"  🔄 ページリフレッシュ回数: {self.stats['refresh_count']}")
        print(f"  ⚠️  メモリ警告回数: {self.stats['memory_warnings']}")
        print(f"  💾 最大メモリ使用量: {self.max_memory_seen:.1f}MB")
        
        print("✅" * 50)

    def print_resource_status(self, health_info: Dict[str, Any]):
        """リソース状態の表示"""
        if not health_info.get('healthy', True):
            print(f"⚠️  メモリ使用量: {health_info['current_memory_mb']:.1f}MB (増加: +{health_info['memory_increase_mb']:.1f}MB)")
            print(f"🌐 Chrome プロセス: {health_info['chrome_process_count']}個, 総メモリ: {health_info['total_chrome_memory_mb']:.1f}MB")
                        
    def bring_chrome_to_front(self):
        """Chromeウィンドウを物理的に前面に表示（強化版）"""
        try:
            logger.info("Chromeウィンドウを前面に表示中...")
            
            # Windowsの場合
            if os.name == 'nt':
                try:
                    import win32gui
                    import win32con
                    import win32process
                    import win32api
                    
                    def enum_windows_callback(hwnd, windows):
                        """ウィンドウ列挙のコールバック関数"""
                        try:
                            if win32gui.IsWindowVisible(hwnd):
                                window_title = win32gui.GetWindowText(hwnd)
                                class_name = win32gui.GetClassName(hwnd)
                                
                                # Chromeウィンドウの特定（複数パターン対応）
                                chrome_indicators = [
                                    'chrome.exe' in window_title.lower(),
                                    'google chrome' in window_title.lower(),
                                    'chrome' in class_name.lower(),
                                    class_name == 'Chrome_WidgetWin_1'
                                ]
                                
                                if any(chrome_indicators):
                                    # プロセスIDを取得してChromeプロセスか確認
                                    try:
                                        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
                                        process_handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, process_id)
                                        process_name = win32process.GetModuleFileNameEx(process_handle, 0)
                                        win32api.CloseHandle(process_handle)
                                        
                                        if 'chrome.exe' in process_name.lower():
                                            windows.append({
                                                'hwnd': hwnd,
                                                'title': window_title,
                                                'class': class_name,
                                                'process_id': process_id
                                            })
                                            logger.debug(f"Chromeウィンドウ発見: {window_title} (PID: {process_id})")
                                    
                                    except Exception as process_e:
                                        # プロセス確認に失敗した場合でも、タイトルでChromeと判断できれば追加
                                        if any(chrome_indicators[:2]):  # タイトルベースの判定のみ
                                            windows.append({
                                                'hwnd': hwnd,
                                                'title': window_title,
                                                'class': class_name,
                                                'process_id': 'unknown'
                                            })
                                            logger.debug(f"Chromeウィンドウ発見（プロセス確認失敗）: {window_title}")
                        
                        except Exception as e:
                            logger.debug(f"ウィンドウ列挙エラー: {e}")
                        
                        return True
                    
                    # Chromeウィンドウを検索
                    chrome_windows = []
                    win32gui.EnumWindows(enum_windows_callback, chrome_windows)
                    
                    if not chrome_windows:
                        logger.warning("Chromeウィンドウが見つかりません")
                        return False
                    
                    logger.info(f"{len(chrome_windows)}個のChromeウィンドウを発見")
                    
                    # 最適なChromeウィンドウを選択（最前面または最大のウィンドウ）
                    best_window = None
                    
                    for window in chrome_windows:
                        hwnd = window['hwnd']
                        
                        # ウィンドウの状態を確認
                        try:
                            window_rect = win32gui.GetWindowRect(hwnd)
                            is_minimized = win32gui.IsIconic(hwnd)
                            is_maximized = win32gui.IsZoomed(hwnd)
                            
                            # 最小化されていないウィンドウを優先
                            if not is_minimized:
                                if best_window is None:
                                    best_window = window
                                else:
                                    # より大きなウィンドウを選択
                                    best_rect = win32gui.GetWindowRect(best_window['hwnd'])
                                    current_area = (window_rect[2] - window_rect[0]) * (window_rect[3] - window_rect[1])
                                    best_area = (best_rect[2] - best_rect[0]) * (best_rect[3] - best_rect[1])
                                    
                                    if current_area > best_area:
                                        best_window = window
                            
                            logger.debug(f"ウィンドウ状態 - {window['title']}: 最小化={is_minimized}, 最大化={is_maximized}")
                        
                        except Exception as e:
                            logger.debug(f"ウィンドウ状態確認エラー: {e}")
                    
                    if best_window is None:
                        # 最小化されたウィンドウしかない場合は最初のものを使用
                        best_window = chrome_windows[0]
                        logger.info("最小化されたChromeウィンドウを使用")
                    
                    target_hwnd = best_window['hwnd']
                    target_title = best_window['title']
                    
                    logger.info(f"対象Chromeウィンドウ: {target_title}")
                    
                    # 段階的にウィンドウを前面に表示
                    success_steps = []
                    
                    # ステップ1: 最小化状態の解除
                    try:
                        if win32gui.IsIconic(target_hwnd):
                            win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                            success_steps.append("最小化解除")
                            time.sleep(0.2)
                    except Exception as e:
                        logger.debug(f"最小化解除エラー: {e}")
                    
                    # ステップ2: ウィンドウを表示
                    try:
                        win32gui.ShowWindow(target_hwnd, win32con.SW_SHOW)
                        success_steps.append("ウィンドウ表示")
                        time.sleep(0.1)
                    except Exception as e:
                        logger.debug(f"ウィンドウ表示エラー: {e}")
                    
                    # ステップ3: 前面に移動
                    try:
                        win32gui.SetForegroundWindow(target_hwnd)
                        success_steps.append("前面移動")
                        time.sleep(0.1)
                    except Exception as e:
                        logger.debug(f"前面移動エラー: {e}")
                    
                    # ステップ4: フォーカス設定
                    try:
                        win32gui.SetActiveWindow(target_hwnd)
                        success_steps.append("フォーカス設定")
                        time.sleep(0.1)
                    except Exception as e:
                        logger.debug(f"フォーカス設定エラー: {e}")
                    
                    # ステップ5: 最上位に配置
                    try:
                        win32gui.SetWindowPos(
                            target_hwnd,
                            win32con.HWND_TOP,
                            0, 0, 0, 0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                        )
                        success_steps.append("最上位配置")
                        time.sleep(0.1)
                    except Exception as e:
                        logger.debug(f"最上位配置エラー: {e}")
                    
                    # 成功確認
                    try:
                        foreground_hwnd = win32gui.GetForegroundWindow()
                        if foreground_hwnd == target_hwnd:
                            logger.info(f"✅ Chromeウィンドウの前面表示完了: {target_title}")
                            logger.info(f"成功した操作: {', '.join(success_steps)}")
                            return True
                        else:
                            foreground_title = win32gui.GetWindowText(foreground_hwnd)
                            logger.warning(f"前面表示未完了: 前面ウィンドウ='{foreground_title}'")
                            
                            # 部分的成功でもTrueを返す（何らかの操作は成功している）
                            if success_steps:
                                logger.info(f"部分的成功: {', '.join(success_steps)}")
                                return True
                            else:
                                return False
                    
                    except Exception as e:
                        logger.warning(f"成功確認エラー: {e}")
                        # 確認できない場合は成功と仮定（操作は実行された）
                        if success_steps:
                            logger.info(f"確認不可だが操作は実行: {', '.join(success_steps)}")
                            return True
                        else:
                            return False
                
                except ImportError:
                    logger.warning("win32guiが利用できません。pip install pywin32を実行してください")
                    return False
                except Exception as e:
                    logger.error(f"Windows環境でのChrome前面表示エラー: {e}")
                    return False
            
            # macOSの場合
            elif os.name == 'posix' and os.uname().sysname == 'Darwin':
                try:
                    logger.info("macOS環境でのChrome前面表示を試行")
                    
                    # AppleScriptを使用してChromeを前面に表示
                    applescript_commands = [
                        '''
                        tell application "Google Chrome"
                            activate
                            set frontmost to true
                        end tell
                        ''',
                        '''
                        tell application "System Events"
                            tell process "Google Chrome"
                                set frontmost to true
                            end tell
                        end tell
                        '''
                    ]
                    
                    for i, script in enumerate(applescript_commands):
                        try:
                            result = subprocess.run(
                                ['osascript', '-e', script],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            
                            if result.returncode == 0:
                                logger.info(f"✅ macOS Chrome前面表示成功 (方法{i+1})")
                                return True
                            else:
                                logger.debug(f"AppleScript方法{i+1}失敗: {result.stderr}")
                        
                        except subprocess.TimeoutExpired:
                            logger.debug(f"AppleScript方法{i+1}タイムアウト")
                        except Exception as e:
                            logger.debug(f"AppleScript方法{i+1}エラー: {e}")
                    
                    logger.warning("macOSでのChrome前面表示に失敗")
                    return False
                
                except Exception as e:
                    logger.error(f"macOS環境エラー: {e}")
                    return False
            
            # Linuxの場合
            elif os.name == 'posix':
                try:
                    logger.info("Linux環境でのChrome前面表示を試行")
                    
                    # xdotoolを使用
                    linux_commands = [
                        ['xdotool', 'search', '--name', 'chrome', 'windowactivate'],
                        ['xdotool', 'search', '--class', 'chrome', 'windowactivate'],
                        ['wmctrl', '-a', 'chrome'],
                        ['wmctrl', '-a', 'Chrome']
                    ]
                    
                    for i, cmd in enumerate(linux_commands):
                        try:
                            result = subprocess.run(
                                cmd,
                                capture_output=True,
                                text=True,
                                timeout=3
                            )
                            
                            if result.returncode == 0:
                                logger.info(f"✅ Linux Chrome前面表示成功 (方法{i+1})")
                                return True
                            else:
                                logger.debug(f"Linux方法{i+1}失敗: {result.stderr}")
                        
                        except FileNotFoundError:
                            logger.debug(f"コマンド未インストール: {cmd[0]}")
                        except subprocess.TimeoutExpired:
                            logger.debug(f"Linux方法{i+1}タイムアウト")
                        except Exception as e:
                            logger.debug(f"Linux方法{i+1}エラー: {e}")
                    
                    logger.warning("LinuxでのChrome前面表示に失敗")
                    return False
                
                except Exception as e:
                    logger.error(f"Linux環境エラー: {e}")
                    return False
            
            else:
                logger.warning(f"未対応のOS環境: {os.name}")
                return False
            
        except Exception as e:
            logger.error(f"Chromeウィンドウ前面表示の全般エラー: {e}")
            return False

    async def connect_to_existing_browser(self) -> bool:
        """
        既存のChromeに接続、なければ指定の設定（固定パス）で自動起動して接続
        """
        try:
            logger.info("Chromeへの接続を試みています...")
            
            playwright = await async_playwright().start()
            
            # --- フェーズ1: 既存のデバッグChromeへの接続試行 ---
            try:
                self.browser = await playwright.chromium.connect_over_cdp("http://localhost:9222")
                logger.info("✅ 既存のChromeブラウザに接続成功")
                
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                    return True
            except Exception:
                logger.info("既存のデバッグ用Chromeが見つかりません。設定を読み込んで自動起動します...")

            # --- フェーズ2: 指定設定でChromeを自動起動 ---
            # 固定パスを使用
            chrome_path = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
            
            if not os.path.exists(chrome_path):
                logger.error(f"❌ 指定されたパスにChromeが見つかりません: {chrome_path}")
                return False

            # [20260806] youtube_summary_list_*.py・各バッチファイルと同じプロファイル
            # フォルダに統一する。以前は Documents\ChromeDebugProfile という別フォルダを
            # 使っていたため、Chromeが未起動の状態でこのツールを単体起動すると、
            # 要約コード側とは別のプロファイル（別ログイン状態）でChromeが立ち上がっていた。
            user_data_dir = os.path.join(
                os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                "ChromeDebugProfile_20260725"
            )

            logger.info(f"Chromeを起動します: {chrome_path}")
            logger.info(f"プロファイル: {user_data_dir}")

            # 起動コマンド（BATファイルの内容に相当）
            cmd = [
                chrome_path,
                "--remote-debugging-port=9222",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                # [20260806] taskkill等で強制終了した直後に出る「ページを復元しますか？」
                # クラッシュ復元ダイアログを抑制する。
                "--disable-session-crashed-bubble",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
            
            try:
                subprocess.Popen(cmd)
            except Exception as e:
                logger.error(f"Chrome起動エラー: {e}")
                return False
            
            # 起動待ち
            print("⏳ Chromeを起動中です... (約5秒待機)")
            for i in range(5):
                await asyncio.sleep(1)
                print(".", end="", flush=True)
            print()

            # --- フェーズ3: 再接続試行 ---
            try:
                self.browser = await playwright.chromium.connect_over_cdp("http://localhost:9222")
                logger.info("✅ 自動起動したChromeに接続成功")
                
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                else:
                    self.context = await self.browser.new_context()
                
                return True
                
            except Exception as e:
                logger.error(f"❌ 自動起動後の接続に失敗しました: {e}")
                return False

        except Exception as e:
            logger.error(f"Playwright初期化エラー: {e}")
            return False

    async def refresh_page_safely(self, page) -> bool:
        """安全なページリロードとコンテキスト復旧"""
        try:
            logger.info("ページを安全にリフレッシュ中...")
            
            # 現在のURL保存
            current_url = page.url
            
            # リロード実行
            await page.reload(wait_until='domcontentloaded')
            
            # プレイリストパネルの復旧待機
            try:
                await page.wait_for_selector('#secondary ytd-playlist-panel-renderer', timeout=10000)
                await asyncio.sleep(self.get_dynamic_wait_time(1, 1.0))  # リフレッシュ後は少し長めに待機
            except Exception as e:
                logger.warning(f"プレイリストパネル復旧に時間がかかっています: {e}")
                await asyncio.sleep(2.0)
            
            # DOM参照のクリーンアップ
            self.cleanup_dom_references()
            
            # 統計更新
            self.stats['refresh_count'] += 1
            
            logger.info(f"ページリフレッシュ完了 (リフレッシュ回数: {self.stats['refresh_count']})")
            return True
            
        except Exception as e:
            logger.error(f"ページリフレッシュエラー: {e}")
            return False

    async def get_playlist_name_optimized(self, page) -> str:
        """動画ページの右側からプレイリスト名を取得（最適化版）"""
        try:
            logger.info("プレイリスト名を取得中...")
            
            # キャッシュされたセレクターを最初に試行
            if self.selector_cache.playlist_name_selector:
                try:
                    logger.debug(f"キャッシュされたセレクター試行: {self.selector_cache.playlist_name_selector}")
                    element = await page.query_selector(self.selector_cache.playlist_name_selector)
                    if element:
                        playlist_name = await element.text_content()
                        if playlist_name and playlist_name.strip():
                            clean_name = self.clean_video_title(playlist_name)
                            if clean_name:
                                logger.info(f"キャッシュからプレイリスト名取得: '{clean_name}'")
                                return clean_name
                except Exception as e:
                    logger.debug(f"キャッシュセレクターでエラー: {e}")
            
            # セレクターを効率順に並び替え（成功率の高い順）
            selectors = [
                '#secondary ytd-playlist-panel-renderer h3 a#wc-endpoint',
                '#secondary ytd-playlist-panel-renderer h3 span#container',
                'ytd-playlist-panel-renderer h3 a#wc-endpoint',
                '#secondary ytd-playlist-panel-renderer [id="title"] a',
                '#secondary ytd-playlist-panel-renderer h3 a',
                '#secondary ytd-playlist-panel-renderer h3.ytd-playlist-panel-renderer a#wc-endpoint',
                'ytd-playlist-panel-renderer h3 span#container',
                '#secondary ytd-playlist-panel-renderer h3.ytd-playlist-panel-renderer span#container',
                '#secondary ytd-playlist-panel-renderer [id="title"] span',
                '#secondary ytd-playlist-panel-renderer h3 span'
            ]
            
            for selector in selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        playlist_name = await element.text_content()
                        if playlist_name and playlist_name.strip():
                            clean_name = self.clean_video_title(playlist_name)
                            if clean_name:
                                # 成功したセレクターをキャッシュ
                                self.selector_cache.playlist_name_selector = selector
                                logger.info(f"プレイリスト名取得成功: '{clean_name}' (セレクター: {selector})")
                                return clean_name
                except Exception as e:
                    logger.debug(f"セレクター '{selector}' でエラー: {e}")
                    continue
            
            # フォールバック処理（簡略化）
            try:
                panel = await page.query_selector('#secondary ytd-playlist-panel-renderer')
                if panel:
                    h3_elements = await panel.query_selector_all('h3')
                    if h3_elements:
                        text = await h3_elements[0].text_content()
                        if text and text.strip():
                            clean_name = self.clean_video_title(text)
                            if clean_name:
                                logger.info(f"フォールバックでプレイリスト名取得: '{clean_name}'")
                                return clean_name
            except Exception as debug_e:
                logger.debug(f"フォールバック処理エラー: {debug_e}")
            
            logger.info("プレイリスト名を確認できませんでした")
            return "確認できませんでした"
            
        except Exception as e:
            logger.error(f"プレイリスト名取得エラー: {e}")
            return "確認できませんでした"

    async def get_current_video_position_in_playlist(self, page) -> tuple[int, str]:
        """現在の動画のプレイリスト内での位置と動画IDを取得"""
        try:
            logger.info("現在の動画のプレイリスト内位置を特定中...")
            
            # 現在のURLから動画IDを取得
            current_url = page.url
            current_video_id = self._extract_video_id_from_url(current_url)
            
            if not current_video_id:
                logger.error("現在のURLから動画IDを取得できませんでした")
                return -1, ""
            
            logger.info(f"現在の動画ID: {current_video_id}")
            
            # プレイリストパネルから全動画を取得して現在の動画を探す
            try:
                await page.wait_for_selector('#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer', timeout=5000)
            except Exception as e:
                logger.warning(f"プレイリスト動画要素の待機タイムアウト: {e}")
            
            video_elements = await page.query_selector_all('#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer')
            
            if not video_elements:
                logger.error("プレイリスト内の動画要素が見つかりませんでした")
                return -1, current_video_id
            
            logger.info(f"プレイリスト内動画数: {len(video_elements)}個")
            
            for index, element in enumerate(video_elements):
                try:
                    # 各動画のリンクから動画IDを取得
                    link_selectors = [
                        'a#wc-endpoint',
                        'a[href*="/watch"]',
                        '#video-title'
                    ]
                    
                    href = None
                    for selector in link_selectors:
                        try:
                            link_element = await element.query_selector(selector)
                            if link_element:
                                href = await link_element.get_attribute('href')
                                if href:
                                    break
                        except Exception:
                            continue
                    
                    if href:
                        video_id = self._extract_video_id_from_url(href)
                        
                        if video_id == current_video_id:
                            logger.info(f"現在の動画を発見: プレイリスト内位置 {index + 1}番目")
                            return index, current_video_id
                        
                except Exception as e:
                    logger.debug(f"動画要素 {index + 1} の処理エラー: {e}")
                    continue
            
            logger.warning("現在の動画の位置をプレイリスト内で特定できませんでした")
            return -1, current_video_id
            
        except Exception as e:
            logger.error(f"現在の動画位置取得エラー: {e}")
            return -1, ""

    def _extract_video_id_from_url(self, url: str) -> str:
        """URLから動画IDを抽出"""
        if not url:
            return ""
        
        try:
            import re
            match = re.search(r'v=([^&]+)', url)
            return match.group(1) if match else ""
        except Exception as e:
            logger.debug(f"動画ID抽出エラー: {e}")
            return ""

    async def get_youtube_tabs(self) -> List[dict]:
        """YouTubeタブの一覧を取得（ナビゲーション中ページ対応版）"""
        try:
            logger.info("YouTubeタブを検索中...")
            youtube_tabs = []
            
            pages = self.context.pages
            logger.info(f"全タブ数: {len(pages)}個")
            
            for i, page in enumerate(pages):
                try:
                    # ページの基本的な有効性チェック
                    try:
                        is_closed = page.is_closed()
                        if is_closed:
                            logger.debug(f"タブ {i+1}: ページが閉じられています")
                            continue
                    except Exception as e:
                        logger.debug(f"タブ {i+1}: ページ状態確認エラー: {e}")
                        continue
                    
                    # URLを安全に取得
                    try:
                        url = page.url
                        if not url:
                            logger.debug(f"タブ {i+1}: URLが空です")
                            continue
                    except Exception as e:
                        logger.debug(f"タブ {i+1}: URL取得エラー: {e}")
                        continue
                    
                    logger.debug(f"タブ {i+1}: {url}")
                    
                    # watchページとplaylistページの両方を対象にする
                    if url.startswith("https://www.youtube.com/watch") or url.startswith("https://www.youtube.com/playlist"):
                        # ナビゲーション中でもタブ情報を取得（待機 + リトライ方式）
                        title = await self._get_page_title_with_retry(page, i+1)
                        playlist_name = await self._get_playlist_name_with_retry(page, i+1)
                        
                        # playlistページの場合、プレイリストIDから名前を取得
                        if url.startswith("https://www.youtube.com/playlist"):
                            import re
                            playlist_match = re.search(r'list=([^&]+)', url)
                            if playlist_match:
                                playlist_id = playlist_match.group(1)
                                # プレイリストIDから名前をマッピング
                                name_mapping = {
                                    "PL0UGJjoPnxKjT1ClcCwngoCDhModNIG3H": "プレイリストS",
                                    "PL0UGJjoPnxKgphke6I63QVyHeToWaNSTD": "プレイリストA",
                                    "PL0UGJjoPnxKhM3jXPMhNxONyvyZbClDuM": "プレイリストB",
                                    "PL0UGJjoPnxKj6T0VlBmyxVqVmBIK1h3G6": "プレイリストN",
                                    "PL0UGJjoPnxKhX6NN6K5GSPCzh9H8bK1F3": "プレイリストM",
                                }
                                playlist_name = name_mapping.get(playlist_id, f"プレイリスト({playlist_id[:10]}...)")
                        
                        youtube_tabs.append({
                            'index': i,
                            'page': page,
                            'url': url,
                            'title': title,
                            'playlist_name': playlist_name
                        })
                        
                        if url.startswith("https://www.youtube.com/watch"):
                            logger.info(f"  -> YouTube動画タブ発見: {title}")
                        else:
                            logger.info(f"  -> YouTubeプレイリストタブ発見: {playlist_name}")
                        logger.info(f"  -> プレイリスト名: {playlist_name}")
                        
                except Exception as e:
                    logger.warning(f"タブ {i+1} の情報取得エラー: {e}")
                    continue
            
            logger.info(f"YouTubeタブ合計: {len(youtube_tabs)}個")
            
            # YouTubeタブが見つからない場合の詳細情報
            if len(youtube_tabs) == 0:
                logger.warning("YouTubeタブが見つかりませんでした。以下を確認してください:")
                logger.warning("1. Chromeで YouTube動画またはプレイリストページを開いているか")
                logger.warning("2. URLが https://www.youtube.com/watch または https://www.youtube.com/playlist で始まっているか")
                logger.warning("3. ページの読み込みが完了するまで少し待ってから再実行してください")
                
                # デバッグ用：全タブのURLを表示
                try:
                    for i, page in enumerate(pages):
                        try:
                            debug_url = page.url
                            logger.info(f"デバッグ - タブ {i+1}: {debug_url}")
                        except Exception:
                            logger.info(f"デバッグ - タブ {i+1}: URL取得不可")
                except Exception as debug_e:
                    logger.debug(f"デバッグ情報取得エラー: {debug_e}")
            
            return youtube_tabs
            
        except Exception as e:
            logger.error(f"YouTubeタブ取得エラー: {e}")
            return []
            
    async def _get_page_title_with_retry(self, page, tab_number: int) -> str:
        """ページタイトルを安全に取得（リトライ対応）"""
        try:
            # 最初は短いタイムアウトで試行
            try:
                title = await asyncio.wait_for(page.title(), timeout=2.0)
                if title:
                    return title
            except asyncio.TimeoutError:
                logger.info(f"タブ {tab_number}: ページ読み込み中のため少し待機します...")
            
            # ナビゲーション完了を待機（最大10秒）
            try:
                await asyncio.wait_for(
                    page.wait_for_load_state('domcontentloaded'), 
                    timeout=10.0
                )
                logger.info(f"タブ {tab_number}: ページ読み込み完了")
            except asyncio.TimeoutError:
                logger.warning(f"タブ {tab_number}: ページ読み込みがタイムアウト")
            
            # 再度タイトル取得を試行
            try:
                title = await asyncio.wait_for(page.title(), timeout=3.0)
                return title if title else "タイトル取得できませんでした"
            except Exception as e:
                logger.warning(f"タブ {tab_number}: タイトル取得最終試行失敗: {e}")
                return "読み込み中..."
                
        except Exception as e:
            logger.warning(f"タブ {tab_number}: タイトル取得エラー: {e}")
            return "タイトル取得エラー"
    
    async def _get_playlist_name_with_retry(self, page, tab_number: int) -> str:
        """プレイリスト名を安全に取得（リトライ対応）"""
        try:
            # 最初は短いタイムアウトで試行
            try:
                playlist_name = await asyncio.wait_for(
                    self.get_playlist_name_optimized(page), 
                    timeout=3.0
                )
                if playlist_name and playlist_name != "確認できませんでした":
                    return playlist_name
            except asyncio.TimeoutError:
                logger.info(f"タブ {tab_number}: プレイリスト情報読み込み中...")
            
            # 少し待機してから再試行
            await asyncio.sleep(2.0)
            
            try:
                playlist_name = await asyncio.wait_for(
                    self.get_playlist_name_optimized(page), 
                    timeout=5.0
                )
                return playlist_name
            except Exception as e:
                logger.warning(f"タブ {tab_number}: プレイリスト名取得最終試行失敗: {e}")
                return "読み込み中..."
                
        except Exception as e:
            logger.warning(f"タブ {tab_number}: プレイリスト名取得エラー: {e}")
            return "確認できませんでした"

    async def execute_batch_deletion(self, page, start_position: int, total_delete_count: int, delete_all: bool = False) -> dict:
        """バッチ処理による動画削除（メイン制御関数）"""
        try:
            logger.info(f"バッチ削除開始: 位置{start_position + 1}から{total_delete_count}件を削除")
            
            # バッチ計算
            batch_size = self.batch_config.batch_size
            total_batches = (total_delete_count + batch_size - 1) // batch_size
            
            self.print_section_header(f"バッチ削除モード開始 ({total_batches}バッチ構成)")
            print(f"🎯 総削除件数: {total_delete_count}件")
            print(f"📦 バッチサイズ: {batch_size}件/バッチ")
            print(f"🔄 総バッチ数: {total_batches}バッチ")
            
            total_deleted = 0
            batch_start_time = time.time()
            
            # 静かなモードを有効化（バッチ処理中は簡潔な表示）
            self.set_quiet_mode(True)
            
            for batch_num in range(1, total_batches + 1):
                if self.cancel_operation:
                    print(f"\n⚠️ バッチ {batch_num}: ユーザーによりキャンセルされました")
                    break
                
                # バッチ開始
                batch_start = time.time()
                remaining_items = total_delete_count - total_deleted
                current_batch_size = min(batch_size, remaining_items)
                
                print(f"\n📦 バッチ {batch_num}/{total_batches} 開始 ({current_batch_size}件)")
                
                # ヘルスチェック
                if batch_num % self.health_check_interval == 0:
                    health_info = self.check_browser_health()
                    self.print_resource_status(health_info)
                    
                    if health_info['recommendation'] == 'refresh_needed':
                        print("🔄 メモリ使用量が多いため、ページをリフレッシュします")
                        refresh_success = await self.refresh_page_safely(page)
                        if not refresh_success:
                            logger.warning("ページリフレッシュに失敗しました")
                
                # バッチ内削除処理
                batch_deleted = await self._execute_single_batch(
                    page, start_position, current_batch_size, delete_all, batch_num
                )
                
                total_deleted += batch_deleted
                batch_elapsed = time.time() - batch_start
                
                # バッチ結果表示
                self.print_batch_summary(batch_num, batch_deleted, current_batch_size, batch_elapsed)
                
                # バッチ間のクリーンアップとリフレッシュ判定
                self.cleanup_dom_references()
                
                # 定期的なページリフレッシュ
                if batch_num % self.batch_config.refresh_interval == 0 and batch_num < total_batches:
                    print("🔄 定期リフレッシュを実行中...")
                    await self.refresh_page_safely(page)
                
                # バッチ間待機
                if batch_num < total_batches:
                    inter_batch_wait = self.get_dynamic_wait_time(batch_num, 0.5)
                    await asyncio.sleep(inter_batch_wait)
                
                # 統計更新
                self.stats['batch_count'] += 1
                
                # 全削除モードの場合、残り動画数チェック
                if delete_all and batch_deleted == current_batch_size:
                    remaining_videos = await self.count_remaining_videos(page)
                    if remaining_videos == 0:
                        print("✅ 全動画削除完了（プレイリストが空になりました）")
                        break
            
            # 最終結果
            total_elapsed = time.time() - batch_start_time
            
            # 静かなモードを解除
            self.set_quiet_mode(False)
            
            self.print_final_summary(total_deleted, total_delete_count, total_elapsed)
            
            return {
                'success': total_deleted > 0,
                'deleted_count': total_deleted,
                'all_deleted': delete_all and await self.count_remaining_videos(page) == 0,
                'batch_count': self.stats['batch_count']
            }
            
        except Exception as e:
            logger.error(f"バッチ削除処理エラー: {e}")
            self.set_quiet_mode(False)
            return {
                'success': False,
                'deleted_count': 0,
                'all_deleted': False,
                'batch_count': self.stats['batch_count']
            }

    async def _execute_single_batch(self, page, start_position: int, batch_size: int, delete_all: bool, batch_num: int) -> int:
        """単一バッチの削除処理"""
        try:
            batch_deleted = 0
            consecutive_failures = 0
            max_failures = 3
            
            for item_num in range(1, batch_size + 1):
                if self.cancel_operation:
                    break
                
                # プログレス表示
                progress = self.show_batch_progress(batch_num, self.stats['batch_count'] + 1, item_num, batch_size)
                print(f"\r{progress}", end="", flush=True)
                
                # 現在の動画数を取得
                current_video_count = await self.count_remaining_videos(page)
                if current_video_count == 0:
                    print("\n✅ プレイリストが空になりました")
                    break
                
                # 削除実行（常に先頭要素を削除）
                deletion_success = await self._delete_first_video_with_enhanced_safety(page)
                
                if deletion_success:
                    batch_deleted += 1
                    consecutive_failures = 0
                    self.stats['total_processed'] += 1
                    
                    # 動的待機時間
                    wait_time = self.get_dynamic_wait_time(self.stats['total_processed'])
                    await asyncio.sleep(wait_time)
                    
                else:
                    consecutive_failures += 1
                    logger.warning(f"バッチ{batch_num} 項目{item_num}: 削除失敗 (連続失敗: {consecutive_failures})")
                    
                    if consecutive_failures >= max_failures:
                        logger.error(f"バッチ{batch_num}: 連続{max_failures}回失敗のため中断")
                        break
                    
                    # 失敗時は少し長めに待機
                    await asyncio.sleep(self.get_dynamic_wait_time(consecutive_failures, 1.0))
            
            print()  # 改行
            return batch_deleted
            
        except Exception as e:
            logger.error(f"単一バッチ実行エラー: {e}")
            return batch_deleted

    async def _delete_first_video_with_enhanced_safety(self, page) -> bool:
        """先頭動画の安全な削除（拡張安全機能付き）"""
        try:
            # DOM要素を新規取得（キャッシュ使用禁止）
            video_elements = await page.query_selector_all('#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer')
            
            if not video_elements:
                logger.warning("削除対象の動画要素が見つかりません")
                return False
            
            first_video = video_elements[0]
            
            # 要素の有効性確認
            try:
                is_connected = await first_video.evaluate('el => el.isConnected')
                if not is_connected:
                    logger.warning("先頭動画要素がDOM上に存在しません")
                    return False
            except Exception as e:
                logger.warning(f"要素有効性確認エラー: {e}")
                return False
            
            # タイトル取得（ログ用）
            try:
                element_text = await first_video.text_content()
                clean_title = self.clean_video_title(element_text)
            except Exception:
                clean_title = "タイトル取得不可"
            
            if not self.quiet_mode:
                logger.info(f"削除対象: {clean_title}")
            
            # メニューボタンの検索と操作
            menu_clicked = await self._click_menu_button_safe(first_video)
            if not menu_clicked:
                logger.error("メニューボタンのクリックに失敗")
                return False
            
            # メニュー開放待機
            menu_opened = await self.wait_for_menu_open(page, timeout=3000)
            if not menu_opened:
                logger.warning("メニューが開かない可能性があります")
            
            # 削除メニューの検索と操作
            remove_clicked = await self._click_remove_menu_safe(page)
            if not remove_clicked:
                logger.error("削除メニューのクリックに失敗")
                return False
            
            # 削除完了待機
            deletion_completed = await self.wait_for_deletion_completion(page, len(video_elements), timeout=4000)
            
            if not deletion_completed:
                # フォールバック: 固定待機
                await asyncio.sleep(self.get_dynamic_wait_time(1, 0.6))
            
            # DOM参照解放
            first_video = None
            video_elements = None
            
            return True
            
        except Exception as e:
            logger.error(f"先頭動画削除エラー: {e}")
            return False

    async def _click_menu_button_safe(self, video_element) -> bool:
        """メニューボタンの安全なクリック"""
        try:
            # キャッシュされたセレクターを優先使用
            menu_button = None
            
            if self.selector_cache.menu_button_selector:
                try:
                    menu_button = await video_element.query_selector(self.selector_cache.menu_button_selector)
                    if menu_button and await menu_button.is_visible():
                        await menu_button.click()
                        return True
                except Exception as e:
                    logger.debug(f"キャッシュメニューボタンクリックエラー: {e}")
            
            # 標準セレクターで検索
            menu_selectors = [
                'ytd-menu-renderer button',
                'button[aria-label*="アクション"]',
                'button#button',
                'button[aria-label*="Action"]',
                'button[aria-label*="menu"]'
            ]
            
            for selector in menu_selectors:
                try:
                    menu_button = await video_element.query_selector(selector)
                    if menu_button and await menu_button.is_visible():
                        await menu_button.click()
                        # 成功したセレクターをキャッシュ
                        self.selector_cache.menu_button_selector = selector
                        return True
                except Exception as e:
                    logger.debug(f"メニューボタンセレクター '{selector}' でエラー: {e}")
                    continue
            
            return False
            
        except Exception as e:
            logger.error(f"メニューボタンクリックエラー: {e}")
            return False

    async def _click_remove_menu_safe(self, page) -> bool:
        """削除メニューの安全なクリック"""
        try:
            # キャッシュされたセレクターを優先使用
            if self.selector_cache.remove_button_selector:
                try:
                    if self.selector_cache.remove_button_selector.startswith('text='):
                        remove_button = await page.wait_for_selector(self.selector_cache.remove_button_selector, timeout=1000)
                    else:
                        remove_button = await page.query_selector(self.selector_cache.remove_button_selector)
                    
                    if remove_button:
                        await remove_button.click()
                        return True
                except Exception as e:
                    logger.debug(f"キャッシュ削除ボタンクリックエラー: {e}")
            
            # 標準セレクターで検索
            remove_selectors = [
                'text="再生リストから削除"',
                'text="プレイリストから削除"', 
                'text="から削除"',
                'text="Remove from playlist"',
                '[aria-label*="削除"]',
                '[aria-label*="Remove"]'
            ]
            
            for selector in remove_selectors:
                try:
                    if selector.startswith('text='):
                        remove_button = await page.wait_for_selector(selector, timeout=800)
                    else:
                        remove_button = await page.query_selector(selector)
                    
                    if remove_button:
                        await remove_button.click()
                        # 成功したセレクターをキャッシュ
                        self.selector_cache.remove_button_selector = selector
                        return True
                except Exception as e:
                    logger.debug(f"削除メニューセレクター '{selector}' でエラー: {e}")
                    continue
            
            # フォールバック: テキスト検索
            try:
                menu_items = await page.query_selector_all(
                    '[role="menuitem"], ytd-menu-service-item-renderer, .style-scope.ytd-menu-service-item-renderer'
                )
                
                for item in menu_items:
                    try:
                        text = await item.text_content()
                        if text and any(keyword in text for keyword in ["から削除", "再生リストから削除", "Remove from", "削除"]):
                            await item.click()
                            return True
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"フォールバック削除メニュー検索エラー: {e}")
            
            return False
            
        except Exception as e:
            logger.error(f"削除メニュークリックエラー: {e}")
            return False

    async def count_remaining_videos(self, page) -> int:
        """残りの動画数をカウント（キャッシュ無効化版）"""
        try:
            # 短時間待機
            await asyncio.sleep(0.1)
            
            # 毎回新規取得（キャッシュ無効化）
            video_elements = await page.query_selector_all('#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer')
            count = len(video_elements)
            
            # DOM参照解放
            video_elements = None
            
            return count
        except Exception as e:
            logger.error(f"残り動画数カウントエラー: {e}")
            return 0

    async def wait_for_deletion_completion(self, page, expected_count: int, timeout: int = 4000) -> bool:
        """削除完了を動的に待機（緩和版）"""
        try:
            selector = self.selector_cache.video_count_selector or '#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer'
            
            start_time = asyncio.get_event_loop().time()
            check_interval = 0.2  # 50ms -> 200msに緩和
            
            while True:
                try:
                    elements = await page.query_selector_all(selector)
                    current_count = len(elements)
                    elements = None  # DOM参照解放
                    
                    # expected_countより少なくなったら削除完了
                    if current_count < expected_count:
                        logger.debug(f"削除完了を検知: {expected_count} -> {current_count}")
                        return True
                    
                    # タイムアウトチェック
                    elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
                    if elapsed > timeout:
                        logger.debug(f"削除完了の待機がタイムアウト ({elapsed:.0f}ms)")
                        return False
                    
                    await asyncio.sleep(check_interval)
                    
                except Exception as e:
                    logger.debug(f"削除検知中のエラー: {e}")
                    await asyncio.sleep(check_interval)
                
        except Exception as e:
            logger.debug(f"削除完了待機エラー: {e}")
            return False

    async def wait_for_menu_open(self, page, timeout: int = 3000) -> bool:
        """メニューが開くまで動的に待機（緩和版）"""
        try:
            menu_selectors = [
                '[role="menu"]',
                'ytd-menu-popup-renderer',
                'tp-yt-paper-listbox',
                '.ytd-menu-popup-renderer'
            ]
            
            start_time = asyncio.get_event_loop().time()
            check_interval = 0.1  # 50ms -> 100msに緩和
            
            while True:
                for selector in menu_selectors:
                    try:
                        element = await page.query_selector(selector)
                        if element and await element.is_visible():
                            logger.debug(f"メニュー開放を確認: {selector}")
                            return True
                    except Exception:
                        continue
                
                # タイムアウトチェック
                elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
                if elapsed > timeout:
                    logger.debug(f"メニュー開放待機がタイムアウト ({elapsed:.0f}ms)")
                    return False
                
                await asyncio.sleep(check_interval)
                
        except Exception as e:
            logger.debug(f"メニュー開放待機エラー: {e}")
            return False


    async def delete_playlist_videos_simple(self, page, playlist_name: str) -> bool:
        """シンプルな個別削除ループ（全選択不要版）- 右側パネルから順次削除"""
        try:
            logger.info(f"{playlist_name} の動画削除を開始（個別削除方式）")
            print(f"\n🗑️ {playlist_name} の動画を個別削除中...")
            
            deleted_count = 0
            consecutive_failures = 0
            max_failures = 3
            start_time = time.time()
            
            while True:
                if self.cancel_operation:
                    logger.info("ユーザーによりキャンセルされました")
                    break
                
                # 右側パネルの動画数を確認
                video_elements = await page.query_selector_all(
                    '#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer'
                )
                
                if not video_elements or len(video_elements) == 0:
                    logger.info(f"{playlist_name} のすべての動画を削除しました")
                    print(f"✅ {playlist_name} の全動画削除完了（{deleted_count}個削除）")
                    return True
                
                current_video_count = len(video_elements)
                logger.info(f"残り動画数: {current_video_count}個")
                
                # 最初の動画要素を取得
                first_video = video_elements[0]
                
                # タイトル取得（ログ用）
                try:
                    title_element = await first_video.query_selector('#video-title')
                    if title_element:
                        video_title = await title_element.text_content()
                        clean_title = self.clean_video_title(video_title)
                    else:
                        clean_title = "タイトル不明"
                except Exception:
                    clean_title = "タイトル取得失敗"
                
                # メニューボタンをクリック
                menu_success = False
                menu_selectors = [
                    'ytd-menu-renderer button',
                    'button[aria-label*="アクション"]',
                    'button#button',
                    'yt-icon-button#button',
                    'button.yt-icon-button',
                    '[aria-label="その他の操作"]'
                ]
                
                for selector in menu_selectors:
                    try:
                        menu_button = await first_video.query_selector(selector)
                        if menu_button and await menu_button.is_visible():
                            await menu_button.click()
                            menu_success = True
                            logger.debug(f"メニューボタンクリック成功: {selector}")
                            break
                    except Exception as e:
                        logger.debug(f"メニューボタンセレクタ {selector} 失敗: {e}")
                        continue
                
                if not menu_success:
                    consecutive_failures += 1
                    logger.warning(f"メニューボタンのクリック失敗（連続失敗: {consecutive_failures}）")
                    
                    if consecutive_failures >= max_failures:
                        logger.error("連続失敗のため中断")
                        break
                    
                    await asyncio.sleep(1.0)
                    continue
                
                # メニュー表示待機
                await asyncio.sleep(0.5)
                
                # 削除メニューをクリック
                remove_success = False
                remove_selectors = [
                    'text="再生リストから削除"',
                    'text="プレイリストから削除"',
                    'text="から削除"',
                    'text="Remove from playlist"',
                    '[aria-label*="削除"]'
                ]
                
                for selector in remove_selectors:
                    try:
                        if selector.startswith('text='):
                            remove_button = await page.wait_for_selector(selector, timeout=2000)
                        else:
                            remove_button = await page.query_selector(selector)
                        
                        if remove_button:
                            await remove_button.click()
                            remove_success = True
                            logger.debug(f"削除メニュークリック成功: {selector}")
                            break
                    except Exception as e:
                        logger.debug(f"削除メニューセレクタ {selector} 失敗: {e}")
                        continue
                
                if remove_success:
                    deleted_count += 1
                    consecutive_failures = 0
                    
                    # 進捗表示
                    elapsed = time.time() - start_time
                    avg_time = elapsed / deleted_count if deleted_count > 0 else 0
                    estimated_remaining = avg_time * (current_video_count - 1)
                    
                    print(f"  [{deleted_count}個削除済] {clean_title[:30]}... (残り約{estimated_remaining:.1f}秒)")
                    logger.info(f"削除成功 [{deleted_count}]: {clean_title}")
                    
                    # 動的待機時間
                    wait_time = self.get_dynamic_wait_time(deleted_count)
                    await asyncio.sleep(wait_time)
                    
                else:
                    consecutive_failures += 1
                    logger.warning(f"削除メニューのクリック失敗（連続失敗: {consecutive_failures}）")
                    
                    if consecutive_failures >= max_failures:
                        logger.error("連続失敗のため中断")
                        break
                    
                    # エラー時はメニューを閉じる試行
                    try:
                        await page.keyboard.press('Escape')
                    except:
                        pass
                    
                    await asyncio.sleep(1.0)
            
            # 最終結果
            elapsed_total = time.time() - start_time
            if deleted_count > 0:
                print(f"\n✅ {playlist_name} 処理完了:")
                print(f"  - 削除数: {deleted_count}個")
                print(f"  - 処理時間: {elapsed_total:.1f}秒")
                print(f"  - 平均処理時間: {elapsed_total/deleted_count:.1f}秒/個")
                logger.info(f"{playlist_name} の削除完了: {deleted_count}個削除")
            else:
                print(f"\n⚠️ {playlist_name} で動画を削除できませんでした")
                logger.warning(f"{playlist_name} で動画を削除できませんでした")
            
            return deleted_count > 0
            
        except Exception as e:
            logger.error(f"個別削除処理エラー: {e}")
            print(f"❌ エラーが発生しました: {e}")
            return False


    async def delete_videos_from_position(self, page, start_position: int, delete_count: int, delete_all: bool = False) -> dict:
        """指定位置から動画を削除（バッチ処理版）"""
        try:
            if delete_all:
                logger.info(f"全削除モード（位置{start_position + 1}から最後まで）で動画削除開始")
                
                # 全削除の場合は、スキップ + バッチ削除の組み合わせ
                if start_position > 0:
                    # フェーズ1: 指定位置までスキップ（先頭削除を利用）
                    logger.info(f"=== フェーズ1: 位置 {start_position + 1} までスキップ開始 ===")
                    
                    skip_result = await self.execute_batch_deletion(page, 0, start_position, False)
                    
                    if not skip_result['success']:
                        logger.error("スキップフェーズに失敗したため、削除処理を中止します")
                        return {
                            'success': False,
                            'deleted_count': 0,
                            'all_deleted': False
                        }
                    
                    logger.info(f"=== フェーズ1完了: {start_position}個の動画をスキップ ===")
                
                # フェーズ2: 残りを全削除
                total_videos = await self.count_remaining_videos(page)
                remaining_delete_count = total_videos
                
                logger.info(f"=== フェーズ2: 残り全削除開始（{remaining_delete_count}件） ===")
                
                delete_result = await self.execute_batch_deletion(page, 0, remaining_delete_count, True)
                
                # 結果の統合
                total_processed = start_position + delete_result['deleted_count']
                
                return {
                    'success': delete_result['success'],
                    'deleted_count': total_processed,
                    'all_deleted': delete_result['all_deleted']
                }
                
            else:
                # 部分削除の場合
                logger.info(f"部分削除モード（位置{start_position + 1}から{delete_count}件）で動画削除開始")
                
                if start_position > 0:
                    # フェーズ1: 指定位置までスキップ
                    logger.info(f"=== フェーズ1: 位置 {start_position + 1} までスキップ開始 ===")
                    
                    skip_result = await self.execute_batch_deletion(page, 0, start_position, False)
                    
                    if not skip_result['success']:
                        logger.error("スキップフェーズに失敗したため、削除処理を中止します")
                        return {
                            'success': False,
                            'deleted_count': 0,
                            'all_deleted': False
                        }
                    
                    logger.info(f"=== フェーズ1完了: {start_position}個の動画をスキップ ===")
                
                # フェーズ2: 指定件数を削除
                logger.info(f"=== フェーズ2: 部分削除開始（{delete_count}件） ===")
                
                delete_result = await self.execute_batch_deletion(page, 0, delete_count, False)
                
                # 結果の統合
                total_processed = start_position + delete_result['deleted_count']
                
                return {
                    'success': delete_result['success'],
                    'deleted_count': delete_result['deleted_count'],  # 実際の削除数のみ
                    'all_deleted': False
                }
                
        except Exception as e:
            logger.error(f"位置指定削除処理エラー（バッチ版）: {e}")
            return {
                'success': False,
                'deleted_count': 0,
                'all_deleted': False
            }


    async def count_playlist_videos_optimized(self, page) -> int:
        """動画ページのプレイリストパネルから動画数をカウント（最適化版）"""
        try:
            logger.info("プレイリスト内の動画数をカウント開始")
            
            # まず空プレイリストかどうかを早期検出
            is_empty = await self.detect_empty_playlist_message(page)
            if is_empty:
                logger.info("空プレイリストメッセージを検出: 動画数0として返却")
                return 0
            
            # キャッシュされたセレクターを最初に試行
            if self.selector_cache.video_count_selector:
                try:
                    elements = await page.query_selector_all(self.selector_cache.video_count_selector)
                    if elements:
                        video_count = len(elements)
                        elements = None  # DOM参照解放
                        logger.info(f"キャッシュからビデオカウント取得: {video_count}個")
                        return video_count
                except Exception as e:
                    logger.debug(f"キャッシュセレクターでエラー: {e}")
            
            # 特定要素の出現を待機（networkidleより効率的）
            try:
                await page.wait_for_selector('#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer', timeout=8000)
            except Exception as e:
                logger.warning(f"プレイリスト動画要素の待機タイムアウト: {e}")
            
            # セレクターを効率順に並び替え
            selectors = [
                '#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer',
                'ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer',
                '#secondary ytd-playlist-panel-renderer [data-index]',
                'ytd-playlist-panel-renderer [data-index]'
            ]
            
            video_count = 0
            
            for selector in selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        video_count = len(elements)
                        elements = None  # DOM参照解放
                        # 成功したセレクターをキャッシュ
                        self.selector_cache.video_count_selector = selector
                        logger.info(f"セレクター '{selector}' で {video_count} 個の動画を発見")
                        break
                except Exception as e:
                    logger.debug(f"セレクター '{selector}' でエラー: {e}")
                    continue
            
            if video_count == 0:
                logger.warning("動画が見つかりません。少し待ってから再試行...")
                
                # 短時間待機してから再試行
                await asyncio.sleep(1.5)
                elements = await page.query_selector_all('#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer')
                video_count = len(elements)
                elements = None  # DOM参照解放
                
                if video_count == 0:
                    # デバッグ用：パネルの存在確認
                    panel = await page.query_selector('#secondary ytd-playlist-panel-renderer')
                    if panel:
                        logger.info("プレイリストパネルは存在しますが、動画要素が見つかりません")
                    else:
                        logger.warning("プレイリストパネル自体が見つかりません")
            
            logger.info(f"プレイリスト内動画数: {video_count}個")
            return video_count
            
        except Exception as e:
            logger.error(f"動画数カウントエラー: {e}")
            return 0


    async def detect_empty_playlist_message(self, page) -> bool:
        """日本語の空プレイリストメッセージを検出（誤検出防止版）"""
        try:
            logger.debug("空プレイリストメッセージの検出開始")
            
            # まず実際に動画要素が存在するかチェック（最優先）
            video_element_selectors = [
                '#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer',
                'ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer',
                'ytd-playlist-video-renderer',
                '#contents ytd-playlist-video-renderer'
            ]
            
            for video_selector in video_element_selectors:
                try:
                    video_elements = await page.query_selector_all(video_selector)
                    if video_elements and len(video_elements) > 0:
                        video_elements = None  # DOM参照解放
                        logger.debug(f"動画要素が存在するため空プレイリストではありません: {len(video_elements)}個")
                        return False
                except Exception:
                    continue
            
            # 動画要素が見つからない場合のみ空メッセージ検出を実行
            logger.debug("動画要素が見つからないため、空メッセージの詳細検出を開始")
            
            # 日本語の空プレイリストメッセージパターン（具体的なセレクタのみ）
            specific_empty_selectors = [
                'text="この再生リストには動画がありません"',
                'text="動画がありません"',
                'text="再生リスト・非公開・動画はありません"',
                '[aria-label*="動画がありません"]',
                '[aria-label*="この再生リストには動画がありません"]'
            ]
            
            # 短いタイムアウトで具体的なメッセージを検索
            for selector in specific_empty_selectors:
                try:
                    element = await page.wait_for_selector(selector, timeout=1000)
                    if element:
                        # 要素が実際に表示されているかも確認
                        is_visible = await element.is_visible()
                        if is_visible:
                            logger.info(f"具体的な空プレイリストメッセージを検出: {selector}")
                            return True
                except Exception:
                    continue
            
            # より限定的な空状態専用コンテナでのテキスト検索
            limited_empty_containers = [
                '.empty-state',
                '[data-empty="true"]',
                '.ytd-playlist-video-list-renderer[empty]',
                '#contents .empty-message'
            ]
            
            for container_selector in limited_empty_containers:
                try:
                    container = await page.query_selector(container_selector)
                    if container:
                        text_content = await container.text_content()
                        if text_content:
                            empty_keywords = [
                                "この再生リストには動画がありません",
                                "動画がありません",
                                "再生リスト・非公開・動画はありません"
                            ]
                            
                            for keyword in empty_keywords:
                                if keyword in text_content:
                                    logger.info(f"限定コンテナから空メッセージを検出: '{keyword}' in {container_selector}")
                                    return True
                except Exception:
                    continue
            
            # 最終手段：プレイリストパネル内の限定的なテキスト検索
            try:
                playlist_panel = await page.query_selector('#secondary ytd-playlist-panel-renderer')
                if playlist_panel:
                    panel_text = await playlist_panel.text_content()
                    if panel_text:
                        # より厳密な判定：空メッセージがあり、かつ動画タイトルらしいテキストがない
                        empty_keywords = [
                            "この再生リストには動画がありません",
                            "動画がありません"
                        ]
                        
                        # 動画の存在を示すキーワード（これがあれば空ではない）
                        video_indicators = [
                            "再生中",
                            "分前",
                            "時間前", 
                            "日前",
                            "週間前",
                            "か月前",
                            "年前",
                            "チャンネル",
                            "視聴回数"
                        ]
                        
                        has_empty_message = any(keyword in panel_text for keyword in empty_keywords)
                        has_video_indicators = any(indicator in panel_text for indicator in video_indicators)
                        
                        if has_empty_message and not has_video_indicators:
                            logger.info("プレイリストパネル内で空メッセージを検出（動画インジケーターなし）")
                            return True
                        elif has_empty_message and has_video_indicators:
                            logger.debug("空メッセージがあるが動画インジケーターも存在するため、空ではないと判定")
                            return False
                
            except Exception as e:
                logger.debug(f"プレイリストパネル検索エラー: {e}")
            
            logger.debug("空プレイリストメッセージは検出されませんでした")
            return False
            
        except Exception as e:
            logger.debug(f"空プレイリストメッセージ検出エラー: {e}")
            return False




    async def count_playlist_videos_in_playlist_page(self, page) -> int:
        """プレイリストページ専用の動画カウント"""
        try:
            logger.info("プレイリストページの動画数をカウント開始")
            
            # 早期空検出
            is_empty = await self.detect_empty_playlist_message(page)
            if is_empty:
                logger.info("プレイリストページで空メッセージを検出: 動画数0として返却")
                return 0
            
            # プレイリストページ専用のセレクタ
            selectors = [
                'ytd-playlist-video-renderer',
                'ytd-playlist-panel-video-renderer',
                '#contents ytd-playlist-video-renderer',
                '[id="content"] ytd-playlist-video-renderer'
            ]
            
            video_count = 0
            
            for selector in selectors:
                try:
                    # ページ読み込み待機
                    await page.wait_for_selector(selector, timeout=5000)
                    elements = await page.query_selector_all(selector)
                    if elements:
                        video_count = len(elements)
                        elements = None
                        logger.info(f"セレクタ '{selector}' で {video_count} 個の動画を発見")
                        break
                except Exception as e:
                    logger.debug(f"セレクタ '{selector}' で失敗: {e}")
                    continue
            
            if video_count == 0:
                # ヘッダーの動画数表示から取得を試みる
                try:
                    stats_element = await page.query_selector('yt-formatted-string.ytd-playlist-sidebar-primary-info-renderer')
                    if stats_element:
                        stats_text = await stats_element.text_content()
                        import re
                        match = re.search(r'(\d+)', stats_text)
                        if match:
                            video_count = int(match.group(1))
                            logger.info(f"ヘッダーから動画数を取得: {video_count}個")
                except Exception as e:
                    logger.debug(f"ヘッダーからの動画数取得失敗: {e}")
            
            logger.info(f"プレイリストページ内動画数: {video_count}個")
            return video_count
            
        except Exception as e:
            logger.error(f"プレイリストページ動画数カウントエラー: {e}")
            return 0


    # 一時的なデバッグコードを追加
    async def debug_playlist_structure(self, page):
        try:
            # ページのHTML構造を出力
            html = await page.content()
            with open('playlist_page_debug.html', 'w', encoding='utf-8') as f:
                f.write(html)
            
            # 一般的な候補セレクターをテスト
            test_selectors = [
                'ytd-playlist-video-renderer',
                '#contents ytd-playlist-video-renderer', 
                'ytd-playlist-video-list-renderer ytd-playlist-video-renderer',
                '[data-playlist-video-id]',
                '.ytd-playlist-video-renderer'
            ]
            
            for selector in test_selectors:
                elements = await page.query_selector_all(selector)
                print(f"{selector}: {len(elements)}個の要素")
                
        except Exception as e:
            print(f"デバッグエラー: {e}")


    async def delete_single_playlist_all_videos(self, page, playlist_name: str) -> bool:
        """単一再生リストの全動画削除"""
        try:
            logger.info(f"{playlist_name} の全動画削除処理を開始")
            
            # ページ読み込み完了待機
            await page.wait_for_load_state('domcontentloaded')
            
            # 早期空プレイリスト検出（処理時間短縮）
            logger.debug(f"{playlist_name} の空プレイリスト検出を実行中...")
            is_empty = await self.detect_empty_playlist_message(page)
            if is_empty:
                logger.info(f"{playlist_name} は空のプレイリストです（早期検出により即座にスキップ）")
                print(f"ℹ️ {playlist_name} は空のプレイリストです（処理をスキップ）")
                return True
            
            # 通常の待機とカウント処理
            await asyncio.sleep(2.0)
            
            # 動画数を確認（空検出の二重チェック）
            video_count = await self.count_playlist_videos_optimized(page)
            if video_count == 0:
                logger.info(f"{playlist_name} は空のプレイリストです（動画カウントによる検出）")
                print(f"ℹ️ {playlist_name} は空のプレイリストです")
                return True
            
            logger.info(f"{playlist_name} に {video_count} 個の動画があります")
            
            # 全選択チェックボックスをクリック
            select_success = await self.select_all_videos_in_playlist(page)
            if not select_success:
                logger.error(f"{playlist_name} の全選択に失敗しました")
                return False
            
            # 1秒待機（DOM更新待ち）
            await asyncio.sleep(1.0)
            
            # Shift+D で削除トリガー
            delete_triggered = await self.trigger_delete_shortcut()
            if not delete_triggered:
                logger.error(f"{playlist_name} の削除トリガーに失敗しました")
                return False
            
            # 確認ダイアログの検出と手動操作待機
            dialog_handled = await self.wait_for_delete_confirmation_dialog(playlist_name)
            
            if dialog_handled:
                logger.info(f"{playlist_name} の削除処理が完了しました")
                return True
            else:
                logger.warning(f"{playlist_name} の確認ダイアログ処理がタイムアウトしました")
                return True  # タイムアウトでも処理は継続
            
        except Exception as e:
            logger.error(f"{playlist_name} の全動画削除エラー: {e}")
            return False



    # def count_playlist_videos_in_playlist_page(self): 
    # このメソッドは既に非同期版として上で定義されています（async def count_playlist_videos_in_playlist_page(self, page) -> int）。
    # 重複定義を避けるため、またPlaywrightを使用しているため、ここでの同期版定義は削除またはコメントアウトします。
    # 元のコードには async 版と 同期版（引数なしselfのみ）が混在しているように見えますが、
    # Playwrightの文脈では async 版が正しいため、async版を生かします。

    async def verify_tab_consolidation(self, expected_tab_count: int = 1) -> bool:
        """タブ統合完了の確認（期待されるタブ数との照合）"""
        try:
            logger.info(f"タブ統合結果の検証開始 (期待タブ数: {expected_tab_count})")
            
            # 1. 現在のタブ数を取得
            try:
                current_pages = self.context.pages
                current_tab_count = len(current_pages)
                logger.info(f"現在のタブ数: {current_tab_count}個")
            except Exception as e:
                logger.error(f"現在タブ数取得エラー: {e}")
                return False
            
            # 2. 基本的な成功判定（期待値との比較）
            if current_tab_count <= expected_tab_count:
                logger.info(f"✅ 基本判定成功: {current_tab_count} <= {expected_tab_count}")
                basic_success = True
            else:
                # 期待値より多いが、大幅な削減があった場合は部分成功
                reduction_threshold = 0.7  # 70%以上削減されていればOK
                if current_tab_count <= expected_tab_count * (1 / reduction_threshold):
                    logger.info(f"⚠️ 部分成功: {current_tab_count}個（大幅削減により許容）")
                    basic_success = True
                else:
                    logger.warning(f"❌ 基本判定失敗: {current_tab_count} > {expected_tab_count}")
                    basic_success = False
            
            # 3. タブの有効性確認
            valid_tabs = 0
            youtube_tabs = 0
            closed_tabs = 0
            
            for i, page in enumerate(current_pages):
                try:
                    # ページが閉じられているかチェック
                    is_closed = page.is_closed()
                    if is_closed:
                        closed_tabs += 1
                        logger.debug(f"タブ {i+1}: 閉じられています")
                        continue
                    
                    # URLを安全に取得
                    try:
                        url = page.url
                        if url:
                            valid_tabs += 1
                            
                            # YouTubeタブかどうか確認
                            if "youtube.com/watch" in url:
                                youtube_tabs += 1
                                logger.debug(f"タブ {i+1}: YouTube動画タブ - {url[:50]}...")
                            else:
                                logger.debug(f"タブ {i+1}: 一般タブ - {url[:50]}...")
                        else:
                            logger.debug(f"タブ {i+1}: URLが空")
                    
                    except Exception as e:
                        logger.debug(f"タブ {i+1}: URL取得エラー - {e}")
                        continue
                
                except Exception as e:
                    logger.debug(f"タブ {i+1}: 状態確認エラー - {e}")
                    continue
            
            logger.info(f"タブ有効性確認結果:")
            logger.info(f"  - 有効なタブ: {valid_tabs}個")
            logger.info(f"  - YouTubeタブ: {youtube_tabs}個")
            logger.info(f"  - 閉じられたタブ: {closed_tabs}個")
            
            # 4. 統合品質の評価
            quality_score = 0
            max_score = 100
            
            # スコア計算: タブ数削減効果
            if current_tab_count <= expected_tab_count:
                quality_score += 40  # 期待値達成
            elif current_tab_count <= expected_tab_count * 2:
                quality_score += 20  # 許容範囲
            
            # スコア計算: YouTubeタブの残存
            if youtube_tabs >= 1:
                quality_score += 30  # YouTubeタブが残っている
            
            # スコア計算: 有効タブの比率
            if valid_tabs > 0:
                valid_ratio = valid_tabs / (valid_tabs + closed_tabs) if (valid_tabs + closed_tabs) > 0 else 1
                quality_score += int(30 * valid_ratio)  # 有効タブの比率に応じて
            
            logger.info(f"統合品質スコア: {quality_score}/{max_score}")
            
            # 5. 最終判定
            success_threshold = 50  # 50点以上で成功とみなす
            
            final_success = basic_success and quality_score >= success_threshold
            
            if final_success:
                logger.info("✅ タブ統合検証成功")
                
                # 6. 成功時の詳細レポート
                if youtube_tabs == 1 and current_tab_count == 1:
                    logger.info("🎯 完璧な統合: YouTube動画タブ1個のみ残存")
                elif youtube_tabs >= 1 and current_tab_count <= 3:
                    logger.info("🎯 良好な統合: 最小限のタブで統合完了")
                elif current_tab_count <= expected_tab_count * 2:
                    logger.info("🎯 許容可能な統合: 期待値近くまで削減")
                else:
                    logger.info("🎯 部分的統合: 一定の効果あり")
                
                return True
            
            else:
                logger.warning("❌ タブ統合検証失敗")
                
                # 7. 失敗時の詳細分析
                failure_reasons = []
                
                if not basic_success:
                    failure_reasons.append(f"タブ数が期待値を大幅に超過 ({current_tab_count} > {expected_tab_count})")
                
                if quality_score < success_threshold:
                    failure_reasons.append(f"統合品質が不十分 ({quality_score}/{max_score})")
                
                if youtube_tabs == 0:
                    failure_reasons.append("YouTubeタブが残存していない")
                
                if valid_tabs == 0:
                    failure_reasons.append("有効なタブが存在しない")
                
                logger.warning("失敗理由:")
                for reason in failure_reasons:
                    logger.warning(f"  - {reason}")
                
                return False
            
        except Exception as e:
            logger.error(f"タブ統合検証エラー: {e}")
            
            # 8. エラー時のフォールバック検証
            try:
                # 最低限の確認: コンテキストが有効で、何らかのページが存在するか
                fallback_pages = self.context.pages
                if len(fallback_pages) > 0 and len(fallback_pages) <= expected_tab_count * 3:
                    logger.info("⚠️ フォールバック検証: 最低限の条件を満たしているため成功とみなす")
                    return True
                else:
                    logger.error("❌ フォールバック検証も失敗")
                    return False
            except Exception as fallback_e:
                logger.error(f"フォールバック検証エラー: {fallback_e}")
                return False

    async def close_other_tabs_playwright_fast(self, keep_page) -> bool:
        """Playwright標準機能による確実なタブ削除（pyautoguiフォーカス問題解決版）"""
        try:
            logger.info("Playwright標準機能による確実なタブ削除開始")
            
            # 1. 残すタブをアクティブにする
            await keep_page.bring_to_front()
            await asyncio.sleep(0.5)
            logger.info("対象タブのアクティブ化完了")
            
            # 2. Chromeウィンドウを物理的に前面に表示
            chrome_front_success = self.bring_chrome_to_front()
            if chrome_front_success:
                logger.info("Chromeウィンドウ前面表示成功")
            else:
                logger.warning("Chromeウィンドウ前面表示に失敗、処理継続")
            
            await asyncio.sleep(0.3)
            
            # 3. 削除前の状態確認
            try:
                all_pages_before = self.context.pages
                tabs_before_count = len(all_pages_before)
                pages_to_close = [page for page in all_pages_before if page != keep_page]
                pages_to_close_count = len(pages_to_close)
                
                logger.info(f"削除前のタブ数: {tabs_before_count}個")
                logger.info(f"削除予定のタブ数: {pages_to_close_count}個")
                
                if pages_to_close_count <= 0:
                    logger.info("削除対象タブがないため処理をスキップ")
                    return True
                    
            except Exception as e:
                logger.error(f"削除前状態確認エラー: {e}")
                return False
            
            # 4. Playwright標準機能による順次タブ削除
            try:
                logger.info(f"🚀 Playwright標準削除開始: {pages_to_close_count}個のタブを順次削除")
                
                start_time = time.time()
                closed_count = 0
                failed_count = 0
                
                # 順次削除（Playwright標準API使用）
                for i, page in enumerate(pages_to_close):
                    try:
                        # ページが既に閉じられていないかチェック
                        if not page.is_closed():
                            await page.close()  # Playwright標準のclose()メソッド
                            closed_count += 1
                            logger.info(f"削除成功: {closed_count}/{pages_to_close_count} (タブ{i+1})")
                            
                            # 安定化待機
                            await asyncio.sleep(0.1)
                        else:
                            logger.debug(f"タブ{i+1}: 既に閉じられています")
                            
                    except Exception as close_e:
                        failed_count += 1
                        logger.warning(f"タブ{i+1}削除失敗: {close_e}")
                        continue
                    
                    # 5個おきに進捗表示
                    if (i + 1) % 5 == 0:
                        current_pages = len(self.context.pages)
                        logger.info(f"中間進捗: 残り{current_pages}個 (成功{closed_count}/失敗{failed_count})")
                
                elapsed_time = time.time() - start_time
                logger.info(f"Playwright削除実行完了: 成功{closed_count}件/失敗{failed_count}件 ({elapsed_time:.2f}秒)")
                
            except Exception as e:
                logger.error(f"Playwright削除実行エラー: {e}")
                return False
            
            # 5. 削除結果の検証
            try:
                # 処理完了待機
                await asyncio.sleep(0.5)
                
                # 最終的なタブ数確認
                final_pages = self.context.pages
                final_count = len(final_pages)
                actual_closed = tabs_before_count - final_count
                
                logger.info(f"✅ Playwright削除結果:")
                logger.info(f"  - 処理時間: {elapsed_time:.2f}秒")
                logger.info(f"  - 削除実行: 成功{closed_count}件/失敗{failed_count}件")
                logger.info(f"  - 実際の効果: {tabs_before_count}個 → {final_count}個 (削減: {actual_closed}個)")
                
                # 成功判定
                if final_count == 1:
                    logger.info("🎯 完璧な削除: 目標の1タブに統合成功")
                    return True
                elif final_count <= 3:
                    logger.info("✅ 良好な削除: 最小限のタブに削減成功")
                    return True
                elif actual_closed >= pages_to_close_count * 0.8:
                    logger.info("⚠️ 部分的成功: 80%以上のタブ削除成功")
                    return True
                else:
                    logger.warning(f"❌ 効果不十分: 削減率{(actual_closed/pages_to_close_count)*100:.1f}%")
                    return False
                    
            except Exception as e:
                logger.error(f"削除結果確認エラー: {e}")
                # 確認できない場合は、成功件数で判定
                if closed_count >= pages_to_close_count * 0.8:
                    logger.info("確認不可だが、成功件数から成功と判定")
                    return True
                else:
                    return False
            
        except Exception as e:
            logger.error(f"Playwright削除エラー: {e}")
            return False

    async def check_and_consolidate_playlist_tabs(self, youtube_tabs: List[dict]) -> Optional[dict]:
        """再生リストの統合判定と自動統合処理（効率的バッチ処理版）"""
        try:
            if len(youtube_tabs) <= 1:
                logger.info("タブ数が1個以下のため統合処理をスキップ")
                return None
            
            logger.info(f"再生リスト統合判定開始: {len(youtube_tabs)}個のタブを分析")
            
            # 1. 各タブの再生リストIDとインデックスを抽出
            playlist_info = []
            for i, tab in enumerate(youtube_tabs):
                try:
                    url = tab['url']
                    
                    # 再生リストIDを抽出
                    playlist_match = re.search(r'list=([^&]+)', url)
                    if not playlist_match:
                        logger.warning(f"タブ{i+1}: 再生リストIDが見つかりません: {url}")
                        continue
                    
                    playlist_id = playlist_match.group(1)
                    
                    # インデックス（プレイリスト内位置）を抽出
                    index_match = re.search(r'index=(\d+)', url)
                    playlist_index = int(index_match.group(1)) if index_match else 0
                    
                    playlist_info.append({
                        'tab_index': i,
                        'tab': tab,
                        'playlist_id': playlist_id,
                        'playlist_index': playlist_index,
                        'url': url
                    })
                    
                    logger.info(f"タブ{i+1}: プレイリストID={playlist_id}, インデックス={playlist_index}")
                    
                except Exception as e:
                    logger.warning(f"タブ{i+1}の分析エラー: {e}")
                    continue
            
            if len(playlist_info) <= 1:
                logger.info("分析可能なタブが1個以下のため統合処理をスキップ")
                return None
            
            # 2. 再生リストIDでグループ化
            playlist_groups = {}
            for info in playlist_info:
                playlist_id = info['playlist_id']
                if playlist_id not in playlist_groups:
                    playlist_groups[playlist_id] = []
                playlist_groups[playlist_id].append(info)
            
            logger.info(f"再生リストグループ数: {len(playlist_groups)}個")
            for playlist_id, group in playlist_groups.items():
                logger.info(f"  - {playlist_id}: {len(group)}個のタブ")
            
            # 3. すべての動画タブが同一再生リストかチェック
            if len(playlist_groups) > 1:
                logger.info("複数の異なる再生リストが検出されたため、通常のUI表示に移行")
                return None
            
            # 4. 同一再生リストの場合、最右端タブ（最大インデックス）を特定
            target_playlist_id = list(playlist_groups.keys())[0]
            target_group = playlist_groups[target_playlist_id]
            
            logger.info(f"✅ 同一再生リスト検出: {target_playlist_id} ({len(target_group)}個のタブ)")
            
            # 最右端タブ（最大インデックス）を特定
            max_index_info = max(target_group, key=lambda x: x['playlist_index'])
            rightmost_tab = max_index_info['tab']
            rightmost_index = max_index_info['playlist_index']
            
            logger.info(f"最右端タブを特定: インデックス={rightmost_index} (タブ{max_index_info['tab_index']+1})")
            playlist_name = rightmost_tab.get('playlist_name', '不明なプレイリスト')
            
            # 5. 統合前の状態確認
            try:
                all_pages_before = self.context.pages
                tabs_before_count = len(all_pages_before)
                logger.info(f"統合前のタブ数: {tabs_before_count}個")
                
                # 残すべきページを特定
                keep_page = rightmost_tab['page']
                pages_to_close = [page for page in all_pages_before if page != keep_page]
                pages_to_close_count = len(pages_to_close)
                
                if pages_to_close_count == 0:
                    logger.info("閉じるべきタブがないため、統合処理をスキップ")
                    return rightmost_tab
                
                logger.info(f"閉じる予定のタブ数: {pages_to_close_count}個")
                
            except Exception as e:
                logger.error(f"統合前状態確認エラー: {e}")
                return None
            
            # 6. 超高速ショートカットによる高速タブ統合実行
            try:
                logger.info(f"🚀 Playwright標準機能による高速タブ統合開始")
                logger.info(f"  - 処理方式: Playwright標準削除")
                logger.info(f"  - 残存予定タブ: インデックス={rightmost_index} (最右端)")
                logger.info(f"  - 削除予定タブ数: {pages_to_close_count}個")
                
                start_time = time.time()
                                    
                # Playwright標準機能を使用した確実なタブ閉じ
                batch_success = await self.close_other_tabs_playwright_fast(keep_page)
                
                elapsed_time = time.time() - start_time
                logger.info(f"ショートカット処理時間: {elapsed_time:.2f}秒")
                
                if not batch_success:
                    logger.warning("超高速ショートカットによる統合に失敗")
                    logger.info("通常のUI表示に移行します")
                    return None
                            
                
            except Exception as e:
                logger.error(f"バッチ処理統合処理エラー: {e}")
                logger.info("統合処理に失敗したため、通常のUI表示に移行します")
                return None
            
            # 7. 統合結果の検証
            try:
                logger.info("統合結果の検証開始")
                
                # 短時間待機（Chrome処理完了確保）
                await asyncio.sleep(1.0)
                
                # 統合検証の実行
                verification_success = await self.verify_tab_consolidation(expected_tab_count=1)
                
                if not verification_success:
                    logger.warning("統合結果の検証に失敗")
                    logger.info("通常のUI表示に移行します")
                    return None
                
            except Exception as e:
                logger.warning(f"統合結果検証エラー: {e}")
                # 検証エラーは致命的ではないため、処理を継続
                logger.info("検証エラーが発生しましたが、統合処理は継続します")
            
            # 8. ブラウザ接続の安定性確認
            try:
                # コンテキストの有効性を確認
                current_pages = self.context.pages
                current_tab_count = len(current_pages)
                
                logger.info(f"統合後のタブ数: {current_tab_count}個")
                
                # 残すべきページが有効かチェック
                try:
                    if keep_page.is_closed():
                        logger.error("残すべきタブが閉じられています")
                        return None
                    
                    # URLアクセス可能性の確認
                    keep_page_url = keep_page.url
                    if not keep_page_url or "youtube.com/watch" not in keep_page_url:
                        logger.warning(f"残存タブのURLが期待と異なります: {keep_page_url}")
                    else:
                        logger.info(f"残存タブのURL確認OK: {keep_page_url[:50]}...")
                    
                except Exception as e:
                    logger.warning(f"残存タブ確認エラー: {e}")
                
            except Exception as e:
                logger.error(f"ブラウザ接続確認エラー: {e}")
                logger.info("接続確認に失敗しましたが、統合処理は完了とみなします")
            
            # 9. 統合完了の最終報告
            try:
                final_elapsed = time.time() - start_time
                logger.info(f"🚀 効率的バッチ処理統合完了")
                logger.info(f"  - 対象再生リスト: {playlist_name}")
                logger.info(f"  - 残存タブ: インデックス={rightmost_index} (最右端)")
                logger.info(f"  - 処理時間: {final_elapsed:.2f}秒")
                logger.info(f"  - 統合効果: {tabs_before_count}個 → {current_tab_count}個")
                
                # 統合効果の評価
                if current_tab_count == 1:
                    logger.info("✨ 完璧な統合: 目標の1タブに統合成功")
                elif current_tab_count <= 3:
                    logger.info("✅ 良好な統合: 最小限のタブに削減成功")
                elif current_tab_count < tabs_before_count * 0.5:
                    logger.info("🎯 効果的な統合: 50%以上のタブ削減成功")
                else:
                    logger.info("⚠️ 部分的統合: 一定の効果を確認")
                
            except Exception as e:
                logger.debug(f"最終報告エラー: {e}")
            
            # 10. 成功した統合結果を返す
            return rightmost_tab
            
        except Exception as e:
            logger.error(f"再生リスト統合処理エラー: {e}")
            logger.info("統合処理に失敗したため、通常のUI表示に移行します")
            return None

    def show_tab_selection_dialog(self, youtube_tabs: List[dict]) -> Optional[dict]:
        """タブ選択ダイアログを表示"""
        try:
            logger.info("タブ選択ダイアログを表示")
            
            if not youtube_tabs:
                # エラーダイアログも最前面に表示
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                messagebox.showerror("エラー", "https://www.youtube.com/watch から始まるタブが見つかりません", parent=root)
                root.destroy()
                return None
            
            # タブ一覧を作成（プレイリスト名を先頭に表示）
            tab_list = []
            for i, tab in enumerate(youtube_tabs):
                playlist_name = tab.get('playlist_name', '不明なプレイリスト')
                video_title = tab['title']
                
                tab_info = f"{i+1}. 【{playlist_name}】\n   動画: {video_title}"
                tab_list.append(tab_info)
            
            tab_text = "\n\n".join(tab_list)
            
            # ダイアログで選択を求める
            root = tk.Tk()
            root.withdraw()  # メインウィンドウを非表示
            root.attributes('-topmost', True)  # 最前面に表示
            root.lift()
            root.focus_force()
            
            message = f"YouTube動画タブが {len(youtube_tabs)} 個見つかりました。\n\n{tab_text}\n\nどのプレイリストを編集しますか？（1-{len(youtube_tabs)}）"
            
            selection = simpledialog.askinteger(
                "プレイリスト選択",
                message,
                initialvalue=1,
                minvalue=1,
                maxvalue=len(youtube_tabs),
                parent=root
            )
            
            root.destroy()
            
            if selection is None:
                logger.info("ユーザーがプレイリスト選択をキャンセル")
                return None
            
            selected_tab = youtube_tabs[selection - 1]
            selected_playlist = selected_tab.get('playlist_name', '不明なプレイリスト')
            logger.info(f"選択されたプレイリスト: {selected_playlist}")
            logger.info(f"選択されたタブ: {selected_tab['title']}")
            return selected_tab
            
        except Exception as e:
            logger.error(f"タブ選択ダイアログエラー: {e}")
            return None

    async def navigate_to_playlist(self, page) -> bool:
        """プレイリストの確認（移動はしない）"""
        try:
            logger.info("プレイリストの確認を開始")
            
            # 現在のURLをチェック
            current_url = page.url
            logger.info(f"現在のURL: {current_url}")
            
            # プレイリストIDを抽出
            playlist_match = re.search(r'list=([^&]+)', current_url)
            if not playlist_match:
                logger.error("プレイリストIDが見つかりません")
                return False
            
            playlist_id = playlist_match.group(1)
            logger.info(f"プレイリストID: {playlist_id}")
            
            # より柔軟なプレイリストパネル検出
            try:
                # 複数のセレクターを試行
                panel_selectors = [
                    '#secondary ytd-playlist-panel-renderer',
                    'ytd-playlist-panel-renderer',
                    '#secondary .ytd-playlist-panel-renderer',
                    '[data-component="playlist-panel"]',
                    '#playlist'
                ]
                
                panel_found = False
                for selector in panel_selectors:
                    try:
                        logger.info(f"プレイリストパネル検索中: {selector}")
                        panel = await page.wait_for_selector(selector, timeout=3000)
                        if panel:
                            logger.info(f"✅ プレイリストパネル発見: {selector}")
                            panel_found = True
                            break
                    except Exception as e:
                        logger.debug(f"セレクター '{selector}' で失敗: {e}")
                        continue
                
                if not panel_found:
                    # フォールバック: URLにプレイリストIDがあれば成功とみなす
                    logger.warning("プレイリストパネルが見つかりませんが、URLにプレイリストIDが含まれているため処理を継続します")
                    return True
                
                return True
                
            except Exception as e:
                # 最終フォールバック: プレイリストIDがURLに含まれていれば続行
                logger.warning(f"プレイリストパネル検出エラー: {e}")
                logger.info("プレイリストIDが確認できているため、処理を継続します")
                return True
            
        except Exception as e:
            logger.error(f"プレイリスト確認エラー: {e}")
            return False
 
    
    def show_deletion_dialog(self, video_count: int, current_position: int = 0, auto_start: bool = False) -> tuple[Optional[int], bool, bool, dict]:
        """削除設定ダイアログ（Auto機能修正版：10秒タイマー・過敏な停止防止）"""
        try:
            root = tk.Tk()
            root.title("YouTube Playlist Remover")
            root.geometry("600x700") 
            root.resizable(False, False)
            
            # ダイアログを最前面に表示
            root.attributes('-topmost', True)
            root.lift()
            root.focus_force()
            root.grab_set()
            
            # 結果を保存する変数
            result = {
                'delete_count': 0,      # ダミー値
                'delete_all': True,     # 常に全削除
                'from_current': False,  # 使用しない
                'playlist_deletion': True,
                'selected_playlists': [],
                'mode': 'auto'          # デフォルト: 自動全削除
            }
            
            # メインフレーム
            main_frame = tk.Frame(root, padx=20, pady=20)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # プレイリスト名のマッピング
            name_mapping = {
                "S": "プレイリストS",
                "A": "プレイリストA",
                "B": "プレイリストB",
                "N": "プレイリストN",
                "M": "プレイリストM",
                "L": "プレイリストL",
                "P+": "プレイリストP+",
                "V": "プレイリストV",
                "WL": "後で見る",
            }
            
            # プレイリストID
            default_playlists = {
                "S": "PL0UGJjoPnxKjT1ClcCwngoCDhModNIG3H",
                "A": "PL0UGJjoPnxKgphke6I63QVyHeToWaNSTD",
                "B": "PL0UGJjoPnxKhM3jXPMhNxONyvyZbClDuM",
                "N": "PL0UGJjoPnxKj6T0VlBmyxVqVmBIK1h3G6",
                "M": "PL0UGJjoPnxKhX6NN6K5GSPCzh9H8bK1F3",
                "L": "PL0UGJjoPnxKhEsnwZqNSkcUZow4Uklz5R",
                "P+": "PL0UGJjoPnxKggbm7xrXUJQAExVbuca8-M",
                "V": "PL0UGJjoPnxKgZaJvHD5lGzOmGnEAdrn9H",
                "WL": "WL",
            }
            
            # ========== 動作モード選択セクション ==========
            mode_frame = tk.LabelFrame(main_frame, text="動作モード", font=("Arial", 11, "bold"))
            mode_frame.pack(pady=(0, 15), fill=tk.X)
            
            # 初期値を "auto" に設定
            mode_var = tk.StringVar(value="auto")
            
            # UI切り替え用関数
            def toggle_mode_description():
                is_manual = mode_var.get() == "manual"
                if is_manual:
                    mode_desc_label.config(
                        text="選択したプレイリストのタブを開きます。\n削除操作は行いません。",
                        fg="blue"
                    )
                    warning_label.pack_forget() # 警告を隠す
                else:
                    mode_desc_label.config(
                        text="選択したプレイリストの動画を【全て】自動削除します。\nゴミ箱アイコンを順次クリックして空にします。",
                        fg="red"
                    )
                    warning_label.pack(pady=(0, 15)) # 警告を表示
            
            # ラジオボタン配置
            radio_frame = tk.Frame(mode_frame)
            radio_frame.pack(padx=10, pady=(10, 5))
            
            tk.Radiobutton(
                radio_frame,
                text="手動モード（タブを開くのみ）",
                variable=mode_var,
                value="manual",
                font=("Arial", 10, "bold"),
                fg="blue",
                command=toggle_mode_description
            ).pack(side=tk.LEFT, padx=(0, 30))
            
            tk.Radiobutton(
                radio_frame,
                text="自動全削除モード",
                variable=mode_var,
                value="auto",
                font=("Arial", 10, "bold"),
                fg="red",
                command=toggle_mode_description
            ).pack(side=tk.LEFT)
            
            # モード説明文
            mode_desc_label = tk.Label(
                mode_frame,
                text="", 
                font=("Arial", 10),
                justify=tk.LEFT
            )
            mode_desc_label.pack(padx=10, pady=(0, 10))
            
            # ========== 再生リスト選択セクション ==========
            playlist_frame = tk.LabelFrame(main_frame, text="対象プレイリスト選択", font=("Arial", 10, "bold"))
            playlist_frame.pack(pady=(0, 20), fill=tk.X)
            
            # チェックボックス用の変数
            playlist_vars = {}
            
            # ALLの初期値はFalse（Lが外れているため）
            all_var = tk.BooleanVar(value=False)
            
            # チェックボックスコンテナ
            checkbox_container = tk.Frame(playlist_frame)
            checkbox_container.pack(padx=10, pady=10, fill=tk.X)
            
            # ALL チェックボックス
            def on_all_changed():
                state = all_var.get()
                for key in name_mapping.keys():
                    playlist_vars[key].set(state)
            
            all_cb = tk.Checkbutton(
                checkbox_container,
                text="ALL",
                variable=all_var,
                command=on_all_changed,
                font=("Arial", 10, "bold")
            )
            all_cb.pack(anchor=tk.W, pady=(0, 5))
            
            tk.Frame(checkbox_container, height=1, bg="#cccccc").pack(fill=tk.X, pady=5)
            
            # 個別チェックボックス
            list_frame = tk.Frame(checkbox_container)
            list_frame.pack(fill=tk.X)
            
            def on_individual_changed():
                all_checked = all(playlist_vars[k].get() for k in name_mapping.keys())
                all_var.set(all_checked)
            
            # グリッド配置で並べる
            row = 0
            col = 0
            for key, display_name in name_mapping.items():
                # キーが "L", "P+", "WL" の場合のみ初期値をFalseにする（Vはデフォルトでチェック済みにする）
                initial_state = False if key in ("L", "P+", "WL") else True
                
                playlist_vars[key] = tk.BooleanVar(value=initial_state)
                cb = tk.Checkbutton(
                    list_frame,
                    text=f"{key}: {display_name}",
                    variable=playlist_vars[key],
                    command=on_individual_changed,
                    font=("Arial", 10)
                )
                cb.grid(row=row, column=col, sticky="w", padx=10, pady=2)
                
                # 2列で折り返し
                col += 1
                if col > 1:
                    col = 0
                    row += 1

            # ========== 注意事項 ==========
            warning_label = tk.Label(
                main_frame,
                text="⚠️ 注意: 自動モードはプレイリスト内の【全動画】を削除します。\n削除処理は元に戻せません。",
                font=("Arial", 10, "bold"),
                fg="orange",
                bg="#fff0f0",
                padx=10,
                pady=5,
                relief=tk.RIDGE
            )

            # ========== Autoモード設定 (タイマー) ==========
            auto_frame = tk.Frame(main_frame)
            auto_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 10))
            
            auto_var_tk = tk.BooleanVar(value=auto_start)
            timer_label = tk.Label(auto_frame, text="", font=("Arial", 10, "bold"), fg="green")
            
            auto_timer_id = None
            remaining_seconds = [10] # ★ 変更点: 30秒 -> 10秒に変更
            
            # OK処理（前方宣言）
            on_ok_action = None

            def cancel_auto_timer(event=None):
                nonlocal auto_timer_id
                if auto_timer_id:
                    root.after_cancel(auto_timer_id)
                    auto_timer_id = None
                
                if auto_var_tk.get():
                    auto_var_tk.set(False)
                    timer_label.config(text="タイマー停止（手動操作を検出）", fg="blue")
            
            def update_timer():
                nonlocal auto_timer_id
                if not auto_var_tk.get():
                    return
                
                if remaining_seconds[0] > 0:
                    timer_label.config(text=f"⏳ Autoモード: {remaining_seconds[0]}秒後に自動実行します...")
                    remaining_seconds[0] -= 1
                    auto_timer_id = root.after(1000, update_timer)
                else:
                    logger.info("Autoモード: タイムアウト - 自動実行")
                    timer_label.config(text="🚀 自動実行を開始します...", fg="red")
                    root.update()
                    time.sleep(0.5) # 少し待機して視認させる
                    if on_ok_action:
                        on_ok_action()
            
            # Autoモードチェックボックス
            # チェックを外したときのみタイマーをキャンセルするように変更
            def on_auto_check_toggle():
                if auto_var_tk.get():
                    # 再開時は時間をリセットしない（必要なら remaining_seconds[0] = 10 を入れる）
                    update_timer()
                else:
                    cancel_auto_timer()

            auto_check = tk.Checkbutton(
                auto_frame,
                text="Autoモード（タイマー自動進行）",
                variable=auto_var_tk,
                command=on_auto_check_toggle,
                font=("Arial", 10)
            )
            auto_check.pack(anchor="w")
            timer_label.pack(anchor="w")

            # ボタンフレーム
            button_frame = tk.Frame(main_frame)
            button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
            
            def on_ok():
                # タイマーキャンセル
                if auto_timer_id:
                    root.after_cancel(auto_timer_id)

                result['mode'] = mode_var.get()
                
                # 選択されたプレイリストを収集
                selected = []
                for key, var in playlist_vars.items():
                    if var.get():
                        selected.append({
                            'key': key,
                            'name': name_mapping[key],
                            'id': default_playlists[key]
                        })
                
                if not selected:
                    tk.messagebox.showwarning("警告", "プレイリストを1つ以上選択してください", parent=root)
                    return
                
                result['selected_playlists'] = selected
                
                root.quit()
                root.destroy()
            
            on_ok_action = on_ok
            
            def on_cancel():
                if auto_timer_id:
                    root.after_cancel(auto_timer_id)

                result['selected_playlists'] = []
                root.quit()
                root.destroy()
            
            # ボタン
            tk.Button(
                button_frame, 
                text="実行", 
                command=on_ok, 
                bg="#ddddff", 
                font=("Arial", 11, "bold"),
                width=15,
                height=2
            ).pack(side=tk.LEFT, padx=(50, 20))
            
            tk.Button(
                button_frame, 
                text="キャンセル", 
                command=on_cancel,
                font=("Arial", 11),
                width=10,
                height=2
            ).pack(side=tk.RIGHT, padx=(20, 50))
            
            # 初期表示UI設定
            toggle_mode_description()
            
            # 画面中央配置
            root.update_idletasks()
            w = root.winfo_width()
            h = root.winfo_height()
            x = (root.winfo_screenwidth() // 2) - (w // 2)
            y = (root.winfo_screenheight() // 2) - (h // 2)
            root.geometry(f"+{x}+{y}")
            
            root.after(100, lambda: root.attributes('-topmost', False))
            
            # ★ 変更点: 過敏なイベントバインド（root.bind）を削除しました
            # これにより、ウィンドウをクリックしてもタイマーは止まらなくなります。
            # 止めるには「キャンセル」か「Autoモードのチェックを外す」必要があります。

            # 初期タイマー起動
            if auto_start:
                update_timer()

            root.mainloop()
            
            # キャンセル判定
            if not result['selected_playlists']:
                return None, False, True, {'playlist_deletion': False, 'selected_playlists': []}
            
            return 0, True, False, result
            
        except Exception as e:
            logger.error(f"ダイアログエラー: {e}")
            return None, False, True, {}
    
    

    def show_cancel_button(self):
        """キャンセルボタンを表示"""
        def create_cancel_window():
            try:
                self.cancel_window = tk.Tk()
                self.cancel_window.title("削除実行中")
                self.cancel_window.geometry("200x100")
                self.cancel_window.attributes('-topmost', True)  # 常に前面表示
                
                label = tk.Label(self.cancel_window, text="削除実行中...", font=("Arial", 12))
                label.pack(pady=10)
                
                cancel_btn = tk.Button(
                    self.cancel_window,
                    text="キャンセル",
                    command=self.cancel_deletion,
                    bg="red",
                    fg="white",
                    font=("Arial", 10, "bold")
                )
                cancel_btn.pack(pady=10)
                
                self.cancel_window.protocol("WM_DELETE_WINDOW", self.cancel_deletion)
                
                # mainloopを開始（これがスレッドをブロックする）
                self.cancel_window.mainloop()
                
            except Exception as e:
                logger.debug(f"キャンセルウィンドウ作成エラー: {e}")
        
        # 別スレッドでキャンセルウィンドウを表示
        cancel_thread = threading.Thread(target=create_cancel_window, daemon=True)
        cancel_thread.start()
        
        logger.info("キャンセルボタンを表示")
        
        # スレッドが開始されるまで少し待機
        time.sleep(0.3)  # 0.5 -> 0.3に短縮
    
    def cancel_deletion(self):
        """削除操作をキャンセル"""
        self.cancel_operation = True
        logger.info("ユーザーが削除操作をキャンセル")
        try:
            if self.cancel_window:
                self.cancel_window.quit()  # mainloopを終了
                self.cancel_window.destroy()
                self.cancel_window = None
        except Exception as e:
            logger.debug(f"キャンセル処理エラー: {e}")
    
    def close_cancel_button(self):
        """キャンセルボタンを閉じる"""
        try:
            if self.cancel_window:
                self.cancel_window.quit()  # mainloopを終了
                self.cancel_window.destroy()
                self.cancel_window = None
                logger.info("キャンセルボタンを閉じました")
        except Exception as e:
            logger.debug(f"キャンセルボタン終了エラー: {e}")

    async def navigate_to_playlists_page(self, page) -> bool:
        """プレイリスト一覧ページに移動"""
        try:
            logger.info("プレイリスト一覧ページに移動中...")
            await page.goto("https://www.youtube.com/feed/playlists")
            await page.wait_for_load_state('domcontentloaded')
            logger.info("プレイリスト一覧ページに移動完了")
            return True
        except Exception as e:
            logger.error(f"プレイリスト一覧ページ移動エラー: {e}")
            return False



    async def delete_entire_playlists(self, selected_playlists: list) -> bool:
        """複数の再生リスト全削除を順次実行（個別削除方式）"""
        try:
            logger.info(f"再生リスト全削除処理開始: {len(selected_playlists)}個のプレイリスト")
            print(f"\n🎵 {len(selected_playlists)}個のプレイリストを処理します（個別削除方式）")
            
            success_count = 0
            failed_count = 0
            
            for i, playlist_info in enumerate(selected_playlists, 1):
                playlist_key = playlist_info['key']
                playlist_name = playlist_info['name']
                playlist_id = playlist_info['id']
                
                logger.info(f"{'='*50}")
                logger.info(f"処理中 ({i}/{len(selected_playlists)}): {playlist_name} (ID: {playlist_id})")
                print(f"\n{'='*50}")
                print(f"[{i}/{len(selected_playlists)}] 🎵 {playlist_name} の処理を開始...")
                
                # キャンセルチェック
                if self.cancel_operation:
                    logger.info("ユーザーによるキャンセルを検出")
                    print("⚠️ 処理がキャンセルされました")
                    break
                
                # プレイリストの最初の動画に移動
                success = await self.navigate_to_first_video_in_playlist(playlist_id)
                if not success:
                    logger.warning(f"{playlist_name} の最初の動画への移動に失敗（空の可能性あり）")
                    print(f"ℹ️ {playlist_name} は空のプレイリストか、アクセスできません（スキップ）")
                    success_count += 1  # 空のプレイリストも成功とカウント
                    continue
                
                # 個別削除処理を実行
                deletion_success = await self.delete_playlist_videos_simple(self.page, playlist_name)
                
                if deletion_success:
                    success_count += 1
                    logger.info(f"✅ {playlist_name} の処理が完了しました")
                    print(f"✅ {playlist_name} の削除が完了しました")
                else:
                    failed_count += 1
                    logger.warning(f"⚠️ {playlist_name} の処理に失敗しました")
                    print(f"⚠️ {playlist_name} の削除に失敗しました")
                
                # 次のプレイリストまで少し待機
                if i < len(selected_playlists):
                    await asyncio.sleep(2.0)
            
            # 最終結果
            logger.info(f"{'='*50}")
            logger.info(f"再生リスト全削除完了: 成功{success_count}個, 失敗{failed_count}個")
            print(f"\n{'='*50}")
            print(f"📊 処理結果: 成功{success_count}個, 失敗{failed_count}個")
            
            return success_count > 0
            
        except Exception as e:
            logger.error(f"再生リスト全削除処理エラー: {e}")
            print(f"❌ エラーが発生しました: {e}")
            return False




    async def delete_single_playlist_all_videos(self, page, playlist_name: str) -> bool:
        """単一再生リストの全動画削除（個別削除方式）"""
        try:
            logger.info(f"{playlist_name} の全動画削除処理を開始（個別削除方式）")
            
            # 既に動画ページにいる場合はそのまま処理
            current_url = page.url
            if "youtube.com/watch" in current_url:
                logger.info("既に動画ページにいるため、そのまま削除処理を開始")
                return await self.delete_playlist_videos_simple(page, playlist_name)
            
            # プレイリストページの場合は最初の動画に移動
            if "youtube.com/playlist" in current_url:
                # URLからプレイリストIDを抽出
                import re
                playlist_match = re.search(r'list=([^&]+)', current_url)
                if playlist_match:
                    playlist_id = playlist_match.group(1)
                    logger.info(f"プレイリストID: {playlist_id}")
                    
                    # 最初の動画に移動
                    success = await self.navigate_to_first_video_in_playlist(playlist_id)
                    if not success:
                        logger.warning(f"{playlist_name} は空のプレイリストです")
                        print(f"ℹ️ {playlist_name} は空のプレイリストです")
                        return True
                    
                    # 個別削除処理
                    return await self.delete_playlist_videos_simple(page, playlist_name)
                else:
                    logger.error("プレイリストIDを抽出できません")
                    return False
            
            logger.error(f"未対応のページタイプ: {current_url}")
            return False
            
        except Exception as e:
            logger.error(f"{playlist_name} の全動画削除エラー: {e}")
            return False


    async def open_playlist_tabs(self, selected_playlists: list) -> bool:
        """選択されたプレイリストのタブを開く（並列処理版）"""
        try:
            logger.info(f"手動削除モード: {len(selected_playlists)}個のプレイリストタブを並列で開きます")
            print(f"\n📂 {len(selected_playlists)}個のプレイリストタブを一括で開いています...")
            
            async def open_single_tab(playlist_info: dict, index: int) -> dict:
                """単一のプレイリストタブを開く（並列実行用）"""
                playlist_name = playlist_info['name']
                playlist_id = playlist_info['id']
                
                try:
                    logger.info(f"タブ生成開始: {playlist_name}")
                    
                    # 新しいタブを作成
                    new_page = await self.context.new_page()
                    
                    # プレイリストURLを構築
                    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                    
                    # プレイリストページに移動
                    await new_page.goto(playlist_url)
                    await new_page.wait_for_load_state('domcontentloaded')
                    
                    # 空のプレイリストチェック
                    is_empty = await self.detect_empty_playlist_message(new_page)
                    
                    status = "empty" if is_empty else "success"
                    logger.info(f"タブ生成完了: {playlist_name} (status: {status})")
                    
                    return {
                        'index': index,
                        'name': playlist_name,
                        'status': status,
                        'error': None
                    }
                    
                except Exception as e:
                    logger.error(f"{playlist_name} のタブ生成エラー: {e}")
                    return {
                        'index': index,
                        'name': playlist_name,
                        'status': 'failed',
                        'error': str(e)
                    }
            
            # 並列実行のタスクを作成
            tasks = [
                open_single_tab(playlist_info, i) 
                for i, playlist_info in enumerate(selected_playlists, 1)
            ]
            
            # すべてのタスクを並列実行
            print("⏳ すべてのタブを同時に開いています...")
            results = await asyncio.gather(*tasks, return_exceptions=False)
            
            # 結果を集計
            success_count = 0
            failed_count = 0
            empty_count = 0
            
            print("\n📊 タブ生成結果:")
            for result in sorted(results, key=lambda x: x['index']):
                if result['status'] == 'success':
                    success_count += 1
                    print(f"  ✅ {result['name']}: 正常に開きました")
                elif result['status'] == 'empty':
                    empty_count += 1
                    print(f"  ℹ️ {result['name']}: 空のプレイリスト")
                else:
                    failed_count += 1
                    print(f"  ❌ {result['name']}: 失敗 ({result['error']})")
            
            # サマリー表示
            print(f"\n📊 集計:")
            print(f"  ✅ 成功: {success_count}個")
            if empty_count > 0:
                print(f"  ℹ️ 空: {empty_count}個")
            if failed_count > 0:
                print(f"  ❌ 失敗: {failed_count}個")
            
            total_opened = success_count + empty_count
            if total_opened > 0:
                print(f"\n💡 {total_opened}個のプレイリストタブを開きました")
                print("手動で削除操作を行ってください")
                
                # 最初のタブにフォーカスを移動
                try:
                    pages = self.context.pages
                    if len(pages) > 1:  # 元のタブ + 新しく開いたタブ
                        await pages[1].bring_to_front()
                except:
                    pass
                
                return True
            else:
                logger.error("タブを1つも開けませんでした")
                return False
                
        except Exception as e:
            logger.error(f"プレイリストタブ並列生成エラー: {e}")
            print(f"❌ タブ生成中にエラーが発生しました: {e}")
            return False




    async def navigate_to_first_video_in_playlist(self, playlist_id: str) -> bool:
        """プレイリストの最初の動画ページに移動（動画ページ + 右側パネル表示）"""
        try:
            logger.info(f"プレイリスト {playlist_id} の最初の動画に移動中...")
            
            # まずプレイリストページに移動
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            logger.info(f"プレイリストページに移動: {playlist_url}")
            await self.page.goto(playlist_url)
            await self.page.wait_for_load_state('domcontentloaded')
            await asyncio.sleep(2.0)
            
            # プレイリストが空かチェック
            is_empty = await self.detect_empty_playlist_message(self.page)
            if is_empty:
                logger.info("プレイリストは空です")
                return False
            
            # 最初の動画要素を探す（複数のセレクタを試行）
            first_video_selectors = [
                'ytd-playlist-video-renderer:first-child a#video-title',
                'ytd-playlist-video-renderer:first-of-type a#video-title',
                '#contents ytd-playlist-video-renderer:first-child a',
                'ytd-playlist-video-renderer a[href*="watch"]:first-of-type',
                '#content a#video-title'
            ]
            
            first_video_href = None
            for selector in first_video_selectors:
                try:
                    first_video = await self.page.wait_for_selector(selector, timeout=3000)
                    if first_video:
                        first_video_href = await first_video.get_attribute('href')
                        if first_video_href:
                            logger.info(f"最初の動画を発見: セレクタ={selector}")
                            break
                except Exception as e:
                    logger.debug(f"セレクタ {selector} で動画が見つかりません: {e}")
                    continue
            
            if not first_video_href:
                logger.error("最初の動画のURLを取得できません")
                return False
            
            # 動画ページに移動（プレイリストパラメータ付き）
            if not first_video_href.startswith('http'):
                video_url = f"https://www.youtube.com{first_video_href}"
            else:
                video_url = first_video_href
            
            # list パラメータが含まれているか確認
            if 'list=' not in video_url:
                video_url += f"&list={playlist_id}" if '?' in video_url else f"?list={playlist_id}"
            
            logger.info(f"動画ページに移動: {video_url}")
            await self.page.goto(video_url)
            await self.page.wait_for_load_state('domcontentloaded')
            
            # 右側のプレイリストパネルが表示されるのを待つ
            try:
                await self.page.wait_for_selector('#secondary ytd-playlist-panel-renderer', timeout=10000)
                logger.info("右側のプレイリストパネルの表示を確認")
                
                # パネル内の動画要素の存在も確認
                await asyncio.sleep(1.0)
                video_elements = await self.page.query_selector_all(
                    '#secondary ytd-playlist-panel-renderer ytd-playlist-panel-video-renderer'
                )
                
                if video_elements and len(video_elements) > 0:
                    logger.info(f"プレイリストパネルに {len(video_elements)} 個の動画を確認")
                    return True
                else:
                    logger.warning("プレイリストパネルに動画が表示されていません")
                    return False
                    
            except Exception as e:
                logger.error(f"プレイリストパネルの表示待機エラー: {e}")
                return False
                
        except Exception as e:
            logger.error(f"最初の動画への移動エラー: {e}")
            return False

    
    async def navigate_to_playlist_by_id(self, playlist_id: str) -> bool:
        """プレイリストIDから直接遷移"""
        try:
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            logger.info(f"プレイリストに遷移: {playlist_url}")
            
            await self.page.goto(playlist_url)
            await self.page.wait_for_load_state('domcontentloaded')
            
            # プレイリストページの読み込み確認
            try:
                await self.page.wait_for_selector('#secondary ytd-playlist-panel-renderer', timeout=10000)
                logger.info("プレイリストページの読み込み完了")
                return True
            except Exception as e:
                logger.warning(f"プレイリストパネルの読み込みに時間がかかっています: {e}")
                # パネルが見つからなくても処理は継続
                return True
                
        except Exception as e:
            logger.error(f"プレイリスト遷移エラー: {e}")
            return False

    async def select_all_videos_in_playlist(self, page) -> bool:
        """全選択チェックボックスをクリック（プレイリストページ対応）"""
        try:
            logger.info("全選択チェックボックスを探しています...")
            
            # まず動画数を確認
            video_count = await self.count_playlist_videos_in_playlist_page(page)
            if video_count == 0:
                logger.warning("動画が見つからないため、全選択できません")
                return False
            
            # プレイリストページの全選択チェックボックスセレクタ
            selectors = [
                '#checkbox',  # 最も一般的
                'tp-yt-paper-checkbox#checkbox',
                '[aria-label*="すべて"]',
                '[aria-label*="Select all"]',
                'ytd-playlist-video-list-renderer tp-yt-paper-checkbox',
                '#contents tp-yt-paper-checkbox',
                '.style-scope.ytd-playlist-header-renderer tp-yt-paper-checkbox',
                '[role="checkbox"]'
            ]
            
            for selector in selectors:
                try:
                    # チェックボックスを探す
                    checkboxes = await page.query_selector_all(selector)
                    if checkboxes and len(checkboxes) > 0:
                        # 最初のチェックボックスをクリック（通常これが全選択）
                        await checkboxes[0].click()
                        logger.info(f"全選択チェックボックスをクリックしました (セレクタ: {selector})")
                        
                        # 選択状態の確認
                        await asyncio.sleep(0.5)
                        
                        # 選択された動画数の確認
                        selected_indicators = [
                            '[aria-label*="selected"]',
                            '[aria-label*="選択済み"]',
                            '.selection-counter',
                            'text=/\\d+件選択済み/'
                        ]
                        
                        for indicator_selector in selected_indicators:
                            try:
                                selected_indicator = await page.query_selector(indicator_selector)
                                if selected_indicator:
                                    selected_text = await selected_indicator.text_content()
                                    logger.info(f"選択状態: {selected_text}")
                                    break
                            except:
                                continue
                        
                        return True
                except Exception as e:
                    logger.debug(f"セレクタ '{selector}' で失敗: {e}")
                    continue
            
            logger.error("全選択チェックボックスが見つかりませんでした")
            return False
            
        except Exception as e:
            logger.error(f"全選択チェックボックスクリックエラー: {e}")
            return False

    async def count_playlist_videos_in_playlist_page(self, page) -> int:
        """プレイリストページ専用の動画カウント"""
        try:
            logger.info("プレイリストページの動画数をカウント開始")
            
            # プレイリストページ専用のセレクタ
            selectors = [
                'ytd-playlist-video-renderer',
                'ytd-playlist-panel-video-renderer',
                '#contents ytd-playlist-video-renderer',
                '[id="content"] ytd-playlist-video-renderer'
            ]
            
            video_count = 0
            
            for selector in selectors:
                try:
                    # ページ読み込み待機
                    await page.wait_for_selector(selector, timeout=5000)
                    elements = await page.query_selector_all(selector)
                    if elements:
                        video_count = len(elements)
                        elements = None
                        logger.info(f"セレクタ '{selector}' で {video_count} 個の動画を発見")
                        break
                except Exception as e:
                    logger.debug(f"セレクタ '{selector}' で失敗: {e}")
                    continue
            
            if video_count == 0:
                # ヘッダーの動画数表示から取得を試みる
                try:
                    stats_element = await page.query_selector('yt-formatted-string.ytd-playlist-sidebar-primary-info-renderer')
                    if stats_element:
                        stats_text = await stats_element.text_content()
                        import re
                        match = re.search(r'(\d+)', stats_text)
                        if match:
                            video_count = int(match.group(1))
                            logger.info(f"ヘッダーから動画数を取得: {video_count}個")
                except Exception as e:
                    logger.debug(f"ヘッダーからの動画数取得失敗: {e}")
            
            logger.info(f"プレイリストページ内動画数: {video_count}個")
            return video_count
            
        except Exception as e:
            logger.error(f"プレイリストページ動画数カウントエラー: {e}")
            return 0

    async def trigger_delete_shortcut(self) -> bool:
        """Shift+D キー送信"""
        try:
            logger.info("1秒待機後、Shift+D ショートカットを送信します...")
            
            # 1秒待機（全選択処理の完了とDOM更新を待つ）
            await asyncio.sleep(1.0)
            
            # フォーカスの確保
            try:
                # ページにフォーカスを当てる
                await self.page.focus('body')
                await asyncio.sleep(0.2)
                
                # フォーカス確認
                focused_element = await self.page.query_selector(':focus')
                if focused_element:
                    logger.debug("ページにフォーカス設定完了")
                else:
                    logger.warning("フォーカス設定が確認できません")
                    
            except Exception as focus_error:
                logger.warning(f"フォーカス設定に失敗: {focus_error}")
            
            # Shift+D を送信（Shift修飾子付き）
            shortcut_success = False
            try:
                await self.page.keyboard.press('Shift+KeyD')
                logger.info("Shift+D ショートカット（方法1）を送信しました")
                shortcut_success = True
            except Exception as e1:
                try:
                    # 代替方法1
                    await self.page.keyboard.press('D', modifiers=['Shift'])
                    logger.info("Shift+D ショートカット（方法2）を送信しました")
                    shortcut_success = True
                except Exception as e2:
                    try:
                        # 代替方法2
                        await self.page.keyboard.down('Shift')
                        await self.page.keyboard.press('KeyD')
                        await self.page.keyboard.up('Shift')
                        logger.info("Shift+D ショートカット（方法3）を送信しました")
                        shortcut_success = True
                    except Exception as e3:
                        logger.error(f"全てのショートカット送信方法が失敗: {e1}, {e2}, {e3}")
                        return False
            
            if not shortcut_success:
                logger.error("ショートカット送信に失敗しました")
                return False
                
            # 処理完了の待機とダイアログ出現確認
            await asyncio.sleep(0.5)
            
            # 削除確認ダイアログが出現するか短時間チェック
            try:
                dialog_selectors = [
                    '[role="dialog"]',
                    '.style-scope.ytd-popup-container',
                    '#dialog',
                    'tp-yt-paper-dialog'
                ]
                
                dialog_appeared = False
                for selector in dialog_selectors:
                    try:
                        await self.page.wait_for_selector(selector, timeout=2000)
                        logger.info(f"削除確認ダイアログの出現を確認: {selector}")
                        dialog_appeared = True
                        break
                    except:
                        continue
                
                if not dialog_appeared:
                    logger.warning("削除確認ダイアログの出現が確認できませんでした（タイムアウト）")
                    
            except Exception as dialog_error:
                logger.debug(f"ダイアログ確認エラー: {dialog_error}")
            
            logger.info("Shift+D ショートカット送信完了")
            return True
            
        except Exception as e:
            logger.error(f"ショートカット送信エラー: {e}")
            return False

    async def wait_for_delete_confirmation_dialog(self, playlist_name: str, timeout: int = 60) -> bool:
        """確認ダイアログの検出と手動操作待機"""
        try:
            logger.info(f"{playlist_name} の削除確認ダイアログを待機中...")
            print(f"\n⏳ 削除確認ダイアログが表示されます。手動でOK/キャンセルをクリックしてください...")
            print(f"📋 対象: {playlist_name}")
            print(f"⚠️ デバッグ期間中のため手動操作が必要です")
            
            # 確認ダイアログのセレクタ
            dialog_selectors = [
                'tp-yt-paper-dialog',
                'yt-confirm-dialog-renderer',
                '[role="dialog"]',
                '.yt-dialog-base',
                'ytd-popup-container',
                '#dialog',
                '.style-scope.ytd-popup-container'
            ]
            
            # ダイアログの出現を待つ（短時間）
            dialog_found = False
            dialog_element = None
            
            for selector in dialog_selectors:
                try:
                    dialog_element = await self.page.wait_for_selector(selector, timeout=5000)
                    if dialog_element:
                        logger.info(f"確認ダイアログを検出しました (セレクタ: {selector})")
                        dialog_found = True
                        break
                except Exception:
                    continue
            
            if not dialog_found:
                logger.warning("確認ダイアログが検出されませんでした")
                print("⚠️ 確認ダイアログが見つかりませんでした。次のプレイリストに進みます。")
                return False
            
            print(f"✅ 確認ダイアログを検出しました。手動で操作してください...")
            
            # ダイアログが消えるまで待機（手動操作待ち）
            start_time = time.time()
            check_interval = 1.0  # チェック間隔（秒）
            last_progress_time = start_time
            
            while time.time() - start_time < timeout:
                try:
                    # 進行状況の表示（10秒ごと）
                    current_time = time.time()
                    if current_time - last_progress_time > 10:
                        elapsed = int(current_time - start_time)
                        remaining = max(0, timeout - elapsed)
                        print(f"⏰ 手動操作待機中... ({elapsed}秒経過 / 残り{remaining}秒)")
                        last_progress_time = current_time
                    
                    # ダイアログがまだ存在するかチェック
                    dialog_exists = False
                    for selector in dialog_selectors:
                        try:
                            element = await self.page.query_selector(selector)
                            if element and await element.is_visible():
                                dialog_exists = True
                                break
                        except:
                            continue
                    
                    if not dialog_exists:
                        logger.info(f"確認ダイアログが閉じられました（手動操作完了）")
                        print(f"✅ {playlist_name} の確認ダイアログ処理完了")
                        print(f"➡️ 次のプレイリストに移動します...\n")
                        return True
                    
                    await asyncio.sleep(check_interval)
                    
                except Exception as e:
                    logger.debug(f"ダイアログ確認中のエラー: {e}")
                    await asyncio.sleep(check_interval)
            
            # タイムアウト処理
            logger.warning(f"確認ダイアログの手動操作がタイムアウトしました（{timeout}秒）")
            print(f"⚠️ タイムアウト({timeout}秒): 次のプレイリストに進みます")
            print(f"➡️ {playlist_name} の処理をスキップします...\n")
            return False
            
        except Exception as e:
            logger.error(f"確認ダイアログ待機エラー: {e}")
            print(f"❌ ダイアログ待機エラー: 次のプレイリストに進みます")
            return False


    async def delete_videos_individually(self, page) -> bool:
        """
        動画リストの先頭から順に削除（高速化版）
        """
        try:
            logger.info("個別削除フローを開始します（高速化設定）")
            
            # 1. 画面サイズを固定
            await page.set_viewport_size({"width": 1280, "height": 800})
            
            # 動画リストの待機
            try:
                await page.wait_for_selector('ytd-playlist-video-renderer', timeout=5000)
            except:
                logger.info("動画リストが見つかりません（既に空の可能性があります）")
                return True

            deleted_count = 0
            consecutive_errors = 0
            
            while True:
                if self.cancel_operation:
                    print("\n⚠️ ユーザーにより中断されました")
                    return False

                # DOM再取得
                videos = await page.query_selector_all('ytd-playlist-video-renderer')
                if not videos:
                    logger.info("動画リストが空になりました。削除完了です。")
                    return True

                remaining = len(videos)
                # print出力を少し減らして高速化（毎回flushすると遅くなるため）
                print(f"\r  ⏳ 残り: {remaining}件 (削除済: {deleted_count}件)", end="", flush=True)

                target_video = videos[0]

                try:
                    # アプローチ1: ゴミ箱アイコンを直接探す
                    
                    # ホバー
                    await target_video.hover()
                    # ★高速化ポイント1: ホバー待ちを 0.3秒 -> 0.1秒 に短縮
                    await asyncio.sleep(0.1) 

                    trash_selectors = [
                        'button[aria-label="削除"]',
                        'button[aria-label="Remove from playlist"]',
                        'yt-icon-button[aria-label="削除"]',
                        '#remove-button',
                        '#menu button[aria-label*="削除"]' 
                    ]

                    trash_btn = None
                    for selector in trash_selectors:
                        try:
                            btn = await target_video.query_selector(selector)
                            if btn and await btn.is_visible():
                                trash_btn = btn
                                break
                        except:
                            continue
                    
                    if trash_btn:
                        # ゴミ箱クリック
                        await trash_btn.click()
                    
                    else:
                        # アプローチ2: メニュー経由（ここはUI遷移が必要なためあまり短縮できません）
                        menu_btn_selectors = [
                            'button[aria-label="アクション メニュー"]',
                            'button[aria-label="Action menu"]',
                            '#menu-button button',
                            'yt-icon-button.dropdown-trigger'
                        ]
                        
                        menu_btn = None
                        for selector in menu_btn_selectors:
                            try:
                                btn = await target_video.query_selector(selector)
                                if btn and await btn.is_visible():
                                    menu_btn = btn
                                    break
                            except:
                                continue
                        
                        if menu_btn:
                            await menu_btn.click()
                            try:
                                menu_item = await page.wait_for_selector(
                                    'ytd-menu-service-item-renderer:has-text("削除"), ytd-menu-service-item-renderer:has-text("Remove")',
                                    timeout=2000
                                )
                                if menu_item:
                                    await menu_item.click()
                                else:
                                    consecutive_errors += 1
                                    await asyncio.sleep(0.5)
                                    continue
                            except:
                                consecutive_errors += 1
                                continue
                        else:
                            consecutive_errors += 1
                            await asyncio.sleep(0.5)
                            continue

                    # 削除成功後の処理
                    deleted_count += 1
                    consecutive_errors = 0
                    
                    # ★高速化ポイント2: 削除反映待ちを 1.2秒 -> 0.5秒 に短縮
                    # ※もし「クリックしたのに消えない」エラーが出る場合はここを 0.8 程度に戻してください
                    await asyncio.sleep(0.5) 

                except Exception as e:
                    # エラー時は少し待つ
                    consecutive_errors += 1
                    await asyncio.sleep(0.5)

                # 安全装置
                if consecutive_errors >= 10: # 許容回数を少し増やす
                    logger.error("  ❌ 連続エラーのため中断します")
                    print("\n  ❌ エラー: 削除操作が連続して失敗しました")
                    return False

        except Exception as e:
            logger.error(f"個別削除ループ全体のエラー: {e}")
            return False


    # ----------------------------------------------------------------
    # 新規追加: ツールバー操作による削除実行メソッド
    # ----------------------------------------------------------------
    
    async def delete_via_toolbar_action(self, page) -> bool:
        """
        GUIツールバーを使用した一括削除
        フロー: 全選択チェックボックス -> ゴミ箱アイコン -> ブラウザ確認ダイアログ(OK)
        """
        try:
            # プレイリスト管理画面であることを確認
            if "youtube.com/playlist" not in page.url:
                logger.warning(f"対象外のページです: {page.url}")
                return False

            logger.info("ツールバー操作による削除プロセスを開始します")
            print(f"  ...削除処理を実行中")

            # ページの読み込みを待つ
            await page.wait_for_load_state('networkidle', timeout=10000)
            await asyncio.sleep(2.0)  # 追加の待機時間

            # デバッグ: ページ内の要素を確認
            logger.debug("ページ内のチェックボックス要素を検索中...")
            
            # ---------------------------------------------------------
            # ステップ1: 全選択チェックボックスをクリック
            # ---------------------------------------------------------
            checkbox_selectors = [
                # 2024-2025年のYouTube UI用セレクター
                'ytd-playlist-header-renderer #checkbox',
                '#header-container #checkbox',
                'tp-yt-paper-checkbox#checkbox',
                '#checkbox.ytd-playlist-header-renderer',
                'ytd-playlist-header-renderer tp-yt-paper-checkbox',
                '#contents tp-yt-paper-checkbox',
                'tp-yt-paper-checkbox[aria-label="すべて選択"]',
                'tp-yt-paper-checkbox[aria-label="Select all"]',
                '[aria-label="すべて選択"]',
                '[aria-label="Select all"]',
                'ytd-browse[page-subtype="playlist"] #checkbox',
                '#playlist-action-menu tp-yt-paper-checkbox',
                '.metadata-action-bar tp-yt-paper-checkbox',
                '#header tp-yt-paper-checkbox',
            ]
            
            checkbox_clicked = False
            
            for selector in checkbox_selectors:
                try:
                    logger.debug(f"セレクター試行: {selector}")
                    checkbox = await page.wait_for_selector(selector, timeout=2000, state="visible")
                    if checkbox:
                        # チェックボックスの状態を確認
                        is_checked = await checkbox.get_attribute("aria-checked")
                        logger.info(f"チェックボックス発見: {selector}, 状態: {is_checked}")
                        
                        if is_checked != "true":
                            await checkbox.click()
                            logger.info(f"全選択チェックボックスをクリック: {selector}")
                        else:
                            logger.info("既に全選択されています")
                        checkbox_clicked = True
                        break
                except Exception as e:
                    logger.debug(f"セレクター {selector} で失敗: {e}")
                    continue
            
            if not checkbox_clicked:
                # デバッグ: ページ内のtp-yt-paper-checkbox要素をすべて検索
                try:
                    all_checkboxes = await page.query_selector_all('tp-yt-paper-checkbox')
                    logger.info(f"ページ内のチェックボックス数: {len(all_checkboxes)}")
                    
                    for i, cb in enumerate(all_checkboxes):
                        try:
                            aria_label = await cb.get_attribute('aria-label')
                            parent_tag = await cb.evaluate('el => el.parentElement ? el.parentElement.tagName : "none"')
                            logger.info(f"  チェックボックス {i+1}: aria-label={aria_label}, parent={parent_tag}")
                        except:
                            pass
                    
                    # 最初のチェックボックスを試す（ヘッダーの全選択の可能性）
                    if all_checkboxes and len(all_checkboxes) > 0:
                        first_checkbox = all_checkboxes[0]
                        is_visible = await first_checkbox.is_visible()
                        if is_visible:
                            await first_checkbox.click()
                            logger.info("最初のチェックボックスをクリックしました")
                            checkbox_clicked = True
                            
                except Exception as debug_e:
                    logger.debug(f"デバッグ検索エラー: {debug_e}")
            
            if not checkbox_clicked:
                # 動画一覧の有無を確認
                video_items = await page.query_selector_all('ytd-playlist-video-renderer')
                logger.info(f"動画アイテム数: {len(video_items)}")
                
                if len(video_items) == 0:
                    logger.info("動画が0件のため削除不要です")
                    return True  # 空のプレイリストは成功扱い
                
                logger.warning("全選択チェックボックスが見つかりません（動画が0件の可能性があります）")
                
                # HTMLをファイルに保存（デバッグ用）
                try:
                    html_content = await page.content()
                    debug_filename = f"debug_playlist_{int(time.time())}.html"
                    with open(debug_filename, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    logger.info(f"デバッグ用HTMLを保存: {debug_filename}")
                except Exception as save_e:
                    logger.debug(f"HTML保存エラー: {save_e}")
                
                return False

            # UIの反応待ち（ツールバーが表示されるまで）
            await asyncio.sleep(1.5)

            # ---------------------------------------------------------
            # ステップ2: ダイアログの自動承認準備 と ゴミ箱アイコンのクリック
            # ---------------------------------------------------------
            dialog_handled = False
            
            def handle_dialog(dialog):
                nonlocal dialog_handled
                logger.info(f"確認ダイアログを検出: {dialog.message}")
                print(f"  🔔 確認ダイアログを自動承認しました")
                dialog.accept()
                dialog_handled = True

            # リスナーを登録
            page.on("dialog", handle_dialog)

            # ゴミ箱/削除アイコンを探してクリック
            remove_button_selectors = [
                # 2024-2025年のYouTube UI用セレクター
                'ytd-playlist-video-list-renderer #top-level-buttons-computed button[aria-label*="削除"]',
                '#top-level-buttons-computed button[aria-label*="削除"]',
                'button[aria-label="再生リストから削除"]',
                'button[aria-label="プレイリストから削除"]',
                'button[aria-label="Remove from playlist"]',
                '[aria-label*="削除"]',
                '[aria-label*="Remove"]',
                'ytd-menu-renderer button[aria-label*="削除"]',
                '#actions-inner button[aria-label*="削除"]',
                '.dropdown-trigger-text:has-text("削除")',
                '#top-level-buttons button:has(yt-icon)',
                'ytd-button-renderer[style-action-button] button',
            ]
            
            remove_clicked = False
            
            for selector in remove_button_selectors:
                try:
                    logger.debug(f"削除ボタンセレクター試行: {selector}")
                    btn = await page.wait_for_selector(selector, timeout=2000, state="visible")
                    if btn:
                        logger.info(f"削除ボタン発見: {selector}")
                        await btn.click()
                        remove_clicked = True
                        break
                except Exception as e:
                    logger.debug(f"セレクター {selector} で失敗")
                    continue

            if not remove_clicked:
                # デバッグ: ボタン要素を検索
                try:
                    all_buttons = await page.query_selector_all('button')
                    logger.info(f"ページ内のボタン数: {len(all_buttons)}")
                    
                    for i, btn in enumerate(all_buttons[:20]):  # 最初の20個だけ
                        try:
                            aria_label = await btn.get_attribute('aria-label')
                            if aria_label:
                                logger.info(f"  ボタン {i+1}: aria-label={aria_label}")
                        except:
                            pass
                except Exception as debug_e:
                    logger.debug(f"ボタンデバッグエラー: {debug_e}")
                
                logger.error("ゴミ箱アイコンが見つからないか、クリックできませんでした")
                page.remove_listener("dialog", handle_dialog)
                return False

            # ダイアログが出るまで少し待機（非同期で処理されるためループで確認）
            for _ in range(10):  # 最大5秒待機
                if dialog_handled:
                    break
                await asyncio.sleep(0.5)
            
            # リスナー解除（クリーンアップ）
            page.remove_listener("dialog", handle_dialog)

            if dialog_handled:
                logger.info("✅ 削除処理完了")
                # 削除後の画面更新を少し待つ
                await asyncio.sleep(2.0)
                return True
            else:
                # ダイアログが出なかった場合でも、削除が実行された可能性がある
                logger.warning("⚠️ ダイアログが表示されませんでしたが、削除は実行された可能性があります")
                await asyncio.sleep(2.0)
                return True  # 成功扱いにする

        except Exception as e:
            logger.error(f"ツールバー削除エラー: {e}")
            import traceback
            traceback.print_exc()
            return False
            

    # ----------------------------------------------------------------
    # 修正版: Run メソッド
    # ----------------------------------------------------------------

    async def run(self, auto_start=False):
        """メイン処理（順次削除対応・完了タブ自動クローズ版）"""
        try:
            logger.info("=== YouTube Playlist Manager 開始 ===")
            
            # 1. 既存ブラウザに接続
            if not await self.connect_to_existing_browser():
                logger.error("ブラウザ接続に失敗")
                return
            
            # 2. 削除ダイアログを表示
            logger.info("プレイリスト選択画面を表示します")
            _, _, _, deletion_info = self.show_deletion_dialog(0, -1, auto_start=auto_start)
            
            if not deletion_info.get('selected_playlists'):
                logger.info("処理がキャンセルされました")
                print("処理を終了します")
                return

            selected_playlists = deletion_info['selected_playlists']
            mode = deletion_info.get('mode', 'manual')
            
            # 3. 選択されたプレイリストのタブを開く
            logger.info(f"{len(selected_playlists)}個のプレイリストタブを開きます...")
            tabs_opened = await self.open_playlist_tabs(selected_playlists)
            
            if not tabs_opened:
                logger.error("タブの生成に失敗しました")
                return

            # 4. モードによる分岐
            if mode == 'manual':
                # 手動モード: タブを開いた状態で終了
                logger.info("=== 手動モード: 完了 ===")
                print("\n✅ プレイリストタブを開きました。手動で操作してください。")
                return

            elif mode == 'auto':
                # 自動モード
                logger.info("=== 自動全削除モード: 順次削除を開始 ===")
                print("\n🤖 自動全削除モードを開始します")
                print("   (処理が完了したタブは自動的に閉じられます)")

                self.show_cancel_button()
                
                # 現在のページリストを取得（コピーを作成して安全に反復）
                pages = list(self.context.pages)
                success_count = 0
                
                # 開いたタブを順番に処理
                for i, page in enumerate(pages):
                    if self.cancel_operation:
                        print("\n⚠️ ユーザー中断により停止しました")
                        break

                    try:
                        # ページが既に閉じられていないか確認
                        if page.is_closed():
                            continue

                        # タブを前面に
                        await page.bring_to_front()
                        await asyncio.sleep(0.5)
                        
                        # プレイリストページか確認
                        if "youtube.com/playlist" not in page.url:
                            continue
                            
                        try:
                            title = await page.title()
                            clean_title = title.replace(" - YouTube", "")
                        except:
                            clean_title = "プレイリスト"

                        print(f"\n[{i+1}/{len(pages)}] 処理中: {clean_title}")
                        
                        # 個別削除を実行
                        result = await self.delete_videos_individually(page)
                        
                        print() # 改行
                        if result:
                            print(f"  ✅ {clean_title} の処理完了")
                            
                            # ★追加機能: 処理完了後にタブを閉じる
                            print(f"  🗑️ タブを閉じます...")
                            await asyncio.sleep(0.5) # 余韻を持たせる
                            await page.close()
                            
                            success_count += 1
                        else:
                            print(f"  ⚠️ {clean_title} の処理中断（タブは残します）")

                    except Exception as e:
                        logger.error(f"タブ処理中のエラー: {e}")

                self.close_cancel_button()
                print(f"\n{'='*40}")
                print(f"📊 全処理完了 (完了/全対象: {success_count}/{len(pages)})")
                print(f"{'='*40}")

        except Exception as e:
            logger.error(f"メイン処理エラー: {e}")
            self.close_cancel_button()
        
        finally:
            self.close_cancel_button()
            self.cleanup_dom_references()
            print("\nプログラムを終了します")
            await asyncio.sleep(0.5)


# リソース警告を抑制
warnings.filterwarnings("ignore", category=ResourceWarning)


# cleanup関数
async def cleanup(manager):
    """リソースのクリーンアップ"""
    try:
        logger.info("リソースのクリーンアップを開始...")
        if manager:
            manager.cleanup_dom_references()
            manager.close_cancel_button()
            
            # Playwrightの接続を適切にクローズ（ブラウザは閉じない）
            if manager.browser:
                try:
                    # 既存ブラウザへの接続を切断（ブラウザ自体は閉じない）
                    await manager.browser.close()
                except Exception as e:
                    logger.debug(f"ブラウザ切断時の警告（無視可能）: {e}")
                    
        logger.info("クリーンアップ完了")
    except Exception as e:
        logger.warning(f"クリーンアップ中のエラー: {e}")


# main関数（修正版）
async def main(auto_start=False):
    manager = None
    
    try:
        logger.info("=== YouTube Playlist Manager 開始 ===")
        
        # YouTubePlaylistManagerのインスタンスを作成
        manager = YouTubePlaylistManager()
        
        # run()メソッドを実行（クラス内で全ての処理を行う）
        await manager.run(auto_start=auto_start)
        
        logger.info("=== 処理終了 ===")
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # クリーンアップ処理
        await cleanup(manager)
        
        # 非同期タスクの完了を待つ
        await asyncio.sleep(0.5)
        
        print("\nプログラムを終了します")


# エントリーポイント
if __name__ == "__main__":
    # リソース警告を抑制
    warnings.filterwarnings("ignore", category=ResourceWarning)
    warnings.filterwarnings("ignore", message="unclosed transport")
    warnings.filterwarnings("ignore", message="I/O operation on closed pipe")
    
    # asyncioのデバッグ警告も抑制
    import logging as std_logging
    std_logging.getLogger("asyncio").setLevel(std_logging.CRITICAL)
    
    # コマンドライン引数の解析
    parser = argparse.ArgumentParser(description='YouTube Playlist Remover')
    parser.add_argument('--auto', action='store_true', help='Enable auto-start timer mode')
    args = parser.parse_args()
    
    try:
        asyncio.run(main(auto_start=args.auto))
    except KeyboardInterrupt:
        print("\n\nプログラムが中断されました")
    except Exception as e:
        logger.error(f"予期しないエラー: {e}")
        import traceback
        traceback.print_exc()