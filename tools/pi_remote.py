#!/usr/bin/env python3
"""Remote connection tool for the SunFounder PiDog robot (stdlib only).

Provides a small, reusable API + CLI to run shell commands on, and fetch/push
files from/to, the robot Raspberry Pi over SSH/SCP.

Connection config resolution order (first match wins):
  1. Environment variables: PIR_HOST, PIR_USER, PIR_PORT, PIR_PASSWORD,
     PIR_KEY, PIR_REMOTE_BASE, PIR_CONNECT_TIMEOUT, PIR_SSH_EXTRA
  2. .env file in the project root (keys: REMOTE_PI_DOG_HOST/USER/PORT/
     PASSWORD/KEY/PATH, plus PIDOG_SSH_PASSWORD as a password fallback)
  3. Built-in defaults (matching .deploy-pipeline.sh)

Auth:
  - Password auth (default, matches deploy pipeline): uses the system
    `sshpass` binary with the password passed via the SSHPASS env var —
    never placed on argv, never printed.
  - Key auth: set PIR_KEY=/path/to/key to use `ssh -i` instead.
  - With neither password nor key, commands run with BatchMode so the tool
    fails fast instead of hanging on an interactive prompt.

CLI:
  python3 tools/pi_remote.py run "<cmd>" [--timeout SECS] [--dry-run]
  python3 tools/pi_remote.py get <remote_path> <local_path> [--dry-run]
  python3 tools/pi_remote.py put <local_path> <remote_path> [--dry-run]

Importable:
  import pi_remote
  rc, out, err = pi_remote.run("uname -a")
  pi_remote.get("/home/pidog/pidog/main.py", "local_main.py")
  pi_remote.put("local_main.py", "/home/pidog/pidog/main.py")
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from shutil import which

__all__ = ["run", "get", "put", "PiRemoteError", "get_config"]

DEFAULTS = {
    "host": "192.168.0.15",
    "user": "pidog",
    "port": "22",
    "remote_base": "/home/pidog/pidog",
    "connect_timeout": "10",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# SSH exit code 255 = connection/auth-level failure (not a remote command exit).
SSH_TRANSPORT_FAILURE = 255


class PiRemoteError(RuntimeError):
    """Raised when a remote operation fails for a clear, user-facing reason."""


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file (ignores comments/blank lines)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def get_config() -> dict[str, str | None]:
    """Resolve effective connection config: env vars > .env > defaults."""
    file_env = _parse_env_file(ENV_FILE)

    def pick(env_key: str, env_file_keys: tuple[str, ...], default: str | None = None) -> str | None:
        if os.environ.get(env_key, ""):
            return os.environ[env_key]
        for fk in env_file_keys:
            if file_env.get(fk):
                return file_env[fk]
        return default

    return {
        "host": pick("PIR_HOST", ("REMOTE_PI_DOG_HOST",), DEFAULTS["host"]),
        "user": pick("PIR_USER", ("REMOTE_PI_DOG_USER",), DEFAULTS["user"]),
        "port": pick("PIR_PORT", ("REMOTE_PI_DOG_PORT",), DEFAULTS["port"]),
        "password": pick("PIR_PASSWORD", ("REMOTE_PI_DOG_PASSWORD", "PIDOG_SSH_PASSWORD")),
        "key": pick("PIR_KEY", ("REMOTE_PI_DOG_KEY",)),
        "remote_base": pick("PIR_REMOTE_BASE", ("REMOTE_PI_DOG_PATH", "REMOTE_PATH"), DEFAULTS["remote_base"]),
        "connect_timeout": pick("PIR_CONNECT_TIMEOUT", (), DEFAULTS["connect_timeout"]),
        "ssh_extra": os.environ.get("PIR_SSH_EXTRA", "").strip(),
    }


def _quote(args: list[str]) -> str:
    """Render a command list as a shell-readable one-liner."""
    return " ".join(shlex.quote(a) for a in args)


def _ssh_base_opts(cfg: dict[str, str | None]) -> list[str]:
    opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={cfg['connect_timeout']}",
        "-o", "IdentitiesOnly=yes",
    ]
    if cfg.get("ssh_extra"):
        opts.extend(shlex.split(cfg["ssh_extra"]))
    return opts


def _build_ssh_cmd(cfg: dict[str, str | None], cmd: str) -> list[str]:
    """Build the full ssh command list for a remote shell command."""
    args = ["-p", str(cfg["port"]), *_ssh_base_opts(cfg)]
    if cfg.get("password"):
        args += [
            "-o", "PreferredAuthentications=password",
            "-o", "PubkeyAuthentication=no",
            "-o", "NumberOfPasswordPrompts=1",
        ]
    args.append(f"{cfg['user']}@{cfg['host']}")
    args.append(cmd)
    if cfg.get("password"):
        return ["sshpass", "-e", "ssh", *args]
    if cfg.get("key"):
        return ["ssh", "-i", cfg["key"], *args]
    return ["ssh", "-o", "BatchMode=yes", *args]


def _build_scp_cmd(
    cfg: dict[str, str | None],
    src: str,
    dst: str,
) -> list[str]:
    """Build the full scp command list for a file transfer."""
    args = ["-P", str(cfg["port"]), *_ssh_base_opts(cfg), src, dst]
    if cfg.get("password"):
        return ["sshpass", "-e", "scp", *args]
    if cfg.get("key"):
        return ["scp", "-i", cfg["key"], *args]
    return ["scp", "-o", "BatchMode=yes", *args]


def _execute(cmd_list: list[str], timeout: float | None) -> tuple[int, str, str]:
    """Run a local subprocess; returns (rc, stdout, stderr)."""
    if which(cmd_list[0]) is None:
        raise PiRemoteError(
            f"Required program '{cmd_list[0]}' not found on this workstation. "
            "Install it or adjust PIR_* settings."
        )
    env = dict(os.environ)
    password = get_config().get("password")
    if password:
        env["SSHPASS"] = password
    try:
        proc = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise PiRemoteError(
            f"Command timed out after {timeout}s: {_quote(cmd_list)}"
        ) from exc
    return proc.returncode, proc.stdout, proc.stderr


def run(cmd: str, timeout: float | None = None) -> tuple[int, str, str]:
    """Run a shell command on the robot. Returns (rc, stdout, stderr).

    Raises PiRemoteError on transport-level failures (missing binary,
    unreachable host, bad auth).
    """
    rc, out, err = _execute(_build_ssh_cmd(get_config(), cmd), timeout)
    if rc == SSH_TRANSPORT_FAILURE:
        cfg = get_config()
        raise PiRemoteError(
            f"SSH to {cfg['user']}@{cfg['host']}:{cfg['port']} failed "
            f"(unreachable host or bad auth): {err.strip() or 'no output'}"
        )
    return rc, out, err


def _transfer(direction: str, src: str, dst: str) -> tuple[int, str, str]:
    cfg = get_config()
    if direction == "get":
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
    else:
        if not Path(src).is_file():
            raise PiRemoteError(f"Local file not found: {src}")
    cmd_list = _build_scp_cmd(cfg, src, dst)
    rc, out, err = _execute(cmd_list, timeout=300)
    if rc != 0:
        raise PiRemoteError(
            f"scp {direction} failed (rc={rc}): {err.strip() or out.strip() or 'no output'}"
        )
    return rc, out, err


def get(remote_path: str, local_path: str) -> tuple[int, str, str]:
    """Fetch a file from the robot over scp. Returns (rc, stdout, stderr)."""
    cfg = get_config()
    return _transfer("get", f"{cfg['user']}@{cfg['host']}:{remote_path}", local_path)


def put(local_path: str, remote_path: str) -> tuple[int, str, str]:
    """Push a file to the robot over scp. Returns (rc, stdout, stderr)."""
    cfg = get_config()
    return _transfer("put", local_path, f"{cfg['user']}@{cfg['host']}:{remote_path}")


def _dry_run_note() -> None:
    if get_config().get("password"):
        print("[dry-run] (password supplied via SSHPASS env var, not shown)")


def _preview_run(cmd: str) -> None:
    print(f"[dry-run] would execute: {_quote(_build_ssh_cmd(get_config(), cmd))}")
    _dry_run_note()


def _preview_transfer(direction: str, src: str, dst: str) -> None:
    print(f"[dry-run] would execute: {_quote(_build_scp_cmd(get_config(), src, dst))}")
    _dry_run_note()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pi_remote",
        description="Run commands on and transfer files to/from the PiDog robot.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help='run a shell command, e.g. run "uname -a"')
    p_run.add_argument("cmd")
    p_run.add_argument("--timeout", type=float, default=None, help="seconds (default: none)")
    p_run.add_argument("--dry-run", action="store_true", help="print command, do not connect")

    p_get = sub.add_parser("get", help="fetch a file from the robot")
    p_get.add_argument("remote_path")
    p_get.add_argument("local_path")
    p_get.add_argument("--dry-run", action="store_true", help="print command, do not connect")

    p_put = sub.add_parser("put", help="push a file to the robot")
    p_put.add_argument("local_path")
    p_put.add_argument("remote_path")
    p_put.add_argument("--dry-run", action="store_true", help="print command, do not connect")

    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            if args.dry_run:
                _preview_run(args.cmd)
                return 0
            rc, out, err = run(args.cmd, timeout=args.timeout)
            if out:
                sys.stdout.write(out)
            if err:
                sys.stderr.write(err)
            return rc
        if args.command == "get":
            if args.dry_run:
                cfg = get_config()
                _preview_transfer("get", f"{cfg['user']}@{cfg['host']}:{args.remote_path}", args.local_path)
                return 0
            rc, out, err = get(args.remote_path, args.local_path)
            if err:
                sys.stderr.write(err)
            print(f"Fetched {args.remote_path} -> {args.local_path}")
            return rc
        if args.command == "put":
            if args.dry_run:
                cfg = get_config()
                _preview_transfer("put", args.local_path, f"{cfg['user']}@{cfg['host']}:{args.remote_path}")
                return 0
            rc, out, err = put(args.local_path, args.remote_path)
            if err:
                sys.stderr.write(err)
            print(f"Pushed {args.local_path} -> {args.remote_path}")
            return rc
    except PiRemoteError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return SSH_TRANSPORT_FAILURE
    return 1


if __name__ == "__main__":
    sys.exit(main())
