"""Download National Register of Historic Places points + polygons — no API key needed.

Source: https://public-nps.opendata.arcgis.com/datasets/nps::national-register-of-historic-places-points
(item id 18fe4b262473496a8ca7871a67d844ee, layers 0=points, 1=polygons)
"""
import pathlib

from _common import download

ITEM = "18fe4b262473496a8ca7871a67d844ee"
BASE = f"https://public-nps.opendata.arcgis.com/api/download/v1/items/{ITEM}/geojson"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "nrhp"

LAYERS = {
    0: "nrhp_points.geojson",
    1: "nrhp_polygons.geojson",
}


def main():
    for layer, filename in LAYERS.items():
        print(filename)
        download(f"{BASE}?layers={layer}", OUT / filename)


if __name__ == "__main__":
    main()
