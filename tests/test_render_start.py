"""Deployment adapter checks without contacting Render or changing a live DB."""
import os
import sys
import unittest
from unittest.mock import patch

import render_start
import server


class RenderStartTests(unittest.TestCase):
    def test_bind_port_host_allowlist_and_secure_defaults(self):
        env = {'RENDER_EXTERNAL_HOSTNAME': 'nexus-test.onrender.com', 'PORT': '10000',
               'NEXUS_ALLOWED_HOSTS': 'custom.example'}
        with patch.dict(os.environ, env, clear=True), patch.object(sys, 'argv', []), \
                patch.object(server, 'main') as start:
            render_start.main()
            start.assert_called_once()
            self.assertEqual(sys.argv, ['server.py', '--host', '0.0.0.0', '--port', '10000'])
            self.assertEqual(os.environ['NEXUS_ALLOWED_HOSTS'], 'custom.example,nexus-test.onrender.com')
            self.assertEqual(os.environ['NEXUS_SECURE_COOKIE'], '1')
            self.assertEqual(os.environ['NEXUS_DISABLE_DEMO'], '1')

    def test_reject_missing_or_invalid_hostname(self):
        for host in ('', '*', 'https://example.com', 'example.com/path'):
            with self.subTest(host=host), patch.dict(os.environ, {'RENDER_EXTERNAL_HOSTNAME': host}, clear=True):
                with self.assertRaises(SystemExit):
                    render_start.main()

    def test_reject_invalid_port(self):
        with patch.dict(os.environ, {'RENDER_EXTERNAL_HOSTNAME': 'test.onrender.com', 'PORT': '65536'}, clear=True):
            with self.assertRaises(SystemExit):
                render_start.main()
