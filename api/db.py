import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_DATABASE_URL = 'postgresql+psycopg://localhost:5432/check_stock'

engine = create_engine(
    os.getenv('DATABASE_URL', DEFAULT_DATABASE_URL),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(engine)


class Base(DeclarativeBase):
    pass