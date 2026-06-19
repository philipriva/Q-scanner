import datetime
import io
import os
import random
import time
import pandas as pd
import requests
import yfinance as yf

# --- 🎯 Qullamaggie 進階策略參數 ---
MIN_PRICE = 5.0  
PROXIMITY_TO_HIGH = 0.10  
ADR_MULTIPLIER = 4.5  
RELEVANT_YEARS = 5  

# 🔥 進階核心濾網：
MIN_ADR = 4.0  
MIN_DOLLAR_VOLUME = 5000000  
MIN_MOM_3M = 1.15  
CHUNK_SIZE = 100             # 每次群組下載 100 隻股票

# 輸出結果檔名
FILE_NAME = f"Qullamaggie_Top50_{datetime.datetime.now().strftime('%Y%m%d')}.txt"

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
    print(f"🚀 開始高效雙重掃描，總共分為 {len(ticker_chunks)} 組執行...")
    
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
                
                # 🔥 關鍵修復：強力濾除包含 NaN 的無效行
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

                # 2. 52 週新高檢查
                year_high = hist_2y["Close"].tail(252).max()
                if (year_high - current_price) / year_high > PROXIMITY_TO_HIGH:
                    continue

                # 3. 流動性過濾 (提升至 500 萬美元)
                avg_vol = hist_2y["Volume"].iloc[-20:].mean()
                if current_price * avg_vol < MIN_DOLLAR_VOLUME:
                    continue

                # 4. 計算動能並進行爆發性過濾
                avg_25 = hist_2y["Close"].rolling(window=25).mean().iloc[-1]
                avg_66 = hist_2y["Close"].rolling(window=66).mean().iloc[-1]
                avg_126 = hist_2y["Close"].rolling(window=126).mean().iloc[-1]

                mom_1m = current_price / avg_25
                mom_3m = current_price / avg_66
                mom_6m = current_price / avg_126

                if mom_3m < MIN_MOM_3M:
                    continue

                # 5. ATH 與 ADR 篩選
                relevant_ath = hist_5y["Close"].max()
                daily_range_pct = (hist_5y["High"] - hist_5y["Low"]) / hist_5y["Low"]
                adr_pct = daily_range_pct.tail(20).mean() * 100

                if adr_pct < MIN_ADR:
                    continue

                dist_to_ath = (relevant_ath - current_price) / relevant_ath
                if dist_to_ath > (adr_pct * ADR_MULTIPLIER) / 100:
                    continue

                # 打包黃金數據
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
                print(f"🔥 [通過篩選] {symbol} | 現價: {current_price:.2f} | ADR: {adr_pct:.1f}%")
                    
            except Exception:
                pass
        time.sleep(random.uniform(1.0, 1.5))

    end_time = time.time()
    print("-" * 50)
    print(f"🏆 掃描完成！總耗時: {(end_time - start_time)/60:.1f} 分鐘")

    if successful_scans:
        df_final = pd.DataFrame(successful_scans)
        df_final["Rank_1M"] = df_final["Mom_1M"].rank(ascending=False)
        df_final["Rank_3M"] = df_final["Mom_3M"].rank(ascending=False)
        df_final["Rank_6M"] = df_final["Mom_6M"].rank(ascending=False)
        df_final["Blended_Rank"] = (df_final["Rank_1M"] + df_final["Rank_3M"] + df_final["Rank_6M"]) / 3

        df_top50 = df_final.sort_values(by="Blended_Rank").head(50)

        # 💡 將結果美化並直接寫入文字檔中！起床後可以直接看精美表格
        with open(FILE_NAME, "w", encoding="utf-8") as f:
            f.write(f"📊 QULLAMAGGIE 系統：全美股強勢動能精選 Top 50 ({datetime.datetime.now().strftime('%Y-%m-%d')})\n")
            f.write("=" * 80 + "\n")
            f.write(df_top50[["Ticker", "Price", "Dist_High_%", "ADR_%", "Mom_1M", "Mom_3M"]].to_string(index=False))
            f.write("\n\n💬 TRADINGVIEW 批量導入 (逗號分隔) 💬\n")
            f.write("=" * 80 + "\n")
            f.write(",".join(df_top50["Ticker"].tolist()) + "\n")
        print(f"📁 成功生成精選報告: {FILE_NAME}")
    else:
        print("\n❌ 今日未發現符合標準的股票。")
