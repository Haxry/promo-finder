"""Talk to ANY LLM and get a JSON object back.

Two kinds of endpoint (set per provider in config.toml):
  api = "openai"    any OpenAI-compatible /chat/completions (Groq, OpenRouter, Gemini, Bedrock's /openai/v1, OpenAI,
                    a local proxy, vLLM, Ollama ...)
  api = "converse"  Amazon Bedrock's Converse API (DeepSeek, Claude, Qwen, Mistral, Nova ...)

Every problem we hit while switching models is handled here, so a new model should "just work":
  1. Reasoning models spend hidden tokens first   -> `reasoning` setting + the token budget doubles if a reply is cut off
  2. Reasoning text in the reply (<think>, <reasoning>, a reasoning field) -> stripped before reading the JSON
  3. JSON wrapped in fences / chatter / doubled braces / trailing commas / smart quotes -> tolerant reader
  4. A parameter the server doesn't support (400)  -> that parameter is dropped and the call retried
  5. Valid JSON but the wrong shape (missing key)  -> ONE repair turn: "reply with only the JSON object with <key>"
  6. Rate limits / server errors / timeouts        -> wait (as long as the server says) and retry
  7. Bad key / unknown model (401/403/404)         -> stop at once with a clear message
Pick a model with ONE string "provider/model" (see PRESETS below). Test it in ~10 s:
    python -m promo.llm check groq/openai/gpt-oss-120b
"""
import argparse, json, os, re, sys, threading, time, urllib.parse, urllib.request, urllib.error

LOCK = threading.Lock()                    # usage counters are shared between threads
SLOTS = threading.BoundedSemaphore(16)     # at most this many API calls at the same time


def set_max_parallel_calls(n):
    global SLOTS
    SLOTS = threading.BoundedSemaphore(max(1, n))


def load_env(*folders):
    """Read KEY=value lines from .env files into the environment (existing variables win)."""
    for d in folders:
        path = os.path.join(d, ".env")
        if not os.path.exists(path): continue
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip().removeprefix("export "), v.strip().strip("\"'"))


# ---- 2 + 3: reading JSON out of whatever the model wrote --------------------------------------------------------
def strip_reasoning(text):
    """Remove <think>...</think> / <reasoning>...</reasoning> blocks, and an unclosed one at the start."""
    text = re.sub(r"<(think|thinking|reasoning)>.*?</\1>", "", text or "", flags=re.S | re.I)
    m = re.match(r"\s*<(think|thinking|reasoning)>", text, re.I)          # cut off before it was closed
    return text[text.find("{", m.end()):] if m and "{" in text[m.end():] else text


def _tidy(text):
    """Common near-JSON mistakes: smart quotes, trailing commas, // comments."""
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    return re.sub(r",\s*([}\]])", r"\1", text)


def extract_json(text):
    """The first JSON object in a reply (a bare list is returned as a list). Raises ValueError if there is none."""
    text = strip_reasoning(text)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for candidate in (text, _tidy(text)):
        try:
            return json.loads(candidate)
        except ValueError:
            pass
        decoder = json.JSONDecoder()
        for i, ch in enumerate(candidate):               # first "{" (or "[") that starts something valid
            if ch in "{[":
                try:
                    obj, _ = decoder.raw_decode(candidate, i)
                    if obj: return obj
                except ValueError:
                    continue
    raise ValueError(f"no JSON in model output: {text[:120]!r}")


def shape(obj, expect):
    """Accept the answer if it has the expected top-level key; wrap a bare list under it."""
    if expect is None: return obj if isinstance(obj, dict) else None
    if isinstance(obj, list): return {expect: obj}
    if isinstance(obj, dict) and expect in obj: return obj
    if isinstance(obj, dict) and len(obj) == 1 and isinstance(next(iter(obj.values())), list):
        return {expect: next(iter(obj.values()))}        # e.g. {"clips": [...]} when "promos" was asked
    return None


# ---- the client -------------------------------------------------------------------------------------------------
REASONING_PARAM = {"openai": "reasoning_effort", "openrouter": "reasoning"}   # how providers spell "think less/more"


