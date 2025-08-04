# Currency names (can be overridden by user_templates)
MAIN_CURRENCY = "Requisition Points"
MAIN_CURRENCY_SHORT = "Req"
SECONDARY_CURRENCY = "Bonus Pay"
SECONDARY_CURRENCY_SHORT = "BP"

# Import user templates to override constants (this is an optional import because you don't have to override anything)
try:
    from user_templates import MAIN_CURRENCY, MAIN_CURRENCY_SHORT, SECONDARY_CURRENCY, SECONDARY_CURRENCY_SHORT #type: ignore
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
updating_bot = "Updating bot"
cannot_unload_debug = "Cannot unload debug extension from in Discord"
checking_fk = "Checking External Foreign Keys"
applying_updates = "Applying updates"

# Permission and validation messages
not_authorized = "You are not authorized to use this command"
no_permission_set_nickname = "You don't have permission to set the bot's nickname"
text_channel_only = "This command can only be used in a text channel"
dm_not_allowed = "This command cannot be run in a DM"
server_only = "This command can only be run in a server"

# Campaign related messages
campaign_not_found = "Campaign not found"
campaign_name_too_long = "Campaign name must be less than 30 characters"
campaign_name_invalid_char = "Campaign name cannot contain a '#' due to discord autocompletion"
campaign_name_taken = "Campaign name already taken"
campaign_created = "Campaign {name} created"
campaign_opened = "Campaign {campaign} opened"
campaign_closed = "Campaign {campaign} closed"
gm_cannot_create_for_others = "GMs cannot create campaigns for other GMs, ask a bot Manager to do this"
gm_no_permission = "{gm.mention} doesn't have permission to be a GM"
no_permission_open_campaign = "You don't have permission to open this campaign"
no_permission_close_campaign = "You don't have permission to close this campaign"
no_permission_remove_campaign = "You don't have permission to remove this campaign"
no_permission_payout_campaign = "You don't have permission to payout this campaign"
no_permission_invite_campaign = "You don't have permission to invite to this campaign"
no_permission_deactivate_player = "You don't have permission to deactivate this player"
no_permission_kill_unit = "You don't have permission to kill this unit"
no_permission_raffle_units = "You don't have permission to raffle units"
no_permission_limit_types = "You don't have permission to limit types for this campaign"
no_permission_merge_campaigns = "You don't have permission to merge these campaigns"

# Unit related messages
unit_not_found = "Unit not found"
unit_not_active = "Unit is not active"
unit_already_active = "You already have an active unit"
unit_not_inactive = "That unit is not inactive"
unit_name_too_long = "Unit name is too long, please use a shorter name"
unit_name_invalid = "Unit names cannot contain discord tags"
unit_name_ascii = "Unit names must be ASCII"
unit_name_exists = "You already have a unit with that name"
unit_invalid_type = "Invalid unit type, something went wrong"
callsign_too_long = "Callsign is too long, please use a shorter callsign"
callsign_invalid = "Callsigns cannot contain discord tags"
callsign_ascii = "Callsigns must be ASCII"
callsign_taken = "That callsign is already in use"
stockpile_cannot_remove = "Stockpile units cannot be removed"
stockpile_cannot_rename = "Stockpile units cannot be renamed"
unit_removed = "Unit {unit.name} removed"
unit_deactivated = "Unit with callsign {original_callsign} deactivated"
unit_renamed = "Unit renamed to {new_name}"
unit_killed = "Unit {callsign} killed{mia_text}"

# Player related messages
player_not_found = "Player not found"
player_no_company = "Player doesn't have a Meta Campaign company"
player_no_units = "User doesn't have any Units"
player_max_units = "You already have 3 proposed Units, which is the maximum allowed"
player_not_eligible = "You are not eligible to join this campaign"
player_invited = "Player {player.mention} invited to {campaign}"
player_deactivated = "Player {player.mention} deactivated from {campaign}"

