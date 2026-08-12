import json
import base64
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import server
import export_static


class FundTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.patch = mock.patch.object(server, "DB_PATH", self.db_path)
        self.patch.start()
        server.init_db()

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_scope_contains_only_three_indices(self):
        indices = {fund[2] for fund in server.FUNDS}
        self.assertEqual(indices, {"S&P 500", "S&P 500 Equal Weight", "NASDAQ-100"})

    def test_ytd_uses_previous_year_last_cumulative_nav(self):
        code = "018043"
        previous_year = date.today().year - 1
        current_year = date.today().year
        with server.connect() as db:
            db.executemany(
                "INSERT INTO navs VALUES (?,?,?,?,?,?,?,?)",
                [
                    (code, f"{previous_year}-12-30", 1.0, 1.0, "开放申购", "开放赎回", "test", "now"),
                    (code, f"{previous_year}-12-31", 1.1, 1.1, "开放申购", "开放赎回", "test", "now"),
                    (code, f"{current_year}-01-02", 1.21, 1.21, "开放申购", "开放赎回", "test", "now"),
                ],
            )
        fund = next(item for item in server.list_funds() if item["code"] == code)
        self.assertEqual(fund["ytd_base_date"], f"{previous_year}-12-31")
        self.assertAlmostEqual(fund["ytd"], 10.0)

    def test_seed_limit_is_bound_to_each_share_code(self):
        funds = {item["code"]: item for item in server.list_funds()}
        self.assertEqual(funds["018064"]["limit"]["limit_amount"], 100)
        self.assertEqual(funds["018065"]["limit"]["limit_amount"], 100)
        self.assertEqual(funds["018043"]["limit"]["confidence"], "snapshot")
        self.assertEqual(funds["014978"]["limit"]["limit_amount"], 10)

    def test_first_run_contains_visible_snapshot_data(self):
        fund = next(item for item in server.list_funds() if item["code"] == "018043")
        self.assertEqual(fund["snapshot_date"], "2026-08-11")
        self.assertAlmostEqual(fund["ytd"], 11.95)
        self.assertAlmostEqual(fund["asset_size_billion"], 12.0)

    def test_cost_separates_paid_and_embedded_fees(self):
        cost = server.calculate_cost(100_000, 365, 0.1, 0, 0.3, 0.5, 0.1)
        self.assertAlmostEqual(cost["investor_paid_cost"], 100)
        self.assertAlmostEqual(cost["annual_product_cost"], 900)
        self.assertAlmostEqual(cost["estimated_total_cost"], 1000)

    def test_basic_auth_header_format(self):
        encoded = base64.b64encode("fund:test-password".encode()).decode()
        self.assertEqual(encoded, "ZnVuZDp0ZXN0LXBhc3N3b3Jk")

    def test_static_export_contains_funds_and_limit_history(self):
        output = Path(self.temp_dir.name) / "data.json"
        payload = export_static.export(output)
        self.assertGreater(len(payload["funds"]), 0)
        self.assertIn("018043", payload["limits"])
        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["funds"][0]["code"], payload["funds"][0]["code"])

    def test_catalog_filter_excludes_exchange_and_usd_shares(self):
        self.assertFalse(server.is_otc_cny_share("513500", "标普500ETF博时"))
        self.assertFalse(server.is_otc_cny_share("013425", "博时标普500ETF联接美元汇A"))
        self.assertFalse(server.is_otc_cny_share("017642", "摩根标普500指数(QDII)美钞"))
        self.assertTrue(server.is_otc_cny_share("050025", "博时标普500ETF联接A"))

    def test_sales_page_parses_channel_limit(self):
        page = """规模</a>：21.78亿元（2026-06-30）
        <span class='letterSpace01'>成 立 日</span>：2023-11-29
        <span class='letterSpace01'>管 理 人</span>：<a>招商基金</a>
        跟踪标的：</a>纳斯达克100指数 | <span>交易状态：</span><span>限大额
        (<span>单日累计购买上限10.00元</span>)</span><span>开放赎回</span>"""
        fund = server.parse_sales_page("019547", "招商纳斯达克100ETF发起式联接(QDII)A", page)
        self.assertEqual(fund["index_key"], "NASDAQ-100")
        self.assertEqual(fund["share_class"], "A")
        self.assertEqual(fund["status"], "有限额")
        self.assertEqual(fund["limit_amount"], 10)

    def test_sales_page_parses_class_before_currency_suffix(self):
        fund = server.parse_sales_page("021838", "嘉实纳斯达克100ETF发起联接(QDII)I人民币", "")
        self.assertEqual(fund["share_class"], "I")
        fund = server.parse_sales_page("012870", "易方达纳斯达克100ETF联接(QDII-LOF)C(人民币)", "")
        self.assertEqual(fund["share_class"], "C")

    def test_sales_page_marks_unavailable_channel_as_not_distributed(self):
        page = "交易状态：</span><span class='staticCell'>限大额</span>该基金暂不开放购买"
        fund = server.parse_sales_page("021000", "南方纳斯达克100指数发起(QDII)I", page)
        self.assertEqual(fund["status"], "不代销")
        self.assertIsNone(fund["limit_amount"])


if __name__ == "__main__":
    unittest.main()
