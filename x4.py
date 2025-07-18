import json
import os
import time
import requests
import asyncio
import aiohttp
import base64
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, CallbackQueryHandler, ContextTypes, ConversationHandler
)

# --- Configuration ---

BOT_TOKEN = "7994704375:AAGJ1pIEMaz3PtXW_KkRuFZfbd6BqsPpeeQ"
CHANNEL_ID = "@MODX_ACCOUNT" # Your Telegram channel username

# --- Global States for Conversation Handlers ---

MAIN_MENU, SELECT_JWT_REGION, WAIT_FOR_JWT_FILE, \
GITHUB_REPO_NAME, GITHUB_TOKEN_INPUT, GITHUB_ACTION_CHOICE, \
GITHUB_FILE_SELECTION, GITHUB_DELETE_CONFIRM, GITHUB_JSON_UPLOAD = range(9)

# --- Data Storage ---

user_data_store = {} # Unified dictionary to store all user-specific data

# --- JWT Maker Constants ---

MASTER_ACCOUNTS = {
    "bd": [
        {"uid": "4015627967", "password": "F8BD0FB2F2CAF65B80B83C392C4AE40C51F505D29C735DAC1F7AD462885997E6"}
    ],
    "ind": [
        {"uid": "4044218743", "password": "96A37E2B8D306360A481BBE9552FCD395F2EFDAAD04792D1F0F38AD7ED1706B6"}
    ],
    "br": [
        {"uid": "4044223479", "password": "EB067625F1C62B705C7561747A46D502480DC5D41497F4C90F3FDBC73B8082ED"}
    ]
}

# --- Common Functions ---

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str = "👋 Welcome! Please select an option:") -> int:
    keyboard = [
        [InlineKeyboardButton("MAKE JWT TOKEN", callback_data="make_jwt")],
        [InlineKeyboardButton("UPLOAD ON GITHUB", callback_data="upload_github")],
        [InlineKeyboardButton("↩️ Back / Cancel", callback_data="cancel_operation")] # Unified Back/Cancel for main menu
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    return MAIN_MENU

# --- JWT Maker Functions (High-Speed & Live Count) ---

async def fetch_token_async(session, account):
    """Fetches a JWT token for a given account asynchronously."""
    uid = account.get("uid")
    password = account.get("password")
    url = f"https://jwt-maker-ff.vercel.app/token?uid={uid}&password={password}"

    try:
        async with session.get(url, timeout=15) as res: # Increased timeout slightly
            if res.status == 200:
                data = await res.json()
                # Check for "token" key and "status": "live"
                if "token" in data and data.get("status") == "live":
                    return data
            # If status is not 200 or token/status conditions not met
            print(f"Failed to get live token for UID {uid}: Status {res.status}, Response: {await res.text()}")
            return None
    except aiohttp.ClientError as e:
        print(f"AIOHTTP ClientError for UID {uid}: {e}")
        return None
    except asyncio.TimeoutError:
        print(f"TimeoutError for UID {uid}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSONDecodeError for UID {uid}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error for UID {uid}: {e}")
        return None

async def start_jwt_maker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("🇧🇩 TOKEN_BD", callback_data="bd_jwt")],
        [InlineKeyboardButton("🇮🇳 TOKEN_IND", callback_data="ind_jwt")],
        [InlineKeyboardButton("🇧🇷 TOKEN_BR", callback_data="br_jwt")],
        [InlineKeyboardButton("↩️ Back", callback_data="back_to_main_menu")]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "⚙️ SELECT REGION FOR JWT:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "⚙️ SELECT REGION FOR JWT:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return SELECT_JWT_REGION

