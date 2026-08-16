"""DeepSeek-generated spoken commentary, built from db/queries.py's
structured output. All arithmetic (renter_pct, margin_pct, vs_state_pct,
etc.) is precomputed in db/queries.py before this ever runs -- the model is
asked to narrate given numbers, not compute its own, so it can't introduce
a math error into a stat.
"""
import json
import os

from openai import OpenAI

_client = None

SYSTEM_PROMPT = """You are narrating interesting facts about a place to someone driving through it, for a voice assistant (Siri) to read aloud.

You will be given structured JSON: demographics, home values, crime, 2024 election results, historic sites, and sometimes a comparison to the listener's home location.

Write a few short sentences suitable for text-to-speech. Rules:
- Strongly prefer facts directly present in the JSON. Add data points or commentary to explain outlier data (examples: High drug crime rate for area, if LLM knows opiod crisis is bad in region add note.  If demographics espeically young, and you know it's a college town, note that.)  
- always state the name of the location, like city, town, and county.
- always state the property information such as median home price and renter percentage if possible.
- always include demographic information if available
- if crime is higher or lower than average, include crime rates
- Do not do your own math -- use the numbers and percentages already computed in the JSON (e.g. renter_pct, vs_state_pct, margin_pct) rather than calculating your own from raw counts.
- Prefer what's genuinely notable (an unusual age skew, a big gap vs. state/national/home, a distinctive economic pattern) over reciting every field in order.
- Round numbers the way a person would say them aloud ("about sixty thousand dollars", not "59,987.42").
- Concise robotic tone. not conversational or breezy. No bullet points, no headers, no markdown. Just reading stats and data
- If home-comparison data is present, you may reference it, but don't force it if nothing about it is actually interesting.
- if there is something notable about the data and the location that you know, like the high drug crime rate maps to known info about opiod addiction in the region, mention it breifly
- for politics, call republican red or deep red, and democrat blue or deep blue in addition to the lean percentage
- If a field is null/missing/None, don't mention it -- don't say "data is unavailable," just skip it.
- If school data (schools/enrollment/pupil_teacher_ratio/free_reduced_lunch_pct) is present, describe it only as characteristics -- never call a school "good" or "bad," never imply a quality rating or ranking, and never infer quality from free_reduced_lunch_pct (a poverty indicator, not a performance measure). No school-quality data exists in this JSON; do not invent an impression of one.
"""


LONG_ADDENDUM = """

The user explicitly asked for a full, thorough rundown of this location -- not a quick highlight. Cover every category present in the JSON in some depth (demographics, housing, crime, elections, history/historic sites, and the home comparison if present), not just the single most notable fact. This should read as a longer, complete narration, not a short summary."""

# Single source of truth for what `classify_intent` can return -- both
# INTENT_SYSTEM_PROMPT and help_text() are built from this, so the model's
# classification options and the user-facing help description can't drift
# apart the way two independently hand-written lists would. "help" is a
# meta-category (not a data category, and not in api/main.py's
# CATEGORY_BUILDERS) -- handled as a special case by both classify_intent's
# prompt and api/main.py's route.
CATEGORY_INFO = {
    "demographics": {
        "description": "population, age, income, race/ethnicity, poverty",
        "example": "what's the population here",
    },
    "housing": {
        "description": "home values, rent, renter percentage, housing type mix",
        "example": "how much are homes here",
    },
    "crime": {
        "description": "crime rates and offense breakdown, vs. state and national averages",
        "example": "is this area safe",
    },
    "elections": {
        "description": "2024 presidential election results",
        "example": "how did this county vote",
    },
    "history": {
        "description": "historic sites and local history, notable nearby places",
        "example": "tell me about the history here",
    },
    "compare": {
        "description": "how this place compares to your home location",
        "example": "compare this to home",
    },
    "hazards": {
        "description": "natural hazard risk -- flooding, wildfire, earthquake, hurricane, tornado, and other disaster risk",
        "example": "is this area at risk of flooding",
    },
    "schools": {
        "description": "nearby public school characteristics -- enrollment, staffing ratio, poverty indicators (not quality ratings, which don't exist in this data)",
        "example": "are there schools nearby",
    },
    "walkability": {
        "description": "how walkable the area is, plus residential/employment density and transit access",
        "example": "how walkable is this area",
    },
    "everything": {
        "description": "a full, longer rundown covering every category above",
        "example": "tell me everything about this place",
    },
}

VALID_CATEGORIES = set(CATEGORY_INFO) | {"help"}


def _build_intent_prompt() -> str:
    category_lines = "\n".join(f'- "{name}" -- {info["description"]}' for name, info in CATEGORY_INFO.items())
    return f"""The user spoke a request to a voice assistant while driving, asking for information about their current location. Classify what they're asking for.

Respond with ONLY a JSON object of the form {{"categories": [...]}}.

Valid category values:
{category_lines}
- "help" -- the user is asking what they can ask, what this tool does, or for instructions/examples -- not asking about their current location at all

Include every category the request is actually asking about (a request can name more than one, e.g. "crime and history"). If the request is vague, general ("what's around here", "tell me about this place"), or clearly wants multiple/all categories, respond with ["everything"]. If it's a meta question about the tool itself ("what can I ask", "help", "what do you do"), respond with ["help"] only. If you genuinely cannot tell what's being asked, default to ["everything"] rather than guessing narrowly -- never return an empty list.
"""


INTENT_SYSTEM_PROMPT = _build_intent_prompt()


def help_text() -> str:
    """Deterministic (not LLM-generated), concise keyword-style listing of
    what this API understands -- built from CATEGORY_INFO's keys, so it
    can never list a category classify_intent doesn't actually support and
    never goes stale when a category is added. Deliberately terse (a
    keyword list, not full example sentences) since it's read aloud."""
    return "Topics: " + ", ".join(CATEGORY_INFO) + "."


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
    return _client


def classify_intent(utterance: str) -> list[str]:
    """Free-text utterance -> list of category names from VALID_CATEGORIES.
    Never returns an empty list -- falls back to ["everything"] on an
    unparseable/empty model response so a classification hiccup fails open
    (more data than asked for) rather than silently returning nothing."""
    client = _get_client()
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": utterance},
        ],
        max_tokens=100,
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        parsed = json.loads(resp.choices[0].message.content)
        categories = [c for c in parsed.get("categories", []) if c in VALID_CATEGORIES]
    except (json.JSONDecodeError, AttributeError, TypeError):
        categories = []
    return categories or ["everything"]


def generate_commentary(data: dict, long: bool = False) -> str:
    client = _get_client()
    system_prompt = SYSTEM_PROMPT + LONG_ADDENDUM if long else SYSTEM_PROMPT
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(data, default=str)},
        ],
        max_tokens=900 if long else 300,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()
