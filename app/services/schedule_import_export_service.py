"""
Schedule import/export service for tags, fields, and matches.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.error_values import Err, Ok, Result, allow_Q, option
from app.exceptions import ArctosError, NotFoundError, ValidationError
from app.serializers.match_schedule_serializer import MatchScheduleSerializer
from app.utils.toml_helpers import parse_toml_schedule, write_toml_schedule

if TYPE_CHECKING:  # pragma: no cover
    from models import Field, Match, Tag


@dataclass(frozen=True)
class ImportResult:
    """Result of an import operation."""
    tags_created: int = 0
    tags_updated: int = 0
    fields_created: int = 0
    fields_updated: int = 0
    matches_created: int = 0
    matches_updated: int = 0
    errors: list[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            object.__setattr__(self, "errors", [])


@dataclass(frozen=True)
class ScheduleImportExportService:
    """Service for importing and exporting tournament schedules."""
    
    # ----------------------------
    # Internal helpers
    # ----------------------------

    @staticmethod
    def _validate_semantics(
        tags_data: list[dict],
        fields_data: list[dict],
        matches_data: list[dict],
    ) -> list[str]:
        """
        Perform higher-level semantic validation on the uploaded schedule.

        - Ensure match.field (if set) refers to a field listed in [[fields]].
        - Ensure team1_initial / team2_initial / refs_initial use only:
          - explicit team id: any non-empty string that is not a special
            'tag::' or match reference pattern
          - tag reference: 'tag::TAG_NAME' where TAG_NAME exists in [[tags]]
          - match reference: "[match name]::winner" or "[match name]::loser"
            where match name exists in the uploaded [[matches]] section.
        """
        errors: list[str] = []

        # Build lookup sets from uploaded data
        field_names: set[str] = set()
        for f in fields_data:
            name = str(f.get("name", "")).strip()
            if name:
                field_names.add(name)

        tag_names: set[str] = set()
        for t in tags_data:
            name = str(t.get("name", "")).strip()
            if name:
                tag_names.add(name)

        match_names: set[str] = set()
        for m in matches_data:
            name = str(m.get("name", "")).strip()
            if name:
                match_names.add(name)

        def _validate_initial_token(token: str, context: str) -> None:
            """
            Validate a single initial token.

            Allowed forms:
            - explicit team id: any non-empty string that is not a special
              'tag::' or match reference pattern
            - tag reference: 'tag::TAG_NAME' where TAG_NAME exists in tags_data
            - match reference: '[match name]::winner' or '[match name]::loser'
              where match name exists in uploaded matches.
            """
            tok = (token or "").strip()
            if not tok:
                return

            # Tag reference: tag::TAG_NAME
            if tok.lower().startswith("tag::"):
                tag_name = tok[5:].strip()
                if not tag_name:
                    errors.append(f"{context}: missing tag name in reference '{tok}'")
                    return
                if tag_name not in tag_names:
                    errors.append(
                        f"{context}: referenced tag '{tag_name}' not found in [[tags]] section"
                    )
                return

            base, sep, suffix = tok.partition("::")
            if not sep:
                # Plain explicit team id (no special validation).
                return

            base = base.strip()
            suffix = suffix.strip().lower()

            if suffix not in ("winner", "loser"):
                errors.append(
                    f"{context}: invalid reference suffix '{suffix}' in '{tok}' "
                    "(must be 'winner' or 'loser')"
                )
                return

            if not base:
                errors.append(f"{context}: missing match name in reference '{tok}'")
                return

            if base not in match_names:
                errors.append(
                    f"{context}: referenced match '{base}' not found in uploaded matches"
                )

        # Validate each match entry
        for m in matches_data:
            match_name = str(m.get("name", "")).strip() or "<unnamed match>"

            # 1) field must exist in [[fields]] if provided
            field_val = str(m.get("field", "")).strip()
            if field_val and field_val not in field_names:
                errors.append(
                    f"Match '{match_name}': field '{field_val}' not found in [[fields]] section"
                )

            # 2) team1_initial / team2_initial
            t1_init = str(m.get("team1_initial", "")).strip()
            if t1_init:
                _validate_initial_token(t1_init, f"Match '{match_name}' team1_initial")

            t2_init = str(m.get("team2_initial", "")).strip()
            if t2_init:
                _validate_initial_token(t2_init, f"Match '{match_name}' team2_initial")

            # 3) refs_initial: comma-separated list of tokens
            refs_init = str(m.get("refs_initial", "")).strip()
            if refs_init:
                for part in refs_init.split(","):
                    part_tok = part.strip()
                    if not part_tok:
                        continue
                    _validate_initial_token(
                        part_tok, f"Match '{match_name}' refs_initial"
                    )

        return errors

    @staticmethod
    @allow_Q
    def export_schedule(tournament_url: str) -> Result[str, ArctosError]:
        """
        Export schedule (tags, fields, matches) to TOML string.
        
        Args:
            tournament_url: Tournament to export
        
        Returns:
            Result containing TOML string
        """
        from models import Field, Match, Tag, db
        
        # Verify tournament exists
        from models import Tournament
        tournament = Tournament.query.filter_by(url=tournament_url).first()
        if not tournament:
            return Err(NotFoundError(f"Tournament not found: {tournament_url}"))
        
        # Fetch all tags, fields, and matches
        tags = Tag.query.filter_by(event=tournament_url).all()
        fields = Field.query.filter_by(event=tournament_url).all()
        matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
        
        # Serialize to dicts
        tag_dicts = [MatchScheduleSerializer.tag_to_dict(tag) for tag in tags]
        field_dicts = [MatchScheduleSerializer.field_to_dict(field) for field in fields]
        match_dicts = [MatchScheduleSerializer.match_to_dict(match) for match in matches]
        
        # Generate TOML
        metadata = {
            "exported_from": tournament_url,
            "export_date": datetime.now().isoformat(),
            "tags_count": len(tag_dicts),
            "fields_count": len(field_dicts),
            "matches_count": len(match_dicts),
        }
        
        toml_content = write_toml_schedule(
            event=tournament_url,
            tags=tag_dicts,
            fields=field_dicts,
            matches=match_dicts,
            metadata=metadata,
        )
        
        return Ok(toml_content)
    
    @staticmethod
    @allow_Q
    def import_schedule(
        tournament_url: str,
        toml_content: str,
        *,
        dry_run: bool = False,
    ) -> Result[ImportResult, ArctosError]:
        """
        Import schedule from TOML string.
        
        Handles both same-tournament (update) and different-tournament (create) scenarios.
        
        Args:
            tournament_url: Target tournament URL
            toml_content: TOML schedule content
            dry_run: If True, validate only without making changes
        
        Returns:
            Result containing ImportResult with counts and errors
        """
        from models import Field, Match, Tag, db
        
        # Parse TOML
        parsed = parse_toml_schedule(toml_content).Q()
        source_event = parsed["event"]
        tags_data = parsed["tags"]
        fields_data = parsed["fields"]
        matches_data = parsed["matches"]
        
        # Verify target tournament exists
        from models import Tournament
        tournament = Tournament.query.filter_by(url=tournament_url).first()
        if not tournament:
            return Err(NotFoundError(f"Tournament not found: {tournament_url}"))
        
        is_same_tournament = source_event == tournament_url
        
        tags_created = 0
        tags_updated = 0
        fields_created = 0
        fields_updated = 0
        matches_created = 0
        matches_updated = 0
        errors: list[str] = []
        
        # High-level semantic validation shared by dry-run and real import
        semantic_errors = ScheduleImportExportService._validate_semantics(
            tags_data, fields_data, matches_data
        )

        if dry_run:
            # Validation only - check that data is structurally valid
            for tag_data in tags_data:
                res = MatchScheduleSerializer.tag_from_dict(tag_data, tournament_url)
                if isinstance(res, Err):
                    errors.append(f"Tag validation error: {res.value.message}")
            
            for field_data in fields_data:
                res = MatchScheduleSerializer.field_from_dict(field_data, tournament_url)
                if isinstance(res, Err):
                    errors.append(f"Field validation error: {res.value.message}")
            
            for match_data in matches_data:
                res = MatchScheduleSerializer.match_from_dict(match_data, tournament_url)
                if isinstance(res, Err):
                    errors.append(f"Match validation error: {res.value.message}")

            # Add semantic validation errors
            errors.extend(semantic_errors)

            if errors:
                return Err(ValidationError(f"Validation failed with {len(errors)} errors"))
            
            return Ok(ImportResult(
                tags_created=0,
                tags_updated=0,
                fields_created=0,
                fields_updated=0,
                matches_created=0,
                matches_updated=0,
                errors=errors,
            ))
        # For real imports, abort early if semantic validation failed
        if semantic_errors:
            return Err(
                ValidationError(f"Validation failed with {len(semantic_errors)} errors")
            )

        # Actual import
        try:
            # Keep track of which objects are present in the uploaded file for this tournament.
            # Anything NOT in these sets will be deleted at the end of a successful import.
            kept_tag_names: set[str] = set()
            kept_field_names: set[str] = set()
            kept_match_uuids: set[str] = set()

            # Build UUID mapping for matches (old_uuid -> new_uuid for different tournament)
            match_uuid_map: dict[str, str] = {}  # old_uuid -> new_uuid
            match_name_to_uuid: dict[str, str] = {}  # name -> uuid (for resolving relationships)
            
            # Pre-build UUID map for different tournament
            if not is_same_tournament:
                for match_data in matches_data:
                    old_uuid = match_data.get("uuid", "")
                    if old_uuid:
                        new_uuid = str(uuid.uuid4())
                        match_uuid_map[old_uuid] = new_uuid
            
            # Import tags
            for tag_data in tags_data:
                tag_res = MatchScheduleSerializer.tag_from_dict(tag_data, tournament_url).Q()
                tag_dict = tag_res
                
                # Track by name; IDs may differ across tournaments and inserts.
                if "name" in tag_dict and tag_dict["name"]:
                    kept_tag_names.add(tag_dict["name"])

                if is_same_tournament and "id" in tag_dict:
                    # Same tournament: update by ID
                    tag = Tag.query.filter_by(id=tag_dict["id"], event=tournament_url).first()
                    if tag:
                        tag.name = tag_dict["name"]
                        tags_updated += 1
                    else:
                        # ID doesn't exist, create new (don't include id in creation)
                        create_dict = {k: v for k, v in tag_dict.items() if k != "id"}
                        tag = Tag(**create_dict)
                        db.session.add(tag)
                        tags_created += 1
                else:
                    # Different tournament: always create new (don't include id)
                    create_dict = {k: v for k, v in tag_dict.items() if k != "id"}
                    tag = Tag(**create_dict)
                    db.session.add(tag)
                    tags_created += 1
            
            # Import fields
            for field_data in fields_data:
                field_res = MatchScheduleSerializer.field_from_dict(field_data, tournament_url).Q()
                field_dict = field_res
                
                # Track by name; IDs may differ across tournaments and inserts.
                if "name" in field_dict and field_dict["name"]:
                    kept_field_names.add(field_dict["name"])

                if is_same_tournament and "id" in field_dict:
                    # Same tournament: update by ID
                    field = Field.query.filter_by(id=field_dict["id"], event=tournament_url).first()
                    if field:
                        field.name = field_dict["name"]
                        field.camera = field_dict["camera"]
                        fields_updated += 1
                    else:
                        # ID doesn't exist, create new (don't include id in creation)
                        create_dict = {k: v for k, v in field_dict.items() if k != "id"}
                        field = Field(**create_dict)
                        db.session.add(field)
                        fields_created += 1
                else:
                    # Different tournament: always create new (don't include id)
                    create_dict = {k: v for k, v in field_dict.items() if k != "id"}
                    field = Field(**create_dict)
                    db.session.add(field)
                    fields_created += 1
            
            db.session.flush()  # Flush to get IDs for fields
            
            # Import matches - first pass: create/update without relationships
            for match_data in matches_data:
                # Prepare match data with new UUID if different tournament
                old_uuid = match_data.get("uuid", "")
                if not is_same_tournament and old_uuid:
                    # Use pre-generated UUID from map
                    new_uuid = match_uuid_map.get(old_uuid, str(uuid.uuid4()))
                    match_data = {**match_data, "uuid": new_uuid}
                
                match_res = MatchScheduleSerializer.match_from_dict(
                    match_data,
                    tournament_url,
                    match_uuid_map=match_uuid_map if not is_same_tournament else None,
                ).Q()
                match_dict = match_res
                
                match_name = match_dict["name"]
                
                if is_same_tournament and "uuid" in match_dict:
                    # Same tournament: update by UUID
                    match = Match.query.filter_by(uuid=match_dict["uuid"], event=tournament_url).first()
                    if match:
                        # Update fields (excluding relationships which we'll handle in second pass)
                        for key, value in match_dict.items():
                            if key not in ("uuid", "event", "previous_match", "next_match"):
                                setattr(match, key, value)
                        match_name_to_uuid[match_name] = match.uuid
                        kept_match_uuids.add(match.uuid)
                        matches_updated += 1
                    else:
                        # UUID doesn't exist, create new
                        create_dict = {k: v for k, v in match_dict.items() if k not in ("previous_match", "next_match")}
                        match = Match(**create_dict)
                        db.session.add(match)
                        match_name_to_uuid[match_name] = match.uuid
                        kept_match_uuids.add(match.uuid)
                        matches_created += 1
                else:
                    # Different tournament: always create new
                    create_dict = {k: v for k, v in match_dict.items() if k not in ("previous_match", "next_match")}
                    match = Match(**create_dict)
                    db.session.add(match)
                    match_name_to_uuid[match_name] = match.uuid
                    kept_match_uuids.add(match.uuid)
                    matches_created += 1
            
            db.session.flush()  # Flush to get UUIDs for matches
            
            # Second pass: resolve relationships (previous_match/next_match)
            for match_data in matches_data:
                old_uuid = match_data.get("uuid", "")
                match_name = match_data.get("name", "")
                
                # Find the match we just created/updated
                if is_same_tournament and old_uuid:
                    match = Match.query.filter_by(uuid=old_uuid, event=tournament_url).first()
                else:
                    # Different tournament: use new UUID from map
                    if old_uuid and old_uuid in match_uuid_map:
                        new_uuid = match_uuid_map[old_uuid]
                        match = Match.query.filter_by(uuid=new_uuid, event=tournament_url).first()
                    else:
                        match = Match.query.filter_by(name=match_name, event=tournament_url).first()
                
                if not match:
                    continue
                
                # Resolve previous_match
                if "previous_match" in match_data and match_data["previous_match"]:
                    prev_old_uuid = str(match_data["previous_match"]).strip()
                    if prev_old_uuid:
                        if is_same_tournament:
                            # Use UUID directly
                            prev_match = Match.query.filter_by(uuid=prev_old_uuid, event=tournament_url).first()
                            if prev_match:
                                match.previous_match = prev_match.uuid
                        else:
                            # Map old UUID to new UUID
                            if prev_old_uuid in match_uuid_map:
                                new_prev_uuid = match_uuid_map[prev_old_uuid]
                                prev_match = Match.query.filter_by(uuid=new_prev_uuid, event=tournament_url).first()
                                if prev_match:
                                    match.previous_match = prev_match.uuid
                
                # Resolve next_match
                if "next_match" in match_data and match_data["next_match"]:
                    next_old_uuid = str(match_data["next_match"]).strip()
                    if next_old_uuid:
                        if is_same_tournament:
                            # Use UUID directly
                            next_match = Match.query.filter_by(uuid=next_old_uuid, event=tournament_url).first()
                            if next_match:
                                match.next_match = next_match.uuid
                        else:
                            # Map old UUID to new UUID
                            if next_old_uuid in match_uuid_map:
                                new_next_uuid = match_uuid_map[next_old_uuid]
                                next_match = Match.query.filter_by(uuid=new_next_uuid, event=tournament_url).first()
                                if next_match:
                                    match.next_match = next_match.uuid

            # Delete any tags, fields, or matches for this tournament that are
            # NOT present in the uploaded file. This makes the uploaded schedule
            # authoritative for these three tables.
            # Tags: match by name within this tournament.
            if kept_tag_names:
                Tag.query.filter_by(event=tournament_url).filter(~Tag.name.in_(kept_tag_names)).delete(synchronize_session=False)
            else:
                # No tags in file -> delete all tags for this event
                Tag.query.filter_by(event=tournament_url).delete(synchronize_session=False)

            # Fields: match by name within this tournament.
            if kept_field_names:
                Field.query.filter_by(event=tournament_url).filter(~Field.name.in_(kept_field_names)).delete(synchronize_session=False)
            else:
                # No fields in file -> delete all fields for this event
                Field.query.filter_by(event=tournament_url).delete(synchronize_session=False)

            # Matches: match by UUID within this tournament.
            if kept_match_uuids:
                Match.query.filter_by(event=tournament_url).filter(~Match.uuid.in_(kept_match_uuids)).delete(synchronize_session=False)
            else:
                # No matches in file -> delete all matches for this event
                Match.query.filter_by(event=tournament_url).delete(synchronize_session=False)

            db.session.commit()
            
            result = ImportResult(
                tags_created=tags_created,
                tags_updated=tags_updated,
                fields_created=fields_created,
                fields_updated=fields_updated,
                matches_created=matches_created,
                matches_updated=matches_updated,
                errors=errors,
            )
            
            return Ok(result)
        
        except Exception as e:
            db.session.rollback()
            return Err(ValidationError(f"Import failed: {str(e)}"))

