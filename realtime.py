import json
from typing import List, Optional

import redis.asyncio as aioredis
from fastapi import WebSocket

active_connections: dict[int, WebSocket] = {}
redis_pool: aioredis.ConnectionPool | None = None


def init_redis(url: str) -> None:
    global redis_pool
    redis_pool = aioredis.ConnectionPool.from_url(url, decode_responses=True)


async def close_redis() -> None:
    if redis_pool is not None:
        await redis_pool.disconnect()


def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=redis_pool)


async def invalidate_dialogs_cache(user_id: int):
    r = get_redis()
    await r.delete(f"user:{user_id}:dialogs")


async def get_cached_dialogs(user_id: int) -> Optional[List[dict]]:
    r = get_redis()
    cached = await r.get(f"user:{user_id}:dialogs")
    if cached:
        return json.loads(cached)
    return None


async def set_cached_dialogs(user_id: int, dialogs_data: List[dict], ttl: int = 60):
    r = get_redis()
    await r.setex(f"user:{user_id}:dialogs", ttl, json.dumps(dialogs_data))


async def publish_to_user(user_id: int, payload: dict):
    r = get_redis()
    await r.publish(f"user:{user_id}", json.dumps(payload))


async def listen_for_messages(user_id: int, websocket: WebSocket):
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"user:{user_id}")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                if websocket.client_state.value == 1:
                    await websocket.send_json(data)
    except Exception as e:
        print(f"Redis listener error for user {user_id}: {e}")
    finally:
        await pubsub.unsubscribe(f"user:{user_id}")
