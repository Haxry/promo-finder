"""Check a promo the model proposed, repair near-misses, or reject it with a reason.

The model only names line ids ("L12"); here code looks up the real text and times and enforces the brief:
  - 20-60 seconds, made of 1-3 segments in story order (segments may come from several episodes)
  - the HOOK is in the first 3 seconds, the clip ENDS on the CLIFFHANGER (nothing after it)
  - the cliffhanger is dialogue or a plot action, not a sound cue or a reaction shot
Every repair is written to promo["notes"]. Type is decided here: A = 1 segment, B = 2-3 segments of one episode,
C = segments from 2+ episodes.
"""
import re
from .parse import mmss, story_lines, is_continuation

MIN_LEN, MAX_LEN = 20.0, 60.0     # promo length (s)
HOOK_WINDOW = 3.0                 # the hook must start within the first 3 s
MIN_SEG = 2.0                     # shortest segment of a single clip
MIN_STITCH_SEG = 4.0              # shortest segment of a stitched clip (a shorter jump cut is unwatchable)
MAX_C_SEG = 25.0                  # longest segment of a cross-episode clip
MERGE_GAP = 3.0                   # same-episode segments closer than this are one segment
CLIFF_EXTEND = 6.0                # a cliffhanger line ending up to 6 s after the clip is pulled in
MAX_CUT_OVER = 5.0                # a clip up to 5 s too long may lose one middle line
MAX_SETUP = 8.0                   # a too-short clip may get a setup line of 4-8 s in front
EPS = 0.01

# An ACTION line can end a promo only if something physical happens (not a look, a gasp, a smile).
PLOT_ACTION = re.compile(
    r"\b(strik|slap|grab|seiz|burst|raise[sd]? (?:a|the|his|her) (?:sword|blade|knife|dagger|pistol|gun|hand)|point|collaps|"
    r"enter|reveal|drop|kneel|knelt|kiss|stab|shov|drag|unmask|pull|throw|threw|burn|arrest|chain|lung|charg|attack|"
    r"shoot|shot|opens? fire|fires\b|fired\b|kick|swing|swung|hurl|tears? (?:open|apart|off|down)|tore|rip[s ]|smash|"
    r"shatter|crash|falls? (?:to|from|into|onto)|fell|faint|bleed|blood|blade|knife|sword|dagger|gun|pistol|poison|"
    r"barg|storm|block|corner|strangl|seal|slam|step[s]? between|emerg|breach|armed|appear|arriv|inches from|in judgment|verdict|sentenc)", re.I)
REACTION = re.compile(r"recoil|gasp|flinch|stare|gaze|glanc|look|smil|smirk|freez|widen|trembl|blink|sigh|frown|exchange", re.I)
STRONG = re.compile(r"strik|slap|grab|seiz|stab|arrest|shov|drag|kick|punch|burst|charg|attack|lung|emerg|breach|"
                    r"(sword|blade|knife|dagger|pistol|gun)|chain|collaps|faint|bleed", re.I)

# Words that carry stakes on their own: a short opening line with one of these is still a real hook.
STAKES = re.compile(
    r"\b(lie|lies|lying|liar|lied|poison\w*|kill\w*|die|dies|dying|dead|death|murder\w*|arrest\w*|guard\w*|marry|married|"
    r"husband|wife|bride|groom|steal|stole|stolen|thief|plant\w*|impost\w*|traitor|treason|blood|truth|secret|"
    r"witch\w*|hang\w*|execut\w*|prison|dungeon|burn\w*|duke|duchess|heir|mother|father|sister|brother|son|daughter|"
    r"never|how dare|get out|stop|help|run|leave)\b", re.I)
FUNCTION_WORDS = set("""i you he she him her it they them this that these those here there me we us my your his its our their
and but or so for what who why how the a an of at to is are was were be do did look see come go now then well oh yes no not
you're it's that's i'm he's she's""".split())
ADDRESS = set("""lady lord sir madam madame my your grace highness majesty duke duchess mother father sister brother mistress
master miss mister mr mrs captain dear the of her his dowager lordship ladyship""".split())


# ---- line-level rules -------------------------------------------------------------------------------------------
def reaction_only(kind, text):
    """An ACTION line where nobody does anything physical TO anyone (a look, gasp, recoil, smirk, freeze ...)."""
    return kind == "action" and (not PLOT_ACTION.search(text) or (bool(REACTION.search(text)) and not STRONG.search(text)))


