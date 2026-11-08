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
import io
import zipfile
import datetime
import calendar
import urllib.parse
import time
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

st.title("🏇 JRA 黄金パターン AI ダッシュボード【単勝・3連複人気取得対応】")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 設定")
    min_coverage = st.slider("最低過去走データ保有率 (%)", 50, 100, 75, 5)
    min_gap = st.slider("上位4頭と5位の最低指数差（※旧AIのみ適用）", 0.0, 20.0, 3.0, 0.5)
    min_confidence = st.slider("推奨最低評価点（的中確率ではありません）", 40, 95, 90, 5)
    max_recommendations = st.slider("1日あたりの指数候補表示上限（購入数ではありません）", 1, 5, 5)
    min_top_history = st.slider("上位4頭の最低過去走数", 1, 4, 4)
    min_top_dirt = st.slider("上位4頭の最低ダート経験馬数", 2, 4, 4)
    bet_unit = st.number_input("1点あたりの金額 (円)", min_value=100, max_value=10000, value=100, step=100, key="box_unit")
    if st.button("🔄 Google Driveデータを更新（直接取得は保持）"):
        # 過去走と3連複の直接取得済みデータは消さない。
        # 条件変更・Driveの更新は取得済みスナップショットを上書きしない。
        # ボタンは関数定義より先に描画されるので全キャッシュを安全に消す。
        st.cache_data.clear()
        st.session_state["drive_refresh_notice"] = "Driveの再読み込みを実施しました。スマホ直接取得データは維持しています。"
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



def parse_prior_history_date(value):
    """成績文字列から実開催日を取得。不明な履歴は予想に使わない。"""
    value = clean_text(value)
    m = re.search(r"(20\d{2})\s*(?:年|[-/])\s*(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})\s*日?", value)
    if not m:
        return None
    try:
        return datetime.date(*(int(x) for x in m.groups()))
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
                current = {**heading, "horses": [], "heading_raw": " ".join(cells),
                           "race_info": [], "sheet_name": sheet_name,
                           "race_date": heading_date(" ".join(cells)) or heading_date(sheet_name),
                           "除外した当日以降の履歴": 0, "除外した日付不明履歴": 0}
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
        # Some exported workbooks have an entirely empty 馬番 column.
        # Preserve the horse rows for analysis, but never regard an inferred
        # sequential position as a verified betting horse number.
        inferred_number = False
        try:
            horse_no = int(float(cells[hi]))
            if not 1 <= horse_no <= 18 or float(cells[hi]) != horse_no:
                continue
        except (ValueError, TypeError):
            if not cells[ni] or not previous_indices:
                continue
            if not any(i < len(cells) and cells[i] for i in previous_indices):
                continue
            horse_no = len(current["horses"]) + 1
            if horse_no > 18:
                continue
            inferred_number = True
        if any(h["horse_no"] == horse_no for h in current["horses"]):
            continue
        if inferred_number:
            current["horse_numbers_unverified"] = True
        field = cells[ni]
        name = field.split("\n")[0].strip()
        if not name:
            continue
        odds_match = ODDS_PATTERN.search(field)
        odds_idx = columns.get("odds")
        odds = numeric_odds(cells[odds_idx]) if odds_idx is not None and odds_idx < len(cells) else (float(odds_match.group(1)) if odds_match else None)
        popularity = int(odds_match.group(2)) if odds_match else None

        histories = [cells[i] for i in previous_indices if i < len(cells) and cells[i]]
        # 発走前の履歴だけ。今回の開催日と同日・未来・日付不明は指数へ渡さない。
        valid_histories = []
        cutoff = current.get("race_date")
        for h in histories:
            run_date = parse_prior_history_date(h)
            if run_date is None or not isinstance(cutoff, datetime.date):
                current["除外した日付不明履歴"] += 1
            elif run_date >= cutoff:
                current["除外した当日以降の履歴"] += 1
            else:
                valid_histories.append(h)
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
            "horse_no_verified": not inferred_number,
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


def summarize_history_exclusions(races):
    return {
        "当日以降": sum(int(r.get("除外した当日以降の履歴", 0)) for r in races),
        "日付不明": sum(int(r.get("除外した日付不明履歴", 0)) for r in races),
    }


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
            diagnostics.append(f"{day}: {method}から {len(parsed)} レースを取得 / 馬番空欄レース {sum(bool(r.get('horse_numbers_unverified')) for r in parsed)}件")
            if not parsed:
                errors.append(f"{day}: Excelは取得できましたが、レースを解析できませんでした")
        except Exception as exc:
            errors.append(f"{day}: {exc}")
    return races, errors, diagnostics


# ============================================================
# スマートフォンから直接取得（Colab不要）
# netkeiba公開ページをStreamlitサーバー側で取得する。
# 旧AI・新AIのスコア関数は改変しない。
# ============================================================

def mobile_browser_session():
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.6",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session


def mobile_get_soup(url, session=None, tries=3):
    import requests
    from bs4 import BeautifulSoup
    session = session or mobile_browser_session()
    failures = []
    for attempt in range(1, tries + 1):
        try:
            response = session.get(url, timeout=(8, 23), allow_redirects=True)
            response.raise_for_status()
            if len(response.content) < 250:
                raise RuntimeError("HTML本文が短すぎます")
            soup = BeautifulSoup(response.content, "html.parser")
            body_text = soup.get_text(" ", strip=True)[:500].lower()
            if any(t in body_text for t in ("access denied", "captcha", "アクセスが集中")):
                raise RuntimeError("提供元がアクセスを制限しています")
            return soup
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            failures.append(f"{attempt}回目 HTTP {status}")
            if status in (403, 404):
                break
        except Exception as exc:
            failures.append(f"{attempt}回目 {type(exc).__name__}: {str(exc)[:120]}")
        if attempt < tries:
            time.sleep(min(attempt * 1.0, 2.5))
    raise RuntimeError(" / ".join(failures))


def mobile_race_list(soup, target_date, min_race=6, max_race=12):
    """リンクだけでなく、ページ内JSON・埋込データのレースIDも検索。"""
    source = str(soup)
    ids = re.findall(r"(?:race_id(?:=|[\\\"': ]+)|[\\\"'])(20\d{10})(?:[\\\"'&]|$)", source)
    ids += re.findall(r"race_id(?:=|%3[Dd])(20\d{10})", source)
    valid = []
    for rid in dict.fromkeys(ids):
        if (rid.startswith(str(target_date.year))
                and rid[4:6] in TRIO_VENUE_CODES.values()
                and min_race <= int(rid[-2:]) <= max_race):
            valid.append(rid)
    return sorted(valid)


def mobile_schedule_venues(target_date, session):
    """JRA公式の開催日別番組表から (競馬場, 開催回, 開催日) を取得する。

    予定番組表は変更され得るため、得られたIDは後段で出走表と照合する。
    """
    url = (f"https://jra.jp/keiba/calendar{target_date.year}/"
           f"{target_date.year}/{target_date:%m}/{target_date:%m%d}.html")
    soup = mobile_get_soup(url, session=session, tries=2)
    # タグ間の空白・全角表記差を許容する。
    text = unicodedata.normalize("NFKC", soup.get_text(" ", strip=True))
    compact = re.sub(r"\s+", "", text)
    date_token = f"{target_date.year}年{target_date.month}月{target_date.day}日"
    if date_token not in compact:
        raise RuntimeError("JRA番組表の開催日を確認できません")
    venues_pattern = "|".join(COURSES)
    result = []
    for kai_s, venue, day_s in re.findall(
        rf"(?<!\d)(\d{{1,2}})回({venues_pattern})(\d{{1,2}})日", compact
    ):
        kai, day = int(kai_s), int(day_s)
        if venue in TRIO_VENUE_CODES and 1 <= kai <= 9 and 1 <= day <= 12:
            item = (venue, kai, day)
            if item not in result:
                result.append(item)
    if not result:
        raise RuntimeError("JRA番組表から開催場・回次・日次を認識できません")
    # 通常の中央競馬開催は最大3場。想定外の場合は自動生成しない。
    if len(result) > 3:
        raise RuntimeError(f"開催情報が多すぎます（{len(result)}場）")
    return result, url


# 取得エンジンの稼働版を画面・診断・バックアップへ表示する。
# 旧版か新版か区別できない状態での調査を防ぐ。
MOBILE_FETCH_BUILD = "2026-11-08-verified-id-v3"

# この2開催日はJRA公式の開催情報および実在する出走表IDを照合済み。
# 対象日以外に適用しない。候補生成後も個別出走表側の開催日を検証する。
MOBILE_CONFIRMED_SESSIONS = {
    datetime.date(2026, 11, 7): (("東京", 5, 1), ("京都", 5, 1), ("福島", 3, 1)),
    datetime.date(2026, 11, 8): (("東京", 5, 2), ("京都", 5, 2), ("福島", 3, 2)),
}


def mobile_discover_race_ids(target_date, session, min_race=6, max_race=12):
    """取得一覧が空でも、確認済み開催日のID探索を妨げない。

    重要: 2026/11/08の確定開催IDはnetkeiba一覧ページより先に生成する。
    旧版は一覧が空で候補0件のまま停止したため、通信結果への依存をなくす。
    未確認日には公式番組表から開催場/回次/日次を取得し、個別ページで再検証。
    """
    log = [f"取得エンジン={MOBILE_FETCH_BUILD}"]
    sessions = MOBILE_CONFIRMED_SESSIONS.get(target_date)

    # この分岐はネットワーク通信が失敗しても必ず候補21件（3場 x 7R）を返す。
    if sessions:
        result = []
        for venue, kai, day in sessions:
            for n in range(min_race, max_race + 1):
                result.append(f"{target_date.year:04d}{TRIO_VENUE_CODES[venue]}{kai:02d}{day:02d}{n:02d}")
        log.append(f"公式開催日程確認済み：{target_date:%Y-%m-%d}、{len(sessions)}場、候補{len(result)}件")
        log.append("候補IDは出走表ページの開催日・レースID照合後に採用")
        return sorted(result), log

    # その他の日もできる限り公式の当日番組表からIDを生成する。
    # スケジュールページが利用できない場合にのみnetkeiba一覧へフォールバックする。
    try:
        sessions, schedule_url = mobile_schedule_venues(target_date, session)
        result = [
            f"{target_date.year:04d}{TRIO_VENUE_CODES[venue]}{kai:02d}{day:02d}{n:02d}"
            for venue, kai, day in sessions
            for n in range(min_race, max_race + 1)
        ]
        log.append(f"JRA公式開催日程: {schedule_url}、{len(sessions)}場、候補{len(result)}件")
        return sorted(set(result)), log
    except Exception as exc:
        log.append(f"JRA公式日程から取得できず: {type(exc).__name__}: {str(exc)[:160]}")

    urls = [
        f"https://race.netkeiba.com/top/race_list.html?kaisai_date={target_date:%Y%m%d}",
        f"https://race.netkeiba.com/top/race_list.html?date={target_date:%Y%m%d}",
        f"https://race.netkeiba.com/top/race_list.html?kaisai_date={target_date:%Y%m%d}&kaisai_id=",
    ]
    found_ids = set()
    for url in urls:
        try:
            soup = mobile_get_soup(url, session=session, tries=2)
            found = mobile_race_list(soup, target_date, min_race, max_race)
            found_ids.update(found)
            log.append(f"{url} 候補{len(found)}件")
        except Exception as exc:
            log.append(f"{url} {type(exc).__name__}: {str(exc)[:120]}")
        if found_ids:
            break
    return sorted(found_ids), log


def mobile_validate_race_page(soup, rid, target_date):
    """別日への転送や無関係なレースを除外。日付の検証ができない場合は採用しない。"""
    metadata = " ".join(x.get_text(" ", strip=True) for x in soup.select(
        ".RaceData01, .RaceData02, .RaceData03, .RaceList_DateList, .RaceName, .RaceData"))
    raw = str(soup)
    expected = target_date.strftime("%Y%m%d")
    date_tokens = [expected, target_date.strftime("%Y/%m/%d"), target_date.strftime("%Y-%m-%d"),
                   f"{target_date.year}年{target_date.month}月{target_date.day}日"]
    if not any(token in raw or token in metadata for token in date_tokens):
        raise RuntimeError("ページ内で対象開催日を検証できません（別日・HTML変更の可能性）")
    # ページに別レースIDが明記されている場合は誤取得を防ぐ。
    canonical = soup.select_one('link[rel="canonical"]')
    if canonical:
        match = re.search(r"race_id=(20\d{10})", canonical.get("href", ""))
        if match and match.group(1) != rid:
            raise RuntimeError(f"別レースへの転送: {match.group(1)}")
    return True


