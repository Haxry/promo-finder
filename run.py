#!/usr/bin/env python3
"""Find the best promos in a folder of microdrama screenplays.

    python run.py --input "../I Married a Broken Soldier. He was a Duke"      # models from config.toml
    python run.py --input DIR --model groq/openai/gpt-oss-120b --critic groq/openai/gpt-oss-20b
    python run.py --input DIR --model mock                                    # offline, no keys

Steps:  1 read episodes + show bible  ->  2 per episode: propose (LLM) -> check & repair (code) -> critic (other LLM)
        ->  3 stitched promos B/C  ->  4 rank  ->  5 write promos.md / .csv / .json, rejected.json, run_stats.json
Every LLM answer is cached in outputs/<run>/raw_llm/, so re-running the same command only does what is missing.
"""
import argparse, csv, glob, json, os, sys, time, tomllib
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

from promo import prompts
from promo.parse import parse_file, transcript
from promo.llm import make_llm, load_env, set_max_parallel_calls
from promo.validate import validate, bad_refs, character_names
from promo.critic import critique
from promo.stitch import hook_beats, cliff_beats, setup_beats, b_episodes, stitch_b, stitch_c, with_defaults
from promo.rank import rank

HERE = os.path.dirname(os.path.abspath(__file__))


def episode_range(text, numbers):
    if not text: return numbers
    wanted = set()
    for part in text.split(","):
        a, _, b = part.partition("-"); wanted.update(range(int(a), int(b or a) + 1))
    return [n for n in numbers if n in wanted]


def save(path, data):
    json.dump(data, open(path, "w"), indent=1, ensure_ascii=False)


