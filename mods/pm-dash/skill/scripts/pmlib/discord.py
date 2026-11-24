"""Optional Discord mirror: channel board updates, per-PM MCP config, and turn mirroring. `DiscordMirror` over
explicit `Context`, plus legacy wrappers. Layer 3.

A PM can be bound to a Discord channel (`claim --discord-channel`), and the board mirrored into one
(`board --channel`). All of it is off unless config.json says {"discord": true}: then no call is made, nothing is
printed and nothing fails, whatever discord.json, the registrations or the token file hold from earlier installs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Sequence

from .context import Context
from .errors import Refused
from .ledger.ledger import Ledger
from .ledger.task import ACTIVE
from .project.project import ProjectRegistry, pm_name

DISCORD_HOME = Path(os.environ.get("DISCORD_HOME", Path.home() / ".claude" / "channels" / "discord"))
DISCORD_TOKEN_FILE = DISCORD_HOME / "pm-token.env"
DISCORD_PLUGIN_ROOT = Path.home() / ".claude" / "plugins" / "cache" / "claude-plugins-official" / "discord"
MCP_SERVER = "discord-pm"
DISCORD_API = "https://discord.com/api/v10"


def chunks(text: str, size: int = 1900, limit: int = 3) -> list[str]:
    parts: list[str] = []
    while text and len(parts) < limit:
        cut = text.rfind("\n", 0, size) if len(text) > size else len(text)
        cut = cut if cut > size // 2 else size
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts[-1] = parts[-1][:size - 30] + "\n…(已截断，完整内容见终端)"
    return parts


def replied_on_discord(transcript: str | Path | None) -> bool:
    """The last turn of a Claude Code transcript answered through the Discord plugin's reply tool."""
    try:
        lines = Path(transcript).read_text().splitlines()[::-1] if transcript else []
    except OSError:
        return False
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        content = (row.get("message") or {}).get("content")
        if row.get("isSidechain"):
            continue
        if (row.get("type") == "user" and not row.get("isMeta")
                and not row.get("isCompactSummary") and not row.get("isVisibleInTranscriptOnly")):
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            if any(isinstance(b, dict) and b.get("type") == "text" for b in blocks):
                return False  # the prompt that started this turn
        elif row.get("type") == "assistant" and isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_use" and "discord" in str(b.get("name", ""))
                   and str(b.get("name", "")).endswith("__reply") for b in content):
                return True
    return False


