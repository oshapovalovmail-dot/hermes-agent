"""Standalone native MemoryProvider entry point for the Atlas Mac bridge."""
from atlas_native_bridge.memory_provider import AtlasBridgeMemoryProvider


def register(ctx):
    ctx.register_memory_provider(AtlasBridgeMemoryProvider())
