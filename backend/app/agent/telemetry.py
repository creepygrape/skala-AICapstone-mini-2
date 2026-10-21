"""Optional metadata-only LangSmith reporting; no raw query/source uploads."""

import logging
import os
from datetime import datetime, timedelta, timezone

from langsmith import Client

logger = logging.getLogger('wish_finder.agent')


def publish_summary(record):
    """Called off the event loop only after explicit opt-in plus credentials."""
    if os.getenv('WISH_LANGSMITH_ENABLED') != '1' or not os.getenv('LANGSMITH_API_KEY'):
        return
    client = None
    try:
        client = Client(auto_batch_tracing=False,timeout_ms=2000)
        end = datetime.now(timezone.utc)
        client.create_run(name='wish-finder-agent-summary',run_type='chain',
            id=record['request_id'],inputs={'source':'metadata_only'},
            outputs=record,start_time=end-timedelta(seconds=record.get('seconds',0)),end_time=end,
            project_name=os.getenv('LANGSMITH_PROJECT','wish-finder'))
    except Exception:
        logger.warning('langsmith_summary_failed request_id=%s',record['request_id'])
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning('langsmith_close_failed request_id=%s',record['request_id'])
