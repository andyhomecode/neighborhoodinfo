"""Download Zillow ZHVI (Home Value Index) CSVs — no API key needed.

Source: https://www.zillow.com/research/data/
Zillow occasionally changes these paths without notice; if a download starts
404ing, re-check the current links on the page above and update FILES below.
"""
import pathlib

from _common import download

BASE = "https://files.zillowstatic.com/research/public_csvs/zhvi"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "zhvi"

# All-homes (SFR+condo), smoothed & seasonally adjusted, mid-tier (0.33-0.67).
FILES = {
    "metro": "Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "county": "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "zip": "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
}


def main():
    for label, filename in FILES.items():
        print(label)
        download(f"{BASE}/{filename}", OUT / filename)


if __name__ == "__main__":
    main()
