# Currency names (can be overridden by user_templates)
MAIN_CURRENCY = "Requisition Points"
MAIN_CURRENCY_SHORT = "Req"
SECONDARY_CURRENCY = "Bonus Pay"
SECONDARY_CURRENCY_SHORT = "BP"

# Import user templates to override constants (this is an optional import because you don't have to override anything)
try:
    from user_templates import MAIN_CURRENCY, MAIN_CURRENCY_SHORT, SECONDARY_CURRENCY, SECONDARY_CURRENCY_SHORT
except ImportError:
    pass

Dossier = """{mention} V1.0
# {player.name}

{player.lore}

{medals}
"""

Statistics_Player = f"""{{mention}} V1.0
## {{player.name}}

{MAIN_CURRENCY}: {{player.rec_points}}
{SECONDARY_CURRENCY}: {{player.bonus_pay}}

Units:
{{units}}
"""

Statistics_Unit = """### {unit.name} {callsign} ({unit.unit_type}) {unit.status.name} {campaign_name}
{upgrades}"""

Statistics_Unit_Active = """### {unit.name} ({unit.unit_type}) {unit.status.name}
{upgrades}
{stats}"""

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

general_stats = f"""Players: {{players}} {MAIN_CURRENCY}: {{rec_points}} {SECONDARY_CURRENCY}: {{bonus_pay}}
Units: Total: {{units}} Purchased: {{purchased}} Active: {{active}} KIA/MIA: {{dead}}
Upgrades: {{upgrades}}
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
select_unit_to_buy = f"Please select a unit to buy upgrades for, you have {{rec_points}} {MAIN_CURRENCY}"
cant_buy_upgrades_stockpile = "You can't buy upgrades for a stockpile"
not_enough_req_points_unit = f"You don't have enough {MAIN_CURRENCY} to buy this unit"
cant_buy_upgrades_active = "You can't buy upgrades for an Active or MIA/KIA unit"
no_upgrades_available = "No upgrades are available for this unit"
select_upgrade_to_buy = "Please select an upgrade to buy, you have {req_points} {req_type} points"
upgrade_not_found = "Upgrade not found."
not_enough_req_points_upgrade = f"You don't have enough {MAIN_CURRENCY} to buy this upgrade"
dont_have_required_upgrade = "You don't have the required upgrade"
you_have_bought_upgrade = f"You have bought {{upgrade_name}} for {{upgrade_cost}} {MAIN_CURRENCY_SHORT}"
you_have_bought_refit = f"You have bought a refit to {{refit_target}} for {{refit_cost}} {MAIN_CURRENCY_SHORT}"
created_stockpile_unit = "You have created a new stockpile unit"
upgrade_created = "Upgrade created"
already_have_upgrade = "You already have this upgrade"
already_have_stockpile = "You already have a stockpile unit"
not_enough_bonus_pay = f"You don't have enough {SECONDARY_CURRENCY} to convert"
dont_have_stockpile = "You don't have a stockpile unit"

# Shop UI elements
shop_title = "Shop"
shop_unit_title = "Unit: {unit_name}"
shop_select_unit_placeholder = "Select a unit to buy upgrades for"
shop_no_units_option = "Please Create a Unit before using the Shop"
shop_convert_bp_button = f"Convert 10 {SECONDARY_CURRENCY_SHORT} to 1 {MAIN_CURRENCY_SHORT}"
shop_back_to_home_button = "Back to Home"
shop_buy_unit_button = f"Buy Unit (-1 {MAIN_CURRENCY_SHORT})"
shop_select_upgrade_placeholder = "Select an upgrade to buy"
shop_previous_button = "Previous"
shop_next_button = "Next"
shop_footer = "ALL SALES ARE FINAL AND NO REFUNDS WILL BE GIVEN"
shop_upgrade_button_template = f"{{type}} {{insufficient}} {{name}} - {{cost}} {MAIN_CURRENCY_SHORT}"

# Shop admin UI
shop_add_upgrade_modal_title = "Add Shop Upgrade"
shop_upgrade_name_label = "Name"
shop_upgrade_name_placeholder = "Enter the name of the upgrade"
shop_refit_target_label = "Refit Target"
shop_refit_target_placeholder = "Enter the refit target of the upgrade, or leave blank if it's not a refit"
shop_upgrade_cost_label = "Cost"
shop_upgrade_cost_placeholder = "Enter the cost of the upgrade"
shop_unit_types_label = "Unit Types"
shop_unit_types_placeholder = "Enter the unit types the upgrade is available for, comma separated"
shop_select_upgrade_type_message = "Please select an upgrade type"
shop_select_upgrade_type_placeholder = "Select an upgrade type"
shop_create_upgrade_button = "Create Upgrade"

# Import any other user template overrides
try:
    from user_templates import *
except ImportError:
    pass
