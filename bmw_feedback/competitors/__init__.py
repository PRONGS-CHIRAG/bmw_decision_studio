"""Competitor analysis: public web data on the rivals of the 1, 5 and 7 Series per market.

    snapshot.py   download a web page or PDF, keep the raw bytes and a normalised text copy (acquisition only)
    records.py    the extracted value rows and the validator that gates every build
    build.py      records -> data/processed/competitor_*.csv, top-5 selection, review classification
    engine.py     deterministic BMW-vs-competitor comparison per series x market (no LLM)
    facts.py      the comparison as facts with stable IDs for the competitor agents
"""
