import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.services.llm import BudgetExceeded, CallBudget, LLMError, LLMReply
from app.services.model_pool import (
    EndpointConfig,
    ModelPool,
    NoModelAvailable,
    PoolExhausted,
    auto_endpoints,
    load_scores,
    merge_endpoints,
    parse_endpoints,
    quality_hint,
)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeClient:
    """Behaviour is a list consumed per call: a string is a reply, an Exception is raised."""

    def __init__(self, behaviour):
        self.behaviour, self.calls = list(behaviour), []

    def complete(self, system, messages):
        self.calls.append(messages)
        item = self.behaviour.pop(0) if self.behaviour else "ok"
        if isinstance(item, Exception):
            raise item
        return LLMReply(item, {"input_tokens": 10, "output_tokens": 2})


def make_pool(models_by_endpoint, behaviours=None, endpoints=None, **kwargs):
    behaviours = behaviours or {}
    clients = {}
    eps = endpoints or [EndpointConfig(name, "openai_compatible", f"http://127.0.0.1:{9000 + i}", hosted=False) for i, name in enumerate(models_by_endpoint)]

    def factory(endpoint, model):
        return clients.setdefault(f"{endpoint.name}/{model}", FakeClient(behaviours.get(f"{endpoint.name}/{model}", [])))

    def lister(endpoint):
        value = models_by_endpoint[endpoint.name]
        if isinstance(value, Exception):
            raise value
        return value

    clock = kwargs.pop("clock", Clock())
    pool = ModelPool(eps, client_factory=factory, lister=lister, clock=clock, **kwargs)
    return pool, clients, clock


def keys(pool, role="plan"):
    return [c.key for c in pool.candidates(role)]


class DiscoveryAndRankingTests(unittest.TestCase):
    def test_discovered_models_are_filtered_capped_and_ranked(self):
        pool, _, _ = make_pool({"local": ["tiny-0.6b", "embed-text-v2", "big-70b", "mid-8b", "whisper-large", "x-3b", "y-1b"]}, per_endpoint_cap=3)
        self.assertEqual(keys(pool), ["local/big-70b", "local/mid-8b", "local/x-3b"])

    def test_name_hints_cover_known_families(self):
        self.assertGreater(quality_hint("claude-opus-5-5"), quality_hint("claude-sonnet-5-5"))
        self.assertGreater(quality_hint("claude-sonnet-5-5"), quality_hint("claude-haiku-5-5"))
        self.assertGreater(quality_hint("gpt-5"), quality_hint("gpt-5-mini"))
        self.assertGreater(quality_hint("qwen3-32b"), quality_hint("qwen3-0.6b"))
        self.assertEqual(quality_hint("unknown-model"), 50.0)

    def test_measured_scores_override_hints_and_gate_planning(self):
        pool, _, _ = make_pool({"a": ["big-70b", "small-1b", "bad-8b"]}, scores={"a/small-1b": 0.95, "a/big-70b": 0.7, "bad-8b": 0.2})
        self.assertEqual(keys(pool), ["a/small-1b", "a/big-70b"])  # measured 95 beats measured 70; 0.2 is below the planning gate
        self.assertIn("a/bad-8b", keys(pool, "compose"))  # still usable for writing replies

    def test_priority_beats_quality_and_prefer_orders_tiers(self):
        eps = [
            EndpointConfig("hosted", "openai_compatible", "https://h.example/v1", hosted=True, priority=100),
            EndpointConfig("local", "openai_compatible", "http://127.0.0.1:1", hosted=False, priority=100),
        ]
        listing = {"hosted": ["gpt-5"], "local": ["tiny-1b"]}
        self.assertEqual(keys(make_pool(listing, endpoints=eps)[0]), ["hosted/gpt-5", "local/tiny-1b"])
        self.assertEqual(keys(make_pool(listing, endpoints=eps, prefer="local")[0]), ["local/tiny-1b", "hosted/gpt-5"])
        self.assertEqual(keys(make_pool(listing, endpoints=eps, prefer="hosted")[0])[0], "hosted/gpt-5")
        eps[1] = EndpointConfig("local", "openai_compatible", "http://127.0.0.1:1", hosted=False, priority=10)
        self.assertEqual(keys(make_pool(listing, endpoints=eps)[0])[0], "local/tiny-1b")

    def test_hosted_endpoints_can_be_excluded(self):
        eps = [EndpointConfig("hosted", "openai_compatible", "https://h.example/v1", hosted=True), EndpointConfig("local", "openai_compatible", "http://127.0.0.1:1", hosted=False)]
        pool, _, _ = make_pool({"hosted": ["gpt-5"], "local": ["m-8b"]}, endpoints=eps, allow_hosted=False)
        self.assertEqual(keys(pool), ["local/m-8b"])

    def test_pinned_models_skip_discovery(self):
        eps = [EndpointConfig("p", "openai_compatible", "http://127.0.0.1:1", models=("exact-model",))]
        pool, _, _ = make_pool({"p": LLMError("never called")}, endpoints=eps)
        self.assertEqual(keys(pool), ["p/exact-model"])

    def test_refresh_interval_changes_and_failure_tolerance(self):
        listing = {"a": ["m-8b"]}
        pool, _, clock = make_pool(listing, refresh_seconds=100)
        self.assertEqual(keys(pool), ["a/m-8b"])
        listing["a"] = ["m-8b", "new-70b"]
        self.assertEqual(keys(pool), ["a/m-8b"])  # cached
        clock.now += 101
        self.assertEqual(keys(pool), ["a/new-70b", "a/m-8b"])  # a model appeared
        listing["a"] = LLMError("blip")
        clock.now += 101
        self.assertEqual(keys(pool), ["a/new-70b", "a/m-8b"])  # a failed refresh keeps the last known list

    def test_nothing_reachable_means_no_candidates(self):
        pool, _, _ = make_pool({"a": LLMError("refused")})
        self.assertFalse(pool.available())
        with self.assertRaises(NoModelAvailable):
            pool.complete("plan", "s", [{"role": "user", "content": "x"}])
        self.assertEqual(pool.status()[0]["available"], False)


