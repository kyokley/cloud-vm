import json
import pathlib
import subprocess
import unittest
from unittest import mock

from cloud_vm.backend import VM, BackendError, FleetBackend


class FleetBackendTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path("/project")
        self.backend = FleetBackend(self.root)

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_list_vms_parses_documented_inventory(self, run):
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "vms": [
                        {
                            "vm_name": "dev-1",
                            "ssh_dest": "dev-1.exe.xyz",
                            "ssh_host": "dev-1.exe.xyz",
                            "status": "running",
                            "https_url": "https://dev-1.exe.xyz",
                            "region": "lon",
                            "region_display": "London, UK",
                            "image": "debian",
                            "created_at": "2026-11-04T12:00:00Z",
                        }
                    ]
                }
            ),
            "",
        )
        self.assertEqual(
            self.backend.list_vms(),
            [
                VM(
                    "dev-1",
                    "running",
                    ssh_host="dev-1.exe.xyz",
                    image="debian",
                    created_at="2026-11-04T12:00:00Z",
                )
            ],
        )
        self.assertEqual(run.call_args.args[0], ["ssh", "exe.dev", "ls", "--json"])
        self.assertEqual(self.backend.ssh_args("dev-1"), ["ssh", "dev-1.exe.xyz"])

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_malformed_inventory_fails_closed(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '{"vms": {}}', "")
        with self.assertRaisesRegex(BackendError, "inventory"):
            self.backend.list_vms()

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_inventory_error_and_missing_nonessential_fields(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 0, '{"error":"Choose a plan to start creating VMs."}', ""
        )
        with self.assertRaisesRegex(BackendError, "Choose a plan"):
            self.backend.list_vms()
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "vms": [
                        {
                            "vm_name": "dev-1",
                            "ssh_dest": "dev-1.exe.xyz",
                            "ssh_host": "dev-1.exe.xyz",
                            "status": "custom-state",
                        }
                    ]
                }
            ),
            "",
        )
        self.assertEqual(
            self.backend.list_vms(), [VM("dev-1", "custom-state", "dev-1.exe.xyz")]
        )

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_all_mutators_require_authorization_before_commands(self, run):
        for operation in (
            self.backend.create,
            self.backend.bootstrap,
            self.backend.apply,
            self.backend.remove,
        ):
            with (
                self.subTest(operation=operation.__name__),
                self.assertRaises(BackendError),
            ):
                operation("dev-1")
        run.assert_not_called()

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_create_uses_fixed_argv_and_strict_name(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "created", "")
        self.assertEqual(self.backend.create("dev-1", authorized=True), "created")
        self.assertEqual(
            run.call_args.args[0], ["ssh", "exe.dev", "new", "--name=dev-1", "--json"]
        )
        for invalid in ("Dev", "dev_1", "-dev", "dev;rm"):
            with self.subTest(name=invalid), self.assertRaises(BackendError):
                self.backend.create(invalid, authorized=True)
        run.reset_mock()
        with self.assertRaises(BackendError):
            self.backend.create("bad/name", authorized=True)
        run.assert_not_called()

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_unnamed_create_uses_provider_default(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "created", "")
        self.assertEqual(self.backend.create(None, authorized=True), "created")
        self.assertEqual(run.call_args.args[0], ["ssh", "exe.dev", "new", "--json"])
        run.reset_mock()
        self.assertEqual(self.backend.create("", authorized=True), "created")
        self.assertEqual(run.call_args.args[0], ["ssh", "exe.dev", "new", "--json"])

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_unnamed_create_still_requires_authorization_first(self, run):
        with self.assertRaises(BackendError):
            self.backend.create(None)
        with self.assertRaises(BackendError):
            self.backend.create("")
        run.assert_not_called()

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_remove_calls_existing_script_with_one_name(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "removed", "")
        self.backend.remove("dev-1", authorized=True)
        self.assertEqual(
            run.call_args.args[0], [str(self.root / "scripts/rm-vm.sh"), "dev-1"]
        )

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_create_surfaces_json_errors_and_preserves_unspecified_success_json(
        self, run
    ):
        run.return_value = subprocess.CompletedProcess(
            [], 0, '{"error":"Choose a plan"}\n', ""
        )
        with self.assertRaisesRegex(BackendError, "Choose a plan"):
            self.backend.create("dev-1", authorized=True)
        run.return_value = subprocess.CompletedProcess(
            [], 0, '{"success":"provider schema unknown"}\n', ""
        )
        self.assertEqual(
            self.backend.create("dev-1", authorized=True),
            '{"success":"provider schema unknown"}\n',
        )

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_ssh_destination_uses_validated_inventory_or_safe_fallback(self, run):
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "vms": [
                        {
                            "vm_name": "dev-1",
                            "ssh_dest": "vm+dev-1@vm.exe.xyz",
                            "ssh_host": "dev-1.exe.xyz",
                            "status": "anything",
                            "https_url": "",
                            "region": "",
                            "region_display": "",
                        },
                    ]
                }
            ),
            "",
        )
        self.backend.list_vms()
        self.assertEqual(self.backend.ssh_args("dev-1"), ["ssh", "vm+dev-1@vm.exe.xyz"])
        self.assertEqual(self.backend.ssh_args("other"), ["ssh", "vm+other@vm.exe.xyz"])

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_unsafe_ssh_dest_fails_closed(self, run):
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "vms": [
                        {
                            "vm_name": "dev-1",
                            "ssh_dest": "-oProxyCommand=bad",
                            "ssh_host": "dev-1.exe.xyz",
                            "status": "running",
                        },
                    ]
                }
            ),
            "",
        )
        with self.assertRaisesRegex(BackendError, "unsafe ssh_dest"):
            self.backend.list_vms()

    @mock.patch(
        "cloud_vm.backend.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["ssh"], 1),
    )
    def test_mutation_timeout_reports_unknown_outcome_without_retry(self, run):
        with self.assertRaisesRegex(BackendError, "outcome may be unknown"):
            self.backend.create("dev-1", authorized=True)
        run.assert_called_once()

    @mock.patch("cloud_vm.backend.subprocess.run")
    def test_nonzero_mutation_preserves_both_streams_and_warns_about_partial_outcome(
        self, run
    ):
        run.return_value = subprocess.CompletedProcess(
            [], 255, "remote started work\n", "ssh: connection lost\n"
        )
        with self.assertRaises(BackendError) as raised:
            self.backend.apply("dev-1", authorized=True)
        message = str(raised.exception)
        self.assertIn("remote started work", message)
        self.assertIn("ssh: connection lost", message)
        self.assertIn("unknown or partially applied", message)
        self.assertIn("inspect the VM before retrying", message)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
