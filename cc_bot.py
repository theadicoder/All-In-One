import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import asyncio
import json
from requests.exceptions import RequestException
from telegram.error import InvalidToken
import httpx
import os
from dotenv import load_dotenv
from faker import Faker
import binlookup
from datetime import datetime, timedelta
import csv
from country_data import SUPPORTED_COUNTRIES
from utils import generate_iban, generate_fake_address
from iban_utils import generate_iban

# Load environment variables
load_dotenv()

# Configure logging with more detail
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Get configuration from environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN not found in environment variables.")
    exit()

ADMIN_USERS = {
    "ZEROFLUX01": -1002805460020,
    "theadicoder": 7108572857,
    "CLOUDxGAURAV": 7950051505
}

def is_admin(user_id: int) -> bool:
    """Check if user is admin by ID"""
    return user_id in ADMIN_USERS.values()

# Update environment variables handling
ADMIN_USER_IDS_STR = os.getenv('ADMIN_USER_IDS', '')
ADMIN_USER_IDS = set(map(int, ADMIN_USER_IDS_STR.split(','))) if ADMIN_USER_IDS_STR else set()

if not ADMIN_USER_IDS:
    logger.warning("No admin IDs found in environment variables. Using hardcoded admin IDs.")
    ADMIN_USER_IDS = {-1002805460020, 7108572857, 7950051505}  # Fallback to hardcoded values

# --- Constants for Messages ---
MSG_PROVIDE_CC = "Please provide a card number to check. Usage: /chk <card_number>"
MSG_PROVIDE_BIN = "Please provide a BIN number. Usage: /bin <bin>"
MSG_PROVIDE_BIN_FOR_GEN = "Please provide a BIN to generate cards from. Usage: /gen <bin>"
MSG_INVALID_BIN = "Invalid BIN. It must be a 6-digit number."
MSG_INVALID_CC = "Invalid card number. It must be a 15 or 16-digit number."
MSG_PROVIDE_MASS_CC = """Please provide cards in format:
/masscheck
cc|mm|yy|cvv
cc|mm|yy|cvv
...etc

Example:
/masscheck
4532515244633735|03|2025|772
4532515677883754|11|2024|227"""

CHARGE_AMOUNTS = [0.5, 1, 2, 5, 10]  # Default charge amounts in USD
CARD_BRANDS = {
    '4': 'VISA',
    '5': 'MASTERCARD',
    '3': 'AMEX',
    '6': 'DISCOVER'
}

# --- In-memory Storage ---
POSTS_FILE = "posts.json"
CARDS_FILE = "cards.json"
USERS_FILE = "users.json"
STATS_FILE = "bot_stats.csv"

def load_data(filename: str) -> list:
    """Loads data from a JSON file."""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_data(data: list, filename: str):
    """Saves data to a JSON file."""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

POSTS = load_data(POSTS_FILE)
PRE_GENERATED_CARDS = load_data(CARDS_FILE)
USER_DATA = load_data(USERS_FILE) or {}  # Dictionary to store user data

BOT_STATS = {
    'total_users': 0,
    'active_users': 0,
    'new_users_today': 0,
    'cards_generated': 0,
    'last_update': str(datetime.now())
}

# --- Panel/Keyboard Layouts ---
def get_main_menu_keyboard(user_id: int = None):
    keyboard = [
        [InlineKeyboardButton("📜 Methods", callback_data='show_methods'), 
         InlineKeyboardButton("💳 Generated CC", callback_data='show_generated_cc')],
        [InlineKeyboardButton("📝 Posts", callback_data='show_posts'),
         InlineKeyboardButton("⚙️ CC Generation Service", callback_data='show_services')],
        [InlineKeyboardButton("📋 Commands", callback_data='show_commands')]  # New commands button
    ]
    
    # Add admin-only button if user is admin
    if user_id and is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 Admin Stats", callback_data='admin_stats')])
    
    keyboard.append([InlineKeyboardButton("🔗 Channel Links", callback_data='show_links')])
    return InlineKeyboardMarkup(keyboard)

