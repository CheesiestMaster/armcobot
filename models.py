from __future__ import annotations
from sqlalchemy import Integer, String, Enum, ForeignKey, PickleType, Boolean, BigInteger
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.hybrid import hybrid_property
from enum import Enum as PyEnum
import logging
from typing import Optional

logger = logging.getLogger(__name__)

engine_logger = logging.getLogger("sqlalchemy.engine")
#engine_logger.setLevel(logging.DEBUG)

class UnitStatus(PyEnum):
    ACTIVE = "1"
    INACTIVE = "0"
    MIA = "2"
    KIA = "3"
    PROPOSED = "4"
    LEGACY = "5"

class BaseModel(DeclarativeBase):
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

class UpgradeType(BaseModel):
    __tablename__ = "upgrade_types"
    # columns
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    emoji: Mapped[str] = mapped_column(String(4), default="")
    is_refit: Mapped[bool] = mapped_column(Boolean, default=False)
    non_purchaseable: Mapped[bool] = mapped_column(Boolean, default=False)
    can_use_unit_req: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # relationships
    shop_upgrades: Mapped[list[ShopUpgrade]] = relationship("ShopUpgrade", foreign_keys="ShopUpgrade.type", back_populates="upgrade_type", lazy="select")
    player_upgrades: Mapped[list[PlayerUpgrade]] = relationship("PlayerUpgrade", foreign_keys="PlayerUpgrade.type", back_populates="upgrade_type", lazy="select")

class Extension(BaseModel):
    __tablename__ = "extensions"
    # column
    name: Mapped[str] = mapped_column(String(264), primary_key=True) # this table is just a list of loaded extensions, hence only one column and no relationships

class Unit(BaseModel):
    __tablename__ = "units"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True, nullable=False)
    unit_type: Mapped[str] = mapped_column(ForeignKey("unit_types.unit_type"))
    status: Mapped[UnitStatus] = mapped_column(Enum(UnitStatus), default=UnitStatus.PROPOSED)
    legacy: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    callsign: Mapped[str] = mapped_column(String(15), index=True, unique=True, nullable=True)
    area_operation: Mapped[str] = mapped_column(String(30), default="ARMCO")
    original_type: Mapped[Optional[str]] = mapped_column(ForeignKey("unit_types.unit_type"), nullable=True)
    unit_req: Mapped[int] = mapped_column(Integer, default=0)
    
    # relationships
    player: Mapped[Player] = relationship("Player", back_populates="units")
    upgrades: Mapped[list[PlayerUpgrade]] = relationship("PlayerUpgrade", back_populates="unit", cascade="all, delete-orphan", lazy="select")
    campaign: Mapped[Optional[Campaign]] = relationship("Campaign", back_populates="units")
    type_info: Mapped[UnitType] = relationship("UnitType", foreign_keys=[unit_type], lazy="joined", back_populates="units", cascade="save-update")
    original_type_info: Mapped[Optional[UnitType]] = relationship("UnitType", foreign_keys=[original_type], lazy="joined", back_populates="original_units")
    available_upgrades: Mapped[list[ShopUpgrade]] = relationship(
        "ShopUpgrade",
        secondary="shop_upgrade_unit_types",
        primaryjoin="Unit.unit_type==ShopUpgradeUnitTypes.unit_type",
        secondaryjoin="ShopUpgrade.id==ShopUpgradeUnitTypes.shop_upgrade_id",
        overlaps="unit_types,type_info",
        lazy="select",
        viewonly=True)

class Campaign(BaseModel):
    __tablename__ = "campaigns"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), index=True, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    open: Mapped[bool] = mapped_column(Boolean, default=False)
    gm: Mapped[str] = mapped_column(String(255), default="")
    player_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # null for no limit
    required_role: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True) # null for no role required
    # relationships
    units: Mapped[list[Unit]] = relationship("Unit", back_populates="campaign", lazy="select")
    invites: Mapped[list[CampaignInvite]] = relationship("CampaignInvite", back_populates="campaign", cascade="all, delete-orphan", lazy="select")
    players: Mapped[set[Player]] = relationship(
        "Player",
        secondary="units",
        primaryjoin="Campaign.id == Unit.campaign_id",
        secondaryjoin="Unit.player_id == Player.id",
        collection_class=set,
        lazy="select"
    )
    live_players: Mapped[set[Player]] = relationship(
        "Player",
        secondary="units",
        primaryjoin="and_(Campaign.id == Unit.campaign_id, Unit.status == 'ACTIVE')",
        secondaryjoin="Unit.player_id == Player.id",
        collection_class=set,
        lazy="select"
    )

