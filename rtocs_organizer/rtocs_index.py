# -*- coding: utf-8 -*-
"""RTOCSケースインデックス構築モジュール。

data/JSON_lake/*.json を走査し、1話=1コンパクトレコードの
data/rtocs_index.json を増分構築する。
このインデックスは傾向分析ダッシュボードと戦略パイプラインの
類似ケース検索（LLM-as-retriever）の共通基盤になる。
"""

import os
import glob
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.path.join(BASE_DIR, "data")

CONCLUSION_MAX_CHARS = 120


def _record_from_json(data, source_file, source_mtime):
    """JSON_lakeの1ファイルからコンパクトレコードを作る"""
    meta = data.get("metadata", {})
    classifiers = data.get("classifiers", {})
    content = data.get("content", data)  # 旧フラット構造への後方互換

    conclusion = str(content.get("conclusion", "") or "")
    keywords = classifiers.get("strategic_keywords", [])
    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    regions = classifiers.get("regions", [])
    if not isinstance(regions, list):
        regions = [str(regions)]

    return {
        "video_id": str(meta.get("video_id", "")),
        "episode": str(meta.get("episode_no", "")),
        "date": str(meta.get("broadcast_date", "")),
        "company": classifiers.get("company_name", "Unknown"),
        "sector": classifiers.get("industry_sector", "未分類"),
        "niche": classifiers.get("industry_niche", ""),
        "regions": regions,
        "keywords": keywords,
        "gist": str(content.get("gist", "") or ""),
        "conclusion_short": conclusion[:CONCLUSION_MAX_CHARS],
        "source_file": os.path.basename(source_file),
        "source_mtime": source_mtime,
    }


def build_index(data_dir=None, force=False):
    """インデックスを増分構築して保存し、インデックス全体(dict)を返す。

    - 既存インデックスの source_file+source_mtime と突合し、
      新規/更新ファイルのみ再パースする
    - JSON_lakeから消えたファイルのレコードは除去する
    - force=True で全件再パース
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    json_dir = os.path.join(data_dir, "JSON_lake")
    index_path = os.path.join(data_dir, "rtocs_index.json")

    existing = {}
    if not force and os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                for rec in json.load(f).get("records", []):
                    existing[rec.get("source_file", "")] = rec
        except Exception:
            existing = {}

    records = []
    changed = False
    seen_files = set()

    for path in sorted(glob.glob(os.path.join(json_dir, "*.json"))):
        name = os.path.basename(path)
        seen_files.add(name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue

        prev = existing.get(name)
        if prev and prev.get("source_mtime") == mtime:
            records.append(prev)
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            records.append(_record_from_json(data, path, mtime))
            changed = True
        except Exception:
            # 壊れたJSONはスキップ（インデックス全体は生かす）
            changed = True
            continue

    if set(existing.keys()) - seen_files:
        changed = True  # 削除されたファイルがある

    records.sort(key=lambda r: r.get("date", ""), reverse=True)
    index = {"built_at": datetime.now().isoformat(), "records": records}

    if changed or force or not os.path.exists(index_path):
        os.makedirs(data_dir, exist_ok=True)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
    else:
        # 変更なしなら既存のbuilt_atを維持（総評キャッシュのキーを安定させる）
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index["built_at"] = json.load(f).get("built_at", index["built_at"])
        except Exception:
            pass

    return index


def load_index(data_dir=None):
    """保存済みインデックスを読むだけ（無ければ構築する）"""
    data_dir = data_dir or DEFAULT_DATA_DIR
    index_path = os.path.join(data_dir, "rtocs_index.json")
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return build_index(data_dir=data_dir)


def compact_index_for_llm(records):
    """LLMプロンプト投入用のコンパクトなテキスト表現（1行=1ケース）"""
    lines = []
    for r in records:
        kw = "/".join(r.get("keywords", [])[:5])
        lines.append(
            f"[{r.get('video_id')}] #{r.get('episode')} {r.get('date')} "
            f"{r.get('company')}｜{r.get('sector')}｜{r.get('niche')}｜{kw}｜{r.get('gist')}"
        )
    return "\n".join(lines)


def load_full_case(video_id, data_dir=None):
    """video_idに一致するJSON_lakeのフルJSONを返す（戦略パイプラインのステージ5用）"""
    data_dir = data_dir or DEFAULT_DATA_DIR
    json_dir = os.path.join(data_dir, "JSON_lake")
    if not os.path.isdir(json_dir):
        return None
    for name in os.listdir(json_dir):
        if f"_{video_id}_" in name and name.endswith(".json"):
            try:
                with open(os.path.join(json_dir, name), "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
    return None
