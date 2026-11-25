"""Security hardening tests: headers, request IDs, authz boundaries, input fuzz."""
import http.client
import json
import os
import random
import sqlite3
import string
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

PG_TEST_URL = os.environ.get('NEXUS_TEST_DATABASE_URL') or os.environ.get('NEXUS_DATABASE_URL') or os.environ.get('NEXUS_DB_URL') or ''


def _is_pg_test():
    return server.nexus_db.is_postgres_url(PG_TEST_URL)


def _create_pg_test_db(base_url):
    from urllib.parse import urlsplit, urlunsplit
    import psycopg
    parts = urlsplit(base_url)
    dbname = 'nexus_sectest_' + uuid.uuid4().hex[:12]
    admin_url = urlunsplit((parts.scheme, parts.netloc, '/postgres', parts.query, parts.fragment))
    test_url = urlunsplit((parts.scheme, parts.netloc, '/' + dbname, parts.query, parts.fragment))
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE {dbname}')
    return test_url, dbname, admin_url


def _drop_pg_test_db(test_url, dbname, admin_url):
    import psycopg
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid <> pg_backend_pid()", (dbname,))
        conn.execute(f'DROP DATABASE IF EXISTS {dbname}')


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = ''
        self.csrf = ''

    def raw(self, path, method='GET', data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=60)
        hs = {'Content-Type': 'application/json', 'Cookie': self.cookie, 'X-CSRF-Token': self.csrf}
        if headers:
            hs.update(headers)
        body = json.dumps(data or {}) if method != 'GET' else None
        conn.request(method, '/api' + path, body, hs)
        response = conn.getresponse()
        payload = response.read()
        content_type = response.getheader('Content-Type', '')
        set_cookie = response.getheader('Set-Cookie')
        if set_cookie:
            self.cookie = set_cookie.split(';')[0]
        result = json.loads(payload) if 'json' in content_type else payload
        if isinstance(result, dict) and result.get('csrf'):
            self.csrf = result['csrf']
        out = {
            'status': response.status,
            'body': result,
            'headers': {k.lower(): v for k, v in response.getheaders()},
        }
        conn.close()
        return out

    def call(self, path, method='GET', data=None, headers=None):
        r = self.raw(path, method, data, headers)
        return r['status'], r['body']

    def ok(self, path, method='GET', data=None, headers=None):
        status, result = self.call(path, method, data, headers)
        if status != 200:
            raise AssertionError(f'{method} {path} -> {status}: {result}')
        return result


class SecurityHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pg_test = None
        cls._old_env = {k: os.environ.get(k) for k in ('NEXUS_DATABASE_URL', 'NEXUS_DB_URL', 'NEXUS_DB')}
        cls.old_db = server.DB_PATH
        temp_root = server.ROOT / '.test-runs'
        temp_root.mkdir(exist_ok=True)
        cls.test_dir = temp_root / ('sec-' + uuid.uuid4().hex)
        cls.test_dir.mkdir()
        if _is_pg_test():
            test_url, dbname, admin_url = _create_pg_test_db(PG_TEST_URL)
            cls.pg_test = (test_url, dbname, admin_url)
            os.environ['NEXUS_DATABASE_URL'] = test_url
            os.environ.pop('NEXUS_DB_URL', None)
            server.DB_PATH = cls.test_dir / 'unused.sqlite3'
            server.initialize()
        else:
            os.environ.pop('NEXUS_DATABASE_URL', None)
            os.environ.pop('NEXUS_DB_URL', None)
            server.DB_PATH = cls.test_dir / 'test.sqlite3'
            server.initialize()

        class QuietHandler(server.Handler):
            def log_message(self, *args):
                pass

        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.http.server_port
        cls.password = 'Integration-test-passphrase-42'
        cls.admin = Client(cls.port)
        cls.admin.ok('/auth/register', 'POST', {'email': 'owner@sec.test', 'password': cls.password, 'name': 'Sec Owner', 'organization': 'Sec Org', 'currency': 'USD'})
        cls.me = cls.admin.ok('/me')
        cls.org = cls.me['organization']['id']
        cls.owner_id = cls.me['user']['user_id']
        inv = cls.admin.ok('/invitations', 'POST', {'email': 'member@sec.test', 'role': 'member', 'department': 'Ops'})
        cls.member = Client(cls.port)
        cls.member.ok('/auth/join', 'POST', {'token': inv['token'], 'email': 'member@sec.test', 'password': cls.password, 'name': 'Member'})
        cls.other = Client(cls.port)
        cls.other.ok('/auth/register', 'POST', {'email': 'owner@other-sec.test', 'password': cls.password, 'name': 'Other', 'organization': 'Other Org'})

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=3)
        server.DB_PATH = cls.old_db
        for k, v in getattr(cls, '_old_env', {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if getattr(cls, 'pg_test', None):
            try:
                _drop_pg_test_db(*cls.pg_test)
            except Exception:
                pass
        for name in ('test.sqlite3', 'test.sqlite3-wal', 'test.sqlite3-shm', 'unused.sqlite3'):
            try:
                (cls.test_dir / name).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            cls.test_dir.rmdir()
        except Exception:
            pass

    def test_security_headers_and_request_id(self):
        r = self.admin.raw('/me')
        self.assertEqual(r['status'], 200)
        h = r['headers']
        self.assertEqual(h.get('x-content-type-options'), 'nosniff')
        self.assertEqual(h.get('x-frame-options'), 'DENY')
        self.assertEqual(h.get('referrer-policy'), 'no-referrer')
        self.assertEqual(h.get('cross-origin-opener-policy'), 'same-origin')
        self.assertEqual(h.get('cross-origin-resource-policy'), 'same-origin')
        self.assertIn("default-src 'self'", h.get('content-security-policy', ''))
        self.assertIn("frame-ancestors 'none'", h.get('content-security-policy', ''))
        self.assertRegex(h.get('x-request-id', ''), r'^[A-Za-z0-9._:-]{8,128}$')
        supplied = self.admin.raw('/me', headers={'X-Request-ID': 'req-fixed-12345678'})
        self.assertEqual(supplied['headers'].get('x-request-id'), 'req-fixed-12345678')

    def test_error_responses_include_request_id(self):
        r = Client(self.port).raw('/projects')  # unauthenticated
        self.assertEqual(r['status'], 401)
        self.assertTrue(r['body'].get('request_id'))
        self.assertEqual(r['headers'].get('x-request-id'), r['body'].get('request_id'))

    def test_authz_boundary_fuzz(self):
        # Member cannot access admin endpoints; other tenant cannot access org resources.
        project = self.admin.ok('/projects', 'POST', {'name': 'Sec Project', 'private': False, 'budget': '100.00'})
        forbidden_member = [
            ('/audit', 'GET', None),
            ('/invitations', 'POST', {'email': 'x@sec.test', 'role': 'member'}),
        ]
        for path, method, data in forbidden_member:
            status, _ = self.member.call(path, method, data)
            self.assertIn(status, (401, 403), f'member should not access {method} {path}')
        # Tenant isolation
        status, _ = self.other.call('/projects/' + project['id'], 'GET')
        self.assertIn(status, (403, 404))
        status, _ = self.other.call('/projects/' + project['id'], 'PATCH', {'status': 'complete'})
        self.assertIn(status, (403, 404))

    def test_input_fuzz_no_server_errors(self):
        rng = random.Random(42)
        endpoints = [
            ('/projects', 'POST', lambda: {'name': fuzz_str(rng, 300), 'private': rng.choice([True, False, 'x', 1]), 'budget': fuzz_budget(rng)}),
            ('/tasks', 'POST', lambda: {'title': fuzz_str(rng, 500), 'assignee_id': fuzz_id(rng), 'project_id': fuzz_id(rng), 'priority': fuzz_str(rng, 20)}),
            ('/customers', 'POST', lambda: {'name': fuzz_str(rng, 300), 'email': fuzz_str(rng, 300), 'stage': fuzz_str(rng, 30)}),
            ('/requisitions', 'POST', lambda: {'item': fuzz_str(rng, 300), 'quantity': rng.choice([0, -1, 1, 2**31, '1', None]), 'unit_price': fuzz_budget(rng)}),
        ]
        for _ in range(40):
            path, method, maker = rng.choice(endpoints)
            status, body = self.admin.call(path, method, maker())
            self.assertLess(status, 500, f'{method} {path} returned {status}: {body}')
            self.assertIn(status, (200, 400, 403, 404, 409, 413, 415, 429))

    def test_stored_xss_payloads_returned_as_data(self):
        # Payloads should be stored/returned as plain JSON strings; frontend must escape on render.
        payload = '<script>alert(1)</script><img src=x onerror=alert(1)>'
        c = self.admin.ok('/customers', 'POST', {'name': 'Safe Name', 'notes': payload, 'company': payload})
        got = self.admin.ok('/customers')
        row = next(x for x in got if x['id'] == c['id'])
        self.assertEqual(row['notes'], payload)
        self.assertEqual(row['company'], payload)
        # Ensure response is JSON, not HTML
        r = self.admin.raw('/customers')
        self.assertIn('application/json', r['headers'].get('content-type', ''))

    def test_invalid_ids_and_paths_do_not_500(self):
        bad_ids = ['', 'not-a-uuid', '../etc/passwd', '%2e%2e', 'a'*500, 'zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz']
        for bad in bad_ids:
            status, body = self.admin.call('/projects/' + bad, 'GET')
            self.assertLess(status, 500, body)
            status, body = self.admin.call('/messages/' + bad, 'GET')
            self.assertLess(status, 500, body)

    def test_auth_rate_limit_returns_429(self):
        # Use a fresh client/IP-like behavior is shared; login attempt limiter is per email+ip in DB.
        email = 'ratelimit@sec.test'
        for i in range(11):
            status, _ = Client(self.port).call('/auth/login', 'POST', {'email': email, 'password': 'wrong-password-12345'})
        self.assertEqual(status, 429)


def fuzz_str(rng, max_len):
    chars = string.ascii_letters + string.digits + ' <>"\'&/\x00\n\t'
    n = rng.randint(0, max_len)
    return ''.join(rng.choice(chars) for _ in range(n))


def fuzz_budget(rng):
    return rng.choice(['0', '1.00', '-1', '999999999999', 'NaN', '1e3', '', None, True, False, [], {}])


def fuzz_id(rng):
    return rng.choice([uuid.uuid4().hex, '', 'bad', '0'*32, 'g'*32, None, 123, '../x'])


if __name__ == '__main__':
    unittest.main()