"""Hierarchical catalog metadata and deterministic L2 discovery helpers."""
from agent.skill_utils import extract_skill_catalog_metadata


def hermes_metadata(frontmatter):
    """Malformed catalog containers stay canonically loadable without crashing tags/config readers."""
    metadata = frontmatter.get("metadata")
    hermes = metadata.get("hermes") if isinstance(metadata, dict) else None
    return hermes if isinstance(hermes, dict) else {}


def catalog_fields(frontmatter, name):
    """JSON-safe catalog projection shared by disk and plugin skill listing."""
    catalog = extract_skill_catalog_metadata(frontmatter, skill_name=name)
    return {"visibility": catalog.visibility, "profiles": list(catalog.profiles),
            "aliases": list(catalog.aliases), "metadata_valid": catalog.valid}


def filter_catalog_query(skills, query):
    """L2 includes deferred skills; only the explicit substring/category query narrows it."""
    needle = (query or "").strip().casefold()
    return [s for s in skills if not needle or needle in " ".join([
        str(s.get("name") or ""), " ".join(s.get("aliases") or []),
        str(s.get("description") or ""), str(s.get("category") or ""),
    ]).casefold()]


def alias_ambiguity(name, candidates):
    """Aliases must never steal another canonical identity, even across precedence tiers."""
    from tools.skills_tool import _safe_frontmatter
    from agent.skill_utils import skill_catalog_aliases
    alias_matches = []
    for directory, md in candidates:
        frontmatter = _safe_frontmatter(md)
        canonical = str(frontmatter.get("name") or md.parent.name)
        if name not in {canonical, md.parent.name, md.stem if directory is None else ""}:
            if name in skill_catalog_aliases(frontmatter, skill_name=canonical):
                alias_matches.append(md)
    if alias_matches and len(candidates) > 1:
        return f"Ambiguous skill name '{name}': alias collides with another skill; use an exact categorized path."
    return None
