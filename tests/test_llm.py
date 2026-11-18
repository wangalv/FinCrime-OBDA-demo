"""The LLM client against a small fake server on localhost: no real provider, no key, nothing leaves the machine."""
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import llm  # noqa: E402


class Fake:
    """Starts a server that answers like a chat-completions API and records what it was sent."""

    def __init__(self, reply=None, reject_response_format=False, status=200, body=None):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "payload": payload})
                if reject_response_format and "response_format" in payload:
                    out, code = {"error": {"message": "unsupported parameter: response_format"}}, 400
                elif body is not None:
                    out, code = body, status
                else:
                    out, code = {"choices": [{"message": {"content": reply if reply is not None else '{"ok": true}'}}]}, status
                data = json.dumps(out).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def cfg(url, key="sk-test-123", model="some-model", **more):
    return {"api_key": key, "base_url": url, "model": model, "extra_body": more.get("extra", {}), "json_mode": more.get("json_mode", True)}


class Chat(unittest.TestCase):
    def test_request_goes_to_chat_completions_with_key_model_and_json_mode(self):
        f = Fake()
        try:
            text, secs = llm.chat("sys", "usr", temperature=0.2, seed=7, cfg=cfg(f.url))
        finally:
            f.close()
        r = f.requests[0]
        self.assertEqual(r["path"], "/v1/chat/completions")
        self.assertEqual(r["auth"], "Bearer sk-test-123")
        p = r["payload"]
        self.assertEqual((p["model"], p["temperature"], p["seed"]), ("some-model", 0.2, 7))
        self.assertEqual(p["messages"], [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}])
        self.assertEqual(p["response_format"], {"type": "json_object"})
        self.assertEqual(json.loads(text), {"ok": True})
        self.assertGreaterEqual(secs, 0)

    def test_no_key_means_no_authorization_header(self):
        f = Fake()
        try:
            llm.chat("s", "u", cfg=cfg(f.url, key=""))
        finally:
            f.close()
        self.assertIsNone(f.requests[0]["auth"])

    def test_a_named_model_overrides_the_configured_one_and_num_ctx_is_ignored(self):
        f = Fake()
        try:
            llm.chat("s", "u", model="other", num_ctx=8192, cfg=cfg(f.url))
        finally:
            f.close()
        self.assertEqual(f.requests[0]["payload"]["model"], "other")
        self.assertNotIn("num_ctx", f.requests[0]["payload"])

    def test_extra_body_is_merged_into_the_request(self):
        f = Fake()
        try:
            llm.chat("s", "u", cfg=cfg(f.url, extra={"thinking": {"type": "disabled"}}))
        finally:
            f.close()
        self.assertEqual(f.requests[0]["payload"]["thinking"], {"type": "disabled"})

    def test_json_mode_off_sends_no_response_format(self):
        f = Fake()
        try:
            llm.chat("s", "u", cfg=cfg(f.url, json_mode=False))
        finally:
            f.close()
        self.assertNotIn("response_format", f.requests[0]["payload"])

    def test_a_provider_that_rejects_response_format_is_asked_again_without_it(self):
        f = Fake(reject_response_format=True)
        try:
            text, _ = llm.chat("s", "u", cfg=cfg(f.url))
        finally:
            f.close()
        self.assertEqual(len(f.requests), 2)
        self.assertIn("response_format", f.requests[0]["payload"])
        self.assertNotIn("response_format", f.requests[1]["payload"])
        self.assertEqual(json.loads(text), {"ok": True})

    def test_a_code_fence_around_the_json_is_removed(self):
        f = Fake(reply='```json\n{"a": 1}\n```')
        try:
            text, _ = llm.chat("s", "u", cfg=cfg(f.url))
        finally:
            f.close()
        self.assertEqual(json.loads(text), {"a": 1})

    def test_errors_are_llm_errors_and_never_carry_the_key(self):
        f = Fake(status=401, body={"error": {"message": "bad key"}})
        try:
            with self.assertRaises(llm.LLMError) as e:
                llm.chat("s", "u", cfg=cfg(f.url, key="sk-secret-999"))
        finally:
            f.close()
        self.assertIn("401", str(e.exception))
        self.assertNotIn("sk-secret-999", str(e.exception))
        f = Fake(reply="   ")
        try:
            with self.assertRaises(llm.LLMError):
                llm.chat("s", "u", cfg=cfg(f.url))
        finally:
            f.close()
        f = Fake(body={"unexpected": 1})
        try:
            with self.assertRaises(llm.LLMError):
                llm.chat("s", "u", cfg=cfg(f.url))
        finally:
            f.close()

    def test_unreachable_server_is_an_llm_error(self):
        with self.assertRaises(llm.LLMError):
            llm.chat("s", "u", cfg=cfg("http://127.0.0.1:9/v1"), timeout=3)

    def test_not_configured_says_what_to_set(self):
        with self.assertRaises(llm.LLMError) as e:
            llm.chat("s", "u", cfg=cfg("", model=""))
        self.assertIn("LLM_BASE_URL", str(e.exception))
        self.assertIn("LLM_MODEL", str(e.exception))


class Settings(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / ".env"
        p.write_text(text, encoding="utf-8")
        return p

    def test_env_file_is_read_and_the_environment_wins(self):
        p = self.write('# comment\nLLM_BASE_URL="https://x.example/v1/"\nLLM_MODEL=m1\nLLM_API_KEY=k1\n')
        s = llm.settings(env={}, files=[p])
        self.assertEqual((s["base_url"], s["model"], s["api_key"]), ("https://x.example/v1", "m1", "k1"))      # the trailing / is dropped
        s = llm.settings(env={"LLM_MODEL": "m2"}, files=[p])
        self.assertEqual(s["model"], "m2")

    def test_the_first_file_wins_over_a_later_one(self):
        a, b = self.write("LLM_MODEL=from-a\n"), self.write("LLM_MODEL=from-b\nLLM_BASE_URL=https://b/v1\n")
        s = llm.settings(env={}, files=[a, b])
        self.assertEqual((s["model"], s["base_url"]), ("from-a", "https://b/v1"))

    def test_the_old_z_ai_names_are_read_when_the_new_ones_are_missing(self):
        s = llm.settings(env={"Z_AI_API_KEY": "zk", "Z_AI_BASE_URL": "https://z/v4", "Z_AI_CHAT_MODEL": "glm"}, files=[])
        self.assertEqual((s["api_key"], s["base_url"], s["model"]), ("zk", "https://z/v4", "glm"))
        s = llm.settings(env={"LLM_MODEL": "new", "Z_AI_CHAT_MODEL": "glm"}, files=[])
        self.assertEqual(s["model"], "new")

    def test_extra_body_and_json_mode(self):
        s = llm.settings(env={"LLM_EXTRA_BODY": '{"a": 1}', "LLM_JSON_MODE": "off"}, files=[])
        self.assertEqual((s["extra_body"], s["json_mode"]), ({"a": 1}, False))
        self.assertEqual(llm.settings(env={"LLM_EXTRA_BODY": "not json"}, files=[])["extra_body"], {})

    def test_missing_lists_what_is_not_set(self):
        self.assertEqual(llm.missing(llm.settings(env={}, files=[])), ["LLM_BASE_URL", "LLM_MODEL"])
        self.assertEqual(llm.missing(llm.settings(env={"LLM_BASE_URL": "u", "LLM_MODEL": "m"}, files=[])), [])


if __name__ == "__main__":
    unittest.main()