def mobile_race_surface(soup):
    # 出走表のレース条件欄だけを使う。ページ全文の芝・ダート混在は使わない。
    selectors = (".RaceData01", ".RaceData02", ".RaceData03", ".RaceData", ".race_data")
    metadata = " ".join(
        el.get_text(" ", strip=True)
        for sel in selectors for el in soup.select(sel)
    )
    normalized = unicodedata.normalize("NFKC", metadata)
    patterns = [
        (r"(?:ダート|ダ)\s*([0-9]{3,4})\s*m?", "ダート"),
        (r"(?:芝)\s*([0-9]{3,4})\s*m?", "芝"),
        (r"(?:障害|障)\s*([0-9]{3,4})\s*m?", "障害"),
        (r"([0-9]{3,4})\s*(?:m|メートル)\s*[（(]\s*(ダート|芝|障害)", "逆順"),
    ]
    found = []
    for pattern, label in patterns:
        for m in re.finditer(pattern, normalized):
            surface = m.group(2) if label == "逆順" else label
            found.append((surface, int(m.group(1))))
    if not found:
        return "不明", None, metadata
    surfaces = {a for a, _ in found}
    if len(surfaces) != 1:
        return "不明", None, metadata
    surface = found[0][0]
    distances = {distance for s, distance in found if s == surface}
    if len(distances) != 1:
        return "不明", None, metadata
    return surface, distances.pop(), metadata


def mobile_visible_text(node):
    return node.get_text(" ", strip=True) if node else ""


def mobile_number(value, lo=1, hi=18):
    text = unicodedata.normalize("NFKC", str(value)).strip()
    m = re.fullmatch(r"\d{1,3}", text)
    if m:
        n = int(text)
        return n if lo <= n <= hi else None
    return None


def mobile_parse_shutuba(soup, rid, target_date):
    venue = next((name for name, code in TRIO_VENUE_CODES.items() if code == rid[4:6]), None)
    if not venue:
        raise ValueError("競馬場コードが不明")
    surface, distance, race_metadata = mobile_race_surface(soup)
    course_title_node = soup.select_one(".RaceName")
    race_title = mobile_visible_text(course_title_node).strip() or f"{int(rid[-2:])}R"
    race_num = int(rid[-2:])
    text = unicodedata.normalize("NFKC", " ".join(
        mobile_visible_text(soup.select_one(sel))
        for sel in (".RaceData01", ".RaceData02", ".RaceData03")
    ))
    start_m = re.search(r"(?<!\d)(\d{1,2}):(\d{2})\s*発走", text)
    if not start_m:
        start_m = re.search(r"発走\s*(\d{1,2}):(\d{2})", text)
    start_text = (f"発走時刻：{int(start_m.group(1))}時{int(start_m.group(2))}分" if start_m else "発走時刻不明")
    heading = (f"{target_date.year}年{target_date.month}月{target_date.day}日 "
               f"第{int(rid[6:8])}回{venue}第{int(rid[8:10])}日 {start_text} "
               f"{race_num}R {surface}{distance if distance else ''}m")
    race = {
        "course": venue, "race_no": race_num, "race_title": race_title,
        "race_name": f"{venue} {race_num}R {race_title}",
        "race_date": target_date, "heading_raw": heading,
        "race_info": [race_metadata], "sheet_name": "スマホ直接取得(netkeiba)",
        "identified": True, "netkeiba_race_id": rid, "horses": [],
        "is_dirt_race": surface == "ダート", "surface_conflict": surface == "不明",
        "surface_diagnostic": race_metadata[:240], "target_distance": distance,
        "target_going": None, "horse_numbers_unverified": False,
        "除外した当日以降の履歴": 0, "除外した日付不明履歴": 0,
    }
    if surface != "ダート":
        return race, [], "芝・障害のため対象外" if surface != "不明" else "コース条件不明"
    table = soup.select_one("table.ShutubaTable, table.RaceTable01")
    if table is None:
        raise RuntimeError("出走表テーブルが取得できません（アクセス制限・HTML変更の可能性）")
    entrants = []
    problems = []
    rows = table.select("tbody tr") or table.select("tr")
    for tr in rows:
        horse_link = tr.select_one('a[href*="/horse/"]')
        if horse_link is None:
            continue
        href = horse_link.get("href", "")
        hm = re.search(r"/horse/(\d{8,12})", href)
        if not hm:
            problems.append("馬IDなし")
            continue
        horse_id = hm.group(1)
        name = mobile_visible_text(horse_link)
        node = tr.select_one("td.Umaban, td[class*='Umaban']")
        horse_number = mobile_number(mobile_visible_text(node)) if node else None
        if horse_number is None:
            # 馬番を行番号から推定しない。
            problems.append(f"馬番未確定:{name}")
            continue
        odds = None
        for selector in ("td.Odds", "td[class*='Odds']", "td.Popular", "td[class*='Popular']"):
            cell = tr.select_one(selector)
            if cell:
                m = re.search(r"(?<!\d)(\d+\.\d+)(?!\d)", mobile_visible_text(cell))
                if m:
                    odds = float(m.group(1))
                    break
        popularity = None
        for selector in ("td.Ninki", "td[class*='Ninki']", "td.Rank", "[class*='NinkiRank']"):
            cell = tr.select_one(selector)
            if cell:
                m = re.search(r"(?:^|\s)(\d{1,2})(?:番人気)?(?:\s|$)", mobile_visible_text(cell))
                if m:
                    popularity = mobile_number(m.group(1))
                    break
        entrants.append({
            "レースID":rid, "開催日":target_date.isoformat(), "馬番":horse_number,
            "馬名":name, "馬ID":horse_id, "オッズ":odds, "人気":popularity,
        })
    if not entrants:
        raise RuntimeError("出走表から有効な馬番・馬名・馬IDを取得できません")
    nums = [row["馬番"] for row in entrants]
    if len(nums) != len(set(nums)):
        problems.append("馬番重複")
    official_match = re.search(r"(\d{1,2})\s*頭", unicodedata.normalize("NFKC", race_metadata))
    if official_match and len(entrants) != int(official_match.group(1)):
        problems.append(f"頭数不一致:{len(entrants)}/{official_match.group(1)}")
    if problems:
        race["horse_numbers_unverified"] = True
    return race, entrants, "; ".join(problems)


