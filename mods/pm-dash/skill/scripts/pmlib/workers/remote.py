"""Remote `hc` workers (`<machine>/t7`, `pm-message-routing.md` §7.3 items 1-3, §9.3 phase 6a): the worktree prepared
on the other machine through `hc exec --on`, the worker's state folder (`context.json`, `credential.json`, the
report outbox) handed over with `hc file write --on`, and the branch brought back to the coordinator's checkout
before a review or a merge. Layer 3 (workers).

Nothing here adds or logs in a machine, or opens a shell on it: every remote step is a single `hc exec --on <m>`
(no shell unless the argv names one) or `hc file read|write --on <m>`, on a machine the user added to hc.

Per-machine settings (config.json):

    "machines": {"dev": {"repos": {"dudu": "~/src/dudu"},        # the project's clone there (required)
                         "pm": "python3 ~/.claude/skills/pm/scripts/pm.py",  # how a worker there runs pm.py
                         "worktrees": "~/.herdr/worktrees",      # where task worktrees go there
                         "state": "~/.herdr/pm-worker",          # where worker state folders go there
                         "git_remote": ""}}                      # a git remote both sides reach (else: bundles)
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from ..context import Context
from ..errors import Refused
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..messaging.address import Endpoint
from ..messaging.outbox import CONTEXT_FILE, CREDENTIAL_FILE, TaskTokens
from ..messaging.transports.remote_hc import RemoteHcTransport


DEFAULT_REMOTE_PM = "python3 ~/.claude/skills/pm/scripts/pm.py"
MAX_BUNDLE_BYTES = 6 * 1024 * 1024  # `hc exec` keeps 8 MB of stdout; base64 grows a bundle by a third
_B64_WRITE = "import base64,sys;open(sys.argv[1],'wb').write(base64.b64decode(sys.stdin.read()))"
_B64_READ = "import base64,sys;sys.stdout.write(base64.b64encode(open(sys.argv[1],'rb').read()).decode())"


@dataclass(frozen=True)
class MachineProfile:
    """What the coordinator knows about a machine's side of one project."""

    name: str
    repo: str
    pm_command: str = DEFAULT_REMOTE_PM
    worktrees: str = "~/.herdr/worktrees"
    state_root: str = "~/.herdr/pm-worker"
    git_remote: str = ""


@dataclass(frozen=True)
class RemotePrep:
    worktree: str
    state_dir: str
    base_sha: str
    repo: str


def machine_profile(ctx: Context, machine: str, local_repo: str, *, remote_repo: str = "") -> MachineProfile:
    cfg = ctx.config.get("machines") if ctx.config is not None else None
    row = (cfg or {}).get(machine) if isinstance(cfg, Mapping) else None
    row = row if isinstance(row, Mapping) else {}
    slug = project_slug(local_repo)
    repos = row.get("repos") if isinstance(row.get("repos"), Mapping) else {}
    repo = str(remote_repo or repos.get(slug) or "").strip()
    if not repo:
        raise Refused(ctx.config.tr(
            f"no checkout of {slug} on {machine}: set config.json machines.{machine}.repos.{slug} or pass --remote-repo",
            f"{machine} 上没有登记 {slug} 的检出：在 config.json 写 machines.{machine}.repos.{slug}，或传 --remote-repo"))
    return MachineProfile(
        name=machine, repo=repo,
        pm_command=str(row.get("pm") or DEFAULT_REMOTE_PM),
        worktrees=str(row.get("worktrees") or "~/.herdr/worktrees"),
        state_root=str(row.get("state") or "~/.herdr/pm-worker"),
        git_remote=str(row.get("git_remote") or ""),
    )


def is_remote_task(task: Mapping[str, Any] | None) -> bool:
    remote = (task or {}).get("remote")
    return isinstance(remote, Mapping) and bool(remote.get("machine")) and bool(remote.get("worktree"))


