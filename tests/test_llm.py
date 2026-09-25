from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx2 as httpx  # client HTTP embarque par anthropic 1.x
import pytest

import clipper.llm as llm
from clipper.config import Config
from clipper.llm import LLMError, SchemaError, TransientLLMError
from clipper.llm.fake import FakeBackend

COLOR_SCHEMA = {
    "type": "object",
    "properties": {"couleur": {"type": "string"}},
    "required": ["couleur"],
    "additionalProperties": False,
}

# Sortie reelle de `claude -p --output-format json` (Claude Code 2.1.282),
# enregistree une fois sur une image rouge, champs de telemetrie retires.
RECORDED_CLAUDE_CLI_OK = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "api_error_status": None,
    "num_turns": 2,
    "duration_ms": 8679,
    "stop_reason": "end_turn",
    "terminal_reason": "completed",
    "session_id": "9f30ba08-d590-421a-b1ee-aaab1a469667",
    "total_cost_usd": 0.7325792000000001,
    "permission_denials": [],
    "result": '{"couleur": "rouge"}',
}

# Meme forme, cas d'erreur quota (is_error + api_error_status 429).
RECORDED_CLAUDE_CLI_QUOTA = {
    "type": "result",
    "subtype": "success",
    "is_error": True,
    "api_error_status": 429,
    "num_turns": 1,
    "result": "Claude AI usage limit reached|1790000000",
    "session_id": "00000000-0000-0000-0000-000000000000",
}


def make_config(**llm_table) -> Config:
    return Config(
        mode="review",
        workspace_dir=Path("workspace"),
        output_dir=Path("output"),
        _sections={"llm": llm_table} if llm_table else {},
    )


class FakeRun:
    """Stands in for subprocess.run: records the call, returns a canned
    CompletedProcess."""

    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[dict] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), **kwargs})
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


@pytest.fixture
def fake_run(monkeypatch):
    def _install(stdout, returncode=0, stderr=""):
        run = FakeRun(stdout, returncode, stderr)
        monkeypatch.setattr("clipper.llm.claude_cli.subprocess.run", run)
        return run

    return _install


# --- config par usage -------------------------------------------------------


def test_llm_section_is_declared_with_claude_cli_as_default_backend():
    section = make_config().section("llm")
    assert section["backend"] == "claude-cli"


def test_usage_strong_tier_maps_to_opus_and_other_usages_to_sonnet(fake_run):
    run = fake_run(json.dumps(RECORDED_CLAUDE_CLI_OK))
    cfg = make_config()

    llm.ask("moments", "p", [], COLOR_SCHEMA, config=cfg)
    llm.ask("captions", "p", [], COLOR_SCHEMA, config=cfg)

    models = [c["cmd"][c["cmd"].index("--model") + 1] for c in run.calls]
    assert models == ["opus", "sonnet"]


def test_usage_can_override_backend_and_literal_model():
    fake = FakeBackend([{"couleur": "bleu"}])
    cfg = make_config(usages={"qa": {"backend": "fake", "model": "mon-modele"}})

    with llm.register_backend("fake", lambda settings: fake):
        out = llm.ask("qa", "p", [], COLOR_SCHEMA, config=cfg)

    assert out == {"couleur": "bleu"}
    assert fake.calls[0].model == "mon-modele"
    assert fake.calls[0].usage == "qa"


def test_unknown_backend_is_an_error():
    cfg = make_config(backend="nope")
    with pytest.raises(LLMError, match="nope"):
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=cfg)


# --- backend claude-cli -----------------------------------------------------


def test_claude_cli_builds_print_json_command_and_parses_recorded_output(fake_run):
    run = fake_run(json.dumps(RECORDED_CLAUDE_CLI_OK))

    out = llm.ask("vision", "De quelle couleur ?", [], COLOR_SCHEMA, config=make_config())

    assert out == {"couleur": "rouge"}
    cmd = run.calls[0]["cmd"]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    # Le prompt passe par stdin (transcriptions longues > limite de ligne Windows).
    assert "De quelle couleur ?" in run.calls[0]["input"]


def test_claude_cli_passes_images_as_files_readable_by_read_tool(fake_run, tmp_path):
    img = tmp_path / "frames" / "f001.jpg"
    img.parent.mkdir()
    img.write_bytes(b"\xff\xd8")
    run = fake_run(json.dumps(RECORDED_CLAUDE_CLI_OK))

    llm.ask("vision", "Decris.", [img], COLOR_SCHEMA, config=make_config())

    cmd = run.calls[0]["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    assert cmd[cmd.index("--add-dir") + 1] == str(img.parent.resolve())
    assert str(img.resolve()) in run.calls[0]["input"]


def test_claude_cli_without_images_disables_all_tools(fake_run):
    run = fake_run(json.dumps(RECORDED_CLAUDE_CLI_OK))
    llm.ask("captions", "p", [], COLOR_SCHEMA, config=make_config())
    cmd = run.calls[0]["cmd"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--add-dir" not in cmd


def test_claude_cli_accepts_json_wrapped_in_markdown_fence(fake_run):
    fenced = dict(RECORDED_CLAUDE_CLI_OK, result='```json\n{"couleur": "vert"}\n```')
    fake_run(json.dumps(fenced))
    assert llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config()) == {"couleur": "vert"}


def test_claude_cli_quota_is_transient(fake_run):
    fake_run(json.dumps(RECORDED_CLAUDE_CLI_QUOTA), returncode=1)
    with pytest.raises(TransientLLMError, match="limit"):
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config())


