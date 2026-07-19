import os
import time
import requests
import pandas as pd
from datetime import datetime

class QuantDataEngine:
    def __init__(self, storage_dir="data_warehouse"):
        self.storage_dir = storage_dir
        self.base_url = "https://api.binance.com/api/v3/klines"
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)
            print(f"[*] تم إنشاء مجلد تخزين البيانات المحلي: {self.storage_dir}")

    def fetch_historical_candles(self, symbol, interval="1h", total_candles=13000):
        """جلب كميات ضخمة من البيانات التاريخية عبر حلقة تراجع زمني تكسر حاجز الـ 1000 شمعة لـ Binance"""
        print(f"\n[+] جاري سحب البيانات التاريخية للعملة {symbol} ({interval})...")
        all_klines = []
        end_time = int(time.time() * 1000)
        
        iterations = (total_candles // 1000) + 1
        
        for iteration in range(iterations):
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": 1000,
                "endTime": end_time
            }
            try:
                response = requests.get(self.base_url, params=params, timeout=15)
                data = response.json()
                
                if not data or len(data) == 0:
                    print(f"[!] لا توجد بيانات تاريخية إضافية متاحة لـ {symbol}")
                    break
                    
                all_klines = data + all_klines
                end_time = data[0][0] - 1
                
                print(f"    -> التقدم: تم جلب {len(all_klines)}/{total_candles} شمعة...")
                time.sleep(0.5) # حماية الـ IP من الحظر
                
                if len(all_klines) >= total_candles:
                    all_klines = all_klines[-total_candles:]
                    break
            except Exception as e:
                print(f"[X] خطأ في الشبكة أثناء جلب الحزمة: {e}")
                time.sleep(2)
                continue

        # تحويل البيانات الخام إلى مصفوفة Pandas وتنظيفها
        columns = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ]
        df = pd.DataFrame(all_klines, columns=columns)
        
        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
        # الاحتفاظ بالأعمدة الأساسية للتداول الكمي فقط لتوفير الذاكرة والسرعة
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
        return df

    def build_and_save_basket(self, assets, interval="1h", total_candles=13000):
        """بناء السلة الكاملة وحفظها بصيغة Parquet المضغوطة"""
        summary_report = {}
        for asset in assets:
            df = self.fetch_historical_candles(asset, interval, total_candles)
            
            # حفظ الملف بصيغة Parquet عالية الأداء
            file_path = os.path.join(self.storage_dir, f"{asset}_{interval}.parquet")
            df.to_parquet(file_path, index=False, engine="pyarrow", compression="snappy")
            
            summary_report[asset] = {
                "total_rows": len(df),
                "start_date": str(df["timestamp"].min()),
                "end_date": str(df["timestamp"].max()),
                "file_path": file_path
            }
            print(f"[✓] تم أرشفة {asset} بنجاح. النطاق الزمني: {df['timestamp'].min()} إلى {df['timestamp'].max()}")
            
        return summary_report

if __name__ == "__main__":
    # السلة المقترحة لمنع انحياز الأصل المالي (Asset Overfitting)
    crypto_basket = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT"]
    
    engine = QuantDataEngine(storage_dir="data_warehouse")
    report = engine.build_and_save_basket(assets=crypto_basket, interval="1h", total_candles=13000)
    
    print("\n" + "="*50)
    print("      DATA ENGINE PHASE 1 REPORT")
    print("="*50)
    import json
    print(json.dumps(report, indent=4))
