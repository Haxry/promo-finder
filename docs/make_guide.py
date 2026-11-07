"""Builds promo_finder/docs/How_Promo_Finder_Works.pdf (5 pages, A4)."""
import sys
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
                                Preformatted)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

OUT = sys.argv[1]
INK, MUTED, ACCENT, SOFT, CODEBG, LINE = (colors.HexColor(c) for c in ("#1f2328", "#57606a", "#1a5fb4", "#eef4fb", "#f6f8fa", "#d0d7de"))

base = dict(fontName="Helvetica", fontSize=9.6, leading=13.4, textColor=INK)
S = {
    "title": ParagraphStyle("title", **{**base, "fontName": "Helvetica-Bold", "fontSize": 20, "leading": 24, "spaceAfter": 2}),
    "sub": ParagraphStyle("sub", **{**base, "textColor": MUTED, "fontSize": 10.5, "leading": 14, "spaceAfter": 8}),
    "h1": ParagraphStyle("h1", **{**base, "fontName": "Helvetica-Bold", "fontSize": 14, "leading": 18, "textColor": ACCENT,
                                  "spaceBefore": 2, "spaceAfter": 5}),
    "h2": ParagraphStyle("h2", **{**base, "fontName": "Helvetica-Bold", "fontSize": 10.8, "leading": 14, "spaceBefore": 7, "spaceAfter": 3}),
    "p": ParagraphStyle("p", **{**base, "spaceAfter": 5}),
    "li": ParagraphStyle("li", **{**base, "leftIndent": 11, "bulletIndent": 2, "spaceAfter": 2.5}),
    "small": ParagraphStyle("small", **{**base, "fontSize": 8.4, "leading": 11, "textColor": MUTED}),
    "cell": ParagraphStyle("cell", **{**base, "fontSize": 8.6, "leading": 11.2}),
    "cellb": ParagraphStyle("cellb", **{**base, "fontSize": 8.6, "leading": 11.2, "fontName": "Helvetica-Bold"}),
    "code": ParagraphStyle("code", fontName="Courier", fontSize=8.1, leading=10.4, textColor=INK),
    "note": ParagraphStyle("note", **{**base, "fontSize": 9.2, "leading": 12.8}),
}

W = A4[0] - 2 * 18 * mm


def P(t, s="p"): return Paragraph(t, S[s])
def bullets(items): return [Paragraph(i, S["li"], bulletText="•") for i in items]


def code(text):
    t = Table([[Preformatted(text, S["code"])]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODEBG), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def box(title, body):
    """A light-blue 'in this project' note."""
    t = Table([[P(f"<b>{title}</b>", "note")], [P(body, "note")]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, 0), 6),
                           ("BOTTOMPADDING", (0, -1), (-1, -1), 6), ("TOPPADDING", (0, 1), (-1, 1), 1)]))
    return t


