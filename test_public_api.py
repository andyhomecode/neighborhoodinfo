"""Smoke test against the *public* API (https://server.maxwell.nyc/neighborhoodapi),
not the local DB -- exercises the whole real path: Cloudflare -> Caddy -> the
containerized api service. See test_lookup.py for a local-DB-only equivalent.

stdlib only, no venv required:
  python3 test_public_api.py <lat> <lon> [--path neighborhood/crime] [--utterance "..."] [--home-zip 90210]

Examples:
  python3 test_public_api.py 41.293 -82.223
  python3 test_public_api.py 41.293 -82.223 --path neighborhood/history
  python3 test_public_api.py 41.293 -82.223 --utterance "tell me about crime here"
  python3 test_public_api.py 41.293 -82.223 --utterance "compare to home" --home-zip 90210
"""
import argparse
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://server.maxwell.nyc/neighborhoodapi"
ENV_PATH = pathlib.Path(__file__).resolve().parent / ".env"


def _load_api_key() -> str:
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("API_KEY="):
            return line.split("=", 1)[1]
    raise SystemExit(f"API_KEY not found in {ENV_PATH}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lat")
    parser.add_argument("lon")
    parser.add_argument("--path", default="neighborhood", help='e.g. "neighborhood/crime" (default: "neighborhood")')
    parser.add_argument("--utterance", default=None, help='free text, e.g. "tell me about crime here"')
    parser.add_argument("--home-zip", default=None, help="only used with --utterance's compare/everything intent")
    parser.add_argument("--no-commentary", action="store_true", help="skip the DeepSeek call, just get raw data")
    args = parser.parse_args()

    params = {"lat": args.lat, "lon": args.lon}
    if args.utterance:
        params["utterance"] = args.utterance
    if args.home_zip:
        params["home_zip"] = args.home_zip
    if args.no_commentary:
        params["commentary"] = "false"

    url = f"{BASE_URL}/{args.path}?{urllib.parse.urlencode(params)}"
    # Explicit User-Agent -- Cloudflare's bot protection in front of
    # server.maxwell.nyc blocks urllib's default "Python-urllib/x.x" UA
    # outright (HTTP 403, Cloudflare error 1010), confirmed live.
    req = urllib.request.Request(
        url, headers={"X-API-Key": _load_api_key(), "User-Agent": "neighborhoodinfo-test-script/0.1"}
    )

    print(f"GET {url}\n")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}")
        return

    if "requested_categories" in body["data"]:
        print(f"requested_categories: {body['data']['requested_categories']}\n")
    if body.get("summary"):
        print(f"summary: {body['summary']}\n")
    print("data:")
    print(json.dumps(body["data"], indent=2))


if __name__ == "__main__":
    main()
