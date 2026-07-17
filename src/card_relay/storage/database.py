from pathlib import Path

from sqlalchemy import Engine, create_engine

from card_relay.storage.models import Base


def create_database(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine
