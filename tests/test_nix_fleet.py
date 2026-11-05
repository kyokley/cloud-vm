"""Focused flake-evaluation checks for fleet metadata and per-VM isolation."""

import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("nix"), "Nix is required for flake evaluation")
class FleetFlakeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="cloud-vm-nix-test-")
        self.root = pathlib.Path(self.tempdir.name) / "project"
        self.root.mkdir()
        for name in ("flake.nix", "flake.lock"):
            shutil.copy2(ROOT / name, self.root / name)
        for name in ("cloud_vm", "config", "modules", "scripts"):
            shutil.copytree(ROOT / name, self.root / name)

    def tearDown(self):
        self.tempdir.cleanup()

    def evaluate(self, attr):
        result = subprocess.run(
            [
                "nix",
                "--extra-experimental-features",
                "nix-command flakes",
                "eval",
                "--no-update-lock-file",
                "--no-write-lock-file",
                "--raw",
                f"path:{self.root}#{attr}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result.stdout

    def test_base_target_and_home_configuration_match(self):
        self.assertEqual(self.evaluate("lib.target.username"), "exedev")
        self.assertEqual(
            self.evaluate("homeConfigurations.vm.config.home.username"), "exedev"
        )
        self.assertEqual(
            self.evaluate("homeConfigurations.vm.config.home.homeDirectory"),
            "/home/exedev",
        )
        result = subprocess.run(
            [
                "nix",
                "--extra-experimental-features",
                "nix-command flakes",
                "eval",
                "--no-update-lock-file",
                "--no-write-lock-file",
                "--json",
                f"path:{self.root}#lib.fleet.targets",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "{}")

    def test_split_home_modules_preserve_shell_and_opencode_configuration(self):
        self.assertEqual(
            self.evaluate("homeConfigurations.vm.config.programs.zsh.prezto.prompt.theme"),
            "powerlevel10k",
        )
        self.assertEqual(
            self.evaluate("homeConfigurations.vm.config.programs.opencode.settings.model"),
            "opencode/big-pickle",
        )

    def test_per_vm_metadata_and_home_module_are_isolated(self):
        (self.root / "config" / "vms" / "alice.nix").write_text(
            "{ ... }: { fleet.vms.alice = { "
            'target = { username = "alice"; homeDirectory = "/home/alice"; }; '
            'modules = [ ({ ... }: { home.sessionVariables.FLEET_TEST = "alice-only"; }) ]; '
            "}; }\n"
        )

        self.assertEqual(self.evaluate("lib.fleet.targets.alice.username"), "alice")
        self.assertEqual(
            self.evaluate("homeConfigurations.alice.config.home.username"), "alice"
        )
        self.assertEqual(
            self.evaluate("homeConfigurations.alice.config.home.homeDirectory"),
            "/home/alice",
        )
        self.assertEqual(
            self.evaluate(
                "homeConfigurations.alice.config.home.sessionVariables.FLEET_TEST"
            ),
            "alice-only",
        )
        self.assertEqual(
            self.evaluate("homeConfigurations.vm.config.home.username"), "exedev"
        )
        with self.assertRaises(subprocess.CalledProcessError):
            self.evaluate(
                "homeConfigurations.vm.config.home.sessionVariables.FLEET_TEST"
            )

    def test_home_module_cannot_override_validated_target(self):
        (self.root / "config" / "vms" / "alice.nix").write_text(
            "{ ... }: { fleet.vms.alice = { "
            'target = { username = "alice"; homeDirectory = "/home/alice"; }; '
            'modules = [ ({ lib, ... }: { home.username = lib.mkForce "mallory"; }) ]; '
            "}; }\n"
        )

        with self.assertRaises(subprocess.CalledProcessError) as failure:
            self.evaluate("homeConfigurations.alice.activationPackage.drvPath")
        self.assertIn(
            "home.username must match fleet target metadata", failure.exception.stderr
        )

    def test_invalid_vm_name_is_rejected(self):
        (self.root / "config" / "vms" / "bad-name.nix").write_text(
            "{ ... }: { fleet.vms.bad_name = { }; }\n"
        )
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            self.evaluate("lib.fleet.targets")
        self.assertIn("fleet VM names must match", failure.exception.stderr)

    def test_unsafe_base_identity_is_rejected(self):
        (self.root / "config" / "target.nix").write_text(
            '{ system = "x86_64-linux"; username = "root"; homeDirectory = "/root"; }\n'
        )
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            self.evaluate("lib.target")
        self.assertIn("base target metadata requires", failure.exception.stderr)


if __name__ == "__main__":
    unittest.main()
