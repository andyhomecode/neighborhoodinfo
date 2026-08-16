"""FEMA National Risk Index (NRI) — manual step, like FBI crime.

Free, no signup, current version v1.20 (Dec 2025) — but every automated
fetch attempt against hazards.fema.gov and fema.gov during development
returned either a 403, a 301 redirect into an interactive tool page, or
(for the OpenFEMA REST API) no matching dataset at all. NRI isn't part of
the standard OpenFEMA disaster-data catalog -- it's served from a separate
portal (the "Resilience Analysis and Planning Tool"), which appears to be
behind bot protection for anything but a real browser. Confirmed real and
free via web search, just not scriptable the way every other source here is.

  1. Open https://hazards.fema.gov/nri/data-resources in a real browser.
  2. Download the census-tract-level table in CSV format (nationwide, not
     a per-state file, if a nationwide option exists -- if only per-state
     downloads are offered, grab all of them).
  3. Save the file(s) into datasets/fema_nri/.

Re-run this script with --check to verify datasets/fema_nri/ isn't empty.

Once a real file is in hand: db/load.py's load_hazard_risk() column-name
mapping (RISK_SCORE, RISK_RATNG, and one <HAZARDCODE>_RISKS-style column
per hazard) is a best-effort draft based on NRI's documented naming
convention, NOT verified against an actual downloaded header this
session -- open the real CSV and confirm/correct the mapping in
NRI_COLUMN_MAP before trusting load_hazard_risk()'s output.
"""
import pathlib
import sys

OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "fema_nri"


def main():
    if "--check" in sys.argv:
        files = list(OUT.glob("*"))
        if not files:
            raise SystemExit(f"{OUT} is empty — see this script's docstring for manual download steps.")
        print(f"{len(files)} file(s) in {OUT}:")
        for f in files:
            print(f"  {f.name}")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
