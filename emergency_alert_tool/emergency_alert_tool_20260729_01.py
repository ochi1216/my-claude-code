"""
emergency_alert_tool_20260729_01.py

緊急地震速報（大分県・大阪府・東京都、震度5弱以上）を検知したら、緊急連絡網の
スタッフへ安否確認を送信し、スタッフが「無事/被災」「職場/自宅」「出社可能/
出社不可能」の3項目をクリックで回答したら、即座に上司へ通知するツール。

Microsoft 365環境（Microsoft Graph API, app-only / client credentials）を前提とする。

実行方法:
    python emergency_alert_tool_20260729_01.py --config config.json --mode web
    python emergency_alert_tool_20260729_01.py --config config.json --mode poll

詳細は README.md を参照。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests
from flask import Flask, abort, render_template_string, request, url_for

try:
    import msal
except ImportError:  # msal はweb/poll実行時のみ必須。ロジック単体テストでは不要。
    msal = None

logger = logging.getLogger("emergency_alert_tool")

# ---------------------------------------------------------------------------
# 震度スケール判定
# ---------------------------------------------------------------------------

INTENSITY_SCALE = ["1", "2", "3", "4", "5弱", "5強", "6弱", "6強", "7"]

# P2P地震情報API (https://api.p2pquake.net/v2/) の緊急地震速報(警報, code=556)
# レスポンスにおける震度階級コードの想定対応表。
# 注意: 本セッション環境では外部API仕様ドキュメントへアクセスできなかったため、
# 既知情報を基にした想定値であり未検証。本番導入前に実データで確認すること。
SCALE_CODE_TO_INTENSITY = {
    10: "1", 20: "2", 30: "3", 40: "4",
    45: "5弱", 50: "5強", 55: "6弱", 60: "6強", 70: "7",
}


def intensity_index(intensity: str) -> int:
    try:
        return INTENSITY_SCALE.index(intensity)
    except ValueError:
        return -1


def meets_threshold(intensity: str, threshold: str) -> bool:
    idx = intensity_index(intensity)
    if idx < 0:
        return False
    return idx >= intensity_index(threshold)


# ---------------------------------------------------------------------------
# 緊急地震速報イベントの正規化
# ---------------------------------------------------------------------------

@dataclass
class AreaIntensity:
    prefecture: str
    max_intensity: str


@dataclass
class EEWEvent:
    event_id: str
    reported_at: str
    areas: list = field(default_factory=list)  # list[AreaIntensity]


def parse_p2pquake_eew(raw: dict) -> Optional[EEWEvent]:
    """P2P地震情報APIの緊急地震速報(警報, code=556)レスポンス1件をEEWEventへ変換する。

    フィールド名・スケールコードの対応は未検証（README/PROJECT_STATUS参照）。
    数値スケールコード(scaleTo)と、文字列表記(maxInt/scaleMax)の両方に対応する。
    """
    if raw.get("code") != 556:
        return None

    event_id = str(raw.get("id") or raw.get("eventId") or raw.get("time") or "")
    reported_at = str(raw.get("time") or "")

    areas = []
    for area_raw in raw.get("areas") or []:
        prefecture = area_raw.get("pref") or area_raw.get("name") or ""
        intensity = ""
        scale_to = area_raw.get("scaleTo")
        if isinstance(scale_to, int):
            intensity = SCALE_CODE_TO_INTENSITY.get(scale_to, "")
        if not intensity:
            raw_intensity = area_raw.get("maxInt") or area_raw.get("scaleMax")
            if isinstance(raw_intensity, str):
                intensity = raw_intensity
        if prefecture and intensity:
            areas.append(AreaIntensity(prefecture=prefecture, max_intensity=intensity))

    return EEWEvent(event_id=event_id, reported_at=reported_at, areas=areas)


def judge_trigger(event: EEWEvent, target_prefectures, threshold: str):
    """対象都府県のうち、閾値以上の震度が観測された地域のリストを返す。空リストなら未トリガー。"""
    return [
        area for area in event.areas
        if area.prefecture in target_prefectures and meets_threshold(area.max_intensity, threshold)
    ]


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

@dataclass
class StaffMember:
    id: str
    name: str
    email: str


@dataclass
class Config:
    tenant_id: str
    client_id: str
    client_secret: str
    sender_upn: str
    target_prefectures: list
    intensity_threshold: str
    quake_api_url: str
    poll_interval_seconds: int
    response_base_url: str
    database_path: str
    staff: list  # list[StaffMember]
    supervisors: list  # list[StaffMember]
    dry_run: bool = False

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        secret_env = raw.get("client_secret_env", "EMERGENCY_ALERT_CLIENT_SECRET")
        client_secret = os.environ.get(secret_env, "")
        return cls(
            tenant_id=raw["tenant_id"],
            client_id=raw["client_id"],
            client_secret=client_secret,
            sender_upn=raw["sender_upn"],
            target_prefectures=raw["target_prefectures"],
            intensity_threshold=raw["intensity_threshold"],
            quake_api_url=raw["quake_api_url"],
            poll_interval_seconds=int(raw.get("poll_interval_seconds", 30)),
            response_base_url=raw["response_base_url"].rstrip("/"),
            database_path=raw.get("database_path", "emergency_alert.db"),
            staff=[StaffMember(**s) for s in raw["staff"]],
            supervisors=[StaffMember(**s) for s in raw["supervisors"]],
            dry_run=bool(raw.get("dry_run", False)),
        )


# ---------------------------------------------------------------------------
# Microsoft Graph 通知
# ---------------------------------------------------------------------------

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


class GraphNotifier:
    """Microsoft Graph API (app-only, client credentials フロー) 経由でメールを送信する。

    Azure ADアプリ登録側で、アプリケーション権限 `Mail.Send` の管理者同意が必要。
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, sender_upn: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.sender_upn = sender_upn
        self._app = None

    def _msal_app(self):
        if self._app is None:
            if msal is None:
                raise RuntimeError("msal がインストールされていません")
            self._app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                client_credential=self.client_secret,
            )
        return self._app

    def _acquire_token(self) -> str:
        result = self._msal_app().acquire_token_silent(GRAPH_SCOPE, account=None)
        if not result:
            result = self._msal_app().acquire_token_for_client(scopes=GRAPH_SCOPE)
        if not result or "access_token" not in result:
            error = result.get("error_description") if result else "unknown error"
            raise RuntimeError(f"Graph token acquisition failed: {error}")
        return result["access_token"]

    def send_mail(self, to_email: str, subject: str, body_html: str) -> None:
        token = self._acquire_token()
        url = f"https://graph.microsoft.com/v1.0/users/{self.sender_upn}/sendMail"
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": [{"emailAddress": {"address": to_email}}],
            },
            "saveToSentItems": "false",
        }
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()