class CampaignInvite(BaseModel):
    __tablename__ = "campaign_invites"
    # just an association table for the many-to-many relationship between campaigns and invited players
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)

    # relationships
    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="invites", lazy="joined")
    player: Mapped[Player] = relationship("Player", back_populates="campaign_invites", lazy="joined")

class Player(BaseModel):
    __tablename__ = "players"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    discord_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    lore: Mapped[str] = mapped_column(String(1000), default="")
    rec_points: Mapped[int] = mapped_column(Integer, default=0)
    bonus_pay: Mapped[int] = mapped_column(Integer, default=0)
    # relationships
    units: Mapped[list[Unit]] = relationship("Unit", back_populates="player", cascade="none", lazy="select")
    dossier: Mapped[Dossier] = relationship("Dossier", back_populates="player")
    statistic: Mapped[Statistic] = relationship("Statistic", back_populates="player")
    medals: Mapped[list[Medals]] = relationship("Medals", back_populates="player", cascade="none", lazy="select")
    campaign_invites: Mapped[list[CampaignInvite]] = relationship("CampaignInvite", back_populates="player", cascade="none", lazy="select")

    stockpile: Mapped[Optional[Unit]] = relationship(
        "Unit",
        primaryjoin="and_(Player.id == Unit.player_id, Unit.unit_type == 'STOCKPILE')",
        uselist=False,
        viewonly=True
    )
    active_units: Mapped[list[Unit]] = relationship(
        "Unit",
        primaryjoin="and_(Player.id == Unit.player_id, Unit.active == True)",
        uselist=True,
        viewonly=True,
    )

class PlayerUpgrade(BaseModel):
    __tablename__ = "player_upgrades"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    type: Mapped[str] = mapped_column(ForeignKey("upgrade_types.name"))
    name: Mapped[str] = mapped_column(String(30), index=True)
    original_price: Mapped[int] = mapped_column(Integer, default=0)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    shop_upgrade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shop_upgrades.id"), nullable=True)
    non_transferable: Mapped[bool] = mapped_column(Boolean, default=False)
    # relationships
    unit: Mapped[Unit] = relationship("Unit", back_populates="upgrades", lazy="joined")
    shop_upgrade: Mapped[Optional[ShopUpgrade]] = relationship("ShopUpgrade", back_populates="player_upgrades", lazy="joined")
    upgrade_type: Mapped[UpgradeType] = relationship("UpgradeType", foreign_keys=[type], back_populates="player_upgrades", lazy="joined")

class Dossier(BaseModel):
    __tablename__ = "dossiers"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), unique=True, index=True, nullable=False)
    message_id: Mapped[str] = mapped_column(String(255), index=True)
    # relationships
    player: Mapped[Player] = relationship("Player", back_populates="dossier", lazy="joined")

class Statistic(BaseModel):
    __tablename__ = "statistics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), unique=True, index=True, nullable=False)
    message_id: Mapped[str] = mapped_column(String(255), index=True)
    # relationships
    player: Mapped[Player] = relationship("Player", back_populates="statistic", lazy="joined")

class Config(BaseModel):
    __tablename__ = "configs"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), index=True, unique=True)
    value: Mapped[PickleType] = mapped_column(PickleType)

class Medals(BaseModel):
    __tablename__ = "medals"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    # relationships
    player: Mapped[Player] = relationship("Player", back_populates="medals", lazy="joined")

class Faq(BaseModel):
    __tablename__ = "faq"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(100), index=True)
    answer: Mapped[str] = mapped_column(String(1873))

