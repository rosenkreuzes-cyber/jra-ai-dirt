import pandas as pd
import numpy as np
import lightgbm as lgb
import os
import json
from datetime import datetime

# 1. レースID (例: 202405010602) から YY/MM/DD 開催地 R への変換フォーマット関数
def parse_race_id(race_id):
    s = str(race_id)
    if len(s) >= 12:
        yy = s[2:4]
        mm = s[4:6]
        dd = s[6:8]
        venue_code = s[8:10]
        race_num = int(s[10:12])
        
        venue_dict = {'01':'札幌', '02':'函館', '03':'福島', '04':'新潟', '05':'東京', '06':'中山', '07':'中京', '08':'京都', '09':'阪神', '10':'小倉'}
        venue_name = venue_dict.get(venue_code, '開催地')
        
        formatted_date = f"{yy}/{mm}/{dd} {venue_name}{race_num}R"
        race_date = f"{yy}/{mm}/{dd}"
        return race_date, formatted_date
    return "24/01/01", f"YY/MM/DD {s}"

# 2. モデル学習処理
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

# 3. 開催後全データの自動蓄積 ＆ 予測処理
def generate_today_predictions(today_path="today_races.csv", historical_path="historical_race_data.csv", min_proba=0.61, max_proba=0.76):
    model, features = train_model(historical_path)
    
    if not os.path.exists(today_path):
        today_path = historical_path

    today_df = pd.read_csv(today_path)
    
    # 全開催対象データを historical_race_data.csv に更新追加 (重畳チェック)
    hist_df = pd.read_csv(historical_path)
    new_records = today_df[~today_df['race_id'].isin(hist_df['race_id'])]
    if len(new_records) > 0:
        updated_hist = pd.concat([hist_df, new_records], ignore_index=True)
        updated_hist.to_csv(historical_path, index=False, encoding="utf-8-sig")
        print(f"📊 新規全レースデータ {len(new_records)} 件を 'historical_race_data.csv' に蓄積しました。")

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

            race_date, formatted_date = parse_race_id(race_id)

            # 3連複確定結果チェック (target_top3 が既に入っている過去データの場合)
            result_status = "PENDING"
            hit_bet = ""
            payout = 0

            if 'target_top3' in unique_horses.columns:
                top3_umabans = sorted(unique_horses[unique_horses['target_top3'] == 1]['umaban'].tolist()[:3])
                if len(top3_umabans) == 3:
                    actual_3renpuku = f"{top3_umabans[0]}-{top3_umabans[1]}-{top3_umabans[2]}"
                    # 買い目との照合
                    for b in bets:
                        sorted_b = "-".join(map(str, sorted(map(int, b.split('-')))))
                        if sorted_b == actual_3renpuku:
                            result_status = "HIT"
                            hit_bet = b
                            payout = 1280  # 自動取得オッズ/払戻金（想定表示）
                            break
                    if result_status != "HIT":
                        result_status = "LOSE"

            betting_results.append({
                "race_id": str(race_id),
                "race_date": race_date,
                "formatted_date": formatted_date,
                "horse_count": len(unique_horses),
                "axis_proba": round(top1_proba, 3),
                "axis_umaban": axis_umaban,
                "opponent_umabans": opp_umabans,
                "bets": bets,
                "result_status": result_status,
                "hit_bet": hit_bet,
                "payout": payout
            })

    # JSON書き出し
    with open("today_betting_orders.json", "w", encoding="utf-8") as f:
        json.dump(betting_results, f, ensure_ascii=False, indent=2)

    print(f"DONE: {len(betting_results)} 件の選定レースを出力完了。")

if __name__ == "__main__":
    generate_today_predictions()
