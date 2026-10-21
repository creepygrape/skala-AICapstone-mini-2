"""Small Server-Sent Events contract helpers; payloads never contain raw errors."""

import json

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