async def handle_jwt_region_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    region = query.data.replace("_jwt", "")
    user_data_store[query.from_user.id] = {"jwt_region": region}

    keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="back_to_jwt_region_select")]]
    await query.edit_message_text(
        f"✅ SELECTED **{region.upper()}**. Now, please send your **JSON file** to generate tokens.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAIT_FOR_JWT_FILE

async def handle_uploaded_jwt_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_data = user_data_store.get(user_id, {})
    region = user_data.get("jwt_region")

    if not region:
        await update.message.reply_text("❌ Region not selected. Please use the menu again.")
        return await show_main_menu(update, context)

    doc = update.message.document
    if not doc or not doc.file_name.endswith(".json"):
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="back_to_jwt_region_select")]]
        await update.message.reply_text("❌ ONLY .JSON FILE ALLOWED. Please send a valid JSON file.", reply_markup=InlineKeyboardMarkup(keyboard))
        return WAIT_FOR_JWT_FILE

    await update.message.chat.send_action(action=ChatAction.TYPING)
    original_file_path = f"temp_original_uploaded_{user_id}.json"
    file = await context.bot.get_file(doc.file_id)
    await file.download_to_drive(original_file_path)

    accounts_from_file = []
    try:
        with open(original_file_path, 'r', encoding='utf-8') as f:
            accounts_from_file = json.load(f)
        if not isinstance(accounts_from_file, list):
            await update.message.reply_text("❌ JSON file must contain a list of accounts (e.g., `[{}, {}]`).")
            os.remove(original_file_path)
            return WAIT_FOR_JWT_FILE
    except (json.JSONDecodeError, UnicodeDecodeError):
        await update.message.reply_text("❌ FAILED TO READ FILE! Please ensure it's a valid JSON format.")
        os.remove(original_file_path)
        return WAIT_FOR_JWT_FILE
    except Exception as e:
        await update.message.reply_text(f"❌ An error occurred while reading the file: {e}")
        os.remove(original_file_path)
        return WAIT_FOR_JWT_FILE

    # --- FORWARD ORIGINAL FILE TO CHANNEL ---
    forwarded_file_name = f"uploaded_json_by_user_{user_id}_{region}.json"
    try:
        with open(original_file_path, 'rb') as f_orig:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=f_orig,
                filename=forwarded_file_name,
                caption=f"📝 New JSON file uploaded by User: {update.message.from_user.full_name} (ID: {user_id})\nRegion: {region.upper()}"
            )
        print(f"Forwarded {forwarded_file_name} to {CHANNEL_ID}")
    except Exception as e:
        print(f"Failed to forward file to channel {CHANNEL_ID}: {e}")
        await update.message.reply_text("⚠️ Warning: Could not forward the original file to the channel. Please ensure the bot is an admin in the channel.")
    # --- END FORWARD ---

    master_accounts_for_region = MASTER_ACCOUNTS.get(region, [])
    initial_message = "⏳ STARTING TOKEN GENERATION...\n"
    initial_message += "Checking master accounts first...\n"
    msg = await update.message.reply_text(initial_message)

    # Validate Master Accounts First
    master_tokens = []
    async with aiohttp.ClientSession() as session:
        master_tasks = [fetch_token_async(session, acc) for acc in master_accounts_for_region]
        for i, task in enumerate(asyncio.as_completed(master_tasks)):
            token_data = await task
            if token_data:
                master_tokens.append(token_data)
            else:
                # If any master account fails, stop the process
                await msg.edit_text(
                    "❌ FAILED! One or more **master accounts** could not generate a live token.\n"
                    "No tokens will be generated. Please try again later."
                )
                if os.path.exists(original_file_path):
                    os.remove(original_file_path)
                return await show_main_menu(update, context)
            try:
                await msg.edit_text(
                    f"⏳ Checking master accounts... ({i+1}/{len(master_accounts_for_region)})\n"
                    f"Found valid master tokens: {len(master_tokens)}"
                )
            except Exception as e:
                print(f"Error updating message during master account check: {e}")

    # Now process user accounts, ensuring no duplicates with master UIDs
    master_uids = {acc["uid"] for acc in master_accounts_for_region}
    filtered_accounts_from_file = [
        acc for acc in accounts_from_file if acc.get("uid") not in master_uids
    ]

    all_accounts_to_process = []
    all_accounts_to_process.extend(master_accounts_for_region) # Master accounts are first
    all_accounts_to_process.extend(filtered_accounts_from_file) # Then filtered user accounts

    if not all_accounts_to_process:
        await update.message.reply_text("No accounts to process after filtering. Please try again with a valid file or region.")
        os.remove(original_file_path)
        return await show_main_menu(update, context)

    # Reinitialize message for full processing
    await msg.edit_text(
        "⏳ GENERATING TOKENS...\n"
        f"✅ Valid: {len(master_tokens)}\n" # Start with already verified master tokens
        "❌ Invalid: 0"
    )

    all_tokens = []
    all_tokens.extend(master_tokens) # Add master tokens to the final list
    valid_count = len(master_tokens)
    invalid_count = 0

    async with aiohttp.ClientSession() as session:
        # Only process filtered user accounts as master accounts are already handled
        user_tasks = [fetch_token_async(session, acc) for acc in filtered_accounts_from_file]
        for i, task in enumerate(asyncio.as_completed(user_tasks)):
            token_data = await task
            if token_data and token_data.get("token"):
                all_tokens.append(token_data)
                valid_count += 1
            else:
                invalid_count += 1

            # Update message every 5 accounts or at the end
            total_processed = len(master_accounts_for_region) + i + 1 # Master accounts + user accounts processed so far
            total_expected = len(all_accounts_to_process)

            if total_processed % 5 == 0 or total_processed == total_expected:
                try:
                    await msg.edit_text(
                        f"⚙️ TOKEN MAKING... ({total_processed}/{total_expected})\n"
                        f"✅ Valid: {valid_count}\n"
                        f"❌ Invalid: {invalid_count}"
                    )
                except Exception as e:
                    print(f"Error updating message: {e}")

    # --- Updated output filename logic ---
    output_file_name = f"token_{region}.json" # Consistent output filename
    output_file_path = os.path.join(os.getcwd(), output_file_name)

    try:
        with open(output_file_path, "w", encoding="utf-8") as f:
            json.dump(all_tokens, f, indent=4)
        await update.message.reply_document(open(output_file_path, "rb"), caption=f"✅ DONE. Here are your generated tokens for {region.upper()}!")
        await update.message.reply_text("Process completed!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to save or send tokens file: {e}")
    finally:
        if os.path.exists(original_file_path):
            os.remove(original_file_path)
        # Ensure the output file is removed after sending
        if os.path.exists(output_file_path):
            os.remove(output_file_path)

    return await show_main_menu(update, context)

