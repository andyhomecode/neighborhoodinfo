"""Query functions the API will call. Each takes plain Python args and
returns plain dicts/lists/None -- no ORM objects leaking out, so this can be
called directly from FastAPI route handlers without extra translation."""

from sqlalchemy import text

from db.engine import engine

# NIBRS/UCR Group A offense codes -> readable labels. Covers every code that
# actually shows up in the ingested crime table (confirmed against 52
# distinct codes / all incidents in the loaded 2025 file -- see "Known gap"
# in CLAUDE.md, now closed), not the full theoretical NIBRS code space.
OFFENSE_LABELS = {
    "09A": "murder/nonnegligent manslaughter",
    "09B": "negligent manslaughter",
    "09C": "justifiable homicide",
    "100": "kidnapping/abduction",
    "11A": "rape",
    "11B": "sodomy",
    "11C": "sexual assault with an object",
    "11D": "fondling",
    "120": "robbery",
    "13A": "aggravated assault",
    "13B": "simple assault",
    "13C": "intimidation",
    "200": "arson",
    "210": "extortion/blackmail",
    "220": "burglary/breaking & entering",
    "23A": "pocket-picking",
    "23B": "purse-snatching",
    "23C": "shoplifting",
    "23D": "theft from building",
    "23E": "theft from coin-operated machine",
    "23F": "theft from motor vehicle",
    "23G": "theft of motor vehicle parts",
    "23H": "all other larceny",
    "240": "motor vehicle theft",
    "250": "counterfeiting/forgery",
    "270": "embezzlement",
    "26A": "false pretenses/swindle",
    "26B": "credit card/ATM fraud",
    "26C": "impersonation",
    "26D": "welfare fraud",
    "26E": "wire fraud",
    "26F": "identity theft",
    "26G": "hacking/computer invasion",
    "280": "stolen property offenses",
    "290": "destruction/damage/vandalism",
    "35A": "drug/narcotic violations",
    "35B": "drug equipment violations",
    "36A": "incest",
    "36B": "statutory rape",
    "370": "pornography/obscene material",
    "39A": "betting/wagering",
    "39B": "operating/promoting gambling",
    "39C": "gambling equipment violation",
    "39D": "sports tampering",
    "40A": "prostitution",
    "40B": "assisting/promoting prostitution",
    "40C": "purchasing prostitution",
    "510": "bribery",
    "520": "weapon law violations",
    "64A": "human trafficking, commercial sex acts",
    "64B": "human trafficking, involuntary servitude",
    "720": "animal cruelty",
    "90C": "disorderly conduct",
    "90D": "driving under the influence",
    "90J": "trespassing",
    "90Z": "all other offenses",
}

# Broad crime categories shared between NIBRS offense codes (target/state/
# national) and NYPD's ofns_desc text (home, when home is NYC) -- the two
# taxonomies are completely different systems, this is the common ground
# that makes "assault vs. home" comparisons possible at all. Built directly
# against the actual distinct values in both tables, not a generic NIBRS
# reference list -- extend both maps if new codes/descriptions show up.
NIBRS_CATEGORY = {
    "09A": "homicide", "09B": "homicide", "09C": "homicide",
    "11A": "sex_offenses", "11B": "sex_offenses", "11C": "sex_offenses", "11D": "sex_offenses",
    "36A": "sex_offenses", "36B": "sex_offenses", "370": "sex_offenses",
    "100": "kidnapping",
    "120": "robbery",
    "13A": "assault", "13B": "assault", "13C": "assault",
    "200": "arson",
    "210": "fraud",
    "220": "burglary",
    "23A": "larceny_theft", "23B": "larceny_theft", "23C": "larceny_theft", "23D": "larceny_theft",
    "23E": "larceny_theft", "23F": "larceny_theft", "23G": "larceny_theft", "23H": "larceny_theft",
    "240": "motor_vehicle_theft",
    "250": "fraud", "270": "fraud",
    "26A": "fraud", "26B": "fraud", "26C": "fraud", "26D": "fraud", "26E": "fraud", "26F": "fraud", "26G": "fraud",
    "280": "other",
    "290": "vandalism",
    "35A": "drug", "35B": "drug",
    "39A": "other", "39B": "other", "39C": "other", "39D": "other",
    "40A": "other", "40B": "other", "40C": "other",
    "510": "other",
    "520": "weapons",
    "64A": "other", "64B": "other",
    "720": "other",
}

