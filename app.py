import streamlit as st
import pandas as pd
import numpy as np
import itertools
import os
import glob
import re

# 1. ページの設定
st.set_page_config(
    page_title="JRA 黄金パターン AI ダッシュボード",
    page_icon="🏇",
    layout="centered"
)

# 2. カスタムCSS
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    h1 { font-size: 1.4rem !important; color: #ff4b4b; }
    h3 { font-size: 1.1rem !important; color: #f6e05e; }
    .race-card {
        background-color: #1a1c23; padding: 15px; border-radius: 10px;
        border-left: 5px solid #ff4b4b; margin-bottom: 15px;
    }
    .confidence-badge {
        background-color: #b7791f; color: #ffffff; padding: 2px 8px;
        border-radius: 4px; font-size: 0.75rem; font-weight: bold; float: right;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏇 JRA 黄金パターン AI ダッシュボード [強制読込版]")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="box_unit")
    if st.button("🔄 アプリを再読込"):
        st.rerun()

# タイム・上り3F解析
def parse_horse_history(row_str):
    time_score = 70.0
    last3f_score = 70.0
    try:
        m_3f = re.search(r'3F\s*([\d\.]+)', row_str)
        if m_3f:
            val_3f = float(m_3f.group(1))
            last3f_score = max(50.0, 100.0 - (val_3f - 35.0) * 10)
            
        m_time = re.search(r'(\d+):([\d\.]+)', row_str)
        if m_time:
            minutes = int(m_time.group(1))
            seconds = float(m_time.group(2))
            total_sec = minutes * 60 + seconds
            time_score = max(50.0, 110.0 - (total_sec - 75.0) * 2)
    except:
        pass
    return time_score, last3f_score

# ワークスペース内のすべてのExcelファイルを強制的に解析する関数
def load_and_parse_excel_races():
    excel_files = glob.glob('*.xlsx')
    races = []
    
    for filename in excel_files:
        try:
            xls = pd.ExcelFile(filename)
            # ファイル名に18が含まれていれば日曜、それ以外は土曜
            is_sunday = ('18' in filename)
            day_label = "日曜日開催" if is_sunday else "土曜日開催"
            
            for sheet_name in xls.sheet_names:
                df_data = pd.read_excel(filename, sheet_name=sheet_name, header=1)
                
                # 馬番カラムの検索
                horse_col = None
                for col in df_data.columns:
                    if '馬番' in str(col):
                        horse_col = col
                        break
                if not horse_col:
                    continue
                
                df_data['馬番_num'] = pd.to_numeric(df_data[horse_col], errors='coerce')
                reset_indices = df_data[df_data['馬番_num'] == 1].index.tolist()
                reset_indices.append(len(df_data))
                
                for i in range(len(reset_indices) - 1):
                    start_idx = reset_indices[i]
                    end_idx = reset_indices[i+1]
                    race_df = df_data.iloc[start_idx:end_idx].copy()
                    
                    if len(race_df) < 2:
                        continue
                        
                    race_no = i + 1
                    s_lower = sheet_name.lower()
                    if "kyouto" in s_lower or "京都" in sheet_name:
                        course_name = "京都"
                    elif "niigata" in s_lower or "新潟" in sheet_name:
                        course_name = "新潟"
                    else:
                        course_name = "東京"
                    
                    horses = []
                    for _, row in race_df.iterrows():
                        h_val = row.get(horse_col)
                        if pd.isna(h_val):
                            continue
                        try:
                            horse_no = int(float(h_val))
                        except:
                            continue
                            
                        name_col = None
                        for c in race_df.columns:
                            if '馬名' in str(c):
                                name_col = c
                                break
                        if not name_col:
                            continue
                            
                        col_val = str(row[name_col])
                        name_line = col_val.split('\n')[0].strip()
                        if not name_line or name_line == 'nan':
                            continue
                        
                        odds_val = 15.0
                        pop_val = 5
                        try:
                            if '(' in col_val and '人気' in col_val:
                                m_odds = re.search(r'([\d\.]+)\s*\(\s*(\d+)番人気', col_val)
                                if m_odds:
                                    odds_val = float(m_odds.group(1))
                                    pop_val = int(m_odds.group(2))
                        except:
                            pass

                        prev_run = ""
                        for c in race_df.columns:
                            if '前走' in str(c):
                                prev_run = str(row.get(c, ''))
                                break
                                
                        t_score, l3f_score = parse_horse_history(prev_run)
                        
                        horses.append({
                            "horse_no": horse_no,
                            "name": name_line,
                            "pop_rank": pop_val,
                            "odds": odds_val,
                            "time_index": t_score,
                            "last3f_index": l3f_score,
                            "track_aptitude": float(75.0)
                        })
                    
                    if horses:
                        races.append({
                            "course": course_name,
                            "day_label": day_label,
                            "race_name": f"{course_name} 第{race_no}レース",
                            "horses": horses
                        })
        except Exception as e:
            continue
            
    return races

all_loaded_races = load_and_parse_excel_races()

def calculate_ai_indices(horses_data):
    df = pd.DataFrame(horses_data)
    df['ai_score'] = (
        df['time_index'] * 0.5 + 
        df['last3f_index'] * 0.3 + 
        df['track_aptitude'] * 0.2
    )
    df['idx_rank'] = df['ai_score'].rank(ascending=False, method='min').astype(int)
    df['divergence'] = df['pop_rank'] - df['idx_rank']
    return df.sort_values('idx_rank').reset_index(drop=True)

# --- タブ構成: 土曜日 / 日曜日 ---
tab_sat, tab_sun = st.tabs(["📅 土曜日開催レース", "📅 日曜日開催レース"])

def render_race_list(target_day_label):
    filtered_races = [r for r in all_loaded_races if r['day_label'] == target_day_label]
    
    if not filtered_races:
        st.warning(f"⚠️ {target_day_label} のレースデータが検出されませんでした。")
        return

    for r_idx, race in enumerate(filtered_races):
        scored_df = calculate_ai_indices(race["horses"])
        top4_nos = scored_df.head(4)['horse_no'].tolist()

        st.markdown(f"""
        <div class="race-card">
            <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">📅 {race['day_label']}</span>
            <span class="confidence-badge">🔥 4頭BOX (4点)</span>
            <h3 style="margin-top: 8px;">📍 {race['race_name']}</h3>
            <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
                <b>🎯 AI上位4頭 (BOX対象):</b> 馬番 <b>{', '.join(map(str, top4_nos))}番</b>
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"🎫 {race['race_name']} の3連複4頭BOX買い目 & 出走馬一覧を開く", expanded=False):
            box_bets = []
            for comb in itertools.combinations(top4_nos, 3):
                comb_sorted = sorted(list(comb))
                matched_odds = scored_df[scored_df['horse_no'].isin(comb_sorted)]['odds'].sum()
                simulated_odds = round(matched_odds * 1.5, 1)
                box_bets.append({
                    "券種": "3連複BOX",
                    "組み合わせ": f"{comb_sorted[0]} - {comb_sorted[1]} - {comb_sorted[2]}",
                    "投資金額": f"{bet_unit:,} 円",
                    "想定オッズ": f"{simulated_odds} 倍",
                    "予想払戻金": f"約 {int(bet_unit * simulated_odds):,} 円"
                })
            st.dataframe(pd.DataFrame(box_bets), use_container_width=True, hide_index=True)

            st.markdown("##### 📋 出走馬 AIスコアリング一覧")
            sorted_df = scored_df.sort_values('idx_rank').reset_index(drop=True)
            for _, row in sorted_df.iterrows():
                gap_color = "#63b3ed" if row['divergence'] > 0 else ("#f6e05e" if row['divergence'] == 0 else "#ff4b4b")
                st.markdown(f"""
                <div style="background-color: #1a1c23; border: 1px solid #374151; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;">
                    <div style="font-size: 1.0rem; font-weight: bold; color: #ffffff; margin-bottom: 4px;">
                        <span style="background-color: #2b6cb0; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; margin-right: 6px;">馬番 {int(row['horse_no'])}</span>
                        {row['name']}
                    </div>
                    <div style="display: flex; gap: 15px; font-size: 0.8rem; color: #cbd5e0; flex-wrap: wrap;">
                        <div>AI順位: <b style="color: #f6e05e;">第{int(row['idx_rank'])}位</b></div>
                        <div>人気: <b>{int(row['pop_rank'])}番人気</b></div>
                        <div>AI指数: <b>{row['ai_score']:.1f}</b></div>
                        <div>乖離: <b style="color: {gap_color};">{row['divergence']:+d}</b></div>
                        <div>単勝オッズ: <b style="color: #4ade80;">{row['odds']}倍</b></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

with tab_sat:
    st.markdown("### 🟢 土曜日開催のレース一覧")
    render_race_list("土曜日開催")

with tab_sun:
    st.markdown("### 🟠 日曜日開催のレース一覧")
    render_race_list("日曜日開催")
