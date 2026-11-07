"""Whole runs with the offline mock model: outputs, resume after a failure, empty answers, stitched promos."""
import json, os, subprocess, sys
from conftest import ROOT, SHOW
import pytest


def run(out, *args, env=None):
    if not SHOW: pytest.skip("input pack not found")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "run.py"), "--input", SHOW, "--model", "mock", "--out", str(out),
                        "--workers", "1", *args], capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    folder = out / "mock__mock__v4"
    return folder, json.load(open(folder / "run_stats.json")), r


def test_end_to_end_outputs(tmp_path):
    d, st, _ = run(tmp_path, "--episodes", "1-6")
    assert st["complete"] and st["valid"] > 0 and st["stitch"]["calls"] >= 1
    for f in ("promos.json", "promos.md", "promos.csv", "rejected.json", "run_stats.json", "bible.json", "usage_ledger.json"):
        assert (d / f).exists()
    P = json.load(open(d / "promos.json"))
    assert [p["rank"] for p in P] == list(range(1, len(P) + 1)) and all(p.get("post_reason") is not None for p in P)
    assert {p["type"] for p in P} <= {"A", "B", "C"}


def test_failure_then_resume(tmp_path):
    d, st, r = run(tmp_path, "--episodes", "1-4", env={"MOCK_FAIL_AFTER": "3"})      # quota runs out mid-run
    assert not st["complete"] and st["failed_episodes"] and "again" in r.stderr
    d, st, _ = run(tmp_path, "--episodes", "1-4")                                     # same command finishes the job
    assert st["complete"] and len(list((d / "raw_llm").glob("ep*.json"))) == 4


def test_empty_answer_retried_and_reasked(tmp_path):
    d, st, _ = run(tmp_path, "--episodes", "1-3", env={"MOCK_EMPTY_EPS": "2"})
    assert st["empty_episodes"] == [2] and json.load(open(d / "raw_llm" / "ep02.json"))["proposals"] == []
    d, st, _ = run(tmp_path, "--episodes", "1-3")                                     # asked again next time
    assert st["empty_episodes"] == []


def test_cached_rerun_makes_no_calls(tmp_path):
    run(tmp_path, "--episodes", "1-4")
    d, st, _ = run(tmp_path, "--episodes", "1-4")
    assert st["usage_this_run"]["mock"]["calls"] == 0


def test_editor_review_feeds_the_score(tmp_path):
    d, st, _ = run(tmp_path, "--episodes", "1-4")
    P = json.load(open(d / "promos.json"))
    with open(d / "review.csv", "w") as f:                                            # what the app writes
        f.write("promo_id,where,decision\n" + "".join(f"{p['id']},x,{'post' if i % 2 == 0 else 'skip'}\n" for i, p in enumerate(P)))
    import eval.score as score
    reviews = [(score.spans(p), "post" if i % 2 == 0 else "skip") for i, p in enumerate(P)]
    from promo.parse import parse_file
    import glob
    eps = {e.number: e for e in (parse_file(f) for f in sorted(glob.glob(os.path.join(SHOW, "*.txt"))))}
    res = score.score_run(str(d), reviews, eps)
    assert res["p@10"].startswith("50%") and res["after_cliff"] == 0


def test_cached_run_without_any_key_still_works(tmp_path):
    run(tmp_path, "--episodes", "1-3", env={"MOCK_EMPTY_EPS": "2"})                  # ep 2 cached as empty
    d, st, _ = run(tmp_path, "--episodes", "1-3", env={"MOCK_FAIL_AFTER": "-1", "MOCK_EMPTY_EPS": "2"})   # every call fails
    assert st["complete"] and st["empty_episodes"] == [2] and st["failed_episodes"] == []
