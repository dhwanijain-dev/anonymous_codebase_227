"""GeoJSON / JSON / CSV exports. Every row/feature carries provenance."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.db.models import ChangeAnalysis
from app.services.change_detection.service import ChangeAnalysisService
from app.services.provenance.service import ProvenanceService
from app.services.retrieval.service import RetrievalService
from app.storage import get_storage


def _default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(type(o))


def _dumps(obj) -> str:
    return json.dumps(obj, default=_default, indent=2)


class ExportService:
    def __init__(self, db: Session):
        self.db = db
        self.prov = ProvenanceService(db)

    def _save(self, name: str, content: str) -> str:
        key = f"exports/{name}"
        get_storage().save(key, content.encode())
        return key

    def search(self, query_id: str, fmt: str) -> tuple[str, str, str]:
        if fmt not in ("geojson", "csv"):
            raise ValidationError("format must be geojson or csv")
        q = RetrievalService(self.db).get_query(query_id)
        qprov = self.prov.compact("search_query", query_id)
        now = datetime.now(timezone.utc).isoformat()
        if fmt == "geojson":
            feats = []
            for r in q["results"]:
                props = {k: v for k, v in r.items() if k not in ("geometry",)}
                props["provenance"] = self.prov.compact("search_result", r["result_id"])
                feats.append({"type": "Feature", "id": r["result_id"], "geometry": r["geometry"], "properties": props})
            doc = {"type": "FeatureCollection", "features": feats,
                   "properties": {"query_id": query_id, "query": q["query"], "query_type": q["query_type"],
                                  "filters": q["filters"], "embedding_model": q["embedding_model"],
                                  "exported_at": now, "provenance": qprov}}
            body, mt = _dumps(doc), "application/geo+json"
        else:
            buf = io.StringIO()
            cols = ["rank", "result_id", "tile_id", "scene_id", "acquisition_time", "sensor", "platform",
                    "semantic_score", "quality_score", "metadata_score", "change_score", "final_score",
                    "change_analysis_id", "status", "bbox", "source_path", "source_checksum",
                    "embedding_model", "embedding_version", "preprocessing_version", "provenance_href"]
            w = csv.writer(buf)
            w.writerow([f"# query_id={query_id}", f"query={q['query']}", f"exported_at={now}",
                        f"embedding_model={q['embedding_model']}"])
            w.writerow(cols)
            for r in q["results"]:
                p = r["provenance"]
                w.writerow([r["rank"], r["result_id"], r["tile_id"], r["scene_id"], _iso(r["acquisition_time"]),
                            r["sensor"], r["platform"], r["semantic_score"], r["quality_score"],
                            r["metadata_score"], r["change_score"], r["final_score"], r.get("change_analysis_id"),
                            r.get("status"), json.dumps(r["bbox"]), p["source_path"], p["checksum"],
                            p["embedding_model"], p["embedding_version"], p["preprocessing_version"], p["href"]])
            body, mt = buf.getvalue(), "text/csv"
        self._save(f"search_{query_id}.{fmt}", body)
        return body, mt, f"search_{query_id}.{fmt}"

    def change(self, analysis_id: str, fmt: str) -> tuple[str, str, str]:
        if fmt not in ("geojson", "json", "csv"):
            raise ValidationError("format must be geojson, json or csv")
        svc = ChangeAnalysisService(self.db)
        d = svc.get(analysis_id)
        full_prov = self.prov.get("change_analysis", analysis_id)
        if fmt == "json":
            body, mt = _dumps(d | {"provenance": full_prov}), "application/json"
        elif fmt == "geojson":
            props = {k: v for k, v in d.items() if k not in ("geometry", "provenance")}
            doc = {"type": "FeatureCollection", "features": [
                {"type": "Feature", "id": analysis_id, "geometry": d["geometry"], "properties": props | {
                    "provenance": d["provenance"]}}],
                "properties": {"exported_at": datetime.now(timezone.utc).isoformat(), "provenance": full_prov}}
            body, mt = _dumps(doc), "application/geo+json"
        else:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["analysis_id", "change_type", "confidence", "earliest_supported_time", "before_scene",
                        "after_scene", "before_tile", "after_tile", "before_time", "after_time", "evidence_score",
                        "change_model", "change_model_version", "source_paths", "source_checksums",
                        "provenance_href"])
            srcs = full_prov["source_scenes"]
            for e in d["evidence"]:
                w.writerow([analysis_id, d["change_type"], d["confidence"], _iso(d["earliest_supported_time"]),
                            e["before_scene"], e["after_scene"], e["before_tile"], e["after_tile"],
                            _iso(e["before_time"]), _iso(e["after_time"]), e["score"], d["model_name"],
                            d["model_version"], ";".join(s["original_file"] for s in srcs),
                            ";".join(s["checksum"] for s in srcs), d["provenance"]["href"]])
            body, mt = buf.getvalue(), "text/csv"
        name = f"change_{analysis_id}.{fmt}"
        self._save(name, body)
        return body, mt, name

    def change_request(self, request_id: str) -> list[str]:
        return list(self.db.scalars(select(ChangeAnalysis.analysis_id).where(ChangeAnalysis.request_id == request_id)))


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v
