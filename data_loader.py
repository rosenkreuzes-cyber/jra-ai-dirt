import os
import pandas as pd

def load_historical_jra_data(filepath="dirt_races_201812_202107_clean.csv"):
    """
    Googleドライブ内にある実際のJRAダート戦データCSVを読み込む。
    """
    target_path = filepath
    if not os.path.exists(target_path):
        # 代替として別名の可能性も考慮
        if os.path.exists("jra_historical_data.csv"):
            target_path = "jra_historical_data.csv"
        else:
            return pd.DataFrame(), f"実データファイル ({filepath}) が見つかりません。リポジトリにアップロードされているか確認してください。"
    
    try:
        try:
            df = pd.read_csv(target_path, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(target_path, encoding='cp932')
            
        return df, "success"
    except Exception as e:
        return pd.DataFrame(), f"データ読み込みエラー: {str(e)}"

def run_strict_backtest(df):
    """
    実際のJRAデータフレームからレース数を集計する
    """
    if df.empty:
        return None
    
    # レースID単位で集計
    if 'レースID' in df.columns:
        total_races = df['レースID'].nunique()
    elif 'race_id' in df.columns:
        total_races = df['race_id'].nunique()
    else:
        total_races = len(df) // 16 # 1レース平均頭数からの概算
    
    return {
        "total_races": total_races,
        "hits": 0,
        "hit_rate": 0.0,
        "total_investment": total_races * 600,
        "total_payout": 0,
        "roi": 0.0,
        "avg_payout": 0
    }
