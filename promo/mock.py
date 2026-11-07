"""Offline stand-in for an LLM so the whole pipeline (and the tests) run without keys or network.
It answers every prompt type with something plausible. It is NOT a judge - it only exercises the plumbing.

  MOCK_FAIL_AFTER=n   calls after the n-th one fail (to test resuming after a quota stop); -1 = every call fails
  MOCK_EMPTY_EPS=2,5  the proposer returns no promos for these episodes
"""
import json, os, re, threading

LINE = re.compile(r"^\s*L(\d+) \[([\d.:]+)s?-([\d.:]+)s?\] ([^:]+):")
LOCK = threading.Lock()


class MockLLM:
    model = "mock"

    def __init__(self):
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "seconds": 0.0,
                      "cut_off_retries": 0, "json_repairs": 0, "dropped_params": []}
        self.fail_after = int(os.environ.get("MOCK_FAIL_AFTER", "0") or 0)

    def ask_json(self, system, user, expect=None):
        with LOCK:
            if self.fail_after < 0 or (self.fail_after and self.usage["calls"] >= self.fail_after):
                raise RuntimeError("mock: out of quota / no key")
            self.usage["calls"] += 1
            self.usage["prompt_tokens"] += (len(system) + len(user)) // 4; self.usage["completion_tokens"] += 50
        if user.startswith("LOGLINES:"):
            return {"premise": "mock premise", "known_by_ep5": "mock", "late_reveals": ["mock reveal"],
                    "characters": [{"name": "Juliana", "role": "heroine"}]}
        if user.startswith("CLIPS TO CHECK:"): return self.critic(user)
        if user.startswith("CLIP:"):
            n = len([l for l in user.splitlines() if re.match(r"^L\d+ ", l)])
            return {"what_is_happening": "mock", "conflict_between": "A vs B" if n >= 3 else "", "want_to_know_next": "?",
                    "would_keep_watching": n >= 3, "why": "mock"}
        if user.startswith("CANDIDATES:"):
            ids = [json.loads(l)["id"] for l in user.splitlines()[1:] if l.startswith("{")]
            return {"order": [{"id": i, "reason": "mock order"} for i in ids]}
        if user.startswith("STITCH"): return {"promos": self.stitch(user)}
        return self.propose(user)

    def propose(self, user):
        ep = re.search(r"^EPISODE (\d+)", user, re.M)
        if ep and ep.group(1) in os.environ.get("MOCK_EMPTY_EPS", "").split(","): return {"promos": []}
        lines = [m.groups() for l in user.splitlines() if (m := LINE.match(l))]
        end = next((l for l in lines if float(l[2]) >= 30), lines[-1])        # the first ~30 seconds
        return {"promos": [{"segments": [{"start_line": f"L{lines[0][0]}", "end_line": f"L{end[0]}"}],
                            "hook_line": f"L{lines[0][0]}", "cliff_line": f"L{end[0]}", "hook_strength": 3,
                            "cliff_strength": 3, "standalone": 3, "missing_context": "mock", "spoiler": False, "why": "mock"}]}

    def critic(self, user):
        from .prompts import PATTERNS
        late = re.search(r"LATE REVEALS \(spoilers\): (.*)", user)
        words = lambda s: re.findall(r"[a-z']+", s.lower())
        grams = {" ".join(w[i:i + 4]) for s in (late.group(1).split("|") if late else []) for w in [words(s)]
                 for i in range(len(w) - 3)}
        clips = []
        for k, block in enumerate(re.split(r"^### CLIP ", user, flags=re.M)[1:]):
            w = words(block)
            spoils = any(" ".join(w[i:i + 4]) in grams for i in range(len(w) - 3))     # repeats a late reveal
            checks = {c: {"pass": True, "reason": "mock"} for c in ("hook_conflict_no_context", "open_question_at_end",
                      "nothing_resolves_after_cliff", "standalone_understandable", "hook_in_rubric", "cliff_in_rubric")}
            checks["not_a_spoiler"] = {"pass": not (spoils or k % 4 == 3), "reason": "mock"}
            if "[cut" in block: checks["cuts_make_sense"] = {"pass": True, "reason": "mock"}
            clips.append({"id": block.split()[0], "checks": checks, "pattern": PATTERNS[k % 3],
                          "hook_type": "threat", "cliff_type": "unanswered_question"})
        return {"clips": clips}

    def stitch(self, user):
        """Join an opening stretch and a closing stretch (>= 8 s each) from the lines shown."""
        def stretch(lines, forward=True):
            seq, out = (lines if forward else lines[::-1]), []
            for l in seq:
                out.append(l)
                if abs(float(out[-1][2]) - float(out[0][1])) >= 8 or abs(float(out[0][2]) - float(out[-1][1])) >= 8: break
            return out if forward else out[::-1]
        if user.startswith("STITCH B"):
            lines = [m.groups() for l in user.split("TRANSCRIPT", 1)[-1].splitlines() if (m := LINE.match(l))]
            dialogue = [i for i, l in enumerate(lines) if l[3] not in ("ACTION", "SFX")]
            if len(lines) < 6 or not dialogue: return []
            a, b = stretch(lines[:12]), stretch(lines[:dialogue[-1] + 1][-12:], forward=False)
            if float(b[0][1]) - float(a[-1][2]) < 3: return []
            return [{"segments": [{"start_line": f"L{a[0][0]}", "end_line": f"L{a[-1][0]}"},
                                  {"start_line": f"L{b[0][0]}", "end_line": f"L{b[-1][0]}"}],
                     "hook_line": f"L{a[0][0]}", "cliff_line": f"L{b[-1][0]}", "pattern": "betrayal", "why": "mock B"}]
        parts = re.split(r"^- \[(\w+)\] episode (\d+) L(\d+)", user, flags=re.M)[1:]
        beats = [(parts[i], int(parts[i + 1]), int(parts[i + 2]), parts[i + 3]) for i in range(0, len(parts), 4)]
        first = next((b for b in beats if b[0] in ("setup", "hook")), None)
        later = next((b for b in beats if b[0] == "cliff" and first and b[1] > first[1]), None)
        if not first or not later: return []
        lo = [m.groups() for l in first[3].splitlines() if (m := LINE.match(l)) and int(m.group(1)) >= first[2]]
        lc = [m.groups() for l in later[3].splitlines() if (m := LINE.match(l)) and int(m.group(1)) <= later[2]]
        if not lo or not lc: return []
        a, b = stretch(lo), stretch(lc, forward=False)
        return [{"segments": [{"episode": first[1], "start_line": f"L{a[0][0]}", "end_line": f"L{a[-1][0]}"},
                              {"episode": later[1], "start_line": f"L{b[0][0]}", "end_line": f"L{b[-1][0]}"}],
                 "hook_line": {"episode": first[1], "line": f"L{a[0][0]}"},
                 "cliff_line": {"episode": later[1], "line": f"L{b[-1][0]}"}, "pattern": "humiliation_revenge", "why": "mock C"}]
