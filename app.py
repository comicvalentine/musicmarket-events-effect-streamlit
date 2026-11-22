"""이벤트 코호트 리텐션 대시보드 — 밑그림(blueprint).

마케팅 이벤트 하나를 고르면, 그 전후 스트리밍 지표를 세 가지 코호트 축으로 나눠
"관심(일시적 반응)"과 "팬(남는 반응)"을 구분해본다. 모든 데이터는 합성(가상)이다.

축 1. Active vs Programmed — 직접 찾아 들은 사람 vs 추천·플레이리스트로 들어온 사람
축 2. 국가 — 이벤트 대상국 vs 나머지 국가(비교군)
축 3. 신곡 vs 기존곡 — 이벤트 시점의 "가장 최근 발매" 수록곡 vs 그 이전 발매 수록곡

실행: streamlit run app.py
"""

import csv
import sqlite3
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import truth

DB_PATH = Path(__file__).parent / "event_effect.sqlite"
PRE_WINDOW = (-28, -1)   # 베이스라인으로 쓰는 이벤트 이전 구간

st.set_page_config(page_title="이벤트 코호트 리텐션 (밑그림)", layout="wide")


@st.cache_resource
def get_conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def run(sql: str, params: dict | None = None) -> pd.DataFrame:
    return pd.read_sql_query(sql, get_conn(), params=params or {})


# ---------------------------------------------------------------- 이벤트 선택
# '이벤트'는 두 종류를 합쳐서 고른다: marketing_events(공연·페스티벌 등, 국가별)와
# dim_release(발매, 국가 구분 없이 전 세계 동시). 발매는 country가 없으므로 따로 고른다.

MARKETING_SQL = """
SELECT e.event_id AS id, e.artist_id, a.artist_name, e.date, e.name, e.kind, e.target_country
FROM marketing_events e JOIN dim_artist a ON a.artist_id = e.artist_id
"""
RELEASE_SQL = """
SELECT r.release_id AS id, r.artist_id, a.artist_name, r.release_date AS date,
       r.title AS name, '발매' AS kind, NULL AS target_country
FROM dim_release r JOIN dim_artist a ON a.artist_id = r.artist_id
WHERE r.release_date >= (SELECT MIN(date) FROM fact_spotify_artist_daily)
"""
events = pd.concat([run(MARKETING_SQL), run(RELEASE_SQL)], ignore_index=True).sort_values("date")

st.title("이벤트 코호트 리텐션 대시보드")
st.caption("합성 데이터(가상 아티스트 11명). 실제 아티스트·수치와 무관합니다.")

if "event_toast" in st.session_state:
    st.toast(st.session_state.pop("event_toast"))

artist_names = sorted(events["artist_name"].unique())
picked_artist = st.sidebar.selectbox("아티스트", artist_names)
events_scoped = events[events["artist_name"] == picked_artist].copy()
events_scoped["label"] = events_scoped["date"] + " · " + events_scoped["kind"] + " · " + events_scoped["name"]

picked_label = st.sidebar.selectbox("이벤트 (마케팅 또는 발매)", events_scoped["label"])
ev = events_scoped.loc[events_scoped["label"] == picked_label].iloc[0]
artist_id, event_date = ev["artist_id"], ev["date"]
is_release = pd.isna(ev["target_country"])

COUNTRIES = ["KR", "JP", "US", "TW", "ID"]
FOCUS_COUNTRIES = ["전체"] + COUNTRIES
if is_release:
    default_country = run("SELECT home_country FROM dim_artist WHERE artist_id = :aid", dict(aid=artist_id)).iloc[0, 0]
else:
    default_country = ev["target_country"]
target_country = st.sidebar.selectbox("포커스 국가", FOCUS_COUNTRIES, index=FOCUS_COUNTRIES.index(default_country))
all_countries = target_country == "전체"

st.subheader(f"{ev['artist_name']} · {ev['name']} ({ev['kind']}) · {event_date} · 포커스 국가 {target_country}")

platform = st.sidebar.radio("플랫폼", ["Spotify", "Apple Music"])