NYPD_CATEGORY = {
    "GRAND LARCENY": "larceny_theft",
    "PETIT LARCENY": "larceny_theft",
    "OTHER OFFENSES RELATED TO THEFT": "larceny_theft",
    "GRAND LARCENY OF MOTOR VEHICLE": "motor_vehicle_theft",
    "PETIT LARCENY OF MOTOR VEHICLE": "motor_vehicle_theft",
    "UNAUTHORIZED USE OF A VEHICLE": "motor_vehicle_theft",
    "ASSAULT 3 & RELATED OFFENSES": "assault",
    "FELONY ASSAULT": "assault",
    "SEX CRIMES": "sex_offenses",
    "RAPE": "sex_offenses",
    "ROBBERY": "robbery",
    "BURGLARY": "burglary",
    "ARSON": "arson",
    "KIDNAPPING & RELATED OFFENSES": "kidnapping",
    "DANGEROUS DRUGS": "drug",
    "DANGEROUS WEAPONS": "weapons",
    "CRIMINAL MISCHIEF & RELATED OF": "vandalism",
    "THEFT-FRAUD": "fraud",
    "FRAUDS": "fraud",
    "FORGERY": "fraud",
    "OFFENSES INVOLVING FRAUD": "fraud",
    "HARRASSMENT 2": "other",
    "OFF. AGNST PUB ORD SENSBLTY &": "other",
    "MISCELLANEOUS PENAL LAW": "other",
    "OTHER STATE LAWS": "other",
    "OTHER STATE LAWS (NON PENAL LAW)": "other",
    "VEHICLE AND TRAFFIC LAWS": "other",
    "OFFENSES AGAINST PUBLIC ADMINI": "other",
    "OFFENSES AGAINST THE PERSON": "other",
    "CRIMINAL TRESPASS": "other",
    "PROSTITUTION & RELATED OFFENSES": "other",
    "INTOXICATED & IMPAIRED DRIVING": "other",
    "ADMINISTRATIVE CODE": "other",
}


