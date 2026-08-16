# Neighborhood Data API — Research Notes

## Goal
Server with an API, called from a Siri Shortcut with lat/long, returning interesting data about the neighborhood/area the user is currently driving through:
1. Median home values
2. City/county demographics
3. City/county crime rate
4. Political voting results (most recent local + federal elections)
5. Other interesting facts (stretch)

## Existing commercial APIs (evaluated, not chosen)
No single vendor covers all of this, and none include voting data.

- **ATTOM Data** — demographics, crime, unemployment, POI, transit, home values/rents. Enterprise pricing, sales-call onboarding.
- **NeighborhoodScout (Location Inc.)** — crime, demographics, housing, schools, real estate. Explicitly excludes race/ethnicity/income/protected-class demographic data. Enterprise pricing.
- **Local Logic** — lat/lng + radius → demographics, scores, POI. B2B/enterprise pricing.
- **DoorProfit** — crime-focused, looks more self-serve/affordable than the above; demographics/home-value coverage unclear, worth checking docs if budget is a concern.
- **HomeJunction Slipstream** — real estate + demographics + schools, industry-focused.

**Conclusion:** these are priced for real estate SaaS, not a hobby project, and none solve the voting-data requirement. Decided to build on free government data sources instead.

## Data sources (decided approach)

### 1. Median home values
- **Zillow ZHVI** — free CSV downloads by ZIP/county/metro, no API key, updated monthly. Primary source.
- **Census ACS table B25077** — median home value by tract/county/place, free API w/ key. More authoritative, lags Zillow.
- **Redfin Data Center** — similar free bulk CSVs, backup/cross-check.

### 2. Demographics
- **Census ACS 5-year API** — population, income, race/ethnicity, education, age, etc. Available down to census tract / block group (finer than city/county — worth using given the driving-through use case). Free, requires API key.

### 3. Crime rate
No single clean federal source.
- **FBI Crime Data Explorer API** — free, NIBRS agency-reported, but participation is inconsistent by department.
- Many cities/counties run their own **Socrata-based open data crime feeds** (NYC, LA, Chicago, SF, etc.) — per-jurisdiction integration work.
- Paid aggregators (SpotCrime, CrimeoMeter, NeighborhoodScout, DoorProfit) exist if per-jurisdiction handling becomes too much work.

### 4. Voting / elections
- **MIT Election Data + Science Lab (MEDSL)** — free bulk datasets, county-level federal results (president/senate/house) back decades. Static files, no live API.
- **Harvard Dataverse** — similar precinct-level files for some states.
- **OpenElections project** — volunteer-run, standardized CSVs, many states/counties, free.
- **Local elections (mayor, city council)** — no standard source; mostly individual county election board sites. Expect this to be the highest-maintenance part of the project. Consider deprioritizing local elections in v1.

### Other interesting data (same geocode-join pattern, stretch goals)
- Walk Score API (freemium) — walkability/bikeability/transit
- EPA AirNow API — real-time air quality
- FEMA API — flood zone data
- Census Business Patterns — business density/employer counts by industry
- USDA/Census — food desert / grocery access
- National Register of Historic Places — historic district overlays
- FCC Broadband Map — internet speed/availability
- GreatSchools API (paid) or state Dept of Ed open data (free, varies) — school ratings
- NASA/USGS — elevation, tree canopy %

## Architecture

**Pattern:** geocode-first, pre-ingested, FIPS-keyed lookups. Not live-calling external APIs per request — these sources update monthly/yearly at most.

### Request flow
1. Client (Siri Shortcut) sends lat/long to the API
2. API resolves lat/long → state/county/tract/place FIPS codes
   - Option A: call Census Geocoder API live (simple, adds a network hop per request)
   - Option B: load TIGER/Line tract shapefiles into local PostGIS, do point-in-polygon lookup (faster, offline, more setup) — **preferred given existing homelab**
3. API queries Postgres using FIPS codes as join keys across demographics/home-value/crime/election tables
4. Returns combined JSON

### Schema sketch (all keyed by GEOID/FIPS)
- `geographies` — tract/county/place boundaries (PostGIS geometry)
- `demographics` — GEOID, year, ACS variables
- `home_values` — GEOID/ZIP, year-month, ZHVI or ACS median value
- `crime` — county/city GEOID, year, offense counts/rates (schema will vary more here — sources aren't standardized)
- `elections` — county GEOID, year, office, candidate, votes

### Ingestion
Separate batch jobs (cron/manual scripts) per source, decoupled from the live API. Fits existing Docker homelab pattern: Postgres+PostGIS container + ingestion scripts + API container.

## Client: Siri Shortcut
1. **Get Current Location** action → lat/long
2. **Get Contents of URL** action → GET/POST to `https://yourserver.com/api/neighborhood?lat=[Latitude]&long=[Longitude]`
3. **Get Dictionary Value** on the JSON response → speak/show result

Needs HTTPS exposed (ngrok/Cloudflare Tunnel, as used previously for the MCP server) — Shortcuts won't reliably hit plain HTTP over cellular.

**Trigger options:**
- Manual voice invocation ("Hey Siri, Neighborhood info") — simplest, avoids spamming lookups
- Personal Automation on CarPlay-connect — fires at connection time, before you're moving, so may not reflect "current" neighborhood
- Siri Suggestions — automatic, based on usage patterns, not directly configurable

## Open decisions for v1
- Census Geocoder API call vs. local PostGIS point-in-polygon (leaning local, given homelab)
- Whether to include local (non-federal) election data in v1 given maintenance burden
- Crime data: FBI Crime Data Explorer only, or add per-city Socrata feeds for cities frequently driven through
- Which stretch datasets (if any) to include in v1 vs. later