class LoggingNotifier:
    """実際にはメールを送信せず、送信内容をログに出力するテスト用Notifier。

    Microsoft 365側（Azure ADアプリ登録・クライアントシークレット等）の
    準備が整う前に、トリガー判定〜スタッフ通知〜回答〜上司通知までの
    一連の流れを動作確認するために使う（`config.json` の `dry_run: true`）。
    """

    def send_mail(self, to_email: str, subject: str, body_html: str) -> None:
        logger.info("[DRY-RUN] メール送信をスキップしました。宛先=%s 件名=%s", to_email, subject)
        logger.info("[DRY-RUN] 本文:\n%s", body_html)


# ---------------------------------------------------------------------------
# 緊急地震速報フィード取得
# ---------------------------------------------------------------------------

class EarthquakeEEWClient:
    """緊急地震速報フィードから最新イベントを取得するクライアント。"""

    def __init__(self, api_url: str):
        self.api_url = api_url

    def fetch_latest(self):
        resp = requests.get(self.api_url, timeout=10)
        resp.raise_for_status()
        events = []
        for raw in resp.json():
            event = parse_p2pquake_eew(raw)
            if event is not None:
                events.append(event)
        return events


# ---------------------------------------------------------------------------
# 永続化（SQLite）
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    triggered_areas TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS response_tokens (
    token TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL,
    staff_id TEXT NOT NULL,
    staff_name TEXT NOT NULL,
    staff_email TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    staff_id TEXT NOT NULL,
    staff_name TEXT NOT NULL,
    safety_status TEXT NOT NULL,
    location TEXT NOT NULL,
    can_attend TEXT NOT NULL,
    responded_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def alert_exists_for_event(self, event_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM alerts WHERE event_id = ?", (event_id,)).fetchone()
            return row is not None

    def create_alert(self, event_id: str, triggered_areas) -> str:
        alert_id = secrets.token_hex(8)
        now = datetime.now(timezone.utc).isoformat()
        areas_json = json.dumps(
            [{"prefecture": a.prefecture, "max_intensity": a.max_intensity} for a in triggered_areas],
            ensure_ascii=False,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO alerts (alert_id, event_id, created_at, triggered_areas) VALUES (?, ?, ?, ?)",
                (alert_id, event_id, now, areas_json),
            )
        return alert_id

    def create_response_token(self, alert_id: str, staff: StaffMember) -> str:
        token = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO response_tokens "
                "(token, alert_id, staff_id, staff_name, staff_email, used, created_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (token, alert_id, staff.id, staff.name, staff.email, now),
            )
        return token

    def get_token(self, token: str):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM response_tokens WHERE token = ?", (token,)).fetchone()

    def mark_token_used(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE response_tokens SET used = 1 WHERE token = ?", (token,))

    def record_response(self, alert_id, staff_id, staff_name, safety_status, location, can_attend) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO responses "
                "(alert_id, staff_id, staff_name, safety_status, location, can_attend, responded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (alert_id, staff_id, staff_name, safety_status, location, can_attend, now),
            )

    def list_responses(self, alert_id: str):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM responses WHERE alert_id = ? ORDER BY responded_at", (alert_id,)
            ).fetchall()

    def list_tokens(self, alert_id: str):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM response_tokens WHERE alert_id = ?", (alert_id,)).fetchall()


