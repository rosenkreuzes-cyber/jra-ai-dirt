import streamlit as st
import pandas as pd
import itertools

# ページのレイアウト設定
st.set_page_config(
    page_title="JRA 黄金パターン馬券アシスタント",
    page_icon="🏇",
    layout="centered"
)

# --- カスタムCSS（スマホで見やすいスタイル） ---
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
</style>
""", unsafe_allow_html=True)

# --- タイトル ---
st.title("🏇 JRA 黄金パターン AI ダッシュボード")
st.caption("1頭軸流しフォーメーション（6点買い）専用アシスタント")

# --- 軸1頭・相手4頭から6点（軸-相手A-相手B）の組み合わせを生成する関数 ---
def generate_formation_bets(axis, others):
    combinations = []
    for pair in itertools.combinations(others, 2):
        comb = sorted([pair[0], pair[1]])
        combinations.append(f"{axis} - {comb[0]} - {comb[1]}")
    return combinations

# レースデータの定義（前の2レースは6〜7番人気を軸に設定）
races = [
    {
        "title": "📍 東京 10R - 3歳以上2勝クラス",
        "day": "📅 10月17日(土) 開催",
        "axis": 4,
        "axis_name": "テイエムスパーダ (6番人気)",
        "others": [2, 7, 9, 12],
        "odds_sample": ['45.8倍', '78.2倍', '112.5倍', '65.0倍', '88.4倍', '134.0倍']
    },
    {
        "title": "📍 中山 11R - アケボノ賞",
        "day": "📅 10月17日(土) 開催",
        "axis": 12,
        "axis_name": "ゴールドバローズ (7番人気)",
        "others": [1, 3, 5, 8],
        "odds_sample": ['62.4倍', '89.1倍', '134.6倍', '75.0倍', '98.2倍', '145.0倍']
    },
    {
        "title": "📍 京都 11R - プロキオンステークス(G3)",
        "day": "📅 10月18日(日) 開催",
        "axis": 7,
        "axis_name": "ヤマニンウルス (2番人気)",
        "others": [4, 6, 11, 14],
        "odds_sample": ['18.5倍', '24.2倍', '41.0倍', '22.1倍', '33.4倍', '52.0倍']
    }
]

# --- メインコンテンツ ---
st.subheader("🎯 本日の推奨レース（1頭軸流し 6点買い）")

# サイドバー設定（資金配分）
with st.sidebar:
    st.header("⚙️ 資金配分設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100)
    total_races = len(races)
    total_points = total_races * 6
    st.markdown(f"**1レースあたり:** {6 * bet_unit} 円 (6点)")
    st.markdown(f"**総投資額 (全レース):** {total_points * bet_unit} 円")

# 各レースの表示
for r in races:
    bets = generate_formation_bets(r["axis"], r["others"])
    
    st.markdown(f"""
    <div class="race-card">
        <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold;">{r["day"]}</span>
        <h3 style="margin-top: 8px;">{r["title"]}</h3>
        <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
            <b>🔥 軸馬:</b> 馬番 <b>{r["axis"]}番</b> ({r["axis_name"]})<br>
            <b>🎯 相手:</b> 馬番 {r["others"]} （1頭軸流し 6点買い）
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # 6点の買い目テーブルを作成（余計な式別名やカッコを排除）
    df_bets = pd.DataFrame({
        '買い目': bets,
        '点数': [1] * 6,
        '予測オッズ': r["odds_sample"]
    })
    
    st.dataframe(df_bets, width='stretch', hide_index=True)
    st.markdown("---")
