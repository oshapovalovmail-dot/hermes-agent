from . import qyp_delegate
"""QYP delegation plugin registration."""

import os

from .qyp_delegate import (
    DELEGATE_QYP_SCHEMA,
    QYP_TERMINAL_SCHEMA,
    check_qyp_delegate_available,
    handle_delegate_qyp,
    handle_qyp_terminal,
)


def register(ctx) -> None:
    if not ctx.get_config("enabled", False):
        return
    ctx.register_tool(
        name="delegate_qyp",
        toolset="qyp_delegate",
        schema=DELEGATE_QYP_SCHEMA,
        handler=lambda args, **kw: handle_delegate_qyp(args),
        check_fn=check_qyp_delegate_available,
        description="Delegate a bounded task to the the configured SSH worker worker plane.",
        emoji="🛰️",
    )
    # Least privilege: the raw SSH executor exists only inside the child process
    # created by delegate_qyp. Normal CLI/gateway sessions never see it.
    if os.environ.get("QYP_DELEGATE_CHILD") == "1":
        ctx.register_tool(
            name="qyp_terminal",
            toolset="qyp_worker",
            schema=QYP_TERMINAL_SCHEMA,
            handler=lambda args, **kw: handle_qyp_terminal(args),
            check_fn=check_qyp_delegate_available,
            description="Execute one command on the configured SSH worker for a delegated worker.",
            emoji="🖥️",
        )
