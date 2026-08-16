from geoalchemy2 import Geometry
from sqlalchemy import Column, DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Geography(Base):
    """Tract/county/place boundaries, from TIGER/Line. geo_type distinguishes
    the three (GEOID formats don't overlap: county=5 digits, place=7, tract=11,
    but geo_type keeps queries explicit rather than relying on string length)."""

    __tablename__ = "geographies"

    geoid = Column(String, primary_key=True)
    geo_type = Column(String, primary_key=True)  # 'county' | 'tract' | 'place' | 'bg'
    name = Column(String)
    state_fips = Column(String(2))
    aland_sq_m = Column(Float)  # TIGER's ALAND -- land area, sq meters, water excluded
    geometry = Column(Geometry(geometry_type="GEOMETRY", srid=4326))


class Demographic(Base):
    """ACS 5-year estimates, tract level."""

    __tablename__ = "demographics"

    geoid = Column(String, primary_key=True)  # tract GEOID
    year = Column(Integer, primary_key=True)
    total_population = Column(Integer)
    median_age = Column(Float)
    median_household_income = Column(Integer)
    median_gross_rent = Column(Integer)
    population_white_alone = Column(Integer)
    population_black_alone = Column(Integer)
    population_asian_alone = Column(Integer)
    population_hispanic_or_latino = Column(Integer)
    poverty_universe = Column(Integer)
    population_below_poverty = Column(Integer)
    occupied_housing_units = Column(Integer)
    owner_occupied_units = Column(Integer)
    renter_occupied_units = Column(Integer)
    units_1detached = Column(Integer)
    units_1attached = Column(Integer)
    units_2 = Column(Integer)
    units_3_to_4 = Column(Integer)
    units_5_to_9 = Column(Integer)
    units_10_to_19 = Column(Integer)
    units_20_to_49 = Column(Integer)
    units_50_plus = Column(Integer)
    units_mobile_home = Column(Integer)
    median_year_built = Column(Integer)
    # Educational attainment, ACS table B15003, population 25+.
    population_25_plus = Column(Integer)
    bachelors_degree = Column(Integer)
    masters_degree = Column(Integer)
    professional_degree = Column(Integer)
    doctorate_degree = Column(Integer)


class HomeValue(Base):
    """Zillow ZHVI/ZORI, county level. Latest available month only (not a
    time series) -- keeps the loader simple; extend to monthly history later
    if trend data is ever wanted."""

    __tablename__ = "home_values"

    geoid = Column(String, primary_key=True)  # county GEOID
    zhvi = Column(Float, nullable=True)
    zhvi_date = Column(String, nullable=True)
    zori = Column(Float, nullable=True)
    zori_date = Column(String, nullable=True)


class Crime(Base):
    """FBI NIBRS, aggregated to county/offense/year by ingestion/parse_nibrs.py."""

    __tablename__ = "crime"

    geoid = Column(String, primary_key=True)  # county GEOID
    year = Column(Integer, primary_key=True)
    offense_code = Column(String, primary_key=True)
    incident_count = Column(Integer)


class Election(Base):
    """2024 presidential results, county level, two-party totals."""

    __tablename__ = "elections"

    geoid = Column(String, primary_key=True)  # county GEOID
    year = Column(Integer, primary_key=True)
    votes_gop = Column(Integer)
    votes_dem = Column(Integer)
    total_votes = Column(Integer)


class LocalCrimeSupplement(Base):
    """One-off, scoped exception to the "no per-city sources" rule: real
    NYPD complaint data for a whole county (borough), pulled because NIBRS
    crime data is unusable for NYC (see MIN_RELIABLE_INCIDENTS in
    db/queries.py). County-keyed like every other crime-adjacent table (not
    ZIP+radius -- an earlier version was, but that meant estimating
    population within a radius, which turned out to meaningfully overcount;
    NYC boroughs map 1:1 to counties, so filtering NYPD's own `boro_nm`
    field and using the real Census county population is both simpler and
    exact). NOT a general per-city crime table -- only as many rows as
    ingestion/download_nypd_crime.py has actually been pointed at."""

    __tablename__ = "local_crime_supplement"

    county_geoid = Column(String(5), primary_key=True)
    year = Column(Integer, primary_key=True)
    offense_category = Column(String, primary_key=True)  # ofns_desc
    # Same offense_category can legitimately appear at more than one legal
    # severity (e.g. "DANGEROUS DRUGS" as both FELONY and MISDEMEANOR) --
    # part of the key, not just descriptive, or inserts collide.
    law_category = Column(String, primary_key=True)  # FELONY | MISDEMEANOR | VIOLATION
    incident_count = Column(Integer)
    borough_name = Column(String)
    source = Column(String)


class ZipCentroid(Base):
    """ZCTA (ZIP code) centroids, from the Census Gazetteer file. Used to
    resolve a ZIP to an approximate lat/long -- not real ZCTA boundaries."""

    __tablename__ = "zip_centroids"

    zip_code = Column(String(5), primary_key=True)
    lat = Column(Float)
    lon = Column(Float)


class HistoricSite(Base):
    """NRHP points + polygons (districts) in one table -- generic GEOMETRY
    column so both fit; queried by proximity (ST_DWithin), not by GEOID."""

    __tablename__ = "historic_sites"

    id = Column(Integer, primary_key=True)  # NRHP OBJECTID
    name = Column(String)
    site_type = Column(String)  # building | object | site | structure | district
    city = Column(String)
    county_name = Column(String)
    state = Column(String)
    listed_date = Column(String)
    geometry = Column(Geometry(geometry_type="GEOMETRY", srid=4326))


