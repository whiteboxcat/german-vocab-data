"""Main entry point: discover words at the target level(s), fetch their pages, store what changed.

Usage:
    python -m scraper.sync              # does work only if something is due (weekly, later monthly)
    python -m scraper.sync --force      # re-check everything now
    python -m scraper.sync --limit 20   # small test run: at most 20 detail pages
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import time
from urllib.parse import quote

import requests

from .config import SEEDS_DIR, current_interval_days, load_config
from .http import OutOfTime, PoliteClient, RateLimited
from .parse_noun import REQUIRED_NOUN_FIELDS, parse_noun
from .parse_search import parse_search, slug_from_url
from .parse_verb import REQUIRED_VERB_FIELDS, parse_verb
from .store import Store, archive_html, content_hash, now_iso

CANONICAL_RE = re.compile(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"')
WORD_RE = re.compile(r"^[A-Za-zÄÖÜäöüß-]{2,40}$")


# --------------------------------------------------------------------------- candidates
def load_seed_words() -> list[str]:
    words: list[str] = []
    for path in sorted(SEEDS_DIR.glob("*.txt")):
        for ln in path.read_text(encoding="utf-8").splitlines():
            w = ln.split("#", 1)[0].strip()
            if w and WORD_RE.match(w):
                words.append(w)
    return words


def load_candidate_words(cfg: dict) -> list[str]:
    words: list[str] = load_seed_words()
    disc = cfg["discovery"]
    url, top_n = disc.get("frequency_list_url"), int(disc.get("frequency_top_n", 0))
    if url and top_n > 0:
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            n = 0
            for ln in r.text.splitlines():
                w = ln.split(" ", 1)[0].strip()
                if WORD_RE.match(w):
                    words.append(w)
                    n += 1
                    if n >= top_n:
                        break
        except requests.RequestException as e:
            print(f"! frequency list unavailable ({e}); using seed words only")
    seen, out = set(), []
    for w in words:
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out


def _days_since(iso: str | None) -> float:
    if not iso:
        return 1e9
    then = dt.datetime.fromisoformat(iso)
    if then.tzinfo is None:
        then = then.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - then).total_seconds() / 86400


# --------------------------------------------------------------------------- phases
def discover(client: PoliteClient, store: Store, words: list[str], cfg: dict, targets: set[str],
             limit: int | None = None, stop_at: float | None = None) -> int:
    disc = cfg["discovery"]
    recheck = float(disc["recheck_candidates_after_days"])
    budget = int(disc["max_searches_per_run"])
    if limit:  # test runs stay quick: no more searches than the page limit
        budget = min(budget, limit)
    pending = [w for w in words if _days_since(store.candidates.get(w.lower(), {}).get("checked")) > recheck]
    print(f"Discovery: {len(pending)} of {len(words)} candidate words to look up (budget {budget} this run)")
    seeds = {w.lower() for w in load_seed_words()}
    rank_of = {w.lower(): i for i, w in enumerate(words)}  # seeds first, then by frequency
    done = unreadable = 0
    for w in pending[:budget]:
        if stop_at and time.time() > stop_at:
            print(f"  discovery: stopping after {done} searches to leave time for fetching")
            break
        resp = client.get(f"/suche/?w={quote(w)}")
        if resp.status != 200:
            continue
        entries = parse_search(resp.text)
        if not entries:
            unreadable += 1
            if unreadable >= 15 and done == 0:
                print("! Search pages can't be read; stopping discovery for this run (layout probably changed)")
                break
            if unreadable <= 3:
                archive_html("search", quote(w, safe=""), resp.text, sub="_search_debug")
            # Search page not readable: for your own seed words, try the word's own page directly.
            # Other words are left unchecked so they're retried once the search parser is fixed.
            if w.lower() in seeds:
                entries = probe_direct(client, w)
            if not entries:
                continue
        added = 0
        for e in entries:
            key = f"{e['kind']}:{e['slug']}"
            exact = e["headword_norm"] == w.lower()
            lvl = e["listing_level"]
            if (lvl in targets) or (lvl is None and exact):
                reg = store.registry.setdefault(key, {
                    "kind": e["kind"], "slug": e["slug"], "url": e["url"], "status": "pending",
                    "found_via": w, "first_seen": now_iso(),
                })
                reg["listing_level"] = lvl
                r = rank_of.get(w.lower())
                if r is not None and r < reg.get("rank", 10**9):
                    reg["rank"] = r
                added += 1
        store.candidates[w.lower()] = {"checked": now_iso(), "added": added}
        done += 1
        if done % 25 == 0:
            store.save_state()
            print(f"  … {done} searches, registry has {len(store.registry)} entries · {client.summary()}")
    if unreadable:
        print(f"! {unreadable} search pages could not be read (saved examples in archive/_search_debug/)")
    return done


UMLAUT_SLUG = str.maketrans({"ä": "a3", "ö": "o3", "ü": "u3", "Ä": "A3", "Ö": "O3", "Ü": "U3", "ß": "s5"})


def probe_direct(client: PoliteClient, word: str) -> list[dict]:
    """Try /konjugation/<word>.htm and /deklination/substantive/<Word>.htm without the search page."""
    found = []
    tries = []
    if word[:1].islower():
        tries.append(("verb", word.lower(), "/konjugation/"))
    tries.append(("noun", word[:1].upper() + word[1:], "/deklination/substantive/"))
    for kind, form, prefix in tries:
        slug = form.translate(UMLAUT_SLUG)
        resp = client.get(f"{prefix}{quote(slug)}.htm")
        if resp.status == 200:
            found.append({"kind": kind, "slug": slug, "url": client.abs_url(f"{prefix}{slug}.htm"),
                          "headword_norm": word.lower(), "listing_level": None})
    return found


def due_entries(store: Store, interval_days: float, targets: set[str]) -> list[dict]:
    due = []
    for key, e in store.registry.items():
        if e["status"] in ("removed", "alias"):
            continue
        if e["status"] == "excluded" and e.get("detail_level") not in targets:
            continue
        if _days_since(e.get("fetched_at")) >= interval_days - 0.25:
            due.append(e | {"key": key})
    due.sort(key=lambda e: e.get("fetched_at") or "")
    return due


def fetch_entry(client: PoliteClient, store: Store, e: dict, targets: set[str]) -> str:
    key, kind, slug = e["key"], e["kind"], e["slug"]
    reg = store.registry[key]
    resp = client.get(e["url"])
    if resp.status == 404:
        reg["status"] = "removed"
        reg["fetched_at"] = now_iso()
        store.changes.append({"key": key, "change": "removed_from_site"})
        return "removed"
    if resp.status != 200:
        return f"http_{resp.status}"

    # Some URLs show another word's page (e.g. .../Anrufen.htm shows "Anruf"). Follow the canonical
    # link so each word is stored once, under its real ID.
    m = CANONICAL_RE.search(resp.text)
    canon = slug_from_url(m.group(1)) if m else None
    if canon and canon != (kind, slug):
        ckind, cslug = canon
        reg["status"] = "alias"
        reg["alias_of"] = f"{ckind}:{cslug}"
        reg["fetched_at"] = now_iso()
        if slug in store.records[kind]:
            del store.records[kind][slug]
            store.changes.append({"key": key, "change": f"merged_into_{ckind}:{cslug}"})
        ckey = f"{ckind}:{cslug}"
        target = store.registry.setdefault(ckey, {
            "kind": ckind, "slug": cslug, "url": client.abs_url(m.group(1)), "status": "pending",
            "found_via": reg.get("found_via"), "first_seen": now_iso(),
        })
        if "rank" in reg and reg["rank"] < target.get("rank", 10**9):
            target["rank"] = reg["rank"]
        if target["status"] != "alias":
            return fetch_entry(client, store, target | {"key": ckey}, targets)
        return "alias"

    parser, required = (parse_noun, REQUIRED_NOUN_FIELDS) if kind == "noun" else (parse_verb, REQUIRED_VERB_FIELDS)
    rec = parser(resp.text, e["url"])
    reg["detail_level"] = rec["level"]
    reg["fetched_at"] = now_iso()
    if rec["level"] not in targets:
        reg["status"] = "excluded"
        if slug in store.records[kind]:  # level changed on the site → drop from output (history stays in Git)
            del store.records[kind][slug]
            store.changes.append({"key": key, "change": f"level_changed_to_{rec['level']}"})
        return "excluded"

    missing = [f for f in required if not rec.get(f)]
    if missing:
        archive_html(kind, slug, resp.text, sub="_parse_errors")
        reg["parse_error"] = missing
        print(f"  ! {key}: could not read {missing} — kept previous data, saved page to archive/_parse_errors/")
        return "parse_error"
    reg.pop("parse_error", None)
    reg["status"] = "included"

    rec = {"id": slug, **rec, "rank": reg.get("rank")}  # lower rank = more common; the app teaches these first
    h = content_hash(rec)
    old = store.records[kind].get(slug)
    if old and reg.get("hash") == h:
        return "unchanged"
    rec["first_seen"] = (old or {}).get("first_seen") or reg.get("first_seen") or now_iso()
    rec["updated_at"] = now_iso()
    rec["hash"] = h
    store.records[kind][slug] = rec
    reg["hash"] = h
    archive_html(kind, slug, resp.text)
    store.changes.append({"key": key, "change": "updated" if old else "added"})
    return "updated" if old else "added"


# --------------------------------------------------------------------------- main
def run(force: bool = False, limit: int | None = None, skip_discovery: bool = False) -> int:
    cfg = load_config()
    targets = set(cfg["target_levels"])
    interval = 0 if force else current_interval_days(cfg)
    deadline = time.time() + float(cfg["max_runtime_minutes"]) * 60
    store = Store()

    words = [] if skip_discovery else load_candidate_words(cfg)
    recheck = float(cfg["discovery"]["recheck_candidates_after_days"])
    discovery_pending = any(_days_since(store.candidates.get(w.lower(), {}).get("checked")) > recheck for w in words)
    due = due_entries(store, interval, targets)
    print(f"Target levels {sorted(targets)} · interval {interval} days · {len(due)} entries due · "
          f"discovery {'pending' if discovery_pending else 'up to date'}")
    if not due and not discovery_pending:
        print("Nothing due. Exiting.")
        return 0

    client = PoliteClient(cfg["http"], deadline)
    stats: dict[str, int] = {}
    stop_reason = "finished"
    total_secs = float(cfg["max_runtime_minutes"]) * 60
    fetch_share = float(cfg.get("fetch_time_share", 0.6))

    def fetch_phase(label: str, stop_at: float) -> None:
        due = due_entries(store, interval, targets)
        if limit:
            due = due[:limit]
        if not due:
            return
        print(f"{label}: fetching {len(due)} word pages")
        for i, e in enumerate(due, 1):
            if time.time() > stop_at:
                print(f"  {label}: time share used after {i - 1} pages; continuing with the next step")
                break
            result = fetch_entry(client, store, e, targets)
            stats[result] = stats.get(result, 0) + 1
            if i % 25 == 0:
                store.save_state()
                store.save_outputs(sorted(targets))  # keep data/ current even if the run is cut off
                print(f"  … {i}/{len(due)} {stats} · {client.summary()}")

    try:
        # 1) Words already found come first: they turn into data straight away.
        #    If discovery still has work, keep part of the time for it.
        first_stop = time.time() + (total_secs * fetch_share if discovery_pending else total_secs)
        fetch_phase("Step 1", first_stop)
        # 2) Look for more words with the remaining time.
        if discovery_pending:
            discover(client, store, words, cfg, targets, limit, stop_at=deadline - total_secs * 0.15)
            store.save_state()
            # 3) Fetch what discovery just found, with whatever time is left.
            fetch_phase("Step 3", deadline)
    except RateLimited as ex:
        stop_reason = f"paused: site is rate-limiting ({ex}); the next run continues"
    except OutOfTime:
        stop_reason = "paused: time budget used; the next run continues"
    finally:
        store.meta["last_run"] = now_iso()
        store.meta["last_run_result"] = stop_reason
        store.meta["last_run_stats"] = {"results": stats, **client.stats()}
        store.save_state()
        store.save_outputs(sorted(targets))

    print(f"Done ({stop_reason}). {client.summary()}. Results: {stats}. "
          f"Changes: {len(store.changes)}. Data version: {store.meta['data_version']}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-check every word now, ignoring the schedule")
    ap.add_argument("--limit", type=int, help="fetch at most N word pages (for testing)")
    ap.add_argument("--skip-discovery", action="store_true", help="only refresh words already known")
    a = ap.parse_args()
    raise SystemExit(run(force=a.force, limit=a.limit, skip_discovery=a.skip_discovery))


if __name__ == "__main__":
    main()
