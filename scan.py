import datetime
import io
import os
import random
import time
import pandas as pd
import requests
import yfinance as yf

# --- 🎯 Qullamaggie 進階策略參數 ---
MIN_PRICE = 5.0  # 最低股價
# 💡 移除原本固定的 PROXIMITY_TO_HIGH = 0.10，改由動能判斷中即時計算 3 倍 ADR
ADR_MULTIPLIER = 4.5  # 歷史高點距離限制係數
RELEVANT_YEARS = 5  # 歷史高點參考年限

# 🔥 進階核心濾網：
MIN_ADR = 4.0  # 進階：ADR 必須大於 4% (過濾慢速股，只要猛獸)
MIN_DOLLAR_VOLUME = 5000000  # 進階：日均成交金額提升至 500 萬美元 (確保機構參與)
MIN_MOM_3M = 1.15  # 進階：股價必須高於 66MA 至少 15% 以上 (確保有爆發性前置趨勢)
CHUNK_SIZE = 100  # 每次群組下載 100 隻股票

# 輸出結果檔名 (對齊 V3 命名模式)
FILE_NAME = f"Strong_Stocks_V3_{datetime.datetime.now().strftime('%Y%m%d')}.txt"

def is_internet_up():
    try:
        requests.get("http://www.google.com", timeout=5)
        return True
    except:
        return False

def wait_for_internet():
    if not is_internet_up():
        print("\n⚠️ 偵測到網路斷開！腳本已自動暫停...")
        while not is_internet_up():
            time.sleep(10)
        print("✅ 網路已恢復，繼續掃描...\n")

def get_nasdaq_list():
    print("📋 正在獲取官方精確市場名單...")
    try:
        url = "http://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
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

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

if __name__ == "__main__":
    start_time = time.time()
    all_tickers = get_nasdaq_list()
    ticker_chunks = list(chunk_list(all_tickers, CHUNK_SIZE))
    
    successful_scans = []
    print(f"🚀 開始高效批次掃描，總共分為 {len(ticker_chunks)} 組執行...")
    
    for i, chunk in enumerate(ticker_chunks):
        wait_for_internet()
        try:
            batch_data = yf.download(
                tickers=chunk, 
                period=f"{RELEVANT_YEARS}y", 
                group_by='ticker', 
                auto_adjust=True, 
                progress=False,
                threads=True
            )
        except Exception as e:
            continue

        for symbol in chunk:
            try:
                if len(chunk) == 1:
                    hist_5y = batch_data
                else:
                    if symbol not in batch_data.columns.levels[0]:
                        continue
                    hist_5y = batch_data[symbol]
                
                # 濾除包含 NaN 的無效數據
                hist_5y = hist_5y.dropna(subset=['Close', 'High', 'Low', 'Volume'])
                
                if len(hist_5y) < 200:
                    continue
                    
                hist_2y = hist_5y.tail(252 * 2)
                current_price = hist_2y["Close"].iloc[-1]
                
                if pd.isna(current_price) or current_price < MIN_PRICE:
                    continue

                # 均線趨勢檢查
                ema_200 = hist_2y["Close"].ewm(span=200, adjust=False).mean().iloc[-1]
                ema_50 = hist_2y["Close"].ewm(span=50, adjust=False).mean().iloc[-1]
                if current_price < ema_200 or ema_50 < ema_200:
                    continue

                # 計算流動性 (日均成交量金額)
                avg_vol = hist_2y["Volume"].iloc[-20:].mean()
                if current_price * avg_vol < MIN_DOLLAR_VOLUME:
                    continue

                # 計算 20 天 ADR 百分比
                daily_range_pct = (hist_5y["High"] - hist_5y["Low"]) / hist_5y["Low"]
                adr_pct = daily_range_pct.tail(20).mean() * 100

                # 濾網：過濾慢速股
                if adr_pct < MIN_ADR:
                    continue

                # 💡 修改點一：52 週新高檢查改為「距離在 3 倍 ADR 以內」
                year_high = hist_2y["Close"].tail(252).max()
                dist_to_year_high_pct = ((year_high - current_price) / year_high) * 100
                if dist_to_year_high_pct > (adr_pct * 3):
                    continue

                # 計算趨勢動能
                avg_25 = hist_2y["Close"].rolling(window=25).mean().iloc[-1]
                avg_66 = hist_2y["Close"].rolling(window=66).mean().iloc[-1]
                avg_126 = hist_2y["Close"].rolling(window=126).mean().iloc[-1]

                mom_1m = current_price / avg_25
                mom_3m = current_price / avg_66
                mom_6m = current_price / avg_126

                # 濾網：爆發性趨勢過濾
                if mom_3m < MIN_MOM_3M:
                    continue

                # 歷史高點 ATH 限制檢查
                relevant_ath = hist_5y["Close"].max()
                dist_to_ath = (relevant_ath - current_price) / relevant_ath
                if dist_to_ath > (adr_pct * ADR_MULTIPLIER) / 100:
                    continue

                # 通過篩選，記錄數據
                stock_data = {
                    "Ticker": symbol,
                    "Price": round(current_price, 2),
                    "Dist_High_%": round(dist_to_ath * 100, 1),
                    "ADR_%": round(adr_pct, 1),
                    "Mom_1M": round(mom_1m, 3),
                    "Mom_3M": round(mom_3m, 3),
                    "Mom_6M": round(mom_6m, 3),
                }
                successful_scans.append(stock_data)
                print(f"🔥 [符合條件] {symbol} | 現價: {current_price:.2f} | ADR: {adr_pct:.1f}% | 距離高點: {dist_to_year_high_pct:.1f}%")
                    
            except Exception:
                pass
        time.sleep(random.uniform(1.0, 1.5))

    end_time = time.time()
    print("-" * 50)
    print(f"🏆 掃描完成！總耗時: {(end_time - start_time)/60:.1f} 分鐘")

    if successful_scans:
        df_final = pd.DataFrame(successful_scans)

        # 計算綜合排名分數（為了幫你在檔案中從最強排到最弱）
        df_final["Rank_1M"] = df_final["Mom_1M"].rank(ascending=False)
        df_final["Rank_3M"] = df_final["Mom_3M"].rank(ascending=False)
        df_final["Rank_6M"] = df_final["Mom_6M"].rank(ascending=False)
        df_final["Blended_Rank"] = (df_final["Rank_1M"] + df_final["Rank_3M"] + df_final["Rank_6M"]) / 3

        # 💡 修改點二：移除 .head(50) 限制！保留「所有」通過篩選的強勢股
        df_sorted = df_final.sort_values(by="Blended_Rank")

        print(f"\n📊 偵測完畢：今日共有 {len(df_sorted)} 支股票符合所有篩選標準。")

        # 💡 精確輸出：以覆寫模式（"w"）將所有符合的股票「一行一個 Ticker」乾淨寫入檔案
        with open(FILE_NAME, "w", encoding="utf-8") as f:
            for ticker in df_sorted["Ticker"]:
                f.write(f"{ticker}\n")
        print(f"📁 乾淨代碼清單已寫入: {FILE_NAME}")
    else:
        print("\n❌ 今日未發現符合標準的股票。")
