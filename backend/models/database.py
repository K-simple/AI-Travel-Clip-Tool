import os
import uuid
from pathlib import Path

from sqlalchemy import Column, Float, Integer, JSON, String, Text, create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_ROOT / "ai_travel_cut.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record):
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Template(Base):
    __tablename__ = "templates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    duration = Column(Float, default=0.0)
    slot_count = Column(Integer, default=0)
    file_path = Column(String, nullable=False)
    slots = Column(JSON, default=list)
    audio_path = Column(String, default="")
    subtitle_srt_path = Column(String, default="")
    subtitle_ass_path = Column(String, default="")
    subtitle_style = Column(Text, default="")
    segments_json = Column(JSON, default=list)
    processing_status = Column(String, default="ready")
    processing_progress = Column(Integer, default=100)
    beat_markers = Column(JSON, default=list)
    proxy_paths = Column(JSON, default=dict)
    enhance_status = Column(String, default="ready")
    enhance_progress = Column(Integer, default=100)
    ai_vision_json = Column(JSON, default=dict)
    sfx_markers = Column(JSON, default=list)
    created_at = Column(Float, default=0.0)


class Asset(Base):
    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    duration = Column(Float, default=0.0)
    file_path = Column(String, nullable=False)
    thumbnail_path = Column(String, default="")
    segments = Column(JSON, default=list)
    proxy_path = Column(String, default="")
    proxy_paths = Column(JSON, default=dict)
    processing_status = Column(String, default="ready")
    processing_progress = Column(Integer, default=100)
    created_at = Column(Float, default=0.0)
    updated_at = Column(Float, default=0.0)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id = Column(String, nullable=False)
    name = Column(String, default="")
    timeline = Column(JSON, default=list)
    edl_json = Column(JSON, default=dict)
    track_controls_json = Column(JSON, default=dict)
    match_strategy_json = Column(JSON, default=dict)
    cover_thumbnail = Column(String, default="")
    created_at = Column(Float, default=0.0)
    updated_at = Column(Float, default=0.0)


def migrate_db():
    migrations = [
        "ALTER TABLE projects ADD COLUMN name VARCHAR DEFAULT ''",
        "ALTER TABLE templates ADD COLUMN processing_status VARCHAR DEFAULT 'ready'",
        "ALTER TABLE templates ADD COLUMN processing_progress INTEGER DEFAULT 100",
        "ALTER TABLE templates ADD COLUMN beat_markers JSON DEFAULT '[]'",
        "ALTER TABLE projects ADD COLUMN edl_json JSON DEFAULT '{}'",
        "ALTER TABLE projects ADD COLUMN track_controls_json JSON DEFAULT '{}'",
        "ALTER TABLE projects ADD COLUMN match_strategy_json JSON DEFAULT '{}'",
        "ALTER TABLE assets ADD COLUMN proxy_path VARCHAR DEFAULT ''",
        "ALTER TABLE assets ADD COLUMN processing_status VARCHAR DEFAULT 'ready'",
        "ALTER TABLE assets ADD COLUMN processing_progress INTEGER DEFAULT 100",
        "ALTER TABLE assets ADD COLUMN updated_at FLOAT DEFAULT 0",
        "ALTER TABLE projects ADD COLUMN cover_thumbnail VARCHAR DEFAULT ''",
        "ALTER TABLE assets ADD COLUMN proxy_paths JSON DEFAULT '{}'",
        "ALTER TABLE templates ADD COLUMN proxy_paths JSON DEFAULT '{}'",
        "ALTER TABLE templates ADD COLUMN enhance_status VARCHAR DEFAULT 'ready'",
        "ALTER TABLE templates ADD COLUMN enhance_progress INTEGER DEFAULT 100",
        "ALTER TABLE templates ADD COLUMN ai_vision_json JSON DEFAULT '{}'",
        "ALTER TABLE templates ADD COLUMN sfx_markers JSON DEFAULT '[]'",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass


def init_db():
    Base.metadata.create_all(bind=engine)
    migrate_db()
