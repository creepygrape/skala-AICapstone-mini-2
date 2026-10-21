"""Optional LangSmith reporting (WISH_LANGSMITH_ENABLED=1 plus LANGSMITH_API_KEY).

When enabled, the agent run is traced (graph nodes plus every LLM call, with the question
and candidate subtitle excerpts; ADR-0008). One batching client is shared with the
request-summary reporter; both are off by default.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
import asyncio

from langsmith import Client

logger = logging.getLogger('wish_finder.agent')


def publish_summary(record, client=None):
    """Called off the event loop only after explicit opt-in plus credentials."""
    if os.getenv('WISH_LANGSMITH_ENABLED') != '1' or not os.getenv('LANGSMITH_API_KEY'):
        return
    owned = client is None
    try:
        client = client or Client(auto_batch_tracing=False,timeout_ms=2000)
        end = datetime.now(timezone.utc)
        client.create_run(name='wish-finder-agent-summary',run_type='chain',
            id=record['request_id'],inputs={'source':'metadata_only'},
            outputs=record,start_time=end-timedelta(seconds=record.get('seconds',0)),end_time=end,
            project_name=os.getenv('LANGSMITH_PROJECT','wish-finder'))
    except Exception:
        logger.warning('langsmith_summary_failed request_id=%s',record['request_id'])
    finally:
        if owned and client is not None:
            try:
                client.close()
            except Exception:
                logger.warning('langsmith_close_failed request_id=%s',record['request_id'])


class TelemetryPublisher:
    """Lifespan-owned, non-blocking metadata queue with one reusable client."""
    def __init__(self):
        self.enabled = os.getenv('WISH_LANGSMITH_ENABLED') == '1' and bool(os.getenv('LANGSMITH_API_KEY'))
        self.queue = asyncio.Queue(maxsize=100)
        self.task = None
        self.client = None

    async def start(self):
        if self.enabled:
            try:
                # Batched in a background thread so traces never block a request.
                self.client = await asyncio.to_thread(Client,timeout_ms=2000)
                self.task = asyncio.create_task(self._worker())
            except Exception:
                logger.warning('langsmith_start_failed')
                self.client = None
                self.task = None
                self.enabled = False
        return self

    def submit(self, record):
        if not self.enabled:
            return
        try:
            self.queue.put_nowait(record)
        except asyncio.QueueFull:
            logger.warning('langsmith_queue_full request_id=%s',record['request_id'])

    async def _worker(self):
        while True:
            record = await self.queue.get()
            try:
                await asyncio.to_thread(publish_summary,record,self.client)
            finally:
                self.queue.task_done()

    async def close(self):
        if self.task is None and self.client is None:
            return
        if self.task is not None:
            try:
                async with asyncio.timeout(3):
                    await self.queue.join()
            except TimeoutError:
                logger.warning('langsmith_queue_shutdown_timeout')
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        if self.client is not None:
            try:
                flush = getattr(self.client,'flush',None)
                if flush is not None:
                    await asyncio.to_thread(flush)
                await asyncio.to_thread(self.client.close)
            except Exception:
                logger.warning('langsmith_close_failed')
            self.client = None
        self.enabled = False