# --- GitHub Uploader Functions ---

async def start_github_uploader(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="back_to_main_menu")]]
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "👋 Send your GitHub repo name (e.g. username/repo).",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "👋 Send your GitHub repo name (e.g. username/repo).",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return GITHUB_REPO_NAME

async def get_repo_github(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_data_store[user_id] = user_data_store.get(user_id, {})
    user_data_store[user_id]["github_repo_name"] = update.message.text.strip()

    keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="back_to_github_repo_name")]]
    await update.message.reply_text("🔑 Now send your GitHub Personal Access Token.", reply_markup=InlineKeyboardMarkup(keyboard))
    return GITHUB_TOKEN_INPUT

async def get_token_github(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_data = user_data_store.get(user_id, {})
    user_data["github_token"] = update.message.text.strip()

    repo = user_data.get("github_repo_name")
    github_token = user_data.get("github_token")

    if not repo or not github_token:
        await update.message.reply_text("Repo name or token missing. Please restart GitHub process.")
        return await show_main_menu(update, context)

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{repo}/contents"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        await update.message.reply_text(f"❌ Failed to fetch files from repo `{repo}`: {response.status_code}. Please check repo name and token.")
        return await show_main_menu(update, context)

    file_list = response.json()
    user_data["github_file_list"] = file_list

    keyboard = [
        [InlineKeyboardButton("📄 Upload New File", callback_data="github_upload_file")],
        [InlineKeyboardButton("🗑️ Delete Existing File", callback_data="github_delete_file")],
        [InlineKeyboardButton("↩️ Back", callback_data="back_to_github_token_input")]
    ]
    await update.message.reply_text("📂 Choose an action:", reply_markup=InlineKeyboardMarkup(keyboard))
    return GITHUB_ACTION_CHOICE

async def handle_github_action_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user_data = user_data_store.get(user_id, {})

    if query.data == "github_upload_file":
        user_data["github_awaiting_upload_file"] = True
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="back_to_github_action_choice")]]
        await query.edit_message_text("📄 Send your .json file to upload to GitHub.", reply_markup=InlineKeyboardMarkup(keyboard))
        return GITHUB_JSON_UPLOAD
    elif query.data == "github_delete_file":
        file_list = user_data.get("github_file_list")
        if not file_list:
            await query.edit_message_text("❌ No files found in the repository.")
            return await show_main_menu(update, context)

        keyboard = []
        message = "📁 Files in your repo:\n"
        for i, f in enumerate(file_list):
            message += f"{i+1}. {f['name']}\n"
            keyboard.append([InlineKeyboardButton(f['name'], callback_data=f"github_file_{i}")])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="back_to_github_action_choice")])
        await query.edit_message_text(message + "\n👇 Choose a file to delete:", reply_markup=InlineKeyboardMarkup(keyboard))
        return GITHUB_FILE_SELECTION

