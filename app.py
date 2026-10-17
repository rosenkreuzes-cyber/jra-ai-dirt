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
import zipfile
from urllib.error import HTTPError, URLError

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
    min_coverage = st.slider("最低過去走データ保有率 (%)", 50, 100, 75, 5)
    min_gap = st.slider("上位4頭と5位の最低指数差", 0.0, 20.0, 3.0, 0.5)
    min_confidence = st.slider("推奨最低評価点（的中確率ではありません）", 40, 95, 65, 5)
    max_recommendations = st.slider("1日あたりの推奨上限", 3, 5, 5)
    min_top_history = st.slider("上位4頭の最低過去走数", 1, 4, 2)
    min_top_dirt = st.slider("上位4頭の最低ダート経験馬数", 2, 4, 3)
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
        aliases = {"tokyou": "東京", "tokyo": "東京", "kyouto": "京都", "kyoto": "京都", "niigata": "新潟"}
        lower = sheet_name.lower()
        course = next((c for c in COURSES if c in sheet_name), None)
        if course is None:
            course = next((v for k, v in aliases.items() if k in lower), None)
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
                "previous": [i for i, c in enumerate(cells) if re.search(r"前走|前々走|[34]走前", c)],
            }
            continue
        if current is None or columns is None:
            continue
        hi, ni, previous_indices = columns["horse"], columns["name"], columns["previous"]
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
        histories = [cells[i] for i in previous_indices if i < len(cells) and cells[i]]
        valid_histories = [h for h in histories if re.search(r"20\d{2}年\d{1,2}月\d{1,2}日", h)]
        previous = valid_histories[0] if valid_histories else ""
        time_score, last3f_score = parse_horse_history(previous)
        # 異なる距離の走破タイムを直接比較しない。着順と頭数を相対評価に使う。
        history_scores = []
        dirt_runs = 0
        for history in valid_histories:
            finish_match = re.search(r"(?<!\d)(\d{1,2})着", history)
            field_size = re.search(r"(?<!\d)(\d{1,2})頭", history)
            is_dirt = bool(re.search(r"\d{3,4}\s*ダ", history))
            if is_dirt:
                dirt_runs += 1
            if finish_match and field_size:
                rank, field = int(finish_match.group(1)), int(field_size.group(1))
                if field >= 2 and 1 <= rank <= field:
                    percentile = 100 * (field - rank) / (field - 1)
                    history_scores.append((percentile, is_dirt))
        # ダート実績を優先し、直近の実績に重みを置く。
        weighted = [(v, 1.0 if is_dirt else 0.65) for v, is_dirt in history_scores]
        relative_score = (sum(v * w for v, w in weighted) / sum(w for _, w in weighted)) if weighted else None
        dirt_results = [v for v, is_dirt in history_scores if is_dirt]
        dirt_score = sum(dirt_results) / len(dirt_results) if dirt_results else None
        current["horses"].append({
            "horse_no": horse_no, "name": name,
            "pop_rank": popularity, "odds": odds,
            "time_index": time_score, "last3f_index": last3f_score,
            "track_aptitude": 75.0,
            "history_count": len(valid_histories),
            "dirt_runs": dirt_runs,
            "relative_score": relative_score,
            "dirt_score": dirt_score,
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


# Googleスプレッドシートと、Driveに置いた元ExcelではダウンロードURLが異なる。
SOURCES = [
    {"id": "14Zn-qUtrbhvNIXJXfNoB8hLfFXLzzeRf-jI3qBDZI_Q", "day_label": "土曜日開催"},
    {"id": "1oI_Z6cqjDjQP9C81WsLJ5GgfTMqNw7mbiH2N9N9b780", "day_label": "日曜日開催"},
]


def download_workbook(file_id):
    candidates = [
        ("Googleスプレッドシート形式", f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"),
        ("Google DriveのExcelファイル", f"https://drive.google.com/uc?export=download&id={file_id}"),
    ]
    failures = []
    for label, url in candidates:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=35) as response:
                content = response.read()
                final_url = response.geturl()
            if not zipfile.is_zipfile(io.BytesIO(content)):
                preview = content[:200].decode("utf-8", errors="replace").replace("\n", " ")
                failures.append(f"{label}: Excelではない応答 ({len(content)} bytes, {preview[:90]!r})")
                continue
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if "xl/workbook.xml" not in z.namelist():
                    failures.append(f"{label}: ExcelブックではないZIP")
                    continue
            return content, label
        except HTTPError as exc:
            failures.append(f"{label}: HTTP {exc.code} {exc.reason}")
        except (URLError, TimeoutError, OSError) as exc:
            failures.append(f"{label}: 通信エラー {type(exc).__name__}: {exc}")
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    raise RuntimeError(" / ".join(failures))


@st.cache_data(ttl=300)
def load_races_from_google_drive():
    races, errors, diagnostics = [], [], []
    for source in SOURCES:
        day = source["day_label"]
        try:
            content, method = download_workbook(source["id"])
            parsed = parse_workbook_bytes(content, day)
            races.extend(parsed)
            diagnostics.append(f"{day}: {method}から {len(parsed)} レースを取得")
            if not parsed:
                errors.append(f"{day}: Excelは取得できましたが、レースを解析できませんでした")
        except Exception as exc:
            errors.append(f"{day}: {exc}")
    return races, errors, diagnostics


all_loaded_races, load_errors, load_diagnostics = load_races_from_google_drive()
with st.sidebar.expander("📡 データ取得診断", expanded=bool(load_errors)):
    for msg in load_diagnostics:
        st.success(msg)
    for msg in load_errors:
        st.error(msg)
    st.caption("403なら公開設定・組織のダウンロード制限、404ならID違い、Excel以外の応答ならGoogleのログイン画面やプレビュー画面への転送が考えられます。")

# Google Drive側の仕様に左右されず、手元のExcelで表示を確認できる代替手段
with st.sidebar.expander("📂 Excelファイルから読み込む（代替）"):
    uploaded_sat = st.file_uploader("土曜日のExcel", type=["xlsx"], key="sat_xlsx")
    uploaded_sun = st.file_uploader("日曜日のExcel", type=["xlsx"], key="sun_xlsx")
    for upload, day in ((uploaded_sat, "土曜日開催"), (uploaded_sun, "日曜日開催")):
        if upload is not None:
            try:
                replacement = parse_workbook_bytes(upload.getvalue(), day)
                if not replacement:
                    st.error(f"{day}: レースが見つかりませんでした")
                else:
                    all_loaded_races = [r for r in all_loaded_races if r["day_label"] != day] + replacement
                    st.success(f"{day}: {len(replacement)} レースを読み込みました")
            except Exception as exc:
                st.error(f"{day}: ファイル解析エラー: {exc}")

def calculate_ai_indices(horses_data):
    df = pd.DataFrame(horses_data)
    # ダート戦なのでダート着順の相対成績を優先。芝のみの馬は不確実性を反映。
    base = pd.to_numeric(df["relative_score"], errors="coerce")
    dirt = pd.to_numeric(df["dirt_score"], errors="coerce")
    runs = pd.to_numeric(df["history_count"], errors="coerce").fillna(0)
    dirt_runs = pd.to_numeric(df["dirt_runs"], errors="coerce").fillna(0)
    df["ai_score"] = (0.35 * base + 0.65 * dirt.fillna(base) -
                      (dirt_runs.eq(0) * 15) -
                      (runs.lt(2) * 8)).where(base.notna())
    df = df.sort_values(["ai_score", "horse_no"], ascending=[False, True], na_position="last").reset_index(drop=True)
    df["idx_rank"] = range(1, len(df) + 1)
    df["divergence"] = df["pop_rank"] - df["idx_rank"]
    return df


def screen_race(race, min_coverage, min_gap, min_confidence, min_top_history, min_top_dirt):
    df = calculate_ai_indices(race["horses"])
    n = len(df)
    title = race.get("race_title", "")
    if not race.get("identified", False):
        return None, "開催場・レース番号が特定できない", df
    if re.search(r"新馬|メイクデビュー", title):
        return None, "新馬戦（過去走なし）", df
    if n < 6:
        return None, "出走馬6頭未満", df
    known = int(df["history_count"].gt(0).sum())
    coverage = known / n * 100
    if coverage < min_coverage:
        return None, f"過去走データ保有率不足 ({coverage:.0f}%)", df
    if df["ai_score"].notna().sum() < 5:
        return None, "指数算出可能馬が5頭未満", df
    top = df.head(4)
    if top["history_count"].lt(min_top_history).any():
        return None, f"上位4頭に過去走{min_top_history}走未満の馬がいる", df
    top_dirt = int(top["dirt_runs"].gt(0).sum())
    if top_dirt < min_top_dirt:
        return None, f"上位4頭のダート経験馬不足 ({top_dirt}/4)", df
    gap = float(df.iloc[3]["ai_score"] - df.iloc[4]["ai_score"])
    if gap < min_gap:
        return None, f"4位と5位の指数差不足 ({gap:.1f})", df
    dirt_coverage = float(df["dirt_runs"].gt(0).mean() * 100)
    top_avg_runs = float(top["history_count"].mean())
    # 過去走の充実・ダート経験・上位候補の層・5位との差を総合評価。
    # 検証済みの的中確率ではない。閾値は運用後にバックテストで調整する。
    quality = min(100., 0.25 * coverage + 0.20 * dirt_coverage +
                  0.20 * min(100., top_avg_runs / 4 * 100) +
                  0.15 * (top_dirt / 4 * 100) +
                  0.20 * min(100., gap / 12 * 100))
    if quality < min_confidence:
        return None, f"評価点不足 ({quality:.0f}点)", df
    return {"score": round(quality), "gap": round(gap, 1), "coverage": round(coverage),
            "dirt_coverage": round(dirt_coverage), "top_dirt": top_dirt,
            "top_avg_runs": round(top_avg_runs, 1)}, None, df

# --- タブ構成: 土曜日 / 日曜日 ---
tab_sat, tab_sun = st.tabs(["📅 土曜日開催レース", "📅 日曜日開催レース"])

def render_race_list(target_day_label):
    filtered_races = [r for r in all_loaded_races if r['day_label'] == target_day_label]
    
    if not filtered_races:
        st.warning(f"⚠️ {target_day_label} のレースデータがありません。サイドバーの『データ取得診断』で原因を確認するか、Excelファイルをアップロードしてください。")
        return

    selected = []
    excluded = []
    for race in filtered_races:
        metrics, reason, df = screen_race(race, min_coverage, min_gap, min_confidence, min_top_history, min_top_dirt)
        if metrics is None:
            excluded.append((race["race_name"], reason))
        else:
            selected.append((race, metrics, df))
    selected.sort(key=lambda item: (item[1]["score"], item[1]["gap"]), reverse=True)
    overflow = selected[max_recommendations:]
    selected = selected[:max_recommendations]
    for race, metrics, _ in overflow:
        excluded.append((race["race_name"], f"推奨上限{max_recommendations}件による見送り（評価{metrics['score']}点）"))
    st.info(f"推奨 {len(selected)} レース / 対象 {len(filtered_races)} レース（見送り {len(excluded)}）。基準未達なら3件未満もあります。")
    if not selected:
        st.warning("条件に合う推奨候補はありません。条件を緩めるか、データを確認してください。")
    with st.expander(f"スクリーニング除外理由（{len(excluded)}レース）"):
        for name, reason in excluded:
            st.write(f"{name}：{reason}")
    for race, metrics, scored_df in selected:
        if not race["identified"]:
            st.warning("⚠️ このレースの開催場・レース番号はCSV内で特定できませんでした。元シートの見出しをご確認ください。")
        top4_nos = scored_df.head(4)['horse_no'].tolist()

        st.markdown(f"""
        <div class="race-card">
            <span style="background-color: #2d3748; color: #63b3ed; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">📅 {html.escape(race['day_label'])}</span>
            <span class="confidence-badge">候補評価 {metrics["score"]}点</span>
            <h3 style="margin-top: 8px;">📍 {html.escape(race['race_name'])}</h3>
            <p style='margin: 4px 0; font-size: 0.8rem; color: #cbd5e0;'>過去走保有率 {metrics["coverage"]}% ／ ダート実績保有率 {metrics["dirt_coverage"]}% ／ 上位4頭ダート経験 {metrics["top_dirt"]}/4 ／ 4位-5位指数差 {metrics["gap"]}</p>
            <p style='margin: 4px 0; font-size: 0.85rem; color: #a0aec0;'>
                <b>🎯 AI上位4頭 (BOX対象):</b> 馬番 <b>{', '.join(map(str, top4_nos))}番</b>
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"🎫 {race['race_name']} の3連複4頭BOX買い目 & 出走馬一覧を開く", expanded=False):
            box_bets = []
            for comb in itertools.combinations(top4_nos, 3):
                box_bets.append({
                    "券種": "3連複BOX",
                    "組み合わせ": " - ".join(map(str, sorted(comb))),
                    "投資金額": f"{bet_unit:,} 円",
                })
            st.dataframe(pd.DataFrame(box_bets), use_container_width=True, hide_index=True)
            st.caption(f"4点 × {bet_unit:,}円 = 合計 {bet_unit * 4:,}円。実際の3連複オッズは取得していないため、架空の払戻予測は表示しません。")

            st.markdown("##### 📋 出走馬 AIスコアリング一覧")
            sorted_df = scored_df.sort_values("ai_score", ascending=False, na_position="last").reset_index(drop=True)
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
                        <div>AI指数: <b>{row['ai_score']:.1f} / 過去{int(row['history_count'])}走</b></div>
                        <div>乖離: <b style="color: {gap_color};">{row['divergence']:+d}</b></div>
                        <div>単勝オッズ: <b style="color: #4ade80;">{row['odds']}倍</b></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

st.caption("評価点は過去走・ダート実績・指数差に基づく独自の順位付けで、的中確率ではありません。過去の確定着順によるバックテストは未実施です。")

with tab_sat:
    st.markdown("### 🟢 土曜日開催のレース一覧")
    render_race_list("土曜日開催")

with tab_sun:
    st.markdown("### 🟠 日曜日開催のレース一覧")
    render_race_list("日曜日開催")
