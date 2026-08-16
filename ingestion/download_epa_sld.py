"""Download the EPA Smart Location Database (SLD) — no API key needed.

Source: https://edg.epa.gov/data/PUBLIC/OP/SLD/ (v3, Jan 2021) -- confirmed
live and reachable (unlike FEMA's NRI site). Flat CSV, block-group level,
90+ built-environment variables; this app only keeps a curated subset (see
db/load.py's load_built_environment()) -- walkability (NatWalkInd),
residential/employment density (D1A/D1C), intersection density (D3B), and
transit frequency (D4C).

No geopandas needed for this one -- it's a plain CSV with no geometry
column; the block-group boundary join happens against already-loaded TIGER
`bg` geographies at query time, not from SLD's own shapefile.
"""
import pathlib

from _common import download

URL = "https://edg.epa.gov/EPADataCommons/public/OA/EPA_SmartLocationDatabase_V3_Jan_2021_Final.csv"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "epa_sld" / "sld.csv"


def main():
    download(URL, OUT)


if __name__ == "__main__":
    main()
