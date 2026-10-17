import streamlit as st
import pandas as pd
import numpy as np
import itertools
import urllib.request
import io
import re
import csv
import html
import unicodedata

# 1. ページの設定
st.set_page_config(
    page_title="JRA 黄金パターン AI ダッシュボード",
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
    .confidence-badge {
        background-color: #b7791f; color: #ffffff; padding: 2px 8px;
        border-radius: 4px; font-size: 0.75rem; font-weight: bold; float: right;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏇 JRA 黄金パターン AI ダッシュボード")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="box_unit")
    if st.button("🔄 Google Driveから最新データを再取得"):
        st.cache_data.clear()
        st.rerun()

# タイム・上り3F解析
def parse_horse_history(row_str):
    time_score = 70.0
    last3f_score = 70.0
    try:
        m_3f = re.search(r'3F\s*([\d\.]+)', row_str)
        if m_3f:
            val_3f = float(m_3f.group(1))
            last3f_score = max(50.0, 100.0 - (val_3f - 35.0) * 10)
            
        m_time = re.search(r'(\d+):([\d\.]+)', row_str)
        if m_time:
            minutes = int(m_time.group(1))
            seconds = float(m_time.group(2))
            total_sec = minutes * 60 + seconds
            time_score = max(50.0, 110.0 - (total_sec - 75.0) * 2)
    except:
        pass
    return time_score, last3f_score

# 実際のJRA表では「2026年... 4回東京6日」の次の行に「1レース」が入る。
# 各シートを個別に読み、見出しセルを起点にレースを分割する。
COURSES = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")
COURSE_PATTERN = re.compile(r"(?:[1-5]回\s*)?(" + "|".join(COURSES) + r")(?:\s*\d+日|競馬場)?")
RACE_NUMBER_PATTERN = re.compile(r"(?<!\d)(1[0-2]|[1-9])\s*(?:レース|R|Ｒ)(?!\w)", re.I)
ODDS_PATTERN = re.compile(r"([\d.]+)\s*\(\s*(\d+)\s*番人気\s*\)")


def clean_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return unicodedata.normalize("NFKC", str(value)).strip()


def parse_race_heading(value, sheet_name=""):
    text = clean_text(value)
    # 「ウインファイヴ 2レース目」は誤検出しないよう、行頭の単独レース番号を優先。
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    course_match = COURSE_PATTERN.search(text)
    course = course_match.group(1) if course_match else None
    if course is None:
        course = next((c for c in COURSES if c in sheet_name.lower() or
                       {"東京": "tokyou", "京都": "kyouto", "新潟": "niigata"}.get(c) in sheet_name.lower()
                       if {"東京": "tokyou", "京都": "kyouto", "新潟": "niigata"}.get(c)), None)
    race_no = None
    race_line_index = None
    for i, line in enumerate(lines):
        match = re.fullmatch(r"(?:第\s*)?(1[0-2]|[1-9])\s*(?:レース|R|Ｒ)", line, re.I)
        if match:
            race_no = int(match.group(1))
            race_line_index = i
            break
    if race_no is None:
        return None
    # 競走名は「Nレース」の次の行。WIN5表記が間にある場合は読み飛ばす。
    following = lines[race_line_index + 1:]
    following = [x for x in following if not re.search(r"ウインファイヴ|レース目", x)]
    race_title = following[0] if following else ""
    return {"course": course, "race_no": race_no, "race_title": race_title}


def parse_sheet_rows(rows, day_label, sheet_name=""):
    races = []
    current = None
    columns = None

    def finish():
        nonlocal current
        if current and current["horses"]:
            course = current["course"]
            number = current["race_no"]
            name = f"{course} {number}R" if course else f"開催場不明 {number}R"
            if current["race_title"]:
                name += f" {current['race_title']}"
            current["race_name"] = name
            current["identified"] = bool(course and number)
            current["day_label"] = day_label
            races.append(current)
        current = None

    for raw in rows:
        cells = [clean_text(x) for x in raw]
        if not any(cells):
            continue
        first = cells[0]
        # 見出しはA列にあり、複数行テキストでレース番号が単独行に入る。
        if first and ("発走時刻" in first or "レース" in first):
            heading = parse_race_heading(first, sheet_name)
            if heading:
                finish()
                current = {**heading, "horses": []}
                columns = None
                continue
        if any("馬番" in c for c in cells) and any("馬名" in c for c in cells):
            columns = {
                "horse": next(i for i, c in enumerate(cells) if "馬番" in c),
                "name": next(i for i, c in enumerate(cells) if "馬名" in c),
                "previous": next((i for i, c in enumerate(cells) if "前走" in c), None),
            }
            continue
        if current is None or columns is None:
            continue
        hi, ni, pi = columns["horse"], columns["name"], columns["previous"]
        if max(hi, ni) >= len(cells):
            continue
        try:
            horse_no = int(float(cells[hi]))
            if not 1 <= horse_no <= 18 or float(cells[hi]) != horse_no:
                continue
        except (ValueError, TypeError):
            continue
        field = cells[ni]
        name = field.split("\n")[0].strip()
        if not name:
            continue
        odds_match = ODDS_PATTERN.search(field)
        odds = float(odds_match.group(1)) if odds_match else 15.0
        popularity = int(odds_match.group(2)) if odds_match else 5
        previous = cells[pi] if pi is not None and pi < len(cells) else ""
        time_score, last3f_score = parse_horse_history(previous)
        current["horses"].append({
            "horse_no": horse_no, "name": name,
            "pop_rank": popularity, "odds": odds,
            "time_index": time_score, "last3f_index": last3f_score,
            "track_aptitude": 75.0,
        })
    finish()
    return races


def parse_workbook_bytes(data, day_label):
    from openpyxl import load_workbook
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        races = []
        for sheet in workbook.worksheets:
            races.extend(parse_sheet_rows(sheet.values, day_label, sheet.title))
        return races
    finally:
        workbook.close()


@st.cache_data(ttl=300)
def load_races_from_google_drive():
    sources = [
        {"id": "14Zn-qUtrbhvNIXJXfNoB8hLfFXLzzeRf-jI3qBDZI_Q", "day_label": "土曜日開催"},
        {"id": "1oI_Z6cqjDjQP9C81WsLJ5GgfTMqNw7mbiH2N9N9b780", "day_label": "日曜日開催"},
    ]
    races, errors = [], []
    for source in sources:
        # CSVは最初のタブだけになるため、Excel形式で全タブを取得する。
        url = f"https://docs.google.com/spreadsheets/d/{source['id']}/export?format=xlsx"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
            parsed = parse_workbook_bytes(data, source["day_label"])
            races.extend(parsed)
            if not parsed:
                errors.append(f"{source['day_label']}: 出走馬を含むレースが見つかりません")
        except Exception as exc:
            errors.append(f"{source['day_label']}: 取得・解析失敗 ({exc})")
    return races, errors

all_loaded_races, load_errors = load_races_from_google_drive()
for error in load_errors:
    st.warning(error)

def calculate_ai_indices(horses_data):
    df = pd.DataFrame(horses_data)
    df['ai_score'] = (
        df['time_index'] * 0.5 + 
        df['last3f_index'] * 0.3 + 
        df['track_aptitude'] * 0.2
    )
    df['idx_rank'] = df['ai_score'].rank(ascending=False, method='min').astype(int)
    df['divergence'] = df['pop_rank'] - df['idx_rank']
    return df.sort_values('idx_rank').reset_index(drop=True)

# --- タブ構成: 土曜日 / 日曜日 ---
tab_sat, tab_sun = st.tabs(["📅 土曜日開催レース", "📅 日曜日開催レース"])

def render_race_list(target_day_label):
    filtered_races = [r for r in all_loaded_races if r['day_label'] == target_day_label]
    
    if not filtered_races:
        st.warning(f"⚠️ Google Driveからの {target_day_label} のレースデータ取得に失敗しました。スプレッドシートのアクセス権限（リンクを知っている全員が閲覧可能）をご確認ください。")
        return

    for r_idx, race in enumerate(filtered_races):
        if not race["identified"]:
            st.warning("⚠️ このレースの開催場・レース番号はCSV内で特定できませんでした。元シートの見出しをご確認ください。")
        scored_df = calculate_ai_indices(race["horses"])
        top4_nos = scored_df.head(4)['horse_no'].tolist()

        st.markdown(f"""
        <div class="race-card">
            <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">📅 {html.escape(race['day_label'])}</span>
            <span class="confidence-badge">🔥 4頭BOX (4点)</span>
            <h3 style="margin-top: 8px;">📍 {html.escape(race['race_name'])}</h3>
            <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
                <b>🎯 AI上位4頭 (BOX対象):</b> 馬番 <b>{', '.join(map(str, top4_nos))}番</b>
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"🎫 {race['race_name']} の3連複4頭BOX買い目 & 出走馬一覧を開く", expanded=False):
            box_bets = []
            for comb in itertools.combinations(top4_nos, 3):
                comb_sorted = sorted(list(comb))
                matched_odds = scored_df[scored_df['horse_no'].isin(comb_sorted)]['odds'].sum()
                simulated_odds = round(matched_odds * 1.5, 1)
                box_bets.append({
                    "券種": "3連複BOX",
                    "組み合わせ": f"{comb_sorted[0]} - {comb_sorted[1]} - {comb_sorted[2]}",
                    "投資金額": f"{bet_unit:,} 円",
                    "想定オッズ": f"{simulated_odds} 倍",
                    "予想払戻金": f"約 {int(bet_unit * simulated_odds):,} 円"
                })
            st.dataframe(pd.DataFrame(box_bets), use_container_width=True, hide_index=True)

            st.markdown("##### 📋 出走馬 AIスコアリング一覧")
            sorted_df = scored_df.sort_values('idx_rank').reset_index(drop=True)
            for _, row in sorted_df.iterrows():
                gap_color = "#63b3ed" if row['divergence'] > 0 else ("#f6e05e" if row['divergence'] == 0 else "#ff4b4b")
                st.markdown(f"""
                <div style="background-color: #1a1c23; border: 1px solid #374151; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;">
                    <div style="font-size: 1.0rem; font-weight: bold; color: #ffffff; margin-bottom: 4px;">
                        <span style="background-color: #2b6cb0; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; margin-right: 6px;">馬番 {int(row['horse_no'])}</span>
                        {html.escape(str(row['name']))}
                    </div>
                    <div style="display: flex; gap: 15px; font-size: 0.8rem; color: #cbd5e0; flex-wrap: wrap;">
                        <div>AI順位: <b style="color: #f6e05e;">第{int(row['idx_rank'])}位</b></div>
                        <div>人気: <b>{int(row['pop_rank'])}番人気</b></div>
                        <div>AI指数: <b>{row['ai_score']:.1f}</b></div>
                        <div>乖離: <b style="color: {gap_color};">{row['divergence']:+d}</b></div>
                        <div>単勝オッズ: <b style="color: #4ade80;">{row['odds']}倍</b></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

with tab_sat:
    st.markdown("### 🟢 土曜日開催のレース一覧")
    render_race_list("土曜日開催")

with tab_sun:
    st.markdown("### 🟠 日曜日開催のレース一覧")
    render_race_list("日曜日開催")
