"""JRA dirt analysis: pre-race features, out-of-sample evaluation, trio pricing."""
from __future__ import annotations
import hashlib
import itertools
import math
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

FEATURES = ['past_speed','past_finish_avg','past_last3f','distance_fit','track_fit','going_fit','early_pace','rest_days','draw','carried_weight']
HIST_REQUIRED = ['race_id','race_date','horse_no','horse_name','surface','finish']
UPCOMING_REQUIRED = ['race_id','race_date','horse_no','horse_name','surface']
ODDS_REQUIRED = ['race_id','horse1','horse2','horse3','trio_odds']
PAYOUT_REQUIRED = ['race_id','horse1','horse2','horse3','trio_payout_100']
FORBIDDEN = ('finish','result','payout','return','prize','post_race','final_time','actual_','確定','着順','払戻')

def validate(df, required, name):
    missing = [x for x in required if x not in df.columns]
    if missing: raise ValueError(f'{name}: 必須列がありません: {missing}')
    d = df.copy()
    d['race_id'] = d['race_id'].astype(str).str.strip()
    if 'race_date' in d:
        d['race_date'] = pd.to_datetime(d['race_date'], errors='coerce')
        if d['race_date'].isna().any(): raise ValueError(f'{name}: race_dateに不正な日付があります')
    if 'horse_no' in d:
        d['horse_no'] = pd.to_numeric(d['horse_no'], errors='coerce')
        if d['horse_no'].isna().any() or (d['horse_no'] <= 0).any(): raise ValueError(f'{name}: horse_noが不正です')
        d['horse_no'] = d['horse_no'].astype(int)
        if d.duplicated(['race_id','horse_no']).any(): raise ValueError(f'{name}: 同一レースに馬番の重複があります')
    for col in ('horse1','horse2','horse3'):
        if col in d:
            d[col] = pd.to_numeric(d[col], errors='coerce')
            if d[col].isna().any(): raise ValueError(f'{name}: {col}に不正値があります')
            d[col] = d[col].astype(int)
    if all(x in d for x in ('horse1','horse2','horse3')):
        if ((d['horse1']==d['horse2']) | (d['horse1']==d['horse3']) | (d['horse2']==d['horse3'])).any():
            raise ValueError(f'{name}: 3連複の馬番が重複しています')
        d[['horse1','horse2','horse3']] = np.sort(d[['horse1','horse2','horse3']].to_numpy(),axis=1)
        if d.duplicated(['race_id','horse1','horse2','horse3']).any(): raise ValueError(f'{name}: 同一買い目が重複しています')
    if 'surface' in d:
        d = d[d['surface'].astype(str).str.lower().isin(['dirt','ダート'])].copy()
    if 'finish' in d:
        d['finish'] = pd.to_numeric(d['finish'],errors='coerce')
        if d['finish'].isna().any() or (d['finish'] < 1).any(): raise ValueError('finishには確定着順の正整数が必要です（取消・中止は除外してください）')
        if (d.groupby('race_id')['finish'].apply(lambda s:(s==1).sum())!=1).any():
            raise ValueError('各レースに1着馬がちょうど1頭必要です')
    for c in FEATURES:
        if c in d:
            d[c] = pd.to_numeric(d[c],errors='coerce')
    return d

def select_features(train, predict):
    available = [c for c in FEATURES if c in train and c in predict and train[c].notna().any()]
    if not available: raise ValueError('利用可能なレース前特徴量がありません。テンプレートの特徴量列を入力してください')
    return available

def fit_model(train, features):
    if len(train['race_id'].unique()) < 10: raise ValueError('学習用レースが10件未満です。十分な実データを用意してください')
    y = (train['finish']==1).astype(int)
    if y.nunique()!=2: raise ValueError('学習データの1着ラベルに両クラスが必要です')
    model = make_pipeline(SimpleImputer(strategy='median',add_indicator=False),StandardScaler(),LogisticRegression(max_iter=2000,class_weight=None))
    model.fit(train[features],y)
    return model

def predict(model, data, features):
    d = data.copy()
    # Binary win model outputs a strength proxy; within-race normalization is not calibrated win probability.
    strength = np.clip(model.predict_proba(d[features])[:,1],1e-7,1-1e-7)
    d['strength'] = strength
    d['win_share'] = d['strength'] / d.groupby('race_id')['strength'].transform('sum')
    d['ai_index'] = (100 * d['win_share'] / d.groupby('race_id')['win_share'].transform('max')).round(1)
    d['ai_rank'] = d.groupby('race_id')['win_share'].rank(ascending=False,method='min').astype(int)
    return d

def trio_bets(axis, others):
    a = int(axis)
    clean = sorted(set(map(int,others))-{a})
    return sorted(tuple(sorted((a,x,y))) for x,y in itertools.combinations(clean,2))

def trio_probs(race, n_sim=30000, seed=42):
    """Approximate unordered top-3 probabilities under Plackett-Luce ranking model."""
    if len(race)<3: return {}
    nums = race['horse_no'].astype(int).to_numpy()
    weights = race['win_share'].to_numpy(dtype=float)
    weights = np.maximum(weights,1e-12)
    rng = np.random.default_rng(seed)
    # Gumbel top-k is equivalent to Plackett-Luce sampling.
    scores = np.log(weights)[None,:] + rng.gumbel(size=(n_sim,len(nums)))
    top = np.argpartition(scores,-3,axis=1)[:,-3:]
    triples = np.sort(nums[top],axis=1)
    keys,counts = np.unique(triples,axis=0,return_counts=True)
    return {tuple(map(int,k)):float(v/n_sim) for k,v in zip(keys,counts)}

