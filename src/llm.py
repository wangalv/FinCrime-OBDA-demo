"""Minimal client for any LLM that offers an OpenAI-compatible chat API (OpenAI, Z.ai, OpenRouter, vLLM, a local server, ...).

chat(system, user, model, temperature) -> (text, seconds). Raises LLMError if the API cannot be reached, refuses the call, or answers with
nothing. The reply is asked for as a JSON object so that the SPARQL can be cut out reliably; checking what is inside is the guard's job.

Configuration comes from the environment, or from a `.env` file in the repository root (git-ignored; see `.env.example`):
  LLM_API_KEY    the key of the provider. Never put it in code. Empty is allowed for a server that needs none.
  LLM_BASE_URL   the API root, for example https://api.openai.com/v1 ; the call goes to <base>/chat/completions
  LLM_MODEL      the model name the provider uses
  LLM_EXTRA_BODY optional JSON object merged into every request, for a provider-specific switch (for example one that turns thinking off)
  LLM_JSON_MODE  "off" to never send response_format (default: sent, and dropped for good if the provider rejects it)
For compatibility with the AML Triage Demo, Z_AI_API_KEY, Z_AI_BASE_URL and Z_AI_CHAT_MODEL are read when the LLM_* ones are not set.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILES = [ROOT / ".env", ROOT / "demo" / ".env"]          # the first file that sets a name wins; real environment variables win over both
_ALIASES = {"LLM_API_KEY": "Z_AI_API_KEY", "LLM_BASE_URL": "Z_AI_BASE_URL", "LLM_MODEL": "Z_AI_CHAT_MODEL"}


class LLMError(RuntimeError):
    pass


def _read_env_file(path):
    out = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def settings(env=None, files=None):
    """{'api_key', 'base_url', 'model', 'extra_body', 'json_mode'}: what the next call will use. Never raises."""
    merged = {}
    for f in reversed(ENV_FILES if files is None else files):       # earlier files override later ones
        merged.update(_read_env_file(f))
    merged.update(os.environ if env is None else env)               # the real environment overrides the files

    def pick(name):
        return (merged.get(name) or merged.get(_ALIASES.get(name, ""), "") or "").strip()

    extra = {}
    raw = pick("LLM_EXTRA_BODY")
    if raw:
        try:
            parsed = json.loads(raw)
            extra = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            extra = {}
    return {"api_key": pick("LLM_API_KEY"), "base_url": pick("LLM_BASE_URL").rstrip("/"), "model": pick("LLM_MODEL"), "extra_body": extra,
            "json_mode": pick("LLM_JSON_MODE").lower() != "off"}


def missing(cfg=None):
    """What is not configured yet, as a list of names (empty when a call can be made). The key is not required."""
    cfg = cfg or settings()
    return [n for n, k in (("LLM_BASE_URL", "base_url"), ("LLM_MODEL", "model")) if not cfg[k]]


DEFAULT_MODEL = settings()["model"]          # what the page offers in its model box; a call can name another model


def _strip_fence(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _post(url, payload, key, timeout):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def chat(system, user, model=None, temperature=0.3, num_ctx=None, timeout=600, seed=None, cfg=None):
    """num_ctx is accepted and ignored (it belonged to the old local-model client); the API decides the context window."""
    cfg = cfg or settings()
    model = model or cfg["model"]
    gaps = [n for n, ok in (("LLM_BASE_URL", cfg["base_url"]), ("LLM_MODEL", model)) if not ok]
    if gaps:
        raise LLMError("the LLM is not configured: set " + ", ".join(gaps) + " (in the environment or in .env; see .env.example)")
    payload = {"model": model, "temperature": temperature, "stream": False,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if seed is not None:
        payload["seed"] = seed
    payload.update(cfg["extra_body"])
    url = cfg["base_url"] + "/chat/completions"
    use_json_mode = cfg["json_mode"]
    t = time.time()
    for attempt in (1, 2):
        body = dict(payload)
        if use_json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            data = _post(url, body, cfg["api_key"], timeout)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if use_json_mode and e.code == 400 and attempt == 1 and "response_format" in detail.lower():
                use_json_mode = False                      # this provider does not take it: ask again without (the prompt already asks for JSON)
                continue
            raise LLMError(f"the LLM API answered HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            raise LLMError(f"the LLM API call failed: {e}") from e
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected answer shape from the LLM API: {str(data)[:200]}") from e
    if not isinstance(text, str) or not text.strip():
        raise LLMError("the LLM API returned an empty answer")
    return _strip_fence(text), time.time() - t
