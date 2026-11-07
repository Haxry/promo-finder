"""promo/llm.py against every model quirk we have actually met (fake HTTP, no network)."""
import io, json, urllib.error, urllib.request
import pytest
from promo import llm as L


# ---- reading JSON out of model replies ----------------------------------------------------------------------------
@pytest.mark.parametrize("reply,expected", [
    ('{"promos": []}', {"promos": []}),
    ('<reasoning>The user wants {"ok":1} so I output it.</reasoning>{"promos": [1]}', {"promos": [1]}),   # Bedrock gpt-oss
    ('<think>let me think about {"a": 1}</think>\n{"promos": [2]}', {"promos": [2]}),                     # DeepSeek-R1 style
    ('<think>long thoughts that never close ... {"promos": [3]}', {"promos": [3]}),                       # cut-off think
    ('{\n{\n  "premise": "x"\n}', {"premise": "x"}),                                                      # doubled brace
    ('```json\n{"a": 2}\n```', {"a": 2}),                                                                 # code fence
    ('Sure! Here it is: {"a": {"b": 1}} hope that helps', {"a": {"b": 1}}),                               # chatter
    ('{"a": [1, 2,], "b": 3,}', {"a": [1, 2], "b": 3}),                                                   # trailing commas
    ('{“a”: “x”}', {"a": "x"}),                                                       # smart quotes
])
def test_extract_json(reply, expected):
    assert L.extract_json(reply) == expected


def test_extract_json_raises_when_nothing():
    with pytest.raises(ValueError): L.extract_json("I could not find any promos, sorry.")


def test_shape():
    assert L.shape({"promos": []}, "promos") == {"promos": []}
    assert L.shape([{"x": 1}], "promos") == {"promos": [{"x": 1}]}              # bare list -> wrapped
    assert L.shape({"clips": [1]}, "promos") == {"promos": [1]}                 # single list under another name
    assert L.shape({"premise": "x", "other": 1}, "promos") is None             # wrong shape -> repair turn


# ---- fake server ------------------------------------------------------------------------------------------------
class Server:
    """Plays back a list of responses: dicts are JSON bodies, (code, text) tuples are HTTP errors. Records bodies."""
    def __init__(self, monkeypatch, *responses):
        self.responses, self.bodies, self.sleeps = list(responses), [], []
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)
        monkeypatch.setattr(L.time, "sleep", lambda s: self.sleeps.append(s))

    def urlopen(self, req, timeout=0):
        self.bodies.append(json.loads(req.data))
        r = self.responses.pop(0)
        if isinstance(r, tuple):
            raise urllib.error.HTTPError(req.full_url, r[0], "x", {}, io.BytesIO(r[1].encode()))
        return io.BytesIO(json.dumps(r).encode())


