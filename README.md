# Promo Finder

This tool reads the screenplays of a microdrama show and finds the best **promo clips** (20–60 seconds) to post on
Instagram, TikTok or YouTube.

A good promo:
- **starts with a hook** in the first 3 seconds (a slap, a shock, a threat)
- **ends on a cliffhanger** (the viewer wants to know what happens next)
- **makes sense** to someone who has never seen the show

For every promo the tool gives: the episode, the start and end time, the hook, the cliffhanger, why it works, and
why to post it first. It also shows where it picks badly.

---

## Contents

**Solution write-up:** [SUBMISSION.md](SUBMISSION.md) · [SUBMISSION.pdf](SUBMISSION.pdf) — the full approach, features, results, and app screenshots.

Getting started
- [Step 1 — Install](#step-1--install)
- [Step 2 — See the results (no API key needed)](#step-2--see-the-results-no-api-key-needed)
- [Step 3 — Use a different model](#step-3--use-a-different-model)
- [Step 4 — Run on a new show](#step-4--run-on-a-new-show)

Reference
- [What you get](#what-you-get)
- [The app](#the-app)
- [How we check quality](#how-we-check-quality)
- [How it works (short)](#how-it-works-short)
- [Known limits](#known-limits)

---

## Step 1 — Install

You need Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/activate 
pip install -r requirements.txt
```

Keep this folder next to the screenplay folder (`I Married a Broken Soldier. He was a Duke/`).

## Step 2 — See the results (no API key needed)

The full show has already been run. These two commands work without any key:

```bash
python3 run.py --input "../I Married a Broken Soldier. He was a Duke"     # rebuilds the results from saved answers
.venv/bin/streamlit run app.py                                             # opens the app in your browser
```

The results are in `outputs/bedrock__openai.gpt-oss-120b-1_0__v4/`. Open **`promos.md`** first.

## Step 3 — Use a different model

1. Open `config.toml` and change these two lines:

   ```toml
   model  = "groq/openai/gpt-oss-120b"     # this model finds the promos
   critic = "groq/openai/gpt-oss-20b"      # this model checks them (use a different one)
   ```

   You always write it as **`provider/model-name`**.

2. Make a file called `.env` in this folder and put your key in it, for example:

   ```
   GROQ_API_KEY=your-key-here
   ```

3. Test the model (takes about 10 seconds):

   ```bash
   python3 -m promo.llm check groq/openai/gpt-oss-120b
   ```

4. Run it:

   ```bash
   python3 run.py --input "../I Married a Broken Soldier. He was a Duke"
   ```

You can also pick the models only for one run:
`python3 run.py --input "..." --model openai/gpt-4.1 --critic anthropic/claude-sonnet-4-5`

**Which key name to use:**

| You write | Key in `.env` |
|---|---|
| `groq/...` (free) | `GROQ_API_KEY` |
| `openai/...` | `OPENAI_API_KEY` |
| `anthropic/...` | `ANTHROPIC_API_KEY` |
| `gemini/...` | `GEMINI_API_KEY` |
| `openrouter/...` | `OPENROUTER_API_KEY` |
| `bedrock/...` (Amazon) | `AWS_BEARER_TOKEN_BEDROCK` |
| `deepseek/...` · `mistral/...` · `together/...` | `DEEPSEEK_API_KEY` · `MISTRAL_API_KEY` · `TOGETHER_API_KEY` |
| `ollama/...` (runs on your computer) | no key |
| `custom/model-name` (any other OpenAI-style API) | `CUSTOM_BASE_URL` and `CUSTOM_API_KEY` |

Nothing else needs to change. Reasoning models (like gpt-oss, o3, DeepSeek-R1) are set up automatically.

## Step 4 — Run on a new show

```bash
python3 run.py --input "path/to/new/show"
```

The folder just needs the episode `.txt` files. Useful extras:

```bash
python3 run.py --input "..." --episodes 1-10     # only some episodes
python3 run.py --input "..." --model mock        # a fake model, to test without any key
```

If a run stops (no quota, no internet), **run the same command again**. It saves every answer, so it continues
where it stopped.

---

## What you get

In `outputs/<model>/`:

| File | What it is |
|---|---|
| `promos.md` | the ranked promos, easy to read |
| `promos.csv` | the same, for a spreadsheet |
| `promos.json` | the same, for code |
| `rejected.json` | promos the tool threw away, with the reason |
| `run_stats.json` | numbers: how many found, rejected, time, cost |
| `raw_llm/` | every answer the models gave, unedited |

## The app

`.venv/bin/streamlit run app.py` opens it in your browser. At the top it explains what you are looking at and shows
4 numbers (promos found, episodes, average quality, ideas thrown away). It has 4 tabs:

1. **🏆 Best promos** — one card per promo: rank, where it is, what it opens with (green) and ends on (blue), why it
   works, why to post it there, and the checker's 4 ticks. Mark each one **👍 Post / 🤔 Maybe / 👎 Skip** (this is the
   human check; it is saved and used to measure quality).
2. **⚠️ Where it struggles** — ideas that were thrown away (grouped, in plain words), weak promos, and the ones the AI
   liked but you skipped.
3. **📄 Read an episode** — the script of one episode and what the tool kept or threw away there.
4. **ℹ️ How it works** — the 6 steps and the words used, for someone seeing it for the first time.

The app shows lines from the scripts. The scripts are confidential, so run it on your own computer — don't put it online.

## How we check quality

```bash
python3 eval/score.py outputs/groq__openai_gpt-oss-120b__v3.1 outputs/bedrock__openai.gpt-oss-120b-1_0__v4
```

This compares the old version with the new one. It counts problems (clips that run past the cliffhanger, duplicates,
weak openings, spoilers) and, if you marked promos in the app, how many of the top 10 you would post.

To run the tests: `.venv/bin/python -m pytest -q`

---

## How it works (short)

1. **Read** the scripts. Every line gets a number like `L12`.
2. **Find** — an AI model reads each episode and picks promos by line number.
3. **Check** — the code checks the rules (20–60 s, hook in the first 3 s, ends on the cliffhanger) and fixes small mistakes.
4. **Judge** — a second, different AI model scores each promo. A "fresh viewer" sees only the clip and says if they would keep watching.
5. **Join** — some promos join two moments, from one episode or from different episodes.
6. **Rank** — best score first, then the AI says why to post each one first.

The AI never writes times or dialogue. It only picks line numbers, and the code looks up the real text and times.

| File | Job |
|---|---|
| `run.py` | runs all the steps |
| `promo/parse.py` | reads the scripts |
| `promo/prompts.py` | all the instructions sent to the AI |
| `promo/llm.py` | talks to any AI model |
| `promo/validate.py` | checks the rules |
| `promo/critic.py` | the second model's score |
| `promo/stitch.py` | promos that join two moments |
| `promo/rank.py` | puts promos in order |

## Known limits

- The tool only reads the script, so a hook that is only visual can be scored wrong.
- Promos that join moments from different episodes usually repeat a moment already used, so most of them are dropped.
- Small AI models give noisy scores, so the second model votes 2–3 times per promo.
