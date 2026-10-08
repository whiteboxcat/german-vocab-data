"""Daily health check: compare what we found on verbformen, what's in data/, and what's in Supabase.

    python -m scraper.health --local-only   # before the sync: queue words that are missing locally
    python -m scraper.health                # after the upload: repair Supabase if needed, record the result

Three numbers per word type (nouns / verbs):
  source  – words verbformen tags with a target level that we have found so far
            (verbformen has no published total, so this grows while discovery runs)
  local   – words in data/levels/<LEVEL>/nouns.json and verbs.json
  db      – rows in the Supabase tables

Repairs:
  * a word found on the source but missing locally  → queued so the sync downloads it again
  * Supabase rows missing, outdated or extra          → uploaded / deleted right away (full reconcile)

Each day's result is written to data/health.json and to the Supabase table `sync_health`
(one row per day). That daily write also keeps a free Supabase project from pausing for inactivity.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import requests

from .config import DATA_DIR, STATE_DIR, load_config
from .store import load_records, now_iso, read_json, write_json
from .supabase_upload import NOUN_COLS, VERB_COLS, _headers, _row

TABLES = (("noun", "nouns", "nouns.json", NOUN_COLS), ("verb", "verbs", "verbs.json", VERB_COLS))
LIVE_STATUSES = {"pending", "included"}


# --------------------------------------------------------------------------- source & local
def source_counts(registry: dict, targets: set[str]) -> dict:
    """Words on verbformen at a target level that we know about, by type and download status."""
    out = {k: {"found": 0, "downloaded": 0, "waiting": 0, "unreadable": 0} for k, *_ in TABLES}
    for e in registry.values():
        if e["status"] not in LIVE_STATUSES:
            continue
        level = e.get("detail_level") or e.get("listing_level")
        if e["status"] == "pending" and level not in targets and level is not None:
            continue
        c = out[e["kind"]]
        c["found"] += 1
        if e.get("parse_error"):
            c["unreadable"] += 1
        elif e["status"] == "included":
            c["downloaded"] += 1
        else:
            c["waiting"] += 1
    return out


def check_local(registry: dict, fix: bool) -> dict:
    """Words marked as downloaded but missing from data/*.json get queued for download again."""
    report = {}
    for kind, _table, fname, _cols in TABLES:
        ids = {r["id"] for r in load_records(kind)}
        missing = [k for k, e in registry.items()
                   if e["kind"] == kind and e["status"] == "included" and e["slug"] not in ids]
        if fix:
            for k in missing:
                registry[k]["status"] = "pending"
                registry[k].pop("fetched_at", None)
                registry[k].pop("hash", None)
        report[kind] = {"local": len(ids), "missing_locally": len(missing), "requeued": len(missing) if fix else 0,
                        "examples": [registry[k]["slug"] for k in missing[:5]]}
    return report


# --------------------------------------------------------------------------- supabase
def _db_rows(sess: requests.Session, url: str, table: str) -> dict[str, str] | None:
    rows: dict[str, str] = {}
    page = 1000
    for offset in range(0, 10**7, page):
        r = sess.get(f"{url}/rest/v1/{table}", params={"select": "id,hash", "order": "id",
                                                      "limit": page, "offset": offset}, timeout=60)
        if r.status_code >= 300:
            print(f"  could not read {table}: HTTP {r.status_code} {r.text[:200]}")
            return None
        batch = r.json()
        rows.update({x["id"]: x["hash"] for x in batch})
        if len(batch) < page:
            return rows
    return rows


def reconcile_supabase(sess: requests.Session, url: str, repair: bool) -> dict:
    """Compare every row (id + fingerprint). Upload missing/outdated rows, delete extra ones."""
    uploaded_path = STATE_DIR / "supabase_uploaded.json"
    uploaded: dict[str, str] = read_json(uploaded_path, {})
    report = {}
    for kind, table, fname, cols in TABLES:
        local = {r["id"]: r for r in load_records(kind)}
        db = _db_rows(sess, url, table)
        if db is None:
            report[kind] = {"db": None, "error": f"could not read table {table}"}
            continue
        missing = [i for i in local if i not in db]
        outdated = [i for i in local if i in db and db[i] != local[i]["hash"]]
        extra = [i for i in db if i not in local]
        fixed = False
        if repair and (missing or outdated or extra):
            todo = [local[i] for i in missing + outdated]
            for n in range(0, len(todo), 200):
                batch = todo[n:n + 200]
                r = sess.post(f"{url}/rest/v1/{table}?on_conflict=id", json=[_row(x, cols) for x in batch],
                              headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, timeout=60)
                r.raise_for_status()
            for n in range(0, len(extra), 100):
                ids = ",".join('"' + x.replace('"', "") + '"' for x in extra[n:n + 100])
                r = sess.delete(f"{url}/rest/v1/{table}", params={"id": f"in.({ids})"}, timeout=60)
                r.raise_for_status()
            fixed = True
        # Keep the uploader's memory in line with what is really in the database now.
        for k in [k for k in uploaded if k.startswith(f"{table}:")]:
            del uploaded[k]
        state = {i: local[i]["hash"] for i in local} if fixed else \
                {i: h for i, h in db.items() if i in local and local[i]["hash"] == h}
        uploaded.update({f"{table}:{i}": h for i, h in state.items()})
        db_after = len(local) if fixed else len(db)
        report[kind] = {"db": db_after, "db_before": len(db), "missing_in_db": len(missing),
                        "outdated_in_db": len(outdated), "extra_in_db": len(extra), "repaired": fixed}
    write_json(uploaded_path, uploaded)
    return report


def record(sess: requests.Session | None, url: str, row: dict) -> str:
    if sess is None:
        return "skipped (no Supabase secrets)"
    r = sess.post(f"{url}/rest/v1/sync_health?on_conflict=check_date", json=[row],
                  headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, timeout=30)
    if r.status_code == 404 or "PGRST205" in r.text or "does not exist" in r.text:
        return "table sync_health not found: run supabase/health.sql once in the Supabase SQL Editor"
    if r.status_code >= 300:
        return f"HTTP {r.status_code} {r.text[:200]}"
    return "saved"


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-only", action="store_true", help="only check data/ against the source and queue repairs")
    a = ap.parse_args()

    cfg = load_config()
    hcfg = cfg.get("health", {})
    targets = set(cfg["target_levels"])
    registry_path = STATE_DIR / "registry.json"
    registry: dict = read_json(registry_path, {})

    local = check_local(registry, fix=bool(hcfg.get("refetch_missing_local_words", True)))
    if any(v["requeued"] for v in local.values()):
        write_json(registry_path, registry)
    for kind, v in local.items():
        if v["missing_locally"]:
            print(f"{kind}s: {v['missing_locally']} words missing from data/ (e.g. {v['examples']}) → queued for download")
    if a.local_only:
        print("Local check done.")
        return 0

    src = source_counts(registry, targets)
    meta = read_json(DATA_DIR / "meta.json", {})
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    sess = None
    db: dict = {}
    db_error = None
    if url and key:
        sess = requests.Session()
        sess.headers.update(_headers(key))
        try:
            db = reconcile_supabase(sess, url, repair=bool(hcfg.get("repair_supabase_on_mismatch", True)))
        except requests.RequestException as e:
            db_error = str(e)[:300]
            print(f"Supabase check failed: {db_error}")

    problems, actions = [], []
    for kind, *_ in TABLES:
        s, l, d = src[kind], local[kind], db.get(kind, {})
        if l["missing_locally"]:
            problems.append(f"{l['missing_locally']} {kind}s missing locally")
            actions.append(f"queued {l['requeued']} {kind}s for download")
        if d.get("missing_in_db") or d.get("outdated_in_db") or d.get("extra_in_db"):
            problems.append(f"Supabase {kind}s: {d['missing_in_db']} missing, {d['outdated_in_db']} outdated, "
                            f"{d['extra_in_db']} extra")
            if d.get("repaired"):
                actions.append(f"repaired Supabase {kind}s")
        if d.get("error"):
            problems.append(d["error"])
    if db_error:
        problems.append(f"Supabase unreachable: {db_error}")

    waiting = src["noun"]["waiting"] + src["verb"]["waiting"]
    if problems and not actions:
        status = "problem"
    elif problems:
        status = "repaired"
    elif waiting:
        status = "downloading"   # healthy; the crawl hasn't fetched every found word yet
    else:
        status = "ok"

    run_stats = meta.get("last_run_stats", {})
    row = {
        "check_date": dt.date.today().isoformat(),
        "checked_at": now_iso(),
        "status": status,
        "target_levels": sorted(targets),
        "source_nouns": src["noun"]["found"], "source_verbs": src["verb"]["found"],
        "downloaded_nouns": src["noun"]["downloaded"], "downloaded_verbs": src["verb"]["downloaded"],
        "waiting_nouns": src["noun"]["waiting"], "waiting_verbs": src["verb"]["waiting"],
        "unreadable": src["noun"]["unreadable"] + src["verb"]["unreadable"],
        "local_nouns": local["noun"]["local"], "local_verbs": local["verb"]["local"],
        "db_nouns": db.get("noun", {}).get("db"), "db_verbs": db.get("verb", {}).get("db"),
        "data_version": meta.get("data_version", 0),
        "candidates_checked": len(read_json(STATE_DIR / "candidates.json", {})),
        "last_sync_result": meta.get("last_run_result"),
        "requests": run_stats.get("requests"), "rate_limited": run_stats.get("rate_limited"),
        "problems": problems, "actions": actions,
    }
    row["saved_to_supabase"] = record(sess, url, row)

    history = read_json(DATA_DIR / "health.json", {}).get("history", [])
    history = [h for h in history if h.get("check_date") != row["check_date"]] + [row]
    write_json(DATA_DIR / "health.json", {"latest": row, "history": history[-400:]})

    print(f"\nHealth {row['check_date']}: {status.upper()}")
    print(f"  nouns  source {row['source_nouns']:>5} · downloaded {row['downloaded_nouns']:>5} · "
          f"local {row['local_nouns']:>5} · Supabase {row['db_nouns']}")
    print(f"  verbs  source {row['source_verbs']:>5} · downloaded {row['downloaded_verbs']:>5} · "
          f"local {row['local_verbs']:>5} · Supabase {row['db_verbs']}")
    print(f"  still to download: {waiting} · search words checked: {row['candidates_checked']}")
    for p in problems:
        print(f"  problem: {p}")
    for act in actions:
        print(f"  fixed:   {act}")
    print(f"  Supabase health row: {row['saved_to_supabase']}")
    return 1 if status == "problem" else 0


if __name__ == "__main__":
    sys.exit(main())
