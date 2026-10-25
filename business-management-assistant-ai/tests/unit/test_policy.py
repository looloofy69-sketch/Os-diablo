import unittest

from app.services.policy import PolicyEngine, Risk, external_action_types


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = PolicyEngine(high_value_threshold=1000)

    def test_internal_low_risk_needs_no_approval(self):
        decision = self.policy.evaluate("record.create")
        self.assertFalse(decision.requires_approval)
        self.assertEqual(decision.risk, Risk.low)

    def test_external_actions_always_need_approval(self):
        for action in ("message.send", "content.publish", "calendar.invite", "crm.update"):
            self.assertTrue(self.policy.evaluate(action).requires_approval, action)

    def test_unknown_action_fails_closed(self):
        decision = self.policy.evaluate("teleport.cargo")
        self.assertTrue(decision.requires_approval)
        self.assertFalse(decision.known)
        self.assertEqual(decision.risk, Risk.high)

    def test_aliases_and_case_are_canonicalised(self):
        self.assertEqual(self.policy.evaluate("  Send_External_Message ").action_type, "message.send")

    def test_high_value_amount_escalates_one_level(self):
        low = self.policy.evaluate("invoice.send", {"amount": 50})
        high = self.policy.evaluate("invoice.send", {"amount": "2,500"})
        self.assertEqual(low.risk, Risk.high)
        self.assertEqual(high.risk, Risk.critical)

    def test_nested_amount_and_non_numeric_amount_escalate(self):
        self.assertEqual(self.policy.evaluate("invoice.send", {"invoice": {"total": 5000}}).risk, Risk.critical)
        self.assertEqual(self.policy.evaluate("invoice.send", {"amount": "lots"}).risk, Risk.critical)

    def test_bool_is_not_an_amount(self):
        self.assertEqual(self.policy.evaluate("invoice.send", {"amount": True}).risk, Risk.critical)  # non-numeric -> escalated

    def test_escalation_is_capped_at_critical(self):
        self.assertEqual(self.policy.evaluate("payment.execute", {"amount": 10**6}).risk, Risk.critical)

    def test_bulk_recipients_escalate(self):
        decision = self.policy.evaluate("message.send", {"recipients": [f"u{i}@x.io" for i in range(30)]})
        self.assertEqual(decision.risk, Risk.critical)

    def test_public_visibility_raises_floor_to_high(self):
        decision = self.policy.evaluate("message.draft", {"public": True})
        self.assertEqual(decision.risk, Risk.high)
        self.assertTrue(decision.requires_approval)

    def test_medium_internal_action_requires_approval_by_floor(self):
        self.assertTrue(self.policy.evaluate("payment.prepare").requires_approval)

    def test_catalog_lists_every_action(self):
        self.assertTrue(all({"action_type", "risk", "external"} <= set(item) for item in self.policy.catalog()))


class ModelProposableTypesTests(unittest.TestCase):
    def test_only_external_or_medium_plus_types_are_proposable(self):
        types = external_action_types()
        for allowed in ("message.send", "payment.execute", "payment.prepare", "data.delete", "calendar.invite"):
            self.assertIn(allowed, types)
        for internal in ("record.create", "record.update", "task.complete", "message.draft"):
            self.assertNotIn(internal, types)


if __name__ == "__main__":
    unittest.main()
