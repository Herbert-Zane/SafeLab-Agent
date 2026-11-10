r"""Fetch GHS hazard statements from PubChem for the substances in the family table.

    .venv/Scripts/python.exe tools/fetch_pubchem.py
    .venv/Scripts/python.exe tools/fetch_pubchem.py --names "sodium hypochlorite" ethanol
    .venv/Scripts/python.exe tools/fetch_pubchem.py --refresh --json pubchem_ghs.json

For every PubChem search name listed under ``pubchem:`` in
``src/safelab/critic/families.yaml`` (or given with ``--names``), this resolves
the compound id through PUG-REST and reads the "GHS Classification" section
through PUG-View, then prints the hazard codes (H2xx-H4xx, EUHxxx) per family.

What it is for: a human cross-check of the family table. PubChem is not an
entry of ``docs/sources.md``, so nothing printed here may be cited by a
knowledge card or used by a rule. The critic never imports this script and
never calls PubChem.

Responses are cached under ``runs/cache/pubchem/`` (``runs/`` is not
committed); ``--refresh`` fetches again. PubChem asks for at most five
requests per second; the script waits between requests.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ROOT/"src"/"safelab"/"critic"/"families.yaml"
CACHE = ROOT/"runs"/"cache"/"pubchem"
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
HEADERS = {"User-Agent": "SafeLab-Agent family-table check (non-commercial research)"}
CODE = re.compile(r"\b(EUH\d{3}|H\d{3})\b")
PAUSE_S = 0.3


def get_json(url, timeout=30):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def cid_for(name):
    url = f"{PUG}/compound/name/{urllib.parse.quote(name)}/cids/JSON"
    try:
        data = get_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    cids = (data.get("IdentifierList") or {}).get("CID") or []
    return cids[0] if cids else None


def _strings(node):
    """Every ``String`` under a PUG-View node."""
    if isinstance(node, dict):
        if isinstance(node.get("String"), str):
            yield node["String"]
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _sections(node, heading):
    if isinstance(node, dict):
        if node.get("TOCHeading") == heading:
            yield node
        for value in node.values():
            yield from _sections(value, heading)
    elif isinstance(node, list):
        for value in node:
            yield from _sections(value, heading)


def ghs_for(cid):
    url = f"{PUG_VIEW}/data/compound/{cid}/JSON?heading=GHS+Classification"
    try:
        data = get_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"statements": [], "codes": [], "note": "no GHS Classification section"}
        raise
    statements = []
    for section in _sections(data, "GHS Classification"):
        for info in section.get("Information") or []:
            if info.get("Name") == "GHS Hazard Statements":
                statements += list(_strings(info.get("Value")))
    codes = sorted(set(CODE.findall(" ".join(statements))))
    return {"statements": list(dict.fromkeys(statements)), "codes": codes}


def fetch(name, cache, refresh=False):
    path = cache/f"{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}.json"
    if path.is_file() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    cid = cid_for(name)
    time.sleep(PAUSE_S)
    row = {"name": name, "cid": cid, "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
           "source": "PubChem PUG-REST / PUG-View (not an entry of docs/sources.md)"}
    if cid is not None:
        row.update(ghs_for(cid))
        row["url"] = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
        time.sleep(PAUSE_S)
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    return row


def names_by_family(path=FAMILIES):
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {family: list(spec.get("pubchem") or [])
            for family, spec in (data.get("families") or {}).items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--names", nargs="+", help="Search names (default: the family table's)")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--refresh", action="store_true", help="Ignore the cache")
    parser.add_argument("--json", type=Path, help="Also write all rows as JSON here")
    args = parser.parse_args(argv)
    groups = {"(given)": args.names} if args.names else names_by_family()
    rows = []
    print("PubChem GHS cross-check -- a development aid, not a knowledge-card source.\n")
    print("| family | name | CID | hazard codes |")
    print("|---|---|---|---|")
    for family, names in groups.items():
        for name in names:
            try:
                row = fetch(name, args.cache, args.refresh)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                row = {"name": name, "cid": None, "error": f"{type(exc).__name__}: {exc}"}
            rows.append({"family": family, **row})
            codes = ", ".join(row.get("codes") or []) or row.get("error") or row.get("note") or "-"
            print(f"| {family} | {name} | {row.get('cid')} | {codes} |")
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if all(row.get("cid") for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
