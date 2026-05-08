# `app/domain/` - domain enums

Domain enums separated from the models so that services, serializers,
and routes can import them without pulling in SQLAlchemy.

## The enums

| Enum | Values | Stored as |
|------|--------|-----------|
| `MatchNoteTarget` | `TEAM1`, `TEAM2`, `MATCH`, `PLAYER` | the lowercase value (`"team1"`, ...) |
| `RegistrationStatus` | `PENDING_TEAM_APPROVAL`, `CONFIRMED`, `REJECTED`, `CANCELLED` | uppercase string |
| `TeamRegistrationStatus` | `CONFIRMED`, `CANCELLED` | uppercase string |
| `MatchStatus` | `NOT_STARTED`, `TIME_FINALIZED`, `READY_TO_START`, `IN_PROGRESS`, `COMPLETED`, `SKIPPED` | uppercase string |
| `ScheduleType` | `STATIC`, `SAFE`, `FAST`, `BREAK`, `JOIN` | uppercase string |
| `SetType` | `SETS`, `STONES` | uppercase string |
| `WinnerSide` | `TEAM1`, `TEAM2` | uppercase string |

All enums subclass `StrEnum`, so `MatchStatus.IN_PROGRESS == "IN_PROGRESS"`
is true.

## `MatchStatus`

The match lifecycle is the only enum complex enough to need explanation:

```
NOT_STARTED ─-> TIME_FINALIZED ─-> READY_TO_START ─-> IN_PROGRESS ─-> COMPLETED
                                                                  │
                                                                  └─-> SKIPPED (instead of starting)
```

- **`NOT_STARTED`** - initial state. The start time can still be pushed
  back by schedule recomputation.
- **`TIME_FINALIZED`** - the start time will not move further. The
  match is guaranteed not to be skipped.
- **`READY_TO_START`** - all ref and playing teams resolved; the game
  can start as soon as people show up.
- **`IN_PROGRESS`** - match started but not finished.
- **`COMPLETED`** - finished. Both `started_at` and `completed_time`
  are populated.
- **`SKIPPED`** - effectively completed; `started_at == completed_time`
  and equals the time the skip was applied.

## `ScheduleType`

- **`STATIC`** - fixed time, never recalculated automatically.
- **`SAFE`** - recalculate conservatively. Start time is finalised when
  the last dependency *starts*. Avoids cascading delays.
- **`FAST`** - recalculate aggressively. Start time is finalised when
  all dependencies *complete*. Schedules as early as possible.
- **`BREAK`** - a scheduled break (no match played).
- **`JOIN`** - a synchronisation point; waits for multiple preceding
  matches to complete before advancing.

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
