"""Download NCES Common Core of Data (CCD) public school characteristics —
no API key needed.

Source: https://data-nces.opendata.arcgis.com/datasets/nces::public-school-characteristics-current
(item id 5cd68dad64f641f6b847367493e92657, layer 1) -- a perpetually-updated
"current" layer, currently reflecting school year 2024-2025. Confirmed real
field names live: NCESSCH, SCH_NAME, SCHOOL_TYPE_TEXT, LCITY, LSTATE, TOTAL,
STUTERATIO, TOTFRL, ULOCALE, LATCOD, LONCOD. Missing/not-applicable values
are encoded as small negative sentinels (e.g. -2), same convention as other
NCES/education data -- handled in db/load.py's load_schools().

This is school *characteristics* (enrollment, staffing ratio, free/reduced-
lunch rate as a poverty proxy), not a quality/rating dataset -- no free
nationwide school-quality data exists (checked during research).
"""
import pathlib

from _common import download

ITEM = "5cd68dad64f641f6b847367493e92657"
URL = f"https://data-nces.opendata.arcgis.com/api/download/v1/items/{ITEM}/csv?layers=1"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "nces_ccd" / "schools.csv"


def main():
    download(URL, OUT)


if __name__ == "__main__":
    main()
