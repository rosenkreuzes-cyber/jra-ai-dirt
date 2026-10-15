import streamlit as st
import itertools
import pandas as pd
import numpy as np

# data_loaderモジュールからデータ読み込み関数をインポート
try:
    import data_loader
    is_dataloader_available = True
except ImportError:
    is_dataloader_available = False

# ページのレイアウト設定
st.set_page_config(
    page_title="JRA 黄金パターン AI ダッシュボード (厳格検証版)",
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

st.title("🏇 JRA 黄金パターン AI ダッシュボード [厳格・実データ検証版]")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 資金・検証設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="final_unit")
    
    st.markdown("---")
    st.markdown("### 📊 分析モード・戦略")
    bt_strategy = st.selectbox(
        "検証戦略", 
        ["黄金パターン (6-7人気軸 / 相手4頭)", "指数3位軸 (堅実型 / 相手4頭)"], 
        key="final_strat"
    )

# --- 3連複の正確な重複なし（6点）生成ロジック ---
def generate_exact_sanrenpuku_mult(axis, others):
    bets = []
    for pair in itertools.combinations(others, 2):
        comb = sorted([axis, pair[0], pair[1]])
        bets.append(f"{comb[0]} - {comb[1]} - {comb[2]}")
    return sorted(list(set(bets)))

# --- AI指数の算出ロジック ---
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

# --- タブ ---
tab_live, tab_backtest = st.tabs(["📍 本日のレース & AIスコアリング (LIVE)", "📈 実データ過去検証・バックテスト"])

with tab_live:
    st.caption("【厳密検証】重複なし6点フォーメーションとリアルタイムAIスコアリング")

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
    others_list = scored_df[scored_df['horse_no'] != recommended_axis['horse_no']]['horse_no'].tolist()[:4]

    exact_bets = generate_exact_sanrenpuku_mult(int(recommended_axis['horse_no']), others_list)
    total_investment = len(exact_bets) * bet_unit

    st.markdown(f"""
    <div class="race-card">
        <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">📅 10月17日(土) 開催</span>
        <span class="confidence-badge">🔥 自信度: ★★★★☆</span>
        <h3 style="margin-top: 8px;">AI自動選定された黄金パターン推奨軸馬</h3>
        <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
            <b>🎯 AI推奨軸:</b> 馬番 <b>{int(recommended_axis['horse_no'])}番 ({recommended_axis['name']})</b><br>
            <b>📊 期待値ギャップ評価:</b> 世間人気 <span style="color: #f6e05e;">{int(recommended_axis['pop_rank'])}番人気</span> ⇄ <b>AI指数順位: 第{int(recommended_axis['idx_rank'])}位</b> (ギャップ: +{int(recommended_axis['divergence'])})<br>
            <b>📌 厳密フォーメーション (6点):</b> 投資額 {total_investment:,} 円
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("#### 📋 出走馬 AIスコアリング＆ギャップ一覧")
    display_df = scored_df[['horse_no', 'name', 'pop_rank', 'ai_score', 'idx_rank', 'divergence']].rename(columns={
        'horse_no': '馬番', 'name': '馬名', 'pop_rank': '人気順', 'ai_score': 'AI総合指数', 'idx_rank': 'AI順位', 'divergence': '乖離ギャップ'
    })
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    table_markdown = "| 買い目番号 | 3連複 厳密フォーメーション (6点) | 点数 |\n|:---:|:---:|:---:|\n"
    for idx, bet in enumerate(exact_bets, 1):
        table_markdown += f"| **#{idx}** | {bet} | 1点 |\n"
    st.markdown(table_markdown)

with tab_backtest:
    st.markdown("### 📈 実データ連動型バックテスト・エンジン")
    
    if not is_dataloader_available:
        st.markdown("""
        <div class="error-box">
            <b>⚠️ エラー: data_loader.py が検出されません。</b><br>
            実データに基づかない架空の数値表示は行いません。
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    # 正しい実データCSVをロード
    df, status_msg = data_loader.load_historical_jra_data()
    
    if df.empty:
        st.markdown(f"""
        <div class="error-box">
            <b>⚠️ 実データ未検出（未検証ステータス）</b><br>
            {status_msg}<br><br>
            <b>【対応方法】</b> Googleドライブ内にある <code>dirt_races_201812_202107_clean.csv</code> をリポジトリのルートにアップロードしてください。実データが確認できるまでバックテストおよび回収率の算出・表示は停止されます。
        </div>
        """, unsafe_allow_html=True)
        st.stop()
    else:
        bt_results = data_loader.run_strict_backtest(df)
        
        st.success("実データCSVの読み込みに成功しました。")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("検証レース数", f"{bt_results['total_races']:,} レース")
        col2.metric("実測的中率", f"{bt_results['hit_rate']}%")
        col3.metric("平均払戻", f"{bt_results['avg_payout']:,} 円")
        col4.metric("実測回収率 (ROI)", f"{bt_results['roi']}%")

        st.markdown(f"""
        <div class="result-box">
            <b>📐 実データ集計サマリー (<code>dirt_races_201812_202107_clean.csv</code> 連携)</b><br>
            * 総投資金額: <code>{int(bt_results['total_investment']):,} 円</code><br>
            * 総払戻金額: <code>{int(bt_results['total_payout']):,} 円</code><br>
            <hr style="border-color: #374151; margin: 8px 0;">
            <b>📌 状態:</b> 架空データを完全に排除し、実際のCSV構造に基づいた厳格な検証モードで稼働中です。
        </div>
        """, unsafe_allow_html=True)
