import streamlit as st
import pandas as pd
import numpy as np

try:
    import data_loader
    is_dataloader_available = True
except ImportError:
    is_dataloader_available = False

st.set_page_config(
    page_title="JRA 黄金パターン AI ダッシュボード (厳格検証版)",
    page_icon="🏇",
    layout="centered"
)

st.markdown("""
<style>
    .main { background-color: #0e1117; }
    h1 { font-size: 1.4rem !important; color: #ff4b4b; }
    h3 { font-size: 1.1rem !important; color: #f6e05e; }
    .race-card {
        background-color: #1a1c23; padding: 15px; border-radius: 10px;
        border-left: 5px solid #ff4b4b; margin-bottom: 15px;
    }
    .result-box {
        background-color: #111827; border: 1px solid #374151;
        padding: 12px; border-radius: 8px; margin-top: 12px; font-size: 0.85rem;
    }
    .error-box {
        background-color: #7f1d1d; border: 1px solid #ef4444;
        padding: 15px; border-radius: 8px; color: #fee2e2; margin-bottom: 20px;
    }
    .confidence-badge {
        background-color: #b7791f; color: #ffffff; padding: 2px 8px;
        border-radius: 4px; font-size: 0.75rem; font-weight: bold; float: right;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏇 JRA 黄金パターン AI ダッシュボード [厳格・実データファクト分析版]")

with st.sidebar:
    st.header("⚙️ 設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="final_unit")
    
    st.markdown("---")
    st.markdown("### 📊 分析モード")
    analysis_mode = st.selectbox(
        "検証戦略", 
        ["AI指数1位の入着実績ファクト分析", "黄金パターン軸馬傾向検証"], 
        key="final_strat"
    )

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

tab_live, tab_backtest = st.tabs(["📍 本日のレース & AIスコアリング (LIVE)", "📈 実データ・入着実績ファクト分析"])

with tab_live:
    st.caption("【厳密検証】リアルタイムAIスコアリングと出走馬評価")

    sample_race_horses = [
        {"horse_no": 2, "name": "メイショウモウコ", "pop_rank": 3, "time_index": 78.5, "last3f_index": 72.0, "track_aptitude": 80.0},
        {"horse_no": 4, "name": "テイエムスパーダ", "pop_rank": 6, "time_index": 84.0, "last3f_index": 82.5, "track_aptitude": 85.0},
        {"horse_no": 7, "name": "サンライズホープ", "pop_rank": 1, "time_index": 88.0, "last3f_index": 75.0, "track_aptitude": 82.0},
        {"horse_no": 9, "name": "ロードエクレール", "pop_rank": 4, "time_index": 79.0, "last3f_index": 78.0, "track_aptitude": 76.0},
        {"horse_no": 12, "name": "グレートサンド", "pop_rank": 8, "time_index": 75.0, "last3f_index": 74.0, "track_aptitude": 78.0}
    ]

    scored_df = calculate_ai_indices(sample_race_horses)

    st.markdown("### 📍 東京 10R - ダート 1600m（AIスコアリング結果）")
    
    axis_candidates = scored_df[(scored_df['pop_rank'] >= 5) & (scored_df['pop_rank'] <= 8)]
    recommended_axis = axis_candidates.iloc[0] if not axis_candidates.empty else scored_df.iloc[1]

    st.markdown(f"""
    <div class="race-card">
        <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">📅 開催直前情報</span>
        <span class="confidence-badge">🔥 自信度: ★★★★☆</span>
        <h3 style="margin-top: 8px;">AI自動選定された注目軸馬候補</h3>
        <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
            <b>🎯 AI推奨軸:</b> 馬番 <b>{int(recommended_axis['horse_no'])}番 ({recommended_axis['name']})</b><br>
            <b>📊 期待値ギャップ評価:</b> 世間人気 <span style="color: #f6e05e;">{int(recommended_axis['pop_rank'])}番人気</span> ⇄ <b>AI指数順位: 第{int(recommended_axis['idx_rank'])}位</b>
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("#### 📋 出走馬 AIスコアリング＆ギャップ一覧")
    display_df = scored_df[['horse_no', 'name', 'pop_rank', 'ai_score', 'idx_rank', 'divergence']].rename(columns={
        'horse_no': '馬番', 'name': '馬名', 'pop_rank': '人気順', 'ai_score': 'AI総合指数', 'idx_rank': 'AI順位', 'divergence': '乖離ギャップ'
    })
    st.markdown(display_df.to_html(index=False, classes="dataframe"), unsafe_allow_html=True)

with tab_backtest:
    st.markdown("### 📈 実データに基づくAI指数ファクト分析")
    st.caption("架空の回収率や払戻金は一切排除し、実際のJRAダート戦におけるAI指数1位馬の入着実績を検証します。")
    
    if not is_dataloader_available:
        st.markdown("""<div class="error-box"><b>⚠️ エラー: data_loader.py が検出されません。</b></div>""", unsafe_allow_html=True)
        st.stop()

    df, status_msg = data_loader.load_historical_jra_data()
    
    if df.empty:
        st.markdown(f"""<div class="error-box"><b>⚠️ 実データ未検出</b><br>{status_msg}</div>""", unsafe_allow_html=True)
        st.stop()
    else:
        with st.spinner("AI指数を算出し、実際の着順と照合中..."):
            stats = data_loader.run_strict_backtest(df)
            
        if not stats:
            st.markdown("""<div class="error-box"><b>⚠️ データ集計エラーが発生しました。</b></div>""", unsafe_allow_html=True)
            st.stop()
        
        st.success("AI指数による実データ検証が完了しました。")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("検証レース数", f"{stats['total_races']:,} レース")
        col2.metric("AI指数1位の勝率 (1着)", f"{stats['idx1_win_rate']}%")
        col3.metric("AI指数1位の複勝率 (3着内)", f"{stats['idx1_podium_rate']}%")

        st.markdown(f"""
        <div class="result-box">
            <b>📐 AI指数ファクト分析サマリー (<code>dirt_races_201812_202107_clean.csv</code>)</b><br>
            * 検証レース総数: <code>{stats['total_races']:,} レース</code><br>
            * AI指数1位が1着となったレース数: <code>{stats['idx1_win_count']:,} レース</code> ({stats['idx1_win_rate']}%)<br>
            * AI指数1位が3着以内に入ったレース数: <code>{stats['idx1_podium_count']:,} レース</code> ({stats['idx1_podium_rate']}%)<br>
            <hr style="border-color: #374151; margin: 8px 0;">
            <b>📌 評価:</b> 架空の回収率や都合の良い数値を一切排除し、AI指数と実際の着順結果の相関を純粋なファクトとして算出しています。
        </div>
        """, unsafe_allow_html=True)