def chat(content, finish="stop", **msg):
    return {"choices": [{"message": {"content": content, **msg}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    return lambda **kw: L.LLM(base_url="http://x/v1", model="m", key_env="TEST_KEY", **kw)


def test_plain_answer_and_reasoning_setting(monkeypatch, client):
    s = Server(monkeypatch, chat('{"promos": [1]}'))
    assert client(reasoning="medium").ask_json("s", "u", expect="promos") == {"promos": [1]}
    assert s.bodies[0]["reasoning_effort"] == "medium" and s.bodies[0]["response_format"] == {"type": "json_object"}


def test_openrouter_reasoning_style(monkeypatch, client):
    s = Server(monkeypatch, chat('{"promos": []}'))
    client(reasoning="low", reasoning_style="openrouter").ask_json("s", "u", expect="promos")
    assert s.bodies[0]["reasoning"] == {"effort": "low"} and "reasoning_effort" not in s.bodies[0]


def test_unsupported_parameter_is_dropped(monkeypatch, client):
    s = Server(monkeypatch, (400, '{"error": "Unrecognized request argument: reasoning_effort"}'), chat('{"promos": []}'))
    c = client(reasoning="medium")
    assert c.ask_json("s", "u", expect="promos") == {"promos": []}
    assert "reasoning_effort" not in s.bodies[1] and c.usage["dropped_params"] == ["reasoning_effort"]


def test_json_mode_failure_drops_json_mode(monkeypatch, client):      # Groq: 400 json_validate_failed
    s = Server(monkeypatch, (400, '{"error":{"code":"json_validate_failed","message":"Failed to validate JSON"}}'),
               chat('{"promos": [5]}'))
    assert client().ask_json("s", "u", expect="promos") == {"promos": [5]}
    assert "response_format" not in s.bodies[1]


def test_cut_off_reply_doubles_the_budget(monkeypatch, client):       # hidden reasoning ate the tokens
    s = Server(monkeypatch, chat("", finish="length"), chat('{"promos": []}'))
    c = client(max_tokens=4096)
    assert c.ask_json("s", "u", expect="promos") == {"promos": []}
    assert s.bodies[1]["max_tokens"] == 8192 and c.usage["cut_off_retries"] == 1


def test_wrong_shape_gets_one_repair_turn(monkeypatch, client):
    s = Server(monkeypatch, chat('Here are my thoughts: the hook is strong.'), chat('{"promos": [7]}'))
    c = client()
    assert c.ask_json("s", "u", expect="promos") == {"promos": [7]}
    assert c.usage["json_repairs"] == 1 and "ONLY the JSON object" in s.bodies[1]["messages"][-1]["content"]


def test_gives_up_after_one_repair(monkeypatch, client):
    Server(monkeypatch, chat("no json"), chat("still no json"))
    with pytest.raises(ValueError): client().ask_json("s", "u", expect="promos")


def test_answer_only_in_reasoning_field(monkeypatch, client):         # some models leave content empty
    Server(monkeypatch, chat("", reasoning_content='thinking... final: {"promos": [9]}'))
    assert client().ask_json("s", "u", expect="promos") == {"promos": [9]}


def test_content_as_list_of_parts(monkeypatch, client):
    Server(monkeypatch, chat([{"type": "text", "text": '{"promos": '}, {"type": "text", "text": "[1]}"}]))
    assert client().ask_json("s", "u", expect="promos") == {"promos": [1]}


def test_bad_key_stops_at_once(monkeypatch, client):
    s = Server(monkeypatch, (401, '{"error": "Invalid API key"}'))
    with pytest.raises(RuntimeError, match="Check the key"): client().ask_json("s", "u")
    assert len(s.bodies) == 1


def test_rate_limit_waits_as_told(monkeypatch, client):
    s = Server(monkeypatch, (429, '{"error": "Rate limit. Please try again in 12.5s"}'), chat('{"a": 1}'))
    assert client().ask_json("s", "u") == {"a": 1} and s.sleeps == [13.5]


def test_bedrock_converse_shape(monkeypatch, client):
    reply = {"output": {"message": {"content": [{"reasoningContent": {"reasoningText": {"text": "hmm {"}}},
                                                 {"text": '{"clips": [{"id": "E1-1"}]}'}]}},
             "stopReason": "end_turn", "usage": {"inputTokens": 7, "outputTokens": 3}}
    s = Server(monkeypatch, reply)
    c = client(api="converse")
    assert c.ask_json("s", "u", expect="clips") == {"clips": [{"id": "E1-1"}]}
    assert s.bodies[0]["inferenceConfig"]["maxTokens"] == 8192 and c.usage["prompt_tokens"] == 7


def test_missing_key_only_fails_when_a_call_is_needed(monkeypatch):
    monkeypatch.delenv("NO_SUCH_KEY", raising=False)
    c = L.LLM(base_url="http://x/v1", model="m", key_env="NO_SUCH_KEY")         # building the client is fine
    with pytest.raises(RuntimeError, match="NO_SUCH_KEY"): c.ask_json("s", "u")


@pytest.mark.parametrize("spec,base,api,reasoning", [
    ("groq/openai/gpt-oss-120b", "https://api.groq.com/openai/v1", "openai", "medium"),      # model id with a slash
    ("bedrock/openai.gpt-oss-120b-1:0", "/openai/v1", "openai", "medium"),
    ("bedrock/deepseek.v3.2", "amazonaws.com", "converse", None),
    ("bedrock/us.deepseek.r1-v1:0", "amazonaws.com", "converse", "medium"),
    ("openai/gpt-4.1", "https://api.openai.com/v1", "openai", None),
    ("ollama/llama3.1", "http://localhost:11434/v1", "openai", None),
])
def test_one_string_picks_a_model(spec, base, api, reasoning):
    s = L.model_settings(spec)
    assert base in s["base_url"] and s.get("api", "openai") == api and s.get("reasoning") == reasoning
    assert s["model"] == spec.split("/", 1)[1]


def test_unknown_provider_and_config_override():
    with pytest.raises(SystemExit, match="Unknown provider"): L.model_settings("nope/model")
    s = L.model_settings("myapi/m1", {"providers": {"myapi": {"base_url": "https://x/v1", "key_env": "K"}}})
    assert s["base_url"] == "https://x/v1" and s["model"] == "m1"
    assert L.model_settings("groq/x", {"providers": {"groq": {"reasoning": "low"}}})["reasoning"] == "low"


def test_ollama_needs_no_key():
    assert L.make_llm("ollama/llama3.1").key == "none"
