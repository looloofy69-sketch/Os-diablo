import json
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.services.llm import CallBudget, ChatClient, LLMError, _urllib_get, is_loopback


def openai_body(text, usage=None):
    return {"choices": [{"message": {"content": text}}], "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}


def anthropic_body(text):
    return {"content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": text}], "usage": {"input_tokens": 7, "output_tokens": 3}}


class Capture:
    def __init__(self, body):
        self.body, self.calls = body, []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        return self.body


class ClientTests(unittest.TestCase):
    def test_openai_compatible_request_and_response(self):
        cap = Capture(openai_body("<think>x</think>hello"))
        client = ChatClient("openai_compatible", "m", "http://127.0.0.1:8001", api_key="k", transport=cap)
        reply = client.complete("sys", [{"role": "user", "content": "hi"}])
        url, headers, payload, _ = cap.calls[0]
        self.assertEqual(url, "http://127.0.0.1:8001/v1/chat/completions")
        self.assertEqual(headers["authorization"], "Bearer k")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "sys"})
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual((reply.text, reply.usage), ("hello", {"input_tokens": 10, "output_tokens": 5}))

    def test_base_url_already_ending_in_v1(self):
        client = ChatClient("openai_compatible", "m", "https://api.example.com/v1/", transport=Capture(openai_body("x")))
        self.assertEqual(client.url, "https://api.example.com/v1/chat/completions")

    def test_anthropic_request_and_text_block_extraction(self):
        cap = Capture(anthropic_body("plan"))
        client = ChatClient("anthropic", "claude-x", api_key="sk-secret", transport=cap)
        reply = client.complete("sys", [{"role": "user", "content": "hi"}])
        url, headers, payload, _ = cap.calls[0]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], "sk-secret")
        self.assertIn("anthropic-version", headers)
        self.assertEqual((payload["system"], payload["messages"][0]["role"]), ("sys", "user"))
        self.assertNotIn("system", [m["role"] for m in payload["messages"]])
        self.assertEqual((reply.text, reply.usage["output_tokens"]), ("plan", 3))

    def test_model_api_does_not_follow_redirect_with_provider_credentials(self):
        hits = {"models": 0, "target": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
                if self.path == "/models":
                    hits["models"] += 1
                    self.send_response(302)
                    self.send_header("Location", "/target")
                    self.end_headers()
                    self.wfile.write(b"redirect")
                else:
                    hits["target"] += 1
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"data": []}')

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(LLMError) as ctx:
                _urllib_get(f"http://127.0.0.1:{server.server_port}/models", {"authorization": "Bearer secret"}, 2.0)
            self.assertIn("HTTP 302", str(ctx.exception))
            self.assertEqual(hits, {"models": 1, "target": 0})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_configuration_errors(self):
        with self.assertRaises(ValueError):
            ChatClient("anthropic", "m")  # no key
        with self.assertRaises(ValueError):
            ChatClient("openai_compatible", "m")  # no base url
        with self.assertRaises(ValueError):
            ChatClient("openai_compatible", "m", "file:///etc/passwd")
        with self.assertRaises(ValueError):
            ChatClient("carrier-pigeon", "m", "http://x")

    def test_bad_shapes_and_empty_responses_raise_llm_error(self):
        for body in ({}, {"choices": []}, {"choices": [{"message": {"content": None}}]}, {"choices": [{"message": {"content": "<think>only</think>"}}]}):
            client = ChatClient("openai_compatible", "m", "http://127.0.0.1:1", transport=Capture(body))
            with self.assertRaises(LLMError, msg=str(body)):
                client.complete("s", [{"role": "user", "content": "x"}])

    def test_transport_errors_propagate_as_llm_error_without_secrets(self):
        def boom(*_):
            raise LLMError("provider unreachable: URLError")
        client = ChatClient("anthropic", "m", api_key="sk-secret", transport=boom)
        with self.assertRaises(LLMError) as ctx:
            client.complete("s", [{"role": "user", "content": "x"}])
        self.assertNotIn("sk-secret", str(ctx.exception))

    def test_budget_blocks_calls_before_transport(self):
        cap = Capture(openai_body("ok"))
        client = ChatClient("openai_compatible", "m", "http://127.0.0.1:1", transport=cap, budget=CallBudget(2))
        for _ in range(2):
            client.complete("s", [{"role": "user", "content": "x"}])
        with self.assertRaisesRegex(LLMError, "daily"):
            client.complete("s", [{"role": "user", "content": "x"}])
        self.assertEqual(len(cap.calls), 2)

    def test_budget_resets_on_new_day_and_zero_disables(self):
        today = [date(2026, 10, 10)]
        budget = CallBudget(1, today=lambda: today[0])
        self.assertTrue(budget.try_acquire())
        self.assertFalse(budget.try_acquire())
        today[0] = date(2026, 10, 11)
        self.assertTrue(budget.try_acquire())
        self.assertTrue(all(CallBudget(0).try_acquire() for _ in range(100)))

    def test_loopback_detection(self):
        self.assertTrue(is_loopback("http://127.0.0.1:8001") and is_loopback("http://localhost/x"))
        self.assertFalse(is_loopback("http://10.0.0.5") or is_loopback("https://api.anthropic.com"))
        json.dumps(openai_body("x"))


if __name__ == "__main__":
    unittest.main()
