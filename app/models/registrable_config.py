"""RegistrableConfig model for shared registration settings."""

from __future__ import annotations

from app.models.base import db


class RegistrableConfig(db.Model):
    """
    Shared registration config for standalone tournaments and leagues.

    Standalone tournaments (league_id is null) have their own RegistrableConfig.
    League events use the league's RegistrableConfig.
    """

    __tablename__ = "registrable_configs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    team_reg_fee = db.Column(db.Float, default=0.0, nullable=False)
    player_reg_fee = db.Column(db.Float, default=0.0, nullable=False)
    payment_info = db.Column(db.Text)
    # Deprecated: use team_registration_open / player_registration_open instead.
    # Kept for backward compatibility and migration scripts.
    registration_open = db.Column(db.Boolean, default=False, nullable=False)
    # Separate toggles for team and player registration.
    team_registration_open = db.Column(db.Boolean, default=False, nullable=False)
    player_registration_open = db.Column(db.Boolean, default=False, nullable=False)
    terms_link = db.Column(db.String(500))
    n_max_teams = db.Column(db.Integer)
    max_team_size_roster = db.Column(db.Integer)
    max_team_size_field = db.Column(db.Integer)

    __table_args__ = (
        db.CheckConstraint("team_reg_fee >= 0", name="ck_registrable_config_team_reg_fee_nonneg"),
        db.CheckConstraint("player_reg_fee >= 0", name="ck_registrable_config_player_reg_fee_nonneg"),
    )
