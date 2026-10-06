"""Parse a verbformen.de verb page (/konjugation/<verb>.htm)."""
from __future__ import annotations

import re

from .parse_common import (
    parse_audio, parse_definition_lines, parse_english, parse_examples, parse_ipa, parse_level,
)
from .textutil import clean, norm_quotes, section_text, soupify, to_text

PERSONS = ("ich", "du", "er", "wir", "ihr", "sie")
TENSES = ("Präsens", "Präteritum", "Perfekt", "Plusquamperfekt", "Futur I", "Futur II")
SEPARABLE_PREFIXES = (
    "zurück", "zusammen", "weiter", "wieder", "vorbei", "vorher", "heraus", "herein", "herunter", "hinaus",
    "hinein", "hinunter", "fest", "fern", "frei", "statt", "teil", "kennen", "spazieren", "kaputt",
    "weg", "vor", "nach", "mit", "ab", "an", "auf", "aus", "bei", "ein", "her", "hin", "los", "zu", "um", "dar",
    "durch", "über", "unter", "wider", "da", "fort", "empor", "entgegen", "fehl", "hoch", "nieder", "voran",
    "voraus", "vorüber", "zurecht", "zwischen",
)


def _conjugation_block(block: str) -> dict[str, dict[str, str]]:
    """Parse lines like 'Präsens:\\nich habe, du hast, er hat, ...' into {tense: {person: form}}."""
    out: dict[str, dict[str, str]] = {}
    lines = block.splitlines()
    for i, ln in enumerate(lines):
        name = ln.strip().rstrip(":")
        if name in TENSES and ln.strip().endswith(":") and i + 1 < len(lines):
            forms: dict[str, str] = {}
            for part in re.split(r",\s*", lines[i + 1]):
                bits = part.strip().split(" ", 1)
                if len(bits) == 2 and bits[0] in PERSONS:
                    forms[bits[0]] = bits[1].strip()
            if forms and name not in out:
                out[name] = forms
    return out


def parse_verb(html: str, url: str) -> dict:
    soup = soupify(html)
    text = norm_quotes(to_text(soup))
    flat = re.sub(r"\s+", " ", text)

    infinitive = None
    h1 = soup.find("h1")
    if h1:
        m = re.search(r"Verbs\s+(.+)$", clean(h1.get_text("")))
        if m:
            infinitive = m.group(1)

    present_3sg = preteritum = perfect = None
    m = re.search(r'Stammformen von "([^"]+)" sind "([^"]+)", "([^"]+)" und "([^"]+)"', flat)
    if m:
        infinitive = infinitive or m.group(1)
        present_3sg, preteritum, perfect = m.group(2), m.group(3), m.group(4)

    aux_raw = None
    m = re.search(r"Als Hilfsverb von .+? wird (.+?) verwendet", flat)
    if m:
        aux_raw = clean(m.group(1).replace('"', ""))
    auxiliaries = [a for a in ("haben", "sein") if aux_raw and re.search(rf"\b{a}\b", aux_raw)]
    if not auxiliaries and perfect:
        first = perfect.split(" ", 1)[0]
        auxiliaries = ["sein"] if first in {"ist", "sind"} else ["haben"] if first in {"hat", "haben"} else []

    partizip2 = perfect.split(" ", 1)[1] if perfect and " " in perfect else None

    m = re.search(r"erfolgt\s+(unregelmäßig|regelmäßig|gemischt)", flat)
    conj_class = m.group(1) if m else None
    if not conj_class:
        m = re.search(r"^[ABC][12]\s*·\s*(unregelmäßig|regelmäßig|gemischt)", text, re.M)
        conj_class = m.group(1) if m else None

    separable_prefix = None
    if present_3sg and " " in present_3sg and infinitive:
        tail = present_3sg.rsplit(" ", 1)[1]
        base = infinitive.removeprefix("sich ").strip()
        if base.startswith(tail) and tail in SEPARABLE_PREFIXES:
            separable_prefix = tail

    # Usage pattern line, e.g. "(sich+A, Akk., zu+D, vor+D, ...)"
    pattern_raw = None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("(") and s.endswith(")") and re.search(r"\+[ADG]\b|Akk\.|Dat\.|Gen\.|\bsich\b", s):
            pattern_raw = s[1:-1]
            break
    pattern_tokens = [t.strip() for t in pattern_raw.split(",")] if pattern_raw else []
    objects = sorted({{"Akk.": "Akk", "Dat.": "Dat", "Gen.": "Gen"}[t] for t in pattern_tokens if t in {"Akk.", "Dat.", "Gen."}})
    prepositions = [t for t in pattern_tokens if re.fullmatch(r"[a-zäöüß]+\+[ADG]", t) and not t.startswith("sich")]
    reflexive_use = any(t.startswith("sich") for t in pattern_tokens) or (infinitive or "").startswith("sich ")

    indicative = _conjugation_block(section_text(text, "Indikativ sind:", ("Wie ist der Konjunktiv", "Konjunktiv von")))
    if not indicative:
        indicative = _conjugation_block(text)

    imperative = []
    imp = section_text(text, "Imperativ von", ("Welche infiniten", "\n###"))
    m = re.search(r"Präsens:\s*\n(.+)", imp)
    if m:
        imperative = [x.strip() for x in m.group(1).split(",") if x.strip()]

    return {
        "type": "verb",
        "infinitive": infinitive,
        "level": parse_level(text),
        "conjugation_class": conj_class,
        "auxiliaries": auxiliaries,
        "auxiliary_raw": aux_raw,
        "present_3sg": present_3sg,
        "praeteritum_3sg": preteritum,
        "perfekt_3sg": perfect,
        "partizip2": partizip2,
        "separable_prefix": separable_prefix,
        "separable": separable_prefix is not None,
        "reflexive_use": reflexive_use,
        "objects": objects,
        "prepositions": prepositions,
        "usage_pattern_raw": pattern_raw,
        "indicative": indicative,
        "imperative": imperative,
        "english": parse_english(soup),
        "definitions_de": parse_definition_lines(soup),
        "ipa": parse_ipa(text),
        "examples": parse_examples(soup),
        "audio": parse_audio(soup),
        "source_url": url,
    }


# "level" is not required: many rare words have no level on the site and are simply excluded.
REQUIRED_VERB_FIELDS = ("infinitive", "partizip2", "auxiliaries", "english")