class FailoverTests(unittest.TestCase):
    msgs = [{"role": "user", "content": "hi"}]

    def test_cascades_past_a_failing_model(self):
        pool, clients, _ = make_pool({"a": ["big-70b", "mid-8b"]}, {"a/big-70b": [LLMError("down")], "a/mid-8b": ["hello"]})
        result = pool.complete("plan", "s", self.msgs)
        self.assertEqual((result.model, result.text), ("mid-8b", "hello"))
        self.assertEqual([a.ok for a in result.attempts], [False, True])

    def test_breaker_opens_after_repeated_failures_and_recovers(self):
        pool, clients, clock = make_pool({"a": ["big-70b", "mid-8b"]}, {"a/big-70b": [LLMError("x")] * 3 + ["back"]})
        for _ in range(3):
            pool.complete("plan", "s", self.msgs)
        self.assertEqual(keys(pool), ["a/mid-8b"])  # big is cooling down
        clock.now += 61
        self.assertEqual(keys(pool)[0], "a/big-70b")
        self.assertEqual(pool.complete("plan", "s", self.msgs).text, "back")

    def test_all_failing_raises_with_attempt_trail(self):
        pool, _, _ = make_pool({"a": ["big-70b", "mid-8b"]}, {"a/big-70b": [LLMError("one")], "a/mid-8b": [LLMError("two")]})
        with self.assertRaises(PoolExhausted) as ctx:
            pool.complete("plan", "s", self.msgs)
        self.assertEqual(len(ctx.exception.attempts), 2)

    def test_cascade_is_bounded(self):
        pool, clients, _ = make_pool({"a": ["a-70b", "b-32b", "c-14b", "d-8b"]}, {k: [LLMError("x")] for k in ("a/a-70b", "a/b-32b", "a/c-14b", "a/d-8b")}, max_cascade=2)
        with self.assertRaises(PoolExhausted):
            pool.complete("plan", "s", self.msgs)
        self.assertEqual(sum(len(c.calls) for c in clients.values()), 2)

    def test_preferred_key_goes_first(self):
        pool, _, _ = make_pool({"a": ["big-70b", "mid-8b"]})
        self.assertEqual(pool.complete("compose", "s", self.msgs, prefer_key="a/mid-8b").model, "mid-8b")

    def test_budgets_stop_calls_without_tripping_breakers(self):
        pool, clients, _ = make_pool({"a": ["big-70b"]}, budget=CallBudget(1))
        pool.complete("plan", "s", self.msgs)
        for _ in range(5):
            with self.assertRaises(BudgetExceeded):
                pool.complete("plan", "s", self.msgs)
        self.assertEqual(keys(pool), ["a/big-70b"])
        self.assertEqual(len(clients["a/big-70b"].calls), 1)

    def test_endpoint_daily_limit(self):
        eps = [EndpointConfig("paid", "openai_compatible", "https://h.example/v1", daily_limit=1, models=("gpt-5",)), EndpointConfig("free", "openai_compatible", "http://127.0.0.1:1", hosted=False, models=("m-8b",), priority=200)]
        pool, _, _ = make_pool({"paid": [], "free": []}, endpoints=eps)
        self.assertEqual(pool.complete("plan", "s", self.msgs).model, "gpt-5")
        self.assertEqual(pool.complete("plan", "s", self.msgs).model, "m-8b")  # paid cap reached: next candidate takes over


