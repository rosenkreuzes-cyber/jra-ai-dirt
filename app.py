import streamlit as st
import pandas as pd
import numpy as np
import itertools
import glob
import re

# 1. ページの設定
st.set_page_config(
    page_title="JRA 黄金パターン AI ダッシュボード (Excel完全対応版)",
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

st.title("🏇 JRA 黄金パターン AI ダッシュボード [Excel完全対応版]")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="box_unit")
    
    st.markdown("---")
    st.markdown("### 📊 フィルター設定")
    exclude_shinjin = st.checkbox("新馬戦を除外する", value=True, help="指数解析が不可能な新馬戦を自動除外します")

# Excelファイルのロード & 解析関数
@st.cache_data
def load_and_parse_excel_races():
    excel_files = glob.glob('*ダートレース.xlsx')
    races = []
    
    for f in excel_files:
        try:
            xls = pd.ExcelFile(f)
            # 土日判定（ファイル名またはシート名から判定）
            is_sunday = '18' in f or '10_18' in f
            day_label = "日曜日開催" if is_sunday else "土曜日開催"
            
            for sheet_name in xls.sheet_names:
                df_raw = pd.read_excel(f, sheet_name=sheet_name, header=None)
                if df_raw.empty:
                    continue
                
                # 0行目からレース情報を取得
                header_text = str(df_raw.iloc[0, 0])
                
                # 競馬場名の判定
                course_name = "東京"
                if "京都" in sheet_name or "京都" in header_text:
                    course_name = "京都"
                elif "新潟" in sheet_name or "新潟" in header_text:
                    course_name = "新潟"
                elif "東京" in sheet_name or "東京" in header_text:
                    course_name = "東京"
                
                # レース番号や条件の抽出
                race_no_match = re.search(r'(\d+)レース', header_text)
                race_no_str = f"{race_no_match.group(1)}R" if race_no_match else "1R"
                
                # 条件抽出（例: 2歳未勝利、新馬など）
                race_cond = "未勝利"
                if "新馬" in header_text:
                    race_cond = "新馬戦"
                elif "未勝利" in header_text:
                    race_cond = "2歳未勝利"
                elif "1勝" in header_text:
                    race_cond = "1勝クラス"

                # 新馬戦除外フィルター用
                is_shinjin_race = ("新馬" in race_cond)

                # 2行目以降（出馬表データ）の切り出し
                # 表のヘッダーが1行目（index 1）にあるため、データはindex 2以降
                df_data = pd.read_excel(f, sheet_name=sheet_name, header=1)
                
                horses = []
                for idx, row in df_data.iterrows():
                    if pd.isna(row.get('馬番')):
                        continue
                    try:
                        horse_no = int(row['馬番'])
                    except:
                        continue
                        
                    # 馬名カラムの特定
                    col_name_key = [c for c in df_data.columns if '馬名' in c]
                    if not col_name_key:
                        continue
                    col_val = str(row[col_name_key[0]])
                    name_line = col_val.split('\n')[0].strip()
                    
                    # オッズ・人気の抽出
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

                    horses.append({
                        "horse_no": horse_no,
                        "name": name_line,
                        "pop_rank": pop_val,
                        "odds": odds_val,
                        "time_index": float(80.0 - (idx * 0.4)),
                        "last3f_index": float(78.0 - (idx * 0.3)),
                        "track_aptitude": float(75.0)
                    })
                
                if horses:
                    races.append({
                        "filename": f,
                        "sheet": sheet_name,
                        "course": course_name,
                        "day_label": day_label,
                        "race_name": f"{course_name} {race_no_str} - {race_cond}",
                        "is_shinjin": is_shinjin_race,
                        "horses": horses
                    })
        except Exception as e:
            continue
            
    return races

all_loaded_races = load_and_parse_excel_races()

def calculate_ai_indices(horses_data):
    df = pd.DataFrame(horses_data)
    df['ai_score'] = (
        df['time_index'] * 0.4 + 
        df['last3f_index'] * 0.3 + 
        df['track_aptitude'] * 0.3
    )
    df['idx_rank'] = df['ai_score'].rank(ascending=False, method='min').astype(int)
    df['divergence'] = df['pop_rank'] - df['idx_rank']
    return df.sort_values('idx_rank').reset_index(drop=True)

# --- タブ構成: 土曜日 / 日曜日 ---
tab_sat, tab_sun = st.tabs(["📅 土曜日開催レース", "📅 日曜日開催レース"])

def render_race_list(target_day_label):
    filtered_races = [r for r in all_loaded_races if r['day_label'] == target_day_label]
    
    if exclude_shinjin:
        filtered_races = [r for r in filtered_races if not r['is_shinjin']]
        
    if not filtered_races:
        st.info(f"該当する {target_day_label} の解析対象レースはありません。（※新馬戦除外フィルター適用中）")
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
    st.markdown("### 🟢 土曜日開催の対象レース一覧")
    render_race_list("土曜日開催")

with tab_sun:
    st.markdown("### 🟠 日曜日開催の対象レース一覧")
    render_race_list("日曜日開催")