class LLM:
    def __init__(self, base_url, model, key_env, api="openai", reasoning=None, max_tokens=8192, json_mode=True,
                 extra=None, reasoning_style="openai", **_):
        self.base_url, self.model, self.api = base_url.rstrip("/"), model, api
        self.reasoning, self.max_tokens, self.json_mode = reasoning, int(max_tokens), json_mode
        self.extra, self.reasoning_style = dict(extra or {}), reasoning_style
        names = [key_env] if isinstance(key_env, str) else list(key_env or [])      # first name that is set wins
        self.key_env = next((n for n in names if os.environ.get(n)), names[0] if names else "")
        self.key = os.environ.get(self.key_env, "") if self.key_env else "none"      # e.g. a local Ollama needs no key
        # (checked at the first real call, so a fully cached re-run works without any API key)
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "seconds": 0.0,
                      "cut_off_retries": 0, "json_repairs": 0, "dropped_params": []}

    # -- request ------------------------------------------------------------------------------------------------
    def _body(self, messages, max_tokens):
        if self.api == "converse":
            system = [{"text": messages[0]["content"] + "\nReturn ONLY one JSON object."}]
            msgs = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages[1:]]
            return {"system": system, "messages": msgs, "inferenceConfig": {"temperature": 0.2, "maxTokens": max_tokens}}
        body = {"model": self.model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens, **self.extra}
        if self.json_mode: body["response_format"] = {"type": "json_object"}
        if self.reasoning and self.reasoning != "off":                       # 1. keep hidden reasoning in check
            if self.reasoning_style == "openrouter": body["reasoning"] = {"effort": self.reasoning}
            else: body["reasoning_effort"] = self.reasoning
        return body

    def _url(self):
        if self.api == "converse":
            return f"{self.base_url}/model/{urllib.parse.quote(self.model, safe='')}/converse"
        return self.base_url + "/chat/completions"

    # -- response -----------------------------------------------------------------------------------------------
    def _read(self, data):
        """-> (answer text, reasoning text, cut_off, prompt_tokens, completion_tokens, reasoning_tokens)"""
        if self.api == "converse":
            blocks, u = data.get("output", {}).get("message", {}).get("content", []), data.get("usage", {})
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            think = "".join(str(b.get("reasoningContent", "")) for b in blocks if isinstance(b, dict))
            return text, think, data.get("stopReason") == "max_tokens", u.get("inputTokens", 0), u.get("outputTokens", 0), 0
        choice, u = data["choices"][0], data.get("usage") or {}
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        if isinstance(text, list):                                           # content given as parts
            text = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in text)
        think = msg.get("reasoning_content") or msg.get("reasoning") or ""   # DeepSeek / OpenRouter / Groq style
        rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        return text, str(think), choice.get("finish_reason") == "length", u.get("prompt_tokens", 0), u.get("completion_tokens", 0), rt

    # -- one HTTP call with retries -----------------------------------------------------------------------------
    def _call(self, messages, tries=6):
        max_tokens, last, dropped = self.max_tokens, None, set()
        for attempt in range(tries):
            body = self._body(messages, max_tokens)
            for k in dropped: body.pop(k, None)
            try:
                req = urllib.request.Request(self._url(), json.dumps(body).encode(), {
                    "Authorization": f"Bearer {self.key}", "Content-Type": "application/json", "User-Agent": "promo-finder/1.0"})
                t0 = time.time()
                with SLOTS, urllib.request.urlopen(req, timeout=240) as r:
                    data = json.load(r)
                text, think, cut_off, pt, ct, rt = self._read(data)
                with LOCK:
                    u = self.usage
                    u["calls"] += 1; u["prompt_tokens"] += pt or 0; u["completion_tokens"] += ct or 0
                    u["reasoning_tokens"] += rt; u["seconds"] = round(u["seconds"] + time.time() - t0, 1)
                if cut_off and not (text and "}" in text):                   # 1. budget spent on reasoning: double it
                    with LOCK: self.usage["cut_off_retries"] += 1
                    max_tokens, last = min(32768, max_tokens * 2), f"reply cut off at {ct} tokens"
                    continue
                return text, think
            except urllib.error.HTTPError as e:
                msg = e.read()[:500].decode("utf-8", "replace")
                last = f"HTTP {e.code}: {msg[:200]}"
                if e.code in (401, 403, 404):                                # 7. no point retrying
                    raise RuntimeError(f"{self.model}: request rejected ({last}). Check the key, the model id and access.")
                if e.code == 400:                                            # 4. drop what the server doesn't accept
                    names = ("response_format", "reasoning_effort", "reasoning", "temperature", "max_tokens", *self.extra)
                    bad = [k for k in names if re.search(rf"\b{k}\b", msg) and k not in dropped] \
                        or (["response_format"] if "json" in msg.lower() and "response_format" not in dropped else [])
                    if not bad: raise RuntimeError(f"{self.model}: bad request ({last})")
                    dropped.update(bad)
                    with LOCK: self.usage["dropped_params"] = sorted(set(self.usage["dropped_params"]) | set(bad))
                    continue
                wait = re.search(r"(?:try again in|retry after|reset ~)\s*(\d+(?:\.\d+)?)\s*(ms|s|m)\b", msg, re.I)
                time.sleep(min(120, (float(wait.group(1)) * {"ms": 0.001, "s": 1, "m": 60}[wait.group(2).lower()]
                                     if wait else 5 * 2 ** attempt) + 1))   # 6. rate limit / server error
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
                last = repr(e); time.sleep(2 ** attempt)
        raise RuntimeError(f"{self.model}: failed after {tries} tries ({last})")

    # -- the one function the pipeline uses ---------------------------------------------------------------------
    def ask_json(self, system, user, expect=None):
        """Send a prompt, return a JSON object. `expect` = a top-level key that must be there (e.g. "promos")."""
        if not self.key: raise RuntimeError(f"No API key: put {self.key_env}=... in the .env file (needed for {self.model}).")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        text, think = self._call(messages)
        for source in (text, think):                                         # 2. answer, then reasoning as last resort
            try:
                ok = shape(extract_json(source), expect)
                if ok is not None: return ok
            except ValueError:
                pass
        with LOCK: self.usage["json_repairs"] += 1                           # 5. one repair turn
        need = f' with the key "{expect}"' if expect else ""
        messages += [{"role": "assistant", "content": (text or "(empty)")[:3000]},
                     {"role": "user", "content": f"That was not a valid JSON object{need}. Reply with ONLY the JSON object, "
                                                 f"no explanation, no code fences."}]
        text, think = self._call(messages)
        for source in (text, think):
            try:
                ok = shape(extract_json(source), expect)
                if ok is not None: return ok
            except ValueError:
                pass
        raise ValueError(f"{self.model}: no usable JSON{need} after a repair turn: {text[:150]!r}")


