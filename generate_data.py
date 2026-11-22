"""합성 스트리밍 데이터 생성기 — 가상 아티스트 11명, 발매·곡 단위.

모든 아티스트명·곡명·값·추세·이벤트 날짜는 이 스크립트가 지어낸 것이다.
실제 데이터에서 참고한 것은 Spotify for Artists / Apple Music for Artists 내보내기의
컬럼 구조(active / programmed 청취자·스트림, 팔로워, plays, 곡별 timeline)뿐이다.

실행:  python3 generate_data.py          (표준 라이브러리만 사용)
결과:  data/*.csv, data/fact_spotify_track_daily.csv.gz
구조:  SCHEMA.md 참고
"""

import csv
import datetime as dt
import gzip
import math
import random
from pathlib import Path

SEED = 20261113
rng = random.Random(SEED)
ROOT = Path(__file__).parent
OUT = ROOT / "data"

START, END = dt.date(2025, 1, 1), dt.date(2026, 11, 22)
DAYS = [START + dt.timedelta(i) for i in range((END - START).days + 1)]
N = len(DAYS)

# 발매·이벤트 날짜 구간을 전부 START/END 기준 상대값으로 잡는다(하드코딩된 연도 금지 —
# START/END를 바꿀 때 여기 손댈 필요가 없게).
CATALOG_LO1, CATALOG_HI1 = (START - dt.timedelta(days=1037)).isoformat(), (START - dt.timedelta(days=366)).isoformat()
CATALOG_LO2, CATALOG_HI2 = (START - dt.timedelta(days=365)).isoformat(), (START - dt.timedelta(days=32)).isoformat()
NEW_REL_LO, NEW_REL_HI = (START + dt.timedelta(days=31)).isoformat(), (END - dt.timedelta(days=31)).isoformat()
EVENT_LO, EVENT_HI = (START + dt.timedelta(days=45)).isoformat(), (END - dt.timedelta(days=46)).isoformat()
EVENT_VALID_LO, EVENT_VALID_HI = START + dt.timedelta(days=31), END - dt.timedelta(days=30)
WEEKDAY = [0.97, 0.98, 0.99, 1.00, 1.04, 1.06, 1.00]

COUNTRIES = [("KR", "대한민국"), ("JP", "일본"), ("US", "미국"), ("TW", "대만"), ("ID", "인도네시아"), ("OTHERS", "기타")]
CC = [c for c, _ in COUNTRIES]
EVENT_CC = [c for c in CC if c != "OTHERS"]  # 공연 등 이벤트는 특정 국가에서 열리므로 OTHERS는 대상에서 제외

# 시장별 반응 차이 가설(가상): 아시아는 현지 공연 뒤 기존 팬이 직접 찾아 듣는 반응이
# 느리게 꺼지고 카탈로그(기존곡)까지 다시 찾아 듣는다. 북미는 신곡 발매 직후에만
# 반짝 반응하고 공연 효과는 빨리 꺼진다. 실제 특정 아티스트 사례가 아니라
# 이 생성기 안에서 지역 공통으로 적용하는 가상의 규칙이다.
ASIA = {"KR", "JP", "TW", "ID"}
CONCERT_KINDS = {"공연", "페스티벌"}
ASIA_TAU_MULT, NA_TAU_MULT = 2.2, 0.55       # 공연류 이벤트의 al/fol 지속 기간 배수
ASIA_CATALOG_AMP = 0.9                        # 아시아 공연 뒤 '기존곡' 트랙에 추가로 붙는 재청취 펄스 크기