st.sidebar.markdown("**카드 윈도우 (이벤트 후 며칠)**")
wcol1, wcol2, wcol3 = st.sidebar.columns(3)
w1 = wcol1.number_input("윈도우 1", min_value=1, max_value=180, value=7, label_visibility="collapsed")
w2 = wcol2.number_input("윈도우 2", min_value=1, max_value=180, value=14, label_visibility="collapsed")
w3 = wcol3.number_input("윈도우 3", min_value=1, max_value=180, value=28, label_visibility="collapsed")
DELTA_WINDOWS = tuple(sorted({int(w1), int(w2), int(w3)}))

PLOT_HALF = max(35, DELTA_WINDOWS[-1])  # 차트 범위는 가장 긴 윈도우를 항상 덮도록 자동으로 넓힌다
PLOT_WINDOW = (-PLOT_HALF, PLOT_HALF)


# ---------------------------------------------------------------- 마케팅 이벤트 추가 (사용자 입력 → DB)

EVENT_KINDS = ["공연", "페스티벌", "방송", "플레이리스트 프로모션", "SNS 광고"]

with st.sidebar.expander("+ 마케팅 이벤트 추가"):
    artists_df = run("SELECT artist_id, artist_name FROM dim_artist ORDER BY artist_name")
    data_lo, data_hi = run("SELECT MIN(date) AS lo, MAX(date) AS hi FROM fact_spotify_artist_daily").iloc[0]
    data_lo, data_hi = pd.to_datetime(data_lo).date(), pd.to_datetime(data_hi).date()
    with st.form("add_event_form", clear_on_submit=True):
        f_artist_name = st.selectbox("아티스트", artists_df["artist_name"])
        f_date = st.date_input("날짜", value=data_hi, min_value=data_lo, max_value=data_hi)
        f_name = st.text_input("이벤트명")
        f_kind = st.selectbox("종류", EVENT_KINDS)
        f_country = st.selectbox("대상국", COUNTRIES)
        submitted = st.form_submit_button("추가", type="primary")

    if submitted:
        f_artist_id = artists_df.loc[artists_df["artist_name"] == f_artist_name, "artist_id"].iloc[0]
        existing = run("SELECT event_id FROM marketing_events WHERE event_id LIKE 'U%'")
        next_n = 1 if existing.empty else int(existing["event_id"].str[1:].astype(int).max()) + 1
        new_id = f"U{next_n:03d}"
        row = dict(event_id=new_id, artist_id=f_artist_id, date=f_date.isoformat(),
                   name=f_name or f_kind, kind=f_kind, target_country=f_country, apple=1)

        con = get_conn()
        con.execute(
            "INSERT INTO marketing_events (event_id, artist_id, date, name, kind, target_country, apple) "
            "VALUES (:event_id, :artist_id, :date, :name, :kind, :target_country, :apple)",
            row,
        )
        con.commit()
        with (Path(__file__).parent / "data" / "marketing_events.csv").open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([row["event_id"], row["artist_id"], row["date"], row["name"],
                                     row["kind"], row["target_country"], row["apple"]])

        st.session_state["event_toast"] = f"'{row['name']}' 이벤트를 추가했습니다."
        st.rerun()


# ---------------------------------------------------------------- 공통: 베이스라인 지수화

def _index_by_series(long_df: pd.DataFrame) -> pd.DataFrame:
    """long_df에 day_offset, series, value가 있다고 보고, series별 이벤트 이전(PRE_WINDOW) 평균을
    100으로 둔 index_100 컬럼을 추가한다. 신곡처럼 이벤트(발매) 이전 데이터가 아예 없는 series는
    PRE_WINDOW에 값이 없으므로, 대신 가장 이른 관측치(보통 발매 당일)를 100으로 삼는다."""
    pre_mean = (
        long_df.loc[long_df["day_offset"].between(*PRE_WINDOW)]
        .groupby("series")["value"].mean()
    )
    first_val = long_df.sort_values("day_offset").groupby("series")["value"].first()
    baseline = pre_mean.combine_first(first_val).rename("baseline")
    long_df = long_df.join(baseline, on="series")
    long_df["index_100"] = long_df["value"] / long_df["baseline"] * 100
    return long_df


