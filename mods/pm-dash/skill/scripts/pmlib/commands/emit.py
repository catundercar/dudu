"""How a command leaves when a service raised `PmError`, and writing what a service said. Layer 4."""
import sys

from ..errors import IdentityError, StoreError


def exit_with(ctx, err):
    """Leave as the command did before its body became a service: let StoreError/IdentityError bubble to cli.main;
    a PmError on stdout prints there and exits with its code; on stderr, exit 1 with the message as
    `sys.exit(message)` did, any other code after printing it."""
    if isinstance(err, (StoreError, IdentityError)):
        raise err
    if err.stream == "stdout":
        if str(err):
            ctx.out.line(str(err))
        sys.exit(err.code)
    if err.code == 1:
        sys.exit(str(err) if str(err) else 1)
    if str(err):
        ctx.out.err_line(str(err))
    sys.exit(err.code)


def say_all(ctx, said):
    """Write `(stream, text)` pairs in the order a service said them ("err": stderr, else stdout)."""
    for stream, text in said:
        if stream == "err":
            ctx.out.err_line(text)
        else:
            ctx.out.line(text)


def sayer(ctx):
    """A `say(text, err=False)` callback that writes each line as it is said."""
    def say(text, err=False):
        if err:
            ctx.out.err_line(text)
        else:
            ctx.out.line(text)
    return say
