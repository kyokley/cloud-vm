import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rm-vm.sh"
BASH = shutil.which("bash")
PYTHON = shutil.which("python3")


class RmVmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.trace = self.root / "trace"
        self.env = os.environ.copy()
        self.env.update(
            PATH=(
                f"{self.bin}:{pathlib.Path(BASH).parent}:"
                f"{pathlib.Path(PYTHON).parent}:{os.environ['PATH']}"
            ),
            TRACE=str(self.trace),
            REMOTE_HOST="node",
        )

    def tearDown(self):
        self.temp.cleanup()

    def mock(self, name, source):
        path = self.bin / name
        path.write_text("#!/usr/bin/env python3\n" + source + "\n")
        path.chmod(0o755)
        return path

    def set_mocks(self, pages=None, fail=""):
        self.env.update(PAGES=json.dumps([] if pages is None else pages), FAIL=fail)
        self.env.pop("FAIL_STATUS", None)
        self.env.pop("DELETE_STATUS", None)
        self.mock("hostname", 'import os; print(os.environ["REMOTE_HOST"])')
        self.mock(
            "curl",
            """
import json,os,sys
from urllib.parse import parse_qs,urlencode,urlparse,urlunparse

args=sys.argv[1:]
urls=[arg for arg in args if arg.startswith("https://")]
if len(urls)!=1: sys.exit("expected one HTTPS URL")
url=urls[0]
parts=urlparse(url)
method="DELETE" if "--request" in args else "GET"
if parts.scheme!="https" or parts.netloc!="mattermost.int.exe.xyz": sys.exit("wrong API origin")
if args[args.index("--connect-timeout")+1]!="5" or args[args.index("--max-time")+1]!="20": sys.exit("missing bounded timeout")
if "--header" in args or "-H" in args or any("permanent" in arg for arg in args): sys.exit("unexpected auth/permanent option")
if method=="GET":
 if parts.path!="/api/v4/users" or parts.query or "--get" not in args: sys.exit("wrong users endpoint")
 query={}
 for index,arg in enumerate(args):
  if arg=="--data-urlencode":
   key,value=args[index+1].split("=",1)
   query[key]=value
 if set(query)!={"active","page","per_page"} or query["active"]!="true": sys.exit("wrong user query")
 url=urlunparse(parts._replace(query=urlencode(query)))
else:
 if not parts.path.startswith("/api/v4/users/") or parts.query: sys.exit("wrong delete endpoint")
 if "--request" not in args or args[args.index("--request")+1]!="DELETE": sys.exit("wrong delete method")
output=args[args.index("--output")+1]
with open(os.environ["TRACE"],"a") as stream: stream.write("api="+method+" "+url+"\\n")
if method=="GET" and os.environ.get("FAIL")=="get-transport": sys.exit(8)
if method=="DELETE" and os.environ.get("FAIL")=="delete-transport": sys.exit(9)
if method=="GET":
 page=int(query["page"])
 pages=json.loads(os.environ["PAGES"])
 payload=pages[page] if page<len(pages) else []
 if os.environ.get("FAIL")=="invalid-json":
  open(output,"w").write("not json")
  print("200",end="")
  sys.exit()
 if os.environ.get("FAIL")=="invalid-schema": payload={"users":[]}
 status=os.environ.get("FAIL_STATUS","200")
else:
 payload={}
 status=os.environ.get("DELETE_STATUS","200")
open(output,"w").write(json.dumps(payload))
print(status,end="")
""",
        )
        self.mock(
            "ssh",
            f"""import json,os,subprocess,sys
target=sys.argv[1]
command=sys.argv[2:]
with open(os.environ["TRACE"],"a") as stream: stream.write("ssh="+target+" "+" ".join(command)+"\\n")
if target=="exe.dev":
 if command[:2]==["ls","--json"]:
  if os.environ.get("FAIL")=="inventory-transport": sys.exit(12)
  if os.environ.get("FAIL")=="inventory-json": print("not json"); sys.exit()
  print(json.dumps({{"vms":[{{"vm_name":"one"}},{{"vm_name":"two"}}]}})); sys.exit()
 if command[:1]==["rm"]: sys.exit(0)
if target.startswith("vm+"):
 if os.environ.get("FAIL")=="ssh": sys.exit(4)
 result=subprocess.run([{BASH!r},"-s"],input=sys.stdin.read(),text=True,env=os.environ.copy(),capture_output=True)
 sys.stdout.write(result.stdout)
 sys.stderr.write(result.stderr)
 sys.exit(result.returncode)
sys.exit(5)
""",
        )

    def run_script(self, *args):
        return subprocess.run(
            [str(SCRIPT), *args], env=self.env, text=True, capture_output=True
        )

    def events(self):
        return self.trace.read_text().splitlines() if self.trace.exists() else []

    def test_multiple_vm_cleanup_precedes_delete_and_uses_exact_remote_prefix(self):
        users = [
            {"username": "node-suffix", "id": "a" * 26},
            {"username": "node-", "id": "b" * 26},
            {"username": "other-node-suffix", "id": "c" * 26},
            {"username": "bot-ignored", "id": "d" * 26},
            {"username": "node-longer", "id": "e" * 26},
        ]
        self.set_mocks([users, []])
        result = self.run_script("one", "two")
        self.assertEqual(result.returncode, 0, result.stderr + "\n".join(self.events()))
        events = self.events()
        for vm in ("one", "two"):
            start = events.index(f"ssh=vm+{vm}@vm.exe.xyz bash -s")
            deletion = events.index(f"ssh=exe.dev rm {vm}")
            self.assertLess(start, deletion)
            deleted = [
                line for line in events[start:deletion] if line.startswith("api=DELETE")
            ]
            self.assertEqual(len(deleted), 2)
            self.assertTrue(any("users/" + "a" * 26 in line for line in deleted))
            self.assertTrue(any("users/" + "e" * 26 in line for line in deleted))
            self.assertFalse(
                any(
                    any(user_id in line for user_id in ("b" * 26, "c" * 26, "d" * 26))
                    for line in deleted
                )
            )
        self.assertEqual(sum(line.startswith("ssh=exe.dev rm") for line in events), 2)

    def test_get_requests_use_proxy_query_and_bounded_no_auth_options(self):
        self.set_mocks([[]])
        result = self.run_script("one")
        self.assertEqual(result.returncode, 0, result.stderr)
        get_urls = [
            line.removeprefix("api=GET ")
            for line in self.events()
            if line.startswith("api=GET ")
        ]
        self.assertEqual(len(get_urls), 1)
        for url in get_urls:
            parsed = urlparse(url)
            self.assertEqual(parsed.scheme, "https")
            self.assertEqual(parsed.netloc, "mattermost.int.exe.xyz")
            self.assertEqual(parsed.path, "/api/v4/users")
            query = parse_qs(parsed.query)
            self.assertEqual(query["active"], ["true"])
            self.assertEqual(query["per_page"], ["200"])
        self.assertEqual(
            [parse_qs(urlparse(url).query)["page"] for url in get_urls], [["0"]]
        )

    def test_collects_every_page_before_deleting_and_short_page_does_not_stop_scan(
        self,
    ):
        first = {"username": "node-first", "id": "a" * 26}
        second = {"username": "node-second", "id": "b" * 26}
        self.set_mocks([[first], [second], []])
        result = self.run_script("one")
        self.assertEqual(result.returncode, 0, result.stderr)
        api_events = [line for line in self.events() if line.startswith("api=")]
        self.assertEqual(
            [line.split()[0] for line in api_events],
            ["api=GET"] * 3 + ["api=DELETE"] * 2,
        )
        get_urls = [
            urlparse(line.removeprefix("api=GET "))
            for line in api_events
            if line.startswith("api=GET ")
        ]
        self.assertEqual(
            [parse_qs(url.query)["page"] for url in get_urls], [["0"], ["1"], ["2"]]
        )

    def test_no_matches_succeeds(self):
        self.set_mocks([[{"username": "unrelated"}]])
        result = self.run_script("one")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ssh=exe.dev rm one", self.events())
        self.assertFalse(any(event.startswith("api=DELETE") for event in self.events()))

    def test_interactive_selection_and_cancel(self):
        self.set_mocks([[]])
        self.env["SELECTED"] = "one"
        self.mock(
            "fzf", 'import os,sys; sys.stdin.read(); print(os.environ["SELECTED"])'
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ssh=exe.dev rm one", self.events())

        self.trace.unlink()
        self.env["SELECT_STATUS"] = "130"
        self.mock(
            "fzf",
            'import os,sys; sys.stdin.read(); sys.exit(int(os.environ["SELECT_STATUS"]))',
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            any(event.startswith("ssh=exe.dev rm") for event in self.events())
        )

    def test_malformed_inventory_and_inventory_transport_failure_stop(self):
        for failure in ("inventory-json", "inventory-transport"):
            with self.subTest(failure=failure):
                self.trace.unlink(missing_ok=True)
                self.set_mocks([], failure)
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    any(event.startswith("ssh=exe.dev rm") for event in self.events())
                )

    def test_cleanup_failure_stops_before_any_delete_or_later_vm(self):
        for failure, pages in (
            ("ssh", [[]]),
            ("get-transport", [[]]),
            ("invalid-json", [[]]),
            ("invalid-schema", [[]]),
        ):
            with self.subTest(failure=failure):
                self.trace.unlink(missing_ok=True)
                self.set_mocks(pages, failure)
                result = self.run_script("one", "two")
                self.assertNotEqual(result.returncode, 0)
                events = self.events()
                self.assertFalse(
                    any(event.startswith("ssh=exe.dev rm") for event in events)
                )
                self.assertFalse(
                    any(event.startswith("ssh=vm+two@") for event in events)
                )

    def test_all_matched_ids_validated_before_any_delete_even_on_later_page(self):
        for bad_id in (
            "",
            None,
            42,
            "unsafe/id",
            "a" * 26 + "\n",
            "a" * 26 + "\n" + "b" * 26,
        ):
            with self.subTest(bad_id=repr(bad_id)):
                self.trace.unlink(missing_ok=True)
                good = {"username": "node-good", "id": "c" * 26}
                bad = {"username": "node-bad", "id": bad_id}
                self.set_mocks([[good], [bad]])
                result = self.run_script("one", "two")
                self.assertNotEqual(result.returncode, 0)
                events = self.events()
                self.assertFalse(
                    any(event.startswith("api=DELETE") for event in events)
                )
                self.assertFalse(
                    any(event.startswith("ssh=exe.dev rm") for event in events)
                )
                self.assertFalse(
                    any(event.startswith("ssh=vm+two@") for event in events)
                )

    def test_get_and_delete_http_and_transport_failures_prevent_vm_deletion(self):
        for status in ("302", "503"):
            with self.subTest(method="GET", status=status):
                self.trace.unlink(missing_ok=True)
                self.set_mocks([[]])
                self.env["FAIL_STATUS"] = status
                result = self.run_script("one")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    any(event.startswith("ssh=exe.dev rm") for event in self.events())
                )

        for status in ("204", "302", "503"):
            with self.subTest(method="DELETE", status=status):
                self.trace.unlink(missing_ok=True)
                self.set_mocks([[{"username": "node-user", "id": "a" * 26}]])
                self.env["DELETE_STATUS"] = status
                result = self.run_script("one")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    any(event.startswith("ssh=exe.dev rm") for event in self.events())
                )

        for failure in ("get-transport", "delete-transport"):
            with self.subTest(failure=failure):
                self.trace.unlink(missing_ok=True)
                pages = [[{"username": "node-user", "id": "a" * 26}]]
                self.set_mocks(pages, failure)
                result = self.run_script("one")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    any(event.startswith("ssh=exe.dev rm") for event in self.events())
                )

    def test_rejects_invalid_vm_names_before_ssh(self):
        self.set_mocks([])
        result = self.run_script("valid", "bad;rm")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.events(), [])


if __name__ == "__main__":
    unittest.main()
