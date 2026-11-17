"""Minimal client for a local Ollama model. No keys, no .env.

chat(system, user, model, temperature) -> (text, seconds). Raises LLMError if Ollama is not reachable or answers badly.
think is switched off (a reasoning model would spend minutes thinking). The reply is asked for as JSON so that the SPARQL can be
cut out reliably; checking what is inside is the guard's job, not this module's.
"""
import json
import time
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:9b"


class LLMError(RuntimeError):
    pass


def chat(system, user, model=DEFAULT_MODEL, temperature=0.3, num_ctx=8192, timeout=600, seed=None):
    options = {"temperature": temperature, "num_ctx": num_ctx}
    if seed is not None:
        options["seed"] = seed
    payload = {"model": model, "stream": False, "think": False, "format": "json", "options": options,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
        raise LLMError(f"Ollama call failed: {e}") from e
    text = (data.get("message") or {}).get("content")
    if not isinstance(text, str) or not text.strip():
        raise LLMError("Ollama returned an empty answer")
    return text, time.time() - t
