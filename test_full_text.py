"""Preserve note tweet bodies across raw search, direct lookup, and replies."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import pytest
import server as srv
from twikit.tweet import Tweet


@pytest.fixture(scope='session')
def anyio_backend():
    return 'asyncio'


def payload(text='preview', full='complete body '*50):
    result = {'rest_id':'2107164653147340988', 'legacy':{'full_text':text},
              'core':{'user_results':{'result':{'core':{'screen_name':'OpenAI','name':'OpenAI'}}}}}
    if full is not None:
        result['note_tweet'] = {'note_tweet_results':{'result':{'text':full}}}
    return result


@pytest.mark.parametrize('full', ['complete body '*50, None, ''])
def test_search_prefers_complete_note_with_legacy_fallback(full):
    result=payload(full=full)
    entry={'content':{'itemContent':{'tweet_results':{'result':result}}}}
    assert srv.TwitterMCPServer()._search_entry_to_result(entry)['text'] == (full or 'preview')


@pytest.mark.anyio
async def test_complete_text_across_exact_lookup_detail_and_replies(monkeypatch):
    result=payload()
    result['legacy'].update(created_at='now',favorite_count=1,retweet_count=2,reply_count=3,
                            lang='en',is_quote_status=False)
    user=SimpleNamespace(screen_name='OpenAI',name='OpenAI',id='123')
    tweet=Tweet(None,result,user)
    reply_result=payload(full='complete reply '*50)
    reply_result['legacy'].update(result['legacy'])
    reply_result['legacy']['full_text']='reply preview'
    reply=Tweet(None,reply_result,user)
    tweet.replies=[reply]
    client=SimpleNamespace(get_tweet_by_id=AsyncMock(return_value=tweet))
    instance=srv.TwitterMCPServer()
    monkeypatch.setattr(instance,'_ensure_client',AsyncMock(return_value=client))
    monkeypatch.setenv('TWITTER_CT0','placeholder')
    monkeypatch.setenv('TWITTER_AUTH_TOKEN','placeholder')
    expected=result['note_tweet']['note_tweet_results']['result']['text']
    for query in ['2107164653147340988','https://x.com/OpenAI/status/2107164653147340988']:
        data=await instance._search_tweets(client,query)
        assert data[0]['text'] == expected
    data=await instance._get_tweet_by_id(client,'2107164653147340988')
    assert data['text'] == expected
    out=await instance.execute_tool('get_tweet_replies',{'tweet_id':'2107164653147340988','count':3})
    data=json.loads(out[0].text)
    assert data['original_tweet']['text'] == expected
    assert data['replies'][0]['text'] == 'complete reply '*50
