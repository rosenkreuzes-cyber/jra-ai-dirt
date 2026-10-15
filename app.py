"""JRA ダート分析 / 実データCSV版. Run: streamlit run app.py"""
import io
import pandas as pd
import numpy as np
import streamlit as st
from core import (FEATURES,HIST_REQUIRED,UPCOMING_REQUIRED,ODDS_REQUIRED,PAYOUT_REQUIRED,
                  validate,select_features,fit_model,predict,build_tickets,backtest)

st.set_page_config(page_title='JRA ダートAI 実データ分析',page_icon='🏇',layout='wide')
st.title('🏇 JRA ダートAI 実データ分析')
st.caption('実測CSVのみ使用｜過去データで学習 → 未使用期間で検証｜3連複は重複なし')
st.warning('このアプリは自動でJRAのデータを取得しません。架空の的中率・オッズ・払戻は表示しません。AI指数と3連複確率は推定値であり、利益を保証しません。')

with st.expander('CSV仕様・データ作成時の注意（必読）',expanded=False):
    st.markdown('''**過去レースCSV**: race_id, race_date (YYYY-MM-DD), horse_no, horse_name, surface (dirt), finish、およびレース前に確定している特徴量。1行=1頭。全出走馬を収録。取消・中止等は除外し、各レースの1着馬を1頭にしてください。\n
**予測対象CSV**: 過去レースCSVから finish を除いた形式。\n
**3連複オッズCSV**: race_id,horse1,horse2,horse3,trio_odds。オッズは倍率（例 25.6）、購入判断時点のスナップショットを使用。\n
**払戻CSV**: race_id,horse1,horse2,horse3,trio_payout_100。JRAの3連複100円あたり払戻金（円）。各レースの的中組1行。\n
**特徴量**: past_speed（過去走のみの速度指数）、past_finish_avg（過去着順平均）、past_last3f（過去上がり3F）、distance_fit（距離適性）、track_fit（コース適性）、going_fit（馬場適性）、early_pace（先行力）、rest_days（休養日数）、draw（枠番）、carried_weight（斤量）。単位・算出期間はCSV全体で統一してください。\n
**重要**: 特徴量は必ず対象レース発走前に得られる情報から作成。対象レースの確定着順・走破時計・払戻・確定オッズを特徴量に混ぜないでください。オッズCSVも購入時点の記録が必要です。''')
    hist_cols=HIST_REQUIRED+FEATURES
    samples=[('過去レース_テンプレート.csv',hist_cols),('予測対象_テンプレート.csv',UPCOMING_REQUIRED+FEATURES),('3連複オッズ_テンプレート.csv',ODDS_REQUIRED),('3連複払戻_テンプレート.csv',PAYOUT_REQUIRED)]
    for filename,cols in samples:
        st.download_button(filename,pd.DataFrame(columns=cols).to_csv(index=False).encode('utf-8-sig'),filename,mime='text/csv',key=filename)

def upload(label,key):
    file=st.file_uploader(label,type='csv',key=key)
    if file is None: return None
    try:
        return pd.read_csv(file,encoding='utf-8-sig',dtype={'race_id':str})
    except Exception as e:
        st.error(f'{label}: CSV読み込み失敗: {e}')
        return None

with st.sidebar:
    st.header('⚙️ 分析設定')
    stake=st.number_input('1点の購入金額（円）',min_value=100,max_value=10000,value=100,step=100)
    axis_rank=st.selectbox('軸馬 AI順位',[1,2,3,4,5],index=0)
    other_count=st.slider('相手頭数',2,8,4)
    min_ev=st.slider('期待ROI下限（例 0.1 = +10%）',-0.5,2.0,0.0,0.05)
    n_sim=st.select_slider('3連複確率シミュレーション回数',[5000,10000,30000,60000],value=30000)
    train_ratio=st.slider('バックテスト学習期間の比率',0.5,0.9,0.7,0.05)

st.subheader('1. データを読み込む')
c1,c2=st.columns(2)
with c1:
    history=upload('過去レース（学習・検証用）','history')
    upcoming=upload('予測対象レース（任意）','upcoming')
with c2:
    odds=upload('3連複オッズ（任意・期待値判定に必要）','odds')
    payouts=upload('過去の3連複払戻（バックテストに必要）','payouts')

try:
    if history is not None: history=validate(history,HIST_REQUIRED,'過去レース')
    if upcoming is not None: upcoming=validate(upcoming,UPCOMING_REQUIRED,'予測対象')
    if odds is not None:
        odds=validate(odds,ODDS_REQUIRED,'オッズ')
        odds['trio_odds']=pd.to_numeric(odds['trio_odds'],errors='coerce')
        if odds['trio_odds'].isna().any() or (odds['trio_odds']<=0).any(): raise ValueError('trio_oddsは正の数値で入力してください')
    if payouts is not None:
        payouts=validate(payouts,PAYOUT_REQUIRED,'払戻')
        payouts['trio_payout_100']=pd.to_numeric(payouts['trio_payout_100'],errors='coerce')
        if payouts['trio_payout_100'].isna().any() or (payouts['trio_payout_100']<0).any(): raise ValueError('trio_payout_100は0以上の数値で入力してください')
