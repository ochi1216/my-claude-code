import os
import sqlite3
import datetime as dt
from typing import Dict, List, Optional, Tuple
import json

import pandas as pd
import streamlit as st

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import pickle

# ========= 設定 =========
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
DB_PATH = "yt_ranker.db"
TOKEN_PATH = "token_project2.pickle"
CLIENT_SECRET_FILE = "credentials_project2.json"  # Project2の認証ファイル名
LEARNED_JSON = "learned_channels.json"

TAGS = ["Keep", "Review", "Remove"]  # Tag候補


# ========= ユーティリティ =========
def parse_iso8601_duration_to_seconds(d: str) -> int:
    """YouTube contentDetails.duration (例: 'PT1M3S') を秒に変換"""
    if not d or not d.startswith("P"):
        return 0
    t = d
    hours = minutes = seconds = 0
    if "T" in t:
        t = t.split("T", 1)[1]
    num = ""
    for ch in t:
        if ch.isdigit():
            num += ch
        else:
            if not num:
                continue
            val = int(num)
            num = ""
            if ch == "H":
                hours = val
            elif ch == "M":
                minutes = val
            elif ch == "S":
                seconds = val
    return hours * 3600 + minutes * 60 + seconds


def utc_rfc3339_to_jst(rfc3339: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(rfc3339.replace("Z", "+00:00"))
    return t.astimezone(dt.timezone(dt.timedelta(hours=9)))


def jst_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))


def channel_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}"


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def load_learned_channels(json_path: str = LEARNED_JSON) -> Dict[str, str]:
    """
    learned_channels.json の "channels": { "チャンネル名": "S" ... } を読み込む。
    見つからない / エラー時は {}。
    """
    try:
        if not os.path.exists(json_path):
            return {}
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ch = data.get("channels", {})
        if isinstance(ch, dict):
            return {str(k): str(v) for k, v in ch.items()}
        return {}
    except Exception as e:
        print(f"[WARN] failed to load {json_path}: {e}")
        return {}


# ========= OAuth / API =========
def get_youtube_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(

                CLIENT_SECRET_FILE,  # ← ここを定数に
                SCOPES,
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)


# ========= DB =========
def db_init():
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
        CREATE TABLE IF NOT EXISTS channel_tags (
            channel_id TEXT PRIMARY KEY,
            tag TEXT NOT NULL
        )
        """
        )
        con.execute(
            """
        CREATE TABLE IF NOT EXISTS channel_metrics (
            channel_id TEXT NOT NULL,
            title TEXT NOT NULL,
            subscribers TEXT NOT NULL,
            last_upload_jst TEXT,
            period_days INTEGER NOT NULL,
            fetch_n INTEGER NOT NULL,
            expand_pages INTEGER NOT NULL,
            video_count INTEGER NOT NULL,
            shorts_count INTEGER NOT NULL,
            top_video_views INTEGER NOT NULL,
            top_video_url TEXT,
            top_shorts_views INTEGER NOT NULL,
            top_shorts_url TEXT,
            channel_url TEXT NOT NULL,
            computed_at_jst TEXT NOT NULL,
            PRIMARY KEY (channel_id, period_days, fetch_n, expand_pages)
        )
        """
        )


def db_get_tags() -> Dict[str, str]:
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("SELECT channel_id, tag FROM channel_tags").fetchall()
    return {cid: tag for cid, tag in rows}


def db_upsert_tag(channel_id: str, tag: str):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
        INSERT INTO channel_tags(channel_id, tag) VALUES(?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET tag=excluded.tag
        """,
            (channel_id, tag),
        )


def db_load_metrics(period_days: int, fetch_n: int, expand_pages: int) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query(
            """
        SELECT m.*, COALESCE(t.tag, 'Review') as tag
        FROM channel_metrics m
        LEFT JOIN channel_tags t ON t.channel_id = m.channel_id
        WHERE m.period_days=? AND m.fetch_n=? AND m.expand_pages=?
        """,
            con,
            params=(period_days, fetch_n, expand_pages),
        )
    return df


