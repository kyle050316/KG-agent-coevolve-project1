"""A tiny KB in the official KQA Pro kb.json format, KILT-format pages and KQA Pro-style questions.

Relations are stored on both endpoints (forward at the subject, backward mirror at the object),
as in the released KQA Pro KB. ``predicate`` is used on purpose for some relations to exercise
normalization of the two field names seen in the wild.
"""

from __future__ import annotations

import copy

CONCEPTS = {
    "Q5": {"name": "human", "instanceOf": []},
    "Q515": {"name": "city", "instanceOf": ["Q2221906"]},
    "Q2221906": {"name": "geographic location", "instanceOf": []},
    "Q6256": {"name": "country", "instanceOf": ["Q2221906"]},
    "Q618779": {"name": "award", "instanceOf": []},
    "Q7278": {"name": "political party", "instanceOf": []},
    "Q3918": {"name": "university", "instanceOf": []},
    "Q11424": {"name": "film", "instanceOf": []},
}


def _d(v):
    return {"type": "date", "value": v}


def _y(v):
    return {"type": "year", "value": v}


def _q(v, unit="1"):
    return {"type": "quantity", "value": v, "unit": unit}


def _s(v):
    return {"type": "string", "value": v}


ENT = {
    "Q76": ("Barack Obama", ["Q5"], [("date of birth", _d("1961-08-04"), {}), ("sex or gender", _s("male"), {})]),
    "Q13133": ("Michelle Obama", ["Q5"], [("date of birth", _d("1964-01-17"), {}), ("sex or gender", _s("female"), {})]),
    "Q15070044": ("Malia Obama", ["Q5"], [("date of birth", _d("1998-07-04"), {})]),
    "Q22686": ("Donald Trump", ["Q5"], [("date of birth", _d("1946-06-14"), {}), ("sex or gender", _s("male"), {})]),
    "Q432473": ("Melania Trump", ["Q5"], [("date of birth", _d("1970-04-26"), {})]),
    "Q6279": ("Joe Biden", ["Q5"], [("date of birth", _d("1942-11-20"), {})]),
    "Q18094": ("Honolulu", ["Q515"], [("population", _q(345064), {"point in time": [_y(2010)]})]),
    "Q1297": ("Chicago", ["Q515"], [("population", _q(2695598), {"point in time": [_y(2010)]})]),
    "Q999001": ("Chicago", ["Q11424"], [("publication date", _d("2002-12-27"), {})]),
    "Q60": ("New York City", ["Q515"], [("population", _q(8175133), {"point in time": [_y(2010)]})]),
    "Q30": ("United States of America", ["Q6256"], [("inception", _y(1776), {})]),
    "Q35637": ("Nobel Peace Prize", ["Q618779"], [("inception", _y(1901), {})]),
    "Q29552": ("Democratic Party", ["Q7278"], [("inception", _y(1828), {})]),
    "Q29468": ("Republican Party", ["Q7278"], [("inception", _y(1854), {})]),
    "Q13371": ("Harvard University", ["Q3918"], [("inception", _y(1636), {})]),
    "Q49088": ("Columbia University", ["Q3918"], [("inception", _y(1754), {})]),
}

RELS = [  # (subject, relation, object, qualifiers)
    ("Q76", "spouse", "Q13133", {"start time": [_d("1992-10-03")]}),
    ("Q13133", "spouse", "Q76", {"start time": [_d("1992-10-03")]}),
    ("Q76", "place of birth", "Q18094", {}),
    ("Q76", "award received", "Q35637", {"point in time": [_y(2009)]}),
    ("Q76", "member of political party", "Q29552", {}),
    ("Q76", "educated at", "Q13371", {}),
    ("Q76", "educated at", "Q49088", {}),
    ("Q76", "child", "Q15070044", {}),
    ("Q13133", "child", "Q15070044", {}),
    ("Q15070044", "father", "Q76", {}),
    ("Q15070044", "mother", "Q13133", {}),
    ("Q13133", "place of birth", "Q1297", {}),
    ("Q13133", "educated at", "Q13371", {}),
    ("Q22686", "spouse", "Q432473", {"start time": [_d("2005-01-22")]}),
    ("Q432473", "spouse", "Q22686", {"start time": [_d("2005-01-22")]}),
    ("Q22686", "place of birth", "Q60", {}),
    ("Q22686", "member of political party", "Q29468", {}),
    ("Q6279", "member of political party", "Q29552", {}),
    ("Q6279", "place of birth", "Q60", {}),
    ("Q76", "country of citizenship", "Q30", {}),
    ("Q13133", "country of citizenship", "Q30", {}),
    ("Q22686", "country of citizenship", "Q30", {}),
    ("Q18094", "country", "Q30", {}),
    ("Q1297", "country", "Q30", {}),
    ("Q60", "country", "Q30", {}),
    ("Q13371", "country", "Q30", {}),
]


