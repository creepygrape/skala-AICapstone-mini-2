"""WISH_LLM_BACKEND=openai: same JSON contract as Ollama via OpenAI Chat Completions.

Uses the existing httpx dependency (no openai SDK). Structured Outputs (strict
json_schema) constrain the shape; Pydantic still validates every response, so
keywords strict mode does not accept are stripped only from the transmitted schema.
Billing applies per request. The question and up to three candidate subtitle
excerpts with their 20s context are sent to OpenAI (ADR-0008). The API key and
request/response bodies are never logged.
"""

import copy

import httpx
from pydantic import ValidationError

from backend.app.agent.model import JsonLLM
from backend.app.services.search import SearchFailure

OPENAI_BASE_URL = 'https://api.openai.com/v1'
# Validated locally by Pydantic instead of being sent to strict mode.
UNSENT_KEYWORDS = {'minLength', 'maxLength', 'minItems', 'maxItems', 'default'}


def strict_schema(schema_model):
    """Pydantic JSON schema minus keywords strict Structured Outputs may reject."""
    def clean(node):
        if isinstance(node, dict):
            return {key: clean(value) for key, value in node.items() if key not in UNSENT_KEYWORDS}
        if isinstance(node, list):
            return [clean(value) for value in node]
        return node
    return clean(copy.deepcopy(schema_model.model_json_schema()))


class OpenAIModel(JsonLLM):
    backend = 'openai'

    def __init__(self, model='gpt-4o-mini', quality_model='gpt-4o', *, api_key=''):
        super().__init__(model, quality_model)
        self.api_key = api_key
        self.client = httpx.AsyncClient(base_url=OPENAI_BASE_URL, timeout=httpx.Timeout(20),
                                        headers={'Authorization': f'Bearer {api_key}'})

    async def ready(self):
        """Free metadata check: key is valid and both models are accessible."""
        if not self.api_key or self.api_key.startswith('sk-...'):
            raise SearchFailure('model_unavailable')
        try:
            for name in {self.model, self.quality_model}:
                response = await self.client.get(f'/models/{name}')
                if response.status_code == 404:
                    raise SearchFailure('model_not_installed')
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchFailure('model_unavailable') from exc

    async def close(self):
        await self.client.aclose()

    async def _ask(self, task, payload, schema, role='fast'):
        try:
            reply = await self.client.post('/chat/completions', json={
                'model': self.model_for(role),
                'messages': self.messages(task, payload),
                'temperature': 0, 'seed': 42, 'max_tokens': 512,
                'response_format': {'type': 'json_schema', 'json_schema': {
                    'name': schema.__name__, 'strict': True, 'schema': strict_schema(schema)}},
            })
            reply.raise_for_status()
            data = reply.json()
            usage = data.get('usage') or {}
            self.record_usage(usage.get('prompt_tokens'), usage.get('completion_tokens'))
            message = data['choices'][0]['message']
            if message.get('refusal'):
                raise ValueError('model refusal')
            return schema.model_validate_json(message['content'])
        except httpx.TimeoutException as exc:
            raise SearchFailure('model_timeout') from exc
        except httpx.HTTPError as exc:
            raise SearchFailure('model_unavailable') from exc
        except (ValidationError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise SearchFailure('model_invalid_response') from exc
