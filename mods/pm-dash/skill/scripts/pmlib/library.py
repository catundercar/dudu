"""Library and Memory page edits, path parsing, and research report migration: `LibraryService` over explicit `Context`,
plus legacy wrappers. Layer 3.

`pm.py project library|memory <slug>` list them as JSON; `project save|delete|restore|history|add|retopic` edit
them. The Library's docs root (projects/<slug>/docs) and both memory layers are editable; research and
instructions are read-only. A delete keeps what was there in .history, and `restore` brings it back.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .caller import memory_writer
from .context import Context, SystemClock
from .home import project_slug
from .ledger.ledger import slugify
from .memory.candidates import MemoryCandidates
from .memory.layer import (
    FOLDED_TOPICS,
    MEMORY_TYPES,
    PERSONAL_TYPES,
    SECRET,
    STALE_DAYS,
    TOPICS,
    TYPE_TOPIC,
    WORKER_ONLY_TYPES,
    MemoryLayer,
    MemoryRefused,
    clean_memory,
    memory_text,
    read_memory,
    scalar,
)
from .project.conversation import Conversation
from .store import (
    DOCS_FOLDER,
    DOCS_RESEARCH,
    DOCUMENT_ROOTS,
    RESEARCH_FOLDER,
    VersionConflict,
    version_of,
    write_atomic,
)


WRITABLE_ROOTS = ("docs", "memory", "personal")
RESEARCH_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def memory_version(m: dict[str, Any]) -> str:
    try:
        return version_of(os.lstat(m["path"]))
    except (OSError, KeyError):
        return ""


def parse_memory(text: str, name: str) -> dict[str, Any] | None:
    """A memory file's text as read_memory reads a file, plus what it said for type and topic as written ("" when
    it said none), so that an edit naming a type or topic that does not exist is refused instead of mended."""
    text = text.replace("\r\n", "\n")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        m = read_memory(path)
    if not m:
        return None
    said: dict[str, str] = {}
    head = text[3:].partition("\n---")[0]
    for line in head.splitlines():
        key, colon, value = line.strip().partition(":")
        if colon and key in ("type", "topic"):
            said[key] = scalar(value)
    m["said_type"], m["said_topic"] = said.get("type", ""), said.get("topic", "")
    m.pop("path", None)
    return m


def memory_target(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".md") else rel
    if "/" in stem or not stem:
        raise ValueError(f"invalid memory name: {rel!r}")
    return stem


def split_context_path(raw_path: Any, explicit_root: str | None = None) -> tuple[str, str]:
    """Split a CLI context file target (`project/decisions.md`, `user/foo.md`, `research/topic/README.md`,
    or `--root project decisions.md`)."""
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("document path is required")
    if explicit_root is not None:
        return explicit_root, raw_path
    head, slash, tail = raw_path.partition("/")
    if slash and head in DOCUMENT_ROOTS and tail:
        return head, tail
    return "project", raw_path


class LibraryService:
    """Library/Memory page read/edit service and research report migration over explicit `Context`."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def _tr(self, en: str, zh: str) -> str:
        return self.ctx.config.tr(en, zh)

    def _utc_stamp(self) -> str:
        if isinstance(self.ctx.clock, SystemClock):
            return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return self.ctx.clock.datetime_now().strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def slug_repo(self, slug: str) -> str:
        """A folder for a project slug that the memory functions find the project by."""
        repo = self.ctx.store._project_repo(slug)
        if repo is not None and project_slug(repo) == slug:
            return str(repo)
        return str(self.ctx.home.projects / slug)

    def memory_row(self, m: dict[str, Any], layer: str) -> dict[str, Any]:
        """One memory as the Memory page lists it."""
        mem = MemoryLayer(self.ctx)
        stamp = str(m.get("modified") or "")
        row: dict[str, Any] = {
            "layer": layer,
            "root": "memory" if layer == "project" else "personal",
            "path": f"{m['name']}.md",
            "name": m["name"],
            "type": m["type"],
            "topic": m["topic"],
            "description": m["description"],
            "modified": (stamp[:19] + "Z") if len(stamp) >= 19 else stamp,
            "by": m.get("by") or "",
            "version": memory_version(m),
            "writable": True,
        }
        for key in ("quote", "quote_checked", "verified", "task", "expires", "checked"):
            if m.get(key):
                row[key] = m[key]
        if m.get("topic_inferred"):
            row["topic_inferred"] = True
        age = mem.days_old(m.get("checked") or m.get("modified") or "")
        if age > STALE_DAYS:
            row["stale_days"] = age
        if mem.expired(m):
            row["expired"] = True
        return row

    def memory_page(self, repo: str | Path) -> dict[str, Any]:
        """The Memory page of a project as JSON-ready data."""
        cands = MemoryCandidates(self.ctx, repo)
        cands.prune()
        proj_layer = MemoryLayer(self.ctx, repo)
        pers_layer = MemoryLayer(self.ctx, None)
        files = [self.memory_row(m, "project") for m in proj_layer.memories() if not Path(m["path"]).is_symlink()]
        files += [self.memory_row(m, "personal") for m in pers_layer.memories() if not Path(m["path"]).is_symlink()]
        waiting = [
            {
                "worker": who,
                "name": m["name"],
                "path": f"{who}/{m['name']}.md",
                "type": m["type"],
                "description": m["description"],
                "modified": m.get("modified") or "",
            }
            for who, m in cands.list()
        ]
        return {
            "project": project_slug(repo),
            # Stable English keys only: the UI translates them by config lang (ui-labels-i18n).
            "topics": [{"id": t, "folded": t in FOLDED_TOPICS} for t in TOPICS],
            "types": [
                {
                    "id": k,
                    "worker_only": k in WORKER_ONLY_TYPES,
                    "layers": [x for x, ok in (("project", k != "user"), ("personal", k in PERSONAL_TYPES)) if ok],
                }
                for k in ("project", "feedback", "reference", "pitfall", "user")
            ],
            "layers": [
                {"id": "project", "root": "memory", "writable": True},
                {"id": "personal", "root": "personal", "writable": True},
            ],
            "files": files,
            "candidates": waiting,
            "history": {"project": len(proj_layer.history()), "personal": len(pers_layer.history())},
        }

    def save_memory_file(
        self,
        repo: str | Path,
        personal: bool,
        name: str,
        text: str,
        *,
        writer: tuple[str, str],
        if_version: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Write a memory from the Memory page. Returns (memory, created)."""
        role, caller = writer
        if role not in ("user", "pm"):
            raise MemoryRefused(self._tr(
                "the Memory page is the user's (and the PM's): a worker writes with `remember`",
                "Memory 页是用户（和 PM）改的：worker 用 `remember` 写",
            ))
        stem = Path(name).stem if name.endswith(".md") else name
        slug = slugify(stem)
        if not slug or slug != stem:
            raise MemoryRefused(self._tr(
                "a memory's name is a short English slug, such as no-right-angle-wires",
                "记忆名应是简短英文短横线名，例如 no-right-angle-wires",
            ))
        layer_obj = MemoryLayer(self.ctx, None if personal else repo)
        path = layer_obj.dir / f"{slug}.md"
        if path.is_symlink():
            raise MemoryRefused(f"{slug}.md is not a plain file")
        old = read_memory(path)
        current = memory_version(old) if old else ""
        if if_version is not None and not (if_version == "new" and not old) and if_version != current:
            raise VersionConflict(f"{slug} changed since it was read", current)
        text = (text or "").replace("\r\n", "\n")
        if text.lstrip("\ufeff").startswith("---"):
            new = parse_memory(text.lstrip("\ufeff"), slug)
            if not new:
                raise MemoryRefused(self._tr(
                    "the frontmatter is not closed (a line with --- after it)",
                    "frontmatter 未闭合（需要一行 --- 结束）",
                ))
            if new["said_type"] and new["said_type"] not in MEMORY_TYPES:
                raise MemoryRefused(self._tr(
                    f"type is one of {', '.join(MEMORY_TYPES)}",
                    f"type 只能是 {', '.join(MEMORY_TYPES)} 之一",
                ))
            if new["said_topic"] and new["said_topic"] not in TOPICS:
                raise MemoryRefused(self._tr(
                    f"topic is one of {', '.join(TOPICS)}: the groups are fixed",
                    f"topic 只能是 {', '.join(TOPICS)} 之一：主题组是固定的",
                ))
            if new["said_type"]:
                new["type"] = new["said_type"]
            elif old:
                new["type"] = old["type"]
            if new["said_topic"]:
                new["topic"] = new["said_topic"]
            else:
                new["topic"] = (old or {}).get("topic") if old and old["type"] == new["type"] else TYPE_TOPIC[new["type"]]
        elif old:
            new = {**old, "body": text}
        else:
            raise MemoryRefused(self._tr(
                "a new memory needs its frontmatter (name, description, metadata: type, topic)",
                "新建记忆需要带 frontmatter（name、description、metadata: type、topic）",
            ))
        new["description"] = clean_memory(new.get("description", ""))
        new["body"] = clean_memory(new.get("body", "")) or new["description"]
        new["quote"] = clean_memory(new.get("quote", ""))
        new["verified"] = clean_memory(new.get("verified", ""))
        if not new["description"]:
            raise MemoryRefused(self._tr(
                "say what the memory is in one sentence (description)",
                "请用一句话写明记忆摘要（description）",
            ))
        if any(SECRET.search(str(new.get(k) or "")) for k in ("description", "body", "quote", "verified")):
            raise MemoryRefused(self._tr(
                "that looks like a key or a token: every later session and worker reads memory, so it is "
                "not written. Leave the secret out.",
                "内容疑似包含密钥或 token：后续会话和 worker 都会读记忆，拒绝写入。请去掉密钥。",
            ))
        kind = new["type"]
        if personal and kind not in PERSONAL_TYPES:
            raise MemoryRefused(self._tr(
                "the personal layer holds user, feedback and reference",
                "个人层只放 user、feedback 和 reference",
            ))
        if not personal and kind == "user":
            raise MemoryRefused(self._tr(
                "a memory about the user belongs to the personal layer",
                "关于用户的记忆（user）放在个人层",
            ))
        if kind == "pitfall":
            new["topic"] = "pitfalls"
        elif new.get("topic") == "pitfalls":
            raise MemoryRefused(self._tr(
                "the pitfalls group holds pitfalls: set type to pitfall, or pick another topic",
                "pitfalls 组只放踩坑：把 type 设成 pitfall，或换个主题",
            ))
        if not new["quote"]:
            new["quote_checked"] = ""
        elif old and new["quote"] == old.get("quote", "") and old.get("quote_checked"):
            new["quote_checked"] = old["quote_checked"]
        else:
            new["quote_checked"] = "true" if layer_obj.quote_said(new["quote"], project_repo=repo) else "false"
        new.pop("topic_inferred", None)
        m = {
            **new,
            "name": slug,
            "by": (old or {}).get("by") or new.get("by") or caller,
            "modified": self._utc_stamp(),
            "checked": self.ctx.clock.now()[:10],
            "extra": {**((old or {}).get("extra") or {}), **(new.get("extra") or {})},
        }
        if old and all(
            m.get(k) == old.get(k)
            for k in ("description", "type", "topic", "body", "quote", "quote_checked", "verified", "expires")
        ):
            return old, False
        with layer_obj.lock():
            if old:
                layer_obj.keep_history(old, "replaced")
            path.write_text(memory_text(m), encoding="utf-8")
            layer_obj.write_index()
        Conversation(self.ctx, repo).record(
            "memory",
            layer="personal" if personal else "project",
            action="edit" if old else "remember",
            name=slug,
            memory_type=kind,
            topic=m["topic"],
            by=caller,
            text=m["description"],
            **({"was": old["description"]} if old and old["description"] != m["description"] else {}),
        )
        return read_memory(path), not old

    def retopic_memory(
        self,
        repo: str | Path,
        personal: bool,
        name: str,
        *,
        writer: tuple[str, str],
        topic: str | None = None,
        kind: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Move a memory to another topic (and/or type), as a drag between folders of the Memory page does."""
        layer_obj = MemoryLayer(self.ctx, None if personal else repo)
        slug = slugify(Path(name).stem)
        old = read_memory(layer_obj.dir / f"{slug}.md")
        if not old:
            raise MemoryRefused(f"no memory called {slug}")
        if old["type"] == "pitfall" and topic and topic != "pitfalls" and not kind:
            raise MemoryRefused(self._tr(
                "a pitfall stays in pitfalls: give it another type too (--type)",
                "踩坑只能在 pitfalls 组：要换组请同时换类型（--type）",
            ))
        kind = kind or old["type"]
        topic = "pitfalls" if kind == "pitfall" else (topic or (old["topic"] if old["type"] == kind else TYPE_TOPIC[kind]))
        return self.save_memory_file(
            repo,
            personal,
            slug,
            memory_text({**old, "topic": topic, "type": kind}),
            writer=writer,
        )

    def research_migrations(self, slug: str) -> list[dict[str, Any]]:
        """What `project research-migrate` would do for each evidence/<topic>/README.md."""
        base = self.ctx.home.project(slug).docs_research
        rows: list[dict[str, Any]] = []
        for rel, (_st, readme, source) in sorted(self.ctx.store._evidence_reports(slug).items()):
            topic = rel.split("/", 1)[0]
            dest = base / f"{topic}.md"
            try:
                text = readme.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                rows.append({"topic": topic, "from": f"{RESEARCH_FOLDER}/{rel}", "status": "unreadable"})
                continue
            links: list[str] = []
            for target in RESEARCH_LINK.findall(text):
                if re.match(r"^(?:[a-z][a-z0-9+.-]*:|#|/)", target, re.I):
                    continue
                if (readme.parent / target.split("#", 1)[0]).exists():
                    links.append(target)
            status = "move"
            if os.path.lexists(dest):
                try:
                    status = "done" if dest.read_text(encoding="utf-8") == text else "exists"
                except (OSError, UnicodeDecodeError):
                    status = "exists"
            rows.append({
                "topic": topic,
                "from": f"{RESEARCH_FOLDER}/{rel}",
                "source": source,
                "file": str(readme),
                "to": f"{DOCS_FOLDER}/{DOCS_RESEARCH}/{topic}.md",
                "dest": str(dest),
                "status": status,
                "links_to_fix": sorted(set(links)),
            })
        return rows

    def migrate_research(self, slug: str, topics: tuple[str, ...] = (), *, apply: bool = False) -> dict[str, Any]:
        """Copy evidence reports to the project's docs/research. Dry run unless apply."""
        rows = [r for r in self.research_migrations(slug) if not topics or r["topic"] in topics]
        sources = self.ctx.store.research_sources(slug)
        for r in rows:
            if not apply or r.get("status") != "move":
                continue
            dest = Path(r["dest"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(dest, Path(r["file"]).read_bytes())
            task = sources.get(r["from"])
            if task:
                self.ctx.store.note_research_source(slug, r["to"], task)
            r["status"] = "moved"
        return {"project": slug, "applied": bool(apply), "reports": rows}

    def project_write_check(self, writer: tuple[str, str]) -> None:
        role, _ = writer
        if role not in ("user", "pm"):
            raise MemoryRefused(self._tr(
                "the Library and Memory pages are edited by the user (or the PM), not by a worker",
                "Library 和 Memory 页由用户（或 PM）编辑，worker 不能改",
            ))


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def slug_repo(slug: str) -> str:
    return LibraryService(Context.from_env()).slug_repo(slug)


def memory_row(m: dict[str, Any], layer: str) -> dict[str, Any]:
    return LibraryService(Context.from_env()).memory_row(m, layer)


def memory_page(repo: str | Path) -> dict[str, Any]:
    return LibraryService(Context.from_env()).memory_page(repo)


def save_memory_file(
    repo: str | Path,
    personal: bool,
    name: str,
    text: str,
    if_version: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    ctx = Context.from_env()
    return LibraryService(ctx).save_memory_file(
        repo,
        personal,
        name,
        text,
        writer=memory_writer(repo),
        if_version=if_version,
    )


def retopic_memory(
    repo: str | Path,
    personal: bool,
    name: str,
    topic: str | None = None,
    kind: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    ctx = Context.from_env()
    return LibraryService(ctx).retopic_memory(
        repo,
        personal,
        name,
        writer=memory_writer(repo),
        topic=topic,
        kind=kind,
    )


def research_migrations(slug: str) -> list[dict[str, Any]]:
    return LibraryService(Context.from_env()).research_migrations(slug)


def migrate_research(slug: str, topics: tuple[str, ...] = (), apply: bool = False) -> dict[str, Any]:
    return LibraryService(Context.from_env()).migrate_research(slug, topics=topics, apply=apply)


def project_write_check(repo: str | Path) -> None:
    LibraryService(Context.from_env()).project_write_check(memory_writer(repo))