def get_back_to_menu_keyboard():
    keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='main_menu')]]
    return InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu."""
    user = update.effective_user
    update_user_stats(user)  # Track user interaction
    
    reply_markup = get_main_menu_keyboard(user.id)  # Pass user.id here
    if is_admin(user.id):
        welcome_text = (
            "👋 Welcome Admin!\n\n"
            "You have access to these special commands:\n"
            "• /method - Post methods (supports text, photos, videos, files)\n"
            "• /post - Post regular updates\n"
            "• /export_stats - Export user statistics\n"
            "• Other admin features are available in the menu"
        )
    else:
        welcome_text = "👋 Welcome to the All-in-One Bot! Please choose an option:"
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    try:
        # Try to answer the callback query with a small timeout
        await query.answer()  # Remove timeout parameter
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")
        # Continue execution even if answering fails
        pass

    try:
        if query.data == 'main_menu':
            await query.edit_message_text(
                "👋 Welcome back! Please choose an option:", 
                reply_markup=get_main_menu_keyboard(query.from_user.id)
            )

        elif query.data.startswith('delete_post_'):
            user_id = str(query.from_user.id)
            if user_id not in ADMIN_USER_IDS:
                await query.answer("You are not authorized to perform this action.", show_alert=True)
                return
            
            post_index = int(query.data.split('_')[2])
            if 0 <= post_index < len(POSTS):
                del POSTS[post_index]
                save_data(POSTS, POSTS_FILE)
                await query.answer("Post deleted successfully.")
                # Refresh the methods view
                await show_methods_panel(query, user_id)

        elif query.data == 'show_methods':
            user_id = str(query.from_user.id)
            await show_methods_panel(query, user_id)

        elif query.data == 'show_generated_cc':
            if not PRE_GENERATED_CARDS:
                text = "No cards have been pre-generated yet. Check back later!"
            else:
                text = "💳 **Pre-Generated Cards**\n\n" + "\n".join(PRE_GENERATED_CARDS)
            await query.edit_message_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode='Markdown')

        elif query.data == 'show_services':
            text = (
                "⚙️ **CC Generation Services**\n\n"
                "Here are the services used by this bot:\n\n"
                "🔹 **/chk**: Placeholder for a real card checking API.\n"
                "🔹 **/bin**: `binlist.net` API for BIN details.\n"
                "🔹 **/gen**: Internal Luhn algorithm generator.\n"
            )
            await query.edit_message_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode='Markdown')

        elif query.data == 'show_links':
            text = (
                "🔗 **Channel & Bot Links**\n\n"
                "Join our main channel:\n"
                "➡️ https://t.me/ZEROFLUX01\n\n"
                "Join our backup channel:\n"
                "➡️ https://t.me/+BkKPvi3tPNEzMDg1\n\n"
                "To buy premium services, contact our bot:\n"
                "➡️ @AdityaPremiumbot"
            )
            await query.edit_message_text(text, reply_markup=get_back_to_menu_keyboard(), disable_web_page_preview=True)

        elif query.data == 'show_posts':
            if not POSTS:
                text = "No posts available yet."
            else:
                text = "📝 **Latest Posts**\n\n" + "\n\n---\n\n".join(POSTS)
            await query.edit_message_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode='Markdown')

        elif query.data == 'admin_stats':
            if not is_admin(query.from_user.id):
                await query.answer("Access denied", show_alert=True)
                return
            
            # Generate current stats
            active_threshold = datetime.now() - timedelta(days=7)
            active_users = sum(1 for data in USER_DATA.values() 
                              if datetime.fromisoformat(data['last_active']) > active_threshold)
            
            stats_text = (
                "Admin Statistics\n\n"  # Removed fancy formatting
                f"Total Users: {len(USER_DATA)}\n"
                f"Active Users (7d): {active_users}\n"
                f"New Users Today: {BOT_STATS['new_users_today']}\n"
                f"Cards Generated: {BOT_STATS['cards_generated']}\n\n"
                "Use /export_stats to get detailed CSV report"
            )
            
            keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='main_menu')]]
            try:
                await query.edit_message_text(
                    text=stats_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=None  # Removed Markdown to avoid parsing issues
                )
            except Exception as e:
                logger.error(f"Error displaying admin stats: {e}")
                await query.edit_message_text(
                    "Error displaying statistics. Please try again.",
                    reply_markup=get_back_to_menu_keyboard()
                )
        elif query.data == 'show_commands':
            try:
                commands_text = (
                    "🤖 Available Commands\n\n"
                    "Basic Commands:\n"
                    "• /start - Start the bot and show main menu\n"
                    "• /chk - Check a single card\n"
                    "• /bin - Look up BIN information\n"
                    "• /gen - Generate cards from a BIN\n"
                    "• /masscheck - Check multiple cards\n"
                    "• /fake - Generate fake address\n"
                    "• /me - Show your user information\n"
                    "• /commands - Show this help message\n\n"
                    
                    "Usage Examples:\n"
                    "Single Check:\n"
                    "/chk 4532515244633735|03|2025|772\n\n"
                    "Mass Check:\n"
                    "/masscheck\n"
                    "4532515244633735|03|2025|772\n"
                    "4532515677883754|11|2024|227\n\n"
                    "Generate Cards:\n"
                    "/gen 453251 10\n\n"
                    "BIN Lookup:\n"
                    "/bin 453251"
                )
                
                if is_admin(query.from_user.id):
                    admin_commands = (
                        "\n\nAdmin Commands:\n"
                        "• /method - Post methods (text/media)\n"
                        "• /post - Make announcements\n"
                        "• /export_stats - Export user statistics"
                    )
                    commands_text += admin_commands
                
                await query.edit_message_text(
                    text=commands_text,
                    reply_markup=get_back_to_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"Error showing commands: {str(e)}")
                await query.edit_message_text(
                    "Error displaying commands. Please try again.",
                    reply_markup=get_back_to_menu_keyboard()
                )
    except Exception as e:
        logger.error(f"Error handling button click: {e}")
        try:
            await query.edit_message_text(
                "An error occurred. Please try again.",
                reply_markup=get_back_to_menu_keyboard()
            )
        except:
            pass

# Add error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "Sorry, an error occurred while processing your request."
            )
    except:
        pass

async def method_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to post methods with media support."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    
    message = update.message
    
    # Handle different types of media
    if message.text and len(message.text.split()) > 1:
        # Text method
        method_text = " ".join(message.text.split()[1:])
        POSTS.insert(0, method_text)
        await message.reply_text("✅ Method posted successfully!")
    
    elif message.photo:
        # Photo with caption
        photo = message.photo[-1]  # Get the highest quality photo
        caption = message.caption or "New method shared by admin"
        method_content = {
            'type': 'photo',
            'file_id': photo.file_id,
            'caption': caption
        }
        POSTS.insert(0, json.dumps(method_content))
        await message.reply_text("✅ Photo method posted successfully!")
    
    elif message.video:
        # Video with caption
        video = message.video
        caption = message.caption or "New video method shared by admin"
        method_content = {
            'type': 'video',
            'file_id': video.file_id,
            'caption': caption
        }
        POSTS.insert(0, json.dumps(method_content))
        await message.reply_text("✅ Video method posted successfully!")
    
    elif message.document:
        # Document/File
        doc = message.document
        caption = message.caption or f"New file: {doc.file_name}"
        method_content = {
            'type': 'document',
            'file_id': doc.file_id,
            'caption': caption,
            'filename': doc.file_name
        }
        POSTS.insert(0, json.dumps(method_content))
        await message.reply_text("✅ File method posted successfully!")
    
    else:
        usage_text = (
            "Usage:\n"
            "• Send text: /method <your text>\n"
            "• Send media: /method + attach photo/video\n"
            "• Send file: /method + attach file\n"
            "\nYou can add captions to media/files."
        )
        await message.reply_text(usage_text)
    
    save_data(POSTS, POSTS_FILE)

async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command for regular posts."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /post <your announcement>")
        return
    
    post_text = " ".join(context.args)
    post_content = {
        'type': 'text',
        'content': post_text,
        'timestamp': str(datetime.now())
    }
    
    POSTS.insert(0, json.dumps(post_content))
    save_data(POSTS, POSTS_FILE)
    await update.message.reply_text("✅ Post published successfully!")

async def show_methods_panel(query, user_id: str):
    """Helper function to display the methods panel for users or admins."""
    if not POSTS:
        text = "No methods have been posted yet."
        await query.edit_message_text(text, reply_markup=get_back_to_menu_keyboard())
        return

    try:
        messages = []
        for post in POSTS:
            try:
                post_data = json.loads(post)
                if isinstance(post_data, dict):
                    if post_data['type'] == 'text':
                        messages.append(post_data['content'])
                    else:
                        messages.append(f"[{post_data['type'].upper()}] {post_data['caption']}")
                else:
                    messages.append(post)  # Legacy text post
            except json.JSONDecodeError:
                messages.append(post)  # Legacy text post
        
        if is_admin(int(user_id)):
            text = "📜 **Admin: Manage Posts**\n\n"
            keyboard = []
            for i, _ in enumerate(messages):
                keyboard.append([InlineKeyboardButton(f"❌ Delete #{i+1}", callback_data=f'delete_post_{i}')])
            keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='main_menu')])
            await query.edit_message_text(
                text + "\n\n---\n\n".join(messages),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            text = "📜 **Latest Methods & Posts**\n\n"
            await query.edit_message_text(
                text + "\n\n---\n\n".join(messages),
                reply_markup=get_back_to_menu_keyboard(),
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error showing methods panel: {e}")
        await query.edit_message_text(
            "An error occurred while displaying posts.",
            reply_markup=get_back_to_menu_keyboard()
        )

async def check_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check card with improved error handling"""
    msg = None
    try:
        if not context.args:
            await update.message.reply_text(MSG_PROVIDE_CC)
            return

        full_input = " ".join(context.args)
        parts = [p.strip() for p in full_input.replace(' ', '|').replace('/', '|').split('|') if p]

        card_number = parts[0] if len(parts) > 0 else ""
        exp_month = parts[1] if len(parts) > 1 else "N/A"
        exp_year = parts[2] if len(parts) > 2 else "N/A"
        cvv = parts[3] if len(parts) > 3 else "N/A"

        if not card_number.isdigit() or len(card_number) not in [15, 16]:
            await update.message.reply_text(MSG_INVALID_CC)
            return

        card_display = f"`{card_number}|{exp_month}|{exp_year}|{cvv}`"
        msg = await update.message.reply_text(
            f"🔍 Initializing check for {card_display}...\n"
            "⏳ Running security checks...", 
            parse_mode='Markdown'
        )

        # Enhanced check simulation with fallback
        bin_info = await fetch_bin_info_async(card_number[:6]) or {
            'scheme': get_card_brand(card_number),
            'type': 'UNKNOWN',
            'bank': {'name': 'Unknown Bank'},
            'country': {'name': 'Unknown', 'emoji': ''}
        }

        await msg.edit_text(f"{msg.text}\n✅ BIN data retrieved", parse_mode='Markdown')
        await asyncio.sleep(1.5)

        # Enhanced result generation
        is_live = random.choices([True, False], weights=[65, 35])[0]
        auth_code = generate_auth_code() if is_live else None
        charge_amount = random.choice(CHARGE_AMOUNTS)
        gateway = random.choice(["Stripe", "Braintree", "Square", "PayPal"])
        
        if is_live:
            title = "𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅"
            response_msg = f"Payment Method Added - Auth: {auth_code}"
            charge_status = f"${charge_amount:.2f} Authorization: Successful"
        else:
            title = "𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌"
            decline_reasons = [
                "Insufficient funds",
                "Card declined",
                "Security check failed",
                "Invalid card",
                "Expired card"
            ]
            response_msg = random.choice(decline_reasons)
            charge_status = "Authorization failed"

        response_lines = [
            f"𝗖𝗮𝗿𝗱: {card_display}",
            f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲: {gateway}",
            f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {response_msg}",
            f"𝐂𝐡𝐚𝐫𝐠𝐞: {charge_status}",
            "",
            f"𝗜𝗻𝗳𝗼: {bin_info.get('scheme', 'UNKNOWN')} - {bin_info.get('type', 'UNKNOWN')}",
            f"𝟯𝗗 𝗦𝗲𝗰𝘂𝗿𝗲: {'VBV' if random.random() > 0.7 else 'Non-VBV'}",
            f"𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get('bank', {}).get('name', 'Unknown Bank')}",
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get('country', {}).get('name', 'Unknown')} {bin_info.get('country', {}).get('emoji', '')}"
        ]

        if auth_code:
            response_lines.append(f"𝐀𝐮𝐭𝐡 𝐂𝐨𝐝𝐞: {auth_code}")

        final_text = f"{title}\n\n" + "\n".join(response_lines)
        await msg.edit_text(final_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in check_card: {str(e)}", exc_info=True)
        if msg:
            await msg.edit_text(
                f"Error checking card. Please try again.\nCard: {card_display}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("Error processing your request. Please try again.")

async def iban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate IBAN for specified country"""
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a country code.\n"
            "Usage: /iban <country_code>\n"
            "Supported countries: DE, FR, GB, IT, ES, NL, BE, US"
        )
        return

    country_code = context.args[0].upper()
    iban, success = generate_iban(country_code)
    
    if success:
        await update.message.reply_text(
            f"🏦 Generated IBAN for {country_code}:\n`{iban}`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ Invalid country code.\n"
            "Supported countries: DE, FR, GB, IT, ES, NL, BE, US"
        )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot commands menu"""
    menu_text = """📜 BOT COMMANDS MENU

💳 BIN Info
├ Command : /bin {6-digit}
└ Example : /bin 412236

🔐 CC Generator
├ Command : /gen BIN|MM|YYYY|CVV
└ Example : /gen 412236xxxx|xx|2025|xxx

ℹ️ IBAN Generator
├ Command : /iban COUNTRY_CODE
└ Example : /iban de

📍 Fake Address
├ Command : /fake {country_code}
├ Example : /fake bd
└ Example : /fake us

👤 Profile Info
└ Command : /me

📌 Menu
└ Command : /menu"""

    await update.message.reply_text(menu_text)

async def process_mass_check(cards: list) -> list:
    """Process multiple cards through Stripe B3 gate simulation"""
    results = []
    for card in cards:
        parts = card.strip().split('|')
        if len(parts) != 4:
            results.append(f"❌ Invalid format: {card}")
            continue

        cc, mm, yy, cvv = parts
        if not cc.isdigit() or len(cc) not in [15, 16]:
            results.append(f"❌ Invalid card number: {card}")
            continue

        # Stripe auth simulation with B3 gate specifics
        is_live = random.choices([True, False], weights=[55, 45])[0]
        auth_code = generate_auth_code() if is_live else None
        gateway = "Stripe B3"
        charge = random.uniform(0.5, 2.0)

        if is_live:
            results.append(
                f"✅ {cc}|{mm}|{yy}|{cvv} - Approved\n"
                f"Gateway: {gateway}\n"
                f"Amount: ${charge:.2f}\n"
                f"Auth: {auth_code}"
            )
        else:
            decline_reasons = [
                "Do not honor", 
                "Card declined", 
                "Insufficient funds",
                "Suspected fraud",
                "Card not supported"
            ]
            results.append(
                f"❌ {cc}|{mm}|{yy}|{cvv} - Declined\n"
                f"Gateway: {gateway}\n"
                f"Message: {random.choice(decline_reasons)}"
            )
        
        # Add delay between checks to avoid rate limiting
        await asyncio.sleep(1.5)

    return results

# Add this new command handler
async def mass_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mass card checking through Stripe B3 gate"""
    message_text = update.message.text
    
    # Check if there are cards to process
    if len(message_text.split('\n')) < 2:
        await update.message.reply_text(MSG_PROVIDE_MASS_CC)
        return

    # Get cards from message (skip first line which is command)
    cards = message_text.split('\n')[1:]
    
    # Remove empty lines
    cards = [card.strip() for card in cards if card.strip()]
    
    if not cards:
        await update.message.reply_text("No valid cards provided.")
        return
    
    if len(cards) > 15:
        await update.message.reply_text("Maximum 15 cards allowed per check.")
        return

    msg = await update.message.reply_text(
        f"🔄 Processing {len(cards)} cards through Stripe B3 gate...\n"
        "This may take a few moments."
    )

    try:
        results = await process_mass_check(cards)
        
        # Format results with separators
        formatted_results = "\n\n".join(results)
        response = f"💳 Mass Check Results ({len(cards)} cards):\n\n{formatted_results}"
        
        # Split response if too long
        if len(response) > 4000:
            chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await msg.edit_text(chunk)
                else:
                    await update.message.reply_text(chunk)
        else:
            await msg.edit_text(response)
            
    except Exception as e:
        logger.error(f"Error in mass check: {e}")
        await msg.edit_text("❌ An error occurred while processing cards.")

async def show_commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available commands when /commands is used"""
    commands_text = (
        "🤖 Available Commands\n\n"
        "Basic Commands:\n"
        "• /start - Start the bot and show main menu\n"
        "• /chk - Check a single card\n"
        "• /bin - Look up BIN information\n"
        "• /gen - Generate cards from a BIN\n"
        "• /masscheck - Check multiple cards\n"
        "• /fake - Generate fake address\n"
        "• /me - Show your user information\n"
        "• /commands - Show this help message\n\n"
        
        "Usage Examples:\n"
        "Single Check:\n"
        "/chk 4532515244633735|03|2025|772\n\n"
        "Mass Check:\n"
        "/masscheck\n"
        "4532515244633735|03|2025|772\n"
        "4532515677883754|11|2024|227\n\n"
        "Generate Cards:\n"
        "/gen 453251 10\n\n"
        "BIN Lookup:\n"
        "/bin 453251"
    )
    
    if is_admin(update.effective_user.id):
        admin_commands = (
            "\n\nAdmin Commands:\n"
            "• /method - Post methods (text/media)\n"
            "• /post - Make announcements\n"
            "• /export_stats - Export user statistics"
        )
        commands_text += admin_commands
    
    await update.message.reply_text(commands_text)

def generate_auth_code() -> str:
    """Generate a random auth code"""
    letters = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=2))
    numbers = ''.join(random.choices('0123456789', k=4))
    return f"{letters}{numbers}"

