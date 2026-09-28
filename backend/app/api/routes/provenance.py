from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.provenance import ProvenanceOut
from app.services.provenance.service import ProvenanceService

router = APIRouter(prefix="/provenance", tags=["provenance"])


@router.get("/{entity_type}/{entity_id}", response_model=ProvenanceOut,
            summary="Full lineage: scene | tile | search_query | search_result | change_analysis")
def get_provenance(entity_type: str, entity_id: str, db: Session = Depends(get_db)):
    return ProvenanceService(db).get(entity_type, entity_id)
