from __future__ import annotations

import asyncio


async def await_thread_task[T](task: asyncio.Task[T]) -> T:
    """Join a resource-owning thread through repeated cancellation before propagating it."""
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result
