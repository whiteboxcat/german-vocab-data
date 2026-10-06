"""HTML → clean text helpers that don't depend on the site's CSS class names."""
from __future__ import annotations

import copy
import re

from bs4 import BeautifulSoup, NavigableString, Tag

BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table",
    "section", "article", "header", "footer", "blockquote", "dd", "dt", "dl", "main", "nav",
}
LEVEL_RE = re.compile(r"\b([ABC][12])\b")
QUOTE_CHARS = str.maketrans({"„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "‚": "'", "‘": "'", "’": "'"})


def soupify(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    return soup


def to_text(node: Tag | BeautifulSoup) -> str:
    """Inline elements joined without spaces (so 'hab<i>en</i>' → 'haben'); block elements on their own lines."""
    node = copy.copy(node)
    for br in node.find_all("br"):
        br.replace_with("\n")
    for t in node.find_all(BLOCK_TAGS):
        t.insert_before("\n")
        t.insert_after("\n")
    for t in node.find_all(["td", "th"]):
        t.insert_after(" ")
    raw = node.get_text("")
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in raw.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def norm_quotes(s: str) -> str:
    return s.translate(QUOTE_CHARS)


def clean(s: str | None) -> str:
    if not s:
        return ""
    s = norm_quotes(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" \t\n·,;:")


def split_list(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"\s*,\s*", s) if x.strip()]


def text_after_img(img: Tag) -> str:
    """Collect the inline text that follows an <img> until the next image or block boundary."""
    parts: list[str] = []
    for sib in img.next_siblings:
        if isinstance(sib, NavigableString):
            parts.append(str(sib))
            continue
        if not isinstance(sib, Tag):
            continue
        if sib.name == "img" or sib.name == "br" or sib.name in BLOCK_TAGS:
            break
        if sib.find("img"):
            break
        parts.append(sib.get_text(""))
    return clean("".join(parts))


def find_heading(soup: BeautifulSoup, *titles: str) -> Tag | None:
    wanted = {t.lower() for t in titles}
    for h in soup.find_all(["h2", "h3"]):
        if clean(h.get_text("")).lower() in wanted:
            return h
    return None


def nodes_until_next_heading(start: Tag, level_names=("h2",)):
    """Yield elements that come after `start` in document order until the next heading of the same rank."""
    for el in start.find_all_next(True):
        if el.name in level_names:
            return
        yield el


def english_img(tag: Tag) -> bool:
    if tag.name != "img":
        return False
    alt = (tag.get("alt") or "").strip().lower()
    src = tag.get("src") or ""
    return alt in {"englisch", "english"} or (alt and src.endswith("/en.svg"))


def section_text(full_text: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    i = full_text.find(start_marker)
    if i < 0:
        return ""
    rest = full_text[i + len(start_marker):]
    end = len(rest)
    for m in end_markers:
        j = rest.find(m)
        if 0 <= j < end:
            end = j
    return rest[:end]