async def update_user_stats(user: User):
    """Update user statistics"""
    now = datetime.now()
    user_id = str(user.id)
    
    if user_id not in USER_DATA:
        USER_DATA[user_id] = {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'first_seen': str(now),
            'last_active': str(now),
            'commands_used': 0
        }
        BOT_STATS['new_users_today'] += 1
    else:
        USER_DATA[user_id]['last_active'] = str(now)
        USER_DATA[user_id]['commands_used'] += 1
    
    save_data(USER_DATA, USERS_FILE)

async def pre_generate_cards_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to pre-generate cards"""
    # Your existing pre-generate cards codeapplication.add_handler(CommandHandler(command, handler))
    pass  # Implement this if not already done

def main():
    try:
        # Create the Application with job queue
        logger.info("Initializing bot...")
        application = Application.builder().token(TOKEN).build()
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Add command handlers
        command_handlers = [
            ("method", method_command),
            ("post", post_command),
            ("start", start),
            ("chk", check_card),
            ("bin", get_bin_info),
            ("gen", generate_cards),
            ("fake", generate_fake_address),
            ("me", user_info),
            ("export_stats", export_stats),
            ("masscheck", mass_check_command),
            ("commands", show_commands_command),
            ("countrycodes", show_country_codes),
            ("iban", iban_command),
            ("menu", menu_command)
        ]
        
        # Register command handlers
        for command, handler in command_handlers:
            application.add_handler(CommandHandler(command, handler))
        
        # Add callback query handler    
        application.add_handler(CallbackQueryHandler(button_handler))

        # Schedule job
        try:
            job = application.job_queue.run_repeating(
                pre_generate_cards_job, 
                interval=3600,
                first=10,
                name='pre_generate_cards'
            )
            logger.info("Successfully scheduled card generation job")
        except Exception as e:
            logger.error(f"Failed to schedule card generation job: {e}")
        
        # Start bot
        logger.info("Bot started successfully. Polling for updates...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.critical(f"An unexpected error occurred while starting the bot: {e}")
        raise

if __name__ == "__main__":
    main()
                "Do not honor", 
                "Card declined", 
                "Insufficient funds",
                "Suspected fraud",
                "Card not supported"
            ]
            results.append(
                f"❌ {cc}|{mm}|{yy}|{cvv} - Declined\n"
                f"Gateway: {gateway}\n"
                f"Message: {random.choice(decline_reasons)}"
            )
        
        # Add delay between checks to avoid rate limiting
        await asyncio.sleep(1.5)

    return results

# Add this new command handler
async def mass_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mass card checking through Stripe B3 gate"""
    message_text = update.message.text
    
    # Check if there are cards to process
    if len(message_text.split('\n')) < 2:
        await update.message.reply_text(MSG_PROVIDE_MASS_CC)
        return

    # Get cards from message (skip first line which is command)
    cards = message_text.split('\n')[1:]
    
    # Remove empty lines
    cards = [card.strip() for card in cards if card.strip()]
    
    if not cards:
        await update.message.reply_text("No valid cards provided.")
        return
    
    if len(cards) > 15:
        await update.message.reply_text("Maximum 15 cards allowed per check.")
        return

    msg = await update.message.reply_text(
        f"🔄 Processing {len(cards)} cards through Stripe B3 gate...\n"
        "This may take a few moments."
    )

    try:
        results = await process_mass_check(cards)
        
        # Format results with separators
        formatted_results = "\n\n".join(results)
        response = f"💳 Mass Check Results ({len(cards)} cards):\n\n{formatted_results}"
        
        # Split response if too long
        if len(response) > 4000:
            chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await msg.edit_text(chunk)
                else:
                    await update.message.reply_text(chunk)
        else:
            await msg.edit_text(response)
            
    except Exception as e:
        logger.error(f"Error in mass check: {e}")
        await msg.edit_text("❌ An error occurred while processing cards.")

