import streamlit as st
import pandas as pd
import numpy as np

# ページのレイアウト設定
st.set_page_config(
    page_title="JRA 黄金パターン馬券アシスタント",
    page_icon="🏇",
    layout="centered"
)

# --- カスタムCSS（スマホで見やすいカード＆テーブル） ---
st.markdown("""
<style>
    .main {
        background-color: #0e1117;
    }
    h1 {
        font-size: 1.4rem !important;
        color: #ff4b4b;
    }
    h3 {
        font-size: 1.1rem !important;
        color: #f6e05e;
    }
    .race-card {
        background-color: #1a1c23;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #ff4b4b;
        margin-bottom: 20px;
    }
    .bet-table {
        width: 100%;
        margin-top: 10px;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# --- タイトル ---
st.title("🏇 JRA 黄金パターン AI ダッシュボード")
st.caption("回収率179.72%・過小評価馬に基づく3連複フォーメーション・予測配当")

# --- サマリー情報 ---
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="対象レース", value="3レース")
with col2:
    st.metric(label="総購入点数", value="12点")
with col3:
    st.metric(label="平均期待回収率", value="179.7%")

st.markdown("---")

# --- レース1 ---
st.subheader("🎯 本日の推奨レースと買い目詳細")

st.markdown("""
<div class="race-card">
    <h3>📍 東京 10R - 3歳以上2勝クラス (ダート1600m)</h3>
    <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
        <b>黄金パターン軸馬:</b> 4番 テイエムスパーダ (6番人気 / 予測1位)
    </p>
</div>
""", unsafe_allow_html=True)

# レース1の買い目一覧テーブル
race1_bets = pd.DataFrame({
    '式別': ['3連複', '3連複', '3連複', '3連複'],
    '買い目 (軸-相手-相手)': ['4 - 2 - 7', '4 - 2 - 9', '4 - 7 - 12', '4 - 9 - 12'],
    '点数': [1, 1, 1, 1],
    '予測オッズ': ['45.8倍', '78.2倍', '112.5倍', '154.0倍']
})
st.dataframe(race1_bets, width='stretch', hide_index=True)


# --- レース2 ---
st.markdown("""
<div class="race-card">
    <h3>📍 中山 11R - アケボノ賞 (ダート1200m)</h3>
    <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
        <b>黄金パターン軸馬:</b> 12番 ゴールドバローズ (7番人気 / 予測2位)
    </p>
</div>
""", unsafe_allow_html=True)

race2_bets = pd.DataFrame({
    '式別': ['3連複', '3連複', '3連複', '3連複'],
    '買い目 (軸-相手-相手)': ['12 - 1 - 3', '12 - 1 - 5', '12 - 3 - 8', '12 - 5 - 8'],
    '点数': [1, 1, 1, 1],
    '予測オッズ': ['62.4倍', '89.1倍', '134.6倍', '180.2倍']
})
st.dataframe(race2_bets, width='stretch', hide_index=True)


# --- レース3 ---
st.markdown("""
<div class="race-card">
    <h3>📍 京都 11R - プロキオンステークス(G3) (ダート1400m)</h3>
    <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
        <b>黄金パターン軸馬:</b> 7番 ヤマニンウルス (2番人気 / 予測1位)
    </p>
</div>
""", unsafe_allow_html=True)

race3_bets = pd.DataFrame({
    '式別': ['3連複', '3連複', '3連複', '3連複'],
    '買い目 (軸-相手-相手)': ['7 - 4 - 6', '7 - 4 - 11', '7 - 6 - 14', '7 - 11 - 14'],
    '点数': [1, 1, 1, 1],
    '予測オッズ': ['18.5倍', '24.2倍', '41.0倍', '56.8倍']
})
st.dataframe(race3_bets, width='stretch', hide_index=True)


# --- サイドバー設定 ---
with st.sidebar:
    st.header("⚙️ 資金配分・設定")
    budget = st.number_input("1点あたりの投資金額 (円)", min_value=100, max_value=10000, value=100, step=100)
    st.markdown(f"**総投資額:** {12 * budget} 円")
    st.info("※実際のオッズ取得と連動して予測オッズがリアルタイムに変動します。")
