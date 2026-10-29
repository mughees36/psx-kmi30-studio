import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./test.db")

# Some providers still issue the legacy postgres:// scheme, while SQLAlchemy
# expects postgresql://. Neon currently supplies postgresql://, so this also
# keeps the app compatible if the URL format changes in the future.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def run_migrations():
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "users" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    migrations = {
        "phone": "ALTER TABLE users ADD COLUMN phone VARCHAR",
    }

    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))
