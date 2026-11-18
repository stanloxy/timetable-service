"""Порядок команд контейнерного entrypoint."""

import os
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh"


@pytest.mark.parametrize(
    ("seed_on_start", "expected"),
    [
        (
            "0",
            [
                "alembic upgrade head",
                "launch-app --example",
            ],
        ),
        (
            "1",
            [
                "alembic upgrade head",
                "python -m app.maintenance.seed",
                "launch-app --example",
            ],
        ),
    ],
)
def test_entrypoint_command_order(
    tmp_path: Path,
    seed_on_start: str,
    expected: list[str],
) -> None:
    commands = tmp_path / "bin"
    commands.mkdir()
    trace = tmp_path / "commands.log"

    # Команды ничего не запускают, только записывают свои вызовы.
    for name in ("alembic", "python", "launch-app"):
        executable = commands / name
        executable.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "{name} $*" >> "$TRACE_FILE"\n',
            encoding="utf-8",
        )
        executable.chmod(0o700)

    environment = os.environ.copy()
    environment["PATH"] = str(commands) + os.pathsep + environment.get("PATH", "")
    environment["TRACE_FILE"] = str(trace)
    environment["SEED_ON_START"] = seed_on_start

    subprocess.run(
        ["/bin/sh", str(ENTRYPOINT), "launch-app", "--example"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert trace.read_text(encoding="utf-8").splitlines() == expected