def mobile_horse_histories(soup, horse_id, target_date, limit=None):
    """競走成績専用ページを解析。列位置が変わっても検証して誤データを除外する。"""
    tables = soup.select("table.db_h_race_results, table[class*='db_h_race_results']")
    if not tables:
        title = mobile_visible_text(soup.title)[:60] if soup.title else "タイトルなし"
        raise RuntimeError(f"競走成績テーブルなし（専用URLの応答内容を確認：{title}）")

    aliases = {
        "日付": {"日付", "年月日"}, "開催": {"開催", "場所"},
        "頭数": {"頭数", "出走頭数"}, "着順": {"着順", "着"},
        "タイム": {"タイム", "走破タイム"}, "着差": {"着差"},
        "上り": {"上り", "上がり", "上り3F", "上がり3F", "上3F"},
        "距離": {"距離"}, "馬場": {"馬場", "馬場状態"},
        "レース名": {"レース名", "競走名"}, "馬番": {"馬番"},
        "人気": {"人気"}, "通過": {"通過"}, "ペース": {"ペース"},
    }
    def norm(value):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))
    keymap = {norm(a): key for key, alt in aliases.items() for a in alt}
    date_re = re.compile(r"(20\d{2})[./年-](\d{1,2})[./月-](\d{1,2})")
    dist_re = re.compile(r"^(?:ダート|ダ|芝|障害|障)\s*\d{3,4}\s*m?$", re.I)
    time_re = re.compile(r"^\d{1,2}:\d{2}\.\d$")
    final_re = re.compile(r"^\d{2}\.\d$")
    going_set = {"良", "稍重", "重", "不良"}

    def looks_like(value, key):
        v = norm(value)
        if key == "日付":
            return bool(date_re.search(v))
        if key == "距離":
            return bool(dist_re.fullmatch(v))
        if key == "タイム":
            return bool(time_re.fullmatch(v))
        if key == "馬場":
            return v in going_set
        if key == "着順":
            return bool(re.fullmatch(r"(?:[1-9]|1[0-8])", v))
        if key == "頭数":
            return bool(re.fullmatch(r"(?:[2-9]|1[0-8])", v))
        if key == "上り":
            return bool(final_re.fullmatch(v) and 28.0 <= float(v) <= 55.0)
        return True

    def by_verified_headers(headers, vals):
        # 列数一致だけでは安全ではない。対象の値も型検証して採用する。
        if len(headers) != len(vals):
            return None
        result = {k: v for k, v in zip(headers, vals) if k}
        required = ("日付", "距離", "頭数", "着順", "タイム")
        if not all(result.get(k) and looks_like(result[k], k) for k in required):
            return None
        if result.get("上り") and not looks_like(result["上り"], "上り"):
            result.pop("上り", None)
        if result.get("馬場") and not looks_like(result["馬場"], "馬場"):
            result.pop("馬場", None)
        return result

    def verified_fallback(vals):
        # netkeibaの有料指標列がHTML上で欠ける場合、ヘッダー位置がずれる。
        # その場合は日付・距離・着順・頭数・走破タイムの各値で必ず検証する。
        if len(vals) < 18 or not date_re.search(norm(vals[0])):
            return None
        distance_idxs = [i for i in range(10, min(len(vals), 20)) if looks_like(vals[i], "距離")]
        if len(distance_idxs) != 1:
            return None
        di = distance_idxs[0]
        # 距離列の直前に着順（-3列）、頭数（-8列）がある標準レイアウト。
        if di < 8 or not looks_like(vals[di-3], "着順") or not looks_like(vals[di-8], "頭数"):
            return None
        time_idxs = [i for i in range(di+1, min(len(vals), di+9)) if looks_like(vals[i], "タイム")]
        if len(time_idxs) != 1:
            return None
        ti = time_idxs[0]
        going_values = [norm(v) for v in vals[di+1:ti] if norm(v) in going_set]
        result = {
            "日付": vals[0], "開催": vals[1], "頭数": vals[di-8],
            "着順": vals[di-3], "距離": vals[di], "タイム": vals[ti],
            "馬場": going_values[0] if len(going_values) == 1 else "",
            "レース名": vals[4] if len(vals) > 4 else "",
        }
        if ti + 1 < len(vals) and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", norm(vals[ti+1])):
            result["着差"] = norm(vals[ti+1])
        # 通過→ペース→上り は連続する。上り候補を別の指数と取り違えない。
        # 後半の最初のペース列の直後にある値が実際に28~55秒なら採用。
        pace_re = re.compile(r"^\d{2}\.\d\s*-\s*\d{2}\.\d$")
        paces = [i for i in range(ti+2, len(vals)) if pace_re.fullmatch(norm(vals[i]))]
        if len(paces) == 1 and paces[0] + 1 < len(vals):
            next_value = norm(vals[paces[0]+1])
            if looks_like(next_value, "上り"):
                result["上り"] = next_value
        return result

    data = []
    excluded_today, excluded_undated, rows_seen, rejected = 0, 0, 0, 0
    for table in tables:
        headers = None
        for tr in table.select("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            vals = [mobile_visible_text(cell) for cell in cells]
            keys = [keymap.get(norm(v), "") for v in vals]
            if "日付" in keys and "距離" in keys:
                headers = keys
                continue
            if not tr.find("td", recursive=False):
                continue
            rows_seen += 1
            # まず厳密なヘッダー照合。それが失敗したら値ベースで安全に解析。
            row = by_verified_headers(headers, vals) if headers else None
            if row is None:
                row = verified_fallback(vals)
            if row is None:
                rejected += 1
                continue
            dm = date_re.search(norm(row["日付"]))
            if not dm:
                excluded_undated += 1
                continue
            try:
                run_date = datetime.date(*map(int, dm.groups()))
            except ValueError:
                excluded_undated += 1
                continue
            if run_date >= target_date:
                excluded_today += 1
                continue
            row["日付"] = run_date.isoformat()
            row["馬ID"] = horse_id
            data.append(row)
            if limit and len(data) >= limit:
                break
        if data:
            break
    if not data and rows_seen and rejected == rows_seen:
        raise RuntimeError(f"競走成績表の列を安全に解析できません（行{rows_seen}件、解析不一致{rejected}件）")
    # 0件でも「新馬で本当に過去走なし」と「解析不能」を混同させない。
    if rows_seen == 0:
        # 出走前の新馬は履歴ゼロで正常。
        return [], 0, 0
    data.sort(key=lambda r: r["日付"], reverse=True)
    return data, excluded_today, excluded_undated


def mobile_history_run_string(r):
    # 元のExcel履歴パーサーに渡すための文字列（指数ロジックは変更しない）。
    distance = unicodedata.normalize("NFKC", r.get("距離", ""))
    dist_m = re.search(r"(?:ダート|ダ|芝)\s*([0-9]{3,4})", distance)
    is_dirt = bool(re.search(r"(?:ダート|ダ)\s*\d{3,4}", distance))
    if not dist_m:
        dist_m = re.search(r"([0-9]{3,4})\s*(?:ダート|ダ|芝)", distance)
        is_dirt = bool(re.search(r"[0-9]{3,4}\s*(?:ダート|ダ)", distance))
    d = int(dist_m.group(1)) if dist_m else None
    surface_text = f"{d}{'ダ' if is_dirt else '芝'}" if d else distance
    rank = unicodedata.normalize("NFKC", r.get("着順", ""))
    rank_m = re.fullmatch(r"\s*(\d{1,2})\s*", rank)
    rank_text = f"{rank_m.group(1)}着" if rank_m else rank
    field = r.get("頭数", "")
    field_m = re.search(r"\d{1,2}", str(field))
    field_text = f"{field_m.group(0)}頭" if field_m else ""
    last3f = unicodedata.normalize("NFKC", r.get("上り", ""))
    margin = unicodedata.normalize("NFKC", r.get("着差", ""))
    margin_text = f"({margin})" if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", margin) else ""
    going = unicodedata.normalize("NFKC", r.get("馬場", ""))
    course = re.sub(r"[^一-龥ぁ-んァ-ン]", "", r.get("開催", ""))
    venue = next((v for v in COURSES if v in course), "")
    return "\n".join([r["日付"].replace("-", "/"), venue, field_text, rank_text,
                      surface_text + " " + going, r.get("タイム", ""),
                      "3F" + last3f if re.fullmatch(r"\d{2}\.\d", last3f) else "",
                      margin_text])


def mobile_horse_from_runs(entry, runs, target_date):
    all_before = [r for r in runs if isinstance(r.get("日付"), str) and r["日付"] < target_date.isoformat()]
    # 既存Excelが4走分のため、指数の入力は直近4走に揃える。全履歴はCSVに残す。
    latest = sorted(all_before, key=lambda r: r["日付"], reverse=True)[:4]
    texts = [mobile_history_run_string(r) for r in latest]
    time_score, last3f_score = parse_horse_history(texts[0] if texts else "")
    scores = []
    dirt_runs = 0
    for txt in texts:
        ranking = re.search(r"(?<!\d)(\d{1,2})着", txt)
        field = re.search(r"(?<!\d)(\d{1,2})頭", txt)
        is_dirt = bool(re.search(r"\d{3,4}\s*ダ", txt))
        if is_dirt:
            dirt_runs += 1
        if ranking and field:
            rank, total = int(ranking.group(1)), int(field.group(1))
            if total > 1 and 1 <= rank <= total:
                scores.append((100 * (total-rank) / (total-1), is_dirt))
    weighted = [(value, 1.0 if dirt else .65) for value, dirt in scores]
    relative = sum(v*w for v,w in weighted)/sum(w for _,w in weighted) if weighted else None
    dirt_scores = [value for value,dirt in scores if dirt]
    return {
        "horse_no":int(entry["馬番"]), "name":entry["馬名"],
        "horse_no_verified":True, "horse_id":entry["馬ID"],
        "pop_rank":entry.get("人気"), "odds":entry.get("オッズ"),
        "time_index":time_score, "last3f_index":last3f_score,
        "track_aptitude":75.0, "history_count":len(texts), "dirt_runs":dirt_runs,
        "relative_score":relative,
        "dirt_score":sum(dirt_scores)/len(dirt_scores) if dirt_scores else None,
        "dirt_histories":[v for v in (parse_dirt_run(txt) for txt in texts) if v],
    }


def mobile_fetch_date(target_date, min_race=6, max_race=12):
    """レース一覧・出走表・過去成績を取得して、アプリ既存形式に変換。"""
    import concurrent.futures
    session = mobile_browser_session()
    race_ids, discovery_log = mobile_discover_race_ids(target_date, session, min_race, max_race)
    if not race_ids:
        raise RuntimeError("レースID候補が0件（取得版:" + MOBILE_FETCH_BUILD + "）。取得診断: " + " / ".join(discovery_log))
    progress = st.progress(0.0, text="出走表を取得中")
    race_records = []
    entries = []
    diagnostics = [{"レースID":"", "処理結果":"レースID探索", "取得頭数":0,
                    "理由": msg, "取得日時JST":datetime.datetime.now(TRIO_JST).isoformat(timespec="seconds")}
                   for msg in discovery_log]
    for i, rid in enumerate(race_ids, 1):
        stamp = datetime.datetime.now(TRIO_JST).isoformat(timespec="seconds")
        try:
            race_soup = mobile_get_soup(
                f"https://race.netkeiba.com/race/shutuba.html?race_id={rid}",
                session=session, tries=3)
            mobile_validate_race_page(race_soup, rid, target_date)
            race, horses, message = mobile_parse_shutuba(race_soup, rid, target_date)
            if race["is_dirt_race"]:
                if horses:
                    race_records.append(race)
                    entries.extend(horses)
                    result = "ダート出走表取得（馬番要確認）" if race["horse_numbers_unverified"] else "ダート出走表取得成功"
                else:
                    result = "ダート出走表なし"
            else:
                result = "ダート以外対象外" if not race["surface_conflict"] else "コース不明"
            diagnostics.append({"レースID":rid,"処理結果":result,"取得頭数":len(horses),
                                "理由":message,"取得日時JST":stamp})
        except Exception as exc:
            diagnostics.append({"レースID":rid,"処理結果":"取得失敗","取得頭数":0,
                                "理由":str(exc)[:400],"取得日時JST":stamp})
        progress.progress(i / max(len(race_ids),1) * .3,
                          text=f"出走表 {i}/{len(race_ids)}件（ダート{len(race_records)}件）")
        time.sleep(.35)
    if not race_records:
        progress.empty()
        raise RuntimeError("ダート出走表を取得できませんでした。" + str(diagnostics[-5:]))
    entries_by_horse = {e["馬ID"]:e for e in entries}
    # 新馬戦の出走馬には、指数用の過去走が原則ありません。
    # netkeibaの競走成績表がないことを「通信エラー」と誤カウントしない。
    # ただし、非新馬の通信失敗・解析失敗は従来どおり欠損として記録する。
    debut_race_ids = {
        r["netkeiba_race_id"] for r in race_records
        if "新馬" in str(r.get("race_title", ""))
    }
    debut_ids = {
        e["馬ID"] for e in entries if e["レースID"] in debut_race_ids
    }
    eligible_horses = [one for one in entries_by_horse.items() if one[0] not in debut_ids]
    histories = {hid: [] for hid in debut_ids}
    horse_errors = {}
    excluded_same_day = 0
    excluded_no_date = 0
    skips_by_horse = {hid: (0, 0) for hid in debut_ids}
    for race in race_records:
        if race["netkeiba_race_id"] in debut_race_ids:
            n = sum(e["レースID"] == race["netkeiba_race_id"] for e in entries)
            diagnostics.append({
                "レースID": race["netkeiba_race_id"],
                "処理結果": "新馬戦・過去走取得対象外",
                "取得頭数": n,
                "理由": "新馬戦は過去走0件が正常。履歴取得失敗には含めない（指数対象外）。",
                "取得日時JST": datetime.datetime.now(TRIO_JST).isoformat(timespec="seconds"),
            })
    def fetch_horse(one):
        hid, entry = one
        try:
            horse_soup = mobile_get_soup(f"https://db.netkeiba.com/horse/result/{hid}/", tries=2)
            run_list, excluded_today, excluded_unknown = mobile_horse_histories(horse_soup, hid, target_date)
            for run in run_list:
                run["馬名"] = entry["馬名"]
            return hid, run_list, excluded_today, excluded_unknown, ""
        except Exception as exc:
            return hid, [], 0, 0, str(exc)[:250]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch_horse, one) for one in eligible_horses]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            hid, rows, skip_day, skip_unknown, error = future.result()
            histories[hid] = rows
            skips_by_horse[hid] = (skip_day, skip_unknown)
            excluded_same_day += skip_day
            excluded_no_date += skip_unknown
            if error:
                horse_errors[hid] = error
            progress.progress(.3 + .7 * i/max(len(futures), 1),
                              text=f"各馬の過去成績 {i}/{len(futures)}頭")
    progress.empty()
    # 新馬のみの開催では、過去走0件は正常。履歴対象馬がいる場合だけ診断する。
    if eligible_horses and not any(histories.get(hid) for hid, _ in eligible_horses):
        reasons = list(dict.fromkeys(horse_errors.values()))[:5]
        diagnostics.append({"レースID":"", "処理結果":"非新馬の過去走0件", "取得頭数":0,
                            "理由":" / ".join(reasons) if reasons else "非新馬の全対象馬で履歴0件（日付・HTML解析を確認）",
                            "取得日時JST":datetime.datetime.now(TRIO_JST).isoformat(timespec="seconds")})
    for race in race_records:
        this_entries = [e for e in entries if e["レースID"] == race["netkeiba_race_id"]]
        race["horses"] = [mobile_horse_from_runs(e, histories.get(e["馬ID"], []), target_date)
                           for e in this_entries]
        race["除外した当日以降の履歴"] = sum(skips_by_horse.get(e["馬ID"], (0, 0))[0] for e in this_entries)
        race["除外した日付不明履歴"] = sum(skips_by_horse.get(e["馬ID"], (0, 0))[1] for e in this_entries)
        dirt_model(race["horses"], race.get("target_distance"), race.get("target_going"))
        if horse_errors:
            miss = sum(e["馬ID"] in horse_errors for e in this_entries)
            if miss:
                diagnostics.append({"レースID":race["netkeiba_race_id"],"処理結果":"過去成績一部失敗",
                                    "取得頭数":len(this_entries), "理由":f"{miss}頭の履歴取得失敗",
                                    "取得日時JST":datetime.datetime.now(TRIO_JST).isoformat(timespec="seconds")})
    all_history = [run for rows in histories.values() for run in rows]
    all_history.sort(key=lambda r:(r.get("馬ID", ""), r.get("日付", "")), reverse=True)
    for hid, error in horse_errors.items():
        diagnostics.append({"レースID":"","処理結果":"馬履歴取得失敗",
                            "取得頭数":0,"理由":f"{entries_by_horse[hid]['馬名']}({hid}):{error}",
                            "取得日時JST":datetime.datetime.now(TRIO_JST).isoformat(timespec="seconds")})
    day_label = ("土曜日開催" if target_date.weekday() == 5 else
                 "日曜日開催" if target_date.weekday() == 6 else "指定日開催")
    for race in race_records:
        race["day_label"] = day_label
    empty_eligible = sum(not histories.get(hid) for hid, _ in eligible_horses)
    meta = {"fetch_build": MOBILE_FETCH_BUILD, "date":target_date.isoformat(), "race_ids":len(race_ids), "dirt_races":len(race_records),
            "horses":len(entries), "past_runs":len(all_history),
            "debut_horses":len(debut_ids), "history_eligible_horses":len(eligible_horses),
            "history_zero_non_debut":empty_eligible,
            "excluded_today_or_later":excluded_same_day, "excluded_unknown_date":excluded_no_date,
            "history_errors":len(horse_errors), "history_zero_rows":sum(not v for v in histories.values()),
            "history_fetch_url":"https://db.netkeiba.com/horse/result/{馬ID}/",
            "fetched_at":datetime.datetime.now(TRIO_JST).isoformat(timespec="seconds")}
    return race_records, entries, all_history, diagnostics, meta


