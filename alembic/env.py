from alembic import context
from sqlalchemy import create_engine

from exoplanet_archive.config import get_settings

# Tests point migrations at their own database through config.attributes.
url = context.config.attributes.get("url") or get_settings().database_url

engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
