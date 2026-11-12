"""Golden screening + freshness gate for Maggie (no network)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marketdata as md  # noqa: E402
import scan  # noqa: E402


def make_hist_rally(end="2026-11-11", n=260, vol=1_000_000.0, range_frac=0.06):
    """Flat then a sharp rally so mom_3m and ADR clear Maggie filters."""
    idx = pd.bdate_range(end=end, periods=n)
    closes = np.concatenate([np.full(n - 40, 10.0), np.linspace(10.0, 25.0, 40)])
    highs = closes * (1 + range_frac / 2)
    lows = closes * (1 - range_frac / 2)
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": np.full(n, vol)},
        index=idx,
    )


def test_golden_screen_identical_for_same_bars():
    good = make_hist_rally()
    cheap = make_hist_rally()
    cheap = cheap.copy()
    cheap["Close"] = 3.0
    cheap["Open"] = 3.0
    cheap["High"] = 3.1
    cheap["Low"] = 2.9
    first = scan.screen_symbol("GOOD", good.copy())
    second = scan.screen_symbol("GOOD", good.copy())
    assert first is not None and first[0]["Ticker"] == "GOOD"
    assert second == first
    assert scan.screen_symbol("CHEAP", cheap) is None


def test_ranked_write_identical(tmp_path):
    scans = [
        {"Ticker": "AAA", "Price": 10, "Dist_High_%": 1.0, "ADR_%": 5.0, "Mom_1M": 1.2, "Mom_3M": 1.3, "Mom_6M": 1.1},
        {"Ticker": "BBB", "Price": 11, "Dist_High_%": 1.0, "ADR_%": 5.0, "Mom_1M": 1.5, "Mom_3M": 1.4, "Mom_6M": 1.4},
    ]
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    t1 = scan.write_ranked(scans, f1)
    t2 = scan.write_ranked(scans, f2)
    assert t1 == t2
    assert f1.read_text(encoding="utf-8") == f2.read_text(encoding="utf-8")
    assert t1[0] == "BBB"  # higher blended rank


def test_blocked_does_not_write_session_file(monkeypatch, tmp_path):
    expected = date(2026, 11, 11)
    stale = make_hist_rally(end="2026-11-10")
    syms = [f"S{i}" for i in range(10)]
    frames = {s: stale.copy() for s in syms}
    stats = md.DownloadStats(requested=10, yahoo=10, fresh=0, stale_after=10)

    monkeypatch.setattr(scan, "last_complete_us_session_date", lambda: expected)
    monkeypatch.setattr(scan, "get_nasdaq_list", lambda: list(syms))
    monkeypatch.setattr(scan, "wait_for_internet", lambda: None)
    monkeypatch.setattr(scan, "download_daily", lambda *a, **k: (frames, stats))
    monkeypatch.chdir(tmp_path)
    old = tmp_path / "Maggiestocks_20261110.txt"
    old.write_text("OLD\n")
    rc = scan.main()
    assert rc == 3
    assert not (tmp_path / "Maggiestocks_20261111.txt").exists()
    assert old.read_text() == "OLD\n"


def test_fresh_pass_writes_expected_session_filename(monkeypatch, tmp_path):
    expected = date(2026, 11, 11)
    good = make_hist_rally(end="2026-11-11")
    frames = {"GOOD": good}
    stats = md.DownloadStats(requested=1, yahoo=1, fresh=1)

    monkeypatch.setattr(scan, "last_complete_us_session_date", lambda: expected)
    monkeypatch.setattr(scan, "get_nasdaq_list", lambda: ["GOOD"])
    monkeypatch.setattr(scan, "wait_for_internet", lambda: None)
    monkeypatch.setattr(scan, "download_daily", lambda *a, **k: (frames, stats))
    monkeypatch.chdir(tmp_path)
    rc = scan.main()
    assert rc == 0
    out = tmp_path / "Maggiestocks_20261111.txt"
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip().splitlines() == ["GOOD"]
    assert not (tmp_path / "Maggiestocks_20261112.txt").exists()
