"""Opt-in profile-local web search registration."""
from .provider import YandexSearchProvider


def register(ctx):
    if not ctx.get_config("enabled", False):
        return
    ctx.register_web_search_provider(YandexSearchProvider())
    endpoint = ctx.get_config("context_endpoint")
    if endpoint:
        ctx.register_web_search_provider(YandexSearchProvider(context=True, endpoint=endpoint))
