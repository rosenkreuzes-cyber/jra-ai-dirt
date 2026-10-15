import streamlit as st
import itertools
import pandas as pd
import numpy as np

try:
    import data_loader
    is_dl_available = True
except ImportError:
    is_dl_available = False

st.set_page_config(
    page_title="JRA 黄金パターン AI 検証エンジン (厳格運用版)",
    page_icon="🏇",
    layout="centered"
)

st.markdown("""
<style>
    .main { background-color: #0e1117; }
    h1 { font-size: 1.4rem !important; color: #ff4b4b; }
    .error-box {
        background-color: #7f1d1d; border: 1px solid #ef4444;
        padding: 15px; border-radius: 8px; color: #fee2e2; margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏇 JRA 黄金パターン AI 検証エンジン [厳格・実データ専用版]")

with st.sidebar:
    st.header("⚙️ 設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100)

tab_live, tab_backtest = st.tabs(["📍 本日のレース (LIVE)", "📈 過去データ検証 (バックテスト)"])

with tab_live:
    st.caption("実データおよびオッズに基づく厳密な買い目生成")
    st.info("現在、直近の公式出走表データとの連携待機中です。")

with tab_backtest:
    st.markdown("### 📈 実データ検証モード（架空シミュレーション完全廃止）")
    
    if not is_dl_available:
        st.markdown("""
        <div class="error-box">
            <b>⚠️ エラー: data_loader.py が検出されません。</b><br>
            実データに基づかない架空の数値表示は、検証の信頼性を損なうため一切行いません。
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    # 実データファイルのロード試行
    df, status_msg = data_loader.load_historical_jra_data()
    
    if df.empty:
        st.markdown(f"""
        <div class="error-box">
            <b>⚠️ 実データ未検出（未検証ステータス）</b><br>
            {status_msg}<br><br>
            <b>【対応方法】</b> JRAの過去実績CSV（<code>jra_historical_data.csv</code>）をリポジトリのルートにアップロードしてください。実データが確認できるまでバックテストおよび回収率の算出・表示は停止されます。
        </div>
        """, unsafe_allow_html=True)
        st.stop()
    else:
        st.success("実データCSVの読み込みに成功しました。実績照合を実行します。")
        # 実データに基づく集計処理へ進む
        results = data_loader.run_strict_backtest(df)
        st.metric("検証レース数", f"{results['total_races']:,} レース")
        st.metric("実測回収率", f"{results['roi']}%")
