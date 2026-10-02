import json
import os
import pathlib
import shlex
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap-nix.sh"


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        source = SCRIPT.read_text()
        source = source.replace("nix_root=/nix", f"nix_root={self.root}/nix")
        source = source.replace("systemd_dir=/run/systemd/system", f"systemd_dir={self.root}/systemd")
        self.script = self.root / "bootstrap-nix.sh"
        self.script.write_text(source)
        self.script.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(
            HOME=str(self.home),
            PATH=f"{self.bin}:/usr/bin:/bin",
            NIX_TRACE=str(self.root / "nix-trace"),
            SUDO_TRACE=str(self.root / "sudo-trace"),
            CURL_TRACE=str(self.root / "curl-trace"),
        )

    def tearDown(self):
        self.temp.cleanup()

    def mock(self, name, source):
        path = self.bin / name
        path.write_text(source)
        path.chmod(0o755)
        return path

    def bash_mock(self, name, body):
        return self.mock(name, "#!/bin/bash\n" + body + "\n")

    def set_linux(self, arch="x86_64", uid=1000):
        self.bash_mock("uname", f'[[ "$1" == -m ]] && echo {arch} || echo Linux')
        self.bash_mock("id", f'[[ "$1" == -u ]] && echo {uid} || echo test-user')

    def set_systemd(self, state="running"):
        (self.root / "systemd").mkdir(exist_ok=True)
        self.bash_mock("systemctl", f'echo {state}')

    def set_sudo(self, installer_status=0, preflight_status=0):
        self.mock("sudo", f'''#!/usr/bin/env python3
import json,os,subprocess,sys
args=sys.argv[1:]
with open(os.environ["SUDO_TRACE"],"a") as f: f.write(json.dumps(args)+"\\n")
if args == ["-n","true"]: sys.exit({preflight_status})
if args[:2] != ["-n","--"]: sys.exit(88)
if {installer_status} != 0: sys.exit({installer_status})
result=subprocess.run(args[2:],stdin=sys.stdin.buffer)
sys.exit(result.returncode)
''')

    def set_curl(self, fail=False):
        self.mock("curl", f'''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
with open(os.environ["CURL_TRACE"],"a") as f: f.write(json.dumps(args)+"\\n")
if {fail}: sys.exit(22)
output=pathlib.Path(args[args.index("--output")+1])
output.write_bytes(pathlib.Path(os.environ["ENTRY_SCRIPT"]).read_bytes())
''')

    def legacy_nix_installer(self, *, ping_failure=False, record_env=True):
        lines = [
            "#!/bin/sh",
            'printf "%s\\n" "$@" > "$INSTALLER_ARGS"',
        ]
        if record_env:
            lines.append('printf "%s\\n%s\\n" "${NIX_BECOME-UNSET}" "${NIX_INSTALLER_YES-UNSET}" > "$INSTALLER_ENV"')
        lines.extend([
            'if IFS= read -r line; then exit 12; fi',
            'mkdir -p "$HOME/.nix-profile/bin"',
            "printf '#!/bin/sh\\nprintf \\\"%%s\\\\n\\\" \\\"\\$*\\\" >> \\\"\\$NIX_TRACE\\\"\\ncase \\\"\\$*\\\" in *store\\\\ ping*) ",
            "exit 29;",
            ";; esac\\nexit 0\\n' > \"$HOME/.nix-profile/bin/nix\"",
            'chmod +x "$HOME/.nix-profile/bin/nix"',
        ])
        if ping_failure:
            lines[-2] = "printf '#!/bin/sh\\nexit 29\\n' > \"$HOME/.nix-profile/bin/nix\""
        else:
            lines[-3] = "printf '#!/bin/sh\\nprintf \\\"%%s\\\\n\\\" \\\"\\$*\\\" >> \\\"\\$NIX_TRACE\\\"\\ncase \\\"\\$*\\\" in *store\\\\ ping*) exit 29 ;; esac\\nexit 0\\n' > \"$HOME/.nix-profile/bin/nix\""
        return "\n".join(lines) + "\n"

    def nix_installer(self, ping_failure=False):
        ping_case = 'case "$*" in *"store ping"*) exit 29 ;; esac\n' if ping_failure else ""
        fake_nix = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$NIX_TRACE"\n' + ping_case + "exit 0\n"
        return (
            'if IFS= read -r line; then exit 12; fi\n'
            'mkdir -p "$HOME/.nix-profile/bin"\n'
            f"printf %s {shlex.quote(fake_nix)} > \"$HOME/.nix-profile/bin/nix\"\n"
            'chmod +x "$HOME/.nix-profile/bin/nix"\n'
        )

    def installer_file(self, content=None):
        path = self.root / "reviewed installer"
        path.write_text(content if content is not None else self.nix_installer())
        return path

    def run_script(self, *args):
        return subprocess.run([str(self.script), *args], env=self.env, text=True, capture_output=True)

    def test_help_consent_and_legacy_modes(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--yes [--allow-sudo]", result.stdout)
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertIn("requires --yes", self.run_script("--allow-sudo").stderr)
        for flag in ("--daemon", "--no-daemon"):
            result = self.run_script(flag, "--yes")
            self.assertIn("legacy", result.stderr)

    def test_platform_architecture_and_systemd_preflight(self):
        self.bash_mock("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Darwin')
        self.assertIn("only Linux", self.run_script("--yes").stderr)
        self.bash_mock("uname", '[[ "$1" == -m ]] && echo riscv64 || echo Linux')
        self.assertIn("unsupported Linux architecture", self.run_script("--yes").stderr)

        self.set_linux()
        self.bash_mock("systemctl", 'echo running')
        marker = self.root / "ran"
        installer = self.installer_file(f"/usr/bin/touch '{marker}'\n")
        self.set_curl(fail=True)
        result = self.run_script("--yes", "--installer-file", str(installer))
        self.assertIn("requires usable systemd", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / "curl-trace").exists())

    def test_nonroot_authorization_and_sudo_preflight(self):
        self.set_linux()
        self.set_systemd()
        marker = self.root / "ran"
        installer = self.installer_file(f"/usr/bin/touch '{marker}'\n")
        self.set_curl(fail=True)
        result = self.run_script("--yes", "--installer-file", str(installer))
        self.assertIn("requires explicit --allow-sudo", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / "curl-trace").exists())

        self.set_sudo(preflight_status=1)
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("sudo is unavailable", result.stderr)
        self.assertFalse(marker.exists())

    def test_root_installs_without_sudo_and_forwards_exact_cli(self):
        self.set_linux(uid=0)
        self.set_systemd()
        sudo_trace = self.root / "sudo-trace"
        self.bash_mock("sudo", f'echo called >> "{sudo_trace}"; exit 88')
        args_file = self.root / "args"
        env_file = self.root / "env"
        installer = self.installer_file(
            f'printf "%s\\n" "$@" > "{args_file}"\n'
            f'printf "%s\\n%s\\n" "${{NIX_BECOME-UNSET}}" "${{NIX_INSTALLER_YES-UNSET}}" > "{env_file}"\n'
            + self.nix_installer()
        )
        self.env["NIX_BECOME"] = "/hostile/inherited/sudo"
        self.env["NIX_INSTALLER_YES"] = "hostile"
        result = self.run_script("--yes", "--installer-file", str(installer))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(sudo_trace.exists())
        self.assertEqual(args_file.read_text().splitlines(), ["install", "--no-confirm", "--diagnostic-endpoint="])
        self.assertEqual(env_file.read_text().splitlines(), ["UNSET", "UNSET"])
        self.assertIn("Nix installation verified", result.stdout)

    def test_nonroot_sudo_invocation_and_failure_are_noninteractive(self):
        self.set_linux()
        self.set_systemd()
        self.set_sudo()
        args_file = self.root / "args"
        env_file = self.root / "env"
        installer = self.installer_file(
            f'printf "%s\\n" "$@" > "{args_file}"\n'
            f'printf "%s\\n%s\\n" "${{NIX_BECOME-UNSET}}" "${{NIX_INSTALLER_YES-UNSET}}" > "{env_file}"\n'
            + self.nix_installer()
        )
        self.env["NIX_BECOME"] = "/hostile/inherited/sudo"
        self.env["NIX_INSTALLER_YES"] = "hostile"
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in (self.root / "sudo-trace").read_text().splitlines()]
        self.assertEqual(calls[0], ["-n", "true"])
        self.assertEqual(calls[1], ["-n", "--", "sh", str(installer), "install", "--no-confirm", "--diagnostic-endpoint="])
        self.assertEqual(args_file.read_text().splitlines(), ["install", "--no-confirm", "--diagnostic-endpoint="])
        self.assertEqual(env_file.read_text().splitlines(), ["UNSET", "UNSET"])
        self.assertIn("--experimental-features nix-command store ping --store daemon", (self.root / "nix-trace").read_text())

        self.set_sudo(installer_status=19)
        args_file.unlink()
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("installation verified", result.stdout)

    def test_reviewed_installer_skips_fetch_and_invalid_file_fails(self):
        self.set_linux()
        self.set_systemd()
        self.set_sudo()
        self.set_curl(fail=True)
        installer_args = self.root / "args"
        installer = self.installer_file(f'printf "%s\\n" "$@" > "{installer_args}"\n' + self.nix_installer())
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "curl-trace").exists())
        self.assertEqual(installer_args.read_text().splitlines(), ["install", "--no-confirm", "--diagnostic-endpoint="])

        (self.home / ".nix-profile/bin/nix").unlink()
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(self.root / "missing"))
        self.assertIn("readable, non-empty regular file", result.stderr)
        self.assertFalse((self.root / "curl-trace").exists())

    def test_mocked_https_download_executes_then_removes_temp_file(self):
        self.set_linux()
        self.set_systemd()
        self.set_sudo()
        entry_script = self.root / "entry-script"
        entry_script.write_text(self.nix_installer())
        self.env["ENTRY_SCRIPT"] = str(entry_script)
        self.set_curl()
        result = self.run_script("--yes", "--allow-sudo")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads((self.root / "curl-trace").read_text().splitlines()[0])
        self.assertIn("https://install.determinate.systems/nix", args)
        self.assertIn("--proto", args)
        self.assertIn("--proto-redir", args)
        temp_path = pathlib.Path(args[args.index("--output") + 1])
        self.assertFalse(temp_path.exists())
        self.assertIn("Nix installation verified", result.stdout)

    def test_existing_nix_path_profile_or_path_command_stops_before_installer(self):
        self.set_linux()
        self.set_systemd()
        self.set_sudo()
        installer = self.installer_file("touch '" + str(self.root / "ran") + "'\n")
        self.set_curl(fail=True)
        nix_root = self.root / "nix"
        nix_root.mkdir()
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("existing /nix state", result.stderr)
        self.assertFalse((self.root / "curl-trace").exists())
        self.assertFalse((self.root / "ran").exists())

        nix_root.rmdir()
        profile = self.home / ".nix-profile/bin/nix"
        profile.parent.mkdir(parents=True)
        profile.write_text("#!/bin/sh\nexit 0\n")
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("existing Nix installation marker", result.stderr)

        profile.unlink()
        self.bash_mock("nix", 'exit 0')
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("Nix command already exists", result.stderr)

    def test_successful_installer_without_daemon_store_or_failing_installer_fails(self):
        self.set_linux()
        self.set_systemd()
        self.set_sudo()
        installer = self.installer_file(self.nix_installer(ping_failure=True))
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("daemon store verification failed", result.stderr)
        self.assertNotIn("installation verified", result.stdout)

        installer.write_text("exit 23\n")
        result = self.run_script("--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("installation verified", result.stdout)


if __name__ == "__main__":
    unittest.main()