# ---------------------------------------------------------------- 아티스트 (전부 가상)
# scale: 전체 국가 합산 일일 청취자 규모 / mix: 국가 비중(4개국 기준, 아래서 ID 추가) / g: 연간 성장(log)
ARTISTS = [
    ("A01", "Lumen Tide",          "인디 록",   "KR", 2019, "Low Orbit Records", 16000, dict(KR=.50, JP=.22, US=.16, TW=.12), .30),
    ("A02", "소금빛 라디오",         "포크",      "KR", 2017, "Low Orbit Records",  6000, dict(KR=.78, JP=.10, US=.06, TW=.06), .08),
    ("A03", "NOVA//9",             "K-POP",    "KR", 2022, "Brightline Ent.",   60000, dict(KR=.30, JP=.28, US=.24, TW=.18), .45),
    ("A04", "Pale Comet",          "드림팝",    "KR", 2020, "Low Orbit Records",  5000, dict(KR=.40, JP=.15, US=.30, TW=.15), .20),
    ("A05", "Midnight Ferry",      "시티팝",    "JP", 2018, "Harbor Tone",        9000, dict(KR=.22, JP=.58, US=.10, TW=.10), .12),
    ("A06", "Glass Orchard",       "일렉트로닉", "US", 2016, "Coldframe",          11000, dict(KR=.12, JP=.13, US=.65, TW=.10), .05),
    ("A07", "모래시계 클럽",         "힙합",      "KR", 2021, "Sandglass",          14000, dict(KR=.82, JP=.06, US=.07, TW=.05), .25),
    ("A08", "Hollow Velour",       "R&B",      "KR", 2019, "Brightline Ent.",     8000, dict(KR=.55, JP=.12, US=.18, TW=.15), .18),
    ("A09", "Tangerine Static",    "얼터너티브", "US", 2015, "Coldframe",           7000, dict(KR=.15, JP=.10, US=.62, TW=.13), -.05),
    ("A10", "Lantern Society",     "재즈",      "TW", 2018, "Harbor Tone",         3500, dict(KR=.20, JP=.20, US=.15, TW=.45), .10),
    ("A11", "Quiet Avalanche",     "포스트록",   "KR", 2014, "Low Orbit Records",  4500, dict(KR=.35, JP=.30, US=.20, TW=.15), .02),
]

# 인도네시아를 뒤늦게 시장에 추가: 기존 4개국 비중을 10% 줄이고 그만큼 ID에 배정
ID_SHARE = 0.10
ARTISTS = [
    a[:7] + ({**{k: v * (1 - ID_SHARE) for k, v in a[7].items()}, "ID": ID_SHARE},) + a[8:]
    for a in ARTISTS
]

# 5개국 밖 나머지 전세계 스트림을 OTHERS로 묶음: 기존 5개국 비중을 20% 줄이고 그만큼 OTHERS에 배정
OTHERS_SHARE = 0.20
ARTISTS = [
    a[:7] + ({**{k: v * (1 - OTHERS_SHARE) for k, v in a[7].items()}, "OTHERS": OTHERS_SHARE},) + a[8:]
    for a in ARTISTS
]

WORDS_A = ["Paper", "Silver", "Northern", "Glass", "Velvet", "Hollow", "Distant", "Neon", "Quiet", "Burning",
           "Lunar", "Salt", "Amber", "Static", "Winter", "Golden", "Slow", "Electric", "Paper", "Faded"]
WORDS_B = ["Moon", "Orbit", "Harbor", "Signal", "Garden", "Tide", "Room", "Letter", "Summer", "Motel",
           "Ferry", "Lantern", "Weather", "Avenue", "Static", "Hour", "Comet", "Window", "Island", "Engine"]
used_titles = set()


def title():
    while True:
        t = f"{rng.choice(WORDS_A)} {rng.choice(WORDS_B)}"
        if rng.random() < 0.25:
            t += rng.choice([" (Live)", " Part II", " Reprise", " (Interlude)"])
        if t not in used_titles:
            used_titles.add(t)
            return t


def rand_date(lo, hi):
    a, b = dt.date.fromisoformat(lo), dt.date.fromisoformat(hi)
    return a + dt.timedelta(rng.randrange((b - a).days + 1))


def idx(d):
    return (d - START).days


def pulse(t, t0, amp, lag, tau):
    s = t - t0 - lag
    return 0.0 if s < 0 or amp == 0 else amp * math.exp(-s / tau)


def ar1(n, phi, sd):
    e, out = 0.0, []
    for _ in range(n):
        e = phi * e + rng.gauss(0, sd)
        out.append(e)
    return out


def year_end(d):
    return 1 + 0.06 * math.exp(-(((d.timetuple().tm_yday - 356) / 10) ** 2))