def to_index_wide(df: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    """지표마다 컬럼이 따로 있는 경우(축 1: active_streams, programmed_streams 컬럼).
    컬럼 이름을 series 값으로 녹여(melt) 지수화한다."""
    long_rows = []
    for col in value_cols:
        sub = df[["day_offset", col]].rename(columns={col: "value"})
        sub["series"] = col
        long_rows.append(sub)
    return _index_by_series(pd.concat(long_rows, ignore_index=True))


def to_index_long(df: pd.DataFrame, series_col: str, value_col: str) -> pd.DataFrame:
    """코호트가 이미 한 컬럼의 값으로 들어 있는 경우(축 2: country 그룹, 축 3: cohort)."""
    long_df = df[["day_offset", series_col, value_col]].rename(
        columns={series_col: "series", value_col: "value"}
    )
    return _index_by_series(long_df)


def summary_cards(idx_df: pd.DataFrame, domain: list[str] | None = None) -> None:
    """Mixpanel 식 요약 카드: series마다 큰 숫자(최근값) + 스파크라인 + 7/14/28일 후 변화율.
    idx_df는 line_chart에 넣는 것과 같은 long-format(day_offset, series, value, index_100).
    domain을 주면 그 순서대로 카드를 배열해 line_chart의 범례 순서와 맞춘다."""
    series_list = idx_df["series"].dropna().unique().tolist()
    if domain:
        series_list = [s for s in domain if s in series_list] + [s for s in series_list if s not in domain]
    cols = st.columns(len(series_list))
    for col, s in zip(cols, series_list):
        d = idx_df.loc[idx_df["series"] == s].sort_values("day_offset")
        with col:
            latest = d.iloc[-1]
            st.markdown(f"**{s}**")
            st.markdown(f"### {latest['value']:,.0f}")
            spark = (
                alt.Chart(d)
                .mark_line(color="#6250d6")
                .encode(x=alt.X("day_offset:Q", axis=None), y=alt.Y("index_100:Q", axis=None, scale=alt.Scale(zero=False)))
                .properties(height=50)
            )
            st.altair_chart(spark, use_container_width=True)
            wcols = st.columns(len(DELTA_WINDOWS))
            for wcol, w in zip(wcols, DELTA_WINDOWS):
                row = d.loc[d["day_offset"] == w]
                if row.empty:
                    wcol.metric(f"{w}일 후", "–")
                else:
                    idx_val = row.iloc[0]["index_100"]
                    wcol.metric(f"{w}일 후", f"{idx_val:.0f}", delta=f"{idx_val - 100:+.1f}%")


# 두 코호트 비교에 쓰는 고정 2색(파랑/주황) — CVD 안전성 검증됨(dataviz 스킬). domain 순서로
# "누가 파랑이고 누가 주황인지"를 고정해서, 데이터 순서가 바뀌어도 같은 대상은 항상 같은 색이 되게 한다.
COHORT_COLORS = ["#2a78d6", "#eb6834"]


def line_chart(df: pd.DataFrame, color_field: str, title: str, domain: list[str] | None = None) -> alt.Chart:
    color = alt.Color(f"{color_field}:N", title=None,
                       scale=alt.Scale(domain=domain, range=COHORT_COLORS) if domain else alt.Undefined)
    rule = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#999", strokeDash=[4, 4]).encode(x="x:Q")
    line = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("day_offset:Q", title="이벤트 기준 날짜 (0 = 이벤트 당일)"),
            y=alt.Y("index_100:Q", title="지수 (이벤트 전 28일 평균 = 100)", scale=alt.Scale(zero=False)),
            color=color,
            tooltip=["day_offset", color_field, alt.Tooltip("index_100:Q", format=".1f")],
        )
        .properties(title=title, height=320)
    )
    return (line + rule).interactive()


# ---------------------------------------------------------------- 축 1. Active vs Programmed

