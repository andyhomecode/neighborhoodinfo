"""Load datasets/ into Postgres/PostGIS. Full reload each run (drop + recreate
all tables) -- matches the "batch refresh yearly" model, no incremental-upsert
complexity needed. Run: ingestion/.venv/bin/python -m db.load
"""
import csv
import json
import pathlib

import geopandas as gpd
import pandas as pd
from sqlalchemy import text

from db.engine import engine
from db.models import (
    Base,
    BuiltEnvironment,
    Crime,
    Demographic,
    Election,
    Geography,
    HistoricSite,
    HomeValue,
    LocalCrimeSupplement,
    NaturalHazardRisk,
    School,
    ZipCentroid,
)

# Tables this script owns and fully reloads every run. Deliberately excludes
# HistoryCache -- that table is written by the API at request time (see
# db/models.py's HistoryCache docstring), not by ingestion, so it must survive
# a batch reload rather than being dropped along with everything else.
BATCH_TABLES = [
    Geography.__table__,
    Demographic.__table__,
    HomeValue.__table__,
    Crime.__table__,
    Election.__table__,
    LocalCrimeSupplement.__table__,
    ZipCentroid.__table__,
    HistoricSite.__table__,
    NaturalHazardRisk.__table__,
    School.__table__,
    BuiltEnvironment.__table__,
]

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATASETS = REPO_ROOT / "datasets"

STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
    "60": "AS", "66": "GU", "69": "MP", "72": "PR", "78": "VI",
}

# Matches ingestion/download_acs.py's VARIABLES mapping.
ACS_COLUMNS = {
    "B01003_001E": "total_population",
    "B01002_001E": "median_age",
    "B19013_001E": "median_household_income",
    "B25064_001E": "median_gross_rent",
    "B02001_002E": "population_white_alone",
    "B02001_003E": "population_black_alone",
    "B02001_005E": "population_asian_alone",
    "B03002_012E": "population_hispanic_or_latino",
    "B17001_001E": "poverty_universe",
    "B17001_002E": "population_below_poverty",
    "B25003_001E": "occupied_housing_units",
    "B25003_002E": "owner_occupied_units",
    "B25003_003E": "renter_occupied_units",
    "B25024_002E": "units_1detached",
    "B25024_003E": "units_1attached",
    "B25024_004E": "units_2",
    "B25024_005E": "units_3_to_4",
    "B25024_006E": "units_5_to_9",
    "B25024_007E": "units_10_to_19",
    "B25024_008E": "units_20_to_49",
    "B25024_009E": "units_50_plus",
    "B25024_010E": "units_mobile_home",
    "B25035_001E": "median_year_built",
    "B15003_001E": "population_25_plus",
    "B15003_022E": "bachelors_degree",
    "B15003_023E": "masters_degree",
    "B15003_024E": "professional_degree",
    "B15003_025E": "doctorate_degree",
}


def load_geographies():
    print("geographies: county")
    gdf = gpd.read_file(f"zip://{DATASETS}/tiger/county/tl_2025_us_county.zip")
    gdf = gdf.to_crs(4326)
    out = gdf[["GEOID", "NAMELSAD", "STATEFP", "ALAND", "geometry"]].rename(
        columns={"GEOID": "geoid", "NAMELSAD": "name", "STATEFP": "state_fips", "ALAND": "aland_sq_m"}
    )
    out["geo_type"] = "county"
    out.to_postgis("geographies", engine, if_exists="append", index=False)

    for geo_type in ("tract", "place", "bg"):
        for fips in STATE_FIPS:
            path = DATASETS / "tiger" / geo_type / f"tl_2025_{fips}_{geo_type}.zip"
            if not path.exists():
                continue
            gdf = gpd.read_file(f"zip://{path}")
            gdf = gdf.to_crs(4326)
            out = gdf[["GEOID", "NAMELSAD", "STATEFP", "ALAND", "geometry"]].rename(
                columns={"GEOID": "geoid", "NAMELSAD": "name", "STATEFP": "state_fips", "ALAND": "aland_sq_m"}
            )
            out["geo_type"] = geo_type
            out.to_postgis("geographies", engine, if_exists="append", index=False)
        print(f"geographies: {geo_type} done")


