import os
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, request, render_template_string, redirect, session, url_for, flash
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-this')

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
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            momo_number TEXT,
            status TEXT DEFAULT 'pending',
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Create admin if not exists
    cursor.execute("SELECT * FROM users WHERE email=%s", ('admin@test.com',))
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO users (email, password, points, referral_code) VALUES (%s, %s, %s, %s)",
                     ('admin@test.com', '123', 0, 'EL1'))
    conn.commit()
    conn.close()

init_db()

def make_code(user_id):
    return f"EL{user_id}"

# HTML TEMPLATE - All pages in one
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
        input{width:100%;padding:10px;margin:5px 0;border:1px solid #ddd;border-radius:5px;box-sizing:border-box}
   .nav a{margin-right:15px;text-decoration:none;color:#0088cc}
        h1{color:#333;margin-top:0}
   .balance{font-size:24px;color:#28a745;font-weight:bold}
        table{width:100%;border-collapse:collapse}
        td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}
    </style>
</head>
<body>
    <div class="nav card">
        <a href="/">Dashboard</a>
        <a href="/leaderboard">Leaderboard</a>
        <a href="/withdraw">Withdraw</a>
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

    content = f'''
    <div class="card">
        <h1>Welcome {user['email']}</h1>
        <p>Your Balance:</p>
        <p class="balance">{user['points']} Points</p>
        <p>1 point = 1 FCFA | Min withdrawal: 100 points</p>
    </div>
    <div class="card">
        <h3>🔗 Your Referral Link</h3>
        <input value="{link}" readonly onclick="this.select()">
        <p>Share this link. You get 20 points per friend who joins!</p>
        <a href="/leaderboard" class="btn">🏆 Leaderboard</a>
        <a href="/withdraw" class="btn btn-green">💰 Withdraw</a>
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
        cur.execute('SELECT * FROM users WHERE email=%s AND password=%s', (email, password))
        user = cur.fetchone()
        conn.close()
        if user:
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

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute('INSERT INTO users (email, password, referred_by) VALUES (%s,%s,%s) RETURNING id', (email, password, ref))
            user_id = cur.fetchone()['id']
            code = make_code(user_id)
            cur.execute('UPDATE users SET referral_code=%s WHERE id=%s', (code, user_id))

            # Give referrer 20 points
            if ref:
                cur.execute('SELECT id FROM users WHERE referral_code=%s', (ref,))
                referrer = cur.fetchone()
                if referrer:
                    cur.execute('UPDATE users SET points = points + 20 WHERE id=%s', (referrer['id'],))

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

    if request.method == 'POST':
        amount = int(request.form['amount'])
        momo = request.form['momo']
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT points FROM users WHERE id=%s', (session['user_id'],))
        user = cur.fetchone()

        # BUG FIX 1: Stop execution after error flash
        if amount < 100:
            flash('Minimum withdrawal is 100 points')
            conn.close()
            return redirect('/withdraw')
        elif user['points'] < amount:
            flash(f'Not enough points. Balance: {user["points"]}')
            conn.close()
            return redirect('/withdraw')
        else:
            cur.execute('UPDATE users SET points = points - %s, momo_number = %s WHERE id = %s',
                         (amount, momo, session['user_id']))
            cur.execute('INSERT INTO withdrawals (user_id, amount, momo_number) VALUES (%s,%s,%s)',
                         (session['user_id'], amount, momo))
            conn.commit()
            flash(f'Withdrawal of {amount} FCFA requested. Paid within 24h.')
            conn.close()
            return redirect('/withdraw')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT points FROM users WHERE id=%s', (session['user_id'],))
    user = cur.fetchone()
    conn.close()

    # BUG FIX 2: Add max attribute so user can't type more than balance
    content = f'''
    <div class="card">
        <h1>💰 Withdraw</h1>
        <p>Current Balance: <b>{user['points']} points</b></p>
        <form method="post">
            <input name="amount" type="number" placeholder="Amount (min 100)" min="100" max="{user['points']}" required>
            <input name="momo" placeholder="MTN MoMo Number: 677123456" required>
            <button class="btn btn-green" type="submit">Request Withdrawal</button>
        </form>
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
        SELECT w.id, w.amount, w.momo_number, w.status, w.request_date, u.email
        FROM withdrawals w
        JOIN users u ON w.user_id = u.id
        ORDER BY w.request_date DESC
    ''')
    withdrawals = cur.fetchall()
    conn.close()

    rows = ''
    for w in withdrawals:
        status_color = '#28a745' if w['status'] == 'paid' else '#ffc107'
        action = f'<a href="/pay/{w["id"]}" class="btn btn-green">Mark Paid</a>' if w['status'] == 'pending' else 'Done'
        rows += f'''
        <tr>
            <td>{w['id']}</td>
            <td>{w['email']}</td>
            <td>{w['amount']} FCFA</td>
            <td>{w['momo_number']}</td>
            <td><span style="background:{status_color};color:white;padding:3px 8px;border-radius:3px">{w['status']}</span></td>
            <td>{w['request_date'].strftime('%Y-%m-%d %H:%M')}</td>
            <td>{action}</td>
        </tr>
        '''

    content = f'''
    <div class="card">
        <h1>🔒 Admin Panel - Withdrawals</h1>
        <table>
            <tr><th>ID</th><th>User</th><th>Amount</th><th>MoMo</th><th>Status</th><th>Date</th><th>Action</th></tr>
            {rows if rows else '<tr><td colspan="7">No withdrawal requests yet</td></tr>'}
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

    cur.execute('UPDATE withdrawals SET status=%s WHERE id=%s', ('paid', wid))
    conn.commit()
    conn.close()
    flash(f'Withdrawal #{wid} marked as paid')
    return redirect('/admin')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
