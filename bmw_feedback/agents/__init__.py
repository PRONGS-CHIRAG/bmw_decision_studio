"""Three agents that evaluate a PM's feature idea against the knowledge graph.

    retriever.py   Agent 1: idea -> validated IdeaSpec (features from the graph, series, markets, move, price)
    explainer.py   Agent 2: fact bundle -> decision brief for a product manager, every claim citing fact IDs
    verifier.py    Agent 3: rules + LLM entailment check of every claim against the cited facts
    facts.py       deterministic fact bundle from the decision engine's evaluation (the LLM computes nothing)
    evidence.py    the knowledge-graph neighbourhood of one evaluation, for the graph view
    pipeline.py    orchestration and caching; contracts.py: the Pydantic models; llm.py: OpenAI access
"""
