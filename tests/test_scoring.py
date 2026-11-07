"""Critic scoring and ranking rules (promo/critic.py, promo/rank.py)."""
from promo.critic import CHECKS, score_promo, majority, cold_viewer_ok
from promo.rank import rank, duplicate_reason, limit_patterns

CFG = {"rank": {"min_quality": 2, "max_per_pattern": 3, "min_stitched": 2, "ranked_by_llm": 20}}
KEEP = {"conflict_between": "Juliana vs Gerald", "would_keep_watching": True}


def promo(**kw):
    p = {"id": "E1-1", "episode": 1, "type": "A", "hook": "h", "cliffhanger": "c", "hook_kind": "dialogue", "cliff_kind": "dialogue",
         "length_s": 30, "notes": "", "segments": [{"episode": 1, "start": "", "end": "", "start_s": 0, "end_s": 30, "scene": 1}]}
    return {**p, **kw}


def critic(fail=()):
    return {"checks": {c: {"pass": c not in fail, "reason": "r"} for c in CHECKS}, "pattern": "betrayal"}


def test_quality_4_counts_groups():
    assert score_promo(promo(), critic(), KEEP)["quality_4"] == 4
    assert score_promo(promo(), critic(["open_question_at_end", "cliff_in_rubric"]), KEEP)["quality_4"] == 3   # one group
    assert score_promo(promo(), critic(["nothing_resolves_after_cliff"]), KEEP)["quality_4"] == 4             # not counted
    p = score_promo(promo(), critic(["not_a_spoiler"]), KEEP)
    assert p["quality_4"] == 3 and p["spoiler"] is True


def test_cold_viewer_and_code_rules():
    assert not cold_viewer_ok({"conflict_between": "", "would_keep_watching": True})
    assert not cold_viewer_ok({"conflict_between": "a vs b", "would_keep_watching": False})
    assert score_promo(promo(), critic(), {"conflict_between": "a vs b", "would_keep_watching": False})["quality_4"] == 3
    react = score_promo(promo(hook="Her smug expression freezes.", hook_kind="action"), critic(), KEEP)
    assert react["quality_groups"]["hook"] is False and react["quality_4"] == 3
    assert score_promo(promo(weak_cold_open=True), critic(), KEEP)["quality_4"] == 3


def test_majority_vote():
    merged, agreement = majority([critic(), critic(["hook_in_rubric"]), critic(["hook_in_rubric"])])
    assert merged["checks"]["hook_in_rubric"]["pass"] is False and agreement < 1


def q(i, ep, quality, **kw):
    return promo(id=f"E{ep}-{i}", episode=ep, quality_4=quality, pattern=kw.pop("pattern", "betrayal"),
                 hook=f"h{ep}{i}", cliffhanger=f"c{ep}{i}", segments=[{"episode": ep, "start": "", "end": "", "start_s": i * 100,
                                                                     "end_s": i * 100 + 30, "scene": i}], **kw)


def test_rank_never_puts_lower_quality_above_higher():
    out, _, _ = rank([q(1, 10, 2), q(1, 11, 4), q(1, 12, 3), q(1, 13, 4, weak_cold_open=True)], CFG)
    assert [p["quality_4"] for p in out] == [4, 4, 3, 2] and out[1]["id"] == "E13-1"     # weak opening last in its tier


def test_duplicates():
    a = q(1, 1, 4); a["segments"] = [{"episode": 1, "start_s": 46.8, "end_s": 70.4, "scene": 1}]
    b = q(2, 1, 3); b["segments"] = [{"episode": 1, "start_s": 60.1, "end_s": 98.2, "scene": 1}]
    assert duplicate_reason(b, a) == "same scene, overlap > 25%"
    c, d = q(3, 2, 4, cliff_ref=[2, 40]), q(4, 2, 4, hook_ref=[2, 40])
    assert duplicate_reason(d, c) == "one clip's cliffhanger line is the other's hook line"
    out, dups, _ = rank([a, b], CFG)
    assert [p["id"] for p in out] == ["E1-1"] and dups[0]["dup_of"] == "E1-1"


def test_pattern_cap_only_swaps_within_a_quality():
    order = [q(i, 10 + i, 4, pattern="betrayal") for i in range(1, 6)] + [q(i, 30 + i, 4, pattern="rescue") for i in range(1, 6)]
    assert [p["pattern"] for p in limit_patterns(order, 3)[:6]].count("betrayal") == 3