def cliff_problem(e):
    if e.kind == "sound": return f"cliffhanger is a sound cue, not a story beat: {e.text[:60]!r}"
    if e.kind == "action" and not PLOT_ACTION.search(e.text):
        return f"cliffhanger is a reaction/mood action, not a plot beat: {e.text[:60]!r}"
    return None


def name_only(e, names=()):
    """'Lady Juliana Ashcroft.', 'Alexander!', 'Your Grace.' - only a name / form of address."""
    words = re.findall(r"[A-Za-z']+", e.text) if e.kind == "dialogue" else []
    low = {n.lower() for n in names}
    if not words or len(words) > 4: return False
    if not any(w.lower() in low for w in words) and not all(w.lower() in ADDRESS for w in words): return False
    return all(w.lower() in low or w.lower() in ADDRESS for w in words)


def weak_cold_open(e, names=()):
    """A short opening that only makes sense with context: 'Look at him.', 'For what?', or a bare name."""
    if e.kind != "dialogue": return False
    if name_only(e, names): return True
    words = re.findall(r"[A-Za-z']+", e.text)
    if not words or len(words) > 4 or STAKES.search(e.text): return False
    low = {n.lower() for n in names}
    if any(w.lower() in low for w in words): return False
    if any(w[0].isupper() and i > 0 and w.lower() not in FUNCTION_WORDS for i, w in enumerate(words)): return False
    if len(words) == 1 and words[0][0].isupper() and words[0].lower() not in FUNCTION_WORDS: return False
    return sum(w.lower() in FUNCTION_WORDS for w in words) / len(words) >= 0.6


# ---- looking up lines -------------------------------------------------------------------------------------------
def line(ep, ref):
    """'L12' -> ep.events[12] (None if it isn't a real, non-camera line)."""
    m = re.match(r"^\s*L?(\d+)\s*$", str(ref or ""))
    i = int(m.group(1)) if m else -1
    return ep.events[i] if 0 <= i < len(ep.events) and ep.events[i].kind != "camera" else None


def ref(eps, r, default_ep):
    """A line reference "L12" (in default_ep) or {"episode": 15, "line": "L12"} -> (episode number, Event or None)."""
    if isinstance(r, dict):
        try: n = int(r.get("episode", default_ep))
        except (TypeError, ValueError): return default_ep, None
        return n, (line(eps[n], r.get("line")) if n in eps else None)
    return default_ep, (line(eps[default_ep], r) if default_ep in eps else None)


def bad_refs(ep, j, eps=None):
    """Line ids in a proposal that don't exist (the model made them up) - counted in run_stats."""
    eps = eps or {ep.number: ep}
    out = []
    for sg in j.get("segments") or []:
        if not isinstance(sg, dict): continue
        for x in (sg.get("start_line"), sg.get("end_line")):
            if x is not None and ref(eps, {"episode": sg.get("episode", ep.number), "line": x}, ep.number)[1] is None:
                out.append(str(x))
    for r in (j.get("hook_line"), j.get("cliff_line")):
        if r is not None and ref(eps, r, ep.number)[1] is None: out.append(str(r.get("line") if isinstance(r, dict) else r))
    return out


def total(segs):
    return sum(t - s for _, s, t in segs)


def score(x):
    try: return max(1.0, min(5.0, float(x)))
    except (TypeError, ValueError): return None


# ---- the two length repairs -------------------------------------------------------------------------------------
def cut_middle_line(eps, segs, hook, cliff):
    """Up to 5 s too long: remove ONE whole middle line (never the hook, the cliffhanger or the line before it).
    Returns (segment index, removed line, next line) for the smallest cut that works, or None."""
    if len(segs) >= 3: return None
    before_cliff = max((e for e in story_lines(eps[segs[-1][0]]) if e.end <= cliff.start + EPS and e is not cliff),
                       key=lambda e: e.start, default=None)
    over, best = total(segs) - MAX_LEN, None
    for k, (n, s, t) in enumerate(segs):
        inside = sorted((e for e in story_lines(eps[n]) if s + EPS < e.start and e.end <= t + EPS), key=lambda e: e.start)
        for e, nxt in zip(inside, inside[1:]):
            if e is hook or e is cliff or e is before_cliff or (k == 0 and e.start < hook.end - EPS): continue
            if is_continuation(nxt) or nxt.start <= e.start: continue
            save = nxt.start - e.start
            if save < over + 0.05 or e.start - s < MIN_STITCH_SEG or t - nxt.start < MIN_STITCH_SEG: continue
            if total(segs) - save < MIN_LEN: continue
            if best is None or save < best[2].start - best[1].start: best = (k, e, nxt)
    return best


