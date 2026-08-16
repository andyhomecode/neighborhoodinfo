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
    Crime,
    Demographic,
    Election,
    Geography,
    HistoricSite,
    HomeValue,
    LocalCrimeSupplement,
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
}


def load_geographies():
    print("geographies: county")
    gdf = gpd.read_file(f"zip://{DATASETS}/tiger/county/tl_2025_us_county.zip")
    gdf = gdf.to_crs(4326)
    out = gdf[["GEOID", "NAMELSAD", "STATEFP", "geometry"]].rename(
        columns={"GEOID": "geoid", "NAMELSAD": "name", "STATEFP": "state_fips"}
    )
    out["geo_type"] = "county"
    out.to_postgis("geographies", engine, if_exists="append", index=False)

    for geo_type in ("tract", "place"):
        for fips in STATE_FIPS:
            path = DATASETS / "tiger" / geo_type / f"tl_2025_{fips}_{geo_type}.zip"
            if not path.exists():
                continue
            gdf = gpd.read_file(f"zip://{path}")
            gdf = gdf.to_crs(4326)
            out = gdf[["GEOID", "NAMELSAD", "STATEFP", "geometry"]].rename(
                columns={"GEOID": "geoid", "NAMELSAD": "name", "STATEFP": "state_fips"}
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

    with engine.connect() as conn:
        # Plain-geometry GIST indexes: used by ST_Contains point-in-polygon
        # lookups (resolve_location), which query in degrees/SRID 4326 directly.
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_geographies_geom ON geographies USING GIST (geometry)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_historic_sites_geom ON historic_sites USING GIST (geometry)"))
        # Geography-cast GIST indexes: used by ST_DWithin/ST_Distance queries
        # (get_historic_sites, any radius search), which cast to ::geography
        # for accurate meter-based distance. A plain-geometry index does NOT
        # get used for a ::geography-cast query -- confirmed via EXPLAIN
        # ANALYZE, an 8.8-second full scan of every tract nationwide became
        # an 8.8ms index scan once this existed. Without both index flavors,
        # whichever query style doesn't match falls back to a full scan.
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_geographies_geom_geog ON geographies USING GIST ((geometry::geography))"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_historic_sites_geom_geog ON historic_sites USING GIST ((geometry::geography))"))
        conn.commit()
    print("done, spatial indexes built")


if __name__ == "__main__":
    main()
