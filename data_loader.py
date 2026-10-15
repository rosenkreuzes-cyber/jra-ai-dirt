import os
import pandas as pd
import itertools
import streamlit as st
import traceback

@st.cache_data
def load_historical_jra_data(filepath="dirt_races_201812_202107_clean.csv"):
    target_path = None
    for path in [filepath, "dirt_races_201812_202107_clean.csv", "./dirt_races_201812_202107_clean.csv"]:
        if os.path.exists(path):
            target_path = path
            break
            
    if not target_path:
        current_files = os.listdir(".") if os.path.exists(".") else []
        return pd.DataFrame(), f"ファイルが見つかりません。現在地のファイル: {current_files}"
    
    try:
        df = pd.read_csv(target_path, encoding='utf-8', low_memory=False)
        return df, "success"
    except Exception as e:
        # エラーのフルスタックトレースを文字列として返す
        error_detail = traceback.format_exc()
        return pd.DataFrame(), f"読込例外詳細:\n{error_detail}"

@st.cache_data
def run_strict_backtest(df):
    if df.empty:
        return None
    
    try:
        race_id_col = 'レースID' if 'レースID' in df.columns else 'race_id'
        rank_col = '着順' if '着順' in df.columns else 'rank'
        pop_col = '人気' if '人気' in df.columns else 'popularity'
        horse_no_col = '馬番' if '馬番' in df.columns else 'horse_no'

        grouped = df.groupby(race_id_col)
        total_races = 0
        hits = 0
        points_per_race = 6
        assumed_payout = 7500
        
        for r_id, group in grouped:
            if len(group) < 6:
                continue
                
            g = group.copy()
            g[pop_col] = pd.to_numeric(g[pop_col], errors='coerce')
            g[rank_col] = pd.to_numeric(g[rank_col], errors='coerce')
            g[horse_no_col] = pd.to_numeric(g[horse_no_col], errors='coerce')
            
            axis_candidates = g[(g[pop_col] >= 5) & (g[pop_col] <= 8)]
            if axis_candidates.empty:
                continue
                
            podium = g[g[rank_col] <= 3][horse_no_col].dropna().astype(int).tolist()
            if len(podium) < 3:
                continue
                
            axis_row = axis_candidates.iloc[0]
            axis_horse = int(axis_row[horse_no_col])
            
            others_pool = g[g[horse_no_col] != axis_horse].sort_values(pop_col)
            others_list = others_pool[horse_no_col].head(4).dropna().astype(int).tolist()
            
            if len(others_list) < 4:
                continue
                
            bets = []
            for pair in itertools.combinations(others_list, 2):
                comb = sorted([axis_horse, pair[0], pair[1]])
                bets.append((comb[0], comb[1], comb[2]))
                
            actual_podium_set = set(podium[:3])
            hit_flag = False
            for bet in bets:
                if set(bet) == actual_podium_set:
                    hit_flag = True
                    break
                    
            if hit_flag:
                hits += 1
                
            total_races += 1

        total_investment = total_races * (points_per_race * 100)
        total_payout = hits * assumed_payout

        hit_rate = round((hits / total_races) * 100, 2) if total_races > 0 else 0.0
        roi = round((total_payout / total_investment) * 100, 1) if total_investment > 0 else 0.0
        avg_payout = int(total_payout / hits) if hits > 0 else 0

        return {
            "total_races": total_races,
            "hits": hits,
            "hit_rate": hit_rate,
            "total_investment": total_investment,
            "total_payout": total_payout,
            "roi": roi,
            "avg_payout": avg_payout
        }
    except Exception as e:
        # バックテスト計算中のエラー詳細を例外として投げる
        raise RuntimeError(f"バックテスト計算エラー: {traceback.format_exc()}")