# ---- choosing a model: "provider/model id" ---------------------------------------------------------------------
# Everything the client needs for well-known providers. A model is picked with ONE string, e.g.
#   "groq/openai/gpt-oss-120b"   "bedrock/deepseek.v3.2"   "openai/gpt-4.1"   "anthropic/claude-sonnet-4-5"
#   "ollama/llama3.1"   "custom/<model>"  (any OpenAI-compatible endpoint: set CUSTOM_BASE_URL + CUSTOM_API_KEY)
REGION = os.environ.get("AWS_REGION", "us-east-1")
PRESETS = {
    "openai":     {"base_url": "https://api.openai.com/v1", "key_env": ["OPENAI_API_KEY"]},
    "anthropic":  {"base_url": "https://api.anthropic.com/v1", "key_env": ["ANTHROPIC_API_KEY"], "json_mode": False},
    "groq":       {"base_url": "https://api.groq.com/openai/v1", "key_env": ["GROQ_API_KEY"]},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": ["OPENROUTER_API_KEY"], "reasoning_style": "openrouter"},
    "gemini":     {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": ["GEMINI_API_KEY", "Gemini_API_KEY"]},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1", "key_env": ["DEEPSEEK_API_KEY"]},
    "mistral":    {"base_url": "https://api.mistral.ai/v1", "key_env": ["MISTRAL_API_KEY"]},
    "together":   {"base_url": "https://api.together.xyz/v1", "key_env": ["TOGETHER_API_KEY"]},
    "ollama":     {"base_url": "http://localhost:11434/v1", "key_env": []},
    "bedrock":    {"key_env": ["AWS_BEARER_TOKEN_BEDROCK", "AMAZON_BEDROCK_API_KEY"]},   # endpoint chosen per model below
    "custom":     {"base_url": os.environ.get("CUSTOM_BASE_URL", "http://localhost:8000/v1"), "key_env": ["CUSTOM_API_KEY"]},
}
REASONING_MODEL = re.compile(r"gpt-oss|(^|/)o[1-9]|deepseek-r|\.r1|qwq|thinking|reason", re.I)


