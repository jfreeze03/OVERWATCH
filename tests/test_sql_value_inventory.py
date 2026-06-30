from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SqlValueInventoryTests(unittest.TestCase):
    def test_daily_account_usage_path_fails_cleanup_gate(self):
        from tools.contracts.sql_value_inventory import build_sql_value_inventory, evaluate_sql_cleanup_gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql_dir = root / "snowflake"
            sql_dir.mkdir()
            (sql_dir / "daily.sql").write_text("select * from snowflake.account_usage.query_history limit 10;", encoding="utf-8")
            inventory = build_sql_value_inventory(root)
            inventory["rows"][0]["classification"] = "daily_first_paint_packet"
            inventory["rows"][0]["daily_safe"] = False
            gate = evaluate_sql_cleanup_gate(inventory)

        self.assertFalse(gate["passed"])

