from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.db.models import Embedding, Tile
from app.geo.raster import geojson
from app.repositories.scene_repository import SceneRepository
from app.repositories.tile_repository import TileRepository
from app.schemas.common import check_bbox
from app.schemas.scene import SceneOut
from app.schemas.tile import TileOut
from app.services.registry import get_vector_store
from app.storage import get_storage

router = APIRouter(tags=["scenes"])


def _scene(s, db=None):
    out = SceneOut.model_validate(s).model_dump()
    out["geometry"] = geojson(s.geometry)
    if db is not None:
        out["tile_count"] = db.scalar(select(func.count()).select_from(Tile).where(Tile.scene_id == s.scene_id))
    return out


def _tile(t):
    out = TileOut.model_validate(t).model_dump()
    out["geometry"] = geojson(t.geometry)
    return out


@router.get("/scenes")
def list_scenes(sensor: str | None = None, platform: str | None = None, status: str | None = None,
                date_from: datetime | None = None, date_to: datetime | None = None,
                bbox: list[float] | None = Query(None, description="minx,miny,maxx,maxy (repeat param)"),
                limit: int = Query(50, le=500), offset: int = 0, db: Session = Depends(get_db)):
    rows, total = SceneRepository(db).list(sensor=sensor, platform=platform, status=status, date_from=date_from,
                                           date_to=date_to, bbox=check_bbox(bbox), limit=limit, offset=offset)
    return {"total": total, "items": [_scene(s) for s in rows]}


@router.get("/scenes/{scene_id}")
def get_scene(scene_id: str, db: Session = Depends(get_db)):
    s = SceneRepository(db).get(scene_id)
    if not s:
        raise NotFoundError(f"Scene '{scene_id}' not found")
    return _scene(s, db)


@router.get("/scenes/{scene_id}/tiles")
def scene_tiles(scene_id: str, limit: int = Query(500, le=5000), offset: int = 0, db: Session = Depends(get_db)):
    if not SceneRepository(db).get(scene_id):
        raise NotFoundError(f"Scene '{scene_id}' not found")
    return {"items": [_tile(t) for t in TileRepository(db).for_scene(scene_id, limit, offset)]}


@router.delete("/scenes/{scene_id}", summary="Remove a scene, its tiles and vectors (provenance retained)")
def delete_scene(scene_id: str, db: Session = Depends(get_db)):
    s = SceneRepository(db).get(scene_id)
    if not s:
        raise NotFoundError(f"Scene '{scene_id}' not found")
    store = get_vector_store()
    vids = list(db.scalars(select(Embedding.vector_id).join(Tile, Tile.tile_id == Embedding.tile_id)
                           .where(Tile.scene_id == scene_id)))
    db.delete(s)
    db.commit()
    store.delete(vids)
    store.save()
    return {"deleted": scene_id, "vectors_removed": len(vids)}


@router.get("/tiles/{tile_id}")
def get_tile(tile_id: str, db: Session = Depends(get_db)):
    t = TileRepository(db).get(tile_id)
    if not t:
        raise NotFoundError(f"Tile '{tile_id}' not found")
    return _tile(t)


@router.get("/tiles/{tile_id}/thumbnail", response_class=FileResponse)
def tile_thumbnail(tile_id: str, db: Session = Depends(get_db)):
    t = TileRepository(db).get(tile_id)
    if not t or not t.thumbnail_path:
        raise NotFoundError(f"Thumbnail for '{tile_id}' not found")
    return FileResponse(get_storage().get_path(t.thumbnail_path), media_type="image/png")


@router.get("/tiles/{tile_id}/raster", response_class=FileResponse)
def tile_raster(tile_id: str, kind: str = Query("data", pattern="^(data|mask)$"), db: Session = Depends(get_db)):
    t = TileRepository(db).get(tile_id)
    if not t:
        raise NotFoundError(f"Tile '{tile_id}' not found")
    key = t.raster_path if kind == "data" else t.mask_path
    return FileResponse(get_storage().get_path(key), media_type="image/tiff", filename=f"{tile_id}_{kind}.tif")
