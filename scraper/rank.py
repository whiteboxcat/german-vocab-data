"""Order words by how common they are in written and spoken German together.

Uses wordfreq (Wikipedia, news, books, web text, subtitles, social media; data CC BY-SA 4.0)
instead of subtitles only, which is closer to the reading and listening texts of exams.
Each word gets `zipf` (frequency on a log scale: ~7 = "und", 3 = rare) and `rank`
(1 = most common of all saved words). The app teaches lower ranks first within each level.
"""
from __future__ import annotations

import sys

from .config import load_config
from .store import Store, content_hash, now_iso

try:
    from wordfreq import zipf_frequency
except ImportError:          # not installed (local runs): keep the existing order
    zipf_frequency = None


def headword(r: dict) -> str:
    return r.get("lemma") or r.get("infinitive") or r["id"]


def zipf(word: str) -> float:
    if zipf_frequency is None:
        return 0.0
    score = zipf_frequency(word, "de", wordlist="large")
    if score == 0 and " " in word:                     # "sich freuen" → "freuen"
        score = zipf_frequency(word.split()[-1], "de", wordlist="large")
    return round(score, 2)


def apply_ranks(store: Store) -> int:
    """Set zipf + rank on every record; returns how many words changed."""
    if zipf_frequency is None:
        print("wordfreq not installed: word order unchanged")
        return 0
    rows = [(kind, r) for kind, recs in store.records.items() for r in recs.values()]
    scores = {(kind, r["id"]): zipf(headword(r)) for kind, r in rows}
    ordered = sorted(rows, key=lambda kr: (-scores[(kr[0], kr[1]["id"])], headword(kr[1]).lower()))
    changed = 0
    for i, (kind, r) in enumerate(ordered, 1):
        z = scores[(kind, r["id"])]
        if r.get("rank") == i and r.get("zipf") == z:
            continue
        r["rank"], r["zipf"] = i, z
        r["hash"] = content_hash({k: v for k, v in r.items() if k != "hash"})
        r["updated_at"] = now_iso()
        key = f"{kind}:{r['id']}"
        if key in store.registry:
            store.registry[key]["hash"] = r["hash"]
            store.registry[key]["rank"] = i
        changed += 1
    if changed:
        store.changes.append({"key": "*", "change": f"reordered {changed} words by frequency"})
    return changed


def main() -> int:
    cfg = load_config()
    store = Store()
    n = apply_ranks(store)
    store.save_state()
    store.save_outputs(cfg["target_levels"])
    print(f"Word order: {n} words got a new rank.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