except Exception as e:
    st.error(f'データ検証エラー: {e}')
    st.stop()

live, bt = st.tabs(['🎯 予測・買い目','📈 実績バックテスト'])
with live:
    if history is None or upcoming is None:
        st.info('過去レースCSVと予測対象CSVをアップロードしてください。')
    elif st.button('AI学習・予測を実行',type='primary'):
        try:
            # Avoid training on data from prediction date or later.
            cutoff=upcoming['race_date'].min()
            train=history[history['race_date']<cutoff].copy()
            if train.empty: raise ValueError('予測日より前の学習レースがありません')
            features=select_features(train,upcoming)
            model=fit_model(train,features)
            preds=predict(model,upcoming,features)
            st.success(f'学習: {train.race_id.nunique()}レース / 使用特徴量: {", ".join(features)}')
            for rid,race in preds.groupby('race_id',sort=False):
                st.markdown(f'#### レース {rid} ({race.race_date.iloc[0].date()})')
                st.dataframe(race[['horse_no','horse_name','ai_index','ai_rank','win_share']].sort_values('ai_rank').rename(columns={'horse_no':'馬番','horse_name':'馬名','ai_index':'AI指数','ai_rank':'指数順位','win_share':'モデル内勝率シェア'}),hide_index=True,use_container_width=True)
                tickets=build_tickets(race,odds,axis_rank,other_count,min_ev,n_sim)
                if tickets.empty:
                    st.warning('出走頭数不足のため3連複を生成できません。')
                    continue
                st.dataframe(tickets[['買い目','推定的中確率','3連複オッズ','推定期待ROI','購入候補']],hide_index=True,use_container_width=True)
                if odds is None or tickets['3連複オッズ'].notna().sum()==0:
                    st.info('購入時点の3連複オッズがないため期待値判定・購入候補は表示できません。')
                elif tickets['3連複オッズ'].isna().any():
                    st.warning('一部の買い目にオッズがなく、期待値判定から除外されています。')
                selected=tickets[tickets['購入候補']]
                st.write(f'期待値条件を満たす買い目: {len(selected)}点 / 想定投資: {len(selected)*stake:,}円')
                st.download_button(f'{rid} 買い目CSV',tickets.to_csv(index=False).encode('utf-8-sig'),f'tickets_{rid}.csv',key=f'live_{rid}')
        except Exception as e:
            st.error(f'予測失敗: {e}')
with bt:
    st.caption('日付で学習期間と未使用の検証期間を分離します。検証データの着順をモデルの特徴量には使いません。')
    if history is None or payouts is None:
        st.info('過去レースCSVと確定払戻CSVをアップロードしてください。')
    elif st.button('実績バックテストを実行',type='primary'):
        try:
            if odds is None:
                st.warning('過去オッズがないため期待値による選別はせず、軸・相手の固定ルールで全買い目を検証します。')
            preds,bets,stats=backtest(history,payouts,odds,train_ratio,stake,axis_rank,other_count,min_ev,min(n_sim,30000))
            st.write(f'検証期間の開始日: {stats["学習最終日"]}（この日以降を検証）')
            cols=st.columns(4)
            cols[0].metric('検証レース数',stats['検証レース数'])
            cols[1].metric('購入点数',stats['購入点数'])
            cols[2].metric('回収率',f'{stats["回収率"]:.1f}%' if pd.notna(stats['回収率']) else '算出不可')
            cols[3].metric('レース的中率',f'{stats["的中率"]:.1f}%' if pd.notna(stats['的中率']) else '算出不可')
            st.write(f'投資: {stats["投資額"]:,.0f}円 / 払戻: {stats["払戻額"]:,.0f}円 / 損益: {stats["払戻額"]-stats["投資額"]:,.0f}円 / 最大DD: {stats["最大DD"]:,.0f}円' if pd.notna(stats['最大DD']) else '購入対象なし：収支・最大DDは算出できません。')
            if not bets.empty:
                st.line_chart(bets.set_index('race_date')['累積損益'])
                st.dataframe(bets,hide_index=True,use_container_width=True)
                st.download_button('バックテスト明細をダウンロード',bets.to_csv(index=False).encode('utf-8-sig'),'backtest_result.csv')
            st.info('注意：3連複確率はPlackett–Luce近似で、未校正です。表示された期待値は確定的な優位性を示しません。期間を一度分けるだけの検証であり、運用前には時系列ウォークフォワード検証が必要です。')
        except Exception as e:
            st.error(f'バックテスト失敗: {e}')