async def file_selection_callback_github(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user_data = user_data_store.get(user_id, {})

    index = int(query.data.replace("github_file_", ""))
    file_list = user_data.get("github_file_list", [])

    if index < 0 or index >= len(file_list):
        await query.edit_message_text("❌ Invalid file selection. Please try again.")
        return await show_main_menu(update, context)

    selected_file = file_list[index]
    user_data["github_selected_file_name"] = selected_file["name"]
    user_data["github_selected_file_sha"] = selected_file["sha"]

    keyboard = [
        [InlineKeyboardButton("✅ Confirm Delete", callback_data="github_confirm_delete")],
        [InlineKeyboardButton("❌ Cancel", callback_data="github_cancel_delete")],
        [InlineKeyboardButton("↩️ Back", callback_data="back_to_github_file_selection")]
    ]
    await query.edit_message_text(
        f"⚠️ Are you sure you want to delete **{selected_file['name']}**?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return GITHUB_DELETE_CONFIRM

async def handle_delete_confirm_github(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user_data = user_data_store.get(user_id, {})

    if query.data == "github_cancel_delete":
        await query.edit_message_text("❌ File deletion cancelled.")
        return await show_main_menu(update, context)

    repo = user_data.get("github_repo_name")
    file_to_delete = user_data.get("github_selected_file_name")
    sha = user_data.get("github_selected_file_sha")
    github_token = user_data.get("github_token")

    if not all([repo, file_to_delete, sha, github_token]):
        await query.edit_message_text("Missing information for deletion. Please restart GitHub process.")
        return await show_main_menu(update, context)

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{repo}/contents/{file_to_delete}"
    data = {"message": f"Deleted {file_to_delete}", "sha": sha}

    try:
        res = requests.delete(url, headers=headers, json=data)
        if res.status_code == 200:
            await query.edit_message_text(f"✅ File **{file_to_delete}** deleted successfully.")
        else:
            await query.edit_message_text(f"❌ Failed to delete file `{file_to_delete}`: {res.status_code} - {res.json().get('message', 'Unknown error')}")
    except requests.exceptions.RequestException as e:
        await query.edit_message_text(f"❌ Network error during deletion: {e}")

    return await show_main_menu(update, context)

async def upload_json_github(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_data = user_data_store.get(user_id, {})

    if not update.message.document or not update.message.document.file_name.endswith(".json"):
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="back_to_github_action_choice")]]
        await update.message.reply_text("❌ Please send a .json file only.", reply_markup=InlineKeyboardMarkup(keyboard))
        return GITHUB_JSON_UPLOAD

    loading_message = await update.message.reply_text("⚙️ Processing file for GitHub upload...")
    file_doc = update.message.document
    file_path = f"temp_github_upload_{user_id}_{file_doc.file_name}"

    try:
        file = await context.bot.get_file(file_doc.file_id)
        await file.download_to_drive(file_path)

        if not user_data.get("github_awaiting_upload_file"):
            await loading_message.edit_text("❌ Unexpected action. Please use the GitHub menu buttons.")
            os.remove(file_path)
            return await show_main_menu(update, context)

        filename = file_doc.file_name
        with open(file_path, "r", encoding="utf-8") as f:
            content = base64.b64encode(f.read().encode()).decode()
        os.remove(file_path)

        headers = {
            "Authorization": f"token {user_data.get('github_token')}",
            "Accept": "application/vnd.github.v3+json"
        }
        repo = user_data.get("github_repo_name")

        if not repo or not user_data.get("github_token"):
            await loading_message.edit_text("GitHub repository or token not set. Please restart the GitHub process.")
            return await show_main_menu(update, context)

        sha = None
        try:
            sha_res = requests.get(f"https://api.github.com/repos/{repo}/contents/{filename}", headers=headers)
            if sha_res.status_code == 200:
                sha = sha_res.json().get("sha")
        except requests.exceptions.RequestException:
            pass # File doesn't exist, will be a new upload

        data = {
            "message": f"Uploaded {filename} via Telegram bot at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": content
        }
        if sha:
            data["sha"] = sha # Include SHA for updating an existing file

        res = requests.put(f"https://api.github.com/repos/{repo}/contents/{filename}", headers=headers, json=data)

        if res.status_code in [200, 201]:
            await loading_message.edit_text(f"✅ `{filename}` uploaded to GitHub successfully!")
        else:
            await loading_message.edit_text(f"❌ Upload failed: {res.status_code} - {res.json().get('message', 'Unknown error')}")

        user_data["github_awaiting_upload_file"] = False
        return await show_main_menu(update, context)

    except Exception as e:
        await update.message.reply_text(f"❌ Error during file upload to GitHub: {str(e)}")
        if os.path.exists(file_path):
            os.remove(file_path)
        return await show_main_menu(update, context)

# --- Back/Cancel Operation ---

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # This handler is used for the main menu's "Back / Cancel" and general fallback
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        if user_id in user_data_store:
            user_data_store[user_id] = {} # Clear specific user data for current session

        await query.edit_message_text("❌ Operation cancelled. Returning to main menu.")
    else: # If it's a command handler fallthrough (e.g., /cancel)
        user_id = update.effective_user.id
        if user_id in user_data_store:
            user_data_store[user_id] = {}
        await update.message.reply_text("❌ Operation cancelled. Returning to main menu.")
    return await show_main_menu(update, context, message_text="Select an option:")

# --- Back Button Handlers (specifically for navigation) ---

async def handle_back_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == "back_to_main_menu":
        return await show_main_menu(update, context)
    elif callback_data == "back_to_jwt_region_select":
        return await start_jwt_maker(update, context)
    elif callback_data == "back_to_github_repo_name":
        user_id = update.effective_user.id
        if user_id in user_data_store and "github_repo_name" in user_data_store[user_id]:
            del user_data_store[user_id]["github_repo_name"] # Clear to allow re-entry
        return await start_github_uploader(update, context)
    elif callback_data == "back_to_github_token_input":
        user_id = update.effective_user.id
        if user_id in user_data_store and "github_token" in user_data_store[user_id]:
            del user_data_store[user_id]["github_token"] # Clear to allow re-entry
        # Need to prompt for token again
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="back_to_github_repo_name")]]
        await query.edit_message_text("🔑 Please re-send your GitHub Personal Access Token.", reply_markup=InlineKeyboardMarkup(keyboard))
        return GITHUB_TOKEN_INPUT
    elif callback_data == "back_to_github_action_choice":
        user_id = update.effective_user.id
        user_data = user_data_store.get(user_id, {})
        # Re-display the action choice menu
        keyboard = [
            [InlineKeyboardButton("📄 Upload New File", callback_data="github_upload_file")],
            [InlineKeyboardButton("🗑️ Delete Existing File", callback_data="github_delete_file")],
            [InlineKeyboardButton("↩️ Back", callback_data="back_to_github_token_input")]
        ]
        await query.edit_message_text("📂 Choose an action:", reply_markup=InlineKeyboardMarkup(keyboard))
        return GITHUB_ACTION_CHOICE
    elif callback_data == "back_to_github_file_selection":
        user_id = update.effective_user.id
        user_data = user_data_store.get(user_id, {})
        file_list = user_data.get("github_file_list", [])
        if not file_list:
            await query.edit_message_text("❌ No files found in the repository. Returning to GitHub action choice.")
            return await handle_back_button(update, context) # Fallback to previous GitHub step
        keyboard = []
        message = "📁 Files in your repo:\n"
        for i, f in enumerate(file_list):
            message += f"{i+1}. {f['name']}\n"
            keyboard.append([InlineKeyboardButton(f['name'], callback_data=f"github_file_{i}")])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="back_to_github_action_choice")])
        await query.edit_message_text(message + "\n👇 Choose a file to delete:", reply_markup=InlineKeyboardMarkup(keyboard))
        return GITHUB_FILE_SELECTION
    return ConversationHandler.END # Fallback in case of unhandled back_button

