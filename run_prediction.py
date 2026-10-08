import pandas as pd
import numpy as np
import lightgbm as lgb
import os
import json

def train_model(historical_path="historical_race_data.csv"):
    if not os.path.exists(historical_path):
        raise FileNotFoundError("過去データが見つかりません。")
        
    df = pd.read_csv(historical_path)
    df['race_date'] = pd.to_datetime(df['race_date'])
    
    if 'horse_id' in df.columns:
        df = df.sort_values(['horse_id', 'race_date']).reset_index(drop=True)
        df['prev_distance'] = df.groupby('horse_id')['race_distance'].shift(1).fillna(df['race_distance'])
        df['prev_kinryo'] = df.groupby('horse_id')['kinryo'].shift(1).fillna(df['kinryo'])
    else:
        df = df.sort_values('race_date').reset_index(drop=True)
        df['prev_distance'] = df['race_distance']
        df['prev_kinryo'] = df['kinryo']

    df['dist_diff'] = df['race_distance'] - df['prev_distance']
    df['weight_change'] = df['kinryo'] - df['prev_kinryo']
    df['jockey_horse_win_rate'] = 0.33

    base_features = [
        'venue_code', 'race_distance', 'umaban', 'kinryo', 
        'pib3', 'pic', 'corner_4', 'avg_time_diff',
        'dist_diff', 'weight_change', 'jockey_horse_win_rate'
    ]
    features = [f for f in base_features if f in df.columns]
    target = 'target_top3'
    df['venue_code'] = df['venue_code'].astype('category')

    model = lgb.LGBMClassifier(
        objective='binary', boosting_type='gbdt',
        n_estimators=300, learning_rate=0.03, num_leaves=31, random_state=42
    )
    model.fit(df[features], df[target])
    
    return model, features

def generate_today_predictions(today_path="today_races.csv", historical_path="historical_race_data.csv", min_proba=0.61, max_proba=0.76):
    model, features = train_model(historical_path)
    
    if not os.path.exists(today_path):
        print(f"提示: '{today_path}' がないため過去データで出力テストを行います。")
        today_path = historical_path

    today_df = pd.read_csv(today_path)
    
    for col in ['dist_diff', 'weight_change']:
        if col not in today_df.columns:
            today_df[col] = 0
    if 'jockey_horse_win_rate' not in today_df.columns:
        today_df['jockey_horse_win_rate'] = 0.33
    if 'venue_code' in today_df.columns:
        today_df['venue_code'] = today_df['venue_code'].astype('category')

    today_df['pred_proba'] = model.predict_proba(today_df[features])[:, 1]

    betting_results = []

    for race_id, group in today_df.groupby('race_id'):
        unique_horses = group.drop_duplicates(subset=['umaban']).sort_values('pred_proba', ascending=False).reset_index(drop=True)
        if len(unique_horses) < 5:
            continue
            
        top1_proba = float(unique_horses.loc[0, 'pred_proba'])

        if min_proba <= top1_proba <= max_proba:
            axis_umaban = int(unique_horses.loc[0, 'umaban'])
            opp_umabans = [int(u) for u in unique_horses.loc[1:4, 'umaban']]

            bets = []
            for i in range(len(opp_umabans)):
                for j in range(i + 1, len(opp_umabans)):
                    bets.append(f"{axis_umaban}-{opp_umabans[i]}-{opp_umabans[j]}")

            betting_results.append({
                "race_id": str(race_id),
                "horse_count": len(unique_horses),
                "axis_proba": round(top1_proba, 3),
                "axis_umaban": axis_umaban,
                "opponent_umabans": opp_umabans,
                "bets": bets
            })

    with open("today_betting_orders.json", "w", encoding="utf-8") as f:
        json.dump(betting_results, f, ensure_ascii=False, indent=2)

    print(f"DONE: {len(betting_results)}件の対象レースを出力完了。")

if __name__ == "__main__":
    generate_today_predictions()
