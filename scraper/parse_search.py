"""Parse a verbformen.de search result page (/suche/?w=<word>) into entries with their level.

Real layout (checked against a live page, Oct 2026): each result is a <div class="bTrf ...">.
Inside it the level is <span class="bZrt">A1</span>, the headword sits in a span with a large
font size, and the detail-page URL appears in onclick="Rahmen.a(event, '/konjugation/x.htm')"
handlers and in an icon-only <a href>. A generic fallback handles other layouts.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from .parse_common import BASE, level_in_text
from .textutil import clean, soupify

ENTRY_RE = re.compile(r"^/(konjugation|deklination/substantive)/([^/?#]+)\.htm$")
ONCLICK_URL_RE = re.compile(r"""Rahmen\.a\(\s*event\s*,\s*['"]([^'"]+)['"]""")


def slug_from_url(url: str) -> tuple[str, str] | None:
    """('noun'|'verb', slug) for a detail-page URL, or None."""
    m = ENTRY_RE.match(urlparse(urljoin(BASE, url)).path)
    if not m:
        return None
    kind = "verb" if m.group(1) == "konjugation" else "noun"
    return kind, m.group(2)


def normalize_headword(s: str) -> str:
    s = clean(s).replace("·", "").replace("|", "")
    s = re.sub(r"\(.*?\)|<.*?>", "", s)
    s = re.sub(r"^(der|die|das|sich)\s+", "", s.strip())
    s = re.sub(r",\s*(der|die|das|sich)?\s*$", "", s)
    return s.strip().lower()


def _urls_in(node) -> list[str]:
    urls = [a["href"] for a in node.find_all("a", href=True)]
    for el in node.find_all(onclick=True):
        urls += ONCLICK_URL_RE.findall(el["onclick"])
    return urls


def _parse_blocks(soup) -> list[dict]:
    out = []
    for block in soup.select("div.bTrf"):
        hit = next((slug_from_url(u) for u in _urls_in(block) if slug_from_url(u)), None)
        if not hit:
            continue  # adjectives, adverbs, ...
        kind, slug = hit
        lvl_el = block.select_one(".bZrt")
        level = level_in_text(lvl_el.get_text(" ")) if lvl_el else None
        head_el = block.find("span", style=re.compile(r"font-size:\s*1\.44em"))
        if head_el is None:
            head_el = block.find("q")
        headword = clean(head_el.get_text("")) if head_el else slug
        prefix = "/konjugation/" if kind == "verb" else "/deklination/substantive/"
        out.append({"kind": kind, "slug": slug, "url": urljoin(BASE, prefix + slug + ".htm"),
                    "headword": headword, "headword_norm": normalize_headword(headword),
                    "listing_level": level})
    return out


def _parse_generic(soup) -> list[dict]:
    """Fallback for other layouts: text links to detail pages, level found in the surrounding element."""
    links = []
    for a in soup.find_all("a", href=True):
        hit = slug_from_url(a["href"])
        if hit and clean(a.get_text("")):
            links.append((a, hit))
    link_ids = {id(a) for a, _ in links}

    def result_links_in(node) -> int:
        return sum(1 for x in node.find_all("a", href=True) if id(x) in link_ids)

    out = []
    for a, (kind, slug) in links:
        node = a
        while node.parent is not None and node.parent.name not in ("body", "html", "[document]") \
                and result_links_in(node.parent) == 1:
            node = node.parent
        out.append({
            "kind": kind, "slug": slug, "url": urljoin(BASE, a["href"]),
            "headword": clean(a.get_text("")), "headword_norm": normalize_headword(a.get_text("")),
            "listing_level": level_in_text(node.get_text(" ")),  # spaces so "A1" and the word don't merge
        })
    return out


def parse_search(html: str) -> list[dict]:
    soup = soupify(html)
    rows = _parse_blocks(soup) or _parse_generic(soup)
    seen, out = set(), []
    for r in rows:
        if (r["kind"], r["slug"]) not in seen:
            seen.add((r["kind"], r["slug"]))
            out.append(r)
    return out
