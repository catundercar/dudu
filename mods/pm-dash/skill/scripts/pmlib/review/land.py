"""Merge (land) primitives: the project's verify commands, the check runner, `land`'s exit codes, and whether a branch
still matches the commit the PM approved. The `Landing` service (approve, triage, land) is in `pmlib/landing.py`.
Layer 3."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping

from ..context import Context
from ..osutil import own_group, stop_group


def verify_commands_for(
    ctx: Context,
    repo: str | Path,
    *,
    project_slug_val: str | None = None,
    folder_alias: str | None = None,
) -> list[str] | None:
    """The project's checks, one shell command per line of projects/<project>/verify[.<alias>] (`#` starts a comment);
    None when the file does not exist."""
    proj_dir = ctx.home.project(project_slug_val) if project_slug_val else ctx.home.project_for(repo)
    candidates: list[Path] = []
    if folder_alias:
        candidates.append(proj_dir.root / f"verify.{folder_alias}")
    candidates.append(proj_dir.verify)
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return None
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def verify_commands(
    repo: str | Path,
    *,
    project_slug_val: str | None = None,
    folder_alias: str | None = None,
) -> list[str] | None:
    return verify_commands_for(
        Context.from_env(),
        repo,
        project_slug_val=project_slug_val,
        folder_alias=folder_alias,
    )


# `land` exit codes: 1 a check failed or timed out, 2 refused (nothing was changed), 4 conflicts,
# 5 the merge could not be undone (the main checkout's state is printed), 128+n stopped by signal n.
LAND_REFUSED, LAND_CONFLICTS, LAND_STUCK = 2, 4, 5


class LandStopped(Exception):
    pass


def run_checks(repo: str | Path, checks: list[str], timeout: float, running: list[Any],
               env: Mapping[str, str] | None = None,
               tr: Any = None) -> tuple[str, str, str] | None:
    """Run the checks in order within one time limit. None when all pass, else (check, why, output)."""
    translate = tr if tr is not None else Context.from_env().config.tr
    base_env = os.environ if env is None else env
    deadline = time.time() + timeout
    for check in checks:
        proc = subprocess.Popen(check, shell=True, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", env={**base_env, "MAIN": str(repo)}, **own_group())
        running[:] = [proc]
        try:
            out, _ = proc.communicate(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            stop_group(proc)
            out = proc.communicate()[0]  # what it printed before it was stopped
            return check, translate(f"timed out: the checks have {timeout} s in all", f"超时：全部检查共 {timeout} 秒"), out or ""
        if proc.returncode:
            return check, translate(f"exit {proc.returncode}", f"退出码 {proc.returncode}"), out or ""
    running.clear()
    return None


def branch_matches_approved_commit_for(ctx: Context, repo: str | Path, branch: str | None, base: str | None,
                                       approved_commit: str) -> bool:
    """Verify `branch` HEAD is either `approved_commit` itself or has ONLY 2-parent merge commits bringing in
    commits already reachable from `base` (pure `git merge <base>` conflict-resolution commits) on top of it."""
    if not approved_commit or not branch:
        return False
    git = ctx.git
    approved_full = git.run(repo, "rev-parse", "--verify", "--quiet", f"{approved_commit}^{{commit}}")
    branch_head = git.run(repo, "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}")
    if not approved_full or not branch_head:
        return False
    target_base = git.merge_target(repo, base or "main")
    cur = branch_head
    for _ in range(50):
        if cur == approved_full:
            return True
        line = git.run(repo, "rev-list", "-1", "--parents", cur) or ""
        parts = line.split()
        if len(parts) != 3:
            return False  # non-merge (or octopus) commit after approved_commit: unreviewed change
        _, p1, p2 = parts
        if git.run(repo, "merge-base", "--is-ancestor", p2, target_base) is None:
            return False  # merged something other than base
        cur = p1
    return False


def _branch_matches_approved_commit(repo: str | Path, branch: str | None, base: str | None,
                                    approved_commit: str) -> bool:
    return branch_matches_approved_commit_for(Context.from_env(), repo, branch, base, approved_commit)