def seed_for(race_id):
    return int.from_bytes(hashlib.sha256(str(race_id).encode()).digest()[:4],'big')

def odds_map(odds, race_id):
    if odds is None or odds.empty: return {}
    subset = odds[odds['race_id']==str(race_id)]
    return {(int(r.horse1),int(r.horse2),int(r.horse3)):float(r.trio_odds) for r in subset.itertuples()}

def build_tickets(race, odds=None, axis_rank=1, other_count=4, min_ev=0.0, n_sim=30000):
    race = race.sort_values(['ai_rank','horse_no'])
    if len(race)<3: return pd.DataFrame()
    axis = int(race.iloc[min(axis_rank-1,len(race)-1)]['horse_no'])
    others = race.loc[race['horse_no']!=axis].head(other_count)['horse_no'].tolist()
    combos = trio_bets(axis,others)
    probs = trio_probs(race,n_sim=n_sim,seed=seed_for(race.iloc[0]['race_id']))
    lookup = odds_map(odds,race.iloc[0]['race_id'])
    rows=[]
    for combo in combos:
        odd=lookup.get(combo,np.nan)
        prob=probs.get(combo,0.)
        ev=prob*odd-1 if np.isfinite(odd) and odd>0 else np.nan
        rows.append({'race_id':str(race.iloc[0]['race_id']),'買い目':'-'.join(map(str,combo)),'horse1':combo[0],'horse2':combo[1],'horse3':combo[2], '推定的中確率':prob,'3連複オッズ':odd,'推定期待ROI':ev,'購入候補':bool(np.isfinite(ev) and ev>=min_ev)})
    return pd.DataFrame(rows)

def backtest(historical, payouts, odds=None, train_ratio=.7, stake=100, axis_rank=1, other_count=4, min_ev=0., n_sim=5000):
    hist = validate(historical,HIST_REQUIRED,'過去レース')
    pay = validate(payouts,PAYOUT_REQUIRED,'払戻')
    if odds is not None: odds=validate(odds,ODDS_REQUIRED,'オッズ')
    dates = hist[['race_id','race_date']].drop_duplicates().sort_values(['race_date','race_id'])
    if len(dates)<15: raise ValueError('最低15レースが必要です')
    # Entire dates separated: no same-day train/test leakage.
    unique_dates = sorted(dates['race_date'].unique())
    if len(unique_dates)<2: raise ValueError('学習・検証用に異なる日付が必要です')
    split=max(1,min(len(unique_dates)-1,int(len(unique_dates)*train_ratio)))
    cutoff=unique_dates[split]
    train=hist[hist['race_date']<cutoff]
    test=hist[hist['race_date']>=cutoff]
    features=select_features(train,test)
    model=fit_model(train,features)
    predicted=predict(model,test,features)
    missing=set(test['race_id'])-set(pay['race_id'])
    if missing: raise ValueError(f'検証期間の払戻データが不足しています: {len(missing)}レース。未収録レースを0円払戻として扱いません')
    paylookup={(str(r.race_id),int(r.horse1),int(r.horse2),int(r.horse3)):float(r.trio_payout_100) for r in pay.itertuples()}
    tickets=[]
    for rid,race in predicted.groupby('race_id',sort=False):
        selected=build_tickets(race,odds,axis_rank,other_count,min_ev,n_sim)
        if selected.empty: continue
        # Without historical odds, evaluate all generated tickets as a fixed strategy; EV filtering is unavailable.
        if odds is not None:
            selected=selected[selected['購入候補']].copy()
        for _,r in selected.iterrows():
            combo=(str(rid),int(r['horse1']),int(r['horse2']),int(r['horse3']))
            if combo not in paylookup and str(rid) not in set(pay['race_id']):
                continue # no certified result for this race
            payout=paylookup.get(combo,0)*stake/100
            tickets.append({'race_id':str(rid),'race_date':race['race_date'].iloc[0], '買い目':r['買い目'],'投資':stake,'払戻':payout,'損益':payout-stake,'推定期待ROI':r['推定期待ROI']})
    bets=pd.DataFrame(tickets)
    if bets.empty: return predicted,bets,{'検証レース数':test['race_id'].nunique(),'購入点数':0,'投資額':0,'払戻額':0,'回収率':np.nan,'的中率':np.nan,'最大DD':np.nan,'学習最終日':str(pd.Timestamp(cutoff).date())}
    bets=bets.sort_values(['race_date','race_id','買い目']).reset_index(drop=True)
    bets['累積損益']=bets['損益'].cumsum()
    dd=bets['累積損益'].cummax().clip(lower=0)-bets['累積損益']
    raced=bets.groupby('race_id').agg(払戻=('払戻','sum'))
    stats={'検証レース数':test['race_id'].nunique(),'購入レース数':len(raced),'購入点数':len(bets),'投資額':float(bets['投資'].sum()),'払戻額':float(bets['払戻'].sum()),'回収率':100*bets['払戻'].sum()/bets['投資'].sum(),'的中率':100*(raced['払戻']>0).mean(),'最大DD':float(dd.max()),'学習最終日':str(pd.Timestamp(cutoff).date())}
    return predicted,bets,stats
