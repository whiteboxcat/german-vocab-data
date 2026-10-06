"""Parse a verbformen.de search result page (/suche/?w=<word>) into entries with their level."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from .parse_common import BASE, level_in_text
from .textutil import clean, soupify

ENTRY_RE = re.compile(r"^/(konjugation|deklination/substantive)/([^/?#]+)\.htm$")


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
    s = re.sub(r",\s*(der|die|das)$", "", s)
    return s.strip().lower()


def parse_search(html: str) -> list[dict]:
    soup = soupify(html)
    links = []
    for a in soup.find_all("a", href=True):
        hit = slug_from_url(a["href"])
        if hit and clean(a.get_text("")):
            links.append((a, hit))
    link_ids = {id(a) for a, _ in links}

    def result_links_in(node) -> int:
        return sum(1 for x in node.find_all("a", href=True) if id(x) in link_ids)

    out, seen = [], set()
    for a, (kind, slug) in links:
        if (kind, slug) in seen:
            continue
        seen.add((kind, slug))
        node = a
        while node.parent is not None and node.parent.name not in ("body", "html", "[document]") \
                and result_links_in(node.parent) == 1:
            node = node.parent
        container_text = node.get_text(" ")  # spaces between tags so "A1" and the word don't merge
        out.append({
            "kind": kind,
            "slug": slug,
            "url": urljoin(BASE, a["href"]),
            "headword": clean(a.get_text("")),
            "headword_norm": normalize_headword(a.get_text("")),
            "listing_level": level_in_text(container_text),
        })
    return out
