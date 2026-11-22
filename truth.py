"""이벤트 효과(참/정답)를 임의의 윈도우 길이에 대해 실시간으로 재계산한다.

generate_data.py는 데이터를 만들 때 "이벤트가 있었다면(with) vs 없었다면(without)"을
시뮬레이션해서 7/14/28일 고정 윈도우로만 planted_effects에 저장해 둔다. 그 with/without
쌍 자체는 저장되지 않고 생성 시점에만 존재했다가 버려진다.

하지만 생성 공식을 보면 base·share·노이즈는 with/without에서 완전히 같고, 오직 이벤트 자신의
펄스(E)만 다르다. 그래서 "오늘 날짜(t)의 실제 관측값(with)"과 "그 시점에 걸려 있던 발매 펄스(R,
dim_release로 재현 가능)·이벤트 펄스(E, event_fx 테이블에 저장해 둔 amp/lag/tau로 재현 가능)"만
알면, 나눗셈으로 without을 거꾸로 복원할 수 있다. 이 모듈이 그 복원을 한다 — 그래서 윈도우를
7/14/28이 아닌 임의의 값으로 바꿔도 정답을 다시 계산할 수 있다.

generate_data.py의 공식과 반드시 같이 맞춰서 고쳐야 한다(REL_AMP, pulse 모양 등).
"""

import math

import pandas as pd

REL_AMP = {"싱글": 0.30, "EP": 0.40, "정규": 0.55}


def pulse(t_days: "pd.Series | float", lag: float, tau: float, amp: float):
    """t_days: 날짜 - 기준일(일수, 음수 허용). generate_data.py의 pulse()와 동일한 모양."""
    s = t_days - lag
    out = amp * (-s / tau).apply(math.exp) if hasattr(s, "apply") else (amp * math.exp(-s / tau) if s >= 0 else 0.0)
    if hasattr(s, "apply"):
        out = out.where(s >= 0, 0.0)
    return out


def release_pulses(dates: pd.Series, releases: pd.DataFrame) -> dict[str, pd.Series]:
    """dates 위에서 R_al, R_pl, R_aspl(날짜별 발매 펄스 합)을 계산."""
    R = {"al": pd.Series(0.0, index=dates.index), "pl": pd.Series(0.0, index=dates.index),
         "aspl": pd.Series(0.0, index=dates.index)}
    for _, r in releases.iterrows():
        t_days = (dates - r["release_date"]).dt.days
        amp = REL_AMP[r["release_type"]]
        R["al"] += pulse(t_days, 0, 9, amp)
        R["pl"] += pulse(t_days, 3, 21, amp * 0.75)
        R["aspl"] += pulse(t_days, 0, 6, 0.07)
    return R


def event_pulses(dates: pd.Series, events_fx: pd.DataFrame) -> dict[str, pd.Series]:
    """dates 위에서 E_al, E_pl, E_aspl, E_pspl, E_a_l, E_a_spl(날짜별 이벤트 펄스 합)을 계산.
    events_fx: event_date, key, amp, lag, tau 컬럼(같은 artist_id·country의 모든 이벤트 전부 포함해야
    겹치는 이벤트 효과까지 맞게 합산된다)."""
    keys = ["al", "pl", "aspl", "pspl"]
    E = {k: pd.Series(0.0, index=dates.index) for k in keys}
    E["a_l"] = pd.Series(0.0, index=dates.index)
    E["a_spl"] = pd.Series(0.0, index=dates.index)
    for event_date, grp in events_fx.groupby("event_date"):
        t_days = (dates - event_date).dt.days
        row = {r["key"]: r for _, r in grp.iterrows()}
        for k in keys:
            if k in row:
                E[k] += pulse(t_days, row[k]["lag"], row[k]["tau"], row[k]["amp"])
        if "al" in row:
            E["a_l"] += pulse(t_days, 0, row["al"]["tau"], row["al"]["amp"] * 0.85)
        if "aspl" in row:
            E["a_spl"] += pulse(t_days, 0, row["aspl"]["tau"], row["aspl"]["amp"] * 0.8)
    return E


