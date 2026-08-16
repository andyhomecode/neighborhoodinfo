"""Live Wikipedia/Wikidata history lookup -- the one category not
pre-ingested into Postgres (see CLAUDE.md "History category specifics").
Two live calls on a cache miss:

1. Wikipedia GeoSearch (`list=geosearch` for distance-ordered pageids, then
   a batched `prop=extracts|pageterms|pageprops` call on those pageids for
   description/extract/Wikidata Q-id -- two calls instead of one because the
   geosearch *generator* form doesn't return distance, only the plain
   `list=geosearch` module does).
2. A single batched Wikidata SPARQL query (all Q-ids from the above, one
   request) for `wdt:P31` ("instance of"), used to classify each result as a
   person/event/site/other. Reliable for "person" (Wikidata's `Q5` = human,
   an exact match, not a label guess); event/site is the same "noisier
   free-text fallback" CLAUDE.md describes for Wikipedia categories, just
   applied to Wikidata instance-of labels instead, since P31 is already
   being fetched to catch Q5.

Results are cached in `history_cache` after first fetch per location -- see
db/models.py's HistoryCache. No refresh policy yet (open decision): a cached
location is never refetched.

Uses stdlib `urllib` rather than an HTTP client library, on purpose -- keeps
this feature dependency-free for the `api` image (see CLAUDE.md's "slim
image" design principle), and this environment's installed HTTP client
happens to be packaged as `httpx2`/`httpcore2` rather than `httpx`, which
isn't worth chasing down for two GET requests.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.engine import engine
from db.models import HistoryCache

USER_AGENT = "neighborhoodinfo/0.1 (personal hobby project; contact via GitHub issues)"

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

GEOSEARCH_RADIUS_M = 10_000  # Wikipedia's hard cap on gsradius -- no way to search wider in one call
GEOSEARCH_LIMIT = 20
REQUEST_TIMEOUT_S = 10

HUMAN_QID = "Q5"

# Classification heuristic over Wikidata P31 ("instance of") labels. Matches
# CLAUDE.md's documented "noisier, cheaper fallback" approach, but on
# Wikidata's structured (if messy) instance-of labels rather than Wikipedia's
# free-text categories, since P31 is already being fetched to detect Q5.
# Extend either regex if real-world results turn up an obvious miss -- built
# against what actually showed up testing Oberlin OH and Kearney NE, not a
# generic reference list.
EVENT_LABEL_RE = re.compile(
    r"\b(battle|war|riot|massacre|fire|flood|hurricane|tornado|disaster|"
    r"election|strike|protest|uprising|rebellion|siege|explosion|"
    r"earthquake|attack|shooting|accident|epidemic|outbreak|event)\b",
    re.IGNORECASE,
)
SITE_LABEL_RE = re.compile(
    r"\b(building|house|church|school|college|university|museum|park|"
    r"bridge|monument|memorial|cemetery|theater|theatre|library|hospital|"
    r"station|landmark|structure|district|neighborhood|hotel|courthouse|"
    r"lighthouse|fort|dam|stadium|arena|tower|mill|factory|farm|"
    r"conservatory|academy)\b",
    re.IGNORECASE,
)


def _get_json(url: str, params: dict, accept: str) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
        return json.loads(resp.read())


def _geosearch_pageids(lat: float, lon: float) -> list[dict]:
    """Distance-ordered (pageid, title, dist_m) via the plain geosearch list
    module -- the only form that returns `dist`."""
    data = _get_json(
        WIKIPEDIA_API,
        {
            "action": "query",
            "format": "json",
            "list": "geosearch",
            "gscoord": f"{lat}|{lon}",
            "gsradius": GEOSEARCH_RADIUS_M,
            "gslimit": GEOSEARCH_LIMIT,
        },
        accept="application/json",
    )
    return data.get("query", {}).get("geosearch", [])


def _fetch_page_details(pageids: list[int]) -> dict[int, dict]:
    """Description/extract/Wikidata Q-id for a batch of pageids, one call."""
    if not pageids:
        return {}
    data = _get_json(
        WIKIPEDIA_API,
        {
            "action": "query",
            "format": "json",
            "pageids": "|".join(str(p) for p in pageids),
            "prop": "extracts|pageterms|pageprops",
            "ppprop": "wikibase_item",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 400,
        },
        accept="application/json",
    )
    pages = data.get("query", {}).get("pages", {})
    details = {}
    for pageid_str, page in pages.items():
        details[int(pageid_str)] = {
            "description": (page.get("terms", {}).get("description") or [None])[0],
            "extract": page.get("extract"),
            "wikidata_id": page.get("pageprops", {}).get("wikibase_item"),
        }
    return details


def _fetch_instance_of(qids: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Batched SPARQL query: {qid: [(instance_of_qid, label), ...]}. A page
    can have several P31 values (e.g. Oberlin College is both "college" and
    "private university") -- keep all of them, classification checks the
    whole list. Returns {} (not raises) on failure -- classification is an
    enrichment, not core to the feature; losing it shouldn't break the
    lookup itself."""
    if not qids:
        return {}
    values = " ".join(f"wd:{q}" for q in qids)
    query = (
        "SELECT ?item ?instanceOf ?instanceOfLabel WHERE { "
        f"VALUES ?item {{ {values} }} "
        "?item wdt:P31 ?instanceOf. "
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } '
        "}"
    )
    try:
        data = _get_json(WIKIDATA_SPARQL, {"query": query, "format": "json"}, accept="application/sparql-results+json")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}

    result = {}
    for row in data.get("results", {}).get("bindings", []):
        qid = row["item"]["value"].rsplit("/", 1)[-1]
        instance_qid = row["instanceOf"]["value"].rsplit("/", 1)[-1]
        label = row.get("instanceOfLabel", {}).get("value", "")
        result.setdefault(qid, []).append((instance_qid, label))
    return result


