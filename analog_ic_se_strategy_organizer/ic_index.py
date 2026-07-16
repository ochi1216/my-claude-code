# -*- coding: utf-8 -*-
"""製品ケースインデックス構築モジュール（rtocs_organizer/rtocs_index.py と同型）。

data/product_lake/*.json（1製品=1ファイル、metadata/classifiers/content の3層構造。
DESIGN_analog_ic_se_strategy_organizer.md 4章参照）を走査し、1製品=1コンパクトレコードの
data/ic_index.json を増分構築する。ダッシュボードの一覧・検索タブ、
ポートフォリオ俯瞰タブの共通データ基盤になる。
"""

import os
import glob
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.path.join(BASE_DIR, "data")

OVERVIEW_MAX_CHARS = 120


def _record_from_json(data, source_file, source_mtime):
    """product_lakeの1ファイルからコンパクトレコードを作る"""
    meta = data.get("metadata", {})
    classifiers = data.get("classifiers", {})
    content = data.get("content", {})

    stage0 = content.get("stage0_product", {}) if isinstance(content, dict) else {}
    short_description = str(stage0.get("short_description", "") or "") if isinstance(stage0, dict) else ""

    applications = classifiers.get("applications_short", [])
    if not isinstance(applications, list):
        applications = [str(applications)]
    regions = classifiers.get("regions_covered", [])
    if not isinstance(regions, list):
        regions = [str(regions)]

    stage_status = meta.get("stage_status", {})
    if not isinstance(stage_status, dict):
        stage_status = {}

    return {
        "part_number": str(meta.get("part_number", "")),
        "manufacturer": str(meta.get("manufacturer", "Texas Instruments")),
        "analyzed_at": str(meta.get("analyzed_at", "")),
        "category": classifiers.get("category", "generic_analog_ic"),
        "category_confirmed_by_user": bool(classifiers.get("category_confirmed_by_user", False)),
        "applications": applications,
        "regions_covered": regions,
        "top_priority_kpi": str(classifiers.get("top_priority_kpi", "") or ""),
        "short_description": short_description[:OVERVIEW_MAX_CHARS],
        "stage_status": stage_status,
        "source_file": os.path.basename(source_file),
        "source_mtime": source_mtime,
    }


def build_index(data_dir=None, force=False):
    """インデックスを増分構築して保存し、インデックス全体(dict)を返す。

    - 既存インデックスの source_file+source_mtime と突合し、新規/更新ファイルのみ再パースする
    - product_lakeから消えたファイルのレコードは除去する
    - force=True で全件再パース
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    lake_dir = os.path.join(data_dir, "product_lake")
    index_path = os.path.join(data_dir, "ic_index.json")

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

    for path in sorted(glob.glob(os.path.join(lake_dir, "*.json"))):
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

    records.sort(key=lambda r: r.get("analyzed_at", ""), reverse=True)
    index = {"built_at": datetime.now().isoformat(), "records": records}

    if changed or force or not os.path.exists(index_path):
        os.makedirs(data_dir, exist_ok=True)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
    else:
        # 変更なしなら既存のbuilt_atを維持（キャッシュのキーを安定させる）
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index["built_at"] = json.load(f).get("built_at", index["built_at"])
        except Exception:
            pass

    return index


def load_index(data_dir=None):
    """保存済みインデックスを読むだけ（無ければ構築する）"""
    data_dir = data_dir or DEFAULT_DATA_DIR
    index_path = os.path.join(data_dir, "ic_index.json")
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return build_index(data_dir=data_dir)


def compact_index_for_llm(records):
    """LLMプロンプト投入用のコンパクトなテキスト表現（1行=1製品）"""
    lines = []
    for r in records:
        apps = "/".join(r.get("applications", [])[:3])
        lines.append(
            f"[{r.get('part_number')}] {r.get('category')}｜{apps}｜{r.get('short_description')}"
        )
    return "\n".join(lines)


def load_full_case(part_number, data_dir=None):
    """part_numberに一致するproduct_lakeのフルJSONを返す（最新のanalyzed_atのもの）"""
    data_dir = data_dir or DEFAULT_DATA_DIR
    lake_dir = os.path.join(data_dir, "product_lake")
    if not os.path.isdir(lake_dir):
        return None
    candidates = []
    for name in os.listdir(lake_dir):
        if name.startswith(f"{part_number}_") and name.endswith(".json"):
            candidates.append(os.path.join(lake_dir, name))
    if not candidates:
        return None
    candidates.sort(reverse=True)  # ファイル名にyyyymmdd_HHMMSSを含むため文字列ソートで最新が先頭
    try:
        with open(candidates[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_product_case(result, data_dir=None):
    """IcPipeline.run_pipeline()の結果dictをproduct_lakeに保存し、保存先パスを返す"""
    data_dir = data_dir or DEFAULT_DATA_DIR
    lake_dir = os.path.join(data_dir, "product_lake")
    os.makedirs(lake_dir, exist_ok=True)

    part_number = result.get("metadata", {}).get("part_number", "UNKNOWN")
    safe_part = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(part_number))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(lake_dir, f"{safe_part}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return path
