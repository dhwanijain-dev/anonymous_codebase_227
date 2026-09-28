from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.db.models import ModelRegistry

router = APIRouter(prefix="/models", tags=["models"])


def _m(r: ModelRegistry) -> dict:
    return {"model_name": r.model_name, "version": r.version, "type": r.type, "local_path": r.local_path,
            "checksum": r.checksum, "license": r.license, "source": r.source, "input_schema": r.input_schema,
            "output_schema": r.output_schema, "active": r.active, "registered_at": r.registered_at}


@router.get("")
def list_models(type: str | None = None, active: bool | None = None, db: Session = Depends(get_db)):
    stmt = select(ModelRegistry).order_by(ModelRegistry.type, ModelRegistry.model_name)
    if type:
        stmt = stmt.where(ModelRegistry.type == type)
    if active is not None:
        stmt = stmt.where(ModelRegistry.active == active)
    return {"items": [_m(r) for r in db.scalars(stmt)]}


@router.get("/{model_name}")
def get_model(model_name: str, db: Session = Depends(get_db)):
    rows = list(db.scalars(select(ModelRegistry).where(ModelRegistry.model_name == model_name)
                           .order_by(ModelRegistry.registered_at.desc())))
    if not rows:
        raise NotFoundError(f"Model '{model_name}' not registered")
    return {"model_name": model_name, "active": next((_m(r) for r in rows if r.active), None),
            "versions": [_m(r) for r in rows]}
