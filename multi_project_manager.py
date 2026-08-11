# multi_project_manager.py
import pickle
import os
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
import logging
import json
from datetime import date
import threading

class MultiProjectManager:
    """複数プロジェクトのYouTube API管理クラス（スレッドセーフ版）"""

    def __init__(self):
        """初期化（スレッドセーフ版）"""
        self.projects = {
            'project1': {
                'credentials_file': 'credentials.json',
                'token_file': 'token.pickle',
                'quota_used': 0,
                'quota_limit': 10000,
                'service': None
            },
            'project2': {
                'credentials_file': 'credentials_project2.json',
                'token_file': 'token_project2.pickle',
                'quota_used': 0,
                'quota_limit': 10000,
                'service': None
            }
        }

        self.current_project = 'project1'
        self.total_operations = 0
        self.quota_file = 'quota_usage.json'

        # スレッドセーフティ用のロック
        self.quota_lock = threading.Lock()
        self.file_lock = threading.Lock()

        # 手動モード関連の変数
        self.mode = 'auto'
        self.forced_project = None

        # クォータ読み込み・サービス初期化
        self.load_quota_usage()
        self.initialize_services()

        # 初期化時に適切なプロジェクトを選択
        if self.projects['project1']['quota_used'] >= self.projects['project1']['quota_limit']:
            if self.projects['project2']['service']:
                self.current_project = 'project2'
                logging.info("Initial selection: Project 2 (project1 is full)")
        elif self.projects['project1']['quota_used'] >= self.projects['project1']['quota_limit'] * 0.9:
            if self.projects['project2']['service']:
                self.current_project = 'project2'
                logging.info("Initial selection: Project 2 (project1 is near limit)")

    def initialize_services(self):
        """全プロジェクトのサービスを初期化"""
        SCOPES = ['https://www.googleapis.com/auth/youtube']

        for project_id, project_info in self.projects.items():
            try:
                creds = None

                # トークン読み込み
                if os.path.exists(project_info['token_file']):
                    with open(project_info['token_file'], 'rb') as token:
                        creds = pickle.load(token)

                # トークンリフレッシュまたは新規取得
                if not creds or not creds.valid:
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                    else:
                        flow = InstalledAppFlow.from_client_secrets_file(
                            project_info['credentials_file'], SCOPES)
                        creds = flow.run_local_server(port=0)

                        with open(project_info['token_file'], 'wb') as token:
                            pickle.dump(creds, token)

                # サービス作成
                project_info['service'] = build('youtube', 'v3', credentials=creds)
                logging.info(f"✅ {project_id} initialized successfully")

            except Exception as e:
                logging.error(f"❌ Failed to initialize {project_id}: {e}")
                project_info['service'] = None

    def load_quota_usage(self):
        """保存されたクォータ使用量を読み込み（スレッドセーフ）"""
        try:
            with self.file_lock:
                if os.path.exists(self.quota_file):
                    with open(self.quota_file, 'r') as f:
                        data = json.load(f)
                    today = str(date.today())

                    if data.get('date') == today:
                        for project_id in self.projects:
                            if project_id in data.get('projects', {}):
                                self.projects[project_id]['quota_used'] = data['projects'][project_id].get('used', 0)
                                logging.info(f"Loaded quota for {project_id}: {self.projects[project_id]['quota_used']}")
                    else:
                        self._save_quota_usage_internal()
                else:
                    self._save_quota_usage_internal()
        except Exception as e:
            logging.error(f"Failed to load quota: {e}")

    def _save_quota_usage_internal(self):
        """内部用: ファイルロックなしで保存（既にロックされている前提）"""
        try:
            data = {
                'date': str(date.today()),
                'projects': {}
            }
            for project_id, info in self.projects.items():
                data['projects'][project_id] = {
                    'used': info['quota_used'],
                    'limit': info['quota_limit']
                }

            with open(self.quota_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save quota internally: {e}")

    def save_quota_usage(self):
        """クォータ使用量を保存（スレッドセーフ）"""
        with self.file_lock:
            self._save_quota_usage_internal()


    def get_current_service(self):
        """現在のYouTube APIサービスを取得（認証状態を確認して返す）"""
        # 現在のプロジェクト情報を取得
        info = self.projects[self.current_project]

        # サービスが未作成、または無効な場合は再構築を試みる
        if info['service'] is None:
            logging.info(f"Building service for {self.current_project}...")
            self.initialize_services() # 全サービスをリフレッシュ

        return self.projects[self.current_project]['service']


    def reset_to_auto(self):
        """自動モードに戻す（forced_projectをクリア）"""
        with self.quota_lock:
            self.mode = 'auto'
            self.forced_project = None
        logging.info("🔧 System reset to AUTO mode")

    def refresh_project_service(self, project_id):
        """
        指定されたプロジェクトの認証をやり直し、サービスを再構築する
        """
        SCOPES = ['https://www.googleapis.com/auth/youtube']
        info = self.projects.get(project_id)
        if not info: return False

        try:
            # 既存のトークンファイルを削除して強制再認証
            if os.path.exists(info['token_file']):
                os.remove(info['token_file'])

            flow = InstalledAppFlow.from_client_secrets_file(
                info['credentials_file'], SCOPES)
            creds = flow.run_local_server(port=0)

            with open(info['token_file'], 'wb') as token:
                pickle.dump(creds, token)

            info['service'] = build('youtube', 'v3', credentials=creds)
            logging.info(f"✅ {project_id} has been re-authorized and rebuilt.")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to re-authorize {project_id}: {e}")
            return False

    def should_switch_project(self):
        """プロジェクト切り替えが必要か判定"""
        if self.mode == 'manual':
            return False

        with self.quota_lock:
            current = self.projects[self.current_project]
            return current['quota_used'] >= current['quota_limit'] * 0.9

    def switch_project(self):
        """プロジェクトを切り替える"""
        if self.mode == 'manual':
            logging.warning(f"⚠️ Manual mode active, cannot switch from {self.forced_project}")
            return False

        with self.quota_lock:
            if self.current_project == 'project1':
                if self.projects['project2']['service']:
                    self.current_project = 'project2'
                    logging.info("🔄 Switched to Project 2")
                    return True
            else:
                if self.projects['project1']['service']:
                    self.current_project = 'project1'
                    logging.info("🔄 Switched to Project 1")
                    return True
        return False

    def set_manual_mode(self, project_name):
        """手動モードを設定"""
        if project_name not in self.projects:
            logging.error(f"❌ Invalid project name: {project_name}")
            return False

        with self.quota_lock:
            self.mode = 'manual'
            self.forced_project = project_name
            self.current_project = project_name
        logging.info(f"🔧 Manual mode enabled: forcing {project_name}")
        return True

    def get_current_mode(self):
        """現在のモードを取得"""
        return self.mode

    def record_api_usage(self, cost):
        """API使用量を記録（スレッドセーフ版）"""
        try:
            with self.quota_lock:
                self.projects[self.current_project]['quota_used'] += cost
                logging.info(
                    f"📊 Recorded {cost} quota for {self.current_project} "
                    f"(total: {self.projects[self.current_project]['quota_used']})"
                )
            self.save_quota_usage()
        except Exception as e:
            logging.error(f"❌ Failed to record API usage: {e}")

    def get_quota_status(self):
        """現在のクォータ状況を取得（スレッドセーフ）"""
        try:
            with self.quota_lock:
                total_used = sum(p['quota_used'] for p in self.projects.values())
                total_limit = sum(p['quota_limit'] for p in self.projects.values())

                return {
                    'total_used': total_used,
                    'total_limit': total_limit,
                    'current_project': self.current_project,
                    'mode': self.mode,
                    'projects': {
                        pid: {
                            'used': info['quota_used'],
                            'limit': info['quota_limit'],
                            'percentage': (
                                (info['quota_used'] / info['quota_limit']) * 100
                                if info['quota_limit'] > 0 else 0
                            )
                        } for pid, info in self.projects.items()
                    }
                }
        except Exception as e:
            logging.error(f"❌ Failed to get quota status: {e}")
            return {}
