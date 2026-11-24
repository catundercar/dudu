"""Compatibility re-export: implementation lives in pmlib.project.readmodel."""
import sys as _sys
import pmlib.project.readmodel as _impl

_sys.modules[__name__] = _impl
