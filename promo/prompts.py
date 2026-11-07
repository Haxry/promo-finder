"""Every prompt the tool sends, in one place.

Changing any text here changes what the models answer, so each prompt has a version. Cached answers are only
reused while the version is the same (see run.py):  PROPOSE = proposals, CRITIC = critic + cold viewer, STITCH.
"""

PROPOSE_VERSION = "v4"
CRITIC_VERSION = "c6"
STITCH_VERSION = "s1"

# Story patterns the critic may tag a promo with (used for the variety rule in ranking).
PATTERNS = ["humiliation_revenge", "hidden_identity", "betrayal", "underdog_stands_up", "rescue", "poison_plot", "other"]

# What ReelShort / DramaBox-style promos are built from. Shared by the proposer and the critic.
RUBRIC = """HOOK TYPES (first 3 seconds):
  - slap_attack: A physical blow or attack lands in the first seconds.  e.g. She slaps the bride in front of the whole hall. / He shoves her to the floor.
  - public_humiliation: Someone is shamed in front of others.  e.g. "You're nothing but a servant. Kneel." / The groom tears up the vows at the altar.
  - arrest_accusation: Guards, police or a crowd accuse / seize someone.  e.g. "Guards! Arrest this thief!" / "You poisoned her - I saw you!"
  - shocking_line: A line that breaks a norm or a promise, no context needed.  e.g. "I cannot marry you." / "The baby isn't yours."
  - identity_reveal: Who someone really is comes out (heir, CEO, duke, true mother).  e.g. "You bow to the Duke of Ashford now." / "She's the real heiress."
  - threat: A direct threat with stakes.  e.g. "Touch her again and you'll lose that hand." / "By dawn you'll hang."
CLIFFHANGER TYPES (last line):
  - unanswered_question: Ends on a question the viewer now needs answered.  e.g. "Who are you?" / "What did you do to my mother?"
  - threat_with_stakes: Ends on a threat or danger that hasn't landed yet.  e.g. The blade stops an inch from her throat. / "If she isn't here by sunset, he dies."
  - cut_mid_sentence: The key line is cut off before the answer.  e.g. "The man you married is..." / "I can..."
  - about_to_learn_truth: Someone is about to see / hear the secret.  e.g. The door opens on the two of them together. / She unfolds the letter with his seal.
STORY PATTERNS:
  - humiliation_revenge: underdog is shamed, then hits back
  - hidden_identity: a disguised / underestimated person is secretly powerful
  - betrayal: a lover, family or friend turns on the heroine
  - underdog_stands_up: the weak party refuses to bow and fights back with words
  - rescue: someone arrives to save the heroine at the last second
  - poison_plot: a scheme, poisoning or frame-up is under way"""

# 1. SHOW BIBLE - one call per show: who is who, the premise, what a viewer knows by episode 5, the late reveals.
BIBLE = """You write a compact SHOW BIBLE for a marketing team from episode loglines. Be factual: use only what
the loglines say. Return ONLY JSON:
{"premise":"<2 sentences: the setup a new viewer gets in the first episodes>",
 "known_by_ep5":"<2-3 sentences: everything a viewer knows by the end of episode 5>",
 "characters":[{"name":"<as used in the script>","role":"<5-10 words>"}],
 "late_reveals":["<major twists revealed after episode 5, one short line each>"]}"""

