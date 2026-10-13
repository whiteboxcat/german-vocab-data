"""Apply parser fixes to words already saved, without waiting for their next weekly/monthly check.

Runs at the start of every sync and does nothing unless PARSER_VERSION (scraper/parse_common.py)
is newer than the version the data was last parsed with:
  * words whose page is in archive/ are parsed again straight from that copy (no download)
  * other words (C1/C2 keep no page copy) that look affected are queued to download again
"""
from __future__ import annotations

import gzip
import sys

from .config import ARCHIVE_DIR, load_config
from .parse_common import PARSER_VERSION
from .parse_noun import parse_noun
from .parse_verb import parse_verb
from .store import Store, content_hash, now_iso

PARSERS = {"noun": parse_noun, "verb": parse_verb}


def looks_broken(rec: dict) -> bool:
    """Signs of the pre-v2 example bug: German sentence cut short (no final punctuation / one word)."""
    return any(not e["de"] or e["de"][-1] not in '.!?…"' or len(e["de"].split()) < 2
               for e in rec.get("examples", []))


def main() -> int:
    cfg = load_config()
    store = Store()
    have = int(store.meta.get("parser_version", 1))
    if have >= PARSER_VERSION:
        print(f"Parser version {PARSER_VERSION}: saved words are up to date.")
        return 0

    reparsed = unchanged = requeued = 0
    for kind, records in store.records.items():
        for slug, old in list(records.items()):
            page = ARCHIVE_DIR / f"{kind}s" / f"{slug}.html.gz"
            key = f"{kind}:{slug}"
            if page.exists():
                html = gzip.open(page).read().decode("utf-8")
                rec = {"id": slug, **PARSERS[kind](html, old.get("source_url", "")),
                       "rank": old.get("rank"), "zipf": old.get("zipf")}
                h = content_hash(rec)
                if h == old.get("hash"):
                    unchanged += 1
                    continue
                rec.update(first_seen=old.get("first_seen"), updated_at=now_iso(), hash=h)
                records[slug] = rec
                if key in store.registry:
                    store.registry[key]["hash"] = h
                store.changes.append({"key": key, "change": "reparsed"})
                reparsed += 1
            elif looks_broken(old) and key in store.registry:
                reg = store.registry[key]
                reg.pop("fetched_at", None)   # due again on the next sync, ahead of everything else
                reg.pop("hash", None)
                requeued += 1

    store.meta["parser_version"] = PARSER_VERSION
    store.save_state()
    store.save_outputs(cfg["target_levels"])
    print(f"Parser version {have} → {PARSER_VERSION}: {reparsed} words fixed from saved pages, "
          f"{unchanged} unchanged, {requeued} queued to download again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