def model_settings(spec, cfg=None):
    """'groq/openai/gpt-oss-120b' -> everything LLM() needs. config.toml [providers.<name>] can add or override."""
    provider, _, model = spec.partition("/")
    if not model: raise SystemExit(f"Write the model as provider/model, e.g. groq/openai/gpt-oss-120b (got {spec!r}).")
    custom = dict((cfg or {}).get("providers", {}).get(provider, {}))
    if provider not in PRESETS and not custom.get("base_url"):
        raise SystemExit(f"Unknown provider {provider!r}. Use one of {', '.join(PRESETS)}, or add [providers.{provider}] "
                         f"with base_url and key_env to config.toml.")
    s = {**PRESETS.get(provider, {}), "model": model}
    if provider == "bedrock":                       # Bedrock: OpenAI-style endpoint for openai.* models, Converse otherwise
        openai_style = model.startswith("openai.")
        s.update(base_url=f"https://bedrock-runtime.{REGION}.amazonaws.com" + ("/openai/v1" if openai_style else ""),
                 api="openai" if openai_style else "converse")
    if REASONING_MODEL.search(model): s["reasoning"] = "medium"     # dropped automatically if the server refuses it
    return {**s, **custom, "model": model}


def make_llm(spec, cfg=None):
    """The client for a model string like 'bedrock/deepseek.v3.2' (or 'mock' for the offline fake)."""
    if spec == "mock":
        from .mock import MockLLM
        return MockLLM()
    return LLM(**model_settings(spec, cfg))


# ---- python -m promo.llm check <provider/model> -----------------------------------------------------------------
def check(spec, cfg=None):
    """Smoke-test a model: does it answer, in the JSON shape we need, how fast, does it reason?"""
    llm = make_llm(spec, cfg)
    t0 = time.time()
    ans = llm.ask_json("You pick promo clips. Return ONLY JSON.",
                       'Transcript:\nL1 [0.0s-2.0s] JULIANA: "You knew?"\nL2 [2.0s-4.0s] GERALD: "I chose her."\n'
                       'Return {"promos":[{"hook_line":"L<n>","cliff_line":"L<n>","why":"<short>"}]}', expect="promos")
    ok = isinstance(ans.get("promos"), list) and ans["promos"] and "hook_line" in ans["promos"][0]
    u = llm.usage
    print(f"model          {spec}\nanswer ok      {bool(ok)}  {json.dumps(ans)[:120]}\n"
          f"seconds        {time.time() - t0:.1f}\ntokens         in {u['prompt_tokens']}, out {u['completion_tokens']}"
          f" (reasoning {u['reasoning_tokens']})\nfixes needed   cut-off retries {u['cut_off_retries']}, json repairs "
          f"{u['json_repairs']}, dropped params {u['dropped_params'] or 'none'}")
    return bool(ok)


if __name__ == "__main__":
    import tomllib
    ap = argparse.ArgumentParser(description="Test a model in ~10 s:  python -m promo.llm check groq/openai/gpt-oss-120b")
    ap.add_argument("cmd", choices=["check"]); ap.add_argument("model", help="provider/model, e.g. bedrock/deepseek.v3.2")
    a = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_env(root, os.path.dirname(root))
    sys.exit(0 if check(a.model, tomllib.load(open(os.path.join(root, "config.toml"), "rb"))) else 1)