class CheckedCascadeTests(unittest.TestCase):
    msgs = [{"role": "user", "content": "plan this"}]

    @staticmethod
    def check(text):
        ok = text.startswith("{")
        return ok, {"n": text} if ok else None, None if ok else "not json"

    @staticmethod
    def repair(messages, bad, error):
        return [*messages, {"role": "assistant", "content": bad}, {"role": "user", "content": f"fix: {error}"}]

    def test_repair_on_same_model_then_success(self):
        pool, clients, _ = make_pool({"a": ["big-70b"]}, {"a/big-70b": ["garbage", "{}"]})
        result = pool.complete_checked("plan", "s", self.msgs, self.check, self.repair)
        self.assertEqual((result.parsed, len(clients["a/big-70b"].calls)), ({"n": "{}"}, 2))
        self.assertIn("fix: not json", clients["a/big-70b"].calls[1][-1]["content"])
        self.assertEqual(result.usage, {"input_tokens": 20, "output_tokens": 4})

    def test_falls_to_next_model_when_repair_fails_and_demotes_the_first(self):
        pool, _, _ = make_pool({"a": ["big-70b", "mid-8b"]}, {"a/big-70b": ["x", "y"], "a/mid-8b": ["{}"]})
        result = pool.complete_checked("plan", "s", self.msgs, self.check, self.repair)
        self.assertEqual(result.model, "mid-8b")
        self.assertEqual([a.ok for a in result.attempts], [False, False, True])
        self.assertEqual(keys(pool)[0], "a/big-70b")  # one quality failure is a small penalty, not an exclusion

    def test_repeated_quality_failures_demote_ranking(self):
        pool, _, _ = make_pool({"a": ["big-70b", "mid-8b"]}, {"a/big-70b": ["x", "y"] * 3, "a/mid-8b": ["{}"] * 3})
        for _ in range(3):
            pool.complete_checked("plan", "s", self.msgs, self.check, self.repair)
        self.assertEqual(keys(pool)[0], "a/mid-8b")

    def test_exhaustion_lists_every_attempt(self):
        pool, _, _ = make_pool({"a": ["big-70b"]}, {"a/big-70b": ["x", "y"]})
        with self.assertRaises(PoolExhausted) as ctx:
            pool.complete_checked("plan", "s", self.msgs, self.check, self.repair)
        self.assertEqual(len(ctx.exception.attempts), 2)