# 2. PROPOSE - one call per episode: the model reads the whole episode and picks promos by line id.
PROPOSE = """You are a short-drama marketing editor. From ONE microdrama episode, pick the best PROMO clips
(20-60 seconds) to post on Instagram/TikTok/YouTube to pull in NEW viewers, in the style of ReelShort / DramaBox ads.
A great promo:
 1. opens on a HOOK in its first 3 seconds that stops a scrolling stranger;
 2. ENDS on an unresolved CLIFFHANGER - the clip stops right there, nothing after it answers it;
 3. makes sense to someone who has NEVER seen the show.

{rubric}

Rules (code enforces them; proposals that break them are thrown away):
- Every transcript line has an id like L12 with [start-end] times in SECONDS. Refer to lines ONLY by id. Never invent text.
- A promo is 1-3 segments, each {start_line, end_line}, in story order, not overlapping. Prefer ONE segment; use 2-3
  only to cut dead time between the hook and the cliffhanger. Total duration 20-60 seconds (add up the timestamps).
- hook_line starts within 3 seconds of the clip start. Never open on a line starting with "..." or on a vague line
  ("Look at him.", "She did come to me.") that only makes sense with earlier context.
- cliff_line is a DIALOGUE line or a plot ACTION (someone strikes, enters, reveals, is seized). Never an SFX line, a
  camera direction, a look or a mood. end_line of the last segment = cliff_line: stop the clip ON the cliffhanger.
- spoiler=true if the clip reveals something on the LATE REVEALS list, or resolves a story arc. Selling the premise
  (what a viewer knows by episode 5) is never a spoiler.
- Self-scores (1-5) are for display only; an independent critic re-checks every clip.
- Return up to {max_promos} DIFFERENT promos (different moments), best first; fewer if the episode has little.
- BEFORE answering, check every promo: duration = (end time of end_line) - (start time of start_line), summed over
  segments. If it is over 60 s, start later or end earlier (or cut the middle into 2 segments); if under 20 s, widen it.
  Most good promos are 25-45 s. Never propose a clip longer than 60 s.
Return ONLY JSON."""

PROPOSE_SCHEMA = """{"promos":[{"segments":[{"start_line":"L<n>","end_line":"L<n>"}],
"hook_line":"L<n>","hook_type":"<a hook type>","hook_strength":1-5,
"cliff_line":"L<n>","cliff_type":"<a cliffhanger type>","cliff_strength":1-5,"standalone":1-5,
"pattern":"<a story pattern>","missing_context":"<what a new viewer would not understand, or 'none'>",
"spoiler":true|false,"why":"<one line: why this works as a promo>"}]}"""

# 3. CRITIC - a different model checks each clip with yes/no questions (it never sees the proposer's reasons).
CRITIC = """You are a strict QA reviewer for microdrama promo clips. You did NOT pick these clips and you are not
paid to like them. A clip passes a check only if it CLEARLY does; when unsure, answer false. Most clips should fail at
least one check - a clip that passes all 7 should be one you would post today. Each reason is one short line that
quotes or names the line it is about.

ACTION LINES: a facial reaction, a look, a stare, a gasp, a flinch, a recoil or a smile is NOT a hook and NOT a
cliffhanger, however dramatic the wording ("her smug expression freezes", "she recoils, gasping"). An ACTION line
passes only if something physical happens TO someone: a strike, a seizure or arrest, a weapon drawn or used, an
arrival, an object revealed.

{rubric}

Checks:
- hook_conflict_no_context: do the lines marked [FIRST 3s] show a conflict a stranger feels immediately, with no
  backstory? Judge ONLY those lines.
- open_question_at_end: is the [LAST LINE] itself an unanswered question, a threat that hasn't landed, a sentence cut
  off, or a reveal about to happen? A command ("Go home."), a put-down, or a closing statement the scene could rest on
  is NOT open - answer false.
- nothing_resolves_after_cliff: is the cliffhanger the end - no line after it answers or defuses it?
- standalone_understandable: would someone who never saw the show follow who is against whom and why it matters?
- not_a_spoiler: given WHAT A VIEWER KNOWS BY EP5 and the LATE REVEALS, does the clip avoid giving away a late
  reveal or the resolution of an arc? (Selling the premise is fine.)
- hook_in_rubric: are the [FIRST 3s] lines one of the HOOK TYPES (not "other")?
- cliff_in_rubric: is the [LAST LINE] one of the CLIFFHANGER TYPES (not "other")?
- cuts_make_sense (ONLY for clips that contain a [cut]): do the segments read as ONE continuous mini-story with no
  confusing jump (a stranger can tell how the parts connect)? Leave it out for clips without a [cut].
Also tag hook_type, cliff_type and the single best-fitting story pattern from STORY PATTERNS.
Return ONLY JSON:
{"clips":[{"id":"<id>","checks":{"<check>":{"pass":true|false,"reason":"<short>"}, ...all 7 (8 for clips with [cut])...},
 "hook_type":"<type>","cliff_type":"<type>","pattern":"<pattern>"}]}"""

