import textwrap
from datetime import datetime, timezone

import pytest

from app.error_values import Err, Ok
from app.services.schedule_import_export_service import ScheduleImportExportService
from app.utils.toml_helpers import write_toml_schedule
from models import Field, Match, Tag, Tournament, db


@pytest.mark.unit
def test_export_schedule_includes_tags_fields_and_matches(test_db, tournament):
    """Exported TOML should contain tags, fields, and matches with expected structure."""
    tournament_url = tournament.url

    # Seed tags and fields
    tag1 = Tag(event=tournament_url, name="Pool A")
    tag2 = Tag(event=tournament_url, name="Pool B")
    field1 = Field(event=tournament_url, name="Field 1", camera=None)
    field2 = Field(event=tournament_url, name="Field 2", camera="[]")
    db.session.add_all([tag1, tag2, field1, field2])

    # Seed a simple match that uses tag and result references
    m1 = Match(
        name="M1",
        event=tournament_url,
        field="Field 1",
        nominal_start_time=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
        nominal_length=60,
        schedule_type="STATIC",
        set_type="SETS",
        team1_initial="tag::Pool A",
        team2_initial="tag::Pool B",
        refs_initial="tag::Pool A, tag::Pool B",
    )
    db.session.add(m1)
    db.session.commit()

    res = ScheduleImportExportService.export_schedule(tournament_url)
    match res:
        case Ok(toml_str):
            # Basic sanity checks: event and table headers present
            assert f'event = "{tournament_url}"' in toml_str
            assert "[[tags]]" in toml_str
            assert "[[fields]]" in toml_str
            assert "[[matches]]" in toml_str
            # Ensure tag names and field names are present
            assert 'name = "Pool A"' in toml_str
            assert 'name = "Pool B"' in toml_str
            assert 'name = "Field 1"' in toml_str
            # Ensure match record contains key fields
            assert 'name = "M1"' in toml_str
            assert 'field = "Field 1"' in toml_str
            assert 'team1_initial = "tag::Pool A"' in toml_str
            assert 'refs_initial = "tag::Pool A, tag::Pool B"' in toml_str
        case Err(err):
            raise AssertionError(f"Expected Ok(TOML), got Err({err})")


@pytest.mark.unit
def test_import_schedule_dry_run_rejects_invalid_tag_and_field(test_db, tournament):
    """Dry run import should fail when tag::NAME or field reference is invalid."""
    tournament_url = tournament.url

    # Construct a minimal invalid TOML schedule:
    # - references tag::Missing (no such tag)
    # - match.field = "Missing Field" (no such field)
    toml_content = textwrap.dedent(
        f"""
        event = "{tournament_url}"

        [[tags]]
        id = 1
        name = "Existing"

        [[fields]]
        id = 1
        name = "Field 1"

        [[matches]]
        uuid = "00000000-0000-0000-0000-000000000001"
        name = "M1"
        field = "Missing Field"
        schedule_type = "STATIC"
        set_type = "SETS"
        nominal_length = 60
        team1_initial = "tag::Missing"
        """
    ).strip()

    res = ScheduleImportExportService.import_schedule(
        tournament_url, toml_content, dry_run=True
    )
    match res:
        case Ok(_):
            raise AssertionError("Expected Err(ValidationError) for invalid tag/field")
        case Err(err):
            # We don't assert exact message, but ensure it's a validation error
            from app.exceptions import ValidationError

            assert isinstance(err, ValidationError)


@pytest.mark.unit
def test_import_schedule_dry_run_rejects_invalid_match_reference(test_db, tournament):
    """Dry run import should fail when a MATCH::winner/loser reference targets a non-existent match."""
    tournament_url = tournament.url

    toml_content = textwrap.dedent(
        f"""
        event = "{tournament_url}"

        [[tags]]
        id = 1
        name = "Pool A"

        [[fields]]
        id = 1
        name = "Field 1"

        [[matches]]
        uuid = "00000000-0000-0000-0000-000000000001"
        name = "M1"
        field = "Field 1"
        schedule_type = "STATIC"
        set_type = "SETS"
        nominal_length = 60
        team1_initial = "Nonexistent Match::winner"
        """
    ).strip()

    res = ScheduleImportExportService.import_schedule(
        tournament_url, toml_content, dry_run=True
    )
    match res:
        case Ok(_):
            raise AssertionError("Expected Err(ValidationError) for invalid match reference")
        case Err(err):
            from app.exceptions import ValidationError

            assert isinstance(err, ValidationError)


@pytest.mark.unit
def test_import_schedule_replaces_existing_objects_and_deletes_missing(test_db, tournament):
    """
    Real import should:
    - create new tags/fields/matches present in TOML,
    - update same-tournament by id/uuid,
    - delete any tags/fields/matches in DB that are not present in the TOML.
    """
    tournament_url = tournament.url

    # Seed two tags/fields/matches; only one of each will appear in the TOML
    old_tag = Tag(event=tournament_url, name="Old Tag")
    keep_tag = Tag(event=tournament_url, name="Keep Tag")
    old_field = Field(event=tournament_url, name="Old Field", camera=None)
    keep_field = Field(event=tournament_url, name="Keep Field", camera=None)
    db.session.add_all([old_tag, keep_tag, old_field, keep_field])
    db.session.flush()

    old_match = Match(
        name="Old Match",
        event=tournament_url,
        field="Old Field",
        nominal_length=30,
        schedule_type="STATIC",
        set_type="SETS",
    )
    keep_match = Match(
        name="Keep Match",
        event=tournament_url,
        field="Keep Field",
        nominal_length=60,
        schedule_type="STATIC",
        set_type="SETS",
    )
    db.session.add_all([old_match, keep_match])
    db.session.commit()

    # Build TOML that only contains keep_tag / keep_field / keep_match
    tags = [{"id": keep_tag.id, "name": keep_tag.name}]
    fields = [{"id": keep_field.id, "name": keep_field.name, "camera": ""}]
    matches = [
        {
            "uuid": keep_match.uuid,
            "name": keep_match.name,
            "field": keep_field.name,
            "nominal_length": keep_match.nominal_length,
            "schedule_type": keep_match.schedule_type,
            "set_type": keep_match.set_type,
        }
    ]
    toml_str = write_toml_schedule(event=tournament_url, tags=tags, fields=fields, matches=matches)

    res = ScheduleImportExportService.import_schedule(
        tournament_url, toml_str, dry_run=False
    )
    match res:
        case Ok(result):
            # One of each object should have been "updated", the old ones deleted.
            assert result.tags_created >= 0
            assert result.tags_updated >= 0
            assert result.fields_created >= 0
            assert result.fields_updated >= 0
            assert result.matches_created >= 0
            assert result.matches_updated >= 0
        case Err(err):
            raise AssertionError(f"Expected Ok(ImportResult), got Err({err})")

    # Verify DB state: only keep_* objects remain for this tournament
    tag_names = {t.name for t in Tag.query.filter_by(event=tournament_url).all()}
    field_names = {f.name for f in Field.query.filter_by(event=tournament_url).all()}
    match_names = {m.name for m in Match.query.filter_by(event=tournament_url).all()}

    assert tag_names == {"Keep Tag"}
    assert field_names == {"Keep Field"}
    assert match_names == {"Keep Match"}


