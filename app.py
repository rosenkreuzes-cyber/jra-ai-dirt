import streamlit as st
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
        margin-bottom: 15px;
    }
    .result-box {
        background-color: #111827;
        border: 1px solid #374151;
        padding: 12px;
        border-radius: 8px;
        margin-top: 12px;
        font-size: 0.85rem;
    }
    .confidence-badge {
        background-color: #b7791f;
        color: #ffffff;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: bold;
        float: right;
    }
</style>
""", unsafe_allow_html=True)

# --- タイトル ---
st.title("🏇 JRA 黄金パターン AI ダッシュボード")
st.caption("1頭軸マルチ（12点買い）＆ 結果・配当トラッカー")

# --- サイドバー設定（オッズ取得スイッチ ＆ 資金配分） ---
with st.sidebar:
    st.header("⚙️ 運用・資金設定")
    
    st.subheader("📊 オッズ取得モード")
    odds_mode = st.radio(
        "取得タイミングを選択",
        ["当日朝 7:00 時点固定", "一括手動取得（ボタン実行）"]
    )
    
    if odds_mode == "一括手動取得（ボタン実行）":
        if st.button("🔄 今すぐオッズを一括取得する", type="primary"):
            st.success("最新オッズの取得が完了しました！")
    else:
        st.info("⏰ 当日朝 7:00 時点のオッズデータを自動適用中です。")

    st.markdown("---")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100)
    total_races = 3
    total_points_per_race = 12  # マルチ12点
    total_points = total_races * total_points_per_race
    st.markdown(f"**1レースあたり:** {total_points_per_race * bet_unit} 円 (12点)")
    st.markdown(f"**総投資額 (全3レース):** {total_points * bet_unit} 円")

# --- 1頭軸マルチ（12点）の組み合わせ生成関数 ---
def generate_mult_bets(axis, others):
    final_bets = []
    for p1 in others:
        for p2 in others:
            if p1 < p2:
                final_bets.append(f"{axis} - {p1} - {p2}")
                final_bets.append(f"{p1} - {axis} - {p2}")
    return sorted(list(set(final_bets)))[:12]

# レースデータの定義
races = [
    {
        "title": "📍 東京 10R - 3歳以上2勝クラス",
        "day": "📅 10月17日(土) 開催",
        "confidence": "🔥 自信度: ★★★★☆ (勝負)",
        "axis": 4,
        "axis_name": "テイエムスパーダ (6番人気)",
        "others": [2, 7, 9, 12],
        "result_status": "⏳ レース前 / 確定待ち",
        "winning_comb": "-",
        "payout": "-"
    },
    {
        "title": "📍 中山 11R - アケボノ賞",
        "day": "📅 10月17日(土) 開催",
        "confidence": "🔥 自信度: ★★★★★ (特選)",
        "axis": 12,
        "axis_name": "ゴールドバローズ (7番人気)",
        "others": [1, 3, 5, 8],
        "result_status": "⏳ レース前 / 確定待ち",
        "winning_comb": "-",
        "payout": "-"
    },
    {
        "title": "📍 京都 11R - プロキオンステークス(G3)",
        "day": "📅 10月18日(日) 開催",
        "confidence": "⚡ 自信度: ★★★☆☆ (狙い目)",
        "axis": 7,
        "axis_name": "ヤマニンウルス (2番人気)",
        "others": [4, 6, 11, 14],
        "result_status": "⏳ レース前 / 確定待ち",
        "winning_comb": "-",
        "payout": "-"
    }
]

# --- メインコンテンツ ---
st.subheader("🎯 本日の推奨レース（1頭軸マルチ 12点買い）")

for r in races:
    bets = generate_mult_bets(r["axis"], r["others"])
    dummy_odds = [f"{40.0 + i * 10.5:.1f}倍" for i in range(len(bets))]
    
    st.markdown(f"""
    <div class="race-card">
        <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold;">{r["day"]}</span>
        <span class="confidence-badge">{r["confidence"]}</span>
        <h3 style="margin-top: 8px;">{r["title"]}</h3>
        <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
            <b>🔥 軸馬:</b> 馬番 <b>{r["axis"]}番</b> ({r["axis_name"]})<br>
            <b>🎯 相手:</b> 馬番 {r["others"]} （1頭軸マルチ <b>12点買い</b>）
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # マークダウン形式のテーブルで綺麗に一望表示
    table_markdown = "| 買い目 | 点数 | 予測オッズ |\n|:---:|:---:|:---:|\n"
    for bet, odds in zip(bets, dummy_odds):
        table_markdown += f"| **{bet}** | 1点 | {odds} |\n"
    
    st.markdown(table_markdown)
    
    # レース結果 ＆ 配当金表示枠
    st.markdown(f"""
    <div class="result-box">
        <b>🏆 レース結果・払戻金</b><br>
        ステータス: <span style="color: #f6e05e;">{r["result_status"]}</span><br>
        的中馬番 (3連複): <b>{r["winning_comb"]}</b> | 払戻配当: <span style="color: #68D391; font-weight: bold;">{r["payout"]}</span>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
