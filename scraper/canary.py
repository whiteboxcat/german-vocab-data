"""Safety check before every sync: fetch two known words and make sure the parsers still read them correctly.

If verbformen.de changes its page layout, this fails loudly (GitHub emails you) instead of
filling the database with empty fields. The live pages are saved to archive/_canary/ for debugging.
"""
from __future__ import annotations

import sys
import time

from .config import load_config
from .http import PoliteClient
from .parse_noun import parse_noun
from .parse_verb import parse_verb
from .store import archive_html

CHECKS = [
    ("verb", "/konjugation/haben.htm", parse_verb, {
        "infinitive": "haben", "level": "A1", "partizip2": "gehabt", "praeteritum_3sg": "hatte",
        "auxiliaries": ["haben"],
    }),
    ("verb", "/konjugation/anrufen.htm", parse_verb, {
        "infinitive": "anrufen", "partizip2": "angerufen", "separable_prefix": "an",
    }),
    ("noun", "/deklination/substantive/Tisch.htm", parse_noun, {
        "lemma": "Tisch", "article": "der", "plural": "Tische", "level": "A1",
    }),
]


def main() -> int:
    cfg = load_config()
    client = PoliteClient(cfg["http"], time.time() + 15 * 60)
    problems = []
    for kind, path, parser, expected in CHECKS:
        resp = client.get(path)
        if resp.status != 200:
            problems.append(f"{path}: HTTP {resp.status}")
            continue
        archive_html(kind, path.rsplit("/", 1)[-1].removesuffix(".htm"), resp.text, sub="_canary")
        rec = parser(resp.text, client.abs_url(path))
        for field, want in expected.items():
            if rec.get(field) != want:
                problems.append(f"{path}: {field} = {rec.get(field)!r}, expected {want!r}")
        for field in ("english", "examples"):
            if not rec.get(field):
                problems.append(f"{path}: {field} is empty")
        if kind == "verb" and not rec.get("indicative", {}).get("Präsens"):
            problems.append(f"{path}: conjugation table (Präsens) not found")
        print(f"checked {path}: english={rec.get('english', [])[:3]} examples={len(rec.get('examples', []))}")

    hard = [p for p in problems if "examples is empty" not in p]
    for p in problems:
        print(("ERROR " if p in hard else "WARN  ") + p)
    if hard:
        print("\nThe page layout may have changed. Sync stopped so no bad data gets saved. "
              "Live pages are in archive/_canary/ — share one with Claude to update the parser.")
        return 1
    print("Canary OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
