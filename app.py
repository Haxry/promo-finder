"""The editor's screen:   .venv/bin/streamlit run app.py

Tabs: Best promos (review them: Post / Maybe / Skip) · Where it struggles · Read an episode · How it works
"""
import collections, csv, glob, html, json, os, re
import streamlit as st
from promo.parse import parse_file, transcript
from promo.validate import validate, character_names
from promo.critic import clip_text

HERE = os.path.dirname(os.path.abspath(__file__))
st.set_page_config(page_title="Promo Finder", page_icon="🎬", layout="wide")

# ---- plain-language names ---------------------------------------------------------------------------------------
CHECKS = {"hook": "Strong opening", "ending": "Open ending", "standalone": "Makes sense alone", "not_a_spoiler": "No spoiler"}
TYPES = {"A": "Single clip", "B": "2–3 moments joined (same episode)", "C": "Moments from different episodes"}
DECISIONS = {"not reviewed": "–", "post": "👍 Post", "maybe": "🤔 Maybe", "skip": "👎 Skip"}
REJECT_GROUPS = [   # (words in the technical reason, plain title, plain explanation)
    ("total length", "Wrong length", "The clip was shorter than 20 s or longer than 60 s, and could not be fixed."),
    ("cliffhanger", "Bad ending", "The ending was missing, in the wrong place, or only a sound / a look."),
    ("hook", "Hook not at the start", "The hook was not in the first 3 seconds, and moving the start did not help."),
    ("does not exist|not a real line", "Made-up line number", "The AI named a line that is not in the script."),
    ("mid-sentence", "Starts mid-sentence", "The clip would open in the middle of a sentence."),
    ("duplicate", "Same moment twice", "A joined promo repeated a moment that a better promo already uses."),
    ("segment", "Bad cut", "The pieces of a joined promo were out of order, overlapping or too short."),
]