def worker_context(ctx: Context, task: Mapping[str, Any]) -> dict[str, Any]:
    """The remote worker's read-only `context.json`: refreshed (never left as the dispatch snapshot) whenever a
    field it carries changes: merge approval (`land_approved`), a new epoch (Fable's #329 review note)."""
    remote = task.get("remote") if isinstance(task.get("remote"), Mapping) else {}
    la = task.get("land_approved")
    return {
        "remote": True,
        "role": "worker",
        "project": project_slug(str(task.get("repo") or "")),
        "repo": str(task.get("repo") or ""),
        "task_id": str(task.get("id") or ""),
        "number": task.get("number"),
        "title": str(task.get("title") or ""),
        "branch": str(task.get("branch") or ""),
        "base": str(task.get("base") or ""),
        "epoch": int(remote.get("epoch") or 1),
        "machine": str(remote.get("machine") or ""),
        "terminal": str(remote.get("terminal") or ""),
        "worktree": str(remote.get("worktree") or ""),
        "land_approved": dict(la) if isinstance(la, Mapping) else None,
        "lang": ctx.config.lang() if ctx.config is not None else "en",
        "pm": str(remote.get("pm") or DEFAULT_REMOTE_PM),
        "updated": ctx.clock.now(),
    }


class RemoteWorkspace:
    """One machine's side of one project, driven through `hc exec --on` / `hc file read|write --on`."""

    def __init__(self, ctx: Context, profile: MachineProfile, *, transport: RemoteHcTransport | None = None) -> None:
        self.ctx = ctx
        self.profile = profile
        self.transport = transport or RemoteHcTransport(ctx)
        self._home = ""

    @classmethod
    def for_task(cls, ctx: Context, task: Mapping[str, Any]) -> RemoteWorkspace:
        remote = task.get("remote") if isinstance(task.get("remote"), Mapping) else {}
        machine = str(remote.get("machine") or "")
        if not machine:
            raise Refused(f"{task.get('id')}: not a remote worker task")
        try:
            prof = machine_profile(ctx, machine, str(task.get("repo") or ""), remote_repo=str(remote.get("repo") or ""))
        except Refused:
            prof = MachineProfile(name=machine, repo=str(remote.get("repo") or ""))
        return cls(ctx, prof)

    # --- primitives ----------------------------------------------------------------------------------------------

    def _tr(self, en: str, zh: str) -> str:
        return self.ctx.config.tr(en, zh) if self.ctx.config is not None else en

    def require_link(self, what: str) -> None:
        self.transport.forget_machine_state()
        view = self.transport.machine_view(self.profile.name)
        if str(view.get("state") or "") != "connected":
            raise Refused(self._tr(
                f"machine {self.profile.name} is {view.get('detail') or view.get('state')}: cannot {what} now "
                f"(nothing was changed; retry once `hc machine ls` shows it connected)",
                f"机器 {self.profile.name} 当前 {view.get('detail') or view.get('state')}：现在无法{what}"
                f"（未做任何改动；等 `hc machine ls` 显示 connected 后重试）"))

    def exec(self, argv: list[str], *, what: str, cwd: str = "", timeout: float = 120, stdin: str | None = None,
             check: bool = True) -> dict[str, Any]:
        res = self.ctx.hc.exec(argv, on=self.profile.name, cwd=cwd, timeout=timeout, stdin=stdin)
        err = res.get("error") if isinstance(res, Mapping) else None
        if res is None or err:
            kind = (err.get("kind") if isinstance(err, Mapping) else err) or "no answer"
            raise Refused(self._tr(f"machine {self.profile.name} unreachable ({kind}) while trying to {what}",
                                   f"机器 {self.profile.name} 不可达（{kind}），无法{what}"))
        if res.get("timed_out"):
            raise Refused(self._tr(f"{what} on {self.profile.name} timed out", f"{self.profile.name} 上{what}超时"))
        if check and int(res.get("code") or 0) != 0:
            tail = (str(res.get("stderr") or "") or str(res.get("stdout") or "")).strip()[-600:]
            raise Refused(self._tr(f"{what} on {self.profile.name} failed: {tail}",
                                   f"{self.profile.name} 上{what}失败：{tail}"))
        return res

    def home(self) -> str:
        if not self._home:
            res = self.exec(["sh", "-c", 'printf %s "$HOME"'], what="read $HOME")
            self._home = str(res.get("stdout") or "").strip().rstrip("/")
        return self._home

    def abspath(self, path: str) -> str:
        p = str(path or "")
        if p == "~":
            return self.home()
        if p.startswith("~/"):
            return f"{self.home()}/{p[2:]}"
        if not p.startswith("/"):
            return f"{self.home()}/{p}"
        return p

    def write_file(self, path: str, text: str, *, what: str, private: bool = False) -> None:
        res = self.ctx.hc.file_write(path, text, on=self.profile.name)
        err = res.get("error") if isinstance(res, Mapping) else None
        if res is None or err:
            kind = (err.get("kind") if isinstance(err, Mapping) else err) or "no answer"
            raise Refused(self._tr(f"could not write {what} on {self.profile.name} ({kind})",
                                   f"无法在 {self.profile.name} 上写入{what}（{kind}）"))
        if private:
            self.exec(["chmod", "600", path], what=f"protect {what}")

    # --- worktree ------------------------------------------------------------------------------------------------

    def _has_commit(self, repo: str, sha: str) -> bool:
        res = self.exec(["git", "-C", repo, "cat-file", "-e", f"{sha}^{{commit}}"], what="look up the base commit",
                        check=False)
        return int(res.get("code") or 0) == 0

    def push_commit(self, local_repo: str, remote_repo: str, sha: str) -> str:
        """Bring commit `sha` (and its history) to the remote clone as a bundle when it does not have it. Each push
        uses a ref of its own (`refs/pm-remote/<sha>`, here and there, force-updated), so pushes of unrelated
        histories for different tasks never collide; returns that remote ref, which the caller drops once the
        commit is reachable from a branch (`drop_pushed`)."""
        ref = f"refs/pm-remote/{sha}"
        git = self.ctx.git
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "push.bundle"
            try:
                if git.run(local_repo, "update-ref", ref, sha) is None or \
                        git.run(local_repo, "bundle", "create", str(bundle), ref) is None:
                    raise Refused(self._tr(f"could not bundle {sha[:7]} in {local_repo}",
                                           f"无法在 {local_repo} 打包提交 {sha[:7]}"))
            finally:
                git.run(local_repo, "update-ref", "-d", ref)
            data = bundle.read_bytes()
        if len(data) > MAX_BUNDLE_BYTES:
            raise Refused(self._tr(
                f"commit bundle is {len(data)} bytes, over the {MAX_BUNDLE_BYTES} hc can carry: fetch "
                f"{sha[:7]} into {remote_repo} on {self.profile.name} (or set machines.{self.profile.name}.git_remote)",
                f"提交的 bundle 有 {len(data)} 字节，超过 hc 能带的 {MAX_BUNDLE_BYTES}：请先在 {self.profile.name} "
                f"的 {remote_repo} 里取到 {sha[:7]}（或配置 machines.{self.profile.name}.git_remote）"))
        remote_bundle = str(self.exec(["mktemp"], what="make a temporary file").get("stdout") or "").strip()
        if not remote_bundle:
            raise Refused(self._tr(f"mktemp gave no path on {self.profile.name}", f"{self.profile.name} 上 mktemp 没给出路径"))
        try:
            self.exec(["python3", "-c", _B64_WRITE, remote_bundle], stdin=base64.b64encode(data).decode("ascii"),
                      what=f"upload commit {sha[:7]}")
            self.exec(["git", "-C", remote_repo, "fetch", remote_bundle, f"+{ref}:{ref}"],
                      what=f"unbundle commit {sha[:7]}")
        finally:
            self.exec(["rm", "-f", remote_bundle], what="remove the uploaded bundle", check=False)
        return ref

    def drop_pushed(self, remote_repo: str, ref: str) -> None:
        if ref:
            self.exec(["git", "-C", remote_repo, "update-ref", "-d", ref], what=f"drop {ref}", check=False)

    def _remote_rev(self, cwd_repo: str, ref: str) -> str:
        res = self.exec(["git", "-C", cwd_repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                        what=f"read {ref}", check=False)
        return str(res.get("stdout") or "").strip() if int(res.get("code") or 0) == 0 else ""

    def _remote_is_ancestor(self, cwd_repo: str, older: str, newer: str) -> bool:
        res = self.exec(["git", "-C", cwd_repo, "merge-base", "--is-ancestor", older, newer],
                        what="compare commits", check=False)
        return int(res.get("code") or 0) == 0

    def _bring_local_commits(self, local_repo: str, remote_repo: str, worktree: str, branch: str) -> None:
        """The task's branch here has commits the remote one lacks (a reviewer's fix, a worker on another machine):
        bring them and fast-forward the remote branch. Diverged histories are refused, never overwritten."""
        local_head = self.ctx.git.run(local_repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}") or ""
        if not local_head:
            return
        remote_head = self._remote_rev(remote_repo, f"refs/heads/{branch}")
        if remote_head == local_head:
            return
        pushed = self.push_commit(local_repo, remote_repo, local_head) if not self._has_commit(remote_repo, local_head) else ""
        try:
            self._fast_forward_to(remote_repo, worktree, branch, local_head, remote_head)
        finally:
            self.drop_pushed(remote_repo, pushed)

    def _fast_forward_to(self, remote_repo: str, worktree: str, branch: str, local_head: str, remote_head: str) -> None:
        if self._remote_is_ancestor(remote_repo, local_head, remote_head):
            return  # the remote branch already contains everything this side has
        if not self._remote_is_ancestor(remote_repo, remote_head, local_head):
            raise Refused(self._tr(
                f"{branch} on {self.profile.name} ({remote_head[:7]}) and here ({local_head[:7]}) have diverged: "
                f"reconcile them by hand before redispatching (nothing was changed)",
                f"{self.profile.name} 上的 {branch}（{remote_head[:7]}）和本机（{local_head[:7]}）已分叉："
                f"请先手动合并再重派（未做任何改动）"))
        dirty = self.exec(["git", "-C", worktree, "status", "--porcelain", "--untracked-files=no"],
                          what=f"check {worktree} is clean")
        if str(dirty.get("stdout") or "").strip():
            raise Refused(self._tr(
                f"{self.profile.name}:{worktree} has uncommitted changes; cannot fast-forward {branch} to {local_head[:7]}",
                f"{self.profile.name}:{worktree} 有未提交改动，无法把 {branch} 快进到 {local_head[:7]}"))
        self.exec(["git", "-C", worktree, "merge", "--ff-only", local_head], what=f"fast-forward {branch}")

    def prepare(self, *, local_repo: str, branch: str, base: str, epoch: int = 1) -> RemotePrep:
        """The task's worktree in the project's clone there, made or reused:

        - its worktree already there on `branch` (a redispatch on the same machine): reused as it is;
        - `branch` already in that clone without a worktree: checked out into one;
        - otherwise a new branch, from this side's `refs/heads/<branch>` when it exists (the task moves here from
          another machine: its commits come along) else from `base`.

        Commits this side has beyond the remote branch are brought and fast-forwarded; diverged histories, or a
        path taken by something else, are refused. Each epoch gets its own state folder (its own outbox and token).
        """
        self.require_link("prepare a worktree")
        base_sha = self.ctx.git.run(local_repo, "rev-parse", "--verify", f"{base}^{{commit}}") or ""
        if not base_sha:
            raise Refused(self._tr(f"base {base} not found in {local_repo}", f"{local_repo} 里找不到基准 {base}"))
        slug = project_slug(local_repo)
        leaf = branch.replace("/", "-")
        remote_repo = self.abspath(self.profile.repo)
        worktree = self.abspath(f"{self.profile.worktrees.rstrip('/')}/{slug}/{leaf}")
        state_dir = self.abspath(f"{self.profile.state_root.rstrip('/')}/{slug}-{leaf}-e{int(epoch or 1)}")
        self.exec(["git", "-C", remote_repo, "rev-parse", "--git-dir"], what=f"find the clone {remote_repo}")
        exists = int(self.exec(["test", "-e", worktree], what="check the worktree path", check=False).get("code") or 0) == 0
        if exists:
            on = self.exec(["git", "-C", worktree, "branch", "--show-current"], what=f"read {worktree}", check=False)
            if int(on.get("code") or 0) != 0 or str(on.get("stdout") or "").strip() != branch:
                raise Refused(self._tr(f"{self.profile.name}:{worktree} exists and is not a worktree on {branch}",
                                       f"{self.profile.name}:{worktree} 已存在，且不是 {branch} 的工作树"))
        elif self._remote_rev(remote_repo, f"refs/heads/{branch}"):
            self.exec(["git", "-C", remote_repo, "worktree", "add", worktree, branch], what=f"git worktree add {worktree}")
        else:
            start = self.ctx.git.run(local_repo, "rev-parse", "--verify", "--quiet",
                                     f"refs/heads/{branch}^{{commit}}") or base_sha
            pushed = self.push_commit(local_repo, remote_repo, start) if not self._has_commit(remote_repo, start) else ""
            try:
                self.exec(["git", "-C", remote_repo, "worktree", "add", "-b", branch, worktree, start],
                          what=f"git worktree add {worktree}")
            finally:
                self.drop_pushed(remote_repo, pushed)
        self._bring_local_commits(local_repo, remote_repo, worktree, branch)
        # Made only once the worktree is in place: a refused prepare leaves nothing behind.
        self.exec(["mkdir", "-p", state_dir], what="make the worker state folder")
        return RemotePrep(worktree=worktree, state_dir=state_dir, base_sha=base_sha, repo=remote_repo)

    # --- state folder ------------------------------------------------------------------------------------------

    def write_state(self, state_dir: str, context: Mapping[str, Any], credential: Mapping[str, Any] | None = None) -> None:
        self.write_file(f"{state_dir}/{CONTEXT_FILE}", json.dumps(dict(context), ensure_ascii=False, indent=2) + "\n",
                        what="the worker context")
        if credential is not None:
            # Made 0600 from its first byte (umask 077 in the writing shell): never readable by others, not even
            # between a write and a chmod.
            # A leftover `.tmp` is removed first and the new one created exclusively (`set -C`), so it never keeps
            # an older file's mode.
            self.exec(["sh", "-c", 'umask 077 && rm -f "$1.tmp" && set -C && cat > "$1.tmp" && chmod 600 "$1.tmp" '
                       '&& mv -f "$1.tmp" "$1"', "sh",
                       f"{state_dir}/{CREDENTIAL_FILE}"],
                      stdin=json.dumps(dict(credential), indent=2) + "\n", what="write the worker credential")

    # --- bringing the branch back --------------------------------------------------------------------------------

    def fetch_branch(self, task: Mapping[str, Any]) -> str:
        """Bring the remote worker's branch into the coordinator's checkout (`refs/remotes/workers/<m>/<branch>`,
        then `refs/heads/<branch>` moved to it), by bundle over `hc exec` or through the configured git remote.
        Returns the fetched commit. Refused, with what to do, when the machine is unreachable."""
        remote = task.get("remote") if isinstance(task.get("remote"), Mapping) else {}
        repo = str(task.get("repo") or "")
        branch = str(task.get("branch") or "")
        worktree = str(remote.get("worktree") or "")
        if not (repo and branch and worktree):
            raise Refused(f"{task.get('id')}: remote task without repo, branch or worktree")
        self.require_link(self._tr("fetch the worker's branch", "取回 worker 的分支"))
        git = self.ctx.git
        track = f"refs/remotes/workers/{self.profile.name}/{branch}"
        if self.profile.git_remote:
            self.exec(["git", "-C", worktree, "push", self.profile.git_remote, f"+refs/heads/{branch}:refs/heads/{branch}"],
                      what=f"push {branch} to {self.profile.git_remote}")
            res = git.run_raw(repo, "fetch", self.profile.git_remote, f"+refs/heads/{branch}:{track}", timeout=300)
            if res is None or not res.ok:
                raise Refused(self._tr(f"git fetch {self.profile.git_remote} {branch} failed: "
                                       f"{(res.stderr if res else '').strip()[-400:]}",
                                       f"git fetch {self.profile.git_remote} {branch} 失败"))
        else:
            head = str(self.exec(["git", "-C", worktree, "rev-parse", f"refs/heads/{branch}"],
                                 what=f"read {branch}").get("stdout") or "").strip()
            have = git.run(repo, "rev-parse", "--verify", "--quiet", f"{head}^{{commit}}") if head else None
            if not have:
                base_sha = str(remote.get("base_sha") or "")
                state_dir = str(remote.get("state_dir") or worktree)
                rb = f"{state_dir}/fetch.bundle"
                spec = [f"refs/heads/{branch}"] + ([f"^{base_sha}"] if base_sha and git.run(
                    repo, "rev-parse", "--verify", "--quiet", f"{base_sha}^{{commit}}") else [])
                made = self.exec(["git", "-C", worktree, "bundle", "create", rb, *spec], what=f"bundle {branch}",
                                 check=False)
                if int(made.get("code") or 0) != 0:
                    # Nothing new past the base (an empty bundle is refused): fall back to the full branch.
                    self.exec(["git", "-C", worktree, "bundle", "create", rb, f"refs/heads/{branch}"],
                              what=f"bundle {branch}")
                got = self.exec(["python3", "-c", _B64_READ, rb], what=f"download the {branch} bundle", timeout=300)
                self.exec(["rm", "-f", rb], what="remove the bundle there", check=False)
                if got.get("truncated"):
                    raise Refused(self._tr(
                        f"{branch} bundle is larger than hc can carry; set machines.{self.profile.name}.git_remote",
                        f"{branch} 的 bundle 超过 hc 的上限；请配置 machines.{self.profile.name}.git_remote"))
                data = base64.b64decode(str(got.get("stdout") or "").encode("ascii"))
                with tempfile.TemporaryDirectory() as tmp:
                    local_bundle = Path(tmp) / "branch.bundle"
                    local_bundle.write_bytes(data)
                    res = git.run_raw(repo, "fetch", str(local_bundle), f"+refs/heads/{branch}:{track}", timeout=300)
                if res is None or not res.ok:
                    raise Refused(self._tr(f"git fetch of the {branch} bundle failed: "
                                           f"{(res.stderr if res else '').strip()[-400:]}",
                                           f"取回 {branch} 的 bundle 失败"))
            else:
                git.run(repo, "update-ref", track, head)
        sha = git.run(repo, "rev-parse", "--verify", "--quiet", f"{track}^{{commit}}") or ""
        if not sha:
            raise Refused(f"{track} missing after fetch")
        local = git.run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}") or ""
        if local == sha:
            return sha
        anc = git.run_raw(repo, "merge-base", "--is-ancestor", local, sha) if local else None
        if local and (anc is None or not anc.ok):
            # Never move the branch back or sideways: commits made here (a reviewer's fix, an earlier epoch's work)
            # would silently drop out of what gets reviewed and merged.
            raise Refused(self._tr(
                f"{branch} here ({local[:7]}) is not an ancestor of the remote worker's {sha[:7]} (fetched to {track}): "
                f"not a fast-forward, so {branch} was left as it is; have the worker merge {local[:7]} "
                f"(`pm.py send <task> ...`) or reconcile by hand",
                f"本机 {branch}（{local[:7]}）不是远端 worker {sha[:7]} 的祖先（已取到 {track}）：非快进，"
                f"本机分支保持不动；请让 worker 合入 {local[:7]} 或手动处理"))
        holder = git.checkout_of(repo, branch)
        if holder:
            raise Refused(self._tr(f"{branch} is checked out in {holder} here; cannot move it to the remote worker's "
                                   f"{sha[:7]}", f"{branch} 在本机 {holder} 里检出着，不能改指到远端 worker 的 {sha[:7]}"))
        # Compare-and-swap: only from the head just checked (or from nothing), so a concurrent change is not lost.
        if git.run(repo, "update-ref", f"refs/heads/{branch}", sha, local or "0" * 40) is None:
            raise Refused(self._tr(f"{branch} changed here while fetching; fetch again",
                                   f"取回时本机 {branch} 被改动了；请重新取回"))
        return sha

    def review_checkout(self, task: Mapping[str, Any], sha: str) -> str:
        """A detached local worktree at `sha` for a read-only reviewer of a remote task."""
        repo = str(task.get("repo") or "")
        branch = str(task.get("branch") or "")
        path = self.ctx.git.worktree_home(repo) / f"{branch.replace('/', '-')}-remote"
        if path.is_dir():
            if self.ctx.git.run(str(path), "checkout", "--detach", sha) is None:
                raise Refused(f"could not move {path} to {sha[:7]}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if self.ctx.git.run(repo, "worktree", "add", "--detach", str(path), sha) is None:
                raise Refused(f"git worktree add --detach {path} {sha[:7]} failed")
        return str(path)


def issue_credential(ctx: Context, task_id: str, epoch: int, machine: str) -> dict[str, Any]:
    return TaskTokens(ctx.home.tokens).issue(task_id, epoch, machine=machine)


def next_remote_epoch(task: Mapping[str, Any] | None) -> int:
    """The epoch a new remote worker of this task gets: one past every earlier endpoint's."""
    best = 0
    for row in [(task or {}).get("remote"), *((task or {}).get("remote_history") or [])]:
        if isinstance(row, Mapping) and isinstance(row.get("epoch"), int):
            best = max(best, int(row["epoch"]))
    ep = (task or {}).get("endpoint")
    if isinstance(ep, Mapping) and isinstance(ep.get("epoch"), int):
        best = max(best, int(ep["epoch"]))
    return best + 1 if best else 1


def record_remote_worker(ctx: Context, task_id: str, *, machine: str, terminal: str, epoch: int, prep: RemotePrep,
                         pm_command: str) -> dict[str, Any]:
    """Write the remote endpoint on the task: `remote` (the earlier one moved to `remote_history`, whose outbox
    is still pulled for late reports) and the structured `endpoint`."""
    def _rec(cur: Any, _ch: Any) -> dict[str, Any]:
        assert cur is not None
        raw = cur.raw
        old = raw.get("remote")
        if isinstance(old, Mapping) and old.get("state_dir") and old.get("state_dir") != prep.state_dir:
            hist = [dict(h) for h in (raw.get("remote_history") or []) if isinstance(h, Mapping)]
            hist.append(dict(old))
            raw["remote_history"] = hist[-8:]
        raw["remote"] = {"machine": machine, "terminal": terminal, "epoch": int(epoch), "worktree": prep.worktree,
                         "state_dir": prep.state_dir, "repo": prep.repo, "base_sha": prep.base_sha, "pm": pm_command}
        raw["endpoint"] = Endpoint(runtime="hc", machine=machine, terminal=terminal, workspace=prep.worktree,
                                   agent_kind=str((raw.get("worker") or {}).get("kind") or ""),
                                   epoch=int(epoch)).to_dict()
        return raw

    changed = Ledger(ctx).change(task_id, _rec)
    return changed.raw if changed is not None else {}


def refresh_remote_context(ctx: Context, task: Mapping[str, Any]) -> str:
    """Rewrite a remote worker's `context.json` from the task as it is now. "" when written (or not remote), else
    why not (the machine is down: the next refresh writes it; the ledger stays the truth)."""
    if not is_remote_task(task):
        return ""
    remote = task["remote"]
    try:
        RemoteWorkspace.for_task(ctx, task).write_state(str(remote["state_dir"]), worker_context(ctx, task))
    except Refused as err:
        return str(err)
    return ""