def discord_api(
    method: str,
    path: str,
    body: Any = None,
    *,
    token: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> Any:
    """One Discord REST call with the bot token; returns the parsed JSON, or None (no token: no call)."""
    import urllib.error
    import urllib.request
    tok = discord_token() if token is None else token
    if not tok:
        return None
    log = discord_log if log_fn is None else log_fn
    req = urllib.request.Request(
        f"{DISCORD_API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bot {tok}",
            "Content-Type": "application/json",
            "User-Agent": "pm.py (herdr PM skill)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        log(f"discord {method} {path}: HTTP {e.code} {e.read()[:200]!r}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        log(f"discord {method} {path}: {e!r}")
    return None


_DEFAULT_DISCORD_API = discord_api
_DEFAULT_DISCORD_HOME = DISCORD_HOME
_DEFAULT_DISCORD_PLUGIN_ROOT = DISCORD_PLUGIN_ROOT


class DiscordMirror:
    """Optional Discord board mirror, MCP config writer, and turn mirror over explicit `Context`."""

    def __init__(
        self,
        ctx: Context,
        *,
        discord_home: Path | None = None,
        plugin_root_dir: Path | None = None,
        api_fn: Callable[[str, str, Any], Any] | None = None,
    ) -> None:
        self.ctx = ctx
        self.discord_home = (
            Path(discord_home)
            if discord_home is not None
            else Path(ctx.env.get("DISCORD_HOME") or Path.home() / ".claude" / "channels" / "discord")
        )
        self.plugin_root_dir = Path(plugin_root_dir) if plugin_root_dir is not None else DISCORD_PLUGIN_ROOT
        self._api_fn = api_fn

    @property
    def cfg_path(self) -> Path:
        return self.ctx.home.discord_config

    @property
    def log_path(self) -> Path:
        return self.ctx.home.discord_log

    @property
    def mcp_dir(self) -> Path:
        return self.ctx.home.mcp

    @property
    def token_file(self) -> Path:
        return self.discord_home / "pm-token.env"

    def is_on(self) -> bool:
        return self.ctx.config.get("discord") is True

    def require_on(self) -> None:
        if not self.is_on():
            raise Refused('Discord is off: set "discord": true in config.json in the ledger home to use it')

    def token(self) -> str | None:
        tok = self.ctx.env.get("DISCORD_BOT_TOKEN")
        try:
            if not tok and self.token_file.exists():
                m = re.search(r"^DISCORD_BOT_TOKEN=(.+)$", self.token_file.read_text(), re.M)
                tok = m.group(1).strip() if m else None
        except OSError:
            return None
        return tok

    def log(self, text: str) -> None:
        """Append one line to discord.log in the ledger home; the mirror must never fail a command or a hook."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(f"{self.ctx.clock.now()} [{self.ctx.pane or '-'}] {text}\n")
        except OSError:
            pass

    def api(self, method: str, path: str, body: Any = None) -> Any:
        if self._api_fn is not None:
            return self._api_fn(method, path, body)
        return _DEFAULT_DISCORD_API(method, path, body, token=self.token() or "", log_fn=self.log)

    def read_cfg(self) -> dict[str, Any]:
        try:
            cfg = json.loads(self.cfg_path.read_text()) if self.cfg_path.exists() else {}
        except (OSError, ValueError):
            return {}
        return cfg if isinstance(cfg, dict) else {}

    def write_cfg(self, cfg: dict[str, Any]) -> Path:
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
        return self.cfg_path

    def board_text(self) -> str:
        """BOARD.md condensed for a single Discord message (limit 2000 chars)."""
        ledger = Ledger(self.ctx)
        tasks = ledger.raw_tasks()
        reg = ProjectRegistry(self.ctx)
        lines = [f"**PM Board** · {self.ctx.clock.now()}"]
        for project in sorted({t["project"] for t in tasks}):
            pm = reg.pm_record_for_project(project)
            where = f" · PM {pm['pane']}" if pm and pm.get("pane") else ""
            lines.append(f"\n__{project}__{where}")
            all_by_id = {x["id"]: x for x in tasks}
            for t in [t for t in tasks if t["project"] == project and t["status"] in ACTIVE]:
                latest = (t.get("log") or [{}])[-1].get("text", "").replace("\n", " ")[:60]
                who = " ".join(x for x in (t.get("pane"), t.get("agent")) if x) or t.get("owner", "")
                tag = ledger.task_num_label(t, all_by_id)
                prefix = f"{tag} " if tag else ""
                lines.append(f"• `{t['status']}` {prefix}{t['title']} — {who} · {latest}")
            if not any(t["project"] == project and t["status"] in ACTIVE for t in tasks):
                lines.append("• (no active tasks)")
        text = "\n".join(lines)
        return text if len(text) <= 1900 else text[:1880] + "\n…(truncated)"

    def post_board(self, force: bool = False) -> bool:
        """Mirror the board into the configured Discord channel by editing one message in place.

        Best effort: never fails the ledger write. Returns True when the message was updated.
        """
        if not self.is_on():
            return False
        cfg = self.read_cfg()
        channel = cfg.get("board_channel")
        if not channel or (self.ctx.env.get("PM_NO_DISCORD") and not force):
            return False
        body = {"content": self.board_text()}
        if cfg.get("message_id"):
            if self.api("PATCH", f"/channels/{channel}/messages/{cfg['message_id']}", body):
                return True
            cfg.pop("message_id", None)  # deleted by hand; post a fresh one
        created = self.api("POST", f"/channels/{channel}/messages", body)
        if not created or "id" not in created:
            return False
        cfg["message_id"] = created["id"]
        try:
            self.cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
        except OSError:
            pass
        return True

    def state_dir(self, repo: str | Path) -> Path:
        return self.discord_home / pm_name(repo)

    def plugin_root(self) -> Path:
        """Newest installed version of the official discord plugin."""
        versions = sorted(self.plugin_root_dir.glob("*/server.ts"), key=lambda p: p.parent.name)
        if not versions:
            raise Refused(f"discord plugin not installed under {self.plugin_root_dir}")
        return versions[-1].parent

    def mcp_config_path(self, repo: str | Path) -> Path:
        return self.mcp_dir / f"{pm_name(repo)}.json"

    def write_mcp_config(self, repo: str | Path) -> Path:
        """A session-only MCP config that runs the plugin's server with this PM's state dir."""
        self.mcp_dir.mkdir(parents=True, exist_ok=True)
        cfg = {
            "mcpServers": {
                MCP_SERVER: {
                    "command": "bun",
                    "args": ["run", "--cwd", str(self.plugin_root()), "--shell=bun", "--silent", "start"],
                    "env": {"DISCORD_STATE_DIR": str(self.state_dir(repo))},
                }
            }
        }
        path = self.mcp_config_path(repo)
        path.write_text(json.dumps(cfg, indent=2) + "\n")
        return path

    def write_state(self, repo: str | Path, channel_id: Any, user_ids: Sequence[Any]) -> Path:
        """Per-PM plugin state: own .env (token) and an access.json that admits only this PM's channel."""
        sdir = self.state_dir(repo)
        sdir.mkdir(parents=True, exist_ok=True)
        tok = self.token()
        if not tok:
            raise Refused(f"no bot token: put DISCORD_BOT_TOKEN=... in {self.token_file}")
        env = sdir / ".env"
        env.write_text(f"DISCORD_BOT_TOKEN={tok}\n")
        env.chmod(0o600)
        access_file = sdir / "access.json"
        access = json.loads(access_file.read_text()) if access_file.exists() else {}
        # "disabled" would drop guild messages too; allowlist with nobody drops DMs silently and keeps the channel.
        access.update({"dmPolicy": "allowlist", "allowFrom": [], "pending": {}})
        access.setdefault("groups", {})[str(channel_id)] = {"requireMention": False, "allowFrom": list(user_ids)}
        access_file.write_text(json.dumps(access, indent=2) + "\n")
        access_file.chmod(0o600)
        self.write_mcp_config(repo)
        return sdir

    def default_users(self) -> list[Any]:
        """Users already paired with the bot in the shared access.json (the user's own account)."""
        try:
            return list(json.loads((self.discord_home / "access.json").read_text()).get("allowFrom", []))
        except (OSError, ValueError, AttributeError):
            return []

    def mirror(self, rec: dict[str, Any] | None, text: str) -> None:
        """Post a PM's chat turn into its Discord channel, when its registration has one."""
        channel = ((rec or {}).get("discord") or {}).get("channel_id")
        if not channel or not text or self.ctx.env.get("PM_NO_DISCORD") or not self.is_on():
            return
        for part in chunks(text):
            if not self.api("POST", f"/channels/{channel}/messages", {"content": part, "flags": 4}):  # 4: no embeds
                self.log(f"mirror: post failed ({len(part)} chars)")
                return


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def _default_mirror() -> DiscordMirror:
    home_override = DISCORD_HOME if DISCORD_HOME != _DEFAULT_DISCORD_HOME else None
    plugin_override = DISCORD_PLUGIN_ROOT if DISCORD_PLUGIN_ROOT != _DEFAULT_DISCORD_PLUGIN_ROOT else None
    return DiscordMirror(Context.from_env(), discord_home=home_override, plugin_root_dir=plugin_override)


def discord_on() -> bool:
    return _default_mirror().is_on()


def discord_needed() -> None:
    _default_mirror().require_on()


def discord_token() -> str | None:
    return _default_mirror().token()


def discord_token_file() -> Path:
    return _default_mirror().token_file


def discord_log(text: str) -> None:
    _default_mirror().log(text)


def discord_cfg() -> dict[str, Any]:
    return _default_mirror().read_cfg()


def write_discord_cfg(cfg: dict[str, Any]) -> Path:
    return _default_mirror().write_cfg(cfg)


def board_text() -> str:
    return _default_mirror().board_text()


def post_board(force: bool = False) -> bool:
    return _default_mirror().post_board(force=force)


def discord_state_dir(repo: str | Path) -> Path:
    return _default_mirror().state_dir(repo)


def write_discord_state(repo: str | Path, channel_id: Any, user_ids: Sequence[Any]) -> Path:
    return _default_mirror().write_state(repo, channel_id, user_ids)


def plugin_root() -> Path:
    return _default_mirror().plugin_root()


def mcp_config_path(repo: str | Path) -> Path:
    return _default_mirror().mcp_config_path(repo)


def write_mcp_config(repo: str | Path) -> Path:
    return _default_mirror().write_mcp_config(repo)


def default_discord_users() -> list[Any]:
    return _default_mirror().default_users()


def discord_mirror(rec: dict[str, Any] | None, text: str) -> None:
    _default_mirror().mirror(rec, text)
