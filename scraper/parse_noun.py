"""Parse a verbformen.de noun page (/deklination/substantive/<Word>.htm)."""
from __future__ import annotations

import re

from .parse_common import (
    parse_audio, parse_definition_lines, parse_english, parse_examples, parse_ipa, parse_level,
)
from .textutil import clean, norm_quotes, soupify, to_text

GENDER = {"maskulin": "m", "feminin": "f", "neutral": "n", "neutrum": "n"}
ARTICLE_FOR = {"m": "der", "f": "die", "n": "das"}


def parse_noun(html: str, url: str) -> dict:
    soup = soupify(html)
    text = norm_quotes(to_text(soup))
    flat = re.sub(r"\s+", " ", text)

    lemma = None
    h1 = soup.find("h1")
    if h1:
        m = re.search(r"Substantivs\s+(.+?)\s+mit\s+Plural", clean(h1.get_text("")))
        if m:
            lemma = m.group(1)

    articles = re.findall(r'Der Artikel lautet "(der|die|das) ([^"]+)"', flat)
    genders = []
    for g in re.findall(r'" ist (maskulin|feminin|neutral|neutrum)', flat):
        genders.append(GENDER[g])
    if not genders:
        m = re.search(r"Substantiv\s*·\s*(maskulin|feminin|neutral)", flat)
        if m:
            genders.append(GENDER[m.group(1)])
    article_list = list(dict.fromkeys(a for a, _ in articles)) or [ARTICLE_FOR[g] for g in dict.fromkeys(genders)]
    if not lemma and articles:
        lemma = articles[0][1]

    plural = None
    m = re.search(r'Nominativ Plural "([^"]+)"', flat)
    if m:
        plural = m.group(1)
    else:
        m = re.search(r"^Nom\.\s+die\s+(\S.*)$", text.split("Plural", 1)[-1], re.M)
        if m and "-" not in m.group(1):
            plural = clean(m.group(1))
    genitive = None
    m = re.search(r'Genitiv Singular "([^"]+)"', flat)
    if m:
        genitive = m.group(1)

    singular_only = plural is None and bool(re.search(r"nur (im )?Singular|kein Plural|Singularetantum", flat))
    plural_only = bool(re.search(r"nur (im )?Plural|Pluraletantum", flat))

    return {
        "type": "noun",
        "lemma": lemma,
        "article": article_list[0] if article_list else None,
        "articles": article_list,
        "gender": genders[0] if genders else None,
        "plural": plural,
        "genitive": genitive,
        "singular_only": singular_only,
        "plural_only": plural_only,
        "level": parse_level(text),
        "english": parse_english(soup),
        "definitions_de": parse_definition_lines(soup),
        "ipa": parse_ipa(text),
        "examples": parse_examples(soup),
        "audio": parse_audio(soup),
        "source_url": url,
    }


# "level" is not required: many rare words have no level on the site and are simply excluded.
REQUIRED_NOUN_FIELDS = ("lemma", "article", "english")
