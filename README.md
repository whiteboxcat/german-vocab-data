# German vocab data (A1 → B2)

A self-updating German vocabulary dataset for a WaniKani-style learning app:
**nouns** with article, plural and English meaning, and **verbs** with type
(trennbar, Dativ/Akkusativ, prepositions), past forms (Präteritum, Partizip II,
haben/sein) and English meaning. Every word also has example sentences and
audio links. Source: [verbformen.de](https://www.verbformen.de/) (CC BY-SA 4.0, see `DATA_LICENSE.md`).

## How it works

```
GitHub Actions (daily check, 03:17 UTC)
  └─ canary: are haben / anrufen / Tisch still read correctly?  ── no → stop, email you
  └─ sync: anything due?  ── no → exit in seconds
        1. discovery: look up candidate words on verbformen search, keep those at target level
        2. fetch each word page slowly (~1 every 2.5–3.5 s), parse it
        3. compare a fingerprint (hash) with last time → only changed words are saved
  └─ upload new/changed rows to Supabase (if secrets are set)
  └─ commit data/ + archive/ to this repo  → full history, your permanent backup
```

- **Schedule:** every word is re-checked **weekly** until the date in
  `config.json` → `switch_to_monthly_on`, then **monthly**. Nothing to do by hand.
- **Big first crawl:** a run stops itself after ~5 h or if the site starts rate-limiting,
  saves progress, and the next daily run continues where it left off.
- **Where words come from:** `seeds/*.txt` (your own list) plus the 5,000 most frequent
  German words ([FrequencyWords](https://github.com/hermitdave/FrequencyWords)), each looked
  up on verbformen. Any result tagged with a target level is kept, so related words
  (e.g. *ausgehen* found via *gehen*) come along too.

## Files

| Path | What it is |
|---|---|
| `data/nouns.json`, `data/verbs.json` | The dataset your app uses |
| `data/meta.json` | `data_version` (goes up whenever anything changes), counts, last run |
| `data/changes/YYYY-MM-DD.json` | What was added / updated / removed on each day |
| `data/_state/` | Sync bookkeeping (which words exist, when checked, fingerprints) |
| `archive/nouns/`, `archive/verbs/` | Compressed raw page of every word (re-parse later without re-downloading) |
| `archive/_canary/`, `archive/_parse_errors/` | Pages that failed checks, for debugging |
| `config.json` | Levels, schedule, speed — the only file you normally edit |
| `seeds/my_words.txt` | Add your own words here |
| `supabase/schema.sql` | Database tables, run once in Supabase |

## Common changes

- **Add A2 (later B1, B2):** in `config.json` set `"target_levels": ["A1", "A2"]`. Words
  already seen at A2 get fetched on the next run; discovery picks up the rest. For B1/B2, also
  raise `frequency_top_n` (e.g. 12000).
- **Run now:** GitHub → *Actions* → *Sync vocabulary* → *Run workflow*.
  Tick *force* to re-check every word, or put `20` in *limit* for a quick test.
- **Change the schedule:** edit `sync_interval_days`, `switch_to_monthly_on`, `monthly_interval_days`.

## Supabase (optional)

1. Create a project at supabase.com (region: Singapore).
2. SQL Editor → paste `supabase/schema.sql` → Run.
3. In this repo: *Settings → Secrets and variables → Actions*, add
   `SUPABASE_URL` (Project URL) and `SUPABASE_SERVICE_KEY` (the secret / service_role key).
4. The next run uploads everything; after that only changes.

The app reads with the **public anon/publishable key** (read-only by the policies in the schema).
To stay fresh: compare `meta.data_version` with the version the app has, then fetch rows where
`updated_at` is newer than its last sync.

## Being a good guest

- One request at a time, 2.5–3.5 s apart, honest User-Agent, robots.txt respected.
- Audio is stored **as links only**; robots.txt asks bots not to download `.mp3` files.
  For an app with many users, generate your own audio (e.g. Azure/Google TTS) rather than
  streaming from their server.
- Credit "Netzverb (www.verbformen.de)" with a link inside the app (CC BY-SA 4.0).
- Consider emailing info@netzverb.de to say hello and ask about a data export.

## Local use

```bash
pip install -r requirements.txt
python -m pytest -q                # parser tests on saved pages
python -m scraper.canary           # live check of 3 known words
python -m scraper.sync --limit 20  # small real run
```
