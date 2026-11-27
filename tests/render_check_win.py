#!/usr/bin/env python3
"""Run tests/render_check.py remotely on a Windows host over SSH.

Ships the working tree's (or --rev's) mods/, layouts/, tests/render_check.py, and a compact
slice of a local ledger to the Windows host, executes tests/render_check.py in an isolated
temp directory (launching herdr-app.exe in interactive Session 1 via schtasks /IT), optionally
verifies real Windows window controls (window.maximize grow + restore), and pulls shots/*.png,
report.txt, and app.log back to --out.

Usage:
    python3 tests/render_check_win.py --host user@win-host
    DUDU_WIN_HOST=user@win-host python3 tests/render_check_win.py --out evidence/render-check-win

Exit codes mirror tests/render_check.py:
    0  every page rendered without an error
    1  mod errors, or a page/window-control check failed
    2  not judged (missing --host, SSH failure, or remote render_check exit 2)
"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

REPO = Path(__file__).resolve().parent.parent
SAFE_DIR = re.compile(r"^[\w.-]+$")
SKIP_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
    ".mp4", ".mov", ".avi", ".mkv", ".wav", ".mp3",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".exe", ".dll", ".dylib",
}
SKIP_PROJECT_DIRS = {"__pycache__", ".git", "attachments", "helpers"}
MAX_PROJECT_FILE_BYTES = 512 * 1024  # 512 KB
MAX_MEMORY_FILES = 20


def ledger_source():
    if os.environ.get("PM_HOME"):
        return Path(os.environ["PM_HOME"]).expanduser()
    canonical = Path.home() / ".dudu"
    default = Path.home() / ".claude/pm"
    if default.is_dir():
        try:
            if canonical.exists() and default.samefile(canonical):
                return canonical
        except OSError:
            pass
        return default
    return canonical


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _count_lines(path):
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _discover_pms(src):
    """Return list of (pm_name, project_slug, pm_json_path, conv_path) from a ledger."""
    pms_dir = src / "pms"
    projects_dir = src / "projects"
    found = []
    seen = set()
    if pms_dir.is_dir():
        for p in sorted(pms_dir.glob("*.json")):
            data = _read_json(p) or {}
            name = data.get("name") or p.stem
            project = data.get("project") or re.sub(r"^pm-", "", name)
            conv = projects_dir / project / "conversation.jsonl"
            found.append((name, project, p, conv))
            seen.add(name)
    if projects_dir.is_dir():
        for proj_dir in sorted(projects_dir.iterdir()):
            if not proj_dir.is_dir() or proj_dir.is_symlink():
                continue
            name = f"pm-{proj_dir.name}"
            if name in seen:
                continue
            conv = proj_dir / "conversation.jsonl"
            if conv.is_file():
                found.append((name, proj_dir.name, None, conv))
    return found


def slice_ledger(src, dst, pm_name=None, thread_id=None, max_conv_lines=100, max_tasks=20):
    """Copy a compact slice of a ledger into dst:
      - config.json (if present)
      - the chosen PM's pms/<pm>.json
      - its projects/<project>/ (trimming conversation.jsonl to last max_conv_lines, skipping large/binary files)
      - its latest max_tasks tasks in tasks/ (always including thread_id if specified)
    Returns (selected_pm_name, selected_project, stats_dict).
    """
    src = Path(src)
    dst = Path(dst)
    if not (src / "tasks").is_dir():
        raise ValueError(f"no ledger tasks/ directory at {src}")

    # Load task metadata to rank PMs and pick latest tasks.
    all_tasks = []
    for p in (src / "tasks").glob("*.json"):
        if p.is_symlink():
            continue
        data = _read_json(p)
        if isinstance(data, dict):
            all_tasks.append((p, data))

    candidates = _discover_pms(src)
    if pm_name:
        candidates = [c for c in candidates if c[0] == pm_name]
        if not candidates:
            raise ValueError(f"no PM named {pm_name} in ledger {src}")

    def task_matches(task_data, pm_name, project_slug):
        t_pm = task_data.get("pm")
        if t_pm:
            return t_pm == pm_name
        return task_data.get("project") == project_slug

    def rank_key(item):
        name, project, _pm_path, conv = item
        lines = _count_lines(conv) if conv.is_file() else 0
        task_count = sum(1 for _, t in all_tasks if task_matches(t, name, project))
        return (lines > 0, task_count, lines)

    ranked = sorted(candidates, key=rank_key, reverse=True)
    if not ranked:
        raise ValueError(f"no PMs found in ledger {src}")
    selected_pm, selected_project, pm_path, _conv = ranked[0]

    dst.mkdir(parents=True, exist_ok=True)
    files_copied = 0
    bytes_copied = 0

    def record(path):
        nonlocal files_copied, bytes_copied
        files_copied += 1
        try:
            bytes_copied += path.stat().st_size
        except OSError:
            pass

    # 1. config.json
    cfg = src / "config.json"
    if cfg.is_file() and not cfg.is_symlink():
        out = dst / "config.json"
        shutil.copy2(cfg, out)
        record(out)

    # 2. pms/<pm>.json
    if pm_path and pm_path.is_file() and not pm_path.is_symlink():
        out = dst / "pms" / pm_path.name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pm_path, out)
        record(out)

    # 3. projects/<project>/
    proj_src = src / "projects" / selected_project
    proj_dst = dst / "projects" / selected_project
    if proj_src.is_dir():
        for root, dirs, files in os.walk(proj_src):
            dirs[:] = sorted(
                d for d in dirs if d not in SKIP_PROJECT_DIRS and not (Path(root) / d).is_symlink()
            )
            rel_root = Path(root).relative_to(proj_src)
            names = sorted(files)
            if rel_root == Path("memory") and len(names) > MAX_MEMORY_FILES:
                names = names[-MAX_MEMORY_FILES:]
            for fname in names:
                if fname == ".DS_Store" or fname.endswith(".lock"):
                    continue
                fpath = Path(root) / fname
                if fpath.is_symlink():
                    continue
                if fpath.suffix.lower() in SKIP_BINARY_EXTS:
                    continue
                target = proj_dst / rel_root / fname
                target.parent.mkdir(parents=True, exist_ok=True)
                if rel_root == Path(".") and fname == "conversation.jsonl":
                    lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                    trimmed = lines[-max_conv_lines:] if max_conv_lines and len(lines) > max_conv_lines else lines
                    target.write_text("\n".join(trimmed) + ("\n" if trimmed else ""), encoding="utf-8")
                    record(target)
                else:
                    try:
                        if fpath.stat().st_size > MAX_PROJECT_FILE_BYTES:
                            continue
                    except OSError:
                        continue
                    shutil.copy2(fpath, target)
                    record(target)

    # 4. tasks/ (latest max_tasks for selected_pm, plus thread_id if specified)
    tasks_dst = dst / "tasks"
    tasks_dst.mkdir(parents=True, exist_ok=True)
    own_tasks = [(p, t) for p, t in all_tasks if task_matches(t, selected_pm, selected_project)]
    own_tasks.sort(key=lambda pt: (pt[1].get("updated") or "", pt[0].stat().st_mtime), reverse=True)
    chosen = []
    chosen_ids = set()
    if thread_id:
        for p, t in all_tasks:
            tid = t.get("id") or p.stem
            if tid == thread_id:
                chosen.append((p, t))
                chosen_ids.add(tid)
                break
    for p, t in own_tasks:
        if len(chosen) >= max_tasks:
            break
        tid = t.get("id") or p.stem
        if tid in chosen_ids:
            continue
        chosen.append((p, t))
        chosen_ids.add(tid)
    for p, _t in chosen:
        out = tasks_dst / p.name
        shutil.copy2(p, out)
        record(out)

    return selected_pm, selected_project, {
        "files": files_copied,
        "bytes": bytes_copied,
        "tasks": len(chosen),
    }


def _add_dir_to_tar(tf, src_dir, arc_prefix):
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".git") and not (Path(root) / d).is_symlink())
        for fname in sorted(files):
            if fname == ".DS_Store":
                continue
            fpath = Path(root) / fname
            if fpath.is_symlink():
                continue
            rel = fpath.relative_to(src_dir).as_posix()
            tf.add(fpath, arcname=f"{arc_prefix}/{rel}", recursive=False)


def build_payload(repo, dst_tar, ledger_src, rev=None, pm_name=None, thread_id=None):
    """Create a .tar.gz containing mods/, layouts/, tests/render_check.py, and ledger/."""
    repo = Path(repo)
    with tempfile.TemporaryDirectory(prefix="dudu-rc-win-stage-") as stage_str:
        stage = Path(stage_str)
        selected_pm, selected_project, stats = slice_ledger(
            ledger_src, stage / "ledger", pm_name=pm_name, thread_id=thread_id
        )
        if rev:
            r = subprocess.run(
                ["git", "-C", str(repo), "archive", rev, "mods", "layouts"],
                capture_output=True,
            )
            if r.returncode != 0:
                raise RuntimeError(f"git archive {rev}: {r.stderr.decode('utf-8', 'replace').strip()}")
            src_root = stage / "rev"
            src_root.mkdir()
            with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:*") as rev_tf:
                rev_tf.extractall(src_root)
            mods_dir, layouts_dir = src_root / "mods", src_root / "layouts"
        else:
            mods_dir, layouts_dir = repo / "mods", repo / "layouts"

        with tarfile.open(dst_tar, mode="w:gz") as tf:
            _add_dir_to_tar(tf, mods_dir, "mods")
            _add_dir_to_tar(tf, layouts_dir, "layouts")
            tf.add(repo / "tests/render_check.py", arcname="tests/render_check.py", recursive=False)
            _add_dir_to_tar(tf, stage / "ledger", "ledger")

    return selected_pm, selected_project, stats


def remote_python_cmd(script):
    """Encode a Python snippet into a single SSH command string that runs identically under
    Windows cmd.exe, PowerShell, and POSIX sh (no spaces inside the -c expression)."""
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return [f'python -c "exec(__import__(\'base64\').b64decode(__import__(\'sys\').argv[1]))" {encoded}']


def ssh_cmd(host, remote_argv):
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, *remote_argv]


def build_remote_run_args(remote_dir, args):
    """Build the remote render_check.py CLI flags (relative to the remote base dir)."""
    flags = ["--ledger", "ledger", "--dir", "run"]
    if args.pm:
        flags += ["--pm", args.pm]
    if args.thread:
        flags += ["--thread", args.thread]
    if args.keep:
        flags.append("--keep")
    if not args.no_window_controls:
        flags.append("--verify-window-controls")
    return flags


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default=None,
                        help="Windows SSH target (e.g. user@host); defaults to $DUDU_WIN_HOST")
    parser.add_argument("--rev", help="check this commit's mods/ and layouts/ (default: working tree)")
    parser.add_argument("--ledger", help="local ledger path (default: $PM_HOME, ~/.claude/pm or ~/.dudu)")
    parser.add_argument("--out", default=str(REPO / "evidence/render-check-win"),
                        help="local directory for pulled shots, report.txt, and app.log")
    parser.add_argument("--pm", help="PM name to render (forwarded to render_check.py)")
    parser.add_argument("--thread", help="task id to open (forwarded to render_check.py)")
    parser.add_argument("--keep", action="store_true",
                        help="keep remote temp directory and private Herdr state")
    parser.add_argument("--remote-dir", default="dudu-rc-win",
                        help="subdirectory name under remote %%TEMP%% (default: dudu-rc-win)")
    parser.add_argument("--no-window-controls", action="store_true",
                        help="skip window.maximize verification on Windows")
    return parser.parse_args(argv)


def resolve_host(args, env=None):
    env = os.environ if env is None else env
    host = (args.host or env.get("DUDU_WIN_HOST") or "").strip()
    return host


def _upload_script(remote_dir):
    return (
        "import io, os, pathlib, shutil, sys, tarfile, tempfile\n"
        f"base = pathlib.Path(tempfile.gettempdir()) / {json.dumps(remote_dir)}\n"
        "if base.exists():\n"
        "    shutil.rmtree(base, ignore_errors=True)\n"
        "base.mkdir(parents=True, exist_ok=True)\n"
        "data = sys.stdin.buffer.read()\n"
        "with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tf:\n"
        "    tf.extractall(base)\n"
        "print(str(base))\n"
    )


def _exec_script(remote_dir, flags):
    return (
        "import os, pathlib, subprocess, sys, tempfile\n"
        f"base = pathlib.Path(tempfile.gettempdir()) / {json.dumps(remote_dir)}\n"
        f"flags = {json.dumps(flags)}\n"
        "cmd = [sys.executable, str(base / 'tests' / 'render_check.py')]\n"
        "i = 0\n"
        "while i < len(flags):\n"
        "    if flags[i] in ('--ledger', '--dir') and i + 1 < len(flags):\n"
        "        cmd += [flags[i], str(base / flags[i + 1])]\n"
        "        i += 2\n"
        "    else:\n"
        "        cmd.append(flags[i])\n"
        "        i += 1\n"
        "env = os.environ.copy()\n"
        "env['PYTHONUTF8'] = '1'\n"
        "r = subprocess.run(cmd, cwd=str(base), env=env)\n"
        "sys.exit(r.returncode)\n"
    )


def _pull_script(remote_dir, cleanup):
    return (
        "import io, pathlib, shutil, sys, tarfile, tempfile\n"
        f"base = pathlib.Path(tempfile.gettempdir()) / {json.dumps(remote_dir)}\n"
        "run_dir = base / 'run'\n"
        "buf = io.BytesIO()\n"
        "with tarfile.open(fileobj=buf, mode='w:gz') as tf:\n"
        "    for name in ('report.txt', 'app.log'):\n"
        "        p = run_dir / name\n"
        "        if p.is_file():\n"
        "            tf.add(p, arcname=name)\n"
        "    shots = run_dir / 'shots'\n"
        "    if shots.is_dir():\n"
        "        for p in sorted(shots.glob('*.png')):\n"
        "            tf.add(p, arcname='shots/' + p.name)\n"
        "sys.stdout.buffer.write(buf.getvalue())\n"
        "sys.stdout.buffer.flush()\n"
        f"if {bool(cleanup)!r} and base.exists():\n"
        "    shutil.rmtree(base, ignore_errors=True)\n"
    )


def main(argv=None):
    args = parse_args(argv)
    host = resolve_host(args)
    if not host:
        print("render_check_win: missing Windows SSH host; pass --host user@host or set DUDU_WIN_HOST",
              file=sys.stderr)
        return 2
    if not SAFE_DIR.match(args.remote_dir):
        print(f"render_check_win: invalid --remote-dir {args.remote_dir!r} (must match [\\w.-]+)",
              file=sys.stderr)
        return 2

    ledger_src = Path(args.ledger).expanduser() if args.ledger else ledger_source()
    if not (ledger_src / "tasks").is_dir():
        print(f"render_check_win: no ledger at {ledger_src} (set PM_HOME or pass --ledger)", file=sys.stderr)
        return 2

    out_dir = Path(args.out).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="dudu-rc-win-") as tmp_str:
        tar_path = Path(tmp_str) / "payload.tar.gz"
        try:
            selected_pm, _project, stats = build_payload(
                REPO, tar_path, ledger_src, rev=args.rev, pm_name=args.pm, thread_id=args.thread
            )
        except (ValueError, RuntimeError) as exc:
            print(f"render_check_win: {exc}", file=sys.stderr)
            return 2

        payload_bytes = tar_path.read_bytes()
        print(
            f"render_check_win: shipping {len(payload_bytes) / 1024:.1f} KB "
            f"(pm={selected_pm}, {stats['tasks']} tasks, {stats['files']} ledger files) to {host}...",
            flush=True,
        )

        # 1. Upload & extract payload
        up = subprocess.run(
            ssh_cmd(host, remote_python_cmd(_upload_script(args.remote_dir))),
            input=payload_bytes,
            capture_output=True,
            timeout=60,
        )
        if up.returncode != 0:
            err = (up.stderr or up.stdout).decode("utf-8", "replace").strip()
            print(f"render_check_win: upload failed (exit {up.returncode}): {err}", file=sys.stderr)
            return 2

        # 2. Execute render_check.py remotely
        flags = build_remote_run_args(args.remote_dir, args)
        run_proc = subprocess.run(
            ssh_cmd(host, remote_python_cmd(_exec_script(args.remote_dir, flags))),
            timeout=300,
        )

        # 3. Pull report.txt, app.log, shots/*.png and clean up remote temp dir unless --keep
        pull = subprocess.run(
            ssh_cmd(host, remote_python_cmd(_pull_script(args.remote_dir, cleanup=not args.keep))),
            capture_output=True,
            timeout=60,
        )
        if pull.returncode == 0 and pull.stdout:
            if out_dir.exists():
                shutil.rmtree(out_dir / "shots", ignore_errors=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(pull.stdout), mode="r:gz") as tf:
                tf.extractall(out_dir)
            shots_count = len(list((out_dir / "shots").glob("*.png"))) if (out_dir / "shots").is_dir() else 0
            print(f"render_check_win: pulled {shots_count} shot(s), report.txt, and app.log to {out_dir}", flush=True)
        else:
            err = (pull.stderr or b"").decode("utf-8", "replace").strip()
            print(f"render_check_win: warning: could not pull artifacts: {err}", file=sys.stderr)

        return run_proc.returncode


if __name__ == "__main__":
    sys.exit(main())
