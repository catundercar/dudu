"""Compatibility re-export: implementation lives in pmlib.store."""
import sys as _sys
import pmlib.store as _impl

_sys.modules[__name__] = _impl