# ---------------------------------------------------------------- 발매 · 곡
TRACK_COUNT = {"싱글": (1, 2), "EP": (4, 6), "정규": (9, 12)}
releases, tracks = [], []
rel_seq = trk_seq = 0
for a in ARTISTS:
    aid = a[0]
    plan = [("정규", CATALOG_LO1, CATALOG_HI1), (rng.choice(["EP", "싱글"]), CATALOG_LO2, CATALOG_HI2)]
    n_new = rng.choice([2, 2, 3])
    for _ in range(n_new):
        plan.append((rng.choices(["싱글", "EP", "정규"], [5, 3, 2])[0], NEW_REL_LO, NEW_REL_HI))
    dates_new = []
    for kind, lo, hi in plan:
        if lo == NEW_REL_LO:  # 신규 발매끼리 최소 90일 간격
            for _ in range(200):
                d = rand_date(lo, hi)
                if all(abs((d - x).days) >= 90 for x in dates_new):
                    break
            dates_new.append(d)
        else:
            d = rand_date(lo, hi)
        rel_seq += 1
        rid = f"R{rel_seq:03d}"
        releases.append(dict(release_id=rid, artist_id=aid, title=title(), release_type=kind, release_date=d))
        n_tr = rng.randint(*TRACK_COUNT[kind])
        focus_no = 1 if kind == "싱글" else rng.randint(1, min(3, n_tr))
        for no in range(1, n_tr + 1):
            trk_seq += 1
            tracks.append(dict(track_id=f"T{trk_seq:04d}", release_id=rid, artist_id=aid, title=title(),
                               track_no=no, duration_sec=rng.randint(150, 300) if a[2] != "포스트록" else rng.randint(280, 560),
                               is_focus=int(no == focus_no),
                               appeal=math.exp(rng.gauss(0, 0.5)) * (3.0 if no == focus_no else 1.0)))

# ---------------------------------------------------------------- 마케팅 이벤트 (= 심어 둔 효과)
KINDS = {
    #            al            pl               aspl          pspl           fol
    "공연":       lambda: dict(al=(rng.uniform(.15, .28), 0, rng.uniform(12, 20)), pl=(rng.uniform(.05, .10), 6, 22),
                             aspl=(rng.uniform(.06, .11), 0, 12), pspl=(0, 0, 1), fol=(rng.uniform(2, 3.5), 0, 7)),
    "페스티벌":    lambda: dict(al=(rng.uniform(.20, .32), 0, rng.uniform(10, 16)), pl=(rng.uniform(.06, .12), 5, 20),
                             aspl=(rng.uniform(.03, .07), 0, 10), pspl=(0, 0, 1), fol=(rng.uniform(2, 3), 0, 6)),
    "방송":       lambda: dict(al=(rng.uniform(.04, .12), 0, 7), pl=(0, 0, 1),
                             aspl=(rng.uniform(.01, .04), 0, 7), pspl=(0, 0, 1), fol=(rng.uniform(.6, 1.2), 0, 5)),
    "플레이리스트 프로모션": lambda: dict(al=(.02, 0, 10), pl=(rng.uniform(.30, .45), 0, 20),
                             aspl=(0, 0, 1), pspl=(rng.uniform(-.15, -.08), 0, 20), fol=(.3, 0, 5)),
    "SNS 광고":   lambda: dict(al=(rng.uniform(.06, .14), 0, 10), pl=(rng.uniform(.02, .05), 3, 14),
                             aspl=(rng.uniform(-.05, -.01), 0, 10), pspl=(0, 0, 1), fol=(rng.uniform(.8, 1.5), 0, 5)),
}
EVENT_NAMES = {"공연": ["단독 공연", "투어 공연", "쇼케이스"], "페스티벌": ["페스티벌 출연", "록 페스티벌 출연", "여름 페스티벌 출연"],
               "방송": ["음악 방송 출연", "라디오 출연", "예능 출연"], "플레이리스트 프로모션": ["유료 플레이리스트 프로모션"],
               "SNS 광고": ["SNS 광고 캠페인", "숏폼 광고 캠페인"]}
CITY = {"KR": "서울", "JP": "도쿄", "US": "LA", "TW": "타이베이", "ID": "자카르타"}