def test_claude_cli_other_error_is_not_transient(fake_run):
    bad = dict(RECORDED_CLAUDE_CLI_QUOTA, api_error_status=400, result="invalid model")
    fake_run(json.dumps(bad), returncode=1)
    with pytest.raises(LLMError) as exc:
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config())
    assert not isinstance(exc.value, TransientLLMError)


def test_claude_cli_timeout_is_transient(monkeypatch):
    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr("clipper.llm.claude_cli.subprocess.run", boom)
    with pytest.raises(TransientLLMError):
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config())


def test_claude_cli_missing_binary_is_a_permanent_error(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr("clipper.llm.claude_cli.subprocess.run", missing)
    with pytest.raises(LLMError) as exc:
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config())
    assert not isinstance(exc.value, TransientLLMError)


# --- validation de schema ---------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        "pas du json",
        '{"color": "rouge"}',
        '{"couleur": 3}',
        '{"couleur": "rouge", "extra": 1}',
        '["rouge"]',
    ],
)
def test_non_conforming_response_raises_schema_error(fake_run, result):
    fake_run(json.dumps(dict(RECORDED_CLAUDE_CLI_OK, result=result)))
    with pytest.raises(SchemaError):
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config())


def test_schema_error_is_neither_transient_nor_silent():
    assert issubclass(SchemaError, LLMError)
    assert not issubclass(SchemaError, TransientLLMError)


@pytest.mark.parametrize(
    "value,ok",
    [
        ({"moments": [{"start": 1.5, "end": 3, "score": 7, "kind": "rire"}]}, True),
        ({"moments": [{"start": 1.5, "end": 3, "score": 11, "kind": "rire"}]}, False),
        ({"moments": [{"start": 1.5, "end": 3, "score": 7, "kind": "autre"}]}, False),
        ({"moments": [{"start": "1.5", "end": 3, "score": 7, "kind": "rire"}]}, False),
        ({"moments": [{"start": 1.5, "end": 3, "score": 7.5, "kind": "rire"}]}, False),
        ({"moments": []}, False),
        ({"moments": [{"start": True, "end": 3, "score": 7, "kind": "rire"}]}, False),
    ],
)
def test_schema_validator_covers_nested_types_ranges_enums(value, ok):
    schema = {
        "type": "object",
        "required": ["moments"],
        "properties": {
            "moments": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["start", "end", "score", "kind"],
                    "properties": {
                        "start": {"type": "number"},
                        "end": {"type": "number"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 10},
                        "kind": {"enum": ["rire", "clash"]},
                    },
                },
            }
        },
    }
    fake = FakeBackend([value])
    with llm.register_backend("fake", lambda s: fake):
        if ok:
            assert llm.ask("moments", "p", [], schema, config=make_config(backend="fake")) == value
        else:
            with pytest.raises(SchemaError):
                llm.ask("moments", "p", [], schema, config=make_config(backend="fake"))


# --- backend ollama ---------------------------------------------------------


class _OllamaHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    reply: tuple[int, dict] = (200, {})

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        type(self).requests.append({"path": self.path, "body": json.loads(self.rfile.read(length))})
        status, body = type(self).reply
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def ollama_server():
    handler = type("H", (_OllamaHandler,), {"requests": [], "reply": (200, {})})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield handler, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_ollama_calls_local_chat_api_with_keep_alive_zero(ollama_server, tmp_path):
    handler, url = ollama_server
    # Reponse de /api/chat d'ollama (stream: false), forme enregistree.
    handler.reply = (
        200,
        {
            "model": "qwen2.5vl:7b",
            "created_at": "2026-09-25T10:00:00Z",
            "message": {"role": "assistant", "content": '{"couleur": "rouge"}'},
            "done": True,
            "done_reason": "stop",
        },
    )
    img = tmp_path / "f.png"
    img.write_bytes(b"PNGDATA")
    cfg = make_config(backend="ollama", ollama={"url": url, "models": {"fast": "qwen2.5vl:7b"}})

    out = llm.ask("vision", "Couleur ?", [img], COLOR_SCHEMA, config=cfg)

    assert out == {"couleur": "rouge"}
    req = handler.requests[0]
    assert req["path"] == "/api/chat"
    body = req["body"]
    assert body["keep_alive"] == 0
    assert body["stream"] is False
    assert body["model"] == "qwen2.5vl:7b"
    assert body["format"] == COLOR_SCHEMA
    msg = body["messages"][-1]
    assert "Couleur ?" in msg["content"]
    assert msg["images"] == ["UE5HREFUQQ=="]  # base64(b"PNGDATA")