# FAQ related messages
faq_no_questions = "No FAQ questions found"
faq_select_question = "Select a question"
faq_max_questions = "You cannot add more than 125 questions to the FAQ"
faq_question_added = "Question added to the FAQ"
faq_question_removed = "Question removed from the FAQ"
faq_question_edited = "Question edited in the FAQ"
faq_file_here = "Here is the question file"

# Company related messages
company_name_length = "Name must be between 1 and 32 characters"
company_lore_length = "Lore must be less than 1000 characters"
company_lore_urls = "Lore cannot contain invalid URLs"

# Search related messages
search_no_company = "You don't have a Meta Campaign company so you can't search"
search_select_params = "Please select the unit type and the ao"

# Configuration related messages
config_nickname_global = "Bot nickname globally set to {nick}"
config_nickname_guild = "Bot nickname in {interaction.guild.name} set to {nick}"
config_dossier_channel = "Dossier channel set to {interaction.channel.mention}"
config_stats_channel = "Statistics channel set to {interaction.channel.mention}"
config_list = "Configurations:\n{config_str}"

# Debug related messages
debug_no_commands = "No commands found"
debug_reload_success = "String templates and dependent modules reloaded successfully"
debug_reload_error = "Error reloading templates: {e}"
debug_reloading = "Reloading {extension}"
debug_loading = "Loading {extension}"
debug_unloading = "Unloading {extension}"
debug_query_result = "Query result: {rows}"
debug_query_no_rows = "No rows returned"
debug_query_error = "Error: {e}"
debug_command_ban_status = "Command ban is {status}"
debug_command_ban_toggle = "Command ban {action}"
debug_log_level = "Log level set to {level}"

# Ping related messages
ping_recent_user = "You've already pinged me recently, wait a bit before pinging again"
ping_recent_bot = "I've been pinged recently, wait a bit before pinging again"
ping_response = "Pong! I was last restarted at <t:{timestamp}:F>, <t:{timestamp}:R>"

# Command ban messages
command_ban_effect = "# A COMMAND BAN IS IN EFFECT {user.mention}, WHY ARE YOU TRYING TO RUN A COMMAND?"
user_banned = "You are banned from using this bot"

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
upgrade_non_purchaseable = "This upgrade is not purchaseable"

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

# Shop management UI
shop_manage_select_content = "Select what you want to manage"
shop_unit_type_button = "Unit Type"
shop_upgrade_type_button = "Upgrade Type"
shop_upgrade_button = "Upgrade"

# Unit Type Management
shop_unit_type_select_placeholder = "Select a unit type"
shop_add_new_unit_type_modal_title = "Add New Unit Type"
shop_unit_type_name_label = "Unit Type Name"
shop_unit_type_name_placeholder = "Enter the name of the new unit type"
shop_is_base_placeholder = "Is this a base unit?"
shop_unit_req_amount_placeholder = f"Unit {MAIN_CURRENCY_SHORT} Amount"
shop_done_button = "Done"
shop_please_setup_unit_type = "Please set up the unit type"
shop_unit_type_added = "Unit type added"
shop_unit_type_title = "Unit Type: {unit_type}"
shop_rename_button = "Rename"
shop_delete_button = "Delete"
shop_rename_unit_type_modal_title = "Rename Unit Type"
shop_new_name_label = "New Name"
shop_new_name_placeholder = "Enter new unit type name"
shop_name_cannot_be_empty = "Name cannot be empty"
shop_unit_type_already_exists = "Unit type '{name}' already exists"
shop_unit_type_renamed = "Unit type '{old}' renamed to '{new}'"
shop_unit_type_updated = "Unit type updated"
shop_unit_type_deleted = "Unit type deleted"

