"""Compatibility re-export: implementation lives in pmlib.agents.transcripts."""
import sys as _sys
import pmlib.agents.transcripts as _impl

_sys.modules[__name__] = _impl
