import json
import time
from collections import defaultdict, deque
from typing import Protocol

from redis.asyncio import Redis

from agentlab.models import Message


class SessionMemory(Protocol):
    async def load(self, session_id: str, limit: int) -> list[Message]: ...
    async def append(self, session_id: str, user: str, assistant: str) -> None: ...
    async def health(self) -> bool: ...
    async def close(self) -> None: ...


class InMemorySessionMemory:
    def __init__(self, max_messages: int = 12) -> None:
        self.max_messages = max_messages
        self._data: dict[str, deque[Message]] = defaultdict(
            lambda: deque(maxlen=max_messages * 2)
        )

    async def load(self, session_id: str, limit: int) -> list[Message]:
        return list(self._data[session_id])[-limit:]

    async def append(self, session_id: str, user: str, assistant: str) -> None:
        now = time.time()
        self._data[session_id].append(Message("user", user, now))
        self._data[session_id].append(Message("assistant", assistant, now))

    async def health(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class RedisSessionMemory:
    def __init__(
        self, redis: Redis, max_messages: int = 12, ttl_seconds: int = 86400
    ) -> None:
        self.redis = redis
        self.max_messages = max_messages
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(session_id: str) -> str:
        return f"session:{session_id}:messages"

    async def load(self, session_id: str, limit: int) -> list[Message]:
        raw = await self.redis.lrange(self._key(session_id), -limit, -1)
        return [Message(**json.loads(item)) for item in raw]

    async def append(self, session_id: str, user: str, assistant: str) -> None:
        now = time.time()
        key = self._key(session_id)
        items = [
            json.dumps({"role": "user", "content": user, "ts": now}),
            json.dumps({"role": "assistant", "content": assistant, "ts": now}),
        ]
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.rpush(key, *items)
            pipe.ltrim(key, -self.max_messages * 2, -1)
            pipe.expire(key, self.ttl_seconds)
            await pipe.execute()

    async def health(self) -> bool:
        try:
            return bool(await self.redis.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self.redis.aclose()
