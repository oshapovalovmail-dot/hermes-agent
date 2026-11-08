---
sidebar_label: Skill catalog visibility and cache families
---

# Skill catalog visibility and cache families

## Three discovery levels

The system-prompt catalog (L1) is a compact, conversation-frozen index. `skills_list`
(L2) discovers enabled, platform-compatible skills, including skills omitted from L1.
`skill_view` (L3) loads full instructions by canonical name, exact categorized path,
or an unambiguous declared alias. Visibility is an offer-time control, not an access
or security boundary: existing disabled-skill, platform and project quarantine gates remain.

Legacy skills without catalog metadata remain globally visible. A skill can opt into
one of three visibility modes in `SKILL.md` frontmatter:

```yaml
metadata:
  hermes:
    visibility: profile
    profiles: [engineering]
    aliases: [legacy-build-guide]
```

- `global`: included in L1 by default.
- `profile`: included when at least one declared catalog profile is active.
- `on_demand`: omitted from L1 and automatic filesystem slash-command discovery;
  still discoverable through L2 and explicitly loadable through L3.

Select catalog profiles in the active Hermes home's `config.yaml`:

```yaml
skills:
  active_profiles: [engineering]
```

Catalog selectors are independent of Hermes runtime profiles. An empty selector list
includes only global skills. Trusted project-local skills with valid `profile` metadata
remain visible without activating their catalog profile. `on_demand` and malformed
project entries remain hidden but still claim their canonical identities, preventing a
lower-precedence copy from being advertised under a name that loads the hidden project copy.

Malformed metadata fails closed for L1; explicit canonical loads remain available and
report `metadata_valid: false`. Aliases do not create extra L1 rows or slash commands.
Alias/alias and alias/canonical collisions refuse to guess, even across source tiers;
use an exact categorized path. Existing source precedence, identical-copy checks and
same-tier categorized disambiguation still apply to canonical identifiers.

Use `skills_list(query="build", category="engineering")` for case-insensitive substring
search over names, aliases, descriptions and categories. Both filters compose; no result
pagination is needed to discover deferred skills. Selecting profiles changes future
catalog builds and automatic command discovery, not an already-cached conversation prompt.

## Prompt-cache families

On capable OpenAI-wire chat-completions and Responses endpoints, main requests derive a
bounded routing key from the effective wire model, API mode, tenant/profile/principal
isolation, reusable system prefix and complete emitted tool schemas. Tool mappings are
canonicalized but tool sequence order is preserved. The reusable prefix contains identity,
guidance, the frozen skills catalog and project context; memory and runtime metadata remain
in the volatile tail. Keys can therefore be reused across physical sessions with equivalent
prefixes without mixing principals or homes.

Unresolved identities or malformed family inputs keep the existing conversation-scoped
fallback. Unknown gateway principals never default to a shared owner identity; explicitly
local first-party surfaces may use their profile owner. Explicit caller keys, endpoint
opt-outs, xAI-specific routing, compression lineage and cache-parity fork scope rules retain
their existing contracts. Responses identity uses the normalized, overridden wire model,
not a picker alias. DEBUG diagnostics contain fingerprints, not raw prompt, home or principal
values. No requests or credentials are needed to derive a family key.

Stored system prompts are never rewritten to adopt this layout. Restore and keep-prompt
compression reconstruct the reusable prefix only when it exactly matches the stored bytes;
otherwise the original prompt is sent unchanged with the existing fallback routing.
