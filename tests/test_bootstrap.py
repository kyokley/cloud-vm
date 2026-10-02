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
        self.home = pathlib.Path(self.temp.name) / "home"
        self.home.mkdir()
        self.bin = pathlib.Path(self.temp.name) / "bin"
        self.bin.mkdir()
        self.script = pathlib.Path(self.temp.name) / "bootstrap-nix.sh"
        source = SCRIPT.read_text()
        source = source.replace("/nix/var/nix/profiles", f"{self.temp.name}/nix/var/nix/profiles")
        source = source.replace("/nix/store", f"{self.temp.name}/nix/store")
        source = source.replace("[[ -d /nix && -w /nix ]]", f"[[ -d {self.temp.name}/nix && -w {self.temp.name}/nix ]]")
        source = source.replace("/run/systemd/system", f"{self.temp.name}/systemd")
        selinux = pathlib.Path(self.temp.name) / "selinux"
        source = source.replace("[[ -e /sys/fs/selinux ]]", f"[[ -e {selinux} ]]")
        source = source.replace("[[ -e /selinux ]]", f"[[ -e {selinux}-legacy ]]")
        self.script.write_text(source)
        self.script.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), PATH=f"{self.bin}:/usr/bin:/bin", NIX_TRACE=str(pathlib.Path(self.temp.name) / "nix-trace"))

    def tearDown(self):
        self.temp.cleanup()

    def cmd(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
        return path

    def run_script(self, *args):
        return subprocess.run([str(self.script), *args], env=self.env, text=True, capture_output=True)

    def test_help_documents_single_user_prep_and_options(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("administrator", result.stdout)
        self.assertIn("--installer-file PATH", result.stdout)

    def test_mode_consent_and_root_rejected(self):
        self.assertNotEqual(self.run_script("--yes" ).returncode, 0)
        self.assertIn("--yes", self.run_script("--no-daemon").stderr)
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && { echo 0; exit; }; echo root')
        result = self.run_script("--no-daemon", "--yes")
        self.assertIn("non-root", result.stderr)

    def test_unsupported_os_and_architecture_rejected(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Darwin')
        self.assertIn("only Linux", self.run_script("--no-daemon", "--yes").stderr)
        self.cmd("uname", '[[ "$1" == -m ]] && echo riscv64 || echo Linux')
        self.assertIn("unsupported Linux architecture", self.run_script("--no-daemon", "--yes").stderr)

    def test_partial_install_fails_and_does_not_run_installer(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("nix", '[[ "$1" == --version ]] && exit 0; exit 1')
        installer = pathlib.Path(self.temp.name) / "installer"
        installer.write_text("touch '" + str(pathlib.Path(self.temp.name) / "ran") + "'\n")
        result = self.run_script("--no-daemon", "--yes", "--installer-file", str(installer))
        self.assertIn("partial Nix", result.stderr)
        self.assertFalse((pathlib.Path(self.temp.name) / "ran").exists())

    def test_existing_usable_nix_bypasses_installer(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        nix = self.home / ".nix-profile/bin/nix"
        nix.parent.mkdir(parents=True)
        nix.write_text("#!/bin/sh\nexit 0\n")
        nix.chmod(0o755)
        result = self.run_script("--no-daemon", "--yes", "--installer-file", "/missing")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("already usable", result.stdout)

    def test_reviewed_installer_never_curls_and_executes_selected_mode(self):
        curl_trace = pathlib.Path(self.temp.name) / "curl-trace"
        installer_trace = pathlib.Path(self.temp.name) / "installer-trace"
        self.cmd("curl", f"echo curl >> {curl_trace}; exit 99")
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        (self.home / ".local").mkdir()
        (self.home / ".local/share").mkdir()
        nix_root = pathlib.Path(self.temp.name) / "nix"
        nix_root.mkdir()
        installer = pathlib.Path(self.temp.name) / "reviewed"
        installer.write_text(
            f'printf "%s\\n" "$@" > "{self.temp.name}/installer-args"\n'
            "mkdir -p \"$HOME/.nix-profile/bin\"\n"
            "printf '#!/bin/sh\\nprintf \"%%s\\\\n\" \"$*\" >> \"$NIX_TRACE\"\\nexit 0\\n' > \"$HOME/.nix-profile/bin/nix\"\n"
            "chmod +x \"$HOME/.nix-profile/bin/nix\"\n"
            f"/usr/bin/touch '{installer_trace}'\n"
        )
        result = self.run_script("--no-daemon", "--yes", "--installer-file", str(installer))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Nix installation verified", result.stdout)
        self.assertFalse(curl_trace.exists())
        self.assertTrue(installer_trace.exists())
        self.assertEqual((pathlib.Path(self.temp.name) / "installer-args").read_text().splitlines(), ["--no-daemon"])
        self.assertIn("--experimental-features nix-command store ping --store local", (pathlib.Path(self.temp.name) / "nix-trace").read_text())

    def test_download_failure_propagates_without_installer_execution(self):
        trace = pathlib.Path(self.temp.name) / "trace"
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        self.cmd("curl", f"echo \"$*\" >> {trace}; exit 22")
        (pathlib.Path(self.temp.name) / "nix").mkdir()
        result = self.run_script("--no-daemon", "--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("official installer download failed", result.stderr)
        curl_args = shlex.split(trace.read_text())
        self.assertIn("https://nixos.org/nix/install", curl_args)
        self.assertIn("--proto-redir", curl_args)
        self.assertFalse(pathlib.Path(curl_args[curl_args.index("--output") + 1]).exists())

    def test_successful_mocked_download_executes_and_verifies_install(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        (pathlib.Path(self.temp.name) / "nix").mkdir()
        consent = pathlib.Path(self.temp.name) / "consent"
        args_path = pathlib.Path(self.temp.name) / "installer-args"
        body = f'''while (($#)); do
  if [[ "$1" == --output ]]; then output=$2; shift 2; else shift; fi
done
cat >"$output" <<'INSTALLER'
printf '%s\\n' "$NIX_INSTALLER_YES" > "{consent}"
if IFS= read -r line; then exit 12; fi
printf '%s\\n' "$@" > "{args_path}"
mkdir -p "$HOME/.nix-profile/bin"
printf '#!/bin/sh\\nexit 0\\n' > "$HOME/.nix-profile/bin/nix"
chmod +x "$HOME/.nix-profile/bin/nix"
INSTALLER
'''
        self.cmd("curl", body)
        result = self.run_script("--no-daemon", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(consent.read_text().strip(), "1")
        self.assertEqual(args_path.read_text().splitlines(), ["--no-daemon"])
        self.assertIn("Nix installation verified", result.stdout)

    def test_successful_installer_without_usable_store_fails_verification(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        (pathlib.Path(self.temp.name) / "nix").mkdir()
        installer = pathlib.Path(self.temp.name) / "reviewed"
        installer.write_text("exit 0\n")
        result = self.run_script("--no-daemon", "--yes", "--installer-file", str(installer))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no usable Nix store", result.stderr)
        self.assertNotIn("Nix installation verified", result.stdout)
        installer.write_text("exit 22\n")
        result = self.run_script("--no-daemon", "--yes", "--installer-file", str(installer))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Nix installation verified", result.stdout)

    def test_daemon_requires_sudo_authorization_and_usable_privilege(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        self.cmd("sudo", '[[ "$1" == -n && "$2" == true ]] && exit 0; exit 0')
        self.cmd("systemctl", 'echo running')
        self.cmd("getenforce", 'echo Disabled')
        systemd = pathlib.Path(self.temp.name) / "systemd"
        systemd.mkdir()
        installer = pathlib.Path(self.temp.name) / "reviewed"
        installer.write_text(
            "mkdir -p \"$HOME/.nix-profile/bin\"\n"
            "printf '#!/bin/sh\\nexit 0\\n' > \"$HOME/.nix-profile/bin/nix\"\n"
            "chmod +x \"$HOME/.nix-profile/bin/nix\"\n"
        )
        result = self.run_script("--daemon", "--yes")
        self.assertIn("--allow-sudo", result.stderr)
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Nix installation verified", result.stdout)
        self.cmd("sudo", 'exit 1')
        (self.home / ".nix-profile/bin/nix").unlink()
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("sudo is unavailable", result.stderr)

    def test_unavailable_systemd_stops_before_installer(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        self.cmd("sudo", 'exit 0')
        self.cmd("systemctl", 'echo running')
        self.cmd("getenforce", 'echo Disabled')
        installer = pathlib.Path(self.temp.name) / "reviewed"
        marker = pathlib.Path(self.temp.name) / "ran"
        installer.write_text(f"/usr/bin/touch '{marker}'\n")
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("requires usable systemd", result.stderr)
        self.assertFalse(marker.exists())

    def test_daemon_runs_installer_as_user_and_wraps_sudo_noninteractively(self):
        self.env["NIX_BECOME"] = "/untrusted/inherited/sudo"
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        trace = pathlib.Path(self.temp.name) / "sudo-trace"
        self.cmd("sudo", f'echo "$*" >> "{trace}"; exit 0')
        self.cmd("systemctl", 'echo running')
        self.cmd("getenforce", 'echo Disabled')
        (pathlib.Path(self.temp.name) / "systemd").mkdir()
        installer = pathlib.Path(self.temp.name) / "reviewed"
        installer.write_text(
            f'printf "%s\\n" "$@" > "{self.temp.name}/installer-args"\n'
            f'printf "%s\\n%s\\n" "$NIX_INSTALLER_YES" "$NIX_BECOME" > "{self.temp.name}/installer-env"\n'
            "if IFS= read -r line; then exit 9; fi\n"
            "set -e\n"
            "\"$NIX_BECOME\" true\n"
            "mkdir -p \"$HOME/.nix-profile/bin\"\n"
            "printf '#!/bin/sh\\nprintf \"%%s\\\\n\" \"$*\" >> \"$NIX_TRACE\"\\nexit 0\\n' > \"$HOME/.nix-profile/bin/nix\"\n"
            "chmod +x \"$HOME/.nix-profile/bin/nix\"\n"
            f'printf running > "{self.temp.name}/ran"\n'
        )
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((pathlib.Path(self.temp.name) / "ran").exists())
        installer_env = (pathlib.Path(self.temp.name) / "installer-env").read_text().splitlines()
        self.assertEqual(installer_env[0], "1")
        self.assertTrue(os.path.isabs(installer_env[1]))
        self.assertEqual(pathlib.Path(installer_env[1]).name, "sudo")
        self.assertEqual((pathlib.Path(self.temp.name) / "installer-args").read_text().splitlines(), ["--daemon"])
        self.assertNotEqual(installer_env[1], "/untrusted/inherited/sudo")
        self.assertGreaterEqual(trace.read_text().splitlines().count("-n true"), 2)
        self.assertIn("--experimental-features nix-command store ping --store daemon", (pathlib.Path(self.temp.name) / "nix-trace").read_text())

    def test_noninteractive_sudo_failure_propagates_from_installer(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        trace = pathlib.Path(self.temp.name) / "sudo-calls"
        self.cmd("sudo", f'''echo call >> "{trace}"
count=$(wc -l < "{trace}")
((count == 1)) && exit 0
exit 17''')
        self.cmd("systemctl", 'echo running')
        self.cmd("getenforce", 'echo Disabled')
        (pathlib.Path(self.temp.name) / "systemd").mkdir()
        marker = pathlib.Path(self.temp.name) / "ran-after-sudo"
        installer = pathlib.Path(self.temp.name) / "reviewed"
        installer.write_text(f'set -e\n"$NIX_BECOME" true\n/usr/bin/touch "{marker}"\n')
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Nix installation verified", result.stdout)
        self.assertFalse(marker.exists())
        self.assertEqual(trace.read_text().splitlines(), ["call", "call"], result.stderr)

    def test_daemon_rejects_enabled_and_unknown_selinux(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        self.cmd("sudo", 'exit 0')
        self.cmd("systemctl", 'echo running')
        (pathlib.Path(self.temp.name) / "systemd").mkdir()
        installer = pathlib.Path(self.temp.name) / "reviewed"
        installer.write_text("# reviewed\n")
        self.cmd("getenforce", 'echo Enforcing')
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("requires disabled SELinux", result.stderr)
        (self.bin / "getenforce").write_text("#!/bin/bash\nexit 1\n")
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("SELinux status is unknown", result.stderr)

    def test_selinux_missing_tool_and_interfaces_fail_closed(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        self.cmd("sudo", 'exit 0')
        self.cmd("systemctl", 'echo running')
        (pathlib.Path(self.temp.name) / "systemd").mkdir()
        installer = pathlib.Path(self.temp.name) / "reviewed"
        marker = pathlib.Path(self.temp.name) / "installer-ran"
        installer.write_text(f"/usr/bin/touch '{marker}'\n")
        curl_trace = pathlib.Path(self.temp.name) / "curl-trace"
        self.cmd("curl", f"echo invoked >> '{curl_trace}'")
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("getenforce is required", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(curl_trace.exists())
        (pathlib.Path(self.temp.name) / "selinux").mkdir()
        result = self.run_script("--daemon", "--yes", "--allow-sudo", "--installer-file", str(installer))
        self.assertIn("absent or unreadable interfaces", result.stderr)
        self.assertFalse(marker.exists())

    def test_single_user_rejects_sudo_flag_and_requires_prepared_store(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        self.cmd("id", '[[ "$1" == -u ]] && echo 1000 || echo user')
        result = self.run_script("--no-daemon", "--yes", "--allow-sudo")
        self.assertIn("not used for single-user", result.stderr)
        result = self.run_script("--no-daemon", "--yes")
        self.assertIn("administrator-prepared writable", result.stderr)

    def test_invalid_reviewed_file_fails(self):
        self.cmd("uname", '[[ "$1" == -m ]] && echo x86_64 || echo Linux')
        result = self.run_script("--no-daemon", "--yes", "--installer-file", "/missing")
        self.assertIn("readable, non-empty regular file", result.stderr)


if __name__ == "__main__":
    unittest.main()
