"""Small Server-Sent Events contract helpers; payloads never contain raw errors."""

import asyncio
import json
import logging

import anyio
from fastapi.responses import StreamingResponse

from backend.app.services.search import SearchFailure


MESSAGES = {
    'routing': '질문 유형을 확인하고 있어요.',
    'searching': '관련 장면을 검색 중이에요.',
    'validating': '원문과 시점을 확인하고 있어요.',
    'replanning': '다른 표현으로 다시 찾고 있어요.',
}


def encode_event(event: str, data: dict) -> str:
    """Encode one UTF-8 SSE frame with a single JSON data field."""
    payload = json.dumps(data,ensure_ascii=False,separators=(',',':'))
    return f'event: {event}\ndata: {payload}\n\n'


def public_error(exc: SearchFailure) -> tuple[str,str]:
    """Return a stable error code and safe Korean message."""
    if exc.code == 'search_busy':
        message = '이전 검색을 마무리 중입니다. 잠시 후 다시 시도해 주세요.'
    elif exc.code.startswith('model_'):
        message = '의미 검증 모델에 오류가 발생했습니다. 다시 시도해 주세요.'
    elif exc.code == 'agent_failure':
        message = '검색 처리 중 오류가 발생했습니다. 다시 시도해 주세요.'
    else:
        message = '검색 도구에 오류가 발생했습니다. 다시 시도해 주세요.'
    return exc.code,message


class StreamOwner:
    """Keep the reservation until the producer terminates, even after disconnect."""
    cleanup_timeout = 5

    def __init__(self, release, tasks=None):
        self.release = release
        self.tasks = tasks if tasks is not None else set()
        self.task = None
        self.closed = False
        self.released = False

    def start(self, coroutine):
        self.task = asyncio.create_task(coroutine)
        self.tasks.add(self.task)

    def _release(self, task=None):
        if task is not None:
            self.tasks.discard(task)
            if not task.cancelled():
                task.exception()  # Retrieve a late exception without exposing it.
        if not self.released:
            self.released = True
            self.release()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.task is None:
            self._release()
            return
        if not self.task.done():
            self.task.cancel()
        self.task.add_done_callback(self._release)
        # asyncio.wait does not propagate the cleanup deadline into the producer.
        with anyio.CancelScope(shield=True):
            done, _ = await asyncio.wait({self.task}, timeout=self.cleanup_timeout)
        if done:
            self._release(self.task)
        else:
            logging.getLogger(__name__).warning('stream_cleanup_timeout busy_retained=true')


class ManagedStreamingResponse(StreamingResponse):
    """Run cleanup even when the body iterator never receives its first anext."""
    def __init__(self, *args, owner: StreamOwner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.owner.close()
