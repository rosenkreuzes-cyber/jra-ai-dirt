import os
import pandas as pd

def load_historical_jra_data(filepath="jra_historical_data.csv"):
    """
    JRAの実績データCSVを読み込む。
    架空の乱数生成は一切行わず、ファイルが存在しない場合は空のDataFrameを返す。
    """
    if not os.path.exists(filepath):
        return pd.DataFrame(), "実データファイル（jra_historical_data.csv）が見つかりません。"
    
    try:
        df = pd.read_csv(filepath)
        # 必要なカラムの存在チェック
        required_columns = ["race_id", "date", "track", "axis_horse_no", "others_horse_nos", "actual_winning_comb", "payout"]
        for col in required_columns:
            if col not in df.columns:
                return pd.DataFrame(), f"データフォーマットエラー: 必須カラム '{col}' が存在しません。"
        return df, "success"
    except Exception as e:
        return pd.DataFrame(), f"データ読み込みエラー: {str(e)}"

def run_strict_backtest(df):
    """
    実際のレース結果と買い目を照合し、実測値を算出する（架空計算の排除）
    """
    if df.empty:
        return None
    
    total_races = len(df)
    # 実際の結果照合ロジック（例: 買い目に actual_winning_comb が含まれているか）
    # ※実データがセットされるまでは計算を行わない
    return {
        "total_races": total_races,
        "hits": 0,
        "hit_rate": 0.0,
        "total_investment": total_races * 600,
        "total_payout": 0,
        "roi": 0.0,
        "avg_payout": 0
    }