def table(rows, widths, head=True):
    data = [[P(c, "cellb" if (head and r == 0) else "cell") for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[w * W for w in widths], repeatRows=1 if head else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if head: style.append(("BACKGROUND", (0, 0), (-1, 0), CODEBG))
    t.setStyle(TableStyle(style))
    return t


def pipeline():
    """Six boxes with arrows: who does each step (AI or code)."""
    steps = [("1 Read", "code", "script to\nnumbered lines"), ("2 Find", "AI #1", "picks promos\nby line number"),
             ("3 Check", "code", "rules + small\nrepairs"), ("4 Judge", "AI #2", "scores each\npromo"),
             ("5 Join", "AI #1", "2 moments\ninto 1 promo"), ("6 Rank", "code + AI #2", "order +\n'post first' reason")]
    n, gap = len(steps), 9
    bw, bh = (W - gap * (n - 1)) / n, 64
    d = Drawing(W, bh + 22)
    for i, (name, who, what) in enumerate(steps):
        x = i * (bw + gap)
        ai = "AI" in who
        d.add(Rect(x, 8, bw, bh, rx=6, ry=6, fillColor=SOFT if ai else colors.white, strokeColor=ACCENT if ai else LINE, strokeWidth=1))
        d.add(String(x + bw / 2, bh - 8, name, textAnchor="middle", fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
        d.add(String(x + bw / 2, bh - 21, who, textAnchor="middle", fontName="Helvetica-Bold", fontSize=7.6,
                     fillColor=ACCENT if ai else MUTED))
        for k, l in enumerate(what.split("\n")):
            d.add(String(x + bw / 2, bh - 36 - k * 10, l, textAnchor="middle", fontName="Helvetica", fontSize=7.4, fillColor=INK))
        if i < n - 1:
            ax = x + bw + 1
            d.add(Line(ax, 8 + bh / 2, ax + gap - 3, 8 + bh / 2, strokeColor=MUTED, strokeWidth=1))
            d.add(Polygon([ax + gap - 2, 8 + bh / 2, ax + gap - 6, 8 + bh / 2 + 2.5, ax + gap - 6, 8 + bh / 2 - 2.5],
                          fillColor=MUTED, strokeColor=MUTED))
    d.add(String(0, 0, "Blue = an AI model does this step.  White = plain Python code does it (fast, free, always the same).",
                 fontName="Helvetica", fontSize=7.6, fillColor=MUTED))
    return d


def footer(c, doc):
    c.saveState(); c.setFont("Helvetica", 7.5); c.setFillColor(MUTED)
    c.drawString(18 * mm, 10 * mm, "Promo Finder - how it works")
    c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page} of 5")
    c.restoreState()


story = []

# ================================== PAGE 1 =================================================================
story += [P("Promo Finder - how it works", "title"),
          P("A plain-language guide for someone who knows programming but has not worked much with AI APIs.", "sub"),
          P("1. The problem", "h1"),
          P("A microdrama is a show with very short episodes (1-2 minutes). To get new viewers, the company posts "
            "<b>promos</b>: 20-60 second clips cut from the show, on Instagram, TikTok and YouTube. Today an editor "
            "watches every episode and picks these clips by hand. This tool reads the <b>screenplays</b> (the written "
            "scripts, where every line has a timestamp) and finds the clips automatically."),
          P("A good promo has three things:"),
          *bullets(["<b>A hook</b> in the first 3 seconds - something that makes a scrolling person stop (a slap, a shocking line).",
                    "<b>A cliffhanger</b> at the end - it stops at an open moment, so the viewer wants to know what happens next.",
                    "<b>It makes sense alone</b> - a stranger who never saw the show can follow it."]),
          Spacer(1, 3),
          P("2. What the tool gives you", "h1"),
          P("A ranked list. For each promo: where it is (episode, start and end time), the hook, the cliffhanger, why it "
            "works, and why to post it at this position. For example (made-up lines, not from the real show):"),
          code('#1  Episode 2  00:18.20 - 00:52.40  (34 s)  quality 4/4\n'
               '    Opens on:  "You promised to marry me in front of everyone."\n'
               '    Ends on:   "Then who is the woman wearing my ring?"\n'
               '    Why it works:  instant betrayal, and the last line is an unanswered question.\n'
               '    Why post it first:  sells the premise of the whole show in one clip.'),
          Spacer(1, 4),
          P("3. The big picture", "h1"),
          P("The work is split into six steps. Two different AI models do the parts that need judgement; normal "
            "code does everything that can be checked by rules."),
          pipeline(),
          Spacer(1, 4),
          box("The most important design idea",
              "The AI never writes times or dialogue. Every script line gets a number (L12, L13 ...). The AI answers "
              "only with line numbers (\"start at L12, hook is L12, cliffhanger is L30\"), and the code looks up the real "
              "text and the real times. So the AI cannot invent a line or a wrong timestamp - the worst it can do is "
              "pick a bad line, and the code then checks that."),
          PageBreak()]

# ================================== PAGE 2 =================================================================
story += [P("4. AI APIs in five minutes", "h1"),
          P("An <b>LLM</b> (large language model) is a program that reads text and writes text. You do not run it "
            "yourself; a company runs it on their servers, and you use it through an <b>API</b>: your code sends an "
            "HTTP request over the internet, and gets an answer back - just like calling any web service."),
          P("What a request looks like", "h2"),
          P("Almost every provider accepts the same format, called the <b>OpenAI-compatible format</b>. You send a "
            "JSON body with the model name and the messages:"),
          code('POST https://api.groq.com/openai/v1/chat/completions\n'
               'Authorization: Bearer <your API key>\n\n'
               '{ "model": "openai/gpt-oss-120b",\n'
               '  "messages": [\n'
               '    {"role": "system", "content": "You pick promo clips. Reply ONLY with JSON."},\n'
               '    {"role": "user",   "content": "L1 [0.0s-2.0s] JULIA: \\"You knew?\\" ..."} ],\n'
               '  "response_format": {"type": "json_object"} }'),
          P("The answer comes back as JSON too; the model's text is inside it:"),
          code('{ "choices": [ {"message": {"content": "{\\"promos\\": [{\\"hook_line\\": \\"L1\\", ...}]}"},\n'
               '                "finish_reason": "stop"} ],\n'
               '  "usage": {"prompt_tokens": 1830, "completion_tokens": 410} }'),
          P("The words you need", "h2"),
          table([["Word", "What it means"],
                 ["API key", "A secret password for your account. Sent with every request. Never put it in the code - "
                             "this project keeps keys in a <b>.env</b> file that is not shared."],
                 ["Provider", "The company running the model: Groq, OpenAI, Anthropic, Google (Gemini), Amazon Bedrock, OpenRouter ..."],
                 ["Model", "The specific AI, e.g. <i>gpt-oss-120b</i> or <i>deepseek-v3.2</i>. Bigger models are usually smarter, slower and cost more."],
                 ["System / user message", "The <b>system</b> message says what the model's job is and the rules; the <b>user</b> message is the actual input (here: one episode's script)."],
                 ["Prompt", "All the text you send. This project keeps every prompt in one file: <b>promo/prompts.py</b>."],
                 ["Token", "Models count text in tokens (about 3/4 of a word). You pay per token: input tokens + output tokens."],
                 ["JSON mode", "Asks the model to reply with valid JSON only, so code can read the answer. Not every model supports it."],
                 ["Rate limit / quota", "Free plans limit how much you can send: per minute (wait and retry) and per day (stop, continue tomorrow)."],
                 ["Reasoning model", "A model that \"thinks\" first in hidden text before answering (e.g. gpt-oss, o3, DeepSeek-R1). Better at "
                                     "hard tasks, but the thinking also uses tokens."]],
                [0.22, 0.78]),
          Spacer(1, 6),
          box("Why answers must be JSON",
              "The code has to read the model's answer automatically. Free text like \"I think the best clip starts at "
              "line 12\" is hard to use; JSON like {\"start_line\": \"L12\"} is easy. So every prompt in this project "
              "asks for JSON and shows the exact shape it wants."),
          PageBreak()]

# ================================== PAGE 3 =================================================================
story += [P("5. Talking to any model: promo/llm.py", "h1"),
          P("All communication with AI models goes through one small file. The rest of the project only calls one "
            "function: <b>ask_json(system, user)</b>, which returns a Python dictionary. That is why the model is "
            "easy to swap."),
          P("Choosing a model = one line", "h2"),
          P("A model is written as <b>provider/model-name</b>. The file already knows the web address, the key "
            "name and the request style of the common providers, so you only change this line in <b>config.toml</b>:"),
          code('model  = "groq/openai/gpt-oss-120b"     # the model that finds promos\n'
               'critic = "groq/openai/gpt-oss-20b"      # a DIFFERENT model that checks them'),
          P("and put the key in <b>.env</b> (for example GROQ_API_KEY=...). Built in: openai, anthropic, groq, gemini, "
            "openrouter, bedrock, deepseek, mistral, together, ollama (runs locally, no key), and <b>custom</b> for any "
            "other OpenAI-style API. Before a full run you can test a model in about 10 seconds:"),
          code('python3 -m promo.llm check groq/openai/gpt-oss-120b'),
          P("What goes wrong with real models - and what the file does", "h2"),
          P("When we switched between models, each one broke in a different way. These problems all really happened in "
            "this project; the file now handles each of them, so a new model usually just works:"),
          table([["What went wrong", "Seen with", "What llm.py does"],
                 ["The answer stopped half-way: the reasoning model used all its tokens on hidden thinking", "Groq gpt-oss-20b, Bedrock gpt-oss-120b",
                  "Sets a reasoning level; if an answer is cut off, doubles the token limit and asks again"],
                 ["Thinking text mixed into the answer (&lt;reasoning&gt; ... &lt;/reasoning&gt;), even with JSON-looking text inside it", "Bedrock gpt-oss",
                  "Removes the thinking part before reading the JSON"],
                 ["Messy JSON: in code fences, with chatty text, a doubled opening brace, trailing commas", "Bedrock, Nemotron",
                  "A tolerant reader that finds the first valid JSON object"],
                 ["The server refuses an option (JSON mode, reasoning setting) with error 400", "Groq, OpenRouter",
                  "Drops that option and sends the request again"],
                 ["Valid JSON, but not the shape we asked for", "smaller models",
                  "One 'repair' message: \"reply with ONLY the JSON object\""],
                 ["Rate limit (error 429): \"try again in 12 s\"", "every free plan", "Waits as long as the server says, then retries"],
                 ["Wrong key or model name (401/403/404)", "-", "Stops at once with a clear message (retrying would not help)"]],
                [0.40, 0.20, 0.40]),
          Spacer(1, 4),
          P("Two more things that save time and money", "h2"),
          *bullets(["<b>Cache.</b> Every answer is saved in <b>outputs/&lt;run&gt;/raw_llm/</b>. Running the same command "
                    "again re-uses the saved answers and only asks for what is missing - so if the quota runs out "
                    "half-way, you just run it again later. A finished show re-builds in under a second, with no key.",
                    "<b>Parallel calls.</b> Six episodes are processed at the same time (threads), with a cap of 16 calls "
                    "at once so the provider is not flooded."]),
          PageBreak()]

# ================================== PAGE 4 =================================================================
story += [P("6. The steps, with one example", "h1"),
          P("<b>Step 1 - Read (code).</b> <b>promo/parse.py</b> turns each script file into a list of lines with a "
            "number, a type (dialogue, action, sound, camera) and start/end times. What the model sees:"),
          code('L12 [33.0s-35.1s] MARGARET (Cold): "You should turn around."\n'
               'L13 [35.5s-36.3s] JULIA (Confused): "Why?"\n'
               'L14 [36.4s-38.0s] ACTION: Julia sees the groom holding another woman\'s hand.\n'
               'L15 [38.2s-39.0s] MARGARET: "Not anymore."'),
          P("<b>Step 2 - Find (AI model 1).</b> For each episode the model gets the whole script plus a short "
            "<b>show bible</b> (who is who, and which twists come late - so it can avoid spoilers). It answers with "
            "up to 6 promos, using line numbers only:"),
          code('{"promos": [{"segments": [{"start_line": "L12", "end_line": "L30"}],\n'
               '              "hook_line": "L12", "cliff_line": "L30", "why": "public betrayal ..."}]}'),
          P("<b>Step 3 - Check (code).</b> <b>promo/validate.py</b> looks up the lines and checks the brief's rules. "
            "Small mistakes are repaired (and the repair is written down); the rest are thrown away with a reason:"),
          *bullets(["Do the line numbers exist? (a model once answered \"L40.5\")",
                    "Is it 20-60 seconds? A clip 2 s too long can lose one middle line; a clip too short can get a short setup line in front.",
                    "Is the hook in the first 3 seconds? If not, the start is moved.",
                    "Does it END on the cliffhanger? Lines after it are cut off.",
                    "Is the cliffhanger a real story moment? A sound effect or a look (\"she gasps\") is not - the clip then ends on the last spoken line.",
                    "Is the first line vague, like \"Look at him.\"? Then it is flagged as a weak opening."]),
          P("<b>Step 4 - Judge (AI model 2).</b> A <b>different</b> model checks every clip - the model that picked "
            "the clips should not grade its own work. It answers yes/no questions (does the opening show a conflict? "
            "is the last line an open question? would a stranger follow it? does it spoil a late twist?) and votes "
            "2-3 times, because one answer can be noisy. A second call, the <b>cold viewer</b>, gets only the clip - "
            "no background at all - and says who the conflict is between and whether it would keep watching. The "
            "result is a score from <b>0 to 4</b>: hook, ending, understandable alone, not a spoiler."),
          P("<b>Step 5 - Join (AI model 1).</b> Sometimes the best hook and the best cliffhanger are too far apart for "
            "one clip. The code collects strong moments and asks the model to join 2-3 of them, from one episode "
            "(type B) or from different episodes (type C). These go through Steps 3 and 4 like every other promo."),
          P("<b>Step 6 - Rank (code + AI model 2).</b> <b>promo/rank.py</b> sorts by the 0-4 score first, so a weaker "
            "clip is never placed above a stronger one. Inside the same score: clean openings before weak ones, "
            "non-spoilers first, earlier episodes first. It removes duplicates (the same moment twice), allows at most "
            "3 clips of the same story type in the top 10, and asks the model to order small groups and say "
            "<i>why to post it first</i>."),
          PageBreak()]

# ================================== PAGE 5 =================================================================
story += [P("7. Running it", "h1"),
          code('# once: install\n'
               'python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n'
               '# find the promos (models from config.toml)\n'
               'python3 run.py --input "../I Married a Broken Soldier. He was a Duke"\n'
               '# open the editor screen in the browser\n'
               '.venv/bin/streamlit run app.py\n'
               '# compare two versions\n'
               'python3 eval/score.py outputs/<old run> outputs/<new run>'),
          P("The results are in <b>outputs/&lt;model&gt;/</b>: <b>promos.md</b> (read this first), promos.csv, "
            "promos.json, <b>rejected.json</b> (what was thrown away and why), run_stats.json (counts, time, cost) and "
            "raw_llm/ (every model answer, unedited). The <b>app</b> is the editor's screen, with 4 tabs: <b>Best promos</b> "
            "(one card per promo; the editor clicks <b>Post / Maybe / Skip</b>), <b>Where it struggles</b>, <b>Read an "
            "episode</b> and <b>How it works</b>. The editor's choices are saved and used to measure quality - this is "
            "where a human stays in the loop."),
          P("8. Does it work? Real numbers from the full show (50 episodes)", "h1"),
          table([["Problem in the top promos", "First version", "Final version"],
                 ["Clip keeps running after the cliffhanger (top 40)", "4", "0"],
                 ["Clip ends on a sound effect (top 40)", "2", "0"],
                 ["The same moment twice (top 40)", "1", "0"],
                 ["Vague opening line (top 10)", "2", "0"],
                 ["Hook or ending is only a look / gasp (top 10)", "1", "0"]],
                [0.62, 0.19, 0.19]),
          Spacer(1, 3),
          P("Final run: 165 proposals, 156 passed the code checks, 60 duplicates removed, 40 ranked, covering 33 "
            "episodes. The top 10 average 3.7 out of 4 on the critic's score. Finding the promos cost about <b>$0.07</b> "
            "for the whole show (gpt-oss-120b on Amazon Bedrock); the critic used about 1.7 million tokens; a full run "
            "takes about 10-20 minutes with 6 episodes in parallel, and seconds when cached. The same setup also works "
            "on free plans (Groq), just slower because of daily limits.", "p"),
          P("9. Where it is weak", "h1"),
          *bullets(["It only reads the script. A hook that is purely visual (a look, a costume) can be scored wrong.",
                    "The critic is also an AI, so it can be wrong. That is why the editor's Post / Maybe / Skip is the real test.",
                    "Promos joined from different episodes usually repeat a moment that a normal promo already uses, so most are removed as duplicates.",
                    "The list of \"real action\" words (strikes, grabs, enters ...) that decides if an action line can end a promo is written by hand."]),
          P("10. Where to look in the code", "h1"),
          table([["File", "Job", "File", "Job"],
                 ["run.py", "runs all six steps, top to bottom", "promo/critic.py", "step 4: the second model's score"],
                 ["promo/parse.py", "step 1: reads the scripts", "promo/stitch.py", "step 5: joins moments"],
                 ["promo/prompts.py", "every instruction sent to the AI", "promo/rank.py", "step 6: order, duplicates, variety"],
                 ["promo/llm.py", "talks to any model (page 3)", "app.py", "the editor's screen"],
                 ["promo/validate.py", "step 3: the rules and repairs", "eval/score.py", "measures quality"]],
                [0.19, 0.31, 0.19, 0.31]),
          Spacer(1, 4),
          P("Tip: to see the whole flow, read <b>run.py</b> from top to bottom - its five numbered sections match the steps in this guide.", "small")]

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm, bottomMargin=16 * mm,
                        title="Promo Finder - how it works", author="dharmsingh")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
