"""Cache-family inputs shared by the main OpenAI-wire request builders."""
from agent.prompt_cache_scope import resolve_prompt_cache_isolation_scope_safe


def cache_family_params(agent, api_mode):
    """Keep transport identity separate from physical conversation/session routing."""
    return {"stable_prompt_prefix": getattr(agent, "_cached_system_prompt_static", None),
            "cache_isolation_scope": resolve_prompt_cache_isolation_scope_safe(agent),
            "api_mode": api_mode}
