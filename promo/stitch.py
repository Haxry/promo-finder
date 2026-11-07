"""Stitched promos (runs after the critic): join strong moments that are too far apart for one clip.
   type B = 2-3 moments of ONE episode (cut the dull middle)
   type C = moments from SEVERAL episodes (an early setup + a later escalation, or one character's arc)

Code picks the ingredients ("beats") from promos the critic already liked, shows each with the lines around it,
and the model joins them. The result goes through the same validator, critic and ranking as everything else.
Answers are cached in raw_llm/stitch_B_epNN.json and raw_llm/stitch_C_<mode>.json.
"""
import json, os, re
from . import prompts
from .parse import transcript, story_lines, is_continuation
from .validate import STAKES


# ---- beats: candidate moments, chosen by code -------------------------------------------------------------------
def beat(eps, n, idx, kind, score):
    e = eps[n].events[idx]
    return {"kind": kind, "episode": n, "line": f"L{idx}", "start": round(e.start, 1), "end": round(e.end, 1),
            "text": e.text, "score": score}


def best(beats, k, per_episode):
    """The k best beats, at most `per_episode` from one episode, no duplicates."""
    out, seen, count = [], set(), {}
    for b in sorted(beats, key=lambda b: (-b["score"], b["episode"], b["start"])):
        key = (b["episode"], b["line"])
        if key in seen or count.get(b["episode"], 0) >= per_episode: continue
        seen.add(key); count[b["episode"]] = count.get(b["episode"], 0) + 1; out.append(b)
        if len(out) >= k: break
    return out


def hook_beats(promos, eps, k=30):
    return best([beat(eps, *p["hook_ref"], "hook", 10 * bool(p["quality_groups"]["hook"]) + (p["quality_4"] or 0))
                 for p in promos if p.get("checks")], k, 3)


def cliff_beats(promos, eps, k=30):
    return best([beat(eps, *p["cliff_ref"], "cliff", 10 * bool(p["quality_groups"]["ending"]) + (p["quality_4"] or 0))
                 for p in promos if p.get("checks")], k, 3)


def setup_beats(eps, names, k=20):
    """Short lines (2-8 s) that name a character AND the stakes, early episodes first."""
    low = {n.lower() for n in names}
    found = [beat(eps, n, i, "setup", (2 if n <= 5 else 0) - n / 100)
             for n in sorted(eps) for i, e in enumerate(eps[n].events)
             if e.kind == "dialogue" and 2.0 <= e.end - e.start <= 8.0 and not is_continuation(e)
             and {w.lower() for w in re.findall(r"[A-Za-z']+", e.text)} & low and STAKES.search(e.text)]
    return best(found, k, 2)


def show_beats(eps, beats, title):
    """Each beat with ~4 lines before and after it (ids + times), so the model can build real segments."""
    rows = [f"{title}:"]
    for b in beats:
        ep = eps[b["episode"]]
        lines, e = story_lines(ep), ep.events[int(b["line"][1:])]
        i = next((k for k, x in enumerate(lines) if x.start >= e.start - 0.01), len(lines) - 1)   # nearest story line
        lo, hi = lines[max(0, i - 4)], lines[min(len(lines) - 1, i + 4)]
        around = transcript(ep, lo.start - 0.01, hi.end + 0.01, secs=True)
        rows.append(f"- [{b['kind']}] episode {b['episode']} {b['line']} [{b['start']}s-{b['end']}s]: {b['text'][:110]}\n"
                    + "\n".join("    " + l for l in around.splitlines()))
    return "\n".join(rows)


# ---- the LLM calls (cached) --------------------------------------------------------------------------------------
def cached(path, make):
    """Return the cached answer for this stitch version, or call make() and cache it. -> (proposals, called_llm)"""
    if os.path.exists(path):
        d = json.load(open(path))
        if d.get("version") == prompts.STITCH_VERSION: return d["proposals"], False
    props = [p for p in make().get("promos", []) if isinstance(p, dict)]
    json.dump({"version": prompts.STITCH_VERSION, "proposals": props}, open(path, "w"), indent=1, ensure_ascii=False)
    return props, True


def b_episodes(eps, hooks, cliffs):
    """Episodes whose best hook and best cliffhanger are > 60 s apart, or have >= 6 s of dead time between them."""
    out = []
    for n in sorted({b["episode"] for b in hooks} & {b["episode"] for b in cliffs}):
        h = next(b for b in hooks if b["episode"] == n)
        later = [c for c in cliffs if c["episode"] == n and c["start"] > h["end"]]
        if not later: continue
        talk = [e for e in eps[n].events if e.kind == "dialogue" and h["start"] <= e.start <= later[0]["end"]]
        dead = max((b.start - a.end for a, b in zip(talk, talk[1:])), default=0)
        if later[0]["end"] - h["start"] > 60 or dead >= 6: out.append(n)
    return out


def stitch_b(llm, eps, n, hooks, cliffs, bible_text, folder):
    mine = lambda bs: [b for b in bs if b["episode"] == n]
    user = (f"STITCH B\nSHOW BIBLE\n{bible_text}\n\nEPISODE {n}\n" + show_beats(eps, mine(hooks), "HOOK MOMENTS") + "\n"
            + show_beats(eps, mine(cliffs), "CLIFFHANGER MOMENTS") + "\n\nTRANSCRIPT (times in seconds):\n"
            + transcript(eps[n], secs=True))
    return cached(os.path.join(folder, f"stitch_B_ep{n:02d}.json"), lambda: llm.ask_json(prompts.STITCH_B, user, expect="promos"))


def stitch_c(llm, eps, mode, hooks, cliffs, setups, bible_text, folder):
    if mode == "early_to_late":
        first, later = [b for b in setups + hooks if b["episode"] <= 10], [b for b in cliffs if b["episode"] > 5]
    else:
        first, later = setups + hooks, cliffs
    user = (f"STITCH C ({mode})\nSHOW BIBLE\n{bible_text}\n\n" + show_beats(eps, first, "OPENING BEATS (setup / hook)") + "\n\n"
            + show_beats(eps, later, "LATER BEATS (escalation / cliffhanger)"))
    system = prompts.STITCH_C.replace("{mode}", prompts.STITCH_C_MODES[mode])
    return cached(os.path.join(folder, f"stitch_C_{mode}.json"), lambda: llm.ask_json(system, user, expect="promos"))


def with_defaults(j, episode=None):
    """Stitch answers have no self-scores (display only): fill neutral ones; type B segments get their episode."""
    j = {"hook_strength": 3, "cliff_strength": 3, "standalone": 3, "missing_context": "none", **j}
    if episode is not None:
        j["segments"] = [dict(s, episode=s.get("episode", episode)) if isinstance(s, dict) else s for s in j.get("segments") or []]
    return j