def load_demographics():
    print("demographics")
    rows = []
    for path in sorted((DATASETS / "acs").glob("acs5_*.json")):
        data = json.loads(path.read_text())
        header = data[0]
        for record in data[1:]:
            d = dict(zip(header, record))
            geoid = d["state"] + d["county"] + d["tract"]
            row = {"geoid": geoid, "year": 2023}
            for code, name in ACS_COLUMNS.items():
                val = d.get(code)
                try:
                    val = float(val)
                    row[name] = val if val >= 0 else None  # negative = ACS "not available" sentinel
                except (TypeError, ValueError):
                    row[name] = None
            rows.append(row)
    df = pd.DataFrame(rows)
    df.to_sql("demographics", engine, if_exists="append", index=False, chunksize=5000, method="multi")
    print(f"demographics: {len(df):,} tracts")


def _latest_value(row, date_columns):
    for col in reversed(date_columns):
        if pd.notna(row[col]):
            return row[col], col
    return None, None


def load_home_values():
    print("home_values")
    zhvi = pd.read_csv(DATASETS / "zhvi" / "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv")
    zori = pd.read_csv(DATASETS / "zori" / "County_zori_uc_sfrcondomfr_sm_month.csv")

    def build(df, value_name, date_name):
        date_cols = [c for c in df.columns if c[:1].isdigit()]
        out = []
        for _, row in df.iterrows():
            geoid = f"{int(row['StateCodeFIPS']):02d}{int(row['MunicipalCodeFIPS']):03d}"
            value, date = _latest_value(row, date_cols)
            out.append({"geoid": geoid, value_name: value, date_name: date})
        return pd.DataFrame(out)

    zhvi_df = build(zhvi, "zhvi", "zhvi_date")
    zori_df = build(zori, "zori", "zori_date")
    merged = zhvi_df.merge(zori_df, on="geoid", how="outer")
    merged.to_sql("home_values", engine, if_exists="append", index=False, chunksize=2000, method="multi")
    print(f"home_values: {len(merged):,} counties")


def load_crime():
    print("crime")
    df = pd.read_csv(DATASETS / "fbi_crime" / "county_offense_counts_2025.csv", dtype=str)
    df = df[df["geoid"].notna() & (df["geoid"] != "")]
    df["incident_count"] = df["incident_count"].astype(int)
    df["year"] = df["year"].astype(int)
    df = df[["geoid", "year", "offense_code", "incident_count"]]
    df.to_sql("crime", engine, if_exists="append", index=False, chunksize=5000, method="multi")
    print(f"crime: {len(df):,} rows")


def load_elections():
    print("elections")
    rows = []
    with open(DATASETS / "elections" / "2024_US_County_Level_Presidential_Results.csv") as f:
        for r in csv.DictReader(f):
            fips = r["county_fips"].strip()
            if not fips or not fips.isdigit():
                continue
            rows.append(
                {
                    "geoid": fips.zfill(5),
                    "year": 2024,
                    "votes_gop": int(r["votes_gop"]),
                    "votes_dem": int(r["votes_dem"]),
                    "total_votes": int(r["total_votes"]),
                }
            )
    df = pd.DataFrame(rows)
    df.to_sql("elections", engine, if_exists="append", index=False, chunksize=2000, method="multi")
    print(f"elections: {len(df):,} counties")


def load_zip_centroids():
    print("zip_centroids")
    import zipfile

    zip_path = DATASETS / "zcta" / "2025_Gaz_zcta_national.zip"
    with zipfile.ZipFile(zip_path) as zf:
        name = [n for n in zf.namelist() if n.endswith(".txt")][0]
        with zf.open(name) as f:
            df = pd.read_csv(f, sep="|", dtype={"GEOID": str})
    out = df[["GEOID", "INTPTLAT", "INTPTLONG"]].rename(
        columns={"GEOID": "zip_code", "INTPTLAT": "lat", "INTPTLONG": "lon"}
    )
    out.to_sql("zip_centroids", engine, if_exists="append", index=False, chunksize=5000, method="multi")
    print(f"zip_centroids: {len(out):,} ZCTAs")


