import pytest
from pydantic import SecretStr

from sourcehaven.composition import AppContainer, build_container
from sourcehaven.config import Settings
from sourcehaven.storage.db import PrivilegedRoleError
from tests.support.db import TestDatabaseUrls

pytestmark = pytest.mark.integration


def _offline_settings(database_url: SecretStr) -> Settings:
    return Settings(
        database_url=database_url,
        embedding_provider="hash",
        generation_provider="fake",
        human_verification="disabled",
    )


async def test_container_starts_as_the_application_role(database_urls: TestDatabaseUrls) -> None:
    container: AppContainer
    async with build_container(_offline_settings(database_urls.app)) as container:
        assert container.embedding_config_id > 0


@pytest.mark.parametrize("role", ["admin", "maintenance"])
async def test_container_refuses_a_role_that_bypasses_rls(
    database_urls: TestDatabaseUrls, role: str
) -> None:
    url: SecretStr = database_urls.admin if role == "admin" else database_urls.maintenance
    with pytest.raises(PrivilegedRoleError, match="BYPASSRLS"):
        async with build_container(_offline_settings(url)):
            pytest.fail("the container must not start")