st.markdown("""
<style>
  .block-container {padding-top: 2.4rem; max-width: 1180px;}
  .hero {background: linear-gradient(135deg, #eef2ff 0%, #f8fafc 100%); border: 1px solid #e0e7ff; border-radius: 16px;
         padding: 22px 26px; margin-bottom: 18px;}
  .hero h1 {margin: 0 0 6px 0; font-size: 2.1rem; color: #1e1b4b;}
  .hero p {margin: 0; font-size: 1.08rem; color: #374151;}
  .card {border: 1px solid #e5e7eb; border-radius: 14px; padding: 18px 22px 14px 22px; margin: 6px 0 4px 0;
         background: #ffffff; box-shadow: 0 1px 3px rgba(15, 23, 42, .06);}
  .card-top {display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 10px;}
  .rank {background: #4f46e5; color: #fff; font-weight: 800; font-size: 1.15rem; border-radius: 10px; padding: 4px 12px;}
  .where {font-size: 1.15rem; font-weight: 700; color: #111827;}
  .pill {font-size: .85rem; padding: 3px 10px; border-radius: 999px; background: #f1f5f9; color: #334155; font-weight: 600;}
  .pill.warn {background: #fef3c7; color: #92400e;}
  .score {margin-left: auto; font-weight: 800; font-size: 1.05rem; padding: 4px 12px; border-radius: 10px;}
  .s4 {background: #dcfce7; color: #166534;} .s3 {background: #e0f2fe; color: #075985;}
  .s2 {background: #fef3c7; color: #92400e;} .s1, .s0 {background: #fee2e2; color: #991b1b;}
  .line {border-radius: 10px; padding: 10px 14px; margin: 8px 0; font-size: 1.06rem; line-height: 1.5;}
  .line b {display: block; font-size: .78rem; letter-spacing: .06em; text-transform: uppercase; margin-bottom: 2px;}
  .hook {background: #ecfdf5; border-left: 5px solid #10b981;} .hook b {color: #047857;}
  .cliff {background: #eff6ff; border-left: 5px solid #3b82f6;} .cliff b {color: #1d4ed8;}
  .why {font-size: 1.0rem; color: #374151; margin: 6px 0 2px 0; line-height: 1.55;}
  .checks {margin-top: 8px; font-size: .95rem; color: #374151;}
  .checks span {margin-right: 14px; white-space: nowrap;}
  .script {font-family: ui-monospace, Menlo, monospace; font-size: .92rem; background: #f8fafc; border-radius: 8px;
           padding: 10px 12px; white-space: pre-wrap; line-height: 1.5; color: #1f2937;}
  .howto {background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px 18px; font-size: 1.0rem;}
  div[data-testid="stMetricValue"] {font-size: 2.0rem; color: #1e1b4b;}
  div[data-testid="stMetricLabel"] p {font-size: 1.0rem;}
  .stTabs [role="tab"] p, .stTabs [role="tab"] div {font-size: 1.15rem !important; font-weight: 700;}
  .stTabs [role="tab"] {padding: 10px 18px 10px 0;}
  div[data-testid="stExpander"] summary p {font-size: 1.02rem;}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def episodes(folder):
    return {e.number: e for e in (parse_file(f) for f in sorted(glob.glob(os.path.join(folder, "*.txt"))))}


def load(path, default):
    try: return json.load(open(path))
    except (OSError, ValueError): return default


def esc(text):
    return html.escape(str(text or ""))


def where(p):
    return " + ".join(f"Episode {s['episode']} · {s['start'][:5]}–{s['end'][:5]}" for s in p["segments"])


# ---- sidebar: which results to show -----------------------------------------------------------------------------
st.sidebar.markdown("## 🎬 Promo Finder")
folder = st.sidebar.text_input("Screenplay folder", next(iter(glob.glob(os.path.join(os.path.dirname(HERE), "I Married*"))), ""))
runs = sorted(d for d in glob.glob(os.path.join(HERE, "outputs", "*"))
              if load(os.path.join(d, "promos.json"), []) and not os.path.basename(d).startswith("_"))
if not runs or not os.path.isdir(folder):
    st.warning("No results yet. Run `python3 run.py --input <screenplay folder>` first, then reload this page.")
    st.stop()
run = st.sidebar.selectbox("Results from", runs, format_func=lambda d: os.path.basename(d).replace("__", " · "))
show_n = st.sidebar.select_slider("Show the top", [10, 20, 40], value=20)
only_open = st.sidebar.checkbox("Only promos I have not reviewed yet")

eps = episodes(folder)
promos, rejects, stats = load(f"{run}/promos.json", []), load(f"{run}/rejected.json", []), load(f"{run}/run_stats.json", {})
review_path = os.path.join(run, "review.csv")
review = {r["promo_id"]: r["decision"] for r in csv.DictReader(open(review_path))} if os.path.exists(review_path) else {}
st.sidebar.caption(f"Found by **{stats.get('proposer', '?')}**, checked by **{stats.get('critic', '?')}**.")
done = collections.Counter(d for d in review.values() if d != "not reviewed")
if done:
    st.sidebar.markdown("**Your review so far**  \n" + "  \n".join(f"{DECISIONS[k]}: {v}" for k, v in done.items()))


def save_review():
    with open(review_path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["promo_id", "where", "decision"])
        for p in promos:
            w.writerow([p["id"], where(p), st.session_state.get(f"rv_{p['id']}", review.get(p["id"], "not reviewed"))])


# ---- header: what this is + the key numbers ---------------------------------------------------------------------
st.markdown("""<div class="hero"><h1>🎬 Promo Finder</h1>
<p>An AI read every episode of the show and picked short clips (20–60 s) to post on Instagram, TikTok and YouTube.
Each clip <b>opens with a hook</b> that stops scrolling and <b>ends on a cliffhanger</b>. A second AI checked every
clip, and the best ones are listed first. <b>Your job:</b> mark each clip Post, Maybe or Skip.</p></div>""",
            unsafe_allow_html=True)
scored = [p["quality_4"] for p in promos if p.get("quality_4") is not None]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Promos found", len(promos))
c2.metric("Episodes they come from", len({s["episode"] for p in promos for s in p["segments"]}))
c3.metric("Average quality", f"{sum(scored) / len(scored):.1f} / 4" if scored else "–")
c4.metric("Ideas thrown away", len(rejects), help="Clips the code rejected because they broke a rule (see 'Where it struggles').")

tab_best, tab_bad, tab_ep, tab_how = st.tabs(["🏆 Best promos", "⚠️ Where it struggles", "📄 Read an episode", "ℹ️ How it works"])

# ---- 1. best promos ---------------------------------------------------------------------------------------------
with tab_best:
    st.markdown("""<div class="howto"><b>How to read a card:</b> the number is the rank (1 = post first).
    <span style="color:#047857"><b>Green</b></span> = how the clip opens (the hook),
    <span style="color:#1d4ed8"><b>blue</b></span> = how it ends (the cliffhanger).
    The score (out of 4) counts the AI checker's ticks: strong opening, open ending, makes sense alone, no spoiler.
    Open <b>See the script</b> to read the whole clip.</div>""", unsafe_allow_html=True)
    shown = [p for p in promos[:show_n] if not (only_open and review.get(p["id"], "not reviewed") != "not reviewed")]
    if not shown: st.info("Nothing to show with these filters.")
    for p in shown:
        q = p.get("quality_4")
        groups = p.get("quality_groups") or {}
        pills = f'<span class="pill">{TYPES.get(p.get("type", "A"))}</span><span class="pill">{p["length_s"]:.0f} s</span>'
        if p.get("spoiler"): pills += '<span class="pill warn">⚠ may spoil a twist</span>'
        ticks = "".join(f"<span>{'✅' if groups.get(k) else '❌'} {name}</span>" for k, name in CHECKS.items())
        post = f'<div class="why"><b>Why post it at #{p["rank"]}:</b> {esc(p["post_reason"])}</div>' if p.get("post_reason") else ""
        st.markdown(f"""<div class="card">
          <div class="card-top"><span class="rank">#{p['rank']}</span><span class="where">{esc(where(p))}</span>{pills}
            <span class="score s{q if q is not None else 0}">Score {q if q is not None else '–'} / 4</span></div>
          <div class="line hook"><b>Opens with (hook)</b>{esc(p['hook'])}</div>
          <div class="line cliff"><b>Ends on (cliffhanger)</b>{esc(p['cliffhanger'])}</div>
          <div class="why"><b>Why it works:</b> {esc(p['why'])}</div>{post}
          <div class="checks">{ticks}</div></div>""", unsafe_allow_html=True)
        left, right = st.columns([3, 2])
        right.radio("Your decision", list(DECISIONS), format_func=DECISIONS.get, horizontal=True, key=f"rv_{p['id']}",
                    index=list(DECISIONS).index(review.get(p["id"], "not reviewed")), on_change=save_review)
        with left.expander("See the script of this clip, and the checker's notes"):
            st.markdown(f'<div class="script">{esc(clip_text(eps, p))}</div>', unsafe_allow_html=True)
            for k, v in (p.get("checks") or {}).items():
                st.markdown(f"{'✅' if v['pass'] else '❌'} **{k.replace('_', ' ')}** — {v['reason']}")
            cv = p.get("cold_viewer") or {}
            if cv:
                st.markdown(f"**A stranger who saw only this clip** · sees a conflict between: *{cv.get('conflict_between') or '—'}* · "
                            f"wants to know: *{cv.get('want_to_know_next') or '—'}* · would keep watching: "
                            f"{'yes' if cv.get('would_keep_watching') is True else 'no'}")
            if p.get("notes"): st.markdown(f"**Small fixes made by the code:** {p['notes']}")

# ---- 2. where it struggles --------------------------------------------------------------------------------------
with tab_bad:
    st.markdown("### Ideas the code threw away")
    st.write("The AI suggests clips; plain code then checks the rules. These suggestions broke a rule that could not be fixed.")
    left_over = list(rejects)
    for pattern, title, explain in REJECT_GROUPS:
        group = [r for r in left_over if re.search(pattern, r["reason"], re.I)]
        left_over = [r for r in left_over if r not in group]
        if group:
            with st.expander(f"{title} — {len(group)}"):
                st.write(explain)
                for r in group:
                    st.markdown(f"- Episode {r['episode']}: <span style='color:#6b7280'>{esc(r['reason'])}</span>", unsafe_allow_html=True)
    if left_over:
        with st.expander(f"Other — {len(left_over)}"):
            for r in left_over: st.markdown(f"- Episode {r['episode']}: {esc(r['reason'])}")
    st.markdown("### Weak promos in the list")
    weak = [p for p in promos if (p.get("quality_4") or 0) <= 2]
    st.write(f"{len(weak)} of the {len(promos)} listed promos scored 2 / 4 or less. What they missed:")
    for p in weak:
        missed = [CHECKS[k] for k, v in (p.get("quality_groups") or {}).items() if not v]
        st.markdown(f"- **#{p['rank']}** {esc(where(p))} — missing: {', '.join(missed)}")
    disagree = [p for p in promos if review.get(p["id"]) == "skip" and (p.get("quality_4") or 0) >= 3]
    if disagree:
        st.markdown("### The AI liked these, you skipped them")
        for p in disagree: st.markdown(f"- **#{p['rank']}** {esc(where(p))} — opens with: {esc(p['hook'][:80])}")

# ---- 3. read an episode -----------------------------------------------------------------------------------------
with tab_ep:
    n = st.selectbox("Episode", sorted(eps), format_func=lambda x: f"Episode {x}")
    ep = eps[n]
    st.markdown(f"**{ep.duration:.0f} seconds** — {esc(ep.logline)}")
    names = character_names(load(f"{run}/bible.json", {}), eps.values())
    props = load(f"{run}/raw_llm/ep{n:02d}.json", {}).get("proposals", [])
    st.markdown(f"#### The AI suggested {len(props)} clip(s) in this episode")
    for j in props:
        p, why = validate(ep, j, names, eps)
        if p: st.success(f"Kept: {where(p)} ({p['length_s']:.0f} s)" + (f" — small fixes: {p['notes']}" if p["notes"] else ""))
        else: st.error(f"Thrown away: {why}")
    with st.expander("Read the full script (each line has a number like L12 — the AI picks clips by these numbers)"):
        st.markdown(f'<div class="script">{esc(transcript(ep))}</div>', unsafe_allow_html=True)

# ---- 4. how it works --------------------------------------------------------------------------------------------
with tab_how:
    st.markdown("""
### How the promos were found

1. **Read** — the code turns every script into numbered lines (L1, L2, …), each with a start and end time.
2. **Find** — an AI model reads one episode at a time and suggests clips by line number (it never writes times or text,
   so it cannot invent them).
3. **Check** — plain code checks the rules: 20–60 seconds, the hook in the first 3 seconds, the clip ends exactly on the
   cliffhanger. Small mistakes are fixed; the rest are thrown away (see *Where it struggles*).
4. **Judge** — a **second, different** AI checks every clip with four yes/no questions → the score out of 4. A "fresh
   viewer" sees only the clip and says if they would keep watching.
5. **Join** — some promos join 2–3 strong moments, from one episode or from different episodes.
6. **Rank** — highest score first; the AI then explains why to post each one first.

### Words used here

| Word | Meaning |
|---|---|
| **Hook** | the first 3 seconds — what makes someone stop scrolling |
| **Cliffhanger** | the last line — an open question or threat, so the viewer wants more |
| **Score / 4** | how many of the 4 checks the second AI ticked |
| **Spoiler** | the clip gives away a twist from late in the show |
| **Thrown away** | a suggestion that broke a rule the code could not fix |
""")
