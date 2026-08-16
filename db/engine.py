import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://neighborhoodinfo:neighborhoodinfo@localhost:5432/neighborhoodinfo"
)

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
