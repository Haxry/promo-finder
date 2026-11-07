"""Read a screenplay .txt file into an Episode: a list of timed lines (camera, action, sound, dialogue).

A line's position in ep.events is its id: the model refers to "L12" and code looks up ep.events[12]."""
import re
from dataclasses import dataclass, field

TIMES = re.compile(r"^Start:\s*\((\d+):(\d{2})\.(\d{2})\)\s*\|\s*End:\s*\((\d+):(\d{2})\.(\d{2})\)\s*$")
HEADER = re.compile(r"^\*\*(?P<label>[^*]+?)\s*:\*\*\s*$")          # **CAMERA:**  **JULIANA (Cold):**


@dataclass
class Event:
    kind: str            # camera | action | sound | dialogue
    start: float         # seconds
    end: float
    text: str
    speaker: str = ""
    emotion: str = ""
    scene: int = 0


@dataclass
class Episode:
    number: int
    logline: str = ""
    continuity: str = ""
    scenes: list = field(default_factory=list)    # [{"id", "heading", "start", "end"}]
    events: list = field(default_factory=list)

    @property
    def duration(self):
        return max((s["end"] for s in self.scenes), default=0.0)


def seconds(m, i):
    return int(m.group(i)) * 60 + int(m.group(i + 1)) + int(m.group(i + 2)) / 100


def kind_of(label):
    upper = label.upper()
    for kind in ("CAMERA", "ACTION", "SOUND"):
        if upper.startswith(kind): return kind.lower(), "", ""
    m = re.match(r"^(.*?)\s*(?:\((.*)\))?$", label.strip())         # SPEAKER (emotion)
    return "dialogue", m.group(1).strip().title(), (m.group(2) or "").strip()


def parse_file(path):
    ep, scene, cur = Episode(number=0), None, None
    for line in open(path, encoding="utf-8").read().splitlines():
        s = line.strip()
        low = s.lower()
        if s.startswith("EPISODE NUMBER:"): ep.number = int(re.search(r"\d+", s).group())
        elif s.startswith("EPISODE LOGLINE:"): ep.logline = s.split(":", 1)[1].strip()
        elif s.startswith("CONTINUITY NOTES:"): ep.continuity = s.split(":", 1)[1].strip()
        elif re.match(r"^SCENE \d+", s):
            scene = {"id": int(re.search(r"\d+", s).group()), "heading": "", "start": 0.0, "end": 0.0}
            ep.scenes.append(scene)
        elif scene is not None and low.startswith("scene heading:"): scene["heading"] = s.split(":", 1)[1].strip()
        elif scene is not None and (low.startswith("scene start:") or low.startswith("scene end:")):
            m = re.search(r"(\d+):(\d{2})\.(\d{2})", s)
            scene["start" if "start" in low else "end"] = seconds(m, 1)
        elif HEADER.match(s):
            kind, speaker, emotion = kind_of(HEADER.match(s).group("label"))
            cur = Event(kind, 0, 0, "", speaker, emotion, scene["id"] if scene else 0)
            ep.events.append(cur)
        elif cur is not None and TIMES.match(s):
            m = TIMES.match(s)
            cur.start, cur.end = seconds(m, 1), seconds(m, 4)
        elif s and cur is not None and not s.startswith("---") and not low.startswith("actions and dialogue"):
            cur.text = (cur.text + " " + s).strip()
    ep.events = sorted((e for e in ep.events if e.text), key=lambda e: (e.start, e.end))
    return ep


# ---- small helpers used everywhere ------------------------------------------------------------------------------
def mmss(x):
    return f"{int(x // 60):02d}:{x % 60:05.2f}"


def story_lines(ep):
    """Lines a clip can start or end on (dialogue and action; camera and sound cues are not story)."""
    return [e for e in ep.events if e.kind in ("dialogue", "action")]


def is_continuation(e):
    """A line that continues an earlier sentence ('...and then') - never open a clip on it."""
    s = e.text.lstrip('"\' ')
    return s.startswith(("...", "…")) or (s[:1].islower() and e.kind == "dialogue")


def transcript(ep, start=0.0, end=None, secs=False):
    """The lines between start and end as 'L12 [01:13.10-01:14.30] JULIANA (Cold): text' (camera lines skipped).
    secs=True prints times as plain seconds, which a model subtracts more reliably."""
    end = ep.duration + 1 if end is None else end
    out = []
    for i, e in enumerate(ep.events):
        if e.end <= start + 0.01 or e.start >= end - 0.01 or e.kind == "camera": continue
        tag = {"dialogue": e.speaker + (f" ({e.emotion})" if e.emotion else ""), "action": "ACTION", "sound": "SFX"}[e.kind]
        tm = f"{e.start:.1f}s-{e.end:.1f}s" if secs else f"{mmss(e.start)}-{mmss(e.end)}"
        out.append(f"L{i} [{tm}] {tag}: {e.text}")
    return "\n".join(out)