def main():
    load_env(HERE, os.path.dirname(HERE))
    cfg = tomllib.load(open(os.path.join(HERE, "config.toml"), "rb"))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="folder with the episode .txt files")
    ap.add_argument("--model", default=cfg["run"]["model"], help="the model that finds promos, as provider/model")
    ap.add_argument("--critic", default=cfg["run"]["critic"], help="the model that checks them (a different one)")
    ap.add_argument("--episodes", help="e.g. 1-10 or 3,7")
    ap.add_argument("--out", default=os.path.join(HERE, "outputs")); ap.add_argument("--workers", type=int)
    ap.add_argument("--no-stitch", action="store_true"); ap.add_argument("--accept-empty", action="store_true",
                    help="trust cached empty proposal lists instead of asking again")
    a = ap.parse_args()
    R = cfg["run"]
    t0 = time.time()

    # ---- 1. episodes, models, show bible -------------------------------------------------------------------------
    eps = {e.number: e for e in (parse_file(f) for f in sorted(glob.glob(os.path.join(a.input, "*.txt"))))}
    if not eps: sys.exit(f"No .txt screenplays in {a.input}")
    todo = episode_range(a.episodes, sorted(eps))
    proposer = make_llm(a.model, cfg)
    judge = proposer if a.model == "mock" else make_llm(a.critic, cfg)
    workers = a.workers or R["workers"]
    set_max_parallel_calls(R["max_calls"] if workers > 1 else 1)
    provider = a.model.split("/")[0]
    tag = f"{provider}__{proposer.model.replace('/', '_').replace(':', '_')}__{prompts.PROPOSE_VERSION}"
    out = os.path.join(a.out, tag); raw = os.path.join(out, "raw_llm"); os.makedirs(raw, exist_ok=True)
    print(f"proposer {proposer.model} | critic {judge.model} | {len(todo)} episodes | output {out}")

    bible_path = os.path.join(out, "bible.json")
    bible = json.load(open(bible_path)) if os.path.exists(bible_path) else None
    if not bible or bible.get("episodes") != sorted(eps):
        try:
            loglines = "LOGLINES:\n" + "\n".join(f"Ep{e.number}: {e.logline}  [continuity: {e.continuity}]" for e in eps.values())
            b = proposer.ask_json(prompts.BIBLE, loglines, expect="premise")
            bible = {"premise": str(b.get("premise", "")), "known_by_ep5": str(b.get("known_by_ep5", "")),
                     "characters": [c for c in b.get("characters", []) if isinstance(c, dict) and c.get("name")][:20],
                     "late_reveals": [str(x) for x in b.get("late_reveals", [])][:15], "episodes": sorted(eps)}
            save(bible_path, bible)
        except Exception as e:
            sys.exit(f"Show bible failed ({str(e)[:200]}). The model can't answer right now - try again later.")
    chars = "; ".join(f"{c['name']} = {c.get('role', '')}" for c in bible["characters"])
    bible_text = (f"PREMISE: {bible['premise']}\nCHARACTERS: {chars}\nWHAT A VIEWER KNOWS BY EP5: {bible['known_by_ep5']}\n"
                  f"LATE REVEALS (spoilers): " + " | ".join(bible["late_reveals"]))
    names = character_names(bible, eps.values())
    propose_system = prompts.PROPOSE.replace("{max_promos}", str(R["max_promos"])).replace("{rubric}", prompts.RUBRIC)

    # ---- 2. per episode: propose -> check -> critic ---------------------------------------------------------------
    def propose(ep):
        user = (f"SHOW BIBLE\n{bible_text}\n\nEPISODE {ep.number} (duration {ep.duration:.1f}s)\nLOGLINE: {ep.logline}\n"
                f"CONTINUITY: {ep.continuity}\n\nOutput schema:\n{prompts.PROPOSE_SCHEMA}\n\nTRANSCRIPT:\n" + transcript(ep, secs=True))
        return [p for p in proposer.ask_json(propose_system, user, expect="promos")["promos"] if isinstance(p, dict)]

    def episode(n):
        ep, res = eps[n], {"episode": n, "promos": [], "rejects": [], "bad_refs": [], "error": None, "empty": False}
        path = os.path.join(raw, f"ep{n:02d}.json")
        try:
            props = json.load(open(path))["proposals"] if os.path.exists(path) else None
            if not props and not (props == [] and a.accept_empty):
                try:
                    props = propose(ep) or propose(ep)           # an empty answer is asked once more
                except Exception:
                    if props != []: raise                        # nothing cached at all: a real failure
                    print(f"ep{n}: could not re-ask (no key / no quota) - keeping the cached empty answer", file=sys.stderr)
                save(path, {"episode": n, "model": proposer.model, "prompt": prompts.PROPOSE_VERSION, "proposals": props})
            res["empty"] = not props
            for i, j in enumerate(props):
                p, why = validate(ep, j, names, eps)
                res["bad_refs"] += bad_refs(ep, j)
                if p: p["id"] = f"E{n}-{i + 1}"; res["promos"].append(p)
                else: res["rejects"].append({"episode": n, "proposal": i + 1, "reason": why, "raw": j})
            if res["promos"]:
                critique(judge, eps, res["promos"], bible_text, os.path.join(raw, f"critic_ep{n:02d}.json"), R["votes"], 4)
        except Exception as e:                                   # one episode failing never stops the run
            res["error"] = str(e)[:300]
            print(f"ep{n}: {res['error']}", file=sys.stderr)
        print(f"ep{n:>2}: {len(res['promos'])} valid, {len(res['rejects'])} rejected, quality "
              f"{[p.get('quality_4') for p in res['promos']]}", flush=True)
        return res

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(episode, todo))
    promos = [p for r in results for p in r["promos"]]
    rejects = [x for r in results for x in r["rejects"]]
    failed = [r["episode"] for r in results if r["error"]]
    unscored = [p["id"] for p in promos if p.get("quality_4") is None]

    # ---- 3. stitched promos: B (one episode) and C (several episodes) --------------------------------------------
    stitch = {"proposed": Counter(), "valid": Counter(), "rejected": Counter(), "calls": 0, "skipped": None}
    if a.no_stitch or not R["stitch"]: stitch["skipped"] = "turned off"
    elif failed or unscored: stitch["skipped"] = "some episodes failed - re-run to finish first"
    else:
        hooks, cliffs, setups = hook_beats(promos, eps), cliff_beats(promos, eps), setup_beats(eps, names)
        jobs = [("B", n) for n in b_episodes(eps, hooks, cliffs)] + [("C", m) for m in prompts.STITCH_C_MODES]

        def run_job(job):
            kind, key = job
            try:
                props, called = (stitch_b(proposer, eps, key, hooks, cliffs, bible_text, raw) if kind == "B" else
                                 stitch_c(proposer, eps, key, hooks, cliffs, setups, bible_text, raw))
                return kind, key, props, called
            except Exception as e:
                print(f"stitch {kind} {key}: {str(e)[:200]}", file=sys.stderr); return kind, key, [], False
        stitched = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for kind, key, props, called in pool.map(run_job, jobs):
                stitch["calls"] += called; stitch["proposed"][kind] += len(props)
                for i, j in enumerate(props):
                    first = (j.get("segments") or [{}])[0]
                    n0 = key if kind == "B" else (first.get("episode") if isinstance(first, dict) else None)
                    try: n0 = int(n0)
                    except (TypeError, ValueError): n0 = None
                    p, why = validate(eps[n0], with_defaults(j, key if kind == "B" else None), names, eps) if n0 in eps \
                        else (None, f"first segment names no valid episode: {first}")
                    if p and p["type"] == "A": p, why = None, "joined into a single segment (already covered by type A)"
                    if p and kind == "B" and p["type"] != "B": p, why = None, "a type B answer used several episodes"
                    if p:
                        p["id"] = f"B{key}-{i + 1}" if kind == "B" else f"C-{key}-{i + 1}"
                        stitched.append(p)
                    else:
                        stitch["rejected"][kind] += 1
                        rejects.append({"episode": n0, "proposal": f"stitch-{kind}-{key}-{i + 1}", "type": kind, "reason": why, "raw": j})
        if stitched:
            unscored += critique(judge, eps, stitched, bible_text, os.path.join(raw, "critic_stitch.json"), R["votes"], workers)
        for p in stitched: stitch["valid"][p["type"]] += 1
        promos += stitched

    # ---- 4. rank ------------------------------------------------------------------------------------------------
    final, dups, rank_calls = rank(promos, cfg, judge, os.path.join(raw, "rank_groups.json"))
    for p in dups:                                   # a stitched promo that repeats a better moment counts as a reject
        if p["id"][0] in "BC":
            rejects.append({"episode": p["episode"], "proposal": p["id"], "type": p["type"],
                            "reason": f"duplicate of {p['dup_of']} ({p['dup_reason']})", "raw": None})
    final = final[:R["top"]]

    # ---- 5. outputs ---------------------------------------------------------------------------------------------
    usage = {proposer.model: proposer.usage} if judge is proposer else {proposer.model: proposer.usage, judge.model: judge.usage}
    ledger_path = os.path.join(out, "usage_ledger.json")                 # every run's tokens, so cost is cumulative
    ledger = (json.load(open(ledger_path)) if os.path.exists(ledger_path) else []) + \
        [{"time": time.strftime("%F %T"), "model": m, **u} for m, u in usage.items() if u["calls"]]
    save(ledger_path, ledger)
    stats = {
        "proposer": proposer.model, "critic": judge.model, "episodes": len(todo), "complete": not failed and not unscored,
        "failed_episodes": failed, "unscored_promos": unscored, "empty_episodes": [r["episode"] for r in results if r["empty"]],
        "proposed": sum(len(r["promos"]) + len(r["rejects"]) for r in results), "valid": len(promos), "rejected": len(rejects),
        "duplicates_dropped": len(dups), "ranked": len(final),
        "hallucinated_line_ids": {"count": sum(len(r["bad_refs"]) for r in results),
                                  "examples": sorted({x for r in results for x in r["bad_refs"]})[:10]},
        "stitch": {k: (dict(v) if isinstance(v, Counter) else v) for k, v in stitch.items()} |
                  {"in_top20": sum(p["type"] != "A" for p in final[:20])},
        "top10_patterns": dict(Counter(p.get("pattern") for p in final[:10])),
        "types_top40": dict(Counter(p["type"] for p in final)), "episodes_in_top40": len({p["episode"] for p in final}),
        "spoilers_in_top10": sum(bool(p.get("spoiler")) for p in final[:10]),
        "weak_openings_in_top10": sum(bool(p.get("weak_cold_open")) for p in final[:10]),
        "quality_4_top40": dict(sorted(Counter(p.get("quality_4") for p in final).items(), key=lambda kv: (kv[0] is None, kv[0] or 0))),
        "rank_llm_calls": rank_calls, "usage_this_run": usage, "cost_usd": cost(ledger, cfg.get("prices", {}), len(eps)),
        "seconds": round(time.time() - t0, 1)}
    save(os.path.join(out, "promos.json"), final)
    save(os.path.join(out, "rejected.json"), rejects)
    save(os.path.join(out, "run_stats.json"), stats)
    write_md(final, stats, os.path.join(out, "promos.md"))
    write_csv(final, os.path.join(out, "promos.csv"))
    print(f"\n{len(final)} ranked | {len(promos)} valid of {stats['proposed'] + sum(stitch['proposed'].values())} proposed | "
          f"{len(rejects)} rejected | {len(dups)} duplicates | {stats['seconds']}s\n-> {out}/")
    if not stats["complete"]:
        print(f"!! Incomplete (failed episodes {failed}, unscored {len(unscored)}). Run the same command again to finish.", file=sys.stderr)


