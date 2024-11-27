Dossier = """# {player.name}

{player.lore}

{medals}"""

Statistics_Player = """## {player.name}

Reqisition Points: {player.rec_points}
Bonus Pay: {player.bonus_pay}

Units:
{units}"""

Statistics_Unit = """### {unit.name} {callsign} ({unit.unit_type}) {unit.status.name}
{upgrades}"""

Statistics_Unit_Active = """### {unit.name} ({unit.unit_type}) {unit.status.name}
{upgrades}
{stats}"""

Non_Combat_Stats = "FS: {unit.force_strength} Cargo: {unit.supply}"
Infantry_Stats = "FS: {unit.force_strength} Range: {unit.range} Speed: {unit.speed} Defense: {unit.defense}"
Armor_Stats = "FS: {unit.force_strength} Armor: {unit.armor} Range: {unit.range} Speed: {unit.speed} Defense: {unit.defense}"
Artillery_Stats = "FS: {unit.force_strength} Range: {unit.range} Speed: {unit.speed} Ammo: {unit.supply}"
Air_Stats = "FS: {unit.force_strength} Range: {unit.range} Speed: {unit.speed} Armor: {unit.armor} Cargo: {unit.supply}"
