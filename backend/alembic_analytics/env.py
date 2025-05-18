# backend/alembic_analytics/env.py
from logging.config import fileConfig
from sqlalchemy import pool, create_engine # create_engine for sync Alembic operations
from alembic import context

# This section allows importing modules from your 'backend' directory
import sys
import os
# Add the 'backend' directory (which is /app in the container) to sys.path
# This assumes env.py is in alembic_analytics, and analytics_db.py is in the parent (backend)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    # Attempt to import from analytics_db which should be in the backend directory
    from analytics_db import SQLModel, ANALYTICS_DATABASE_URL
except ImportError as e:
    print(f"CRITICAL Error importing from analytics_db in env.py: {e}")
    print("Ensure 'analytics_db.py' is in the 'backend' directory and accessible.")
    print(f"Current sys.path: {sys.path}")
    SQLModel = None 
    ANALYTICS_DATABASE_URL = None

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here for 'autogenerate' support
if SQLModel:
    target_metadata = SQLModel.metadata
else:
    # This will likely cause issues with autogenerate if SQLModel couldn't be imported
    print("Warning: SQLModel could not be imported, target_metadata is None. Autogenerate might not work.")
    target_metadata = None

# Use the ANALYTICS_DATABASE_URL from your application's configuration
db_url_for_alembic = ANALYTICS_DATABASE_URL
if db_url_for_alembic:
    if "+asyncpg" in db_url_for_alembic:
        db_url_for_alembic = db_url_for_alembic.replace("+asyncpg", "") # Convert to sync for Alembic
    config.set_main_option("sqlalchemy.url", db_url_for_alembic)
else:
    print("CRITICAL WARNING: ANALYTICS_DATABASE_URL is not set in the environment. "
          "Alembic needs this to connect to the database for 'online' mode and autogenerate. "
          "Set it in your .env file and ensure it's passed to the container.")
    # Provide a placeholder to allow some Alembic commands to run without crashing immediately,
    # but 'upgrade' and 'autogenerate --online' will fail.
    config.set_main_option("sqlalchemy.url", "postgresql://user:pass@host/db_placeholder_for_alembic")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable_url = config.get_main_option("sqlalchemy.url")
    if not connectable_url or "db_placeholder_for_alembic" in connectable_url :
        raise Exception(
            "sqlalchemy.url not properly configured for Alembic online mode. "
            "Ensure ANALYTICS_DATABASE_URL is correctly set in your .env file and accessible to the backend container."
        )

    connectable = create_engine(connectable_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()