from app.db.session import SessionLocal
from app.geo.raster import parse_datetime
from app.services.change_detection.service import ChangeAnalysisService
from app.workers.jobs import register


@register("change_analyze")
def change_analyze(params: dict, progress) -> dict:
    with SessionLocal() as db:
        res = ChangeAnalysisService(db).analyze(
            params.get("bbox"), parse_datetime(params["start_date"]) if params.get("start_date") else None,
            parse_datetime(params["end_date"]) if params.get("end_date") else None, params.get("change_types"),
            params.get("min_quality"))
        return {"request_id": res["request_id"], "diagnostics": res["diagnostics"],
                "analysis_ids": [d["analysis_id"] for d in res["detections"]]}
