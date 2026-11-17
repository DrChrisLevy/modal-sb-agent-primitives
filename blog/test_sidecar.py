from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / "steps"))
import s3_sidecar as sidecar


class SidecarTests(unittest.TestCase):
    def test_curl_is_installed_at_build_time_without_opening_main_network(self):
        sandbox = Mock()
        with patch.object(sidecar.modal.Image, "debian_slim") as image, \
             patch.object(sidecar.modal.App, "lookup"), \
             patch.object(sidecar.modal.Secret, "from_name") as secret, \
             patch.object(sidecar.modal.Sandbox, "create", return_value=sandbox) as create, \
             patch.object(sidecar, "wait_for") as wait:
            self.assertIs(sidecar.create_sandbox(), sandbox)
        image.assert_called_once_with(python_version="3.13")
        image.return_value.apt_install.assert_called_once_with("git", "curl")
        self.assertIs(create.call_args.kwargs["image"], image.return_value.apt_install.return_value)
        self.assertEqual(create.call_args.kwargs["outbound_cidr_allowlist"], [])
        self.assertNotIn("secrets", create.call_args.kwargs)
        self.assertNotIn("env", create.call_args.kwargs)
        secret.assert_called_once_with("blog-demo-key")
        proxy = sandbox._experimental_sidecars.create.call_args.kwargs
        self.assertEqual(proxy["secrets"], [secret.return_value])
        self.assertEqual(proxy["outbound_domain_allowlist"], ["httpbin.org"])
        wait.assert_called_once_with(sandbox, "key-proxy", 8080)

    def test_readiness_failure_stops_sandbox(self):
        sandbox = Mock()
        sandbox.exec.return_value.wait.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "key-proxy did not become ready"):
            sidecar.wait_for(sandbox, "key-proxy", 8080)
        sandbox.terminate.assert_called_once_with(wait=True)
