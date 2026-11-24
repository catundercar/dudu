"""Compatibility re-export: implementation lives in pmlib.terminals.events."""
import sys as _sys
import pmlib.terminals.events as _impl

_sys.modules[__name__] = _impl
