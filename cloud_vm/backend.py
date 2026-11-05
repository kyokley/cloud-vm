"""Synchronous, consent-gated exe.dev operations."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
from dataclasses import dataclass

_NAME = re.compile(r"(?:[a-z]|[a-z][a-z0-9-]{0,38}[a-z0-9])\Z")
_SSH_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+exe\.xyz\Z")


class BackendError(Exception):
    """Actionable operation failure shown by the CLI and TUI."""


@dataclass(frozen=True)
class VM:
    name: str
    status: str
    ssh_host: str = ""
    image: str = ""
    created_at: str = ""


class FleetBackend:
    def __init__(self, project_root: pathlib.Path):
        self.project_root = pathlib.Path(project_root).resolve()
        self.vm_script = self.project_root / "scripts" / "vm.sh"
        self.remove_script = self.project_root / "scripts" / "rm-vm.sh"
        self._ssh_destinations: dict[str, str] = {}

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise BackendError(
                f"Invalid VM name {name!r}; use 1-40 lowercase letters, digits, and hyphens"
            )
        return name

    @staticmethod
    def _error(result: subprocess.CompletedProcess[str], action: str) -> BackendError:
        detail = (
            "\n".join(
                stream.strip()
                for stream in (result.stdout, result.stderr)
                if stream and stream.strip()
            )
            or "no diagnostic output"
        )
        return BackendError(f"{action} failed (exit {result.returncode}): {detail}")

    def _run(self, argv: list[str], action: str, *, mutation: bool = False) -> str:
        try:
            result = subprocess.run(
                argv,
                cwd=self.project_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=1800 if mutation else 120,
            )
        except subprocess.TimeoutExpired as exc:
            message = f"{action} timed out"
            if mutation:
                message += "; remote outcome may be unknown or partially applied; inspect the VM before retrying"
            raise BackendError(message) from exc
        except OSError as exc:
            raise BackendError(f"Cannot run {action}: {exc}") from exc
        if result.returncode:
            error = self._error(result, action)
            if mutation:
                raise BackendError(
                    f"{error}; remote outcome may be unknown or partially applied; "
                    "inspect the VM before retrying"
                )
            raise error
        return result.stdout

    @staticmethod
    def _authorized(authorized: bool, action: str) -> None:
        if authorized is not True:
            raise BackendError(f"{action} requires explicit authorization")

    def list_vms(self) -> list[VM]:
        output = self._run(["ssh", "exe.dev", "ls", "--json"], "VM inventory")
        try:
            payload = json.loads(output)
            if not isinstance(payload, dict):
                raise TypeError("response is not an object")
            if "error" in payload:
                detail = payload["error"]
                if not isinstance(detail, str):
                    raise ValueError("exe.dev error field is not a string")
                raise BackendError(f"exe.dev inventory error: {detail.strip()}")
            records = payload["vms"]
            if not isinstance(records, list):
                raise TypeError("vms is not an array")
            result = []
            destinations = {}
            seen = set()
            for record in records:
                if not isinstance(record, dict) or not isinstance(
                    record.get("vm_name"), str
                ):
                    raise TypeError("VM entry has no string vm_name")
                name = self._validate_name(record["vm_name"])
                if name in seen:
                    raise ValueError(f"duplicate VM name: {name}")
                seen.add(name)
                status = record.get("status")
                host = record.get("ssh_host")
                destination = record.get("ssh_dest")
                if not isinstance(status, str) or not isinstance(host, str):
                    raise TypeError("VM entry status and ssh_host must be strings")
                if not _SSH_HOST.fullmatch(host):
                    raise ValueError(f"VM entry has unsafe ssh_host: {host!r}")
                if not isinstance(destination, str):
                    raise TypeError("VM entry ssh_dest must be a string")
                fallback = f"vm+{name}@vm.exe.xyz"
                if destination not in (f"{name}.exe.xyz", fallback):
                    raise ValueError(f"VM entry has unsafe ssh_dest: {destination!r}")
                for field in (
                    "https_url",
                    "region",
                    "region_display",
                    "image",
                    "created_at",
                ):
                    if field in record and not isinstance(record[field], str):
                        raise ValueError(f"{field} must be a string")
                destinations[name] = destination
                result.append(
                    VM(
                        name=name,
                        status=status,
                        ssh_host=host,
                        image=record.get("image", ""),
                        created_at=record.get("created_at", ""),
                    )
                )
            self._ssh_destinations = destinations
            return result
        except BackendError:
            raise
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise BackendError(f"Invalid exe.dev VM inventory JSON: {exc}") from exc

    def inspect(self, name: str) -> str:
        name = self._validate_name(name)
        return self._run([str(self.vm_script), "inspect", name], f"Inspect {name}")

    def create(self, name: str, *, authorized: bool = False) -> str:
        self._authorized(authorized, "VM creation")
        name = self._validate_name(name)
        output = self._run(
            ["ssh", "exe.dev", "new", f"--name={name}", "--json"],
            f"Create {name}",
            mutation=True,
        )
        try:
            response = json.loads(output)
        except json.JSONDecodeError:
            return output
        if isinstance(response, dict) and "error" in response:
            detail = response["error"]
            if not isinstance(detail, str):
                raise BackendError("exe.dev returned malformed creation error JSON")
            raise BackendError(f"Create {name} failed: {detail.strip()}")
        return output

    def bootstrap(self, name: str, *, authorized: bool = False) -> str:
        self._authorized(authorized, "Bootstrap")
        name = self._validate_name(name)
        return self._run(
            [str(self.vm_script), "bootstrap", name, "--yes", "--allow-sudo"],
            f"Bootstrap {name}",
            mutation=True,
        )

    def apply(self, name: str, *, authorized: bool = False) -> str:
        self._authorized(authorized, "Apply")
        name = self._validate_name(name)
        return self._run(
            [str(self.vm_script), "apply", name, "--yes"],
            f"Apply {name}",
            mutation=True,
        )

    def remove(self, name: str, *, authorized: bool = False) -> str:
        self._authorized(authorized, "VM removal")
        name = self._validate_name(name)
        return self._run(
            [str(self.remove_script), name], f"Remove {name}", mutation=True
        )

    def ssh_args(self, name: str) -> list[str]:
        name = self._validate_name(name)
        destination = self._ssh_destinations.get(name, f"vm+{name}@vm.exe.xyz")
        if destination not in (f"{name}.exe.xyz", f"vm+{name}@vm.exe.xyz"):
            raise BackendError(f"Unsafe SSH destination recorded for VM {name}")
        return ["ssh", destination]
