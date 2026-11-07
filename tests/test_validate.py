"""The brief's hard rules, checked on real screenplay lines (promo/validate.py)."""
import pytest
from promo.parse import Event, story_lines, is_continuation
from promo.validate import validate, weak_cold_open, cliff_problem, reaction_only

NAMES = {"Juliana", "Ashcroft", "Alexander", "Gerald", "Clarissa"}


def ids(ep): return [i for i, e in enumerate(ep.events) if e.kind in ("dialogue", "action")]
def span(ep, a, b): return ep.events[b].end - ep.events[a].start


def clip(ep, lo, hi, end_dialogue=True):
    """A real stretch lo..hi seconds long that starts on a clean line (and ends on dialogue)."""
    L = ids(ep)
    for x, a in enumerate(L):
        if is_continuation(ep.events[a]): continue
        for b in L[x:]:
            if lo <= span(ep, a, b) <= hi and (ep.events[b].kind == "dialogue" or not end_dialogue): return a, b
    pytest.skip("no fixture")


def prop(segs, hook, cliff, **kw):
    return {"segments": [{"start_line": f"L{a}", "end_line": f"L{b}"} for a, b in segs], "hook_line": f"L{hook}",
            "cliff_line": f"L{cliff}", "hook_strength": 4, "cliff_strength": 4, "standalone": 4, "missing_context": "none", **kw}


def test_valid_clip(eps):
    ep = eps[1]; a, b = clip(ep, 30, 45)
    p, why = validate(ep, prop([(a, b)], a, b))
    assert p and p["type"] == "A" and 20 <= p["length_s"] <= 60 and p["hook"] == ep.events[a].text


def test_ends_on_the_cliffhanger(eps):
    ep = eps[1]; L = ids(ep); a, cl = clip(ep, 28, 40)
    p, _ = validate(ep, prop([(a, L[L.index(cl) + 3])], a, cl))          # 3 lines run past the cliffhanger
    assert p["segments"][-1]["end_s"] == round(ep.events[cl].end, 2) and "trimmed end to the cliffhanger" in p["notes"]


def test_sound_or_reaction_cliffhanger_moves_to_dialogue(eps):
    ep = eps[1]
    snd = next(i for i, e in enumerate(ep.events) if e.kind == "sound")
    a = next(i for i in ids(ep) if ep.events[i].start >= ep.events[snd].end - 45 and not is_continuation(ep.events[i]))
    p, why = validate(ep, prop([(a, snd)], a, snd))
    assert (p and p["cliff_kind"] == "dialogue" and "cliffhanger moved" in p["notes"]) or "sound cue" in why


def test_hook_must_be_in_first_3_seconds(eps):
    ep = eps[1]; L = ids(ep); a, b = clip(ep, 35, 50)
    late = next(i for i in L[L.index(a):] if ep.events[i].start - ep.events[a].start > 3 and not is_continuation(ep.events[i]))
    p, why = validate(ep, prop([(a, b)], late, b))
    assert (p and "so the hook is in the first 3s" in p["notes"]) or "first 3s" in why or "length" in why


@pytest.mark.parametrize("lo,hi,word", [(8, 11, "< 20s"), (80, 100, "> 60s")])
def test_length_limits(eps, lo, hi, word):
    ep = eps[1]; a, b = clip(ep, lo, hi)
    p, why = validate(ep, prop([(a, b)], a, b))
    assert p is None and word in why


def test_made_up_line_and_bad_structure_rejected(eps):
    ep = eps[1]; a, b = clip(ep, 30, 40)
    assert "not a real line" in validate(ep, prop([(a, b)], a, 9999))[1]
    assert "1-3 segments" in validate(ep, prop([(a, b)] * 4, a, b))[1]
    L = ids(ep); c, d = L[L.index(b) + 5], L[L.index(b) + 12]
    assert "out of order" in validate(ep, prop([(c, d), (a, b)], c, b))[1]


def test_cross_episode_promo_is_type_c_and_order_matters(eps):
    a1, b1 = clip(eps[2], 10, 20, end_dialogue=False)
    a2, b2 = clip(eps[15], 10, 20)
    j = lambda e1, s1, e2, s2: {"segments": [{"episode": e1, "start_line": f"L{s1[0]}", "end_line": f"L{s1[1]}"},
                                              {"episode": e2, "start_line": f"L{s2[0]}", "end_line": f"L{s2[1]}"}],
                                 "hook_line": {"episode": e1, "line": f"L{s1[0]}"}, "cliff_line": {"episode": e2, "line": f"L{s2[1]}"},
                                 "hook_strength": 3, "cliff_strength": 3, "standalone": 3}
    p, why = validate(eps[2], j(2, (a1, b1), 15, (a2, b2)), (), eps)
    assert p and p["type"] == "C" and p["episodes"] == [2, 15], why
    assert "out of order" in validate(eps[15], j(15, (a2, b2), 2, (a1, b1)), (), eps)[1]


@pytest.mark.parametrize("text,weak", [
    ('"Look at him."', True), ('"For what?"', True), ('"Who are you?"', True), ('"Lady Juliana Ashcroft."', True),
    ('"Alexander!"', True), ('"Poison."', False), ('"You planted it!"', False), ('"Guards! Arrest this imposter!"', False),
    ('"Silence! Silence!"', False), ('"Gerald is waiting for me."', False)])
def test_weak_cold_open(text, weak):
    assert weak_cold_open(Event("dialogue", 0, 1, text), NAMES) == weak


@pytest.mark.parametrize("text,plot", [
    ("Juliana smiles softly, gazing at the fire.", False), ("Gerald slaps Juliana hard across the face.", True),
    ("Armed figures emerge through the smoke.", True), ("Juliana recoils, gasping, as the iron stops inches from her face.", False)])
def test_action_lines(text, plot):
    assert (not reaction_only("action", text)) == plot
    assert cliff_problem(Event("dialogue", 0, 1, text)) is None
