"""Download TIGER/Line boundary shapefiles (tract, county, place) — no API key needed.

Source: https://www2.census.gov/geo/tiger/
Run yearly to pick up the newest vintage: change TIGER_YEAR below.
"""
import pathlib

from _common import STATE_FIPS, download

TIGER_YEAR = 2025
BASE = f"https://www2.census.gov/geo/tiger/TIGER{TIGER_YEAR}"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "tiger"


def main():
    # County: one file covers the whole country.
    print("county (nationwide, 1 file)")
    download(f"{BASE}/COUNTY/tl_{TIGER_YEAR}_us_county.zip", OUT / "county" / f"tl_{TIGER_YEAR}_us_county.zip")

    # Tract, place, and block group: one file per state/territory.
    for geo in ("tract", "place", "bg"):
        print(f"{geo} (per state, {len(STATE_FIPS)} files)")
        for fips in STATE_FIPS:
            url = f"{BASE}/{geo.upper()}/tl_{TIGER_YEAR}_{fips}_{geo}.zip"
            dest = OUT / geo / f"tl_{TIGER_YEAR}_{fips}_{geo}.zip"
            download(url, dest)


if __name__ == "__main__":
    main()