def mobile_export_zip(entries, histories, diagnostics, trio_snaps, meta, win_snaps=None, win_diagnostics=None):
    payload = io.BytesIO()
    prefix = meta.get("date", "mobile").replace("-", "")
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        datasets = {
            f"{prefix}_出走表.csv":pd.DataFrame(entries),
            f"{prefix}_過去成績_当日以降除外.csv":pd.DataFrame(histories),
            f"{prefix}_取得診断.csv":pd.DataFrame(diagnostics),
            f"{prefix}_3連複オッズ人気.csv":trio_allmarket_csv(trio_snaps),
            f"{prefix}_単勝オッズ人気.csv":win_allmarket_csv(win_snaps or {}),
            f"{prefix}_単勝取得診断.csv":pd.DataFrame(win_diagnostics or []),
        }
        for filename, frame in datasets.items():
            archive.writestr(filename, frame.to_csv(index=False).encode("utf-8-sig"))
        archive.writestr(f"{prefix}_取得情報.json", json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    return payload.getvalue()


# 結果が確認できた入着馬のみを緑色で表示する（予想指数には影響させない）。
def green_placed_rows(frame, placed_numbers, number_col='horse_no'):
    placed = {int(x) for x in placed_numbers if pd.notna(x)}
    def paint(row):
        try:
            matched = pd.notna(row[number_col]) and int(row[number_col]) in placed
        except (ValueError, TypeError, KeyError):
            matched = False
        return ['background-color: #174a32; color: #b8f7cb; font-weight: bold' if matched else '' for _ in row]
    return frame.style.apply(paint, axis=1)


def green_ticket_rows(frame, winning_numbers):
    winning = {int(x) for x in winning_numbers if pd.notna(x)}
    def paint(row):
        try:
            nums = {int(x) for x in str(row['3連複組合せ']).split('-')}
            matched = len(winning) == 3 and nums == winning
        except (ValueError, TypeError, KeyError):
            matched = False
        return ['background-color: #174a32; color: #b8f7cb; font-weight: bold' if matched else '' for _ in row]
    return frame.style.apply(paint, axis=1)


def green_combo_html(combos, placed_numbers):
    placed = {int(x) for x in placed_numbers if pd.notna(x)}
    parts = []
    for combo in combos:
        formatted = []
        for n in combo:
            n = int(n)
            formatted.append(f"<strong style='color:#69e6a0'>{n}</strong>" if n in placed else str(n))
        content = '-'.join(formatted)
        if len(placed) == 3 and set(combo) == placed:
            content = f"<span style='background:#174a32;color:#b8f7cb;font-weight:bold;padding:2px 5px;border-radius:4px'>{content} (的中)</span>"
        parts.append(content)
    return ' ／ '.join(parts)

def calculate_ai_indices(horses_data):
    df = pd.DataFrame(horses_data)
    df["ai_score"] = pd.to_numeric(df["ai_score"], errors="coerce")
    df = df.sort_values(["ai_score", "horse_no"], ascending=[False, True], na_position="last").reset_index(drop=True)
    df["idx_rank"] = range(1, len(df)+1)
    df["divergence"] = pd.to_numeric(df["pop_rank"], errors="coerce") - df["idx_rank"]
    return df


# --- GitHub Private repository persistence ---
APP_VERSION = "dual-model-4.5-combined-market-default90-history4-dirt4"

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


def _github_archive_history():
    """Download one repository snapshot rather than N Contents API requests.

    The archive endpoint requires one authenticated API call and follows a
    redirect to GitHub's archive host. Never put the token in the URL.
    """
    token, repo = github_config()
    url = "https://api.github.com/repos/" + repo + "/zipball"
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JRA-Streamlit-History",
    })
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            archive_bytes = response.read(35 * 1024 * 1024 + 1)
    except HTTPError as e:
        raise _github_http_error(e, "GET history archive") from e
    except (OSError, TimeoutError) as e:
        raise RuntimeError("GitHub履歴の一括取得に失敗: " + type(e).__name__) from e
    if len(archive_bytes) > 35 * 1024 * 1024:
        raise RuntimeError("履歴アーカイブが35MBを超えました。取得を停止しました")
    predictions, results = {}, {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > 10000:
                raise RuntimeError("履歴ファイル数が上限を超えました")
            for item in entries:
                if item.is_dir() or not item.filename.endswith(".json"):
                    continue
                parts = item.filename.split("/")
                # GitHub zipball has one generated top-level directory.
                if len(parts) != 4 or parts[1] not in ("predictions", "results"):
                    continue
                if not re.fullmatch(r"\d{4}", parts[2]):
                    continue
                if item.file_size > 1024 * 1024:
                    raise RuntimeError("履歴JSONが1MBを超えました: " + parts[-1])
                record = json.loads(archive.read(item).decode("utf-8"))
                if not isinstance(record, dict) or not record.get("race_id"):
                    continue
                target = predictions if parts[1] == "predictions" else results
                target[record["race_id"]] = record
    except (zipfile.BadZipFile, UnicodeError, ValueError) as e:
        raise RuntimeError("GitHub履歴アーカイブの解析に失敗: " + type(e).__name__) from e
    return predictions, results


@st.cache_data(ttl=600, show_spinner=False)
def read_all_history():
    predictions, results = _github_archive_history()
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


# ============================================================
# スマホ直接取得データの永続保存・復元 (GitHub Private repository)
# 
# 以前はブラウザのsession_stateにしか保存しておらず、画面更新・新しい
# セッション・Drive再取得で古い予想に戻っていた。取得済みデータを
# 日付別にGitHubへ圧縮保存し、起動時に最新版を自動復元する。
# ============================================================
MOBILE_ARCHIVE_SCHEMA = 1
MOBILE_ARCHIVE_LATEST = "mobile_data/latest.json"


def _mobile_state_pack(state):
    """日付・3連複tupleキーを安全にJSON化し、サイズを圧縮する。"""
    import zlib

    def encode_any(value):
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat()
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, set):
            return sorted(value)
        raise TypeError("復元対象にJSON非対応の型があります: " + type(value).__name__)

    payload = dict(state)
    market_snapshots = {}
    for rid, snapshot in (state.get("trio_market_snapshots") or {}).items():
        clone = dict(snapshot)
        clone["market"] = {
            "-".join(map(str, combo)) if isinstance(combo, (tuple, list)) else str(combo): record
            for combo, record in (snapshot.get("market") or {}).items()
        }
        market_snapshots[str(rid)] = clone
    payload["trio_market_snapshots"] = market_snapshots
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, default=encode_any, separators=(",", ":")).encode("utf-8")
    packed = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
    return {"schema": MOBILE_ARCHIVE_SCHEMA, "date": str(state["mobile_scrape_meta"]["date"]),
            "fetched_at": str(state["mobile_scrape_meta"].get("fetched_at", "")),
            "format": "zlib+base64+json", "payload": packed}


def _mobile_state_unpack(record):
    import zlib
    if not isinstance(record, dict) or record.get("schema") != MOBILE_ARCHIVE_SCHEMA or record.get("format") != "zlib+base64+json":
        raise ValueError("データ形式が未対応のため、復元を停止しました")
    packed = record.get("payload", "")
    if not isinstance(packed, str) or len(packed) > 15_000_000:
        raise ValueError("保存データが大きすぎるか不正です")
    raw = zlib.decompress(base64.b64decode(packed, validate=True))
    if len(raw) > 30_000_000:
        raise ValueError("展開サイズが上限を超えています")
    state = json.loads(raw.decode("utf-8"))
    meta = state.get("mobile_scrape_meta") or {}
    date_string = str(meta.get("date", ""))
    snapshot_date = datetime.date.fromisoformat(date_string)
    if record.get("date") != date_string:
        raise ValueError("保存レコードの日付が一致しません")
    races = state.get("mobile_scraped_races")
    if not isinstance(races, list) or not races:
        raise ValueError("復元対象に出走表がありません")
    for race in races:
        race_date = datetime.date.fromisoformat(race["race_date"])
        if race_date != snapshot_date:
            raise ValueError("復元対象に別開催日のレースが混入しています")
        race["race_date"] = race_date
        if not isinstance(race.get("horses"), list):
            raise ValueError("出走馬データが不正です")
    state["trio_market_snapshots"] = {
        str(rid): {**snapshot, "market": {
            tuple(int(number) for number in key.split("-")): rec
            for key, rec in (snapshot.get("market") or {}).items()
        }} for rid, snapshot in (state.get("trio_market_snapshots") or {}).items()
    }
    # 以前の保存データは win_market_snapshots を含まないため空として互換復元。
    state["win_market_snapshots"] = {
        str(rid): {**snapshot, "market": {
            int(number): rec for number, rec in (snapshot.get("market") or {}).items()
            if re.fullmatch(r"\d{1,2}", str(number))
        }} for rid, snapshot in (state.get("win_market_snapshots") or {}).items()
    }
    return state


def mobile_state_from_session():
    keys = ("mobile_scraped_races", "mobile_entries", "mobile_histories", "mobile_diagnostics",
            "mobile_scrape_meta", "trio_market_snapshots", "trio_market_errors", "trio_market_diagnostics",
            "win_market_snapshots", "win_market_errors", "win_market_diagnostics")
    empty_lists = ("mobile_entries", "mobile_histories", "mobile_diagnostics", "trio_market_errors",
                   "trio_market_diagnostics", "win_market_errors", "win_market_diagnostics")
    return {key: st.session_state.get(key, [] if key in empty_lists else {}) for key in keys}


def mobile_save_github():
    """直接取得の全データを日付別に保存。市場データだけではない。"""
    state = mobile_state_from_session()
    meta = state.get("mobile_scrape_meta") or {}
    date = datetime.date.fromisoformat(str(meta["date"]))
    if not state.get("mobile_scraped_races"):
        raise RuntimeError("レースデータがないため保存できません")
    record = _mobile_state_pack(state)
    path = f"mobile_data/{date:%Y-%m-%d}.json"
    old_record, _ = get_record(path)
    if old_record and str(old_record.get("fetched_at", "")) > str(record.get("fetched_at", "")):
        # 別の端末で新しく取得した同開催日の情報を、古いセッションで上書きしない。
        raise RuntimeError("GitHubにはこの日付の新しい取得データがあります。先にGitHubから復元してください")
    put_record(path, record, overwrite=True)
    # "最新"は取得日時で判定。過去の日付を手動復元しても最新ポインタを巻き戻さない。
    pointer = {"schema": MOBILE_ARCHIVE_SCHEMA, "date": date.isoformat(),
               "path": path, "fetched_at": meta.get("fetched_at", "")}
    current_pointer, _ = get_record(MOBILE_ARCHIVE_LATEST)
    if not current_pointer or str(pointer["fetched_at"]) >= str(current_pointer.get("fetched_at", "")):
        put_record(MOBILE_ARCHIVE_LATEST, pointer, overwrite=True)
    return path


def mobile_read_github(target_date=None):
    if target_date is None:
        pointer, _ = get_record(MOBILE_ARCHIVE_LATEST)
        if pointer is None:
            return None
        path = str(pointer.get("path", ""))
        if not re.fullmatch(r"mobile_data/\d{4}-\d{2}-\d{2}\.json", path):
            raise ValueError("保存先の指定が不正です")
    else:
        date = target_date if isinstance(target_date, datetime.date) else datetime.date.fromisoformat(str(target_date))
        path = f"mobile_data/{date:%Y-%m-%d}.json"
    record, _ = get_record(path)
    return _mobile_state_unpack(record) if record is not None else None


def mobile_apply_restored_state(state):
    for key, val in state.items():
        if key in ("mobile_scraped_races", "mobile_entries", "mobile_histories", "mobile_diagnostics",
                   "mobile_scrape_meta", "trio_market_snapshots", "trio_market_errors", "trio_market_diagnostics",
                   "win_market_snapshots", "win_market_errors", "win_market_diagnostics"):
            st.session_state[key] = val
    # GitHubの保存形式が旧版でも、単勝のキーを補正して復元する。
    st.session_state.setdefault("win_market_snapshots", {})
    st.session_state.setdefault("win_market_errors", [])
    st.session_state.setdefault("win_market_diagnostics", [])
    win_apply_snapshots_to_races(st.session_state.get("win_market_snapshots", {}),
                                 st.session_state.get("mobile_scraped_races", []),
                                 st.session_state.get("mobile_entries", []))
    meta = state["mobile_scrape_meta"]
    st.session_state["mobile_fetch_message"] = (
        f"GitHub保存分を復元：{meta.get('date', '日付不明')} / "
        f"ダート{len(state.get('mobile_scraped_races', []))}レース・"
        f"過去走{len(state.get('mobile_histories', []))}件。"
    )
    st.session_state["mobile_persist_status"] = "GitHub保存済みの直接取得データを復元しました。"