def reconstruct_without(daily: pd.DataFrame, releases: pd.DataFrame, events_fx: pd.DataFrame,
                         is_apple_event: bool) -> pd.DataFrame:
    """daily: date, active_listeners, programmed_listeners, active_streams, programmed_streams
    (spotify) + listeners, plays(apple)가 있는 artist·country 전체 기간 일별 데이터.
    반환: 같은 date 인덱스 위에 각 지표의 '이벤트가 없었다면' 값을 추가한 데이터프레임."""
    dates = daily["date"]
    R = release_pulses(dates, releases)
    E = event_pulses(dates, events_fx)

    out = daily.copy()
    al_w, pl_w = daily["active_listeners"], daily["programmed_listeners"]
    ast_w, pst_w = daily["active_streams"], daily["programmed_streams"]

    al_wo = al_w * (1 + R["al"]) / (1 + R["al"] + E["al"])
    pl_wo = pl_w * (1 + R["pl"]) / (1 + R["pl"] + E["pl"])
    ast_wo = ast_w * (al_wo / al_w) * (1 + R["aspl"]) / (1 + R["aspl"] + E["aspl"])
    pst_wo = pst_w * (pl_wo / pl_w) / (1 + E["pspl"])

    out["al_wo"], out["pl_wo"], out["ast_wo"], out["pst_wo"] = al_wo, pl_wo, ast_wo, pst_wo

    if is_apple_event and "listeners" in daily and "plays" in daily:
        a_l_w, a_p_w = daily["listeners"], daily["plays"]
        a_l_wo = a_l_w * (1 + 0.8 * R["al"]) / (1 + 0.8 * R["al"] + E["a_l"])
        a_p_wo = a_p_w * (a_l_wo / a_l_w) * (1 + 0.6 * R["aspl"]) / (1 + 0.6 * R["aspl"] + E["a_spl"])
        out["a_l_wo"], out["a_p_wo"] = a_l_wo, a_p_wo
    return out


def lift_table(daily_with_wo: pd.DataFrame, event_date: pd.Timestamp, windows: list[int],
               has_apple: bool) -> pd.DataFrame:
    """event_date 뒤 W일 평균으로 지표별 true_lift를 계산 (generate_data.py의 defs와 동일한 지표)."""
    rows = []
    for w in windows:
        win = daily_with_wo[(daily_with_wo["date"] >= event_date) & (daily_with_wo["date"] < event_date + pd.Timedelta(days=w))]
        if win.empty:
            continue

        def lift(with_col_expr, wo_col_expr):
            a, b = with_col_expr(win).mean(), wo_col_expr(win).mean()
            return float(a / b - 1) if b else float("nan")

        defs = {
            ("spotify", "listeners"): (lambda d: d["active_listeners"] + d["programmed_listeners"],
                                        lambda d: d["al_wo"] + d["pl_wo"]),
            ("spotify", "streams"): (lambda d: d["active_streams"] + d["programmed_streams"],
                                      lambda d: d["ast_wo"] + d["pst_wo"]),
            ("spotify", "streams_per_listener"): (
                lambda d: (d["active_streams"] + d["programmed_streams"]) / (d["active_listeners"] + d["programmed_listeners"]),
                lambda d: (d["ast_wo"] + d["pst_wo"]) / (d["al_wo"] + d["pl_wo"])),
            ("spotify", "active_streams_per_listener"): (
                lambda d: d["active_streams"] / d["active_listeners"], lambda d: d["ast_wo"] / d["al_wo"]),
            ("spotify", "active_stream_share"): (
                lambda d: d["active_streams"] / (d["active_streams"] + d["programmed_streams"]),
                lambda d: d["ast_wo"] / (d["ast_wo"] + d["pst_wo"])),
        }
        if has_apple:
            defs[("apple", "listeners")] = (lambda d: d["listeners"], lambda d: d["a_l_wo"])
            defs[("apple", "plays")] = (lambda d: d["plays"], lambda d: d["a_p_wo"])
            defs[("apple", "plays_per_listener")] = (
                lambda d: d["plays"] / d["listeners"], lambda d: d["a_p_wo"] / d["a_l_wo"])

        for (plat, met), (fw, fwo) in defs.items():
            rows.append({"platform": plat, "metric": met, "window_days": w, "true_lift": round(lift(fw, fwo), 5)})
    return pd.DataFrame(rows)
