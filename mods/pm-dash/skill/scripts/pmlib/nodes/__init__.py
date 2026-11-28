"""Self-hosted worker nodes: coordinator sync hub, HTTP/SSH-stdio wire carriers, and local worker agent (phase 6b). Layer 3."""
from __future__ import annotations

from .agent import (
    AGENT_FILE,
    CREDENTIAL,
    AgentError,
    Cycle,
    FileDriver,
    HcDriver,
    TaskState,
    WorkerAgent,
    default_state_dir,
    join,
    write_private,
    write_private_exclusive,
)
from .hub import SyncHub, error_reply, http_status_of, task_key
from .wire import (
    HttpHubClient,
    HubUnavailable,
    InProcessHubClient,
    StdioHubClient,
    client_for,
    handle_http,
    serve_http,
    serve_stdio,
    ssh_argv,
    wsgi_app,
)

__all__ = [
    "AGENT_FILE",
    "AgentError",
    "CREDENTIAL",
    "Cycle",
    "FileDriver",
    "HcDriver",
    "HttpHubClient",
    "HubUnavailable",
    "InProcessHubClient",
    "StdioHubClient",
    "SyncHub",
    "TaskState",
    "WorkerAgent",
    "client_for",
    "default_state_dir",
    "error_reply",
    "handle_http",
    "http_status_of",
    "join",
    "serve_http",
    "serve_stdio",
    "ssh_argv",
    "task_key",
    "write_private",
    "write_private_exclusive",
    "wsgi_app",
]