def resolve_zip(zip_code: str) -> tuple[float, float] | None:
    """ZIP code -> (lat, lon) via its ZCTA centroid (approximate -- not real
    ZCTA boundaries, see ingestion/download_zcta.py). None if unknown ZIP."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT lat, lon FROM zip_centroids WHERE zip_code = :zip"),
            {"zip": zip_code},
        ).fetchone()
    return (row.lat, row.lon) if row else None


def resolve_location(lat: float, lon: float) -> dict | None:
    """Lat/long -> tract/county/place GEOIDs + names. None if the point isn't
    in any tract (e.g. open ocean)."""
    with engine.connect() as conn:
        tract = conn.execute(
            text(
                "SELECT geoid, name, state_fips FROM geographies "
                "WHERE geo_type = 'tract' AND ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) "
                "LIMIT 1"
            ),
            {"lat": lat, "lon": lon},
        ).fetchone()
        if tract is None:
            return None

        county_geoid = tract.geoid[:5]
        county = conn.execute(
            text("SELECT name FROM geographies WHERE geo_type = 'county' AND geoid = :geoid"),
            {"geoid": county_geoid},
        ).fetchone()

        place = conn.execute(
            text(
                "SELECT geoid, name FROM geographies "
                "WHERE geo_type = 'place' AND ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) "
                "LIMIT 1"
            ),
            {"lat": lat, "lon": lon},
        ).fetchone()

    return {
        "tract_geoid": tract.geoid,
        "tract_name": tract.name,
        "county_geoid": county_geoid,
        "county_name": county.name if county else None,
        "place_geoid": place.geoid if place else None,
        "place_name": place.name if place else None,
        "state_fips": tract.state_fips,
    }


def get_demographics(tract_geoid: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM demographics WHERE geoid = :geoid ORDER BY year DESC LIMIT 1"),
            {"geoid": tract_geoid},
        ).mappings().fetchone()
    if row is None:
        return None
    d = dict(row)
    if d.get("occupied_housing_units"):
        d["renter_pct"] = round(100 * d["renter_occupied_units"] / d["occupied_housing_units"], 1)
    return d


def get_home_values(county_geoid: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM home_values WHERE geoid = :geoid"),
            {"geoid": county_geoid},
        ).mappings().fetchone()
    return dict(row) if row else None


def get_crime(county_geoid: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT year, offense_code, incident_count FROM crime "
                "WHERE geoid = :geoid ORDER BY incident_count DESC"
            ),
            {"geoid": county_geoid},
        ).mappings().fetchall()
    return [
        {**dict(r), "offense_label": OFFENSE_LABELS.get(r["offense_code"], r["offense_code"])}
        for r in rows
    ]


# Below this many total incident records for the year, treat a county's
# crime data as an artifact of incomplete agency reporting rather than a
# real low-crime signal -- flagged via `reliable` on get_crime_rate's
# output. NYPD is the motivating example: all 5 NYC boroughs combined
# report 2 incidents for 2025 in the NIBRS master file (vs. hundreds of
# thousands for LA/Chicago/Houston), despite NYC obviously not having
# near-zero crime -- NYPD just hasn't meaningfully transitioned to NIBRS
# reporting. Never trust a rate built on this few records.
MIN_RELIABLE_INCIDENTS = 100


def get_crime_rate(county_geoid: str, year: int = 2025) -> dict | None:
    """Incidents per 100k population, for this county vs. its state vs.
    nationally. State/national denominators use only counties that actually
    have NIBRS data for `year` (not all counties report -- see
    ingestion/parse_nibrs.py) so the rate isn't diluted by population from
    counties with zero recorded crime just because their agency didn't
    submit data. Returns None if this county itself has no crime data.

    Check `reliable` before trusting `county_rate_per_100k` -- a county with
    a real reporting gap (e.g. NYPD/NYC) will still show up here with a
    tiny, meaningless rate rather than None, because it does have *some*
    rows in the crime table. See MIN_RELIABLE_INCIDENTS."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "WITH county_pop AS ("
                "  SELECT LEFT(geoid, 5) AS county_geoid, SUM(total_population) AS population "
                "  FROM demographics GROUP BY LEFT(geoid, 5)"
                "), county_crime AS ("
                "  SELECT geoid AS county_geoid, SUM(incident_count) AS incidents "
                "  FROM crime WHERE year = :year GROUP BY geoid"
                ") "
                "SELECT cc.county_geoid, cc.incidents, cp.population "
                "FROM county_crime cc JOIN county_pop cp ON cc.county_geoid = cp.county_geoid "
                "WHERE cp.population > 0"
            ),
            {"year": year},
        ).mappings().fetchall()

    county = next((r for r in rows if r["county_geoid"] == county_geoid), None)
    if county is None:
        return None

    # Counties below the reliability floor are dropped from the state/national
    # comparison pools entirely (not just flagged) -- otherwise a state with
    # one big non-reporting city (NY, with NYC) gets its "state average"
    # quietly built almost entirely from its smaller reporting counties
    # while looking like it covers the whole state.
    reliable_rows = [r for r in rows if r["incidents"] >= MIN_RELIABLE_INCIDENTS]

    state_fips = county_geoid[:2]
    state_rows = [r for r in reliable_rows if r["county_geoid"][:2] == state_fips]

    def totals(subset):
        return sum(r["incidents"] for r in subset), sum(r["population"] for r in subset)

    def rate(incidents, population):
        return round(incidents * 100_000 / population, 1) if population else None

    county_rate = rate(county["incidents"], county["population"])
    state_incidents, state_population = totals(state_rows)
    state_rate = rate(state_incidents, state_population)
    national_incidents, national_population = totals(reliable_rows)
    national_rate = rate(national_incidents, national_population)

    reliable = county["incidents"] >= MIN_RELIABLE_INCIDENTS
    return {
        "year": year,
        "county_incidents": county["incidents"],
        "county_population": county["population"],
        "county_rate_per_100k": county_rate,
        "reliable": reliable,
        "state_rate_per_100k": state_rate,
        "state_counties_reporting": len(state_rows),
        "vs_state_pct": round(100 * (county_rate / state_rate - 1), 1) if reliable and state_rate else None,
        "national_rate_per_100k": national_rate,
        "national_counties_reporting": len(reliable_rows),
        "vs_national_pct": round(100 * (county_rate / national_rate - 1), 1) if reliable and national_rate else None,
    }


