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

st.title("🏇 JRA 黄金パターン AI ダッシュボード [ガード強化版]")

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
    going_m = re.search(r"(?:^|\n)\s*(稍重|不良|良|重)\s*(?:\n|$)", t)
    rank = int(rank_m.group(1)) if rank_m else None
    field = int(field_m.group(1)) if field_m else None
    
    corner_pos = None
    corner_m = re.search(r"([1-9]\d*)[角コーナー]", t)
    if corner_m:
        corner_pos = int(corner_m.group(1))

    return {
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


def dirt_model(horses, target_distance=None, target_going=None):
    runs_all = [r for h in horses for r in h.get("dirt_histories", [])]
    def normalized_time(r):
        if r.get("time") is None or not r.get("going"):
            return None
        return r["time"] - GOING_SEC_PER_1000M[r["going"]] * r["distance"] / 1000

    def time_reference(r):
        peers = [normalized_time(q) for q in runs_all
                 if q["distance"] == r["distance"] and q.get("course") == r.get("course")
                 and normalized_time(q) is not None]
        return robust_scale(peers)

    total_horses = len(horses)
    for h in horses:
        components = {k: [] for k in ("time", "last3f", "distance", "pace", "rank_score", "gate_bias")}
        
        h_no = h.get("horse_no", 8)
        if total_horses > 1:
            gate_score = 50.0 + (h_no / total_horses) * 20.0
        else:
            gate_score = 60.0
        components["gate_bias"].append(float(np.clip(gate_score, 0, 100)))

        for r in h.get("dirt_histories", []):
            dist = r["distance"]
            ref = time_reference(r)
            t = normalized_time(r)
            if ref and t is not None:
                med, spread, sign = ref
                components["time"].append(float(np.clip(50 + 16*sign*(t-med)/spread, 0, 100)))
            
            finals = [q["last3f"] for q in runs_all if abs(q["distance"]-dist) <= 100 and q.get("last3f") is not None]
            fref = robust_scale(finals)
            if fref and r.get("last3f") is not None:
                med, spread, sign = fref
                components["last3f"].append(float(np.clip(50 + 16*sign*(r["last3f"]-med)/spread, 0, 100)))
            
            if r.get("rank") and r.get("field", 0) > 1:
                p_score = 100.0 * (r["field"] - r["rank"]) / (r["field"] - 1)
                components["rank_score"].append(float(np.clip(p_score, 0, 100)))

            corner_pos = r.get("corner_pos")
            if corner_pos and r.get("field", 0) > 1:
                front_bonus = max(0.0, 1.0 - (corner_pos - 1) / max(1, r.get("field", 1) - 1))
                components["pace"].append(float(np.clip(front_bonus * 100, 0, 100)))

            if target_distance and r.get("rank") and r.get("field", 0) > 1:
                closeness = max(0., 1.-abs(dist-target_distance)/800.)
                finish = (r["field"]-r["rank"])/(r["field"]-1)
                components["distance"].append(100*(.5*closeness+.5*finish)*closeness)

        # 【追加ガード】タイムまたは上り3Fのデータが両方とも無い場合は実力裏付けなしとして対象外(None)にする
        has_time = bool(components["time"])
        has_last3f = bool(components["last3f"])

        if not has_time or not has_last3f:
            h["ai_score"] = None
        else:
            weights = {"time":.20, "distance":.20, "last3f":.15, "pace":.15, "rank_score":.20, "gate_bias":.10}
            values = {k: round(float(np.mean(v)),2) if v else None for k,v in components.items()}
            present = [k for k,v in values.items() if v is not None]
            total = sum(weights[k] for k in present)
            score = sum(weights[k]*values[k] for k in present)/total if total else None
            
            if score is not None:
                h["ai_score"] = round(score, 2)
            else:
                h["ai_score"] = None
            
            h.update({f"{k}_score":values[k] for k in weights})
            h["evidence_coverage"] = round(100*total,1)
            
    return horses


def heading_date(raw):
    m = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", clean_text(raw))
    if not m:
        m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", clean_text(raw))
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
            surface_text = heading + "\n" + "\n".join(current.get("race_info", []))
            surface_text = unicodedata.normalize("NFKC", surface_text)
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
            current["is_dirt_race"] = bool(dirt_match or dirt_match_rev or dirt_marker) and not bool(turf_marker and not (dirt_match or dirt_match_rev or dirt_marker))
            current["surface_diagnostic"] = surface_text[:240]
            current["target_going"] = None
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
APP_VERSION = "dual-model-3.8-missing-data-guard"

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
            metrics, reason, _ = screen_scored_race(race, frame)
            evaluations[label] = {"metrics": metrics, "reason": reason, "df": frame}
        if any(x["metrics"] is not None for x in evaluations.values()):
            selected.append((race, evaluations))
        else:
            excluded.append((race["race_name"], "旧AI: " + str(evaluations["旧AI"]["reason"]) + " / 新AI: " + str(evaluations["新AI"]["reason"])))
    def priority(item):
        ev = item[1]
        return max((v["metrics"]["score"] for v in ev.values() if v["metrics"]), default=-1)
    selected.sort(key=priority, reverse=True)
    for race, _ in selected[max_recommendations:]:
        excluded.append((race["race_name"], "表示上限超過"))
    return selected[:max_recommendations], excluded


def screen_scored_race(race, df):
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
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:250]
        if e.code == 404 and method == "GET":
            return None
        raise RuntimeError(f"GitHub HTTP {e.code}: {body}") from e


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


