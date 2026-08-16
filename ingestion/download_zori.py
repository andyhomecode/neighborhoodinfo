"""Download Zillow ZORI (Observed Rent Index) CSVs — no API key needed.

Source: https://www.zillow.com/research/data/
Same caveat as download_zhvi.py: Zillow occasionally changes these paths
without notice.
"""
import pathlib

from _common import download

BASE = "https://files.zillowstatic.com/research/public_csvs/zori"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "zori"

# All homes + multifamily, smoothed, not seasonally adjusted (sa variant
# isn't published for ZORI at all geographies).
FILES = {
    "metro": "Metro_zori_uc_sfrcondomfr_sm_month.csv",
    "county": "County_zori_uc_sfrcondomfr_sm_month.csv",
    "zip": "Zip_zori_uc_sfrcondomfr_sm_month.csv",
}


def main():
    for label, filename in FILES.items():
        print(label)
        download(f"{BASE}/{filename}", OUT / filename)


if __name__ == "__main__":
    main()
