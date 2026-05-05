# `app/serializers/` - DB row -> JSON shape

Serializers convert ORM instances into the JSON shape the SPA expects.
They live in their own package (rather than as methods on the models)
so they can resolve cross-cutting display details - registration
pseudonyms, head-ref permissions - without bloating the model classes.

## What's in here

| File | What it does |
|------|--------------|
| `match_note_serializer.py` | Serialises a `MatchNote` to the API shape. Resolves the author and target player's display names; for `team1`/`team2`-target notes, fills in the `team_id` from the parent match. |
| `match_schedule_serializer.py` | Serialises tags, fields, and matches to TOML-compatible dicts (and back). Used by the schedule import/export service. Omits empty / null keys to keep the TOML output tidy. |

## Pattern

Each serialiser is a `@dataclass(frozen=True)` namespace with
`@staticmethod` `to_dict` / `to_*` methods:

```python
@dataclass(frozen=True)
class MatchNoteSerializer:
    @staticmethod
    def to_dict(note, tournament_url: str, match=None) -> dict[str, Any]:
        ...
```

That mirrors the service-layer pattern. There's no instance state.

## When to add a serialiser

Add one when:

- You're returning the same model from more than one route and copying
  a `dict(...)` literal across files.
- The serialised shape has to resolve external details (display names,
  permissions, computed fields) that the model doesn't know about.

If you only need to convert a single model in a single endpoint, an
inline dict comprehension in the route is fine.
