import os
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, request, render_template_string, redirect, session, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import urllib.parse
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-this')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

# PART 5 + 6 CONFIG
WITHDRAWAL_FEE_PERCENT = 2
LEVEL_1_REWARD = 20
LEVEL_2_REWARD = 5
MAX_WITHDRAWS_PER_DAY = 1 # PART 6: Anti-spam
MIN_WITHDRAW = 100
MAX_WITHDRAW = 5000 # PART 6: Cap single withdrawal

def send_telegram(telegram_id, message):
    if not TELEGRAM_TOKEN or not telegram_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": telegram_id, "text": message, "parse_mode": "HTML"}, timeout=5)
        return True
    except:
        return False

def get_db():
    DATABASE_URL = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(DATABASE_URL, sslmode='require', cursor_factory=DictCursor)
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE,
            password TEXT,
            points INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by TEXT,
            momo_number TEXT,
            telegram_id TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            fee INTEGER DEFAULT 0,
            net_amount INTEGER,
            momo_number TEXT,
            status TEXT DEFAULT 'pending',
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='telegram_id'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE users ADD COLUMN telegram_id TEXT")
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='withdrawals' AND column_name='fee'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE withdrawals ADD COLUMN fee INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE withdrawals ADD COLUMN net_amount INTEGER")

    cursor.execute("SELECT * FROM users WHERE email=%s", ('admin@test.com',))
    if cursor.fetchone() is None:
        hashed_pw = generate_password_hash('123')
        cursor.execute("INSERT INTO users (email, password, points, referral_code) VALUES (%s, %s, %s, %s)",
                     ('admin@test.com', hashed_pw, 0, 'EL1'))
    conn.commit()
    conn.close()

init_db()

def make_code(user_id):
    return f"EL{user_id}"

