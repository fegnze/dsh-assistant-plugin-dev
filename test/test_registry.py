import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import registry as r


class RegistryTest(unittest.TestCase):
    def call(self):
        return r.verify('dsh-test', '1.0.0', 'https://registry.npmjs.org/', 'owner/dsh-test')

    def test_missing(self):
        error = urllib.error.HTTPError('url', 404, 'missing', {}, None)
        with patch.object(r.urllib.request, 'urlopen', side_effect=error):
            self.assertEqual(self.call()['status'], 'not_visible')

    def test_network_is_not_missing(self):
        with patch.object(r.urllib.request, 'urlopen', side_effect=urllib.error.URLError('offline')):
            with self.assertRaisesRegex(ValueError, 'unknown'):
                self.call()

    def test_wrong_package(self):
        with patch.object(r.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"name":"wrong"}')):
            with self.assertRaisesRegex(ValueError, 'identity'):
                self.call()

    def test_exact_version(self):
        data = {'name': 'dsh-test', 'version': '1.0.0', 'repository': {'url': 'git+https://github.com/owner/dsh-test.git'}}
        with patch.object(r.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(data).encode())):
            self.assertEqual(self.call()['status'], 'published')