# ---------------------------------------------------------------------------
# アラート業務ロジック
# ---------------------------------------------------------------------------

class AlertService:
    def __init__(self, config: Config, store: Store, notifier: GraphNotifier):
        self.config = config
        self.store = store
        self.notifier = notifier

    def check_and_dispatch(self, events) -> Optional[str]:
        """新規イベントをチェックし、トリガー条件を満たせばアラートを発行する。

        発行した場合はalert_idを返す。既に処理済みのイベント、または
        条件を満たさないイベントのみの場合はNoneを返す。
        """
        for event in events:
            if self.store.alert_exists_for_event(event.event_id):
                continue
            triggered = judge_trigger(event, self.config.target_prefectures, self.config.intensity_threshold)
            if not triggered:
                continue
            alert_id = self.store.create_alert(event.event_id, triggered)
            self._dispatch_staff_notifications(alert_id, triggered)
            return alert_id
        return None

    def _dispatch_staff_notifications(self, alert_id: str, triggered_areas) -> None:
        areas_text = "、".join(f"{a.prefecture}（震度{a.max_intensity}）" for a in triggered_areas)
        subject = "【緊急】安否確認のお願い（緊急地震速報）"
        for staff in self.config.staff:
            token = self.store.create_response_token(alert_id, staff)
            link = f"{self.config.response_base_url}/respond/{token}"
            body = (
                f"<p>{staff.name} 様</p>"
                f"<p>緊急地震速報を検知しました。対象地域: {areas_text}</p>"
                f"<p>下記リンクより、安否状況を回答してください。</p>"
                f'<p><a href="{link}">安否確認フォームを開く</a></p>'
            )
            self.notifier.send_mail(staff.email, subject, body)

    def submit_response(self, token: str, safety_status: str, location: str, can_attend: str) -> None:
        row = self.store.get_token(token)
        if row is None:
            raise ValueError("invalid token")
        if row["used"]:
            raise ValueError("token already used")
        self.store.record_response(
            row["alert_id"], row["staff_id"], row["staff_name"], safety_status, location, can_attend
        )
        self.store.mark_token_used(token)
        self._notify_supervisors(row["staff_name"], safety_status, location, can_attend)

    def _notify_supervisors(self, staff_name, safety_status, location, can_attend) -> None:
        subject = f"【安否確認回答】{staff_name} さんから回答がありました"
        body = (
            f"<p>{staff_name} さんから安否確認の回答がありました。</p>"
            "<ul>"
            f"<li>安否: {safety_status}</li>"
            f"<li>場所: {location}</li>"
            f"<li>出社可否: {can_attend}</li>"
            "</ul>"
        )
        for supervisor in self.config.supervisors:
            self.notifier.send_mail(supervisor.email, subject, body)


