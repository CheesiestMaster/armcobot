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

Statistics_Unit = """### {unit.name} {callsign} ({unit.unit_type}) {unit.status.name} {campaign_name}
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

# FAQ related
faq_how_to_use = "Use the `/faq list` command to view all the FAQ questions. Use the `/faq view` command to view a specific question."
no_faq_questions = "No FAQ questions found"
select_question = "Select a question"
faq_max_questions = "You cannot add more than 125 questions to the FAQ"
question_added = "Question added to the FAQ"
question_removed = "Question removed from the FAQ"
question_edited = "Question edited in the FAQ"
here_is_question_file = "Here is the question file"

stats_template = """Uptime: {uptime} Started at: {start_time}
Memory: {resident:0.2f} MB
CPU: {cpu_time:0.2f} seconds ({average_cpu:0.2f} average)
Debug logs: today: {today_DEBUG} total: {total_DEBUG}
Info logs: today: {today_INFO} total: {total_INFO}
Warning logs: today: {today_WARNING} total: {total_WARNING}
Error logs: today: {today_ERROR} total: {total_ERROR}
Critical logs: today: {today_CRITICAL} total: {total_CRITICAL}
Total logs: today: {today_total} total: {total_total}"""

general_stats = """Players: {players} Rec Points: {rec_points} Bonus Pay: {bonus_pay}
Units: Total: {units} Purchased: {purchased} Active: {active} KIA/MIA: {dead}
Upgrades: {upgrades}
"""

# Common error messages
no_meta_campaign_company = "You don't have a Meta Campaign company"
already_have_company = "You already have a Meta Campaign company"
invalid_input = "Invalid input: values cannot contain discord tags or headers"
no_permission = "You don't have permission to run this command"
stopping_bot = "Stopping bot"
restarting_bot = "Restarting bot"
cannot_unload_debug = "Cannot unload debug extension from in Discord"
checking_fk = "Checking External Foreign Keys"
applying_updates = "Applying updates"

# Bot responses
marker_made = "Marker made"
test_complete = "Test complete"
company_updated = "Company updated"
company_refreshed = "Your Meta Campaign company has been refreshed"
joined_meta_campaign = "You have joined Meta Campaign"
queue_emptied = "Queue emptied"
all_deletable_cleared = "All deletable messages have been cleared."
fk_check_complete = "External Foreign Key check complete"

# RP/Roleplay related
rp_template = """---- RP POST ----
```ansi
[32m{message}
```"""
message_sent = "Message sent"

# Company related
bot_company_exists = "Bot company already exists"
bot_company_created = "Bot company created"
member_no_company = "{member.display_name} doesn't have a Meta Campaign company"

# Shop related
unit_doesnt_exist = "That unit doesn't exist"
select_unit_to_buy = "Please select a unit to buy upgrades for, you have {rec_points} requisition points"
cant_buy_upgrades_stockpile = "You can't buy upgrades for a stockpile"
not_enough_req_points_unit = "You don't have enough requisition points to buy this unit"
cant_buy_upgrades_active = "You can't buy upgrades for an Active or MIA/KIA unit"
no_upgrades_available = "No upgrades are available for this unit"
select_upgrade_to_buy = "Please select an upgrade to buy, you have {req_points} {req_type} points"
upgrade_not_found = "Upgrade not found."
not_enough_req_points_upgrade = "You don't have enough requisition points to buy this upgrade"
dont_have_required_upgrade = "You don't have the required upgrade"
you_have_bought_upgrade = "You have bought {upgrade_name} for {upgrade_cost} Req"
you_have_bought_refit = "You have bought a refit to {refit_target} for {refit_cost} Req"
created_stockpile_unit = "You have created a new stockpile unit"
upgrade_created = "Upgrade created"
already_have_upgrade = "You already have this upgrade"
already_have_stockpile = "You already have a stockpile unit"
not_enough_bonus_pay = "You don't have enough bonus pay to convert"
dont_have_stockpile = "You don't have a stockpile unit"