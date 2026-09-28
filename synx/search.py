"""Full-text search and fuzzy matching over the command database."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from synx.models import Command, Tool, normalise_query

__all__ = [
    "FIELD_LABELS",
    "SearchHit",
    "fuzzy_suggestions",
    "score_command",
    "score_tool",
    "search",
    "search_commands",
    "search_tools",
    "suggest",
]

FIELD_LABELS: dict[str, str] = {
    "name": "tool name",
    "alias": "tool alias",
    "tool_description": "tool description",
    "category": "category",
    "command_name": "command name",
    "syntax": "command syntax",
    "description": "command description",
    "tags": "tags",
}

FIELD_WEIGHTS: dict[str, int] = {
    "name": 100,
    "command_name": 80,
    "alias": 70,
    "tags": 50,
    "syntax": 30,
    "description": 25,
    "tool_description": 20,
    "category": 15,
}

_ALL_TOKENS_BONUS = 40
_PHRASE_BONUS = 25
_EXCERPT_RADIUS = 60


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A single match produced by :func:`search`."""

    tool: Tool
    command: Command | None
    field: str
    score: int
    excerpt: str = ""

    @property
    def field_label(self) -> str:
        return FIELD_LABELS.get(self.field, self.field)

    @property
    def sort_key(self) -> tuple[int, str, str]:
        return (
            -self.score,
            self.tool.name.casefold(),
            (self.command.name if self.command else "").casefold(),
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "tool": self.tool.name,
            "matched_field": self.field,
            "matched_field_label": self.field_label,
            "score": self.score,
        }
        if self.command is not None:
            data["command"] = self.command.name
            data["syntax"] = self.command.syntax
        if self.excerpt:
            data["excerpt"] = self.excerpt
        return data


def _tokenize(keyword: str) -> tuple[str, ...]:
    tokens = [token for token in re.split(r"\s+", keyword.strip().casefold()) if token]
    return tuple(dict.fromkeys(tokens))


def _field_score(token: str, weight: int, text: str) -> int:
    haystack = text.casefold()
    if not haystack or token not in haystack:
        return 0
    if haystack == token:
        return weight * 2
    if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", haystack):
        return weight + weight // 2
    return weight


def _score_texts(
    tokens: Sequence[str], fields: Sequence[tuple[str, str]]
) -> tuple[int, str]:
    total = 0
    matched = 0
    best_score = 0
    best_field = ""
    for token in tokens:
        token_best = 0
        token_field = ""
        for key, text in fields:
            score = _field_score(token, FIELD_WEIGHTS[key], text)
            if score > token_best:
                token_best = score
                token_field = key
        if token_best:
            matched += 1
            total += token_best
        if token_best > best_score:
            best_score = token_best
            best_field = token_field
    if not matched:
        return 0, ""
    if matched == len(tokens):
        total += _ALL_TOKENS_BONUS * matched
    return total, best_field


