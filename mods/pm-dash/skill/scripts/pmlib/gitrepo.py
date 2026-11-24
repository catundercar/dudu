"""git, run as a subprocess: `GitRepo` port for project roots, branches, worktrees, branch state, merges,
and research/dirty checks; plus where the desktop app makes a project's worktrees (~/.herdr/worktrees). Layer 1."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Any


@dataclass(frozen=True)
class GitResult:
    """Raw outcome of a `git -C <path> ...` invocation without stripping stdout."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class GitRepo:
    """Port for git CLI queries, worktree management, merges, and status/ignore checks."""

    def __init__(
        self,
        *,
        worktree_base: Path | None = None,
        runner: Any = None,
        raw_runner: Any = None,
        worktree_home_fn: Any = None,
        project_root_fn: Any = None,
        git_state_fn: Any = None,
        merge_target_fn: Any = None,
    ) -> None:
        self._worktree_base = Path(worktree_base) if worktree_base is not None else None
        self._runner = runner
        self._raw_runner = raw_runner
        self._worktree_home_fn = worktree_home_fn
        self._project_root_fn = project_root_fn
        self._git_state_fn = git_state_fn
        self._merge_target_fn = merge_target_fn

    def _default_worktree_base(self) -> Path:
        return self._worktree_base if self._worktree_base is not None else (Path.home() / ".herdr" / "worktrees")

    def run_raw(self, path: str | Path, *args: str, timeout: float | None = 30) -> GitResult | None:
        """Run `git -C <path> *args` and return `GitResult` (stdout preserved verbatim), or None on OSError/timeout."""
        if self._raw_runner is not None:
            return self._raw_runner(path, *args, timeout=timeout)
        try:
            r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return GitResult(returncode=r.returncode, stdout=r.stdout, stderr=r.stderr)

    def run(self, path: str | Path, *args: str, timeout: float | None = 30) -> str | None:
        """Run `git -C <path> *args` and return stripped stdout on success, else None."""
        if self._runner is not None:
            return self._runner(path, *args)
        res = self.run_raw(path, *args, timeout=timeout)
        return res.stdout.strip() if res is not None and res.ok else None

    def main_root(self, path: str | Path) -> str | None:
        """The main checkout of the repository containing path, so worktrees map to one project."""
        common = self.run(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
        return str(Path(common).parent) if common else None

    def project_root(self, path: str | Path) -> str | None:
        """Main checkout of the repository containing path, or the directory itself when it is not under git."""
        if self._project_root_fn is not None:
            return self._project_root_fn(path)
        root = self.main_root(path)
        if root:
            return root
        d = Path(path).resolve()
        return str(d) if d.is_dir() else None

    def base_branch(self, repo: str | Path) -> str:
        for name in ("main", "master"):
            if self.run(repo, "rev-parse", "--verify", "--quiet", name) is not None:
                return name
        return "HEAD"

    def merge_target(self, repo: str | Path, base: str) -> str:
        """The branch a task's work is merged into: its base, or the repository's main branch once deleted."""
        if self._merge_target_fn is not None:
            return self._merge_target_fn(repo, base)
        return base if self.run(repo, "rev-parse", "--verify", "--quiet", base) is not None else self.base_branch(repo)

    def git_state(self, path: str | Path, branch: str | None, base: str) -> tuple[int | None, int | None]:
        """(commits on branch not in base, changed files in path) or (None, None)."""
        if self._git_state_fn is not None:
            return self._git_state_fn(path, branch, base)
        ahead = self.run(path, "rev-list", "--count", f"{base}..{branch}") if branch else None
        status = self.run(path, "status", "--porcelain") if path and Path(path).is_dir() else None
        dirty = None
        if status is not None:
            # Linked tool caches such as `.tools` are expected in fresh worktrees.
            dirty = len([l for l in status.splitlines() if l and not l.endswith(" .tools")])
        return (int(ahead) if ahead and ahead.isdigit() else None), dirty

    def is_owned_worktree(self, path: str | Path | None) -> bool:
        """True only when `path` is inside the managed worktrees root (~/.herdr/worktrees/)."""
        if not path:
            return False
        try:
            return Path(path).resolve().is_relative_to(self._default_worktree_base().resolve())
        except OSError:
            return False

    def worktree_home(self, repo: str | Path) -> Path:
        """Where a project's worktrees are made in the desktop app."""
        if self._worktree_home_fn is not None:
            return Path(self._worktree_home_fn(repo))
        return self._default_worktree_base() / Path(repo).name

    def checkout_of(self, repo: str | Path, branch: str) -> str | None:
        """The checkout (the main one or a worktree) that has this branch checked out, or None."""
        for block in (self.run(repo, "worktree", "list", "--porcelain") or "").split("\n\n"):
            path = re.search(r"^worktree (.+)$", block, re.M)
            if path and re.search(rf"^branch refs/heads/{re.escape(branch)}$", block, re.M):
                return path.group(1)
        return None

    def worktree_add(self, repo: str | Path, path: str | Path, branch: str, base: str) -> bool:
        return self.run(repo, "worktree", "add", str(path), "-b", branch, base) is not None

    def worktree_remove(self, repo: str | Path, worktree: str | Path, *, force: bool = True) -> bool:
        args = ("worktree", "remove", "--force", str(worktree)) if force else ("worktree", "remove", str(worktree))
        return self.run(repo, *args) is not None

    def delete_branch(self, repo: str | Path, branch: str, *, force: bool = True) -> bool:
        return self.run(repo, "branch", "-D" if force else "-d", branch) is not None

    def current_branch(self, repo: str | Path) -> str | None:
        return self.run(repo, "branch", "--show-current")

    def branch_exists(self, repo: str | Path, branch: str) -> bool:
        return self.run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is not None

    def is_ancestor(self, repo: str | Path, ancestor: str, descendant: str = "HEAD") -> bool:
        return self.run(repo, "merge-base", "--is-ancestor", ancestor, descendant) is not None

    def rev_parse(self, repo: str | Path, ref: str, *, short: bool = False, quiet: bool = False) -> str | None:
        args: list[str] = ["rev-parse"]
        if short:
            args.append("--short")
        else:
            args.append("--verify")
        if quiet:
            args.append("--quiet")
        args.append(ref)
        return self.run(repo, *args)

    def has_tracked_changes(self, repo: str | Path) -> bool:
        return bool(self.run(repo, "status", "--porcelain", "--untracked-files=no"))

    def merge_no_commit(self, repo: str | Path, branch: str) -> GitResult:
        res = self.run_raw(repo, "merge", "--no-ff", "--no-commit", branch, timeout=None)
        return res if res is not None else GitResult(returncode=1, stdout="", stderr="git merge failed to start")

    def conflicts(self, repo: str | Path) -> list[str]:
        res = self.run_raw(repo, "diff", "--name-only", "--diff-filter=U", "-z", timeout=30)
        if res is None or not res.stdout:
            return []
        return [f for f in res.stdout.split("\0") if f]

    def commit(self, repo: str | Path, message: str) -> GitResult:
        res = self.run_raw(repo, "commit", "-q", "-m", message, timeout=None)
        return res if res is not None else GitResult(returncode=1, stdout="", stderr="git commit failed to start")

    def undo_merge(self, repo: str | Path) -> bool:
        """Abort the merge in progress, falling back to `git reset --merge`."""
        for args in (("merge", "--abort"), ("reset", "--merge")):
            self.run_raw(repo, *args, timeout=None)
            merging = self.run(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD") is not None
            if not merging and not self.run(repo, "status", "--porcelain", "--untracked-files=no"):
                return True
        return False

    def index_lock(self, worktree: str | Path) -> Path | None:
        """git's index.lock of this worktree while it exists (a commit, checkout or add under way), else None."""
        path = (self.run(str(worktree), "rev-parse", "--git-path", "index.lock") or "").strip()
        return Path(worktree, path) if path and Path(worktree, path).exists() else None

    def tracked_files(self, folder: str | Path, subpath: str, *, timeout: float = 15) -> set[str]:
        """POSIX paths tracked by git under `<folder>/<subpath>`, or set() when not in git / on error."""
        res = self.run_raw(folder, "ls-files", "-z", "--", subpath, timeout=timeout)
        if res is None or not res.ok or not res.stdout:
            return set()
        return {p for p in res.stdout.split("\0") if p}

    def is_ignored(self, repo: str | Path, relpath: str, *, timeout: float = 15) -> bool:
        """Whether git ignores `relpath` in `repo` (checks .gitignore, .git/info/exclude and global excludes)."""
        res = self.run_raw(repo, "check-ignore", "-q", "--", relpath, timeout=timeout)
        return res is not None and res.ok

    def porcelain_status_z(self, worktree: str | Path, *, untracked_all: bool = True, timeout: float = 30) -> str | None:
        """Raw NUL-delimited `git status --porcelain [-uall] -z` stdout, or None on error."""
        args = ("status", "--porcelain", "-uall", "-z") if untracked_all else ("status", "--porcelain", "-z")
        res = self.run_raw(worktree, *args, timeout=timeout)
        if res is None or not res.ok:
            return None
        return res.stdout


def git(path, *args):
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def main_root(path):
    """The main checkout of the repository containing path, so worktrees map to one project."""
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return str(Path(common).parent) if common else None


def project_root(path):
    """Main checkout of the repository containing path, or the directory itself when it is not under git.

    A PM can coordinate a plain working directory (for example an issue-triage folder).
    """
    root = main_root(path)
    if root:
        return root
    d = Path(path).resolve()
    return str(d) if d.is_dir() else None


def base_branch(repo):
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", name) is not None:
            return name
    return "HEAD"


def merge_target(repo, base):
    """The branch a task's work is merged into: its base, or the repository's main branch once the base is deleted
    (a base branch is often merged and removed before the tasks built on it)."""
    return base if git(repo, "rev-parse", "--verify", "--quiet", base) is not None else base_branch(repo)


def git_state(path, branch, base):
    """(commits on branch not in base, changed files in path) or (None, None)."""
    ahead = git(path, "rev-list", "--count", f"{base}..{branch}") if branch else None
    status = git(path, "status", "--porcelain") if path and Path(path).is_dir() else None
    dirty = None
    if status is not None:
        # Linked tool caches such as `.tools` are expected in fresh worktrees.
        dirty = len([l for l in status.splitlines() if l and not l.endswith(" .tools")])
    return (int(ahead) if ahead and ahead.isdigit() else None), dirty


def is_owned_worktree(path):
    """True only when `path` is inside ~/.herdr/worktrees/ (worktrees created by pm.py dispatch)."""
    if not path:
        return False
    try:
        return Path(path).resolve().is_relative_to((Path.home() / ".herdr" / "worktrees").resolve())
    except OSError:
        return False


def worktree_home(repo):
    """Where a project's worktrees are made in the desktop app."""
    return Path.home() / ".herdr" / "worktrees" / Path(repo).name


def checkout_of(repo, branch):
    """The checkout (the main one or a worktree) that has this branch checked out, or None."""
    for block in (git(repo, "worktree", "list", "--porcelain") or "").split("\n\n"):
        path = re.search(r"^worktree (.+)$", block, re.M)
        if path and re.search(rf"^branch refs/heads/{re.escape(branch)}$", block, re.M):
            return path.group(1)
    return None


def undo_merge(repo):
    """Abort the merge in progress, falling back to `git reset --merge`. True when the checkout is back to a clean
    HEAD with no merge in progress; never discards changes that git refuses to drop."""
    for args in (("merge", "--abort"), ("reset", "--merge")):
        subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
        merging = git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD") is not None
        if not merging and not git(repo, "status", "--porcelain", "--untracked-files=no"):
            return True
    return False


def index_lock(worktree):
    """git's index.lock of this worktree while it exists (a commit, checkout or add under way), else None."""
    path = (git(str(worktree), "rev-parse", "--git-path", "index.lock") or "").strip()
    return Path(worktree, path) if path and Path(worktree, path).exists() else None
