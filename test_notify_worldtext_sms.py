#!/usr/bin/env python3
"""Tests for notify_worldtext_sms.py.

Runs against a stub server on localhost, so no account, no credentials and no
network access are required.

    python3 test_notify_worldtext_sms.py
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import notify_worldtext_sms as plugin

VALID_TOKEN = "test-token"
PERMISSIONLESS_TOKEN = "no-sms-token"


class StubApi(BaseHTTPRequestHandler):
    """Minimal stand-in for the World Text API."""

    received = []

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_PUT(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode()
        StubApi.received.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": body,
            "method": "PUT",
        })

        auth = self.headers.get("Authorization") or ""
        if auth == "Bearer " + PERMISSIONLESS_TOKEN:
            return self._send(403, {
                "status": "1", "error": "1000",
                "desc": "[RFC6750] The access token does not cover this operation"})
        if auth != "Bearer " + VALID_TOKEN:
            return self._send(401, {
                "status": "1", "error": "1000",
                "desc": "Authorisation Failure"})

        self._send(200, {
            "status": "0",
            "result": [{"msgid": "10001", "credits": "1.0",
                        "dstaddr": "447989000001", "status": "5"}],
        })

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PluginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), StubApi)
        cls.base_url = "http://127.0.0.1:%d" % cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        StubApi.received = []
        self.env = mock.patch.dict("os.environ", {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def run_plugin(self, *extra):
        return plugin.main(["--base-url", self.base_url,
                            "-d", "447989000001", "-t", "hello"] + list(extra))

    def test_success_sends_bearer_header(self):
        code = self.run_plugin("--token", VALID_TOKEN)
        self.assertEqual(code, plugin.OK)
        sent = StubApi.received[0]
        self.assertEqual(sent["auth"], "Bearer " + VALID_TOKEN)
        self.assertEqual(sent["method"], "PUT")
        self.assertTrue(sent["path"].endswith("/sms/send"))

    def test_token_from_environment(self):
        with mock.patch.dict("os.environ", {plugin.TOKEN_ENV: VALID_TOKEN}):
            self.assertEqual(self.run_plugin(), plugin.OK)
        self.assertEqual(StubApi.received[0]["auth"], "Bearer " + VALID_TOKEN)

    def test_bad_token_is_critical(self):
        self.assertEqual(self.run_plugin("--token", "wrong"), plugin.CRITICAL)

    def test_missing_permission_is_critical(self):
        self.assertEqual(self.run_plugin("--token", PERMISSIONLESS_TOKEN),
                         plugin.CRITICAL)

    def test_missing_token_is_unknown(self):
        self.assertEqual(self.run_plugin(), plugin.UNKNOWN)

    def test_message_and_srcaddr_are_submitted(self):
        self.run_plugin("--token", VALID_TOKEN, "-s", "Monitor")
        body = StubApi.received[0]["body"]
        self.assertIn("txt=hello", body)
        self.assertIn("dstaddr=447989000001", body)
        self.assertIn("srcaddr=Monitor", body)

    def test_sim_flag_adds_simulation_parameter(self):
        """Simulated sends go to /sms/send too, but must not cost credits."""
        self.run_plugin("--token", VALID_TOKEN, "--sim")
        self.assertIn("sim=true", StubApi.received[0]["body"])

    def test_token_never_appears_in_output(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.run_plugin("--token", VALID_TOKEN)
        self.assertNotIn(VALID_TOKEN, buf.getvalue())

    def test_unreachable_host_is_critical(self):
        code = plugin.main(["--base-url", "http://127.0.0.1:1",
                            "-d", "447989000001", "-t", "hello",
                            "--token", VALID_TOKEN])
        self.assertEqual(code, plugin.CRITICAL)

    def test_usage_error_is_unknown(self):
        with self.assertRaises(SystemExit) as ctx:
            plugin.main(["--token", VALID_TOKEN])   # no -d/-t
        self.assertEqual(ctx.exception.code, plugin.UNKNOWN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
