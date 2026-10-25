import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from simple_uploader.core import Item, UploaderError, upload


class S3Server:
    """An HTTP server that independently verifies each incoming SigV4 PUT."""
    def __enter__(self):
        owner = self
        self.requests = []
        self.status = 200

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_PUT(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                error = None
                try:
                    self.verify(body)
                except Exception as exc:
                    error = str(exc)
                owner.requests.append((self.path, self.headers, body, error))
                code = 403 if error else owner.status
                self.send_response(code)
                if code == 307:
                    self.send_header('Location', '/redirected')
                self.end_headers()
                if code != 200:
                    self.wfile.write(b'<Error><Message>Test bucket denied access</Message></Error>')

            def verify(self, body):
                authorization = self.headers['Authorization']
                algorithm, values = authorization.split(' ', 1)
                params = dict(value.split('=', 1) for value in values.split(', '))
                credential, scope = params['Credential'].split('/', 1)
                assert algorithm == 'AWS4-HMAC-SHA256'
                assert credential == 'test-key'
                date, region, service, final = scope.split('/')
                assert service == 's3' and final == 'aws4_request'
                digest = hashlib.sha256(body).hexdigest()
                assert self.headers['X-Amz-Content-Sha256'] == digest, 'Body hash mismatch'
                signed = params['SignedHeaders'].split(';')
                canonical = ''.join(name + ':' + ' '.join(self.headers[name].split()) + '\n' for name in signed)
                canonical_request = '\n'.join(('PUT', self.path, '', canonical, params['SignedHeaders'], digest))
                string_to_sign = '\n'.join((algorithm, self.headers['X-Amz-Date'], scope,
                                           hashlib.sha256(canonical_request.encode()).hexdigest()))
                key = b'AWS4test-secret'
                for value in (date, region, service, final):
                    key = hmac.digest(key, value.encode(), 'sha256')
                expected = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
                assert hmac.compare_digest(params['Signature'], expected), 'Signature mismatch'

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cfg = {'S3_ENDPOINT': f'http://127.0.0.1:{self.server.server_port}/api%20root',
                    'S3_BUCKET': 'test-bucket', 'S3_ACCESS_KEY_ID': 'test-key',
                    'S3_SECRET_ACCESS_KEY': 'test-secret', 'S3_REGION': 'auto',
                    'S3_PUBLIC_URL_BASE': 'https://files.example.test'}
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class UploadTests(unittest.TestCase):
    def test_signed_put_streams_exact_binary_and_escaped_paths(self):
        with S3Server() as server, tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'movie.mp4'
            data = bytes(range(256)) * 12000
            path.write_bytes(data)
            server.cfg.update(S3_ACL='public-read', S3_SESSION_TOKEN='temporary-token')
            url = upload(server.cfg, Item(path, path.name, 'video/mp4'), 'uploads/hello #雪.mp4')
            self.assertEqual(url, 'https://files.example.test/uploads/hello%20%23%E9%9B%AA.mp4')
            request_path, headers, received, error = server.requests[0]
            self.assertIsNone(error)
            self.assertEqual(received, data)
            self.assertEqual(headers['Content-Type'], 'video/mp4')
            self.assertEqual(headers['x-amz-security-token'], 'temporary-token')
            self.assertEqual(headers['x-amz-acl'], 'public-read')
            self.assertNotIn('Transfer-Encoding', headers)
            self.assertEqual(request_path, '/api%20root/test-bucket/uploads/hello%20%23%E9%9B%AA.mp4')

    def test_markdown_upload_and_unique_names(self):
        with S3Server() as server, tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'text'
            path.write_text('# Hello\n\nMarkdown: **bold**\n')
            server.cfg['S3_PATH_PREFIX'] = 'team/notes'
            item = Item(path, 'clipboard.md', 'text/markdown;charset=utf-8')
            first = upload(server.cfg, item)
            second = upload(server.cfg, item)
            self.assertNotEqual(first, second)
            self.assertIn('/team/notes/', first)
            self.assertTrue(first.endswith('-clipboard.md'))
            for _, headers, body, error in server.requests:
                self.assertIsNone(error)
                self.assertEqual(body, path.read_bytes())
                self.assertEqual(headers['Content-Type'], 'text/markdown;charset=utf-8')

    def test_http_failure_is_reported_and_redirect_is_not_followed(self):
        with S3Server() as server, tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data'
            path.write_bytes(b'payload')
            item = Item(path, 'file.bin', 'application/octet-stream')
            for code in (403, 307):
                server.status = code
                with self.assertRaisesRegex(UploaderError, f'HTTP {code}'):
                    upload(server.cfg, item)
            self.assertEqual(len(server.requests), 2)


if __name__ == '__main__':
    unittest.main()
