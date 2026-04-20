import os
import sqlite3
from flask import Flask, request, render_template_string, redirect, session, url_for
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-this')

def init_db():
    conn = sqlite3.connect('earnlink.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            momo_number TEXT,
            status TEXT DEFAULT 'pending',
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect('earnlink.db')
    conn.row_factory = sqlite3.Row
    return conn

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
    return render_template_string(BASE_HTML, content=content, session=session, get_flashed_messages=get_flashed_messages)

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id =?', (session['user_id'],)).fetchone()
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
        user = conn.execute('SELECT * FROM users WHERE email=? AND password=?', (email, password)).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            return redirect('/')
        else:
            from flask import flash
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
            cur.execute('INSERT INTO users (email, password, referred_by) VALUES (?,?,?)', (email, password, ref))
            user_id = cur.lastrowid
            code = make_code(user_id)
            cur.execute('UPDATE users SET referral_code=? WHERE id=?', (code, user_id))

            # Give referrer 20 points
            if ref:
                referrer = conn.execute('SELECT id FROM users WHERE referral_code=?', (ref,)).fetchone()
                if referrer:
                    cur.execute('UPDATE users SET points = points + 20 WHERE id=?', (referrer['id'],))

            conn.commit()
            session['user_id'] = user_id
            conn.close()
            return redirect('/')
        except sqlite3.IntegrityError:
            conn.close()
            from flask import flash
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
        user = conn.execute('SELECT points FROM users WHERE id=?', (session['user_id'],)).fetchone()

        if amount < 100:
            from flask import flash
            flash('Minimum withdrawal is 100 points')
        elif user['points'] < amount:
            from flask import flash
            flash(f'Not enough points. Balance: {user["points"]}')
        else:
            conn.execute('UPDATE users SET points = points -?, momo_number =? WHERE id =?',
                         (amount, momo, session['user_id']))
            conn.execute('INSERT INTO withdrawals (user_id, amount, momo_number) VALUES (?,?,?)',
                         (session['user_id'], amount, momo))
            conn.commit()
            from flask import flash
            flash(f'Withdrawal of {amount} FCFA requested. Paid within 24h.')

        conn.close()
        return redirect('/withdraw')

    conn = get_db()
    user = conn.execute('SELECT points FROM users WHERE id=?', (session['user_id'],)).fetchone()
    conn.close()

    content = f'''
    <div class="card">
        <h1>💰 Withdraw</h1>
        <p>Current Balance: <b>{user['points']} points</b></p>
        <form method="post">
            <input name="amount" type="number" placeholder="Amount (min 100)" min="100" required>
            <input name="momo" placeholder="MTN MoMo Number: 677123456" required>
            <button class="btn btn-green" type="submit">Request Withdrawal</button>
        </form>
    </div>
    '''
    return render_page(content)

@app.route('/leaderboard')
def leaderboard():
    conn = get_db()
    top = conn.execute('SELECT email, points FROM users ORDER BY points DESC LIMIT 10').fetchall()
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

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
