"""
JobPilot events — in-memory pub/sub feeding the SSE log stream.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from loguru import logger


@dataclass
class Event:
    """A single log event."""
    level: str
    message: str
    platform: str | None = None
    run_id: int | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "platform": self.platform,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
        }


class EventBus:
    """
    Simple in-memory pub/sub for SSE log streaming.
    Subscribers get an async generator that yields events.
    Thread-safe via asyncio primitives.
    """

    def __init__(self, max_history: int = 500) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._history: list[Event] = []
        self._max_history = max_history
        self._lock = asyncio.Lock()

    async def publish(
        self,
        message: str,
        level: str = "info",
        platform: str | None = None,
        run_id: int | None = None,
    ) -> Event:
        """Publish an event to all subscribers."""
        event = Event(
            level=level,
            message=message,
            platform=platform,
            run_id=run_id,
        )
        async with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            dead: list[asyncio.Queue[Event]] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

        # Also log via loguru
        log_fn = getattr(logger, level, logger.info)
        prefix = f"[{platform}] " if platform else ""
        log_fn(f"{prefix}{message}")
        return event

    async def subscribe(self, include_history: bool = True) -> AsyncGenerator[Event, None]:
        """
        Subscribe to the event stream. Yields events as they arrive.
        If include_history is True, replays recent events first.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        async with self._lock:
            if include_history:
                for evt in self._history:
                    queue.put_nowait(evt)
            self._subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                if queue in self._subscribers:
                    self._subscribers.remove(queue)

    def get_history(self, limit: int = 100) -> list[Event]:
        """Return the most recent events from history."""
        return self._history[-limit:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Global event bus instance
event_bus = EventBus()
