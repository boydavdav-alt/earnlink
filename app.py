import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from datetime import datetime

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect('earnlink.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            points INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by TEXT,
            momo_number TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            momo_number TEXT,
            status TEXT DEFAULT 'pending',
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referral_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            points_awarded INTEGER DEFAULT 20,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referrer_id) REFERENCES users (user_id),
            FOREIGN KEY (referred_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

def get_db():
    conn = sqlite3.connect('earnlink.db')
    conn.row_factory = sqlite3.Row
    return conn

def make_code(user_id):
    return f"EL{user_id}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "NoUsername"
    first_name = user.first_name or "User"
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id =?", (user_id,))
    exists = cur.fetchone()
    
    if not exists:
        ref_by_code = None
        if context.args and len(context.args) > 0:
            ref_by_code = context.args[0]
            cur.execute("SELECT user_id FROM users WHERE referral_code =?", (ref_by_code,))
            referrer = cur.fetchone()
            if referrer and referrer['user_id']!= user_id:
                referrer_id = referrer['user_id']
                cur.execute("UPDATE users SET points = points + 20 WHERE user_id =?", (referrer_id,))
                cur.execute("INSERT INTO referral_log (referrer_id, referred_id) VALUES (?,?)", (referrer_id, user_id))
                logger.info(f"User {referrer_id} got 20 points for referring {user_id}")
        
        code = make_code(user_id)
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, points, referral_code, referred_by) VALUES (?,?,?, 0,?,?)", 
            (user_id, username, first_name, code, ref_by_code)
        )
        conn.commit()
        
        text = (
            f"🎉 Welcome to EarnLink, {first_name}!\n\n"
            f"💰 Earn 20 points for every friend you invite!\n\n"
            f"🔗 Your referral link:\n"
            f"https://t.me/EarnlinkMoneyBot?start={code}\n\n"
            f"📱 Commands:\n"
            f"/balance - Check your points\n"
            f"/ref - Get your referral link\n"
            f"/withdraw - Cash out to Mobile Money\n"
            f"/leaderboard - Top earners"
        )
        
        keyboard = [
            [InlineKeyboardButton("💰 Check Balance", callback_data='balance')],
            [InlineKeyboardButton("🔗 Get Referral Link", callback_data='ref')]
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        
    else:
        await update.message.reply_text(
            f"👋 Welcome back, {first_name}!\n\n"
            f"Use /balance to check points\n"
            f"Use /ref to get your link\n"
            f"Use /withdraw to cash out"
        )
    conn.close()

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    user_id = update.effective_user.id
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT points, referral_code FROM users WHERE user_id =?", (user_id,))
    res = cur.fetchone()
    conn.close()
    
    if res:
        text = f"💰 Your Balance\n\nPoints: {res['points']}\nCode: {res['referral_code']}\n\n1 point = 1 FCFA\nMin withdrawal: 100 points"
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await msg.reply_text(text)
    else:
        await msg.reply_text("❌ Send /start first")

async def ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    user_id = update.effective_user.id
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT referral_code, points FROM users WHERE user_id =?", (user_id,))
    res = cur.fetchone()
    conn.close()
    
    if res:
        link = f"https://t.me/EarnlinkMoneyBot?start={res['referral_code']}"
        text = f"🔗 Your Referral Link\n\n{link}\n\n📊 Points: {res['points']}\n20 points per friend!"
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await msg.reply_text(text)
    else:
        await msg.reply_text("❌ Send /start first")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args)!= 2:
        await update.message.reply_text(
            "❌ Wrong format!\n\n"
            "✅ Use: /withdraw <points> <momo_number>\n"
            "Example: /withdraw 100 677123456\n\n"
            "Minimum: 100 points"
        )
        return
    
    try:
        amount = int(context.args[0])
        momo = context.args[1].strip()
    except ValueError:
        await update.message.reply_text("❌ Points must be a number. Example: /withdraw 100 677123456")
        return

    if amount < 100:
        await update.message.reply_text("❌ Minimum withdrawal is 100 points.")
        return
    
    if not momo.isdigit() or len(momo) < 9:
        await update.message.reply_text("❌ Invalid MTN number. Example: 677123456")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT points FROM users WHERE user_id =?", (user_id,))
    res = cur.fetchone()
    
    if not res:
        await update.message.reply_text("❌ Send /start first")
        conn.close()
        return
    
    pts = res['points']
    if pts < amount:
        await update.message.reply_text(f"❌ Not enough points.\n\nYour balance: {pts} points\nRequested: {amount} points")
        conn.close()
        return
    
    new_bal = pts - amount
    cur.execute("UPDATE users SET points =?, momo_number =? WHERE user_id =?", (new_bal, momo, user_id))
    cur.execute("INSERT INTO withdrawals (user_id, amount, momo_number) VALUES (?,?,?)", (user_id, amount, momo))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ Withdrawal Requested!\n\n"
        f"💰 Amount: {amount} FCFA\n"
        f"📱 MTN MoMo: {momo}\n"
        f"📊 New Balance: {new_bal} points\n"
        f"⏰ Status: Pending\n\n"
        f"Paid within 24 hours."
    )
    logger.info(f"Withdrawal: User {user_id} requested {amount} to {momo}")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, first_name, points FROM users ORDER BY points DESC LIMIT 10")
    top = cur.fetchall()
    conn.close()
    
    if not top:
        await update.message.reply_text("No users yet. Be the first!")
        return
    
    text = "🏆 Top 10 Earners\n\n"
    for i, u in enumerate(top, 1):
        name = u['first_name'] or u['username'] or "Anonymous"
        text += f"{i}. {name} - {u['points']} points\n"
    
    await update.message.reply_text(text)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'balance':
        await balance(update, context)
    elif query.data == 'ref':
        await ref(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("ref", ref))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CallbackQueryHandler(button))
    app.add_error_handler(error_handler)
    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