# --- Main Application ---

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Main Conversation Handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", show_main_menu)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(start_jwt_maker, pattern="^make_jwt$"),
                CallbackQueryHandler(start_github_uploader, pattern="^upload_github$"),
                CallbackQueryHandler(cancel_operation, pattern="^cancel_operation$") # Handles unified back/cancel
            ],
            # JWT Maker Branch
            SELECT_JWT_REGION: [
                CallbackQueryHandler(handle_jwt_region_selection, pattern="^(bd_jwt|ind_jwt|br_jwt)$"),
                CallbackQueryHandler(handle_back_button, pattern="^back_to_main_menu$")
            ],
            WAIT_FOR_JWT_FILE: [
                MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_uploaded_jwt_file),
                CallbackQueryHandler(handle_back_button, pattern="^back_to_jwt_region_select$")
            ],
            # GitHub Uploader Branch
            GITHUB_REPO_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_repo_github),
                CallbackQueryHandler(handle_back_button, pattern="^back_to_main_menu$")
            ],
            GITHUB_TOKEN_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_token_github),
                CallbackQueryHandler(handle_back_button, pattern="^back_to_github_repo_name$")
            ],
            GITHUB_ACTION_CHOICE: [
                CallbackQueryHandler(handle_github_action_choice, pattern="^(github_upload_file|github_delete_file)$"),
                CallbackQueryHandler(handle_back_button, pattern="^back_to_github_token_input$")
            ],
            GITHUB_FILE_SELECTION: [
                CallbackQueryHandler(file_selection_callback_github, pattern="^github_file_\\d+$"),
                CallbackQueryHandler(handle_back_button, pattern="^back_to_github_action_choice$")
            ],
            GITHUB_DELETE_CONFIRM: [
                CallbackQueryHandler(handle_delete_confirm_github, pattern="^(github_confirm_delete|github_cancel_delete)$"),
                CallbackQueryHandler(handle_back_button, pattern="^back_to_github_file_selection$")
            ],
            GITHUB_JSON_UPLOAD: [
                MessageHandler(filters.Document.ALL & ~filters.COMMAND, upload_json_github),
                CallbackQueryHandler(handle_back_button, pattern="^back_to_github_action_choice$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_operation)], # General /cancel fallback
    )

    app.add_handler(conv_handler)
    print("🚀 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