events = []
ev_seq = 0
for a in ARTISTS:
    aid, mix = a[0], a[7]
    my_rel = [r["release_date"] for r in releases if r["artist_id"] == aid and r["release_date"] >= START]
    chosen = []
    n_ev = rng.randint(3, 5)
    for k in range(n_ev):
        for _ in range(500):
            if k == 0 and my_rel:  # 아티스트마다 하나는 발매 7~12일 뒤에 둬서 교란 사례를 만든다
                d = rng.choice(my_rel) + dt.timedelta(rng.randint(7, 12))
            else:
                d = rand_date(EVENT_LO, EVENT_HI)
            if all(abs((d - x).days) >= 45 for x in chosen) and EVENT_VALID_LO <= d <= EVENT_VALID_HI:
                break
        chosen.append(d)
        kind = rng.choices(list(KINDS), [4, 3, 3, 1, 2])[0]
        country = rng.choices(EVENT_CC, [mix[c] for c in EVENT_CC])[0]
        base_name = rng.choice(EVENT_NAMES[kind])
        name = f"{CITY[country]} {base_name}" if kind in ("공연",) else base_name
        ev_seq += 1
        fx = KINDS[kind]()
        if kind in CONCERT_KINDS:
            # 공연류 이벤트는 지역에 따라 al(능동 청취자)·fol(팔로워) 반응이 꺼지는 속도를 다르게 만든다
            tau_mult = ASIA_TAU_MULT if country in ASIA else NA_TAU_MULT
            for key in ("al", "fol"):
                amp, lag, tau = fx[key]
                fx[key] = (amp, lag, tau * tau_mult)
        events.append(dict(event_id=f"E{ev_seq:03d}", artist_id=aid, date=d, name=name, kind=kind,
                           target_country=country, fx=fx, apple=kind != "플레이리스트 프로모션"))

# ---------------------------------------------------------------- 시계열
COMMON = ar1(N, 0.85, 0.020)        # 플랫폼 전체 공통 변동
COMMON_APPLE = ar1(N, 0.85, 0.020)

sp_rows, ap_rows, truth_rows = [], [], []
track_rows_count = 0
OUT.mkdir(exist_ok=True)
track_f = gzip.open(OUT / "fact_spotify_track_daily.csv.gz", "wt", newline="", encoding="utf-8")
track_w = csv.writer(track_f)
track_w.writerow(["date", "track_id", "country", "streams", "listeners"])

