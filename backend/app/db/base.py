"""Declarative base + a portable geometry column type.

On PostgreSQL the column is a PostGIS geometry(…, 4326) with a GiST index.
On SQLite (tests / laptop mode) it degrades to WKT text; spatial filtering then
falls back to the bbox columns (min_x/min_y/max_x/max_y) that every spatial
table also carries, so the same repositories work on both.
"""
from datetime import datetime, timezone

from shapely import wkb, wkt
from shapely.geometry.base import BaseGeometry
from sqlalchemy import DateTime, Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator, UserDefinedType


class _PostGISGeometry(UserDefinedType):
    """Native PostGIS column. Values travel as EWKT in and hex-EWKB out, so no extra
    driver/ORM extension is needed and ST_* functions apply to the column directly."""

    cache_ok = True

    def __init__(self, geometry_type: str, srid: int):
        self.geometry_type, self.srid = geometry_type, srid

    def get_col_spec(self, **kw):
        return f"geometry({self.geometry_type},{self.srid})"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Geometry(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, geometry_type: str = "GEOMETRY", srid: int = 4326):
        super().__init__()
        self.geometry_type = geometry_type
        self.srid = srid

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PostGISGeometry(self.geometry_type, self.srid))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, BaseGeometry):
            value = value.wkt
        if dialect.name == "postgresql":
            return f"SRID={self.srid};{value}"
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return wkb.loads(value, hex=True).wkt if isinstance(value, str) else wkb.loads(bytes(value)).wkt
        return value.split(";", 1)[1] if value.startswith("SRID") else value


def to_shape(value: str | None) -> BaseGeometry | None:
    return wkt.loads(value) if value else None
