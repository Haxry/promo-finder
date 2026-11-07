# Promo Finder — Solution Doc (Problem 1: Find the Promos)

## 1. Why this problem
I picked **Problem 1** because it is the closest to a real, repeated job at Kuku: today an editor watches every episode to pick promo moments, and new shows arrive every week. The input pack let me test on a real 50-episode show, and the output is easy to check: a clip either opens on a hook, ends on a cliffhanger and stays within 20–60 s, or it does not. That made it possible to measure quality instead of guessing.

## 2. Assumptions (where the brief was silent)
- **Script timestamps match the final cut**, and clips are cut at line boundaries (no half lines).
- A promo is **1–3 segments**: one continuous clip (type A), moments joined from one episode (B) or from several (C).
- **Hook = what happens in the first 3 s; cliffhanger = the last line.** A look, a gasp or a music sting is not a cliffhanger.
- **Spoiler = a twist revealed after episode 5.** Selling the premise (episodes 1–5) is fine — new viewers start there.
- **Post-first order:** best quality first; among equals, a clean opening, no spoiler and earlier episodes win.
- Hooks are judged from the script text only (I cannot see faces or costumes).

## 3. How it works
1. **Read (code):** each screenplay becomes numbered lines (L12 …) with start/end times.
2. **Find (AI #1, gpt-oss-120b):** reads one whole episode plus a short "show bible" (who is who, which twists come late) and proposes up to 6 promos **by line number only** — it never writes times or dialogue, so it cannot invent them.
3. **Check (code):** enforces the brief and repairs near-misses: 20–60 s (cut one middle line or add a setup line), hook in the first 3 s (move the start), end exactly on the cliffhanger (trim), no sound cue / reaction shot as cliffhanger, real line numbers only. Everything else is rejected with a reason.
4. **Judge (AI #2, DeepSeek V3.2 — a different model):** yes/no checks, 2–3 votes per clip → **score 0–4** (strong opening, open ending, makes sense alone, no spoiler). A "cold viewer" call sees only the clip and must name the conflict and say if it would keep watching.
5. **Join (AI #1):** strong moments too far apart for one clip are joined (types B and C), then checked like the rest.
6. **Rank (code + AI #2):** by score; duplicates removed (same scene, back-to-back, one clip's ending = another's hook); at most 3 of one story pattern in the top 10; the model writes "why post it first" for the top 20.

**AI vs code:** the AI does judgement (what is gripping, what is a spoiler); code does everything checkable (times, length, order, duplicates, ranking rules) — so it is cheap, repeatable and testable (66 tests). **Human in the loop:** the editor opens the app, reads the top 20 and clicks Post / Maybe / Skip; those decisions are saved and are the real quality measure. **Model swap:** one line in config.toml (`model = "groq/openai/gpt-oss-120b"`); 10 providers built in, any OpenAI-compatible API via `custom/`, tested on 8 models.

## 4. Scale and cost (per show of 50 episodes)
| | Calls | Tokens | Cost |
|---|---|---|---|
| Find + join (gpt-oss-120b, Bedrock $0.15/$0.60 per M) | ~60 | ~0.4 M | ~$0.15 |
| Judge (DeepSeek V3.2, Bedrock) | ~890 | ~1.7 M | ~$1–2 (at $0.5–1.5 per M) |
| Time | 6 episodes in parallel | | ~15–20 min; re-runs from cache in seconds |

So a new show costs about **$1–2 and 15–20 minutes**, plus **~15 minutes of editor review** (vs. watching ~100 minutes of episodes). Shows run independently, so weekly volume just means more parallel runs. **Free option:** the earlier version ran fully on Groq's free tier (44 calls, 180k tokens); the full version needs ~2M tokens, more than one free daily quota, so I ran it on Bedrock (paid, no daily cap). Every answer is cached, so a free-tier run simply continues the next day. To use another screenplay format, only the parser changes.

## 5. How I know it is good — and where it fails
| Problem in the top promos (full show) | First version | Final |
|---|---|---|
| Clip runs past the cliffhanger (top 40) | 4 | 0 |
| Ends on a sound effect (top 40) | 2 | 0 |
| Same moment twice (top 40) | 1 | 0 |
| Vague opening line, e.g. "Look at him." (top 10) | 2 | 0 |
| Hook or ending is only a look / gasp (top 10) | 1 | 0 |
| Editor would post (precision@10, from the app review) | – | [FILL IN: __ / 10] |

Final run: 165 proposals → 156 passed the code checks (16 rejected: wrong length 3, made-up line numbers 3, duplicates 7 …), 60 duplicates removed, 40 ranked from 33 episodes; top 10 average **3.7 / 4**. I also tested the judge itself: the same clip scored **1, 7, 7** (out of 7) in three identical calls with a small model, while DeepSeek changed only 4 of 35 answers (in 2 of 5 clips) — so the judge votes 2–3 times.

**Where it picks badly:** (1) visual hooks — it only reads text; (2) the judge is an AI too and can be lenient — the editor's review is the real test; (3) cross-episode promos (type C) usually reuse a moment a single clip already has, so all 6 were dropped as duplicates; (4) quiet episodes (e.g. ep 8) give no promo at all; (5) the list of "real action" words that may end a promo is hand-written.

## 6. AI tools I used, and where they got it wrong
I built the code with **Claude Code** (Anthropic) and ran the pipeline with **gpt-oss-120b** (Groq, Amazon Bedrock) and **DeepSeek V3.2** (Bedrock); I also tested Gemini and Nemotron. **Where AI got it wrong:** (1) the judge model was confidently inconsistent (1 / 7 / 7 for the same clip), and a reasoning model spent its whole token budget "thinking" and returned no answer — fixed with votes, a reasoning limit and an automatic retry with more tokens; (2) the proposer ignored the 20–60 s rule (clips of 71–96 s) until the script showed times in plain seconds; (3) my coding assistant said Groq's daily quota had reset at midnight — it is a rolling 24-hour window, so the next run failed again.
