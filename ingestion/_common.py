import pathlib

import requests

USER_AGENT = "neighborhoodinfo-ingestion/0.1 (personal project; contact via GitHub)"

# 50 states + DC + 5 territories covered by TIGER/Line and the Census API.
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


def download(url: str, dest: pathlib.Path, skip_if_exists: bool = True) -> bool:
    """Stream url to dest. Returns True if downloaded, False if skipped."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if skip_if_exists and dest.exists() and dest.stat().st_size > 0:
        print(f"  skip (exists): {dest.name}")
        return False
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=60)
    resp.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)
    tmp.rename(dest)
    print(f"  downloaded: {dest.name} ({dest.stat().st_size:,} bytes)")
    return True
