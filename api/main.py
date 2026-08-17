"""Neighborhood Info API. Run from repo root:
  api/.venv/bin/uvicorn api.main:app --reload
"""
import os
import pathlib

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from api.llm import CATEGORY_INFO, classify_intent, generate_commentary, help_text
from api.wikipedia import get_history_events, get_history_people, get_history_summary
from db.queries import (
    compare_to_home,
    compare_to_national,
    compare_to_state,
    get_built_environment,
    get_crime,
    get_crime_rate,
    get_demographics,
    get_elections,
    get_hazard_risk,
    get_historic_sites,
    get_home_values,
    get_nearby_schools,
    get_neighborhood_summary,
    resolve_location,
)

app = FastAPI(title="Neighborhood Info API")


def require_api_key(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get("API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key header")


def _location_or_404(lat: float, lon: float) -> dict:
    loc = resolve_location(lat, lon)
    if loc is None:
        raise HTTPException(status_code=404, detail="location not covered (outside the US, or over water)")
    return loc


def _respond(data: dict, commentary: bool, style: str = "normal") -> dict:
    return {"summary": generate_commentary(data, style=style) if commentary else None, "data": data}


# One data-builder per category `classify_intent` (api/llm.py) can return --
# kept in sync with its VALID_CATEGORIES set. Each takes (loc, lat, lon,
# home_zip) and returns a dict of keys to merge into the response's `data`,
# mirroring what the equivalent single-category endpoint below returns.
CATEGORY_BUILDERS = {
    "demographics": lambda loc, lat, lon, home_zip: {"demographics": get_demographics(loc["tract_geoid"])},
    "housing": lambda loc, lat, lon, home_zip: {
        "demographics": get_demographics(loc["tract_geoid"]),
        "home_values": get_home_values(loc["county_geoid"]),
    },
    "crime": lambda loc, lat, lon, home_zip: {
        "crime": get_crime(loc["county_geoid"]),
        "crime_rate": get_crime_rate(loc["county_geoid"]),
    },
    "elections": lambda loc, lat, lon, home_zip: {"elections": get_elections(loc["county_geoid"])},
    "history": lambda loc, lat, lon, home_zip: {
        "historic_sites": get_historic_sites(lat, lon),
        **get_history_summary(lat, lon),
    },
    "compare": lambda loc, lat, lon, home_zip: {"compare": compare_to_home(lat, lon, home_zip)},
    "hazards": lambda loc, lat, lon, home_zip: {"hazards": get_hazard_risk(loc["tract_geoid"])},
    "schools": lambda loc, lat, lon, home_zip: {"schools": get_nearby_schools(lat, lon)},
    "walkability": lambda loc, lat, lon, home_zip: {"built_environment": get_built_environment(loc["block_group_geoid"])},
    "compare_state": lambda loc, lat, lon, home_zip: {"compare_state": compare_to_state(lat, lon)},
    "compare_usa": lambda loc, lat, lon, home_zip: {"compare_usa": compare_to_national(lat, lon)},
    # Explicitly NYC regardless of `home_zip` -- "compare to NYC" means NYC,
    # not whatever the caller's configured default home is. `compare` (the
    # existing category) is the one that respects `home_zip`.
    "compare_nyc": lambda loc, lat, lon, home_zip: {"compare_nyc": compare_to_home(lat, lon, "10002")},
    # Reuses the same full-picture data "everything" builds inline below --
    # the snarky one-liner needs the whole picture (demographics, home
    # values, crime, elections, hazards, walkability, schools) to have
    # enough grounded material to draw descriptors from.
    "vibe": lambda loc, lat, lon, home_zip: {
        k: v for k, v in get_neighborhood_summary(lat, lon).items() if k != "location"
    },
}

# Categories whose commentary should use the rapid-fire stat-callout style
# (see api/llm.py's RAPID_FIRE_SYSTEM_PROMPT) instead of narrated prose.
RAPID_FIRE_CATEGORIES = {"compare_state", "compare_usa", "compare_nyc"}

# Categories whose commentary should use the single-line snarky "vibe check"
# style (see api/llm.py's VIBE_SYSTEM_PROMPT) instead of narrated prose.
VIBE_CATEGORIES = {"vibe"}


@app.get("/neighborhood", dependencies=[Depends(require_api_key)])
def neighborhood(
    lat: float = Query(...),
    lon: float = Query(...),
    commentary: bool = Query(True),
    utterance: str | None = Query(
        None,
        description="Free-text request, e.g. 'tell me about crime here' or 'compare to home' -- "
        "routed to the relevant categories via DeepSeek intent classification instead of "
        "returning every category. Omit for the old full-summary behavior.",
    ),
    home_zip: str = Query("10002", description="Used only when the utterance implies a home comparison."),
):
    if utterance:
        categories = classify_intent(utterance)

        # Meta question about the tool itself, not about the current
        # location -- doesn't need a resolvable location or DB/DeepSeek
        # calls at all, so it's handled before location resolution and
        # answered with a fixed, deterministic string (help_text() is built
        # from the same CATEGORY_INFO classify_intent classifies against,
        # so it can't describe a capability that doesn't actually exist).
        if "help" in categories:
            data = {"requested_categories": ["help"], "available_categories": CATEGORY_INFO}
            return {"summary": help_text() if commentary else None, "data": data}

        loc = _location_or_404(lat, lon)
        is_everything = "everything" in categories

        data = {"location": loc, "requested_categories": categories}
        if is_everything:
            full = get_neighborhood_summary(lat, lon)
            data.update({k: v for k, v in full.items() if k != "location"})
            data.update(get_history_summary(lat, lon))
            data["compare"] = compare_to_home(lat, lon, home_zip)
        else:
            for category in categories:
                data.update(CATEGORY_BUILDERS[category](loc, lat, lon, home_zip))

        if is_everything:
            style = "long"
        elif VIBE_CATEGORIES & set(categories):
            style = "vibe"
        elif RAPID_FIRE_CATEGORIES & set(categories):
            style = "rapid_fire"
        else:
            style = "normal"

        summary = generate_commentary(data, style=style) if commentary else None
        return {"summary": summary, "data": data}

    summary = get_neighborhood_summary(lat, lon)
    if summary["location"] is None:
        raise HTTPException(status_code=404, detail="location not covered (outside the US, or over water)")
    return _respond(summary, commentary)


@app.get("/neighborhood/housing", dependencies=[Depends(require_api_key)])
def housing(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {
        "location": loc,
        "demographics": get_demographics(loc["tract_geoid"]),
        "home_values": get_home_values(loc["county_geoid"]),
    }
    return _respond(data, commentary)


@app.get("/neighborhood/demographics", dependencies=[Depends(require_api_key)])
def demographics(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, "demographics": get_demographics(loc["tract_geoid"])}
    return _respond(data, commentary)


@app.get("/neighborhood/crime", dependencies=[Depends(require_api_key)])
def crime(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {
        "location": loc,
        "crime": get_crime(loc["county_geoid"]),
        "crime_rate": get_crime_rate(loc["county_geoid"]),
    }
    return _respond(data, commentary)


@app.get("/neighborhood/elections", dependencies=[Depends(require_api_key)])
def elections(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, "elections": get_elections(loc["county_geoid"])}
    return _respond(data, commentary)


@app.get("/neighborhood/history/sites", dependencies=[Depends(require_api_key)])
def history_sites(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, "historic_sites": get_historic_sites(lat, lon)}
    return _respond(data, commentary)


@app.get("/neighborhood/history", dependencies=[Depends(require_api_key)])
def history(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, **get_history_summary(lat, lon)}
    return _respond(data, commentary)


@app.get("/neighborhood/history/events", dependencies=[Depends(require_api_key)])
def history_events(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, "events": get_history_events(lat, lon)}
    return _respond(data, commentary)


@app.get("/neighborhood/history/people", dependencies=[Depends(require_api_key)])
def history_people(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, "people": get_history_people(lat, lon)}
    return _respond(data, commentary)


@app.get("/neighborhood/hazards", dependencies=[Depends(require_api_key)])
def hazards(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, "hazards": get_hazard_risk(loc["tract_geoid"])}
    return _respond(data, commentary)


@app.get("/neighborhood/schools", dependencies=[Depends(require_api_key)])
def schools(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, "schools": get_nearby_schools(lat, lon)}
    return _respond(data, commentary)


@app.get("/neighborhood/walkability", dependencies=[Depends(require_api_key)])
def walkability(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    loc = _location_or_404(lat, lon)
    data = {"location": loc, "built_environment": get_built_environment(loc["block_group_geoid"])}
    return _respond(data, commentary)


@app.get("/neighborhood/vibe", dependencies=[Depends(require_api_key)])
def vibe(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    data = get_neighborhood_summary(lat, lon)
    if data["location"] is None:
        raise HTTPException(status_code=404, detail="location not covered (outside the US, or over water)")
    return _respond(data, commentary, style="vibe")


@app.get("/neighborhood/compare", dependencies=[Depends(require_api_key)])
def compare(
    lat: float = Query(...),
    lon: float = Query(...),
    home_zip: str = Query("10002"),
    commentary: bool = Query(True),
    rapid_fire: bool = Query(False, description="Use the short stat-callout style instead of narrated prose."),
):
    data = compare_to_home(lat, lon, home_zip)
    if data is None:
        raise HTTPException(status_code=404, detail="location or home ZIP not covered")
    return _respond(data, commentary, style="rapid_fire" if rapid_fire else "normal")


@app.get("/neighborhood/compare/state", dependencies=[Depends(require_api_key)])
def compare_state(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    data = compare_to_state(lat, lon)
    if data is None:
        raise HTTPException(status_code=404, detail="location not covered (outside the US, or over water)")
    return _respond(data, commentary, style="rapid_fire")


@app.get("/neighborhood/compare/national", dependencies=[Depends(require_api_key)])
def compare_national(lat: float = Query(...), lon: float = Query(...), commentary: bool = Query(True)):
    data = compare_to_national(lat, lon)
    if data is None:
        raise HTTPException(status_code=404, detail="location not covered (outside the US, or over water)")
    return _respond(data, commentary, style="rapid_fire")


@app.exception_handler(Exception)
def unhandled_exception(request, exc):
    return JSONResponse(status_code=500, content={"detail": "internal error"})
