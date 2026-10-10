"""Knowledge graph over the processed BMW data and the trained models' outputs.

    build.py     processed tables + models/ + reports/*.json -> networkx MultiDiGraph (validated)
    store.py     load / cache the graph, node inspector, schema (meta-graph)
    semantic.py  feature index for matching free-text ideas (OpenAI embeddings or TF-IDF)
"""
