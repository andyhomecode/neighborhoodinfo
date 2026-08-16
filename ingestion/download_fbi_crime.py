"""FBI crime data (state/national estimates) — manual step, like elections.

The old public UCR API is dead (both documented hosts return cloud.gov
"route does not exist"). The current site, cde.ucr.cjis.gov, has a real
"Downloads" page listing small bulk files (state/national estimates,
participation, hate crime, etc. — see below), but the download itself
goes through a protected API Gateway that returns 403 Forbidden for a
plain script even with a real FBI_API_KEY, the app's own embedded public
key, and browser-style headers — it looks like the "Download" button
calls an authenticated endpoint that hands back a temporary signed S3
URL, not a static file, so there's nothing stable to hardcode a script
against.

These files are small (the main one is 222 KB), so it's not worth
chasing further — download by hand:

  1. Open https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/downloads
  2. Download "Summary Reporting System (SRS)" — state/national estimated
     crime totals, 1979-current. This is the one that matters for the
     `crime` table (participation-adjusted state-level estimates).
  3. Optionally also grab "Uniform Crime Reporting Program Participation
     Data" (how much of each state's population is covered by reporting
     agencies — useful context for the estimates).
  4. Save the file(s) into datasets/fbi_crime/.

Re-run this script with --check to verify datasets/fbi_crime/ isn't empty.
"""
import pathlib
import sys

OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "fbi_crime"


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
