import streamlit as st
import pandas as pd
import numpy as np

# ページのレイアウト設定
st.set_page_config(
    page_title="JRA Dirt AI",
    page_icon="🏇",
    layout="centered" # スマホで見やすいようにcentered（またはwide）
)

# --- カスタムCSS（見た目をカッコよくする設定） ---
st.markdown("""
<style>
    /* 全体のフォントや余白の調整 */
    .main {
        background-color: #0e1117;
    }
    h1 {
        font-size: 1.5rem !important;
        color: #ff4b4b;
    }
    h3 {
        font-size: 1.2rem !important;
    }
    /* カード風スタイルの調整 */
    .metric-card {
        background-color: #262730;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- タイトル ---
st.title("🏇 JRA 黄金パターン AI")
st.caption("回収率179%超・過小評価馬自動スクリーニング")

# --- サマリー情報（カード風メトリクス） ---
col1, col2 = st.columns(2)
with col1:
    st.metric(label="本日の推奨レース数", value="3レース")
with col2:
    st.metric(label="狙い目ヒット馬", value="3頭", delta="期待度高")

st.markdown("---")

# --- メインコンテンツ（推奨馬リスト） ---
st.subheader("🎯 黄金パターン推奨馬")
st.markdown("<p style='font-size: 0.85rem; color: gray;'>※モデル上位3頭 × 5番人気以下</p>", unsafe_allow_html=True)

# サンプルデータ
sample_data = pd.DataFrame({
    'レース': ['3歳未勝利', '4歳1勝C', 'プロキオンS'],
    '馬名': ['テイエムスパーダ', 'ゴールドバローズ', 'ヤマニンウルス'],
    '予測順位': [1, 2, 1],
    '人気': [6, 7, 2],
    '単勝': [14.2, 18.5, 3.8]
})

# 黄金パターンのハイライト（綺麗に見せる）
def highlight_style(row):
    if row['予測順位'] <= 3 and row['人気'] >= 5:
        return ['background-color: #2d3748; color: #f6e05e; font-weight: bold;'] * len(row)
    else:
        return [''] * len(row)

st.dataframe(sample_data.style.apply(highlight_style, axis=1), width='stretch')

# --- サイドバーもすっきり ---
with st.sidebar:
    st.header("⚙️ 設定")
    min_prob = st.slider("最小予測確率", 0.0, 0.5, 0.10, 0.01)
    max_ninki = st.slider("最大人気", 1, 18, 10, 1)
    st.info("スマホでの操作性を最適化中です。")
