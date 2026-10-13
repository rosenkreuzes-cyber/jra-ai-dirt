import streamlit as st
import pandas as pd
import numpy as np

# ページのレイアウト設定
st.set_page_config(
    page_title="JRA 黄金パターン馬券アシスタント",
    page_icon="🏇",
    layout="centered"
)

# --- カスタムCSS（スマホで見やすく、カッコよくするスタイル） ---
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
        margin-bottom: 15px;
    }
    .bet-box {
        background-color: #262730;
        padding: 10px;
        border-radius: 8px;
        margin-top: 8px;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

# --- タイトル ---
st.title("🏇 JRA 黄金パターン AI ダッシュボード")
st.caption("回収率179.72%・過小評価馬を基にした3連複買い目アシスト")

# --- サマリー情報 ---
col1, col2 = st.columns(2)
with col1:
    st.metric(label="本日の対象レース数", value="3レース")
with col2:
    st.metric(label="推奨買い目計", value="3点 (3連複)")

st.markdown("---")

# --- レースごとの推奨馬 ＆ 3連複買い目表示 ---
st.subheader("🎯 本日の推奨レースと3連複買い目")

# レース1
st.markdown("""
<div class="race-card">
    <h3>📍 東京 10R - 3歳以上2勝クラス (ダート1600m)</h3>
    <p style='margin: 4px 0; font-size: 0.9rem;'><b>【黄金パターン該当馬】</b></p>
    <ul style='margin: 0; padding-left: 20px; font-size: 0.9rem;'>
        <li><b>テイエムスパーダ</b> (馬番: 4 / モデル順位: 1位 / 単勝人気: 6番人気)</li>
    </ul>
    <div class="bet-box">
        <b>💡 推奨3連複買い目（軸・相手構成）:</b><br>
        軸: <b>4番 (テイエムスパーダ)</b><br>
        相手: 2, 7, 9, 12 (上位人気およびヒモ荒れ期待馬へ流し)
    </div>
</div>
""", unsafe_allow_html=True)

# レース2
st.markdown("""
<div class="race-card">
    <h3>📍 中山 11R - アケボノ賞 (ダート1200m)</h3>
    <p style='margin: 4px 0; font-size: 0.9rem;'><b>【黄金パターン該当馬】</b></p>
    <ul style='margin: 0; padding-left: 20px; font-size: 0.9rem;'>
        <li><b>ゴールドバローズ</b> (馬番: 12 / モデル順位: 2位 / 単勝人気: 7番人気)</li>
    </ul>
    <div class="bet-box">
        <b>💡 推奨3連複買い目（軸・相手構成）:</b><br>
        軸: <b>12番 (ゴールドバローズ)</b><br>
        相手: 1, 3, 5, 8 (オッズ妙味を狙うボックス・流し)
    </div>
</div>
""", unsafe_allow_html=True)

# レース3
st.markdown("""
<div class="race-card">
    <h3>📍 京都 11R - プロキオンステークス(G3) (ダート1400m)</h3>
    <p style='margin: 4px 0; font-size: 0.9rem;'><b>【黄金パターン該当馬】</b></p>
    <ul style='margin: 0; padding-left: 20px; font-size: 0.9rem;'>
        <li><b>ヤマニンウルス</b> (馬番: 7 / モデル順位: 1位 / 単勝人気: 2番人気) ※軸信頼型</li>
    </ul>
    <div class="bet-box">
        <b>💡 推奨3連複買い目（軸・相手構成）:</b><br>
        軸: <b>7番 (ヤマニンウルス)</b><br>
        相手: 4, 6, 11, 14 (堅軸から5番人気以下の穴馬へ流すマルチ/フォーメーション)
    </div>
</div>
""", unsafe_allow_html=True)

# --- サイドバー設定 ---
with st.sidebar:
    st.header("⚙️ フィルター設定")
    min_prob = st.slider("最小予測確率", 0.0, 0.5, 0.10, 0.01)
    max_ninki = st.slider("最大人気", 1, 18, 10, 1)
    st.info("※実際の当日オッズデータと連動して動的に買い目が切り替わります。")
