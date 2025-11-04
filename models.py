from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import uuid
from sqlalchemy.orm import foreign

# This will be imported from app.py
db = SQLAlchemy()

def init_db(database):
    global db
    db = database

class Player(UserMixin, db.Model):
    __tablename__ = 'players'
    
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    pw_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
    profile_photo = db.Column(db.String(255))
    bio = db.Column(db.Text)
    location = db.Column(db.String(100))  # Path to uploaded photo
    
    def set_password(self, password):
        self.pw_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.pw_hash, password)

class Team(UserMixin, db.Model):
    __tablename__ = 'teams'
    
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    pw_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    icon = db.Column(db.Text)  # base64 image
    profile_photo = db.Column(db.String(255))  # Path to uploaded photo
    socials = db.Column(db.Text)
    website = db.Column(db.String(200))
    location = db.Column(db.String(100))
    about = db.Column(db.Text)
    
    def set_password(self, password):
        self.pw_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.pw_hash, password)

class Injury(db.Model):
    __tablename__ = 'injuries'
    
    id = db.Column(db.Integer, primary_key=True)
    player = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
    show = db.Column(db.Boolean, default=True)
    active = db.Column(db.Boolean, default=True)

class Tournament(db.Model):
    __tablename__ = 'tournaments'
    
    url = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(200))
    num_fields = db.Column(db.Integer, default=1)
    n_max_teams = db.Column(db.Integer)
    max_team_size_roster = db.Column(db.Integer)  # Maximum players on team roster
    max_team_size_field = db.Column(db.Integer)   # Maximum players on field at once
    max_field_size = db.Column(db.Integer)
    team_reg_fee = db.Column(db.Float, default=0.0)
    player_reg_fee = db.Column(db.Float, default=0.0)
    payment_info = db.Column(db.Text)
    published = db.Column(db.Boolean, default=False)
    schedule_published = db.Column(db.Boolean, default=False)
    registration_open = db.Column(db.Boolean, default=False)
    about = db.Column(db.Text)
    terms_link = db.Column(db.String(500))
    head_refs = db.Column(db.Text)  # comma-separated player IDs

class TO(db.Model):
    __tablename__ = 'tos'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)  # Player or Team ID
    user_type = db.Column(db.String(10), nullable=False)  # 'player' or 'team'
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)

class TeamRegistration(db.Model):
    __tablename__ = 'team_registrations'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey('teams.id'), nullable=False)
    pseudonym = db.Column(db.String(100), nullable=False)  # Team name for this tournament
    status = db.Column(db.String(20), default='CONFIRMED')  # CONFIRMED, CANCELLED
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Payment fields
    paid = db.Column(db.Boolean, default=False)
    amount_paid = db.Column(db.Float, default=0.0)
    paid_at = db.Column(db.DateTime, nullable=True)
    payment_method = db.Column(db.String(50))  # e.g., cash, check, venmo, stripe
    payment_reference = db.Column(db.String(100))  # txn id, check #, etc
    payment_notes = db.Column(db.Text)

class PlayerRegistration(db.Model):
    __tablename__ = 'player_registrations'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    player = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey('teams.id'), nullable=True)  # null for unattached
    jersey_number = db.Column(db.String(10))
    jersey_name = db.Column(db.String(100))  # Player name for this tournament
    status = db.Column(db.String(20), default='PENDING_TEAM_APPROVAL')  # PENDING_TEAM_APPROVAL, CONFIRMED, REJECTED
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Payment fields
    paid = db.Column(db.Boolean, default=False)
    amount_paid = db.Column(db.Float, default=0.0)
    paid_at = db.Column(db.DateTime, nullable=True)
    payment_method = db.Column(db.String(50))
    payment_reference = db.Column(db.String(100))
    payment_notes = db.Column(db.Text)

class TeamInvitation(db.Model):
    __tablename__ = 'team_invitations'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey('teams.id'), nullable=False)
    player = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=False)
    status = db.Column(db.String(20), default='PENDING')  # PENDING, ACCEPTED, DECLINED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Field(db.Model):
    __tablename__ = 'fields'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    camera = db.Column(db.String(200))

class Tag(db.Model):
    __tablename__ = 'tags'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    name = db.Column(db.String(50), nullable=False)

