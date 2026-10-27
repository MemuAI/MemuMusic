import unittest
from unittest.mock import patch

import httpx
from starlette.requests import Request

from memumusic.music import online_audio


class OnlineAudioTest(unittest.IsolatedAsyncioTestCase):
    async def test_audio_range_and_reject_untrusted_hosts(self):
        info = {'duration': 5, 'formats': [
            {'url': 'https://example.com/audio', 'acodec': 'aac', 'vcodec': 'none', 'protocol': 'https'},
            {'url': 'https://media.googlevideo.com/audio', 'acodec': 'aac', 'vcodec': 'none', 'protocol': 'https', 'ext': 'm4a'}]}
        with patch('memumusic.music.downloader.Runner') as runner:
            runner.return_value.json.return_value = info
            result = online_audio.resolve('https://www.youtube.com/watch?v=abc', '', '/audio')
        token = result['url'].rsplit('/', 1)[-1]
        self.assertFalse(online_audio._allowed('https://googlevideo.com.attacker.example/audio'))
        self.assertFalse(online_audio._allowed('http://127.0.0.1/audio'))
        async def handler(request):
            self.assertEqual(request.headers['range'], 'bytes=0-3')
            return httpx.Response(206, headers={'content-range': 'bytes 0-3/4', 'content-type': 'audio/mp4'}, content=b'test')
        real = httpx.AsyncClient
        with patch.object(online_audio.httpx, 'AsyncClient', side_effect=lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': [(b'range', b'bytes=0-3')]})
            response = await online_audio.stream(token, request, cors=True)
            body = b''.join([part async for part in response.body_iterator])
        self.assertEqual((response.status_code, body), (206, b'test'))
        self.assertEqual(response.headers['access-control-allow-origin'], '*')
        self.assertEqual((await online_audio.stream('invalid', request)).status_code, 404)


if __name__ == '__main__':
    unittest.main()