def get_crime_by_category(county_geoid: str, year: int = 2025) -> dict | None:
    """Per-category incident rates (assault, drug, larceny_theft, etc. --
    see NIBRS_CATEGORY) for the county vs. its state vs. nationally. Same
    reliability rule as get_crime_rate (state/national pools restricted to
    counties clearing MIN_RELIABLE_INCIDENTS in TOTAL crime) -- but note
    individual categories can still be small-number-noisy even for a
    "reliable" county (e.g. 2 homicides vs. 1 last year is a "100% higher"
    that means much less than the same swing in a category with thousands
    of incidents). Only categories with at least one incident in the target
    county are included. None if this county has no crime data at all."""
    with engine.connect() as conn:
        pop_rows = conn.execute(
            text(
                "SELECT LEFT(geoid, 5) AS county_geoid, SUM(total_population) AS population "
                "FROM demographics GROUP BY LEFT(geoid, 5)"
            )
        ).mappings().fetchall()
        crime_rows = conn.execute(
            text("SELECT geoid AS county_geoid, offense_code, incident_count FROM crime WHERE year = :year"),
            {"year": year},
        ).mappings().fetchall()

    population_by_county = {r["county_geoid"]: r["population"] for r in pop_rows if r["population"]}

    county_category = {}
    county_total = {}
    for r in crime_rows:
        geoid = r["county_geoid"]
        if geoid not in population_by_county:
            continue
        category = NIBRS_CATEGORY.get(r["offense_code"], "other")
        county_category.setdefault(geoid, {})
        county_category[geoid][category] = county_category[geoid].get(category, 0) + r["incident_count"]
        county_total[geoid] = county_total.get(geoid, 0) + r["incident_count"]

    if county_geoid not in county_total:
        return None

    reliable_counties = [g for g, total in county_total.items() if total >= MIN_RELIABLE_INCIDENTS]
    state_fips = county_geoid[:2]
    state_counties = [g for g in reliable_counties if g[:2] == state_fips]
    reliable = county_total[county_geoid] >= MIN_RELIABLE_INCIDENTS

    def rate(incidents, population):
        return round(incidents * 100_000 / population, 1) if population else None

    categories = {}
    for category, target_incidents in sorted(county_category.get(county_geoid, {}).items()):
        target_rate = rate(target_incidents, population_by_county[county_geoid])

        state_incidents = sum(county_category.get(g, {}).get(category, 0) for g in state_counties)
        state_population = sum(population_by_county[g] for g in state_counties)
        state_rate = rate(state_incidents, state_population)

        national_incidents = sum(county_category.get(g, {}).get(category, 0) for g in reliable_counties)
        national_population = sum(population_by_county[g] for g in reliable_counties)
        national_rate = rate(national_incidents, national_population)

        categories[category] = {
            "incidents": target_incidents,
            "rate_per_100k": target_rate,
            "state_rate_per_100k": state_rate,
            "vs_state_pct": round(100 * (target_rate / state_rate - 1), 1) if reliable and state_rate else None,
            "national_rate_per_100k": national_rate,
            "vs_national_pct": round(100 * (target_rate / national_rate - 1), 1) if reliable and national_rate else None,
        }

    return {"year": year, "reliable": reliable, "categories": categories}