for a in ARTISTS:
    aid, scale, mix, g = a[0], a[6], a[7], a[8]
    artist_shock = ar1(N, 0.8, 0.015)  # 아티스트 고유 변동 (국가 공통)
    my_rel = [r for r in releases if r["artist_id"] == aid]
    my_trk = [t for t in tracks if t["artist_id"] == aid]
    rel_date = {r["release_id"]: r["release_date"] for r in my_rel}
    rel_kind = {r["release_id"]: r["release_type"] for r in my_rel}
    new_rel = [r for r in my_rel if r["release_date"] >= START]
    rel_amp = {"싱글": .30, "EP": .40, "정규": .55}
    share0 = rng.uniform(.38, .50)
    aspl0, pspl0 = rng.uniform(2.2, 3.0), rng.uniform(1.25, 1.55)
    my_rel_sorted = sorted(my_rel, key=lambda r: r["release_date"])  # '현재 최신 앨범' 추적용

    for c in CC:
        p = scale * mix[c]
        n_c = ar1(N, 0.5, 0.012)
        n_iid = [rng.gauss(0, 0.02) for _ in range(N)]
        a_c = ar1(N, 0.5, 0.015)
        my_ev = [e for e in events if e["artist_id"] == aid and e["target_country"] == c]
        res = {k: {"with": [], "without": []} for k in ["al", "pl", "ast", "pst", "a_l", "a_p", "fol"]}
        followers = {"with": p * 3.0, "without": p * 3.0}
        ap_scale = p * rng.uniform(.25, .55)
        rel_ptr, current_rid = 0, None  # 날짜가 지날 때마다 '현재 최신 앨범'을 갱신
        new_share = [0.0] * N  # 그날 스트림 중 신곡(현재 최신 앨범) 비중 — 애플 신곡/기존곡 분배에 재사용

        for t, d in enumerate(DAYS):
            while rel_ptr < len(my_rel_sorted) and my_rel_sorted[rel_ptr]["release_date"] <= d:
                current_rid = my_rel_sorted[rel_ptr]["release_id"]
                rel_ptr += 1
            # 아시아 공연·페스티벌 뒤에는 '기존곡(카탈로그)' 쪽에만 재청취 펄스를 더한다 (가상의 지역 규칙)
            catalog_pulse = 0.0
            if c in ASIA:
                for e in my_ev:
                    if e["kind"] in CONCERT_KINDS:
                        catalog_pulse += pulse(t, idx(e["date"]), ASIA_CATALOG_AMP, 5, 24)
            season = WEEKDAY[d.weekday()] * year_end(d)
            base = p * math.exp(g * t / 365) * season * math.exp(COMMON[t] + artist_shock[t] + n_c[t] + n_iid[t])
            R = dict(al=0.0, pl=0.0, aspl=0.0)
            for r in new_rel:
                t0, s = idx(r["release_date"]), rel_amp[r["release_type"]]
                R["al"] += pulse(t, t0, s, 0, 9)
                R["pl"] += pulse(t, t0, s * .75, 3, 21)
                R["aspl"] += pulse(t, t0, .07, 0, 6)
            E = dict(al=0.0, pl=0.0, aspl=0.0, pspl=0.0, fol=0.0, a_l=0.0, a_spl=0.0)
            for e in my_ev:
                t0 = idx(e["date"])
                for k in ["al", "pl", "aspl", "pspl", "fol"]:
                    E[k] += pulse(t, t0, *e["fx"][k])
                if e["apple"]:
                    E["a_l"] += pulse(t, t0, e["fx"]["al"][0] * .85, 0, e["fx"]["al"][2])
                    E["a_spl"] += pulse(t, t0, e["fx"]["aspl"][0] * .8, 0, e["fx"]["aspl"][2])
            share = share0 * math.exp(rng.gauss(0, .02))
            e_aspl, e_pspl = math.exp(rng.gauss(0, .02)), math.exp(rng.gauss(0, .02))
            a_base = ap_scale * math.exp(g * .8 * t / 365) * season * math.exp(COMMON_APPLE[t] + artist_shock[t] + a_c[t] + rng.gauss(0, .025))
            e_ap, e_fol = math.exp(rng.gauss(0, .025)), rng.gauss(0, 1)
            for mode in ("with", "without"):
                m = 1.0 if mode == "with" else 0.0
                al = base * share * (1 + R["al"] + m * E["al"])
                pl = base * (1 - share) * (1 + R["pl"] + m * E["pl"])
                aspl = aspl0 * (1 + R["aspl"] + m * E["aspl"]) * e_aspl
                pspl = pspl0 * (1 + m * E["pspl"]) * e_pspl
                followers[mode] += 0.0035 * base * (1 + 2 * R["al"] + m * E["fol"]) + e_fol * 0.0012 * base
                a_l = a_base * (1 + .8 * R["al"] + m * E["a_l"])
                for k, v in (("al", round(al)), ("pl", round(pl)), ("ast", round(al * aspl)), ("pst", round(pl * pspl)),
                             ("a_l", round(a_l)), ("a_p", round(a_l * 2.05 * (1 + .6 * R["aspl"] + m * E["a_spl"]) * e_ap)),
                             ("fol", round(followers[mode]))):
                    res[k][mode].append(v)

            # 곡 단위: 그날 아티스트 스트림을 이미 발매된 곡들에 나눠 준다 (합계 = 아티스트 스트림)
            total = res["ast"]["with"][t] + res["pst"]["with"][t]
            live = [tr for tr in my_trk if rel_date[tr["release_id"]] <= d]
            weights = []
            for tr in live:
                age = (d - rel_date[tr["release_id"]]).days
                boost = 1 + 4.0 * math.exp(-age / 25) * (1.5 if rel_kind[tr["release_id"]] == "싱글" else 1.0)
                if tr["release_id"] != current_rid:
                    boost *= (1 + catalog_pulse)
                weights.append(tr["appeal"] * boost * math.exp(rng.gauss(0, .12)))
            wsum = sum(weights)
            raw = [total * w / wsum for w in weights]
            alloc = [int(x) for x in raw]
            for j in sorted(range(len(raw)), key=lambda j: raw[j] - alloc[j], reverse=True)[: total - sum(alloc)]:
                alloc[j] += 1
            # 애플용: 그날 스트림 중 '신곡(현재 최신 앨범)' 비중. 애플은 곡별 일별 데이터가 없어
            # 아티스트 합계만 신곡/기존곡으로 나눠 주므로, 같은 날 스포티파이 트랙 분배에서 비중만 가져와 쓴다
            new_share[t] = (
                sum(s for tr, s in zip(live, alloc) if tr["release_id"] == current_rid) / total if total else 0.0
            )
            listeners_cap = res["al"]["with"][t] + res["pl"]["with"][t]
            for tr, s in zip(live, alloc):
                if s == 0:
                    continue
                lis = min(listeners_cap, max(1, round(s / (1.45 * math.exp(rng.gauss(0, .08))))))
                track_w.writerow([d.isoformat(), tr["track_id"], c, s, lis])
                track_rows_count += 1

        for t, d in enumerate(DAYS):
            w = {k: res[k]["with"][t] for k in res}
            sp_rows.append([d.isoformat(), aid, c, w["al"], w["pl"], w["ast"], w["pst"], w["fol"]])
            aaa_plays = round(w["a_p"] * new_share[t])
            ap_rows.append([d.isoformat(), aid, c, w["a_l"], w["a_p"], aaa_plays, w["a_p"] - aaa_plays])

        # 정답: 이벤트가 있었을 때 / 없었을 때 사후 W일 평균 비율
        for e in my_ev:
            t0 = idx(e["date"])
            for W in (7, 14, 28):
                rg = range(t0, t0 + W)

                def avg(f, mode):
                    v = [f(mode, i) for i in rg]
                    return sum(v) / len(v)

                defs = {
                    ("spotify", "listeners"): lambda md, i: res["al"][md][i] + res["pl"][md][i],
                    ("spotify", "streams"): lambda md, i: res["ast"][md][i] + res["pst"][md][i],
                    ("spotify", "streams_per_listener"): lambda md, i: (res["ast"][md][i] + res["pst"][md][i]) / (res["al"][md][i] + res["pl"][md][i]),
                    ("spotify", "active_streams_per_listener"): lambda md, i: res["ast"][md][i] / res["al"][md][i],
                    ("spotify", "active_stream_share"): lambda md, i: res["ast"][md][i] / (res["ast"][md][i] + res["pst"][md][i]),
                    ("apple", "listeners"): lambda md, i: res["a_l"][md][i],
                    ("apple", "plays"): lambda md, i: res["a_p"][md][i],
                    ("apple", "plays_per_listener"): lambda md, i: res["a_p"][md][i] / res["a_l"][md][i],
                }
                for (plat, met), f in defs.items():
                    if plat == "apple" and not e["apple"]:
                        lift = 0.0
                    else:
                        lift = avg(f, "with") / avg(f, "without") - 1
                    truth_rows.append([e["event_id"], plat, met, W, round(lift, 5)])

