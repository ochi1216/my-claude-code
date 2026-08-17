#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
version : 20260515_04_02
purpose : R19 SharePoint Portal 統合版
          Tab1: R19 Portal（Quick Links + P0*/PS0* サイト一覧）
          Tab2: ICS R19 R&D フォルダツリービューワー
          Tab3: サイト別ツリー（アコーディオン選択 + 個別探索）
"""

import json
import time
import glob
import shutil
import argparse
import webbrowser
import threading
import queue
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import msal
import requests as http_req
from flask import Flask, jsonify, request as flask_req
from flask import Response, stream_with_context

# ─────────────────────────────────────────────────────────────
# 設定ファイル読み込み
# ─────────────────────────────────────────────────────────────
def _load_config(path: str = "config.json") -> dict:
    """config.json を読み込んで返す。存在しない場合は即時終了。"""
    config_path = Path(path)
    if not config_path.exists():
        print(f"[ERROR] {path} が見つかりません。")
        raise SystemExit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

_CFG                = _load_config()
TENANT_ID           = _CFG["tenant_id"]
CLIENT_ID           = _CFG["client_id"]
TOKEN_CACHE_PATH    = _CFG.get("token_cache_path",            "token_cache.json")
SITE_HOST           = _CFG.get("site_host",                   "nexperia.sharepoint.com")
SITE_PATH           = _CFG.get("site_path",                   "/sites/PSBGRD")
MAX_ITEMS           = _CFG.get("max_items_per_folder",         20)
MAX_DEEP_FILES      = _CFG.get("max_deep_files_per_folder",    10)
MAX_DEEP_FOLDERS    = _CFG.get("max_deep_folders_per_folder",  30)
HUMAN_LOOP_INTERVAL = _CFG.get("human_loop_interval",          30)
SKIP_FOLDER_NAMES   = {"old"}
PROTOCOL_MAP        = _CFG.get("file_protocol_map",            {})

SCOPES      = ["https://graph.microsoft.com/Sites.Read.All"]
GRAPH_V1    = "https://graph.microsoft.com/v1.0"
FLASK_PORT  = 5005
CACHE_DIR   = Path("cache")
REGISTRY_FILE = Path("site_registry.json")

DOWNLOAD_PREFS_FILE = Path("download_prefs.json")

_last_download_dir: str = str(Path.home())

PROXIES = {
    # "https": "http://proxy.nexperia.com:8080",
}

JST = timezone(timedelta(hours=9))

_cache:       Optional["LazyCache"]        = None
_client:      Optional["FolderTreeClient"] = None
_registry:    Optional["SiteRegistry"]     = None
_loader:      Optional["PortalDataLoader"] = None
_deep_state:  dict                         = {}
_lock:        threading.Lock               = threading.Lock()
_site_clients: dict                        = {}
_site_caches:  dict                        = {}


_site_deep_state: dict = {
    "running":        False,
    "cancelled":      False,
    "site_name":      "",
    "count":          0,
    "pause_event":    None,
    "pause_interval": 100,
}

flask_app = Flask(__name__)


# ─────────────────────────────────────────────────────────────
# Class: GraphAuthManager  [51行]
# ─────────────────────────────────────────────────────────────
class GraphAuthManager:
    """MSAL Device Code Flow による認証管理クラス"""

    def __init__(self, tenant_id: str, client_id: str, cache_path: str):
        """[13行] MSALアプリとキャッシュを初期化する"""
        self.tenant_id  = tenant_id
        self.client_id  = client_id
        self.cache_path = cache_path
        self.cache      = msal.SerializableTokenCache()
        self._load_cache()
        self.app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=self.cache,
        )

    def _load_cache(self) -> None:
        """[6行] トークンキャッシュをファイルから読み込む"""
        if Path(self.cache_path).exists():
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self.cache.deserialize(f.read())

    def _save_cache(self) -> None:
        """[6行] トークンキャッシュをファイルに書き込む"""
        if self.cache.has_state_changed:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                f.write(self.cache.serialize())

    def get_token(self, scopes: list) -> str:
        """[13行] トークンを取得する。キャッシュ優先・Device Code Flow 補完"""
        accounts = self.app.get_accounts()
        result   = None
        if accounts:
            result = self.app.acquire_token_silent(
                scopes, account=accounts[0]
            )
        if not result:
            flow = self.app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                raise RuntimeError(
                    f"Device Flow 開始失敗: {flow.get('error_description')}"
                )
            print("\n" + "=" * 60)
            print(flow["message"])
            print("=" * 60 + "\n")
            result = self.app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(
                f"トークン取得失敗: {result.get('error_description', '不明')}"
            )
        self._save_cache()
        return result["access_token"]


# ─────────────────────────────────────────────────────────────
# Class: FolderTreeClient  [190行]
# ─────────────────────────────────────────────────────────────
class FolderTreeClient:
    """Graph API でフォルダを段階的に取得するクラス（マルチサイト対応）"""

    def __init__(self, token: str,
                 site_host: str = None,
                 site_path: str = None):
        """[9行] 認証ヘッダーとサイト情報を初期化する"""
        self.headers   = {
            "Authorization": f"Bearer {token}",
            "Accept":        "application/json",
        }
        self.site_host = site_host or SITE_HOST
        self.site_path = site_path or SITE_PATH

    def _request(self, url: str) -> dict:
        """
        [29行] GETリクエストを実行する。
        403 → PermissionError 即時 raise。
        400 / 404 → {"_not_found": True} を返す。
        503 / Timeout → 3回リトライ。
        """
        MAX_RETRY  = 3
        last_error = None
        for attempt in range(1, MAX_RETRY + 1):
            try:
                resp = http_req.get(
                    url,
                    headers=self.headers,
                    proxies=PROXIES,
                    timeout=30,
                )
                if resp.status_code == 403:
                    raise PermissionError(
                        "403 Forbidden: Sites.Read.All の"
                        " Admin Consent を確認してください。"
                    )
                if resp.status_code in (400, 404):
                    return {"_not_found": True}
                resp.raise_for_status()
                return resp.json()
            except PermissionError:
                raise
            except Exception as e:
                last_error = e
                print(f"  [リトライ {attempt}/{MAX_RETRY}] {e}")
                time.sleep(1)
        raise RuntimeError(
            f"リクエスト失敗（{MAX_RETRY}回試行）: {last_error}"
        )

    def get_site_id(self) -> str:
        """[10行] サイトIDを取得する。"""
        url     = f"{GRAPH_V1}/sites/{self.site_host}:{self.site_path}"
        data    = self._request(url)
        site_id = data.get("id", "")
        if not site_id:
            raise RuntimeError(f"site-id 取得失敗: {data}")
        print(f"  [OK] site-id 取得: {site_id} ({self.site_path})")
        return site_id

    def get_drive_id(self, site_id: str) -> str:
        """
        [18行] Shared Documents の drive-id を取得する。
        判定優先順位:
          1. name == "Documents"
          2. name == "Shared Documents"
          3. driveType == "documentLibrary" の先頭
        """
        url    = f"{GRAPH_V1}/sites/{site_id}/drives"
        data   = self._request(url)
        drives = data.get("value", [])
        for priority_name in ["Documents", "Shared Documents"]:
            for d in drives:
                if d.get("name", "") == priority_name:
                    print(
                        f"  [OK] drive-id 取得: {d['id']}"
                        f" (name={d['name']})"
                    )
                    return d["id"]
        for d in drives:
            if d.get("driveType", "") == "documentLibrary":
                print(f"  [OK] drive-id 取得（fallback）: {d['id']}")
                return d["id"]
        raise RuntimeError("Shared Documents の drive が見つかりません。")

    def fetch_all_children(self, drive_id: str, item_id: str) -> list:
        """[16行] 指定アイテムの子一覧をページネーション対応で全件取得する。"""
        if item_id == "root":
            url = (
                f"{GRAPH_V1}/drives/{drive_id}"
                f"/root/children?$top=100"
            )
        else:
            url = (
                f"{GRAPH_V1}/drives/{drive_id}"
                f"/items/{item_id}/children?$top=100"
            )
        items = []
        while url:
            data = self._request(url)
            if data.get("_not_found"):
                break
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink", None)
            if url:
                time.sleep(0.2)
        return items

    def _build_file_url(self, name: str, web_url: str) -> str:
        """[3行] 常に web_url を返す。ms-officeプロトコルは廃止。"""
        return web_url


    def fetch_one_level(self, drive_id: str, item_id: str) -> dict:
        """[33行] 指定フォルダの直下1階層のみ取得する（モードB・制約なし）。"""
        children    = self.fetch_all_children(drive_id, item_id)
        folders_raw = [c for c in children if "folder" in c]
        files_raw   = [c for c in children if "file"   in c]

        folders = [
            {
                "name":    f.get("name", ""),
                "web_url": f.get("webUrl", ""),
                "id":      f.get("id",     ""),
            }
            for f in folders_raw
        ]
        files = [
            {
                "name":          f.get("name", ""),
                "web_url":       f.get("webUrl", ""),
                "local_url":     self._build_file_url(
                                     f.get("name", ""),
                                     f.get("webUrl", "")
                                 ),
                "size":          f.get("size", 0),
                "last_modified": f.get("lastModifiedDateTime", ""),
                "item_id":       f.get("id", ""),
            }
            for f in files_raw
        ]
        return {
            "folders":      folders,
            "files":        files,
            "truncated":    False,
            "desc_folders": 0,
            "desc_files":   0,
        }


    def fetch_deep(self, drive_id: str, item_id: str, path: str,
                   cache: "LazyCache", deep_state: dict,
                   event_q: "queue.Queue",
                   current_depth: int = 0,
                   max_depth: int = 3) -> None:
        """[66行] 再帰探索（モードA）。count-based pause対応。"""
        if deep_state.get("cancelled"):
            return

        event_q.put({"type": "exploring", "path": path})

        children    = self.fetch_all_children(drive_id, item_id)
        folders_raw = [c for c in children if "folder" in c]
        files_raw   = [c for c in children if "file"   in c]

        truncated = (
            len(folders_raw) >= MAX_DEEP_FOLDERS or
            len(files_raw)   >= MAX_DEEP_FILES
        )

        if truncated:
            result = {
                "folders":      [],
                "files":        [],
                "truncated":    True,
                "desc_folders": len(folders_raw),
                "desc_files":   len(files_raw),
            }
            with _lock:
                cache.set_explored(path, result)
            return

        files = [
            {
                "name":          f.get("name", ""),
                "web_url":       f.get("webUrl", ""),
                "local_url":     self._build_file_url(
                                     f.get("name", ""),
                                     f.get("webUrl", "")
                                 ),
                "size":          f.get("size", 0),
                "last_modified": f.get("lastModifiedDateTime", ""),
                "item_id":       f.get("id", ""),
            }
            for f in files_raw
        ]

        folders = [
            {
                "name":    f.get("name", ""),
                "web_url": f.get("webUrl", ""),
                "id":      f.get("id",     ""),
            }
            for f in folders_raw
            if f.get("name", "").lower() not in SKIP_FOLDER_NAMES
        ]

        skipped = len(folders_raw) - len(folders)
        if skipped > 0:
            print(f"  [スキップ] {path} 内の 'old' フォルダ {skipped}件")

        result = {
            "folders":      folders,
            "files":        files,
            "truncated":    False,
            "desc_folders": 0,
            "desc_files":   0,
        }

        with _lock:
            cache.set_explored(path, result)

        deep_state["count"]        += 1
        deep_state["current_path"]  = path

        event_q.put({
            "type":  "progress",
            "count": deep_state["count"],
            "path":  path,
        })

        _pause_ev  = deep_state.get("pause_event")
        _pause_int = deep_state.get("pause_interval", 0)
        if (_pause_ev and _pause_int > 0
                and deep_state["count"] % _pause_int == 0):
            event_q.put({
                "type":  "paused",
                "count": deep_state["count"],
                "path":  path,
            })
            _pause_ev.clear()
            _pause_ev.wait()
            if deep_state.get("cancelled"):
                return
            deep_state["count"] = 0

        if current_depth < max_depth - 1:
            for folder in folders:
                if deep_state.get("cancelled"):
                    return
                sub_path = (
                    f"/{folder['name']}"
                    if path == "/"
                    else f"{path}/{folder['name']}"
                )
                self.fetch_deep(
                    drive_id,
                    folder["id"],
                    sub_path,
                    cache,
                    deep_state,
                    event_q,
                    current_depth + 1,
                    max_depth,
                )

# ─────────────────────────────────────────────────────────────
# Class: LazyCache  [75行]
# ─────────────────────────────────────────────────────────────
class LazyCache:
    """累積追記式キャッシュ管理クラス"""

    def __init__(self, cache_path: str):
        """[8行] キャッシュパスと初期データを設定する"""
        self.cache_path = Path(cache_path)
        self.data: dict = {
            "site":       "",
            "drive_id":   "",
            "created_at": "",
            "updated_at": "",
            "explored":   {},
        }

    def load(self) -> bool:
        """[8行] キャッシュファイルを読み込む。存在しない場合は False を返す。"""
        if not self.cache_path.exists():
            return False
        with open(self.cache_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        print(f"  [OK] キャッシュ読み込み: {self.cache_path}")
        return True

    def save(self) -> None:
        """[8行] キャッシュをファイルに保存する。"""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = datetime.now(JST).strftime(
            "%Y-%m-%d %H:%M:%S JST"
        )
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_explored(self, path: str) -> "Optional[dict]":
        """[6行] 指定パスの探索済みデータを返す。未探索は None。"""
        return self.data.get("explored", {}).get(path, None)

    def set_explored(self, path: str, result: dict) -> None:
        """[10行] 探索結果をキャッシュに追記して保存する。"""
        result["explored_at"] = datetime.now(JST).strftime(
            "%Y-%m-%d %H:%M:%S JST"
        )
        if "explored" not in self.data:
            self.data["explored"] = {}
        self.data["explored"][path] = result
        self.save()
        print(f"  [OK] キャッシュ追記: {path}")

    def reset(self) -> None:
        """[6行] キャッシュファイルを削除して初期状態に戻す。"""
        if self.cache_path.exists():
            self.cache_path.unlink()
        self.data = {
            "site":       "",
            "drive_id":   "",
            "created_at": "",
            "updated_at": "",
            "explored":   {},
        }
        print(f"  [OK] キャッシュをリセットしました: {self.cache_path}")

    def path_to_item_id(self, path: str) -> "Optional[str]":
        """[20行] パス文字列を Graph API の item-id に解決する。"""
        if path == "/":
            return "root"

        parts        = [p for p in path.split("/") if p]
        current_path = "/"
        current_id   = "root"

        for part in parts:
            explored = self.get_explored(current_path)
            if not explored:
                return None
            folders  = explored.get("folders", [])
            found    = next(
                (f for f in folders if f.get("name") == part), None
            )
            if not found:
                return None
            current_id   = found.get("id", "")
            current_path = (
                f"/{part}"
                if current_path == "/"
                else f"{current_path}/{part}"
            )

        return current_id


# ─────────────────────────────────────────────────────────────
# Class: SiteRegistry  [54行]
# ─────────────────────────────────────────────────────────────
class SiteRegistry:
    """サイト情報の永続管理クラス"""

    def __init__(self, registry_path: Path):
        """[8行] レジストリパスと初期データを設定する"""
        self.registry_path = registry_path
        self.data: dict    = {}

    def load(self) -> bool:
        """[8行] レジストリファイルを読み込む。存在しない場合は False を返す。"""
        if not self.registry_path.exists():
            return False
        with open(self.registry_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        print(f"  [OK] レジストリ読み込み: {len(self.data)} サイト")
        return True

    def save(self) -> None:
        """[6行] レジストリをファイルに保存する。"""
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_site(self, site_name: str) -> "Optional[dict]":
        """[4行] サイト情報を返す。存在しない場合は None。"""
        return self.data.get(site_name, None)

    def register_site(self, site_name: str, name: str,
                      host: str, path: str, group: str) -> None:
        """[10行] サイトをレジストリに登録する。既存の drive_id は保持。"""
        existing  = self.data.get(site_name, {})
        drive_id  = existing.get("drive_id", "")
        self.data[site_name] = {
            "name":     name,
            "host":     host,
            "path":     path,
            "drive_id": drive_id,
            "group":    group,
        }

    def update_drive_id(self, site_name: str, drive_id: str) -> None:
        """[6行] drive_id を更新して保存する。"""
        if site_name in self.data:
            self.data[site_name]["drive_id"] = drive_id
            self.save()
            print(f"  [OK] drive_id 更新: {site_name}")

    def get_p0_sites(self) -> list:
        """[6行] P0* グループのサイト一覧を返す（name昇順）。"""
        sites = [
            {"site_name": k, **v}
            for k, v in self.data.items()
            if v.get("group") == "p0"
        ]
        return sorted(sites, key=lambda x: x["name"].lower())

    def get_ps0_sites(self) -> list:
        """[6行] PS0* グループのサイト一覧を返す（name昇順）。"""
        sites = [
            {"site_name": k, **v}
            for k, v in self.data.items()
            if v.get("group") == "ps0"
        ]
        return sorted(sites, key=lambda x: x["name"].lower())


# ─────────────────────────────────────────────────────────────
# Class: PortalDataLoader  [60行]
# ─────────────────────────────────────────────────────────────
class PortalDataLoader:
    """起動時に各種JSONを自動検出・読み込むクラス"""

    def __init__(self):
        """[6行] データ格納用フィールドを初期化する"""
        self.quick_links: list = []
        self.sites_total: int  = 0

    def ensure_cache_dir(self) -> None:
        """
        [12行] cache/ フォルダを確認・作成する。
        旧パスに tree_PSBGRD_lazy.json が存在する場合は
        cache/ 配下に自動移動する。
        """
        CACHE_DIR.mkdir(exist_ok=True)
        old_path = Path("tree_PSBGRD_lazy.json")
        new_path = CACHE_DIR / "tree_PSBGRD_lazy.json"
        if old_path.exists() and not new_path.exists():
            shutil.move(str(old_path), str(new_path))
            print(f"  [OK] キャッシュ移動: {old_path} → {new_path}")

    def load_quicklinks(self) -> list:
        """[12行] quick_links_*.json から最新ファイルを読み込む。"""
        files = sorted(glob.glob("quick_links_*.json"), reverse=True)
        if not files:
            print("  [警告] quick_links_*.json が見つかりません。")
            return []
        with open(files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        self.quick_links = data.get("quick_links", [])
        print(f"  [OK] Quick Links 読み込み: {len(self.quick_links)} 件 ({files[0]})")
        return self.quick_links

    def load_sites(self, registry: SiteRegistry) -> None:
        """
        [30行] sites_list_*.json から最新ファイルを読み込み
        P0*/PS0* サイトを SiteRegistry に登録する。
        """
        files = sorted(glob.glob("sites_list_*.json"), reverse=True)
        if not files:
            print("  [警告] sites_list_*.json が見つかりません。")
            return

        with open(files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        sites           = data.get("sites", [])
        self.sites_total = data.get("total_count", len(sites))
        p0_count        = 0
        ps0_count       = 0

        SKIP_NAMES = {"old"}
        for s in sites:
            name    = s.get("displayName", "")
            web_url = s.get("webUrl", "")
            if not name or not web_url:
                continue

            name_lc = name.lower()
            if name_lc in SKIP_NAMES:
                continue

            # site_name をURLから生成
            site_name = web_url.rstrip("/").split("/")[-1]
            host      = web_url.split("/")[2].split(".sharepoint.com")[0]
            host      = host + ".sharepoint.com"
            path      = "/" + "/".join(web_url.split("/")[3:])

            if name_lc.startswith("ps0"):
                registry.register_site(site_name, name, host, path, "ps0")
                ps0_count += 1
            elif name_lc.startswith("p0"):
                registry.register_site(site_name, name, host, path, "p0")
                p0_count += 1

        # PSBGRD を portal グループとして登録
        registry.register_site(
            "PSBGRD", "ICS R19 R&D",
            SITE_HOST, SITE_PATH, "portal"
        )

        registry.save()
        print(
            f"  [OK] サイト登録完了: "
            f"P0*={p0_count}件 / PS0*={ps0_count}件 ({files[0]})"
        )


# ─────────────────────────────────────────────────────────────
# ユーティリティ関数
# ─────────────────────────────────────────────────────────────
def _get_site_cache(site_name: str) -> LazyCache:
    """指定サイトのキャッシュを返す。存在しない場合は新規作成。"""
    if site_name not in _site_caches:
        cache_path = CACHE_DIR / f"tree_{site_name}_lazy.json"
        cache      = LazyCache(str(cache_path))
        cache.load()
        _site_caches[site_name] = cache
    return _site_caches[site_name]


def _get_site_client(site_name: str, token: str) -> FolderTreeClient:
    """指定サイトのクライアントを返す。存在しない場合は新規作成。"""
    if site_name not in _site_clients:
        site_info = _registry.get_site(site_name)
        if not site_info:
            raise ValueError(f"サイト未登録: {site_name}")
        client = FolderTreeClient(
            token,
            site_host=site_info["host"],
            site_path=site_info["path"],
        )
        _site_clients[site_name] = client
    return _site_clients[site_name]


def _load_download_prefs() -> None:
    """[10行] download_prefs.json から前回のDL先フォルダを読み込む。"""
    global _last_download_dir
    if DOWNLOAD_PREFS_FILE.exists():
        try:
            prefs = json.loads(DOWNLOAD_PREFS_FILE.read_text(encoding="utf-8"))
            saved = prefs.get("last_dir", "")
            if saved and Path(saved).exists():
                _last_download_dir = saved
        except Exception:
            pass  # 読み込み失敗は無視してデフォルト（home）を使用


_load_download_prefs()

# ─────────────────────────────────────────────────────────────
# Flask ルート定義
# ─────────────────────────────────────────────────────────────
@flask_app.route("/")
def route_index() -> str:
    resp = flask_app.make_response(HTML_TEMPLATE)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# --- Tab2 用（既存流用）---

@flask_app.route("/api/tree")
def route_tree():
    """[4行] PSBGRD キャッシュデータを返す"""
    return jsonify(_cache.data)


@flask_app.route("/api/expand", methods=["POST"])
def route_expand():
    """[44行] PSBGRD の指定パスを1階層探索する（モードB）"""
    body = flask_req.get_json(force=True, silent=True) or {}
    path = body.get("path", "/")

    existing = _cache.get_explored(path)
    if existing is not None and not existing.get("truncated", False):
        return jsonify({"ok": True, "tree": _cache.data,
                        "message": "既に探索済みです"})

    item_id = _cache.path_to_item_id(path)
    if item_id is None:
        return jsonify({
            "ok":      False,
            "message": f"パスを解決できません: {path}",
        }), 400

    drive_id = _cache.data.get("drive_id", "")
    if not drive_id:
        return jsonify({
            "ok":      False,
            "message": "drive_id が未設定です。",
        }), 500

    try:
        result = _client.fetch_one_level(drive_id, item_id)
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

    force     = body.get("force", False)
    n_folders = len(result["folders"])
    n_files   = len(result["files"])
    if not force and (
        n_folders >= MAX_DEEP_FOLDERS or
        n_files   >= MAX_DEEP_FOLDERS
    ):
        return jsonify({
            "ok":      "confirm",
            "path":    path,
            "folders": n_folders,
            "files":   n_files,
        })

    with _lock:
        _cache.set_explored(path, result)

    print(
        f"  [探索完了] {path} → "
        f"フォルダ:{n_folders} / ファイル:{n_files}"
    )
    return jsonify({"ok": True, "tree": _cache.data})


@flask_app.route("/api/expand_deep")
def route_expand_deep():
    """[48行] PSBGRD の3階層再帰探索（SSEストリーミング）"""
    if _deep_state.get("running"):
        def _already():
            yield (
                "data: " +
                json.dumps(
                    {"type": "error", "message": "既に探索中です"},
                    ensure_ascii=False
                ) + "\n\n"
            )
        return Response(
            stream_with_context(_already()),
            mimetype="text/event-stream"
        )

    _deep_state["running"]   = True
    _deep_state["cancelled"] = False
    _deep_state["count"]     = 0
    _deep_state["pause_event"].set()

    event_q  = queue.Queue()
    drive_id = _cache.data.get("drive_id", "")

    def _run() -> None:
        try:
            _client.fetch_deep(
                drive_id, "root", "/",
                _cache, _deep_state, event_q,
            )
            if _deep_state.get("cancelled"):
                event_q.put({
                    "type":  "cancelled",
                    "count": _deep_state["count"],
                    "tree":  _cache.data,
                })
            else:
                event_q.put({
                    "type":  "done",
                    "count": _deep_state["count"],
                    "tree":  _cache.data,
                })
        except Exception as e:
            event_q.put({"type": "error", "message": str(e)})
        finally:
            _deep_state["running"] = False

    threading.Thread(target=_run, daemon=True).start()

    def _generate():
        while True:
            try:
                event = event_q.get(timeout=30)
                yield (
                    "data: " +
                    json.dumps(event, ensure_ascii=False) +
                    "\n\n"
                )
                if event["type"] in ("done", "cancelled", "error"):
                    break
            except queue.Empty:
                yield ": heartbeat\n\n"
                if not _deep_state.get("running"):
                    break

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@flask_app.route("/api/expand_deep/resume", methods=["POST"])
def route_expand_deep_resume():
    """[9行] ヒューマンループ一時停止中の探索を再開する"""
    if not _deep_state.get("running"):
        return jsonify({"ok": False, "message": "探索中ではありません"}), 400
    _deep_state["pause_event"].set()
    return jsonify({"ok": True})


@flask_app.route("/api/expand_deep/cancel", methods=["POST"])
def route_expand_deep_cancel():
    """[9行] 探索をキャンセルする。取得済み分はキャッシュ保存済み。"""
    if not _deep_state.get("running"):
        return jsonify({"ok": False, "message": "探索中ではありません"}), 400
    _deep_state["cancelled"] = True
    _deep_state["pause_event"].set()
    return jsonify({"ok": True})


@flask_app.route("/api/reset", methods=["POST"])
def route_reset():
    """[7行] PSBGRD キャッシュを全削除して初期状態に戻す"""
    with _lock:
        _cache.reset()
    return jsonify({"ok": True, "message": "キャッシュをリセットしました。"})


# --- Tab1 用（新規）---

@flask_app.route("/api/portal/links")
def route_portal_links():
    """[4行] Quick Links JSON を返す"""
    return jsonify({
        "quick_links": _loader.quick_links,
        "total":       len(_loader.quick_links),
    })


@flask_app.route("/api/portal/sites")
def route_portal_sites():
    """[8行] P0*/PS0* サイト一覧を返す"""
    return jsonify({
        "p0":  _registry.get_p0_sites(),
        "ps0": _registry.get_ps0_sites(),
    })


# --- Tab3 用（新規）---

@flask_app.route("/api/portal/site_tree/<site_name>")
def route_portal_site_tree(site_name: str):
    """[8行] 指定サイトのキャッシュを返す"""
    try:
        cache = _get_site_cache(site_name)
        return jsonify(cache.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/portal/expand/<site_name>", methods=["POST"])
def route_portal_expand(site_name: str):
    """
    [40行] 指定サイトの指定パスを1階層探索する。
    drive_id が未取得の場合は Graph API で取得して登録する。
    """
    body = flask_req.get_json(force=True, silent=True) or {}
    path = body.get("path", "/")

    try:
        cache = _get_site_cache(site_name)

        existing = cache.get_explored(path)
        if existing is not None and not existing.get("truncated", False):
            return jsonify({"ok": True, "tree": cache.data,
                            "message": "既に探索済みです"})

        site_info = _registry.get_site(site_name)
        if not site_info:
            return jsonify({
                "ok":      False,
                "message": f"サイト未登録: {site_name}",
            }), 404

        # drive_id が未取得の場合は Graph API で取得
        drive_id = cache.data.get("drive_id", "")
        if not drive_id:
            token  = _client.headers["Authorization"].replace("Bearer ", "")
            client = _get_site_client(site_name, token)
            site_id  = client.get_site_id()
            drive_id = client.get_drive_id(site_id)
            cache.data["drive_id"]   = drive_id
            cache.data["site"]       = site_name
            cache.data["created_at"] = datetime.now(JST).strftime(
                "%Y-%m-%d %H:%M:%S JST"
            )
            cache.save()
            _registry.update_drive_id(site_name, drive_id)
        else:
            token  = _client.headers["Authorization"].replace("Bearer ", "")
            client = _get_site_client(site_name, token)

        item_id = cache.path_to_item_id(path)
        if item_id is None:
            return jsonify({
                "ok":      False,
                "message": f"パスを解決できません: {path}",
            }), 400

        result = client.fetch_one_level(drive_id, item_id)

    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

    with _lock:
        cache.set_explored(path, result)

    print(
        f"  [探索完了] {site_name}:{path} → "
        f"フォルダ:{len(result['folders'])} / "
        f"ファイル:{len(result['files'])}"
    )
    return jsonify({"ok": True, "tree": cache.data})


@flask_app.route("/api/portal/reset/<site_name>", methods=["POST"])
def route_portal_reset(site_name: str):
    """[8行] 指定サイトのキャッシュをリセットする"""
    try:
        cache = _get_site_cache(site_name)
        with _lock:
            cache.reset()
        if site_name in _site_caches:
            del _site_caches[site_name]
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@flask_app.route("/api/portal/expand_deep/<site_name>")
def route_portal_expand_deep(site_name: str):
    """
    [101行] 指定サイトの再帰探索をSSEストリーミングで実行する。
    ?depth=N  : 探索深さ指定（1/2/3/6=全階層）。デフォルト3。
    ?start_path: 探索開始パス指定。デフォルト"/"（後方互換）。
    count-based pause（100フォルダ）対応。CR-5/CR-6対応。
    """
    depth = flask_req.args.get("depth", 3, type=int)
    if depth <= 0 or depth > 6:
        depth = 6

    # [CR-5] start_path パラメータ（デフォルト"/"で既存呼び出しと後方互換）
    start_path = flask_req.args.get("start_path", "/")

    if _site_deep_state.get("running"):
        def _busy():
            yield (
                "data: " +
                json.dumps({
                    "type":    "error",
                    "message": f"既に {_site_deep_state['site_name']} を探索中です",
                }, ensure_ascii=False) + "\n\n"
            )
        return Response(
            stream_with_context(_busy()),
            mimetype="text/event-stream"
        )

    with _lock:
        _site_deep_state["running"]   = True
        _site_deep_state["cancelled"] = False
        _site_deep_state["site_name"] = site_name
        _site_deep_state["count"]     = 0
        _site_deep_state["pause_event"].set()

    event_q = queue.Queue()

    def _run() -> None:
        try:
            cache     = _get_site_cache(site_name)
            site_info = _registry.get_site(site_name)
            if not site_info:
                event_q.put({"type": "error",
                             "message": f"サイト未登録: {site_name}"})
                return

            drive_id = cache.data.get("drive_id", "")
            if not drive_id:
                token    = _client.headers["Authorization"].replace("Bearer ", "")
                client   = _get_site_client(site_name, token)
                site_id  = client.get_site_id()
                drive_id = client.get_drive_id(site_id)
                cache.data["drive_id"]   = drive_id
                cache.data["site"]       = site_name
                cache.data["created_at"] = datetime.now(JST).strftime(
                    "%Y-%m-%d %H:%M:%S JST"
                )
                cache.save()
                _registry.update_drive_id(site_name, drive_id)
            else:
                token  = _client.headers["Authorization"].replace("Bearer ", "")
                client = _get_site_client(site_name, token)

            # [CR-5] start_path → item_id の解決（fetch_deep は変更しない）
            # [CR-6] item_id が None の場合はSSEエラーを返して正常終了
            if start_path == "/":
                item_id = "root"
            else:
                item_id = cache.path_to_item_id(start_path)
                if item_id is None:
                    event_q.put({
                        "type":    "error",
                        "message": f"パスを解決できません: {start_path}"
                                   f"（先にルートフォルダを探索してください）",
                    })
                    return

            client.fetch_deep(
                drive_id, item_id, start_path,
                cache, _site_deep_state, event_q,
                max_depth=depth,
            )

            if _site_deep_state.get("cancelled"):
                event_q.put({
                    "type":  "cancelled",
                    "count": _site_deep_state["count"],
                    "tree":  cache.data,
                })
            else:
                event_q.put({
                    "type":  "done",
                    "count": _site_deep_state["count"],
                    "tree":  cache.data,
                })
        except Exception as e:
            event_q.put({"type": "error", "message": str(e)})
        finally:
            _site_deep_state["running"] = False

    threading.Thread(target=_run, daemon=True).start()

    def _generate():
        while True:
            try:
                event = event_q.get(timeout=30)
                yield (
                    "data: " +
                    json.dumps(event, ensure_ascii=False) +
                    "\n\n"
                )
                if event["type"] in ("done", "cancelled", "error"):
                    break
                # "paused" はストリームを維持して継続
            except queue.Empty:
                yield ": heartbeat\n\n"
                if not _site_deep_state.get("running"):
                    break

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@flask_app.route(
    "/api/portal/expand_deep/<site_name>/cancel",
    methods=["POST"]
)
def route_portal_expand_deep_cancel(site_name: str):
    """[11行] 探索をキャンセルする。pause中のデッドロックも防止する。"""
    if not _site_deep_state.get("running"):
        return jsonify({"ok": False, "message": "探索中ではありません"}), 400
    if _site_deep_state.get("site_name") != site_name:
        return jsonify({"ok": False, "message": "別のサイトを探索中です"}), 400
    _site_deep_state["cancelled"] = True
    _site_deep_state["pause_event"].set()   # [Bug Fix] pause中のデッドロック防止
    return jsonify({"ok": True})

@flask_app.route(
    "/api/portal/expand_deep/<site_name>/resume",
    methods=["POST"]
)
def route_portal_expand_deep_resume(site_name: str):
    """[12行] count-based pause を解除して探索を再開する。"""
    if not _site_deep_state.get("running"):
        return jsonify({"ok": False, "message": "探索中ではありません"}), 400
    if _site_deep_state.get("site_name") != site_name:
        return jsonify({"ok": False, "message": "別のサイトを探索中です"}), 400
    _site_deep_state["pause_event"].set()
    return jsonify({"ok": True})


@flask_app.route("/api/pick-folder", methods=["POST"])
def route_pick_folder():
    """[38行] subprocess経由でtkinterフォルダ選択ダイアログを起動し、
    選択パスを返す。前回パスをinitial_dirとして使用する。
    選択後は _last_download_dir と download_prefs.json に保存する。
    [v2.1] パス渡しを json.dumps+sys.argv 方式に変更（バックスラッシュ安全化）"""
    global _last_download_dir

    # [Bug②修正] パスをsys.argv[1]にJSON渡し → バックスラッシュ・引用符を安全に処理
    script = (
        "import sys,json,tkinter as tk; from tkinter import filedialog; "
        "init=json.loads(sys.argv[1]); "
        "root=tk.Tk(); root.withdraw(); root.lift(); "
        "root.attributes('-topmost',True); "
        "chosen=filedialog.askdirectory("
        "title='\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u5148\u30d5\u30a9\u30eb\u30c0\u3092\u9078\u629e\u3057\u3066\u304f\u3060\u3055\u3044',"
        "initialdir=init); "
        "print(chosen if chosen else '',end='')"
    )

    try:
        result = subprocess.run(
            [sys.executable, "-c", script, json.dumps(_last_download_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        chosen = result.stdout.strip()
    except Exception as e:
        print(f"  [pick-folder] subprocessエラー: {e}", flush=True)
        return jsonify({"ok": False, "message": str(e)}), 500

    if not chosen:
        return jsonify({"ok": False, "cancelled": True,
                        "message": "キャンセルされました"})

    _last_download_dir = chosen
    try:
        DOWNLOAD_PREFS_FILE.write_text(
            json.dumps({"last_dir": chosen}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # prefs保存失敗は無視して続行

    return jsonify({"ok": True, "folder": chosen})


@flask_app.route("/api/download-to-folder", methods=["POST"])
def route_download_to_folder():
    """[57行] SharePointからファイルを取得してローカルフォルダに保存する。
    route_download と同じ認証・リダイレクト処理を使用する。
    [v2.04] 選択フォルダ下にサイト名サブフォルダを自動作成して保存。"""
    body      = flask_req.get_json(force=True, silent=True) or {}
    site_name = body.get("site_name", "")
    item_id   = body.get("item_id",   "")
    drive_id  = body.get("drive_id",  "")
    filename  = body.get("filename",  "download")
    folder    = body.get("folder_path", "")

    if not item_id or not drive_id or not folder:
        return jsonify({"ok": False,
                        "message": "item_id / drive_id / folder_path は必須です"}), 400

    # [v2.04] 選択フォルダ下にサイト名サブフォルダを作成（既存なら流用）
    save_dir  = Path(folder) / site_name
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename

    if _auth is None:
        return jsonify({"ok": False, "message": "認証が初期化されていません"}), 500

    with _lock:
        token = _auth.get_token(SCOPES)

    headers      = {"Authorization": f"Bearer {token}"}
    download_url = f"{GRAPH_V1}/drives/{drive_id}/items/{item_id}/content"

    try:
        resp = http_req.get(
            download_url,
            headers=headers,
            proxies=PROXIES,
            allow_redirects=False,
            timeout=30,
            stream=True,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            redirect_url = resp.headers.get("Location", "")
            if not redirect_url:
                return jsonify({"ok": False,
                                "message": "リダイレクト先URLが取得できません"}), 502
            resp.close()
            resp = http_req.get(
                redirect_url,
                proxies=PROXIES,
                timeout=60,
                stream=True,
            )
        if resp.status_code == 401:
            resp.close()
            return jsonify({"ok": False, "message": "認証エラー: トークンが無効です"}), 401
        if resp.status_code == 404:
            resp.close()
            return jsonify({"ok": False, "message": "ファイルが見つかりません"}), 404

        resp.raise_for_status()

        with open(save_path, "wb") as f:
            shutil.copyfileobj(resp.raw, f)

        resp.close()
        print(f"  [保存完了] {site_name}/{filename} → {save_path}", flush=True)
        return jsonify({"ok": True, "saved_path": str(save_path)})

    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500



@flask_app.route("/api/download/<site_name>")
def route_download(site_name: str):
    """
    [55行] Graph APIからファイルをストリーミング取得してブラウザに転送する。
    CR-17: _auth.get_token()で毎回トークンを再取得。
    CR-18: stream=True / chunk_size=8192 / RFC5987ファイル名エンコード。
    CR-19: 302リダイレクトを手動処理（Authorizationヘッダー引き継ぎ防止）。
    CR-26: _lockでtoken_cache.jsonの競合書き込みを防止。
    """
    item_id  = flask_req.args.get("item_id",  "")
    drive_id = flask_req.args.get("drive_id", "")
    filename = flask_req.args.get("filename", "download")

    if not item_id or not drive_id:
        return jsonify({"error": "item_id と drive_id は必須です"}), 400

    if _auth is None:
        return jsonify({"error": "認証が初期化されていません"}), 500

    # [CR-26] _lock で token_cache.json の競合書き込みを防止
    # [CR-17] MSALキャッシュ優先で毎回トークンを再取得
    with _lock:
        token = _auth.get_token(SCOPES)

    headers      = {"Authorization": f"Bearer {token}"}
    download_url = f"{GRAPH_V1}/drives/{drive_id}/items/{item_id}/content"

    try:
        # [CR-19] allow_redirects=False で302を手動処理
        resp = http_req.get(
            download_url,
            headers=headers,
            proxies=PROXIES,
            allow_redirects=False,
            timeout=30,
            stream=True,
        )

        # [CR-19] 302リダイレクト先にはAuthorizationなしでアクセス
        if resp.status_code in (301, 302, 303, 307, 308):
            redirect_url = resp.headers.get("Location", "")
            if not redirect_url:
                return jsonify({"error": "リダイレクト先URLが取得できません"}), 502
            resp.close()
            resp = http_req.get(
                redirect_url,
                proxies=PROXIES,
                timeout=60,
                stream=True,
            )

        if resp.status_code == 401:
            resp.close()
            return jsonify({"error": "認証エラー: トークンが無効です"}), 401
        if resp.status_code == 404:
            resp.close()
            return jsonify({"error": "ファイルが見つかりません"}), 404

        resp.raise_for_status()

        # [CR-18] RFC 5987 形式でファイル名エンコード（日本語対応）
        encoded_name = quote(filename, safe="")
        content_type = resp.headers.get(
            "Content-Type", "application/octet-stream"
        )

        # [CR-18] stream_with_context でチャンク転送（メモリフルバッファ防止）
        def _generate():
            try:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                resp.close()

        return Response(
            stream_with_context(_generate()),
            headers={
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{encoded_name}"
                ),
                "Content-Type":  content_type,
                "Cache-Control": "no-cache",
            },
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# HTML テンプレート
# ─────────────────────────────────────────────────────────────
_HTML_RAW = '''<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>R19 SharePoint Portal</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', 'Noto Sans JP', sans-serif;
      background: #f3f4f6;
      color: #1f2937;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }

    /* ── ポータルヘッダー ── */
    .portal-header {
      background: #1e3a5f;
      color: #fff;
      padding: 12px 24px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .portal-header h1 { font-size: 18px; font-weight: 600; flex: 1; }
    .portal-header .meta { font-size: 11px; opacity: 0.7; }

    /* ── タブ ── */
    .tab-bar {
      background: #1e3a5f;
      display: flex;
      gap: 2px;
      padding: 0 16px;
      flex-shrink: 0;
      border-bottom: 2px solid #0f2a4f;
    }
    .tab-btn {
      padding: 10px 20px;
      background: transparent;
      border: none;
      color: rgba(255,255,255,0.6);
      font-size: 13px;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -2px;
      transition: all 0.15s;
    }
    .tab-btn:hover { color: #fff; }
    .tab-btn.active {
      color: #fff;
      border-bottom-color: #60a5fa;
      font-weight: 600;
    }

    /* ── タブコンテンツ ── */
    .tab-content {
      flex: 1;
      overflow: hidden;
      display: none;
      flex-direction: column;
    }
    .tab-content.active { display: flex; }

    /* ── Tab1: Portal ── */
    .portal-body {
      flex: 1;
      overflow-y: auto;
      padding: 16px 20px;
    }
    .portal-section {
      margin-bottom: 12px;
      border-radius: 10px;
      overflow: hidden;
      box-shadow: 0 1px 6px rgba(0,0,0,0.07);
    }
    .portal-section summary {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 18px;
      cursor: pointer;
      list-style: none;
      user-select: none;
    }
    .portal-section summary::-webkit-details-marker { display: none; }
    .portal-section summary::before {
      content: '▶';
      font-size: 10px;
      color: rgba(255,255,255,0.8);
      transition: transform 0.15s;
    }
    .portal-section[open] summary::before { transform: rotate(90deg); }
    .section-label {
      font-size: 14px;
      font-weight: 600;
      color: #fff;
      flex: 1;
    }
    .section-badge {
      font-size: 12px;
      font-weight: 600;
      padding: 2px 10px;
      border-radius: 99px;
    }
    .section-body {
      background: #fff;
      max-height: 55vh;
      overflow-y: auto;
    }
    .portal-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 18px;
      border-bottom: 1px solid #f3f4f6;
      font-size: 13px;
    }
    .portal-item:last-child { border-bottom: none; }
    .portal-item:hover { background: #f0f6ff; }
    .portal-item a {
      color: #0f4a8a;
      text-decoration: none;
      flex: 1;
    }
    .portal-item a:hover { text-decoration: underline; }
    .portal-item .btn-sm {
      padding: 3px 10px;
      background: #0f4a8a;
      color: #fff;
      border: none;
      border-radius: 5px;
      font-size: 11px;
      cursor: pointer;
      text-decoration: none;
      white-space: nowrap;
    }
    .portal-item .btn-sm:hover { background: #0a3a6e; }
    .portal-search {
      padding: 10px 18px;
      background: #f9fafb;
      border-bottom: 1px solid #e5e7eb;
    }
    .portal-search input {
      width: 100%;
      padding: 7px 12px;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      font-size: 13px;
      outline: none;
    }
    .portal-search input:focus { border-color: #0f4a8a; }

    /* ── Tab2: Tree (既存スタイル流用) ── */
    .toolbar {
      padding: 10px 18px;
      background: #f9fafb;
      border-bottom: 1px solid #e5e7eb;
      display: flex;
      gap: 8px;
      align-items: center;
      flex-shrink: 0;
      flex-wrap: wrap;
    }
    .toolbar input {
      flex: 1;
      min-width: 200px;
      padding: 7px 12px;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      font-size: 13px;
      outline: none;
    }
    .toolbar input:focus { border-color: #0f4a8a; }
    .btn {
      padding: 6px 14px;
      border: 1px solid #d1d5db;
      border-radius: 7px;
      background: #fff;
      font-size: 12px;
      cursor: pointer;
      color: #374151;
      white-space: nowrap;
    }
    .btn:hover { background: #e0edff; border-color: #0f4a8a; color: #0f4a8a; }
    .btn-danger { border-color: #fca5a5; color: #b91c1c; }
    .btn-danger:hover { background: #fee2e2; border-color: #b91c1c; }
    .tree-wrap {
      flex: 1;
      overflow-y: auto;
      padding: 14px 18px;
      background: #fff;
    }
    details.folder-node { margin-top: 3px; }
    summary.folder-summary {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 5px 8px;
      border-radius: 6px;
      cursor: pointer;
      list-style: none;
      user-select: none;
    }
    summary.folder-summary::-webkit-details-marker { display: none; }
    .chevron {
      font-size: 10px;
      color: #9ca3af;
      transition: transform 0.15s;
      flex-shrink: 0;
      display: inline-block;
    }
    details[open] > summary.folder-summary .chevron {
      transform: rotate(90deg);
    }
    summary.folder-summary:hover { background: #f0f6ff; }
    .folder-icon { font-size: 14px; flex-shrink: 0; }
    a.folder-link {
      color: #0f4a8a;
      text-decoration: none;
      font-size: 13px;
      font-weight: 500;
      flex: 1;
    }
    a.folder-link:hover { text-decoration: underline; }
    .badge-unexplored {
      font-size: 11px; background: #f3f4f6; color: #6b7280;
      padding: 2px 8px; border-radius: 99px; white-space: nowrap;
    }
    .badge-explored {
      font-size: 11px; background: #d1fae5; color: #065f46;
      padding: 2px 8px; border-radius: 99px; white-space: nowrap;
    }
    .badge-truncated {
      font-size: 11px; background: #fef3c7; color: #92400e;
      padding: 2px 8px; border-radius: 99px; white-space: nowrap;
    }
    .folder-body { padding-left: 24px; }
    .btn-explore {
      margin: 4px 0 4px 4px;
      padding: 4px 12px;
      background: #e0edff;
      color: #0f4a8a;
      border: 1px solid #bfdbfe;
      border-radius: 6px;
      font-size: 12px;
      cursor: pointer;
    }
    .btn-explore:hover { background: #bfdbfe; }
    .btn-explore:disabled { opacity: 0.5; cursor: wait; }
    .truncated-msg { font-size: 12px; color: #92400e; padding: 4px 0 4px 4px; }
    .truncated-msg a { color: #0f4a8a; }
    .file-item { padding: 2px 4px; font-size: 12px; border-radius: 4px; }
    .file-item:hover { background: #f9fafb; }
    .file-item a { color: #374151; text-decoration: none; }
    .file-item a:hover { color: #0f4a8a; text-decoration: underline; }
    .root-explore-area { text-align: center; padding: 40px; }
    .root-explore-area button {
      padding: 12px 28px; background: #0f4a8a; color: #fff;
      border: none; border-radius: 10px; font-size: 15px; cursor: pointer;
    }
    .root-explore-area button:hover { background: #0a3a6e; }
    .root-explore-area button:disabled { background: #9ca3af; cursor: wait; }
    mark { background: #fef08a; color: inherit; border-radius: 2px; padding: 0 2px; }
    .flat-list { width: 100%; border-collapse: collapse; font-size: 13px; }
    .flat-list th {
      position: sticky; top: 0; background: #f9fafb;
      border-bottom: 1px solid #e5e7eb; padding: 8px 12px;
      text-align: left; font-weight: 500; color: #6b7280; font-size: 12px;
    }
    .flat-list td { padding: 7px 12px; border-bottom: 1px solid #f3f4f6; vertical-align: middle; }
    .flat-list tr:hover td { background: #f0f6ff; }
    .flat-list .col-name a { color: #0f4a8a; text-decoration: none; font-weight: 500; }
    .flat-list .col-name a:hover { text-decoration: underline; }
    .flat-list .col-path { font-size: 11px; color: #9ca3af; }
    .flat-list .col-meta { font-size: 11px; color: #6b7280; white-space: nowrap; }
    .flat-list .col-open { text-align: right; }
    .flat-list .btn-open {
      padding: 3px 10px; background: #0f4a8a; color: #fff;
      border: none; border-radius: 5px; font-size: 11px;
      cursor: pointer; text-decoration: none;
    }
    .flat-list .btn-open:hover { background: #0a3a6e; }
    .flat-summary {
      padding: 8px 12px; font-size: 12px; color: #6b7280;
      border-bottom: 1px solid #e5e7eb; background: #f9fafb;
    }
    .btn-copy {
      display: inline-block; padding: 2px 7px; background: #f3f4f6;
      border: 1px solid #d1d5db; border-radius: 5px; font-size: 11px;
      cursor: pointer; color: #374151; margin-left: 6px;
      vertical-align: middle; transition: background 0.15s;
    }
    .btn-copy:hover { background: #e0edff; border-color: #0f4a8a; }
    .freshness-green {
      background: #d1fae5; color: #065f46;
      padding: 2px 8px; border-radius: 99px; font-size: 11px; white-space: nowrap;
    }
    .freshness-yellow {
      background: #fef3c7; color: #92400e;
      padding: 2px 8px; border-radius: 99px; font-size: 11px; white-space: nowrap;
    }
    .freshness-red {
      background: #fee2e2; color: #b91c1c;
      padding: 2px 8px; border-radius: 99px; font-size: 11px; white-space: nowrap;
    }
    .fav-area {
      background: #fffbeb; border-bottom: 1px solid #fde68a;
    }
    .fav-area-title {
      font-size: 11px; font-weight: 600; color: #92400e; cursor: pointer;
      padding: 8px 14px;
    }
    .fav-row {
      display: flex; align-items: center; gap: 6px;
      padding: 3px 14px; font-size: 13px;
    }
    .fav-row a { color: #0f4a8a; text-decoration: none; flex: 1; }
    .fav-row a:hover { text-decoration: underline; }
    .btn-fav {
      background: none; border: none; cursor: pointer;
      font-size: 14px; padding: 0 3px; line-height: 1; color: #f59e0b;
    }
    .btn-fav:hover { transform: scale(1.2); }

    /* ── Tab3: SiteTree ── */
    .sitetree-body {
      flex: 1;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    .sitetree-sidebar {
      width: 100%;
      flex-shrink: 0;
    }
    .sitetree-main {
      flex: 1;
      overflow-y: auto;
      padding: 14px 18px;
      background: #fff;
    }
    .sitetree-search {
      padding: 10px 18px;
      background: #f9fafb;
      border-bottom: 1px solid #e5e7eb;
    }
    .sitetree-search input {
      width: 100%;
      padding: 7px 12px;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      font-size: 13px;
      outline: none;
    }
    .sitetree-search input:focus { border-color: #0f4a8a; }
    .sitetree-accordion {
      max-height: 20vh;
      overflow-y: auto;
    }
    .st-section {
      border-bottom: 1px solid #e5e7eb;
    }
    .st-section summary {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 10px 18px;
      cursor: pointer;
      list-style: none;
      user-select: none;
      background: #f9fafb;
    }
    .st-section summary::-webkit-details-marker { display: none; }
    .st-section summary::before {
      content: '▶';
      font-size: 10px;
      color: #6b7280;
      transition: transform 0.15s;
    }
    .st-section[open] summary::before { transform: rotate(90deg); }
    .st-section-label {
      font-size: 13px;
      font-weight: 600;
      color: #374151;
      flex: 1;
    }
    .st-site-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 18px 7px 32px;
      border-bottom: 1px solid #f9fafb;
      font-size: 12px;
      cursor: pointer;
    }
    .st-site-item:hover { background: #f0f6ff; }
    .st-site-item.selected { background: #e0edff; font-weight: 600; }
    .st-site-name { flex: 1; color: #0f4a8a; }
    .st-site-badge {
      font-size: 10px;
      padding: 1px 6px;
      border-radius: 99px;
      background: #f3f4f6;
      color: #6b7280;
    }
    .st-selected-bar {
      padding: 8px 18px;
      background: #e0edff;
      border-bottom: 1px solid #bfdbfe;
      font-size: 12px;
      color: #0f4a8a;
      display: none;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .st-selected-bar.visible { display: flex; }
    .footer {
      padding: 8px 18px;
      background: #f9fafb;
      border-top: 1px solid #e5e7eb;
      font-size: 11px;
      color: #9ca3af;
      flex-shrink: 0;
      display: flex;
      justify-content: space-between;
    }
    #progressArea {
      width: 100%;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    /* ── Tab3: 一括操作バー ── */
    .st-bulk-bar {
      padding: 6px 12px;
      background: #1e3a5f;
      border-bottom: 2px solid #0f2a4f;
      flex-shrink: 0;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 4px;
    }
    .st-bulk-bar label {
      font-size: 11px;
      color: rgba(255,255,255,0.75);
      white-space: nowrap;
    }
    .st-bulk-bar input {
      padding: 3px 6px;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      font-size: 11px;
      background: #fff;
      outline: none;
      min-width: 80px;
      max-width: 120px;
    }
    .st-bulk-bar input:focus { border-color: #60a5fa; }
    .st-bulk-bar select {
      padding: 3px 5px;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      font-size: 11px;
      background: #fff;
      cursor: pointer;
      outline: none;
    }
    .st-mode-btn {
      padding: 5px 12px;
      background: rgba(255,255,255,0.1);
      border: 1px solid rgba(255,255,255,0.3);
      border-radius: 7px;
      font-size: 12px;
      color: rgba(255,255,255,0.7);
      cursor: pointer;
      white-space: nowrap;
    }
    .st-mode-btn.active {
      background: #fff;
      color: #1e3a5f;
      font-weight: 600;
      border-color: #fff;
    }
    .st-mode-btn:hover { background: rgba(255,255,255,0.2); color: #fff; }
    .st-mode-btn.active:hover { background: #f0f6ff; color: #1e3a5f; }
    .btn-bulk-explore {
      padding: 6px 16px;
      background: #60a5fa;
      color: #1e3a5f;
      border: none;
      border-radius: 7px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }
    .btn-bulk-explore:hover { background: #93c5fd; }
    .btn-bulk-explore:disabled { background: #9ca3af; color: #fff; cursor: wait; }
    .st-bulk-sep {
      width: 1px; height: 20px;
      background: rgba(255,255,255,0.2);
      flex-shrink: 0;
    }


    /* ── Tab3: ダウンロードパネル（CR-25/CR-30）── */
    #stDownloadPanel {
      display: none;
      max-height: 200px;
      overflow-y: auto;
      background: #fffbeb;
      border-bottom: 1px solid #fde68a;
      flex-shrink: 0;
    }
    .dl-panel-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 18px 4px;
      font-size: 12px;
      font-weight: 600;
      color: #92400e;
    }
    .dl-panel-item {
      padding: 2px 18px;
      font-size: 12px;
    }
    .dl-panel-item a {
      color: #0f4a8a;
      text-decoration: none;
    }
    .dl-panel-item a:hover { text-decoration: underline; }
    .dl-panel-site {
      font-size: 11px;
      color: #9ca3af;
      margin-left: 6px;
    }
    
  </style>
</head>
<body>

<div class="portal-header">
  <h1>&#x1F3E2; R19 SharePoint Portal</h1>
  <div class="meta" id="portalMeta">Nexperia ICS R19</div>
</div>

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('portal')">
    &#x1F3E2; R19 Portal
  </button>
  <button class="tab-btn" onclick="switchTab('tree')">
    &#x1F5C2; ICS R19 R&amp;D
  </button>
  <button class="tab-btn" onclick="switchTab('sitetree')">
    &#x1F50D; サイト別ツリー
  </button>
</div>

<!-- ══════════════════════════════════════════ -->
<!-- Tab1: R19 Portal                          -->
<!-- ══════════════════════════════════════════ -->
<div id="tab-portal" class="tab-content active">
  <div class="portal-body">


    <!-- R19 TYPE22 NPI セクション -->
    <details class="portal-section" open
             style="background:#0f4a8a;">
      <summary style="background:#0f4a8a;">
        <span class="section-label">&#x1F535; R19 TYPE22 NPI</span>
        <span class="section-badge"
              style="background:#e0edff;color:#0f4a8a;"
              id="badge-p0">-</span>
      </summary>
      <div class="section-body">
        <div class="portal-search">
          <input type="text" id="searchP0"
                 placeholder="&#x1F50D; サイト名で絞り込み..."
                 oninput="filterPortalSites('p0')">
        </div>
        <div id="portal-p0-list">
          <div style="padding:20px;text-align:center;color:#9ca3af;">
            読み込み中...
          </div>
        </div>
      </div>
    </details>

    <!-- R19 TYPE12 Study セクション -->
    <details class="portal-section" open
             style="background:#1a6b3a;">
      <summary style="background:#1a6b3a;">
        <span class="section-label">&#x1F7E2; R19 TYPE12 Study</span>
        <span class="section-badge"
              style="background:#d1fae5;color:#1a6b3a;"
              id="badge-ps0">-</span>
      </summary>
      <div class="section-body">
        <div class="portal-search">
          <input type="text" id="searchPs0"
                 placeholder="&#x1F50D; サイト名で絞り込み..."
                 oninput="filterPortalSites('ps0')">
        </div>
        <div id="portal-ps0-list">
          <div style="padding:20px;text-align:center;color:#9ca3af;">
            読み込み中...
          </div>
        </div>
      </div>
    </details>

  </div>
</div>

<!-- ══════════════════════════════════════════ -->
<!-- Tab2: ICS R19 R&D Tree                   -->
<!-- ══════════════════════════════════════════ -->
<div id="tab-tree" class="tab-content">
  <div class="toolbar">
    <input type="text" id="searchInput"
           placeholder="&#x1F50D; フォルダ名・ファイル名で絞り込み..."
           oninput="filterTree()">
    <select id="extFilter" onchange="filterTree()"
            style="padding:7px 10px;border:1px solid #d1d5db;
                   border-radius:8px;font-size:13px;
                   background:#fff;cursor:pointer;outline:none;">
      <option value="">すべて</option>
    </select>
    <button class="btn" onclick="expandAll()">全展開</button>
    <button class="btn" onclick="collapseAll()">全折畳</button>
    <button class="btn btn-danger" onclick="resetCache()">&#x1F5D1; キャッシュリセット</button>
    <button id="btnViewToggle" class="btn"
            onclick="toggleViewMode()"
            style="background:#e0edff;border-color:#0f4a8a;color:#0f4a8a;">
      &#x2630; リスト表示
    </button>
    <div id="listControls"
         style="display:none;width:100%;
                justify-content:flex-end;gap:8px;
                padding-top:6px;border-top:1px solid #e5e7eb;
                margin-top:4px;">
      <select id="sortSelect" onchange="renderAll()"
              style="padding:7px 10px;border:1px solid #d1d5db;
                     border-radius:8px;font-size:13px;background:#fff;
                     cursor:pointer;outline:none;">
        <option value="date">&#x1F550; 新しい順</option>
        <option value="name">&#x1F524; 名前順</option>
      </select>
      <select id="targetSelect" onchange="renderAll()"
              style="padding:7px 10px;border:1px solid #d1d5db;
                     border-radius:8px;font-size:13px;background:#fff;
                     cursor:pointer;outline:none;">
        <option value="both">&#x1F4C1;&#x1F4C4; フォルダ+ファイル</option>
        <option value="file">&#x1F4C4; ファイルのみ</option>
      </select>
    </div>
    <div id="progressArea" style="display:none;">
      <span id="progressMsg"
            style="font-size:12px;color:#374151;flex:1;"></span>
      <button id="btnResume" class="btn"
              style="display:none;background:#d1fae5;
                     border-color:#6ee7b7;color:#065f46;"
              onclick="resumeDeep()">&#x2705; 続ける</button>
      <button id="btnCancelDeep" class="btn btn-danger"
              style="display:none;"
              onclick="cancelDeep()">&#x274C; キャンセル</button>
    </div>
  </div>
  <div class="tree-wrap" id="treeWrap">
    <details id="favArea" class="fav-area">
      <summary class="fav-area-title">&#x2605; お気に入り</summary>
      <div id="favList"></div>
    </details>
    <div id="loadingMsg"
         style="text-align:center;padding:40px;color:#9ca3af;">
      読み込み中...
    </div>
    <div id="rootExploreArea"
         style="display:none;" class="root-explore-area">
      <p style="margin-bottom:16px;color:#6b7280;">
        ルートフォルダがまだ探索されていません
      </p>
      <button id="btnRootExplore">
        &#x1F50D; ルートフォルダを探索（3階層）
      </button>
    </div>
    <div id="treeContent"></div>
  </div>
  <div class="footer">
    <span>R19_site_organizer_20260515_01_01.py / v20260515_01_01</span>
    <span id="cacheInfo"></span>
  </div>
</div>

<!-- ══════════════════════════════════════════ -->
<!-- Tab3: サイト別ツリー                       -->
<!-- ══════════════════════════════════════════ -->
<div id="tab-sitetree" class="tab-content">
  <div class="sitetree-body">
    <!-- ══ 一括操作バー（常時表示）══ -->
    <div id="stBulkBar" class="st-bulk-bar">
      <button id="btnModeAll" class="st-mode-btn active"
              onclick="toggleMode('all')">&#x1F310; 全サイト</button>
      <button id="btnModeSingle" class="st-mode-btn"
              onclick="toggleMode('single')">&#x1F4CC; 選択中のみ</button>
      <button class="btn"
              style="font-size:11px;padding:4px 10px;color:#fff;
                     background:rgba(255,255,255,0.15);
                     border-color:rgba(255,255,255,0.3);"
              onclick="selectAllSites()">全選択</button>
      <button class="btn"
              style="font-size:11px;padding:4px 10px;color:#fff;
                     background:rgba(255,255,255,0.15);
                     border-color:rgba(255,255,255,0.3);"
              onclick="deselectAllSites()">全解除</button>
      <div class="st-bulk-sep"></div>
      
      <label for="stDepthSelect">深さ:</label>
      <select id="stDepthSelect" onchange="onDepthChange()">
        <option value="1">1 階層</option>
        <option value="2">2 階層</option>
        <option value="3" disabled>3 階層</option>
        <option value="6" disabled>全階層</option>
      </select>
      

      <div class="st-bulk-sep"></div>
      <label for="stSiteFilterInput">&#x1F50D; サイト名:</label>
      <input type="text" id="stSiteFilterInput"
             placeholder="サイト名絞り込み..."
             oninput="onBulkSiteFilter(this.value)">
      <div class="st-bulk-sep"></div>
      <label for="stContentFilterInput">&#x1F4C1; フォルダ/ファイル:</label>
      <input type="text" id="stContentFilterInput"
             placeholder="キーワード..."
             oninput="onBulkContentFilter(this.value)">
      <select id="stFilterTargetSelect"
              onchange="_stFilterTarget=this.value;scheduleApplyContentFilter()">
        <option value="both">&#x1F4C1;&#x1F4C4; 両方</option>
        <option value="folder">&#x1F4C1; フォルダのみ</option>
      </select>
      <div class="st-bulk-sep"></div>
      <button id="btnBulkExplore" class="btn-bulk-explore"
              onclick="startBulkExplore()">&#x25B6; 一括探索</button>
    </div>
    

    <div class="sitetree-sidebar">
      <div class="sitetree-search">
        <input type="text" id="stSearch"
               placeholder="&#x1F50D; サイト名で絞り込み..."
               oninput="filterStSites()">
      </div>
      <div class="sitetree-accordion" id="stAccordion">
        <div style="padding:20px;text-align:center;color:#9ca3af;">
          読み込み中...
        </div>
      </div>
    </div>

    <div class="st-selected-bar" id="stSelectedBar">
      <span id="stSelectedName">サイトを選択してください</span>
      <button id="btnStDeepExplore"
              class="btn"
              style="font-size:11px;padding:3px 10px;
                     background:#0f4a8a;color:#fff;
                     border-color:#0f4a8a;"
              onclick="startBulkExplore()">
        &#x25B6; 選択サイトを探索
      </button>
      <button id="btnBulkDownload"
              class="btn"
              style="font-size:11px;padding:3px 10px;
                     background:#9ca3af;color:#fff;
                     border-color:#9ca3af;cursor:not-allowed;"
              onclick="bulkDownloadCheckedFiles()"
              disabled>
        &#x2B07; ダウンロード（0件）
      </button>
      <button class="btn btn-danger"
              style="font-size:11px;padding:3px 10px;"
              onclick="resetSiteCache()">
        &#x1F5D1; キャッシュリセット
      </button>
    </div>


    <div id="stProgressArea"
         style="display:none;padding:8px 18px;
                background:#f0f6ff;
                border-bottom:1px solid #bfdbfe;
                align-items:center;gap:8px;">
      <span id="stProgressMsg"
            style="font-size:12px;color:#374151;flex:1;"></span>

      <button id="btnStResume"
              class="btn"
              style="display:none;font-size:11px;padding:3px 10px;
                     background:#d1fae5;border-color:#6ee7b7;color:#065f46;"
              onclick="stPauseResume()">&#x2705; 継続</button>
      <button id="btnStPauseStop"
              class="btn btn-danger"
              style="display:none;font-size:11px;padding:3px 10px;"
              onclick="stPauseStop()">&#x26D4; 全体停止</button>

      <button id="btnStCancel"
              class="btn btn-danger"
              style="font-size:11px;padding:3px 10px;"
              onclick="stCancelDeep()">
        &#x274C; キャンセル
      </button>
    </div>
    <!-- CR-25/CR-30: ダウンロードパネル（stTreeContent外・renderStTree上書き防止）-->
    <div id="stDownloadPanel"></div>
    <div class="sitetree-main" id="stTreeContent"></div>
  </div>
  <div class="footer">
    <span>サイト別ツリー / Stage 1</span>
    <span id="stCacheInfo"></span>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════
// タブ切り替え
// ═══════════════════════════════════════════════
let _activeTab = 'portal';

function switchTab(tabName) {
  _activeTab = tabName;
  document.querySelectorAll('.tab-content').forEach(el => {
    el.classList.remove('active');
  });
  document.querySelectorAll('.tab-btn').forEach(el => {
    el.classList.remove('active');
  });
  document.getElementById('tab-' + tabName).classList.add('active');
  document.querySelectorAll('.tab-btn').forEach((el, i) => {
    const tabs = ['portal', 'tree', 'sitetree'];
    if (tabs[i] === tabName) el.classList.add('active');
  });
}

// ═══════════════════════════════════════════════
// Tab1: Portal
// ═══════════════════════════════════════════════
let _portalSites = { p0: [], ps0: [] };

async function loadPortalData() {
  // サイト一覧 読み込み
  try {
    const resp  = await fetch('/api/portal/sites');
    const data  = await resp.json();
    _portalSites = data;
    renderPortalSites('p0');
    renderPortalSites('ps0');
  } catch(e) {
    console.error('サイト読み込みエラー:', e);
  }
}

function renderPortalSites(group) {
  const sites  = _portalSites[group] || [];
  const listEl = document.getElementById('portal-' + group + '-list');
  const badge  = document.getElementById('badge-' + group);
  const q      = (document.getElementById('search' + (group === 'p0' ? 'P0' : 'Ps0')) || {}).value || '';
  const filtered = q
    ? sites.filter(s => s.name.toLowerCase().includes(q.toLowerCase()))
    : sites;

  badge.textContent = sites.length + '件';

  if (filtered.length === 0) {
    listEl.innerHTML = '<div style="padding:16px;color:#9ca3af;text-align:center;">該当なし</div>';
    return;
  }

  listEl.innerHTML = filtered.map(s => {
    const url  = escAttr(s.web_url || '');
    const name = escHtml(s.name    || s.site_name);
    return '<div class="portal-item">' +
           '&#x1F4C1; ' +
           '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' +
           name + '</a>' +
           (url
             ? '<button class="btn-copy" data-url="' + url + '" ' +
               'onclick="copyLink(this.dataset.url,this)">&#x1F4CB;</button>'
             : '') +
           '<button class="btn-sm" ' +
           'onclick="openSiteTree(' +
           JSON.stringify(s.site_name) + ',' +
           JSON.stringify(s.name) + ')">&#x1F5C2; ツリー</button>' +
           '</div>';
  }).join('');
}

function filterPortalSites(group) {
  renderPortalSites(group);
}

function openSiteTree(siteName, displayName) {
  switchTab('sitetree');
  selectStSite(siteName, displayName);
}

// ═══════════════════════════════════════════════
// Tab3: サイト別ツリー
// ═══════════════════════════════════════════════
let _stCurrentSite  = null;
let _stCurrentName  = '';
let _stTreeData     = null;
let _stAllSites     = [];

async function loadSiteList() {
  try {
    const resp = await fetch('/api/portal/sites');
    const data = await resp.json();
    _stAllSites = [
      ...( data.p0  || []).map(s => ({...s, group: 'p0'})),
      ...( data.ps0 || []).map(s => ({...s, group: 'ps0'})),
    ];
    renderStAccordion(_stAllSites);
  } catch(e) {
    document.getElementById('stAccordion').innerHTML =
      '<div style="padding:16px;color:#b91c1c;">読み込みエラー</div>';
  }
}

function renderStAccordion(sites) {
  const p0Sites  = sites.filter(s => s.group === 'p0');
  const ps0Sites = sites.filter(s => s.group === 'ps0');

  function makeItems(list) {
    return list.map(s => {
      const isSel = _stCurrentSite === s.site_name;
      const name  = escHtml(s.name || s.site_name);
      return '<div class="st-site-item' + (isSel ? ' selected' : '') + '" ' +
             'data-site="' + escAttr(s.site_name) + '" ' +
             'data-name="' + escAttr(s.name) + '" ' +
             'onclick="selectStSite(this.dataset.site, this.dataset.name, true)">' +
             '<span class="st-site-name">' + name + '</span>' +
             '</div>';
    }).join('');
  }

  document.getElementById('stAccordion').innerHTML =
    '<details class="st-section" open>' +
    '<summary><span class="st-section-label">&#x1F535; R19 TYPE22 NPI (' + p0Sites.length + '件)</span></summary>' +
    makeItems(p0Sites) +
    '</details>' +
    '<details class="st-section" open>' +
    '<summary><span class="st-section-label">&#x1F7E2; R19 TYPE12 Study (' + ps0Sites.length + '件)</span></summary>' +
    makeItems(ps0Sites) +
    '</details>';
}


function filterStSites() {
  const q = document.getElementById('stSearch').value.toLowerCase();
  const filtered = q
    ? _stAllSites.filter(s => s.name.toLowerCase().includes(q))
    : _stAllSites;
  renderStAccordion(filtered);
}

async function selectStSite(siteName, displayName, autoToggle = false) {
  _stCurrentSite = siteName;
  _stCurrentName = displayName;

  // [CR-27] サイト切替時: 前サイトのダウンロードリストとチェックをクリア
  document.getElementById('stDownloadPanel').innerHTML = '';
  document.getElementById('stDownloadPanel').style.display = 'none';
  _stCheckedFiles.clear();
  updateBulkDownloadBtn();

  // [CR-1] サイドバー直接クリック時のみモードを切替
  if (autoToggle) {
    toggleMode('single');
  }

  const bar = document.getElementById('stSelectedBar');
  bar.classList.add('visible');
  document.getElementById('stSelectedName').innerHTML =
    '&#x1F4C1; ' + escHtml(displayName);
  document.getElementById('stCacheInfo').textContent = '';

  renderStAccordion(
    document.getElementById('stSearch').value
      ? _stAllSites.filter(s =>
          s.name.toLowerCase().includes(
            document.getElementById('stSearch').value.toLowerCase()
          ))
      : _stAllSites
  );

  document.getElementById('stTreeContent').innerHTML =
    '<div style="text-align:center;padding:40px;color:#9ca3af;">&#x23F3; 読み込み中...</div>';

  try {
    const resp  = await fetch('/api/portal/site_tree/' + encodeURIComponent(siteName));
    _stTreeData = await resp.json();
    _stAllCaches[siteName] = _stTreeData;
    renderStTree();
  } catch(e) {
    document.getElementById('stTreeContent').innerHTML =
      '<div style="padding:20px;color:#b91c1c;">エラー: ' + e.message + '</div>';
  }
}


function renderStTree() {
  if (!_stTreeData) return;

  // [v2.05] 再描画前: 現在 open 状態のフォルダパスを全て収集する
  const openPaths = new Set();
  document.querySelectorAll('#stTreeContent details[data-path][open]')
    .forEach(function(el) { openPaths.add(el.dataset.path); });

  const explored  = _stTreeData.explored  || {};
  const updatedAt = _stTreeData.updated_at || '';
  const pathCount = Object.keys(explored).length;

  document.getElementById('stCacheInfo').textContent =
    (updatedAt ? '最終更新: ' + updatedAt : '未探索') +
    ' | 探索済み: ' + pathCount + 'パス';

  const root = explored['/'];
  if (!root) {
    document.getElementById('stTreeContent').innerHTML =
      '<div style="text-align:center;padding:40px;">' +
      '<p style="color:#6b7280;margin-bottom:16px;">ルートフォルダがまだ探索されていません</p>' +
      '<button class="btn" style="background:#0f4a8a;color:#fff;" ' +
      'onclick="stExploreFolder(\'/\')">&#x1F50D; ルートフォルダを探索</button>' +
      '</div>';
    return;
  }

  document.getElementById('stTreeContent').innerHTML =
    stRenderLevel('/', explored);

  // [v2.05fix] CSS.escapeは属性値セレクターを壊すため廃止
  // dataset.path との直接比較方式に変更
  document.querySelectorAll('#stTreeContent details[data-path]')
    .forEach(function(el) {
      if (openPaths.has(el.dataset.path)) el.open = true;
    });

  stAttachButtons();
}




function stRenderLevel(path, explored) {
  const data = explored[path];
  if (!data) return '';
  let html = '';
  for (const file of (data.files || [])) {
    html += stRenderFile(file);
  }
  for (const folder of (data.folders || [])) {
    const folderPath = path === '/' ? '/' + folder.name : path + '/' + folder.name;
    html += stRenderFolder(folder, folderPath, explored);
  }
  return html;
}

function stRenderFile(file) {
  const ext  = file.name.split('.').pop().toLowerCase();
  const icon = fileIcon(ext);
  const kb   = file.size > 0 ? Math.round(file.size / 1024).toLocaleString() + ' KB' : '-';
  const dt   = file.last_modified ? file.last_modified.substring(0, 10) : '-';
  const meta = '<span style="color:#9ca3af;font-size:11px;margin-left:8px;">' + kb + ' / ' + dt + '</span>';
  const url  = escAttr(file.web_url || file.local_url || '');
  const copy = url
    ? '<button class="btn-copy" data-url="' + url + '" ' +
      'onclick="copyLink(this.dataset.url,this)">&#x1F4CB;</button>'
    : '';
  // [CR-23/CR-28] item_id があるファイルのみチェックボックスを表示
  const itemId = file.item_id || '';
  const chk = itemId
    ? '<input type="checkbox" ' +
      (_stCheckedFiles.has(itemId) ? 'checked ' : '') +
      'style="vertical-align:middle;cursor:pointer;margin-right:4px;" ' +
      'data-item-id="' + escAttr(itemId) + '" ' +
      'data-site="' + escAttr(_stCurrentSite || '') + '" ' +
      'data-filename="' + escAttr(file.name) + '" ' +
      'onchange="onFileCheck(this.dataset.itemId,' +
      'this.dataset.site,this.dataset.filename,this)">'
    : '';
  // [Feature v2.1] ダウンロードボタン生成（data-*属性方式でXSS・引用符問題を回避）
  // item_id と drive_id が両方存在する場合のみ表示（古いキャッシュは非表示）
  const dlDriveId = (_stAllCaches[_stCurrentSite] &&
                     _stAllCaches[_stCurrentSite].drive_id)
                    ? _stAllCaches[_stCurrentSite].drive_id : '';
  const dlBtn = (itemId && dlDriveId)
    ? '<button class="btn-copy" ' +
      'title="ダウンロード先を選択して保存" ' +
      'data-site="'     + escAttr(_stCurrentSite || '') + '" ' +
      'data-item-id="'  + escAttr(itemId)               + '" ' +
      'data-drive-id="' + escAttr(dlDriveId)             + '" ' +
      'data-filename="' + escAttr(file.name)              + '" ' +
      'onclick="singleDownloadWithPicker(' +
      'this.dataset.site,this.dataset.itemId,' +
      'this.dataset.driveId,this.dataset.filename)">&#x2B07;</button>'
    : '';
  return '<div class="file-item">' + chk + '<a href="' + url +
         '" target="_blank" rel="noopener noreferrer">' +
         icon + ' ' + escHtml(file.name) + '</a>' + meta + copy + dlBtn + '</div>';
}


function stRenderFolder(folder, folderPath, explored) {
  const data = explored[folderPath];
  const name = escHtml(folder.name);
  const url  = escAttr(folder.web_url);
  let badge  = '';
  let body   = '';

  if (!data) {
    badge = '<span class="badge-unexplored">&#x1F50D; 未探索</span>';
    body  = '<button class="btn-explore" ' +
            'data-path="' + escAttr(folderPath) + '">' +
            '&#x1F50D; このフォルダを探索</button>';
  } else if (data.truncated) {
    badge = '<span class="badge-truncated">&#x26A0;&#xFE0F; 過密 &#x1F4C1;' +
            data.desc_folders + ' &#x1F4C4;' + data.desc_files + '</span>';
    body  = '<p class="truncated-msg">&#x26A0;&#xFE0F; 過密判定。' +
            '<a href="' + url + '" target="_blank"> SharePointで確認 &#x2192;</a></p>' +
            '<button class="btn-explore" data-path="' + escAttr(folderPath) + '">' +
            '&#x1F50D; このフォルダを探索</button>';
  } else {
    const fs    = freshnessStyle(data.explored_at || '');
    const dtStr = (data.explored_at || '').substring(0, 16);
    badge = '<span class="' + fs.cls + '">' + fs.icon + ' ' + dtStr + '</span>';
    body  = stRenderLevel(folderPath, explored);
  }

  const copy = url
    ? '<button class="btn-copy" data-url="' + url + '" ' +
      'onclick="event.stopPropagation();copyLink(this.dataset.url,this)">&#x1F4CB;</button>'
    : '';

  // [v2.05] data-path を追加 → renderStTree の open 状態復元に使用
  return '<details class="folder-node" data-path="' + escAttr(folderPath) + '">' +
    '<summary class="folder-summary">' +
    '<span class="chevron">&#x25B6;</span>' +
    '<span class="folder-icon">&#x1F4C1;</span>' +
    '<a class="folder-link" href="' + url + '" target="_blank" ' +
    'onclick="event.stopPropagation()">' + name + '</a>' +
    badge + copy +
    '</summary>' +
    '<div class="folder-body">' + body + '</div>' +
    '</details>';
}


function stAttachButtons() {
  document.querySelectorAll('#stTreeContent .btn-explore').forEach(btn => {
    btn.addEventListener('click', function() {
      stExploreFolder(this.dataset.path, this);
    });
  });
}

async function stExploreFolder(path, btn) {
  if (!_stCurrentSite) return;
  if (btn) { btn.disabled = true; btn.innerHTML = '&#x23F3; 探索中...'; }

  try {
    const resp = await fetch(
      '/api/portal/expand/' + encodeURIComponent(_stCurrentSite),
      {
        method:  'POST',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({path: path}),
      }
    );
    const data = await resp.json();
    if (data.ok === true) {
      _stTreeData = data.tree;
      renderStTree();
    } else {
      alert('エラー: ' + data.message);
      if (btn) { btn.disabled = false; btn.innerHTML = '&#x1F50D; このフォルダを探索'; }
    }
  } catch(e) {
    alert('通信エラー: ' + e.message);
    if (btn) { btn.disabled = false; btn.innerHTML = '&#x1F50D; このフォルダを探索'; }
  }
}

async function resetSiteCache() {
  if (!_stCurrentSite) return;
  if (!confirm(_stCurrentName + ' のキャッシュをリセットしますか？')) return;
  await fetch(
    '/api/portal/reset/' + encodeURIComponent(_stCurrentSite),
    {method: 'POST'}
  );
  await selectStSite(_stCurrentSite, _stCurrentName);
}

// [CR-23/Bug-1] ダウンロード選択ファイル管理 Map
// key: item_id (string), value: {site_name, drive_id, item_id, filename}
let _stCheckedFiles = new Map();
let _stSseSource = null;
let _stDeepDone  = false;
let _stMode          = 'all';
let _stDepth         = 1;
let _stRunning       = false;
let _stPauseResolver = null;
let _stSiteFilter    = '';
let _stContentFilter = '';
let _stFilterTarget  = 'both';
let _stAllCaches     = {};
let _stFilterTimer   = null;
let _stFilteredRows           = [];
let _stFilteredExploreSource  = null;
let _stFilteredExploreSiteName = '';
const SSE_INTER_WAIT_MS        = 300;



function stStartDeepExplore(depth = null) {
  if (!_stCurrentSite) {
    alert('サイトを選択してください。');
    return;
  }

  // [CR-2] depth=null の場合は _stDepth グローバルを使用
  const resolvedDepth = (depth !== null) ? depth : _stDepth;

  const progressArea = document.getElementById('stProgressArea');
  const progressMsg  = document.getElementById('stProgressMsg');
  const btnDeep      = document.getElementById('btnStDeepExplore');
  const btnCancel    = document.getElementById('btnStCancel');

  btnDeep.disabled           = true;
  progressArea.style.display = 'flex';
  progressMsg.innerHTML      = '&#x23F3; 探索開始...';
  btnCancel.disabled         = false;
  btnCancel.style.display    = 'inline-block';
  document.getElementById('btnStResume').style.display    = 'none';
  document.getElementById('btnStPauseStop').style.display = 'none';

  if (_stSseSource) { _stSseSource.close(); _stSseSource = null; }
  _stDeepDone = false;
  _stRunning  = true;
  lockSidebar(true);

  const _stUrl = '/api/portal/expand_deep/' +
                 encodeURIComponent(_stCurrentSite) +
                 '?depth=' + resolvedDepth;
  _stSseSource = new EventSource(_stUrl);

  _stSseSource.onmessage = function(e) {
    const data = JSON.parse(e.data);

    if (data.type === 'exploring') {
      progressMsg.innerHTML =
        '&#x1F50D; 探索中... ( ' + data.path + ' )';

    } else if (data.type === 'progress') {
      progressMsg.innerHTML =
        '&#x23F3; ' + data.count + 'フォルダ完了 ( ' + data.path + ' )';

    } else if (data.type === 'paused') {
      // [新規] count-based pause イベント
      progressMsg.innerHTML =
        '&#x23F8; ' + data.count + 'フォルダ到達。継続しますか？';
      document.getElementById('btnStResume').style.display    = 'inline-block';
      document.getElementById('btnStPauseStop').style.display = 'inline-block';
      btnCancel.style.display = 'none';

    } else if (data.type === 'done') {
      _stDeepDone = true;
      _stRunning  = false;
      lockSidebar(false);
      progressMsg.innerHTML =
        '&#x2705; 完了: ' + data.count + 'フォルダ探索済み';
      btnDeep.disabled = false;
      if (data.tree) {
        _stTreeData = data.tree;
        _stAllCaches[_stCurrentSite] = data.tree;
        renderStTree();
      }
      _stSseSource.close(); _stSseSource = null;
      setTimeout(function() {
        progressArea.style.display = 'none';
      }, 5000);

    } else if (data.type === 'cancelled') {
      _stDeepDone = true;
      _stRunning  = false;
      lockSidebar(false);
      progressMsg.innerHTML =
        '&#x26D4; キャンセル: ' + data.count + 'フォルダ取得済み（保存済み）';
      btnDeep.disabled = false;
      if (data.tree) {
        _stTreeData = data.tree;
        _stAllCaches[_stCurrentSite] = data.tree;
        renderStTree();
      }
      _stSseSource.close(); _stSseSource = null;
      setTimeout(function() {
        progressArea.style.display = 'none';
      }, 5000);

    } else if (data.type === 'error') {
      _stDeepDone = true;
      _stRunning  = false;
      lockSidebar(false);
      progressMsg.innerHTML = '&#x274C; エラー: ' + escHtml(data.message);
      btnDeep.disabled = false;
      _stSseSource.close(); _stSseSource = null;
    }
  };

  _stSseSource.onerror = function() {
    if (_stDeepDone || !_stSseSource) return;
    document.getElementById('stProgressMsg').innerHTML =
      '&#x274C; 接続エラー';
    document.getElementById('btnStDeepExplore').disabled = false;
    _stRunning = false;
    lockSidebar(false);
    if (_stSseSource) { _stSseSource.close(); _stSseSource = null; }
  };
}

function stCancelDeep() {
  if (_stMode === 'all') {
    _stRunning = false;
    if (_stPauseResolver) { _stPauseResolver(); _stPauseResolver = null; }
    // [CR-10] depth=2+のSSEループ中: EventSourceを強制終了してcancelを送信
    if (_stFilteredExploreSource) {
      _stFilteredExploreSource.close();
      _stFilteredExploreSource = null;
      if (_stFilteredExploreSiteName) {
        fetch('/api/portal/expand_deep/' +
              encodeURIComponent(_stFilteredExploreSiteName) + '/cancel',
              {method: 'POST'});
      }
    }
    document.getElementById('stProgressMsg').innerHTML = '&#x23F3; キャンセル中...';
    lockSidebar(false);
  } else {
    // [Fix] 判定キー: _stSseSource の有無で処理を分岐
    // _stSseSource=null かつ _stRunning=true
    //   → runFilteredRowsLoop() が動作中
    // _stSseSource=非null かつ _stRunning=true
    //   → stStartDeepExplore() が動作中（既存パス）
    if (_stRunning && !_stSseSource) {
      // [Fix] 絞り込みループキャンセル: _stRunning=false でループ停止
      _stRunning = false;
      // depth=2+のSSEが残っている場合は強制終了（CR-10と同一パターン）
      if (_stFilteredExploreSource) {
        _stFilteredExploreSource.close();
        _stFilteredExploreSource = null;
        if (_stFilteredExploreSiteName) {
          fetch('/api/portal/expand_deep/' +
                encodeURIComponent(_stFilteredExploreSiteName) + '/cancel',
                {method: 'POST'});
        }
      }
      document.getElementById('stProgressMsg').innerHTML = '&#x23F3; キャンセル中...';
      lockSidebar(false);
      // [CR-12] 3秒後に進捗エリアを自動非表示
      setTimeout(function() {
        document.getElementById('stProgressArea').style.display = 'none';
      }, 3000);
      return;
    }
    // 既存パス: stStartDeepExplore() のSSEキャンセル（変更なし）
    if (!_stCurrentSite || (_stDeepDone && !_stRunning)) return;
    document.getElementById('btnStCancel').disabled    = true;
    document.getElementById('stProgressMsg').innerHTML = '&#x23F3; キャンセル中...';
    fetch(
      '/api/portal/expand_deep/' +
      encodeURIComponent(_stCurrentSite) + '/cancel',
      {method: 'POST'}
    );
  }
}


// ═══════════════════════════════════════════════
// Tab3: 一括操作バー制御
// ═══════════════════════════════════════════════

/* 呼び出し元: stBulkBar の btnModeAll / btnModeSingle */
function toggleMode(mode) {
  _stMode = mode;
  const btnAll    = document.getElementById('btnModeAll');
  const btnSingle = document.getElementById('btnModeSingle');
  const depthSel  = document.getElementById('stDepthSelect');

  if (mode === 'all') {
    btnAll.classList.add('active');
    btnSingle.classList.remove('active');
    // 全サイト横断は深さ1または2のみ有効
    if (parseInt(depthSel.value, 10) > 2) {
      depthSel.value = '1';
      _stDepth = 1;
    }
    Array.from(depthSel.options).forEach(function(opt) {
      opt.disabled = (opt.value !== '1' && opt.value !== '2');
    });
  } else {
    btnSingle.classList.add('active');
    btnAll.classList.remove('active');
    // 選択中サイトは全深さ有効
    Array.from(depthSel.options).forEach(function(opt) {
      opt.disabled = false;
    });
  }
}

/* 呼び出し元: stBulkBar の「全選択」ボタン */
function selectAllSites() {
  toggleMode('all');
  _stCurrentSite = null;
  _stCurrentName = '';
  document.getElementById('stSelectedBar').classList.remove('visible');
  document.getElementById('stCacheInfo').textContent = '';
  renderStAccordion(
    document.getElementById('stSearch').value
      ? _stAllSites.filter(s =>
          s.name.toLowerCase().includes(
            document.getElementById('stSearch').value.toLowerCase()
          ))
      : _stAllSites
  );
}

/* 呼び出し元: stBulkBar の「全解除」ボタン */
function deselectAllSites() {
  _stCurrentSite = null;
  _stCurrentName = '';
  document.getElementById('stSelectedBar').classList.remove('visible');
  document.getElementById('stCacheInfo').textContent   = '';
  document.getElementById('stTreeContent').innerHTML   =
    '<div style="text-align:center;padding:40px;color:#9ca3af;">' +
    'サイトが選択されていません</div>';
  renderStAccordion(
    document.getElementById('stSearch').value
      ? _stAllSites.filter(s =>
          s.name.toLowerCase().includes(
            document.getElementById('stSearch').value.toLowerCase()
          ))
      : _stAllSites
  );
}

/* 呼び出し元: stDepthSelect の onchange */
function onDepthChange() {
  _stDepth = parseInt(document.getElementById('stDepthSelect').value, 10);
}

/* 呼び出し元: stSiteFilterInput の oninput */
function onBulkSiteFilter(val) {
  _stSiteFilter = val;
  // [CR-4] filterStSites() は stSearch DOM を読むため呼ばない。
  // val を直接使用して _stAllSites を絞り込み renderStAccordion() を呼ぶ。
  const filtered = val
    ? _stAllSites.filter(function(s) {
        return s.name.toLowerCase().includes(val.toLowerCase());
      })
    : _stAllSites;
  renderStAccordion(filtered);
  scheduleApplyContentFilter();
}

/* 呼び出し元: stContentFilterInput の oninput */
function onBulkContentFilter(val) {
  _stContentFilter = val;
  scheduleApplyContentFilter();
}

/* 呼び出し元: onBulkContentFilter / onBulkSiteFilter / stFilterTargetSelect */
function scheduleApplyContentFilter() {
  clearTimeout(_stFilterTimer);
  _stFilterTimer = setTimeout(applyContentFilter, 500);
}

/* 呼び出し元: stBulkBar の btnBulkExplore / stSelectedBar の btnStDeepExplore */
function startBulkExplore() {
  if (_stRunning) {
    alert('探索中です。完了またはキャンセルをお待ちください。');
    return;
  }
  if (_stMode === 'all') {
    runAllSitesLoop();
  } else {
    if (!_stCurrentSite) {
      alert('サイトを選択してください。');
      return;
    }
    stStartDeepExplore(null);   // null → _stDepth を使用（CR-2）
  }
}

/* 呼び出し元: startBulkExplore() （全サイト横断モード時） */
async function runAllSitesLoop() {
  // 探索対象サイトの確定（サイト名フィルター適用）
  const sf = _stSiteFilter.toLowerCase().trim();
  const targetSites = sf
    ? _stAllSites.filter(s => s.name.toLowerCase().includes(sf))
    : _stAllSites.slice();

  if (targetSites.length === 0) {
    alert('探索対象サイトがありません。フィルターを確認してください。');
    return;
  }

  _stRunning = true;
  if (_stPauseResolver) { _stPauseResolver(); _stPauseResolver = null; }

  const progressArea = document.getElementById('stProgressArea');
  const progressMsg  = document.getElementById('stProgressMsg');
  const btnCancel    = document.getElementById('btnStCancel');
  const btnBulk      = document.getElementById('btnBulkExplore');

  btnBulk.disabled                                         = true;
  progressArea.style.display                               = 'flex';
  btnCancel.disabled                                       = false;
  btnCancel.style.display                                  = 'inline-block';
  document.getElementById('btnStResume').style.display    = 'none';
  document.getElementById('btnStPauseStop').style.display = 'none';

  lockSidebar(true);

  // バックグラウンド遷移警告
  function _onVisibilityChange() {
    if (document.hidden && _stRunning) {
      progressMsg.innerHTML += ' &#x26A0;&#xFE0F; バックグラウンドでは遅延の可能性';
    }
  }
  document.addEventListener('visibilitychange', _onVisibilityChange);

  let completedCount = 0;

  for (let i = 0; i < targetSites.length; i++) {
    if (!_stRunning) break;

    const site = targetSites[i];
    progressMsg.innerHTML =
      '&#x1F50D; ' + (i + 1) + '/' + targetSites.length +
      ': ' + escHtml(site.name) + ' 探索中...';

    try {
      const resp = await fetch(
        '/api/portal/expand/' + encodeURIComponent(site.site_name),
        {
          method:  'POST',
          headers: {'Content-Type': 'application/json'},
          body:    JSON.stringify({path: '/'}),
        }
      );
      if (!resp.ok) {
        progressMsg.innerHTML =
          '&#x274C; HTTP ' + resp.status + ' (' + escHtml(site.name) + ')';
        _stRunning = false;
        break;
      }
      const data = await resp.json();
      if (data.ok !== true) {
        progressMsg.innerHTML =
          '&#x274C; エラー (' + escHtml(site.name) + '): ' +
          escHtml(data.message || '不明');
        _stRunning = false;
        break;
      }

      // キャッシュに格納
      if (data.tree) {
        _stAllCaches[site.site_name] = data.tree;
      }
      completedCount++;

      // ── depth=2: ルート直下の各フォルダを追加探索 ──
      if (_stDepth >= 2 && _stRunning) {
        const rootExplored = (data.tree && data.tree.explored)
                             ? (data.tree.explored['/'] || null) : null;
        const subFolders   = rootExplored ? (rootExplored.folders || []) : [];
        for (let fi = 0; fi < subFolders.length; fi++) {
          if (!_stRunning) break;
          const folder   = subFolders[fi];
          const subPath  = '/' + folder.name;
          progressMsg.innerHTML =
            '&#x1F4C2; ' + (i + 1) + '/' + targetSites.length +
            ': ' + escHtml(site.name) +
            ' [' + (fi + 1) + '/' + subFolders.length + '] ' +
            escHtml(folder.name) + ' 探索中...';
          try {
            const subResp = await fetch(
              '/api/portal/expand/' + encodeURIComponent(site.site_name),
              {
                method:  'POST',
                headers: {'Content-Type': 'application/json'},
                body:    JSON.stringify({path: subPath}),
              }
            );
            if (subResp.ok) {
              const subData = await subResp.json();
              if (subData.ok && subData.tree) {
                _stAllCaches[site.site_name] = subData.tree;
              }
            }
          } catch (e) { /* サブフォルダ失敗はスキップして継続 */ }
          if (_stRunning && fi < subFolders.length - 1) {
            await new Promise(function(r) { setTimeout(r, 300); });
          }
        }
      }

      // 100フォルダ一時停止チェック（Q24: YES）
      const rootData    = (data.tree && data.tree.explored)
                          ? (data.tree.explored['/'] || null) : null;
      const folderCount = rootData ? (rootData.folders || []).length : 0;

      if (folderCount >= 100) {
        progressMsg.innerHTML =
          '&#x23F8; ' + escHtml(site.name) + ': ' + folderCount +
          'フォルダ検出。継続しますか？';
        btnCancel.style.display                                  = 'none';
        document.getElementById('btnStResume').style.display    = 'inline-block';
        document.getElementById('btnStPauseStop').style.display = 'inline-block';

        await new Promise(function(resolve) { _stPauseResolver = resolve; });
        _stPauseResolver = null;

        document.getElementById('btnStResume').style.display    = 'none';
        document.getElementById('btnStPauseStop').style.display = 'none';
        btnCancel.style.display                                  = 'inline-block';

        if (!_stRunning) break;
      }

    } catch (e) {
      progressMsg.innerHTML =
        '&#x274C; 通信エラー (' + escHtml(site.name) + '): ' + escHtml(e.message);
      _stRunning = false;
      break;
    }

    // リクエスト間隔（300ms）
    if (_stRunning && i < targetSites.length - 1) {
      await new Promise(function(r) { setTimeout(r, 300); });
    }
  }

  document.removeEventListener('visibilitychange', _onVisibilityChange);
  lockSidebar(false);
  _stRunning       = false;
  btnBulk.disabled = false;

  if (progressMsg.innerHTML.indexOf('&#x274C;') === -1 &&
      progressMsg.innerHTML.indexOf('&#x26D4;') === -1) {
    progressMsg.innerHTML =
      '&#x2705; 完了: ' + completedCount + '/' +
      targetSites.length + 'サイト探索済み';
  }

  // フィルターを自動再適用（Q23ア: 探索後にフィルター更新）
  applyContentFilter();

  setTimeout(function() {
    if (!_stRunning) {
      progressArea.style.display = 'none';
    }
  }, 5000);
}

/* 呼び出し元: scheduleApplyContentFilter() / runAllSitesLoop()完了後 */
async function applyContentFilter() {
  const contentFilter = _stContentFilter.toLowerCase().trim();
  const siteFilter    = _stSiteFilter.toLowerCase().trim();
  const treeContent   = document.getElementById('stTreeContent');

  // [CR-22/CR-24] フィルターが空になった時のみチェックをリセット
  if (!contentFilter) {
    _stCheckedFiles.clear();
    renderDownloadPanel();
    updateBulkDownloadBtn();
    treeContent.innerHTML =
      '<div style="text-align:center;padding:40px;color:#9ca3af;">' +
      '&#x1F4C1; フォルダ/ファイル検索欄にキーワードを入力してください</div>';
    return;
  }

  const targetSites = siteFilter
    ? _stAllSites.filter(s => s.name.toLowerCase().includes(siteFilter))
    : _stAllSites.slice();

  const uncached = targetSites.filter(function(s) {
    return !_stAllCaches[s.site_name];
  });
  if (uncached.length > 0) {
    treeContent.innerHTML =
      '<div style="text-align:center;padding:20px;color:#9ca3af;">' +
      '&#x23F3; キャッシュ読み込み中 (' + uncached.length + '件)...</div>';
    await Promise.all(uncached.map(async function(site) {
      try {
        const resp = await fetch(
          '/api/portal/site_tree/' + encodeURIComponent(site.site_name)
        );
        const d = await resp.json();
        if (d && d.explored) {
          _stAllCaches[site.site_name] = d;
        }
      } catch(e) { /* 取得失敗はスキップ */ }
    }));
  }

  const rows = [];
  const target = _stFilterTarget;

  for (let si = 0; si < targetSites.length; si++) {
    const site      = targetSites[si];
    const cacheData = _stAllCaches[site.site_name];
    if (!cacheData || !cacheData.explored) continue;

    const explored = cacheData.explored;
    for (const path in explored) {
      if (!Object.prototype.hasOwnProperty.call(explored, path)) continue;
      const data = explored[path];

      const folders = data.folders || [];
      for (let fi = 0; fi < folders.length; fi++) {
        const folder = folders[fi];
        if (folder.name.toLowerCase().includes(contentFilter)) {
          rows.push({
            kind:         'folder',
            name:         folder.name,
            site_name:    site.site_name,
            site_display: site.name,
            path:         path,
            web_url:      folder.web_url || '',
            size:         0,
            date:         data.explored_at || '',
            item_id:      '',
          });
        }
      }

      if (target === 'both') {
        const files = data.files || [];
        for (let fi = 0; fi < files.length; fi++) {
          const file = files[fi];
          if (file.name.toLowerCase().includes(contentFilter)) {
            rows.push({
              kind:         'file',
              name:         file.name,
              site_name:    site.site_name,
              site_display: site.name,
              path:         path,
              web_url:      file.web_url || '',
              size:         file.size || 0,
              date:         file.last_modified || '',
              item_id:      file.item_id || '',
            });
          }
        }
      }
    }
  }

  _stFilteredRows = rows.slice();
  treeContent.innerHTML = renderFlatResultList(rows, contentFilter);
}

/* 呼び出し元: applyContentFilter() */
function renderFlatResultList(rows, q) {
  if (rows.length === 0) {
    return '<div style="padding:20px;text-align:center;color:#9ca3af;">&#x1F50D; 該当なし</div>';
  }

  const nFolders = rows.filter(function(r) { return r.kind === 'folder'; }).length;
  const nFiles   = rows.filter(function(r) { return r.kind === 'file';   }).length;

  let html =
    '<div class="flat-summary" style="display:flex;align-items:center;gap:12px;">' +
    '検索結果: フォルダ ' + nFolders +
    '件 / ファイル ' + nFiles + '件（合計 ' + rows.length + '件）' +
    '<button class="btn" style="font-size:11px;padding:3px 10px;' +
    'background:#0f4a8a;color:#fff;border-color:#0f4a8a;"' +
    ' onclick="runFilteredRowsLoop()">&#x1F50D; 絞り込み結果を一括探索（' +
    rows.length + '件）</button>' +
    '</div>';

  html +=
    '<table class="flat-list"><thead><tr>' +
    '<th style="width:20px;"></th>' +
    '<th style="width:24px;"></th>' +
    '<th>名前</th>' +
    '<th style="min-width:120px;">サイト名</th>' +
    '<th>パス</th>' +
    '<th>サイズ</th>' +
    '<th>更新日</th>' +
    '<th></th>' +
    '</tr></thead><tbody>';

  for (let i = 0; i < rows.length; i++) {
    const row    = rows[i];
    const ext    = (row.kind === 'file' && row.name.includes('.'))
                   ? row.name.split('.').pop().toLowerCase() : '';
    const icon   = row.kind === 'folder' ? '&#x1F4C1;' : fileIcon(ext);
    const nameHL = highlightText(row.name, q || '');
    const kb     = row.size > 0
                   ? Math.round(row.size / 1024).toLocaleString() + ' KB' : '-';
    const dt     = row.date ? row.date.substring(0, 10) : '-';
    const href   = escAttr(row.web_url || '');
    const openBtn = href
      ? '<a class="btn-open" href="' + href +
        '" target="_blank" rel="noopener noreferrer">開く</a>'
      : '';
    const copyBtn = href
      ? '<button class="btn-copy" data-url="' + href +
        '" onclick="copyLink(this.dataset.url,this)">&#x1F4CB;</button>'
      : '';
    const exploreBtn = (row.kind === 'folder')
      ? '<button class="btn" style="font-size:11px;padding:2px 7px;" ' +
        'data-site="' + escAttr(row.site_name) + '" ' +
        'data-path="' + escAttr(row.path) + '" ' +
        'data-name="' + escAttr(row.name) + '" ' +
        'onclick="exploreSingleFilteredRow(' +
        'this.dataset.site,this.dataset.path,this.dataset.name)">' +
        '&#x1F50D;</button>'
      : '';
    // [CR-23/CR-28] ファイル行かつ item_id あり の場合のみチェックボックス表示
    const chkBtn = (row.kind === 'file' && row.item_id)
      ? '<input type="checkbox" ' +
        (_stCheckedFiles.has(row.item_id) ? 'checked ' : '') +
        'style="vertical-align:middle;cursor:pointer;" ' +
        'data-item-id="' + escAttr(row.item_id) + '" ' +
        'data-site="' + escAttr(row.site_name) + '" ' +
        'data-filename="' + escAttr(row.name) + '" ' +
        'onchange="onFileCheck(this.dataset.itemId,' +
        'this.dataset.site,this.dataset.filename,this)">'
      : '';

    html +=
      '<tr>' +
      '<td>' + chkBtn + '</td>' +
      '<td>' + icon + '</td>' +
      '<td class="col-name">' +
        (href
          ? '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' +
            nameHL + '</a>'
          : nameHL) +
      '</td>' +
      '<td style="font-size:11px;color:#0f4a8a;white-space:nowrap;">' +
        escHtml(row.site_display) +
      '</td>' +
      '<td class="col-path">' + escHtml(row.path) + '</td>' +
      '<td class="col-meta">' + kb + '</td>' +
      '<td class="col-meta">' + dt + '</td>' +
      '<td class="col-open">' + openBtn + copyBtn + exploreBtn + '</td>' +
      '</tr>';
  }

  html += '</tbody></table>';
  return html;
}

/* 呼び出し元: runAllSitesLoop() / stStartDeepExplore() */
function lockSidebar(lock) {
  const accordion = document.getElementById('stAccordion');
  const bulkBar   = document.getElementById('stBulkBar');
  if (lock) {
    accordion.style.pointerEvents = 'none';
    accordion.style.opacity       = '0.5';
    Array.from(bulkBar.querySelectorAll('button, select, input')).forEach(
      function(el) {
        if (el.id !== 'btnStCancel' &&
            el.id !== 'btnStResume' &&
            el.id !== 'btnStPauseStop') {
          el.disabled = true;
        }
      }
    );
  } else {
    accordion.style.pointerEvents = '';
    accordion.style.opacity       = '';
    Array.from(bulkBar.querySelectorAll('button, select, input')).forEach(
      function(el) { el.disabled = false; }
    );
  }
}

/* 呼び出し元: stProgressArea の btnStResume */
function stPauseResume() {
  if (_stMode === 'all') {
    if (_stDepth === 1) {
      // depth=1: クライアント側Promiseを解決（runAllSitesLoop / runFilteredRowsLoop共通）
      if (_stPauseResolver) { _stPauseResolver(); _stPauseResolver = null; }
    } else {
      // depth=2+: サーバー側pause_eventをresumeエンドポイントで解除（CR-7対応）
      document.getElementById('stProgressMsg').innerHTML = '&#x23F3; 探索再開中...';
      if (_stFilteredExploreSiteName) {
        fetch('/api/portal/expand_deep/' +
              encodeURIComponent(_stFilteredExploreSiteName) + '/resume',
              {method: 'POST'});
      }
    }
  } else {
    // 単サイトSSEモード
    document.getElementById('stProgressMsg').innerHTML = '&#x23F3; 探索再開中...';
    fetch(
      '/api/portal/expand_deep/' +
      encodeURIComponent(_stCurrentSite) + '/resume',
      {method: 'POST'}
    );
  }
  document.getElementById('btnStResume').style.display    = 'none';
  document.getElementById('btnStPauseStop').style.display = 'none';
  document.getElementById('btnStCancel').style.display    = 'inline-block';
}
/* 呼び出し元: stProgressArea の btnStPauseStop */
function stPauseStop() {
  if (_stMode === 'all') {
    _stRunning = false;
    if (_stPauseResolver) { _stPauseResolver(); _stPauseResolver = null; }
    // [CR-10] depth=2+のSSE一時停止中: EventSourceを強制終了してcancelを送信
    if (_stFilteredExploreSource) {
      _stFilteredExploreSource.close();
      _stFilteredExploreSource = null;
      if (_stFilteredExploreSiteName) {
        fetch('/api/portal/expand_deep/' +
              encodeURIComponent(_stFilteredExploreSiteName) + '/cancel',
              {method: 'POST'});
      }
    }
    lockSidebar(false);
    document.getElementById('btnBulkExplore').disabled = false;
  } else {
    if (_stCurrentSite) {
      fetch(
        '/api/portal/expand_deep/' +
        encodeURIComponent(_stCurrentSite) + '/cancel',
        {method: 'POST'}
      );
    }
  }
  document.getElementById('btnStResume').style.display    = 'none';
  document.getElementById('btnStPauseStop').style.display = 'none';
  document.getElementById('btnStCancel').style.display    = 'inline-block';
  document.getElementById('stProgressMsg').innerHTML      = '&#x26D4; 停止中...';

  if (_stMode === 'all') {
    applyContentFilter();
    setTimeout(function() {
      document.getElementById('stProgressArea').style.display = 'none';
    }, 3000);
  }
}

/* [CR-29] チェックボックス onchange ハンドラ
   item_id: ファイルのGraph API item id
   site_name: サイト名（_stAllCachesのキー）
   filename: ダウンロード時のファイル名
   el: チェックボックス要素 */
function onFileCheck(item_id, site_name, filename, el) {
  if (el.checked) {
    // [CR-15] 10件上限チェック
    if (_stCheckedFiles.size >= 10) {
      el.checked = false;
      alert('最大10件まで選択できます。');
      return;
    }
    // drive_id は _stAllCaches から取得（filesへの追加不要）
    const drive_id = (_stAllCaches[site_name] && _stAllCaches[site_name].drive_id)
                     ? _stAllCaches[site_name].drive_id
                     : '';
    _stCheckedFiles.set(item_id, {
      site_name: site_name,
      drive_id:  drive_id,
      item_id:   item_id,
      filename:  filename,
    });
  } else {
    _stCheckedFiles.delete(item_id);
  }
  renderDownloadPanel();
  updateBulkDownloadBtn();
}

/* [CR-25/CR-29/CR-30] ダウンロードパネルを更新する。
   _stCheckedFiles の全エントリを <a href="/api/download/..."> として描画。
   件数が0の場合はパネルを非表示にする。 */
function renderDownloadPanel() {
  const panel = document.getElementById('stDownloadPanel');
  if (!panel) return;

  if (_stCheckedFiles.size === 0) {
    panel.style.display = 'none';
    panel.innerHTML     = '';
    return;
  }

  panel.style.display = 'block';

  let html =
    '<div class="dl-panel-header">' +
    '&#x2B07; ダウンロードリスト（' + _stCheckedFiles.size + '件）' +
    '<button class="btn" style="font-size:11px;padding:2px 8px;" ' +
    'onclick="_stCheckedFiles.clear();renderDownloadPanel();">&#x274C; クリア</button>' +
    '</div>';

  for (const [item_id, info] of _stCheckedFiles) {
    if (!info.drive_id) {
      // drive_id 空 → グレーアウト表示（Bug-E/Bug-F対応）
      html +=
        '<div class="dl-panel-item" style="color:#9ca3af;">' +
        '&#x26A0; ' + escHtml(info.filename) +
        ' <span style="font-size:10px;">（再探索後にダウンロード可）</span>' +
        '</div>';
    } else {
      // [Feature v2.1] data-*属性方式（JSON.stringify廃止・引用符問題を回避）
      html +=
        '<div class="dl-panel-item">' +
        '<button class="btn-copy" style="margin-right:6px;" ' +
        'data-site="'     + escAttr(info.site_name) + '" ' +
        'data-item-id="'  + escAttr(info.item_id)   + '" ' +
        'data-drive-id="' + escAttr(info.drive_id)  + '" ' +
        'data-filename="' + escAttr(info.filename)   + '" ' +
        'onclick="singleDownloadWithPicker(' +
        'this.dataset.site,this.dataset.itemId,' +
        'this.dataset.driveId,this.dataset.filename)">&#x2B07;</button>' +
        escHtml(info.filename) +
        '<span class="dl-panel-site">(' + escHtml(info.site_name) + ')</span>' +
        '</div>';
    }
  }

  panel.innerHTML = html;
}


/* [CR-B] 一括ダウンロードボタンの件数・状態を更新する。
   _stCheckedFiles.size が 0 の場合はグレーアウト・disabled。
   1件以上の場合はアクティブ表示・件数更新。 */
function updateBulkDownloadBtn() {
  const btn = document.getElementById('btnBulkDownload');
  if (!btn) return;
  const count = _stCheckedFiles.size;
  btn.innerHTML = '&#x2B07; ダウンロード（' + count + '件）';
  if (count === 0) {
    btn.disabled = true;
    btn.style.background   = '#9ca3af';
    btn.style.borderColor  = '#9ca3af';
    btn.style.cursor       = 'not-allowed';
  } else {
    btn.disabled = false;
    btn.style.background   = '#0f4a8a';
    btn.style.borderColor  = '#0f4a8a';
    btn.style.cursor       = 'pointer';
  }
}


/* [Feature] フォルダ選択ダイアログ→1件ローカル保存の共通処理。
   呼び出し元: stRenderFile の dlBtn / renderDownloadPanel の dlBtn */
async function singleDownloadWithPicker(siteName, itemId, driveId, filename) {
  const progressArea = document.getElementById('stProgressArea');
  const progressMsg  = document.getElementById('stProgressMsg');
  progressArea.style.display = 'flex';
  progressMsg.innerHTML = '&#x1F4C2; フォルダ選択ダイアログを開いています...';

  // フォルダ選択
  let folderResp;
  try {
    folderResp = await fetch('/api/pick-folder', {method: 'POST'});
  } catch (e) {
    progressMsg.innerHTML = '&#x274C; フォルダ選択エラー: ' + escHtml(e.message);
    setTimeout(function() { progressArea.style.display = 'none'; }, 5000);
    return;
  }
  const folderData = await folderResp.json();
  if (!folderData.ok) {
    progressMsg.innerHTML = folderData.cancelled
      ? '&#x26D4; キャンセルされました'
      : '&#x274C; ' + escHtml(folderData.message || 'フォルダ選択失敗');
    setTimeout(function() { progressArea.style.display = 'none'; }, 4000);
    return;
  }
  const folder = folderData.folder;

  // ローカル保存
  progressMsg.innerHTML =
    '&#x2B07; ' + escHtml(filename) + ' を保存中... → ' + escHtml(folder);
  try {
    const saveResp = await fetch('/api/download-to-folder', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({
        site_name:   siteName,
        item_id:     itemId,
        drive_id:    driveId,
        filename:    filename,
        folder_path: folder,
      }),
    });
    const saveData = await saveResp.json();
    if (saveData.ok) {
      progressMsg.innerHTML =
        '&#x2705; 保存完了: ' + escHtml(saveData.saved_path);
    } else {
      progressMsg.innerHTML =
        '&#x274C; 保存失敗: ' + escHtml(saveData.message || '不明');
    }
  } catch (e) {
    progressMsg.innerHTML = '&#x274C; 通信エラー: ' + escHtml(e.message);
  }
  setTimeout(function() { progressArea.style.display = 'none'; }, 6000);
}

/* [Feature] チェック済みファイルを1回のフォルダ選択でローカル保存する。
   フォルダ選択は先頭で1回のみ。進捗は個別ファイルごとに表示。
   呼び出し元: stSelectedBar の btnBulkDownload ボタン */
async function bulkDownloadCheckedFiles() {
  if (_stCheckedFiles.size === 0) return;

  const entries = Array.from(_stCheckedFiles.values());
  const total   = entries.length;

  const progressArea = document.getElementById('stProgressArea');
  const progressMsg  = document.getElementById('stProgressMsg');
  progressArea.style.display = 'flex';
  progressMsg.innerHTML = '&#x1F4C2; フォルダ選択ダイアログを開いています...';

  // フォルダ選択（1回のみ）
  let folderResp;
  try {
    folderResp = await fetch('/api/pick-folder', {method: 'POST'});
  } catch (e) {
    progressMsg.innerHTML = '&#x274C; フォルダ選択エラー: ' + escHtml(e.message);
    setTimeout(function() { progressArea.style.display = 'none'; }, 5000);
    return;
  }
  const folderData = await folderResp.json();
  if (!folderData.ok) {
    progressMsg.innerHTML = folderData.cancelled
      ? '&#x26D4; キャンセルされました'
      : '&#x274C; ' + escHtml(folderData.message || 'フォルダ選択失敗');
    setTimeout(function() { progressArea.style.display = 'none'; }, 4000);
    return;
  }
  const folder = folderData.folder;

  let saved = 0;
  let skipped = 0;

  for (let i = 0; i < entries.length; i++) {
    const info = entries[i];

    if (!info.drive_id) {
      progressMsg.innerHTML =
        '&#x26A0; ' + escHtml(info.filename) +
        ' はキャッシュ更新後にダウンロード可能です。スキップします。';
      await new Promise(function(r) { setTimeout(r, 500); });
      skipped++;
      continue;
    }

    progressMsg.innerHTML =
      '&#x1F4C2; ' + (i + 1) + '/' + total + '件: ' +
      escHtml(info.filename) + ' → ' + escHtml(folder) + ' に保存中...';

    try {
      const saveResp = await fetch('/api/download-to-folder', {
        method:  'POST',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({
          site_name:   info.site_name,
          item_id:     info.item_id,
          drive_id:    info.drive_id,
          filename:    info.filename,
          folder_path: folder,
        }),
      });
      const saveData = await saveResp.json();
      if (saveData.ok) {
        saved++;
      } else {
        progressMsg.innerHTML =
          '&#x274C; 保存失敗 (' + escHtml(info.filename) + '): ' +
          escHtml(saveData.message || '不明');
        await new Promise(function(r) { setTimeout(r, 1500); });
      }
    } catch (e) {
      progressMsg.innerHTML =
        '&#x274C; 通信エラー (' + escHtml(info.filename) + '): ' + escHtml(e.message);
      await new Promise(function(r) { setTimeout(r, 1500); });
    }
  }

  progressMsg.innerHTML =
    '&#x2705; ' + saved + '/' + total + '件を ' + escHtml(folder) + ' に保存しました。' +
    (skipped > 0 ? ' （' + skipped + '件スキップ）' : '');
  setTimeout(function() { progressArea.style.display = 'none'; }, 8000);
}



/* [CR-7] EventSource を Promise でラップして await 可能にする
   [CR-8] onerror で cancel エンドポイントを呼んでから reject
   [CR-9] done/cancelled 受信後 SSE_INTER_WAIT_MS 待機してから resolve */
function sseExploreAndWait(site_name, path, depth) {
  _stFilteredExploreSiteName = site_name;

  const url = '/api/portal/expand_deep/' +
              encodeURIComponent(site_name) +
              '?depth=' + depth +
              '&start_path=' + encodeURIComponent(path);

  return new Promise(function(resolve, reject) {
    const src = new EventSource(url);
    _stFilteredExploreSource = src;

    src.onmessage = function(e) {
      const data = JSON.parse(e.data);

      if (data.type === 'exploring' || data.type === 'progress') {
        document.getElementById('stProgressMsg').innerHTML =
          '&#x1F50D; ' + escHtml(site_name) + ' ( ' + escHtml(data.path) + ' )';
        return;
      }

      if (data.type === 'paused') {
        // サーバー側count-based pause → 継続/停止ボタンを表示して待機
        document.getElementById('stProgressMsg').innerHTML =
          '&#x23F8; ' + data.count + 'フォルダ到達。継続しますか？';
        document.getElementById('btnStResume').style.display    = 'inline-block';
        document.getElementById('btnStPauseStop').style.display = 'inline-block';
        document.getElementById('btnStCancel').style.display    = 'none';
        return;  // Promise は解決しない（resumeを待つ）
      }

      if (data.type === 'done' || data.type === 'cancelled') {
        src.close();
        _stFilteredExploreSource = null;
        // [CR-9] サーバー側 finally: running=False の完了を確保するため待機
        setTimeout(function() { resolve(data); }, SSE_INTER_WAIT_MS);
        return;
      }

      if (data.type === 'error') {
        src.close();
        _stFilteredExploreSource = null;
        reject(new Error(data.message || 'SSEエラー'));
      }
    };

    src.onerror = function() {
      src.close();
      _stFilteredExploreSource = null;
      // [CR-8] onerror でも cancel を呼んでサーバーのrunningをFalseにしてからreject
      fetch('/api/portal/expand_deep/' +
            encodeURIComponent(site_name) + '/cancel',
            {method: 'POST'}).finally(function() {
        reject(new Error('SSE接続エラー: ' + site_name));
      });
    };
  });
}

/* 呼び出し元: renderFlatResultList() 内の一括探索ボタン */
async function runFilteredRowsLoop() {
  // ボタン押下時点で _stFilteredRows を確認（古いデータ防止）
  const targetRows = _stFilteredRows.slice();

  if (targetRows.length === 0) {
    alert('探索対象がありません。フィルターを入力してください。');
    return;
  }
  if (_stRunning) {
    alert('探索中です。完了またはキャンセルをお待ちください。');
    return;
  }

  _stRunning = true;
  if (_stPauseResolver) { _stPauseResolver(); _stPauseResolver = null; }

  const progressArea = document.getElementById('stProgressArea');
  const progressMsg  = document.getElementById('stProgressMsg');
  const btnCancel    = document.getElementById('btnStCancel');

  progressArea.style.display                               = 'flex';
  btnCancel.disabled                                       = false;
  btnCancel.style.display                                  = 'inline-block';
  document.getElementById('btnStResume').style.display    = 'none';
  document.getElementById('btnStPauseStop').style.display = 'none';

  lockSidebar(true);

  let completedCount = 0;

  for (let i = 0; i < targetRows.length; i++) {
    if (!_stRunning) break;

    const row = targetRows[i];
    if (row.kind !== 'folder') { completedCount++; continue; }

    // フォルダの実パスを計算（path=親パス、name=フォルダ名）
    const explorePath = (row.path === '/')
      ? '/' + row.name
      : row.path + '/' + row.name;

    progressMsg.innerHTML =
      '&#x1F50D; ' + (i + 1) + '/' + targetRows.length +
      ': ' + escHtml(row.site_display) + ' / ' + escHtml(explorePath) + ' 探索中...';

    try {
      if (_stDepth === 1) {
        // ── depth=1: POST /api/portal/expand/<site_name> ──
        const resp = await fetch(
          '/api/portal/expand/' + encodeURIComponent(row.site_name),
          {
            method:  'POST',
            headers: {'Content-Type': 'application/json'},
            body:    JSON.stringify({path: explorePath}),
          }
        );
        if (!resp.ok) {
          progressMsg.innerHTML =
            '&#x274C; HTTP ' + resp.status + ' (' + escHtml(row.site_display) + ')';
          _stRunning = false;
          break;
        }
        const data = await resp.json();
        if (data.ok !== true) {
          progressMsg.innerHTML =
            '&#x274C; エラー (' + escHtml(row.site_display) + '): ' +
            escHtml(data.message || '不明');
          _stRunning = false;
          break;
        }
        if (data.tree) { _stAllCaches[row.site_name] = data.tree; }

        // Q8ア: 1フォルダ直下100件超で一時停止
        const pathData    = data.tree && data.tree.explored
                            ? (data.tree.explored[explorePath] || null) : null;
        const folderCount = pathData ? (pathData.folders || []).length : 0;

        if (folderCount >= 100) {
          progressMsg.innerHTML =
            '&#x23F8; ' + escHtml(row.site_display) + ': ' + folderCount +
            'フォルダ検出。継続しますか？';
          btnCancel.style.display                                  = 'none';
          document.getElementById('btnStResume').style.display    = 'inline-block';
          document.getElementById('btnStPauseStop').style.display = 'inline-block';

          await new Promise(function(resolve) { _stPauseResolver = resolve; });
          _stPauseResolver = null;

          document.getElementById('btnStResume').style.display    = 'none';
          document.getElementById('btnStPauseStop').style.display = 'none';
          btnCancel.style.display                                  = 'inline-block';

          if (!_stRunning) break;
        }

        completedCount++;

        // depth=1のリクエスト間隔
        if (_stRunning && i < targetRows.length - 1) {
          await new Promise(function(r) { setTimeout(r, 300); });
        }

      } else {
        // ── depth=2/3/6: SSE sseExploreAndWait ──
        try {
          const result = await sseExploreAndWait(row.site_name, explorePath, _stDepth);
          if (result && result.tree) {
            _stAllCaches[row.site_name] = result.tree;
          }
          completedCount++;
          // CR-9の300ms待機は sseExploreAndWait 内の setTimeout で完了済み
        } catch(sseErr) {
          if (!_stRunning) {
            // キャンセル/停止による正常中断
            break;
          }
          progressMsg.innerHTML =
            '&#x274C; SSEエラー (' + escHtml(row.site_display) + '): ' +
            escHtml(sseErr.message || '不明');
          _stRunning = false;
          break;
        }
      }

    } catch (e) {
      progressMsg.innerHTML =
        '&#x274C; 通信エラー (' + escHtml(row.site_display) + '): ' +
        escHtml(e.message);
      _stRunning = false;
      break;
    }
  }

  lockSidebar(false);
  _stRunning = false;

  if (progressMsg.innerHTML.indexOf('&#x274C;') === -1 &&
      progressMsg.innerHTML.indexOf('&#x26D4;') === -1) {
    progressMsg.innerHTML =
      '&#x2705; 完了: ' + completedCount + '/' +
      targetRows.length + '件探索済み';
  }

  // Q2ウ: 完了後は何もしない（applyContentFilter再実行なし）

  setTimeout(function() {
    if (!_stRunning) {
      progressArea.style.display = 'none';
    }
  }, 5000);
}

/* [CR-11] 行単位の深さ1固定探索。_stRunning チェック付き。
   呼び出し元: renderFlatResultList() 内の 🔍 ボタン
   引数: site_name（サイト名）, path（親パス）, name（フォルダ名） */
async function exploreSingleFilteredRow(site_name, path, name) {
  // [CR-11] 探索中チェック
  if (_stRunning) {
    alert('探索中です。完了後にお試しください。');
    return;
  }

  // フォルダの実パスを計算
  const explorePath = (path === '/') ? '/' + name : path + '/' + name;

  try {
    const resp = await fetch(
      '/api/portal/expand/' + encodeURIComponent(site_name),
      {
        method:  'POST',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({path: explorePath}),
      }
    );
    const data = await resp.json();
    if (data.ok === true) {
      // キャッシュを更新（Q2ウ: 表示は何もしない）
      if (data.tree) { _stAllCaches[site_name] = data.tree; }
    } else {
      alert('エラー: ' + escHtml(data.message || '不明'));
    }
  } catch(e) {
    alert('通信エラー: ' + e.message);
  }
}


// ═══════════════════════════════════════════════
// Tab2: Tree （既存コードを移植）
// ═══════════════════════════════════════════════
const FAV_KEY  = ["r19", "favorites"].join("_");
let treeData   = null;
let _sseSource = null;
let _viewMode  = 'tree';
let _favorites = {};

function initFavorites() {
  try {
    _favorites = JSON.parse(localStorage.getItem(FAV_KEY) || "{}");
  } catch(e) { _favorites = {}; }
}

function toggleFavorite(path, name, webUrl, btn) {
  if (_favorites[path]) { delete _favorites[path]; }
  else { _favorites[path] = { name: name, web_url: webUrl }; }
  try { localStorage.setItem(FAV_KEY, JSON.stringify(_favorites)); } catch(e) {}
  btn.innerHTML = _favorites[path] ? '&#x2605;' : '&#x2606;';
  renderFavorites();
}

function renderFavorites() {
  const area    = document.getElementById('favArea');
  const favList = document.getElementById('favList');
  const keys    = Object.keys(_favorites);
  if (keys.length === 0) {
    area.removeAttribute('open');
    favList.innerHTML = '';
    return;
  }
  favList.innerHTML = keys.map(path => {
    const fav     = _favorites[path];
    const url     = escAttr(fav.web_url || '');
    const name    = escHtml(fav.name    || path);
    const copyUrl = escAttr(fav.web_url || '');
    return '<div class="fav-row">' +
           '&#x1F4C1; ' +
           '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + name + '</a>' +
           (url ? '<button class="btn-copy" data-url="' + copyUrl + '" ' +
             'onclick="copyLink(this.dataset.url,this)">&#x1F4CB;</button>' : '') +
           '<button class="btn-fav" data-path="' + escAttr(path) + '" ' +
           'onclick="(function(b){' +
           'var p=b.dataset.path;delete _favorites[p];' +
           'localStorage.setItem(FAV_KEY,JSON.stringify(_favorites));' +
           'renderFavorites();renderAll();})(this)">&#x2605;</button>' +
           '</div>';
  }).join('');
}

async function copyLink(url, btn) {
  try {
    await navigator.clipboard.writeText(url);
    const orig = btn.innerHTML;
    btn.innerHTML = '&#x2705;';
    setTimeout(function() { btn.innerHTML = orig; }, 1000);
  } catch(e) {
    alert('コピー失敗: ' + e.message);
  }
}

function freshnessStyle(dateStr) {
  if (!dateStr) return { cls: 'freshness-red', icon: '&#x1F534;' };
  const now      = new Date();
  const target   = new Date(dateStr);
  const diffDays = (now - target) / (1000 * 60 * 60 * 24);
  if (diffDays <= 31)  return { cls: 'freshness-green',  icon: '&#x1F7E2;' };
  if (diffDays <= 92)  return { cls: 'freshness-yellow', icon: '&#x1F7E1;' };
  return { cls: 'freshness-red', icon: '&#x1F534;' };
}

function highlightText(text, q) {
  if (!q) return escHtml(text);
  const escaped  = escHtml(text);
  const escapedQ = q.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
  const re       = new RegExp('(' + escapedQ + ')', 'gi');
  return escaped.replace(re, '<mark>$1</mark>');
}

function buildExtFilter() {
  const explored = treeData ? (treeData.explored || {}) : {};
  const counts   = {};
  for (const pathData of Object.values(explored)) {
    for (const file of (pathData.files || [])) {
      const ext = '.' + file.name.split('.').pop().toLowerCase();
      counts[ext] = (counts[ext] || 0) + 1;
    }
  }
  const sel = document.getElementById('extFilter');
  const cur = sel.value;
  sel.innerHTML = '<option value="">すべて</option>';
  Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([ext, n]) => {
    const opt       = document.createElement('option');
    opt.value       = ext;
    opt.textContent = ext + ' (' + n + '件)';
    sel.appendChild(opt);
  });
  sel.value = cur;
}

function attachExploreButtons() {
  document.querySelectorAll('#treeContent .btn-explore').forEach(btn => {
    btn.addEventListener('click', function() {
      exploreFolder(this.dataset.path, this);
    });
  });
}

async function loadTree() {
  const resp = await fetch('/api/tree');
  treeData   = await resp.json();
  initFavorites();
  renderAll();
  attachExploreButtons();
  const btnRoot = document.getElementById('btnRootExplore');
  if (btnRoot) {
    btnRoot.addEventListener('click', function() { startDeepExplore(); });
  }
}

function renderAll() {
  const explored  = treeData.explored  || {};
  const updatedAt = treeData.updated_at || '未更新';
  const pathCount = Object.keys(explored).length;

  let unexplored = 0;
  for (const [path, data] of Object.entries(explored)) {
    for (const folder of (data.folders || [])) {
      const subPath = path === '/' ? '/' + folder.name : path + '/' + folder.name;
      if (!explored[subPath]) unexplored++;
    }
  }

  const overallFs = freshnessStyle(treeData.updated_at || '');
  document.getElementById('portalMeta').innerHTML =
    'ICS R19 Tab2 | ' +
    '<span class="' + overallFs.cls + '" style="padding:1px 6px;font-size:11px;">' +
    overallFs.icon + ' ' + updatedAt + '</span>' +
    ' 探索済み: ' + pathCount + 'パス' +
    ' 未探索: <span style="color:#fbbf24;font-weight:600;">' + unexplored + '件</span>';

  document.getElementById('cacheInfo').textContent =
    'drive_id: ' + (treeData.drive_id || '').substring(0, 20) + '...';

  const loadingMsg      = document.getElementById('loadingMsg');
  const rootExploreArea = document.getElementById('rootExploreArea');
  const treeContent     = document.getElementById('treeContent');

  loadingMsg.style.display = 'none';

  const root = explored['/'];
  if (!root) {
    rootExploreArea.style.display = 'block';
    treeContent.innerHTML         = '';
    return;
  }

  // [v2.06] textContent比較廃止 → dataset.path直接比較（Tab3 v2.05fixと同一）
  const openPaths = new Set();
  treeContent.querySelectorAll('details[data-path][open]')
    .forEach(function(el) { openPaths.add(el.dataset.path); });

  rootExploreArea.style.display = 'none';

  const favArea = document.getElementById('favArea');
  if (favArea) {
    favArea.style.display = _viewMode === 'tree' ? '' : 'none';
  }
  renderFavorites();

  if (_viewMode === 'list') {
    const q   = document.getElementById('searchInput').value.toLowerCase();
    const ext = document.getElementById('extFilter').value.toLowerCase();
    treeContent.innerHTML = buildFlatList(q, ext);
  } else {
    treeContent.innerHTML = renderLevel('/', explored);
    attachExploreButtons();
    // [v2.06] dataset.path直接比較で復元（Tab3 v2.05fixと同一）
    treeContent.querySelectorAll('details[data-path]')
      .forEach(function(el) {
        if (openPaths.has(el.dataset.path)) el.open = true;
      });
    buildExtFilter();
  }
}

function renderLevel(path, explored) {
  const data = explored[path];
  if (!data) return '';
  let html = '';
  for (const file of (data.files || [])) { html += renderFile(file); }
  for (const folder of (data.folders || [])) {
    const folderPath = path === '/' ? '/' + folder.name : path + '/' + folder.name;
    html += renderFolder(folder, folderPath, explored);
  }
  return html;
}

function renderFile(file) {
  const ext     = file.name.split('.').pop().toLowerCase();
  const icon    = fileIcon(ext);
  const kb      = file.size > 0 ? Math.round(file.size / 1024).toLocaleString() + ' KB' : '-';
  const dt      = file.last_modified ? file.last_modified.substring(0, 10) : '-';
  const meta    = '<span style="color:#9ca3af;font-size:11px;margin-left:8px;">' + kb + ' / ' + dt + '</span>';
  const copyBtn = '<button class="btn-copy" data-url="' + escAttr(file.web_url) + '" ' +
                  'onclick="copyLink(this.dataset.url,this)">&#x1F4CB;</button>';
  return '<div class="file-item"><a href="' + escAttr(file.local_url) +
         '" target="_blank" rel="noopener noreferrer">' +
         icon + ' ' + escHtml(file.name) + '</a>' + meta + copyBtn + '</div>';
}


function renderFolder(folder, folderPath, explored) {
  const data = explored[folderPath];
  const name = escHtml(folder.name);
  const url  = escAttr(folder.web_url);
  let badge  = '';
  let body   = '';

  if (!data) {
    badge = '<span class="badge-unexplored">&#x1F50D; 未探索</span>';
    body  = '<button class="btn-explore" data-path="' + escAttr(folderPath) + '">' +
            '&#x1F50D; このフォルダを探索</button>';
  } else if (data.truncated) {
    badge = '<span class="badge-truncated">&#x26A0;&#xFE0F; 過密 &nbsp;&#x1F4C1;' +
            data.desc_folders + '&nbsp; &#x1F4C4;' + data.desc_files + '</span>';
    body  = '<p class="truncated-msg">&#x26A0;&#xFE0F; ルート探索で過密判定。' +
            '<a href="' + url + '" target="_blank"> SharePointで直接確認 &#x2192;</a></p>' +
            '<button class="btn-explore" data-path="' + escAttr(folderPath) + '">' +
            '&#x1F50D; このフォルダを探索</button>';
  } else {
    const fs    = freshnessStyle(data.explored_at || '');
    const dtStr = (data.explored_at || '').substring(0, 16);
    badge = '<span class="' + fs.cls + '">' + fs.icon + ' ' + dtStr + '</span>';
    body  = renderLevel(folderPath, explored);
  }

  const isFav  = !!_favorites[folderPath];
  const favBtn = '<button class="btn-fav" ' +
    'data-path="' + escAttr(folderPath) + '" ' +
    'data-name="' + escHtml(folder.name) + '" ' +
    'data-url="'  + url + '" ' +
    'onclick="event.stopPropagation();' +
    'toggleFavorite(this.dataset.path,this.dataset.name,this.dataset.url,this)">' +
    (isFav ? '&#x2605;' : '&#x2606;') + '</button>';

  // [v2.06] data-path を追加 → renderAll の open 状態復元に使用（Tab3 v2.05と同一）
  return '<details class="folder-node" data-path="' + escAttr(folderPath) + '">' +
    '<summary class="folder-summary">' +
    '<span class="chevron">&#x25B6;</span>' +
    '<span class="folder-icon">&#x1F4C1;</span>' +
    '<a class="folder-link" href="' + url + '" target="_blank" ' +
    'onclick="event.stopPropagation()">' + name + '</a>' +
    badge + favBtn +
    (folder.web_url
      ? '<button class="btn-copy" data-url="' + url + '" ' +
        'onclick="event.stopPropagation();copyLink(this.dataset.url,this)">&#x1F4CB;</button>'
      : '') +
    '</summary>' +
    '<div class="folder-body">' + body + '</div>' +
    '</details>';
}



function fileIcon(ext) {
  const m = {
    xlsx:'&#x1F4CA;', xls:'&#x1F4CA;',
    docx:'&#x1F4DD;', doc:'&#x1F4DD;',
    pptx:'&#x1F4D0;', ppt:'&#x1F4D0;',
    pdf:'&#x1F4D5;',  zip:'&#x1F5DC;',
    png:'&#x1F5BC;',  jpg:'&#x1F5BC;', jpeg:'&#x1F5BC;'
  };
  return m[ext] || '&#x1F4C4;';
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escAttr(s) {
  return String(s).replace(/"/g,'&quot;');
}

async function exploreFolder(path, btn) {
  if (btn) { btn.disabled = true; btn.innerHTML = '&#x23F3; 探索中...'; }
  try {
    const resp = await fetch('/api/expand', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({path: path}),
    });
    const data = await resp.json();
    if (data.ok === true) {
      treeData = data.tree;
      renderAll();
    } else if (data.ok === 'confirm') {
      if (btn) { btn.disabled = false; btn.innerHTML = '&#x1F50D; このフォルダを探索'; }
      const msg = data.path + ' には\\nフォルダ: ' + data.folders +
                  '件 / ファイル: ' + data.files + '件\\nあります。探索しますか？';
      if (!confirm(msg)) return;
      if (btn) { btn.disabled = true; btn.innerHTML = '&#x23F3; 探索中...'; }
      try {
        const resp2 = await fetch('/api/expand', {
          method:  'POST',
          headers: {'Content-Type': 'application/json'},
          body:    JSON.stringify({path: data.path, force: true}),
        });
        const data2 = await resp2.json();
        if (data2.ok === true) { treeData = data2.tree; renderAll(); }
        else { alert('エラー: ' + data2.message); }
      } catch(e) { alert('通信エラー: ' + e.message); }
      if (btn) { btn.disabled = false; btn.innerHTML = '&#x1F50D; このフォルダを探索'; }
    } else {
      alert('エラー: ' + data.message);
      if (btn) { btn.disabled = false; btn.innerHTML = '&#x1F50D; このフォルダを探索'; }
    }
  } catch(e) {
    alert('通信エラー: ' + e.message);
    if (btn) { btn.disabled = false; btn.innerHTML = '&#x1F50D; このフォルダを探索'; }
  }
}

function buildFlatList(q, ext) {
  const explored  = treeData ? (treeData.explored || {}) : {};
  const sort      = document.getElementById('sortSelect').value;
  const target    = document.getElementById('targetSelect').value;
  const rows      = [];

  if (target === 'both') {
    for (const [path, data] of Object.entries(explored)) {
      if (path === '/') continue;
      const parts      = path.split('/');
      const name       = parts[parts.length - 1];
      const parent     = parts.slice(0, -1).join('/') || '/';
      const matchQ     = !q || name.toLowerCase().includes(q);
      if (matchQ && !ext) {
        const parentData   = explored[parent];
        const folderInfo   = parentData
          ? (parentData.folders || []).find(f => f.name === name) : null;
        const folderWebUrl = folderInfo ? folderInfo.web_url : '';
        rows.push({
          kind: 'folder', name: name, path: parent,
          web_url: folderWebUrl, size: 0,
          date: data.explored_at || '', local_url: '',
        });
      }
    }
  }

  for (const [path, data] of Object.entries(explored)) {
    for (const file of (data.files || [])) {
      const name    = file.name;
      const fileExt = name.includes('.') ? '.' + name.split('.').pop().toLowerCase() : '';
      const matchQ  = !q   || name.toLowerCase().includes(q);
      const matchE  = !ext || fileExt === ext;
      if (matchQ && matchE) {
        rows.push({
          kind: 'file', name: name, path: path,
          web_url: file.web_url, local_url: file.local_url,
          size: file.size, date: file.last_modified || '',
        });
      }
    }
  }

  if (sort === 'date') rows.sort((a, b) => b.date.localeCompare(a.date));
  else rows.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));

  const nFolders = rows.filter(r => r.kind === 'folder').length;
  const nFiles   = rows.filter(r => r.kind === 'file').length;

  let html = '<div class="flat-summary">検索結果: フォルダ ' + nFolders + '件 / ファイル ' + nFiles + '件</div>';
  html += '<table class="flat-list"><thead><tr>' +
          '<th style="width:28px;"></th><th>名前</th><th>パス</th>' +
          '<th>サイズ</th><th>更新日</th><th></th></tr></thead><tbody>';

  for (const row of rows) {
    const icon    = row.kind === 'folder' ? '&#x1F4C1;' : fileIcon(row.name.split('.').pop().toLowerCase());
    const nameHL  = highlightText(row.name, q);
    const kb      = row.size > 0 ? Math.round(row.size / 1024).toLocaleString() + ' KB' : '-';
    const dt      = row.date ? row.date.substring(0, 10) : '-';
    const href    = escAttr(row.kind === 'folder' ? row.web_url : row.local_url);
    const webUrl  = escAttr(row.web_url || row.local_url);
    const openBtn = href
      ? '<a class="btn-open" href="' + href + '" target="_blank" rel="noopener noreferrer">開く</a>' : '';
    const copyBtn = webUrl
      ? '<button class="btn-copy" data-url="' + webUrl + '" ' +
        'onclick="copyLink(this.dataset.url,this)">&#x1F4CB;</button>' : '';
    html += '<tr><td>' + icon + '</td>' +
            '<td class="col-name">' +
            (href ? '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + nameHL + '</a>' : nameHL) +
            '</td>' +
            '<td class="col-path">' + escHtml(row.path) + '</td>' +
            '<td class="col-meta">' + kb + '</td>' +
            '<td class="col-meta">' + dt + '</td>' +
            '<td class="col-open">' + openBtn + copyBtn + '</td></tr>';
  }
  html += '</tbody></table>';
  return html;
}

function toggleViewMode() { setViewMode(_viewMode === 'tree' ? 'list' : 'tree'); }

function setViewMode(mode) {
  _viewMode      = mode;
  const btn      = document.getElementById('btnViewToggle');
  const listCtrl = document.getElementById('listControls');
  if (mode === 'tree') {
    btn.innerHTML        = '&#x2630; リスト表示';
    btn.style.background   = '#e0edff';
    btn.style.borderColor  = '#0f4a8a';
    btn.style.color        = '#0f4a8a';
    listCtrl.style.display = 'none';
  } else {
    btn.innerHTML        = '&#x1F332; ツリー表示';
    btn.style.background   = '#fff';
    btn.style.borderColor  = '#d1d5db';
    btn.style.color        = '#374151';
    listCtrl.style.display = 'flex';
  }
  renderAll();
}

function filterTree() {
  const q   = document.getElementById('searchInput').value.toLowerCase();
  const ext = document.getElementById('extFilter').value.toLowerCase();
  if (_viewMode === 'list') { renderAll(); return; }
  if (!q && !ext) {
    document.querySelectorAll('#treeContent .folder-node, #treeContent .file-item')
      .forEach(n => n.style.display = '');
    collapseAll();
    return;
  }
  document.querySelectorAll('#treeContent .folder-node').forEach(d => {
    d.style.display = 'none'; d.open = false;
  });
  document.querySelectorAll('#treeContent .file-item').forEach(fi => {
    fi.style.display = 'none';
  });
  function showWithAncestors(el) {
    el.style.display = '';
    let p = el.parentElement;
    while (p) {
      if (p.classList && p.classList.contains('folder-node')) {
        p.style.display = ''; p.open = true;
      }
      p = p.parentElement;
    }
  }
  document.querySelectorAll('#treeContent .folder-node').forEach(d => {
    const link = d.querySelector(':scope > summary a.folder-link');
    const name = link ? link.textContent.toLowerCase() : '';
    if (!ext && name.includes(q)) {
      showWithAncestors(d);
      d.open = true;
      if (link) link.innerHTML = highlightText(link.textContent, q);
      d.querySelectorAll('.file-item').forEach(fi => { fi.style.display = ''; });
    }
  });
  document.querySelectorAll('#treeContent .file-item').forEach(fi => {
    const a       = fi.querySelector('a');
    const name    = a ? a.textContent.toLowerCase() : '';
    const fileExt = name.includes('.') ? '.' + name.split('.').pop() : '';
    const matchQ   = !q   || name.includes(q);
    const matchExt = !ext || fileExt === ext;
    if (matchQ && matchExt) {
      fi.style.display = '';
      if (a) a.innerHTML = highlightText(a.textContent, q);
      showWithAncestors(fi);
    }
  });
}

function expandAll() {
  document.querySelectorAll('#treeContent details.folder-node').forEach(d => d.open = true);
}

function collapseAll() {
  document.querySelectorAll('#treeContent details.folder-node').forEach(d => d.open = false);
}

async function resetCache() {
  if (!confirm('キャッシュをリセットしますか？\\n探索済みデータが全て削除されます。')) return;
  await fetch('/api/reset', {method: 'POST'});
  await loadTree();
}


function startDeepExplore() {
  const progressArea  = document.getElementById('progressArea');
  const progressMsg   = document.getElementById('progressMsg');
  const btnResume     = document.getElementById('btnResume');
  const btnCancelDeep = document.getElementById('btnCancelDeep');
  const btnRoot       = document.getElementById('btnRootExplore');

  if (btnRoot)  btnRoot.disabled     = true;
  progressArea.style.display         = 'flex';
  progressMsg.innerHTML            = '&#x23F3; 探索開始...';
  btnResume.style.display            = 'none';
  btnCancelDeep.style.display        = 'none';

  if (_sseSource) { _sseSource.close(); _sseSource = null; }
  _sseSource = new EventSource('/api/expand_deep');

  _sseSource.onmessage = function(e) {
    const data = JSON.parse(e.data);
    if (data.type === 'exploring') {
      progressMsg.innerHTML = '&#x1F50D; 探索中... ( ' + escHtml(data.path) + ' )';
    } else if (data.type === 'progress') {
      progressMsg.innerHTML = '&#x23F3; 探索中... ' + data.count + 'フォルダ完了 ( ' + escHtml(data.path) + ' )';
    } else if (data.type === 'done') {
      progressMsg.innerHTML = '&#x2705; 完了: ' + data.count + 'フォルダ探索済み';
      btnResume.style.display = 'none'; btnCancelDeep.style.display = 'none';
      if (btnRoot) btnRoot.disabled = false;
      if (data.tree) { treeData = data.tree; renderAll(); }
      _sseSource.close(); _sseSource = null;
      setTimeout(function() { progressArea.style.display = 'none'; }, 5000);
    } else if (data.type === 'cancelled') {
      progressMsg.innerHTML = '&#x26D4; キャンセル: ' + data.count + 'フォルダ取得済み';
      btnResume.style.display = 'none'; btnCancelDeep.style.display = 'none';
      if (btnRoot) btnRoot.disabled = false;
      if (data.tree) { treeData = data.tree; renderAll(); }
      _sseSource.close(); _sseSource = null;
      setTimeout(function() { progressArea.style.display = 'none'; }, 5000);
    } else if (data.type === 'error') {
      progressMsg.innerHTML = '&#x274C; エラー: ' + escHtml(data.message);
      if (btnRoot) btnRoot.disabled = false;
      _sseSource.close(); _sseSource = null;
    }
  };

  _sseSource.onerror = function() {
    if (!_sseSource) return;
    document.getElementById('progressMsg').innerHTML = '&#x274C; 接続エラー';
    const b = document.getElementById('btnRootExplore');
    if (b) b.disabled = false;
    if (_sseSource) { _sseSource.close(); _sseSource = null; }
  };
}

function resumeDeep() {
  document.getElementById('btnResume').style.display     = 'none';
  document.getElementById('btnCancelDeep').style.display = 'none';
  document.getElementById('progressMsg').innerHTML     = '&#x23F3; 探索再開中...';
  fetch('/api/expand_deep/resume', {method: 'POST'});
}

function cancelDeep() {
  document.getElementById('btnResume').style.display     = 'none';
  document.getElementById('btnCancelDeep').style.display = 'none';
  document.getElementById('progressMsg').innerHTML     = '&#x23F3; キャンセル中...';
  fetch('/api/expand_deep/cancel', {method: 'POST'});
}

// ═══════════════════════════════════════════════
// 初期化
// ═══════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', function() {
  loadPortalData();
  loadTree();
  loadSiteList();
});
</script>
</body>
</html>'''

HTML_TEMPLATE = _HTML_RAW.replace("MAXITEMS_PLACEHOLDER", str(MAX_ITEMS))


# ─────────────────────────────────────────────────────────────
# main()  [60行]
# ─────────────────────────────────────────────────────────────
def main() -> None:
    """
    全体オーケストレーション。
    起動 → 認証 → キャッシュ移行 → サイト登録
         → PSBGRD drive_id 取得 → Flask 起動
    --reset: PSBGRD キャッシュをリセットして起動
    """
    import sys
    sys.setrecursionlimit(2000)

    global _cache, _client, _deep_state, _registry, _loader

    parser = argparse.ArgumentParser(description="R19 SharePoint Portal")
    parser.add_argument(
        "--reset", action="store_true",
        help="PSBGRD キャッシュをリセットして起動",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("R19 SharePoint Portal v20260515_01_01")
    print("=" * 60)

    # --- _deep_state 初期化 ---
    _deep_state = {
        "running":      False,
        "cancelled":    False,
        "pause_event":  threading.Event(),
        "count":        0,
        "current_path": "",
    }
    _deep_state["pause_event"].set()

    _site_deep_state["pause_event"] = threading.Event()
    _site_deep_state["pause_event"].set()
    
    # --- cache/ フォルダ確保・旧ファイル移行 ---
    print("\n[Step 1] キャッシュフォルダ確認")
    _loader = PortalDataLoader()
    _loader.ensure_cache_dir()

    # --- サイトレジストリ初期化 ---
    print("\n[Step 2] サイトレジストリ初期化")
    _registry = SiteRegistry(REGISTRY_FILE)
    _registry.load()
    _loader.load_sites(_registry)
    _loader.load_quicklinks()

    # --- PSBGRD キャッシュ初期化 ---
    print("\n[Step 3] PSBGRD キャッシュ読み込み")
    _cache = LazyCache(str(CACHE_DIR / "tree_PSBGRD_lazy.json"))
    if args.reset:
        print("  [INFO] --reset: キャッシュをリセットします。")
        _cache.reset()
    else:
        _cache.load()

    # --- 認証 ---
    print("\n[Step 4] 認証処理")
    global _auth
    _auth   = GraphAuthManager(TENANT_ID, CLIENT_ID, TOKEN_CACHE_PATH)
    token   = _auth.get_token(SCOPES)
    _client = FolderTreeClient(token)
    print("  [OK] トークン取得完了")

    # --- PSBGRD drive_id 取得 ---
    if not _cache.data.get("drive_id"):
        print("\n[Step 5] PSBGRD site-id / drive-id 取得")
        site_id  = _client.get_site_id()
        drive_id = _client.get_drive_id(site_id)
        _cache.data["drive_id"]   = drive_id
        _cache.data["site"]       = "PSBGRD"
        _cache.data["created_at"] = datetime.now(JST).strftime(
            "%Y-%m-%d %H:%M:%S JST"
        )
        _cache.save()
        _registry.update_drive_id("PSBGRD", drive_id)
        print("  [OK] drive_id を保存しました。")
    else:
        print(
            f"\n[INFO] PSBGRD drive_id キャッシュ利用: "
            f"{_cache.data['drive_id'][:30]}..."
        )

    # --- Flask サーバー起動 ---
    print(f"\n[Step 6] Flask サーバー起動: http://localhost:{FLASK_PORT}")

    def _open_browser() -> None:
        time.sleep(1.2)
        webbrowser.open(f"http://localhost:{FLASK_PORT}")

    threading.Thread(target=_open_browser, daemon=True).start()

    print("  ブラウザが自動で開きます。")
    print("  終了するには Ctrl+C を押してください。")
    print("=" * 60)

    flask_app.run(
        host="127.0.0.1",
        port=FLASK_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()