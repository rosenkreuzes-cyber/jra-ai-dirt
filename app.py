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
from urllib.error import HTTPError
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


# --- GitHub Private repository persistence ---
APP_VERSION = "hit-priority-1.0-history-1.0"

def github_config():
    token = st.secrets.get("GITHUB_TOKEN", "")
    repo = st.secrets.get("GITHUB_REPO", "")
    if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise RuntimeError("SecretsにGITHUB_TOKENとGITHUB_REPO（ユーザー名/jra-ai-history）を設定してください")
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
    # GitHub Contents API can return content="" for files >1MB; records here are per-race.
    raw = base64.b64decode(item["content"].replace("\n", ""))
    return json.loads(raw.decode("utf-8")), item["sha"]


def put_record(path, record, overwrite=False):
    # Refuse overwriting a frozen pre-race prediction.
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


def snapshot(date, race, metrics, df, settings):
    top = [int(x) for x in df.head(4)["horse_no"]]
    horses = []
    for row in df.to_dict("records"):
        clean = {}
        for k, v in row.items():
            if isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating,)):
                v = float(v) if np.isfinite(v) else None
            elif pd.isna(v):
                v = None
            clean[k] = v
        horses.append(clean)
    return {
        "race_id": race_key(date, race), "race_date": date.isoformat(),
        "day_label": race["day_label"], "course": race["course"],
        "race_no": int(race["race_no"]), "race_name": race["race_name"],
        "saved_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model_version": APP_VERSION, "settings": settings, "metrics": metrics,
        "top4": top, "bets": [list(c) for c in itertools.combinations(sorted(top), 3)],
        "bet_unit": int(bet_unit), "horses": horses,
    }


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
    # JRA 3連複払戻は100円あたり。4点のうち的中1点に対して計算。
    payout = int(result["trio_payout_100yen"]) * int(pred["bet_unit"]) // 100 if hit else 0
    return hit, stake, payout


settings = {"min_coverage": min_coverage, "min_gap": min_gap,
    "min_confidence": min_confidence, "max_recommendations": max_recommendations,
    "min_top_history": min_top_history, "min_top_dirt": min_top_dirt}

st.sidebar.divider()
st.sidebar.header("📆 開催日（保存時に必須）")
st.sidebar.caption("Excel内の実際の開催日を指定してください。誤った日付で保存すると別レースとして記録されます。")
sat_date = st.sidebar.date_input("土曜日の開催日", value=datetime.date.today(), key="sat_date")
sun_date = st.sidebar.date_input("日曜日の開催日", value=datetime.date.today() + datetime.timedelta(days=1), key="sun_date")


def choose_races(day):
    selected, excluded = [], []
    for race in [r for r in all_loaded_races if r["day_label"] == day]:
        metrics, reason, df = screen_race(race, min_coverage, min_gap, min_confidence, min_top_history, min_top_dirt)
        if metrics is None:
            excluded.append((race["race_name"], reason))
        else:
            selected.append((race, metrics, df))
    selected.sort(key=lambda x: (x[1]["score"], x[1]["gap"]), reverse=True)
    for r, m, _ in selected[max_recommendations:]:
        excluded.append((r["race_name"], "上限超過"))
    return selected[:max_recommendations], excluded


def render_races(day, date):
    selected, excluded = choose_races(day)
    st.info(f"推奨 {len(selected)} レース・除外 {len(excluded)} レース")
    with st.expander("除外レースと理由"):
        for name, reason in excluded:
            st.write(name, "：", reason)
    if not selected:
        st.warning("推奨レースはありません。")
        return
    for race, metrics, df in selected:
        top = [int(x) for x in df.head(4)["horse_no"]]
        st.subheader(f"🏇 {race['race_name']}　評価 {metrics['score']}点")
        st.write("推奨4頭:", "・".join(map(str, top)), "／ 4位-5位指数差:", metrics["gap"])
        with st.expander("買い目・全馬指数"):
            st.dataframe(pd.DataFrame([{"3連複": "-".join(map(str, x)), "金額": bet_unit} for x in itertools.combinations(sorted(top), 3)]), hide_index=True)
            st.dataframe(df, hide_index=True)
        if st.button("💾 このレースの予想を確定保存", key="save_" + race_key(date, race)):
            rec = snapshot(date, race, metrics, df, settings)
            path = f"predictions/{date.year}/{rec['race_id']}.json"
            try:
                if put_record(path, rec):
                    st.success("保存しました。予想は固定され、再保存しても上書きされません。")
                else:
                    st.warning("このレースの予想は保存済みです。上書きしていません。")
            except Exception as e:
                st.error("保存失敗: " + str(e))
                st.download_button("バックアップJSONを保存", json.dumps(rec, ensure_ascii=False, indent=2), file_name=rec["race_id"]+".json", key="backup_"+rec["race_id"])
        st.divider()


t1, t2, t3, t4 = st.tabs(["📅 土曜推奨", "📅 日曜推奨", "📝 結果登録", "📊 長期成績"])
with t1:
    st.caption(f"保存対象開催日: {sat_date}　※必ず実際の開催日を確認")
    render_races("土曜日開催", sat_date)
with t2:
    st.caption(f"保存対象開催日: {sun_date}　※必ず実際の開催日を確認")
    render_races("日曜日開催", sun_date)

