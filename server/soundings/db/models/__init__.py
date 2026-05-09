from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData()


metadata = Base.metadata

from soundings.db.models import geography  # noqa: E402, F401
