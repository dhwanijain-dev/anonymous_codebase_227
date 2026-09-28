from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_job_manager
from app.schemas.change import ChangeAnalysisOut, ChangeAnalyzeRequest, ChangeAnalyzeResponse
from app.services.change_detection.service import ChangeAnalysisService

router = APIRouter(prefix="/change", tags=["change"])


@router.post("/analyze", response_model=ChangeAnalyzeResponse | dict,
             summary="Multi-temporal change detection over an AOI with false-alarm suppression")
def analyze(req: ChangeAnalyzeRequest, db: Session = Depends(get_db)):
    types = [t.value for t in req.change_types] if req.change_types else None
    if req.background:
        return get_job_manager().submit("change_analyze", {
            "bbox": req.bbox, "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None, "change_types": types,
            "min_quality": req.min_quality})
    svc = ChangeAnalysisService(db)
    res = svc.analyze(req.bbox, req.start_date, req.end_date, types, req.min_quality)
    dets = [svc.get(d["analysis_id"]) for d in res["detections"]]
    head = dets[0] if dets else {}
    return {"request_id": res["request_id"], "analysis_id": head.get("analysis_id"),
            "change_type": head.get("change_type"), "confidence": head.get("confidence"),
            "earliest_supported_time": head.get("earliest_supported_time"), "geometry": head.get("geometry"),
            "evidence": head.get("evidence", []), "provenance": head.get("provenance"), "detections": dets,
            "diagnostics": res["diagnostics"], "parameters": res["parameters"], "model": res["model"]}


@router.get("/{analysis_id}", response_model=ChangeAnalysisOut)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    return ChangeAnalysisService(db).get(analysis_id)
