"""JSON state + output files + raw HTML archive. Everything is plain files so Git keeps full history."""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

from .config import ARCHIVE_DIR, DATA_DIR, STATE_DIR

VOLATILE_KEYS = {"fetched_at", "updated_at", "first_seen", "id", "key"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    tmp.replace(path)


LEVELS_DIR = DATA_DIR / "levels"
FILE_FOR = {"noun": "nouns.json", "verb": "verbs.json"}


def load_records(kind: str) -> list[dict]:
    """All saved words of one kind: data/levels/<LEVEL>/<kind>s.json, plus the old single file if present."""
    rows: dict[str, dict] = {}
    legacy = DATA_DIR / FILE_FOR[kind]
    for r in read_json(legacy, []):
        rows[r["id"]] = r
    for path in sorted(LEVELS_DIR.glob(f"*/{FILE_FOR[kind]}")):
        for r in read_json(path, []):
            rows[r["id"]] = r
    return list(rows.values())


def content_hash(record: dict) -> str:
    stable = {k: v for k, v in record.items() if k not in VOLATILE_KEYS}
    blob = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def archive_html(kind: str, slug: str, html: str, sub: str | None = None) -> Path:
    """Save a compressed copy of a page (raw pages are 30–40 KB each, so only some levels keep one)."""
    folder = ARCHIVE_DIR / (sub or (kind + "s"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.html.gz"
    with open(path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:  # mtime=0 → identical bytes for identical pages
            gz.write(html.encode("utf-8"))
    return path


class Store:
    def __init__(self):
        self.registry: dict[str, dict] = read_json(STATE_DIR / "registry.json", {})
        self.candidates: dict[str, dict] = read_json(STATE_DIR / "candidates.json", {})
        self.meta: dict = read_json(DATA_DIR / "meta.json", {"data_version": 0})
        self.records: dict[str, dict[str, dict]] = {
            "noun": {r["id"]: r for r in load_records("noun")},
            "verb": {r["id"]: r for r in load_records("verb")},
        }
        self.changes: list[dict] = []
        self._changes_written = 0      # how many of self.changes are already in the change log
        self._version_bumped = False   # data_version goes up once per run, however often we save

    def save_state(self) -> None:
        write_json(STATE_DIR / "registry.json", dict(sorted(self.registry.items())))
        write_json(STATE_DIR / "candidates.json", dict(sorted(self.candidates.items())))

    def save_outputs(self, target_levels: list[str]) -> None:
        def sort_key(r):
            return ((r.get("lemma") or r.get("infinitive") or r["id"]).lower(), r["id"])

        # One folder per level (data/levels/A1/nouns.json …) keeps files small and lets the app
        # download only the levels it needs.
        for kind, fname in FILE_FOR.items():
            for level in target_levels:
                rows = [r for r in self.records[kind].values() if r.get("level") == level]
                path = LEVELS_DIR / level / fname
                if rows or path.exists():
                    write_json(path, sorted(rows, key=sort_key))
            for path in LEVELS_DIR.glob(f"*/{fname}"):          # levels no longer targeted
                if path.parent.name not in target_levels:
                    path.unlink()
            legacy = DATA_DIR / fname                           # old single-file layout
            if legacy.exists():
                legacy.unlink()

        new = self.changes[self._changes_written:]
        if new:
            if not self._version_bumped:
                self.meta["data_version"] = int(self.meta.get("data_version", 0)) + 1
                self._version_bumped = True
            self.meta["changed_at"] = now_iso()
            day = dt.date.today().isoformat()
            log_path = DATA_DIR / "changes" / f"{day}.json"
            existing = read_json(log_path, [])
            write_json(log_path, existing + new)
            self._changes_written = len(self.changes)
        self.meta["target_levels"] = target_levels
        self.meta["counts_by_level"] = {
            level: {
                "nouns": sum(1 for r in self.records["noun"].values() if r.get("level") == level),
                "verbs": sum(1 for r in self.records["verb"].values() if r.get("level") == level),
            } for level in target_levels
        }
        self.meta["counts"] = {
            "nouns": sum(1 for r in self.records["noun"].values() if r.get("level") in target_levels),
            "verbs": sum(1 for r in self.records["verb"].values() if r.get("level") in target_levels),
        }
        self.meta["source"] = "Netzverb (https://www.verbformen.de/), CC BY-SA 4.0"
        write_json(DATA_DIR / "meta.json", self.meta)
