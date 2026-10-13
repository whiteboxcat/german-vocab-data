"""Fields shared by noun and verb pages: level, English meanings, IPA, examples, audio links."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .textutil import (
    LEVEL_RE, clean, english_img, find_heading, nodes_until_next_heading, norm_quotes, split_list,
    text_after_img,
)

BASE = "https://www.verbformen.de/"

# Bump this whenever a parser fix should be applied to words already saved (see scraper/reparse.py).
PARSER_VERSION = 3   # 2: whole example sentences · 3: synonyms


def parse_level(text: str) -> str | None:
    t = norm_quotes(text)
    m = re.search(r"auf\s+([ABC][12])\s*-\s*Niveau", t)
    if m:
        return m.group(1)
    m = re.search(r"^\s*([ABC][12])\s*·", t, re.M)  # header tag e.g. "A1 · Substantiv · ..."
    return m.group(1) if m else None


def parse_english(soup: BeautifulSoup) -> list[str]:
    """English meanings. Prefer the 'Übersetzungen' section, fall back to the first English flag on the page."""
    candidates = []
    h = find_heading(soup, "Übersetzungen")
    if h:
        for el in nodes_until_next_heading(h):
            if english_img(el):
                candidates.append(text_after_img(el))
                break
    for img in soup.find_all("img"):
        if english_img(img) and not img.find_parent("a"):
            candidates.append(text_after_img(img))
            break
    for c in candidates:
        if c and len(c) < 400:
            return _dedupe(split_list(c))
    return []


def parse_ipa(text: str) -> list[str]:
    head = text.split("\nBeispiele", 1)[0]
    out = []
    for ln in head.splitlines():
        ln = ln.strip()
        if re.fullmatch(r"/[^/\s][^/]{0,40}/", ln) and not ln.startswith("/user"):
            out.append(ln)
    return _dedupe(out)[:6]


def parse_examples(soup: BeautifulSoup, limit: int = 6) -> list[dict]:
    h = find_heading(soup, "Beispiele")
    if not h:
        return []
    out: list[dict] = []
    for el in nodes_until_next_heading(h):
        if el.name != "li":
            continue
        img = next((i for i in el.find_all("img") if english_img(i)), None)
        for a in el.find_all("a"):
            if "satzapp" in (a.get("href") or "") and not a.find("img"):
                a.decompose()
        if img is None:
            continue
        en = text_after_img(img)
        # German = all text in the item that comes before the English flag (or the line break before it).
        # Don't match by content: the highlighted verb is split into pieces like "w", "ä", "sch".
        de_parts = []
        for node in el.descendants:
            if node is img or getattr(node, "name", None) == "br":
                break
            if isinstance(node, str) and not getattr(node, "name", None):
                if not any(p.name == "a" for p in node.parents if p is not el and getattr(p, "name", None)):
                    de_parts.append(str(node))
        de = clean("".join(de_parts).replace('"', ""))
        de = re.sub(r"\s+([.,!?;:])", r"\1", de)
        if de and en:
            out.append({"de": de, "en": en})
        if len(out) >= limit:
            break
    return out


def parse_audio(soup: BeautifulSoup) -> dict[str, str]:
    """Links to the site's own audio files. We store links only; robots.txt asks bots not to fetch .mp3."""
    audio: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().endswith(".mp3"):
            continue
        url = urljoin(BASE, href)
        m = re.search(r"/(konjugation|deklination/substantive)/(.+)/[^/]+\.mp3$", url)
        key = m.group(2).replace("/", "_") if m else url.rsplit("/", 1)[-1]
        audio.setdefault(key, url)
    return audio


def parse_definition_lines(soup: BeautifulSoup, limit: int = 4) -> list[str]:
    h = find_heading(soup, "Bedeutungen")
    if not h:
        return []
    out = []
    for el in nodes_until_next_heading(h):
        if el.name == "li":
            t = clean(el.get_text(""))
            if t and not t.endswith("..."):
                out.append(t)
            elif t:
                out.append(t.rstrip(". "))
        if len(out) >= limit:
            break
    return out


def _dedupe(items):
    seen, out = set(), []
    for x in items:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def level_in_text(s: str) -> str | None:
    m = LEVEL_RE.search(s)
    return m.group(1) if m else None


def parse_synonyms(soup: BeautifulSoup, headword: str, kind: str, limit: int = 8) -> list[str]:
    """Synonyms from the 'Bedeutungen' list (OpenThesaurus, CC BY-SA 4.0).

    Each line there is a definition followed by synonyms, all comma-separated, e.g.
    "mit Wasser … reinigen, den Schmutz entfernen, …, reinigen, sauber machen".
    Synonyms are the short items (one word, or two like "sauber machen"); longer items are
    the definition. Nouns keep capitalised single words, verbs keep lowercase verb forms.
    """
    h = find_heading(soup, "Bedeutungen")
    if not h:
        return []
    own = headword.lower()
    out: list[str] = []
    for el in nodes_until_next_heading(h):
        if el.name != "li":
            continue
        line = clean(el.get_text(""))
        line = re.sub(r"\[[^\]]*\]", "", line)          # "[Möbel]", "[Fachsprache]" tags
        for item in (x.strip(" .") for x in line.split(",")):
            item = item.split("/")[0].strip()                 # "antelefonieren/antelephonieren"
            words = item.split()
            if not words or len(words) > 2 or item.lower() == own or "(" in item or "~" in item:
                continue
            if any(w.lower().startswith(("jemand", "etwas", "sich", "einer", "einem", "einen")) for w in words):
                continue                                       # pieces of a definition, not synonyms
            if kind == "noun":
                ok = len(words) == 1 and item[:1].isupper() and item.replace("-", "").isalpha()
            else:
                last_ok = re.search(r"(e?n|ern|eln)$", words[-1]) is not None
                light = {"machen", "sein", "werden", "haben", "lassen", "gehen", "kommen", "nehmen",
                         "geben", "bringen", "halten", "stellen", "setzen", "legen"}
                ok = item[:1].islower() and last_ok and (len(words) == 1 or words[-1] in light)
            if ok and item not in out:
                out.append(item)
            if len(out) >= limit:
                return out
    return out
