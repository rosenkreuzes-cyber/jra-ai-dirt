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
import json
import base64
import datetime
import calendar
import urllib.parse
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

st.title("🏇 JRA 黄金パターン AI ダッシュボード [新AI評価点グラデーション修正版]")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    min_coverage = st.slider("最低過去走データ保有率 (%)", 50, 100, 75, 5)
    min_gap = st.slider("上位4頭と5位の最低指数差（※旧AIのみ適用）", 0.0, 20.0, 3.0, 0.5)
    min_confidence = st.slider("推奨最低評価点（的中確率ではありません）", 40, 95, 85, 5)
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
    value = html.unescape(str(value))
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return unicodedata.normalize("NFKC", value).replace("\u3000", " ").strip()


def parse_race_heading(value, sheet_name=""):
    text = clean_text(value)
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
    following = lines[race_line_index + 1:]
    following = [x for x in following if not re.search(r"ウインファイヴ|レース目", x)]
    race_title = following[0] if following else ""
    return {"course": course, "race_no": race_no, "race_title": race_title}


def parse_dirt_run(raw):
    t = clean_text(raw).replace("<br>", "\n")
    m = re.search(r"(\d{3,4})\s*ダ", t)
    if not m:
        return None
    distance = int(m.group(1))
    time_m = re.search(r"(?<!\d)(\d{1,2}):(\d{2}\.\d)(?!\d)", t)
    final_m = re.search(r"3F\s*(\d{2}\.\d)", t, re.I)
    rank_m = re.search(r"(?<!\d)(\d{1,2})着", t)
    field_m = re.search(r"(?<!\d)(\d{1,2})頭", t)
    going_m = re.search(r"(?:ダ(?:ート)?\s*)?(稍重|不良|良|重)(?:\s|$)", t)
    rank = int(rank_m.group(1)) if rank_m else None
    field = int(field_m.group(1)) if field_m else None
    
    corner_pos = None
    corner_m = re.search(r"([1-9]\d*)[角コーナー]", t)
    if corner_m:
        corner_pos = int(corner_m.group(1))

    margin_m = re.search(r"[（(]\s*([+-]?\d+(?:\.\d+)?)\s*[）)]", t)
    return {
        "margin": float(margin_m.group(1)) if margin_m else None,
        "distance": distance,
        "course": next((c for c in COURSES if re.search(r"(?:^|\n)\s*"+c+r"\s*(?:\n|$)",t)), None),
        "time": int(time_m.group(1))*60 + float(time_m.group(2)) if time_m else None,
        "last3f": float(final_m.group(1)) if final_m else None,
        "going": going_m.group(1) if going_m else None,
        "rank": rank, "field": field,
        "corner_pos": corner_pos,
    }


