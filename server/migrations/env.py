"""Alembic environment for the dedicated Jarvis MySQL database."""

from alembic import context
from sqlalchemy import create_engine

from server.scripts.check_database import database_url


def run_migrations_offline() -> None:
    # SQL generation must not require or reveal local database credentials.
    context.configure(dialect_name="mysql", literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = database_url()
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
