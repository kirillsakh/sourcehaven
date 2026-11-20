import asyncio
from collections.abc import Awaitable, Callable
from typing import Final

DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0
POLL_INTERVAL_SECONDS: Final[float] = 0.02


async def eventually[T](
    probe: Callable[[], Awaitable[T]],
    *,
    until: Callable[[T], bool],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> T:
    """Call `probe` until its result satisfies `until`, and return that result.

    Raises:
        TimeoutError: If no result satisfies `until` within `timeout` seconds.
    """
    async with asyncio.timeout(timeout):
        while True:
            value: T = await probe()
            if until(value):
                return value
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