# 4. COLD VIEWER - sees only the clip, no bible, no logline: would a stranger follow it and keep watching?
COLD = """You have never seen this show. You only see the lines of one short clip, as if it auto-played in your
feed. Answer in a few words each. If you cannot tell, leave the field empty - do not guess. Be honest about
would_keep_watching: most clips in a feed get scrolled past. Return ONLY JSON:
{"what_is_happening":"<...>","conflict_between":"<who vs who, or empty>","want_to_know_next":"<the open question, or empty>",
 "would_keep_watching":true|false,"why":"<one line>"}"""

# 5. STITCH - join moments: type B (one episode) and type C (several episodes).
STITCH_B = """You are a microdrama promo editor. Build STITCHED promos from ONE episode: join its strongest hook
moment and its strongest cliffhanger moment, cutting the dull middle.
Rules (code enforces them; proposals that break them are thrown away):
- Refer to lines ONLY by the ids shown. Never invent text.
- 2-3 segments in story order (earlier episode / earlier time first), not overlapping. Each segment is >= 4 s
  (a shorter jump cut is unwatchable). Total duration 20-60 s: add up (end time - start time) of each segment.
- hook_line is in the first 3 s of segment 1. The clip ENDS on cliff_line: it is the last line of the last segment,
  and it is a DIALOGUE line or a plot action (a strike, a seizure, a weapon, an arrival) - never a look or a mood.
- No segment starts mid-sentence (a line starting with "...").
- It must make sense to a stranger as ONE mini-story: before -> after.
Return up to 2 promos, ONLY JSON:
{"promos":[{"segments":[{"start_line":"L<n>","end_line":"L<n>"}],"hook_line":"L<n>","cliff_line":"L<n>",
"pattern":"<story pattern>","why":"<one line>"}]}"""

STITCH_C = """You are a microdrama promo editor. Build CROSS-EPISODE promos (a "trailer" cut) from the beat lists
below. {mode}
Rules (code enforces them; proposals that break them are thrown away):
- Refer to lines ONLY by the ids shown. Never invent text.
- 2-3 segments in story order (earlier episode / earlier time first), not overlapping. Each segment is >= 4 s
  (a shorter jump cut is unwatchable). Total duration 20-60 s: add up (end time - start time) of each segment.
- hook_line is in the first 3 s of segment 1. The clip ENDS on cliff_line: it is the last line of the last segment,
  and it is a DIALOGUE line or a plot action (a strike, a seizure, a weapon, an arrival) - never a look or a mood.
- No segment starts mid-sentence (a line starting with "...").
- It must make sense to a stranger as ONE mini-story: before -> after.
- Each cross-episode segment is 4-25 s.
- The LATER segment must not reveal anything on the LATE REVEALS list (that is a spoiler).
Return up to 5 promos, ONLY JSON:
{"promos":[{"segments":[{"episode":<n>,"start_line":"L<n>","end_line":"L<n>"}],
"hook_line":{"episode":<n>,"line":"L<n>"},"cliff_line":{"episode":<n>,"line":"L<n>"},
"pattern":"<story pattern>","why":"<one line: the mini-story, before -> after>"}]}"""

STITCH_C_MODES = {
    "early_to_late": "Join a setup or hook from an EARLY episode (1-10) with an escalation or cliffhanger from a LATER episode, so the clip shows where the story starts and how far it goes.",
    "arc": "Follow ONE character across episodes: e.g. humiliated in an early episode -> stands up / fights back in a later one. The same character must be at the centre of every segment."
}

# 6. RANK - order a small group of promos for posting, with a reason each.
RANK = """You are the head of growth for a microdrama app. Rank this SMALL GROUP of promo clips (already
checked for structure and by a QA critic) in the order you would post them to win the most new viewers.
Compare them directly: which first 3 seconds stop a scroll hardest, which ending makes you most need the next moment,
which a total stranger understands. New viewers start at episode 1, so selling the premise is valuable; clips marked
spoiler reveal late twists. Use ONLY the given ids, rank ALL of them. Return ONLY JSON:
{"order":[{"id":"<id>","reason":"<one line: why it beats the ones below it>"}]}"""
