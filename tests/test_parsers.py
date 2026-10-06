"""Parser tests on saved pages. Run: python -m pytest -q"""
from pathlib import Path

from scraper.parse_noun import parse_noun
from scraper.parse_search import parse_search
from scraper.parse_verb import parse_verb

FX = Path(__file__).parent / "fixtures"


def load(name):
    return (FX / name).read_text(encoding="utf-8")


def test_verb_haben():
    v = parse_verb(load("verb_haben.html"), "https://www.verbformen.de/konjugation/haben.htm")
    assert v["infinitive"] == "haben"
    assert v["level"] == "A1"
    assert v["conjugation_class"] == "unregelmäßig"
    assert v["auxiliaries"] == ["haben"]
    assert v["present_3sg"] == "hat"
    assert v["praeteritum_3sg"] == "hatte"
    assert v["partizip2"] == "gehabt"
    assert v["separable"] is False
    assert v["english"][:2] == ["have", "possess"]
    assert v["indicative"]["Präsens"]["du"] == "hast"
    assert v["indicative"]["Perfekt"]["er"] == "hat gehabt"
    assert v["indicative"]["Futur II"]["wir"] == "werden gehabt haben"
    assert "Konjunktiv" not in str(v["indicative"].keys())
    assert v["imperative"][0] == "habe (du)"
    assert v["ipa"][0] == "/ˈhaːbən/"
    assert v["objects"] == ["Akk"]
    assert "zu+D" in v["prepositions"]
    assert v["examples"][0] == {"de": "Ich habe eine.", "en": "I have one."}
    assert v["examples"][1]["de"] == "Alle hatten Hunger."
    assert "infinitiv" in v["audio"]
    assert v["definitions_de"][0].startswith("eine Sache besitzen")


def test_verb_anrufen_separable():
    v = parse_verb(load("verb_anrufen.html"), "https://www.verbformen.de/konjugation/anrufen.htm")
    assert v["separable"] is True and v["separable_prefix"] == "an"
    assert v["praeteritum_3sg"] == "rief an"
    assert v["partizip2"] == "angerufen"
    assert v["objects"] == ["Akk"]
    assert v["prepositions"] == ["bei+D", "wegen+G"]
    assert v["indicative"]["Präsens"]["ich"] == "rufe an"
    assert v["examples"][0]["de"] == "Ich rufe dich morgen an."


def test_noun_tisch():
    n = parse_noun(load("noun_tisch.html"), "https://www.verbformen.de/deklination/substantive/Tisch.htm")
    assert n["lemma"] == "Tisch"
    assert n["article"] == "der" and n["gender"] == "m"
    assert n["plural"] == "Tische"
    assert n["genitive"] == "Tisch(e)s"
    assert n["level"] == "A1"
    assert n["english"] == ["table", "desk"]
    assert n["ipa"] == ["/tɪʃ/", "/ˈtɪʃəs/", "/ˈtɪʃə/"]
    assert n["examples"][0] == {"de": "Er sitzt am Tisch.", "en": "He's sitting at the table."}
    assert "grundform" in n["audio"] and "plural" in n["audio"]


def test_search_listing():
    rows = {r["slug"]: r for r in parse_search(load("search_tisch.html"))}
    assert set(rows) == {"Tisch", "tischen", "Tischbein", "Tischgespra3ch"}  # adjective + nav links ignored
    assert rows["Tisch"]["listing_level"] == "A1" and rows["Tisch"]["kind"] == "noun"
    assert rows["Tisch"]["headword_norm"] == "tisch"
    assert rows["tischen"]["listing_level"] is None and rows["tischen"]["kind"] == "verb"
    assert rows["Tischbein"]["listing_level"] == "C2"
