"""Public bootstrap checks for the shared Node runtime policy."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bootstrap_root(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(ROOT / "scripts/bootstrap.sh", scripts / "bootstrap.sh")
    shutil.copyfile(ROOT / ".nvmrc", tmp_path / ".nvmrc")
    (tmp_path / "bin").mkdir()
    return tmp_path


@pytest.mark.parametrize("version", ["22.22.0", "24.13.1", "26.9.9", "27.0.0"])
def test_ac2_bootstrap_rejects_before_install(
    bootstrap_root: Path, version: str
) -> None:
    scripts = bootstrap_root / "scripts"
    binaries = bootstrap_root / "bin"
    marker = bootstrap_root / "npm-called"
    (binaries / "node").write_text(f"#!/bin/sh\necho v{version}\n")
    (binaries / "npm").write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    for binary in binaries.iterdir():
        binary.chmod(0o755)
    done = subprocess.run(
        ["bash", str(scripts / "bootstrap.sh")],
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "Node 26 >= 26.10.0" in done.stdout
    assert "nvm install" in done.stdout
    assert "nvm use" in done.stdout
    assert not marker.exists()
    assert not (bootstrap_root / ".venv").exists()


def test_ac1_ac4_shared_runtime_and_pins() -> None:
    import json

    package = json.loads((ROOT / "package.json").read_text())
    lock = json.loads((ROOT / "package-lock.json").read_text())
    minimum = (ROOT / ".nvmrc").read_text().strip()
    major = int(minimum.split(".")[0])
    assert package["engines"]["node"] == f">={minimum} <{major + 1}"
    assert lock["packages"][""]["engines"] == package["engines"]
    assert package["devDependencies"] == {
        "promptfoo": "0.123.1",
        "smee-client": "5.0.0",
    }


@pytest.mark.parametrize("version", ["26.10.0", "26.10.1", "26.11.0"])
def test_ac2_bootstrap_accepts_supported_preflight(
    bootstrap_root: Path, version: str
) -> None:
    scripts = bootstrap_root / "scripts"
    binaries = bootstrap_root / "bin"
    (binaries / "node").write_text(f"#!/bin/sh\necho v{version}\n")
    (binaries / "npm").write_text("#!/bin/sh\necho 11.19.1\n")
    for binary in binaries.iterdir():
        binary.chmod(0o755)
    venv = bootstrap_root / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("")
    (venv / "pip").write_text("#!/bin/sh\necho deliberate-install-stop\nexit 1\n")
    (venv / "pip").chmod(0o755)
    (bootstrap_root / "requirements").mkdir()
    (bootstrap_root / "requirements" / "constraints.txt").write_text("")
    done = subprocess.run(
        ["bash", str(scripts / "bootstrap.sh")],
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert f"node v{version}, npm 11.19.1" in done.stdout
    assert "deliberate-install-stop" in done.stdout


@pytest.mark.parametrize("failed_cli", [None, "promptfoo", "smee"])
def test_ac1_bootstrap_checks_local_clis_and_cleans_configuration(
    bootstrap_root: Path, failed_cli: str | None
) -> None:
    scripts = bootstrap_root / "scripts"
    binaries = bootstrap_root / "bin"
    (binaries / "node").write_text(
        '#!/bin/sh\ncase "$*" in *--version*) echo v26.10.0;; '
        "*promptfoo*) echo 0.123.1;; *smee-client*) echo 5.0.0;; esac\n"
    )
    (binaries / "npm").write_text("#!/bin/sh\necho 11.19.1\n")
    venv = bootstrap_root / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("")
    (venv / "python").write_text(
        '#!/bin/sh\ncase "$*" in *a2a-sdk*) echo 1.1.5;; '
        "*typesafe-sdk*) echo 0.7.1;; *anthropic*) echo 1.8.0;; "
        "*pydantic*) echo 2.13.5;; *psycopg*) echo 3.3.6;; "
        "*jsonschema*) echo 4.25.1;; *uvicorn*) echo 0.54.0;; "
        "*) echo 3.14.2;; esac\n"
    )
    commands = bootstrap_root / "node_modules" / ".bin"
    commands.mkdir(parents=True)
    saved_config = bootstrap_root / "saved-config"
    saved_config.mkdir()
    saved_contents = saved_config / "saved-database"
    saved_contents.write_text("keep saved evals")
    for cli in ("promptfoo", "smee"):
        (commands / cli).write_text(
            f'#!/bin/sh\necho "{cli} $*" >> "{bootstrap_root / "commands"}"\n'
            + (
                f'printf "%s" "$PROMPTFOO_CONFIG_DIR" > "{bootstrap_root / "config-dir"}"\n'
                'test -d "$PROMPTFOO_CONFIG_DIR" || exit 8\n'
                'touch "$PROMPTFOO_CONFIG_DIR/startup-marker"\n'
                if cli == "promptfoo"
                else ""
            )
            + "echo startup-tested\n"
            + ("exit 1\n" if cli == failed_cli else "exit 0\n")
        )
    for directory in (binaries, venv, commands):
        for binary in directory.iterdir():
            binary.chmod(0o755)
    done = subprocess.run(
        ["bash", str(scripts / "bootstrap.sh"), "--print-versions"],
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "PROMPTFOO_CONFIG_DIR": str(saved_config),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == (2 if failed_cli else 0)
    if failed_cli:
        assert f"{failed_cli} CLI startup" in done.stdout
        assert "startup-tested" in done.stdout
    assert (bootstrap_root / "commands").read_text().splitlines() == [
        "promptfoo --version",
        "smee --help",
    ]
    config_dir = Path((bootstrap_root / "config-dir").read_text())
    assert config_dir != saved_config
    assert not config_dir.exists()
    assert saved_contents.read_text() == "keep saved evals"
    assert list(saved_config.iterdir()) == [saved_contents]
