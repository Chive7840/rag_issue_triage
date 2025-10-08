#!/usr/bin/env python3
"""Utilities for resetting sandbox Docker services.

This script helps remove containers, images, and persistent volumes that can
leave the sandbox stack in a broken state (e.g., Postgres schema changes).
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

from mpmath.calculus.calculus import defun

SERVICE_CHOICES = [
    "postgres",
    "redis",
    "bootstrap",
    "api",
    "worker",
    "web",
]


class CommandError(RuntimeError):
    """Raised when an underlying shell command fails."""


def run_command(
        command: Sequence[str],
        *,
        capture_output: bool = False,
        check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command while echoing it for visibility."""
    printable = " ".join(shlex.quote(arg) for arg in command)
    print(f"$ {printable}")
    result = subprocess.run(
        list(command),
        text=True,
        capture_output=capture_output,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise CommandError(f"Command failed ({result.returncode}): {printable}\n{stderr}")
    return result


def compose_command(
        compose_file: Path,
        *args: str,
        capture_output: bool = False,
        check: bool = True,
        project_name: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    command: List[str] = ["docker", "compose", "-f", str(compose_file)]
    if project_name:
        command.extend(["-p", project_name])
    command.extend(args)
    return run_command(command, capture_output=capture_output, check=check)


def detect_project_name(compose_file: Path, explicit_name: Optional[str]) -> Optional[str]:
    if explicit_name:
        return explicit_name
    try:
        result = compose_command(
            compose_file, "config", "--format", "json", capture_output=True
        )
    except CommandError:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data.get("name")


def list_matching_volumes(suffix: str, project_name: Optional[str]) -> Set[str]:
    result = run_command(
        ["docker", "volume", "ls", "--format", "{{.Name}}", "--filter", f"name={suffix}"],
        capture_output=True,
        check=False,
    )
    volume_names = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    if project_name:
        target = f"{project_name}_{suffix}" if not project_name.endswith(suffix) else project_name
        return {name for name in volume_names if name == target}
    return {name for name in volume_names if name.endswith(f"_{suffix}") or name == suffix}


def remove_volume(volume_name: str) -> None:
    run_command(["docker", "volume", "rm", volume_name], check=False)


def prune_postgres_volume(compose_file: Path, project_name: Optional[str]) -> None:
    matching = list_matching_volumes("pgdata", project_name)
    if not matching:
        print("No pgdata volumes found to prune.")
        return
    for volume_name in matching:
        print(f"Removing volume {volume_name}...")
        remove_volume(volume_name)


def reset_service(
        compose_file: Path,
        service: str,
        *,
        project_name: Optional[str],
        prune_images: bool,
        keep_volume: bool,
) -> None:
    compose_command(compose_file, "stop", service, check=False, project_name=project_name)
    compose_command(
        compose_file,
        "rm",
        "-f",
        service,
        check=False,
        project_name=project_name,
    )

    if prune_images:
        result = compose_command(
            compose_file,
            "images",
            "-q",
            service,
            capture_output=True,
            check=False,
            project_name=project_name,
        )
        image_ids = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        for image_id in image_ids:
            run_command(["docker", "image", "rm", image_id], check=False)

    if service == "postgres" and not keep_volume:
        prune_postgres_volume(compose_file, project_name)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    default_compose = script_dir.parent / "docker-compose.sandbox.yml"

    parser = argparse.ArgumentParser(
        description="Reset sandbox Docker services by removing containers, images, and volumes.",

    )
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=default_compose,
        help="Path to the sandbox docker-compose file (default: %(default)s)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--services",
        nargs="+",
        choices=SERVICE_CHOICES,
        help="One or more services to reset",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Reset all sandbox services",
    )
    parser.add_argument(
        "--project-name",
        help="Override the Docker Compose project name if you use a custom one",
    )
    parser.add_argument(
        "--keep-volume",
        action="store_true",
        help="Do not remove the Postgres pgdata volume",
    )
    parser.add_argument(
        "--prune-images",
        action="store_true",
        help="Remove Docker images for the targeted services as part of the reset",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    compose_file = args.compose_file.resolve()
    if not compose_file.exists():
        print(f"Compose file not found: {compose_file}", file=sys.stderr)
        return 1

    services: Iterable[str]
    if args.all:
        services = SERVICE_CHOICES
    else:
        services = args.services

    project_name = detect_project_name(compose_file, args.project_name)
    if project_name:
        print(f"Using Compose project name: {project_name}")
    else:
        print("Unable to detect Compose project name automatically; Docker will infer it from context.")

    for service in services:
        print(f"\nResetting service: {service}")
        try:
            reset_service(
                compose_file,
                service,
                project_name=project_name,
                prune_images=args.prune_images,
                keep_volume=args.keep_volume,
            )
        except CommandError as exc:
            print(f"Error resetting {service}: {exc}", file=sys.stderr)
            return 1

    print("\nReset complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
