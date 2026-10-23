import http.client
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import npm_name


class NpmNameTest(unittest.TestCase):
    def setUp(self):
        transport = patch('npm_name.http.client.HTTPSConnection')
        self.transport = transport.start()
        self.addCleanup(transport.stop)
        self.connection = self.transport.return_value
        self.response = self.connection.getresponse.return_value

    def test_404_is_available_using_only_public_get_with_bounded_timeout(self):
        self.response.status = 404
        with patch.dict('os.environ', {'NPM_TOKEN': 'secret',
                                      'NODE_AUTH_TOKEN': 'secret',
                                      'npm_config_registry': 'https://private.invalid',
                                      'HTTPS_PROXY': 'https://user:secret@proxy.invalid'}):
            self.assertIsNone(npm_name.require_available('dsh-new'))
        self.transport.assert_called_once_with('registry.npmjs.org', timeout=10)
        self.connection.request.assert_called_once_with(
            'GET', '/dsh-new', headers={'Accept': 'application/json'})
        self.response.read.assert_not_called()
        self.response.close.assert_called_once_with()
        self.connection.close.assert_called_once_with()

    def test_200_is_occupied_without_reading_owner_or_metadata(self):
        self.response.status = 200
        self.response.read.return_value = b'{"maintainers":[{"name":"o"}]}'
        with self.assertRaises(ValueError) as caught:
            npm_name.require_available('dsh-new')
        self.assertEqual(str(caught.exception), npm_name.OCCUPIED)
        self.response.read.assert_not_called()
        self.connection.close.assert_called_once_with()

    def test_every_other_status_fails_closed_without_remote_details(self):
        for status in (201, 204, 301, 302, 307, 308, 400, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.response.status = status
                self.response.reason = 'remote secret detail'
                with self.assertRaises(ValueError) as caught:
                    npm_name.require_available('dsh-new')
                self.assertEqual(str(caught.exception), npm_name.UNAVAILABLE)
        self.response.read.assert_not_called()
        self.assertEqual(self.transport.call_count, 12)  # no redirects or retries

    def test_network_timeout_and_protocol_errors_are_fixed_and_closed(self):
        for stage in ('request', 'getresponse'):
            for error in (TimeoutError('secret'), OSError('secret'),
                          http.client.HTTPException('secret')):
                with self.subTest(stage=stage, error=type(error).__name__):
                    self.connection.reset_mock()
                    getattr(self.connection, stage).side_effect = error
                    with self.assertRaises(ValueError) as caught:
                        npm_name.require_available('dsh-new')
                    self.assertEqual(str(caught.exception), npm_name.UNAVAILABLE)
                    self.assertTrue(caught.exception.__suppress_context__)
                    self.connection.close.assert_called_once_with()
                    getattr(self.connection, stage).side_effect = None

    def test_package_name_is_a_single_encoded_path_segment(self):
        self.response.status = 404
        npm_name.require_available('@scope/dsh-new')
        self.connection.request.assert_called_once_with(
            'GET', '/%40scope%2Fdsh-new', headers={'Accept': 'application/json'})


if __name__ == '__main__':
    unittest.main()