def make_kb(mirrors: bool = True) -> dict:
    ents = {}
    for eid, (name, inst, attrs) in ENT.items():
        ents[eid] = {
            "name": name,
            "instanceOf": list(inst),
            "attributes": [{"key": k, "value": copy.deepcopy(v), "qualifiers": copy.deepcopy(q)} for k, v, q in attrs],
            "relations": [],
        }
    for i, (s, r, o, q) in enumerate(RELS):
        rk = "predicate" if i % 3 == 0 else "relation"
        ents[s]["relations"].append({rk: r, "direction": "forward", "object": o, "qualifiers": copy.deepcopy(q)})
        if mirrors:
            ents[o]["relations"].append({"relation": r, "direction": "backward", "object": s, "qualifiers": copy.deepcopy(q)})
    return {"concepts": copy.deepcopy(CONCEPTS), "entities": ents}


def _anchor(text: str, mention: str, para: int, title: str, wid: str) -> dict:
    start = text.index(mention)
    return {"paragraph_id": para, "start": start, "end": start + len(mention), "text": mention,
            "href": title.replace(" ", "%20"), "wikipedia_title": title, "wikipedia_id": wid}


PAGES = {
    # qid: (wikipedia_id, title, paragraphs, [(paragraph_idx, mention, target_title, target_wid)])
    "Q76": ("534366", "Barack Obama", [
        "Barack Obama",
        "Barack Hussein Obama II (born August 4, 1961) is an American politician who served as the 44th president of the United States. "
        "Obama was born in Honolulu, Hawaii. He graduated from Columbia University and Harvard Law School.",
        "Obama married Michelle Robinson in 1992. Obama was awarded the 2009 Nobel Peace Prize. "
        "He is a member of the Democratic Party.",
    ], [(1, "Honolulu", "Honolulu", "13886"), (1, "Columbia University", "Columbia University", "6310"),
        (1, "Harvard Law School", "Harvard University", "18426501"), (2, "Michelle Robinson", "Michelle Obama", "2445628"),
        (2, "Nobel Peace Prize", "Nobel Peace Prize", "21201"), (2, "Democratic Party", "Democratic Party (United States)", "5043544")]),
    "Q13133": ("2445628", "Michelle Obama", [
        "Michelle Obama",
        "Michelle LaVaughn Robinson Obama (born January 17, 1964) is an American attorney and author. "
        "She was raised on the South Side of Chicago and graduated from Harvard Law School.",
        "She married Barack Obama in 1992.",
    ], [(1, "Chicago", "Chicago", "6886"), (1, "Harvard Law School", "Harvard University", "18426501"),
        (2, "Barack Obama", "Barack Obama", "534366")]),
    "Q22686": ("4848272", "Donald Trump", [
        "Donald Trump",
        "Donald John Trump (born June 14, 1946) is an American politician and businessman. He was born in New York City.",
        "Trump married Melania Knauss in 2005. He is a member of the Republican Party.",
    ], [(1, "New York City", "New York City", "645042"), (2, "Melania Knauss", "Melania Trump", "1185373"),
        (2, "Republican Party", "Republican Party (United States)", "16758")]),
    "Q18094": ("13886", "Honolulu", ["Honolulu", "Honolulu is the capital of Hawaii, with a population of 345,064 in 2010."], []),
    "Q1297": ("6886", "Chicago", ["Chicago", "Chicago is a city in the United States with 2,695,598 residents in 2010."], []),
    "Q35637": ("21201", "Nobel Peace Prize", ["Nobel Peace Prize", "The Nobel Peace Prize has been awarded since 1901."], []),
    "Q13371": ("18426501", "Harvard University", ["Harvard University", "Harvard University was founded in 1636."], []),
    "Q49088": ("6310", "Columbia University", ["Columbia University", "Columbia University was established in 1754."], []),
    "Q29552": ("5043544", "Democratic Party (United States)", ["Democratic Party", "The Democratic Party was founded in 1828."], []),
    "Q29468": ("16758", "Republican Party (United States)", ["Republican Party", "The Republican Party was founded in 1854."], []),
    "Q60": ("645042", "New York City", ["New York City", "New York City had a population of 8,175,133 in 2010."], []),
    "Q432473": ("1185373", "Melania Trump", ["Melania Trump", "Melania Trump (born April 26, 1970) is a former model."], []),
}


