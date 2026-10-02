import os
import pathlib
import json
import hashlib
import shlex
import subprocess
import tarfile
import tempfile
import unittest
import io

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "vm.sh"


class VmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bin = pathlib.Path(self.temp.name) / "bin"
        self.bin.mkdir()
        self.trace = pathlib.Path(self.temp.name) / "trace"
        self.home = pathlib.Path(self.temp.name) / "guest-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.bin}:/usr/bin:/bin"
        self.env["TRACE"] = str(self.trace)

    def tearDown(self):
        self.temp.cleanup()

    def mock(self, name, source):
        path = self.bin / name
        path.write_text((source if source.startswith("#!") else "#!/bin/bash\n" + source) + "\n")
        path.chmod(0o755)

    def run_script(self, *args):
        return subprocess.run([str(SCRIPT), *args], cwd=self.temp.name, env=self.env, text=True, capture_output=True)

    def test_help_and_name_validation(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("inspect NAME", result.stdout)
        self.assertIn("bootstrap NAME --yes --allow-sudo", result.stdout)
        self.assertNotEqual(self.run_script("inspect", "Bad_Name").returncode, 0)

    def test_exact_gateway_and_guest_inspect_payload(self):
        # Execute the transmitted real vm.sh guest entry point in the SSH mock.
        self.mock("ssh", '''#!/usr/bin/env python3
import os,subprocess,sys
target,command=sys.argv[1:3]
with open(os.environ["TRACE"],"a") as f: f.write(target+" "+command+"\\n")
payload=sys.stdin.read()
result=subprocess.run(["/bin/bash","-s","--","__guest","inspect"],input=payload,env={**os.environ,"HOME":"/home/alice","USER":"alice"},text=True,capture_output=True)
sys.stdout.write(result.stdout); sys.stderr.write(result.stderr); sys.exit(result.returncode)
''')
        result = self.run_script("inspect", "my-vm")
        self.assertEqual(result.returncode, 0, result.stderr + (self.trace.read_text() if self.trace.exists() else ""))
        self.assertIn("vm+my-vm@vm.exe.xyz", self.trace.read_text())
        self.assertIn("username=", result.stdout)

    def test_bootstrap_preserves_guest_file_option_quoting(self):
        self.mock("ssh", '''
printf '%s\\n' "$*" >> "$TRACE"
cat >/dev/null
''')
        path = "/tmp/reviewed file; safe"
        result = self.run_script("bootstrap", "node", "--yes", "--allow-sudo", "--installer-file", path)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = self.trace.read_text()
        self.assertIn("--installer-file", line)
        self.assertIn("reviewed\\ file\\;\\ safe", line)
        self.assertIn("vm+node@vm.exe.xyz", line)

    def test_bootstrap_rejects_legacy_modes_and_requires_explicit_authority(self):
        for args, message in ((("--daemon", "--yes", "--allow-sudo"), "legacy"),
                              (("--no-daemon", "--yes", "--allow-sudo"), "legacy"),
                              (("--yes",), "requires explicit --allow-sudo"),
                              (("--allow-sudo",), "requires explicit --yes")):
            self.trace.unlink(missing_ok=True)
            result = self.run_script("bootstrap", "node", *args)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertFalse(self.trace.exists())

    def test_apply_requires_inputs_and_local_prerequisites(self):
        result = self.run_script("apply", "node")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nix is required", result.stderr)

    def test_apply_rejects_missing_local_inputs_before_ssh(self):
        repo = pathlib.Path(self.temp.name) / "empty-project"
        (repo / "scripts").mkdir(parents=True)
        (repo / "config").mkdir()
        script = repo / "scripts/vm.sh"
        script.write_text(SCRIPT.read_text())
        script.chmod(0o755)
        for command in ("nix", "tar", "ssh"):
            self.mock(command, "exit 0")
        result = subprocess.run([str(script), "apply", "node"], env=self.env, text=True, capture_output=True)
        self.assertIn("required local input missing or unsafe: flake.nix", result.stderr)
        self.assertFalse(self.trace.exists())

        repo = pathlib.Path(self.temp.name) / "missing-lock-project"
        (repo / "scripts").mkdir(parents=True)
        (repo / "config").mkdir()
        (repo / "flake.nix").write_text("{}\n")
        (repo / "config/target.nix").write_text("{}\n")
        (repo / "config/home.nix").write_text("{}\n")
        script = repo / "scripts/vm.sh"
        script.write_text(SCRIPT.read_text())
        script.chmod(0o755)
        result = subprocess.run([str(script), "apply", "node"], env=self.env, text=True, capture_output=True)
        self.assertIn("required local input missing or unsafe: flake.lock", result.stderr)

    def test_apply_rejects_example_identity_before_ssh(self):
        self.mock("nix", 'printf \'{"system":"x86_64-linux","username":"example","homeDirectory":"/home/example"}\\n\'')
        for cmd in ("tar", "ssh", "python3"):
            if cmd != "python3":
                self.mock(cmd, "exit 0")
        result = self.run_script("apply", "node")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("placeholder or unsafe", result.stderr)
        self.assertFalse(self.trace.exists())

    def deployment_mocks(self, fail_stage="", guest_mode="ok"):
        identity = {"ok": ("alice", "1000", str(self.home), "Linux", "x86_64"),
                    "root": ("root", "0", "/root", "Linux", "x86_64"),
                    "mismatch": ("mallory", "1000", str(self.home), "Linux", "x86_64"),
                    "home-mismatch": ("alice", "1000", "/home/other", "Linux", "x86_64"),
                    "arch-mismatch": ("alice", "1000", str(self.home), "Linux", "aarch64")}[guest_mode]
        self.env["FAIL_STAGE"] = fail_stage
        self.env["GUEST_HOME"] = str(self.home)
        self.env["HOME"] = identity[2]
        self.env["GUEST_USER"] = identity[0]
        self.env["GUEST_UID"] = identity[1]
        self.env["GUEST_OS"] = identity[3]
        self.env["GUEST_ARCH"] = identity[4]
        nix_profile = self.home / ".nix-profile/bin/nix"
        nix_profile.parent.mkdir(parents=True, exist_ok=True)
        if nix_profile.exists() or nix_profile.is_symlink():
            nix_profile.unlink()
        nix_profile.symlink_to(self.bin / "nix")
        target = {"system": "x86_64-linux", "username": "alice", "homeDirectory": str(self.home)}
        self.mock("nix", f'''#!/usr/bin/env python3
import json,os,sys,pathlib
if "eval" in sys.argv:
 with open(os.environ["TRACE"],"a") as f: f.write("eval="+" ".join(sys.argv)+"\\n")
 if os.environ.get("FAIL_STAGE")=="eval": sys.exit(30)
 print(json.dumps({target!r})); sys.exit(0)
if "build" in sys.argv:
 with open(os.environ["TRACE"],"a") as f: f.write("build="+" ".join(sys.argv)+"\\n")
 if os.environ.get("FAIL_STAGE")=="build": sys.exit(31)
 out=sys.argv[sys.argv.index("--out-link")+1]
 pathlib.Path(out).mkdir(parents=True,exist_ok=True)
 p=pathlib.Path(out)/"activate"
 p.write_text("#!/bin/sh\\nprintf activation >> \\\"$TRACE\\\"\\n[ \\\"$FAIL_STAGE\\\" != activation ]\\n")
 p.chmod(0o755); sys.exit(0)
if "store" in sys.argv and "ping" in sys.argv:
 with open(os.environ["TRACE"],"a") as f: f.write("store-ping="+" ".join(sys.argv)+"\\n")
 sys.exit(0)
sys.exit(0)
''')
        self.mock("id", '''[[ "$1" == -un ]] && { printf '%s\\n' "$GUEST_USER"; exit; }
[[ "$1" == -u ]] && { printf '%s\\n' "$GUEST_UID"; exit; }
exit 1''')
        self.mock("uname", '''[[ "$1" == -m ]] && printf '%s\\n' "$GUEST_ARCH" || printf '%s\\n' "$GUEST_OS"''')
        self.mock("stat", '''#!/usr/bin/env python3
import os,stat,sys
if sys.argv[2] == "%u": print("2000" if os.environ.get("FAIL_STAGE")=="owner" else os.environ["GUEST_UID"])
else: print(format(stat.S_IMODE(os.stat(sys.argv[3]).st_mode),"o"))
''')
        self.mock("ssh", f'''#!/usr/bin/env python3
import io,os,shlex,subprocess,sys,tarfile,tempfile
target,command=sys.argv[1:3]
trace=os.environ["TRACE"]
def event(s):
 with open(trace,"a") as f: f.write(s+"\\n")
if target != "vm+node@vm.exe.xyz": sys.exit(80)
if command.startswith("bash -s --"):
    args=shlex.split(command)[3:]
    payload=sys.stdin.read()
    op=args[1]
    event(op)
    if op == "prepare" and os.environ.get("FAIL_STAGE")=="prepare": sys.exit(41)
    result=subprocess.run(["/bin/bash","-s","--",*args],input=payload,env=os.environ.copy(),text=True,capture_output=True,preexec_fn=lambda:os.umask(0))
    if op == "identity": event("observed="+repr(result.stdout))
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr); sys.exit(result.returncode)
if "tar -xf" in command:
    event("transfer")
    event("transfer-command="+command)
    if os.environ.get("FAIL_STAGE")=="transfer": sys.exit(42)
    source=tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode="r:*")
    members=source.getmembers(); names=[member.name for member in members]
    packed=io.BytesIO()
    with tarfile.open(fileobj=packed,mode="w") as output:
        for member in members:
            stream=source.extractfile(member)
            member.mode=0o666
            output.addfile(member,stream if stream is None else io.BytesIO(stream.read()))
    with open(trace,"a") as f: f.write("members="+",".join(sorted(names))+"\\n")
    remote_env=os.environ.copy(); remote_env["HOME"]=os.environ["GUEST_HOME"]
    result=subprocess.run(["/bin/bash","-c",command],input=packed.getvalue(),env=remote_env,capture_output=True)
    sys.stdout.buffer.write(result.stdout); sys.stderr.buffer.write(result.stderr); sys.exit(result.returncode)
sys.exit(81)
''')

    def test_apply_transfers_exact_allowlist_then_builds_and_activates(self):
        self.deployment_mocks()
        lock_path = ROOT / "flake.lock"
        lock_before = hashlib.sha256(lock_path.read_bytes()).hexdigest()
        result = self.run_script("apply", "node")
        self.assertEqual(result.returncode, 0, result.stderr + (self.trace.read_text() if self.trace.exists() else ""))
        events = self.trace.read_text()
        self.assertIn("members=config/home.nix,config/target.nix,flake.lock,flake.nix", events)
        transfer_command = next(line for line in events.splitlines() if line.startswith("transfer-command="))
        self.assertIn("umask 077", transfer_command)
        self.assertIn("--no-same-owner --no-same-permissions", transfer_command)
        self.assertLess(events.index("prepare"), events.index("transfer"))
        self.assertLess(events.index("transfer"), events.index("build"))
        self.assertLess(events.index("build"), events.index("activation"))
        eval_line = next(line for line in events.splitlines() if line.startswith("eval="))
        self.assertIn("path:" + str(ROOT), eval_line)
        self.assertIn("--no-update-lock-file", eval_line)
        self.assertIn("--no-write-lock-file", eval_line)
        ping_line = next(line for line in events.splitlines() if line.startswith("store-ping="))
        self.assertIn("--experimental-features nix-command store ping", ping_line)
        self.assertNotIn("--store local", ping_line)
        build_line = next(line for line in events.splitlines() if line.startswith("build="))
        self.assertIn("path:", build_line)
        self.assertIn("--no-update-lock-file", build_line)
        self.assertIn("--no-write-lock-file", build_line)
        self.assertTrue((self.home / ".local/share/cloud-vm/flake.nix").is_file())
        for directory in (self.home / ".local", self.home / ".local/share",
                          self.home / ".local/share/cloud-vm", self.home / ".local/share/cloud-vm/config"):
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        for managed in (self.home / ".local/share/cloud-vm/flake.nix",
                        self.home / ".local/share/cloud-vm/flake.lock",
                        self.home / ".local/share/cloud-vm/config/target.nix",
                        self.home / ".local/share/cloud-vm/config/home.nix"):
            self.assertEqual(managed.stat().st_mode & 0o022, 0)
            self.assertEqual(managed.stat().st_mode & 0o777, 0o600)
        self.assertEqual(hashlib.sha256(lock_path.read_bytes()).hexdigest(), lock_before)

    def test_group_or_other_writable_existing_directories_stop_before_transfer(self):
        for name in ("home", "parent", "destination", "config"):
            with self.subTest(path=name):
                self.trace.unlink(missing_ok=True)
                self.home = pathlib.Path(self.temp.name) / f"{name}-home"
                self.home.mkdir(mode=0o700)
                if name == "home":
                    affected = self.home
                elif name == "parent":
                    affected = self.home / ".local"
                    affected.mkdir(mode=0o777)
                else:
                    destination = self.home / ".local/share/cloud-vm"
                    destination.mkdir(parents=True, mode=0o700)
                    affected = destination if name == "destination" else destination / "config"
                    if name == "config": affected.mkdir(mode=0o777)
                affected.chmod(0o777)
                self.deployment_mocks()
                result = self.run_script("apply", "node")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("group/other-writable directory rejected", result.stderr)
                self.assertEqual(affected.stat().st_mode & 0o777, 0o777)
                events = self.trace.read_text()
                self.assertNotIn("transfer", events)
                self.assertNotIn("build=", events)

    def test_identity_rejections_do_not_prepare_or_transfer(self):
        for mode, message in (("root", "root target"), ("mismatch", "does not match guest"),
                              ("home-mismatch", "does not match guest"),
                              ("arch-mismatch", "architecture does not match")):
            with self.subTest(mode=mode):
                self.trace.unlink(missing_ok=True)
                self.deployment_mocks(guest_mode=mode)
                result = self.run_script("apply", "node")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertNotIn("prepare", self.trace.read_text())
                self.assertNotIn("transfer", self.trace.read_text())

    def test_transfer_build_and_activation_failures_stop_later_steps(self):
        for stage, forbidden in (("transfer", "build"), ("build", "activate"), ("activation", "")):
            with self.subTest(stage=stage):
                self.trace.unlink(missing_ok=True)
                self.deployment_mocks(fail_stage=stage)
                result = self.run_script("apply", "node")
                self.assertNotEqual(result.returncode, 0)
                events = self.trace.read_text()
                self.assertNotIn("bootstrap", events)
                if forbidden:
                    event_lines = events.splitlines()
                    if forbidden == "build":
                        self.assertFalse(any(line.startswith("build=") for line in event_lines))
                    else:
                        self.assertNotIn(forbidden, event_lines)

    def test_stale_lock_evaluation_and_unsafe_destination_stop_before_transfer(self):
        self.deployment_mocks(fail_stage="eval")
        result = self.run_script("apply", "node")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot evaluate lib.target", result.stderr)
        self.assertNotIn("prepare", self.trace.read_text())

        self.trace.unlink()
        self.deployment_mocks()
        outside = pathlib.Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.home / ".local").symlink_to(outside)
        result = self.run_script("apply", "node")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink path rejected", result.stderr)
        self.assertNotIn("transfer", self.trace.read_text())

        self.trace.unlink()
        self.home = pathlib.Path(self.temp.name) / "owner-home"
        self.home.mkdir()
        self.deployment_mocks(fail_stage="owner")
        result = self.run_script("apply", "node")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe owner", result.stderr)
        self.assertNotIn("transfer", self.trace.read_text())


if __name__ == "__main__":
    unittest.main()