def load_local_crime_supplement():
    print("local_crime_supplement")
    paths = list((DATASETS / "nypd_crime").glob("nypd_complaints_*.json")) if (DATASETS / "nypd_crime").exists() else []
    if not paths:
        print("  none found, skipping (run ingestion/download_nypd_crime.py first)")
        return
    rows = []
    for path in paths:
        data = json.loads(path.read_text())
        for o in data["offenses"]:
            rows.append(
                {
                    "county_geoid": data["county_geoid"],
                    "year": data["year"],
                    "offense_category": o["ofns_desc"],
                    "law_category": o["law_cat_cd"],
                    "incident_count": int(o["n"]),
                    "borough_name": data["borough_name"],
                    "source": data["source"],
                }
            )
    df = pd.DataFrame(rows)
    df.to_sql("local_crime_supplement", engine, if_exists="append", index=False, chunksize=2000, method="multi")
    print(f"local_crime_supplement: {len(df):,} rows from {len(paths)} file(s)")


def load_historic_sites():
    print("historic_sites")
    points = gpd.read_file(DATASETS / "nrhp" / "nrhp_points.geojson")
    polys = gpd.read_file(DATASETS / "nrhp" / "nrhp_polygons.geojson")
    combined = pd.concat([points, polys], ignore_index=True)
    out = combined[["OBJECTID", "RESNAME", "ResType", "City", "County", "State", "CertDate", "geometry"]].rename(
        columns={
            "OBJECTID": "id",
            "RESNAME": "name",
            "ResType": "site_type",
            "City": "city",
            "County": "county_name",
            "State": "state",
            "CertDate": "listed_date",
        }
    )
    out = gpd.GeoDataFrame(out, geometry="geometry", crs=4326)
    out.to_postgis("historic_sites", engine, if_exists="append", index=False)
    print(f"historic_sites: {len(out):,} sites")


# FEMA NRI tract-level CSV column names -> this table's snake_case columns.
# Best-effort draft against NRI's documented naming convention (4-letter
# hazard codes + "_RISKS" suffix) -- NOT verified against a real downloaded
# header (see ingestion/download_fema_nri.py's docstring for why: every
# automated fetch attempt was blocked). load_hazard_risk() loads whatever
# subset of these actually matches the real file and prints the rest as
# unmatched, rather than crashing on a wrong guess -- fix this mapping once
# a real file's header is visible.
NRI_COLUMN_MAP = {
    "TRACTFIPS": "geoid",
    "RISK_SCORE": "risk_score",
    "RISK_RATNG": "risk_rating",
    "EAL_SCORE": "eal_score",
    "SOVI_SCORE": "social_vulnerability_score",
    "RESL_SCORE": "community_resilience_score",
    "AVLN_RISKS": "avalanche_risk_score",
    "CFLD_RISKS": "coastal_flooding_risk_score",
    "CWAV_RISKS": "cold_wave_risk_score",
    "DRGT_RISKS": "drought_risk_score",
    "ERQK_RISKS": "earthquake_risk_score",
    "HAIL_RISKS": "hail_risk_score",
    "HWAV_RISKS": "heat_wave_risk_score",
    "HRCN_RISKS": "hurricane_risk_score",
    "ISTM_RISKS": "ice_storm_risk_score",
    "RFLD_RISKS": "inland_flooding_risk_score",
    "LNDS_RISKS": "landslide_risk_score",
    "LTNG_RISKS": "lightning_risk_score",
    "SWND_RISKS": "strong_wind_risk_score",
    "TRND_RISKS": "tornado_risk_score",
    "TSUN_RISKS": "tsunami_risk_score",
    "VLCN_RISKS": "volcanic_activity_risk_score",
    "WFIR_RISKS": "wildfire_risk_score",
    "WNTW_RISKS": "winter_weather_risk_score",
}