async def show_commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available commands when /commands is used"""
    commands_text = (
        "🤖 Available Commands\n\n"
        "Basic Commands:\n"
        "• /start - Start the bot and show main menu\n"
        "• /chk - Check a single card\n"
        "• /bin - Look up BIN information\n"
        "• /gen - Generate cards from a BIN\n"
        "• /masscheck - Check multiple cards\n"
        "• /fake - Generate fake address\n"
        "• /me - Show your user information\n"
        "• /commands - Show this help message\n\n"
        
        "Usage Examples:\n"
        "Single Check:\n"
        "/chk 4532515244633735|03|2025|772\n\n"
        "Mass Check:\n"
        "/masscheck\n"
        "4532515244633735|03|2025|772\n"
        "4532515677883754|11|2024|227\n\n"
        "Generate Cards:\n"
        "/gen 453251 10\n\n"
        "BIN Lookup:\n"
        "/bin 453251"
    )
    
    if is_admin(update.effective_user.id):
        admin_commands = (
            "\n\nAdmin Commands:\n"
            "• /method - Post methods (text/media)\n"
            "• /post - Make announcements\n"
            "• /export_stats - Export user statistics"
        )
        commands_text += admin_commands
    
    await update.message.reply_text(commands_text)

def main():
    try:
        # Create the Application with job queue
        logger.info("Initializing bot...")
        application = Application.builder().token(TOKEN).build()
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Add command handlers
        application.add_handler(CommandHandler("method", method_command))
        application.add_handler(CommandHandler("post", post_command))
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("chk", check_card))
        application.add_handler(CommandHandler("bin", get_bin_info))
        application.add_handler(CommandHandler("gen", generate_cards))
        application.add_handler(CommandHandler("fake", generate_fake_address))
        application.add_handler(CommandHandler("me", user_info))
        application.add_handler(CommandHandler("export_stats", export_stats))
        application.add_handler(CommandHandler("masscheck", mass_check_command))
        application.add_handler(CommandHandler("commands", show_commands_command))  # Add this line
        application.add_handler(CommandHandler("countrycodes", show_country_codes))
        application.add_handler(CommandHandler("iban", iban_command))
        application.add_handler(CommandHandler("menu", menu_command))
        application.add_handler(CallbackQueryHandler(button_handler))

        # Add job queue with proper error handling
        try:
            job = application.job_queue.run_repeating(
                pre_generate_cards_job, 
                interval=3600,  # 1 hour
                first=10,  # Start after 10 seconds
                name='pre_generate_cards'
            )
            logger.info("Successfully scheduled card generation job")
        except Exception as e:
            logger.error(f"Failed to schedule card generation job: {e}")
        
        logger.info("Bot started successfully. Polling for updates...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.critical(f"An unexpected error occurred while starting the bot: {e}")
        raise

if __name__ == "__main__":
    main()