def mobile_try_autorestore():
    if st.session_state.get("mobile_scraped_races"):
        return
    if st.session_state.get("mobile_auto_restore_tried"):
        return
    st.session_state["mobile_auto_restore_tried"] = True
    try:
        saved = mobile_read_github()
        if saved:
            mobile_apply_restored_state(saved)
    except Exception as exc:
        st.session_state["mobile_restore_error"] = (
            f"GitHubの直接取得データを復元できませんでした: {type(exc).__name__}: {exc}。"
            "Google Driveの旧データへ切り替わる可能性があります。"
        )


# 予想計算に使うデータは、常に「最新の直接取得」をDriveより優先する。
mobile_try_autorestore()
all_loaded_races, load_errors, load_diagnostics = load_races_from_google_drive()

# 同一曜日のDrive旧データより、直接取得データを必ず優先する。
# 条件変更・画面再実行でもsession_stateを保持し、新セッションはGitHubから復元する。
mobile_saved = st.session_state.get("mobile_scraped_races", [])
if mobile_saved:
    mobile_days = {r.get("day_label") for r in mobile_saved}
    all_loaded_races = [r for r in all_loaded_races if r.get("day_label") not in mobile_days] + mobile_saved
    load_diagnostics.append(f"スマホ直接取得：{len(mobile_saved)}ダートレース / "
                            f"{st.session_state.get('mobile_scrape_meta',{}).get('fetched_at','')} JST")

with st.sidebar.expander("📡 データ取得診断", expanded=bool(load_errors)):
    excluded_summary = summarize_history_exclusions(all_loaded_races)
    st.info(f"予想から除外済み：当日以降 {excluded_summary['当日以降']}走 / 日付不明 {excluded_summary['日付不明']}走")
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


if st.session_state.get("drive_refresh_notice"):
    st.info(st.session_state.pop("drive_refresh_notice"))
if st.session_state.get("mobile_restore_error"):
    st.warning(st.session_state["mobile_restore_error"])
if st.session_state.get("mobile_scraped_races"):
    saved_meta = st.session_state.get("mobile_scrape_meta", {})
    st.info(f"📌 予想の使用データ：直接取得 {saved_meta.get('date','日付不明')} "
            f"（{len(st.session_state['mobile_scraped_races'])}ダートレース / "
            f"過去走{len(st.session_state.get('mobile_histories', []))}件）。"
            "条件変更・Drive更新でも保持します。")

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
special_date = (source_date("指定日開催") if any(r.get("day_label") == "指定日開催" for r in all_loaded_races)
                else None)
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
    unverified = [r for r in source_races if r.get("horse_numbers_unverified")]
    if unverified:
        st.warning(f"{len(unverified)}レースでExcelの馬番が空欄です。出走順の仮番号で指数を参考計算しますが、実際の馬番との一致が確認できないため、買い目と予想の確定保存は停止します。")
    if not source_races:
        st.error(f"{day}: 読み込みレース0件です。Google Driveの参照先・公開設定、またはExcelの形式を確認してください。")
        return
    if date is None:
        st.error(f"{day}: 開催日を確定できません。読み込みレース{len(source_races)}件、日付不明または複数の日付があります。")
        return
    if mismatches:
        st.error(f"{day}: 開催日が不一致のレースが{len(mismatches)}件あります。確定保存を停止しました。")
        return
    selected, excluded = choose_dual(day)
    # Always show source races even if the model screens them out.
    source_dirt = [r for r in source_races if r.get("is_dirt_race")]
    st.caption(f"読み込み元のダートレース：{len(source_dirt)}件（東京 {sum(r.get('course') == '東京' for r in source_dirt)}件）")
    st.info(f"指数からの候補 {len(selected)} レース・除外 {len(excluded)} レース（購入確定ではありません）")
    
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
        if race.get("horse_numbers_unverified"):
            st.warning("馬番が空欄のExcelです。以下の順位は仮の出走順であり、実際の馬番ではありません。予想確定保存は無効です。")
        
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
                
                rec_str = ("馬番未確認のため非表示" if race.get("horse_numbers_unverified") else (" ・ ".join(formatted_top) if ev["metrics"] else "対象外（参考：" + "・".join(map(str, top)) + "）"))
                st.markdown(f"推奨4頭： {rec_str}", unsafe_allow_html=True)
                
                if ev["metrics"] and len(top) >= 4 and not race.get("horse_numbers_unverified"):
                    sorted_top4 = sorted(top)
                    combos = list(itertools.combinations(sorted_top4, 3))
                    combos_str = " ／ ".join("-".join(map(str, c)) for c in combos)
                    st.markdown(f"**3連複4点**： `{combos_str}`")

                st.caption("選考通過" if ev["metrics"] else "選考対象外：" + str(ev["reason"]))

        # 3連複4頭BOXの4通りに、取得した人気とオッズを対応表示。
        # 馬番未確定時は組合せを表示しない（出走表順を馬番と誤認しない）。
        netkeiba_rid = trio_race_id(race)
        snapshot = st.session_state.get("trio_market_snapshots", {}).get(netkeiba_rid) if netkeiba_rid else None
        if race.get("horse_numbers_unverified"):
            st.caption("3連複人気は馬番未確定のため表示しません。")
        elif snapshot:
            st.markdown("**📊 3連複・買い目ごとの人気とオッズ**")
            st.caption(f"{snapshot.get('timing', '時刻不明')} / 取得 {snapshot.get('fetched_at', '')} JST / 人気が欠損した買い目は空欄です")
            market_rows = []
            for label, ev in evaluations.items():
                four = [int(n) for n in ev["df"].head(4)["horse_no"]]
                market_rows.extend(trio_ticket_rows(label, four, snapshot))
            if market_rows:
                st.dataframe(pd.DataFrame(market_rows), hide_index=True, use_container_width=True)
                if any(row["取得状態"] != "取得" or pd.isna(row["3連複人気"]) for row in market_rows):
                    st.warning("一部の組合せのオッズ・人気が未取得です。人気を推測で補完しません。")
            else:
                st.caption("4頭BOXの馬番が揃っていません。")
        else:
            st.caption("📱 3連複の人気・オッズは未取得です。画面上部の取得ボタンで更新できます。")

        with st.expander("両モデルの全馬指数・買い目"):
            for label, ev in evaluations.items():
                df = ev["df"]
                st.markdown("**" + label + "**")
                top = sorted(int(x) for x in df.head(4)["horse_no"])
                if race.get("horse_numbers_unverified"):
                    st.write("馬番未確認：買い目は表示しません。指数は参考値です。")
                else:
                    st.markdown("3連複4点： " + green_combo_html(list(itertools.combinations(top, 3)), placed_set), unsafe_allow_html=True)
                cols = [c for c in ["horse_no", "name", "odds", "pop_rank", "ai_score", "margin_score", "distance_score", "going_score", "evidence_coverage", "time_score", "last3f_score", "idx_rank"] if c in df.columns]
                score_columns = [c for c in ("ai_score", "margin_score", "distance_score", "going_score",
                                            "evidence_coverage", "time_score", "last3f_score") if c in cols]
                styled = green_placed_rows(df[cols], placed_set)
                if "odds" in cols:
                    styled = styled.format({"odds": "{:.1f}"}, na_rep="—")
                if score_columns:
                    styled = styled.format({c: "{:.2f}" for c in score_columns}, na_rep="—")
                st.caption("odds＝単勝オッズ、pop_rank＝単勝人気。ai_scoreなどの指数は小数点以下2桁表示。")
                st.dataframe(styled, hide_index=True, use_container_width=True)
                if placed_set:
                    st.caption("緑色＝結果登録済みの3着以内馬。的中した3連複組合せも緑色で表示します。")
        detected_date = race.get("race_date")
        verified = detected_date == date
        save_timing = trio_snapshot_kind(race, datetime.datetime.now(TRIO_JST))
        pre_start = save_timing == "発走前取得"
        if not pre_start:
            st.caption(f"確定保存不可：{save_timing}。結果を知った後のデータを事前予想に混ぜません。")
        if st.button("💾 旧AI・新AIの予想を同時に確定保存", key="save_" + race_key(date, race), disabled=(not verified or not pre_start or detected_date != date or not race.get("is_dirt_race") or race.get("surface_conflict") or race.get("horse_numbers_unverified", False))):
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
                if st.button("新AIの事後検証を保存", key="retro_save_"+race_key(date,race), disabled=(not retro_confirm or race.get("horse_numbers_unverified", False))):
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



# ============================================================
# スマートフォン向け：3連複オッズ・人気をその場で取得
# 取得元は netkeiba のオッズデータ（type=7）。
# 3連複の人気順位はAPIの3番目の値をそのまま使用し、
# 提供がない場合は推測やオッズ順位の代入をしない。
# ============================================================

TRIO_VENUE_CODES = {
    "札幌":"01", "函館":"02", "福島":"03", "新潟":"04", "東京":"05",
    "中山":"06", "中京":"07", "京都":"08", "阪神":"09", "小倉":"10"
}
TRIO_JST = datetime.timezone(datetime.timedelta(hours=9))


def trio_race_id(race):
    """JRA開催見出しの回次・日次・開催場から12桁netkeiba IDを作る。推測補完しない。"""
    date = race.get("race_date")
    if not isinstance(date, datetime.date):
        return None
    official_id = race.get("netkeiba_race_id")
    if official_id is not None:
        rid = str(official_id)
        venue = str(race.get("course", ""))
        if (re.fullmatch(r"20\d{10}", rid) and rid[:4] == str(date.year)
                and TRIO_VENUE_CODES.get(venue) == rid[4:6]
                and int(rid[-2:]) == int(race.get("race_no", 0))):
            return rid
        return None
    heading = unicodedata.normalize("NFKC", str(race.get("heading_raw", "")))
    heading = re.sub(r"\s+", "", heading)
    venue = str(race.get("course") or "")
    number = race.get("race_no")
    if venue not in TRIO_VENUE_CODES or not number:
        return None
    m = re.search(r"(?:第)?(\d{1,2})回" + re.escape(venue) + r"(?:第)?(\d{1,2})日", heading)
    if not m:
        return None
    kai, day = map(int, m.groups())
    if not (1 <= kai <= 9 and 1 <= day <= 12 and 1 <= int(number) <= 12):
        return None
    heading_day = heading_date(heading)
    if heading_day is not None and heading_day != date:
        return None
    return f"{date.year:04d}{TRIO_VENUE_CODES[venue]}{kai:02d}{day:02d}{int(number):02d}"


def trio_combo_key(raw):
    """3連複の組合せキーを (馬番, 馬番, 馬番) に正規化する。"""
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    if re.fullmatch(r"\d{6}", s):
        vals = [int(s[i:i+2]) for i in (0, 2, 4)]
    elif re.fullmatch(r"[1-9]{3}", s):
        vals = [int(v) for v in s]
    else:
        parts = re.split(r"[-_/：:,\s]+", s)
        if len(parts) != 3 or not all(re.fullmatch(r"\d{1,2}", p) for p in parts):
            return None
        vals = [int(p) for p in parts]
    if len(set(vals)) != 3 or any(not (1 <= n <= 18) for n in vals):
        return None
    return tuple(sorted(vals))


