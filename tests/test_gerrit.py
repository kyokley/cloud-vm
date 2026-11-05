"""Focused checks for the isolated Rocker-frost Gerrit configuration."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "vms" / "rocker-frost.nix"
GERRIT_IMAGE = (
    "docker.io/gerritcodereview/gerrit:3.14.5"
    "@sha256:09b8ad30e8b60c3a28e73dc51b1ab14ad0cd6a8d62e68769242f3396dd5f2c57"
)
NGINX_IMAGE = (
    "docker.io/library/nginx:1.30.6-alpine"
    "@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949"
)
VOLUMES = {
    "gerrit-git": "/var/gerrit/git",
    "gerrit-index": "/var/gerrit/index",
    "gerrit-cache": "/var/gerrit/cache",
    "gerrit-db": "/var/gerrit/db",
    "gerrit-etc": "/var/gerrit/etc",
    "gerrit-data": "/var/gerrit/data",
    "gerrit-logs": "/var/gerrit/logs",
}


@unittest.skipUnless(shutil.which("nix"), "Nix is required for flake evaluation")
class GerritFlakeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="cloud-vm-gerrit-test-")
        self.root = pathlib.Path(self.tempdir.name) / "project"
        self.root.mkdir()
        for name in ("flake.nix", "flake.lock"):
            shutil.copy2(ROOT / name, self.root / name)
        for name in ("cloud_vm", "config", "modules", "scripts"):
            shutil.copytree(ROOT / name, self.root / name)

    def tearDown(self):
        self.tempdir.cleanup()

    def evaluate(self, attr, apply=None):
        command = [
            "nix",
            "--extra-experimental-features",
            "nix-command flakes",
            "eval",
            "--no-update-lock-file",
            "--no-write-lock-file",
            "--json",
            f"path:{self.root}#{attr}",
        ]
        if apply:
            command.extend(("--apply", apply))
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode:
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
        return json.loads(result.stdout)

    def projection(self, vm):
        return self.evaluate(
            f"homeConfigurations.{vm}.config",
            "c: { "
            "podmanEnabled = c.services.podman.enable; "
            "autoUpdate = c.services.podman.autoUpdate.enable; "
            "networks = c.services.podman.networks; "
            "namedVolumes = c.services.podman.volumes; "
            "containers = c.services.podman.containers; "
            'startup = c.xdg.configFile."gerrit/start.sh".text; '
            'nginx = c.xdg.configFile."gerrit/nginx.conf".text; '
            " }",
        )

    def test_named_vm_effective_container_and_proxy_contract(self):
        config = self.projection("rocker-frost")
        self.assertTrue(config["podmanEnabled"])
        self.assertFalse(config["autoUpdate"])
        containers = config["containers"]
        self.assertEqual(set(containers), {"gerrit", "gerrit-proxy"})
        gerrit = containers["gerrit"]
        proxy = containers["gerrit-proxy"]
        self.assertEqual(gerrit["image"], GERRIT_IMAGE)
        self.assertEqual(proxy["image"], NGINX_IMAGE)
        self.assertEqual(gerrit.get("ports", []), [])
        self.assertEqual(proxy["ports"], ["127.0.0.1:8000:8080"])
        self.assertEqual(set(config["networks"]), {"gerrit"})
        self.assertEqual(set(config["namedVolumes"]), set(VOLUMES))
        self.assertEqual(gerrit["network"], ["gerrit.network"])
        self.assertEqual(proxy["network"], ["gerrit.network"])
        self.assertEqual(gerrit["networkAlias"], ["gerrit"])
        self.assertNotIn("host", gerrit["network"])
        self.assertNotIn("host", proxy["network"])
        self.assertFalse(gerrit.get("privileged", False))
        self.assertFalse(proxy.get("privileged", False))
        self.assertEqual(
            proxy["extraConfig"]["Unit"]["Requires"], "podman-gerrit.service"
        )
        self.assertEqual(proxy["extraConfig"]["Unit"]["After"], "podman-gerrit.service")

        mounts = gerrit["volumes"]
        for name, destination in VOLUMES.items():
            self.assertTrue(config["namedVolumes"][name]["preserve"])
            self.assertTrue(
                any(
                    mount.startswith(f"{name}.volume:{destination}") for mount in mounts
                ),
                f"missing persistent volume {name} at {destination}",
            )
        self.assertIn(
            "gerrit-htpasswd,type=mount,target=/run/secrets/gerrit.htpasswd,mode=0444",
            " ".join(proxy["extraPodmanArgs"]),
        )
        self.assertNotIn(":U", " ".join(mounts))

    def test_nginx_authenticates_every_route_and_forwards_credentials(self):
        nginx = self.projection("rocker-frost")["nginx"]
        self.assertIn("auth_basic", nginx)
        self.assertIn("auth_basic_user_file /run/secrets/gerrit.htpasswd", nginx)
        self.assertIn("proxy_set_header Authorization $http_authorization", nginx)
        self.assertIn("proxy_set_header Host $http_host", nginx)
        self.assertIn("proxy_set_header X-Forwarded-Proto https", nginx)
        self.assertIn("proxy_pass http://gerrit:8080", nginx)
        self.assertNotIn("auth_basic off", nginx)
        self.assertNotIn("dev", nginx.lower())

    def test_startup_configures_trusted_http_auth_before_serving(self):
        startup = self.projection("rocker-frost")["startup"]
        self.assertIn("/entrypoint.sh init", startup)
        self.assertIn("auth.type", startup)
        self.assertIn("HTTP", startup)
        self.assertIn("auth.httpHeader", startup)
        self.assertIn("Authorization", startup)
        self.assertIn("auth.trustContainerAuth", startup)
        self.assertIn("true", startup)
        self.assertIn(".cloud-vm-initialized", startup)
        self.assertIn("exec /entrypoint.sh", startup)
        self.assertLess(
            startup.index("auth.trustContainerAuth"),
            startup.index("exec /entrypoint.sh"),
        )
        self.assertNotIn("dev auth", startup.lower())

    def run_startup(self, startup, site, mode="ok"):
        bindir = site.parent / "bin"
        bindir.mkdir(exist_ok=True)
        trace = site.parent / "trace"
        entrypoint = bindir / "entrypoint"
        entrypoint.write_text(
            "#!/usr/bin/env bash\n"
            'printf "entrypoint:%s\\n" "${1:-serve}" >> "$TRACE"\n'
            'if [[ "${1:-}" == init ]]; then\n'
            '  mkdir -p "$GERRIT_ROOT/git/All-Projects.git" '
            '"$GERRIT_ROOT/git/All-Users.git" "$GERRIT_ROOT/etc"\n'
            '  touch "$GERRIT_ROOT/etc/gerrit.config"\n'
            "fi\n"
        )
        entrypoint.chmod(0o755)
        git = bindir / "git"
        git.write_text(
            "#!/usr/bin/env bash\n"
            '[[ "$1" == config && "$2" == -f ]] || exit 90\n'
            "file=$3; shift 3\n"
            'if [[ "$1" == --get ]]; then\n'
            '  grep -F "${2}=" "$file" | tail -n 1 | cut -d= -f2-\n'
            "else\n"
            '  [[ "${FAIL_KEY:-}" != "$1" ]] || exit 2\n'
            '  printf "%s=%s\\n" "$1" "$2" >> "$file"\n'
            "fi\n"
        )
        git.chmod(0o755)
        script = site.parent / "start.sh"
        script.write_text(
            startup.replace("/var/gerrit", str(site)).replace(
                "/entrypoint.sh", str(entrypoint)
            )
        )
        env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TRACE": str(trace),
            "GERRIT_ROOT": str(site),
        }
        if mode != "ok":
            env["FAIL_KEY"] = mode
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        return result, trace

    def test_startup_orders_init_and_auth_and_fails_closed(self):
        startup = self.projection("rocker-frost")["startup"]
        with tempfile.TemporaryDirectory(prefix="gerrit-startup-test-") as temp:
            site = pathlib.Path(temp) / "site"
            site.mkdir()
            for directory in ("git", "index", "cache", "db", "etc", "data", "logs"):
                (site / directory).mkdir()
            result, trace = self.run_startup(startup, site)
            self.assertEqual(result.returncode, 0, result.stderr)
            events = trace.read_text().splitlines()
            self.assertEqual(events, ["entrypoint:init", "entrypoint:serve"])
            self.assertTrue((site / "data/.cloud-vm-initialized").is_file())
            saved_config = (site / "etc/gerrit.config").read_text()
            self.assertLess(
                saved_config.index("auth.type=HTTP"),
                saved_config.index("auth.httpHeader=Authorization"),
            )
            self.assertLess(
                saved_config.index("auth.httpHeader=Authorization"),
                saved_config.index("auth.trustContainerAuth=true"),
            )
            trace.unlink()
            result, trace = self.run_startup(startup, site)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(trace.read_text().splitlines(), ["entrypoint:serve"])

        with tempfile.TemporaryDirectory(prefix="gerrit-config-failure-") as temp:
            site = pathlib.Path(temp) / "site"
            site.mkdir()
            for directory in ("git", "index", "cache", "db", "etc", "data", "logs"):
                (site / directory).mkdir()
            result, trace = self.run_startup(startup, site, "auth.httpHeader")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(trace.read_text().splitlines(), ["entrypoint:init"])
            self.assertFalse((site / "data/.cloud-vm-initialized").exists())

        with tempfile.TemporaryDirectory(prefix="gerrit-partial-init-") as temp:
            site = pathlib.Path(temp) / "site"
            partial = site / "git/All-Projects.git"
            partial.mkdir(parents=True)
            result, trace = self.run_startup(startup, site)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("without its initialization marker", result.stderr)
            self.assertFalse(trace.exists())
            self.assertTrue(partial.is_dir())

    def test_fresh_site_accepts_image_seeded_gerrit_config(self):
        startup = self.projection("rocker-frost")["startup"]
        with tempfile.TemporaryDirectory(prefix="gerrit-seeded-config-") as temp:
            site = pathlib.Path(temp) / "site"
            site.mkdir()
            for directory in ("git", "index", "cache", "db", "etc", "data", "logs"):
                (site / directory).mkdir()
            seeded_config = site / "etc/gerrit.config"
            seeded_config.write_text("[gerrit]\nserverId = image-seed\n")

            result, trace = self.run_startup(startup, site)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                trace.read_text().splitlines(), ["entrypoint:init", "entrypoint:serve"]
            )
            saved_config = seeded_config.read_text()
            self.assertIn("serverId = image-seed", saved_config)
            self.assertIn("auth.trustContainerAuth=true", saved_config)
            self.assertTrue((site / "data/.cloud-vm-initialized").is_file())

    def test_unmarked_runtime_and_secret_state_is_rejected_without_mutation(self):
        startup = self.projection("rocker-frost")["startup"]
        unmarked_state = (
            ("All-Projects", "git/All-Projects.git/config"),
            ("runtime data", "index/segment-1"),
            ("secure config", "etc/secure.config"),
            ("SSH key", "etc/ssh_host_rsa_key"),
        )
        for label, relative_path in unmarked_state:
            with (
                self.subTest(state=label),
                tempfile.TemporaryDirectory(prefix="gerrit-unmarked-state-") as temp,
            ):
                site = pathlib.Path(temp) / "site"
                site.mkdir()
                for directory in ("git", "index", "cache", "db", "etc", "data", "logs"):
                    (site / directory).mkdir()
                state = site / relative_path
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text("preserve this state\n")

                result, trace = self.run_startup(startup, site)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("without", result.stderr)
                self.assertIn("initialization marker", result.stderr)
                self.assertFalse(trace.exists())
                self.assertEqual(state.read_text(), "preserve this state\n")

    def test_base_and_unrelated_vm_do_not_enable_podman_or_gerrit(self):
        (self.root / "config" / "vms" / "alice.nix").write_text(
            "{ ... }: { fleet.vms.alice = { "
            'target = { username = "alice"; homeDirectory = "/home/alice"; }; '
            "}; }\n"
        )
        for vm in ("vm", "alice"):
            with self.subTest(vm=vm):
                self.assertFalse(
                    self.evaluate(
                        f"homeConfigurations.{vm}.config.services.podman.enable"
                    )
                )


if __name__ == "__main__":
    unittest.main()
