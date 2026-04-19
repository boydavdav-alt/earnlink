import os
import sqlite3
import secrets
import string
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get('BOT_TOKEN')

def get_db_connection():
    conn = sqlite3.connect('earnlink.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            referral_code TEXT UNIQUE NOT NULL,
            referred_by TEXT,
            points INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def generate_referral_code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    user = update.effective_user
    telegram_id = user.id
    username = user.first_name or user.username or "User"
    
    # Check for referral code from /start ref_CODE
    referred_by = None
    if context.args and len(context.args) > 0:
        referred_by = context.args[0]
    
    conn = get_db_connection()
    
    # Check if user exists
    existing = conn.execute('SELECT * FROM users WHERE telegram_id =?', (telegram_id,)).fetchone()
    
    if existing:
        points = existing['points']
        ref_code = existing['referral_code']
        await update.message.reply_text(
            f"Welcome back {username}! 👋\n\n"
            f"Points: {points}\n"
            f"Your referral code: `{ref_code}`\n"
            f"Share link: t.me/EarnlinkMoneyBot?start={ref_code}\n\n"
            f"Use /balance to check points\n"
            f"Use /leaderboard to see top users",
            parse_mode='Markdown'
        )
        conn.close()
        return
    
    # New user signup
    new_code = generate_referral_code()
    while conn.execute('SELECT id FROM users WHERE referral_code =?', (new_code,)).fetchone():
        new_code = generate_referral_code()
    
    # Validate referrer
    referrer = None
    if referred_by:
        referrer = conn.execute('SELECT telegram_id FROM users WHERE referral_code =?', (referred_by,)).fetchone()
        if referrer and referrer['telegram_id'] == telegram_id:
            referred_by = None # Can't refer yourself
            referrer = None
    
    # Insert new user
    conn.execute(
        'INSERT INTO users (telegram_id, username, referral_code, referred_by, points) VALUES (?,?,?,?, 0)',
        (telegram_id, username, new_code, referred_by)
    )
    
    # Give referrer 20 points
    if referrer:
        conn.execute('UPDATE users SET points = points + 20 WHERE telegram_id =?', (referrer['telegram_id'],))
        try:
            await context.bot.send_message(
                chat_id=referrer['telegram_id'],
                text=f"🎉 Someone used your code! +20 points"
            )
        except:
            pass
    
    conn.commit()
    conn.close()
    
    msg = f"Hey {username}! 👋 Welcome to Earnlink!\n\nYour referral code: `{new_code}`\nShare link: t.me/EarnlinkMoneyBot?start={new_code}\n\nEarn 20 points per referral!"
    if referred_by and referrer:
        msg += "\n\n✅ Referral applied! Your referrer got 20 points."
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    conn = get_db_connection()
    user = conn.execute('SELECT points, referral_code FROM users WHERE telegram_id =?', (telegram_id,)).fetchone()
    conn.close()
    
    if user:
        await update.message.reply_text(
            f"💰 Points: {user['points']}\n"
            f"🔗 Code: `{user['referral_code']}`\n"
            f"Share: t.me/EarnlinkMoneyBot?start={user['referral_code']}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("Use /start first to register!")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    users = conn.execute('SELECT username, points FROM users ORDER BY points DESC LIMIT 10').fetchall()
    conn.close()
    
    if not users:
        await update.message.reply_text("No users yet. Be the first!")
        return
    
    text = "🏆 **Leaderboard**\n\n"
    for i, u in enumerate(users, 1):
        name = u['username'] or "User"
        text += f"{i}. {name} - {u['points']} pts\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    print("Bot running...")
    app.run_polling()

if __name__ == '__main__':
    main()
