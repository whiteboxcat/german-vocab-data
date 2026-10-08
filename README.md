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
        1. fetch word pages already found (first ~60% of the time), parse them
        2. discovery: look up more candidate words on verbformen search
        3. fetch what discovery just found
        (one request every 4–5 s; slows down automatically if the site says "too many requests")
        only words whose fingerprint (hash) changed are saved
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
| `data/levels/<LEVEL>/nouns.json`, `verbs.json` | The dataset your app uses, one folder per level (A1 … C2) |
| `data/meta.json` | `data_version` (goes up whenever anything changes), counts, last run |
| `data/changes/YYYY-MM-DD.json` | What was added / updated / removed on each day |
| `data/_state/` | Sync bookkeeping (which words exist, when checked, fingerprints) |
| `archive/nouns/`, `archive/verbs/` | Compressed raw page of every word (re-parse later without re-downloading) |
| `archive/_canary/`, `archive/_parse_errors/` | Pages that failed checks, for debugging |
| `config.json` | Levels, schedule, speed — the only file you normally edit |
| `seeds/my_words.txt` | Add your own words here |
| `supabase/schema.sql` | Database tables, run once in Supabase |

## Daily health check

Every day, even when no words are due, the job compares three numbers for nouns and verbs:
**source** (target-level words found on verbformen so far; the site publishes no total, so this
grows while discovery runs), **local** (`data/*.json`) and **Supabase** (rows in the tables).
Supabase is compared row by row using each word's fingerprint.

- Missing, outdated or extra Supabase rows → repaired straight away.
- Words missing from `data/` → queued and downloaded again by the sync.
- The result goes to `data/health.json` and to the Supabase table `sync_health`
  (one row per day; run `supabase/health.sql` once to create it). That daily write also keeps
  a free Supabase project from pausing for inactivity.

Status values: `ok`, `downloading` (healthy, still fetching found words), `repaired`, `problem`.

## Common changes

- **Levels:** `target_levels` is A1–C2. verbformen tags most rare words C2, so C1/C2 cover the
  words found among the `frequency_top_n` (20,000) most common German words, not the whole dictionary.
  `archive_levels` (A1–B2) decides which levels keep a raw page copy; pages are 30–40 KB each.
- **Speed:** about 12 requests a minute (`delay_seconds` 4.5 + up to 1 s jitter). verbformen refused
  requests at around 20 a minute, so don't go faster. While the big crawl runs, the job runs twice a
  day (second `cron` line in the workflow); remove that line when the crawl is finished.
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