def trio_parse_payload(payload):
    """公式人気として返された整数のみを格納する。人気が無い時はNone。"""
    if not isinstance(payload, dict):
        raise ValueError("オッズの返答がJSONオブジェクトではありません")
    if str(payload.get("status", "")).lower() in ("ng", "error", "fail"):
        raise ValueError("オッズ提供元が取得失敗を返しました")
    block = payload.get("data")
    if not isinstance(block, dict):
        raise ValueError("オッズデータ領域がありません")
    groups = block.get("odds")
    group = groups.get("7", groups.get(7)) if isinstance(groups, dict) else None
    if not isinstance(group, dict) or not group:
        raise ValueError("3連複のオッズがありません（未発売または取得制限）")
    data = {}
    for key, item in group.items():
        combo = trio_combo_key(key)
        if combo is None or not isinstance(item, (list, tuple)) or not item:
            continue
        try:
            odds = float(str(item[0]).replace(",", ""))
            if not (0 < odds < 1000000) or not np.isfinite(odds):
                continue
        except (ValueError, TypeError):
            continue
        popularity = None
        if len(item) >= 3 and re.fullmatch(r"\d{1,4}", str(item[2]).strip()):
            n = int(str(item[2]).strip())
            if 1 <= n <= 816:  # 最大18頭の3連複全通り
                popularity = n
        data[combo] = {"odds": odds, "popularity": popularity}
    if not data:
        raise ValueError("3連複の組合せ・オッズ形式が読み取れません")
    return data, block.get("official_datetime", "")


