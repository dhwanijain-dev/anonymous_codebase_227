from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.export.service import ExportService

router = APIRouter(prefix="/export", tags=["export"])


def _resp(body: str, mt: str, name: str) -> Response:
    return Response(body, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/search/{query_id}")
def export_search(query_id: str, format: str = Query("geojson", pattern="^(geojson|csv)$"),
                  db: Session = Depends(get_db)):
    return _resp(*ExportService(db).search(query_id, format))


@router.get("/change/{analysis_id}")
def export_change(analysis_id: str, format: str = Query("geojson", pattern="^(geojson|json|csv)$"),
                  db: Session = Depends(get_db)):
    return _resp(*ExportService(db).change(analysis_id, format))
