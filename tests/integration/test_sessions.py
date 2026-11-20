from datetime import UTC, datetime, timedelta

import httpx
import pytest

from sourcehaven.composition import ContainerOverrides
from sourcehaven.sessions.tokens import new_token
from tests.support.app import ApiClientFactory
from tests.support.clock import FakeClock

pytestmark = pytest.mark.integration

SESSION_REQUIRED_BODY: dict[str, object] = {"code": "session_required"}


class RejectingVerifier:
    async def verify(self, token: str | None, remote_ip: str | None) -> bool:
        return False


async def test_create_sets_secure_cookie(make_api_client: ApiClientFactory) -> None:
    clock: FakeClock = FakeClock(datetime(2026, 11, 20, tzinfo=UTC))
    async with make_api_client(
        overrides=ContainerOverrides(clock=clock), settings_overrides={"cookie_secure": True}
    ) as client:
        response: httpx.Response = await client.post("/api/session", json={})
    cookie: str = response.headers["set-cookie"]
    assert response.status_code == 200
    for attribute in ("sh_session=", "HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()
    assert f"max-age={7 * 24 * 3600}" in cookie.lower()


async def test_session_resolves_and_reports_limits(api_client: httpx.AsyncClient) -> None:
    await api_client.post("/api/session", json={})
    response: httpx.Response = await api_client.get("/api/session")
    assert response.status_code == 200
    assert response.json()["limits"]["max_documents"] == 10


async def test_create_without_body_succeeds(api_client: httpx.AsyncClient) -> None:
    assert (await api_client.post("/api/session")).status_code == 200


async def test_post_with_valid_cookie_returns_the_same_session(
    api_client: httpx.AsyncClient,
) -> None:
    first: httpx.Response = await api_client.post("/api/session", json={})
    second: httpx.Response = await api_client.post("/api/session", json={})
    assert second.json()["absolute_expires_at"] == first.json()["absolute_expires_at"]
    assert "set-cookie" not in second.headers


async def test_idle_expiry_requires_new_session(make_api_client: ApiClientFactory) -> None:
    clock: FakeClock = FakeClock(datetime(2026, 11, 20, tzinfo=UTC))
    async with make_api_client(overrides=ContainerOverrides(clock=clock)) as client:
        await client.post("/api/session", json={})
        clock.advance(timedelta(hours=24, seconds=1))
        assert (await client.get("/api/session")).status_code == 401


async def test_absolute_expiry_despite_activity(make_api_client: ApiClientFactory) -> None:
    clock: FakeClock = FakeClock(datetime(2026, 11, 20, tzinfo=UTC))
    async with make_api_client(overrides=ContainerOverrides(clock=clock)) as client:
        await client.post("/api/session", json={})
        for _ in range(7):
            clock.advance(timedelta(hours=23))
            assert (await client.get("/api/session")).status_code == 200
        clock.advance(timedelta(hours=8))
        assert (await client.get("/api/session")).status_code == 401


async def test_idle_expiry_never_outlives_absolute_expiry(
    make_api_client: ApiClientFactory,
) -> None:
    clock: FakeClock = FakeClock(datetime(2026, 11, 20, tzinfo=UTC))
    async with make_api_client(overrides=ContainerOverrides(clock=clock)) as client:
        await client.post("/api/session", json={})
        for _ in range(7):
            clock.advance(timedelta(hours=23))
            body: dict[str, str] = (await client.get("/api/session")).json()
    assert body["idle_expires_at"] == body["absolute_expires_at"]


async def test_missing_forged_and_expired_sessions_get_the_same_401(
    make_api_client: ApiClientFactory,
) -> None:
    clock: FakeClock = FakeClock(datetime(2026, 11, 20, tzinfo=UTC))
    async with make_api_client(overrides=ContainerOverrides(clock=clock)) as client:
        missing: httpx.Response = await client.get("/api/session")
        client.cookies.set("sh_session", new_token())
        forged: httpx.Response = await client.get("/api/session")
        client.cookies.clear()
        await client.post("/api/session", json={})
        clock.advance(timedelta(days=8))
        expired: httpx.Response = await client.get("/api/session")
    for response in (missing, forged, expired):
        assert response.status_code == 401
        assert response.json() == SESSION_REQUIRED_BODY


async def test_forged_cookie_is_rejected(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.set("sh_session", new_token())
    assert (await api_client.get("/api/session")).status_code == 401


async def test_stale_cookie_is_replaced_by_a_new_session(
    make_api_client: ApiClientFactory,
) -> None:
    async with make_api_client() as client:
        client.cookies.set("sh_session", new_token())
        response: httpx.Response = await client.post("/api/session", json={})
        assert response.status_code == 200 and "sh_session=" in response.headers["set-cookie"]
        assert (await client.get("/api/session")).status_code == 200


async def test_failed_verification_creates_no_session(make_api_client: ApiClientFactory) -> None:
    overrides: ContainerOverrides = ContainerOverrides(verifier=RejectingVerifier())
    async with make_api_client(overrides=overrides) as client:
        response: httpx.Response = await client.post("/api/session", json={})
    assert response.status_code == 403
    assert response.json() == {"code": "verification_failed"}
    assert "set-cookie" not in response.headers
