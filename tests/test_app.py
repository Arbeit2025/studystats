import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as studystats  # noqa: E402

HEADER = "日付,科目,学習分,理解度\n"

SAMPLE = HEADER + (
    "2026-10-25,数学,60,4\n"
    "2026-10-26,数学,30,3\n"
    "2026-10-26,英語,45,5\n"
    "2026-10-27,英語,90,4\n"
)


def make_records():
    records, skipped = studystats.parse_csv(SAMPLE)
    assert skipped == 0
    return records


class ParseTest(unittest.TestCase):
    def test_parse_valid_csv(self):
        records, skipped = studystats.parse_csv(SAMPLE)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0]["subject"], "数学")
        self.assertEqual(records[0]["date"], date(2026, 10, 25))
        self.assertEqual(records[0]["understanding"], 4)

    def test_parse_without_header(self):
        records, skipped = studystats.parse_csv("2026-10-25,数学,60,4\n")
        self.assertEqual((len(records), skipped), (1, 0))

    def test_parse_skips_invalid_rows(self):
        text = HEADER + (
            "2026-10-25,数学,60,4\n"      # 有効
            "not-a-date,数学,60,4\n"       # 日付不正
            "2026-10-25,数学,abc,4\n"      # 学習分不正
            "2026-10-25,数学,60,9\n"       # 理解度が範囲外
            "2026-10-25,,60,4\n"           # 科目が空
            "2026-10-25,数学\n"            # 列不足
            "\n"                            # 空行はスキップ件数に数えない
        )
        records, skipped = studystats.parse_csv(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(skipped, 5)


class AnalyzeTest(unittest.TestCase):
    def test_total_and_days(self):
        result = studystats.analyze(make_records())
        self.assertTrue(result["has_data"])
        self.assertEqual(result["total_minutes"], 225)
        self.assertEqual(result["study_days"], 3)
        self.assertEqual(result["total_label"], "3時間45分")

    def test_subject_totals(self):
        result = studystats.analyze(make_records())
        rows = {r["subject"]: r["minutes"] for r in result["subject_rows"]}
        self.assertEqual(rows, {"数学": 90, "英語": 135})
        self.assertEqual(result["subject_rows"][0]["subject"], "英語")  # 多い順
        self.assertEqual(result["top_subject"], "英語")
        self.assertAlmostEqual(result["subject_rows"][0]["pct"], 100.0)

    def test_streak(self):
        result = studystats.analyze(make_records())
        # 10/25, 10/26, 10/27 と連続しているので最新日から遡って3日
        self.assertEqual(result["streak"], 3)

    def test_streak_broken(self):
        text = HEADER + (
            "2026-10-20,数学,30,3\n"
            "2026-10-26,数学,30,3\n"
            "2026-10-27,数学,30,3\n"
        )
        records, _ = studystats.parse_csv(text)
        result = studystats.analyze(records)
        self.assertEqual(result["streak"], 2)  # 10/26-27 のみ連続

    def test_understanding_average(self):
        result = studystats.analyze(make_records())
        self.assertAlmostEqual(result["avg_understanding"], (4 + 3 + 5 + 4) / 4)

    def test_recent7_vs_prev7(self):
        today = date(2026, 10, 31)
        rows = [HEADER.rstrip("\n")]
        # 直近7日（10/25〜10/31）に毎日60分
        for i in range(6, -1, -1):
            rows.append(f"{(today - timedelta(days=i)).isoformat()},数学,60,4")
        # その前7日（10/18〜10/24）に毎日30分
        for i in range(13, 6, -1):
            rows.append(f"{(today - timedelta(days=i)).isoformat()},英語,30,3")
        records, skipped = studystats.parse_csv("\n".join(rows) + "\n")
        self.assertEqual(skipped, 0)
        result = studystats.analyze(records)
        self.assertEqual(result["recent7"], 420)
        self.assertEqual(result["prev7"], 210)
        self.assertEqual(result["diff7"], 210)
        self.assertAlmostEqual(result["diff7_pct"], 100.0)
        self.assertEqual(result["streak"], 14)

    def test_analyze_empty(self):
        result = studystats.analyze([])
        self.assertFalse(result["has_data"])


class WebTest(unittest.TestCase):
    def setUp(self):
        self.client = studystats.app.test_client()

    def test_index_ok(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("studystats", resp.get_data(as_text=True))

    def test_analyze_with_paste(self):
        resp = self.client.post("/analyze", data={"csv_text": SAMPLE})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("3時間45分", body)
        self.assertIn("英語", body)

    def test_sample_csv_download(self):
        resp = self.client.get("/sample.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        records, skipped = studystats.parse_csv(resp.get_data(as_text=True))
        self.assertEqual(skipped, 0)
        self.assertGreater(len(records), 10)


if __name__ == "__main__":
    unittest.main()
