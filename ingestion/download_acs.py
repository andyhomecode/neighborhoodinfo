"""Download Census ACS 5-year estimates, tract level, nationwide.

Needs a free API key: https://api.census.gov/data/key_signup.html
Set CENSUS_API_KEY in ingestion/.env (see .env.example).
"""
import json
import os
import pathlib

import requests
from dotenv import load_dotenv

from _common import STATE_FIPS, USER_AGENT

load_dotenv()

ACS_YEAR = 2023  # latest available 5-year vintage; bump yearly
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "acs"

# GEOID components (NAME, state, county, tract) are always returned automatically.
VARIABLES = {
    "B01003_001E": "total_population",
    "B01002_001E": "median_age",
    "B19013_001E": "median_household_income",
    "B25064_001E": "median_gross_rent",
    "B02001_002E": "population_white_alone",
    "B02001_003E": "population_black_alone",
    "B02001_005E": "population_asian_alone",
    "B03002_012E": "population_hispanic_or_latino",
    "B17001_001E": "poverty_universe",
    "B17001_002E": "population_below_poverty",
    # Tenure (rental %)
    "B25003_001E": "occupied_housing_units",
    "B25003_002E": "owner_occupied_units",
    "B25003_003E": "renter_occupied_units",
    # Units in structure (housing type mix)
    "B25024_002E": "units_1detached",
    "B25024_003E": "units_1attached",
    "B25024_004E": "units_2",
    "B25024_005E": "units_3_to_4",
    "B25024_006E": "units_5_to_9",
    "B25024_007E": "units_10_to_19",
    "B25024_008E": "units_20_to_49",
    "B25024_009E": "units_50_plus",
    "B25024_010E": "units_mobile_home",
    # Housing age
    "B25035_001E": "median_year_built",
}


def fetch_state(fips: str) -> list | None:
    url = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
    params = {
        "get": ",".join(["NAME", *VARIABLES]),
        "for": "tract:*",
        "in": f"state:{fips}",
        "key": os.environ["CENSUS_API_KEY"],
    }
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    if resp.status_code == 204:
        # ACS 5-year only covers the 50 states + DC + Puerto Rico, not the
        # other island-area territories (AS, GU, MP, VI).
        return None
    resp.raise_for_status()
    return resp.json()


def main():
    if "CENSUS_API_KEY" not in os.environ:
        raise SystemExit("Set CENSUS_API_KEY in ingestion/.env first (see .env.example).")

    OUT.mkdir(parents=True, exist_ok=True)
    for fips, abbr in STATE_FIPS.items():
        dest = OUT / f"acs5_{ACS_YEAR}_{fips}.json"
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  skip (exists): {dest.name}")
            continue
        print(f"{abbr} ({fips})")
        data = fetch_state(fips)
        if data is None:
            print("  no ACS 5-year coverage for this territory, skipping")
            continue
        dest.write_text(json.dumps(data))
        print(f"  saved: {dest.name} ({len(data) - 1} tracts)")


if __name__ == "__main__":
    main()
