import os
import pandas as pd
import streamlit as st

@st.cache_data
def load_historical_jra_data(filepath="dirt_races_201812_202107_clean.csv"):
    target_path = None
    for path in [filepath, "dirt_races_201812_202107_clean.csv", "./dirt_races_201812_202107_clean.csv"]:
        if os.path.exists(path):
            target_path = path
            break
            
    if not target_path:
        return pd.DataFrame(), "実データファイルが見つかりません。"
    
    try:
        df = pd.read_csv(target_path, encoding='utf-8', low_memory=False)
        return df, "success"
    except Exception as e:
        try:
            df = pd.read_csv(target_path, encoding='cp932', low_memory=False)
            return df, "success"
        except Exception as ex:
            return pd.DataFrame(), f"読込エラー: {str(ex)}"

@st.cache_data
def run_strict_backtest(df):
    if df.empty:
        return None
    
    try:
        race_id_col = 'レースID' if 'レースID' in df.columns else df.columns[1]
        rank_col = '着順' if '着順' in df.columns else 'rank'
        time_col = 'タイム' if 'タイム' in df.columns else None
        last3f_col = '上り' if '上り' in df.columns else None
        
        grouped = df.groupby(race_id_col)
        total_races = 0
        idx1_win_count = 0
        idx1_podium_count = 0
        
        for r_id, group in grouped:
            g = group.copy()
            g[rank_col] = pd.to_numeric(g[rank_col], errors='coerce')
            
            # AI指数の算出
            if time_col and time_col in g.columns:
                def parse_time(t_str):
                    try:
                        if pd.isna(t_str): return 999.0
                        parts = str(t_str).split(':')
                        if len(parts) == 2:
                            return float(parts[0]) * 60 + float(parts[1])
                        return float(t_str)
                    except:
                        return 999.0
                g['time_sec'] = g[time_col].apply(parse_time)
                g['time_index'] = (100 - (g['time_sec'] - g['time_sec'].min()) * 10).clip(0, 100)
            else:
                g['time_index'] = 50.0
                
            if last3f_col and last3f_col in g.columns:
                g['last3f_val'] = pd.to_numeric(g[last3f_col], errors='coerce').fillna(38.0)
                g['last3f_index'] = (100 - (g['last3f_val'] - g['last3f_val'].min()) * 15).clip(0, 100)
            else:
                g['last3f_index'] = 50.0
                
            g['ai_score'] = g['time_index'] * 0.6 + g['last3f_index'] * 0.4
            g = g.dropna(subset=[rank_col])
            
            if len(g) < 5:
                continue
                
            g['idx_rank'] = g['ai_score'].rank(ascending=False, method='min').astype(int)
            
            idx1_horse = g[g['idx_rank'] == 1]
            if idx1_horse.empty:
                continue
                
            actual_rank = idx1_horse.iloc[0][rank_col]
            
            if actual_rank == 1:
                idx1_win_count += 1
            if actual_rank <= 3:
                idx1_podium_count += 1
                
            total_races += 1

        win_rate = round((idx1_win_count / total_races) * 100, 2) if total_races > 0 else 0.0
        podium_rate = round((idx1_podium_count / total_races) * 100, 2) if total_races > 0 else 0.0

        return {
            "total_races": total_races,
            "idx1_win_rate": win_rate,
            "idx1_podium_rate": podium_rate,
            "idx1_win_count": idx1_win_count,
            "idx1_podium_count": idx1_podium_count
        }
    except Exception as e:
        return None
