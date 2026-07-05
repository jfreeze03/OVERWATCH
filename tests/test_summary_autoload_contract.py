import unittest


def _source_payload(**row_overrides):
    row = {
        "id": "source_runtime_event::summary_cost",
        "event_type": "section_summary_autoload",
        "execution_boundary": "section_summary_autoload",
        "producer": "runtime_state",
        "producer_signature": "runtime_state::row",
        "commit_sha": "abc123",
        "section": "Cost & Contract",
        "workflow": "Cost Overview",
        "query_tier": "section_summary",
        "ttl_key": "section_summary_cost_current_summary",
        "query_count_delta": 1,
        "row_count": 12,
        "max_rows": 200,
        "user_initiated": True,
        "before_first_paint": False,
        "account_usage_marker_present": False,
        "evidence_loader_marker_present": False,
        "source_object_marker_present": False,
        "raw_sql_included": False,
    }
    row.update(row_overrides)
    return {
        "producer": "full_app_runtime_validation",
        "producer_signature": "source_runtime_event_ledger::v1",
        "commit_sha": "abc123",
        "passed": True,
        "rows": [row],
        "raw_sql_included": False,
    }


class SummaryAutoloadContractTests(unittest.TestCase):
    def test_user_initiated_summary_autoload_under_cap_passes(self):
        from tools.contracts.summary_autoload_contract import evaluate_summary_autoload_contract

        results = evaluate_summary_autoload_contract(_source_payload(), commit_sha="abc123")

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertEqual(results["summary_autoload_row_count"], 1)

    def test_missing_summary_autoload_row_fails(self):
        from tools.contracts.summary_autoload_contract import evaluate_summary_autoload_contract

        payload = _source_payload()
        payload["rows"] = []
        results = evaluate_summary_autoload_contract(payload, commit_sha="abc123")

        self.assertFalse(results["passed"])
        self.assertIn("missing section_summary_autoload", str(results["failures"]))

    def test_non_user_initiated_summary_autoload_fails(self):
        from tools.contracts.summary_autoload_contract import evaluate_summary_autoload_contract

        results = evaluate_summary_autoload_contract(_source_payload(user_initiated=False), commit_sha="abc123")

        self.assertFalse(results["passed"])
        self.assertIn("user-initiated", str(results["failures"]))

    def test_account_usage_summary_autoload_fails(self):
        from tools.contracts.summary_autoload_contract import evaluate_summary_autoload_contract

        results = evaluate_summary_autoload_contract(
            _source_payload(account_usage_marker_present=True),
            commit_sha="abc123",
        )

        self.assertFalse(results["passed"])
        self.assertIn("Account Usage", str(results["failures"]))

    def test_source_object_marker_summary_autoload_fails(self):
        from tools.contracts.summary_autoload_contract import evaluate_summary_autoload_contract

        results = evaluate_summary_autoload_contract(
            _source_payload(source_object_marker_present=True),
            commit_sha="abc123",
        )

        self.assertFalse(results["passed"])
        self.assertIn("source-object", str(results["failures"]))

    def test_row_cap_summary_autoload_fails(self):
        from tools.contracts.summary_autoload_contract import evaluate_summary_autoload_contract

        results = evaluate_summary_autoload_contract(_source_payload(max_rows=201), commit_sha="abc123")

        self.assertFalse(results["passed"])
        self.assertIn("max_rows=201", str(results["failures"]))


if __name__ == "__main__":
    unittest.main()