def db_save_metrics(df: pd.DataFrame, period_days: int, fetch_n: int, expand_pages: int):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
        DELETE FROM channel_metrics
        WHERE period_days=? AND fetch_n=? AND expand_pages=?
        """,
            (period_days, fetch_n, expand_pages),
        )
        df.to_sql("channel_metrics", con, if_exists="append", index=False)


# ========= API呼び出しラッパ（クォータ計測付き） =========
def chunked(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def list_subscriptions(service, quota: dict) -> List[Tuple[str, str]]:
    subs = []
    req = service.subscriptions().list(part="snippet", mine=True, maxResults=50)
    while req:
        quota["subscriptions_list"] = quota.get("subscriptions_list", 0) + 1
        res = req.execute()
        for it in res.get("items", []):
            ch_id = it["snippet"]["resourceId"]["channelId"]
            title = it["snippet"]["title"]
            subs.append((ch_id, title))
        req = service.subscriptions().list_next(req, res)
    return subs


def get_channels_info(service, channel_ids: List[str], quota: dict) -> Dict[str, dict]:
    info = {}
    for chunk in chunked(channel_ids, 50):
        quota["channels_list"] = quota.get("channels_list", 0) + 1
        res = service.channels().list(
            part="snippet,statistics,contentDetails",
            id=",".join(chunk),
            maxResults=50,
        ).execute()
        for it in res.get("items", []):
            cid = it["id"]
            info[cid] = it
    return info


def get_recent_upload_video_ids(
    service,
    uploads_playlist_id: str,
    fetch_n: int,
    cutoff_jst: dt.datetime,
    expand_pages: bool,
    max_pages: int,
    quota: dict,
) -> List[Tuple[str, dt.datetime]]:
    """
    returns: [(video_id, publishedAt_jst), ...]

    - expand_pages=False: 1ページ50件だけ取得
    - expand_pages=True : 最大 max_pages ページまで。最後の動画がcutoffより古ければ打ち切り。
    """
    results: List[Tuple[str, dt.datetime]] = []
    page = 0
    page_token: Optional[str] = None

    while True:
        page += 1
        max_results = 50

        try:
            quota["playlistItems_list"] = quota.get("playlistItems_list", 0) + 1
            res = (
                service.playlistItems()
                .list(
                    part="snippet,contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=max_results,
                    pageToken=page_token,
                )
                .execute()
            )
        except HttpError as e:
            if hasattr(e, "resp") and getattr(e.resp, "status", None) == 404:
                print(f"[WARN] uploads playlist not found: {uploads_playlist_id} (skipped)")
                return []
            raise

        items = res.get("items", [])
        if not items:
            break

        for it in items:
            vid = it["contentDetails"]["videoId"]
            published_jst = utc_rfc3339_to_jst(it["snippet"]["publishedAt"])
            results.append((vid, published_jst))

        if not expand_pages:
            break

        if page >= max_pages:
            break

        last_pub = utc_rfc3339_to_jst(items[-1]["snippet"]["publishedAt"])
        if last_pub < cutoff_jst:
            break

        page_token = res.get("nextPageToken")
        if not page_token:
            break

    return results


def get_videos_details(service, video_ids: List[str], quota: dict) -> Dict[str, dict]:
    details = {}
    for chunk in chunked(video_ids, 50):
        quota["videos_list"] = quota.get("videos_list", 0) + 1
        res = (
            service.videos()
            .list(
                part="snippet,statistics,contentDetails",
                id=",".join(chunk),
                maxResults=50,
            )
            .execute()
        )
        for it in res.get("items", []):
            details[it["id"]] = it
    return details


# ========= 指標計算 =========
def compute_metrics_for_channel(
    channel_id: str,
    channel_obj: dict,
    vids_with_pub: List[Tuple[str, dt.datetime]],
    video_details: Dict[str, dict],
    cutoff_jst: dt.datetime,
) -> dict:
    title = channel_obj["snippet"]["title"]

    stats = channel_obj.get("statistics", {})
    hidden = bool(stats.get("hiddenSubscriberCount", False))
    if hidden or ("subscriberCount" not in stats):
        subs = "N/A"
    else:
        subs = str(stats.get("subscriberCount", "N/A"))

    last_upload = None
    if vids_with_pub:
        last_upload = max(pub for _, pub in vids_with_pub)

    v_count = 0
    s_count = 0
    top_v_views = 0
    top_v_url = ""
    top_s_views = 0
    top_s_url = ""

    for vid, pub in vids_with_pub:
        if pub < cutoff_jst:
            continue
        det = video_details.get(vid)
        if not det:
            continue

        duration = det.get("contentDetails", {}).get("duration", "")
        sec = parse_iso8601_duration_to_seconds(duration)
        is_short = sec <= 60

        views = int(det.get("statistics", {}).get("viewCount", 0) or 0)

        if is_short:
            s_count += 1
            if views > top_s_views:
                top_s_views = views
                top_s_url = video_url(vid)
        else:
            v_count += 1
            if views > top_v_views:
                top_v_views = views
                top_v_url = video_url(vid)

    return {
        "channel_id": channel_id,
        "title": title,
        "subscribers": subs,
        "last_upload_jst": last_upload.isoformat() if last_upload else "",
        "video_count": v_count,
        "shorts_count": s_count,
        "top_video_views": top_v_views,
        "top_video_url": top_v_url,
        "top_shorts_views": top_s_views,
        "top_shorts_url": top_s_url,
        "channel_url": channel_url(channel_id),
    }


def refresh_all(
    period_days: int,
    fetch_n: int,
    expand_pages: bool,
    allowed_playlists: Optional[set] = None,
    progress_cb=None,
):
    """
    allowed_playlists:
        None  → 全チャンネル対象
        {"S","A"} など → learned_channels.json 上でそのPlaylistに属するチャンネルのみ対象
    """
    if progress_cb is None:
        progress_cb = lambda p, msg: None

    quota = {
        "subscriptions_list": 0,
        "channels_list": 0,
        "playlistItems_list": 0,
        "videos_list": 0,
    }

    service = get_youtube_service()

    progress_cb(0.0, "開始: YouTube API に接続しています...")
    subs = list_subscriptions(service, quota)  # [(channel_id, title), ...]
    learned_map = load_learned_channels()

    # Playlistによる事前フィルタ
    if allowed_playlists and len(allowed_playlists) > 0:
        filtered_subs = []
        for cid, title in subs:
            pl = learned_map.get(title, "N/A")
            if pl in allowed_playlists:
                filtered_subs.append((cid, title))
        subs = filtered_subs

    channel_ids = [cid for cid, _ in subs]
    total_channels = len(channel_ids)

    if total_channels == 0:
        progress_cb(1.0, "対象Playlistに属するチャンネルがありません。")
        df_empty = pd.DataFrame(
            columns=[
                "channel_id",
                "title",
                "subscribers",
                "last_upload_jst",
                "period_days",
                "fetch_n",
                "expand_pages",
                "video_count",
                "shorts_count",
                "top_video_views",
                "top_video_url",
                "top_shorts_views",
                "top_shorts_url",
                "channel_url",
                "computed_at_jst",
            ]
        )
        quota["total_units"] = (
            quota["subscriptions_list"]
            + quota["channels_list"]
            + quota["playlistItems_list"]
            + quota["videos_list"]
        )
        return df_empty, quota

    progress_cb(0.05, f"登録チャンネル取得完了: {total_channels} チャンネル")

    progress_cb(0.07, "チャンネル情報取得中...")
    ch_info = get_channels_info(service, channel_ids, quota)
    progress_cb(0.10, "チャンネル情報取得完了")

    now = jst_now()
    cutoff = now - dt.timedelta(days=period_days)

    rows = []
    all_video_ids = []
    per_channel_vids: Dict[str, List[Tuple[str, dt.datetime]]] = {}

    processed = 0
    for cid in channel_ids:
        obj = ch_info.get(cid)
        if not obj:
            per_channel_vids[cid] = []
        else:
            uploads_pl = (
                obj.get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads")
            )
            if not uploads_pl:
                per_channel_vids[cid] = []
            else:
                vids_pub = get_recent_upload_video_ids(
                    service=service,
                    uploads_playlist_id=uploads_pl,
                    fetch_n=fetch_n,
                    cutoff_jst=cutoff,
                    expand_pages=expand_pages,
                    max_pages=4,
                    quota=quota,
                )
                per_channel_vids[cid] = vids_pub
                all_video_ids.extend([vid for vid, _ in vids_pub])

        processed += 1
        progress_cb(
            0.1 + 0.6 * processed / max(total_channels, 1),
            f"アップロード動画取得中... {processed}/{total_channels}",
        )

    progress_cb(0.70, "動画詳細情報取得中...")
    video_details = get_videos_details(
        service, list(dict.fromkeys(all_video_ids)), quota
    )
    progress_cb(0.85, "動画詳細情報取得完了")

    progress_cb(0.90, "指標計算中...")
    for cid in channel_ids:
        obj = ch_info.get(cid)
        if not obj:
            continue
        m = compute_metrics_for_channel(
            channel_id=cid,
            channel_obj=obj,
            vids_with_pub=per_channel_vids.get(cid, []),
            video_details=video_details,
            cutoff_jst=cutoff,
        )
        m.update(
            {
                "period_days": period_days,
                "fetch_n": fetch_n,
                "expand_pages": 1 if expand_pages else 0,
                "computed_at_jst": now.isoformat(),
            }
        )
        rows.append(m)

    df = pd.DataFrame(rows)
    df = df[
        [
            "channel_id",
            "title",
            "subscribers",
            "last_upload_jst",
            "period_days",
            "fetch_n",
            "expand_pages",
            "video_count",
            "shorts_count",
            "top_video_views",
            "top_video_url",
            "top_shorts_views",
            "top_shorts_url",
            "channel_url",
            "computed_at_jst",
        ]
    ]

    total_units = (
        quota["subscriptions_list"]
        + quota["channels_list"]
        + quota["playlistItems_list"]
        + quota["videos_list"]
    )
    quota["total_units"] = total_units

    progress_cb(1.0, "完了しました。")
    return df, quota


# ========= Streamlit UI =========
def to_excel_bytes(df: pd.DataFrame) -> bytes:
    from io import BytesIO

    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Ranking")
    return bio.getvalue()


def main():
    st.set_page_config(page_title="YouTube Subscriptions Ranker", layout="wide")
    st.title("YouTube 登録チャンネル整理ツール（Rank / Tag / Export）")

    db_init()

    # サイドバー
    with st.sidebar:
        st.header("設定")
        period_days = st.radio("集計期間", options=[7, 30], index=0)
        fetch_n = st.radio("取得本数（最低限）", options=[3, 10], index=0)
        expand_pages = st.checkbox("追加ページ取得（期間をカバーするまで）", value=False)
        st.caption("※追加ページは上限4ページ（最大200件）で打ち切り")

        # learned_channels.json からPlaylist種別を取得（処理対象用）
        sidebar_learned = load_learned_channels()
        playlist_options_proc = sorted(set(sidebar_learned.values()))
        playlist_options_proc = ["All"] + playlist_options_proc

        selected_proc_playlists = st.multiselect(
            "処理対象Playlist（API取得対象）",
            options=playlist_options_proc,
            default=["All"],
            help="選択したPlaylistに属するチャンネルのみ、動画取得と集計を行います。Allで全チャンネル対象。",
        )
        if "All" in selected_proc_playlists or len(selected_proc_playlists) == 0:
            allowed_proc_playlists = None
        else:
            allowed_proc_playlists = set(selected_proc_playlists)

        if st.button("手動更新（API取得）", type="primary"):
            progress_bar = st.progress(0.0)
            status = st.empty()

            def progress_cb(p: float, msg: str):
                p_clamped = max(0.0, min(1.0, float(p)))
                progress_bar.progress(p_clamped)
                status.text(msg)

            with st.spinner("取得中...（登録数により時間がかかります）"):
                df_new, quota = refresh_all(
                    period_days,
                    fetch_n,
                    expand_pages,
                    allowed_playlists=allowed_proc_playlists,
                    progress_cb=progress_cb,
                )
                db_save_metrics(df_new, period_days, fetch_n, 1 if expand_pages else 0)

            st.success("更新完了")
            st.info(
                "今回の更新で使用した推定クォータ: "
                f"{quota.get('total_units', 0)} units\n\n"
                f"- subscriptions.list: {quota.get('subscriptions_list', 0)}\n"
                f"- channels.list: {quota.get('channels_list', 0)}\n"
                f"- playlistItems.list: {quota.get('playlistItems_list', 0)}\n"
                f"- videos.list: {quota.get('videos_list', 0)}"
            )

    df = db_load_metrics(period_days, fetch_n, 1 if expand_pages else 0)

    if df.empty:
        st.info("まだデータがありません。左の『手動更新（API取得）』を押してください。")
        return

    # subscribers_num 数値化（N/AはNaN）
    df["subscribers_num"] = pd.to_numeric(df["subscribers"], errors="coerce")
    # チャンネルURL → Open列用
    df["channel_link"] = df["channel_url"]

    # Playlist 情報を learned_channels.json から付与（表示・フィルタ用）
    learned_map = load_learned_channels()
    df["playlist"] = df["title"].map(lambda t: learned_map.get(t, "N/A"))

    # フィルタUI
    c1, c2 = st.columns([2, 2])
    with c1:
        keyword = st.text_input("キーワード検索（Channel名）", value="")
    with c2:
        tag_filter = st.multiselect(
            "Tagフィルタ", options=["All"] + TAGS, default=["All"]
        )

    playlist_values = sorted(df["playlist"].unique().tolist())
    playlist_filter = st.multiselect(
        "Playlistフィルタ（表示用）",
        options=["All"] + playlist_values,
        default=["All"],
    )

    # キーワードフィルタ
    if keyword.strip():
        df = df[df["title"].str.contains(keyword.strip(), case=False, na=False)]

    # Tagフィルタ
    if "All" not in tag_filter:
        df = df[df["tag"].isin(tag_filter)]

    # Playlistフィルタ（表示用）
    if "All" not in playlist_filter:
        df = df[df["playlist"].isin(playlist_filter)]

    # 並び替え（Rank用）
    sort_col = st.selectbox(
        "並び替え列（Rank算出用）",
        options=[
            "subscribers_num",
            "video_count",
            "shorts_count",
            "top_video_views",
            "top_shorts_views",
            "last_upload_jst",
        ],
        index=0,
        format_func=lambda x: {
            "subscribers_num": "Subscribers",
            "video_count": f"Videos ({period_days}d)",
            "shorts_count": f"Shorts ({period_days}d)",
            "top_video_views": f"Top Video Views ({period_days}d)",
            "top_shorts_views": f"Top Shorts Views ({period_days}d)",
            "last_upload_jst": "Last Upload (JST)",
        }.get(x, x),
    )
    asc = st.checkbox("昇順ソート（Rank算出）", value=False)

    if sort_col == "subscribers_num":
        sort_series = df["subscribers_num"].fillna(-1)
    else:
        sort_series = df[sort_col]

    df = df.assign(_sort_key=sort_series)
    df = df.sort_values(by="_sort_key", ascending=asc, kind="mergesort").drop(
        columns=["_sort_key"]
    )
    df = df.reset_index(drop=True)
    df["Rank"] = df.index + 1

    # 表示用DataFrame作成
    editable = df.copy()
    editable = editable.rename(
        columns={
            "playlist": "Playlist",
            "title": "Channel",
            "subscribers_num": "Subscribers",
            "last_upload_jst": "Last Upload (JST)",
            "video_count": f"Videos ({period_days}d)",
            "shorts_count": f"Shorts ({period_days}d)",
            "top_video_views": f"Top Video Views ({period_days}d)",
            "top_shorts_views": f"Top Shorts Views ({period_days}d)",
            "top_video_url": "Top Video URL",
            "top_shorts_url": "Top Shorts URL",
            "channel_link": "Open",
            "tag": "Tag",
        }
    )

    column_order = [
        "Playlist",
        "Channel",
        "Subscribers",
        "Last Upload (JST)",
        f"Videos ({period_days}d)",
        f"Shorts ({period_days}d)",
        f"Top Video Views ({period_days}d)",
        f"Top Shorts Views ({period_days}d)",
        "Open",
        "Tag",
        "Rank",
    ]

    st.subheader("チャンネル一覧（Tag編集可）")

    editable["Subscribers"] = pd.to_numeric(
        editable["Subscribers"], errors="coerce"
    )

    edited = st.data_editor(
        editable[
            [
                "channel_id",  # 非表示だがTag保存用
                *column_order,
            ]
        ],
        column_order=column_order,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        column_config={
            "channel_id": st.column_config.TextColumn(
                "channel_id", disabled=True
            ),
            "Playlist": st.column_config.TextColumn(
                "Playlist",
                help="learned_channels.json で分類されたプレイリスト（未登録は N/A）",
                disabled=True,
            ),
            "Channel": st.column_config.TextColumn("Channel", disabled=True),
            "Subscribers": st.column_config.NumberColumn(
                "Subscribers",
                format="%d",
                help="Channel subscriber count (hiddenの場合は空欄)",
                disabled=True,
            ),
            "Last Upload (JST)": st.column_config.TextColumn(
                "Last Upload (JST)", disabled=True
            ),
            f"Videos ({period_days}d)": st.column_config.NumberColumn(
                f"Videos ({period_days}d)", step=1, disabled=True
            ),
            f"Shorts ({period_days}d)": st.column_config.NumberColumn(
                f"Shorts ({period_days}d)", step=1, disabled=True
            ),
            f"Top Video Views ({period_days}d)": st.column_config.NumberColumn(
                f"Top Video Views ({period_days}d)", step=1, disabled=True
            ),
            f"Top Shorts Views ({period_days}d)": st.column_config.NumberColumn(
                f"Top Shorts Views ({period_days}d)", step=1, disabled=True
            ),
            "Top Video URL": st.column_config.LinkColumn(
                "Top Video URL",
                help="最も再生された動画（通常動画）",
            ),
            "Top Shorts URL": st.column_config.LinkColumn(
                "Top Shorts URL",
                help="最も再生されたShorts",
            ),
            "Open": st.column_config.LinkColumn(
                "Open",
                help="チャンネルページを開く",
                display_text="Open ▶",
            ),
            "Tag": st.column_config.SelectboxColumn(
                "Tag",
                options=TAGS,
                required=True,
            ),
            "Rank": st.column_config.NumberColumn(
                "Rank", step=1, disabled=True
            ),
        },
    )

    if st.button("Tagを保存"):
        for _, row in edited.iterrows():
            cid = row["channel_id"]
            tag_value = row["Tag"]
            if cid and tag_value:
                db_upsert_tag(cid, tag_value)
        st.success("Tagを保存しました")

    # Excelエクスポート（表示内容ベース）
    st.subheader("Excelエクスポート")
    export_df = edited[column_order]  # channel_idは含めない
    xbytes = to_excel_bytes(export_df)
    st.download_button(
        "Excelをダウンロード（.xlsx）",
        data=xbytes,
        file_name=f"youtube_rank_{period_days}d_n{fetch_n}_expand{int(expand_pages)}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
