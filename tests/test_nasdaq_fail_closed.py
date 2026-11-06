import unittest
from unittest import mock

import scan

GOOD = "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares\nY|AAPL|Apple|Q|Q|N|100|N|N||AAPL|N\nY|ZZZZ|Test|Q|Q|N|100|Y|N||ZZZZ|N\nFile Creation Time: 1105202621:31|||||||||||\n"


class R:
    def __init__(self, text, code=200):
        self.text, self.status_code = text, code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class T(unittest.TestCase):
    def _get(self, resp):
        return mock.patch.object(scan.requests, "get", return_value=resp)

    def test_good_payload(self):
        with self._get(R(GOOD)):
            self.assertEqual(scan.get_nasdaq_list(), ["AAPL"])

    def test_network_error_raises_no_fallback(self):
        with mock.patch.object(scan.requests, "get", side_effect=OSError("down")):
            with self.assertRaises(RuntimeError):
                scan.get_nasdaq_list()

    def test_http_error_raises(self):
        with self._get(R("", 503)):
            with self.assertRaises(RuntimeError):
                scan.get_nasdaq_list()

    def test_truncated_raises(self):
        with self._get(R(GOOD.rsplit("File", 1)[0])):
            with self.assertRaises(RuntimeError):
                scan.get_nasdaq_list()

    def test_schema_raises(self):
        with self._get(R(GOOD.replace("Test Issue", "X"))):
            with self.assertRaises(RuntimeError):
                scan.get_nasdaq_list()


if __name__ == "__main__":
    unittest.main()
