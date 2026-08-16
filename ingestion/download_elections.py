"""Download 2024 presidential election results, county level — no API key needed.

MEDSL's own Harvard Dataverse blocks scripted downloads entirely (AWS WAF
bot-challenge returns an empty 202 regardless of headers/User-Agent -- we
tried the search API, the dataverse contents API, the dataset landing
page, and the direct file-access API; all blocked). Rather than require a
manual download for a single file, we use a well-established community
mirror instead: tonmcg/US_County_Level_Election_Results_08-24 on GitHub
(actively maintained, MIT-licensed, 400+ stars, derived from the same
official state/AP results MEDSL itself draws from). Its data is two-party
(GOP/Dem) vote totals only -- no third-party candidates, no down-ballot
races -- which matches our v1 scope (presidential only) fine.

Caveat: Alaska reports by state house district and DC by ward, not county
-- both present in the file, just not keyed by a standard county FIPS.
"""
import pathlib

from _common import download

URL = "https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master/2024_US_County_Level_Presidential_Results.csv"
OUT = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "elections"


def main():
    download(URL, OUT / "2024_US_County_Level_Presidential_Results.csv")


if __name__ == "__main__":
    main()
