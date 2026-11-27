import os
import unittest
from unittest.mock import patch
import ai_gateway
import local_agent


class LocalAgentTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'id':'m1','author_name':'John','body':'Please review invoice 123.'}]

    def test_extractive_results_and_no_execution(self):
        for action in ('summary','actions','reply','search'):
            self.assertIn('[m1]',local_agent.respond(self.rows,action,'invoice'))
        self.assertIn('Payment recording does not send money',local_agent.respond(self.rows,'help'))
        with self.assertRaises(ValueError):local_agent.respond(self.rows,'translate')

    def test_default_offline_status_and_no_secrets(self):
        with patch.dict(os.environ,{'NEXUS_AI_API_KEY':'secret-value'},clear=True):
            config=ai_gateway.status()
            self.assertEqual(config['default_mode'],'offline')
            self.assertTrue(config['modes']['offline']['configured'])
            self.assertFalse(config['modes']['local']['configured'])
            self.assertNotIn('secret-value',str(config))

    def test_local_rejects_remote_endpoint_without_network_or_fallback(self):
        with patch.dict(os.environ,{'NEXUS_LOCAL_AI_ENDPOINT':'https://remote.example/v1/chat/completions','NEXUS_LOCAL_AI_MODEL':'test'}), patch('ai_gateway.build_opener') as network:
            with self.assertRaises(ai_gateway.ProviderError):ai_gateway.generate(self.rows,'Summarize',mode='local')
            network.assert_not_called()
