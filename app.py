import streamlit as st
import pandas as pd
import numpy as np
import os

# ページのレイアウト設定
st.set_page_config(
    page_title="JRA Dirt AI Predictor",
    page_icon="🏇",
    layout="wide"
)

st.title("🏇 JRA ダート予測AI & 黄金パターン抽出ダッシュボード")
st.markdown("モデル予測確率と直前オッズのギャップから、回収率170%超の「過小評価馬」を自動検出します。")

# サイドバー設定
st.sidebar.header("⚙️ 表示フィルター設定")
min_prob = st.sidebar.slider("最小予測確率 (pred_prob)", 0.0, 0.5, 0.10, 0.01)
max_ninki = st.sidebar.slider("最大単勝人気 (ninki)", 1, 18, 10, 1)

st.subheader("🎯 本日の黄金パターン推奨馬（モデル上位3頭 × 5番人気以下）")

# サンプル表示用のデータテーブル（後ほど実際の推論データに差し替え可能）
sample_data = pd.DataFrame({
    'レース名': ['3歳未勝利', '4歳以上1勝クラス', 'プロキオンS(G3)'],
    '馬名': ['テイエムスパーダ', 'ゴールドバローズ', 'ヤマニンウルス'],
    '馬番': [4, 12, 7],
    '予測勝率': [0.245, 0.182, 0.310],
    'モデル順位': [1, 2, 1],
    '単勝人気': [6, 7, 2],
    '単勝オッズ': [14.2, 18.5, 3.8]
})

def highlight_golden_pattern(row):
    if row['モデル順位'] <= 3 and row['単勝人気'] >= 5:
        return ['background-color: #ffffe0'] * len(row)
    else:
        return [''] * len(row)

# 最新の指定方法（width='stretch'）を使用
st.dataframe(sample_data.style.apply(highlight_golden_pattern, axis=1), width='stretch')

st.markdown("---")
st.markdown("📱 このアプリをクラウドに載せることで、スマホのブラウザからいつでも確認できるようになります。")