SQL_ACTIVE_PROGRAMMED = f"""
SELECT date,
       CAST(julianday(date) - julianday(:event_date) AS INTEGER) AS day_offset,
       SUM(active_listeners) AS active_listeners, SUM(programmed_listeners) AS programmed_listeners,
       SUM(active_streams) AS active_streams, SUM(programmed_streams) AS programmed_streams
FROM fact_spotify_artist_daily
WHERE artist_id = :artist_id {"" if all_countries else "AND country = :target_country"}
  AND julianday(date) - julianday(:event_date) BETWEEN :lo AND :hi
GROUP BY date
ORDER BY date
"""

COHORT_DOMAIN_1 = ["Active", "Programmed"]

if platform == "Spotify":
    st.caption("축 1")
    st.subheader("Active vs Programmed 청취")

    df1 = run(SQL_ACTIVE_PROGRAMMED, dict(event_date=event_date, artist_id=artist_id,
                                          target_country=target_country, lo=PLOT_WINDOW[0], hi=PLOT_WINDOW[1]))
    df1["active_spl"] = df1["active_streams"] / df1["active_listeners"]
    df1["programmed_spl"] = df1["programmed_streams"] / df1["programmed_listeners"]

    idx1a = to_index_wide(df1, ["active_listeners", "programmed_listeners"])
    idx1a["series"] = idx1a["series"].map({"active_listeners": "Active", "programmed_listeners": "Programmed"})
    summary_cards(idx1a, domain=COHORT_DOMAIN_1)
    st.altair_chart(line_chart(idx1a, "series", "청취자 지수", domain=COHORT_DOMAIN_1), use_container_width=True)

    idx1b = to_index_wide(df1, ["active_spl", "programmed_spl"])
    idx1b["series"] = idx1b["series"].map({"active_spl": "Active", "programmed_spl": "Programmed"})
    st.altair_chart(line_chart(idx1b, "series", "청취자 당 스트림(관여도) 지수", domain=COHORT_DOMAIN_1),
                     use_container_width=True)


# ---------------------------------------------------------------- 축 2. 국가 (대상국 vs 비교군)

if not all_countries:
    if platform == "Spotify":
        SQL_COUNTRY = """
SELECT date, country,
       CAST(julianday(date) - julianday(:event_date) AS INTEGER) AS day_offset,
       active_listeners + programmed_listeners AS listeners,
       active_streams + programmed_streams AS streams
FROM fact_spotify_artist_daily
WHERE artist_id = :artist_id
  AND julianday(date) - julianday(:event_date) BETWEEN :lo AND :hi
ORDER BY country, date
"""
    else:
        SQL_COUNTRY = """
SELECT date, country,
       CAST(julianday(date) - julianday(:event_date) AS INTEGER) AS day_offset,
       listeners, plays AS streams
FROM fact_apple_artist_daily
WHERE artist_id = :artist_id
  AND julianday(date) - julianday(:event_date) BETWEEN :lo AND :hi
ORDER BY country, date
"""

    st.caption("축 2")
    st.subheader("국가 — 대상국 vs 비교군")

    df2 = run(SQL_COUNTRY, dict(event_date=event_date, artist_id=artist_id, lo=PLOT_WINDOW[0], hi=PLOT_WINDOW[1]))
    df2["group"] = df2["country"].apply(lambda c: f"대상국 {c}" if c == target_country else "비교군")
    grp2 = df2.groupby(["group", "day_offset"], as_index=False)[["listeners", "streams"]].sum()
    grp2["spl"] = grp2["streams"] / grp2["listeners"]
    country_domain = [f"대상국 {target_country}", "비교군"]

    idx2a = to_index_long(grp2, "group", "listeners")
    summary_cards(idx2a, domain=country_domain)
    st.altair_chart(line_chart(idx2a, "series", "청취자 지수", domain=country_domain), use_container_width=True)

    idx2b = to_index_long(grp2, "group", "spl")
    st.altair_chart(line_chart(idx2b, "series", "청취자 당 스트림(관여도) 지수", domain=country_domain),
                     use_container_width=True)


# ---------------------------------------------------------------- 축 3. 신곡 vs 기존곡

