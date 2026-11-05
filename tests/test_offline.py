"""Local-only checks; network access and router commands are never allowed."""
import contextlib
import importlib.util
import io
import pathlib
import sys
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parents[1] / "app"
spec = importlib.util.spec_from_file_location("offline_ssh", HERE / "offline_ssh.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
real_environment_check = helper.check_environment


class OfflineChecks(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.object(helper, "check_environment")
        environment.start()
        self.addCleanup(environment.stop)

    def test_ten_character_password_accepted(self):
        with mock.patch.object(helper.getpass, "getpass", side_effect=["Abc1234567", "Abc1234567"]):
            self.assertEqual(helper.password("Password: "), "Abc1234567")

    def test_nine_character_password_rejected(self):
        with mock.patch.object(helper.getpass, "getpass", return_value="Abc123456"):
            with self.assertRaisesRegex(RuntimeError, "10-63"):
                helper.password("Password: ")

    def test_mismatched_password_rejected(self):
        with mock.patch.object(helper.getpass, "getpass", side_effect=["Abc1234567", "Abc1234568"]):
            with self.assertRaisesRegex(RuntimeError, "differ"):
                helper.password("Password: ")

    def test_default_sends_no_requests(self):
        with mock.patch.object(sys, "argv", ["offline_ssh.py"]), \
             mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network")), \
             mock.patch.object(helper.socket, "socket", side_effect=AssertionError("socket")), \
             contextlib.redirect_stdout(io.StringIO()):
            helper.main()

    def test_wrong_hardware_rejected(self):
        response = io.BytesIO(b'{"code":0,"hardware":"RD03","romversion":"2.0.28","id":"TEST-SN"}')
        with mock.patch.object(helper.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "RD03v2"):
                helper.read_info()

    def test_initialized_router_is_not_initialized_again(self):
        with mock.patch.object(sys, "argv", ["offline_ssh.py", "--init"]), \
             mock.patch.object(helper, "read_info", return_value={"inited": 1, "hardware":"RD03v2", "romversion":"2.0.28", "id":"TEST-SN"}), \
             mock.patch.object(helper, "load_tool", side_effect=AssertionError("must stop")):
            with self.assertRaisesRegex(RuntimeError, "already initialized"):
                helper.main()

    def test_valid_different_router_is_not_bound_to_original_sn(self):
        data = {"code": 0, "hardware": "RD03v2", "romversion": "2.0.28", "id": "ANOTHER-TEST-SN"}
        response = io.BytesIO(helper.json.dumps(data).encode())
        with mock.patch.object(helper.urllib.request, "urlopen", return_value=response):
            self.assertEqual(helper.read_info()["id"], "ANOTHER-TEST-SN")

    def test_unsupported_firmware_rejected(self):
        response = io.BytesIO(b'{"code":0,"hardware":"RD03v2","romversion":"2.0.12","id":"TEST-SN"}')
        with mock.patch.object(helper.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "2.0.28"):
                helper.read_info()

    def test_missing_identity_rejected(self):
        response = io.BytesIO(b'{"code":0,"hardware":"RD03v2","romversion":"2.0.28"}')
        with mock.patch.object(helper.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "serial"):
                helper.read_info()

    def test_device_swap_stops_before_write(self):
        before = {"id": "ROUTER-A", "inited": 1}
        with mock.patch.object(helper, "read_info", return_value={"id": "ROUTER-B", "inited": 1}):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                helper.check_same_device(before)

    def test_init_state_change_stops_before_write(self):
        before = {"id": "ROUTER-A", "inited": 0}
        with mock.patch.object(helper, "read_info", return_value={"id": "ROUTER-A", "inited": 1}):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                helper.check_same_device(before)

    def test_private_ipv4_scope(self):
        for address in ("10.1.2.3", "172.16.1.1", "172.31.255.1", "192.168.8.1"):
            self.assertEqual(helper.private_ipv4(address), address)
        for address in ("8.8.8.8", "127.0.0.1", "169.254.1.1", "172.32.1.1", "router.local", "http://192.168.31.1/"):
            with self.assertRaises(helper.argparse.ArgumentTypeError):
                helper.private_ipv4(address)

    def test_custom_target_does_not_send_requests_in_check_mode(self):
        old = helper.HOST, helper.PORT, helper.LOCAL_IP
        try:
            with mock.patch.object(sys, "argv", ["offline_ssh.py", "--host", "192.168.8.1", "--port", "8001", "--local-ip", "192.168.8.2"]), \
                 mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network")), \
                 mock.patch.object(helper.socket, "socket", side_effect=AssertionError("socket")), \
                 contextlib.redirect_stdout(io.StringIO()):
                helper.main()
            self.assertEqual((helper.HOST, helper.PORT, helper.LOCAL_IP), ("192.168.8.1", 8001, "192.168.8.2"))
            self.assertIn(b"192.168.8.2:8001/done/test", helper.stager("LocalRoot10", "LocalWifi10", "192.168.8.2", "test"))
        finally:
            helper.HOST, helper.PORT, helper.LOCAL_IP = old

    def test_web_password_checked_by_standard_login_without_plaintext_transmission(self):
        page = b"key: 'public-salt', var deviceId = '00:11:22:33:44:55';"
        calls = []
        def response(url, data=None, **kwargs):
            calls.append((url, data))
            return io.BytesIO(page if data is None else b'{"code":0,"token":"test-token"}')
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=response), \
             mock.patch.object(helper.time, "time", return_value=100), \
             mock.patch.object(helper.secrets, "randbelow", return_value=1):
            self.assertTrue(helper.verify_web("ExamplePass10"))
        parameters = helper.urllib.parse.parse_qs(calls[1][1].decode())
        account = helper.hashlib.sha256(b"ExamplePass10public-salt").hexdigest()
        expected = helper.hashlib.sha256((parameters["nonce"][0] + account).encode()).hexdigest()
        self.assertEqual(parameters["password"], [expected])
        self.assertNotIn(b"ExamplePass10", calls[1][1])

    def test_blocked_mode_rejected_by_original_poc(self):
        tool = helper.load_tool("ota_rce")
        for raw in ('{"code":0,"netmode":4}', '{"code":0,"netmode":"0"}', '{"code":1}'):
            with self.assertRaises(ValueError):
                tool.require_tested_gate_open_mode(raw)
        self.assertEqual(tool.require_tested_gate_open_mode('{"code":0,"netmode":0}'), 0)

    def test_passwords_are_quoted_and_not_replaced_recursively(self):
        root = "ROOT_PASSWORD'$(false)"
        wifi = "WIFI_PASSWORD;TOKEN"
        body = helper.stager(root, wifi, "192.168.31.2", "abcd").decode("ascii")
        self.assertIn(helper.shlex.quote(root), body)
        self.assertIn(helper.shlex.quote(wifi), body)
        self.assertIn("192.168.31.2:8000/done/abcd", body)


class EnvironmentChecks(unittest.TestCase):
    def test_missing_dependency_has_install_instructions(self):
        import builtins
        original_import = builtins.__import__
        def missing_ssh(name, *args, **kwargs):
            if name == "ssh2.session":
                raise ModuleNotFoundError("ssh2")
            return original_import(name, *args, **kwargs)
        with mock.patch.object(builtins, "__import__", side_effect=missing_ssh):
            with self.assertRaisesRegex(RuntimeError, "requirements.txt"):
                real_environment_check()

    def test_native_library_failure_has_install_instructions(self):
        import builtins
        original_import = builtins.__import__
        def broken_ssh(name, *args, **kwargs):
            if name == "ssh2.session":
                raise OSError("DLL load failed")
            return original_import(name, *args, **kwargs)
        with mock.patch.object(builtins, "__import__", side_effect=broken_ssh):
            with self.assertRaisesRegex(RuntimeError, "requirements.txt"):
                real_environment_check()

    def test_missing_environment_stops_before_any_router_request(self):
        with mock.patch.object(sys, "argv", ["offline_ssh.py", "--enable"]), \
             mock.patch.object(helper, "check_environment", side_effect=RuntimeError("missing dependency")), \
             mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network")) as request:
            with self.assertRaisesRegex(RuntimeError, "missing dependency"):
                helper.main()
            request.assert_not_called()

if __name__ == "__main__":
    unittest.main()
