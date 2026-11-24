"""Review, merge-approval, triage and land commands (`review`, `approve`, `triage`, `land`): thin
adapters over `Reviews(ctx)` and `Landing(ctx)`. Layer 4."""
from ..context import Context
from ..errors import IdentityError, PmError, StoreError
from ..landing import ApproveRequest, LandRequest, Landing, TriageRequest
from ..review.review import ReviewFailed, ReviewRequest, Reviews
from .emit import exit_with, say_all


def cmd_approve(a, ctx=None):
    """PM approves a task for merge and delegates execution (`land` + post-merge steps) asynchronously to its
    worker (default when live) or a dedicated execution helper. Returns immediately; never blocks the PM."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        done = Landing(ctx).approve(ApproveRequest.from_args(a))
    except (StoreError, IdentityError):
        raise
    except PmError as err:
        exit_with(ctx, err)
    a.id = done.task_id
    say_all(ctx, done.said)


def cmd_triage(a, ctx=None):
    """PM delegates inspection and safe unblocking of a stuck worker terminal to an async exec helper."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        done = Landing(ctx).triage(TriageRequest.from_args(a))
    except (StoreError, IdentityError):
        raise
    except PmError as err:
        exit_with(ctx, err)
    a.id = done.task_id
    say_all(ctx, done.said)


def cmd_review(a, ctx=None):
    """Start a read-only reviewer on a task's branch, as a thread of its own: task <id>-review."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Reviews(ctx).start(ReviewRequest.from_args(a))
    except ReviewFailed as err:
        say_all(ctx, err.said)
        exit_with(ctx, err)
    if res.review_id:
        a.id = res.review_id[:-len("-review")]
    say_all(ctx, res.said)
    if res.plan is not None:
        ctx.out.json(res.plan, indent=1)


def cmd_land(a, ctx=None):
    """Merge a task's branch in the main checkout, run the project's checks, and commit only when all pass."""
    if getattr(a, "delegate", False):
        return cmd_approve(a, ctx=ctx)
    ctx = Context.from_env() if ctx is None else ctx
    try:
        done = Landing(ctx).land(LandRequest.from_args(a))
    except (StoreError, IdentityError):
        raise
    except PmError as err:
        exit_with(ctx, err)
    a.id = done.task_id
    say_all(ctx, done.said)


def register_approve_triage_commands(sub):
    ap = sub.add_parser("approve", help="PM approves a task for merge and delegates `land` + post-merge steps asynchronously "
                                        "to the task's worker (default when live) or an exec helper (returns immediately)")
    ap.add_argument("id")
    ap.add_argument("--commit", help="explicitly approve this commit SHA (default: the reviewed/reported commit)")
    ap.add_argument("--message", help="commit message for `land` (default: merge <branch>: <task title>)")
    ap.add_argument("--keep", action="store_true", help="keep the worker, worktree and branch after landing")
    ap.add_argument("--timeout", type=int, default=600, help="seconds for verify checks (default 600)")
    ap.add_argument("--via", choices=["auto", "worker", "helper"], default="auto",
                    help="who executes the merge (default auto: live worker, else exec helper)")
    ap.add_argument("--note", help="extra instructions for the executor (merge/install notes)")
    ap.add_argument("--profile", help="helper profile when --via helper (or worker offline)")
    ap.add_argument("--kind", help="helper agent kind when --via helper")
    ap.add_argument("--model", help="helper model when --via helper")
    ap.add_argument("--effort", help="helper effort when --via helper")
    ap.add_argument("--advisor", help="helper advisor when --via helper")
    ap.add_argument("--codex-profile", help="codex profile when --via helper")
    ap.add_argument("--confirmed", action="store_true", help="user confirmed Fable helper when --via helper")
    ap.add_argument("--revoke", action="store_true", help="revoke an existing merge approval without delegating")
    tr_cmd = sub.add_parser("triage", help="PM delegates inspection and safe unblocking of a stuck worker terminal "
                                           "to an async exec helper (returns immediately)")
    tr_cmd.add_argument("id")
    tr_cmd.add_argument("--note", help="extra context for the triage helper")
    tr_cmd.add_argument("--profile", help="helper profile")
    tr_cmd.add_argument("--kind", help="helper agent kind")
    tr_cmd.add_argument("--model", help="helper model")
    tr_cmd.add_argument("--effort", help="helper effort")
    tr_cmd.add_argument("--advisor", help="helper advisor")
    tr_cmd.add_argument("--codex-profile", help="codex profile")
    tr_cmd.add_argument("--confirmed", action="store_true", help="user confirmed Fable helper")


def register_land_review_commands(sub):
    la = sub.add_parser("land", help="merge a task's branch in the main checkout once the project's checks pass "
                                     "(workers require PM approval via `approve`; PM should use `approve` or `--delegate`)")
    la.add_argument("id")
    la.add_argument("--keep", action="store_true", help="keep the worker, worktree and branch (no automatic retire)")
    la.add_argument("--message", help="commit message (default: merge <branch>: <task title>)")
    la.add_argument("--timeout", type=int, default=None, help="seconds for all checks together (default 600)")
    la.add_argument("--delegate", action="store_true", help="alias for `pm.py approve`: delegate merge asynchronously to worker/helper")
    la.add_argument("--via", choices=["auto", "worker", "helper"], default="auto", help="with --delegate: auto|worker|helper")
    la.add_argument("--note", help="with --delegate: extra instructions for the executor")
    rv = sub.add_parser("review", help="start a read-only reviewer on a task's branch, as thread <id>-review")
    rv.add_argument("id")
    rv.add_argument("--name", help="the reviewer's terminal name (default: <worker>-review)")
    rv.add_argument("--kind", help="reviewer program (default: config.json reviewer, else claude by the review table "
                                    "for the task's profile, else config.json worker, else codex)")
    rv.add_argument("--model", help="default: config.json reviewer, else the review table by the task's profile "
                                     "(config.json review; light/deep: opus, standard/hard: fable, sonnet with "
                                     "\"fable\": false), else config.json "
                                     "worker, else the program's own")
    rv.add_argument("--effort", help="default: config.json, else the program's own")
    rv.add_argument("--tab", help="the tab's short name, with tabs.new_tab (default: config.json tabs.review, else "
                                  "review/审查 by lang, a dash and the task's)")
    rv.add_argument("--bug", help="the BUG number the tab shows (default: in --tab, else the task's)")
    rv.add_argument("--codex-profile", help="codex profile for a codex reviewer (default: the pool's pick)")
    rv.add_argument("--dry-run", action="store_true", help="print what would start as JSON; start nothing")