def list_prediction_files_for_date(target_date):
    matches = []
    for folder in github_list_directories("predictions"):
        for path in list_files(folder):
            rec, _ = get_record(path)
            if rec and rec.get("race_date") == target_date:
                matches.append({"path": path, "record": rec})
    return matches


def list_files(directory):
    token, repo = github_config()
    url = "https://api.github.com/repos/" + repo + "/contents/" + urllib.parse.quote(directory, safe="/") + "?per_page=1000"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "JRA-Streamlit-History"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            items = json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 404:
            return []
        raise RuntimeError(f"GitHub一覧取得エラー HTTP {e.code}") from e
    return [x["path"] for x in items if x.get("type") == "file" and x["name"].endswith(".json")]


def race_key(date, race):
    return f"{date.isoformat()}_{race['course']}_{int(race['race_no']):02d}R"


def read_all_history():
    predictions, results = {}, {}
    for kind, target in (("predictions", predictions), ("results", results)):
        for folder in github_list_directories(kind):
            for path in list_files(folder):
                rec, _ = get_record(path)
                if rec and rec.get("race_id"):
                    target[rec["race_id"]] = rec
    return predictions, results


def github_list_directories(root):
    token, repo = github_config()
    url = "https://api.github.com/repos/" + repo + "/contents/" + root
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json", "User-Agent": "JRA-Streamlit-History"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return [x["path"] for x in json.loads(response.read().decode("utf-8")) if x["type"] == "dir"]
    except HTTPError as e:
        if e.code == 404:
            return []
        raise RuntimeError(f"履歴フォルダ取得失敗 HTTP {e.code}") from e


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
st.sidebar.header("📆 開催日（保存時に必須）")
sat_date = st.sidebar.date_input("土曜日の開催日", value=datetime.date.today() - datetime.timedelta(days=(datetime.date.today().weekday()+2)%7), key="sat_date")
sun_date = st.sidebar.date_input("日曜日の開催日", value=sat_date + datetime.timedelta(days=1), key="sun_date")


def render_races(day, date):
    selected, excluded = choose_dual(day)
    st.info(f"推奨候補 {len(selected)} レース・除外 {len(excluded)} レース")
    
    try:
        _, results_dict = read_all_history()
    except:
        results_dict = {}

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
                
                formatted_top = []
                for num in top:
                    if num in placed_set:
                        formatted_top.append(f"<span style='color: #2e7d32; font-weight: bold; font-size: 1.05rem;'>{num}番(入着)</span>")
                    else:
                        formatted_top.append(f"{num}番")
                
                rec_str = " ・ ".join(formatted_top) if ev["metrics"] else "対象外（参考：" + "・".join(map(str, top)) + "）"
                st.markdown(f"推奨4頭： {rec_str}", unsafe_allow_html=True)
                st.caption("選考通過" if ev["metrics"] else "選考対象外：" + str(ev["reason"]))

        with st.expander("両モデルの全馬指数・買い目"):
            for label, ev in evaluations.items():
                df = ev["df"]
                st.markdown("**" + label + "**")
                top = sorted(int(x) for x in df.head(4)["horse_no"])
                st.write("3連複4点：", " ／ ".join("-".join(map(str, x)) for x in itertools.combinations(top, 3)))
                cols = [c for c in ["horse_no", "name", "odds", "pop_rank", "ai_score", "rank_score_score", "pace_score", "gate_bias_score", "time_score", "last3f_score", "idx_rank"] if c in df.columns]
                st.dataframe(df[cols], hide_index=True, use_container_width=True)
        detected_date = race.get("race_date")
        verified = st.checkbox(f"{race['race_name']} の開催日が {date} であることを確認", key="datecheck_"+race_key(date,race)) if detected_date is None else True
        if st.button("💾 旧AI・新AIの予想を同時に確定保存", key="save_" + race_key(date, race), disabled=(not verified or (detected_date is not None and detected_date != date))):
            rec = dual_snapshot(date, race, evaluations, settings)
            path = f"predictions/{date.year}/{rec['race_id']}.json"
            try:
                if put_record(path, rec):
                    st.success("両モデルの予想を同時保存しました。")
                else:
                    st.warning("このレースはすでに保存済みです。")
            except Exception as e:
                st.error("保存失敗: " + str(e))
        st.divider()


