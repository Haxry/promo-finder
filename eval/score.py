#!/usr/bin/env python3
"""How good is it? Compares runs against the editor's decisions and against the brief's rules. Prints a markdown table.

    python eval/score.py outputs/<run A> outputs/<run B> ...

- precision@10 / @20: of the top-k promos the editor reviewed in the app (Post / Maybe / Skip, saved in each run's
  review.csv), the share marked post or maybe. A decision counts for the same moment in every run
  (same episode, > 50% time overlap), so one review compares several runs.
- critic vs editor: does the run's own judgement (quality_4 >= 3, or older scales) agree with the editor?
- rules, re-checked on the screenplays for the top 40 / top 10: lines after the cliffhanger, sound-cue endings,
  duplicate pairs, weak cold opens, reaction-only hooks or cliffhangers, spoilers"""
import argparse, collections, glob, json, os, re, sys
import csv
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
from promo.parse import parse_file
from promo.validate import weak_cold_open, name_only, reaction_only, character_names
from promo.rank import duplicate_reason

GOOD = {"post", "maybe"}


def spans(p):
    return [(s["episode"], s["start_s"], s["end_s"]) for s in p["segments"]]


def same_moment(a, b):
    """More than half of the shorter clip is covered by the other (same episode)."""
    inter = sum(max(0.0, min(b1, b2) - max(a1, a2)) for e1, a1, b1 in a for e2, a2, b2 in b if e1 == e2)
    return inter > 0.5 * min(sum(t - s for _, s, t in a), sum(t - s for _, s, t in b))


def read_reviews():
    """Every editor decision in outputs/*/review.csv, as (clip spans, decision)."""
    out = []
    for path in glob.glob(os.path.join(ROOT, "outputs", "*", "review.csv")):
        promos = {p["id"]: p for p in json.load(open(os.path.join(os.path.dirname(path), "promos.json")))}
        for r in csv.DictReader(open(path)):
            if r["decision"] in GOOD | {"skip"} and r["promo_id"] in promos: out.append((spans(promos[r["promo_id"]]), r["decision"]))
    return out


def find_line(ep, text, seg):
    return next((i for i, e in enumerate(ep.events) if e.text == text and seg["start_s"] - 0.01 <= e.start <= seg["end_s"] + 0.01), None)


def critic_says_postable(p):
    if p.get("quality_4") is not None: return p["quality_4"] >= 3
    if p.get("quality") is not None: return p["quality"] >= 5                     # first v4 run: 0-7 scale
    s = [p.get(k) for k in ("hook_strength", "cliff_strength", "standalone") if p.get(k) is not None]
    return bool(s) and sum(s) / len(s) >= 4                                       # older runs: self-scores


