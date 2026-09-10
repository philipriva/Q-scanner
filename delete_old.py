import datetime, glob, os

today = datetime.datetime.now().date()
for f in glob.glob("Strong_Stocks_V3_*.txt") + glob.glob("Maggiestocks_*.txt"):
    try:
        date_str = f.split("_")[-1].replace(".txt", "")
        file_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
        if (today - file_date).days >= 5:
            os.remove(f)
            print(f"已刪除過期檔案: {f}")
    except Exception as e:
        print(f"解析或刪除失敗 {f}: {e}")
