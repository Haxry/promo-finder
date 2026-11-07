"""The independent critic: a different model checks every promo with yes/no questions, and a "cold viewer" (who
sees nothing but the clip) says whether a stranger would follow it and keep watching.

quality_4 (0-4) = how many of these GROUPS pass:
   hook      = hook_conflict_no_context AND hook_in_rubric
   ending    = open_question_at_end AND cliff_in_rubric
   standalone = standalone_understandable (+ cuts_make_sense for stitched clips) AND the cold viewer would keep watching
   not_a_spoiler
Code rules on top: a reaction shot (look/gasp/recoil) fails the hook or ending group, a weak cold open costs 1 point.
Answers are cached per clip in raw_llm/critic_*.json (keyed by the exact clip), so a re-run asks only for new clips.
"""
import hashlib, json, os, re
from concurrent.futures import ThreadPoolExecutor
from . import prompts
from .parse import transcript
from .validate import reaction_only

CHECKS = ["hook_conflict_no_context", "open_question_at_end", "nothing_resolves_after_cliff",
          "standalone_understandable", "not_a_spoiler", "hook_in_rubric", "cliff_in_rubric"]
VAGUE = re.compile(r"^\s*(|none|nothing|n/?a|unclear|unknown|not sure|can'?t tell|no idea|unsure)\s*\.?\s*$", re.I)


# ---- what the critic sees ---------------------------------------------------------------------------------------
def clip_text(eps, p, marks=False):
    """The clip's lines, segments joined by [cut] / [cut to episode N]. marks=True tags the [FIRST 3s] and [LAST LINE]."""
    parts = []
    for k, s in enumerate(p["segments"]):
        lines = transcript(eps[s["episode"]], s["start_s"], s["end_s"]).splitlines()
        if marks:
            for i, l in enumerate(lines):
                m = re.match(r"^L\d+ \[(\d+):([\d.]+)-", l)
                if k == 0 and m and int(m.group(1)) * 60 + float(m.group(2)) <= s["start_s"] + 3.0:
                    lines[i] = "[FIRST 3s] " + l
            if k == len(p["segments"]) - 1 and lines:
                lines[-1] = "[LAST LINE] " + lines[-1]
        parts.append("\n".join(lines))
    out = parts[0] if parts else ""
    for k in range(1, len(parts)):
        same_ep = p["segments"][k]["episode"] == p["segments"][k - 1]["episode"]
        out += ("\n   [cut]\n" if same_ep else f"\n   [cut to episode {p['segments'][k]['episode']}]\n") + parts[k]
    return out


def critic_prompt(eps, clips, bible_text):
    where = lambda p: f"episodes {', '.join(map(str, p['episodes']))}" if len(p.get("episodes", [])) > 1 else f"episode {p['episode']}"
    blocks = [f"### CLIP {p['id']} ({where(p)}, {p['length_s']}s)\n{clip_text(eps, p, marks=True)}" for p in clips]
    return f"CLIPS TO CHECK:\nSHOW BIBLE\n{bible_text}\n\n" + "\n\n".join(blocks)


def signature(p):
    """Identifies the exact clip + critic prompt version: a cached answer is reused only if this matches."""
    key = prompts.CRITIC_VERSION + json.dumps([[s["episode"], s["start_s"], s["end_s"]] for s in p["segments"]] + [p["hook"], p["cliffhanger"]])
    return hashlib.sha1(key.encode()).hexdigest()[:12]


# ---- turning answers into a score -------------------------------------------------------------------------------
def checks_for(p):
    return CHECKS + (["cuts_make_sense"] if len(p["segments"]) > 1 else [])


def majority(votes):
    """Merge several critic answers for one clip: each check passes if most votes say so. -> (merged, agreement)."""
    votes = [v for v in votes if isinstance(v, dict) and isinstance(v.get("checks"), dict)]
    if not votes: return None, None
    names = CHECKS + (["cuts_make_sense"] if any("cuts_make_sense" in v["checks"] for v in votes) else [])
    checks, unanimous = {}, 0
    for c in names:
        answers = [v["checks"].get(c) or {} for v in votes]
        yes = [a for a in answers if a.get("pass") is True]
        passed = len(yes) * 2 > len(answers)
        reason = ((yes if passed else [a for a in answers if a.get("pass") is not True]) or answers)[0].get("reason", "")
        checks[c] = {"pass": passed, "reason": f"{reason} [{len(yes)}/{len(answers)} yes]" if len(votes) > 1 else reason}
        unanimous += len(yes) in (0, len(answers))
    most = lambda k: max((v.get(k) for v in votes), key=lambda x: sum(v.get(k) == x for v in votes))
    return ({"checks": checks, "pattern": most("pattern"), "hook_type": most("hook_type"), "cliff_type": most("cliff_type")},
            round(unanimous / len(names), 2))


def cold_viewer_ok(ans):
    """The stranger named a concrete conflict AND would keep watching."""
    ans = ans or {}
    keep = ans.get("would_keep_watching")
    return not ans.get("_malformed") and not VAGUE.match(str(ans.get("conflict_between", ""))) and \
        (keep is True or str(keep).strip().lower() == "true")


