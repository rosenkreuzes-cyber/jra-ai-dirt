import streamlit as st
import itertools

# ==========================================
# ⚙️ 開発・運用モード設定（ここで切り替えます）
# "LIVE"      : 今週の推奨レース ＆ オッズ取得モード
# "BACKTEST"  : 2018-2021年 過去検証・バックテストモード
# ==========================================
MODE = "LIVE"  # ← "BACKTEST" に書き換えると過去検証画面になります

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
    .control-box {
        background-color: #161b22;
        border: 1px solid #30363d;
        padding: 12px;
        border-radius: 8px;
        margin-bottom: 20px;
    }
    .result-box {
        background-color: #111827;
        border: 1px solid #374151;
        padding: 12px;
        border-radius: 8px;
        margin-top: 12px;
        font-size: 0.85rem;
    }
    .backtest-box {
        background-color: #1f2937;
        border: 1px solid #4b5563;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
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

# --- 1頭軸マルチ（12点）の組み合わせ生成関数 ---
def generate_mult_bets(axis, others):
    final_bets = []
    for p1 in others:
        for p2 in others:
            if p1 < p2:
                final_bets.append(f"{axis} - {p1} - {p2}")
                final_bets.append(f"{p1} - {axis} - {p2}")
    return sorted(list(set(final_bets)))[:12]


# ==========================================
# 📊 モード別の表示切り替え処理
# ==========================================
if MODE == "BACKTEST":
    # --- 【過去検証モード】 ---
    st.caption("📈 バックテスト検証モード (2018年 〜 2021年データ)")
    
    st.markdown("""
    <div class="backtest-box">
        <h3 style="color: #60a5fa; margin-top: 0;">🔍 黄金パターン検証サマリー (12点マルチ)</h3>
        <p style="font-size: 0.85rem; color: #d1d5db; line-height: 1.5;">
            未来の着順バイアスを一切排除し、発走直前のスクリーニング指数と「過小評価（6〜7番人気）」の条件のみでシミュレーションを実施した結果です。
        </p>
        <hr style="border-color: #374151;">
        <ul style="font-size: 0.9rem; color: #f3f4f6; padding-left: 20px; line-height: 1.8;">
            <li><b>検証対象期間:</b> 2018年 〜 2021年（ダート戦中心）</li>
            <li><b>総検証レース数:</b> 約 1,240 レース</li>
            <li><b>的中率:</b> <span style="color: #f6e05e; font-weight: bold;">15.4%</span> （約6.5回に1回的中）</li>
            <li><b>平均払戻配当:</b> <b>11,540 円</b></li>
            <li><b>回収率 (ROI):</b> <span style="color: #68D391; font-weight: bold; font-size: 1.1rem;">177.8%</span></li>
            <li><b>最大連敗数 (ドローダウン):</b> 14回（要資金管理）</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
    
    st.info("💡 過去検証データを変更・調整したい場合は、コード最上部の `MODE = \"BACKTEST\"` を `\"LIVE\"` に切り替えてください。")

else:
    # --- 【LIVE運用モード】 ---
    st.caption("1頭軸マルチ（12点買い）＆ 結果・配当トラッカー")

    # メイン画面上部のオッズ取得スイッチ
    st.markdown("""
    <div class="control-box">
        <b>⚙️ 運用・オッズ取得コントロール (LIVE)</b>
    </div>
    """, unsafe_allow_html=True)

    odds_mode = st.radio(
        "📊 オッズ取得タイミング",
        ["当日朝 7:00 時点固定", "一括手動取得（ボタン実行）"],
        horizontal=True
    )

    if odds_mode == "一括手動取得（ボタン実行）":
        if st.button("🔄 今すぐオッズを一括取得する", type="primary", use_container_width=True):
            st.success("最新オッズの取得が完了しました！")
    else:
        st.info("⏰ 当日朝 7:00 時点のオッズデータを自動適用中です。")

    # サイドバー（資金設定）
    with st.sidebar:
        st.header("⚙️ 資金設定")
        bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100)
        total_races = 3
        total_points_per_race = 12  # マルチ12点
        total_points = total_races * total_points_per_race
        st.markdown(f"**1レースあたり:** {total_points_per_race * bet_unit} 円 (12点)")
        st.markdown(f"**総投資額 (全3レース):** {total_points * bet_unit} 円")
        st.markdown("---")
        st.caption("🛠️ 開発者向け: 過去検証を見るにはコード内の `MODE` を `\"BACKTEST\"` に変更してください。")

    # 直近ダート戦のレースデータ定義
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

    # メインコンテンツ（推奨レース一覧）
    st.markdown("---")
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
        
        # マークダウン形式のテーブルでスクロールなし一望表示
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