SQL_FOCUS_RELEASE = """
SELECT release_id, title, release_date
FROM dim_release
WHERE artist_id = :artist_id AND release_date <= :event_date
ORDER BY release_date DESC
LIMIT 1
"""

SQL_TRACK_DAILY = f"""
SELECT s.date,
       CAST(julianday(s.date) - julianday(:event_date) AS INTEGER) AS day_offset,
       CASE WHEN t.release_id = :focus_release_id THEN '신곡 (최신 발매)' ELSE '기존곡 (카탈로그)' END AS cohort,
       SUM(s.streams) AS streams, SUM(s.listeners) AS listeners
FROM fact_spotify_track_daily s
JOIN dim_track t ON t.track_id = s.track_id
WHERE t.artist_id = :artist_id {"" if all_countries else "AND s.country = :target_country"}
  AND julianday(s.date) - julianday(:event_date) BETWEEN :lo AND :hi
GROUP BY s.date, cohort
ORDER BY s.date
"""

_apple_country_clause = "" if all_countries else "AND country = :target_country"
SQL_APPLE_COHORT = f"""
SELECT date, CAST(julianday(date) - julianday(:event_date) AS INTEGER) AS day_offset,
       cohort, SUM(plays) AS plays
FROM (
    SELECT date, '신곡 (최신 발매)' AS cohort, aaa_plays AS plays
    FROM fact_apple_artist_daily
    WHERE artist_id = :artist_id {_apple_country_clause}
      AND julianday(date) - julianday(:event_date) BETWEEN :lo AND :hi
    UNION ALL
    SELECT date, '기존곡 (카탈로그)' AS cohort, non_aaa_plays AS plays
    FROM fact_apple_artist_daily
    WHERE artist_id = :artist_id {_apple_country_clause}
      AND julianday(date) - julianday(:event_date) BETWEEN :lo AND :hi
)
GROUP BY date, cohort
ORDER BY date
"""

COHORT_DOMAIN_3 = ["신곡 (최신 발매)", "기존곡 (카탈로그)"]

st.caption("축 3")
st.subheader("신곡 vs 기존곡")

focus = run(SQL_FOCUS_RELEASE, dict(artist_id=artist_id, event_date=event_date))
if focus.empty:
    st.warning("이 아티스트는 이벤트 시점 이전 발매 기록이 없습니다 (전부 '기존곡' 비교 대상이 없음).")
else:
    focus_release_id, focus_title, focus_date = focus.iloc[0][["release_id", "title", "release_date"]]
    st.caption(f"신곡 기준 앨범: **{focus_title}** (발매 {focus_date})")

    if platform == "Spotify":
        df3 = run(SQL_TRACK_DAILY, dict(event_date=event_date, artist_id=artist_id, target_country=target_country,
                                         focus_release_id=focus_release_id, lo=PLOT_WINDOW[0], hi=PLOT_WINDOW[1]))
        df3["spl"] = df3["streams"] / df3["listeners"]

        idx3a = to_index_long(df3, "cohort", "listeners")
        summary_cards(idx3a, domain=COHORT_DOMAIN_3)
        st.altair_chart(line_chart(idx3a, "series", "청취자(근사) 지수", domain=COHORT_DOMAIN_3),
                         use_container_width=True)

        idx3b = to_index_long(df3, "cohort", "spl")
        st.altair_chart(line_chart(idx3b, "series", "청취자 당 스트림(관여도) 지수", domain=COHORT_DOMAIN_3),
                         use_container_width=True)
    else:
        df3 = run(SQL_APPLE_COHORT, dict(event_date=event_date, artist_id=artist_id,
                                          target_country=target_country, lo=PLOT_WINDOW[0], hi=PLOT_WINDOW[1]))
        idx3 = to_index_long(df3, "cohort", "plays")
        summary_cards(idx3, domain=COHORT_DOMAIN_3)
        st.altair_chart(line_chart(idx3, "series", "신곡 vs 기존곡 재생 지수", domain=COHORT_DOMAIN_3),
                         use_container_width=True)

