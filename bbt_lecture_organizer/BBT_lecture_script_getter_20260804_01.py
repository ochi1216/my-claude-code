#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BBT講義トランスクリプト抽出→Gemini自動送信統合ツール
"""

import os
import sys
import re
import time
import glob
import platform
import subprocess
import threading
import json
import urllib.request
import urllib.error
from datetime import datetime
from collections import OrderedDict

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import google.generativeai as genai

# ========== 追加: ログ出力用クラス ==========
class DualLogger:
    """標準出力とファイルを同時に書き込むためのクラス"""
    def __init__(self, filename):
        self.terminal = sys.stdout
        # 'w'モードで開くことで、実行のたびに上書きします
        self.log = open(filename, "w", encoding="utf-8", buffering=1)

    def write(self, message):
        try:
            self.terminal.write(message)
            self.log.write(message)
        except Exception:
            pass # エンコーディングエラー等の回避

    def flush(self):
        try:
            self.terminal.flush()
            self.log.flush()
        except Exception:
            pass
# ==========================================

# ========== VideoInfoクラス ==========
class VideoInfo:
    """動画情報を格納するシンプルなクラス"""
    
    def __init__(self, url, title="", duration="", tab_handle="", accessible=True, thumbnail_url=""):
        self.url = url
        self.title = title or self.extract_title_from_url(url)
        self.duration = duration or "取得失敗"
        self.tab_handle = tab_handle
        self.accessible = accessible
        self.thumbnail_url = thumbnail_url
    
    def extract_title_from_url(self, url):
        """URLから基本的なタイトルを抽出"""
        try:
            match = re.search(r'/content/(\d+)', url)
            if match:
                return f"講義_{match.group(1)}"
            return "不明な講義"
        except Exception:
            return "不明な講義"


# ========== TranscriptExtractorクラス ==========
class TranscriptExtractor:
    """メインのトランスクリプト抽出クラス"""
    
    def __init__(self, debug_port=9222):
        self.driver = None
        self.debug_port = debug_port
        self.target_url_pattern = "https://player.aircamp.us/content/"
        self.output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.connect_to_chrome()
    
    def connect_to_chrome(self):
        """既存のChromeブラウザに接続"""
        try:
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", f"localhost:{self.debug_port}")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            except ImportError:
                self.driver = webdriver.Chrome(options=chrome_options)
            
            print("✅ Chrome接続成功")
            return True
            
        except Exception as e:
            print(f"❌ Chrome接続エラー: {e}")
            raise

    def discover_videos(self):
        """Chrome上の全タブから動画を検出（ID順にソート）"""
        try:
            print("=== 動画検出開始 ===")
            discovered_videos = []
            original_handle = self.driver.current_window_handle
            
            # 全タブを巡回して情報を取得
            for handle in self.driver.window_handles:
                try:
                    self.driver.switch_to.window(handle)
                    current_url = self.driver.current_url
                    
                    if self.target_url_pattern in current_url:
                        print(f"動画発見: {current_url}")
                        video_info = self.extract_video_info(current_url, handle)
                        discovered_videos.append(video_info)
                        
                except Exception as e:
                    print(f"タブ処理エラー: {e}")
                    continue
            
            # 元のタブに戻る
            try:
                self.driver.switch_to.window(original_handle)
            except Exception:
                if self.driver.window_handles:
                    self.driver.switch_to.window(self.driver.window_handles[0])
            
            if discovered_videos:
                print("検出された動画をID順に並び替えています...")
                discovered_videos.sort(key=lambda v: self._get_video_sort_key(v.url))
            
            print(f"検出完了: {len(discovered_videos)}本")
            
            # 確認用ログ
            for i, v in enumerate(discovered_videos, 1):
                print(f"  {i}. {v.title} ({v.url[-15:]})")
                
            return discovered_videos
            
        except Exception as e:
            print(f"動画検出エラー: {e}")
            return []

    def _get_video_sort_key(self, url):
        """URLからソート用のキー（動画ID）を抽出する"""
        try:
            match = re.search(r'/content/(\d+)', url)
            if match:
                return int(match.group(1))
            return 0 
        except:
            return 0
  
    def extract_video_info(self, url, tab_handle):
        """動画の基本情報を取得（URLからIDも抽出）"""
        try:
            video_id = ""
            match = re.search(r'/content/(\d+)', url)
            if match:
                video_id = match.group(1)
            
            title = self.get_video_title()
            
            if video_id and video_id not in title:
                title = f"{title}_{video_id}"
            
            duration = self.get_video_duration()
            
            return VideoInfo(
                url=url,
                title=title,
                duration=duration,
                tab_handle=tab_handle,
                accessible=True
            )
            
        except Exception as e:
            print(f"動画情報取得エラー: {e}")
            return VideoInfo(url=url, tab_handle=tab_handle, accessible=False)

    def get_video_title(self):
        """動画タイトル取得"""
        try:
            main_title = ""
            sub_title = ""

            try:
                h5_selectors = [
                    'h5.MuiTypography-root.MuiTypography-h5',
                    'h5.MuiTypography-h5',
                    '#content h5',
                    'div.flex-grow-1 > h5'
                ]
                for selector in h5_selectors:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        text = element.text.strip()
                        if text and len(text) > 2:
                            main_title = text.replace('\n', ' ').replace('\r', '')
                            print(f"メインタイトル特定: {main_title}")
                            break
                    if main_title: break
            except Exception as e:
                print(f"メインタイトル取得エラー: {e}")

            try:
                h6_selectors = [
                    'h6.MuiTypography-root.MuiTypography-subtitle1',
                    'h6.MuiTypography-subtitle1',
                    '#content h6',
                    'div.flex-grow-1 > h6'
                ]
                for selector in h6_selectors:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        text = element.text.strip()
                        if text:
                            sub_title = text.replace('\n', ' ').replace('\r', '')
                            print(f"サブタイトル特定: {sub_title}")
                            break
                    if sub_title: break
            except Exception as e:
                print(f"サブタイトル取得エラー: {e}")

            if main_title:
                if sub_title:
                    return f"{main_title}_{sub_title}"
                return main_title

            try:
                breadcrumbs = self.driver.find_elements(By.CSS_SELECTOR, 'nav[aria-label="breadcrumb"] li, .MuiBreadcrumbs-li')
                if breadcrumbs:
                    last_crumb = breadcrumbs[-1].text.strip()
                    if len(last_crumb) > 2:
                        return last_crumb
            except:
                pass

            title_selectors = [
                '.series-title', '.program-title', 
                'h1', 'h2', '.title', '[class*="title"]'
            ]
            
            for selector in title_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        text = element.text.strip()
                        text = text.replace('\n', ' ').replace('\r', '')
                        text = ' '.join(text.split())
                        if text and 5 <= len(text) <= 100:
                            return text
                except:
                    continue
            
            page_title = self.driver.title
            if page_title:
                page_title = page_title.replace('\n', ' ').replace('\r', '')
                return page_title[:50]
            
            return "タイトル未取得"
            
        except Exception as e:
            print(f"タイトル取得処理エラー: {e}")
            return "タイトル取得失敗"

    def sanitize_filename(self, title, max_length=50):
        """ファイル名用に文字列をサニタイズ"""
        try:
            if not title:
                return "Unknown"
            
            title = title.replace('\n', ' ').replace('\r', ' ')
            title = title.replace('\t', ' ')
            title = ' '.join(title.split())
            
            forbidden_chars = {
                '/': '／', '\\': '￥', ':': '：', '*': '＊', 
                '?': '？', '"': '"', '<': '＜', '>': '＞', 
                '|': '｜', '〜': '～', '~': '～',
                '　': '_', ' ': '_'
            }
            
            sanitized = title
            for old_char, new_char in forbidden_chars.items():
                sanitized = sanitized.replace(old_char, new_char)
            
            while '__' in sanitized:
                sanitized = sanitized.replace('__', '_')
            
            sanitized = sanitized.strip('_ ')
            
            if len(sanitized) > max_length:
                sanitized = sanitized[:max_length].rstrip('_')
            
            if not sanitized:
                return "Unknown"
            
            return sanitized
            
        except Exception as e:
            print(f"ファイル名サニタイズエラー: {e}")
            return "Unknown"

    def get_video_duration(self):
        """動画時間を取得"""
        try:
            duration_selectors = [
                '.video-duration', '.duration', '[class*="duration"]', 
                '[class*="time"]', '.video-time', '.total-time',
                'span[class*="duration"]', 'div[class*="duration"]'
            ]
            
            for selector in duration_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        text = element.text.strip()
                        if re.match(r'^\d{1,3}:\d{2}(:\d{2})?$', text):
                            self.current_video_duration = text
                            return text
                        elif re.search(r'(\d+時間)?(\d+分)?(\d+秒)?', text):
                            hours = re.search(r'(\d+)時間', text)
                            minutes = re.search(r'(\d+)分', text)
                            seconds = re.search(r'(\d+)秒', text)
                            
                            h = int(hours.group(1)) if hours else 0
                            m = int(minutes.group(1)) if minutes else 0
                            s = int(seconds.group(1)) if seconds else 0
                            
                            if h or m or s:
                                formatted_time = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
                                self.current_video_duration = formatted_time
                                return formatted_time
                except Exception:
                    continue
            
            try:
                video_element = self.driver.find_element(By.TAG_NAME, 'video')
                duration = self.driver.execute_script("return arguments[0].duration", video_element)
                if duration and duration > 0:
                    hours = int(duration // 3600)
                    minutes = int((duration % 3600) // 60)
                    seconds = int(duration % 60)
                    formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
                    self.current_video_duration = formatted_time
                    return formatted_time
            except:
                pass
            
            self.current_video_duration = "時間未取得"
            return "時間未取得"
            
        except Exception as e:
            print(f"動画時間取得エラー: {e}")
            self.current_video_duration = "取得失敗"
            return "取得失敗"

    def get_thumbnail_url(self):
        """プレイヤーからサムネイル(poster)URLを取得"""
        try:
            # パターン1: <video poster="...">
            try:
                video_el = self.driver.find_element(By.TAG_NAME, 'video')
                poster = video_el.get_attribute('poster')
                if poster and poster.startswith('http'):
                    return poster
            except:
                pass
            
            # パターン2: <div class="vjs-poster" style="background-image: url(...)">
            try:
                poster_el = self.driver.find_element(By.CSS_SELECTOR, '.vjs-poster')
                style = poster_el.get_attribute('style')
                if style:
                    match = re.search(r'url\("?([^"]+)"?\)', style)
                    if match:
                        url = match.group(1)
                        if url.startswith('http'): return url
            except:
                pass
            
            return ""
        except Exception as e:
            print(f"サムネイル取得エラー: {e}")
            return ""

    def switch_to_video_tab(self, video_info):
        """指定された動画のタブに切り替え"""
        try:
            if video_info.tab_handle:
                self.driver.switch_to.window(video_info.tab_handle)
                return True
            
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                if self.driver.current_url == video_info.url:
                    video_info.tab_handle = handle
                    return True
            
            print(f"タブが見つかりません: {video_info.url}")
            return False
            
        except Exception as e:
            print(f"タブ切り替えエラー: {e}")
            return False

    def click_subtitle_tab(self):
        """字幕タブをクリック"""
        try:
            selectors = ['button', 'a', 'div[role="tab"]', '[class*="tab"]']
            
            for selector in selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    if element.text.strip() == '字幕' and element.is_displayed():
                        pre_click_html = self.driver.page_source[:1000]
                        
                        self.driver.execute_script("arguments[0].click();", element)
                        print("字幕タブクリック成功")
                        
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
                                    print(f"字幕データ読み込み確認 ({total_waited:.1f}秒)")
                                    time.sleep(1)
                                    return True
                        
                        print(f"字幕タブクリック後、最大待機時間到達 ({max_wait}秒)")
                        return True
            
            print("字幕タブが見つかりません")
            return False
            
        except Exception as e:
            print(f"字幕タブクリックエラー: {e}")
            return False

    def extract_transcript(self):
        """トランスクリプトデータを抽出（JavaScript直接取得方式）"""
        try:
            print("トランスクリプト抽出開始...")
            
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
                                result.push({ timestamp: timestamp, content: content });
                            }
                        }
                    } catch (e) {
                        console.log('Row parse error:', e);
                    }
                });
                return result;
            """)
            
            if not all_data:
                print("警告: JavaScriptで取得したデータが空です")
                return []
            
            seen_timestamps = set()
            transcript_data = []
            
            for item in all_data:
                timestamp = item.get('timestamp', '').strip()
                content = item.get('content', '').strip()
                
                if not timestamp or not content or ':' not in timestamp:
                    continue
                
                if timestamp not in seen_timestamps:
                    transcript_data.append({
                        'timestamp': timestamp,
                        'content': content
                    })
                    seen_timestamps.add(timestamp)
            
            if transcript_data:
                try:
                    transcript_data.sort(key=lambda x: self.parse_timestamp_to_seconds(x['timestamp']))
                except Exception as sort_error:
                    print(f"ソート警告: {sort_error}")
            
            print(f"抽出完了: {len(transcript_data)}件")
            return transcript_data
            
        except Exception as e:
            print(f"トランスクリプト抽出エラー: {e}")
            return []

    def extract_timetable(self):
        """講義のタイムテーブル（目次）を抽出"""
        try:
            print("タイムテーブル取得開始...")
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
                                    'topic': topic_str.strip(),
                                    'end_time': ""
                                })
                            for i in range(len(timetable_data) - 1):
                                timetable_data[i]['end_time'] = timetable_data[i + 1]['start_time']
                            if timetable_data:
                                timetable_data[-1]['end_time'] = "講義終了"
                            return timetable_data
            
            print("タイムテーブルが見つかりません")
            return []
            
        except Exception as e:
            print(f"タイムテーブル取得エラー: {e}")
            return []
    
    def normalize_time(self, time_str):
        if re.match(r'^\d{1,2}:\d{2}$', time_str):
            return f"{time_str}:00"
        elif re.match(r'^\d{1,2}:\d{2}:\d{2}$', time_str):
            return time_str
        return "00:00:00"

    def parse_timestamp_to_seconds(self, timestamp):
        parts = timestamp.split(':')
        if len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2: return int(parts[0]) * 60 + int(parts[1])
        return 0

    def calculate_completion_rate(self, last_timestamp, total_duration):
        try:
            last_seconds = self.parse_timestamp_to_seconds(last_timestamp)
            total_seconds = self.parse_timestamp_to_seconds(total_duration)
            if total_seconds > 0: return (last_seconds / total_seconds) * 100
        except: pass
        return 0
    
    def save_transcript_to_file(self, video_info, timetable, transcript):
        """トランスクリプトをテキストファイルに保存（RTOCS強調機能付き）"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = self.sanitize_filename(video_info.title)
            filename = f"BBT_Transcript_{safe_title}_{timestamp}.txt"
            filepath = os.path.join(self.output_dir, filename)
            
            # --- RTOCSの特定ロジック ---
            rtocs_start_sec = 0
            rtocs_end_timestamp = None
            
            for item in timetable:
                if "RTOCS" in item['topic'].upper() or "リアルタイムオンラインケーススタディ" in item['topic']:
                    rtocs_start_sec = self.parse_timestamp_to_seconds(item['start_time'])
                    break
            
            if rtocs_start_sec > 0:
                in_rtocs = False
                for item in transcript:
                    t_sec = self.parse_timestamp_to_seconds(item['timestamp'])
                    if not in_rtocs and t_sec >= rtocs_start_sec:
                        in_rtocs = True
                    
                    if in_rtocs:
                        content = item['content']
                        # RTOCS開始からCM/ブレイクタイムキーワードを検知して終了とする
                        if "ブレイクタイム" in content or "一息入れましょう" in content:
                            rtocs_end_timestamp = item['timestamp']
                            break

            with open(filepath, "w", encoding="utf-8") as f:
                f.write("="*80 + "\n")
                f.write("BBT講義トランスクリプト\n")
                f.write("="*80 + "\n\n")
                
                f.write("【講義情報】\n")
                f.write(f"タイトル: {video_info.title}\n")
                f.write(f"URL: {video_info.url}\n")
                f.write(f"時間: {video_info.duration}\n")
                f.write(f"抽出日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}\n")
                f.write("\n" + "="*80 + "\n\n")
                
                if timetable:
                    f.write("【目次（タイムライン）】\n")
                    f.write("-"*40 + "\n")
                    for i, item in enumerate(timetable, 1):
                        end_time = f" - {item['end_time']}" if item['end_time'] and item['end_time'] != "講義終了" else ""
                        f.write(f"{i:2d}. {item['start_time']}{end_time}\n")
                        f.write(f"    {item['topic']}\n\n")
                    f.write("="*80 + "\n\n")
                
                f.write("【トランスクリプト全文】\n")
                f.write("-"*40 + "\n")
                
                if transcript:
                    in_rtocs_block = False
                    for item in transcript:
                        t_sec = self.parse_timestamp_to_seconds(item['timestamp'])
                        
                        # RTOCS開始マーカー
                        if rtocs_start_sec > 0 and t_sec >= rtocs_start_sec and not in_rtocs_block and not rtocs_end_timestamp == item['timestamp']:
                            f.write("\n" + "="*60)
                            f.write("\n【ここからRTOCS（重点分析対象）セクション】\n")
                            f.write("="*60 + "\n")
                            in_rtocs_block = True
                        
                        # RTOCS終了マーカー（CM突入）
                        if in_rtocs_block and rtocs_end_timestamp and item['timestamp'] == rtocs_end_timestamp:
                            f.write(f"\n[{item['timestamp']}]\n{item['content']}\n")
                            f.write("\n" + "="*60)
                            f.write("\n【ここまでRTOCSセクション（以降のCM・宣伝は要約から除外すること）】\n")
                            f.write("="*60 + "\n")
                            in_rtocs_block = False
                            continue
                        
                        f.write(f"\n[{item['timestamp']}]\n{item['content']}\n")
                else:
                    f.write("\nトランスクリプトデータが取得できませんでした。\n")
                
                f.write("\n" + "="*80 + "\n")
                f.write("End of Transcript\n")
                f.write("="*80 + "\n")
            
            print(f"✅ 保存完了: {filename}")
            return filepath
            
        except Exception as e:
            print(f"保存エラー: {e}")
            return None

    def process_single_video(self, video_info):
        """単一動画の処理"""
        try:
            print(f"\n処理開始: {video_info.title}")
            
            if not self.switch_to_video_tab(video_info):
                raise Exception("タブ切り替え失敗")
            
            time.sleep(2)
            
            current_duration = self.get_video_duration()
            if current_duration != "時間未取得" and current_duration != "取得失敗":
                video_info.duration = current_duration
            
            # 追加: サムネイル取得
            video_info.thumbnail_url = self.get_thumbnail_url()
            if video_info.thumbnail_url:
                print(f"サムネイル取得: {video_info.thumbnail_url[:50]}...")
            
            subtitle_clicked = self.click_subtitle_tab()
            if not subtitle_clicked:
                print("警告: 字幕タブが見つかりません - トランスクリプト取得を試みます")
            
            transcript = self.extract_transcript()
            timetable = self.extract_timetable()
            
            if not transcript and not timetable:
                print("再試行中...")
                time.sleep(3)
                transcript = self.extract_transcript()
            
            filepath = self.save_transcript_to_file(video_info, timetable, transcript)
            
            if filepath:
                print(f"✅ 処理完了: {video_info.title}")
                return filepath
            else:
                return None
                
        except Exception as e:
            print(f"処理エラー ({video_info.title}): {e}")
            return None
    
    def process_multiple_videos(self, videos):
        results = []
        for i, video in enumerate(videos, 1):
            print(f"\n[{i}/{len(videos)}] 処理中...")
            filepath = self.process_single_video(video)
            results.append({
                'video': video,
                'filepath': filepath,
                'success': filepath is not None
            })
        return results
    
    def cleanup(self):
        print("Chrome接続を維持します")


# ========== VideoSelectionGUIクラス ==========
class VideoSelectionGUI:
    """動画選択GUI（5秒自動タイムアウト付き）"""
    
    def __init__(self, videos):
        self.videos = videos
        self.selected_videos = []
        self.root = None
        self.video_vars = []
        self.auto_start_timer = None 
        self.timer_cancelled = False 
        self.countdown_seconds = 5 
    
    def show_selection_dialog(self):
        try:
            self.root = tk.Tk()
            self.root.title("BBT講義選択")
            self.root.geometry("800x550") 
            
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after(100, lambda: self.root.attributes('-topmost', False))
            
            main_frame = ttk.Frame(self.root, padding="10")
            main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            
            title_frame = ttk.Frame(main_frame)
            title_frame.grid(row=0, column=0, pady=(0, 10))
            
            title_label = ttk.Label(title_frame, text="処理する講義を選択してください", font=("", 14, "bold"))
            title_label.pack()
            
            self.countdown_label = ttk.Label(
                title_frame,
                text=f"（{self.countdown_seconds}秒後に自動的に全て処理開始します）",
                font=("", 10),
                foreground="red"
            )
            self.countdown_label.pack(pady=(5, 0))
            
            canvas = tk.Canvas(main_frame)
            scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            select_all_var = tk.BooleanVar(value=True)
            select_all_cb = ttk.Checkbutton(
                scrollable_frame,
                text="全て選択",
                variable=select_all_var,
                command=lambda: self.toggle_all_selection(select_all_var)
            )
            select_all_cb.grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 10))
            
            select_all_cb.bind("<Button-1>", lambda e: self.cancel_auto_start())
            
            headers = ["選択", "タイトル", "時間", "URL"]
            for i, header in enumerate(headers):
                label = ttk.Label(scrollable_frame, text=header, font=("", 10, "bold"))
                label.grid(row=1, column=i, padx=5, pady=5, sticky=tk.W)
            
            self.video_vars = []
            for i, video in enumerate(self.videos):
                var = tk.BooleanVar(value=True)
                self.video_vars.append(var)
                
                cb = ttk.Checkbutton(scrollable_frame, variable=var)
                cb.grid(row=i+2, column=0, padx=5, pady=2)
                cb.bind("<Button-1>", lambda e: self.cancel_auto_start())
                
                title_label = ttk.Label(scrollable_frame, text=video.title[:50])
                title_label.grid(row=i+2, column=1, padx=5, pady=2, sticky=tk.W)
                
                duration_label = ttk.Label(scrollable_frame, text=video.duration)
                duration_label.grid(row=i+2, column=2, padx=5, pady=2)
                
                url_text = video.url[-40:] if len(video.url) > 40 else video.url
                url_label = ttk.Label(scrollable_frame, text=url_text)
                url_label.grid(row=i+2, column=3, padx=5, pady=2, sticky=tk.W)
            
            canvas.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            scrollbar.grid(row=1, column=1, sticky=(tk.N, tk.S))
            
            button_frame = ttk.Frame(main_frame)
            button_frame.grid(row=2, column=0, pady=(10, 0))
            
            cancel_button = ttk.Button(button_frame, text="キャンセル", command=self.cancel_selection)
            cancel_button.grid(row=0, column=0, padx=(0, 10))
            cancel_button.bind("<Button-1>", lambda e: self.cancel_auto_start())
            
            execute_button = ttk.Button(button_frame, text="処理開始", command=self.confirm_selection)
            execute_button.grid(row=0, column=1)
            execute_button.bind("<Button-1>", lambda e: self.cancel_auto_start())
            
            self.root.columnconfigure(0, weight=1)
            self.root.rowconfigure(0, weight=1)
            main_frame.columnconfigure(0, weight=1)
            main_frame.rowconfigure(1, weight=1)
            
            self.root.geometry("+{}+{}".format(
                (self.root.winfo_screenwidth() // 2) - 400,
                (self.root.winfo_screenheight() // 2) - 275
            ))
            
            self.root.bind("<Key>", lambda e: self.cancel_auto_start())
            self.root.bind("<Button-1>", lambda e: self.cancel_auto_start())
            
            self.start_auto_countdown()
            self.root.mainloop()
            
            return self.selected_videos

        except Exception as e:
            print(f"GUI表示エラー: {e}")
            return self.videos
    
    def start_auto_countdown(self):
        if self.timer_cancelled:
            return
        
        if self.countdown_seconds > 0:
            self.countdown_label.config(text=f"（{self.countdown_seconds}秒後に自動的に全て処理開始します）")
            self.countdown_seconds -= 1
            self.auto_start_timer = self.root.after(1000, self.start_auto_countdown)
        else:
            print("⏰ 5秒経過：自動的に全動画の処理を開始します")
            self.auto_confirm_selection()
    
    def cancel_auto_start(self):
        if not self.timer_cancelled:
            self.timer_cancelled = True
            if self.auto_start_timer:
                self.root.after_cancel(self.auto_start_timer)
                self.auto_start_timer = None
            self.countdown_label.config(text="（手動選択モード）", foreground="gray")
            print("タイマーキャンセル：手動選択モードに切り替え")
    
    def auto_confirm_selection(self):
        self.selected_videos = []
        for i, var in enumerate(self.video_vars):
            if var.get():
                self.selected_videos.append(self.videos[i])
        
        if self.selected_videos:
            self.root.destroy()
        else:
            self.selected_videos = self.videos
            self.root.destroy()
    
    def toggle_all_selection(self, select_all_var):
        state = select_all_var.get()
        for var in self.video_vars: var.set(state)
    
    def confirm_selection(self):
        self.cancel_auto_start()
        self.selected_videos = []
        for i, var in enumerate(self.video_vars):
            if var.get(): self.selected_videos.append(self.videos[i])
        
        if not self.selected_videos:
            messagebox.showwarning("警告", "少なくとも1つの動画を選択してください")
            return
        self.root.destroy()
    
    def cancel_selection(self):
        self.cancel_auto_start()
        self.selected_videos = []
        self.root.destroy()
    
# ========== ModeSelectionGUI クラス ==========
class ModeSelectionGUI:
    """起動時のモード選択ダイアログ（ラジオボタン）"""

    def __init__(self):
        self.mode = None
        self.root = None

    def show(self):
        """
        モード選択ダイアログを表示する。
        Returns:
            str | None: 'new'（新方式）, 'search'（検索結果方式）,
                        'legacy'（従来方式）, または None（キャンセル）
        """
        try:
            self.root = tk.Tk()
            self.root.title("BBT要約ツール - モード選択")
            self.root.geometry("520x430")
            self.root.resizable(False, False)

            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            self.root.geometry(f"+{screen_w // 2 - 260}+{screen_h // 2 - 215}")
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after(100, lambda: self.root.attributes('-topmost', False))

            main_frame = ttk.Frame(self.root, padding="20")
            main_frame.pack(fill=tk.BOTH, expand=True)

            ttk.Label(main_frame, text="実行モードを選択してください",
                      font=("", 12, "bold")).pack(pady=(0, 15))

            mode_var = tk.StringVar(value='new')

            new_frame = ttk.LabelFrame(main_frame, padding="8")
            new_frame.pack(fill=tk.X, pady=(0, 8))
            ttk.Radiobutton(new_frame,
                            text="最新コンテンツ一覧から選択（新方式）",
                            variable=mode_var, value='new').pack(anchor=tk.W)
            ttk.Label(new_frame,
                      text="BBTサイトの最新コンテンツ30件をスキャンし、GUIで選択して要約します",
                      font=("", 9), foreground="#555555").pack(anchor=tk.W)

            # ★新規: 検索結果一覧から選択（キーワード検索方式）
            search_frame = ttk.LabelFrame(main_frame, padding="8")
            search_frame.pack(fill=tk.X, pady=(0, 8))
            ttk.Radiobutton(search_frame,
                            text="検索結果一覧から選択（キーワード検索方式）",
                            variable=mode_var, value='search').pack(anchor=tk.W)
            ttk.Label(search_frame,
                      text="開いているBBT検索結果タブから全件スキャンし、GUIで選択して要約します",
                      font=("", 9), foreground="#555555").pack(anchor=tk.W)

            legacy_frame = ttk.LabelFrame(main_frame, padding="8")
            legacy_frame.pack(fill=tk.X, pady=(0, 15))
            ttk.Radiobutton(legacy_frame,
                            text="開いているタブから選択（従来方式）",
                            variable=mode_var, value='legacy').pack(anchor=tk.W)
            ttk.Label(legacy_frame,
                      text="現在Chromeで開いているBBT動画タブを検出して要約します",
                      font=("", 9), foreground="#555555").pack(anchor=tk.W)

            btn_frame = ttk.Frame(main_frame)
            btn_frame.pack()

            def on_execute():
                self.mode = mode_var.get()
                self.root.destroy()

            def on_cancel():
                self.mode = None
                self.root.destroy()

            ttk.Button(btn_frame, text="キャンセル",
                       command=on_cancel).grid(row=0, column=0, padx=(0, 10))
            ttk.Button(btn_frame, text="  実行  ",
                       command=on_execute).grid(row=0, column=1)

            self.root.protocol("WM_DELETE_WINDOW", on_cancel)
            self.root.mainloop()
            return self.mode

        except Exception as e:
            print(f"ModeSelectionGUI エラー: {e}")
            return None


# ========== ContentListScraper クラス ==========
class ContentListScraper:
    """BBT最新コンテンツページから最大30件のメタデータを取得するクラス"""

    LIST_URL = (
        "https://www.bbt757.com/svlAirSearch/search"
        "?subCatId=939"
        "&subCatName=%E6%9C%80%E6%96%B0%E3%82%B3%E3%83%B3%E3%83%86%E3%83%B3%E3%83%84"
        "&catName=%E6%9C%80%E6%96%B0%E3%82%B3%E3%83%B3%E3%83%86%E3%83%B3%E3%83%84"
        "&isParent=false&start=1&num=30"
    )
    TARGET_KEYWORD = "subCatId=939"
    STOP_AFTER_CONSECUTIVE_KNOWN = 3   # ★新規: 要約済みがこの件数連続したら早期終了（越智さん承認済み・固定値）

    def find_or_open_list_tab(self, driver):
        """
        既存ChromeタブからBBT最新コンテンツページを検索する。
        見つからない場合は新しいタブで開く。
        Args:
            driver: Selenium WebDriver（デバッグモードで接続済み）
        Returns:
            bool: 成功時 True
        """
        try:
            # 既存タブを検索
            for handle in driver.window_handles:
                try:
                    driver.switch_to.window(handle)
                    if self.TARGET_KEYWORD in driver.current_url:
                        print(f"✅ BBT最新コンテンツタブを発見: {driver.current_url[:60]}...")
                        return True
                except Exception:
                    continue

            # 見つからない場合は新しいタブで開く
            print("BBT最新コンテンツタブが見つかりません。新規タブで開きます...")
            driver.switch_to.new_window('tab')
            driver.get(self.LIST_URL)

            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div.itemAdd.program')))
            print("✅ BBT最新コンテンツページを開きました")
            return True

        except Exception as e:
            print(f"❌ find_or_open_list_tab エラー: {e}")
            import traceback
            traceback.print_exc()
            return False


    # ── scrape_content_list() 56行（要約済み3件連続検出による早期終了対応） ──
    def scrape_content_list(self, driver, progress_callback=None, history_manager=None):
        """
        BBT最新コンテンツを全ページ取得する（ページネーション自動巡回）。
        Args:
            driver: Selenium WebDriver（対象ページを開いた状態）
            progress_callback (callable | None):
                進捗通知コールバック。signature: callback(page, total_found) -> None
            history_manager (SummaryHistoryManager | None): ★新規
                要約履歴管理オブジェクト。渡された場合、ページ内のコンテンツを
                新→旧の順に確認し、要約済みが STOP_AFTER_CONSECUTIVE_KNOWN 件
                連続した時点でそれ以降のページ取得を打ち切る
                （越智さん承認済み: 新規コンテンツは無いと判断できるため）。
                None の場合はこの判定を行わず、従来通り全ページ取得する。
        Returns:
            list[dict]: 全ページ分のコンテンツ情報リスト
        """
        all_contents = []
        page_num     = 1
        start        = 1

        print("BBT最新コンテンツ一覧をスキャン中（全件取得モード）...")

        while True:
            # startパラメータを更新してページURLを構築し遷移
            paged_url = (
                self.LIST_URL.split('&start=')[0]
                + f"&start={start}&num=30"
            )
            print(f"  ページ {page_num} をスキャン中... (start={start})")
            driver.get(paged_url)

            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, 'div.itemAdd.program')))
                time.sleep(1)
            except TimeoutException:
                print(f"  ページ {page_num}: コンテンツ要素が見つかりません（終了）")
                break

            # 現在ページのコンテンツを抽出
            page_contents = self._scrape_current_page(driver)
            print(f"  ページ {page_num}: {len(page_contents)}件取得")

            if not page_contents:
                print("  取得件数0件のため終了")
                break

            all_contents.extend(page_contents)

            # 進捗コールバックへ通知
            if progress_callback:
                progress_callback(page_num, len(all_contents))

            # ★新規: 要約済みが3件連続したら早期終了する
            # （history_manager が渡されている場合のみ判定する）
            if history_manager is not None:
                consecutive_known = 0
                stop_early = False
                for item in page_contents:
                    if history_manager.is_summarized(item['program_id']):
                        consecutive_known += 1
                        if consecutive_known >= self.STOP_AFTER_CONSECUTIVE_KNOWN:
                            stop_early = True
                            break
                    else:
                        consecutive_known = 0

                if stop_early:
                    print(f"  ⏹️ 要約済みコンテンツが"
                          f"{self.STOP_AFTER_CONSECUTIVE_KNOWN}件連続したため、"
                          f"スキャンを終了します")
                    break

            # 最終ページ判定
            if self._is_last_page(driver):
                print(f"  最終ページ到達（ページ {page_num}）")
                break

            start    += 30
            page_num += 1

        print(f"✅ スキャン完了: 全{page_num}ページ / {len(all_contents)}件取得")
        return all_contents




    # ── _scrape_current_page() 新規 22行 ──
    def _scrape_current_page(self, driver):
        """
        現在表示中のページから div.itemAdd.program を全件抽出して返す。
        Args:
            driver: Selenium WebDriver
        Returns:
            list[dict]: 有効なコンテンツ情報のリスト（program_id が '0' のものは除外）
        """
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, 'div.itemAdd.program')
            contents = []
            for card in cards:
                item = self._extract_content_metadata(card)
                if item and item.get('program_id') and item['program_id'] != '0':
                    contents.append(item)
            return contents
        except Exception as e:
            print(f"  _scrape_current_page エラー: {e}")
            return []

    # ── _is_last_page() 新規 15行 ──
    def _is_last_page(self, driver):
        """
        Nextボタンが disabled クラスを持つか、Nextボタン自体が存在しない場合に
        最終ページと判定する。
        Args:
            driver: Selenium WebDriver
        Returns:
            bool: 最終ページなら True
        """
        try:
            next_li = driver.find_element(
                By.CSS_SELECTOR, 'li.page-item.next')
            classes = next_li.get_attribute('class') or ''
            return 'disabled' in classes
        except NoSuchElementException:
            # Nextボタンが存在しない = 最終ページ
            return True
        except Exception as e:
            print(f"  _is_last_page エラー（最終ページとみなす）: {e}")
            return True

    def _extract_content_metadata(self, card):
        """
        1件のカード要素（div.itemAdd.program）からメタデータを抽出する。
        Args:
            card: WebElement
        Returns:
            dict | None
        """
        try:
            # program_id: a.card-img-top の data-program-id 属性
            program_id = ""
            video_url = ""
            try:
                link_el = card.find_element(By.CSS_SELECTOR, 'a.card-img-top')
                program_id = link_el.get_attribute('data-program-id') or ""
                video_url = link_el.get_attribute('href') or ""
            except Exception:
                pass

            if not program_id or program_id == '0':
                return None

            # タイトル: h3.prg-title > a のテキスト
            title = ""
            try:
                title_el = card.find_element(By.CSS_SELECTOR, 'h3.prg-title a')
                title = title_el.text.strip()
            except Exception:
                pass

            # サブタイトル: div.prg-theme > h3 のテキスト
            sub_title = ""
            try:
                sub_el = card.find_element(By.CSS_SELECTOR, 'div.prg-theme h3')
                sub_title = sub_el.text.strip()
            except Exception:
                pass

            # 動画時間: span.program-duration
            duration = ""
            try:
                dur_el = card.find_element(By.CSS_SELECTOR, 'span.program-duration')
                duration = dur_el.text.strip()
            except Exception:
                pass

            # 配信予定日: span.release-date（未公開コンテンツのみ存在）
            release_date = ""
            try:
                date_el = card.find_element(By.CSS_SELECTOR, 'span.release-date')
                release_date = date_el.text.strip()
            except Exception:
                pass

            # サムネイルURL: img.img-fit-content の src 属性
            thumbnail_url = ""
            try:
                img_el = card.find_element(By.CSS_SELECTOR, 'img.img-fit-content')
                thumbnail_url = img_el.get_attribute('src') or ""
            except Exception:
                pass

            # ★新規: 講師名（「講師：」を含む段落内の <a> から取得）
            # 検索結果一覧側で確認済みの構造を流用。最新コンテンツ側の実際の
            # DOM構造は未確認のため、取得できない場合は空文字のまま継続する。
            lecturer_name = ""
            try:
                lecturer_els = card.find_elements(
                    By.XPATH, ".//p[contains(., '講師')]//a")
                for el in lecturer_els:
                    text = el.text.strip()
                    if text:
                        lecturer_name = text
                        break
            except Exception:
                pass

            return {
                'program_id': program_id,
                'title': title or f"講義_{program_id}",
                'sub_title': sub_title,
                'video_url': video_url,
                'duration': duration,
                'release_date': release_date,
                'thumbnail_url': thumbnail_url,
                'lecturer_name': lecturer_name,
            }

        except Exception as e:
            print(f"  _extract_content_metadata エラー: {e}")
            return None


# ========== SearchResultScraper クラス（新規） ==========
class SearchResultScraper:
    """
    BBTキーワード検索結果ページ（.../svlAirSearch/search-content?keyword=...）
    から講義一覧を取得するクラス。

    このページはページ送りが存在せず、スクロールに応じてコンテンツが
    追加読み込みされる「無限スクロール型」構造のため、ContentListScraper
    とは別クラスとして実装する。データモデル（返却する dict のキー）は
    ContentListScraper と完全互換とし、下流処理（ContentSelectionGUI 等）
    をそのまま共用できるようにする。
    """
    TARGET_KEYWORDS       = ["search-content", "search-by-keyword"]  # ★変更: アクティブタブ判定用のURLパターン（OR条件）
    MAX_ITEMS            = 200                # 安全上限（越智さん承認済み）
    MAX_STABLE_ROUNDS    = 3                  # 件数が増えなくなったと判定するまでの継続回数
    SCROLL_PAUSE         = 1.5                # スクロール後の待機秒数
    MIN_DURATION_MINUTES = 10                 # ★新規: 10分未満（広告用抜粋動画）除外の閾値（固定値・越智さん承認済み）
    

    def find_active_search_tab(self, driver):
        """
        現在Chromeで開いているタブの中から、search-content または
        search-by-keyword（検索結果）を含むページを検索し、
        見つかった場合はそのタブへ切り替える。

        Args:
            driver: Selenium WebDriver（デバッグモードで接続済み）
        Returns:
            bool: 検索結果ページが見つかり切り替えできた場合 True、
                  見つからなかった場合 False
        """
        try:
            # まずは現在アクティブなタブを確認
            try:
                if any(kw in driver.current_url for kw in self.TARGET_KEYWORDS):
                    print(f"✅ 検索結果ページを確認: {driver.current_url[:60]}...")
                    return True
            except Exception:
                pass

            # アクティブタブが該当しない場合は、開いている全タブを走査する
            original_handle = driver.current_window_handle
            for handle in driver.window_handles:
                try:
                    driver.switch_to.window(handle)
                    if any(kw in driver.current_url for kw in self.TARGET_KEYWORDS):
                        print(f"✅ 検索結果タブを発見: {driver.current_url[:60]}...")
                        return True
                except Exception:
                    continue

            # 見つからなかった場合は元のタブへ戻してFalseを返す
            try:
                driver.switch_to.window(original_handle)
            except Exception:
                if driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])

            print("❌ 検索結果ページ（search-content / search-by-keyword）が見つかりませんでした")
            return False

        except Exception as e:
            print(f"❌ find_active_search_tab エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ── _duration_to_minutes() 新規（10分未満フィルタ用ヘルパー） ──
    def _duration_to_minutes(self, duration_str):
        """
        duration文字列を分単位の数値に変換する。

        duration には以下の2パターンが混在する:
          - "MM:SS" 形式（span.program-duration 由来。例: "63:20"）
          - "N分"   形式（video-details module のフォールバック抽出由来。例: "60分"）

        Args:
            duration_str (str): 変換対象の文字列
        Returns:
            float | None: 分単位の数値。いずれのパターンにも一致しない
                          場合は None（不明）を返す。
        """
        if not duration_str:
            return None

        text = duration_str.strip()

        # パターン1: "MM:SS"（分:秒）
        match = re.match(r'^(\d+):(\d{2})$', text)
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            return minutes + seconds / 60.0

        # パターン2: "N分"
        match = re.match(r'^(\d+)分$', text)
        if match:
            return float(match.group(1))

        return None



    # ── scrape_content_list() 無限スクロール対応（history_manager引数追加） ──
    def scrape_content_list(self, driver, progress_callback=None, history_manager=None):
        """
        検索結果ページを無限スクロールで巡回し、全件のメタデータを取得する。
        `data-program-id` の総数を監視し、MAX_STABLE_ROUNDS 回連続で
        件数が増加しなくなった時点、または MAX_ITEMS 件に達した時点で終了する。

        Args:
            driver: Selenium WebDriver（検索結果ページを開いた状態）
            progress_callback (callable | None):
                進捗通知コールバック。signature: callback(round, total_found) -> None
            history_manager (SummaryHistoryManager | None): ★新規
                共用ヘルパー _show_scan_progress() とのインターフェース整合のために
                受け取るのみで、本メソッド内では使用しない
                （越智さん承認済み: 今回のフィルタはContentListScraper側限定のため）。
        Returns:
            list[dict]: 取得できたコンテンツ情報のリスト
        """
        print("BBT検索結果ページをスキャン中（無限スクロールモード）...")
        stable_rounds = 0
        prev_count    = 0
        round_num     = 0

        while True:
            round_num += 1
            try:
                program_ids = driver.execute_script(
                    "return Array.from(document.querySelectorAll('[data-program-id]'))"
                    ".map(el => el.getAttribute('data-program-id'));"
                )
            except Exception as e:
                print(f"  program_id取得エラー（終了）: {e}")
                break

            current_count = len(set(
                pid for pid in program_ids if pid and pid != '0'))

            print(f"  ラウンド{round_num}: 累計{current_count}件検出")
            if progress_callback:
                progress_callback(round_num, current_count)

            if current_count >= self.MAX_ITEMS:
                print(f"  安全上限（{self.MAX_ITEMS}件）に到達したため終了")
                break

            if current_count == prev_count:
                stable_rounds += 1
                if stable_rounds >= self.MAX_STABLE_ROUNDS:
                    print(f"  {self.MAX_STABLE_ROUNDS}回連続で件数増加なし。終了")
                    break
            else:
                stable_rounds = 0

            prev_count = current_count

            try:
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);")
            except Exception as e:
                print(f"  スクロールエラー（終了）: {e}")
                break

            time.sleep(self.SCROLL_PAUSE)

        # 最終的に画面上の全カードからメタデータを抽出する
        contents      = []
        seen_ids      = set()
        skipped_short = 0
        try:
            sections = driver.find_elements(
                By.CSS_SELECTOR, 'section[data-program-id]')
        except Exception as e:
            print(f"  カード要素取得エラー: {e}")
            sections = []

        for section in sections:
            item = self._extract_content_metadata(section)
            if not (item and item.get('program_id')
                    and item['program_id'] != '0'
                    and item['program_id'] not in seen_ids):
                continue

            # ★新規: 10分未満（広告用抜粋動画）の除外フィルタ
            # duration不明の場合も除外する（越智さん承認済み: ①②とも除外）
            minutes = self._duration_to_minutes(item.get('duration', ''))
            if minutes is None or minutes < self.MIN_DURATION_MINUTES:
                skipped_short += 1
                print(f"  ⏭️ 10分未満のためスキップ: "
                      f"{item.get('title', '')}"
                      f"（{item.get('duration') or '不明'}）")
                continue

            seen_ids.add(item['program_id'])
            contents.append(item)

        if skipped_short:
            print(f"  ⏭️ 10分未満/不明のため除外: {skipped_short}件")

        print(f"✅ スキャン完了: {len(contents)}件取得")
        return contents

    # ── _extract_content_metadata() 新規（フォールバック抽出） ──
    def _extract_content_metadata(self, section):
        """
        1件の講義セクション（section[data-program-id]）からメタデータを
        抽出する。

        タイトルは description-component-one / description-component-two
        のどちらに実データが入るかがコンテンツ種別によって不定であるため、
        複数の候補セレクタを順に試し、最初に非空となった値を採用する
        フォールバック方式とする。

        Args:
            section: WebElement（section[data-program-id]）
        Returns:
            dict | None: ContentListScraper と共通のスキーマを持つ辞書
        """
        try:
            program_id = section.get_attribute('data-program-id') or ""
            if not program_id or program_id == '0':
                return None

            # 動画URL: program_id から直接組み立てる（DOM構造への依存を避ける）
            video_url = f"https://player.aircamp.us/content/{program_id}"

            # タイトル: 複数候補セレクタを順に試すフォールバック方式
            title = ""
            title_selectors = ['span.prg-title', 'a > span.h3', 'span.h3']
            for sel in title_selectors:
                try:
                    for el in section.find_elements(By.CSS_SELECTOR, sel):
                        text = el.text.strip()
                        if text:
                            title = text
                            break
                    if title:
                        break
                except Exception:
                    continue

            # サブタイトル: div.video-details.module > span.hidden-mobile の
            # 直接の子テキストノードのみを抽出する（越智さん承認済み）。
            # 入れ子の <p>（講師・ゲスト情報等）は個数・有無がコンテンツ
            # 種別により不定（0〜2個、Image1〜3で確認済み）であるため、
            # 改行分割ではなく、DOM上「要素ノードではなくテキストノードの
            # みを対象とする」ことで <p> の内容を一律に除外する。
            # 取得できない場合は既存仕様通り空文字のまま（表示側で非表示扱い）。
            sub_title = ""
            try:
                span_el = section.find_element(
                    By.CSS_SELECTOR,
                    'div.video-details.module > span.hidden-mobile')
                sub_title = section.parent.execute_script(
                    """
                    const el = arguments[0];
                    let text = '';
                    for (const node of el.childNodes) {
                        if (node.nodeType === Node.TEXT_NODE) {
                            text += node.textContent;
                        }
                    }
                    return text.trim();
                    """,
                    span_el
                ) or ""
            except Exception:
                pass

            # 講師名: 「講師」を含む段落内の <a> から取得
            # （複数講師・自由記述の場合は取得されず空文字のまま。
            #   表示側でハイフン表記に変換する：越智さん承認済み）
            lecturer_name = ""
            try:
                for el in section.find_elements(
                        By.XPATH, ".//p[contains(., '講師')]//a"):
                    text = el.text.strip()
                    if text:
                        lecturer_name = text
                        break
            except Exception:
                pass

            # 配信日: video-details module ブロック内のテキストを
            # 正規表現で抽出する（class属性が "classname" という非標準表記
            # のため、クラス名依存ではなくテキストパターンマッチで対応）
            release_date = ""
            try:
                for detail_el in section.find_elements(
                        By.CSS_SELECTOR, '.video-details.module'):
                    text = detail_el.text.strip()
                    if not text:
                        continue
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                    if date_match:
                        release_date = date_match.group(1)
                        break
            except Exception:
                pass

            # 収録時間: span.program-duration（例："63:20"）を優先採用する。
            # ContentListScraper（最新コンテンツ側）と同一セレクタのため、
            # 両スクレイパー間で収録時間の表記形式が統一される。
            # 取得できない場合のみ、video-details module 側のテキストから
            # 「収録時間：60分」形式を正規表現でフォールバック抽出する。
            duration = ""
            try:
                dur_el = section.find_element(
                    By.CSS_SELECTOR, 'span.program-duration')
                duration = dur_el.text.strip()
            except Exception:
                pass

            if not duration:
                try:
                    for detail_el in section.find_elements(
                            By.CSS_SELECTOR, '.video-details.module'):
                        text = detail_el.text.strip()
                        if not text:
                            continue
                        dur_match = re.search(r'収録時間[：:]\s*(\d+分)', text)
                        if dur_match:
                            duration = dur_match.group(1)
                            break
                except Exception:
                    pass

            # サムネイルURL: div.images-component 内の img.none-blur から取得する。
            # 当該画像は lazyload 方式のため、読み込み前は src がプレースホルダー
            # 画像になっている可能性がある。実URLは data-src にも格納されている
            # ため、data-src を優先し、取得できない場合のみ src にフォールバック
            # する。
            thumbnail_url = ""
            try:
                img_el = section.find_element(
                    By.CSS_SELECTOR, 'div.images-component img.none-blur')
                thumbnail_url = (img_el.get_attribute('data-src')
                                  or img_el.get_attribute('src') or "")
            except Exception:
                pass

            return {
                'program_id':    program_id,
                'title':         title or f"講義_{program_id}",
                'sub_title':     sub_title,
                'video_url':     video_url,
                'duration':      duration,
                'release_date':  release_date,
                'thumbnail_url': thumbnail_url,
                'lecturer_name': lecturer_name,
            }

        except Exception as e:
            print(f"  _extract_content_metadata エラー: {e}")
            return None



# ========== SummaryHistoryManager クラス ==========
class SummaryHistoryManager:
    """要約済みコンテンツをJSONファイルで管理するクラス"""

    HISTORY_FILE = r"C:\Users\nx023836\Documents\PythonScripts\bbt\bbt_summary_history.json"

    def __init__(self):
        self._data = self._load()

    def _load(self):
        """JSONファイルから履歴を読み込む。ファイルが存在しない場合は空構造を返す。"""
        try:
            if os.path.exists(self.HISTORY_FILE):
                with open(self.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if 'summaries' not in data:
                    data['summaries'] = {}
                return data
            return {'version': '1.0', 'last_updated': '', 'summaries': {}}
        except Exception as e:
            print(f"⚠️ 履歴ファイル読み込みエラー（新規作成します）: {e}")
            return {'version': '1.0', 'last_updated': '', 'summaries': {}}

    def save(self):
        """現在の履歴データをJSONファイルに保存する。"""
        try:
            self._data['last_updated'] = datetime.now().isoformat()
            os.makedirs(os.path.dirname(self.HISTORY_FILE), exist_ok=True)
            with open(self.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            print(f"✅ 履歴保存完了: {self.HISTORY_FILE}")
        except Exception as e:
            print(f"❌ 履歴保存エラー: {e}")

    def is_summarized(self, program_id):
        """
        指定のprogram_idが要約済みかどうかを返す。
        Args:
            program_id (str): 講義ID
        Returns:
            bool
        """
        return str(program_id) in self._data['summaries']

    def get_summarized_at(self, program_id):
        """要約実施日時を返す。未要約の場合は空文字列。"""
        entry = self._data['summaries'].get(str(program_id), {})
        return entry.get('summarized_at', '')

    def mark_summarized(self, program_id, metadata):
        """
        指定のprogram_idを要約済みとして登録し、即座にJSONへ保存する。
        Args:
            program_id (str): 講義ID
            metadata (dict): 追加で保存するメタデータ（title, html_file 等）
        """
        self._data['summaries'][str(program_id)] = {
            'program_id': str(program_id),
            'summarized_at': datetime.now().isoformat(),
            **metadata,
        }
        self.save()

    def get_all(self):
        """全履歴データの summaries 辞書を返す。"""
        return self._data.get('summaries', {})


# ========== ContentSelectionGUI クラス ==========
class ContentSelectionGUI:
    """最新コンテンツ一覧の選択UI（Treeview + チェックボックス）"""

    COL_CHECK = 'check'
    COL_DONE  = 'done'
    COL_TITLE = 'title'
    COL_SUB   = 'sub_title'
    COL_DUR   = 'duration'
    COL_DATE  = 'release_date'

    # ── __init__() 20行 ──
    def __init__(self, contents, history_manager, chrome_driver, execute_callback=None):
        """
        Args:
            contents (list[dict]): ContentListScraper.scrape_content_list() の戻り値
            history_manager (SummaryHistoryManager): 要約履歴管理オブジェクト
            chrome_driver: Selenium WebDriver
            execute_callback (callable | None): 要約開始時に呼ぶコールバック関数
                signature: callback(selected_contents: list[dict]) -> None
        """
        self.contents                  = contents
        self.history                   = history_manager
        self.driver                    = chrome_driver
        self.execute_callback          = execute_callback       # ★新規
        self.selected_contents         = []
        self.root                      = None
        self.tree                      = None
        self._check_states             = {}
        self._sort_col                 = None
        self._sort_asc                 = True
        self._sorted_contents          = None                   # ★新規: 現在のソート順
        self._filter_active            = False
        self._status_label             = None
        self._filter_btn_text          = None
        self._search_var               = None                   # ★新規: 検索キーワード
        self._checked_filter_active    = False                  # ★新規: 選択済みフィルタ
        self._checked_filter_btn_text  = None                   # ★新規: トグルラベル
        self._execute_btn              = None                   # ★新規: 実行ボタン参照
        self._reverse_sort_var         = None                   # ★新規: 時系列逆順ソートチェックボックス変数
    

    def show(self):
        """
        選択GUIを表示し、ウィンドウが閉じられるまでブロックする。
        Returns:
            list[dict]: _on_cancel() で閉じた場合は空リスト
        """
        try:
            self.root = tk.Tk()
            self.root.title("BBT 最新コンテンツ 要約マネージャー")
            self.root.geometry("1100x660")

            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            self.root.geometry(
                f"+{max(0, (screen_w - 1100) // 2)}+{max(0, (screen_h - 660) // 2)}")
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after(100, lambda: self.root.attributes('-topmost', False))

            for c in self.contents:
                self._check_states[c['program_id']] = False

            # ★新規: 時系列逆順ソートのデフォルトON相当の初期状態
            # （越智さん承認済み: サイト表示順＝新→旧を反転し、古→新で表示する）
            self._sorted_contents = list(reversed(self.contents))

            self._build_ui()
            self._populate_tree()
            self.root.mainloop()
            return self.selected_contents

        except Exception as e:
            print(f"ContentSelectionGUI エラー: {e}")
            import traceback
            traceback.print_exc()
            return []


    # ── _build_ui() 82行（チェックボックス行追加） ──
    def _build_ui(self):
        """UIウィジェットを構築する。"""

        # ── 時系列逆順ソート チェックボックス行（★新規） ──
        sort_frame = ttk.Frame(self.root, padding=(8, 8, 8, 0))
        sort_frame.pack(fill=tk.X)
        self._reverse_sort_var = tk.BooleanVar(value=True)  # デフォルトON（越智さん承認済み）
        ttk.Checkbutton(
            sort_frame,
            text="時系列逆順ソート（古い→新しい順で表示・要約）",
            variable=self._reverse_sort_var,
            command=self._on_reverse_sort_toggle
        ).pack(side=tk.LEFT)

        # ── 検索バー ──
        search_frame = ttk.Frame(self.root, padding=(8, 8, 8, 0))
        search_frame.pack(fill=tk.X)
        ttk.Label(search_frame, text="キーワード検索:").pack(side=tk.LEFT, padx=(0, 5))
        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', self._on_search_change)
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var, width=40)
        search_entry.pack(side=tk.LEFT)
        ttk.Button(search_frame, text="クリア",
                   command=lambda: self._search_var.set("")).pack(
                       side=tk.LEFT, padx=(5, 0))

        # ── ツールバー ──
        toolbar = ttk.Frame(self.root, padding="8")
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="すべて選択",
                   command=self._select_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(toolbar, text="すべて解除",
                   command=self._deselect_all).pack(side=tk.LEFT, padx=(0, 5))

        self._filter_btn_text = tk.StringVar(value="未要約のみ表示")
        ttk.Button(toolbar, textvariable=self._filter_btn_text,
                   command=self._toggle_filter).pack(side=tk.LEFT, padx=(0, 5))

        self._checked_filter_btn_text = tk.StringVar(value="選択済みのみ表示")  # ★新規
        ttk.Button(toolbar,                                                       # ★新規
                   textvariable=self._checked_filter_btn_text,                    # ★新規
                   command=self._toggle_checked_filter).pack(                     # ★新規
                       side=tk.LEFT, padx=(0, 15))                               # ★新規

        self._status_label = ttk.Label(toolbar, text="")
        self._status_label.pack(side=tk.RIGHT)

        # ── Treeview ──
        tree_frame = ttk.Frame(self.root)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        columns = (self.COL_CHECK, self.COL_DONE, self.COL_TITLE,
                   self.COL_SUB, self.COL_DUR, self.COL_DATE)
        self.tree = ttk.Treeview(tree_frame, columns=columns,
                                 show='headings', selectmode='none')

        col_specs = [
            (self.COL_CHECK, "選択",                          55,  tk.CENTER, 55),
            (self.COL_DONE,  "要約済",                         65,  tk.CENTER, 50),
            (self.COL_TITLE, "タイトル（クリックで動画を開く）",  360, tk.W,      120),
            (self.COL_SUB,   "サブタイトル",                   280, tk.W,      80),
            (self.COL_DUR,   "時間",                           70,  tk.CENTER, 50),
            (self.COL_DATE,  "配信日",                         140, tk.CENTER, 60),
        ]
        for col, text, width, anchor, minw in col_specs:
            self.tree.heading(col, text=text,
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=width, anchor=anchor,
                             minwidth=minw, stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                            command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL,
                            command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.tree.bind('<Button-1>', self._on_click)

        # ── ボタンバー ──
        btn_bar = ttk.Frame(self.root, padding="8")
        btn_bar.pack(fill=tk.X)
        ttk.Button(btn_bar, text="閉じる",                          # ★「キャンセル」→「閉じる」
                   command=self._on_cancel).pack(side=tk.RIGHT, padx=(5, 0))
        self._execute_btn = ttk.Button(btn_bar, text="▶ 要約開始",  # ★参照保持
                                       command=self._on_execute)
        self._execute_btn.pack(side=tk.RIGHT)



    # ── _apply_filters() 新規 20行 ──
    def _apply_filters(self, base_contents):
        """未要約・キーワード・選択済みの3フィルタを順に適用してリストを返す。
        Args:
            base_contents (list[dict]): ソート済みのベースリスト
        Returns:
            list[dict]: フィルタ適用後のリスト
        """
        filtered = list(base_contents)

        # 1. 未要約フィルタ
        if self._filter_active:
            filtered = [c for c in filtered
                        if not self.history.is_summarized(c['program_id'])]

        # 2. キーワードフィルタ（タイトル・サブタイトル対象、大小文字を区別しない）
        keyword = self._search_var.get().strip().lower() if self._search_var else ""
        if keyword:
            filtered = [c for c in filtered
                        if keyword in c.get('title', '').lower()
                        or keyword in c.get('sub_title', '').lower()]

        # 3. 選択済みフィルタ
        if self._checked_filter_active:
            filtered = [c for c in filtered
                        if self._check_states.get(c['program_id'], False)]

        return filtered

    # ── _on_search_change() 新規 4行 ──
    def _on_search_change(self, *args):
        """検索ボックスの入力変化を検知してTreeviewを再描画する。"""
        self._populate_tree()

    # ── _toggle_checked_filter() 新規 7行 ──
    def _toggle_checked_filter(self):
        """「選択済みのみ表示」フィルタのON/OFFを切り替える。"""
        self._checked_filter_active = not self._checked_filter_active
        self._checked_filter_btn_text.set(
            "選択済みフィルタ解除" if self._checked_filter_active else "選択済みのみ表示")
        self._populate_tree()

    # ── _populate_tree() 22行（引数削除・_apply_filters使用） ──
    def _populate_tree(self):
        """フィルタ・ソートを適用してTreeviewを再描画する。"""
        base         = (self._sorted_contents
                        if self._sorted_contents is not None
                        else self.contents)
        display_list = self._apply_filters(base)

        for row in self.tree.get_children():
            self.tree.delete(row)

        for c in display_list:
            pid       = c['program_id']
            is_done   = self.history.is_summarized(pid)
            done_mark = "✅" if is_done else ""
            chk_mark  = "☑" if self._check_states.get(pid, False) else "☐"
            self.tree.insert('', tk.END, iid=pid, values=(
                chk_mark, done_mark,
                c.get('title', ''), c.get('sub_title', ''),
                c.get('duration', ''), c.get('release_date', ''),
            ), tags=('done' if is_done else 'pending',))

        self.tree.tag_configure('done',    background='#e8f5e9')
        self.tree.tag_configure('pending', background='#ffffff')
        self._update_status()

    def _on_click(self, event):
        """Treeviewクリックイベント: 選択列トグル / タイトル列で動画タブを開く。"""
        region = self.tree.identify_region(event.x, event.y)
        if region != 'cell':
            return
        col_id = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return

        col_index = int(col_id.replace('#', '')) - 1
        col_names = (self.COL_CHECK, self.COL_DONE, self.COL_TITLE,
                     self.COL_SUB, self.COL_DUR, self.COL_DATE)
        if col_index < 0 or col_index >= len(col_names):
            return
        col_name = col_names[col_index]

        if col_name == self.COL_CHECK:
            self._check_states[row_id] = not self._check_states.get(row_id, False)
            self._refresh_row(row_id)
            self._update_status()
        elif col_name == self.COL_TITLE:
            content = next(
                (c for c in self.contents if c['program_id'] == row_id), None)
            if content and content.get('video_url'):
                self._open_video_tab(content['video_url'])

    def _refresh_row(self, pid):
        """指定行のチェックマーク表示を更新する。"""
        try:
            values    = list(self.tree.item(pid, 'values'))
            values[0] = "☑" if self._check_states.get(pid, False) else "☐"
            self.tree.item(pid, values=values)
        except Exception as e:
            print(f"_refresh_row エラー: {e}")

    def _select_all(self):
        """表示中の全行を選択状態にする。"""
        for pid in self.tree.get_children():
            self._check_states[pid] = True
            self._refresh_row(pid)
        self._update_status()

    def _deselect_all(self):
        """表示中の全行を選択解除する。"""
        for pid in self.tree.get_children():
            self._check_states[pid] = False
            self._refresh_row(pid)
        self._update_status()

    def _toggle_filter(self):
        """未要約フィルタのON/OFFを切り替える。"""
        self._filter_active = not self._filter_active
        self._filter_btn_text.set(
            "全件表示（フィルタ解除）" if self._filter_active else "未要約のみ表示")
        self._populate_tree()


    # ── _on_reverse_sort_toggle() 新規 27行 ──
    def _on_reverse_sort_toggle(self):
        """
        「時系列逆順ソート」チェックボックスのON/OFF切り替えハンドラ。
        ONの場合はサイト表示順（新→旧）を反転し古→新にする。
        OFFの場合はサイト表示順（新→旧）に戻す。
        列見出しクリックによるソート状態はクリアする（越智さん承認済み: 排他制御）。
        """
        self._sort_col = None
        self._sort_asc = True
        header_labels = {
            self.COL_CHECK: "選択",
            self.COL_DONE:  "要約済",
            self.COL_TITLE: "タイトル（クリックで動画を開く）",
            self.COL_SUB:   "サブタイトル",
            self.COL_DUR:   "時間",
            self.COL_DATE:  "配信日",
        }
        for col, text in header_labels.items():
            self.tree.heading(col, text=text)

        if self._reverse_sort_var.get():
            self._sorted_contents = list(reversed(self.contents))
        else:
            self._sorted_contents = list(self.contents)

        self._populate_tree()

    # ── _sort_by() 30行（末尾2行変更） ──
    def _sort_by(self, col):
        """指定列でソートする。同じ列を再クリックで昇順/降順を切り替える。"""
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True

        # ★新規: 列ソートを行った場合は時系列逆順ソートチェックボックスをOFFに戻す
        # （越智さん承認済み: 表示と実態の矛盾を防ぐための排他制御）
        if self._reverse_sort_var is not None:
            self._reverse_sort_var.set(False)

        key_map = {
            self.COL_CHECK: lambda c: self._check_states.get(c['program_id'], False),
            self.COL_DONE:  lambda c: self.history.is_summarized(c['program_id']),
            self.COL_TITLE: lambda c: c.get('title', ''),
            self.COL_SUB:   lambda c: c.get('sub_title', ''),
            self.COL_DUR:   lambda c: c.get('duration', ''),
            self.COL_DATE:  lambda c: c.get('release_date', ''),
        }
        key_fn = key_map.get(col, lambda c: '')
        self._sorted_contents = sorted(              # ★ _sorted_contents に保存
            self.contents, key=key_fn, reverse=not self._sort_asc)

        header_labels = {
            self.COL_CHECK: "選択",
            self.COL_DONE:  "要約済",
            self.COL_TITLE: "タイトル（クリックで動画を開く）",
            self.COL_SUB:   "サブタイトル",
            self.COL_DUR:   "時間",
            self.COL_DATE:  "配信日",
        }
        for c in header_labels:
            suffix = (" ▲" if self._sort_asc else " ▼") if c == col else ""
            self.tree.heading(c, text=header_labels[c] + suffix)

        self._populate_tree()                        # ★ 引数なし


    def _open_video_tab(self, url):
        """指定URLをChromeの新しいタブで開く。"""
        try:
            self.driver.switch_to.new_window('tab')
            self.driver.get(url)
            print(f"✅ 動画タブを開きました: {url[:60]}...")
        except Exception as e:
            print(f"⚠️ 動画タブ起動エラー: {e}")

    def _update_status(self):
        """ツールバーのステータスラベルを更新する。"""
        checked = sum(1 for v in self._check_states.values() if v)
        total   = len(self.tree.get_children())
        self._status_label.config(
            text=f"選択中: {checked}件 / 表示: {total}件 / 全: {len(self.contents)}件")


    # ── _on_execute() 23行（バックグラウンドスレッド化） ──
    def _on_execute(self):
        """要約開始ボタンのハンドラ。
        execute_callback が設定されている場合はバックグラウンドスレッドで処理を開始し、
        UIをそのまま保持する。設定されていない場合は後方互換でウィンドウを閉じる。
        """
        # ★修正: self.contents（サイト表示順=新→旧固定）ではなく、
        # self._sorted_contents（現在の並び替え結果。列ソート/逆順チェック
        # ボックスいずれかを反映した全件リスト）からチェック済みを抽出する。
        # これにより、UI上の並び替え結果がHTMLサマリの生成順序にそのまま
        # 反映されるようになる（越智さん承認済み: 根本原因の修正）。
        base_for_order = (self._sorted_contents
                           if self._sorted_contents is not None
                           else self.contents)
        self.selected_contents = [
            c for c in base_for_order
            if self._check_states.get(c['program_id'], False)
        ]
        if not self.selected_contents:
            messagebox.showwarning("警告", "少なくとも1件を選択してください。")
            return

        print(f"✅ {len(self.selected_contents)}件を選択しました")

        if self.execute_callback:
            self._execute_btn.config(state='disabled', text='処理中...')

            def run_in_thread():
                try:
                    self.execute_callback(self.selected_contents)
                finally:
                    self.root.after(0, self._on_processing_done)

            threading.Thread(target=run_in_thread, daemon=True).start()
        else:
            self.root.destroy()



    # ── _on_processing_done() 新規 6行 ──
    def _on_processing_done(self):
        """処理完了後にメインスレッドでUIを更新する（root.after経由で呼ばれる）。"""
        self._execute_btn.config(state='normal', text='▶ 要約開始')
        self._populate_tree()   # 要約済みマーク（✅ / 緑背景）を最新化
        messagebox.showinfo("処理完了",
                            "要約処理が完了しました。\n"
                            "続けて別の講義を選択するか、「閉じる」でウィンドウを閉じてください。")

    def _on_cancel(self):
        """閉じるボタンのハンドラ。"""
        self.selected_contents = []
        self.root.destroy()


# ========== GeminiAutomatorクラス ==========
class GeminiAutomator:
    """Gemini APIを使用した自動要約クラス（JSON・コスト対応版）"""


    def __init__(self, headless_mode=False):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
            
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        
        self.text_content = ""
        self.summary_result = ""
        self.total_cost_usd = 0.0
        self.total_cost_jpy = 0.0
        
        # ▼ 大前研一ライブ用（RTOCSあり）
        self.prompt_template_live = """# Task