def _classify(qid: str | None, instance_of_by_qid: dict[str, list[tuple[str, str]]]) -> str:
    if not qid or qid not in instance_of_by_qid:
        return "other"
    entries = instance_of_by_qid[qid]
    if any(instance_qid == HUMAN_QID for instance_qid, _ in entries):
        return "person"
    labels = " ".join(label for _, label in entries)
    if EVENT_LABEL_RE.search(labels):
        return "event"
    if SITE_LABEL_RE.search(labels):
        return "site"
    return "other"


def _fetch_live(lat: float, lon: float) -> list[dict]:
    hits = _geosearch_pageids(lat, lon)
    if not hits:
        return []

    details = _fetch_page_details([h["pageid"] for h in hits])
    qids = [d["wikidata_id"] for d in details.values() if d.get("wikidata_id")]
    instance_of_by_qid = _fetch_instance_of(qids)

    places = []
    for hit in hits:
        detail = details.get(hit["pageid"], {})
        wikidata_id = detail.get("wikidata_id")
        places.append(
            {
                "title": hit["title"],
                "distance_m": round(hit["dist"]),
                "description": detail.get("description"),
                "extract": detail.get("extract"),
                "wikidata_id": wikidata_id,
                "category": _classify(wikidata_id, instance_of_by_qid),
            }
        )
    return places


def _location_key(lat: float, lon: float) -> str:
    return f"{round(lat, 3)},{round(lon, 3)}"


def get_history_places(lat: float, lon: float) -> list[dict]:
    """Nearby Wikipedia-documented places/topics, each tagged `category`
    (person/event/site/other), distance-ordered. Cached per location -- see
    module docstring. Empty on genuinely remote stretches (a real
    characteristic of the data, not a bug -- see CLAUDE.md)."""
    key = _location_key(lat, lon)
    table = HistoryCache.__table__
    with engine.connect() as conn:
        row = conn.execute(select(table.c.places).where(table.c.location_key == key)).fetchone()
        if row is not None:
            return row.places

        places = _fetch_live(lat, lon)
        conn.execute(
            pg_insert(table)
            .values(location_key=key, lat=lat, lon=lon, fetched_at=datetime.now(timezone.utc), places=places)
            .on_conflict_do_nothing(index_elements=["location_key"])
        )
        conn.commit()
    return places


def get_history_summary(lat: float, lon: float) -> dict:
    return {"places": get_history_places(lat, lon)}


def get_history_events(lat: float, lon: float) -> list[dict]:
    return [p for p in get_history_places(lat, lon) if p["category"] == "event"]


def get_history_people(lat: float, lon: float) -> list[dict]:
    return [p for p in get_history_places(lat, lon) if p["category"] == "person"]
