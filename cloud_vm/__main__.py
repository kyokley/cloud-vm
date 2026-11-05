"""Command-line entry point for the fleet TUI and safe one-shot operations."""

import argparse
import json
import pathlib
import sys

from .backend import BackendError, FleetBackend


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and manage exe.dev VMs")
    parser.add_argument(
        "--project-root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
        help="project containing scripts/vm.sh (default: current directory)",
    )
    commands = parser.add_subparsers(dest="command")
    listing = commands.add_parser("list", help="list VMs")
    listing.add_argument(
        "--json", action="store_true", help="print machine-readable JSON"
    )
    for command in ("inspect", "create", "bootstrap", "apply", "remove"):
        sub = commands.add_parser(command)
        if command == "create":
            sub.add_argument("name", nargs="?")
        else:
            sub.add_argument("name")
        if command in {"create", "bootstrap", "apply", "remove"}:
            sub.add_argument(
                "--yes",
                action="store_true",
                required=True,
                help="authorize this mutating operation",
            )
        if command == "bootstrap":
            sub.add_argument(
                "--allow-sudo",
                action="store_true",
                required=True,
                help="authorize required noninteractive sudo operations",
            )
    return parser


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    backend = FleetBackend(args.project_root)
    try:
        if args.command is None:
            from .tui import run

            run(backend)
        elif args.command == "list":
            vms = backend.list_vms()
            if args.json:
                print(json.dumps([vm.__dict__ for vm in vms], sort_keys=True))
            else:
                for vm in vms:
                    print(f"{vm.name}\t{vm.status}")
        elif args.command == "inspect":
            sys.stdout.write(backend.inspect(args.name))
        elif args.command == "create":
            sys.stdout.write(backend.create(args.name, authorized=args.yes))
        elif args.command == "bootstrap":
            sys.stdout.write(
                backend.bootstrap(args.name, authorized=args.yes and args.allow_sudo)
            )
        elif args.command == "apply":
            sys.stdout.write(backend.apply(args.name, authorized=args.yes))
        elif args.command == "remove":
            sys.stdout.write(backend.remove(args.name, authorized=args.yes))
        return 0
    except BackendError as exc:
        print(f"cloud-vm: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
