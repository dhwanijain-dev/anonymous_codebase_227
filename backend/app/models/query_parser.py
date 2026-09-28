"""Query understanding. Rule-based now; an on-prem LLM can implement BaseQueryParser later
(e.g. a llama.cpp model returning the same ParsedQuery JSON)."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from app.models.base import ModelInfo, PluggableModel
from app.models.concepts import CHANGE_LEXICON, CONCEPTS, SPATIAL_RELATIONS, TEMPORAL_WORDS


class ParsedQuery(BaseModel):
    raw: str
    semantic_concepts: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    spatial_relation: str | None = None
    change_intent: str | None = None  # e.g. "appearance/construction"
    change_types: list[str] = Field(default_factory=list)
    temporal_intent: bool = False
    date_from: datetime | None = None
    date_to: datetime | None = None
    embedding_text: str = ""  # text actually sent to the encoder (focus concept first)


class BaseQueryParser(PluggableModel, ABC):
    @abstractmethod
    def parse(self, text: str) -> ParsedQuery: ...


def _find(text: str, phrase: str) -> int:
    m = re.search(rf"\b{re.escape(phrase)}\b", text)
    return m.start() if m else -1


class RuleBasedQueryParser(BaseQueryParser):
    def parse(self, text: str) -> ParsedQuery:
        t = " ".join(text.lower().split())
        # split into focus (before spatial relation) and context (after it)
        rel, rel_pos = None, len(t)
        weak = ("on", "by")
        for group in ([r for r in SPATIAL_RELATIONS if r not in weak], list(weak)):
            for r in group:
                p = _find(t, r)
                if 0 < p < rel_pos:
                    rel, rel_pos = r, p
            if rel:
                break
        focus, ctx_txt = t[:rel_pos], t[rel_pos:]

        objects, context = [], []
        for concept, (syns, _cat, _p) in CONCEPTS.items():
            in_focus = any(_find(focus, s) >= 0 for s in syns)
            in_ctx = any(_find(ctx_txt, s) >= 0 for s in syns)
            if in_focus:
                objects.append(concept)
            elif in_ctx:
                # name the context by the word actually used (river, road, ...)
                word = next(s for s in syns if _find(ctx_txt, s) >= 0)
                context.append(word)

        change_types = [ct for ct, words in CHANGE_LEXICON.items() if any(_find(t, w) >= 0 for w in words)]
        if "road" in objects and "construction" in change_types:
            change_types.insert(0, "road_development")
        # order by specificity: typed changes before generic appearance
        order = ["road_development", "construction", "clearance", "water_extent_change", "expansion",
                 "contraction", "disappearance", "appearance"]
        change_types = sorted(dict.fromkeys(change_types), key=order.index)
        activities = [w for w in re.findall(r"\b\w+ing\b", t) if w not in ("building", "during")]

        date_from = date_to = None
        years = [int(y) for y in re.findall(r"\b(19[89]\d|20\d\d)\b", t)]
        if m := re.search(r"\b(since|after|from)\s+(19[89]\d|20\d\d)\b", t):
            date_from = datetime(int(m.group(2)), 1, 1, tzinfo=timezone.utc)
        if m := re.search(r"\b(before|until|to)\s+(19[89]\d|20\d\d)\b", t):
            date_to = datetime(int(m.group(2)), 1, 1, tzinfo=timezone.utc)
        if re.search(r"\bbetween\b", t) and len(years) >= 2:
            date_from = datetime(min(years), 1, 1, tzinfo=timezone.utc)
            date_to = datetime(max(years), 12, 31, 23, 59, tzinfo=timezone.utc)
        if m := re.search(r"\blast\s+(\d+)?\s*(day|week|month|year)s?\b", t):
            n = int(m.group(1) or 1)
            days = {"day": 1, "week": 7, "month": 30, "year": 365}[m.group(2)] * n
            date_from = datetime.now(timezone.utc) - timedelta(days=days)

        temporal = bool(change_types) or any(_find(t, w) >= 0 for w in TEMPORAL_WORDS) or bool(date_from or date_to)
        intent = None
        if change_types:
            generic = "appearance" if "appearance" in change_types or "construction" in change_types else None
            specific = [c for c in change_types if c != "appearance"]
            intent = "/".join(([generic] if generic else []) + specific[:2]) or change_types[0]

        concepts = [("built structures" if o == "built structures" else o) for o in objects] or (
            [focus.strip()] if focus.strip() else [])
        embedding_text = " ".join(concepts + ([f"{rel} {' '.join(context)}"] if context else []))
        return ParsedQuery(raw=text, semantic_concepts=concepts, objects=objects, activities=activities,
                           context=context, spatial_relation=rel if context else None,
                           change_intent=intent, change_types=change_types, temporal_intent=temporal,
                           date_from=date_from, date_to=date_to, embedding_text=embedding_text or t)

    def info(self):
        return ModelInfo("rule-based-parser", "1.0.0", "parser", None, None, "internal", "built-in")