# Unit Type Delete Errors
shop_cannot_delete_has_units = "You cannot delete a unit type that has units assigned to it"
shop_cannot_delete_has_original_units = "You cannot delete a unit type that has original units assigned to it"
shop_cannot_delete_has_refit_targets = "You cannot delete a unit type that has refit targets assigned to it"
shop_cannot_delete_has_compatible_upgrades = "You cannot delete a unit type that has compatible upgrades assigned to it"

# Upgrade Type Management
shop_upgrade_type_select_placeholder = "Select an upgrade type"
shop_add_new_upgrade_type_modal_title = "Add New Upgrade Type"
shop_upgrade_type_name_label = "Name"
shop_upgrade_type_name_placeholder = "Enter upgrade type name"
shop_emoji_label = "Emoji"
shop_emoji_placeholder = "Enter emoji (optional)"
shop_is_refit_label = "Is Refit"
shop_yn_placeholder = "y/n"
shop_non_purchaseable_label = "Non Purchaseable"
shop_can_use_unit_req_label = "Can Use Unit Req"
shop_upgrade_type_added = "Upgrade type added"
shop_upgrade_type_title = "Upgrade Type: {name}"
shop_rename_upgrade_type_modal_title = "Rename Upgrade Type"
shop_upgrade_type_already_exists = "Upgrade type '{name}' already exists"
shop_upgrade_type_renamed = "Upgrade type '{old}' renamed to '{new}'"
shop_please_setup_upgrade_type = "Please set up the upgrade type"
shop_upgrade_type_deleted = "Upgrade type deleted"

# Upgrade Type Delete Errors
shop_cannot_delete_has_shop_upgrades = "You cannot delete an upgrade type that has shop upgrades assigned to it"
shop_cannot_delete_has_player_upgrades = "You cannot delete an upgrade type that has player upgrades assigned to it"

# Shop Upgrade Management
shop_upgrade_select_placeholder = "Select a shop upgrade"
shop_select_upgrade_type_placeholder = "Select Upgrade Type"
shop_disabled_placeholder = "Disabled"
shop_repeatable_placeholder = "Repeatable"
shop_proceed_to_details_button = "Proceed to Details"
shop_add_new_shop_upgrade_modal_title = "Add New Shop Upgrade"
shop_upgrade_name_placeholder = "Enter shop upgrade name"
shop_cost_placeholder = "Enter cost"
shop_refit_target_optional_placeholder = "Enter refit target unit type (optional)"
shop_required_upgrade_id_placeholder = "Enter required upgrade ID (optional)"
shop_compatible_unit_types_placeholder = "Enter unit types (one per line)"
shop_please_select_upgrade_type = "Please select an upgrade type"
shop_please_select_boolean_options = "Please select the boolean options, then fill out the modal"
shop_upgrade_added = "Shop upgrade added"
shop_upgrade_title = "Shop Upgrade: {name}"
shop_edit_shop_upgrade_modal_title = "Edit Shop Upgrade"
shop_upgrade_already_exists = "Shop upgrade '{name}' already exists"
shop_upgrade_renamed = "Shop upgrade '{old}' renamed to '{new}'"
shop_please_select_options_to_edit = "Please select the options to edit, then proceed to details"
shop_upgrade_updated = "Shop upgrade updated"
shop_upgrade_deleted = "Shop upgrade deleted"

# Shop Upgrade Delete Errors
shop_cannot_delete_has_player_upgrades = "You cannot delete a shop upgrade that has player upgrades assigned to it"
shop_cannot_delete_has_unit_type_associations = "You cannot delete a shop upgrade that has unit type associations assigned to it"

# Navigation
shop_previous_button = "Previous"
shop_next_button = "Next"

# Status Messages
shop_upgrade_type_status = "Upgrade Type: {type}"
shop_disabled_status = "Disabled: {status}"
shop_repeatable_status = "Repeatable: {status}"
shop_please_select_unit_type = "Please select a unit type"
shop_please_select_upgrade_type = "Please select an upgrade type"

# Import any other user template overrides
try:
    from user_templates import * #type: ignore
except ImportError:
    pass