class Match(db.Model):
    __tablename__ = 'matches'
    
    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    team1 = db.Column(db.String(50), db.ForeignKey('teams.id'))
    team2 = db.Column(db.String(50), db.ForeignKey('teams.id'))
    team1_initial = db.Column(db.String(200))
    team2_initial = db.Column(db.String(200))
    refs = db.Column(db.Text)  # comma separated team ids
    refs_initial = db.Column(db.Text)
    field = db.Column(db.String(100))
    nominal_start_time = db.Column(db.DateTime)
    confirmed_start_time = db.Column(db.DateTime)
    completed_time = db.Column(db.DateTime)
    nominal_length = db.Column(db.Integer)  # minutes
    type = db.Column(db.String(20), default='SETS')  # SETS, STONES
    nsets = db.Column(db.Integer)
    nstonesperset = db.Column(db.Integer)
    status = db.Column(db.String(20), default='NOT_STARTED')  # NOT_STARTED, IN_PROGRESS, COMPLETED
    gamestate = db.Column(db.Text)
    dynamic = db.Column(db.Boolean, default=True)  # True for dynamic, False for static scheduling
    previous_match = db.Column(db.String(36), db.ForeignKey('matches.uuid'), nullable=True)
    next_match = db.Column(db.String(36), db.ForeignKey('matches.uuid'), nullable=True)
    
    # Relationships
    previous_match_obj = db.relationship('Match', foreign_keys=[previous_match], remote_side=[uuid], post_update=True, backref='previous_of')
    next_match_obj = db.relationship('Match', foreign_keys=[next_match], remote_side=[uuid], post_update=True, backref='next_of')
    team1_registration = db.relationship('TeamRegistration', 
                                       primaryjoin='and_(Match.team1 == foreign(TeamRegistration.team), Match.event == TeamRegistration.event)',
                                       uselist=False)
    team2_registration = db.relationship('TeamRegistration',
                                       primaryjoin='and_(Match.team2 == foreign(TeamRegistration.team), Match.event == TeamRegistration.event)',
                                       uselist=False)

class Point(db.Model):
    __tablename__ = 'points'
    
    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    match = db.Column(db.String(36), db.ForeignKey('matches.uuid'), nullable=False)
    winner = db.Column(db.String(10))  # TEAM1, TEAM2
    rerolled = db.Column(db.Boolean, default=False)
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
    end_stamp = db.Column(db.DateTime)
    footage = db.Column(db.String(500))
    length = db.Column(db.Interval)
    nstones = db.Column(db.Integer)
    rerollreason = db.Column(db.Text)
    set_number = db.Column(db.Integer, default=1)
    notes = db.Column(db.Text)

class MatchNote(db.Model):
    __tablename__ = 'match_notes'
    
    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    match = db.Column(db.String(36), db.ForeignKey('matches.uuid'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    target = db.Column(db.String(50))  # 'TEAM1', 'TEAM2', 'MATCH', or player name
    created_by = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Optional link to a specific player
    player_id = db.Column(db.String(50), db.ForeignKey('players.id'))
    # Optional link to a specific point
    point_id = db.Column(db.String(36), db.ForeignKey('points.uuid'))
    
    # Relationships
    match_obj = db.relationship('Match', backref='match_notes')
    creator = db.relationship('Player', foreign_keys=[created_by])
    player = db.relationship('Player', foreign_keys=[player_id])
    point_obj = db.relationship('Point', foreign_keys=[point_id], backref='point_notes')

class HeadRef(db.Model):
    __tablename__ = 'headrefs'
    
    id = db.Column(db.Integer, primary_key=True)
    player = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=False)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    expdate = db.Column(db.DateTime)

class TeamRecord(db.Model):
    __tablename__ = 'teamrecords'
    
    id = db.Column(db.Integer, primary_key=True)
    team = db.Column(db.String(50), db.ForeignKey('teams.id'), nullable=False)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    ref = db.Column(db.Integer, db.ForeignKey('headrefs.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
    match = db.Column(db.String(36), db.ForeignKey('matches.uuid'))

class PlayerRecord(db.Model):
    __tablename__ = 'playerrecords'
    
    id = db.Column(db.Integer, primary_key=True)
    player = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=False)
    ref = db.Column(db.Integer, db.ForeignKey('headrefs.id'), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey('teams.id'))
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), default='NOTE')  # NOTE, WARNING, CAUTION, EJECTION
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
    match = db.Column(db.String(36), db.ForeignKey('matches.uuid'))

class SideComp(db.Model):
    __tablename__ = 'sidecomps'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)

class SideCompResult(db.Model):
    __tablename__ = 'sidecompresults'
    
    id = db.Column(db.Integer, primary_key=True)
    comp = db.Column(db.Integer, db.ForeignKey('sidecomps.id'), nullable=False)
    player = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=False)
    scanner_id = db.Column(db.Integer)
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