あなたは、経営コンサルタント大前研一氏の思考をトレースし、ビジネスリーダー向けに「大前研一ライブ」のエグゼクティブ・サマリーを作成する戦略コンサルタントです。
提示された講義トランスクリプト（特に【ここからRTOCS（重点分析対象）セクション】とマークされた部分を最重視）から、以下の[Output Format]に従って、厳格なJSON形式で出力してください。

# Constraints
1. タイトルには必ず「ライブ回数」と「配信日」を含めること。
2. 【gist】は、その週で最も重要なトピックスを100文字程度で記述すること。スマホで読みやすいよう完結にまとめる。
3. 【conclusion】は、大局的な視点での世界情勢と日本経済の向かうべき方向性を300文字以内でまとめること。
4. 【main_points】には、後述の【講義アジェンダ】をMECE原則（漏れなく重複なく）でグループ化した5〜7個のcategoryを生成すること。その際、必ず「RTOCS分析」を独立したcategoryとして含め、大前氏の具体的な改善案と結論を記載すること（RTOCSは絶対に他のcategoryと統合しないこと）。
5. 【main_points】内の各カテゴリのポイントは「items」配列とし、要素は {"sub_topic": "中項目名", "detail": "詳細内容"} のオブジェクト形式にすること。
6. 「ネクストアクション」は main_points に含めず、独立した【actions】配列として、ビジネスパーソンが明日から実行すべき具体的な行動指針を3つ提示すること（これらは文字列の配列とする）。