class ConfigTests(unittest.TestCase):
    def test_parse_endpoints(self):
        raw = json.dumps([
            {"name": "local", "base_url": "http://127.0.0.1:8001", "model": "qwen"},
            {"name": "claude", "provider": "anthropic", "api_key_env": "K", "roles": ["plan"], "priority": 50, "daily_limit": 100},
        ])
        local, claude = parse_endpoints(raw, {"K": "secret"})
        self.assertEqual((local.models, local.hosted), (("qwen",), False))
        self.assertEqual((claude.base_url, claude.api_key, claude.roles, claude.hosted), ("https://api.anthropic.com", "secret", frozenset({"plan"}), True))
        self.assertNotIn("secret", repr(claude))
        self.assertEqual(parse_endpoints("  "), [])

    def test_parse_endpoints_rejections(self):
        bad = [
            "{", '{"a":1}', "[1]", '[{"name":"x"}]', '[{"base_url":"ftp://x"}]', '[{"base_url":"http://127.0.0.1","provider":"carrier"}]',
            '[{"base_url":"http://127.0.0.1","surprise":1}]', '[{"provider":"anthropic"}]', '[{"provider":"anthropic","api_key_env":"MISSING"}]',
            '[{"base_url":"http://127.0.0.1","roles":["admin"]}]',
            '[{"name":"a","base_url":"http://127.0.0.1"},{"name":"a","base_url":"http://127.0.0.2"}]',
        ]
        for raw in bad:
            with self.assertRaises(ValueError, msg=raw):
                parse_endpoints(raw, {})

    def test_parse_endpoints_rejects_malformed_types_and_ranges(self):
        bad = [
            '[{"base_url":"https://api.example.com","timeout":0}]',
            '[{"base_url":"https://api.example.com","timeout":NaN}]',
            '[{"base_url":"https://api.example.com","max_tokens":0}]',
            '[{"base_url":"https://api.example.com","daily_limit":-1}]',
            '[{"base_url":"https://api.example.com","hosted":"false"}]',
            '[{"base_url":"https://api.example.com","models":"model-a"}]',
            '[{"base_url":"https://api.example.com","roles":"plan"}]',
            '[{"base_url":"https://user:pass@api.example.com/v1"}]',
            '[{"base_url":"https://api.example.com/v1?token=x"}]',
            '[{"base_url":"https://api.example.com","api_key_env":false}]',
            '[{"base_url":"https://api.example.com","model":"x","models":["y"]}]',
        ]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_endpoints(raw, {})

    def test_load_scores_ignores_nonfinite_out_of_range_and_empty_evaluations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.json"
            path.write_text(json.dumps({
                "good": {"accuracy": 0.9, "graded": 10},
                "legacy": 0.5,
                "missing_graded": {"accuracy": 1.0},
                "graded_bool": {"accuracy": 1.0, "graded": True},
                "graded_float": {"accuracy": 1.0, "graded": 10.0},
                "nan": {"accuracy": float("nan"), "graded": 10},
                "too_high": 1.01,
                "negative": -0.1,
                "empty": {"accuracy": 1.0, "graded": 0},
                "too_small": {"accuracy": 1.0, "graded": 2},
                "bool": True,
            }))
            self.assertEqual(load_scores(path), {"good": 0.9})

    def test_simultaneous_first_discovery_is_coalesced(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        endpoint = EndpointConfig("shared", "openai_compatible", "http://127.0.0.1:9000", hosted=False)

        def lister(_endpoint):
            calls.append(1)
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test release not signalled")
            return ["model-8b"]

        pool = ModelPool([endpoint], lister=lister, refresh_seconds=300)
        results = []
        first = threading.Thread(target=lambda: results.append([c.key for c in pool.candidates("compose")]))
        second = threading.Thread(target=lambda: results.append([c.key for c in pool.candidates("compose")]))
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()
        time.sleep(0.02)
        release.set()
        first.join(2)
        second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(calls, [1])
        self.assertEqual(results, [["shared/model-8b"], ["shared/model-8b"]])

    def test_model_pool_rejects_invalid_constructor_limits_and_direct_scores(self):
        endpoint = EndpointConfig("a", "openai_compatible", "http://127.0.0.1:9000", models=("model-8b",), hosted=False)
        for kwargs in ({"per_endpoint_cap": 0}, {"max_cascade": 0}, {"refresh_seconds": float("nan")}, {"min_plan_score": 1.1}, {"prefer": "random"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ModelPool([endpoint], **kwargs)
        pool = ModelPool([endpoint], scores={"a/model-8b": 2.0, "model-8b": float("nan"), "ok": 0.8})
        self.assertEqual(pool.scores, {"ok": 0.8})

    def test_explicit_non_chat_models_are_filtered(self):
        endpoint = EndpointConfig("a", "openai_compatible", "http://127.0.0.1:9000", models=("text-embedding-3-large", "chat-model"), hosted=False)
        pool = ModelPool([endpoint])
        self.assertEqual([c.model for c in pool.candidates("compose")], ["chat-model"])

    def test_strict_mode_rejects_remote_http_but_allows_private(self):
        with self.assertRaises(ValueError):
            parse_endpoints('[{"base_url":"http://api.example.com"}]', {}, allow_insecure_remote=False)
        self.assertEqual(len(parse_endpoints('[{"base_url":"http://10.0.0.5:8000"}]', {}, allow_insecure_remote=False)), 1)

    def test_auto_endpoints_use_keys_only_for_their_own_hosts(self):
        found = {e.name: e for e in auto_endpoints({"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "o"})}
        self.assertEqual((found["anthropic"].api_key, found["openai"].api_key), ("a", "o"))
        self.assertIsNone(found["ollama"].api_key)
        self.assertFalse(found["ollama"].hosted)
        self.assertNotIn("groq", found)
        self.assertEqual({e.name for e in auto_endpoints({}, probe_local=False)}, set())

    def test_merge_prefers_explicit_endpoints(self):
        explicit = parse_endpoints('[{"name":"mine","base_url":"http://127.0.0.1:11434","model":"x"}]', {})
        merged = merge_endpoints(explicit, auto_endpoints({}))
        self.assertEqual([e.name for e in merged].count("mine"), 1)
        self.assertNotIn("ollama", [e.name for e in merged])  # same URL as the explicit endpoint

    def test_load_scores_formats_and_bad_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "scores.json"
            path.write_text(json.dumps({
                "a/m": {"accuracy": 0.9, "graded": 12},
                "missing_graded": {"accuracy": 0.99},
                "plain": 0.5,
                "bad": "x",
                "flag": True,
            }))
            self.assertEqual(load_scores(path), {"a/m": 0.9})
            path.write_text("not json")
            self.assertEqual(load_scores(path), {})
        self.assertEqual(load_scores("/nonexistent/scores.json"), {})


if __name__ == "__main__":
    unittest.main()
