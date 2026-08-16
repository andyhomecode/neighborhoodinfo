"""Download NYPD complaint data (NYC Open Data / Socrata) for a whole borough.

Scoped, one-off supplement -- NOT a general per-city crime source. The
architecture deliberately stays away from per-city Socrata integrations for
v1 (high-maintenance, doesn't fit the nationwide-batch model -- see
research.md). This exists only because NIBRS crime data for NYC is useless
(NYPD barely reports to it -- see db/queries.py's MIN_RELIABLE_INCIDENTS),
and NYC happens to publish real complaint-level data, geocoded, for free,
with no auth needed.

Borough, not ZIP+radius: NYC's 5 boroughs map 1:1 to counties (Manhattan =
New York County = FIPS 36061, etc.), so filtering NYPD's own `boro_nm`
field and using the real Census county population as the denominator is
both simpler and exact -- no population-within-a-radius estimate needed.

Dataset: "NYPD Complaint Data Current (Year To Date)", resource 5uac-w243,
via the SODA API.
"""
import json
import pathlib

import requests

from _common import USER_AGENT

BOROUGH_TO_COUNTY_FIPS = {
    "MANHATTAN": "36061",
    "BRONX": "36005",
    "BROOKLYN": "36047",
    "QUEENS": "36081",
    "STATEN ISLAND": "36085",
}

BOROUGH = "MANHATTAN"
YEAR = 2025

BASE = "https://data.cityofnewyork.us/resource/5uac-w243.json"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "nypd_crime"


def main():
    where = (
        f"boro_nm = '{BOROUGH}' "
        f"AND cmplnt_fr_dt between '{YEAR}-01-01T00:00:00' and '{YEAR}-12-31T23:59:59'"
    )
    resp = requests.get(
        BASE,
        params={
            "$where": where,
            "$select": "law_cat_cd, ofns_desc, count(*) as n",
            "$group": "law_cat_cd, ofns_desc",
            "$order": "n DESC",
            "$limit": 200,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    rows = resp.json()

    OUT.mkdir(parents=True, exist_ok=True)
    county_geoid = BOROUGH_TO_COUNTY_FIPS[BOROUGH]
    dest = OUT / f"nypd_complaints_{county_geoid}_{YEAR}.json"
    dest.write_text(json.dumps({
        "county_geoid": county_geoid,
        "borough_name": BOROUGH,
        "year": YEAR,
        "source": "NYC Open Data: NYPD Complaint Data Current (Year To Date), resource 5uac-w243",
        "offenses": rows,
    }, indent=2))
    total = sum(int(r["n"]) for r in rows)
    print(f"saved: {dest.name} ({len(rows)} offense categories, {total:,} total complaints)")


if __name__ == "__main__":
    main()
