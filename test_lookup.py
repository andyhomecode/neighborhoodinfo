"""Manual test harness for db/queries.py -- enter a lat/long, see what the
API would eventually return for that spot.

Usage:
  ingestion/.venv/bin/python test_lookup.py <lat> <lon>
  ingestion/.venv/bin/python test_lookup.py          # prompts interactively
"""
import sys

from db.queries import compare_to_home, get_neighborhood_summary

HOME_ZIP = "10002"

COMPARISON_LABELS = {
    "median_household_income": ("Median household income", "$"),
    "median_gross_rent": ("Median gross rent", "$"),
    "renter_pct": ("Renter-occupied %", ""),
    "median_age": ("Median age", ""),
    "zhvi": ("Home value (ZHVI)", "$"),
    "zori": ("Rent (ZORI)", "$"),
    "crime_rate_per_100k": ("Crime rate per 100k", ""),
}


def fmt_money(n):
    return f"${n:,.0f}" if n is not None else "n/a"


def print_summary(lat, lon):
    print(f"\n{'=' * 70}\n{lat}, {lon}\n{'=' * 70}")
    summary = get_neighborhood_summary(lat, lon)

    loc = summary["location"]
    if loc is None:
        print("Not inside any Census tract we have data for (ocean? outside the US?).")
        return

    place = f", {loc['place_name']}" if loc["place_name"] else ""
    print(f"Location: {loc['tract_name']}{place}, {loc['county_name']}")

    demo = summary["demographics"]
    if demo:
        print(f"\nDemographics ({demo['year']}):")
        print(f"  Population: {demo['total_population']:,}" if demo["total_population"] is not None else "  Population: n/a")
        print(f"  Median age: {demo['median_age']}")
        print(f"  Median household income: {fmt_money(demo['median_household_income'])}")
        print(f"  Median gross rent: {fmt_money(demo['median_gross_rent'])}")
        print(f"  Median year built: {demo['median_year_built']}")
        if demo.get("renter_pct") is not None:
            print(f"  Renter-occupied: {demo['renter_pct']}%")
    else:
        print("\nDemographics: no data")

    hv = summary["home_values"]
    if hv:
        print(f"\nHome values (county level, {hv['zhvi_date']}):")
        print(f"  ZHVI (home value index): {fmt_money(hv['zhvi'])}")
        print(f"  ZORI (observed rent index): {fmt_money(hv['zori'])}/mo")
    else:
        print("\nHome values: no data")

    crime = summary["crime"]
    if crime:
        total = sum(c["incident_count"] for c in crime)
        print(f"\nCrime (county level, 2025, {total:,} total incidents):")
        for c in crime[:5]:
            print(f"  {c['offense_label']}: {c['incident_count']:,}")
    else:
        print("\nCrime: no data")

    rate = summary["crime_rate"]
    if rate:
        print(f"\nCrime rate (per 100k population, {rate['year']}):")
        print(f"  This county: {rate['county_rate_per_100k']}")
        print(f"  State avg: {rate['state_rate_per_100k']} ({rate['vs_state_pct']:+}% vs. state, "
              f"{rate['state_counties_reporting']} counties reporting)")
        print(f"  National avg: {rate['national_rate_per_100k']} ({rate['vs_national_pct']:+}% vs. national, "
              f"{rate['national_counties_reporting']} counties reporting)")
    else:
        print("\nCrime rate: no data")

    elec = summary["elections"]
    if elec:
        print(f"\n2024 presidential (county level): {elec['winner']} won by {elec['margin_pct']} points "
              f"({elec['votes_gop']:,} GOP / {elec['votes_dem']:,} Dem)")
    else:
        print("\nElections: no data")

    sites = summary["historic_sites"]
    if sites:
        print(f"\nHistoric sites within 5km:")
        for s in sites:
            print(f"  {s['name']} ({s['site_type']}, {s['distance_m']}m away)")
    else:
        print("\nHistoric sites: none within 5km")

    vs_home = compare_to_home(lat, lon, HOME_ZIP)
    if vs_home:
        print(f"\nVs. home (ZIP {HOME_ZIP}, {vs_home['home_location']['county_name']}):")
        for key, (label, prefix) in COMPARISON_LABELS.items():
            c = vs_home["comparison"][key]
            if c.get("unreliable"):
                print(f"  {label}: not compared (home or target county's crime data too sparse to be reliable)")
                continue
            if c["target"] is None or c["home"] is None:
                continue
            arrow = "higher" if c["diff_pct"] > 0 else "lower"
            fmt = (lambda v: f"{prefix}{v:,.0f}") if prefix == "$" else (lambda v: f"{v:,.1f}")
            print(f"  {label}: {fmt(c['target'])} vs {fmt(c['home'])}  ({abs(c['diff_pct'])}% {arrow})")
        if vs_home["same_winning_party_2024"] is not None:
            phrase = "same as home" if vs_home["same_winning_party_2024"] else "different from home"
            print(f"  2024 winning party: {phrase}")
        lean = vs_home["political_lean"]
        if lean:
            print(f"  2024 political lean: {abs(lean['diff_points'])} points {lean['direction']} than home "
                  f"({lean['target_gop_pct']}% GOP vs {lean['home_gop_pct']}% GOP, two-party share)")

        local = vs_home["home_local_crime"]
        if local:
            print(f"  (real local crime data for home, {local['borough_name']}, not the same methodology "
                  f"as the county rate above: {local['incidents']:,} incidents / {local['population']:,} "
                  f"people = {local['rate_per_100k']} per 100k)")

        by_cat = vs_home["crime_by_category"]
        if by_cat:
            print(f"\n  By crime type (per 100k), vs state / national / home:")
            for category, c in sorted(by_cat.items(), key=lambda kv: -kv[1]["rate_per_100k"]):
                def fmt_pct(p):
                    return f"{p:+.0f}%" if p is not None else "n/a"
                home_note = f" [{c['home_source']}]" if c["home_source"] else " [no home data]"
                print(f"    {category}: {c['rate_per_100k']}  "
                      f"(state {fmt_pct(c['vs_state_pct'])}, national {fmt_pct(c['vs_national_pct'])}, "
                      f"home {fmt_pct(c['vs_home_pct'])}{home_note})")


def main():
    if len(sys.argv) == 3:
        print_summary(float(sys.argv[1]), float(sys.argv[2]))
    else:
        lat = float(input("Latitude: "))
        lon = float(input("Longitude: "))
        print_summary(lat, lon)


if __name__ == "__main__":
    main()