def score_promo(p, critic, cold):
    """Fill in checks, quality_4 (0-4), quality_7 (display), pattern and spoiler from the answers."""
    raw = (critic or {}).get("checks") or {}
    checks = {c: {"pass": (raw.get(c) or {}).get("pass") is True, "reason": str((raw.get(c) or {}).get("reason", "no answer"))[:160]}
              for c in checks_for(p)}
    if cold is not None and not cold_viewer_ok(cold):
        why = ("cold viewer answer was malformed" if cold.get("_malformed") else
               "cold viewer could not name a conflict" if VAGUE.match(str(cold.get("conflict_between", ""))) else
               "cold viewer would scroll past: " + str(cold.get("why") or "")[:100])
        checks["standalone_understandable"] = {"pass": False, "reason": why}
    ok = lambda c: checks.get(c, {}).get("pass", True)
    groups = {"hook": ok("hook_conflict_no_context") and ok("hook_in_rubric"),
              "ending": ok("open_question_at_end") and ok("cliff_in_rubric"),
              "standalone": ok("standalone_understandable") and ok("cuts_make_sense"),
              "not_a_spoiler": ok("not_a_spoiler")}
    notes = [p["notes"]] if p.get("notes") else []
    for group, kind, text in (("hook", p.get("hook_kind"), p["hook"]), ("ending", p.get("cliff_kind"), p["cliffhanger"])):
        if groups[group] and reaction_only(kind, text):         # a look / gasp / recoil is not a hook or a cliffhanger
            groups[group] = False; notes.append(f"{group} group failed: reaction/mood action")
    q4 = sum(groups.values())
    if p.get("weak_cold_open"):
        q4 = max(0, q4 - 1); notes.append("quality -1: weak cold open")
    p.update(checks=checks, cold_viewer=cold, quality_groups=groups, quality_4=q4, quality_7=sum(v["pass"] for v in checks.values()),
             pattern=(critic or {}).get("pattern") if (critic or {}).get("pattern") in prompts.PATTERNS else "other",
             hook_type_critic=(critic or {}).get("hook_type", ""), cliff_type_critic=(critic or {}).get("cliff_type", ""),
             notes="; ".join(dict.fromkeys(n for n in notes if n)))
    if critic and not checks["not_a_spoiler"]["pass"]: p["spoiler"] = True
    return p


# ---- asking the models (cached, in parallel) --------------------------------------------------------------------
def critique(llm, eps, promos, bible_text, cache_path, votes=3, parallel=4):
    """Score `promos` in place. llm=None -> only use cached answers. Returns the ids that are still unscored."""
    cache = json.load(open(cache_path)).get("items", {}) if os.path.exists(cache_path) else {}
    fresh = lambda p: cache.get(p["id"], {}).get("sig") == signature(p)
    system = prompts.CRITIC.replace("{rubric}", prompts.RUBRIC)

    def ask(p):
        got = llm.ask_json(system, critic_prompt(eps, [p], bible_text), expect="clips").get("clips", [])
        return next((c for c in got if isinstance(c, dict) and c.get("id") == p["id"]), got[0] if got else None)

    def judge(p):                                  # 2 votes; a 3rd only if they disagree (same majority, fewer calls)
        answers = [ask(p) for _ in range(min(votes, 2))]
        a = [x for x in answers if isinstance(x, dict) and isinstance(x.get("checks"), dict)]
        disagree = len(a) < 2 or any(bool((a[0]["checks"].get(k) or {}).get("pass")) != bool((a[1]["checks"].get(k) or {}).get("pass"))
                                     for k in set(a[0]["checks"]) | set(a[1]["checks"]))
        if votes >= 3 and disagree: answers.append(ask(p))
        return p, answers

    def cold(p):
        for _ in range(2):                         # one retry if the answer comes back in the wrong shape
            ans = llm.ask_json(prompts.COLD, "CLIP:\n" + clip_text(eps, p))
            if all(k in ans for k in ("conflict_between", "would_keep_watching")): return p, ans
        return p, {"_malformed": True}

    if llm is not None:
        todo = [p for p in promos if not fresh(p) or not cache[p["id"]].get("critic")]
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            for p, answers in pool.map(judge, todo):
                merged, agreement = majority(answers)
                cache[p["id"]] = {"sig": signature(p), "critic": merged, "agreement": agreement, "raw_samples": answers, "cold": None}
            need_cold = [p for p in promos if fresh(p) and cache[p["id"]].get("critic") and not cache[p["id"]].get("cold")]
            for p, ans in pool.map(cold, need_cold): cache[p["id"]]["cold"] = ans
        json.dump({"items": cache}, open(cache_path, "w"), indent=1, ensure_ascii=False)

    unscored = []
    for p in promos:
        item = cache.get(p["id"]) if fresh(p) else None
        if not item or not item.get("critic") or not item.get("cold"):
            p.update(quality_4=None, checks=None, pattern="other"); unscored.append(p["id"]); continue
        score_promo(p, item["critic"], item["cold"])
        p["critic_agreement"] = item.get("agreement")
    return unscored