track_f.close()


def write(name, header, rows):
    with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


write("dim_country", ["country_code", "country_name"], COUNTRIES)
write("dim_artist", ["artist_id", "artist_name", "genre", "home_country", "debut_year", "label"],
      [a[:6] for a in ARTISTS])
write("dim_release", ["release_id", "artist_id", "title", "release_type", "release_date"],
      [[r["release_id"], r["artist_id"], r["title"], r["release_type"], r["release_date"].isoformat()] for r in releases])
write("dim_track", ["track_id", "release_id", "artist_id", "title", "track_no", "duration_sec", "is_focus"],
      [[t["track_id"], t["release_id"], t["artist_id"], t["title"], t["track_no"], t["duration_sec"], t["is_focus"]] for t in tracks])
write("marketing_events", ["event_id", "artist_id", "date", "name", "kind", "target_country", "apple"],
      [[e["event_id"], e["artist_id"], e["date"].isoformat(), e["name"], e["kind"], e["target_country"], int(e["apple"])]
       for e in events])
write("planted_effects", ["event_id", "platform", "metric", "window_days", "true_lift"], truth_rows)
# 이벤트별 펄스 파라미터(amp, lag, tau) — 실시간 정답 재계산(truth.py)이 임의의 윈도우에 대해
# with/without을 복원할 때 쓴다. rel_amp 등 발매 펄스 공식은 상수라 따로 저장할 필요 없다.
write("event_fx", ["event_id", "key", "amp", "lag", "tau"],
      [[e["event_id"], k, *e["fx"][k]] for e in events for k in ("al", "pl", "aspl", "pspl", "fol")])
write("fact_spotify_artist_daily", ["date", "artist_id", "country", "active_listeners", "programmed_listeners",
                                    "active_streams", "programmed_streams", "followers"], sp_rows)
write("fact_apple_artist_daily",
      ["date", "artist_id", "country", "listeners", "plays", "aaa_plays", "non_aaa_plays"], ap_rows)

print(f"artists={len(ARTISTS)} releases={len(releases)} tracks={len(tracks)} events={len(events)}")
print(f"spotify_artist_daily={len(sp_rows)} apple_artist_daily={len(ap_rows)} track_daily={track_rows_count} truth={len(truth_rows)}")