def test_ollama_unreachable_is_transient():
    cfg = make_config(backend="ollama", ollama={"url": "http://127.0.0.1:1"})
    with pytest.raises(TransientLLMError):
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=cfg)


def test_ollama_server_error_is_transient_and_bad_model_is_not(ollama_server):
    handler, url = ollama_server
    cfg = make_config(backend="ollama", ollama={"url": url})

    handler.reply = (503, {"error": "busy"})
    with pytest.raises(TransientLLMError):
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=cfg)

    handler.reply = (404, {"error": "model 'x' not found"})
    with pytest.raises(LLMError) as exc:
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=cfg)
    assert not isinstance(exc.value, TransientLLMError)
    assert "not found" in str(exc.value)


# --- backend claude-api -----------------------------------------------------


class FakeMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeAnthropic:
    def __init__(self, outcome):
        self.messages = FakeMessages(outcome)


def _api_message(text):
    # Forme d'un anthropic.types.Message (attributs utilises seulement).
    from types import SimpleNamespace

    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
    )


def test_claude_api_sends_images_as_base64_blocks_with_full_model_id(monkeypatch, tmp_path):
    client = FakeAnthropic(_api_message('{"couleur": "rouge"}'))
    monkeypatch.setattr("clipper.llm.claude_api.make_client", lambda settings: client)
    img = tmp_path / "f.jpg"
    img.write_bytes(b"JPG")
    cfg = make_config(backend="claude-api")

    out = llm.ask("moments", "Couleur ?", [img], COLOR_SCHEMA, config=cfg)

    assert out == {"couleur": "rouge"}
    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    content = call["messages"][0]["content"]
    assert content[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "SlBH"},
    }
    assert content[-1]["type"] == "text" and "Couleur ?" in content[-1]["text"]


def _request():
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda anthropic: anthropic.APIConnectionError(request=_request()),
        lambda anthropic: anthropic.RateLimitError(
            "rate", response=httpx.Response(429, request=_request()), body=None
        ),
        lambda anthropic: anthropic.InternalServerError(
            "overloaded", response=httpx.Response(529, request=_request()), body=None
        ),
    ],
)
def test_claude_api_quota_and_network_are_transient(monkeypatch, exc_factory):
    import anthropic

    client = FakeAnthropic(exc_factory(anthropic))
    monkeypatch.setattr("clipper.llm.claude_api.make_client", lambda settings: client)
    with pytest.raises(TransientLLMError):
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config(backend="claude-api"))


def test_claude_api_bad_request_is_permanent(monkeypatch):
    import anthropic

    err = anthropic.BadRequestError("bad", response=httpx.Response(400, request=_request()), body=None)
    monkeypatch.setattr("clipper.llm.claude_api.make_client", lambda s: FakeAnthropic(err))
    with pytest.raises(LLMError) as exc:
        llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config(backend="claude-api"))
    assert not isinstance(exc.value, TransientLLMError)


# --- backend fake -----------------------------------------------------------


def test_fake_backend_replays_responses_and_records_calls(tmp_path):
    fake = FakeBackend([{"couleur": "rouge"}, '{"couleur": "vert"}'])
    img = tmp_path / "a.png"

    with llm.use_backend(fake):
        first = llm.ask("vision", "un", [img], COLOR_SCHEMA, config=make_config())
        second = llm.ask("qa", "deux", [], COLOR_SCHEMA, config=make_config())

    assert (first, second) == ({"couleur": "rouge"}, {"couleur": "vert"})
    assert [c.usage for c in fake.calls] == ["vision", "qa"]
    assert fake.calls[0].images == [img]
    assert "un" in fake.calls[0].prompt


def test_fake_backend_still_goes_through_schema_validation():
    with llm.use_backend(FakeBackend([{"wrong": 1}])):
        with pytest.raises(SchemaError):
            llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config())


def test_fake_backend_can_raise_and_compute_responses():
    fake = FakeBackend([TransientLLMError("quota"), lambda req: {"couleur": req.usage}])
    with llm.use_backend(fake):
        with pytest.raises(TransientLLMError):
            llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config())
        assert llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config()) == {"couleur": "qa"}


def test_fake_backend_exhausted_fails_loudly():
    with llm.use_backend(FakeBackend([])):
        with pytest.raises(AssertionError, match="FakeBackend"):
            llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config())


def test_use_backend_restores_config_backend_on_exit(fake_run):
    fake_run(json.dumps(RECORDED_CLAUDE_CLI_OK))
    with llm.use_backend(FakeBackend([{"couleur": "bleu"}])):
        pass
    assert llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config()) == {"couleur": "rouge"}
