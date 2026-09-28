#!/usr/bin/env python
"""Offline evaluation (no retraining).

1) Retrieval, from analyst reviews already in the DB (accept = relevant):
     python scripts/evaluate.py retrieval --k 5 10 20
2) Retrieval, from a labelled benchmark JSONL: {"query": "...", "relevant_tiles": [...], "filters": {...}}
     python scripts/evaluate.py retrieval --benchmark bench.jsonl
3) Change detection vs ground truth GeoJSON (features with properties.change_type, optional .date):
     python scripts/evaluate.py change --truth truth.geojson --bbox minx miny maxx maxy
"""
import argparse
import json
import math
from collections import defaultdict

import _bootstrap

p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
r = sub.add_parser("retrieval")
r.add_argument("--k", type=int, nargs="+", default=[5, 10, 20])
r.add_argument("--benchmark")
c = sub.add_parser("change")
c.add_argument("--truth", required=True)
c.add_argument("--bbox", type=float, nargs=4, required=True)
c.add_argument("--start"), c.add_argument("--end")
c.add_argument("--min-confidence", type=float, default=0.3)
a = p.parse_args()
_bootstrap.init()
from sqlalchemy import select  # noqa: E402

from app.db.models import AnalystReview, SearchResult  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def metrics(ranked: list[str], relevant: set[str], ks) -> dict:
    out = {}
    for k in ks:
        top = ranked[:k]
        hits = [1 if t in relevant else 0 for t in top]
        dcg = sum(h / math.log2(i + 2) for i, h in enumerate(hits))
        idcg = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
        out[f"precision@{k}"] = sum(hits) / k
        out[f"recall@{k}"] = sum(hits) / len(relevant) if relevant else 0.0
        out[f"ndcg@{k}"] = dcg / idcg if idcg else 0.0
    rr = next((1 / (i + 1) for i, t in enumerate(ranked) if t in relevant), 0.0)
    out["mrr"] = rr
    return out


def avg(rows: list[dict]) -> dict:
    agg = defaultdict(float)
    for m in rows:
        for k, v in m.items():
            agg[k] += v
    return {k: round(v / len(rows), 4) for k, v in agg.items()} if rows else {}


with SessionLocal() as db:
    if a.cmd == "retrieval" and not a.benchmark:
        per_q = defaultdict(dict)
        for rv in db.scalars(select(AnalystReview).where(AnalystReview.result_type == "search_result")
                             .order_by(AnalystReview.timestamp)):
            per_q[rv.query_id][rv.result_id] = rv.decision
        rows = []
        for qid, dec in per_q.items():
            res = list(db.scalars(select(SearchResult).where(SearchResult.query_id == qid).order_by(SearchResult.rank)))
            ranked = [x.result_id for x in res]
            rel = {rid for rid, d in dec.items() if d == "accept"}
            if rel:
                rows.append(metrics(ranked, rel, a.k))
        print(json.dumps({"queries_evaluated": len(rows), "note": "relevance = analyst accept (reviewed-only)",
                          **avg(rows)}, indent=2))
    elif a.cmd == "retrieval":
        from app.services.retrieval.service import RetrievalService, SearchParams

        rows = []
        for line in open(a.benchmark):
            b = json.loads(line)
            res = RetrievalService(db).search_text(b["query"], SearchParams(top_k=max(a.k), **b.get("filters", {})))
            rows.append(metrics([x["tile_id"] for x in res["results"]], set(b["relevant_tiles"]), a.k))
        print(json.dumps({"queries_evaluated": len(rows), **avg(rows)}, indent=2))
    else:
        from shapely.geometry import shape

        from app.geo.raster import parse_datetime
        from app.services.change_detection.service import ChangeAnalysisService

        truth = [(shape(f["geometry"]), f["properties"]) for f in json.load(open(a.truth))["features"]]
        res = ChangeAnalysisService(db).analyze(a.bbox, parse_datetime(a.start) if a.start else None,
                                                parse_datetime(a.end) if a.end else None, persist=False)
        dets = [d for d in res["detections"] if d["confidence"] >= a.min_confidence]
        matched, tp, type_ok, lag = set(), 0, 0, []
        for d in dets:
            g = shape(d["geometry"])
            hit = next((i for i, (tg, _) in enumerate(truth) if i not in matched and tg.intersects(g)), None)
            if hit is None:
                continue
            matched.add(hit)
            tp += 1
            props = truth[hit][1]
            type_ok += props.get("change_type") == d["change_type"]
            if props.get("date") and d["earliest_supported_time"]:
                lag.append((d["earliest_supported_time"] - parse_datetime(props["date"])).days)
        fp, fn = len(dets) - tp, len(truth) - tp
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        print(json.dumps({"detections": len(dets), "truth": len(truth), "tp": tp, "fp": fp, "fn": fn,
                          "precision": round(prec, 4), "recall": round(rec, 4),
                          "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
                          "type_accuracy": round(type_ok / tp, 4) if tp else None,
                          "median_detection_lag_days": sorted(lag)[len(lag) // 2] if lag else None}, indent=2))