with t3:
    st.subheader("確定結果の登録・訂正")
    if st.button("🔄 保存済み履歴を読み直す", key="refresh_history"):
        st.rerun()
    try:
        predictions, results = read_all_history()
        if not predictions:
            st.info("保存済みの予想がありません。まず推奨レースを確定保存してください。")
        else:
            ids = sorted(predictions, reverse=True)
            rid = st.selectbox("結果を登録・訂正するレース", ids,
                format_func=lambda k: predictions[k]["race_name"] + " / " + predictions[k]["race_date"] + (" 【登録済み】" if k in results else " 【未登録】"))
            pred = predictions[rid]
            old = results.get(rid)
            st.write("保存済み推奨馬番:", pred["top4"])
            if old:
                st.info("登録済みの結果を表示しています。訂正して保存できます。予想履歴は変更しません。")
            initial = [int(x) for x in old["top3"]] if old else [1, 2, 3]
            with st.form("result_form_" + rid):
                a = st.number_input("1着馬番", 1, 18, initial[0], key="first_" + rid)
                b = st.number_input("2着馬番", 1, 18, initial[1], key="second_" + rid)
                c = st.number_input("3着馬番", 1, 18, initial[2], key="third_" + rid)
                payout = st.number_input("3連複確定払戻（100円あたり・円）", 0, 100000000,
                    int(old.get("trio_payout_100yen", 0)) if old else 0, step=10, key="payout_" + rid)
                reason = st.text_input("訂正理由（訂正時のみ）", placeholder="例：2着と3着を取り違えた", key="reason_" + rid) if old else ""
                confirmed = st.checkbox("登録内容を確認しました", key="confirmed_" + rid)
                submitted = st.form_submit_button("✏️ 訂正して保存" if old else "💾 確定結果を保存")
            if submitted:
                if not confirmed:
                    st.error("確認欄にチェックを入れてください。")
                elif len({a, b, c}) != 3:
                    st.error("1〜3着に同じ馬番は指定できません（同着レースは未対応）。")
                elif old and not reason.strip():
                    st.error("訂正時は理由を入力してください。")
                else:
                    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    record = {
                        "race_id": rid, "race_date": pred["race_date"],
                        "top3": [int(a), int(b), int(c)],
                        "trio_payout_100yen": int(payout),
                        "saved_at_utc": old.get("saved_at_utc", now) if old else now,
                        "updated_at_utc": now,
                        "note": "同着・返還・取消がない通常レース用",
                        "revision_history": list(old.get("revision_history", [])) if old else [],
                    }
                    if old:
                        record["revision_history"].append({
                            "corrected_at_utc": now, "reason": reason.strip(),
                            "previous_top3": old["top3"],
                            "previous_trio_payout_100yen": old["trio_payout_100yen"],
                        })
                    path = f"results/{pred['race_date'][:4]}/{rid}.json"
                    try:
                        if put_record(path, record, overwrite=bool(old)):
                            hit, stake, received = outcome(pred, record)
                            st.success(f"{'訂正' if old else '登録'}完了：{'的中' if hit else '不的中'} ／ 投資 {stake:,}円 ／ 払戻 {received:,}円")
                            st.rerun()
                        else:
                            st.warning("すでに結果が登録されています。履歴を再読み込みしてください。")
                    except Exception as e:
                        st.error("結果保存失敗: " + str(e))
    except Exception as e:
        st.error("履歴取得に失敗: " + str(e))

with t4:
    st.subheader("長期成績")
    try:
        predictions, results = read_all_history()
        records = []
        for rid, pred in predictions.items():
            result = results.get(rid)
            hit, stake, received = outcome(pred, result) if result else (None, None, None)
            records.append({"日付": pred["race_date"], "レース": pred["race_name"],
                "推奨4頭": ",".join(map(str, pred["top4"])), "評価点": pred["metrics"]["score"],
                "状態": "未登録" if result is None else ("的中" if hit else "不的中"),
                "投資額": stake, "払戻額": received,
                "損益": (received-stake) if result else None,
                "指数差": pred["metrics"]["gap"], "モデル": pred["model_version"]})
        df_hist = pd.DataFrame(records)
        if df_hist.empty:
            st.info("まだ履歴がありません。")
        else:
            completed = df_hist[df_hist["状態"] != "未登録"]
            n = len(completed)
            hits = int((completed["状態"] == "的中").sum())
            invested = int(completed["投資額"].sum())
            paid = int(completed["払戻額"].sum())
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("結果登録", n)
            c2.metric("的中率", f"{hits/n*100:.1f}%" if n else "—")
            c3.metric("回収率", f"{paid/invested*100:.1f}%" if invested else "—")
            c4.metric("累計損益", f"{paid-invested:+,}円")
            # 的中レースを緑、不的中を薄い赤、未登録を淡いグレーで区別。
            # データそのものは変更せず、表示時のみスタイルを適用する。
            def color_result_row(row):
                state = row["状態"]
                if state == "的中":
                    bg, fg = "#174b36", "#e7fff0"
                elif state == "不的中":
                    bg, fg = "#4a262b", "#ffe9e9"
                else:
                    bg, fg = "#303640", "#e2e8f0"
                return [f"background-color: {bg}; color: {fg};" for _ in row]

            display_hist = df_hist.sort_values("日付", ascending=False)
            st.caption("🟩 的中　🟥 不的中　⬜ 結果未登録")
            st.dataframe(
                display_hist.style.apply(color_result_row, axis=1),
                hide_index=True,
                use_container_width=True,
            )
            st.download_button("📥 履歴CSVをダウンロード", df_hist.to_csv(index=False).encode("utf-8-sig"), "jra_history.csv", "text/csv")
            st.caption("未登録レースは成績計算から除外。購入実績ではなく推奨4点を各設定金額で購入した場合のシミュレーションです。")
    except Exception as e:
        st.error("長期成績の取得に失敗: " + str(e))

st.caption("⚠️ 同着・返還・取消・不成立の結果は現バージョンでは登録しないでください。JRA確定情報を確認し、通常レースのみ登録してください。")