class ShopUpgrade(BaseModel):
    __tablename__ = "shop_upgrades"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), index=True)
    type: Mapped[str] = mapped_column(ForeignKey("upgrade_types.name"))
    cost: Mapped[int] = mapped_column(Integer, default=0)
    refit_target: Mapped[str | None] = mapped_column(ForeignKey("unit_types.unit_type"), nullable=True)
    required_upgrade_id: Mapped[int | None] = mapped_column(ForeignKey("shop_upgrades.id"), nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    repeatable: Mapped[bool] = mapped_column(Boolean, default=False)

    # relationships
    player_upgrades: Mapped[list[PlayerUpgrade]] = relationship("PlayerUpgrade", back_populates="shop_upgrade", cascade="all", lazy="select")
    unit_types: Mapped[list[ShopUpgradeUnitTypes]] = relationship("ShopUpgradeUnitTypes", back_populates="shop_upgrade", cascade="all, delete-orphan", lazy="select")
    required_upgrade: Mapped[Optional[ShopUpgrade]] = relationship("ShopUpgrade", remote_side=[id], lazy="joined")
    target_type_info: Mapped[UnitType] = relationship("UnitType", foreign_keys=[refit_target], lazy="joined", back_populates="refit_targets")
    compatible_units: Mapped[list[Unit]] = relationship(
        "Unit",
        secondary="shop_upgrade_unit_types",
        primaryjoin="ShopUpgrade.id==ShopUpgradeUnitTypes.shop_upgrade_id",
        secondaryjoin="Unit.unit_type==ShopUpgradeUnitTypes.unit_type",
        back_populates="available_upgrades",
        overlaps="unit_types,type_info",
        lazy="select")
    compatible_unit_types: Mapped[list[UnitType]] = relationship(
        "UnitType",
        secondary="shop_upgrade_unit_types",
        primaryjoin="ShopUpgrade.id==ShopUpgradeUnitTypes.shop_upgrade_id",
        secondaryjoin="UnitType.unit_type==ShopUpgradeUnitTypes.unit_type",
        back_populates="compatible_upgrades",
        overlaps="unit_types,type_info",
        lazy="select")
    upgrade_type: Mapped[UpgradeType] = relationship("UpgradeType", foreign_keys=[type], back_populates="shop_upgrades", lazy="joined")

class ShopUpgradeUnitTypes(BaseModel):
    __tablename__ = "shop_upgrade_unit_types"
    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    shop_upgrade_id: Mapped[int] = mapped_column(ForeignKey("shop_upgrades.id"))
    unit_type: Mapped[str] = mapped_column(ForeignKey("unit_types.unit_type"))
    shop_upgrade: Mapped[ShopUpgrade] = relationship(back_populates="unit_types", overlaps="available_upgrades,compatible_units", lazy="joined")
    type_info: Mapped[UnitType] = relationship(lazy="joined", back_populates="upgrade_types", overlaps="available_upgrades,compatible_units")

class UnitType(BaseModel):
    __tablename__ = "unit_types"
    # columns
    unit_type: Mapped[str] = mapped_column(String(15), primary_key=True, index=True)
    is_base: Mapped[bool] = mapped_column(Boolean, default=False)
    free_upgrade_1: Mapped[Optional[int]] = mapped_column(ForeignKey("shop_upgrades.id"), nullable=True)
    free_upgrade_2: Mapped[Optional[int]] = mapped_column(ForeignKey("shop_upgrades.id"), nullable=True)
    unit_req: Mapped[int] = mapped_column(Integer, default=0)

    # relationships
    units: Mapped[list[Unit]] = relationship("Unit", foreign_keys="Unit.unit_type", back_populates="type_info", lazy="select")
    original_units: Mapped[list[Unit]] = relationship("Unit", foreign_keys="Unit.original_type", back_populates="original_type_info", overlaps="original_type_info", lazy="select")
    refit_targets: Mapped[list[ShopUpgrade]] = relationship("ShopUpgrade", foreign_keys="ShopUpgrade.refit_target", back_populates="target_type_info", overlaps="target_type_info", lazy="select")
    upgrade_types: Mapped[list[ShopUpgradeUnitTypes]] = relationship("ShopUpgradeUnitTypes", back_populates="type_info", overlaps="available_upgrades,compatible_units,type_info", lazy="select")
    free_upgrade_1_info: Mapped[Optional[ShopUpgrade]] = relationship(
        "ShopUpgrade",
        foreign_keys=[free_upgrade_1],
        overlaps="target_type_info")
    free_upgrade_2_info: Mapped[Optional[ShopUpgrade]] = relationship(
        "ShopUpgrade",
        foreign_keys=[free_upgrade_2],
        overlaps="target_type_info")
    compatible_upgrades: Mapped[list[ShopUpgrade]] = relationship(
        "ShopUpgrade",
        secondary="shop_upgrade_unit_types",
        primaryjoin="UnitType.unit_type==ShopUpgradeUnitTypes.unit_type",
        secondaryjoin="ShopUpgrade.id==ShopUpgradeUnitTypes.shop_upgrade_id",
        back_populates="compatible_unit_types",
        overlaps="unit_types,type_info",
        lazy="select")

create_all = BaseModel.metadata.create_all
