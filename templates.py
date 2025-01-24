Dossier = """{mention} V1.0
# {player.name}

{player.lore}

{medals}
"""

Statistics_Player = """{mention} V1.0
## {player.name}

Requisition Points: {player.rec_points}
Bonus Pay: {player.bonus_pay}

Units:
{units}
"""

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

faq_response = """**Question:** {selected.question}

**Answer:** {selected.answer}"""

stats_template = """Uptime: {uptime} Started at: {start_time}
Memory: {resident:0.2f} MB
CPU: {cpu_time:0.2f} seconds ({average_cpu:0.2f} average)
Debug logs: today: {today_DEBUG} total: {total_DEBUG}
Info logs: today: {today_INFO} total: {total_INFO}
Warning logs: today: {today_WARNING} total: {total_WARNING}
Error logs: today: {today_ERROR} total: {total_ERROR}
Critical logs: today: {today_CRITICAL} total: {total_CRITICAL}
Total logs: today: {today_total} total: {total_total}"""

general_stats = """Players: {players}
Units: Total: {units} Purchased: {purchased} Active: {active} KIA/MIA: {dead}
Upgrades: {upgrades}
"""