def trio_fetch_race(rid):
    if not re.fullmatch(r"20\d{10}", str(rid)):
        raise ValueError("レースID形式が不正です")
    params = urllib.parse.urlencode({
        "pid":"api_get_jra_odds", "race_id":rid, "type":"7", "action":"init",
        "sort":"odds", "compress":"0", "output":"json"
    })
    url = "https://race.netkeiba.com/api/api_get_jra_odds.html?" + params
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept":"application/json, text/javascript, */*",
        "Referer": f"https://race.netkeiba.com/odds/index.html?race_id={rid}&type=b7",
    })
    with urllib.request.urlopen(req, timeout=12) as response:
        raw = response.read(3 * 1024 * 1024)
        if len(raw) >= 3 * 1024 * 1024:
            raise ValueError("オッズAPIの応答が大きすぎます")
    content = raw.decode("utf-8-sig", errors="replace").strip()
    if not content.startswith("{"):
        jm = re.fullmatch(r"[a-zA-Z_$][\w$]*\((.*)\)\s*;?", content, re.S)
        if jm:
            content = jm.group(1)
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        raise ValueError("JSONではない応答です。アクセス制限や仕様変更の可能性があります")
    return trio_parse_payload(payload)


# ============================================================
# 単勝オッズ・人気（netkeiba API type=1）
# 出走表HTMLの単勝欄はJavaScript更新されることがあり、HTMLだけでは
# オッズが空欄になる。type=1 の「1」グループを馬番で照合する。
# 不発売・データ欠損の場合は推測や3連複人気で代用しない。
# ============================================================

def win_parse_payload(payload):
    """単勝API JSON -> {馬番: {odds, popularity}}, 更新時刻。

    データが部分的でも有効な馬番のみ取得し、頭数の整合性は呼出元で記録する。
    """
    if not isinstance(payload, dict):
        raise ValueError("単勝APIからJSONオブジェクトが返されません")
    if str(payload.get("status", "")).lower() in ("ng", "error", "fail"):
        raise ValueError("単勝APIが取得失敗を返しました")
    block = payload.get("data")
    if not isinstance(block, dict):
        raise ValueError("単勝APIのデータ領域がありません")
    groups = block.get("odds")
    group = groups.get("1", groups.get(1)) if isinstance(groups, dict) else None
    if not isinstance(group, dict) or not group:
        raise ValueError("単勝オッズ未提供（発売前・提供停止の可能性）")
    out = {}
    for raw_num, row in group.items():
        if not re.fullmatch(r"\d{1,2}", str(raw_num)):
            continue
        number = int(raw_num)
        if not 1 <= number <= 18 or not isinstance(row, (tuple, list)) or not row:
            continue
        try:
            val = float(str(row[0]).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(val) or not 0 < val <= 100000:
            continue
        popular = None
        if len(row) >= 3 and re.fullmatch(r"\d{1,2}", str(row[2]).strip()):
            n = int(str(row[2]).strip())
            if 1 <= n <= 18:
                popular = n
        out[number] = {"odds": val, "popularity": popular}
    if not out:
        raise ValueError("単勝オッズが有効な数値でありません（発売前の可能性）")
    return out, str(block.get("official_datetime", ""))


def win_fetch_race(rid):
    """発売済みの単勝オッズ。init が空の場合のみ update を確認。"""
    if not re.fullmatch(r"20\d{10}", str(rid)):
        raise ValueError("レースIDが不正です")
    errors = []
    for action in ("init", "update"):
        params = urllib.parse.urlencode({
            "pid": "api_get_jra_odds", "race_id": rid,
            "type": "1", "action": action, "sort": "odds", "compress": "0", "output": "json"
        })
        url = "https://race.netkeiba.com/api/api_get_jra_odds.html?" + params
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*",
            "Referer": f"https://race.netkeiba.com/odds/index.html?race_id={rid}&type=b1",
        })
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("単勝APIの応答が大きすぎます")
            content = raw.decode("utf-8-sig", errors="replace").strip()
            if not content.startswith("{"):
                match = re.fullmatch(r"[a-zA-Z_$][\w$]*\((.*)\)\s*;?", content, re.S)
                if match:
                    content = match.group(1)
            payload = json.loads(content)
            return win_parse_payload(payload)
        except Exception as exc:
            errors.append(f"{action}: {type(exc).__name__}: {str(exc)[:120]}")
    raise RuntimeError(" / ".join(errors))


def win_collect_for_loaded_races(races):
    """取得成功レースだけを返す。既存の単勝情報は呼出元で維持する。"""
    snapshots, errors, diagnostics = {}, [], []
    candidates = {}
    for race in races:
        if not race.get("is_dirt_race"):
            continue
        rid = trio_race_id(race)
        if rid:
            candidates[rid] = race
        else:
            errors.append(f"{race.get('race_name', '')}: レースID未確定")
    if not candidates:
        return snapshots, errors, diagnostics
    progress = st.progress(0.0, text="単勝オッズ・人気を取得中")
    try:
        for i, (rid, race) in enumerate(candidates.items(), start=1):
            stamp = datetime.datetime.now(TRIO_JST)
            valid_numbers = {int(h["horse_no"]) for h in race.get("horses", [])
                             if h.get("horse_no_verified") and h.get("horse_no") is not None}
            try:
                fetched, official_time = win_fetch_race(rid)
                # 別レースのデータを誤採用しないよう、有効馬番と照合。
                filtered = {number: rec for number, rec in fetched.items()
                            if not valid_numbers or number in valid_numbers}
                if not filtered:
                    raise ValueError("出走表の馬番と単勝APIの馬番が一致しません")
                snapshots[rid] = {
                    "market": filtered, "race_name": str(race.get("race_name", "")),
                    "race_date": race["race_date"].isoformat(),
                    "fetched_at": stamp.isoformat(timespec="seconds"),
                    "official_datetime": official_time,
                    "timing": trio_snapshot_kind(race, stamp),
                    "source": "netkeiba単勝API(type=1)",
                }
                n = len(filtered)
                count_known = len(valid_numbers)
                diagnostics.append({"レース名": race.get("race_name", ""), "レースID": rid,
                                    "結果": "取得成功" if n == count_known else "一部取得",
                                    "取得頭数": n, "出走頭数": count_known,
                                    "単勝人気あり": sum(rec["popularity"] is not None for rec in filtered.values()),
                                    "理由": "" if n == count_known else "取得できた馬番のみ反映（欠損は補完しない）",
                                    "取得日時JST": stamp.isoformat(timespec="seconds")})
            except Exception as exc:
                message = f"{race.get('race_name', '')} ({rid}): {exc}"
                errors.append(message)
                diagnostics.append({"レース名": race.get("race_name", ""), "レースID": rid,
                                    "結果": "取得失敗・未発売", "取得頭数": 0,
                                    "出走頭数": len(valid_numbers), "単勝人気あり": 0,
                                    "理由": str(exc)[:350], "取得日時JST": stamp.isoformat(timespec="seconds")})
            progress.progress(i / len(candidates), text=f"単勝オッズ {i}/{len(candidates)}レース")
    finally:
        progress.empty()
    return snapshots, errors, diagnostics


def win_apply_snapshots_to_races(snapshots, races, entries):
    """馬番をキーとして単勝APIデータを出走表・予想・保存用CSVに反映。

    予想指数そのものと過去走は変更しない。以前のオッズはAPI失敗時に保持する。
    """
    updated = 0
    by_key = {}
    for rid, snapshot in (snapshots or {}).items():
        for n, value in snapshot.get("market", {}).items():
            if not isinstance(value, dict) or value.get("odds") is None:
                continue
            by_key[(str(rid), int(n))] = value
    for race in races or []:
        rid = str(race.get("netkeiba_race_id") or "")
        for horse in race.get("horses", []):
            key = (rid, int(horse.get("horse_no", 0)))
            rec = by_key.get(key)
            if rec and horse.get("horse_no_verified"):
                horse["odds"] = rec["odds"]
                horse["pop_rank"] = rec.get("popularity")
                horse["win_odds_source"] = "単勝API"
                updated += 1
    for entry in entries or []:
        key = (str(entry.get("レースID")), int(entry.get("馬番", 0)))
        rec = by_key.get(key)
        if rec:
            entry["オッズ"] = rec["odds"]
            entry["人気"] = rec.get("popularity")
            entry["単勝オッズ取得元"] = "単勝API"
    return updated


def win_allmarket_csv(snapshots):
    rows = []
    for rid, snapshot in (snapshots or {}).items():
        for n, rec in sorted(snapshot.get("market", {}).items(), key=lambda x: int(x[0])):
            rows.append({"レースID": rid, "開催日": snapshot.get("race_date"),
                         "レース名": snapshot.get("race_name"), "馬番": int(n),
                         "単勝オッズ": rec.get("odds"), "単勝人気": rec.get("popularity"),
                         "取得日時JST": snapshot.get("fetched_at"),
                         "データ区分": snapshot.get("timing"),
                         "提供元更新時刻": snapshot.get("official_datetime")})
    return pd.DataFrame(rows, columns=["レースID", "開催日", "レース名", "馬番", "単勝オッズ",
                                       "単勝人気", "取得日時JST", "データ区分", "提供元更新時刻"])


def trio_snapshot_kind(race, fetched_at):
    """発走前取得かどうか。不明・発走後は事前データとして利用しない。"""
    d = race.get("race_date")
    if not isinstance(d, datetime.date):
        return "開催日不明・検証対象外"
    m = re.search(r"発走時刻\s*[:：]\s*(\d{1,2})時\s*(\d{1,2})分", str(race.get("heading_raw", "")))
    if not m:
        return "発走時刻不明・参考"
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return "発走時刻不明・参考"
    start = datetime.datetime.combine(d, datetime.time(hour, minute), tzinfo=TRIO_JST)
    return "発走前取得" if fetched_at < start else "発走時刻以降・事後参考"


def trio_ticket_rows(model_name, numbers, snapshot):
    market = snapshot.get("market", {})
    rows = []
    if len(numbers) != 4 or len(set(numbers)) != 4:
        return rows
    for combo in itertools.combinations(sorted(int(x) for x in numbers), 3):
        rec = market.get(combo)
        rows.append({
            "モデル": model_name,
            "組合せ": "-".join(map(str, combo)),
            "3連複オッズ": rec.get("odds") if rec else None,
            "3連複人気": rec.get("popularity") if rec else None,
            "取得状態": "取得" if rec else "未取得",
        })
    return rows


def trio_market_summary(market):
    if not market:
        return "未取得"
    return f"取得 {len(market)}組 / 人気順位あり {sum(r.get('popularity') is not None for r in market.values())}組"


def trio_fetch_race_with_retry(rid, max_attempts=3):
    """アクセスエラーのみ再試行。人気・オッズ未提供も失敗理由を保存。"""
    errors = []
    for attempt in range(1, max_attempts + 1):
        try:
            market, official_time = trio_fetch_race(rid)
            return market, official_time, attempt
        except Exception as exc:
            errors.append(f"{attempt}回目: {type(exc).__name__}: {exc}")
            if attempt < max_attempts:
                time.sleep(min(1.5 * attempt, 3.0))
    raise RuntimeError(" | ".join(errors))


def trio_collect_for_loaded_races(races):
    updates, errors, diagnostics = {}, [], []
    candidates = {}
    for race in races:
        if not race.get("is_dirt_race") or not race.get("identified", True):
            continue
        rid = trio_race_id(race)
        if not rid:
            message = f"{race.get('race_name', 'レース')}: 回次・開催日・日次のいずれかが不明"
            errors.append(message)
            diagnostics.append({"レース名":race.get("race_name", ""), "レースID":"",
                                "結果":"取得不可", "試行回数":0, "理由":message,
                                "取得日時JST": datetime.datetime.now(TRIO_JST).isoformat(timespec="seconds")})
            continue
        candidates[rid] = race
    if not candidates:
        return updates, errors, diagnostics
    bar = st.progress(0, text="3連複人気を取得しています")
    try:
        for idx, (rid, race) in enumerate(candidates.items(), start=1):
            stamp = datetime.datetime.now(TRIO_JST)
            try:
                market, official_time, attempts = trio_fetch_race_with_retry(rid)
                # 頭数と全組合せ数の一致を確認。部分取得を「成功」と扱わない。
                known_numbers = {int(h['horse_no']) for h in race.get('horses', [])
                                 if h.get('horse_no_verified') and h.get('horse_no') is not None}
                if (not race.get('horse_numbers_unverified') and len(known_numbers) >= 3):
                    expected = len(known_numbers) * (len(known_numbers)-1) * (len(known_numbers)-2) // 6
                    if len(market) != expected:
                        raise ValueError(f"3連複組合せ数が不一致：{len(market)}/{expected}組")
                stamp = datetime.datetime.now(TRIO_JST)
                updates[rid] = {
                    "market": market, "official_datetime": str(official_time or ""),
                    "fetched_at": stamp.isoformat(timespec="seconds"),
                    "timing": trio_snapshot_kind(race, stamp),
                    "race_name": str(race.get("race_name", "")),
                    "race_date": race.get("race_date").isoformat(),
                }
                diagnostics.append({"レース名":race.get("race_name", ""), "レースID":rid,
                                    "結果":"取得成功", "試行回数":attempts, "理由":"",
                                    "取得組合せ":len(market),
                                    "人気順位あり":sum(x.get("popularity") is not None for x in market.values()),
                                    "データ区分":updates[rid]["timing"], "取得日時JST":stamp.isoformat(timespec="seconds")})
            except Exception as exc:
                message = f"{race.get('race_name')} ({rid}): {exc}"
                errors.append(message)
                diagnostics.append({"レース名":race.get("race_name", ""), "レースID":rid,
                                    "結果":"取得失敗", "試行回数":3, "理由":str(exc),
                                    "取得組合せ":0, "人気順位あり":0,
                                    "データ区分":"未取得", "取得日時JST":stamp.isoformat(timespec="seconds")})
            bar.progress(idx / len(candidates), text=f"3連複人気取得 {idx}/{len(candidates)}レース")
    finally:
        bar.empty()
    return updates, errors, diagnostics

def trio_allmarket_csv(snapshots):
    rows = []
    for rid, obj in snapshots.items():
        for combo, rec in obj.get("market", {}).items():
            rows.append({
                "レースID":rid, "開催日":obj.get("race_date"), "レース名":obj.get("race_name"),
                "3連複組合せ":"-".join(map(str, combo)), "オッズ":rec.get("odds"),
                "3連複人気":rec.get("popularity"), "取得日時JST":obj.get("fetched_at"),
                "データ区分":obj.get("timing"), "提供元更新時刻":obj.get("official_datetime"),
            })
    return pd.DataFrame(rows, columns=[
        "レースID", "開催日", "レース名", "3連複組合せ", "オッズ", "3連複人気",
        "取得日時JST", "データ区分", "提供元更新時刻"
    ])


def trio_store_snapshot_github(snapshots, diagnostics):
    """既存のGitHub保存先に市場データを1スナップショットとして記録する。"""
    now = datetime.datetime.now(TRIO_JST)
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    path = f"market_snapshots/{now.year}/{stamp}.json"
    markets = []
    for rid, obj in snapshots.items():
        combos = [{"組合せ":"-".join(map(str, combo)),
                   "オッズ": rec.get("odds"), "3連複人気": rec.get("popularity")}
                  for combo, rec in sorted(obj.get("market", {}).items())]
        markets.append({"レースID":rid,
                        "開催日":obj.get("race_date"), "レース名":obj.get("race_name"),
                        "取得日時JST":obj.get("fetched_at"), "データ区分":obj.get("timing"),
                        "提供元更新時刻":obj.get("official_datetime"), "組合せ":combos})
    record = {"保存日時JST": now.isoformat(timespec="seconds"),
              "取得元":"netkeiba・3連複オッズ人気（type=7）",
              "取得レース数":len(markets), "各レース市場データ":markets, "取得診断":diagnostics,
              "注記":"発走後取得は過去の予想・回収率検証に利用不可"}
    put_record(path, record, overwrite=False)
    return path


# ============================================================
# スマホからの日付指定→出走表→過去成績→3連複オッズ人気のワンタップ取得
# 端末にはPython/Colab不要。処理はStreamlitサーバー側で実行される。
# ============================================================
st.subheader("📱 スマホで出走表・過去成績・単勝・3連複人気を取得")
st.caption(f"🔧 取得エンジン: {MOBILE_FETCH_BUILD} ｜ 11月8日のID直接補完：有効")
st.caption("日付を選んで押すだけ。6〜12Rのダートだけ対象に直接取得します。単勝オッズは未発売時には空欄になります。")
default_mobile_date = datetime.datetime.now(TRIO_JST).date()
if st.session_state.get("mobile_scrape_meta", {}).get("date"):
    try:
        default_mobile_date = datetime.date.fromisoformat(st.session_state["mobile_scrape_meta"]["date"])
    except ValueError:
        pass
mobile_selected_date = st.date_input(
    "取得する開催日", value=default_mobile_date,
    key="mobile_target_date"
)
if st.button("📲 出走表＋過去成績＋単勝＋3連複人気を一括取得", key="mobile_fetch_all",
             type="primary", use_container_width=True):
    st.session_state["win_market_message"] = ""
    st.session_state["mobile_fetch_message"] = ""
    try:
        with st.spinner("対象日のダートレースと過去成績を取得中..."):
            races, entries, histories, diagnostics, meta = mobile_fetch_date(mobile_selected_date)
        # 市場データの発売前・通信失敗で出走表や過去走を消さない。
        with st.spinner("単勝オッズ・人気を取得中..."):
            wins, win_errors, win_diag = win_collect_for_loaded_races(races)
        win_apply_snapshots_to_races(wins, races, entries)
        with st.spinner("3連複の組合せ別オッズ・人気を取得中..."):
            markets, errs, market_diag = trio_collect_for_loaded_races(races)
        st.session_state["mobile_scraped_races"] = races
        st.session_state["mobile_entries"] = entries
        st.session_state["mobile_histories"] = histories
        st.session_state["mobile_diagnostics"] = diagnostics + market_diag + win_diag
        meta["win_races"] = len(wins)
        meta["win_horses"] = sum(len(v.get("market", {})) for v in wins.values())
        meta["win_errors"] = len(win_errors)
        st.session_state["win_market_snapshots"] = wins
        st.session_state["win_market_errors"] = win_errors
        st.session_state["win_market_diagnostics"] = win_diag
        meta["trio_races"] = len(markets)
        meta["trio_combinations"] = sum(len(v.get("market",{})) for v in markets.values())
        meta["trio_errors"] = len(errs)
        st.session_state["mobile_scrape_meta"] = meta
        st.session_state["trio_market_snapshots"] = markets
        st.session_state["trio_market_errors"] = errs
        st.session_state["trio_market_diagnostics"] = market_diag
        st.session_state["trio_market_github_save"] = ""
        if markets:
            try:
                saved_path = trio_store_snapshot_github(markets, market_diag)
                st.session_state["trio_market_github_save"] = "取得日時付きでGitHubへ保存: " + saved_path
            except Exception as save_exc:
                st.session_state["trio_market_github_save"] = "GitHub自動保存不可: " + str(save_exc)
        # 取得結果は今までセッションだけだったが、全レース・全履歴もGitHubに永続化する。
        try:
            persistent_path = mobile_save_github()
            st.session_state["mobile_persist_status"] = "全レース・過去走・単勝・3連複をGitHubに保存しました: " + persistent_path
        except Exception as save_exc:
            st.session_state["mobile_persist_status"] = (
                "⚠️ GitHubへの全データ保存に失敗。現セッションでは保持しますが、"
                "ブラウザを閉じると復元できない可能性があります: " + str(save_exc)
            )
        st.session_state["mobile_fetch_message"] = (
            f"出走表取得：ダート{len(races)}レース・{len(entries)}頭・"
            f"発走前履歴{len(histories)}件・単勝{meta['win_horses']}頭・3連複{meta['trio_combinations']}組。"
            f"新馬（履歴対象外）{meta.get('debut_horses', 0)}頭・"
            f"履歴取得失敗{meta.get('history_errors', 0)}頭。"
        )
        st.rerun()
    except Exception as exc:
        st.error(f"直接取得に失敗しました：{type(exc).__name__}: {exc}")
        st.info("netkeibaのアクセス制限・HTML変更・ネットワーク障害の可能性があります。" 
                "既存のDrive読み込みは引き続き利用できます。")

if st.session_state.get("mobile_persist_status"):
    message = st.session_state["mobile_persist_status"]
    (st.warning if message.startswith("⚠️") else st.success)(message)

with st.expander("📥 手元に保存した完全データJSONから復元"):
    backup_upload = st.file_uploader("予想復元データ.json を選択", type=["json"], key="mobile_upload_backup")
    if backup_upload is not None and st.button("このバックアップを復元", key="mobile_restore_local"):
        try:
            restored = _mobile_state_unpack(json.loads(backup_upload.getvalue().decode("utf-8")))
            mobile_apply_restored_state(restored)
            st.rerun()
        except Exception as exc:
            st.error(f"バックアップの解析に失敗: {type(exc).__name__}: {exc}")

with st.expander("📂 過去に直接取得した日付をGitHubから復元"):
    manual_restore_date = st.date_input("復元する開催日", value=mobile_selected_date, key="mobile_restore_date")
    if st.button("この日付の直接取得データを復元", key="restore_mobile_by_date"):
        try:
            restored = mobile_read_github(manual_restore_date)
            if restored is None:
                st.warning("この開催日の保存データはGitHubにありません。")
            else:
                mobile_apply_restored_state(restored)
                st.rerun()
        except Exception as exc:
            st.error(f"復元できませんでした: {type(exc).__name__}: {exc}")

if st.session_state.get("mobile_fetch_message"):
    st.success(st.session_state["mobile_fetch_message"])
    meta = st.session_state.get("mobile_scrape_meta", {})
    st.caption(f"取得日時：{meta.get('fetched_at','不明')} JST / "
               f"当日以降の履歴除外 {meta.get('excluded_today_or_later',0)}件 / "
               f"新馬（履歴対象外） {meta.get('debut_horses',0)}頭 / "
               f"非新馬の履歴取得失敗 {meta.get('history_errors',0)}頭")
    if meta.get("debut_horses", 0):
        st.info(f"新馬戦の{meta['debut_horses']}頭は過去走の取得対象から除外しました。"
                "過去走保有率を上げるための架空データは作らず、新馬戦の指数予想は引き続き対象外です。")
    if meta.get("history_errors", 0) and not meta.get("past_runs", 0):
        st.error("過去成績が全頭取得できていません。履歴からの予想は行わず、診断ZIPをご確認ください。")
    elif meta.get("history_errors", 0):
        st.warning(f"新馬戦以外で過去成績の取得に失敗した馬が{meta['history_errors']}頭います。欠損は予想に使っていません。")
    if meta.get("history_zero_non_debut", 0):
        st.info(f"新馬戦以外で過去走0件の馬が{meta['history_zero_non_debut']}頭います。"
                "本当に出走経験がない場合と、取得できなかった場合を診断CSVで確認できます。")
    if meta.get("trio_races", 0) == 0:
        st.warning("3連複市場データは取得できませんでした。出走表と履歴は保存されています。")
    # GitHubの保存権限がない場合でも、同じ形式を手元に保存できる。
    try:
        import gzip
        data_for_restore = _mobile_state_pack(mobile_state_from_session())
        restore_data = json.dumps(data_for_restore, ensure_ascii=False).encode("utf-8")
        st.download_button("💾 次回復元用の完全データJSONを保存", data=restore_data,
                           file_name=f"{meta.get('date','JRA')}_予想復元データ.json",
                           mime="application/json", key="mobile_full_backup_download",
                           use_container_width=True)
    except Exception as archive_exc:
        st.warning("完全バックアップ作成不可: " + str(archive_exc))
    mobile_zip = mobile_export_zip(
        st.session_state.get("mobile_entries", []),
        st.session_state.get("mobile_histories", []),
        st.session_state.get("mobile_diagnostics", []),
        st.session_state.get("trio_market_snapshots", {}), meta,
        st.session_state.get("win_market_snapshots", {}),
        st.session_state.get("win_market_diagnostics", []))
    st.download_button("📦 スマホで取得した全データと診断をZIP保存", data=mobile_zip,
                       file_name=f"{meta.get('date','JRA')}_スマホ直接取得.zip",
                       mime="application/zip", use_container_width=True,
                       key="mobile_download_all")
    if st.session_state.get("mobile_diagnostics"):
        with st.expander("スマホ直接取得の成功・失敗診断"):
            st.dataframe(pd.DataFrame(st.session_state["mobile_diagnostics"]),
                         hide_index=True, use_container_width=True)

st.divider()
st.subheader("🏇 単勝・3連複オッズ／人気を一括取得・更新")
st.caption("現在表示中のレースを対象に単勝・3連複を同時更新します。"
           "出走表と過去走は再取得せず保持し、更新に失敗した市場データも前回分を消しません。"
           "指数には単勝人気・オッズを使いません。")
for market_key, default in (
    ("win_market_snapshots", {}), ("win_market_errors", []), ("win_market_diagnostics", []),
    ("trio_market_snapshots", {}), ("trio_market_errors", []), ("trio_market_diagnostics", []),
):
    if market_key not in st.session_state:
        st.session_state[market_key] = default

if st.button("🔄 単勝＋3連複のオッズ・人気を一括取得／更新（過去走は保持）",
             key="mobile_fetch_market", use_container_width=True):
    st.session_state["market_refresh_pending"] = True
    st.rerun()

if st.session_state.pop("market_refresh_pending", False):
    # 3連複・単勝とも「現在の直接取得日」だけを扱い、古いDriveの開催日を混ぜない。
    active_date = (st.session_state.get("mobile_scrape_meta") or {}).get("date")
    source_races = st.session_state.get("mobile_scraped_races") or all_loaded_races
    refresh_races = [
        race for race in source_races
        if race.get("is_dirt_race")
        and (not active_date or (
            race.get("race_date").isoformat()[:10] == active_date
            if isinstance(race.get("race_date"), (datetime.date, datetime.datetime))
            else str(race.get("race_date", ""))[:10] == active_date
        ))
    ]
    if not refresh_races:
        st.session_state["market_refresh_message"] = "更新対象のダートレースがありません。先に出走表を取得してください。"
        st.session_state["market_refresh_success"] = False
    else:
        # 単勝と3連複は独立して取得し、一方の失敗が他方を止めない。
        with st.spinner("単勝・3連複オッズと人気をまとめて取得しています..."):
            try:
                wins, win_errors, win_diag = win_collect_for_loaded_races(refresh_races)
            except Exception as exc:
                wins, win_errors, win_diag = {}, [f"単勝の一括取得例外: {type(exc).__name__}: {exc}"], []
            try:
                trios, trio_errors, trio_diag = trio_collect_for_loaded_races(refresh_races)
            except Exception as exc:
                trios, trio_errors, trio_diag = {}, [f"3連複の一括取得例外: {type(exc).__name__}: {exc}"], []

        # 成功したレースだけ新しい市場を上書き。未発売・通信失敗では過去の値を保持。
        st.session_state["win_market_snapshots"] = {
            **st.session_state.get("win_market_snapshots", {}), **wins
        }
        st.session_state["trio_market_snapshots"] = {
            **st.session_state.get("trio_market_snapshots", {}), **trios
        }
        st.session_state["win_market_errors"] = win_errors
        st.session_state["win_market_diagnostics"] = win_diag
        st.session_state["trio_market_errors"] = trio_errors
        st.session_state["trio_market_diagnostics"] = trio_diag

        if wins:
            # 馬番照合で単勝オッズ・人気を予想表示、CSV、永続保存データに反映。
            win_apply_snapshots_to_races(
                wins,
                st.session_state.get("mobile_scraped_races") or all_loaded_races,
                st.session_state.get("mobile_entries", []),
            )

        meta = st.session_state.get("mobile_scrape_meta") or {}
        if meta:
            meta["win_races"] = len(st.session_state["win_market_snapshots"])
            meta["win_horses"] = sum(len(v.get("market", {})) for v in
                                     st.session_state["win_market_snapshots"].values())
            meta["win_errors"] = len(win_errors)
            meta["trio_races"] = len(st.session_state["trio_market_snapshots"])
            meta["trio_combinations"] = sum(len(v.get("market", {})) for v in
                                            st.session_state["trio_market_snapshots"].values())
            meta["trio_errors"] = len(trio_errors)
            st.session_state["mobile_scrape_meta"] = meta

        st.session_state["trio_market_github_save"] = ""
        if (wins or trios) and st.session_state.get("mobile_scraped_races"):
            try:
                saved_path = mobile_save_github()
                st.session_state["mobile_persist_status"] = (
                    "単勝・3連複の最新市場データもGitHubへ永続保存しました: " + saved_path
                )
            except Exception as exc:
                st.session_state["mobile_persist_status"] = (
                    "⚠️ 市場データのGitHub保存失敗（現在の画面では保持）: " + str(exc)
                )
        if trios:
            try:
                saved_path = trio_store_snapshot_github(trios, trio_diag)
                st.session_state["trio_market_github_save"] = "取得日時付きでGitHubへ保存: " + saved_path
            except Exception as exc:
                st.session_state["trio_market_github_save"] = "GitHubへの自動保存不可: " + str(exc)

        win_n = sum(len(x.get("market", {})) for x in wins.values())
        trio_n = sum(len(x.get("market", {})) for x in trios.values())
        st.session_state["market_refresh_message"] = (
            f"一括更新結果：単勝 {len(wins)}レース・{win_n}頭、"
            f"3連複 {len(trios)}レース・{trio_n}組。"
            "出走表・過去走と、取得失敗した市場の前回データは保持しました。"
        )
        st.session_state["market_refresh_success"] = bool(wins or trios)
    # 上部の予想・単勝表示も同じ更新済みデータを描画し直す。
    st.rerun()

if st.session_state.get("market_refresh_message"):
    renderer = st.success if st.session_state.get("market_refresh_success") else st.warning
    renderer(st.session_state["market_refresh_message"])

st.subheader("🏇 単勝オッズ・人気")
st.caption("単勝オッズはnetkeiba APIから馬番で照合。未発売・取得不可なら推測しません。"
           "取得・更新は上の単勝＋3連複一括ボタンで行います。")
win_snaps = st.session_state.get("win_market_snapshots", {})
if win_snaps:
    win_frame = win_allmarket_csv(win_snaps)
    st.caption(f"APIで単勝を取得済み：{len(win_snaps)}レース・{len(win_frame)}頭。オッズは取得時点の値です。")
    st.download_button("📥 単勝オッズ・人気CSVを保存", data=win_frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name="JRA_単勝オッズ人気_取得結果.csv", mime="text/csv",
                       key="win_odds_csv", use_container_width=True)
with st.expander("単勝オッズ一覧（未取得馬を含む）"):
    visible = []
    visible_races = st.session_state.get("mobile_scraped_races") or all_loaded_races
    for r in visible_races:
        if not r.get("is_dirt_race"):
            continue
        rid = trio_race_id(r)
        snapshot = win_snaps.get(rid, {})
        market = snapshot.get("market", {})
        for horse in r.get("horses", []):
            rec = market.get(int(horse["horse_no"])) if rid else None
            visible.append({"レース": r.get("race_name", ""), "馬番": horse["horse_no"],
                            "馬名": horse.get("name", ""),
                            "単勝オッズ": rec.get("odds") if rec else horse.get("odds"),
                            "単勝人気": rec.get("popularity") if rec else horse.get("pop_rank"),
                            "取得元": "単勝API" if rec else ("出走表" if horse.get("odds") is not None else "未取得")})
    if visible:
        st.dataframe(pd.DataFrame(visible), hide_index=True, use_container_width=True,
                     column_config={"単勝オッズ": st.column_config.NumberColumn("単勝オッズ", format="%.1f")})
    else:
        st.info("現在表示中の出走表にダート出走馬がありません。")
if st.session_state.get("win_market_diagnostics"):
    with st.expander("単勝APIの取得診断"):
        st.dataframe(pd.DataFrame(st.session_state["win_market_diagnostics"]),
                     hide_index=True, use_container_width=True)
if st.session_state.get("win_market_errors"):
    with st.expander(f"単勝未取得レース・理由（{len(st.session_state['win_market_errors'])}件）"):
        for message in st.session_state["win_market_errors"]:
            st.write(message)

st.divider()
st.subheader("📊 3連複オッズ・人気")
st.caption("単勝と同じ一括更新ボタンで取得した3連複の組合せ別オッズ・人気です。")

if st.session_state.get("trio_market_github_save"):
    message = st.session_state["trio_market_github_save"]
    if message.startswith("取得日時付き"):
        st.success(message)
    else:
        st.warning(message + "。以下のZIP保存をご利用ください。")

trio_snapshots = st.session_state["trio_market_snapshots"]
if trio_snapshots:
    st.caption(" / ".join(f"{v['race_name']}: {trio_market_summary(v['market'])}" for v in list(trio_snapshots.values())[:8]))
    for v in trio_snapshots.values():
        if v.get("timing") != "発走前取得":
            st.warning("発走時刻以降に取得した市場データが含まれます。過去の予想・バックテストに混ぜないでください。")
            break
    market_csv = trio_allmarket_csv(trio_snapshots)
    st.download_button("📥 取得した3連複オッズ・人気をCSV保存", data=market_csv.to_csv(index=False).encode("utf-8-sig"),
                       file_name="JRA_3連複オッズ人気_取得結果.csv", mime="text/csv", key="trio_market_download", use_container_width=True)
# スマホから取得失敗もCSVに保存できるようにする（成功・失敗両方のログ）。
if st.session_state["trio_market_diagnostics"]:
    diag_df = pd.DataFrame(st.session_state["trio_market_diagnostics"])
    st.download_button("📥 3連複取得診断・失敗理由CSV", data=diag_df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="JRA_3連複人気_取得診断.csv", mime="text/csv", key="trio_diagnostic_download", use_container_width=True)
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("3連複オッズ人気.csv", trio_allmarket_csv(st.session_state["trio_market_snapshots"]).to_csv(index=False).encode("utf-8-sig"))
        zf.writestr("単勝オッズ人気.csv", win_allmarket_csv(st.session_state.get("win_market_snapshots", {})).to_csv(index=False).encode("utf-8-sig"))
        zf.writestr("取得診断.csv", diag_df.to_csv(index=False).encode("utf-8-sig"))
        zf.writestr("単勝取得診断.csv", pd.DataFrame(st.session_state.get("win_market_diagnostics", [])).to_csv(index=False).encode("utf-8-sig"))
    st.download_button("📦 単勝＋3連複の取得結果・診断をZIP保存", data=bundle.getvalue(),
                       file_name="JRA_単勝3連複取得結果_診断一式.zip", mime="application/zip", key="trio_bundle_download", use_container_width=True)

if st.session_state["trio_market_errors"]:
    with st.expander(f"取得できなかったレース・理由（{len(st.session_state['trio_market_errors'])}件）"):
        for err in st.session_state["trio_market_errors"]:
            st.write(err)
st.caption("人気順位とオッズだけで回収率100%を保証することはできません。指数候補は購入確定ではなく、購入しない判断も可能です。")

st.checkbox("🔬 検証モード：推奨上限を解除して全候補を表示", key="show_all_for_validation")
tab_labels = ["📅 土曜推奨", "📅 日曜推奨"]
if special_date is not None:
    tab_labels.append("📅 指定日推奨")
tab_labels += ["📝 結果登録", "📊 長期成績"]
tabs = st.tabs(tab_labels)
with tabs[0]:
    render_races("土曜日開催", sat_date)
with tabs[1]:
    render_races("日曜日開催", sun_date)
next_tab_index = 2
if special_date is not None:
    with tabs[next_tab_index]:
        render_races("指定日開催", special_date)
    next_tab_index += 1
t3, t4 = tabs[next_tab_index:next_tab_index+2]

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
