"""SQLAlchemy models for individual players and teams."""

from __future__ import annotations

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.base import db
from app.models.constants import (
    AUTH_STRING_LEN,
    LONG_NAME_LEN,
    LONG_URL_LEN,
    PHONE_LEN,
    SHORT_NAME_LEN,
    USER_ID_LEN,
)


class Player(UserMixin, db.Model):
    """An individual player account.

    Players can log in with a password or via Google OAuth.  They may be
    Tournament Organisers (TOs) and can register for events independently
    or as part of a team.

    Attributes:
        id: Unique username / slug (primary key).
        name: Display name.
        pw_hash: Werkzeug password hash; ``None`` for OAuth-only accounts.
        google_id: Google OAuth subject identifier.
        email: Email address supplied by Google OAuth.
        phone: Optional contact phone number.
        profile_photo: Server-relative path to the uploaded profile image.
        bio: Free-text biography.
        location: Player's city or region.
    """

    __tablename__ = "players"

    id = db.Column(db.String(USER_ID_LEN), primary_key=True)
    name = db.Column(db.String(SHORT_NAME_LEN), nullable=False)
    pw_hash = db.Column(
        db.String(AUTH_STRING_LEN), nullable=True
    )  # Nullable for Google OAuth users
    google_id = db.Column(
        db.String(AUTH_STRING_LEN), unique=True, nullable=True
    )  # Google OAuth ID
    email = db.Column(db.String(AUTH_STRING_LEN), nullable=True)  # Email from Google
    phone = db.Column(db.String(PHONE_LEN))
    profile_photo = db.Column(db.String(AUTH_STRING_LEN))
    bio = db.Column(db.Text)
    location = db.Column(db.String(SHORT_NAME_LEN))

    def set_password(self, password: str) -> None:
        """Hash *password* and store it in :attr:`pw_hash`.

        Args:
            password: The plaintext password to store securely.
        """
        self.pw_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify *password* against the stored hash.

        Args:
            password: The plaintext password to check.

        Returns:
            ``True`` if the password matches the stored hash, ``False`` if
            :attr:`pw_hash` is ``None`` (OAuth-only account) or the hash does
            not match.
        """
        if not self.pw_hash:
            return False
        return check_password_hash(self.pw_hash, password)


class Team(UserMixin, db.Model):
    """A team account that can register for events.

    Teams can log in with a password or via Google OAuth, just like players.
    A team's roster is determined by :class:`~app.models.registration.PlayerRegistration`
    records linking players to the team for each event.

    Attributes:
        id: Unique team username / slug (primary key).
        name: Display name of the team.
        pw_hash: Werkzeug password hash; ``None`` for OAuth-only accounts.
        google_id: Google OAuth subject identifier.
        phone: Optional contact phone number.
        email: Email address (may come from Google OAuth).
        icon: Base64-encoded team icon image.
        profile_photo: Server-relative path to the uploaded profile photo.
        socials: Free-text social media links.
        website: Team website URL.
        location: Team's city or region.
        about: Free-text team biography / description.
    """

    __tablename__ = "teams"

    id = db.Column(db.String(USER_ID_LEN), primary_key=True)
    name = db.Column(db.String(SHORT_NAME_LEN), nullable=False)
    pw_hash = db.Column(
        db.String(AUTH_STRING_LEN), nullable=True
    )  # Nullable for Google OAuth users
    google_id = db.Column(
        db.String(AUTH_STRING_LEN), unique=True, nullable=True
    )  # Google OAuth ID
    phone = db.Column(db.String(PHONE_LEN))
    email = db.Column(
        db.String(AUTH_STRING_LEN), nullable=True
    )  # Updated to match Player, can be from Google
    icon = db.Column(db.Text)  # base64 image
    profile_photo = db.Column(db.String(AUTH_STRING_LEN))  # Path to uploaded photo
    socials = db.Column(db.Text)
    website = db.Column(db.String(LONG_NAME_LEN))
    location = db.Column(db.String(SHORT_NAME_LEN))
    about = db.Column(db.Text)

    def set_password(self, password: str) -> None:
        """Hash *password* and store it in :attr:`pw_hash`.

        Args:
            password: The plaintext password to store securely.
        """
        self.pw_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify *password* against the stored hash.

        Args:
            password: The plaintext password to check.

        Returns:
            ``True`` if the password matches the stored hash, ``False`` if
            :attr:`pw_hash` is ``None`` (OAuth-only account) or the hash does
            not match.
        """
        if not self.pw_hash:
            return False
        return check_password_hash(self.pw_hash, password)