BASE_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>EarnLink</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body{font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#f5f5f5}
.card{background:white;padding:20px;border-radius:8px;margin-bottom:15px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}
.btn{background:#0088cc;color:white;padding:10px 15px;border:none;border-radius:5px;text-decoration:none;display:inline-block;margin:5px 5px 5px 0}
.btn-red{background:#dc3545}
.btn-green{background:#28a745}
.btn-whatsapp{background:#25D366}
        input{width:100%;padding:10px;margin:5px 0;border:1px solid #ddd;border-radius:5px;box-sizing:border-box}
.nav a{margin-right:15px;text-decoration:none;color:#0088cc}
        h1{color:#333;margin-top:0}
.balance{font-size:24px;color:#28a745;font-weight:bold}
        table{width:100%;border-collapse:collapse}
        td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}
.badge{padding:3px 8px;border-radius:3px;color:white;font-size:12px}
.small{font-size:12px;color:#666}
    </style>
</head>
<body>
    <div class="nav card">
        <a href="/">Dashboard</a>
        <a href="/leaderboard">Leaderboard</a>
        <a href="/withdraw">Withdraw</a>
        <a href="/history">History</a>
        <a href="/settings">Settings</a>
        {% if session.user_id and is_admin %}<a href="/admin">Admin</a>{% endif %}
        {% if session.user_id %}<a href="/logout">Logout</a>{% endif %}
    </div>
    {% with messages = get_flashed_messages() %}
      {% if messages %}<div class="card" style="background:#fff3cd;">{{ messages[0] }}</div>{% endif %}
    {% endwith %}
    {{ content|safe }}
</body>
</html>
'''

def render_page(content):
    from flask import render_template_string, session, get_flashed_messages
    is_admin = False
    if 'user_id' in session:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT email FROM users WHERE id=%s', (session['user_id'],))
        user = cur.fetchone()
        conn.close()
        if user and user['email'] == 'admin@test.com':
            is_admin = True
    return render_template_string(BASE_HTML, content=content, session=session, is_admin=is_admin, get_flashed_messages=get_flashed_messages)

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE id =%s', (session['user_id'],))
    user = cur.fetchone()
    conn.close()

    link = f"{request.host_url}join/{user['referral_code']}"
    wa_text = urllib.parse.quote(f"🔥 Join EarnLink and we both get {LEVEL_1_REWARD} FCFA! Level 2 = {LEVEL_2_REWARD} FCFA bonus 💰\n\nUse my link: {link}")
    wa_link = f"https://wa.me/?text={wa_text}"

    content = f'''
    <div class="card">
        <h1>Welcome {user['email']}</h1>
        <p>Your Balance:</p>
        <p class="balance">{user['points']} Points</p>
        <p>1 point = 1 FCFA | Min: {MIN_WITHDRAW} | Max: {MAX_WITHDRAW} | Fee: {WITHDRAWAL_FEE_PERCENT}%</p>
    </div>
    <div class="card">
        <h3>🔗 Your Referral Link</h3>
        <input value="{link}" readonly onclick="this.select()">
        <p>Level 1: {LEVEL_1_REWARD} pts | Level 2: {LEVEL_2_REWARD} pts per friend</p>
        <a href="{wa_link}" class="btn btn-whatsapp" target="_blank">📲 Share on WhatsApp</a>
        <a href="/leaderboard" class="btn">🏆 Leaderboard</a>
        <a href="/withdraw" class="btn btn-green">💰 Withdraw</a>
        <a href="/history" class="btn">📋 History</a>
    </div>
    '''
    return render_page(content)

@app.route('/settings', methods=['GET','POST'])
def settings():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        telegram_id = request.form.get('telegram_id', '').strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE users SET telegram_id=%s WHERE id=%s', (telegram_id if telegram_id else None, session['user_id']))
        conn.commit()
        conn.close()
        flash('Telegram ID saved! You will get payout notifications.')
        return redirect('/settings')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT telegram_id FROM users WHERE id=%s', (session['user_id'],))
    user = cur.fetchone()
    conn.close()

    content = f'''
    <div class="card">
        <h1>⚙️ Settings</h1>
        <h3>Telegram Notifications</h3>
        <p class="small">Get instant DM when your withdrawal is paid.</p>
        <p class="small">1. Open Telegram → Search @userinfobot → Send /start → Copy your ID</p>
        <p class="small">2. Start a chat with @earnlink_payouts_bot → Send /start</p>
        <form method="post">
            <input name="telegram_id" placeholder="Your Telegram ID: 123456789" value="{user['telegram_id'] or ''}">
            <button class="btn" type="submit">Save Telegram ID</button>
        </form>
    </div>
    '''
    return render_page(content)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE email=%s', (email,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            return redirect('/')
        else:
            flash('Invalid email or password')

    content = '''
    <div class="card">
        <h1>Login to EarnLink</h1>
        <form method="post">
            <input name="email" type="email" placeholder="Email" required>
            <input name="password" type="password" placeholder="Password" required>
            <button class="btn" type="submit">Login</button>
        </form>
        <p>New here? <a href="/register">Create account</a></p>
    </div>
    '''
    return render_page(content)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        ref = request.args.get('ref')

        hashed_pw = generate_password_hash(password)

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute('INSERT INTO users (email, password, referred_by) VALUES (%s,%s,%s) RETURNING id',
                        (email, hashed_pw, ref))
            user_id = cur.fetchone()['id']
            code = make_code(user_id)
            cur.execute('UPDATE users SET referral_code=%s WHERE id=%s', (code, user_id))

            if ref:
                cur.execute('SELECT id, referred_by FROM users WHERE referral_code=%s', (ref,))
                level1 = cur.fetchone()
                if level1:
                    cur.execute('UPDATE users SET points = points + %s WHERE id=%s', (LEVEL_1_REWARD, level1['id']))
                    if level1['referred_by']:
                        cur.execute('SELECT id FROM users WHERE referral_code=%s', (level1['referred_by'],))
                        level2 = cur.fetchone()
                        if level2:
                            cur.execute('UPDATE users SET points = points + %s WHERE id=%s', (LEVEL_2_REWARD, level2['id']))

            conn.commit()
            session['user_id'] = user_id
            conn.close()
            return redirect('/')
        except psycopg2.IntegrityError:
            conn.close()
            flash('Email already exists')

    content = '''
    <div class="card">
        <h1>Create EarnLink Account</h1>
        <form method="post">
            <input name="email" type="email" placeholder="Email" required>
            <input name="password" type="password" placeholder="Password" required>
            <button class="btn" type="submit">Register</button>
        </form>
        <p>Have account? <a href="/login">Login</a></p>
    </div>
    '''
    return render_page(content)

@app.route('/join/<code>')
def join(code):
    return redirect(f'/register?ref={code}')

@app.route('/withdraw', methods=['GET','POST'])
def withdraw():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT points FROM users WHERE id=%s', (session['user_id'],))
    user = cur.fetchone()

    # PART 6: Check daily withdrawal limit
    cur.execute('''
        SELECT COUNT(*) as cnt FROM withdrawals
        WHERE user_id=%s AND request_date > NOW() - INTERVAL '24 hours'
    ''', (session['user_id'],))
    withdraw_count = cur.fetchone()['cnt']

    if request.method == 'POST':
        # PART 6: Block if limit reached
        if withdraw_count >= MAX_WITHDRAWS_PER_DAY:
            flash(f'Daily limit reached. Max {MAX_WITHDRAWS_PER_DAY} withdrawal per 24 hours.')
            conn.close()
            return redirect('/withdraw')

        try:
            amount = int(request.form['amount'])
        except:
            flash('Invalid amount')
            conn.close()
            return redirect('/withdraw')

        momo = request.form['momo']

        if amount < MIN_WITHDRAW:
            flash(f'Minimum withdrawal is {MIN_WITHDRAW} points')
            conn.close()
            return redirect('/withdraw')
        if amount > MAX_WITHDRAW:
            flash(f'Maximum withdrawal is {MAX_WITHDRAW} points')
            conn.close()
            return redirect('/withdraw')
        if user['points'] < amount:
            flash(f'Not enough points. Balance: {user["points"]}')
            conn.close()
            return redirect('/withdraw')
        if not momo:
            flash('MTN MoMo number required')
            conn.close()
            return redirect('/withdraw')

        fee = (amount * WITHDRAWAL_FEE_PERCENT) // 100
        net_amount = amount - fee

        cur.execute('UPDATE users SET points = points - %s, momo_number = %s WHERE id = %s',
                     (amount, momo, session['user_id']))
        cur.execute('INSERT INTO withdrawals (user_id, amount, fee, net_amount, momo_number) VALUES (%s,%s,%s,%s,%s)',
                     (session['user_id'], amount, fee, net_amount, momo))
        conn.commit()
        flash(f'Withdrawal of {net_amount} FCFA requested. Fee: {fee} FCFA. Paid within 24h.')
        conn.close()
        return redirect('/withdraw')

    conn.close()
    limit_msg = f'<p class="small">Daily limit: {MAX_WITHDRAWS_PER_DAY} withdrawal. You have {MAX_WITHDRAWS_PER_DAY - withdraw_count} left today.</p>'

    content = f'''
    <div class="card">
        <h1>💰 Withdraw V6 - DAILY LIMIT</h1>
        <p>Current Balance: <b>{user['points']} points</b></p>
        <p class="small">Min: {MIN_WITHDRAW} | Max: {MAX_WITHDRAW} | Fee: {WITHDRAWAL_FEE_PERCENT}%</p>
        {limit_msg}
        <form method="post">
            <input name="amount" type="number" placeholder="Amount ({MIN_WITHDRAW}-{MAX_WITHDRAW})" min="{MIN_WITHDRAW}" max="{min(MAX_WITHDRAW, user['points'])}" required {'disabled' if withdraw_count >= MAX_WITHDRAWS_PER_DAY else ''}>
            <input name="momo" placeholder="MTN MoMo Number: 677123456" required {'disabled' if withdraw_count >= MAX_WITHDRAWS_PER_DAY else ''}>
            <button class="btn btn-green" type="submit" {'disabled' if withdraw_count >= MAX_WITHDRAWS_PER_DAY else ''}>Request Withdrawal</button>
        </form>
        <p><a href="/history">View history</a> | <a href="/settings">Setup Telegram alerts</a></p>
    </div>
    '''
    return render_page(content)

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        SELECT amount, fee, net_amount, momo_number, status, request_date
        FROM withdrawals
        WHERE user_id=%s
        ORDER BY request_date DESC
    ''', (session['user_id'],))
    withdrawals = cur.fetchall()
    conn.close()

    rows = ''
    for w in withdrawals:
        if w['status'] == 'paid':
            badge = '<span class="badge" style="background:#28a745">Paid</span>'
        else:
            badge = '<span class="badge" style="background:#ffc107">Pending</span>'
        rows += f'''
        <tr>
            <td>{w['net_amount']} FCFA</td>
            <td class="small">Fee: {w['fee']}</td>
            <td>{w['momo_number']}</td>
            <td>{badge}</td>
            <td>{w['request_date'].strftime('%Y-%m-%d %H:%M')}</td>
        </tr>
        '''

    content = f'''
    <div class="card">
        <h1>📋 Withdrawal History</h1>
        <table>
            <tr><th>Net Amount</th><th>Fee</th><th>MoMo</th><th>Status</th><th>Date</th></tr>
            {rows if rows else '<tr><td colspan="5">No withdrawals yet</td></tr>'}
        </table>
        <p><a href="/withdraw" class="btn btn-green">New Withdrawal</a></p>
    </div>
    '''
    return render_page(content)

@app.route('/leaderboard')
def leaderboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT email, points FROM users ORDER BY points DESC LIMIT 10')
    top = cur.fetchall()
    conn.close()

    rows = ''.join([f'<tr><td>{i+1}</td><td>{u["email"]}</td><td>{u["points"]}</td></tr>' for i,u in enumerate(top)])

    content = f'''
    <div class="card">
        <h1>🏆 Top 10 Earners</h1>
        <table>
            <tr><th>#</th><th>User</th><th>Points</th></tr>
            {rows if rows else '<tr><td colspan="3">No users yet</td></tr>'}
        </table>
    </div>
    '''
    return render_page(content)

@app.route('/admin')
def admin():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT email FROM users WHERE id=%s', (session['user_id'],))
    user = cur.fetchone()

    if user['email']!= 'admin@test.com':
        conn.close()
        flash('Access denied')
        return redirect('/')

    cur.execute('''
        SELECT w.id, w.amount, w.fee, w.net_amount, w.momo_number, w.status, w.request_date, u.email
        FROM withdrawals w
        JOIN users u ON w.user_id = u.id
        ORDER BY w.request_date DESC
    ''')
    withdrawals = cur.fetchall()

    # PART 6: Calculate total fees earned
    cur.execute("SELECT COALESCE(SUM(fee), 0) as total_fees FROM withdrawals WHERE status='paid'")
    total_fees = cur.fetchone()['total_fees']
    conn.close()

    rows = ''
    for w in withdrawals:
        status_color = '#28a745' if w['status'] == 'paid' else '#ffc107'
        action = f'<a href="/pay/{w["id"]}" class="btn btn-green">Mark Paid</a>' if w['status'] == 'pending' else 'Done'
        rows += f'''
        <tr>
            <td>{w['id']}</td>
            <td>{w['email']}</td>
            <td>{w['net_amount']} FCFA</td>
            <td class="small">{w['fee']}</td>
            <td>{w['momo_number']}</td>
            <td><span class="badge" style="background:{status_color}">{w['status']}</span></td>
            <td>{w['request_date'].strftime('%Y-%m-%d %H:%M')}</td>
            <td>{action}</td>
        </tr>
        '''

    content = f'''
    <div class="card">
        <h1>🔒 Admin Panel - Withdrawals</h1>
        <p class="balance">Total Fees Earned: {total_fees} FCFA</p>
        <p class="small">Platform earns {WITHDRAWAL_FEE_PERCENT}% on each withdrawal</p>
        <table>
            <tr><th>ID</th><th>User</th><th>Net Pay</th><th>Fee</th><th>MoMo</th><th>Status</th><th>Date</th><th>Action</th></tr>
            {rows if rows else '<tr><td colspan="8">No withdrawal requests yet</td></tr>'}
        </table>
    </div>
    '''
    return render_page(content)

@app.route('/pay/<int:wid>')
def pay(wid):
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT email FROM users WHERE id=%s', (session['user_id'],))
    user = cur.fetchone()

    if user['email']!= 'admin@test.com':
        conn.close()
        flash('Access denied')
        return redirect('/')

    cur.execute('''
        SELECT w.net_amount, u.telegram_id, u.email
        FROM withdrawals w
        JOIN users u ON w.user_id = u.id
        WHERE w.id=%s
    ''', (wid,))
    w_data = cur.fetchone()

    cur.execute('UPDATE withdrawals SET status=%s WHERE id=%s', ('paid', wid))
    conn.commit()
    conn.close()

    if w_data and w_data['telegram_id']:
        msg = f"✅ <b>EarnLink Payout Complete</b>\n\nYour withdrawal of <b>{w_data['net_amount']} FCFA</b> has been paid to your MoMo.\n\nThanks for using EarnLink!"
        send_telegram(w_data['telegram_id'], msg)
        flash(f'Withdrawal #{wid} marked as paid + Telegram sent to {w_data["email"]}')
    else:
        flash(f'Withdrawal #{wid} marked as paid')

    return redirect('/admin')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