def load_hazard_risk():
    print("natural_hazard_risk")
    paths = list((DATASETS / "fema_nri").glob("*.csv")) if (DATASETS / "fema_nri").exists() else []
    if not paths:
        print("  none found, skipping (run ingestion/download_fema_nri.py for manual-download steps)")
        return
    frames = []
    for path in paths:
        df = pd.read_csv(path, low_memory=False)
        found = {src: dst for src, dst in NRI_COLUMN_MAP.items() if src in df.columns}
        missing = [src for src in NRI_COLUMN_MAP if src not in df.columns]
        if missing:
            print(f"  {path.name}: {len(missing)} expected column(s) not found (mapping needs fixing): {missing}")
        if "geoid" not in found.values():
            print(f"  {path.name}: no GEOID column found, skipping this file")
            continue
        out = df[list(found)].rename(columns=found)
        out["geoid"] = out["geoid"].astype(str).str.zfill(11)
        frames.append(out)
    if not frames:
        print("  no usable rows across matched files, skipping")
        return
    combined = pd.concat(frames, ignore_index=True).drop_duplicates(subset="geoid")
    combined.to_sql("natural_hazard_risk", engine, if_exists="append", index=False, chunksize=5000, method="multi")
    print(f"natural_hazard_risk: {len(combined):,} tracts")


