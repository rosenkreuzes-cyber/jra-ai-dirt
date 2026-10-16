with tab_backtest:
    st.markdown("### 📈 着別・AI指数順位ファクト分析（1〜3着の構成比）")
    st.caption("実際のJRAダート戦において、『1着・2着・3着に入った馬』が、それぞれ事前に算出されたAI指数の何位だったのかを1〜7位まで割合（％）で検証します。")
    
    if not is_dataloader_available:
        st.markdown("""<div class="error-box"><b>⚠️ エラー: data_loader.py が検出されません。</b></div>""", unsafe_allow_html=True)
        st.stop()

    df, status_msg = data_loader.load_historical_jra_data()
    
    if df.empty:
        st.markdown(f"""<div class="error-box"><b>⚠️ 実データ未検出</b><br>{status_msg}</div>""", unsafe_allow_html=True)
        st.stop()
    else:
        with st.spinner("全レースの着順とAI指数順位の相関を集計中..."):
            stats = data_loader.run_strict_backtest(df)
            
        if not stats:
            st.markdown("""<div class="error-box"><b>⚠️ データ集計エラーが発生しました。</b></div>""", unsafe_allow_html=True)
            st.stop()
        
        st.success(f"検証完了（対象: {stats['total_races']:,} レース）")
        
        pcts = stats['percentages']
        
        # テーブルデータ形式に整形
        table_data = []
        for idx_r in range(1, 8):
            table_data.append({
                "AI指数順位": f"AI指数 {idx_r}位",
                "1着馬の該当率": f"{pcts[1][idx_r]} %",
                "2着馬の該当率": f"{pcts[2][idx_r]} %",
                "3着馬の該当率": f"{pcts[3][idx_r]} %"
            })
            
        result_df = pd.DataFrame(table_data)
        
        st.markdown("#### 📊 着順別・AI指数順位の出現割合（ファクト分析マトリクス）")
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        st.markdown(f"""
        <div class="result-box">
            <b>📐 分析サマリー (<code>dirt_races_201812_202107_clean.csv</code>)</b><br>
            * 検証レース総数: <code>{stats['total_races']:,} レース</code><br>
            * <b>読み方:</b> 例えば「1着馬の該当率」のAI指数1位が <code>35.0%</code> であれば、実際に1着になった馬のうち約35%の馬が、事前にAI指数1位に評価されていたことを示します。<br>
            <hr style="border-color: #374151; margin: 8px 0;">
            <b>📌 運用方針:</b> 都合の良い回収率や架空の数値を一切排除し、実際の着順とAI指数の相関関係を純粋なファクトとして可視化しています。
        </div>
        """, unsafe_allow_html=True)
