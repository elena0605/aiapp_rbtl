"""Media retrieval module.

Provides semantic retrievers over YouTube/TikTok video content, comment
summaries, and comment topics. Used by the GraphRAG chat app to answer
questions of the form "how many creators talk about X?" / "show me videos
whose comment sections discuss X" without going through text-to-Cypher.

Public API:
- ``MediaRetrievalAgent`` — picks a retriever and runs it.
- ``MediaRetrievalResult`` / ``RetrieverResult`` — uniform result envelopes.
- ``MediaRetrievalAgentError`` — raised when no retriever can be matched.

The retriever Cypher itself is ported from the production notebooks at
``/Users/bojansimoski/airflow_upgrade/notebooks/``; see ``youtube.py`` and
``tiktok.py``.
"""

from .base import (
    RetrieverConfig,
    RetrieverResult,
    FAMILY_TEMPLATES,
    compute_k,
    embed_query,
    get_index_size,
    list_expected_indexes,
)
from .media_retrieval_agent import (
    MediaRetrievalAgent,
    MediaRetrievalAgentError,
    MediaRetrievalResult,
)

__all__ = [
    "MediaRetrievalAgent",
    "MediaRetrievalAgentError",
    "MediaRetrievalResult",
    "RetrieverConfig",
    "RetrieverResult",
    "FAMILY_TEMPLATES",
    "compute_k",
    "embed_query",
    "get_index_size",
    "list_expected_indexes",
]
