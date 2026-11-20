from typing import Protocol


class HumanVerifier(Protocol):
    async def verify(self, token: str | None, remote_ip: str | None) -> bool:
        """Return whether `token` proves that a human is creating the session."""
        ...


class AllowAllVerifier:
    """Accepts every request; used when `human_verification` is `disabled`."""

    async def verify(self, token: str | None, remote_ip: str | None) -> bool:
        return True
