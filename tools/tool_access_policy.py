"""Optional operator-pinned exact tool-name ceiling (including direct dispatch)."""


def allowed_tool_names():
    """None preserves legacy selection; empty/invalid means no tool capability."""
    from hermes_cli.config import load_config_readonly
    try:
        agent=(load_config_readonly() or {}).get('agent') or {}
        value=agent.get('allowed_tools')
    except (Exception,SystemExit):
        return frozenset()
    if value is None:return None
    if not isinstance(value,list) or any(not isinstance(n,str) or not n for n in value):return frozenset()
    return frozenset(value)
