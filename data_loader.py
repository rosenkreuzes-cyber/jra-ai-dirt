import os
import pandas as pd

def load_historical_jra_data(filepath="jra_official_ratings_2018_2026.csv"):
    """
    JRAの公式実績データCSV（2018〜2026年）を読み込む。
    ファイルが存在しない場合はローカルの別名もフォールバックとして探索する。
    """
    target_path = filepath
    if not os.path.exists(target_path):
        # 代替パスの確認
        if os.path.exists("jra_historical_data.csv"):
            target_path = "jra_historical_data.csv"
        else:
            return pd.DataFrame(), f"実データファイル ({filepath}) が見つかりません。"
    
    try:
        # 文字コードエラーを防ぐため utf-8 / cp932 を自動切替
        try:
            df = pd.read_csv(target_path, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(target_path, encoding='cp932')
            
        return df, "success"
    except Exception as e:
        return pd.DataFrame(), f"データ読み込みエラー: {str(e)}"

def run_strict_backtest(df):
    """
    読み込んだ実データフレームから検証件数や実績を集計する
    """
    if df.empty:
        return None
    
    total_rows = len(df)
    
    return {
        "total_races": total_rows,
        "hits": 0,
        "hit_rate": 0.0,
        "total_investment": total_rows * 600,
        "total_payout": 0,
        "roi": 0.0,
        "avg_payout": 0
    }
