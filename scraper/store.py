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


def content_hash(record: dict) -> str:
    stable = {k: v for k, v in record.items() if k not in VOLATILE_KEYS}
    blob = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def archive_html(kind: str, slug: str, html: str, sub: str | None = None) -> Path:
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
            "noun": {r["id"]: r for r in read_json(DATA_DIR / "nouns.json", [])},
            "verb": {r["id"]: r for r in read_json(DATA_DIR / "verbs.json", [])},
        }
        self.changes: list[dict] = []

    def save_state(self) -> None:
        write_json(STATE_DIR / "registry.json", dict(sorted(self.registry.items())))
        write_json(STATE_DIR / "candidates.json", dict(sorted(self.candidates.items())))

    def save_outputs(self, target_levels: list[str]) -> None:
        def sort_key(r):
            return ((r.get("lemma") or r.get("infinitive") or r["id"]).lower(), r["id"])

        for kind, fname in (("noun", "nouns.json"), ("verb", "verbs.json")):
            rows = [r for r in self.records[kind].values() if r.get("level") in target_levels]
            write_json(DATA_DIR / fname, sorted(rows, key=sort_key))

        if self.changes:
            self.meta["data_version"] = int(self.meta.get("data_version", 0)) + 1
            self.meta["changed_at"] = now_iso()
            day = dt.date.today().isoformat()
            log_path = DATA_DIR / "changes" / f"{day}.json"
            existing = read_json(log_path, [])
            write_json(log_path, existing + self.changes)
        self.meta["target_levels"] = target_levels
        self.meta["counts"] = {
            "nouns": sum(1 for r in self.records["noun"].values() if r.get("level") in target_levels),
            "verbs": sum(1 for r in self.records["verb"].values() if r.get("level") in target_levels),
        }
        self.meta["source"] = "Netzverb (https://www.verbformen.de/), CC BY-SA 4.0"
        write_json(DATA_DIR / "meta.json", self.meta)