class NaturalHazardRisk(Base):
    """FEMA National Risk Index, tract level. No `year` column, unlike
    crime/elections -- NRI ships as a single current snapshot per release
    (currently v1.20, Dec 2025), not an annual series; a full reload just
    replaces the prior snapshot. Source is a manual download (see
    ingestion/download_fema_nri.py -- FEMA's site blocks every scripted
    fetch attempted during development, same situation as FBI crime data).

    Column names below are a best-effort draft against NRI's documented
    naming convention -- NOT verified against a real downloaded CSV header
    (see download_fema_nri.py's docstring). Confirm/correct in
    db/load.py's load_hazard_risk() once a real file exists before
    trusting this table's contents."""

    __tablename__ = "natural_hazard_risk"

    geoid = Column(String, primary_key=True)  # tract GEOID
    risk_score = Column(Float)
    risk_rating = Column(String)
    eal_score = Column(Float)  # Expected Annual Loss, composite
    social_vulnerability_score = Column(Float)
    community_resilience_score = Column(Float)
    # Per-hazard risk scores -- all 18 NRI hazard types, confirmed by name
    # (not necessarily by exact column-name mapping) via FEMA/OpenFEMA docs.
    avalanche_risk_score = Column(Float)
    coastal_flooding_risk_score = Column(Float)
    cold_wave_risk_score = Column(Float)
    drought_risk_score = Column(Float)
    earthquake_risk_score = Column(Float)
    hail_risk_score = Column(Float)
    heat_wave_risk_score = Column(Float)
    hurricane_risk_score = Column(Float)
    ice_storm_risk_score = Column(Float)
    inland_flooding_risk_score = Column(Float)
    landslide_risk_score = Column(Float)
    lightning_risk_score = Column(Float)
    strong_wind_risk_score = Column(Float)
    tornado_risk_score = Column(Float)
    tsunami_risk_score = Column(Float)
    volcanic_activity_risk_score = Column(Float)
    wildfire_risk_score = Column(Float)
    winter_weather_risk_score = Column(Float)


class School(Base):
    """NCES CCD public school characteristics -- location, enrollment,
    staffing, free/reduced-lunch eligibility. This is a POVERTY PROXY, NOT
    a quality/rating metric -- no free nationwide school-quality data
    exists (GreatSchools-style ratings are a proprietary product, checked
    during research and rejected for that reason). Point geometry, queried
    by proximity like historic_sites, not GEOID-keyed."""

    __tablename__ = "schools"

    id = Column(String, primary_key=True)  # NCES NCESSCH id
    name = Column(String)
    school_type = Column(String)
    city = Column(String)
    state = Column(String)
    enrollment = Column(Integer)
    pupil_teacher_ratio = Column(Float)
    free_reduced_lunch_pct = Column(Float)  # poverty proxy, not a quality signal
    locale = Column(String)
    geometry = Column(Geometry(geometry_type="POINT", srid=4326))


class BuiltEnvironment(Base):
    """EPA Smart Location Database, block-group level -- walkability plus
    the underlying density/transit measures it's derived from. A curated
    subset of SLD's 90+ variables, not a raw dump (same "sensible subset"
    approach as NaturalHazardRisk's hazard scores).

    Keyed by a 12-digit block group GEOID reconstructed from SLD's
    STATEFP/COUNTYFP/TRACTCE/BLKGRPCE columns (2019/2020-vintage,
    matching this app's current-vintage TIGER `bg` geographies) -- NOT
    from SLD's own GEOID10/GEOID20 columns, which are confirmed corrupted
    into scientific notation in the source CSV itself. See db/load.py's
    load_built_environment() for details."""

    __tablename__ = "built_environment"

    geoid = Column(String, primary_key=True)  # 12-digit block group GEOID (SLD's GEOID20)
    walkability_index = Column(Float)  # SLD's NatWalkInd
    residential_density = Column(Float)  # SLD's D1A, housing units/acre
    employment_density = Column(Float)  # SLD's D1C, jobs/acre
    intersection_density = Column(Float)
    transit_frequency = Column(Float)


class HistoryCache(Base):
    """Cache for the live Wikipedia/Wikidata GeoSearch lookup (api/wikipedia.py)
    -- the one category fetched at request time instead of pre-ingested, so a
    given location is only fetched once. Keyed by lat/lon rounded to 3
    decimals (~111m): tight enough that two distinct towns never collide,
    loose enough that GPS jitter on a re-query of "the same spot" still hits
    the cache. No refresh/expiry policy yet (open decision) -- a cached row
    is never refetched.

    Deliberately NOT part of db/load.py's yearly drop-and-reload cycle --
    unlike every other table here, this one is written by the API at request
    time, not by ingestion, so wiping it on a batch reload would defeat the
    point of caching. See db/load.py's main() for how it's excluded from the
    drop_all/create_all cycle."""

    __tablename__ = "history_cache"

    location_key = Column(String, primary_key=True)  # "lat,lon" rounded to 3 decimals
    lat = Column(Float)
    lon = Column(Float)
    fetched_at = Column(DateTime)
    places = Column(JSON)  # list of classified nearby-place dicts, see api/wikipedia.py
