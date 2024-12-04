from sqlalchemy import Column, Integer, String, Enum, ForeignKey, PickleType, Boolean, BigInteger, event
from sqlalchemy.orm import relationship, backref, declarative_base
from enum import Enum as PyEnum
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

Base: type = declarative_base()

class UpgradeType(PyEnum):
    UPGRADE = "0.0"
    REFIT = "1.0"
    SPECIAL = "2.0"

class UnitStatus(PyEnum):
    ACTIVE = "1"
    INACTIVE = "0"
    MIA = "2"
    KIA = "3"
    PROPOSED = "4"
    LEGACY = "5"

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


class BaseModel(Base):
    __abstract__ = True
    
    def __repr__(self):
        class_name = self.__class__.__name__
        # Correctly access primary key columns
        primary_keys = ", ".join(
            [f"{key}={getattr(self, key)!r}" for key in self.__table__.primary_key.columns.keys()]
        )
        return f"<{class_name}({primary_keys})>"
    
    __str__ = __repr__
    
    def __hash__(self):
        return hash(repr(self))
    
    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return repr(self) == repr(other)


# Models

class Unit(BaseModel):
    __tablename__ = "units"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True, nullable=False)
    unit_type = Column(String(15))
    status = Column(Enum(UnitStatus), default=UnitStatus.PROPOSED) # status is still an enum, but type is a string now
    legacy = Column(Boolean, default=False)
    active = Column(Boolean, default=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    callsign = Column(String(15), index=True, unique=True)
    area_operation = Column(String(30), default="ARMCO")
    
    # relationships
    player = relationship("Player", back_populates="units", lazy="joined")
    upgrades = relationship("PlayerUpgrade", back_populates="unit", cascade="all, delete-orphan", lazy="subquery") # subquery for parent sides, joined for child sides
    campaign = relationship("Campaign", back_populates="units", lazy="joined")

class Campaign(BaseModel):
    __tablename__ = "campaigns"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True, unique=True)
    active = Column(Boolean, default=True)
    open = Column(Boolean, default=False)
    gm = Column(String(255), default="")
    player_limit = Column(Integer, nullable=True) # null for no limit
    required_role = Column(BigInteger, nullable=True) # null for no role required
    # relationships
    units = relationship("Unit", back_populates="campaign", lazy="subquery")
    invites = relationship("CampaignInvite", back_populates="campaign", lazy="subquery")

class CampaignInvite(BaseModel):
    __tablename__ = "campaign_invites"
    # just an association table for the many-to-many relationship between campaigns and invited players
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"), primary_key=True)
    campaign = relationship("Campaign", back_populates="invites", lazy="joined")
    player = relationship("Player", back_populates="campaign_invites", lazy="joined")

class Player(BaseModel):
    __tablename__ = "players"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    discord_id = Column(String(255), index=True)
    name = Column(String(255), index=True)
    lore = Column(String(1000), default="")
    rec_points = Column(Integer, default=0)
    bonus_pay = Column(Integer, default=0)
    # relationships
    units = relationship("Unit", back_populates="player", cascade="all, delete-orphan", lazy="subquery")
    dossier = relationship("Dossier", back_populates="player", lazy="joined")
    statistic = relationship("Statistic", back_populates="player", lazy="joined")
    medals = relationship("Medals", back_populates="player", cascade="all, delete-orphan", lazy="subquery")
    campaign_invites = relationship("CampaignInvite", back_populates="player", cascade="all, delete-orphan", lazy="subquery")

class PlayerUpgrade(BaseModel):
    __tablename__ = "player_upgrades"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    type = Column(Enum(UpgradeType))
    name = Column(String(30), index=True)
    original_price = Column(Integer, default=0)
    unit_id = Column(Integer, ForeignKey("units.id"))
    shop_upgrade_id = Column(Integer, ForeignKey("shop_upgrades.id"))
    # relationships
    unit = relationship("Unit", back_populates="upgrades", lazy="joined")
    shop_upgrade = relationship("ShopUpgrade", back_populates="player_upgrades", lazy="joined")

class Dossier(BaseModel):
    __tablename__ = "dossiers"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, index=True, nullable=False)
    message_id = Column(String(255), index=True)
    # relationships
    player = relationship("Player", back_populates="dossier", lazy="joined")

class Statistic(BaseModel):
    __tablename__ = "statistics"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, index=True, nullable=False)
    message_id = Column(String(255), index=True)
    # relationships
    player = relationship("Player", back_populates="statistic", lazy="joined")

class Config(BaseModel):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(255), index=True, unique=True)
    value = Column(PickleType)

class Medals(BaseModel):
    __tablename__ = "medals"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    # relationships
    player = relationship("Player", back_populates="medals", lazy="joined")

class Faq(BaseModel):
    __tablename__ = "faq"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    question = Column(String(255), index=True)
    answer = Column(String(500))

class ShopUpgrade(BaseModel):
    __tablename__ = "shop_upgrades"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    type = Column(Enum(UpgradeType))
    cost = Column(Integer, default=0)
    description = Column(String(255), default="")
    required_upgrade_id = Column(Integer, ForeignKey("shop_upgrades.id"), nullable=True)
    player_upgrades = relationship("PlayerUpgrade", back_populates="shop_upgrade", cascade="all, delete-orphan", lazy="subquery")
    unit_types = relationship("ShopUpgradeUnitTypes", back_populates="shop_upgrade", cascade="all, delete-orphan", lazy="subquery")
    required_upgrade = relationship("ShopUpgrade", remote_side=[id], lazy="joined")

class ShopUpgradeUnitTypes(BaseModel):
    __tablename__ = "shop_upgrade_unit_types"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    shop_upgrade_id = Column(Integer, ForeignKey("shop_upgrades.id"))
    unit_type = Column(String(15))
    shop_upgrade = relationship("ShopUpgrade", back_populates="unit_types", lazy="joined")

# Unit, PlayerUpgrade need all 3 listeners
# Dossier and Statistic need only after_delete

[event.listen(model, "after_insert", after_insert) for model in [Player, Unit, PlayerUpgrade]]
[event.listen(model, "after_update", after_update) for model in [Player, Unit, PlayerUpgrade]]
[event.listen(model, "after_delete", after_delete) for model in [Unit, PlayerUpgrade, Dossier, Statistic]]

create_all = Base.metadata.create_all
