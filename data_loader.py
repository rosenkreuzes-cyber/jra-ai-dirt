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
        current_files = os.listdir(".") if os.path.exists(".") else []
        return pd.DataFrame(), f"ファイルが見つかりません。現在地のファイル: {current_files}"
    
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
    架空の回収率・払戻金を完全廃止し、実データにおける上位馬（例: 上位5頭）の
    実際の着順入着実績（1着率・2着率・3着内率）を厳密に集計する。
    """
    if df.empty:
        return None
    
    race_id_col = 'レースID' if 'レースID' in df.columns else 'race_id'
    rank_col = '着順' if '着順' in df.columns else 'rank'
    pop_col = '人気' if '人気' in df.columns else 'popularity'
    
    if race_id_col not in df.columns or rank_col not in df.columns or pop_col not in df.columns:
        return None

    grouped = df.groupby(race_id_col)
    total_races = 0
    
    top5_win_count = 0      # 上位5頭のなかに1着馬がいたレース数
    top5_podium_count = 0   # 上位5頭のなかに3着以内馬が入った延べ頭数
    
    for r_id, group in grouped:
        g = group.copy()
        g[pop_col] = pd.to_numeric(g[pop_col], errors='coerce')
        g[rank_col] = pd.to_numeric(g[rank_col], errors='coerce')
        g = g.dropna(subset=[pop_col, rank_col])
        
        if len(g) < 5:
            continue
            
        # 人気上位5頭を抽出
        top5 = g.sort_values(pop_col).head(5)
        
        # 1着馬が上位5頭の中に含まれていたか
        if (top5[rank_col] == 1).any():
            top5_win_count += 1
            
        # 上位5頭のうち3着以内に入った頭数
        podium_in_top5 = len(top5[top5[rank_col] <= 3])
        top5_podium_count += podium_in_top5
        
        total_races += 1

    win_rate = round((top5_win_count / total_races) * 100, 2) if total_races > 0 else 0.0
    avg_podium_in_top5 = round(top5_podium_count / total_races, 2) if total_races > 0 else 0.0

    return {
        "total_races": total_races,
        "win_rate": win_rate,
        "avg_podium": avg_podium_in_top5,
        "top5_win_count": top5_win_count
    }
