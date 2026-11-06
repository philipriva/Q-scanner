import unittest
from datetime import date

import numpy as np
import pandas as pd

import scan


def frame(n, last="2026-11-05", nan=False):
    idx = pd.bdate_range(end=last, periods=n)
    v = np.full(n, np.nan) if nan else np.linspace(10, 20, n)
    return pd.DataFrame({"Open": v, "High": v, "Low": v, "Close": v, "Volume": v}, index=idx)


class T(unittest.TestCase):
    def test_short_history_has_real_bar(self):
        self.assertEqual(scan.usable_last_bar(frame(30)), date(2026, 11, 5))

    def test_all_nan_is_none(self):
        self.assertIsNone(scan.usable_last_bar(frame(300, nan=True)))

    def test_empty_is_none(self):
        self.assertIsNone(scan.usable_last_bar(frame(0)))
        self.assertIsNone(scan.usable_last_bar(None))

    def test_trailing_nan_row_uses_last_complete(self):
        f = frame(5)
        f.iloc[-1, f.columns.get_loc("Volume")] = np.nan
        self.assertEqual(scan.usable_last_bar(f), date(2026, 11, 4))


if __name__ == "__main__":
    unittest.main()
