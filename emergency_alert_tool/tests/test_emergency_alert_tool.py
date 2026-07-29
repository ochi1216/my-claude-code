"""emergency_alert_tool_20260729_01.py のテスト。

Microsoft Graph APIへの実際のネットワーク呼び出しは行わず、
GraphNotifierと同じインタフェースを持つFakeNotifierで代替する。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "emergency_alert_tool_20260729_01.py"
spec = importlib.util.spec_from_file_location("emergency_alert_tool_20260729_01", MODULE_PATH)
eat = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = eat
spec.loader.exec_module(eat)


TARGET_PREFECTURES = ["大分県", "大阪府", "東京都"]
THRESHOLD = "5弱"


class FakeNotifier:
    """GraphNotifierの代わりに送信内容を記録するテスト用ダブル。"""

    def __init__(self):
        self.sent = []  # list of (to_email, subject, body_html)

    def send_mail(self, to_email, subject, body_html):
        self.sent.append((to_email, subject, body_html))


def make_staff(n, prefix="staff"):
    return [
        eat.StaffMember(id=f"{prefix}{i:02d}", name=f"スタッフ{i:02d}", email=f"{prefix}{i:02d}@example.com")
        for i in range(1, n + 1)
    ]


def make_supervisors():
    return [
        eat.StaffMember(id="boss01", name="上司01", email="boss01@example.com"),
        eat.StaffMember(id="boss02", name="上司02", email="boss02@example.com"),
        eat.StaffMember(id="boss03", name="上司03", email="boss03@example.com"),
    ]


def make_config(tmp_path, poll_interval=30):
    return eat.Config(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        sender_upn="sender@example.com",
        target_prefectures=TARGET_PREFECTURES,
        intensity_threshold=THRESHOLD,
        quake_api_url="https://example.invalid/eew",
        poll_interval_seconds=poll_interval,
        response_base_url="http://localhost:5000",
        database_path=str(tmp_path / "test.db"),
        staff=make_staff(18),
        supervisors=make_supervisors(),
    )


# ---------------------------------------------------------------------------
# 震度判定ロジック
# ---------------------------------------------------------------------------

def test_intensity_scale_ordering():
    assert eat.intensity_index("1") < eat.intensity_index("5弱")
    assert eat.intensity_index("5弱") < eat.intensity_index("5強")
    assert eat.intensity_index("5強") < eat.intensity_index("6弱")
    assert eat.intensity_index("7") == len(eat.INTENSITY_SCALE) - 1


def test_meets_threshold():
    assert eat.meets_threshold("5弱", "5弱") is True
    assert eat.meets_threshold("6弱", "5弱") is True
    assert eat.meets_threshold("4", "5弱") is False
    assert eat.meets_threshold("unknown", "5弱") is False


def test_judge_trigger_matches_target_prefecture_and_threshold():
    event = eat.EEWEvent(
        event_id="ev1",
        reported_at="2026-07-29T00:00:00+09:00",
        areas=[
            eat.AreaIntensity(prefecture="大阪府", max_intensity="5弱"),
            eat.AreaIntensity(prefecture="千葉県", max_intensity="6強"),  # 対象外の都府県
            eat.AreaIntensity(prefecture="東京都", max_intensity="4"),  # 閾値未満
        ],
    )
    triggered = eat.judge_trigger(event, TARGET_PREFECTURES, THRESHOLD)
    assert len(triggered) == 1
    assert triggered[0].prefecture == "大阪府"
    assert triggered[0].max_intensity == "5弱"


def test_judge_trigger_no_match_returns_empty():
    event = eat.EEWEvent(
        event_id="ev2",
        reported_at="2026-07-29T00:00:00+09:00",
        areas=[
            eat.AreaIntensity(prefecture="大阪府", max_intensity="4"),
            eat.AreaIntensity(prefecture="千葉県", max_intensity="6強"),
        ],
    )
    assert eat.judge_trigger(event, TARGET_PREFECTURES, THRESHOLD) == []


def test_parse_p2pquake_eew_numeric_scale():
    raw = {
        "code": 556,
        "id": "20260729000001",
        "time": "2026/07/29 12:00:00",
        "areas": [
            {"pref": "大阪府", "scaleTo": 45},
            {"pref": "大分県", "scaleTo": 30},
        ],
    }
    event = eat.parse_p2pquake_eew(raw)
    assert event is not None
    assert event.event_id == "20260729000001"
    assert len(event.areas) == 2
    assert event.areas[0].prefecture == "大阪府"
    assert event.areas[0].max_intensity == "5弱"
    assert event.areas[1].max_intensity == "3"


def test_parse_p2pquake_eew_ignores_other_codes():
    assert eat.parse_p2pquake_eew({"code": 551, "areas": []}) is None


# ---------------------------------------------------------------------------
# AlertService: トリガー〜18名への通知
# ---------------------------------------------------------------------------

def test_check_and_dispatch_sends_mail_to_all_staff(tmp_path):
    config = make_config(tmp_path)
    store = eat.Store(config.database_path)
    notifier = FakeNotifier()
    service = eat.AlertService(config, store, notifier)

    event = eat.EEWEvent(
        event_id="ev-trigger",
        reported_at="2026-07-29T12:00:00+09:00",
        areas=[eat.AreaIntensity(prefecture="東京都", max_intensity="5強")],
    )

    alert_id = service.check_and_dispatch([event])

    assert alert_id is not None
    assert len(notifier.sent) == 18
    recipients = {sent[0] for sent in notifier.sent}
    assert recipients == {s.email for s in config.staff}
    # 回答リンクが本文に含まれること
    assert all(f"{config.response_base_url}/respond/" in body for _, _, body in notifier.sent)


def test_check_and_dispatch_ignores_non_triggering_event(tmp_path):
    config = make_config(tmp_path)
    store = eat.Store(config.database_path)
    notifier = FakeNotifier()
    service = eat.AlertService(config, store, notifier)

    event = eat.EEWEvent(
        event_id="ev-no-trigger",
        reported_at="2026-07-29T12:00:00+09:00",
        areas=[eat.AreaIntensity(prefecture="千葉県", max_intensity="6強")],
    )

    alert_id = service.check_and_dispatch([event])

    assert alert_id is None
    assert notifier.sent == []


def test_check_and_dispatch_is_idempotent_for_same_event(tmp_path):
    config = make_config(tmp_path)
    store = eat.Store(config.database_path)
    notifier = FakeNotifier()
    service = eat.AlertService(config, store, notifier)

    event = eat.EEWEvent(
        event_id="ev-dup",
        reported_at="2026-07-29T12:00:00+09:00",
        areas=[eat.AreaIntensity(prefecture="大分県", max_intensity="5弱")],
    )

    first = service.check_and_dispatch([event])
    second = service.check_and_dispatch([event])

    assert first is not None
    assert second is None
    assert len(notifier.sent) == 18  # 2回目では追加送信されない


# ---------------------------------------------------------------------------
# AlertService: 回答送信〜上司3名への即時通知
# ---------------------------------------------------------------------------

def test_submit_response_notifies_three_supervisors(tmp_path):
    config = make_config(tmp_path)
    store = eat.Store(config.database_path)
    notifier = FakeNotifier()
    service = eat.AlertService(config, store, notifier)

    event = eat.EEWEvent(
        event_id="ev-resp",
        reported_at="2026-07-29T12:00:00+09:00",
        areas=[eat.AreaIntensity(prefecture="大阪府", max_intensity="5弱")],
    )
    service.check_and_dispatch([event])
    notifier.sent.clear()  # 初回通知分はクリアし、回答通知のみを検証する

    tokens = store.list_tokens(store._connect().execute("SELECT alert_id FROM alerts").fetchone()["alert_id"])
    token = tokens[0]["token"]

    service.submit_response(token, "無事", "職場", "出社可能")

    assert len(notifier.sent) == 3
    recipients = {sent[0] for sent in notifier.sent}
    assert recipients == {s.email for s in config.supervisors}
    assert all("無事" in body and "職場" in body and "出社可能" in body for _, _, body in notifier.sent)


def test_submit_response_rejects_invalid_token(tmp_path):
    config = make_config(tmp_path)
    store = eat.Store(config.database_path)
    notifier = FakeNotifier()
    service = eat.AlertService(config, store, notifier)

    with pytest.raises(ValueError):
        service.submit_response("no-such-token", "無事", "職場", "出社可能")


def test_submit_response_rejects_reuse(tmp_path):
    config = make_config(tmp_path)
    store = eat.Store(config.database_path)
    notifier = FakeNotifier()
    service = eat.AlertService(config, store, notifier)

    event = eat.EEWEvent(
        event_id="ev-reuse",
        reported_at="2026-07-29T12:00:00+09:00",
        areas=[eat.AreaIntensity(prefecture="大阪府", max_intensity="5弱")],
    )
    service.check_and_dispatch([event])
    alert_id = store._connect().execute("SELECT alert_id FROM alerts").fetchone()["alert_id"]
    token = store.list_tokens(alert_id)[0]["token"]

    service.submit_response(token, "無事", "職場", "出社可能")
    with pytest.raises(ValueError):
        service.submit_response(token, "被災", "自宅", "出社不可能")


# ---------------------------------------------------------------------------
# Flask ルート
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client(tmp_path):
    config = make_config(tmp_path)
    store = eat.Store(config.database_path)
    notifier = FakeNotifier()
    app = eat.create_app(config, store=store, notifier=notifier)
    app.testing = True
    return app.test_client(), store, notifier, config


def _trigger_alert(store, notifier, config):
    service = eat.AlertService(config, store, notifier)
    event = eat.EEWEvent(
        event_id="ev-web",
        reported_at="2026-07-29T12:00:00+09:00",
        areas=[eat.AreaIntensity(prefecture="東京都", max_intensity="5弱")],
    )
    service.check_and_dispatch([event])
    notifier.sent.clear()
    alert_id = store._connect().execute("SELECT alert_id FROM alerts").fetchone()["alert_id"]
    return store.list_tokens(alert_id)[0]["token"]


def test_respond_form_renders_for_valid_token(app_client):
    client, store, notifier, config = app_client
    token = _trigger_alert(store, notifier, config)

    resp = client.get(f"/respond/{token}")

    assert resp.status_code == 200
    assert "無事".encode() in resp.data
    assert "被災".encode() in resp.data


def test_respond_form_404_for_unknown_token(app_client):
    client, store, notifier, config = app_client
    resp = client.get("/respond/unknown-token")
    assert resp.status_code == 404


def test_respond_submit_notifies_supervisors_and_blocks_reuse(app_client):
    client, store, notifier, config = app_client
    token = _trigger_alert(store, notifier, config)

    resp = client.post(
        f"/respond/{token}",
        data={"safety_status": "被災", "location": "自宅", "can_attend": "出社不可能"},
    )
    assert resp.status_code == 200
    assert len(notifier.sent) == 3
    assert all(
        "被災" in body and "自宅" in body and "出社不可能" in body for _, _, body in notifier.sent
    )

    # 2回目の送信はブロックされる
    resp2 = client.post(
        f"/respond/{token}",
        data={"safety_status": "無事", "location": "職場", "can_attend": "出社可能"},
    )
    assert resp2.status_code == 409
    assert len(notifier.sent) == 3  # 追加送信されない


def test_dashboard_shows_response_status(app_client):
    client, store, notifier, config = app_client
    token = _trigger_alert(store, notifier, config)
    alert_id = store._connect().execute("SELECT alert_id FROM alerts").fetchone()["alert_id"]

    client.post(
        f"/respond/{token}",
        data={"safety_status": "無事", "location": "職場", "can_attend": "出社可能"},
    )

    resp = client.get(f"/dashboard/{alert_id}")
    assert resp.status_code == 200
    assert "回答済み".encode() in resp.data
    assert "未回答".encode() in resp.data  # 他の17名は未回答
