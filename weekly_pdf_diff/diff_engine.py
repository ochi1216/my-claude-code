"""前週との対応付け・単語単位差分（IMPLEMENTATION_PLAN.md 4章）。

対応付けの優先順位:
  1. 正規化済みテキストの完全一致（同一セクション優先、なければWeekly全体 -> moved）
  2. 同一セクションパス内での類似度（RapidFuzz、閾値以上）
  3. 対応なし -> added
  4. 前週側で対応が取れなかったもの -> deleted
"""
from difflib import SequenceMatcher

from rapidfuzz import fuzz

from models import DiffResult, TextUnit

SIMILARITY_THRESHOLD = 82.0  # RapidFuzzは0-100スケール
WHOLE_UNIT_CHANGE_RATIO = 0.6  # 変更語の割合がこれを超えたら単語差分でなく全体を青太字化


def pair_units(prev_units: list[TextUnit], curr_units: list[TextUnit]) -> list[DiffResult]:
    results: list[DiffResult] = []
    matched_prev_ids: set[int] = set()

    prev_by_normalized: dict[str, list[TextUnit]] = {}
    for u in prev_units:
        prev_by_normalized.setdefault(u.normalized_text, []).append(u)

    for curr in curr_units:
        prev = _find_unmatched_exact(curr, prev_by_normalized, matched_prev_ids)
        if prev is not None:
            matched_prev_ids.add(id(prev))
            change_type = "unchanged" if prev.section_path == curr.section_path else "moved"
            results.append(DiffResult(curr, prev, change_type, 100.0, [], False))
            continue

        best, best_score = _best_same_section_match(curr, prev_units, matched_prev_ids)
        if best is not None and best_score >= SIMILARITY_THRESHOLD:
            matched_prev_ids.add(id(best))
            changed_words, whole_unit = _word_diff(best, curr)
            results.append(DiffResult(curr, best, "modified", best_score, changed_words, whole_unit))
            continue

        results.append(DiffResult(curr, None, "added", 0.0, [], True))

    for prev in prev_units:
        if id(prev) not in matched_prev_ids:
            results.append(DiffResult(None, prev, "deleted", 0.0, [], False))

    return results


def _find_unmatched_exact(
    curr: TextUnit,
    prev_by_normalized: dict[str, list[TextUnit]],
    matched_prev_ids: set[int],
) -> TextUnit | None:
    candidates = prev_by_normalized.get(curr.normalized_text)
    if not candidates:
        return None
    for cand in candidates:
        if id(cand) not in matched_prev_ids:
            return cand
    return None


def _best_same_section_match(
    curr: TextUnit,
    prev_units: list[TextUnit],
    matched_prev_ids: set[int],
) -> tuple[TextUnit | None, float]:
    best: TextUnit | None = None
    best_score = 0.0
    for cand in prev_units:
        if id(cand) in matched_prev_ids:
            continue
        if cand.section_path != curr.section_path:
            continue
        score = fuzz.ratio(curr.normalized_text, cand.normalized_text)
        if score > best_score:
            best_score = score
            best = cand
    return best, best_score


def _word_diff(prev: TextUnit, curr: TextUnit) -> tuple[list, bool]:
    if not curr.words:
        return [], False

    prev_tokens = [w.text for w in prev.words]
    curr_tokens = [w.text for w in curr.words]
    matcher = SequenceMatcher(a=prev_tokens, b=curr_tokens, autojunk=False)

    changed_indices: list[int] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            changed_indices.extend(range(j1, j2))

    change_ratio = len(changed_indices) / len(curr_tokens)
    if change_ratio > WHOLE_UNIT_CHANGE_RATIO:
        # 変更が大部分を占める場合は対応付けの信頼度が低いとみなし、
        # 単語単位でなく行アイテム全体を青太字化する（IMPLEMENTATION_PLAN.md 19章の方針）
        return [], True

    changed_words = [curr.words[i] for i in changed_indices]
    return changed_words, False