# ---------------------------------------------------------------------------
# Web UI（回答フォーム・ダッシュボード）
# ---------------------------------------------------------------------------

RESPOND_FORM_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><title>安否確認</title>
<style>
body{font-family:sans-serif;max-width:480px;margin:2em auto;padding:0 1em;}
fieldset{margin-bottom:1.5em;border:1px solid #ccc;border-radius:8px;}
legend{font-weight:bold;padding:0 .5em;}
label{display:block;padding:.75em 1em;margin:.4em 0;border:2px solid #888;border-radius:8px;cursor:pointer;}
input[type=radio]{margin-right:.5em;}
button{width:100%;padding:1em;font-size:1.1em;background:#c0392b;color:#fff;border:none;border-radius:8px;}
</style>
</head>
<body>
<h1>安否確認</h1>
<p>{{ staff_name }} 様</p>
<form method="post" action="{{ action_url }}">
  <fieldset>
    <legend>1. 安否</legend>
    <label><input type="radio" name="safety_status" value="無事" required> 無事</label>
    <label><input type="radio" name="safety_status" value="被災"> 被災</label>
  </fieldset>
  <fieldset>
    <legend>2. 場所</legend>
    <label><input type="radio" name="location" value="職場" required> 職場</label>
    <label><input type="radio" name="location" value="自宅"> 自宅</label>
  </fieldset>
  <fieldset>
    <legend>3. 出社可否</legend>
    <label><input type="radio" name="can_attend" value="出社可能" required> 出社可能</label>
    <label><input type="radio" name="can_attend" value="出社不可能"> 出社不可能</label>
  </fieldset>
  <button type="submit">送信して上司に通知</button>
</form>
</body>
</html>
"""

DONE_TEMPLATE = """
<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>送信完了</title></head>
<body><h1>回答を受け付けました</h1><p>ご回答ありがとうございました。上司へ通知しました。</p></body></html>
"""

ALREADY_RESPONDED_TEMPLATE = """
<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>送信済み</title></head>
<body><h1>この回答は既に送信済みです</h1></body></html>
"""

DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><title>安否確認ダッシュボード</title>
<style>
body{font-family:sans-serif;margin:2em;}
table{border-collapse:collapse;width:100%;}
th,td{border:1px solid #ccc;padding:.5em 1em;text-align:left;}
.pending{color:#c0392b;font-weight:bold;}
.done{color:#27ae60;}
</style>
</head>
<body>
<h1>安否確認ダッシュボード（alert: {{ alert_id }}）</h1>
<table>
<tr><th>氏名</th><th>状態</th><th>安否</th><th>場所</th><th>出社可否</th></tr>
{% for row in rows %}
<tr>
  <td>{{ row.name }}</td>
  <td>{% if row.responded %}<span class="done">回答済み</span>{% else %}<span class="pending">未回答</span>{% endif %}</td>
  <td>{{ row.safety_status }}</td>
  <td>{{ row.location }}</td>
  <td>{{ row.can_attend }}</td>
</tr>
{% endfor %}
</table>
</body>
</html>
"""


def build_notifier(config: Config) -> "GraphNotifier | LoggingNotifier":
    if config.dry_run:
        logger.warning("dry_run が有効です。メールは送信されず、ログに出力されるだけです。")
        return LoggingNotifier()
    return GraphNotifier(config.tenant_id, config.client_id, config.client_secret, config.sender_upn)


def create_app(config: Config, store: Optional[Store] = None, notifier=None) -> Flask:
    app = Flask(__name__)
    store = store or Store(config.database_path)
    notifier = notifier or build_notifier(config)
    service = AlertService(config, store, notifier)

    app.config["ALERT_SERVICE"] = service
    app.config["STORE"] = store

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/internal/check")
    def internal_check():
        quake_client = EarthquakeEEWClient(config.quake_api_url)
        events = quake_client.fetch_latest()
        alert_id = service.check_and_dispatch(events)
        return {"alert_id": alert_id}

    @app.post("/internal/test-trigger")
    def internal_test_trigger():
        """本物の地震を待たずに、トリガー〜18名通知の流れを手動で試すためのエンドポイント。

        本番運用では想定していない検証用の入口であり、外部公開しないこと。
        """
        payload = request.get_json(silent=True) or {}
        prefecture = payload.get("prefecture") or config.target_prefectures[0]
        intensity = payload.get("intensity") or config.intensity_threshold
        event = EEWEvent(
            event_id=f"test-{secrets.token_hex(4)}",
            reported_at=datetime.now(timezone.utc).isoformat(),
            areas=[AreaIntensity(prefecture=prefecture, max_intensity=intensity)],
        )
        alert_id = service.check_and_dispatch([event])
        return {"alert_id": alert_id, "prefecture": prefecture, "intensity": intensity}

    @app.get("/respond/<token>")
    def respond_form(token):
        row = store.get_token(token)
        if row is None:
            abort(404)
        if row["used"]:
            return render_template_string(ALREADY_RESPONDED_TEMPLATE)
        return render_template_string(
            RESPOND_FORM_TEMPLATE,
            staff_name=row["staff_name"],
            action_url=url_for("respond_submit", token=token),
        )

    @app.post("/respond/<token>")
    def respond_submit(token):
        safety_status = request.form.get("safety_status")
        location = request.form.get("location")
        can_attend = request.form.get("can_attend")
        if not (safety_status and location and can_attend):
            abort(400)
        try:
            service.submit_response(token, safety_status, location, can_attend)
        except ValueError as exc:
            abort(404 if str(exc) == "invalid token" else 409)
        return render_template_string(DONE_TEMPLATE)

    @app.get("/dashboard/<alert_id>")
    def dashboard(alert_id):
        tokens = store.list_tokens(alert_id)
        responses = {r["staff_id"]: r for r in store.list_responses(alert_id)}
        rows = []
        for t in tokens:
            r = responses.get(t["staff_id"])
            rows.append(
                {
                    "name": t["staff_name"],
                    "responded": r is not None,
                    "safety_status": r["safety_status"] if r else "-",
                    "location": r["location"] if r else "-",
                    "can_attend": r["can_attend"] if r else "-",
                }
            )
        return render_template_string(DASHBOARD_TEMPLATE, rows=rows, alert_id=alert_id)

    return app


# ---------------------------------------------------------------------------
# ポーリング（緊急地震速報フィードの定期監視）
# ---------------------------------------------------------------------------

def poll_forever(config: Config, store: Store, notifier: GraphNotifier, stop_event: Optional[threading.Event] = None) -> None:
    service = AlertService(config, store, notifier)
    quake_client = EarthquakeEEWClient(config.quake_api_url)
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            events = quake_client.fetch_latest()
            alert_id = service.check_and_dispatch(events)
            if alert_id:
                logger.info("Alert dispatched: %s", alert_id)
        except Exception:
            logger.exception("Error while polling earthquake feed")
        stop_event.wait(config.poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="緊急連絡ツール（安否確認自動送信）")
    parser.add_argument("--config", default="config.json", help="設定ファイルパス")
    parser.add_argument("--mode", choices=["web", "poll"], default="web", help="実行モード")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    config = Config.load(args.config)
    store = Store(config.database_path)
    notifier = build_notifier(config)

    if args.mode == "poll":
        poll_forever(config, store, notifier)
    else:
        app = create_app(config, store=store, notifier=notifier)
        threading.Thread(target=poll_forever, args=(config, store, notifier), daemon=True).start()
        app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
