from __future__ import annotations

import json
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from scan_meta import (
    build_scan_meta,
    payload_hash,
    publish_file_date,
    verify_meta_against_list,
    write_list_and_meta,
)
from us_session import last_complete_us_session_date

NY = ZoneInfo("America/New_York")


class TestMaggieMeta(unittest.TestCase):
    def test_publish_date(self):
        self.assertEqual(publish_file_date(date(2026, 11, 5)), date(2026, 11, 6))

    def test_hash(self):
        self.assertEqual(payload_hash(["ZZ", "AA"]), payload_hash(["aa", "zz"]))

    def test_statuses(self):
        ok = build_scan_meta(
            source_id="q",
            list_filename="Maggiestocks_20261106.txt",
            tickers=["AAA"],
            target_session=date(2026, 11, 5),
            universe_n=5,
            bar_dates_all=[date(2026, 11, 5)] * 5,
            missing_count=0,
            selected_bar_dates={"AAA": "2026-11-05"},
        )
        self.assertEqual(ok["status"], "OK")
        stale = build_scan_meta(
            source_id="q",
            list_filename="x.txt",
            tickers=["AAA"],
            target_session=date(2026, 11, 5),
            universe_n=5,
            bar_dates_all=[date(2026, 11, 4)] * 5,
            missing_count=0,
            selected_bar_dates={"AAA": "2026-11-04"},
        )
        self.assertEqual(stale["status"], "FAIL_STALE")
        empty = build_scan_meta(
            source_id="q",
            list_filename="x.txt",
            tickers=[],
            target_session=date(2026, 11, 5),
            universe_n=5,
            bar_dates_all=[date(2026, 11, 5)] * 5,
            missing_count=0,
            selected_bar_dates={},
        )
        self.assertEqual(empty["status"], "OK_NO_NEW_SIGNAL")

    def test_write_verify(self):
        meta = build_scan_meta(
            source_id="q",
            list_filename="Maggiestocks_20261106.txt",
            tickers=["AAA"],
            target_session=date(2026, 11, 5),
            universe_n=1,
            bar_dates_all=[date(2026, 11, 5)],
            missing_count=0,
            selected_bar_dates={"AAA": "2026-11-05"},
        )
        lp, mp = write_list_and_meta("out_test_maggie.txt", ["AAA"], meta)
        loaded = json.loads(mp.read_text())
        ok, msg = verify_meta_against_list(loaded, ["AAA"])
        self.assertTrue(ok, msg)
        lp.unlink()
        mp.unlink()

    def test_early_close_session(self):
        # before early close on day-after-thanksgiving → prior session Wed
        self.assertEqual(
            last_complete_us_session_date(datetime(2026, 11, 27, 12, 0, tzinfo=NY)),
            date(2026, 11, 25),
        )


if __name__ == "__main__":
    unittest.main()
