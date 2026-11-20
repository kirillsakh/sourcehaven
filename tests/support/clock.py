from datetime import datetime, timedelta


class FakeClock:
    """A settable clock that returns the same timezone-aware instant until advanced."""

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._now: datetime = now

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta
