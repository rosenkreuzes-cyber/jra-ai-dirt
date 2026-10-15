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
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="s1_unit")
    
    st.markdown("---")
    st.markdown("### 📊 分析モード")
    analysis_mode = st.selectbox("モード選択", ["LIVE 予測運用", "過去データ検証 (バックテスト)"], key="s1_mode")

# --- 【ステップ1の核心】正しい3連複マルチ（重複なし）生成ロジック ---
def generate_exact_sanrenpuku_mult(axis, others):
    """
    軸1頭と相手複数のリストから、3連複の重複のない正しい組み合わせを生成する。
    例: 軸=4, 相手=[2, 7, 9, 12] の場合、4を含み残りから2頭を選ぶ組み合わせ（計6点）
    """
    bets = []
    # othersの中から2頭を選ぶ組み合わせを生成
    for pair in itertools.combinations(others, 2):
        comb = sorted([axis, pair[0], pair[1]])
        bets.append(f"{comb[0]} - {comb[1]} - {comb[2]}")
    
    # 重複を完全に排除してソート
    return sorted(list(set(bets)))

# --- タブ ---
tab_live, tab_backtest = st.tabs(["🎯 本日の推奨レース (LIVE)", "📈 過去データ検証・シミュレータ"])

with tab_live:
    st.caption("【修正済】3連複マルチの順列重複を解消し、数学的に正しいフォーメーション点数を算出しています。")

    races = [
        {
            "title": "📍 東京 10R - ダート 1600m（秋季ダート条件戦）",
            "day": "📅 10月17日(土) 開催",
            "confidence": "🔥 自信度: ★★★★☆ (勝負)",
            "axis": 4,
            "axis_name": "テイエムスパーダ",
            "pop_rank": 6,
            "idx_rank": 2,
            "others": [2, 7, 9, 12],
            "result_status": "⏳ レース前 / 確定待ち",
            "winning_comb": "-",
            "payout": "-"
        }
    ]

    for r in races:
        # 正しい重複なしの組み合わせを生成
        exact_bets = generate_exact_sanrenpuku_mult(r["axis"], r["others"])
        total_points = len(exact_bets)
        
        st.markdown(f"""
        <div class="race-card">
            <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">{r["day"]}</span>
            <span class="confidence-badge">{r["confidence"]}</span>
            <h3 style="margin-top: 8px;">{r["title"]}</h3>
            <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
                <b>🔥 軸馬:</b> 馬番 <b>{r["axis"]}番 ({r["axis_name"]})</b> (人気:{r["pop_rank"]}番 ⇄ 指数順:{r["idx_rank"]}位)<br>
                <b>🎯 相手選択:</b> 馬番 {r["others"]}<br>
                <b>📌 修正済フォーメーション点数:</b> <span style="color: #68D391; font-weight: bold;">{total_points} 点</span> （投資額: {total_points * bet_unit:,} 円）
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        table_markdown = "| 買い目番号 | 3連複 厳密フォーメーション | 点数 | 備考 |\n|:---:|:---:|:---:|:---:|\n"
        for idx, bet in enumerate(exact_bets, 1):
            table_markdown += f"| **#{idx}** | {bet} | 1点 | 軸{r["axis"]}含む有効ペア |\n"
        
        st.markdown(table_markdown)

with tab_backtest:
    st.markdown("### 🛠️ ステップ1完了報告")
    st.info("まずは【1. 3連複の買い目生成の重複（順列エラー）】を完全になくし、数学的に正しいフォーメーション（軸1頭＋相手4頭＝6点）を出力するようコードを修正しました。\n\n動作をご確認いただき、問題なければ次は **【2. 収支シミュレーション・回収率（ROI）計算モデルの論理修正】**（期待値と払戻金の整合性確保）に進みます。ご指示ください！")
