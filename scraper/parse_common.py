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
        img.decompose()
        de_parts = []
        for s in el.strings:
            if en and s.strip() and s.strip() in en:
                break
            de_parts.append(s)
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
