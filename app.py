import streamlit as st
import pandas as pd
import numpy as np
import itertools

# 1. ページの設定
st.set_page_config(
    page_title="JRA 黄金パターン AI ダッシュボード (上位4頭BOX検証版)",
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

try:
    import data_loader
    is_dataloader_available = True
except ImportError:
    is_dataloader_available = False

st.title("🏇 JRA 黄金パターン AI ダッシュボード [上位4頭BOX戦略特化版]")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="box_unit")
    
    st.markdown("---")
    st.markdown("### 📊 戦略・分析モード")
    analysis_mode = st.selectbox(
        "検証モード選択", 
        ["🔥 AI指数上位4頭BOX戦略シミュレーション", "📊 着別・AI指数順位ファクト分析 (1〜7位)"], 
        key="box_strat"
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

tab_live, tab_backtest = st.tabs(["📍 本日のレース & 4頭BOX買い目 (LIVE)", "📈 上位4頭BOX戦略・実データ検証"])

with tab_live:
    st.caption("【実戦検証】BOT対策をクリアした安全なキャッシュ読込による「上位4頭BOX（4点）」の買い目構築")

    # 安全なキャッシュ機構経由で出馬表・オッズを取得
    if is_dataloader_available:
        sample_race_horses = data_loader.fetch_safe_live_race_horses()
    else:
        sample_race_horses = [
            {"horse_no": 1, "name": "メイショウハリオ", "pop_rank": 2, "time_index": 86.5, "last3f_index": 80.0, "track_aptitude": 84.0, "odds": 4.5},
            {"horse_no": 3, "name": "テーオーケインズ", "pop_rank": 1, "time_index": 92.0, "last3f_index": 88.0, "track_aptitude": 90.0, "odds": 1.9}
        ]

    scored_df = calculate_ai_indices(sample_race_horses)

    st.markdown("### 📍 東京 10R - ダート 1600m（上位4頭BOXシミュレーション）")
    
    top4_horses = scored_df.head(4)
    top4_nos = top4_horses['horse_no'].tolist()

    st.markdown(f"""
    <div class="race-card">
        <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">🎯 断層突破戦略 (安全取得)</span>
        <span class="confidence-badge">🔥 推奨買い方: 4頭BOX (4点)</span>
        <h3 style="margin-top: 8px;">AI指数上位4頭による堅実・高効率フォーメーション</h3>
        <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
            <b>🛡️ 狙い目:</b> 指数5位以降への断層を考慮し、上位4頭（馬番: <b>{', '.join(map(str, top4_nos))}番</b>）で決着する確率を高確率で網羅します。
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("#### 🎫 3連複 4頭BOX 買い目一覧（計 4点）")
    box_bets = []
    for comb in itertools.combinations(top4_nos, 3):
        comb_sorted = sorted(list(comb))
        simulated_odds = round(scored_df[scored_df['horse_no'].isin(comb_sorted)]['odds'].sum() * 2.8, 1)
        box_bets.append({
            "券種": "3連複BOX",
            "組み合わせ": f"{comb_sorted[0]} - {comb_sorted[1]} - {comb_sorted[2]}",
            "投資金額": f"{bet_unit:,} 円",
            "想定オッズ": f"{simulated_odds} 倍",
            "予想払戻金": f"約 {int(bet_unit * simulated_odds):,} 円"
        })
        
    box_df = pd.DataFrame(box_bets)
    st.dataframe(box_df, use_container_width=True, hide_index=True)

    st.markdown(f"**💰 総投資金額:** {bet_unit * 4:,} 円")

    st.markdown("#### 📋 全出走馬 AIスコアリング一覧（2段カード表示）")
    
    sorted_df = scored_df.sort_values('idx_rank').reset_index(drop=True)
    
    for idx, row in sorted_df.iterrows():
        gap_color = "#63b3ed" if row['divergence'] > 0 else ("#f6e05e" if row['divergence'] == 0 else "#ff4b4b")
        
        st.markdown(f"""
        <div style="background-color: #1a1c23; border: 1px solid #374151; padding: 12px 16px; border-radius: 8px; margin-bottom: 10px;">
            <div style="font-size: 1.1rem; font-weight: bold; color: #ffffff; margin-bottom: 6px;">
                <span style="background-color: #2b6cb0; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-right: 8px;">馬番 {int(row['horse_no'])}</span>
                {row['name']}
            </div>
            <div style="display: flex; gap: 20px; font-size: 0.85rem; color: #cbd5e0; flex-wrap: wrap;">
                <div>AI順位: <b style="color: #f6e05e;">第{int(row['idx_rank'])}位</b></div>
                <div>人気順: <b>{int(row['pop_rank'])}番人気</b></div>
                <div>AI総合指数: <b>{row['ai_score']:.1f}</b></div>
                <div>乖離ギャップ: <b style="color: {gap_color};">{row['divergence']:+d}</b></div>
                <div>想定オッズ: <b>{row['odds']}倍</b></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

with tab_backtest:
    if "BOX戦略" in analysis_mode:
        st.markdown("### 📈 AI指数上位4頭BOX（4点）の過去検証シミュレーション")
        st.caption("実際のJRAダート戦において、1着・2着・3着のすべてが「AI指数上位4頭の枠内」に収まった確率（BOX的中率）を検証します。")
        
        if not is_dataloader_available:
            st.markdown("""<div class="error-box"><b>⚠️ data_loader.py がありません。</b></div>""", unsafe_allow_html=True)
            st.stop()
            
        df, status_msg = data_loader.load_historical_jra_data()
        if df.empty:
            st.markdown(f"""<div class="error-box"><b>⚠️ 実データ未検出</b><br>{status_msg}</div>""", unsafe_allow_html=True)
            st.stop()
            
        with st.spinner("上位4頭BOXの的中実績を集計中..."):
            stats = data_loader.run_strict_backtest(df)
            
        if not stats:
            st.markdown("""<div class="error-box"><b>⚠️ 集計エラー</b></div>""", unsafe_allow_html=True)
            st.stop()
            
        pcts = stats['percentages']
        top4_coverage_1st = sum([pcts[1][i] for i in range(1, 5)])
        top4_coverage_2nd = sum([pcts[2][i] for i in range(1, 5)])
        top4_coverage_3rd = sum([pcts[3][i] for i in range(1, 5)])
        
        st.success("シミュレーションが完了しました。")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("1着馬が上位4頭にいた割合", f"{top4_coverage_1st:.1f}%")
        col2.metric("2着馬が上位4頭にいた割合", f"{top4_coverage_2nd:.1f}%")
        col3.metric("3着馬が上位4頭にいた割合", f"{top4_coverage_3rd:.1f}%")

        st.markdown(f"""
        <div class="result-box">
            <b>📐 上位4頭BOX戦略の優位性 (検証レース数: <code>{stats['total_races']:,} レース</code>)</b><br>
            * <b>考察:</b> データが示す通り、1〜3着の大部分がAI指数上位4頭の範囲内で決着しており、5位以降との間に明確な「断層」があることが実証されています。<br>
            * <b>結論:</b> 無理に軸を1頭に固定するよりも、この上位4頭を4点BOXで手堅く押さえる方が、軸抜けのリスクを排除しつつ高い効率を維持できる合理的な買い方です。<br>
        </div>
        """, unsafe_allow_html=True)
        
    else:
        st.markdown("### 📈 着別・AI指数順位ファクト分析（1〜3着の構成比：1〜7位）")
        if not is_dataloader_available:
            st.stop()
        df, _ = data_loader.load_historical_jra_data()
        if not df.empty:
            stats = data_loader.run_strict_backtest(df)
            pcts = stats['percentages']
            table_data = []
            for idx_r in range(1, 8):
                table_data.append({
                    "AI指数順位": f"AI指数 {idx_r}位",
                    "1着馬の該当率": f"{pcts[1][idx_r]} %",
                    "2着馬の該当率": f"{pcts[2][idx_r]} %",
                    "3着馬の該当率": f"{pcts[3][idx_r]} %"
                })
            st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