【講義アジェンダ（骨組み）】
{agenda}

# Output Format (JSON)
{
    "title": "大前研一ライブ #XXXX（YYYY年MM月DD日配信）",
    "keywords": "キーワード1, キーワード2, キーワード3",
    "gist": "今週の要旨を100文字程度で記述。特に重要なニュースの核心と、大前氏が警鐘を鳴らしているポイントを凝縮する。",
    "conclusion": "今週の結論。大局的な視点での世界情勢と日本経済の向かうべき方向性を300文字以内で。",
    "main_points": [
        { 
            "category": "国際情勢・地政学", 
            "items": [
                { "sub_topic": "中東情勢", "detail": "トランプ政権の政策に関する独自見解..." },
                { "sub_topic": "台湾情勢", "detail": "通常の内容..." }
            ] 
        },
        { 
            "category": "RTOCS分析", 
            "items": [
                { "sub_topic": "ビジネスモデル", "detail": "今回のケーススタディの分析..." },
                { "sub_topic": "改善案", "detail": "具体的な改善案と結論..." }
            ] 
        }
    ],
    "actions": [
        "1. 〇〇を注視する", 
        "2. 〇〇を再点検する", 
        "3. 〇〇に備える"
    ]
}
"""

        # ▼ 大前研一アワー等用（RTOCSなし、カテゴリ動的生成）
        self.prompt_template_general = """# Task
