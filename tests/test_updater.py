from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from memumusic import updater as module
from memumusic.updater_routes import register_update_routes


def release(tag='v1.0.0-preview.3', *, prerelease=True, payload=b'MZ' + b'a' * 1000):
    checksum = (hashlib.sha256(payload).hexdigest() + '  ' + module.INSTALLER_NAME + '\n').encode()
    def asset(name, data):
        return {'name': name, 'state': 'uploaded', 'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest(),
                'browser_download_url': module._public_url(tag, name)}
    return {'tag_name': tag, 'draft': False, 'prerelease': prerelease, 'name': tag, 'published_at': '2026-10-27T00:00:00Z',
            'assets': [asset(module.INSTALLER_NAME, payload), asset(module.CHECKSUM_NAME, checksum)]}, checksum


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.payload = b'MZ' + b'x' * 1000
        self.release, self.checksum = release(payload=self.payload)
        self.requests = []
        self.tamper_checksum = False
        self.tamper_download = False
        self.bad_redirect = False
        self.offline = False
        self.now = 500000.0

        def handler(request):
            self.requests.append(str(request.url))
            if self.offline:
                raise httpx.ConnectError('offline', request=request)
            if request.url.host == 'api.github.com':
                return httpx.Response(200, json=[self.release])
            if request.url.host == 'github.com':
                target = 'https://attacker.invalid/evil' if self.bad_redirect else 'https://release-assets.githubusercontent.com/' + request.url.path.rsplit('/', 1)[-1]
                return httpx.Response(302, headers={'Location': target})
            if request.url.host == 'release-assets.githubusercontent.com':
                data = self.checksum if request.url.path.endswith('.sha256') else self.payload
                if self.tamper_checksum and request.url.path.endswith('.sha256'):
                    data = b'0' * 64 + b'  MemuMusic-Setup.exe\n'
                if self.tamper_download and not request.url.path.endswith('.sha256'):
                    data = b'MZ' + b'z' * 1000
                return httpx.Response(200, content=data)
            raise AssertionError('Untrusted redirect reached: ' + str(request.url))
        self.transport = httpx.MockTransport(handler)
        self.manager = module.Updater(root=self.root, current_version='1.0.0-preview.2',
            client_factory=lambda: httpx.Client(transport=self.transport), clock=lambda: self.now)
        self.manager.settings({'auto_download': False})

    def tearDown(self):
        self.assertTrue(self.manager._operation.acquire(timeout=5), 'update worker did not finish')
        self.manager._operation.release()
        self.temp.cleanup()

    def wait(self, phases, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.manager.status()
            if status['phase'] in phases and not status['busy']:
                return status
            time.sleep(.02)
        self.fail('Update did not finish: ' + str(self.manager.status()))

    def ready(self):
        self.assertTrue(self.manager.check())
        self.assertEqual(self.wait({'available', 'error'})['phase'], 'available')
        self.assertTrue(self.manager.download())
        self.assertEqual(self.wait({'ready', 'error'})['phase'], 'ready')

    def test_semver_and_preview_policy(self):
        self.assertEqual(module.version_key('1.0'), module.version_key('1.0.0'))
        self.assertLess(module.version_key('1.0'), module.version_key('1.0.1'))
        self.assertEqual(module.version_key('v1.0'), module.version_key('1.0.0'))
        self.assertLess(module.version_key('1.0.0-preview.9'), module.version_key('1.0.0-preview.10'))
        self.assertLess(module.version_key('1.0.0-preview.10'), module.version_key('1.0.0'))
        self.assertLess(module.version_key('1.0.0'), module.version_key('1.0.1-preview.1'))
        with self.assertRaises(ValueError):
            module.version_key('1.0.0-preview.01')
        self.assertIsNone(module.select_release([self.release], '1.0.0-preview.2', 'stable'))
        self.assertEqual(module.select_release([self.release], '1.0.0-preview.2', 'preview')['version'], '1.0.0-preview.3')
        stable, _ = release('v1.0.0', prerelease=False)
        self.assertEqual(module.select_release([self.release, stable], '1.0.0-preview.2', 'preview')['version'], '1.0.0')

    def test_check_download_restart_and_reverify(self):
        self.ready()
        self.assertEqual(self.manager.path.read_bytes(), self.payload)
        restored = module.Updater(root=self.root, current_version='1.0.0-preview.2', client_factory=self.manager.client_factory, clock=lambda: self.now)
        self.assertEqual(restored.status()['phase'], 'ready')
        original = getattr(sys, 'frozen', None)
        sys.frozen = True
        try:
            launched = []
            fake_dir = self.root / 'installed'
            with patch.object(module, 'registered_install_dir', return_value=fake_dir), patch.object(module, 'bootloader_pid', return_value=12345):
                self.manager.path.write_bytes(b'MZ' + b'z' * 1000)
                with self.assertRaises(module.UpdateError) as failure:
                    restored.install(launcher=lambda *args, **kwargs: launched.append((args, kwargs)))
                self.assertEqual(failure.exception.code, 'checksum_mismatch')
                self.assertFalse(launched)
                self.manager.path.write_bytes(self.payload)
                result = restored.install(launcher=lambda *args, **kwargs: launched.append((args, kwargs)))
            self.assertTrue(result['installed'])
            command = launched[0][0][0]
            self.assertIn('/MMWAITPID=12345', command)
            self.assertIn('/MMRELAUNCH=1', command)
            self.assertIn('/SILENT', command)
            self.assertIn('/DIR=' + str(fake_dir), command)
            self.assertNotIn('PYTHONPATH', launched[0][1]['env'])
        finally:
            if original is None:
                del sys.frozen
            else:
                sys.frozen = original

    def test_hash_mismatch_stops_and_removes_partial_file(self):
        self.assertTrue(self.manager.check())
        self.wait({'available'})
        self.tamper_download = True
        self.assertTrue(self.manager.download())
        self.assertEqual(self.wait({'error'})['error'], 'checksum_mismatch')
        self.assertFalse(self.manager.path.exists())
        self.assertFalse(list(self.manager.root.glob('*.part')))

    def test_tampered_checksum_and_untrusted_redirect_are_blocked(self):
        self.assertTrue(self.manager.check())
        self.wait({'available'})
        self.tamper_checksum = True
        self.assertTrue(self.manager.download())
        self.assertEqual(self.wait({'error'})['error'], 'checksum_mismatch')
        self.tamper_checksum = False
        self.bad_redirect = True
        self.assertTrue(self.manager.download())
        self.assertEqual(self.wait({'error'})['error'], 'untrusted_url')
        self.assertFalse(any('attacker.invalid' in url for url in self.requests))

    def test_automatic_frequency_settings_and_offline(self):
        self.manager.settings({'enabled': False, 'interval_hours': 6})
        self.assertFalse(self.manager.auto())
        self.assertEqual(self.requests, [])
        self.manager.settings({'enabled': True})
        self.assertTrue(self.manager.auto())
        self.assertEqual(self.wait({'available'})['phase'], 'available')
        count = len(self.requests)
        self.assertFalse(self.manager.auto())
        self.assertEqual(len(self.requests), count)
        self.now += 6 * 3600 + 1
        self.offline = True
        self.assertTrue(self.manager.auto())
        self.assertEqual(self.wait({'error'})['error'], 'network')
        self.assertTrue(self.manager.status()['config']['enabled'])

    def test_changed_release_blocks_cached_installer(self):
        self.ready()
        previous = getattr(sys, 'frozen', None)
        sys.frozen = True
        try:
            self.release, self.checksum = release('v1.0.0-preview.4', payload=self.payload)
            with self.assertRaises(module.UpdateError) as failure:
                self.manager.install(launcher=lambda *args, **kwargs: self.fail('installer launched'))
            self.assertEqual(failure.exception.code, 'update_changed')
        finally:
            if previous is None:
                del sys.frozen
            else:
                sys.frozen = previous

    def test_upgraded_version_does_not_offer_cached_old_release(self):
        self.ready()
        upgraded = module.Updater(root=self.root, current_version='1.0.0-preview.3',
            client_factory=self.manager.client_factory, clock=lambda: self.now)
        status = upgraded.status()
        self.assertEqual(status['phase'], 'idle')
        self.assertIsNone(status['latest'])
        self.assertEqual(status['last_checked'], 0)
        self.assertTrue(upgraded.check())
        deadline = time.monotonic() + 5
        while upgraded.status()['busy'] and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(upgraded.status()['phase'], 'up_to_date')
        self.assertIsNone(upgraded.status()['latest'])

    def test_routes_and_manual_check_when_disabled(self):
        app = FastAPI()
        register_update_routes(app, self.manager)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/updates/status').status_code, 200)
            self.assertEqual(client.post('/api/updates/settings', json={'enabled': False}).status_code, 200)
            self.assertFalse(client.post('/api/updates/auto').json()['started'])
            self.assertTrue(client.post('/api/updates/check').json()['started'])
            self.assertEqual(self.wait({'available'})['latest']['version'], '1.0.0-preview.3')
            self.assertEqual(client.post('/api/updates/install').status_code, 409)
            self.assertEqual(client.post('/api/updates/settings', json={'interval_hours': 1}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