def cost(ledger, prices, n_episodes):
    """Total USD over every run so far (models without a price are listed, never counted as $0)."""
    total, missing = 0.0, set()
    for e in ledger:
        p = prices.get(e["model"])
        if not p or p.get("in_per_m") is None: missing.add(e["model"]); continue
        total += e["prompt_tokens"] / 1e6 * p["in_per_m"] + e["completion_tokens"] / 1e6 * p["out_per_m"]
    return {"total": round(total, 4), "per_episode": round(total / max(1, n_episodes), 5), "missing_prices": sorted(missing)}


def segments(p):
    return " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in p["segments"])


def write_md(final, st, path):
    rows = [f"# Ranked promos - proposer {st['proposer']}, critic {st['critic']}\n",
            f"{st['ranked']} promos. {st['valid']} passed the code checks, {st['rejected']} rejected (rejected.json), "
            f"{st['duplicates_dropped']} duplicates dropped." + ("" if st["complete"] else " **Incomplete run - re-run to finish.**") + "\n"]
    for p in final:
        cv = p.get("cold_viewer") or {}
        rows += [f"## #{p['rank']} · {segments(p)} · {p['length_s']}s · type {p['type']} · quality {p.get('quality_4')}/4"
                 f" · {p.get('pattern', 'other')}" + (" · ⚠ spoiler" if p.get("spoiler") else ""),
                 f"- **Hook:** {p['hook']}", f"- **Cliffhanger:** {p['cliffhanger']}", f"- **Why it works:** {p['why']}"]
        if p.get("post_reason"): rows.append(f"- **Why post it at #{p['rank']}:** {p['post_reason']}")
        if p.get("quality_groups"): rows.append("- **Critic:** " + " · ".join(f"{'✅' if v else '❌'} {k}" for k, v in p["quality_groups"].items()))
        failed = [f"{k} ({v['reason']})" for k, v in (p.get("checks") or {}).items() if not v["pass"]]
        if failed: rows.append("- **Failed checks:** " + "; ".join(failed))
        if cv: rows.append(f"- **Cold viewer:** {cv.get('conflict_between') or '-'} · wants to know: {cv.get('want_to_know_next') or '-'}"
                           f" · keeps watching: {'yes' if cv.get('would_keep_watching') is True else 'no'}")
        if p.get("notes"): rows.append(f"- **Repairs:** {p['notes']}")
        rows.append("")
    open(path, "w").write("\n".join(rows))


def write_csv(final, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "id", "type", "segments", "length_s", "hook", "cliffhanger", "why", "post_reason", "quality_4",
                    "failed_checks", "pattern", "spoiler", "cold_viewer_keeps_watching", "repairs"])
        for p in final:
            w.writerow([p["rank"], p["id"], p["type"], segments(p), p["length_s"], p["hook"], p["cliffhanger"], p["why"],
                        p.get("post_reason", ""), p.get("quality_4"),
                        " | ".join(k for k, v in (p.get("checks") or {}).items() if not v["pass"]), p.get("pattern"),
                        p.get("spoiler"), (p.get("cold_viewer") or {}).get("would_keep_watching"), p.get("notes", "")])


if __name__ == "__main__":
    main()
