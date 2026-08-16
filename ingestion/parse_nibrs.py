"""Aggregate the raw NIBRS master flat file into county-level offense counts.

Input: datasets/fbi_crime/nibrs-<year>.zip (single fixed-width .txt inside,
manually downloaded from https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/downloads
-- see download_fbi_crime.py). Record layout from the FBI's own
"NIBRS Record Description" doc (datasets/fbi_crime/nibrs-help.zip):

  Segment "BH" (batch header, one per agency, precedes that agency's
  records until the next "BH"): state abbreviation at position 72-73,
  primary county FIPS at position 270-272.
  Segment "02" (offense, one or more per incident): incident date at
  position 26-33 (YYYYMMDD), UCR/NIBRS offense code at position 34-36.

All positions below are 0-indexed Python slices (spec positions - 1).

Scope: Group "A" incident-based offenses only (segment "02"). Group "B"
arrest-only offenses (segment "07": minor stuff like DUI, disorderly
conduct) are a different record shape and are not counted here -- this
undercounts total arrests but covers the offense categories people
actually mean by "crime rate" (assault, burglary, theft, etc).

Output: datasets/fbi_crime/county_offense_counts_<year>.csv
  columns: state_fips, county_fips, geoid, year, offense_code, incident_count
"county_fips"/"geoid" are blank when the agency's batch header didn't carry
a county code (rare, but happens for some agency types).
"""
import csv
import pathlib
import sys
import zipfile
from collections import Counter

from _common import STATE_FIPS

FIPS_BY_ABBR = {abbr: fips for fips, abbr in STATE_FIPS.items()}

DATASETS = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "fbi_crime"


def parse(year: int):
    zip_path = DATASETS / f"nibrs-{year}.zip"
    txt_name = f"nibrs-{year}.txt"
    counts = Counter()
    unknown_state_abbrs = Counter()
    current_state_fips = None
    current_county_fips = None
    n_lines = 0
    n_offense = 0

    with zipfile.ZipFile(zip_path) as zf, zf.open(txt_name) as raw:
        for raw_line in raw:
            n_lines += 1
            line = raw_line.decode("latin-1")
            seg = line[0:2]

            if seg == "BH":
                state_abbr = line[71:73].strip()
                county_fips = line[269:272].strip()
                current_state_fips = FIPS_BY_ABBR.get(state_abbr)
                if current_state_fips is None:
                    unknown_state_abbrs[state_abbr] += 1
                current_county_fips = county_fips if county_fips and county_fips != "000" else None

            elif seg == "02":
                n_offense += 1
                incident_date = line[25:33].strip()
                year_field = incident_date[0:4] if len(incident_date) == 8 else str(year)
                offense_code = line[33:36].strip()
                state_fips = current_state_fips or ""
                county_fips = current_county_fips or ""
                geoid = f"{state_fips}{county_fips}" if state_fips and county_fips else ""
                counts[(state_fips, county_fips, geoid, year_field, offense_code)] += 1

            if n_lines % 5_000_000 == 0:
                print(f"  {n_lines:,} lines read, {n_offense:,} offense segments, {len(counts):,} distinct groups", file=sys.stderr)

    print(f"done: {n_lines:,} lines, {n_offense:,} offense segments", file=sys.stderr)
    if unknown_state_abbrs:
        print(f"unrecognized state abbreviations: {dict(unknown_state_abbrs)}", file=sys.stderr)

    out_path = DATASETS / f"county_offense_counts_{year}.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["state_fips", "county_fips", "geoid", "year", "offense_code", "incident_count"])
        for (state_fips, county_fips, geoid, year_field, offense_code), count in sorted(counts.items()):
            writer.writerow([state_fips, county_fips, geoid, year_field, offense_code, count])
    print(f"wrote {out_path} ({len(counts):,} rows)", file=sys.stderr)


if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    parse(year)
