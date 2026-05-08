# `app/domain/` - domain enums

Domain enums separated from the models so that services, serializers,
and routes can import them without pulling in SQLAlchemy.

## `parse_enum`

The DB stores enum values as strings, so reading the column gives you a
`str`, not the enum member. `parse_enum` handles all the cases without
raising:

```python
from app.domain.enums import MatchStatus, parse_enum
from app.error_values import Some

match parse_enum(MatchStatus, getattr(match, "status", None)):
    case Some(MatchStatus.IN_PROGRESS):
        ...
    case Some(MatchStatus.COMPLETED):
        ...
    case _:
        # null or unrecognised - treat as NOT_STARTED
        ...
```

## Adding an enum value

1. Add the value to the `StrEnum` class in `enums.py`.
2. If any model column is typed `db.Enum(MyEnum)` and the DB is SQLite,
   you don't need a migration to widen the value set - SQLite stores
   enums as TEXT. (On other databases you'd need an `ALTER TYPE`.)
3. Update any pattern-match `case`s that should handle the new value.
4. Backfill any existing rows that should adopt the new value.
