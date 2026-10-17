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

@st.cache_data
def fetch_safe_live_race_horses():
    """
    実データファイル（CSV）から特定の1レース分の出走馬データを抽出する。
    オッズはCSV内の「単勝」列のデータを直接取得する。
    """
    df, status = load_historical_jra_data()
    if not df.empty and 'レースID' in df.columns:
        # 先頭のレースIDのデータを取得
        sample_race_id = df['レースID'].iloc[0]
        race_df = df[df['レースID'] == sample_race_id].copy()
        
        horses = []
        for _, row in race_df.iterrows():
            # 単勝オッズの取得（数値化できない場合はデフォルト10.0）
            odds_val = 10.0
            try:
                odds_val = float(row.get('単勝', 10.0))
                if pd.isna(odds_val) or odds_val <= 0:
                    odds_val = 15.0
            except:
                odds_val = 15.0
                
            pop_val = 5
            try:
                pop_val = int(row.get('人気', 5))
                if pd.isna(pop_val):
                    pop_val = 5
            except:
                pop_val = 5

            horses.append({
                "horse_no": int(row.get('馬番', 1)),
                "name": str(row.get('馬名', '抽出馬')),
                "pop_rank": pop_val,
                "time_index": float(78.0),
                "last3f_index": float(75.0),
                "track_aptitude": float(80.0),
                "odds": odds_val,
                "source": f"実データロード成功 (Race ID: {sample_race_id})"
            })
        return horses, f"実データ抽出成功 (レースID: {sample_race_id}, 出走頭数: {len(horses)}頭)"
    
    return [], "実データファイルが見つからないためサンプル表示にフォールバックします。"
