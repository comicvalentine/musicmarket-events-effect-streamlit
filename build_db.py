"""CSV(data/*.csv, *.csv.gz) -> SQLite 한 파일(event_effect.sqlite).

실행: python3 build_db.py
"""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DB_PATH = ROOT / "event_effect.sqlite"

TABLES = {
    "dim_artist": "dim_artist.csv",
    "dim_country": "dim_country.csv",
    "dim_release": "dim_release.csv",
    "dim_track": "dim_track.csv",
    "marketing_events": "marketing_events.csv",
    "planted_effects": "planted_effects.csv",
    "event_fx": "event_fx.csv",
    "fact_spotify_artist_daily": "fact_spotify_artist_daily.csv",
    "fact_apple_artist_daily": "fact_apple_artist_daily.csv",
    "fact_spotify_track_daily": "fact_spotify_track_daily.csv.gz",
}

DATE_COLS = {
    "dim_release": ["release_date"],
    "marketing_events": ["date"],
    "fact_spotify_artist_daily": ["date"],
    "fact_apple_artist_daily": ["date"],
    "fact_spotify_track_daily": ["date"],
}


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)

    for table, filename in TABLES.items():
        df = pd.read_csv(DATA / filename, parse_dates=DATE_COLS.get(table, []))
        for col in DATE_COLS.get(table, []):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
        df.to_sql(table, con, if_exists="replace", index=False)
        print(f"{table:30s} {len(df):>8,d} rows  <- {filename}")

    con.execute("CREATE INDEX idx_artist_daily ON fact_spotify_artist_daily(artist_id, country, date)")
    con.execute("CREATE INDEX idx_track_daily ON fact_spotify_track_daily(track_id, country, date)")
    con.execute("CREATE INDEX idx_track_artist ON dim_track(artist_id, release_id)")
    con.execute("CREATE INDEX idx_release_artist ON dim_release(artist_id, release_date)")
    con.commit()
    con.close()
    print(f"-> {DB_PATH}")


if __name__ == "__main__":
    main()