def get_local_crime_by_category(county_geoid: str, year: int = 2025) -> dict | None:
    """Same category breakdown as get_crime_by_category, but from the local
    crime supplement (NYPD's ofns_desc mapped via NYPD_CATEGORY) with the
    real county population as denominator. Categories are a best-effort
    crosswalk between two different classification systems (built against
    the actual distinct values seen in each -- see NYPD_CATEGORY), not a
    precise mapping -- and NYPD complaints still aren't the same counting
    unit as NIBRS offense records even within a matched category."""
    local = get_local_crime(county_geoid, year)
    if local is None:
        return None
    with engine.connect() as conn:
        population = conn.execute(
            text("SELECT COALESCE(SUM(total_population), 0) FROM demographics WHERE LEFT(geoid, 5) = :geoid"),
            {"geoid": county_geoid},
        ).scalar()

    category_incidents = {}
    for o in local["offenses"]:
        category = NYPD_CATEGORY.get(o["offense_category"], "other")
        category_incidents[category] = category_incidents.get(category, 0) + o["incident_count"]

    def rate(incidents):
        return round(incidents * 100_000 / population, 1) if population else None

    return {
        "year": year,
        "population": population,
        "categories": {cat: {"incidents": n, "rate_per_100k": rate(n)} for cat, n in category_incidents.items()},
    }