def setup_line(eps, segs, names, length):
    """Too short: a 4-8 s line from EARLIER IN THE SAME SCENE that names a character or the stakes, to put in front."""
    if len(segs) >= 3: return None
    lines = story_lines(eps[segs[0][0]])
    first = min((e for e in lines if e.start >= segs[0][1] - EPS), key=lambda e: e.start, default=None)
    if first is None: return None
    low = {n.lower() for n in names}
    ok = lambda e: (e.kind == "dialogue" and e.scene == first.scene and e.end <= segs[0][1] - EPS
                    and MIN_STITCH_SEG <= e.end - e.start <= MAX_SETUP and not is_continuation(e)
                    and MIN_LEN <= length + (e.end - e.start) <= MAX_LEN
                    and (STAKES.search(e.text) or any(w.lower() in low for w in re.findall(r"[A-Za-z']+", e.text))))
    return max((e for e in lines if ok(e)), key=lambda e: e.start, default=None)


# ---- the main check ---------------------------------------------------------------------------------------------
def validate(ep, j, names=(), eps=None):
    """-> (promo dict, None) or (None, reason). `ep` = the promo's first episode; pass `eps` for multi-episode promos."""
    eps = eps or {ep.number: ep}
    notes = []

    # 1. segments: real lines, story order, not overlapping; same-episode segments < 3 s apart are merged
    segs_in = j.get("segments") or []
    if not isinstance(segs_in, list) or not 1 <= len(segs_in) <= 3:
        return None, f"needs 1-3 segments, got {len(segs_in) if isinstance(segs_in, list) else segs_in!r}"
    segs = []                                                    # [episode, start, end]
    for k, sg in enumerate(segs_in):
        sg = sg or {}
        try: n = int(sg.get("episode", ep.number))
        except (TypeError, ValueError): return None, f"segment {k + 1} has a bad episode: {sg}"
        if n not in eps: return None, f"segment {k + 1} cites episode {n}, which is not loaded"
        a, b = line(eps[n], sg.get("start_line")), line(eps[n], sg.get("end_line"))
        if a is None or b is None: return None, f"segment {k + 1} cites a line that does not exist: {sg}"
        if b.end - a.start < MIN_SEG: return None, f"segment {k + 1} is {b.end - a.start:.1f}s (< {MIN_SEG:.0f}s)"
        if segs and (n < segs[-1][0] or n == segs[-1][0] and a.start < segs[-1][2] - EPS):
            return None, f"segment {k + 1} overlaps or is out of order"
        if is_continuation(a):
            if k == 0: return None, f"clip opens mid-sentence: {a.text[:50]!r}"
            notes.append(f"segment {k + 1} starts mid-sentence")
        if segs and segs[-1][0] == n and a.start - segs[-1][2] < MERGE_GAP:
            notes.append(f"merged segments {k} and {k + 1} (gap {a.start - segs[-1][2]:.1f}s: a pointless jump cut)")
            segs[-1][2] = b.end
            continue
        segs.append([n, a.start, b.end])
    first_ep, last_ep = segs[0][0], segs[-1][0]

    # 2. hook in the first segment, cliffhanger in the last one
    hn, hook = ref(eps, j.get("hook_line"), first_ep)
    cn, cliff = ref(eps, j.get("cliff_line"), last_ep)
    if hook is None: return None, f"hook_line {j.get('hook_line')!r} is not a real line"
    if cliff is None: return None, f"cliff_line {j.get('cliff_line')!r} is not a real line"
    if hn != first_ep or not (segs[0][1] - EPS <= hook.start < segs[0][2]):
        return None, f"hook line at {mmss(hook.start)} is not inside the first segment ({mmss(segs[0][1])}-{mmss(segs[0][2])})"
    if cn != last_ep: return None, f"cliffhanger line is not in the last segment's episode ({cn} vs {last_ep})"
    if segs[-1][1] - EPS <= cliff.start and segs[-1][2] + EPS < cliff.end <= segs[-1][2] + CLIFF_EXTEND:
        notes.append(f"extended the last segment by {cliff.end - segs[-1][2]:.1f}s to include the cliffhanger line")
        segs[-1][2] = cliff.end                                 # the model stopped just short of its own cliffhanger
    if not (segs[-1][1] - EPS <= cliff.start and cliff.end <= segs[-1][2] + EPS):
        return None, f"cliffhanger line {mmss(cliff.start)}-{mmss(cliff.end)} is not inside the last segment"
    lines0, linesN = story_lines(eps[first_ep]), story_lines(eps[last_ep])

    # 3. a sound cue / reaction shot can't be the cliffhanger: end on the last dialogue line before it instead
    problem = cliff_problem(cliff)
    if problem:
        before = [e for e in linesN if e.kind == "dialogue" and segs[-1][1] - EPS <= e.start and e.end <= cliff.start + EPS]
        if not before: return None, problem + " (and no dialogue line before it in the last segment)"
        cliff = max(before, key=lambda e: e.end)
        notes.append(f"cliffhanger moved to the last dialogue line {cliff.text[:40]!r} ({problem.split(':')[0]})")
        if len(segs) == 1 and hook.start >= cliff.end - EPS: return None, problem + " (no dialogue between the hook and it)"

    # 4. end ON the cliffhanger: drop any line after it
    after = [e for e in linesN if e.start >= cliff.end - EPS and e.start < segs[-1][2] - EPS]
    if after:
        notes.append(f"trimmed end to the cliffhanger ({len(after)} line(s) after it removed, e.g. {after[0].text[:40]!r})")
        segs[-1][2] = cliff.end
        if segs[-1][2] - segs[-1][1] < MIN_SEG: return None, "last segment too short after trimming to the cliffhanger"

    # 5. hook in the first 3 seconds: start later if needed
    if hook.start > segs[0][1] + HOOK_WINDOW:
        starts = [e.start for e in lines0 if segs[0][1] < e.start <= hook.start <= e.start + HOOK_WINDOW and not is_continuation(e)]
        if not starts: return None, f"hook line at {mmss(hook.start)} is not in the first {HOOK_WINDOW:.0f}s and no clean cut fixes it"
        old, segs[0][1] = segs[0][1], min(starts)
        notes.append(f"start moved {mmss(old)}->{mmss(segs[0][1])} so the hook is in the first {HOOK_WINDOW:.0f}s")

    # 6. length 20-60 s: repair if we can
    length = total(segs)
    if length < MIN_LEN:
        old = segs[0][1]
        for e in sorted((e for e in lines0 if e.start < segs[0][1] - EPS), key=lambda e: -e.start):
            if hook.start > e.start + HOOK_WINDOW: break        # would push the hook out of the first 3 s
            if is_continuation(e): continue
            segs[0][1] = e.start
            if total(segs) >= MIN_LEN: break
        if total(segs) >= MIN_LEN:
            notes.append(f"too short ({length:.1f}s): start extended {mmss(old)}->{mmss(segs[0][1])}")
        else:
            segs[0][1] = old
            setup = setup_line(eps, segs, names, length)
            if setup is None:
                return None, f"total length {length:.1f}s < {MIN_LEN:.0f}s and extending the start would push the hook out of the first {HOOK_WINDOW:.0f}s"
            segs.insert(0, [first_ep, setup.start, setup.end])   # the hook then opens segment 2
            notes.append(f"too short ({length:.1f}s): prepended setup line L{eps[first_ep].events.index(setup)} "
                         f"{setup.text[:40]!r} ({setup.end - setup.start:.1f}s)")
    elif length > MAX_LEN:
        before = [s[:] for s in segs]
        for e in sorted((e for e in lines0 if segs[0][1] < e.start <= hook.start), key=lambda e: e.start):
            if total(segs) <= MAX_LEN: break                     # drop opening lines (hook stays in)
            if not is_continuation(e): segs[0][1] = e.start
        for k in range(1, len(segs)):                            # then the openings of later segments
            if total(segs) <= MAX_LEN: break
            limit = cliff.start if k == len(segs) - 1 else segs[k][2] - MIN_SEG
            for e in sorted((e for e in story_lines(eps[segs[k][0]]) if segs[k][1] < e.start <= limit), key=lambda e: e.start):
                if total(segs) <= MAX_LEN: break
                if not is_continuation(e): segs[k][1] = e.start
        cut = cut_middle_line(eps, segs, hook, cliff) if MAX_LEN < total(segs) <= MAX_LEN + MAX_CUT_OVER else None
        if cut:
            k, e, nxt = cut
            segs[k:k + 1] = [[segs[k][0], segs[k][1], e.start], [segs[k][0], nxt.start, segs[k][2]]]
        if total(segs) > MAX_LEN:
            return None, f"total length {length:.1f}s > {MAX_LEN:.0f}s and dropping opening lines can't fix it without losing the hook/cliffhanger"
        if cut:
            notes.append(f"too long ({length:.1f}s): cut middle line L{eps[segs[cut[0]][0]].events.index(cut[1])} "
                         f"{cut[1].text[:30]!r} ({cut[2].start - cut[1].start:.1f}s) -> 2 segments")
        else:
            notes.append(f"too long ({length:.1f}s): dropped opening lines " + ", ".join(
                f"seg{k + 1} {mmss(b[1])}->{mmss(a[1])}" for k, (b, a) in enumerate(zip(before, segs)) if a[1] != b[1]))
    length = total(segs)
    multi_episode = len({s[0] for s in segs}) > 1
    if len(segs) > 1:
        short = [k + 1 for k, s in enumerate(segs) if s[2] - s[1] < MIN_STITCH_SEG - EPS]
        if short: return None, f"stitched segment(s) {short} shorter than {MIN_STITCH_SEG:.0f}s"
    if multi_episode:
        long_ = [k + 1 for k, s in enumerate(segs) if s[2] - s[1] > MAX_C_SEG + EPS]
        if long_: return None, f"cross-episode segment(s) {long_} longer than {MAX_C_SEG:.0f}s"

    # 7. weak cold open ("Look at you...", a bare name): flagged here, costs a quality point in the critic
    opening = min((e for e in lines0 if segs[0][1] - EPS <= e.start < segs[0][2]), key=lambda e: e.start, default=hook)
    h, c, sa = score(j.get("hook_strength")), score(j.get("cliff_strength")), score(j.get("standalone"))
    if None in (h, c, sa): return None, "missing/invalid numeric scores"
    weak = weak_cold_open(opening, names) or name_only(hook, names)
    if weak:
        notes.append(f"weak cold open {(opening if weak_cold_open(opening, names) else hook).text[:30]!r}: hook capped at 3, quality -1")
        h = min(h, 3.0)
    if sa > 4 and str(j.get("missing_context") or "").strip().lower().rstrip(".") not in ("", "none", "n/a", "nothing"):
        sa = 4.0; notes.append("standalone capped at 4: model listed missing context")

    scene_at = lambda n, s: next((e.scene for e in story_lines(eps[n]) if e.start >= s - EPS), None)
    return {"episode": first_ep, "episodes": sorted({s[0] for s in segs}),
            "type": "A" if len(segs) == 1 else ("C" if multi_episode else "B"),
            "segments": [{"episode": n, "start": mmss(s), "end": mmss(t), "start_s": round(s, 2), "end_s": round(t, 2),
                          "scene": scene_at(n, s)} for n, s, t in segs],
            "hook_ref": [first_ep, eps[first_ep].events.index(hook)], "cliff_ref": [last_ep, eps[last_ep].events.index(cliff)],
            "length_s": round(length, 1), "hook": hook.text, "hook_kind": hook.kind, "hook_type": j.get("hook_type") or "other",
            "hook_strength": h, "cliffhanger": cliff.text, "cliff_kind": cliff.kind, "cliff_strength": c, "standalone": sa,
            "weak_cold_open": weak, "missing_context": j.get("missing_context", ""), "spoiler": bool(j.get("spoiler")),
            "why": j.get("why", ""), "notes": "; ".join(notes)}, None


def character_names(bible, episodes):
    """Names for the weak-opening rule: the bible's characters + every speaker tag in the scripts."""
    names = set()
    for c in bible.get("characters", []):
        names.update(w for w in str(c.get("name", "")).replace("'", " ").split() if w[:1].isupper())
    for ep in episodes:
        for e in ep.events:
            if e.speaker: names.update(w for w in e.speaker.split() if w[:1].isupper())
    return names - {"The", "Lady", "Lord", "Of", "And"}
