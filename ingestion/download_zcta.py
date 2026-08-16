"""Download Census Gazetteer ZCTA file (ZIP code centroids) — no API key needed.

Used to resolve a ZIP code to a lat/long (its centroid), so a ZIP can be fed
into the same point-in-polygon lookup as any other coordinate. Not a
replacement for real ZCTA boundary polygons (a centroid isn't the same as
"which ZIP is this point in"), but sufficient for "what's the data at this
ZIP's approximate location."

Source: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
"""
import pathlib

from _common import download

URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_zcta_national.zip"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "zcta"


def main():
    download(URL, OUT / "2025_Gaz_zcta_national.zip")


if __name__ == "__main__":
    main()
