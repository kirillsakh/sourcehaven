from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from sourcehaven.storage.db import create_engine


async def test_engine_keeps_sql_parameters_out_of_logs_and_errors() -> None:
    engine: AsyncEngine = create_engine(
        SecretStr("postgresql+psycopg://user:secret@127.0.0.1:1/db")
    )
    try:
        assert engine.sync_engine.hide_parameters is True
    finally:
        await engine.dispose()
