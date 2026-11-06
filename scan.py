#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Maggiestocks scanner — emits ticker list + OHLC-bound sidecar metadata."""
from __future__ import annotations

import io
import os
import random
import time
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from scan_meta import build_scan_meta, publish_file_date, write_list_and_meta
from us_session import last_complete_us_session_date, session_bar_date

MIN_PRICE = 5.0
ADR_MULTIPLIER = 4.5
RELEVANT_YEARS = 5
MIN_ADR = 4.0
MIN_DOLLAR_VOLUME = 5000000
MIN_MOM_3M = 1.15
CHUNK_SIZE = 100
SOURCE_ID = "philipriva/Q-scanner:Maggiestocks"
PRODUCER_VERSION = "scan.py@meta-v1"


def is_internet_up() -> bool:
    try:
        requests.get("http://www.google.com", timeout=5)
        return True
    except Exception:
        return False


def wait_for_internet() -> None:
    if not is_internet_up():
        print("\n⚠️ 偵測到網路斷開！腳本已自動暫停...")
        while not is_internet_up():
            time.sleep(10)
        print("✅ 網路已恢復，繼續掃描...\n")


def get_nasdaq_list() -> list[str]:
    print("📋 正在獲取官方精確市場名單...")
    try:
        url = "http://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        df = pd.read_csv(io.StringIO(response.text), sep="|")
        df = df[df["Test Issue"] == "N"]
        df = df[df["ETF"] == "N"]
        df = df.dropna(subset=["Symbol"])
        tickers = df["Symbol"].astype(str).tolist()
        clean = [t for t in tickers if t.isalpha() and len(t) <= 4]
        print(f"📊 市場普通股總數: {len(clean)} | 準備進行群組化高速掃描...")
        return list(set(clean))
    except Exception as e:
        print(f"⚠️ 官方清單獲取失敗: {e}")
        return ["AAPL", "MSFT", "NVDA", "AMD"]


def usable_last_bar(hist):
    """Session date of the last fully-populated OHLCV row, or None if no such row."""
    if hist is None or len(hist) == 0:
        return None
    h = hist.dropna(subset=["Close", "High", "Low", "Volume"])
    if len(h) == 0:
        return None
    return session_bar_date(h.index[-1])


def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def cleanup_old_files(keep_days: int = 5) -> None:
    print("\n🧹 開始檢查並清理過期檔案...")
    now = time.time()
    cutoff = now - (keep_days * 86400)
    for file in os.listdir("."):
        if not (
            file.startswith("Maggiestocks_")
            and (file.endswith(".txt") or file.endswith(".meta.json"))
        ):
            continue
        path = os.path.join(".", file)
        if os.path.getmtime(path) < cutoff:
            os.remove(path)
            print(f"🗑️ 已自動刪除 {keep_days} 天前的舊檔案: {file}")


