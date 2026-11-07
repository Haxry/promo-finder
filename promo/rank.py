"""Rank the promos: critic quality first, then a few clear tie-breaks, and an LLM reason for the top ones.

Order = sort by:
  1. quality_4 (critic, 0-4)  - a lower-quality clip is never placed above a higher one
  2. clean opening before a weak cold open
  3. not a spoiler before a spoiler
  4. the LLM's order inside small groups (it also writes "why post it here")
  5. earlier episodes first (new viewers start at episode 1)
Then: duplicates removed (same moment twice), at most 3 of one story pattern in the top 10, and at least 2 stitched
promos in the top 20 when they are good enough - both done by swapping promos of the SAME quality only.
"""
import json, os
from . import prompts


def quality(p):
    return -1 if p.get("quality_4") is None else p["quality_4"]


# ---- duplicates -------------------------------------------------------------------------------------------------
def duplicate_reason(p, q):
    """Why p repeats q (None if it doesn't)."""
    if p["hook"] == q["hook"] and p["cliffhanger"] == q["cliffhanger"]: return "same hook and cliffhanger"
    if (p.get("cliff_ref") and p["cliff_ref"] == q.get("hook_ref")) or (q.get("cliff_ref") and q["cliff_ref"] == p.get("hook_ref")):
        return "one clip's cliffhanger line is the other's hook line"
    for x in p["segments"]:
        for y in q["segments"]:
            if x["episode"] != y["episode"]: continue
            overlap = min(x["end_s"], y["end_s"]) - max(x["start_s"], y["start_s"])
            shorter = max(1e-6, min(x["end_s"] - x["start_s"], y["end_s"] - y["start_s"]))
            if overlap / shorter > 0.5: return "time overlap > 50%"
            if x.get("scene") is not None and x["scene"] == y.get("scene") and overlap / shorter > 0.25: return "same scene, overlap > 25%"
            if 0 <= -overlap < 3.0: return f"back to back (gap {-overlap:.1f}s)"
    return None


def remove_duplicates(promos):
    """Best first; a promo that repeats a better one is dropped (gets dup_of + dup_reason)."""
    kept, dropped = [], []
    for p in promos:
        hit = next(((q, r) for q in kept if (r := duplicate_reason(p, q))), None)
        if hit: p["dup_of"], p["dup_reason"] = hit[0]["id"], hit[1]; dropped.append(p)
        else: kept.append(p)
    return kept, dropped


# ---- order ------------------------------------------------------------------------------------------------------
def sort_key(p, llm_pos=None):
    return (-quality(p), bool(p.get("weak_cold_open")), bool(p.get("spoiler")), (llm_pos or {}).get(p["id"], 999),
            p["episode"] > 5, p["episode"], p["id"])


def spread_episodes(order):
    """Inside each quality level, don't put several clips of one episode next to each other: take one per episode first."""
    out = []
    for q in sorted({quality(p) for p in order}, reverse=True):
        level, seen, later = [p for p in order if quality(p) == q], set(), []
        for p in level:
            (later if p["episode"] in seen else out).append(p); seen.add(p["episode"])
        out += later
    return out


def limit_patterns(order, cap, top=10):
    """At most `cap` promos of one story pattern in the top 10 (swap with the next promo of the same quality)."""
    out, count, i = list(order), {}, 0
    while i < min(top, len(out)):
        p, pat = out[i], out[i].get("pattern") or "other"
        if pat != "other" and count.get(pat, 0) >= cap:
            j = next((j for j in range(i + 1, len(out)) if quality(out[j]) == quality(p)
                      and ((out[j].get("pattern") or "other") == "other" or count.get(out[j].get("pattern"), 0) < cap)), None)
            if j is not None: out.insert(i, out.pop(j)); continue
        count[pat] = count.get(pat, 0) + 1; i += 1
    return out


def keep_stitched(order, n, min_q, top=20):
    """Make sure n stitched (B/C) promos with quality >= min_q are in the top 20 (swap with a type A of the same quality)."""
    out = list(order)
    good = [p for p in out if p.get("type") in ("B", "C") and quality(p) >= min_q]
    while len(good) >= n and sum(p.get("type") in ("B", "C") for p in out[:top]) < n:
        below = next((i for i in range(top, len(out)) if out[i] in good), None)
        if below is None: break
        swap = next((i for i in range(min(top, len(out)) - 1, -1, -1)
                     if out[i].get("type", "A") == "A" and quality(out[i]) == quality(out[below])), None)
        if swap is None: good.remove(out[below]); continue
        out[swap], out[below] = out[below], out[swap]
    return out


# ---- the LLM's "post first because ..." -----------------------------------------------------------------------
def card(p):
    return json.dumps({"id": p["id"], "clip": " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in p["segments"]),
                       "length_s": p["length_s"], "hook": p["hook"], "cliffhanger": p["cliffhanger"], "pattern": p.get("pattern"),
                       "spoiler": p.get("spoiler"), "qa_failed": [k for k, v in (p.get("checks") or {}).items() if not v["pass"]]},
                      ensure_ascii=False)


def llm_order(llm, order, top_n, cache_path, group=5):
    """The top promos, in groups of <= 5 of the same quality: the LLM orders each group and says why. Cached."""
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    positions, reasons, calls = {}, {}, 0
    head = order[:top_n]
    for q in sorted({quality(p) for p in head}, reverse=True):
        level = [p for p in head if quality(p) == q]
        for k in range(0, len(level), group):
            g = level[k:k + group]
            key = prompts.CRITIC_VERSION + "|" + ",".join(p["id"] for p in g)
            if key not in cache:
                if llm is None or len(g) == 1:
                    cache[key] = [{"id": p["id"], "reason": ""} for p in g]
                else:
                    try:
                        ans = llm.ask_json(prompts.RANK, "CANDIDATES:\n" + "\n".join(card(p) for p in g), expect="order")["order"]
                    except Exception as e:                        # no key / quota: keep the code's order for this group
                        print(f"ranking call failed, keeping the code's order: {str(e)[:120]}")
                        for pos, p in enumerate(g): positions[p["id"]], reasons[p["id"]] = len(positions) + pos, ""
                        continue
                    ids = {p["id"] for p in g}
                    picked = [a for a in ans if isinstance(a, dict) and a.get("id") in ids]
                    cache[key] = picked + [{"id": i, "reason": ""} for i in ids - {a["id"] for a in picked}]
                    calls += 1
            for pos, a in enumerate(cache[key]):
                positions[a["id"]], reasons[a["id"]] = len(positions) + pos, a.get("reason", "")
    json.dump(cache, open(cache_path, "w"), indent=1, ensure_ascii=False)
    return positions, reasons, calls


def rank(promos, cfg, llm=None, cache_path=None):
    """-> (final ranked list, dropped duplicates, number of LLM ranking calls)."""
    r = cfg["rank"]
    pool = sorted((p for p in promos if quality(p) < 0 or quality(p) >= r["min_quality"]), key=sort_key)
    kept, dups = remove_duplicates(pool)
    order = spread_episodes(sorted(kept, key=sort_key))
    calls = 0
    if cache_path:
        positions, reasons, calls = llm_order(llm, order, r["ranked_by_llm"], cache_path)
        for p in order: p["post_reason"] = reasons.get(p["id"], "")
        order = spread_episodes(sorted(order, key=lambda p: sort_key(p, positions)))
    order = keep_stitched(limit_patterns(order, r["max_per_pattern"]), r["min_stitched"], 3)
    for i, p in enumerate(order): p["rank"] = i + 1
    return order, dups, calls
