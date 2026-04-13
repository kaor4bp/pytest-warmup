from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PROFILES_PATH = ROOT / "compat" / "profiles.toml"
VENVS_DIR = ROOT / ".compat" / "venvs"


def _load_profiles() -> dict[str, dict[str, str]]:
    raw = tomllib.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    profiles = raw.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("compat/profiles.toml must contain a [profiles] table")
    normalized: dict[str, dict[str, str]] = {}
    for name, payload in profiles.items():
        if not isinstance(payload, dict):
            raise SystemExit(f"profile {name!r} must be a table")
        python = payload.get("python")
        pytest_spec = payload.get("pytest")
        description = payload.get("description", "")
        if not isinstance(python, str) or not python:
            raise SystemExit(f"profile {name!r} must define a non-empty 'python'")
        if not isinstance(pytest_spec, str) or not pytest_spec:
            raise SystemExit(f"profile {name!r} must define a non-empty 'pytest'")
        if not isinstance(description, str):
            raise SystemExit(f"profile {name!r} field 'description' must be a string")
        normalized[name] = {
            "python": python,
            "pytest": pytest_spec,
            "description": description,
        }
    return normalized


def _sanitize_env_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    printable = " ".join(cmd)
    print(f"+ {printable}")
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def _resolve_python(executable: str) -> str:
    resolved = shutil.which(executable)
    if resolved is None:
        raise SystemExit(f"python executable {executable!r} was not found")
    return resolved


def _create_env(venv_dir: Path, python_executable: str, recreate: bool) -> Path:
    if recreate and venv_dir.exists():
        shutil.rmtree(venv_dir)
    if not venv_dir.exists():
        _run([python_executable, "-m", "venv", str(venv_dir)])
    return _venv_python(venv_dir)


def _install_combo(venv_python: Path, pytest_spec: str) -> None:
    _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(venv_python), "-m", "pip", "install", "-e", str(ROOT)])
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
            f"pytest{pytest_spec}",
        ]
    )


def _show_effective_versions(venv_python: Path) -> None:
    _run(
        [
            str(venv_python),
            "-c",
            "import platform, pytest; "
            "print(f'Python {platform.python_version()} | pytest {pytest.__version__}')",
        ]
    )


def _run_profile(
    *,
    name: str,
    python_spec: str,
    pytest_spec: str,
    recreate: bool,
    pytest_args: list[str],
) -> None:
    resolved_python = _resolve_python(python_spec)
    env_name = _sanitize_env_name(name)
    venv_dir = VENVS_DIR / env_name
    print(f"==> profile={name} python={python_spec} pytest{pytest_spec}")
    venv_python = _create_env(venv_dir, resolved_python, recreate)
    _install_combo(venv_python, pytest_spec)
    _show_effective_versions(venv_python)
    _run([str(venv_python), "-m", "pytest", *(pytest_args or ["-q"])])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run pytest-warmup compatibility profiles against explicit Python/pytest combos."
    )
    parser.add_argument(
        "profile",
        nargs="?",
        help="Profile name from compat/profiles.toml. Omit when using --python and --pytest-spec.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available compatibility profiles and exit.",
    )
    parser.add_argument(
        "--python",
        dest="python_spec",
        help="Python executable to use for an ad-hoc run or to override a profile interpreter.",
    )
    parser.add_argument(
        "--pytest-spec",
        help="Pytest version specifier for an ad-hoc run, for example '==8.4.0' or '>=9,<10'.",
    )
    parser.add_argument(
        "--name",
        help="Stable environment name for an ad-hoc run. Defaults to a name derived from python/pytest.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the compatibility virtual environment before running.",
    )
    args, pytest_args = parser.parse_known_args()

    profiles = _load_profiles()
    if args.list:
        for name, payload in profiles.items():
            description = payload["description"]
            print(f"{name}: python={payload['python']} pytest{payload['pytest']}")
            if description:
                print(f"  {description}")
        return 0

    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]

    if args.profile is not None:
        payload = profiles.get(args.profile)
        if payload is None:
            raise SystemExit(f"unknown profile {args.profile!r}")
        python_spec = args.python_spec or payload["python"]
        pytest_spec = args.pytest_spec or payload["pytest"]
        _run_profile(
            name=args.profile,
            python_spec=python_spec,
            pytest_spec=pytest_spec,
            recreate=args.recreate,
            pytest_args=pytest_args,
        )
        return 0

    if not args.python_spec or not args.pytest_spec:
        raise SystemExit("either choose a profile or provide both --python and --pytest-spec")

    name = args.name or _sanitize_env_name(
        f"{Path(args.python_spec).name}-pytest-{args.pytest_spec}"
    )
    _run_profile(
        name=name,
        python_spec=args.python_spec,
        pytest_spec=args.pytest_spec,
        recreate=args.recreate,
        pytest_args=pytest_args,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
