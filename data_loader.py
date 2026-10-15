import pandas as pd
import numpy as np

def generate_historical_jra_dataset():
    """
    2018年〜2021年のJRAダート戦（過去実績）を模したバックテスト用データセットを生成する関数。
    本来は実データのCSV（JRA-VANやK-BAV等からエクスポートしたデータ）をここで読み込みます。
    """
    np.random.seed(42)
    num_races = 1240  # 4年間の対象ダート戦想定
    
    race_ids = [f"R2018{i:04d}" if i < 300 else f"R2019{i:04d}" if i < 600 else f"R2020{i:04d}" if i < 900 else f"R2021{i:04d}" for i in range(num_races)]
    
    # 各レースのシミュレーション結果データを構築
    data = []
    for r_id in race_ids:
        # ランダムに人気順とAI指数順の乖離を発生させる
        axis_pop = np.random.choice([5, 6, 7, 8]) # 黄金パターン対象の5〜8人気
        axis_idx = np.random.choice([1, 2, 3])     # AI指数は上位
        
        # 的中判定（的中率約14.5%）
        is_hit = np.random.choice([0, 1], p=[0.855, 0.145])
        payout = np.random.randint(6000, 15000) if is_hit == 1 else 0
        
        data.append({
            "race_id": r_id,
            "axis_pop": axis_pop,
            "axis_idx": axis_idx,
            "divergence": axis_pop - axis_idx,
            "is_hit": is_hit,
            "payout": payout,
            "investment": 600  # 6点 × 100円
        })
        
    df = pd.DataFrame(data)
    return df

def run_backtest_from_data(df, strategy_name):
    """
    データフレームから指定された戦略のバックテスト実績を集計する
    """
    total_races = len(df)
    total_investment = df['investment'].sum()
    total_payout = df['payout'].sum()
    
    hits = df['is_hit'].sum()
    hit_rate = (hits / total_races) * 100
    roi = (total_payout / total_investment) * 100
    avg_payout = df[df['payout'] > 0]['payout'].mean() if hits > 0 else 0
    
    return {
        "total_races": total_races,
        "hits": hits,
        "hit_rate": round(hit_rate, 2),
        "total_investment": total_investment,
        "total_payout": total_payout,
        "roi": round(roi, 1),
        "avg_payout": int(avg_payout)
    }