def numeric_odds(value):
    m = re.search(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", clean_text(value))
    return float(m.group(1)) if m else None


def robust_scale(values, higher_is_better=False):
    import numpy as np
    a = np.array([float(v) for v in values if v is not None and np.isfinite(v)], dtype=float)
    if len(a) < 3:
        return None
    med = float(np.median(a))
    mad = float(np.median(np.abs(a-med)))
    spread = max(1.4826*mad, float(np.std(a))*0.5, 0.15)
    return med, spread, (1 if higher_is_better else -1)


GOING_SEC_PER_1000M = {"良": 0.0, "稍重": -0.35, "重": -0.70, "不良": -0.90}


# 新AIの5要素: 走破タイム・上がり3F・着差・距離適性・馬場状態。
# 枠順は一律の加点に使わない。実測データが揃うまで表示専用。
NEW_WEIGHTS = {"time": .25, "last3f": .20, "margin": .20,
               "distance": .20, "going": .15}

def dirt_model(horses, target_distance=None, target_going=None):
    runs_all = [r for h in horses for r in h.get("dirt_histories", [])]
    def normalized_time(r):
        if r.get("time") is None or r.get("going") not in GOING_SEC_PER_1000M:
            return None
        return r["time"] - GOING_SEC_PER_1000M[r["going"]] * r["distance"] / 1000

    reference = {}
    for r in runs_all:
        key = (r.get("course"), r["distance"])
        reference.setdefault(key, []).append(normalized_time(r))
    scales = {key: robust_scale(vals) for key, vals in reference.items()}

    for h in horses:
        components = {k: [] for k in NEW_WEIGHTS}
        for r in h.get("dirt_histories", []):
            dist = r["distance"]
            t = normalized_time(r)
            ref = scales.get((r.get("course"), dist))
            if ref and t is not None:
                med, spread, sign = ref
                components["time"].append(float(np.clip(50 + 16*sign*(t-med)/spread, 0, 100)))
            finals = [q["last3f"] for q in runs_all if abs(q["distance"]-dist) <= 100 and q.get("last3f") is not None]
            fref = robust_scale(finals)
            if fref and r.get("last3f") is not None:
                med, spread, sign = fref
                components["last3f"].append(float(np.clip(50 + 16*sign*(r["last3f"]-med)/spread, 0, 100)))
            # 着差は勝ち馬との秒差。負値（勝利時の2着馬との差）は0扱い。
            if r.get("margin") is not None:
                components["margin"].append(float(np.clip(90 - max(0, r["margin"]) * 22, 0, 100)))
            if target_distance:
                closeness = max(0., 1. - abs(dist-target_distance)/800.)
                if r.get("rank") and r.get("field", 0) > 1:
                    finish = (r["field"]-r["rank"])/(r["field"]-1)
                    components["distance"].append(float(100*(.5*closeness+.5*finish)*closeness))
            # 馬場適性は同じ馬場状態での実績に限る。対象馬場が不明なら採点しない。
            if target_going and r.get("going") == target_going and r.get("rank") and r.get("field", 0) > 1:
                components["going"].append(float(np.clip(100*(r["field"]-r["rank"])/(r["field"]-1), 0, 100)))
        values = {k: round(float(np.mean(v)),2) if v else None for k,v in components.items()}
        present = [k for k,v in values.items() if v is not None]
        total = sum(NEW_WEIGHTS[k] for k in present)
        # 欠損項目の重みを無条件に再配分しない。タイム/上がりの片方と着差が必要。
        required = values["margin"] is not None and (values["time"] is not None or values["last3f"] is not None)
        h["ai_score"] = round(sum(NEW_WEIGHTS[k]*values[k] for k in present)/total, 2) if required and total >= .45 else None
        h.update({f"{k}_score": values[k] for k in NEW_WEIGHTS})
        h["evidence_coverage"] = round(100*total, 1)
    return horses


def heading_date(raw):
    # Some exported JRA headings lose the leading "2" in "2026年".
    # Only repair the exact three-digit year 026, never arbitrary years.
    normalized = clean_text(raw)
    normalized = re.sub(r"(?<!\d)026年(?=\s*\d{1,2}月)", "2026年", normalized)
    m = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", normalized)
    if not m:
        m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", normalized)
    if not m:
        return None
    try:
        return datetime.date(*map(int, m.groups()))
    except ValueError:
        return None


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
            heading = current.get("heading_raw", "")
            current["race_date"] = heading_date(heading) or heading_date(sheet_name)
            surface_text = heading + "\n" + "\n".join(current.get("race_info", [])[:4])
            surface_text = unicodedata.normalize("NFKC", surface_text)
            # JRA race headings use "コース：1,400メートル（ダート・左）".
            # Earlier detection only recognized "ダート1400" and missed Tokyo races.
            # Determine the surface from the current race's course clause first.
            course_clause = re.search(r"コース\s*[:：]\s*[\d,，]+\s*(?:メートル|m)\s*[（(]\s*(ダート|芝)", surface_text)
            dirt_match = re.search(r"(?:ダート|ダ)\s*(\d{3,4})\s*(?:m|メートル)?", surface_text, re.I)
            dirt_match_rev = re.search(r"(\d{3,4})\s*(?:m|メートル)?\s*(?:ダート|ダ)(?![ァ-ン])", surface_text, re.I)
            turf_match = re.search(r"(?:芝|ターフ)\s*(\d{3,4})|(\d{3,4})\s*(?:m)?\s*芝", surface_text, re.I)
            dist_match = dirt_match or dirt_match_rev
            dirt_marker = re.search(r"(?<![ァ-ン一-龥])ダート(?![ァ-ン])|(?<![ァ-ン一-龥])ダ(?=\s|\d{3,4}|$)", surface_text)
            turf_marker = re.search(r"(?<![ァ-ン一-龥])芝(?=\s|\d{3,4}|$)", surface_text)
            target_distance = int(dist_match.group(1)) if dist_match else None
            if target_distance is None and dirt_marker:
                distance_candidates = re.findall(r"(?<!\d)(?:1000|1150|1200|1300|1400|1600|1700|1800|1900|2000|2100|2400|2500)(?!\d)", surface_text)
                if len(set(distance_candidates)) == 1:
                    target_distance = int(distance_candidates[0])
            current["target_distance"] = target_distance
            if course_clause:
                current["is_dirt_race"] = course_clause.group(1) == "ダート"
                current["surface_conflict"] = False
                if target_distance is None:
                    distance_from_clause = re.search(r"コース\s*[:：]\s*([\d,，]+)", surface_text)
                    if distance_from_clause:
                        current["target_distance"] = int(re.sub(r"[,，]", "", distance_from_clause.group(1)))
            else:
                current["is_dirt_race"] = bool(dirt_match or dirt_match_rev or dirt_marker) and not bool(turf_match or turf_marker)
                current["surface_conflict"] = bool((dirt_match or dirt_match_rev or dirt_marker) and (turf_match or turf_marker))
            current["surface_diagnostic"] = surface_text[:240]
            going_match = re.search(r"(?:ダート|ダ)\s*(?:\d{3,4}\s*m?\s*)?(稍重|不良|良|重)", surface_text)
            current["target_going"] = going_match.group(1) if going_match else None
            dirt_model(current["horses"], target_distance, None)
            odds_list = [h.get("odds") for h in current["horses"]]
            if odds_list and all(x is not None for x in odds_list):
                for h in current["horses"]:
                    h["pop_rank"] = 1 + sum(x < h["odds"] for x in odds_list)
            races.append(current)
        current = None

    for raw in rows:
        cells = [clean_text(x) for x in raw]
        if not any(cells):
            continue
        first = cells[0]
        if first and ("発走時刻" in first or "レース" in first):
            heading = parse_race_heading(first, sheet_name)
            if heading:
                finish()
                current = {**heading, "horses": [], "heading_raw": " ".join(cells), "race_info": [], "sheet_name": sheet_name}
                columns = None
                continue
        if any("馬番" in c for c in cells) and any("馬名" in c for c in cells):
            columns = {
                "horse": next(i for i, c in enumerate(cells) if "馬番" in c),
                "name": next(i for i, c in enumerate(cells) if "馬名" in c),
                "previous": [i for i, c in enumerate(cells) if re.search(r"前走|前々走|[34]走前", c)],
                "odds": next((i for i,c in enumerate(cells) if c == "単勝" or c.startswith("単勝オッズ")), None),
            }
            continue
        if current is not None and columns is None:
            current.setdefault("race_info", []).append(" ".join(cells))
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
        odds_idx = columns.get("odds")
        odds = numeric_odds(cells[odds_idx]) if odds_idx is not None and odds_idx < len(cells) else (float(odds_match.group(1)) if odds_match else None)
        popularity = int(odds_match.group(2)) if odds_match else None

        histories = [cells[i] for i in previous_indices if i < len(cells) and cells[i]]
        valid_histories = [h for h in histories if re.search(r"20\d{2}年\d{1,2}月\d{1,2}日", h)]
        previous = valid_histories[0] if valid_histories else ""
        time_score, last3f_score = parse_horse_history(previous)
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
            "dirt_histories": [r for r in (parse_dirt_run(h) for h in valid_histories) if r],
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


@st.cache_data(ttl=60)
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
    df["ai_score"] = pd.to_numeric(df["ai_score"], errors="coerce")
    df = df.sort_values(["ai_score", "horse_no"], ascending=[False, True], na_position="last").reset_index(drop=True)
    df["idx_rank"] = range(1, len(df)+1)
    df["divergence"] = pd.to_numeric(df["pop_rank"], errors="coerce") - df["idx_rank"]
    return df


# --- GitHub Private repository persistence ---
APP_VERSION = "dual-model-4.0-five-factor-85"

def score_old_model(horses):
    data = []
    for horse in horses:
        h = dict(horse)
        relative = h.get("relative_score")
        dirt = h.get("dirt_score")
        if relative is None:
            h["ai_score"] = None
        else:
            penalty = (15 if h.get("dirt_runs", 0) == 0 else 0) + (8 if h.get("history_count", 0) < 2 else 0)
            h["ai_score"] = .35 * relative + .65 * (dirt if dirt is not None else relative) - penalty
        data.append(h)
    return calculate_ai_indices(data)


def score_new_model(horses, race):
    import copy
    cloned = copy.deepcopy(horses)
    dirt_model(cloned, race.get("target_distance"), race.get("target_going"))
    return calculate_ai_indices(cloned)


def model_frames(race):
    return {"旧AI": score_old_model(race["horses"]), "新AI": score_new_model(race["horses"], race)}


def choose_dual(day):
    selected, excluded = [], []
    for race in [r for r in all_loaded_races if r["day_label"] == day]:
        frames = model_frames(race)
        evaluations = {}
        for label, frame in frames.items():
            if label == "旧AI":
                metrics, reason, _ = screen_scored_race_old(race, frame)
            else:
                metrics, reason, _ = screen_scored_race_new(race, frame)
            evaluations[label] = {"metrics": metrics, "reason": reason, "df": frame}
        if any(x["metrics"] is not None for x in evaluations.values()):
            selected.append((race, evaluations))
        else:
            excluded.append((race["race_name"], "旧AI: " + str(evaluations["旧AI"]["reason"]) + " / 新AI: " + str(evaluations["新AI"]["reason"])))
    def priority(item):
        ev = item[1]
        return max((v["metrics"]["score"] for v in ev.values() if v["metrics"]), default=-1)
    selected.sort(key=priority, reverse=True)
    if st.session_state.get("show_all_for_validation", False):
        return selected, excluded
    for race, _ in selected[max_recommendations:]:
        excluded.append((race["race_name"], "表示上限超過（検証モードでは表示可）"))
    return selected[:max_recommendations], excluded


# 旧AI用スクリーニング（指数差ギャップチェックあり）
def screen_scored_race_old(race, df):
    if not race.get("identified", True):
        return None, "レース識別不可", df
    if not race.get("is_dirt_race"):
        return None, "ダート条件を確認できないため対象外", df
    if re.search(r"新馬|メイクデビュー", race.get("race_title", "")):
        return None, "新馬戦", df
    if len(df) < 6:
        return None, "出走馬6頭未満", df
    coverage = float(df["history_count"].gt(0).mean() * 100)
    dirt_coverage = float(df["dirt_runs"].gt(0).mean() * 100)
    if coverage < min_coverage:
        return None, f"過去走保有率不足 ({coverage:.0f}%)", df
    if df["ai_score"].notna().sum() < 5:
        return None, "指数算出可能馬が5頭未満", df
    top = df.head(4)
    if top["ai_score"].isna().any():
        return None, "推奨4頭に指数欠損あり", df
    if top["history_count"].lt(min_top_history).any():
        return None, "上位4頭の過去走数不足", df
    top_dirt = int(top["dirt_runs"].gt(0).sum())
    if top_dirt < min_top_dirt:
        return None, "上位4頭のダート経験不足", df
    gap = float(df.iloc[3]["ai_score"] - df.iloc[4]["ai_score"])
    if gap < min_gap:
        return None, f"指数差不足 ({gap:.1f})", df
    avg_runs = float(top["history_count"].mean())
    quality = min(100., .25 * coverage + .20 * dirt_coverage +
                  .20 * min(100., avg_runs / 4 * 100) +
                  .15 * (top_dirt / 4 * 100) +
                  .20 * min(100., gap / 12 * 100))
    if quality < min_confidence:
        return None, f"評価点不足 ({quality:.0f})", df
    return {"score": round(quality), "gap": round(gap, 1), "coverage": round(coverage),
            "dirt_coverage": round(dirt_coverage), "top_dirt": top_dirt,
            "top_avg_runs": round(avg_runs, 1)}, None, df


# 新AI用スクリーニング（指数差ギャップ撤廃 ＆ 上位馬の指数・競合度を反映したグラデーション評価）
def screen_scored_race_new(race, df):
    if not race.get("identified", True):
        return None, "レース識別不可", df
    if not race.get("is_dirt_race"):
        return None, "ダート条件を確認できないため対象外", df
    if re.search(r"新馬|メイクデビュー", race.get("race_title", "")):
        return None, "新馬戦", df
    if len(df) < 6:
        return None, "出走馬6頭未満", df
    coverage = float(df["history_count"].gt(0).mean() * 100)
    dirt_coverage = float(df["dirt_runs"].gt(0).mean() * 100)
    if coverage < min_coverage:
        return None, f"過去走保有率不足 ({coverage:.0f}%)", df
    if df["ai_score"].notna().sum() < 5:
        return None, "指数算出可能馬が5頭未満", df
    top = df.head(4)
    if top["ai_score"].isna().any():
        return None, "推奨4頭に指数欠損あり", df
    if top["history_count"].lt(min_top_history).any():
        return None, "上位4頭の過去走数不足", df
    top_dirt = int(top["dirt_runs"].gt(0).sum())
    if top_dirt < min_top_dirt:
        return None, "上位4頭のダート経験不足", df
    
    avg_runs = float(top["history_count"].mean())
    
    # 新AIの評価点バランス調整：
    # 上位4頭のAI指数の平均値や、5位とのわずかな差、データ充実度を組み合わせて100点満点でグラデーションを持たせる
    top_scores_mean = float(top["ai_score"].mean()) if "ai_score" in top.columns and top["ai_score"].notna().all() else 70.0
    score_level = np.clip((top_scores_mean - 50.0) / 30.0 * 100.0, 40.0, 100.0)
    
    quality = min(100., 0.25 * coverage + 0.20 * dirt_coverage +
                  0.20 * min(100., avg_runs / 4 * 100) +
                  0.15 * (top_dirt / 4 * 100) +
                  0.20 * score_level)
    
    if quality < min_confidence:
        return None, f"評価点不足 ({quality:.0f})", df
    return {"score": round(quality), "gap": 0.0, "coverage": round(coverage),
            "dirt_coverage": round(dirt_coverage), "top_dirt": top_dirt,
            "top_avg_runs": round(avg_runs, 1)}, None, df


def dual_snapshot(date, race, evaluations, settings):
    models = {}
    for label, ev in evaluations.items():
        df = ev["df"]
        top = [int(x) for x in df.head(4)["horse_no"]] if df["ai_score"].notna().sum() >= 4 else []
        models[label] = {"top4": top, "eligible": ev["metrics"] is not None,
                         "metrics": ev["metrics"], "reason": ev["reason"],
                         "scores": [{"horse_no": int(r["horse_no"]), "ai_score": float(r["ai_score"]) if pd.notna(r["ai_score"]) else None}
                                    for _, r in df.iterrows()]}
    primary = models["新AI"] if models["新AI"]["top4"] else models["旧AI"]
    return {"race_id": race_key(date, race), "race_date": date.isoformat(),
            "day_label": race["day_label"], "course": race["course"],
            "race_no": int(race["race_no"]), "race_name": race["race_name"],
            "saved_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "model_version": APP_VERSION, "settings": settings,
            "models": models, "top4": primary["top4"], "metrics": primary["metrics"] or {"score":0,"gap":0},
            "bet_unit": int(bet_unit)}


def github_config():
    token = st.secrets.get("GITHUB_TOKEN", "")
    repo = st.secrets.get("GITHUB_REPO", "")
    if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise RuntimeError("SecretsにGITHUB_TOKENとGITHUB_REPOを設定してください")
    return token, repo


def _github_http_error(error, operation):
    """Surface useful rate-limit diagnostics without ever logging credentials."""
    raw = error.read().decode("utf-8", errors="replace")
    try:
        message = str(json.loads(raw).get("message", ""))
    except (ValueError, AttributeError):
        message = raw[:180]
    headers = error.headers
    remaining = headers.get("X-RateLimit-Remaining", "不明")
    reset = headers.get("X-RateLimit-Reset", "")
    retry_after = headers.get("Retry-After", "")
    reset_text = "不明"
    if reset.isdigit():
        reset_text = datetime.datetime.fromtimestamp(int(reset), datetime.timezone.utc).astimezone(
            datetime.timezone(datetime.timedelta(hours=9))).strftime("%m/%d %H:%M JST")
    if error.code == 403 and remaining == "0":
        cause = "GitHub API利用上限に到達"
    elif error.code in (403, 429) and ("secondary rate limit" in message.lower() or retry_after):
        cause = "短時間のAPIアクセス制限"
    elif error.code == 403:
        cause = "GitHubアクセス権限・認証またはAPI制限"
    else:
        cause = "GitHub APIエラー"
    # Do not expose the full server body (it can contain private URLs).
    return RuntimeError(f"{operation}: {cause} (HTTP {error.code}, 残りAPI回数={remaining}, "
                        f"上限解除={reset_text}, Retry-After={retry_after or 'なし'}, "
                        f"GitHub応答={message[:150]})")


def github_request(method, path, payload=None):
    token, repo = github_config()
    url = "https://api.github.com/repos/" + repo + "/contents/" + urllib.parse.quote(path, safe="/")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JRA-Streamlit-History",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        raise _github_http_error(e, method + " " + path) from e
    except (TimeoutError, OSError) as e:
        raise RuntimeError(f"GitHub通信失敗 ({method} {path}): {type(e).__name__}。"
                           "保存結果が不明な場合はGitHubの履歴を確認してください") from e


def get_record(path):
    item = github_request("GET", path)
    if item is None:
        return None, None
    if item.get("type") != "file":
        raise RuntimeError("保存先がファイルではありません: " + path)
    raw = base64.b64decode(item["content"].replace("\n", ""))
    return json.loads(raw.decode("utf-8")), item["sha"]


def put_record(path, record, overwrite=False):
    for attempt in range(2):
        old, sha = get_record(path)
        if old is not None and not overwrite:
            return False
        data = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        payload = {"message": "JRA history: " + path, "content": base64.b64encode(data).decode("ascii")}
        if sha:
            payload["sha"] = sha
        try:
            github_request("PUT", path, payload)
            read_all_history.clear()
            st.session_state.pop("last_good_history", None)
            return True
        except RuntimeError as e:
            if "HTTP 409" in str(e) and attempt == 0:
                continue
            raise
    raise RuntimeError("同時更新が発生しました。再読み込みしてから再試行してください")


def delete_record_safely(path, expected_race_id, expected_date):
    if (not re.fullmatch(r"predictions/\d{4}/[^/\\]+\.json", path) or ".." in path):
        raise RuntimeError("予想履歴以外のパスは削除できません")
    record, sha = get_record(path)
    if not record or not sha:
        raise RuntimeError("対象ファイルが見つかりません。履歴を再読み込みしてください")
    if record.get("race_id") != expected_race_id or record.get("race_date") != expected_date:
        raise RuntimeError("削除対象の内容が変わりました。削除を中止しました")
    github_request("DELETE", path, {
        "message": "JRA history: manually delete incorrect prediction " + path,
        "sha": sha,
    })
    read_all_history.clear()
    st.session_state.pop("last_good_history", None)


RESET_DATES = ("2026-10-17", "2026-10-18")


def reset_results_with_backup(dates=RESET_DATES):
    """Archive original result JSON bytes as records before deleting; never touch predictions."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    targets = []
    for folder in github_list_directories("results"):
        for path in list_files(folder):
            record, sha = get_record(path)
            if record and record.get("race_date") in dates:
                rid = record.get("race_id", "")
                if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}_[^/\\]+_\d{2}R", rid):
                    raise RuntimeError("レースIDが不正なため中止: " + path)
                if path != f"results/{record['race_date'][:4]}/{rid}.json":
                    raise RuntimeError("結果ファイルの保存先が想定と違います: " + path)
                targets.append((path, record, sha))
    # All backups must complete before deleting anything.
    for path, record, sha in targets:
        archive = f"backups/result_reset_{stamp}/{path}"
        if not put_record(archive, record):
            raise RuntimeError("バックアップが既に存在するため中止: " + archive)
    deleted = []
    for path, record, sha in targets:
        # Re-read to avoid deleting a record edited during backup.
        current, current_sha = get_record(path)
        if current_sha != sha or current != record:
            raise RuntimeError("結果が途中で変更されました。ここまでの削除: " + str(deleted))
        github_request("DELETE", path, {"message": "JRA reset results 2026-10-17/18 (backup retained)", "sha": sha})
        deleted.append(path)
    return deleted, f"backups/result_reset_{stamp}/"


def inspect_duplicate_predictions(dates=RESET_DATES):
    rows = []
    for folder in github_list_directories("predictions"):
        for path in list_files(folder):
            record, _ = get_record(path)
            if record and record.get("race_date") in dates:
                rows.append({"日付": record.get("race_date"), "レースID": record.get("race_id"),
                             "レース": record.get("race_name"), "保存先": path,
                             "モデル": ",".join((record.get("models") or {record.get("model_version", "旧形式"): None}).keys()),
                             "保存日時": record.get("saved_at_utc", "")})
    return rows


def list_prediction_files_for_date(target_date):
    matches = []
    for folder in github_list_directories("predictions"):
        for path in list_files(folder):
            rec, _ = get_record(path)
            if rec and rec.get("race_date") == target_date:
                matches.append({"path": path, "record": rec})
    return matches


def list_files(directory):
    items = github_request("GET", directory)
    if items is None:
        return []
    if not isinstance(items, list):
        raise RuntimeError("GitHub一覧が配列ではありません: " + directory)
    return [x["path"] for x in items if x.get("type") == "file" and x.get("name", "").endswith(".json")]


def race_key(date, race):
    return f"{date.isoformat()}_{race['course']}_{int(race['race_no']):02d}R"


@st.cache_data(ttl=600, show_spinner=False)
def read_all_history():
    predictions, results = {}, {}
    for kind, target in (("predictions", predictions), ("results", results)):
        for folder in github_list_directories(kind):
            for path in list_files(folder):
                rec, _ = get_record(path)
                if rec and rec.get("race_id"):
                    target[rec["race_id"]] = rec
    st.session_state["last_good_history"] = (predictions, results)
    return predictions, results


def github_list_directories(root):
    items = github_request("GET", root)
    if items is None:
        return []
    if not isinstance(items, list):
        raise RuntimeError("GitHubフォルダ一覧が配列ではありません: " + root)
    return [x["path"] for x in items if x.get("type") == "dir"]


def outcome(pred, result):
    finish = [int(x) for x in result["top3"]]
    hit = len(finish) == 3 and len(set(finish)) == 3 and set(finish).issubset(set(pred["top4"]))
    stake = 4 * int(pred["bet_unit"])
    payout = int(result["trio_payout_100yen"]) * int(pred["bet_unit"]) // 100 if hit else 0
    return hit, stake, payout


settings = {"min_coverage": min_coverage, "min_gap": min_gap,
    "min_confidence": min_confidence, "max_recommendations": max_recommendations,
    "min_top_history": min_top_history, "min_top_dirt": min_top_dirt}

st.sidebar.divider()
st.sidebar.header("📆 開催日（Google Driveから自動取得）")

def source_date(day_label):
    records = [r for r in all_loaded_races if r.get("day_label") == day_label]
    dates = sorted({r.get("race_date") for r in records if isinstance(r.get("race_date"), datetime.date)})
    unknown = sum(not isinstance(r.get("race_date"), datetime.date) for r in records)
    if not records or len(dates) != 1 or unknown:
        st.sidebar.error(f"{day_label}: 開催日を確定できません（取得{len(records)}件・日付候補{len(dates)}種類・日付不明{unknown}件）。保存を停止します。")
        return None
    return dates[0]

sat_date = source_date("土曜日開催")
sun_date = source_date("日曜日開催")
with st.sidebar.expander("📅 更新データの開催日確認", expanded=True):
    for day_label, expected in (("土曜日開催", sat_date), ("日曜日開催", sun_date)):
        records = [r for r in all_loaded_races if r.get("day_label") == day_label]
        dates = sorted({str(r.get("race_date") or "不明") for r in records})
        st.write(f"{day_label}: {len(records)}レース / シート記載日: {', '.join(dates) if dates else '取得なし'}")
        if expected:
            st.success(f"自動設定：{expected.isoformat()}")
        else:
            st.error("開催日未確定：予想の確定保存を停止")
st.sidebar.caption("日付の手入力は不要です。Google Driveの内容を更新したら『最新データを再取得』を押してください。")


def render_races(day, date):
    # Never treat a race from a different date or an unverified surface as eligible.
    # The original records in GitHub are not modified by this filter.
    source_races = [r for r in all_loaded_races if r.get("day_label") == day]
    mismatches = [r for r in source_races if r.get("race_date") != date]
    # Source audit: show the actual races parsed from the chosen day's workbook.
    with st.expander("🔎 読み込み元のレース一覧（確認用）", expanded=True):
        st.caption("ここはGitHubの保存履歴ではなく、選択日のスプレッドシートから取得した内容です。")
        st.dataframe(pd.DataFrame([{"開催日": str(r.get("race_date") or "不明"), "競馬場": r.get("course"), "R": r.get("race_no"), "レース名": r.get("race_name"), "ダート判定": bool(r.get("is_dirt_race")), "元シート": r.get("sheet_name")} for r in source_races]), hide_index=True, use_container_width=True)
        st.caption("レースの芝・ダート判定は読み込み元のコース情報に従います。特定のレース番号を日付だけで除外しません。")
    if date is None or mismatches:
        st.error(f"{day}: シートの開催日が未確定、または不一致のレースが{len(mismatches)}件あります。予想の確定保存を停止しました。")
        return
    selected, excluded = choose_dual(day)
    # Always show source races even if the model screens them out.
    source_dirt = [r for r in source_races if r.get("is_dirt_race")]
    st.caption(f"読み込み元のダートレース：{len(source_dirt)}件（東京 {sum(r.get('course') == '東京' for r in source_dirt)}件）")
    st.info(f"推奨候補 {len(selected)} レース・除外 {len(excluded)} レース")
    
    try:
        _, results_dict = read_all_history()
    except Exception as history_error:
        results_dict = st.session_state.get("last_good_history", ({}, {}))[1]
        st.warning("GitHub履歴の取得に失敗しました。前回取得済みの結果があれば参考表示します（最新ではない可能性があります）: " + str(history_error))

    with st.expander("除外レースと理由"):
        for name, reason in excluded:
            st.write(name, "：", reason)
    if not selected:
        st.warning("推奨対象レースはありません。")
        return
    for race, evaluations in selected:
        st.subheader("🏇 " + race["race_name"])
        
        r_key = race_key(date, race)
        res_data = results_dict.get(r_key)
        placed_set = set(int(x) for x in res_data["top3"]) if res_data and res_data.get("top3") else set()

        a, b = st.columns(2)
        for col, label in ((a, "旧AI"), (b, "新AI")):
            ev = evaluations[label]
            df = ev["df"]
            top = [int(x) for x in df.head(4)["horse_no"]]
            with col:
                st.markdown("**" + label + "**")
                
                if ev["metrics"]:
                    score_val = ev["metrics"].get("score", 0)
                    st.markdown(f"<span style='color: #f6e05e; font-weight: bold;'>🌟 信頼度（評価点）：{score_val}点</span>", unsafe_allow_html=True)

                formatted_top = []
                for num in top:
                    if num in placed_set:
                        formatted_top.append(f"<span style='color: #2e7d32; font-weight: bold; font-size: 1.05rem;'>{num}番(入着)</span>")
                    else:
                        formatted_top.append(f"{num}番")
                
                rec_str = " ・ ".join(formatted_top) if ev["metrics"] else "対象外（参考：" + "・".join(map(str, top)) + "）"
                st.markdown(f"推奨4頭： {rec_str}", unsafe_allow_html=True)
                
                if ev["metrics"] and len(top) >= 4:
                    sorted_top4 = sorted(top)
                    combos = list(itertools.combinations(sorted_top4, 3))
                    combos_str = " ／ ".join("-".join(map(str, c)) for c in combos)
                    st.markdown(f"**3連複4点**： `{combos_str}`")

                st.caption("選考通過" if ev["metrics"] else "選考対象外：" + str(ev["reason"]))

        with st.expander("両モデルの全馬指数・買い目"):
            for label, ev in evaluations.items():
                df = ev["df"]
                st.markdown("**" + label + "**")
                top = sorted(int(x) for x in df.head(4)["horse_no"])
                st.write("3連複4点：", " ／ ".join("-".join(map(str, x)) for x in itertools.combinations(top, 3)))
                cols = [c for c in ["horse_no", "name", "odds", "pop_rank", "ai_score", "margin_score", "distance_score", "going_score", "evidence_coverage", "time_score", "last3f_score", "idx_rank"] if c in df.columns]
                st.dataframe(df[cols], hide_index=True, use_container_width=True)
        detected_date = race.get("race_date")
        verified = detected_date == date
        if st.button("💾 旧AI・新AIの予想を同時に確定保存", key="save_" + race_key(date, race), disabled=(not verified or detected_date != date or not race.get("is_dirt_race") or race.get("surface_conflict"))):
            rec = dual_snapshot(date, race, evaluations, settings)
            path = f"predictions/{date.year}/{rec['race_id']}.json"
            try:
                if put_record(path, rec):
                    st.success("両モデルの予想を同時保存しました。")
                else:
                    st.warning("このレースはすでに保存済みです。")
            except Exception as e:
                st.error("保存失敗: " + str(e))
        # Retrospective snapshots are deliberately isolated from pre-race history.
        # They never overwrite an existing prediction or affect official ROI.
        if r_key in results_dict:
            with st.expander("🧪 新AIの事後検証を別保存（正式成績には加算しない）"):
                st.caption("結果確定後に表示した新AIの4頭を、事後検証として別フォルダに記録します。旧AI・既存の予想JSONは変更しません。")
                retro_confirm = st.checkbox("事後検証であり、事前確定予想ではないことを確認", key="retro_confirm_"+race_key(date,race))
                if st.button("新AIの事後検証を保存", key="retro_save_"+race_key(date,race), disabled=not retro_confirm):
                    try:
                        rec = dual_snapshot(date, race, evaluations, settings)
                        new_model = rec["models"].get("新AI", {})
                        if len(new_model.get("top4", [])) != 4:
                            st.error("新AIの4頭が揃っていないため保存できません。")
                        else:
                            retro = {"race_id": rec["race_id"], "race_date": rec["race_date"], "race_name": rec["race_name"],
                                     "model": "新AI", "classification": "事後検証", "top4": new_model["top4"],
                                     "eligible": new_model.get("eligible", False), "bet_unit": rec["bet_unit"],
                                     "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                     "model_version": APP_VERSION}
                            path = f"retrospective/{date.year}/{rec['race_id']}.json"
                            if put_record(path, retro):
                                st.success("事後検証として別保存しました。正式な新AI成績には加算されません。")
                            else:
                                st.info("このレースの事後検証は保存済みです。上書きしません。")
                    except Exception as exc:
                        st.error("事後検証の保存に失敗: " + str(exc))
        st.divider()


st.checkbox("🔬 検証モード：推奨上限を解除して全候補を表示", key="show_all_for_validation")
t1, t2, t3, t4 = st.tabs(["📅 土曜推奨", "📅 日曜推奨", "📝 結果登録", "📊 長期成績"])
with t1:
    render_races("土曜日開催", sat_date)
with t2:
    render_races("日曜日開催", sun_date)

with t3:
    st.subheader("確定結果の登録・訂正")
    if st.button("🔄 保存済み履歴を読み直す", key="refresh_history"):
        read_all_history.clear()
        st.rerun()
    try:
        predictions, results = read_all_history()
        if not predictions:
            st.info("保存済みの予想がありません。")
        else:
            # Filter the 17/18 October historical entries against the actual dirt source sheets.
            audit_dates = {"2026-10-17", "2026-10-18"} if {str(r.get("race_date")) for r in all_loaded_races} & {"2026-10-17", "2026-10-18"} else set()
            valid_keys = set()
            for race in all_loaded_races:
                d = race.get("race_date")
                d = d.isoformat() if hasattr(d, "isoformat") else str(d)
                if d in audit_dates and race.get("is_dirt_race") and not race.get("surface_conflict"):
                    valid_keys.add((d, str(race.get("course")), int(race.get("race_no"))))
            def valid_result_race(rec):
                d = str(rec.get("race_date", ""))
                if d not in audit_dates:
                    return True
                try:
                    return (d, str(rec.get("course")), int(rec.get("race_no"))) in valid_keys
                except (ValueError, TypeError):
                    return False
            ids = sorted((k for k, rec in predictions.items() if valid_result_race(rec)), reverse=True)
            if len(ids) < len(predictions):
                rejected = [rec for rec in predictions.values() if not valid_result_race(rec)]
                st.warning(f"開催日・ダート対象の照合に合わない履歴 {len(rejected)} 件を結果入力候補から除外しました。GitHubの履歴は削除していません。")
                with st.expander("結果登録から除外した履歴と理由"):
                    for rec in rejected:
                        st.write(f"{rec.get('race_date')} {rec.get('race_name')}: 同日の元シートに一致するダートレースがない、または解析できていません")
            if not ids:
                st.info("照合済みの結果入力対象がありません。読み込み元シートを確認してください。")
                st.stop()
            rid = st.selectbox("結果を登録・訂正するレース", ids,
                format_func=lambda k: f"{predictions[k].get('course','?')} {predictions[k].get('race_no','?')}R {predictions[k].get('race_name','')} / {predictions[k].get('race_date','')} " + ("【登録済み】" if k in results else "【未登録】"))
            pred = predictions[rid]
            old = results.get(rid)
            initial = [int(x) for x in old["top3"]] if old else [1, 2, 3]
            with st.form("result_form_" + rid):
                a = st.number_input("1着馬番", 1, 18, initial[0], key="first_" + rid)
                b = st.number_input("2着馬番", 1, 18, initial[1], key="second_" + rid)
                c = st.number_input("3着馬番", 1, 18, initial[2], key="third_" + rid)
                payout = st.number_input("3連複確定払戻（100円あたり・円）", 0, 100000000,
                    int(old.get("trio_payout_100yen", 0)) if old else 0, step=10, key="payout_" + rid)
                reason = st.text_input("訂正理由（訂正時のみ）", key="reason_" + rid) if old else ""
                confirmed = st.checkbox("登録内容を確認しました", key="confirmed_" + rid)
                submitted = st.form_submit_button("✏️ 訂正して保存" if old else "💾 確定結果を保存")
            if submitted:
                if not confirmed:
                    st.error("確認欄にチェックを入れてください。")
                elif len({a, b, c}) != 3:
                    st.error("1〜3着に同じ馬番は指定できません。")
                else:
                    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    revisions = list(old.get("revision_history", [])) if old else []
                    if old:
                        if not reason.strip():
                            st.error("訂正理由を入力してください")
                            st.stop()
                        revisions.append({"updated_at_utc": now, "reason": reason, "previous_top3": old.get("top3"), "previous_payout": old.get("trio_payout_100yen")})
                    record = {
                        "race_id": rid, "race_date": pred["race_date"],
                        "top3": [int(a), int(b), int(c)],
                        "trio_payout_100yen": int(payout),
                        "saved_at_utc": old.get("saved_at_utc", now) if old else now,
                        "updated_at_utc": now,
                        "revision_history": revisions,
                    }
                    path = f"results/{pred['race_date'][:4]}/{rid}.json"
                    if put_record(path, record, overwrite=bool(old)):
                        st.success("結果を保存しました。")
                        st.rerun()
    except Exception as e:
        st.error("履歴取得に失敗: " + str(e))

with t4:
    st.subheader("長期成績：モデル別")
    try:
        predictions, results = read_all_history()
        records = []
        legacy_count = sum(1 for pred in predictions.values() if not pred.get("models") and len(pred.get("top4", [])) == 4)
        st.caption(f"旧形式の確定予想 {legacy_count}件を旧AIとして読み込みました（元のJSONは変更しません）。")
        for rid, pred in predictions.items():
            result = results.get(rid)
            models = pred.get("models") or {"旧AI": {"top4": pred.get("top4", []), "eligible": True}}
            for label, model in models.items():
                top4 = model.get("top4", [])
                if len(top4) != 4:
                    continue
                eligible = model.get("eligible", True)
                hit, stake, paid = outcome({"top4": top4, "bet_unit": pred.get("bet_unit", 100)}, result) if result and eligible else (None, None, None)
                records.append({"レースID": rid, "日付": pred.get("race_date"), "レース": pred.get("race_name"),
                    "モデル": label, "推奨4頭": ",".join(map(str, top4)),
                    "状態": "対象外" if not eligible else ("未登録" if result is None else ("的中" if hit else "不的中")),
                    "投資額": stake, "払戻額": paid, "損益": paid-stake if stake is not None else None})
        df_hist = pd.DataFrame(records)
        if df_hist.empty:
            st.info("予想履歴がありません")
        else:
            summary = []
            for label in ["旧AI", "新AI"]:
                sub = df_hist[df_hist["モデル"] == label]
                complete = sub[sub["状態"].isin(["的中", "不的中"])]
                n = len(complete)
                hits = int((complete["状態"] == "的中").sum())
                stake = int(complete["投資額"].sum())
                paid = int(complete["払戻額"].sum())
                summary.append({"モデル": label, "保存予想": int((sub["状態"] != "対象外").sum()),
                    "結果登録": n, "的中率": f"{hits/n*100:.1f}%" if n else "—",
                    "回収率": f"{paid/stake*100:.1f}%" if stake else "—", "損益": paid-stake if n else None})
            st.dataframe(pd.DataFrame(summary), hide_index=True, use_container_width=True)
            st.caption("旧形式の確定予想は旧AIとして集計します。新AIは保存済み予想のみ集計し、結果確定後の再計算は過去成績に含めません。")
            paired = df_hist[df_hist["モデル"].isin(["旧AI", "新AI"]) & df_hist["状態"].isin(["的中", "不的中"])]
            both_ids = paired.groupby("レースID")["モデル"].nunique()
            paired = paired[paired["レースID"].isin(both_ids[both_ids == 2].index)]
            if not paired.empty:
                paired_stats = []
                for label, sub in paired.groupby("モデル"):
                    stake = int(sub["投資額"].sum()); paid = int(sub["払戻額"].sum())
                    paired_stats.append({"モデル": label, "同条件レース数": len(sub),
                        "的中率": f"{(sub['状態']=='的中').mean()*100:.1f}%",
                        "回収率": f"{paid/stake*100:.1f}%" if stake else "—", "損益": paid-stake})
                st.markdown("**同一レース比較**")
                st.dataframe(pd.DataFrame(paired_stats), hide_index=True, use_container_width=True)
            st.markdown("**保存履歴の明細**")
            st.dataframe(df_hist.drop(columns=["レースID"]), hide_index=True, use_container_width=True)
            st.info("新AIの過去成績が0件でも、結果確定後に再計算した予想を過去の確定予想として補完しません。")
    except Exception as e:
        st.error("長期成績の取得に失敗: " + str(e))

    with st.expander("🧪 新AIの事後検証成績（正式成績とは別）"):
        try:
            retro_rows = []
            for folder in github_list_directories("retrospective"):
                for path in list_files(folder):
                    if not path.endswith(".json"):
                        continue
                    retro, _ = get_record(path)
                    if not retro or retro.get("classification") != "事後検証":
                        continue
                    rid = retro.get("race_id")
                    result = results.get(rid)
                    top4 = retro.get("top4", [])
                    if len(top4) != 4:
                        continue
                    hit, stake, paid = outcome({"top4": top4, "bet_unit": retro.get("bet_unit", 100)}, result) if result else (None,None,None)
                    retro_rows.append({"レース": retro.get("race_name"), "日付": retro.get("race_date"),
                        "新AI推奨4頭": ",".join(map(str,top4)), "状態": "未登録" if result is None else ("的中" if hit else "不的中"),
                        "投資額": stake, "払戻額": paid})
            if retro_rows:
                df_retro = pd.DataFrame(retro_rows)
                st.dataframe(df_retro, hide_index=True, use_container_width=True)
                completed = df_retro[df_retro["状態"].isin(["的中","不的中"])]
                if not completed.empty:
                    stake_total = int(completed["投資額"].sum()); paid_total = int(completed["払戻額"].sum())
                    st.write(f"事後検証：{len(completed)}件 / 的中率 {(completed['状態']=='的中').mean()*100:.1f}% / 回収率 {paid_total/stake_total*100:.1f}%" if stake_total else "投資額なし")
            else:
                st.info("事後検証の保存履歴はまだありません。")
        except Exception as exc:
            st.warning("事後検証履歴を取得できません: " + str(exc))

    with st.expander("🧹 10月17日・18日の結果だけリセット（予想は保護）"):
        st.warning("対象は2026-10-17（土）と2026-10-18（日）の確定結果のみです。旧AIの確定予想と新AIの保存予想は変更しません。")
        st.caption("実行前に結果JSONをGitHubの backups/ に複製します。予想履歴の重複は自動削除しません。")
        if st.button("対象結果と重複予想を確認", key="preview_oct_reset"):
            try:
                current_results = []
                for folder in github_list_directories("results"):
                    for path in list_files(folder):
                        rec, _ = get_record(path)
                        if rec and rec.get("race_date") in RESET_DATES:
                            current_results.append({"日付": rec["race_date"], "レース": rec.get("race_id"), "結果保存先": path})
                st.session_state["oct_reset_preview"] = current_results
                st.session_state["oct_prediction_preview"] = inspect_duplicate_predictions()
            except Exception as exc:
                st.error("事前確認失敗: " + str(exc))
        if "oct_reset_preview" in st.session_state:
            preview = st.session_state["oct_reset_preview"]
            st.write(f"リセット対象の結果ファイル: {len(preview)}件")
            if preview:
                st.dataframe(pd.DataFrame(preview), hide_index=True)
            predictions_preview = st.session_state.get("oct_prediction_preview", [])
            if predictions_preview:
                df_dup = pd.DataFrame(predictions_preview)
                dup = df_dup[df_dup.duplicated("レースID", keep=False)].sort_values("レースID")
                st.write(f"予想履歴の重複候補: {len(dup)}ファイル（削除しません）")
                if not dup.empty:
                    st.dataframe(dup, hide_index=True)
            st.warning("開催日・芝ダートの履歴照合が未完了のため、結果削除は安全ロック中です。予想履歴は保持されます。")
            phrase = st.text_input("実行確認：『結果だけリセット』と入力", key="oct_reset_phrase")
            if st.button("バックアップ後、対象結果をリセット", key="oct_reset_execute", disabled=True):
                # Safety lock: must audit historical race/date mappings before destructive reset.
                try:
                    deleted, backup = reset_results_with_backup()
                    st.success(f"結果 {len(deleted)}件をリセットしました。バックアップ先: {backup}")
                    st.session_state.pop("oct_reset_preview", None)
                    st.session_state.pop("oct_prediction_preview", None)
                    st.rerun()
                except Exception as exc:
                    st.error("処理を停止しました。GitHubの backups/ と results/ を確認してください: " + str(exc))

    with st.expander("🗑️ 予想履歴を手動削除（GitHub）"):
        st.warning("削除すると予想履歴が消えます。結果登録データは削除しません。")
        target_date = st.date_input("削除対象日", value=datetime.date(2026,10,19), key="delete_date")
        if st.button("削除候補を取得", key="load_delete"):
            try:
                st.session_state["delete_candidates"] = list_prediction_files_for_date(target_date.isoformat())
                st.session_state["delete_date_loaded"] = target_date.isoformat()
            except Exception as e:
                st.error(str(e))
        candidates = st.session_state.get("delete_candidates", []) if st.session_state.get("delete_date_loaded") == target_date.isoformat() else []
        selected = []
        for item in candidates:
            rec = item["record"]
            if st.checkbox(f"{rec.get('race_date')} {rec.get('race_name')} / {item['path']}", key="del_"+item["path"]):
                selected.append(item)
        st.caption(f"選択中：{len(selected)}件")
        confirm = st.text_input("削除する場合は『削除』と入力", key="delete_confirm")
        if st.button("選択した予想履歴を削除", disabled=not selected or confirm != "削除", key="delete_now"):
            success = 0
            for item in selected:
                try:
                    rec = item["record"]
                    delete_record_safely(item["path"], rec["race_id"], rec["race_date"])
                    success += 1
                except Exception as e:
                    st.error(f"{item['path']}: {e}")
            st.success(f"{success}件を削除しました")
            st.session_state.pop("delete_candidates", None)
            st.rerun()