def get_local_crime(county_geoid: str, year: int = 2025) -> dict | None:
    """Real crime data from a local supplement (currently: NYPD complaint
    data for a whole NYC borough/county -- see
    ingestion/download_nypd_crime.py). Only returns data for counties that
    supplement has actually been populated for; this is a scoped exception,
    not a general per-city lookup. None if nothing's been loaded for this
    county/year."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT offense_category, law_category, incident_count, borough_name, source "
                "FROM local_crime_supplement WHERE county_geoid = :geoid AND year = :year "
                "ORDER BY incident_count DESC"
            ),
            {"geoid": county_geoid, "year": year},
        ).mappings().fetchall()
    if not rows:
        return None
    first = rows[0]
    return {
        "county_geoid": county_geoid,
        "year": year,
        "borough_name": first["borough_name"],
        "total_incidents": sum(r["incident_count"] for r in rows),
        "source": first["source"],
        "offenses": [
            {"offense_category": r["offense_category"], "law_category": r["law_category"], "incident_count": r["incident_count"]}
            for r in rows
        ],
    }


def get_local_crime_rate(county_geoid: str, year: int = 2025) -> dict | None:
    """Incidents per 100k using the local crime supplement instead of
    NIBRS, with the county's real Census population as the denominator (an
    earlier version estimated population within a ZIP+radius circle --
    switched to whole-county because NYC boroughs map 1:1 to counties, so
    there's no need to estimate at all here). Still deliberately NOT merged
    into get_crime_rate's output -- different underlying methodology (NYPD
    complaints vs. NIBRS offense records aren't the same counting unit),
    shouldn't be compared as if identical even though the population figure
    is now exact."""
    local = get_local_crime(county_geoid, year)
    if local is None:
        return None
    with engine.connect() as conn:
        population = conn.execute(
            text("SELECT COALESCE(SUM(total_population), 0) FROM demographics WHERE LEFT(geoid, 5) = :geoid"),
            {"geoid": county_geoid},
        ).scalar()
    rate = round(local["total_incidents"] * 100_000 / population, 1) if population else None
    return {
        "county_geoid": county_geoid,
        "year": year,
        "borough_name": local["borough_name"],
        "incidents": local["total_incidents"],
        "population": population,
        "rate_per_100k": rate,
        "source": local["source"],
    }


def get_elections(county_geoid: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM elections WHERE geoid = :geoid ORDER BY year DESC LIMIT 1"),
            {"geoid": county_geoid},
        ).mappings().fetchone()
    if row is None:
        return None
    d = dict(row)
    if d.get("total_votes"):
        d["winner"] = "GOP" if d["votes_gop"] > d["votes_dem"] else "Dem"
        d["margin_pct"] = round(100 * abs(d["votes_gop"] - d["votes_dem"]) / d["total_votes"], 1)
        # Two-party GOP vote share -- the number to diff between two places
        # for "how much more Republican/Democrat," since margin_pct alone
        # doesn't say which direction and isn't on a shared scale.
        two_party = d["votes_gop"] + d["votes_dem"]
        d["gop_two_party_pct"] = round(100 * d["votes_gop"] / two_party, 1) if two_party else None
    return d


def get_historic_sites(lat: float, lon: float, radius_m: int = 5000, limit: int = 5) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, site_type, city, listed_date, "
                "ST_Distance(geometry::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS distance_m "
                "FROM historic_sites "
                "WHERE ST_DWithin(geometry::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius) "
                "ORDER BY distance_m LIMIT :limit"
            ),
            {"lat": lat, "lon": lon, "radius": radius_m, "limit": limit},
        ).mappings().fetchall()
    return [{**dict(r), "distance_m": round(r["distance_m"])} for r in rows]


def get_neighborhood_summary(lat: float, lon: float) -> dict:
    location = resolve_location(lat, lon)
    if location is None:
        return {"location": None}

    return {
        "location": location,
        "demographics": get_demographics(location["tract_geoid"]),
        "home_values": get_home_values(location["county_geoid"]),
        "crime": get_crime(location["county_geoid"]),
        "crime_rate": get_crime_rate(location["county_geoid"]),
        "elections": get_elections(location["county_geoid"]),
        "historic_sites": get_historic_sites(lat, lon),
    }


def _pct_diff(target, home):
    if not isinstance(target, (int, float)) or not isinstance(home, (int, float)) or not home:
        return None
    return round(100 * (target / home - 1), 1)


def compare_to_home(lat: float, lon: float, home_zip: str = "10002") -> dict | None:
    """Compare a location against a fixed home ZIP's stats. `comparison`
    values are {target, home, diff_pct} -- diff_pct is positive when target
    is higher than home. None if either location can't be resolved."""
    home_coords = resolve_zip(home_zip)
    if home_coords is None:
        return None

    home = get_neighborhood_summary(*home_coords)
    target = get_neighborhood_summary(lat, lon)
    if home["location"] is None or target["location"] is None:
        return None

    t_demo, h_demo = target["demographics"] or {}, home["demographics"] or {}
    t_hv, h_hv = target["home_values"] or {}, home["home_values"] or {}
    t_rate, h_rate = target["crime_rate"] or {}, home["crime_rate"] or {}
    t_elec, h_elec = target["elections"] or {}, home["elections"] or {}

    # Crime rate comparison is suppressed entirely (not just a caveat) unless
    # BOTH sides clear MIN_RELIABLE_INCIDENTS -- comparing against a
    # non-reporting jurisdiction's near-zero rate (e.g. NYC/NYPD) produces a
    # nonsense percentage ("2,000,000% higher"), not just an imprecise one.
    both_reliable = bool(t_rate.get("reliable")) and bool(h_rate.get("reliable"))
    crime_rate_pair = (
        (t_rate.get("county_rate_per_100k"), h_rate.get("county_rate_per_100k")) if both_reliable else (None, None)
    )

    fields = {
        "median_household_income": (t_demo.get("median_household_income"), h_demo.get("median_household_income")),
        "median_gross_rent": (t_demo.get("median_gross_rent"), h_demo.get("median_gross_rent")),
        "renter_pct": (t_demo.get("renter_pct"), h_demo.get("renter_pct")),
        "median_age": (t_demo.get("median_age"), h_demo.get("median_age")),
        "zhvi": (t_hv.get("zhvi"), h_hv.get("zhvi")),
        "zori": (t_hv.get("zori"), h_hv.get("zori")),
        "crime_rate_per_100k": crime_rate_pair,
    }
    comparison = {
        name: {"target": t, "home": h, "diff_pct": _pct_diff(t, h)} for name, (t, h) in fields.items()
    }
    comparison["crime_rate_per_100k"]["unreliable"] = not both_reliable

    same_party = None
    if t_elec.get("winner") and h_elec.get("winner"):
        same_party = t_elec["winner"] == h_elec["winner"]

    # Percentage-POINT difference in GOP two-party vote share, not a
    # relative _pct_diff -- "target is 15 points more Republican than home"
    # is the meaningful comparison here, not "GOP share is 20% higher."
    political_lean = None
    if t_elec.get("gop_two_party_pct") is not None and h_elec.get("gop_two_party_pct") is not None:
        diff_points = round(t_elec["gop_two_party_pct"] - h_elec["gop_two_party_pct"], 1)
        political_lean = {
            "target_gop_pct": t_elec["gop_two_party_pct"],
            "home_gop_pct": h_elec["gop_two_party_pct"],
            "diff_points": diff_points,
            "direction": "more Republican" if diff_points > 0 else "more Democratic" if diff_points < 0 else "the same",
        }

    # Separate from `comparison` on purpose: different underlying counting
    # methodology (NYPD complaints vs. NIBRS offense records), so it's
    # context, not a same-units diff_pct against the target's rate.
    home_county_geoid = home["location"]["county_geoid"]
    home_local_crime = get_local_crime_rate(home_county_geoid)

    # Per-category (assault, drug, larceny_theft, etc.) vs. state, national,
    # and home. Home's rate prefers the local supplement (NYPD, real data)
    # over NIBRS when one exists for home's county (currently only NYC) --
    # falls back to home's own NIBRS category rate otherwise, so this works
    # for any home ZIP, not just ones with a local supplement. `home_source`
    # says which was used, since local-supplement vs. NIBRS-vs-NIBRS are not
    # the same apples-to-apples guarantee.
    #
    # MIN_CATEGORY_INCIDENTS guards specifically against home's own count
    # being tiny for a category -- confirmed real on the NYPD supplement
    # (kidnapping: 1 incident, weapons: 3, arson: 3 for all of Manhattan in
    # the pulled data), which produced nonsense like "+36,000% vs home" for
    # a target with just a normal handful of weapons incidents. The overall
    # MIN_RELIABLE_INCIDENTS floor doesn't catch this -- it's a total-crime
    # check, and a jurisdiction can clear it in aggregate while still having
    # a near-zero count in one specific category.
    MIN_CATEGORY_INCIDENTS = 10
    crime_by_category = None
    t_category = get_crime_by_category(target["location"]["county_geoid"])
    if t_category and t_category["reliable"]:
        h_category = get_crime_by_category(home_county_geoid)
        h_local_category = get_local_crime_by_category(home_county_geoid)
        crime_by_category = {}
        for category, stats in t_category["categories"].items():
            entry = dict(stats)
            home_rate, home_source = None, None
            if h_local_category and category in h_local_category["categories"]:
                cat_stats = h_local_category["categories"][category]
                if cat_stats["incidents"] >= MIN_CATEGORY_INCIDENTS:
                    home_rate, home_source = cat_stats["rate_per_100k"], "local_supplement"
            if home_rate is None and h_category and h_category["reliable"] and category in h_category["categories"]:
                cat_stats = h_category["categories"][category]
                if cat_stats["incidents"] >= MIN_CATEGORY_INCIDENTS:
                    home_rate, home_source = cat_stats["rate_per_100k"], "nibrs"
            entry["home_rate_per_100k"] = home_rate
            entry["home_source"] = home_source
            entry["vs_home_pct"] = round(100 * (stats["rate_per_100k"] / home_rate - 1), 1) if home_rate else None
            crime_by_category[category] = entry

    return {
        "home_zip": home_zip,
        "home_location": home["location"],
        "target_location": target["location"],
        "comparison": comparison,
        "home_local_crime": home_local_crime,
        "same_winning_party_2024": same_party,
        "political_lean": political_lean,
        "crime_by_category": crime_by_category,
    }