def run_scan(tickers: list[str] | None = None) -> tuple[int, Path, Path, dict]:
    target_session = last_complete_us_session_date()
    pub = publish_file_date(target_session)
    list_name = f"Maggiestocks_{pub.strftime('%Y%m%d')}.txt"
    print(
        f"target_session={target_session.isoformat()} publish_file_date={pub.isoformat()} "
        f"list={list_name}",
        flush=True,
    )

    all_tickers = tickers if tickers is not None else get_nasdaq_list()
    successful_scans: list[dict] = []
    selected_bars: dict[str, str] = {}
    bar_dates_all: list[date] = []
    reasons: Counter = Counter()
    download_failed = 0

    chunks = list(chunk_list(all_tickers, CHUNK_SIZE))
    print(f"🚀 開始高效批次掃描，總共分為 {len(chunks)} 組執行...", flush=True)

    for chunk in chunks:
        wait_for_internet()
        try:
            batch_data = yf.download(
                tickers=chunk,
                period=f"{RELEVANT_YEARS}y",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception:
            download_failed += len(chunk)
            reasons["download_failed"] += len(chunk)
            continue

        for symbol in chunk:
            try:
                if len(chunk) == 1:
                    hist_5y = batch_data
                else:
                    if not isinstance(batch_data.columns, pd.MultiIndex):
                        reasons["download_failed"] += 1
                        download_failed += 1
                        continue
                    if symbol not in batch_data.columns.levels[0]:
                        reasons["download_failed"] += 1
                        download_failed += 1
                        continue
                    hist_5y = batch_data[symbol]

                hist_5y = hist_5y.dropna(subset=["Close", "High", "Low", "Volume"])
                # Record the real last OHLCV bar BEFORE the lookback filter: a short-history
                # ticker with a genuine target-session bar is fresh data, merely ineligible
                # for signals. Empty / all-NaN frames record nothing (stay missing).
                last_bar = usable_last_bar(hist_5y)
                if last_bar is None:
                    reasons["download_failed"] += 1
                    continue
                bar_dates_all.append(last_bar)
                if len(hist_5y) < 200:
                    reasons["too_few_bars"] += 1
                    continue

                hist_2y = hist_5y.tail(252 * 2)
                current_price = float(hist_2y["Close"].iloc[-1])
                if pd.isna(current_price) or current_price < MIN_PRICE:
                    reasons["price_filter"] += 1
                    continue

                ema_200 = hist_2y["Close"].ewm(span=200, adjust=False).mean().iloc[-1]
                ema_50 = hist_2y["Close"].ewm(span=50, adjust=False).mean().iloc[-1]
                if current_price < ema_200 or ema_50 < ema_200:
                    reasons["ema_filter"] += 1
                    continue

                avg_vol = float(hist_2y["Volume"].iloc[-20:].mean())
                if current_price * avg_vol < MIN_DOLLAR_VOLUME:
                    reasons["dollar_vol_filter"] += 1
                    continue

                daily_range_pct = (hist_5y["High"] - hist_5y["Low"]) / hist_5y["Low"]
                adr_pct = float(daily_range_pct.tail(20).mean() * 100)
                if adr_pct < MIN_ADR:
                    reasons["adr_filter"] += 1
                    continue

                year_high = float(hist_2y["Close"].tail(252).max())
                dist_to_year_high_pct = ((year_high - current_price) / year_high) * 100
                if dist_to_year_high_pct > (adr_pct * 3):
                    reasons["year_high_filter"] += 1
                    continue

                avg_25 = hist_2y["Close"].rolling(window=25).mean().iloc[-1]
                avg_66 = hist_2y["Close"].rolling(window=66).mean().iloc[-1]
                avg_126 = hist_2y["Close"].rolling(window=126).mean().iloc[-1]
                mom_1m = current_price / avg_25
                mom_3m = current_price / avg_66
                mom_6m = current_price / avg_126
                if mom_3m < MIN_MOM_3M:
                    reasons["mom_filter"] += 1
                    continue

                relevant_ath = float(hist_5y["Close"].max())
                dist_to_ath = (relevant_ath - current_price) / relevant_ath
                if dist_to_ath > (adr_pct * ADR_MULTIPLIER) / 100:
                    reasons["ath_filter"] += 1
                    continue

                if last_bar != target_session:
                    reasons["stale_selected_bar"] += 1
                    continue

                sym_u = symbol.strip().upper()
                selected_bars[sym_u] = last_bar.isoformat()
                successful_scans.append(
                    {
                        "Ticker": sym_u,
                        "Price": round(current_price, 2),
                        "Dist_High_%": round(dist_to_ath * 100, 1),
                        "ADR_%": round(adr_pct, 1),
                        "Mom_1M": round(mom_1m, 3),
                        "Mom_3M": round(mom_3m, 3),
                        "Mom_6M": round(mom_6m, 3),
                    }
                )
                print(
                    f"🔥 [符合條件] {sym_u} | 現價: {current_price:.2f} | "
                    f"ADR: {adr_pct:.1f}% | 距離高點: {dist_to_year_high_pct:.1f}% | "
                    f"bar={last_bar.isoformat()}"
                )
            except Exception:
                reasons["symbol_exception"] += 1
        time.sleep(random.uniform(1.0, 1.5))

    if successful_scans:
        df_final = pd.DataFrame(successful_scans)
        df_final["Rank_1M"] = df_final["Mom_1M"].rank(ascending=False)
        df_final["Rank_3M"] = df_final["Mom_3M"].rank(ascending=False)
        df_final["Rank_6M"] = df_final["Mom_6M"].rank(ascending=False)
        df_final["Blended_Rank"] = (
            df_final["Rank_1M"] + df_final["Rank_3M"] + df_final["Rank_6M"]
        ) / 3
        df_sorted = df_final.sort_values(by="Blended_Rank")
        uniq_hits = [str(t).strip().upper() for t in df_sorted["Ticker"].tolist()]
        print(f"\n📊 偵測完畢：今日共有 {len(uniq_hits)} 支股票符合所有篩選標準。")
    else:
        uniq_hits = []
        print("\n❌ 今日未發現符合標準的股票。")

    missing_count = max(0, len(all_tickers) - len(bar_dates_all))
    meta = build_scan_meta(
        source_id=SOURCE_ID,
        list_filename=list_name,
        tickers=uniq_hits,
        target_session=target_session,
        universe_n=len(all_tickers),
        bar_dates_all=bar_dates_all,
        missing_count=missing_count,
        selected_bar_dates={k: selected_bars[k] for k in uniq_hits if k in selected_bars},
        download_failed=download_failed,
        excluded_reasons=dict(reasons),
        producer_version=PRODUCER_VERSION,
    )
    lp, mp = write_list_and_meta(list_name, uniq_hits, meta)
    print(
        f"wrote {lp} n={len(uniq_hits)} meta={mp} status={meta['status']} "
        f"fresh_frac={meta['input_bars'].get('frac')}",
        flush=True,
    )
    code = 0 if meta["status"] in ("OK", "OK_NO_NEW_SIGNAL") else 4
    return code, lp, mp, meta


if __name__ == "__main__":
    start_time = time.time()
    code, lp, mp, meta = run_scan()
    cleanup_old_files()
    end_time = time.time()
    print("-" * 50)
    print(f"🏆 掃描完成！總耗時: {(end_time - start_time)/60:.1f} 分鐘 status={meta['status']}")
    raise SystemExit(code)