def score_run(run, labels, eps):
    P = json.load(open(os.path.join(run, "promos.json")))
    R = json.load(open(os.path.join(run, "rejected.json"))) if os.path.exists(os.path.join(run, "rejected.json")) else []
    S = json.load(open(os.path.join(run, "run_stats.json"))) if os.path.exists(os.path.join(run, "run_stats.json")) else {}
    bible = json.load(open(os.path.join(run, "bible.json"))) if os.path.exists(os.path.join(run, "bible.json")) else {}
    names = character_names(bible, eps.values())
    for p in P:                                    # older runs didn't store these: recover them from the screenplay
        for s in p["segments"]:
            s.setdefault("scene", next((e.scene for e in eps[s["episode"]].events if e.kind != "camera" and e.start >= s["start_s"] - 0.01), None))
        for key, text, seg in (("hook_ref", p["hook"], p["segments"][0]), ("cliff_ref", p["cliffhanger"], p["segments"][-1])):
            if not p.get(key):
                i = find_line(eps[seg["episode"]], text, seg); p[key] = [seg["episode"], i] if i is not None else None
    label_of = lambda p: next((d for s, d in labels if same_moment(spans(p), s)), None)
    ev = lambda ref: eps[ref[0]].events[ref[1]] if ref else None
    res = {"run": os.path.basename(os.path.normpath(run)), "ranked": len(P), "rejected": len(R)}
    for k in (10, 20):
        got = [l for l in map(label_of, P[:k]) if l]
        res[f"p@{k}"] = f"{100 * sum(l in GOOD for l in got) / len(got):.0f}% ({len(got)}/{k})" if got else f"— (0/{k})"
    pairs = [(critic_says_postable(p), l in GOOD) for p in P if (l := label_of(p))]
    res["agree"] = f"{100 * sum(a == b for a, b in pairs) / len(pairs):.0f}% (n={len(pairs)})" if pairs else "— (n=0)"
    after = sound = 0
    for p in P[:40]:
        c, seg = ev(p.get("cliff_ref")), p["segments"][-1]
        if c is None: continue
        sound += c.kind == "sound"
        after += any(e.kind in ("dialogue", "action") and c.end - 0.01 <= e.start < seg["end_s"] - 0.01 for e in eps[seg["episode"]].events)
    res["after_cliff"], res["sound_end"] = after, sound
    res["dups"] = sum(bool(duplicate_reason(a, b)) for i, a in enumerate(P[:40]) for b in P[:i])
    first = lambda p: next((e for e in eps[p["segments"][0]["episode"]].events if e.kind in ("dialogue", "action")
                            and e.start >= p["segments"][0]["start_s"] - 0.01), None)
    res["weak10"] = sum(bool(weak_cold_open(first(p), names) or (ev(p.get("hook_ref")) and name_only(ev(p["hook_ref"]), names))) for p in P[:10])
    res["react10"] = sum(any(e is not None and reaction_only(e.kind, e.text) for e in (ev(p.get("hook_ref")), ev(p.get("cliff_ref")))) for p in P[:10])
    res["spoil10"] = sum(bool(p.get("spoiler")) for p in P[:10])
    res["types"] = " ".join(f"{k}:{v}" for k, v in sorted(collections.Counter(p.get("type", "A") for p in P).items()))
    q = [p.get("quality_4") for p in P[:10] if p.get("quality_4") is not None]
    res["q10"] = f"{sum(q) / len(q):.2f}" if q else "—"
    c = S.get("cost_usd") or S.get("cost_estimate_usd") or {}
    res["cost"] = (f"${c.get('total', c.get('total_usd'))}" + (f" (+ unpriced: {', '.join(c['missing_prices'])})" if c.get("missing_prices") else "")) if c else "—"
    res["reasons"] = collections.Counter(re.sub(r"[\d.:]+s?", "#", r["reason"]).split("(")[0].split(":")[0][:60] for r in R)
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("runs", nargs="+")
    ap.add_argument("--input", default=next(iter(glob.glob(os.path.join(os.path.dirname(os.path.dirname(HERE)), "I Married*"))), ""))
    a = ap.parse_args()
    eps = {e.number: e for e in (parse_file(f) for f in sorted(glob.glob(os.path.join(a.input, "*.txt"))))}
    labels = read_reviews()
    rs = [score_run(r, labels, eps) for r in a.runs]
    rows = [("promos ranked", "ranked"), ("precision@10 (labelled)", "p@10"), ("precision@20 (labelled)", "p@20"),
            ("critic agrees with the editor", "agree"), ("top 10: mean quality_4 (0-4)", "q10"),
            ("top 40: lines after the cliffhanger", "after_cliff"), ("top 40: ends on a sound cue", "sound_end"),
            ("top 40: duplicate pairs", "dups"), ("top 10: weak cold opens", "weak10"),
            ("top 10: reaction-only hook/cliffhanger", "react10"), ("top 10: spoilers", "spoil10"),
            ("top 40: types", "types"), ("rejected proposals", "rejected"), ("cost", "cost")]
    print(f"Editor decisions found: {len(labels)} (review promos in the app: streamlit run app.py)\n")
    print("| metric | " + " | ".join(r["run"] for r in rs) + " |\n|---|" + "---|" * len(rs))
    for title, key in rows: print(f"| {title} | " + " | ".join(str(r[key]) for r in rs) + " |")
    for r in rs:
        print(f"\n**Why proposals were rejected - {r['run']}** ({sum(r['reasons'].values())})")
        for k, v in r["reasons"].most_common(): print(f"- {v} × {k}")


if __name__ == "__main__":
    main()
