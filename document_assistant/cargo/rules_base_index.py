"""Selecting the parts of the reconciliation rules base that a given
declaration actually needs.

The base is injected into the prompt of every chunk, so for a multi-shipment
declaration its size is multiplied by the number of shipments — a 118 KB base
across 61 shipments meant megabytes per run and 500s from the model gateway.

Reuses NormativeIndex's section splitting, but replaces its relevance metric.
NormativeIndex scores with Jaccard (intersection over union), which divides by
the section's own length: a long rule stuffed with boilerplate scores low even
when it is exactly the rule the declaration needs. For a base of instructions
what matters is how much of the query a section covers, not how concise it is.
"""
from document_assistant.ai.context_builder import NormativeIndex


_STEM_LEN = 5


def _stems(tokens: set[str]) -> set[str]:
    """Crude prefix stems, so Russian inflections match.

    The query says «перевозчик» while the rule says «перевозчикоB» or
    «перевозчикA»; exact token matching treats those as unrelated words and
    the right rule never gets selected. Trimming to a common prefix is not
    linguistics, but it costs nothing and errs toward including a rule rather
    than dropping it — the safe direction, since a dropped rule silently
    stops being applied.
    """
    return {t[:_STEM_LEN] if len(t) > _STEM_LEN else t for t in tokens}


class RulesBaseIndex(NormativeIndex):
    """NormativeIndex with query-coverage scoring instead of Jaccard."""

    @staticmethod
    def _score(text: str, query_tokens: set[str]) -> float:
        from document_assistant.ai.context_builder import _tokenize

        if not query_tokens:
            return 0.0
        text_tokens = _tokenize(text)
        if not text_tokens:
            return 0.0

        query_stems = _stems(query_tokens)
        text_stems = _stems(text_tokens)
        covered = len(query_stems & text_stems)
        # Share of the query the section speaks to. A faint length tie-break
        # keeps a focused rule ahead of a sprawling one at equal coverage,
        # without letting length dominate the way Jaccard does.
        return covered / len(query_stems) - 1e-6 * len(text_stems)
