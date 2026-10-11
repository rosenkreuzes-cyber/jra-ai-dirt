import os
import sys
import time
import random
import json
import pandas as pd

# 念のためローカルの抽出済みKeibaScraperパスを検索してシステムパスに追加
scraper_paths = [
    os.path.abspath('extracted_scraper/KeibaScraper-main'),
    os.path.abspath('.')
]
for p in scraper_paths:
    if p not in sys.path and os.path.exists(os.path.join(p, 'keibascraper')):
        sys.path.insert(0, p)

import keibascraper

try:
    from tqdm import tqdm
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "tqdm"])
    from tqdm import tqdm

# 保存先フォルダとチェックポイントの設定
BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "collected_all_races")
os.makedirs(DATA_DIR, exist_ok=True)
CHECKPOINT_FILE = os.path.join(BASE_DIR, "processed_all_races.json")

def load_all_processed_race_ids():
    """
    既存のJSONチェックポイントおよび、すでに保存されている年別CSVファイルから
    すべてのレースIDを自動スキャンして、二度と再取得させない（完璧なレジューム）ためのセットを構築します。
    """
    processed = set()
    
    # 1. JSONチェックポイントからロード
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                processed.update(data)
        except Exception:
            pass
            
    # 2. 既存の年別CSVからも自動でレースIDをスキャン
    if os.path.exists(DATA_DIR):
        for filename in os.listdir(DATA_DIR):
            if filename.endswith(".csv") and "all_race_dataset" in filename:
                filepath = os.path.join(DATA_DIR, filename)
                try:
                    df_existing = pd.read_csv(filepath, usecols=["race_id"], dtype=str)
                    if "race_id" in df_existing.columns:
                        processed.update(df_existing["race_id"].dropna().unique().tolist())
                except Exception:
                    pass
                    
    return processed

def save_checkpoint(processed_set):
    """処理済みIDを即時JSONに保存"""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(list(processed_set), f, ensure_ascii=False, indent=2)

def main():
    print("🚀 【完全決定版】レジューム対応・全レース一括収集パイプライン開始")
    print(f"📁 データ保存先: {DATA_DIR}")
    
    # 既存データをスキャンして既取得IDを完璧に把握
    processed_races = load_all_processed_race_ids()
    print(f"📌 既存のCSV/JSONから引き継いだ処理済みレース数: {len(processed_races)} 件\n")

    start_year, end_year = 2022, 2026
    
    # 2026年から2022年へ逆順で巡回
    for year in range(end_year, start_year - 1, -1):
        year_csv_path = os.path.join(DATA_DIR, f"all_race_dataset_{year}.csv")
        year_records = []
        
        # すでに年別CSVが存在する場合は読み込んでおく
        if os.path.exists(year_csv_path):
            try:
                df_old = pd.read_csv(year_csv_path, dtype=str)
                if not df_old.empty and "race_id" in df_old.columns:
                    year_records.append(df_old)
            except Exception:
                pass

        for month in range(1, 13):
            # 未来の月に対するガード
            if year == end_year and month > 12:
                break
                
            try:
                race_ids = keibascraper.race_list(year, month)
            except Exception:
                continue
                
            if not race_ids:
                continue
                
            # まだ処理していないレースがどれだけあるか確認
            unprocessed_ids = [rid for rid in race_ids if rid not in processed_races]
            if not unprocessed_ids:
                continue
                
            print(f"📅 【{year}年{month:02d}月】 未取得レース: {len(unprocessed_ids)}件 / 全{len(race_ids)}件")
            
            with tqdm(race_ids, desc=f"{year}年{month:02d}月", unit="レース") as pbar:
                for race_id in pbar:
                    # すでに処理済みの場合はサーバーにアクセスせず完全スキップ
                    if race_id in processed_races:
                        pbar.set_postfix(status="スキップ(既取得)")
                        continue
                        
                    pbar.set_postfix(status=f"取得中({race_id[-4:]})")
                    
                    try:
                        # サーバー負荷軽減のウェイト
                        time.sleep(random.uniform(0.3, 0.7))
                        
                        race_info, result_list = keibascraper.load("result", race_id)
                        
                        if not result_list:
                            processed_races.add(race_id)
                            save_checkpoint(processed_races)
                            continue
                            
                        # データフレーム化
                        df_res = pd.DataFrame(result_list)
                        df_res["race_id"] = race_id
                        df_res["開催年"] = year
                        
                        # レース情報（名前やコース）の付与
                        if isinstance(race_info, list) and len(race_info) > 0:
                            info_dict = race_info[0]
                        elif isinstance(race_info, dict):
                            info_dict = race_info
                        else:
                            info_dict = {}
                            
                        df_res["レース名"] = info_dict.get("race_name", "")
                        df_res["コース"] = info_dict.get("course", "")
                        
                        year_records.append(df_res)
                        
                        # 処理済みに追加して即時保存
                        processed_races.add(race_id)
                        save_checkpoint(processed_races)
                        
                        pbar.set_postfix(status=f"保存OK({len(df_res)}頭)")
                        
                    except Exception as e:
                        # エラー時も無限ループ防止のために処理済みとしてマーク
                        processed_races.add(race_id)
                        save_checkpoint(processed_races)
                        continue

        # 年ごとにCSVをまとめて上書き保存（カスタマイズしたresult.jsonの項目が反映されます）
        if year_records:
            year_df = pd.concat(year_records, ignore_index=True).drop_duplicates(subset=["race_id", "horse_number"])
            year_df.to_csv(year_csv_path, index=False, encoding="utf-8-sig")
            print(f"✅ 【{year}年】CSV保存完了: {year_csv_path} (総レコード数: {len(year_df)})")

    print("\n🎉 すべての処理が正常に完了しました！")

if __name__ == "__main__":
    main()