# NCES's own missing/not-applicable sentinel (confirmed live: -1/-2/etc. on
# TOTAL, TOTFRL, STUTERATIO for a real chunk of schools -- grade-level
# counts especially, since not every school reports every field).
def _nces_val(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def load_schools():
    print("schools")
    path = DATASETS / "nces_ccd" / "schools.csv"
    if not path.exists():
        print("  none found, skipping (run ingestion/download_nces_ccd.py first)")
        return
    df = pd.read_csv(
        path,
        usecols=[
            "NCESSCH", "SCH_NAME", "SCHOOL_TYPE_TEXT", "LCITY", "LSTATE",
            "TOTAL", "STUTERATIO", "TOTFRL", "ULOCALE", "SY_STATUS_TEXT", "LATCOD", "LONCOD",
        ],
    )
    df = df[df["SY_STATUS_TEXT"] == "Open"]  # exclude closed/future/inactive listings
    rows = []
    for _, r in df.iterrows():
        total = _nces_val(r["TOTAL"])
        totfrl = _nces_val(r["TOTFRL"])
        rows.append(
            {
                "id": str(r["NCESSCH"]),
                "name": r["SCH_NAME"],
                "school_type": r["SCHOOL_TYPE_TEXT"],
                "city": r["LCITY"],
                "state": r["LSTATE"].strip() if isinstance(r["LSTATE"], str) else r["LSTATE"],
                "enrollment": int(total) if total is not None else None,
                "pupil_teacher_ratio": _nces_val(r["STUTERATIO"]),
                "free_reduced_lunch_pct": round(100 * totfrl / total, 1) if total and totfrl is not None else None,
                "locale": r["ULOCALE"],
                "lat": r["LATCOD"],
                "lon": r["LONCOD"],
            }
        )
    out = pd.DataFrame(rows)
    # Nullable pandas Int64 (capital I), not plain int -- `enrollment` has
    # real Nones mixed in (schools with a missing/sentinel TOTAL), which
    # upcasts a plain int column to float64 (849 -> 849.0). to_postgis uses
    # Postgres COPY under the hood, which -- unlike a normal INSERT -- does
    # NOT tolerate a float value going into an integer column; confirmed
    # live via a real `invalid input syntax for type integer: "849.0"`
    # error before this fix.
    out["enrollment"] = out["enrollment"].astype("Int64")
    gdf = gpd.GeoDataFrame(
        out.drop(columns=["lat", "lon"]),
        geometry=gpd.points_from_xy(out["lon"], out["lat"]),
        crs=4326,
    )
    gdf.to_postgis("schools", engine, if_exists="append", index=False)
    print(f"schools: {len(gdf):,} open public schools")


def load_built_environment():
    print("built_environment")
    path = DATASETS / "epa_sld" / "sld.csv"
    if not path.exists():
        print("  none found, skipping (run ingestion/download_epa_sld.py first)")
        return
    # NOT using the file's own GEOID10/GEOID20 columns -- confirmed live that
    # they're pre-corrupted into scientific notation (e.g. "4.8113E+11") in
    # the source CSV itself, a real precision loss baked in before this
    # script ever touches it. Reconstructing from the separate, clean
    # STATEFP/COUNTYFP/TRACTCE/BLKGRPCE integer columns instead sidesteps
    # that entirely. Assumption (not fully verified): these decomposed
    # columns correspond to the GEOID20 (current-vintage) geography SLD v3
    # is primarily built on, not the legacy GEOID10 -- matches this app's
    # current-vintage TIGER `bg` geographies. Re-check if block-group joins
    # in `built_environment` come back suspiciously empty.
    df = pd.read_csv(
        path,
        low_memory=False,
        dtype={"STATEFP": str, "COUNTYFP": str, "TRACTCE": str, "BLKGRPCE": str},
        usecols=["STATEFP", "COUNTYFP", "TRACTCE", "BLKGRPCE", "NatWalkInd", "D1A", "D1C", "D3B", "D4C"],
    )
    df["geoid"] = (
        df["STATEFP"].str.zfill(2) + df["COUNTYFP"].str.zfill(3) + df["TRACTCE"].str.zfill(6) + df["BLKGRPCE"]
    )
    out = df.rename(
        columns={
            "NatWalkInd": "walkability_index",
            "D1A": "residential_density",
            "D1C": "employment_density",
            "D3B": "intersection_density",
            "D4C": "transit_frequency",
        }
    )[["geoid", "walkability_index", "residential_density", "employment_density", "intersection_density", "transit_frequency"]]
    # SLD's -99999 sentinel for "no transit service in this block group" --
    # confirmed live: 119,319 of 220,740 rows (54%) use it on D4C
    # specifically (no other column here has any negative values at all).
    # Real "no transit" for a rural/small-town block group, not a data
    # error -- coerce to None rather than showing a nonsense negative rate.
    out.loc[out["transit_frequency"] < 0, "transit_frequency"] = None
    out = out.drop_duplicates(subset="geoid")
    out.to_sql("built_environment", engine, if_exists="append", index=False, chunksize=5000, method="multi")
    print(f"built_environment: {len(out):,} block groups")


def main():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()

    Base.metadata.drop_all(engine, tables=BATCH_TABLES)
    Base.metadata.create_all(engine)  # checkfirst=True by default -- creates history_cache if missing, leaves it alone otherwise

    load_geographies()
    load_demographics()
    load_home_values()
    load_crime()
    load_elections()
    load_zip_centroids()
    load_local_crime_supplement()
    load_historic_sites()
    load_hazard_risk()
    load_schools()
    load_built_environment()

    with engine.connect() as conn:
        # Plain-geometry GIST indexes: used by ST_Contains point-in-polygon
        # lookups (resolve_location), which query in degrees/SRID 4326 directly.
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_geographies_geom ON geographies USING GIST (geometry)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_historic_sites_geom ON historic_sites USING GIST (geometry)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_schools_geom ON schools USING GIST (geometry)"))
        # Geography-cast GIST indexes: used by ST_DWithin/ST_Distance queries
        # (get_historic_sites, any radius search), which cast to ::geography
        # for accurate meter-based distance. A plain-geometry index does NOT
        # get used for a ::geography-cast query -- confirmed via EXPLAIN
        # ANALYZE, an 8.8-second full scan of every tract nationwide became
        # an 8.8ms index scan once this existed. Without both index flavors,
        # whichever query style doesn't match falls back to a full scan.
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_geographies_geom_geog ON geographies USING GIST ((geometry::geography))"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_historic_sites_geom_geog ON historic_sites USING GIST ((geometry::geography))"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_schools_geom_geog ON schools USING GIST ((geometry::geography))"))
        conn.commit()
    print("done, spatial indexes built")


if __name__ == "__main__":
    main()
