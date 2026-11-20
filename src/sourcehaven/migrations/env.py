from alembic import context
from sqlalchemy import Connection

from sourcehaven.storage.models import Base


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline (SQL script) migrations are not supported")
shared_connection: object = context.config.attributes.get("connection")
if not isinstance(shared_connection, Connection):
    raise RuntimeError(
        "Run migrations with `sourcehaven migrate`, which supplies the database connection"
    )
run_migrations(shared_connection)
