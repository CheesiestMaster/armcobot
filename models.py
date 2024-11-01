from sqlalchemy import Column, Integer, String, Enum, ForeignKey, PickleType, Boolean, event
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.declarative import declarative_base
from enum import Enum as PyEnum
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

Base = declarative_base()

class UnitType(PyEnum):
    INFANTRY = "0.0"
    MEDIC = "0.1"
    ENGINEER = "0.2"
    LOGISTIC = "1.0"
    LIGHT_VEHICLE = "1.1"
    INFANTRY_VEHICLE = "1.2"
    MAIN_TANK = "1.3"
    ARTILLERY = "2.0"
    FIGHTER = "3.0"
    BOMBER = "3.1"
    VTOL = "3.2"
    HVTOL = "3.3"
    HAT = "3.4"
    LIGHT_MECH = "4.0"

class UpgradeType(PyEnum):
    UPGRADE = "0.0"
    WEAPON = "1.0"
    SPECIAL = "2.0"

class UnitStatus(PyEnum):
    ACTIVE = "1"
    INACTIVE = "0"
    MIA = "2"
    KIA = "3"
    PROPOSED = "4"

class LegacyUnitStatus(PyEnum):
    MIA = "2"
    KIA = "3"
    LEGACY = "5"

class LegacyUnitType(PyEnum):
    INFANTRY = "0.0"
    MEDIC = "0.1"
    ENGINEER = "0.2"
    LOGISTIC = "1.0"
    LIGHT_VEHICLE = "1.1"
    INFANTRY_VEHICLE = "1.2"
    MAIN_TANK = "1.3"
    ARTILLERY = "2.0"
    FIGHTER = "3.0"
    BOMBER = "3.1"
    VTOL = "3.2"
    HVTOL = "3.3"
    HAT = "3.4"
    LIGHT_MECH = "4.0"
    MEDIUM_MECH = "4.1"
    HEAVY_MECH = "4.2"
    CORVETTE = "5.0"
    CRUISER = "5.1"
    DESTROYER = "5.2"
    BATTLESHIP = "5.3"
    V1_CARRIER = "5.4"

# Listeners

def after_insert(mapper, connection, target):
    logger.debug("Inserting target into queue")
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((0, target))

def after_update(mapper, connection, target):
    logger.debug("Updating target in queue")
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((1, target))

def after_delete(mapper, connection, target):
    logger.debug("Deleting target from queue")
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((2, target))
# Models

class Unit(Base):
    __tablename__ = "units"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    unit_type = Column(Enum(UnitType))
    status = Column(Enum(UnitStatus), default=UnitStatus.PROPOSED)
    
    # relationships
    player = relationship("Player", back_populates="units")
    upgrades = relationship("Upgrade", back_populates="unit", cascade="all, delete-orphan")
    active_unit = relationship("ActiveUnit", back_populates="unit", cascade="all, delete-orphan")

class ActiveUnit(Base):
    __tablename__ = "active_units"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # columns
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, index=True)
    call_sign = Column(String(8), default="", index=True, unique=True)
    unit_id = Column(Integer, ForeignKey("units.id"), unique=True, index=True)
    force_strength = Column(Integer, default=0)
    range = Column(Integer, default=0)
    speed = Column(Integer, default=0)
    defense = Column(Integer, default=0)
    armor = Column(Integer, default=0)
    north_south = Column(Integer, default=0)
    east_west = Column(Integer, default=0)
    facing = Column(Integer, default=0)
    area_operation = Column(String(30), default="ARMCO")
    supply = Column(Integer, default=0)
    immobilized = Column(Boolean, default=False)
    disarmed = Column(Boolean, default=False)
    transport_id = Column(Integer, ForeignKey("active_units.id"))
    # relationships
    player = relationship("Player", back_populates="active_units")
    unit = relationship("Unit", back_populates="active_unit")
    transport = relationship("ActiveUnit", remote_side=[id], backref=backref("passengers", lazy="dynamic"))

class Player(Base):
    __tablename__ = "players"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    discord_id = Column(String(255), index=True)
    name = Column(String(255), index=True)
    lore = Column(String(1000), default="")
    rec_points = Column(Integer, default=0)
    bonus_pay = Column(Integer, default=0)
    # relationships
    units = relationship("Unit", back_populates="player", cascade="all, delete-orphan")
    active_units = relationship("ActiveUnit", back_populates="player", cascade="all, delete-orphan")
    dossier = relationship("Dossier", back_populates="player", cascade="all, delete-orphan")
    statistic = relationship("Statistic", back_populates="player", cascade="all, delete-orphan")
    medals = relationship("Medals", back_populates="player", cascade="all, delete-orphan")
class Upgrade(Base):
    __tablename__ = "upgrades"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    type = Column(Enum(UpgradeType))
    name = Column(String(30), index=True)
    unit_id = Column(Integer, ForeignKey("units.id"))
    # relationships
    unit = relationship("Unit", back_populates="upgrades")

class Dossier(Base):
    __tablename__ = "dossiers"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, index=True)
    message_id = Column(String(255), index=True)
    # relationships
    player = relationship("Player", back_populates="dossier")

class Statistic(Base):
    __tablename__ = "statistics"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, index=True)
    message_id = Column(String(255), index=True)
    # relationships
    player = relationship("Player", back_populates="statistic")

class Config(Base):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(255), index=True, unique=True)
    value = Column(PickleType)

class LegacyUnit(Base):
    __tablename__ = "legacy_units"
    # almost identical to Unit, but uses a different pair of Enums for status and type
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    unit_type = Column(String(30), index=True)
    status = Column(String(30), index=True)

class Medals(Base):
    __tablename__ = "medals"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    # relationships
    player = relationship("Player", back_populates="medals")
# Unit, ActiveUnit, Upgrade need all 3 listeners
# Dossier and Statistic need only after_delete

[event.listen(model, "after_insert", after_insert) for model in [Player, Unit, ActiveUnit, Upgrade]]
[event.listen(model, "after_update", after_update) for model in [Player, Unit, ActiveUnit, Upgrade]]
[event.listen(model, "after_delete", after_delete) for model in [Unit, ActiveUnit, Upgrade, Dossier, Statistic]]

create_all = Base.metadata.create_all