t1, t2, t3, t4 = st.tabs(["📅 土曜推奨", "📅 日曜推奨", "📝 結果登録", "📊 長期成績"])
with t1:
    render_races("土曜日開催", sat_date)
with t2:
    render_races("日曜日開催", sun_date)

with t3:
    st.subheader("確定結果の登録・訂正")
    if st.button("🔄 保存済み履歴を読み直す", key="refresh_history"):
        st.rerun()
    try:
        predictions, results = read_all_history()
        if not predictions:
            st.info("保存済みの予想がありません。")
        else:
            ids = sorted(predictions, reverse=True)
            rid = st.selectbox("結果を登録・訂正するレース", ids,
                format_func=lambda k: predictions[k]["race_name"] + " / " + predictions[k]["race_date"] + (" 【登録済み】" if k in results else " 【未登録】"))
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
                    record = {
                        "race_id": rid, "race_date": pred["race_date"],
                        "top3": [int(a), int(b), int(c)],
                        "trio_payout_100yen": int(payout),
                        "saved_at_utc": old.get("saved_at_utc", now) if old else now,
                        "updated_at_utc": now,
                        "revision_history": list(old.get("revision_history", [])) if old else [],
                    }
                    path = f"results/{pred['race_date'][:4]}/{rid}.json"
                    if put_record(path, record, overwrite=bool(old)):
                        st.success("結果を保存しました。")
                        st.rerun()
    except Exception as e:
        st.error("履歴取得に失敗: " + str(e))

with t4:
    st.subheader("長期成績")
    try:
        predictions, results = read_all_history()
        records = []
        for rid, pred in predictions.items():
            result = results.get(rid)
            model_items = pred.get("models")
            if model_items is None:
                model_items = {"旧AI（過去保存）": {"top4": pred["top4"], "eligible": True, "metrics": pred.get("metrics", {})}}
            for label, model in model_items.items():
                if len(model.get("top4", [])) != 4:
                    continue
                hit, stake, received = outcome({"top4": model["top4"], "bet_unit": pred.get("bet_unit", 100)}, result) if result and model.get("eligible",True) else (None, None, None)
                metrics = model.get("metrics"] or {}
                records.append({"日付": pred["race_date"], "レース": pred["race_name"],
                    "推奨4頭": ",".join(map(str, model["top4"])),
                    "状態": "対象外" if not model.get("eligible",True) else ("未登録" if result is None else ("的中" if hit else "不的中")),
                    "投資額": stake, "払戻額": received,
                    "損益": (received-stake) if (result and stake is not None) else None, "モデル": label})
        df_hist = pd.DataFrame(records)
        if df_hist.empty:
            st.info("まだ履歴がありません。")
        else:
            completed = df_hist[df_hist["状態"].isin(["的中", "不的中"])]
            n = len(completed)
            hits = int((completed["状態"] == "的中").sum())
            invested = int(completed["投資額"].sum())
            paid = int(completed["払戻額"].sum())
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("結果登録", n)
            c2.metric("的中率", f"{hits/n*100:.1f}%" if n else "—")
            c3.metric("回収率", f"{paid/invested*100:.1f}%" if invested else "—")
            c4.metric("累計損益", f"{paid-invested:+,}円")
            st.dataframe(df_hist, hide_index=True, use_container_width=True)
    except Exception as e:
        st.error("長期成績の取得に失敗: " + str(e))