あなたは、経営コンサルタント大前研一氏の思考をトレースし、ビジネスリーダー向けにエグゼクティブ・サマリーを作成する戦略コンサルタントです。
提示された講義トランスクリプトから、以下の[Output Format]に従って、厳格なJSON形式で出力してください。

# Constraints
1. タイトルには必ず「番組名」と「配信日」を含めること。
2. 【gist】は、その週で最も重要なトピックスを100文字程度で記述すること。スマホで読みやすいよう完結にまとめる。
3. 【conclusion】は、大局的な視点での世界情勢と日本経済の向かうべき方向性を300文字以内でまとめること。
4. 【main_points】には、後述の【講義アジェンダ】をMECE原則（漏れなく重複なく）でグループ化した5〜7個のcategoryを生成すること。各カテゴリのポイントは「items」配列とし、要素は {"sub_topic": "中項目名", "detail": "詳細内容"} のオブジェクト形式にすること。アジェンダがない場合は、講義内容から論理的に大項目を生成すること。
5. 「ネクストアクション」は main_points に含めず、独立した【actions】配列として、ビジネスパーソンが明日から実行すべき具体的な行動指針を3つ提示すること（これらは文字列の配列とする）。

【講義アジェンダ（骨組み）】
{agenda}

# Output Format (JSON)
{
    "title": "番組名（YYYY年MM月DD日配信）",
    "keywords": "キーワード1, キーワード2, キーワード3",
    "gist": "今週の要旨を100文字程度で記述。特に重要なニュースの核心と、大前氏が警鐘を鳴らしているポイントを凝縮する。",
    "conclusion": "今週の結論。大局的な視点での世界情勢と日本経済の向かうべき方向性を300文字以内で。",
    "main_points": [
        { 
            "category": "講義内容から導き出した適切な大項目A", 
            "items": [
                { "sub_topic": "中項目1", "detail": "詳細内容..." },
                { "sub_topic": "中項目2", "detail": "詳細内容..." }
            ] 
        },
        { 
            "category": "講義内容から導き出した適切な大項目B", 
            "items": [
                { "sub_topic": "中項目1", "detail": "詳細内容..." }
            ] 
        }
    ],
    "actions": [
        "1. 〇〇を注視する", 
        "2. 〇〇を再点検する", 
        "3. 〇〇に備える"
    ]
}
"""


    def connect_chrome(self):
        print("🤖 Gemini API モードで動作します")
        return True

    def upload_file_to_gemini(self, file_path):
        try:
            if not os.path.exists(file_path): return False
            with open(file_path, 'r', encoding='utf-8') as f:
                self.text_content = f.read()
            return True
        except Exception as e:
            return False

    def extract_agenda_from_file(self, file_path):
        """txtファイルの【目次（タイムライン）】セクションからアジェンダを抽出する
        
        Args:
            file_path (str): トランスクリプトtxtファイルの絶対パス
        
        Returns:
            str: 番号付きアジェンダテキスト。見つからない場合は空文字列。
                 例: "#1. [00:00:00 - 00:00:45] AIロボットの定義と概要"
        """
        try:
            if not file_path or not os.path.exists(file_path):
                print("⚠️ アジェンダ抽出: ファイルが存在しません")
                return ""
            
            print("📋 アジェンダを抽出中...")
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 【目次（タイムライン）】セクションの開始・終了位置を特定
            start_marker = "【目次（タイムライン）】"
            end_marker = "【トランスクリプト全文】"
            
            start_idx = content.find(start_marker)
            end_idx = content.find(end_marker)
            
            if start_idx == -1 or end_idx == -1:
                print("⚠️ アジェンダセクションが見つかりません")
                return ""
            
            # 目次セクションを切り出し
            agenda_section = content[start_idx:end_idx]
            
            # 行を解析して番号付きリストを生成
            lines = agenda_section.split('\n')
            agenda_items = []
            item_num = 0
            current_time = ""
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 時刻行を検出（例: "00:00:00 - 00:00:45" または数字付き "1. 00:00:00 - 00:00:45"）
                time_match = re.search(r'(\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2})', line)
                if time_match:
                    current_time = time_match.group(1).strip()
                    continue
                
                # トピック行を検出（区切り文字・マーカー行を除外）
                is_separator = re.match(r'^[=\-]{3,}', line)
                is_marker = '【' in line or '】' in line
                is_number_only = re.match(r'^\d+\.\s*$', line)
                
                if current_time and not is_separator and not is_marker and not is_number_only:
                    item_num += 1
                    agenda_items.append(f"#{item_num}. [{current_time}] {line}")
                    current_time = ""
            
            if not agenda_items:
                print("⚠️ アジェンダ項目が見つかりませんでした")
                return ""
            
            agenda_text = "\n".join(agenda_items)
            print(f"✅ アジェンダ抽出完了: {item_num}項目")
            return agenda_text
            
        except Exception as e:
            print(f"⚠️ アジェンダ抽出エラー（処理を続行します）: {e}")
            return ""
    
    def add_prompt_text(self, prompt_instruction, file_path=None):
        """アジェンダを埋め込んだプロンプトをGemini APIに送信する
        
        Args:
            prompt_instruction (str): プロンプトテンプレート（{agenda}プレースホルダー含む）
            file_path (str, optional): アジェンダ抽出元のtxtファイルパス
        
        Returns:
            bool: API呼び出し成功時True、失敗時False
        """
        try:
            print("🚀 Gemini APIにリクエストを送信中...")
            
            # アジェンダを抽出してプロンプトに埋め込む
            agenda = ""
            if file_path:
                agenda = self.extract_agenda_from_file(file_path)
            
            if agenda:
                final_instruction = prompt_instruction.replace("{agenda}", agenda)
                print(f"✅ アジェンダをプロンプトに埋め込みました（{len(agenda)}文字）")
            else:
                final_instruction = prompt_instruction.replace(
                    "{agenda}",
                    "（アジェンダ情報なし：トランスクリプト全体から論理的に分類してください）"
                )
                print("⚠️ アジェンダなし：トランスクリプト全体から分類します")
            
            final_prompt = f"{final_instruction}\n\n[Transcript Data]\n{self.text_content}"
            
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
            
            if response.text:
                self.summary_result = response.text
                return True
            return False
        except Exception as e:
            print(f"APIリクエストエラー: {e}")
            return False


    def click_send_button(self): return True
    def wait_for_send_completion(self): return True
    def wait_for_summary_completion(self, max_wait=300): return True


    def extract_summary_from_page(self):
        """JSONパースして辞書で返す"""
        try:
            text = self.summary_result.strip()
            # 念のためマークダウン記法をクリーンアップ
            if text.startswith('```json'):
                text = text[7:]
            elif text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]
            
            return json.loads(text.strip())
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            # パース失敗時はフォールバックの辞書を返す
            return {
                "title": "要約抽出失敗",
                "keywords": "エラー",
                "gist": "JSONの解析に失敗しました。",
                "conclusion": self.summary_result[:300] + "...",
                "main_points": []
            }

# ========== HTMLGeneratorクラス ==========
class HTMLGenerator:
    """HTML要約レポート生成クラス（統合マネージャー対応版）"""
    
    def __init__(self, output_dirs):
        # 複数のディレクトリを受け取れるようにリスト化
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


    def generate_html(self, summaries, cost_usd=0.0, cost_jpy=0.0):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_title = "Report"
            if summaries and len(summaries) > 0:
                raw_title = summaries[0].get('title', 'Unknown')
                video_title = self.sanitize_filename(raw_title)
            
            filename = f"Summary_BBT_{timestamp}_{video_title}.html"
            html_content = self.create_html_template(summaries, timestamp, cost_usd, cost_jpy)
            
            main_filepath = ""
            # 設定されたすべてのディレクトリに書き込み
            for i, d in enumerate(self.output_dirs):
                target_path = os.path.join(d, filename)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"✅ HTMLレポート保存完了: {target_path}")
                # 最初に保存したパスを戻り値（ブラウザ起動用）として保持
                if i == 0:
                    main_filepath = target_path
            
            return main_filepath
        except Exception as e:
            print(f"HTML生成エラー: {e}")
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
        html_parts.append('.one-liner-box { background:#f8fafc; padding:15px; border-radius:6px; margin-bottom:20px; font-size: 0.95rem; line-height: 1.6;}')
        html_parts.append('.conclusion-text { font-size: 0.95rem; line-height: 1.8; margin-bottom: 20px; }')
        html_parts.append('.section-content { margin-top: 15px; }')
        html_parts.append('.point-item { margin-bottom: 15px; line-height: 1.6; font-size: 0.95rem; }')
        html_parts.append('.collapse-button { background: #3182ce; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; }')
        html_parts.append('.collapse-content { max-height: 0; overflow: hidden; transition: max-height 0.3s; }')
        html_parts.append('.collapse-content.show { max-height: 5000px; }')
        html_parts.append('.insight-tag { color: #e53e3e; font-weight: bold; background: #fff5f5; padding: 2px 5px; border-radius: 3px; border: 1px solid #feb2b2; }')
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
        
        # summary_data is a parsed JSON dictionary
        sd = summary.get('summary', {})
        if not isinstance(sd, dict): sd = {}
        
        # ★修正: BBT元タイトルを常に使用（Gemini生成タイトルは使用しない）
        disp_title = summary.get('title', '無題')

        # ★新規: 講師名・配信日/収録時間の表示テキストを組み立てる
        # （越智さん承認事項: 講師名は単独講師時のみ実名、複数講師・
        #   自由記述時はハイフン表示。配信日/収録時間は取得不可時「情報なし」）
        lecturer_name = summary.get('lecturer_name', '') or 'ー'
        release_date  = summary.get('release_date', '')
        duration      = summary.get('duration', '')
        if release_date and duration:
            date_duration_text = f"{release_date} 配信／収録時間：{duration}"
        elif release_date:
            date_duration_text = f"{release_date} 配信"
        elif duration:
            date_duration_text = f"収録時間：{duration}"
        else:
            date_duration_text = "情報なし"
        meta_html = (
            '<div class="video-meta" '
            'style="font-size:0.85rem; color:#718096; margin-bottom:8px;">'
            f'講師：{lecturer_name} ／ {date_duration_text}'
            '</div>'
        )

        gist = sd.get('gist', '')
        conclusion = sd.get('conclusion', '')
        keywords_str = sd.get('keywords', '')
        
        keywords_html = ""
        for kw in keywords_str.split(','):
            if kw.strip(): keywords_html += f'<span class="keyword-badge">{kw.strip()}</span>'
        
        points_html = ""
        for pt in sd.get('main_points', []):
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

        # ネクストアクションの追加
        actions = sd.get('actions', [])
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
                        {meta_html}
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


# ========== SimpleIntegratorクラス ==========
class SimpleIntegrator:
    """シンプルな統合クラス（Gemini版）"""

    # ★新規: Chrome Debug Launcher 自動起動用の定数（越智さんの手動起動設定を流用）
    CHROME_PATH          = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    CHROME_USER_DATA_DIR = r"C:\Users\nx023836\AppData\Local\ChromeDebugProfile9222"
    CHROME_DEBUG_PORT    = 9222
    CHROME_LAUNCH_WAIT_SEC = 15   # 起動待機のタイムアウト（秒）

    def __init__(self):
        self.chrome_driver = None
        self.transcript_files = []
        # 保存先パスをリストとして定義（既存 + 新規）
        self.output_dirs = [
            r"C:\Users\nx023836\Documents\PythonScripts\bbt\bbt_lecture_summary",
            r"C:\Users\nx023836\Nexperia\My Private - Documents\Summary"
        ]
        
        self.manual_mode = False        
        self.send_interval = 30
        
        print(f"⏰ 自動待機モード（{self.send_interval}秒）が選択されました")

    # ── _ensure_chrome_debug_running() 新規 45行 ──
    def _ensure_chrome_debug_running(self):
        """
        リモートデバッグ用Chrome（Chrome Debug Launcher相当）が起動済みか
        確認し、未起動の場合は越智さんの手動起動設定と同一の条件で自動起動する。

        既に起動済みの場合は何もしない（二重起動防止）。
        起動に失敗した場合もエラーを表示するのみで処理は継続する
        （従来通り手動起動でも動作するフォールバック）。
        """
        check_url = f"http://localhost:{self.CHROME_DEBUG_PORT}/json/version"

        # 1. 既に起動済みか確認
        try:
            urllib.request.urlopen(check_url, timeout=2)
            print(f"✅ Chrome（デバッグポート{self.CHROME_DEBUG_PORT}）は起動済みです")
            return
        except Exception:
            pass

        # 2. 未起動の場合、越智さんの設定値で自動起動する
        print("Chromeが未起動のため、自動起動します...")
        try:
            subprocess.Popen([
                self.CHROME_PATH,
                f"--remote-debugging-port={self.CHROME_DEBUG_PORT}",
                f"--user-data-dir={self.CHROME_USER_DATA_DIR}",
                ContentListScraper.LIST_URL,
            ])
        except Exception as e:
            print(f"❌ Chrome自動起動エラー: {e}")
            print("   手動でChrome Debug Launcherを起動してから、モードを選択してください。")
            return

        # 3. 起動完了（ポート応答）まで待機
        for i in range(self.CHROME_LAUNCH_WAIT_SEC):
            time.sleep(1)
            try:
                urllib.request.urlopen(check_url, timeout=2)
                print(f"✅ Chromeの起動を確認しました（約{i + 1}秒）")
                return
            except Exception:
                continue

        print(f"⚠️ {self.CHROME_LAUNCH_WAIT_SEC}秒待機してもChromeの起動を確認できませんでした。")
        print("   起動状況を確認の上、モードを選択してください。")

    def run(self):
        """メイン処理フロー（モード選択で分岐）"""
        try:
            print("="*60)
            print("BBT講義トランスクリプト → Gemini自動送信ツール")
            print("="*60)

            # ★新規: モード選択の直前にChrome自動起動を確認・実行する
            self._ensure_chrome_debug_running()

            mode = ModeSelectionGUI().show()
            if mode is None:
                print("キャンセルされました。終了します。")
                return

            if mode == 'legacy':
                self._run_legacy()
            elif mode == 'search':
                self._run_search_mode()
            else:
                self._run_new()

        except Exception as e:
            print(f"\n❌ エラーが発生しました: {e}")
            import traceback
            traceback.print_exc()

    def _run_legacy(self):
        """従来方式: 開いているBBT動画タブを検出して要約する"""
        try:
            if not self.check_chrome_connection():
                print("❌ Chrome接続に失敗しました")
                return

            print("\n📚 トランスクリプト抽出フェーズ")
            transcript_files = self.extract_all_transcripts()
            if not transcript_files:
                print("❌ トランスクリプトが取得できませんでした")
                return

            print(f"\n✅ {len(transcript_files)}個のトランスクリプトを取得しました")

            print("\n🚀 Gemini送信フェーズ")
            summaries, cost_usd, cost_jpy = self.send_all_to_gemini(transcript_files)

            print("\n📄 HTMLレポート生成中...")
            html_generator = HTMLGenerator(self.output_dirs)
            html_path = html_generator.generate_html(
                summaries, cost_usd=cost_usd, cost_jpy=cost_jpy)

            if html_path:
                print(f"✅ HTMLレポート: {html_path}")
                self.open_file(html_path)

            self.show_results(summaries, html_path)

        except Exception as e:
            print(f"\n❌ _run_legacy エラー: {e}")
            import traceback
            traceback.print_exc()


    # ── _show_scan_progress() 68行（history_manager引数追加） ──
    # 配置: SimpleIntegrator._run_new() の直前
    def _show_scan_progress(self, driver, scraper, history_manager=None):
        """
        スキャン中のプログレスバーダイアログを表示しながら全件スキャンを実行する。
        スキャンはバックグラウンドスレッドで実行し、完了後にダイアログを自動クローズ。
        Args:
            driver: Selenium WebDriver
            scraper (ContentListScraper): 初期化済みのスクレイパー
            history_manager (SummaryHistoryManager | None): ★新規
                要約履歴。渡された場合、scraper.scrape_content_list() に
                そのまま伝搬し、要約済み3件連続検出による早期終了判定に使用する。
        Returns:
            list[dict]: scrape_content_list() の戻り値
        """
        import queue
        result_queue   = queue.Queue()
        progress_queue = queue.Queue()

        def scan_worker():
            """バックグラウンドでスキャンを実行し、結果をキューに格納する。"""
            try:
                def on_progress(page, total):
                    progress_queue.put(('progress', page, total))

                contents = scraper.scrape_content_list(
                    driver, progress_callback=on_progress,
                    history_manager=history_manager)
                result_queue.put(('done', contents))
            except Exception as e:
                result_queue.put(('error', str(e)))

        # ── プログレスダイアログを構築 ──
        root = tk.Tk()
        root.title("BBT 最新コンテンツ スキャン中")
        root.geometry("420x160")
        root.resizable(False, False)

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        root.geometry(f"+{screen_w // 2 - 210}+{screen_h // 2 - 80}")
        root.lift()
        root.attributes('-topmost', True)

        frame = ttk.Frame(root, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="BBT最新コンテンツを全件スキャン中...",
                  font=("", 11)).pack(pady=(0, 10))

        page_label = ttk.Label(frame, text="ページ 0 / 取得: 0件",
                               font=("", 9), foreground="#555")
        page_label.pack(pady=(0, 8))

        progress_var = tk.DoubleVar(value=0)
        progress_bar = ttk.Progressbar(
            frame, variable=progress_var,
            mode='indeterminate', length=360)
        progress_bar.pack()
        progress_bar.start(12)  # アニメーション開始

        contents_result = []

        def poll():
            """メインスレッドから定期的にキューを確認してUIを更新する。"""
            nonlocal contents_result

            # 進捗キューを全て処理
            while not progress_queue.empty():
                try:
                    msg = progress_queue.get_nowait()
                    if msg[0] == 'progress':
                        _, page, total = msg
                        page_label.config(
                            text=f"ページ {page} スキャン完了 / 累計取得: {total}件")
                except queue.Empty:
                    break

            # 結果キューを確認
            if not result_queue.empty():
                try:
                    msg = result_queue.get_nowait()
                    if msg[0] == 'done':
                        contents_result = msg[1]
                        page_label.config(
                            text=f"スキャン完了！ {len(contents_result)}件取得")
                    elif msg[0] == 'error':
                        print(f"❌ スキャンエラー: {msg[1]}")
                        page_label.config(text=f"スキャンエラー: {msg[1]}")
                    progress_bar.stop()
                    root.after(600, root.destroy)  # 0.6秒後にダイアログを閉じる
                    return
                except queue.Empty:
                    pass

            root.after(200, poll)  # 200ms後に再ポーリング

        # バックグラウンドスキャン開始
        threading.Thread(target=scan_worker, daemon=True).start()
        # ポーリング開始
        root.after(200, poll)
        # ダイアログが閉じられるまでブロック
        root.mainloop()

        return contents_result


    # ── _run_new() 45行（要約履歴読み込みをスキャン前に移動） ──
    def _run_new(self):
        """新方式: BBT最新コンテンツ一覧から選択して要約する"""
        try:
            # Step1: Chrome接続
            if not self.check_chrome_connection():
                print("❌ Chrome接続に失敗しました")
                return

            # Step2: BBT最新コンテンツページを開く
            scraper = ContentListScraper()
            if not scraper.find_or_open_list_tab(self.chrome_driver):
                print("❌ BBT最新コンテンツページを開けませんでした")
                return

            # ★変更: 要約履歴をスキャンより先に読み込む
            # （越智さん承認済み: 要約済み3件連続検出による早期終了判定のため、
            #   スキャン開始前に履歴を把握しておく必要がある）
            history = SummaryHistoryManager()
            print(f"  要約済み件数: {len(history.get_all())}件")

            # ★変更: _show_scan_progress() 経由で全件スキャン＋プログレス表示
            # history を渡し、要約済み3件連続検出時の早期終了を有効にする
            contents = self._show_scan_progress(
                self.chrome_driver, scraper, history_manager=history)

            if not contents:
                print("❌ コンテンツが取得できませんでした")
                return

            # Step3: TranscriptExtractor を事前に初期化
            extractor = TranscriptExtractor(debug_port=9222)

            # Step4: コンテンツ選択GUI（execute_callback で処理を委譲）
            print(f"\n📋 コンテンツ選択UIを表示します（{len(contents)}件）")

            def process_callback(selected_contents):
                """GUIの「▶ 要約開始」ボタンから呼ばれるコールバック（別スレッド）"""
                self._process_selected_contents(selected_contents, history, extractor)

            gui = ContentSelectionGUI(
                contents, history, self.chrome_driver,
                execute_callback=process_callback
            )
            gui.show()  # ウィンドウが「閉じる」で閉じられるまでブロック

        except Exception as e:
            print(f"\n❌ _run_new エラー: {e}")
            import traceback
            traceback.print_exc()
            


    # ── _run_search_mode() 新規 ──
    # 配置: SimpleIntegrator._run_new() の直後
    def _run_search_mode(self):
        """
        検索結果一覧方式: BBTキーワード検索結果ページ（search-content）
        から選択して要約する。

        検索キーワードはその都度変化するため、GUI上でURLを指定させるの
        ではなく、越智さんの承認済み方針（案A）に従い、現在Chromeで開いて
        いるタブの中から search-content ページを自動検出する。見つから
        ない場合はエラーダイアログを表示し、選び直しを促す。
        """
        try:
            # Step1: Chrome接続
            if not self.check_chrome_connection():
                print("❌ Chrome接続に失敗しました")
                return

            # Step2: アクティブタブ（または開いている全タブ）が
            #        検索結果ページかどうかを検証する
            scraper = SearchResultScraper()
            if not scraper.find_active_search_tab(self.chrome_driver):
                messagebox.showerror(
                    "検索結果ページが見つかりません",
                    "現在Chromeで開いているタブの中に、\n"
                    "BBT検索結果ページ（search-content）が見つかりませんでした。\n\n"
                    "AirSearchでキーワード検索を行い、検索結果ページを開いた\n"
                    "状態で再度実行してください。"
                )
                print("❌ 検索結果ページが見つからないため中断しました")
                return

            # Step3: 検索結果ページを無限スクロールで全件スキャン
            #        （プログレスダイアログ表示付き。_show_scan_progress は
            #          scraper.scrape_content_list(driver, progress_callback)
            #          という共通シグネチャに依存しているため、
            #          ContentListScraper / SearchResultScraper の両方で
            #          そのまま再利用できる）
            contents = self._show_scan_progress(self.chrome_driver, scraper)
            if not contents:
                print("❌ コンテンツが取得できませんでした")
                return

            # Step4: 要約履歴を読み込む（program_id単位でContentListScraper側と共用）
            history = SummaryHistoryManager()
            print(f"  要約済み件数: {len(history.get_all())}件")

            # Step5: TranscriptExtractor を事前に初期化
            extractor = TranscriptExtractor(debug_port=9222)

            # Step6: コンテンツ選択GUI（execute_callback で処理を委譲）
            print(f"\n📋 コンテンツ選択UIを表示します（{len(contents)}件）")

            def process_callback(selected_contents):
                """GUIの「▶ 要約開始」ボタンから呼ばれるコールバック（別スレッド）"""
                self._process_selected_contents(selected_contents, history, extractor)

            gui = ContentSelectionGUI(
                contents, history, self.chrome_driver,
                execute_callback=process_callback
            )
            gui.show()  # ウィンドウが「閉じる」で閉じられるまでブロック

        except Exception as e:
            print(f"\n❌ _run_search_mode エラー: {e}")
            import traceback
            traceback.print_exc()

    # ── _process_selected_contents() 新規 77行 ──
    def _process_selected_contents(self, selected, history, extractor):
        """トランスクリプト抽出 → Gemini要約 → HTML生成 → 履歴保存を実行する。
        バックグラウンドスレッドから呼ばれる。

        Args:
            selected (list[dict]): 選択されたコンテンツのリスト
            history (SummaryHistoryManager): 要約履歴管理オブジェクト
            extractor (TranscriptExtractor): 初期化済みの抽出器
        """
        try:
            transcript_files = []

            for i, content in enumerate(selected, 1):
                pid       = content['program_id']
                title     = content['title']
                sub_title = content.get('sub_title', '')
                video_url = content['video_url']

                print(f"\n[{i}/{len(selected)}] 処理中: {title}")

                try:
                    # 動画タブを開く
                    print(f"  動画タブを開いています...")
                    self.chrome_driver.switch_to.new_window('tab')
                    self.chrome_driver.get(video_url)
                    time.sleep(3)

                    new_handle = self.chrome_driver.current_window_handle
                    full_title = f"{title}_{sub_title}" if sub_title else title

                    video_info = VideoInfo(
                        url=video_url,
                        title=full_title,
                        tab_handle=new_handle,
                        thumbnail_url=content.get('thumbnail_url', ''),
                    )

                    # トランスクリプト抽出・ファイル保存
                    filepath = extractor.process_single_video(video_info)

                    if filepath:
                        transcript_files.append({
                            'filepath':      filepath,
                            'title':         full_title,
                            'url':           video_url,
                            'thumbnail_url': content.get('thumbnail_url', ''),
                            'program_id':    pid,
                            'lecturer_name': content.get('lecturer_name', ''),
                            'release_date':  content.get('release_date', ''),
                            'duration':      content.get('duration', ''),
                        })
                        print(f"  ✅ トランスクリプト取得完了: {os.path.basename(filepath)}")
                    else:
                        print(f"  ⚠️ トランスクリプト取得失敗: {title}")

                    # 処理済みの動画タブを閉じて元のタブへ戻る
                    try:
                        self.chrome_driver.switch_to.window(new_handle)
                        self.chrome_driver.close()
                        remaining = self.chrome_driver.window_handles
                        if remaining:
                            self.chrome_driver.switch_to.window(remaining[0])
                    except Exception as close_err:
                        print(f"  ⚠️ タブクローズエラー（続行）: {close_err}")

                except Exception as e:
                    print(f"  ❌ 処理エラー ({title}): {e}")
                    import traceback
                    traceback.print_exc()

            if not transcript_files:
                print("❌ 処理できたファイルがありませんでした")
                return

            # Gemini API で要約
            print(f"\n🚀 Gemini送信フェーズ ({len(transcript_files)}件)")
            summaries, cost_usd, cost_jpy = self.send_all_to_gemini(transcript_files)

            # 要約済みをJSONに記録
            for s in summaries:
                if s.get('success'):
                    pid_match = next(
                        (f['program_id'] for f in transcript_files
                         if f['filepath'] == s.get('file')), None)
                    if pid_match:
                        history.mark_summarized(pid_match, {
                            'title':     s.get('title', ''),
                            'video_url': s.get('url', ''),
                            'html_file': '',
                        })

            # HTMLレポート生成
            print("\n📄 HTMLレポート生成中...")
            html_generator = HTMLGenerator(self.output_dirs)
            html_path = html_generator.generate_html(
                summaries, cost_usd=cost_usd, cost_jpy=cost_jpy)

            if html_path:
                print(f"✅ HTMLレポート: {html_path}")
                self.open_file(html_path)

            self.show_results(summaries, html_path)

        except Exception as e:
            print(f"\n❌ _process_selected_contents エラー: {e}")
            import traceback
            traceback.print_exc()


    def check_chrome_connection(self):
        try:
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", "localhost:9222")
            self.chrome_driver = webdriver.Chrome(options=chrome_options)
            print("✅ Chrome接続成功")
            return True
        except Exception as e:
            print(f"Chrome接続エラー: {e}")
            return False

    def extract_all_transcripts(self):
        try:
            extractor = TranscriptExtractor(debug_port=9222)
            videos = extractor.discover_videos()
            if not videos: return []
            
            if len(videos) == 1:
                selected_videos = videos
            else:
                gui = VideoSelectionGUI(videos)
                selected_videos = gui.show_selection_dialog()
                if not selected_videos: return []
            
            results = extractor.process_multiple_videos(selected_videos)
            file_paths = []
            for result in results:
                if result['success'] and result['filepath']:
                    file_paths.append({
                        'filepath': result['filepath'],
                        'title': result['video'].title,
                        'url': result['video'].url,
                        'thumbnail_url': result['video'].thumbnail_url
                    })
            return file_paths
        except Exception as e:
            print(f"トランスクリプト抽出エラー: {e}")
            return []


    
    def send_all_to_gemini(self, file_infos):
        summaries = []
        sender = GeminiAutomator(headless_mode=False)
        sender.connect_chrome()
        
        for i, file_info in enumerate(file_infos, 1):
            file_path = file_info['filepath']
            title = file_info['title']
            url = file_info.get('url', '#')
            thumb = file_info.get('thumbnail_url', '')
            lecturer_name = file_info.get('lecturer_name', '')
            release_date = file_info.get('release_date', '')
            duration = file_info.get('duration', '')
            
            print(f"\n[{i}/{len(file_infos)}] 処理開始: {os.path.basename(file_path)}")
            try:
                if not sender.upload_file_to_gemini(file_path):
                    raise Exception("ファイルの読み込みに失敗しました")
                
                # タイトルによるプロンプトの動的切り替え
                if "大前研一ライブ" in title:
                    prompt_instruction = sender.prompt_template_live
                    print("✅ [大前研一ライブ] 用プロンプト（RTOCSあり）を適用します")
                else:
                    prompt_instruction = sender.prompt_template_general
                    print("✅ [一般番組] 用プロンプト（RTOCSなし）を適用します")

                # ★変更点: file_path を渡してアジェンダを動的埋め込み
                if sender.add_prompt_text(prompt_instruction, file_path=file_path):
                    summary_dict = sender.extract_summary_from_page()
                    summaries.append({
                        'title': title,
                        'file': file_path,
                        'url': url,
                        'thumbnail_url': thumb,
                        'lecturer_name': lecturer_name,
                        'release_date': release_date,
                        'duration': duration,
                        'summary': summary_dict,
                        'success': True,
                        'error': None
                    })
                    print(f"✅ 要約成功")
                else:
                    raise Exception("要約の生成に失敗しました")
                
                if i < len(file_infos): time.sleep(2)
                    
            except Exception as e:
                print(f"❌ エラー: {e}")
                summaries.append({
                    'title': title,
                    'file': file_path,
                    'url': url,
                    'thumbnail_url': thumb,
                    'lecturer_name': lecturer_name,
                    'release_date': release_date,
                    'duration': duration,
                    'summary': {},
                    'success': False,
                    'error': str(e)
                })
        
        return summaries, sender.total_cost_usd, sender.total_cost_jpy


    def show_results(self, summaries, html_path):
        print("\n" + "="*60)
        print("🎉 処理完了！")
        print("="*60)
        successful = sum(1 for s in summaries if s['success'])
        failed = len(summaries) - successful
        print(f"\n成功: {successful}件")
        print(f"失敗: {failed}件")
        if html_path:
            print(f"\nHTMLレポート: {html_path}")
        if failed > 0:
            print("\n失敗したファイル:")
            for s in summaries:
                if not s['success']:
                    print(f"  - {s['title']}: {s['error']}")

    def open_file(self, filepath):
        try:
            if not filepath or not os.path.exists(filepath): return
            system = platform.system()
            if system == "Windows": os.startfile(filepath)
            elif system == "Darwin": subprocess.run(['open', filepath])
            elif system == "Linux": subprocess.run(['xdg-open', filepath])
            print(f"ファイルを開きました: {os.path.basename(filepath)}")
        except Exception as e:
            print(f"ファイルオープンエラー: {e}")


    def download_and_copy_pdf(self):
        import glob
        import os
        import time
        import shutil
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException

        try:
            # 汎用的なユーザーのDownloadsフォルダパスを取得
            download_dir = os.path.expanduser(r"~\Downloads")
            target_dir = r"C:\Users\nx023836\Nexperia\My Private - Documents\Summary"
            
            # 1. クリック前に存在するPDFのリストを取得（新規ダウンロードファイルを特定するため）
            before_files = set(glob.glob(os.path.join(download_dir, "*.pdf")))
            
            # 2. ボタンを特定してクリック（最大3秒待機。他要素に被られても作動するようJSクリックを使用）
            button = WebDriverWait(self.chrome_driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'button[title="資料ダウンロード"]'))
            )
            self.chrome_driver.execute_script("arguments[0].click();", button)
            print("⏳ 資料PDFのダウンロードを開始しました...")
            
            # 3. タイムアウト絶対時間（10秒）のループで新規PDFの確定を待機
            timeout = 10
            start_time = time.time()
            new_pdf = None
            
            while time.time() - start_time < timeout:
                current_pdfs = set(glob.glob(os.path.join(download_dir, "*.pdf")))
                new_pdfs = current_pdfs - before_files
                
                if new_pdfs:
                    candidate = list(new_pdfs)[0]
                    try:
                        # ファイルの実体が生成され、サイズが取得可能（ロック解除）になれば完了と判定
                        if os.path.getsize(candidate) > 0:
                            new_pdf = candidate
                            # ダウンロード直後のファイルロックによるコピペ失敗を防ぐためのバッファ待機
                            time.sleep(0.5) 
                            break
                    except OSError:
                        # OSがまだファイルをロックして書き込み中の場合は例外を流して次ループへ
                        pass 
                        
                time.sleep(1)
                
            # 4. 指定フォルダへコピー
            if new_pdf:
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)
                filename = os.path.basename(new_pdf)
                target_path = os.path.join(target_dir, filename)
                shutil.copy2(new_pdf, target_path)
                print(f"✅ 資料PDFを保存しました: {target_path}")
            else:
                print("⚠️ 10秒以内にPDFのダウンロードが完了しなかったため、コピーをスキップしました。")
                
        except TimeoutException:
            # ボタンが存在しない講義の場合も、システムは停止せずスキップする
            print("⚠️ 資料ダウンロードボタンが見つからないため、PDF取得をスキップしました。")
        except Exception as e:
            print(f"⚠️ PDFダウンロード中にエラーが発生しました（スキップして続行します）: {e}")


# ========== メイン関数 ==========
def main():
    """メイン処理"""
    try:
        print("="*60)
        print("BBT講義トランスクリプト → Gemini自動送信ツール")
        print("="*60)
        print()

        integrator = SimpleIntegrator()
        integrator.run()
        
    except KeyboardInterrupt:
        print("\n\n処理が中断されました")
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file_path = os.path.join(script_dir, "execution_log.log")
    logger = DualLogger(log_file_path)
    sys.stdout = logger
    sys.stderr = logger
    
    try:
        print(f"Log file will be saved to: {log_file_path}")
        main()
    except Exception as e:
        print(f"\n❌ 致命的なエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()            