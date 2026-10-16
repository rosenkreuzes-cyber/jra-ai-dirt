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
    """
    各レースでAI指数を算出し、
    『1着・2着・3着になった馬が、それぞれAI指数何位だったのか』の分布（1〜7位の割合％）を集計する。
    """
    if df.empty:
        return None
    
    try:
        race_id_col = 'レースID' if 'レースID' in df.columns else df.columns[1]
        rank_col = '着順' if '着順' in df.columns else 'rank'
        time_col = 'タイム' if 'タイム' in df.columns else None
        last3f_col = '上り' if '上り' in df.columns else None
        
        grouped = df.groupby(race_id_col)
        total_races = 0
        
        # 着順（1, 2, 3着）ごとの、AI指数順位（1〜7位）の出現回数を記録する辞書
        # 例: rank_idx_counts[1][1] = 1着になった馬の中でAI指数が1位だった回数
        rank_idx_counts = {
            1: {i: 0 for i in range(1, 8)},
            2: {i: 0 for i in range(1, 8)},
            3: {i: 0 for i in range(1, 8)}
        }
        
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
            
            if len(g) < 7:
                continue
                
            # AI指数順位を算出（高い方が1位）
            g['idx_rank'] = g['ai_score'].rank(ascending=False, method='min').astype(int)
            
            # 1着、2着、3着の馬を特定して、その馬のAI指数順位を確認
            for target_rank in [1, 2, 3]:
                horses_at_rank = g[g[rank_col] == target_rank]
                if not horses_at_rank.empty:
                    # 同着などがなければ先頭の馬
                    idx_r = int(horses_at_rank.iloc[0]['idx_rank'])
                    if 1 <= idx_r <= 7:
                        rank_idx_counts[target_rank][idx_r] += 1
                        
            total_races += 1

        # 回数データを％（割合）に変換する
        rank_idx_percentages = {
            1: {},
            2: {},
            3: {}
        }
        
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
