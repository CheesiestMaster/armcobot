Dossier = """
# {player.name}

{player.lore}
"""

Statistics_Player = """
## {player.name}

Reqisition Points: {player.rec_points}
Bonus Pay: {player.bonus_pay}

Units:
{units}
"""

Statistics_Unit = """
### {unit.name} ({unit.unit_type.name}) {unit.status.name}
{upgrades}
"""

Statistics_Unit_Active = """
### {unit.name} ({unit.unit_type.name}) {unit.status.name}
{upgrades}
{stats}

"""

Non_Combat_Stats = "FS: {unit.fs} Cargo: {unit.supply}"
Infantry_Stats = "FS: {unit.fs} Range: {unit.range} Speed: {unit.speed} Defense: {unit.defense} | {unit.north_south}N/{unit.east_west}E Facing:{unit.facing}"
Armor_Stats = "FS: {unit.fs} Armor: {unit.armor} Range: {unit.range} Speed: {unit.speed} Defense: {unit.defense} | {unit.north_south}N/{unit.east_west}E Facing:{unit.facing} Disarmed: {unit.disarmed} Immobilized: {unit.immobilized}"
Artillery_Stats = "FS: {unit.fs} Range: {unit.range} Speed: {unit.speed} Ammo: {unit.supply} | {unit.north_south}N/{unit.east_west}E Facing:{unit.facing} Deployed: {unit.immobilized}"
Air_Stats = "FS: {unit.fs} Range: {unit.range} Speed: {unit.speed} Armor: {unit.armor} Cargo: {unit.supply} | {unit.north_south}N/{unit.east_west}E Facing:{unit.facing} Deployed: {unit.immobilized}"
