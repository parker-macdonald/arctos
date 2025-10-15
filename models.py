from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import uuid

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
    profile_photo = db.Column(db.String(255))  # Path to uploaded photo
    
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

class Tournament(db.Model):
    __tablename__ = 'tournaments'
    
    url = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    dates = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200))
    num_fields = db.Column(db.Integer, default=1)
    n_max_teams = db.Column(db.Integer)
    max_team_size = db.Column(db.Integer)
    max_field_size = db.Column(db.Integer)
    team_reg_fee = db.Column(db.Float, default=0.0)
    player_reg_fee = db.Column(db.Float, default=0.0)
    payment_info = db.Column(db.Text)
    published = db.Column(db.Boolean, default=False)
    about = db.Column(db.Text)
    admin_password = db.Column(db.String(255))

class TO(db.Model):
    __tablename__ = 'tos'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)  # Player or Team ID
    user_type = db.Column(db.String(10), nullable=False)  # 'player' or 'team'
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)

class Registration(db.Model):
    __tablename__ = 'registrations'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    player = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=False)
    pseudonym = db.Column(db.String(100))
    jersey = db.Column(db.String(10))
    team = db.Column(db.String(50), db.ForeignKey('teams.id'))
    status = db.Column(db.String(20), default='SENT')  # SENT, CONFIRMED

class TeamInvitation(db.Model):
    __tablename__ = 'team_invitations'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey('teams.id'), nullable=True)
    player = db.Column(db.String(50), db.ForeignKey('players.id'), nullable=True)
    status = db.Column(db.String(20), default='PENDING')  # PENDING, ACCEPTED, DECLINED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Field(db.Model):
    __tablename__ = 'fields'
    
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey('tournaments.url'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    camera = db.Column(db.String(200))

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
    nominal_length = db.Column(db.Integer)  # minutes
    type = db.Column(db.String(20), default='SETS')  # SETS, STONES
    nsets = db.Column(db.Integer)
    nstonesperset = db.Column(db.Integer)
    status = db.Column(db.String(20), default='NOT_STARTED')  # NOT_STARTED, IN_PROGRESS, COMPLETED
    gamestate = db.Column(db.Text)
    dynamic = db.Column(db.Boolean, default=True)  # True for dynamic, False for static scheduling

class Point(db.Model):
    __tablename__ = 'points'
    
    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    match = db.Column(db.String(36), db.ForeignKey('matches.uuid'), nullable=False)
    winner = db.Column(db.String(10))  # TEAM1, TEAM2
    rerolled = db.Column(db.Boolean, default=False)
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
    footage = db.Column(db.String(500))
    length = db.Column(db.Interval)
    nstones = db.Column(db.Integer)
    rerollreason = db.Column(db.Text)

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
