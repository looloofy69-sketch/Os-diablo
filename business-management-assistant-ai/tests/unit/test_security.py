import unittest

from app.security import AuthRegistry, RateLimiter, Role, extract_secret, parse_api_keys


class ParseKeysTests(unittest.TestCase):
    def test_parses_roles_and_secrets_containing_colons(self):
        keys = parse_api_keys("alice:admin:s3cr:et, bob:viewer:abcdef")
        self.assertEqual([k.name for k in keys], ["alice", "bob"])
        self.assertEqual(keys[0].role, Role.admin)

    def test_rejects_bad_entries(self):
        for raw in ("alice:admin", "alice:root:secret", ":admin:secret", "a:admin:x,a:viewer:y"):
            with self.assertRaises(ValueError, msg=raw):
                parse_api_keys(raw)

    def test_minimum_secret_length(self):
        with self.assertRaises(ValueError):
            parse_api_keys("alice:admin:short", min_secret_length=24)
        self.assertEqual(len(parse_api_keys("alice:admin:" + "x" * 24, min_secret_length=24)), 1)

    def test_empty_means_no_keys(self):
        self.assertEqual(parse_api_keys(" , "), [])


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.registry = AuthRegistry(parse_api_keys("alice:admin:alice-secret,bob:viewer:bob-secret"))

    def test_valid_and_invalid_secrets(self):
        self.assertEqual(self.registry.authenticate("bob-secret").name, "bob")
        self.assertIsNone(self.registry.authenticate("wrong"))
        self.assertIsNone(self.registry.authenticate(None))

    def test_open_mode_only_without_keys(self):
        open_registry = AuthRegistry([])
        principal = open_registry.authenticate(None)
        self.assertTrue(principal.open_mode)
        self.assertFalse(self.registry.open_mode)

    def test_role_hierarchy(self):
        bob = self.registry.authenticate("bob-secret")
        alice = self.registry.authenticate("alice-secret")
        self.assertFalse(bob.allows(Role.operator))
        self.assertTrue(alice.allows(Role.operator) and alice.allows(Role.admin))

    def test_extract_secret_prefers_header_then_bearer(self):
        self.assertEqual(extract_secret("k1", "Bearer k2"), "k1")
        self.assertEqual(extract_secret(None, "Bearer k2"), "k2")
        self.assertIsNone(extract_secret(None, "Basic abc"))
        self.assertIsNone(extract_secret("  ", None))


class RateLimiterTests(unittest.TestCase):
    def test_blocks_after_burst_and_recovers(self):
        now = [0.0]
        limiter = RateLimiter(per_minute=60, burst=3, clock=lambda: now[0])
        self.assertEqual([limiter.check("a")[0] for _ in range(4)], [True, True, True, False])
        allowed, retry = limiter.check("a")
        self.assertFalse(allowed)
        self.assertAlmostEqual(retry, 1.0, places=2)
        now[0] += 1.0
        self.assertTrue(limiter.check("a")[0])

    def test_keys_are_independent_and_disable_flag(self):
        limiter = RateLimiter(per_minute=60, burst=1, clock=lambda: 0.0)
        self.assertTrue(limiter.check("a")[0])
        self.assertTrue(limiter.check("b")[0])
        self.assertFalse(limiter.check("a")[0])
        self.assertTrue(RateLimiter(per_minute=0).check("a")[0])

    def test_bucket_table_is_bounded(self):
        now = [0.0]
        limiter = RateLimiter(per_minute=60, burst=5, clock=lambda: now[0], max_keys=50)
        for i in range(500):
            now[0] += 0.001
            limiter.check(f"k{i}")
        self.assertLessEqual(len(limiter._buckets), 51)


if __name__ == "__main__":
    unittest.main()