def _excerpt(text: str, keyword: str) -> str:
    if not text:
        return ""
    lowered = text.casefold()
    positions = [lowered.find(token) for token in _tokenize(keyword)]
    hits = [position for position in positions if position >= 0]
    start = max(0, (min(hits) if hits else 0) - _EXCERPT_RADIUS // 3)
    snippet = text[start : start + _EXCERPT_RADIUS].strip()
    if start > 0:
        snippet = f"...{snippet}"
    if start + _EXCERPT_RADIUS < len(text):
        snippet = f"{snippet}..."
    return " ".join(snippet.split())


def score_tool(tool: Tool, keyword: str) -> tuple[int, str]:
    """Score a tool against ``keyword``, returning ``(score, field)``."""
    tokens = _tokenize(keyword)
    if not tokens:
        return 0, ""
    fields = [
        ("name", tool.name),
        *(("alias", alias) for alias in tool.aliases),
        ("tool_description", tool.description),
        ("category", tool.category or ""),
    ]
    total, field = _score_texts(tokens, fields)
    if total and keyword.strip().casefold() in tool.name.casefold():
        total += _PHRASE_BONUS
    return (total, field) if field else (0, "")


def score_command(command: Command, keyword: str) -> tuple[int, str]:
    """Score a single command against ``keyword``, returning ``(score, field)``."""
    tokens = _tokenize(keyword)
    if not tokens:
        return 0, ""
    fields = [
        ("command_name", command.name),
        ("syntax", command.syntax),
        ("description", command.description),
        *(("tags", tag) for tag in command.tags),
    ]
    total, field = _score_texts(tokens, fields)
    if not total:
        return 0, ""
    if keyword.strip().casefold() in command.name.casefold():
        total += _PHRASE_BONUS
    return total, field


def _tool_hit(tool: Tool, keyword: str, score: int, field: str) -> SearchHit:
    if field == "alias":
        excerpt = f"alias: {', '.join(tool.aliases)}"
    elif field == "category":
        excerpt = f"category: {tool.category}"
    else:
        excerpt = tool.summary_description
    return SearchHit(tool=tool, command=None, field=field, score=score, excerpt=excerpt)


def search_tools(keyword: str, tools: Iterable[Tool]) -> list[SearchHit]:
    """Return tool-level matches for ``keyword``."""
    hits: list[SearchHit] = []
    for tool in tools:
        score, field = score_tool(tool, keyword)
        if score:
            hits.append(_tool_hit(tool, keyword, score, field))
    hits.sort(key=lambda hit: hit.sort_key)
    return hits


def search_commands(keyword: str, tools: Iterable[Tool]) -> list[SearchHit]:
    """Return command-level matches for ``keyword``."""
    hits: list[SearchHit] = []
    for tool in tools:
        for command in tool.commands:
            score, field = score_command(command, keyword)
            if score:
                excerpt = _excerpt(
                    command.syntax if field == "syntax" else command.description, keyword
                )
                hits.append(
                    SearchHit(
                        tool=tool,
                        command=command,
                        field=field,
                        score=score,
                        excerpt=excerpt,
                    )
                )
    hits.sort(key=lambda hit: hit.sort_key)
    return hits


def search(keyword: str, tools: Iterable[Tool]) -> list[SearchHit]:
    """Return every match for ``keyword``, best first.

    Each command is reported at most once, with the score of its best matching
    field. A match on the tool itself is reported as a command-less hit.
    """
    tool_list = list(tools)
    hits = [*search_commands(keyword, tool_list), *search_tools(keyword, tool_list)]
    hits.sort(key=lambda hit: hit.sort_key)
    unique: list[SearchHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.tool.name, hit.command.name if hit.command else "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def fuzzy_suggestions(
    query: str,
    candidates: Sequence[str],
    *,
    limit: int = 3,
    cutoff: float = 0.6,
) -> list[tuple[str, float]]:
    """Return the candidates most similar to ``query``.

    Combines prefix/substring awareness with :class:`difflib.SequenceMatcher`
    ratios so that both ``netexec`` -> ``nxc`` (alias) and ``ceripy`` ->
    ``certipy`` (transposition) are suggested.
    """
    wanted = normalise_query(query)
    if not wanted or not candidates:
        return []
    lowered = {candidate.casefold(): candidate for candidate in candidates}
    scored: dict[str, float] = {}

    for key, candidate in lowered.items():
        score = _ratio(wanted, key)
        if key.startswith(wanted) or wanted.startswith(key):
            score = max(score, 0.9)
        elif wanted in key or key in wanted:
            score = max(score, 0.75)
        else:
            tokens = _tokenize(wanted)
            for token in tokens:
                if token and (token in key or key in token):
                    score = max(score, 0.7)
        if score >= cutoff:
            scored[candidate] = max(scored.get(candidate, 0.0), score)

    ordered = sorted(scored.items(), key=lambda item: (-item[1], item[0].casefold()))
    return ordered[:limit]


def suggest(
    query: str,
    candidates: Sequence[str],
    *,
    limit: int = 3,
) -> list[str]:
    """Return up to ``limit`` suggested candidate names for ``query``."""
    return [name for name, _score in fuzzy_suggestions(query, candidates, limit=limit)]
