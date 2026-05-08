# Scheduling Algorithm

### `MatchGraph` class

represents the data in the Match model, but entirely in memory, and
with relations as actual references like a graph. References are:
- if team1 and team2 are not resolved yet and are the winner or loser
  of another match, that other match is a dependency of this one
- if refs are not resolved yet and any are the winner or loser of
  another match, that other match is a dependency of this one
- the previous match on the same field (as indicated by the
  previous_match column) is a dependency of this match
- any matches referenced by the skip condition. Note that the
  Match.get_skip_condition_dependencies returns a dict of direct and
  skip-condition dependencies; both should be used for the topological
  sort, but later, when getting the end time of dependencies, non
  direct dependencies should return an end time that is actually the
  start time of the match referenced in the `(skip-condition MATCH)`
  command.
- the latest (by nominal start time) match on each field whose nominal
  start time is before this match's nominal start time. 

JOIN matches with the same name are stored as a single node, not
multiple. They have the union of each one's dependencies.

There are two methods for getting dependencies:
1. `get_schedule_dependencies`
2. `get_direct_dependencies`

the latter is any dependency that is one link away.The former contains
only static/dynamic matches that have not been skipped. it will do a
graph search that terminates when it finds a static/dynamic match (ie,
it will search past any `BREAK`/`JOIN` matches).

The `Dependency` abstract class wraps a pointer to a
`MatchNode`. it hashes to the same thing as the node it points to, so it
can be used in equality checks. It adds a `get_time()` method which gets
the effective end time of that node. For most dependencies, this'll be
the end time of the wrapped match. But for matches which are dependent
through a `(skip-condition MATCH)` (as specified by the non-direct
group of dependencies from `Match.get_skip_condition_dependencies()`),
it should return the start time of the match.

there are two subclasses of Dependency:
- `startOfMatchDep`
- `endOfMatchDep`

```
PROCEDURE: WITH MATCH m {
	IF (m is COMPLETED or IN_PROGRESS or SKIPPED) {
		return
	}
	let nominal_start_if_skipped = Null()
	SWITCH schedule type of m {
		CASE STATIC {
			IF m is NOT_STARTED {
			  SET m TIME_FINALIZED
			}
		}
		CASE BREAK/JOIN {
			SET m.nominal_start_time = latest(END_TIMES m.get_direct_dependencies())
		}
		CASE SAFE {
			IF m is NOT_STARTED {
				SET m.nominal_start_time = \
					m.get_direct_dependencies()
					 .map(|x| 
					 	 IF (x is SKIPPED) {
					 	   (END_TIME x) + x.nominal_length
						 } ELSE {
							 END_TIME x
						 })
					 .latest();

				nominal_start_if_skipped = Some(
					m.get_direct_dependencies()
				   .map(|x| END_TIME x)
				   .latest()
				)
			}
		}
		CASE FAST {
			IF m is NOT_STARTED {
				SET m.nominal_start_time = \
				  m.get_direct_dependencies()
				   .map(|x| END_TIME x)
				   .latest()
			}
		}
	}

	IF ALL m.get_schedule_dependencies() ARE COMPLETED/SKIPPED {
		IF skip_cond {
			SET m SKIPPED
			m.nominal_start_time = nominal_start_if_skipped.or_default(m.nominal_start_time);
		} else {
			IF m is STATIC/SAFE/FAST { // ie, if this match is one people play in
				SET m READY_TO_START
			} else {
				SET m COMPLETED
			}
		}
	} ELSE IF (m is SAFE) AND (ALL m.get_schedule_dependencies() ARE IN_PROGRESS/COMPLETED/SKIPPED) {
		SET m TIME_FINALIZED
	}
}
```

### On Match Start/End

0. acquire lock on matches
1. set the match to COMPLETED or IN_PROGRESS as needed, and notate the relevant timestamps.
2. load match graph from db
3. topological sort.
4. in order from root to leaf nodes, perform PROCEDURE.
5. write data to db from graph
6. release lock


### On Match Create/Edit

same as on match start/end, but first set time_finalized on any matches which
should be finalized from the beginning.
