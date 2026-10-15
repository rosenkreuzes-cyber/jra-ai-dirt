import streamlit as st
import itertools
import pandas as pd
import numpy as np

# ページのレイアウト設定
st.set_page_config(
    page_title="JRA 黄金パターン AI ダッシュボード (Ver.2)",
    page_icon="🏇",
    layout="centered"
)

# --- カスタムCSS ---
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    h1 { font-size: 1.4rem !important; color: #ff4b4b; }
    h3 { font-size: 1.1rem !important; color: #f6e05e; }
    .race-card {
        background-color: #1a1c23; padding: 15px; border-radius: 10px;
        border-left: 5px solid #ff4b4b; margin-bottom: 15px;
    }
    .control-box {
        background-color: #161b22; border: 1px solid #30363d;
        padding: 12px; border-radius: 8px; margin-bottom: 20px;
    }
    .result-box {
        background-color: #111827; border: 1px solid #374151;
        padding: 12px; border-radius: 8px; margin-top: 12px; font-size: 0.85rem;
    }
    .backtest-box {
        background-color: #1f2937; border: 1px solid #4b5563;
        padding: 15px; border-radius: 10px; margin-bottom: 20px;
    }
    .confidence-badge {
        background-color: #b7791f; color: #ffffff; padding: 2px 8px;
        border-radius: 4px; font-size: 0.75rem; font-weight: bold; float: right;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏇 JRA 黄金パターン AI ダッシュボード [Ver.2 厳密検証版]")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 資金・検証設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="s3_unit")
    
    st.markdown("---")
    st.markdown("### 📊 分析モード・戦略")
    bt_strategy = st.selectbox(
        "検証戦略", 
        ["黄金パターン (6-7人気軸 / 相手4頭)", "指数3位軸 (堅実型 / 相手4頭)"], 
        key="s3_strat"
    )

# --- 3連複の正確な重複なし（6点）生成ロジック ---
def generate_exact_sanrenpuku_mult(axis, others):
    bets = []
    for pair in itertools.combinations(others, 2):
        comb = sorted([axis, pair[0], pair[1]])
        bets.append(f"{comb[0]} - {comb[1]} - {comb[2]}")
    return sorted(list(set(bets)))

# --- 【ステップ3の核心】論理的AI指数の算出ロジック ---
def calculate_ai_indices(horses_data):
    """
    各馬のファクター（走破タイム指数、上がり指数、馬場適性）を合算してAI総合指数を算出し、
    指数順位（1位が最高得点）を自動決定する。
    """
    df = pd.DataFrame(horses_data)
    # AI総合指数の算出式（重み付けスコアリング）
    df['ai_score'] = (
        df['time_index'] * 0.4 + 
        df['last3f_index'] * 0.3 + 
        df['track_aptitude'] * 0.3
    )
    # 指数順位の算出（高い順に 1, 2, 3...）
    df['idx_rank'] = df['ai_score'].rank(ascending=False, method='min').astype(int)
    # 期待値ギャップ（人気順 - 指数順位：プラスが大きいほど過小評価のお宝馬）
    df['divergence'] = df['pop_rank'] - df['idx_rank']
    return df.sort_values('idx_rank').reset_index(drop=True)

# --- タブ ---
tab_live, tab_backtest = st.tabs(["📍 本日のレース & AIスコアリング (LIVE)", "📈 過去データ検証・シミュレータ"])

with tab_live:
    st.caption("【ステップ3適用】固定値ではなく、タイム・上がり・適性データから動的にAI指数とギャップを算出します。")

    # サンプルレースの出走馬データ（実データ連携の前段階としての構造化データ）
    sample_race_horses = [
        {"horse_no": 2, "name": "メイショウモウコ", "pop_rank": 3, "time_index": 78.5, "last3f_index": 72.0, "track_aptitude": 80.0},
        {"horse_no": 4, "name": "テイエムスパーダ", "pop_rank": 6, "time_index": 84.0, "last3f_index": 82.5, "track_aptitude": 85.0}, # ← AI指数上位の過小評価馬
        {"horse_no": 7, "name": "サンライズホープ", "pop_rank": 1, "time_index": 88.0, "last3f_index": 75.0, "track_aptitude": 82.0},
        {"horse_no": 9, "name": "ロードエクレール", "pop_rank": 4, "time_index": 79.0, "last3f_index": 78.0, "track_aptitude": 76.0},
        {"horse_no": 12, "name": "グレートサンド", "pop_rank": 8, "time_index": 75.0, "last3f_index": 74.0, "track_aptitude": 78.0}
    ]

    # AIスコアリングの実行
    scored_df = calculate_ai_indices(sample_race_horses)

    st.markdown("### 📍 東京 10R - ダート 1600m（AIスコアリング結果）")
    
    # 黄金パターンに合致する軸馬（指数上位かつ6-7人気近辺）の自動選定
    # ここでは例として指数が高く、かつ人気が5〜8位の馬を軸候補としてピックアップ
    axis_candidates = scored_df[(scored_df['pop_rank'] >= 5) & (scored_df['pop_rank'] <= 8)]
    if not axis_candidates.empty:
        recommended_axis = axis_candidates.iloc[0]
    else:
        recommended_axis = scored_df.iloc[1] # フォールバック

    # 相手馬（軸以外の上位馬）の選定
    others_list = scored_df[scored_df['horse_no'] != recommended_axis['horse_no']]['horse_no'].tolist()[:4]

    exact_bets = generate_exact_sanrenpuku_mult(int(recommended_axis['horse_no']), others_list)
    total_investment = len(exact_bets) * bet_unit

    st.markdown(f"""
    <div class="race-card">
        <span style="background-color: #2d3
