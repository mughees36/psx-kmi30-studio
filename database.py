from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

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