def make_kilt_pages() -> list[dict]:
    """Records in the KILT knowledge-source format (one JSON object per Wikipedia page)."""
    out = []
    for qid, (wid, title, paras, anchors) in PAGES.items():
        out.append({
            "_id": wid, "wikipedia_id": wid, "wikipedia_title": title, "text": [p + "\n" for p in paras],
            "anchors": [_anchor(paras[p], m, p, t, w) for p, m, t, w in anchors],
            "categories": "", "history": {}, "wikidata_info": {"wikidata_id": qid},
        })
    out.append({"_id": "1", "wikipedia_id": "1", "wikipedia_title": "Unrelated", "text": ["Unrelated\n", "Nothing here.\n"],
                "anchors": [], "categories": "", "history": {}, "wikidata_info": {"wikidata_id": "Q424242"}})
    return out


def P(*steps) -> list[dict]:
    return [{"function": f, "inputs": list(i)} for f, *i in steps]


QUESTIONS = [
    {"question": "When was Barack Obama born?", "answer": "1961-08-04",
     "program": P(("Find", "Barack Obama"), ("QueryAttr", "date of birth"))},
    {"question": "Who is the spouse of Barack Obama?", "answer": "Michelle Obama",
     "program": P(("Find", "Barack Obama"), ("Relate", "spouse", "forward"), ("FilterConcept", "human"), ("QueryName",))},
    {"question": "When was the spouse of Michelle Obama born?", "answer": "1961-08-04",
     "program": P(("Find", "Michelle Obama"), ("Relate", "spouse", "forward"), ("QueryAttr", "date of birth"))},
    {"question": "In which year did Barack Obama receive the Nobel Peace Prize?", "answer": "2009",
     "program": P(("Find", "Barack Obama"), ("Find", "Nobel Peace Prize"), ("QueryRelationQualifier", "award received", "point in time"))},
    {"question": "What is the population of the birthplace of Barack Obama?", "answer": "345064",
     "program": P(("Find", "Barack Obama"), ("Relate", "place of birth", "forward"), ("QueryAttr", "population"))},
    {"question": "When was the party of Donald Trump founded?", "answer": "1854",
     "program": P(("Find", "Donald Trump"), ("Relate", "member of political party", "forward"), ("QueryAttr", "inception"))},
    {"question": "When was Melania Trump's husband born?", "answer": "1946-06-14",
     "program": P(("Find", "Melania Trump"), ("Relate", "spouse", "forward"), ("QueryAttr", "date of birth"))},
    {"question": "Where was Michelle Obama born?", "answer": "Chicago",
     "program": P(("Find", "Michelle Obama"), ("Relate", "place of birth", "forward"), ("QueryName",))},
    {"question": "Which party is Joe Biden a member of?", "answer": "Democratic Party",
     "program": P(("Find", "Joe Biden"), ("Relate", "member of political party", "forward"), ("QueryName",))},
    {"question": "How many people lived in the city film-namesake Chicago in 2010?", "answer": "2695598",
     "program": P(("Find", "Chicago"), ("FilterConcept", "city"), ("QueryAttr", "population"))},
    {"question": "What year was the population of Honolulu 345064?", "answer": "2010",
     "program": P(("Find", "Honolulu"), ("QueryAttrQualifier", "population", "345064", "point in time"))},
    {"question": "Is Barack Obama male?", "answer": "yes",
     "program": P(("Find", "Barack Obama"), ("QueryAttr", "sex or gender"), ("VerifyStr", "male"))},
    {"question": "How many universities did Barack Obama attend?", "answer": "2",
     "program": P(("Find", "Barack Obama"), ("Relate", "educated at", "forward"), ("Count",))},
]
