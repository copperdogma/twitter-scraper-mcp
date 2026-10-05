"""Search discovery must use the existing session, and failures must be MCP errors."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import server as srv


@pytest.fixture(scope='session')
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_query_discovery_reuses_session_and_caches(monkeypatch):
    monkeypatch.setattr(srv, '_SEARCH_TIMELINE_QUERY_ID_CACHE', None)
    bundle = 'https://abs.twimg.com/responsive-web/client-web/main.fixture.js'
    page = httpx.Response(200, text=f'<script src="{bundle}"></script>', request=httpx.Request('GET', 'https://x.com/search'))
    script = httpx.Response(200, text='queryId:"current-id",operationName:"SearchTimeline"', request=httpx.Request('GET', bundle))
    http = SimpleNamespace(get=AsyncMock(side_effect=[page, script]))
    client = SimpleNamespace(http=http, _user_agent='fixture', language='en-US')
    assert await srv._get_search_timeline_query_id(client) == 'current-id'
    assert await srv._get_search_timeline_query_id(client) == 'current-id'
    assert http.get.await_count == 2
    assert http.get.await_args_list[0].kwargs['follow_redirects'] is True
    assert http.get.await_args_list[1].args[0] == bundle


@pytest.mark.anyio
async def test_login_page_does_not_cache_a_query_id(monkeypatch):
    monkeypatch.setattr(srv, '_SEARCH_TIMELINE_QUERY_ID_CACHE', None)
    page = httpx.Response(200, text='<script src="https://abs.twimg.com/x-web/x-web/entry-client-logged-out.js"></script>', request=httpx.Request('GET', 'https://x.com/i/jf/onboarding/web'))
    client = SimpleNamespace(http=SimpleNamespace(get=AsyncMock(return_value=page)), _user_agent='fixture', language='en-US')
    with pytest.raises(ValueError, match='check session access'):
        await srv._get_search_timeline_query_id(client)
    assert srv._SEARCH_TIMELINE_QUERY_ID_CACHE is None


@pytest.mark.anyio
async def test_expired_cache_refreshes_and_missing_operation_is_error(monkeypatch):
    monkeypatch.setattr(srv, '_SEARCH_TIMELINE_QUERY_ID_CACHE', ('old', -10000))
    bundle = 'https://abs.twimg.com/responsive-web/client-web/main.fixture.js'
    responses = [httpx.Response(200, text=bundle, request=httpx.Request('GET', 'https://x.com/search')), httpx.Response(200, text='other operation', request=httpx.Request('GET', bundle))]
    client = SimpleNamespace(http=SimpleNamespace(get=AsyncMock(side_effect=responses)), _user_agent='fixture', language='en-US')
    with pytest.raises(ValueError, match='query id'):
        await srv._get_search_timeline_query_id(client)


@pytest.mark.anyio
@pytest.mark.parametrize('payload,status', [({'errors': [{'message': 'session rejected', 'code': 32}]}, 200), ({'errors': [{'message': 'rate limited', 'code': 88}]}, 429)])
async def test_search_provider_errors_are_not_empty_success(monkeypatch, payload, status):
    monkeypatch.setattr(srv, '_get_search_timeline_query_id', AsyncMock(return_value='current'))
    response = httpx.Response(status, json=payload, request=httpx.Request('POST', 'https://x.com/i/api/graphql/current/SearchTimeline'))
    client = SimpleNamespace(http=SimpleNamespace(request=AsyncMock(return_value=response)), _base_headers={})
    with pytest.raises(ValueError, match=payload['errors'][0]['message']):
        await srv._request_search_timeline(client, 'from:OpenAI since:2026-10-04', 'Latest', 30)
    kwargs = client.http.request.await_args.kwargs
    assert kwargs['json']['variables'] == {'rawQuery': 'from:OpenAI since:2026-10-04', 'product': 'Latest', 'count': 30, 'querySource': 'typed_query'}


@pytest.mark.anyio
@pytest.mark.parametrize('text,is_error', [('Error: failed search discovery', True), ('{"error":"failed detail"}', True), ('[]', False), ('[{"id":"123","text":"Error: quoted post"}]', False)])
async def test_mcp_error_flag(monkeypatch, text, is_error):
    instance = srv.TwitterMCPServer()
    monkeypatch.setattr(instance, 'execute_tool', AsyncMock(return_value=[srv.types.TextContent(type='text', text=text)]))
    request = srv.types.CallToolRequest(method='tools/call', params=srv.types.CallToolRequestParams(name='search_tweets', arguments={'query':'from:OpenAI'}))
    result = await instance.server.request_handlers[srv.types.CallToolRequest](request)
    assert result.root.isError is is_error
    assert result.root.content[0].text == text


@pytest.mark.anyio
async def test_malformed_search_response_raises(monkeypatch):
    monkeypatch.setattr(srv, '_request_search_timeline', AsyncMock(return_value={'data': {}}))
    with pytest.raises(ValueError, match='missing instructions'):
        await srv.TwitterMCPServer()._search_tweets(None, 'from:OpenAI')
