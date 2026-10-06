"""Upload new/changed words to Supabase. Skips quietly if SUPABASE_URL / SUPABASE_SERVICE_KEY aren't set.

It remembers what it already uploaded (data/_state/supabase_uploaded.json), so the first run uploads
everything and later runs only send what changed. Run tables setup once: supabase/schema.sql.
"""
from __future__ import annotations

import os
import sys

import requests

from .config import DATA_DIR, STATE_DIR
from .store import now_iso, read_json, write_json

NOUN_COLS = ("lemma", "article", "plural", "level", "english")
VERB_COLS = ("infinitive", "level", "auxiliaries", "present_3sg", "praeteritum_3sg", "partizip2",
             "separable_prefix", "english")


def _headers(key: str) -> dict:
    h = {"apikey": key, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}
    if key.startswith("eyJ"):  # legacy JWT service_role key; new sb_secret_ keys only need the apikey header
        h["Authorization"] = f"Bearer {key}"
    return h


def _row(rec: dict, cols: tuple[str, ...]) -> dict:
    row = {"id": rec["id"], "hash": rec["hash"], "data": rec, "updated_at": rec.get("updated_at") or now_iso()}
    for c in cols:
        row[c] = rec.get(c)
    return row


def main() -> int:
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("Supabase secrets not set — skipping upload (data is still saved in the repo).")
        return 0
    uploaded_path = STATE_DIR / "supabase_uploaded.json"
    uploaded: dict[str, str] = read_json(uploaded_path, {})
    sess = requests.Session()
    sess.headers.update(_headers(key))
    total = 0
    for table, fname, cols in (("nouns", "nouns.json", NOUN_COLS), ("verbs", "verbs.json", VERB_COLS)):
        recs = read_json(DATA_DIR / fname, [])
        todo = [r for r in recs if uploaded.get(f"{table}:{r['id']}") != r["hash"]]
        for i in range(0, len(todo), 200):
            batch = todo[i:i + 200]
            r = sess.post(f"{url}/rest/v1/{table}?on_conflict=id", json=[_row(x, cols) for x in batch], timeout=60)
            if r.status_code >= 300:
                print(f"Upload to {table} failed: HTTP {r.status_code} {r.text[:300]}")
                write_json(uploaded_path, uploaded)
                return 1
            for x in batch:
                uploaded[f"{table}:{x['id']}"] = x["hash"]
        total += len(todo)
        # Remove rows that are no longer in the data (merged duplicates, level changes).
        current = {r["id"] for r in recs}
        stale = [k.split(":", 1)[1] for k in uploaded if k.startswith(f"{table}:") and k.split(":", 1)[1] not in current]
        for i in range(0, len(stale), 100):
            ids = ",".join('"' + x.replace('"', '') + '"' for x in stale[i:i + 100])
            r = sess.delete(f"{url}/rest/v1/{table}", params={"id": f"in.({ids})"}, timeout=60)
            if r.status_code >= 300:
                print(f"Deleting old rows from {table} failed: HTTP {r.status_code} {r.text[:300]}")
                write_json(uploaded_path, uploaded)
                return 1
        for x in stale:
            uploaded.pop(f"{table}:{x}", None)
        print(f"{table}: {len(todo)} uploaded, {len(stale)} removed ({len(recs)} total)")

    meta = read_json(DATA_DIR / "meta.json", {})
    r = sess.post(f"{url}/rest/v1/meta?on_conflict=key", json=[
        {"key": "data_version", "value": meta.get("data_version", 0)},
        {"key": "counts", "value": meta.get("counts", {})},
        {"key": "changed_at", "value": meta.get("changed_at")},
    ], timeout=30)
    if r.status_code >= 300:
        print(f"Updating meta failed: HTTP {r.status_code} {r.text[:300]}")
        return 1
    write_json(uploaded_path, uploaded)
    print(f"Supabase up to date ({total} rows sent, data version {meta.get('data_version')}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
