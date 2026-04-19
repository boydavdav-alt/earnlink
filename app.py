import os
from flask import Flask, request, jsonify, render_template_string
import sqlite3
import secrets
import string
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import jwt

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-secret-key-in-production')

def get_db_connection():
    conn = sqlite3.connect('earnlink.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            referral_code TEXT UNIQUE NOT NULL,
            referred_by TEXT,
            points INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

# RUN THIS IMMEDIATELY WHEN APP STARTS
init_db()

def generate_referral_code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))

def create_token(email):
    payload = {
        'email': email,
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

def verify_token(token):
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload['email']
    except:
        return None

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>EarnLink</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial; max-width: 600px; margin: 40px auto; padding: 0 20px; }
        input { width: 100%; padding: 8px; margin: 5px 0; box-sizing: border-box; }
        button { padding: 10px; width: 100%; margin: 10px 0; cursor: pointer; }
    .box { border: 1px solid #ddd; padding: 15px; margin: 15px 0; border-radius: 8px; }
        table { width: 100%; border-collapse: collapse; }
        td, th { border: 1px solid #ddd; padding: 8px; text-align: left; }
        #msg { color: green; min-height: 20px; }
    .hidden { display: none; }
    </style>
</head>
<body>
    <h1>EarnLink</h1>

    <div id="auth" class="box">
        <h3>Signup / Login</h3>
        <input id="email" placeholder="Email">
        <input id="password" type="password" placeholder="Password">
        <input id="referral" placeholder="Referral Code (optional)">
        <button onclick="signup()">Signup</button>
        <button onclick="login()">Login</button>
        <div id="msg"></div>
    </div>

    <div id="dashboard" class="box hidden">
        <h3>Welcome <span id="userEmail"></span></h3>
        <p><b>Points:</b> <span id="points">0</span></p>
        <p><b>Your Code:</b> <span id="myCode"></span></p>
        <button onclick="copyLink()">Copy Referral Link</button>
        <button onclick="logout()">Logout</button>
    </div>

    <div class="box">
        <h3>Leaderboard</h3>
        <table id="board"></table>
    </div>

<script>
let token = localStorage.getItem('token');

function showMsg(text, isError=false) {
    document.getElementById('msg').style.color = isError? 'red' : 'green';
    document.getElementById('msg').innerText = text;
}

async function signup() {
    const res = await fetch('/signup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            email: email.value,
            password: password.value,
            referral: referral.value
        })
    });
    const data = await res.json();
    if (res.status === 201) {
        localStorage.setItem('token', data.token);
        token = data.token;
        loadMe();
        showMsg('Signup success!');
    } else {
        showMsg(data.error, true);
    }
}

async function login() {
    const res = await fetch('/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            email: email.value,
            password: password.value
        })
    });
    const data = await res.json();
    if (res.status === 200) {
        localStorage.setItem('token', data.token);
        token = data.token;
        loadMe();
        showMsg('Login success!');
    } else {
        showMsg(data.error, true);
    }
}

async function loadMe() {
    if (!token) return;
    const res = await fetch('/me', {
        headers: {'Authorization': 'Bearer ' + token}
    });
    if (res.status === 200) {
        const data = await res.json();
        document.getElementById('auth').classList.add('hidden');
        document.getElementById('dashboard').classList.remove('hidden');
        userEmail.innerText = data.email;
        points.innerText = data.points;
        myCode.innerText = data.referral_code;
    } else {
        logout();
    }
}

function logout() {
    localStorage.removeItem('token');
    token = null;
    document.getElementById('auth').classList.remove('hidden');
    document.getElementById('dashboard').classList.add('hidden');
}

function copyLink() {
    const link = window.location.origin + '/?ref=' + myCode.innerText;
    navigator.clipboard.writeText(link);
    showMsg('Copied: ' + link);
}

async function loadBoard() {
    const res = await fetch('/leaderboard');
    const data = await res.json();
    let html = '<tr><th>#</th><th>Email</th><th>Points</th></tr>';
    data.forEach((u, i) => {
        html += `<tr><td>${i+1}</td><td>${u.email}</td><td>${u.points}</td></tr>`;
    });
    board.innerHTML = html;
}

const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('ref')) {
    referral.value = urlParams.get('ref');
}

loadMe();
loadBoard();
setInterval(loadBoard, 5000);
</script>
</body>
</html>
'''

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Email and password required"}), 400
    email = data['email'].strip()
    password = data['password']
    referral = data.get('referral', '').strip()
    conn = get_db_connection()
    existing = conn.execute('SELECT id FROM users WHERE LOWER(email) = LOWER(?)', (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Email already registered"}), 400
    referrer = None
    if referral:
        referrer = conn.execute('SELECT id, email, referral_code FROM users WHERE LOWER(TRIM(referral_code)) = LOWER(TRIM(?))', (referral,)).fetchone()
        if not referrer:
            conn.close()
            return jsonify({"error": "Invalid referral code"}), 400
        if referrer['email'].lower() == email.lower():
            conn.close()
            return jsonify({"error": "Cannot refer yourself"}), 400
    new_code = generate_referral_code()
    while conn.execute('SELECT id FROM users WHERE referral_code =?', (new_code,)).fetchone():
        new_code = generate_referral_code()
    hashed_password = generate_password_hash(password)
    conn.execute('INSERT INTO users (email, password, referral_code, referred_by, points) VALUES (?,?,?,?, 0)', (email, hashed_password, new_code, referral if referral else None))
    if referrer:
        conn.execute('UPDATE users SET points = points + 20 WHERE id =?', (referrer['id'],))
    conn.commit()
    conn.close()
    token = create_token(email)
    return jsonify({"message": "User created", "referral_code": new_code, "token": token}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Email and password required"}), 400
    email = data['email'].strip()
    password = data['password']
    conn = get_db_connection()
    user = conn.execute('SELECT email, password, points, referral_code FROM users WHERE LOWER(email) = LOWER(?)', (email,)).fetchone()
    conn.close()
    if not user:
        return jsonify({"error": "Invalid email or password"}), 401
    if check_password_hash(user['password'], password):
        token = create_token(user['email'])
        return jsonify({"message": "Login success", "email": user['email'], "points": user['points'], "referral_code": user['referral_code'], "token": token}), 200
    else:
        return jsonify({"error": "Invalid email or password"}), 401

@app.route('/me')
def me():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing or invalid token"}), 401
    token = auth_header.split(' ')[1]
    email = verify_token(token)
    if not email:
        return jsonify({"error": "Invalid or expired token"}), 401
    conn = get_db_connection()
    user = conn.execute('SELECT email, points, referral_code FROM users WHERE LOWER(email) = LOWER(?)', (email,)).fetchone()
    conn.close()
    if user:
        return jsonify(dict(user))
    return jsonify({"error": "User not found"}), 404

@app.route('/leaderboard')
def leaderboard():
    conn = get_db_connection()
    users = conn.execute('SELECT email, points, referral_code FROM users ORDER BY points DESC LIMIT 10').fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route('/referrals/<email>')
def get_referrals(email):
    conn = get_db_connection()
    user = conn.execute('SELECT referral_code FROM users WHERE LOWER(email) = LOWER(?)', (email,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    referrals = conn.execute('SELECT email, points FROM users WHERE LOWER(TRIM(referred_by)) = LOWER(TRIM(?))', (user['referral_code'],)).fetchall()
    conn.close()
    return jsonify({"referrer": email, "referral_code": user['referral_code'], "total_referrals": len(referrals), "referred_users": [dict(u) for u in referrals]})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
