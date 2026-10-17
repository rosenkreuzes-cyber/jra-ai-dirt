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
    if df is None or df.empty:
        return None
    
    try:
        race_id_col = 'レースID' if 'レースID' in df.columns else df.columns[1]
        rank_col = '着順' if '着順' in df.columns else 'rank'
        time_col = 'タイム' if 'タイム' in df.columns else None
        last3f_col = '上り' if '上り' in df.columns else None
        
        grouped = df.groupby(race_id_col)
        total_races = 0
        
        rank_idx_counts = {
            1: {i: 0 for i in range(1, 8)},
            2: {i: 0 for i in range(1, 8)},
            3: {i: 0 for i in range(1, 8)}
        }
        
        for r_id, group in grouped:
            g = group.copy()
            g[rank_col] = pd.to_numeric(g[rank_col], errors='coerce')
            
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
            
            if len(g) < 7:
                continue
                
            g['idx_rank'] = g['ai_score'].rank(ascending=False, method='min').astype(int)
            
            for target_rank in [1, 2, 3]:
                horses_at_rank = g[g[rank_col] == target_rank]
                if not horses_at_rank.empty:
                    idx_r = int(horses_at_rank.iloc[0]['idx_rank'])
                    if 1 <= idx_r <= 7:
                        rank_idx_counts[target_rank][idx_r] += 1
                        
            total_races += 1

        rank_idx_percentages = {1: {}, 2: {}, 3: {}}
        for target_rank in [1, 2, 3]:
            for idx_r in range(1, 8):
                count = rank_idx_counts[target_rank][idx_r]
                pct = round((count / total_races) * 100, 2) if total_races > 0 else 0.0
                rank_idx_percentages[target_rank][idx_r] = pct

        return {
            "total_races": total_races,
            "percentages": rank_idx_percentages,
            "raw_counts": rank_idx_counts
        }
    except Exception as e:
        return None

def fetch_api_live_races(api_data=None):
    """
    【API連携用受け皿関数】
    API経由で取得した本日のリアル開催データをここに流し込むことで、
    アプリ側のLIVE画面にリアルタイムの出馬表・オッズを反映させます。
    """
    if not api_data:
        return [], "APIデータがまだ投入されていません。データを取得してからご指示ください。"
    
    # 取得したAPIデータの形式に応じてパース処理をここに記述します
    return api_data, "APIデータの読込に成功しました。"
