import fakeredis.aioredis
import pytest

from agentlab.memory import InMemorySessionMemory, RedisSessionMemory


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_redis_append_and_load(fake_redis):
    memory = RedisSessionMemory(fake_redis, max_messages=4, ttl_seconds=60)
    await memory.append("s1", "你好", "您好，请问有什么可以帮您？")
    await memory.append("s1", "退款多久到账", "一般 3 到 7 个工作日。")
    messages = await memory.load("s1", 10)
    assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[-1].content == "一般 3 到 7 个工作日。"


async def test_redis_trims_to_max_pairs(fake_redis):
    memory = RedisSessionMemory(fake_redis, max_messages=2, ttl_seconds=60)
    for i in range(5):
        await memory.append("s1", f"u{i}", f"a{i}")
    messages = await memory.load("s1", 20)
    assert len(messages) == 4
    assert messages[0].content == "u3"


async def test_redis_isolates_sessions(fake_redis):
    memory = RedisSessionMemory(fake_redis, max_messages=4, ttl_seconds=60)
    await memory.append("a", "qa", "aa")
    await memory.append("b", "qb", "ab")
    assert (await memory.load("a", 10))[0].content == "qa"
    assert (await memory.load("b", 10))[0].content == "qb"


async def test_in_memory_memory_works():
    memory = InMemorySessionMemory(max_messages=2)
    await memory.append("s", "u1", "a1")
    await memory.append("s", "u2", "a2")
    messages = await memory.load("s", 10)
    assert len(messages) == 4
    assert await memory.health() is True
