import os
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask,request,render_template_string,redirect,session,url_for,flash
from werkzeug.security import generate_password_hash,check_password_hash
from datetime import datetime,timedelta
import urllib.parse
import requests
import secrets
import uuid
import base64
import json
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY','dev-secret-change-this')
TELEGRAM_TOKEN=os.environ.get('TELEGRAM_BOT_TOKEN')
SENDGRID_KEY=os.environ.get('SENDGRID_API_KEY')
FROM_EMAIL=os.environ.get('FROM_EMAIL','noreply@earnlink.cm')
MTN_USER_ID=os.environ.get('MTN_USER_ID')
MTN_API_KEY=os.environ.get('MTN_API_KEY')
MTN_SUBSCRIPTION_KEY=os.environ.get('MTN_SUBSCRIPTION_KEY')
MTN_TARGET_ENV=os.environ.get('MTN_TARGET_ENV','sandbox')
MTN_BASE_URL='https://sandbox.momodeveloper.mtn.com' if MTN_TARGET_ENV=='sandbox' else 'https://proxy.momoapi.mtn.com'
WITHDRAWAL_FEE_PERCENT=2
LEVEL_1_REWARD=20
LEVEL_2_REWARD=5
MAX_WITHDRAWS_PER_DAY=1
MIN_WITHDRAW=100
MAX_WITHDRAW=5000
KYC_REQUIRED_ABOVE=2000
RESET_TOKEN_EXPIRE_HOURS=1
def get_momo_token():
 if not all([MTN_USER_ID,MTN_API_KEY,MTN_SUBSCRIPTION_KEY]):return None
 try:
  auth=base64.b64encode(f"{MTN_USER_ID}:{MTN_API_KEY}".encode()).decode()
  headers={'Authorization':f'Basic {auth}','Ocp-Apim-Subscription-Key':MTN_SUBSCRIPTION_KEY}
  r=requests.post(f'{MTN_BASE_URL}/collection/token/',headers=headers,timeout=10)
  return r.json().get('access_token') if r.status_code==200 else None
 except:return None
def send_momo_payment(amount,phone_number,external_id):
 token=get_momo_token()
 if not token:return False,"MTN API not configured"
 if not phone_number.startswith('237'):phone_number=f"237{phone_number.lstrip('0')}"
 try:
  headers={'Authorization':f'Bearer {token}','X-Reference-Id':external_id,'X-Target-Environment':MTN_TARGET_ENV,'Ocp-Apim-Subscription-Key':MTN_SUBSCRIPTION_KEY,'Content-Type':'application/json'}
  body={"amount":str(amount),"currency":"EUR" if MTN_TARGET_ENV=='sandbox' else "XAF","externalId":external_id,"payer":{"partyIdType":"MSISDN","partyId":phone_number},"payerMessage":"EarnLink Payout","payeeNote":"Thanks for using EarnLink"}
  r=requests.post(f'{MTN_BASE_URL}/collection/v1_0/requesttopay',headers=headers,json=body,timeout=15)
  return r.status_code==202,f"Status: {r.status_code}"
 except Exception as e:return False,str(e)
def send_telegram(telegram_id,message):
 if not TELEGRAM_TOKEN or not telegram_id:return False
 try:
  url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  requests.post(url,json={"chat_id":telegram_id,"text":message,"parse_mode":"HTML"},timeout=5)
  return True
 except:return False
def send_email(to_email,subject,html_content):
 if not SENDGRID_KEY:return False
 try:
  message=Mail(from_email=FROM_EMAIL,to_emails=to_email,subject=subject,html_content=html_content)
  sg=SendGridAPIClient(SENDGRID_KEY)
  sg.send(message)
  return True
 except:return False
def get_db():
 DATABASE_URL=os.environ.get('DATABASE_URL')
 conn=psycopg2.connect(DATABASE_URL,sslmode='require',cursor_factory=DictCursor)
 return conn
def init_db():
 conn=get_db()
 cursor=conn.cursor()
 cursor.execute('''CREATE TABLE IF NOT EXISTS users(id SERIAL PRIMARY KEY,email TEXT UNIQUE,password TEXT,points INTEGER DEFAULT 0,referral_code TEXT UNIQUE,referred_by TEXT,momo_number TEXT,telegram_id TEXT,reset_token TEXT,reset_expires TIMESTAMP,signup_ip TEXT,kyc_status TEXT DEFAULT 'none',kyc_id_url TEXT,join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
 cursor.execute('''CREATE TABLE IF NOT EXISTS withdrawals(id SERIAL PRIMARY KEY,user_id INTEGER,amount INTEGER,fee INTEGER DEFAULT 0,net_amount INTEGER,momo_number TEXT,status TEXT DEFAULT 'pending',momo_ref TEXT,request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users (id))''')
 migrations=[('users','telegram_id',"ALTER TABLE users ADD COLUMN telegram_id TEXT"),('users','reset_token',"ALTER TABLE users ADD COLUMN reset_token TEXT"),('users','reset_expires',"ALTER TABLE users ADD COLUMN reset_expires TIMESTAMP"),('users','signup_ip',"ALTER TABLE users ADD COLUMN signup_ip TEXT"),('users','kyc_status',"ALTER TABLE users ADD COLUMN kyc_status TEXT DEFAULT 'none'"),('users','kyc_id_url',"ALTER TABLE users ADD COLUMN kyc_id_url TEXT"),('withdrawals','fee',"ALTER TABLE withdrawals ADD COLUMN fee INTEGER DEFAULT 0"),('withdrawals','net_amount',"ALTER TABLE withdrawals ADD COLUMN net_amount INTEGER"),('withdrawals','momo_ref',"ALTER TABLE withdrawals ADD COLUMN momo_ref TEXT")]
 for table,col,sql in migrations:
  cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' AND column_name='{col}'")
  if not cursor.fetchone():cursor.execute(sql)
 cursor.execute("SELECT * FROM users WHERE email=%s",('admin@test.com',))
 if cursor.fetchone() is None:
  hashed_pw=generate_password_hash('123')
  cursor.execute("INSERT INTO users (email,password,points,referral_code) VALUES (%s,%s,%s,%s)",('admin@test.com',hashed_pw,0,'EL1'))
 conn.commit()
 conn.close()
init_db()
def make_code(user_id):return f"EL{user_id}"
BASE_HTML='''<!DOCTYPE html><html><head><title>EarnLink</title><meta name="viewport" content="width=device-width, initial-scale=1"><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>body{font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;background:#f5f5f5}.card{background:white;padding:20px;border-radius:8px;margin-bottom:15px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}.btn{background:#0088cc;color:white;padding:10px 15px;border:none;border-radius:5px;text-decoration:none;display:inline-block;margin:5px 5px 5px 0}.btn-red{background:#dc3545}.btn-green{background:#28a745}.btn-whatsapp{background:#25D366}input{width:100%;padding:10px;margin:5px 0;border:1px solid #ddd;border-radius:5px;box-sizing:border-box}.nav a{margin-right:15px;text-decoration:none;color:#0088cc}h1{color:#333;margin-top:0}.balance{font-size:24px;color:#28a745;font-weight:bold}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}.badge{padding:3px 8px;border-radius:3px;color:white;font-size:12px}.small{font-size:12px;color:#666}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:15px}.stat{text-align:center;padding:15px;background:#f8f9fa;border-radius:5px}.stat-num{font-size:28px;font-weight:bold;color:#0088cc}</style></head><body><div class="nav card"><a href="/">Dashboard</a><a href="/leaderboard">Leaderboard</a><a href="/withdraw">Withdraw</a><a href="/history">History</a><a href="/kyc">KYC</a><a href="/settings">Settings</a>{% if session.user_id and is_admin %}<a href="/admin">Admin</a>{% endif %}{% if session.user_id %}<a href="/logout">Logout</a>{% else %}<a href="/login">Login</a>{% endif %}</div>{% with messages = get_flashed_messages() %}{% if messages %}<div class="card" style="background:#fff3cd;">{{ messages[0] }}</div>{% endif %}{% endwith %}{{ content|safe }}</body></html>'''
def render_page(content):
 from flask import render_template_string,session,get_flashed_messages
 is_admin=False
 if 'user_id' in session:
  conn=get_db()
  cur=conn.cursor()
  cur.execute('SELECT email FROM users WHERE id=%s',(session['user_id'],))
  user=cur.fetchone()
  conn.close()
  if user and user['email']=='admin@test.com':is_admin=True
 return render_template_string(BASE_HTML,content=content,session=session,is_admin=is_admin,get_flashed_messages=get_flashed_messages)
@app.route('/')
def home():
 if 'user_id' not in session:return redirect('/login')
 conn=get_db()
 cur=conn.cursor()
 cur.execute('SELECT * FROM users WHERE id =%s',(session['user_id'],))
 user=cur.fetchone()
 conn.close()
 link=f"{request.host_url}join/{user['referral_code']}"
 wa_text=urllib.parse.quote(f"🔥 Join EarnLink and we both get {LEVEL_1_REWARD} FCFA! Level 2 = {LEVEL_2_REWARD} FCFA bonus 💰\n\nUse my link: {link}")
 wa_link=f"https://wa.me/?text={wa_text}"
 kyc_badge=f'<span class="badge" style="background:#28a745">KYC Verified</span>' if user['kyc_status']=='approved' else f'<span class="badge" style="background:#ffc107">KYC: {user["kyc_status"]}</span>'
 content=f'''<div class="card"><h1>Welcome {user['email']} {kyc_badge}</h1><p>Your Balance:</p><p class="balance">{user['points']} Points</p><p>1 point = 1 FCFA | Min: {MIN_WITHDRAW} | Max: {MAX_WITHDRAW} | Fee: {WITHDRAWAL_FEE_PERCENT}%</p><p class="small">KYC required for withdrawals over {KYC_REQUIRED_ABOVE} FCFA</p></div><div class="card"><h3>🔗 Your Referral Link</h3><input value="{link}" readonly onclick="this.select()"><p>Level 1: {LEVEL_1_REWARD} pts | Level 2: {LEVEL_2_REWARD} pts per friend</p><a href="{wa_link}" class="btn btn-whatsapp" target="_blank">📲 Share on WhatsApp</a><a href="/leaderboard" class="btn">🏆 Leaderboard</a><a href="/withdraw" class="btn btn-green">💰 Withdraw</a><a href="/kyc" class="btn">🆔 KYC</a></div>'''
 return render_page(content)
@app.route('/kyc',methods=['GET','POST'])
def kyc():
 if 'user_id' not in session:return redirect('/login')
 if request.method=='POST':
  kyc_url=request.form.get('kyc_id_url','').strip()
  if not kyc_url:
   flash('ID image URL required')
   return redirect('/kyc')
  conn=get_db()
  cur=conn.cursor()
  cur.execute('UPDATE users SET kyc_id_url=%s,kyc_status=%s WHERE id=%s',(kyc_url,'pending',session['user_id']))
  conn.commit()
  conn.close()
  flash('KYC submitted! Admin will review within 24h.')
  return redirect('/kyc')
 conn=get_db()
 cur=conn.cursor()
 cur.execute('SELECT kyc_status,kyc_id_url FROM users WHERE id=%s',(session['user_id'],))
 user=cur.fetchone()
 conn.close()
 status_color={'none':'#6c757d','pending':'#ffc107','approved':'#28a745','rejected':'#dc3545'}[user['kyc_status']]
 content=f'''<div class="card"><h1>🆔 KYC Verification</h1><p>Status: <span class="badge" style="background:{status_color}">{user['kyc_status'].upper()}</span></p><p class="small">Required for withdrawals over {KYC_REQUIRED_ABOVE} FCFA. Upload clear photo of CNI/Passport.</p><form method="post"><input name="kyc_id_url" placeholder="Imgur/Drive link to your ID photo" value="{user['kyc_id_url'] or ''}" required><button class="btn" type="submit">Submit for Review</button></form><p class="small">Tip: Upload to imgur.com → Copy direct image link → Paste here</p></div>'''
 return render_page(content)
@app.route('/settings',methods=['GET','POST'])
def settings():
 if 'user_id' not in session:return redirect('/login')
 if request.method=='POST':
  telegram_id=request.form.get('telegram_id','').strip()
  conn=get_db()
  cur=conn.cursor()
  cur.execute('UPDATE users SET telegram_id=%s WHERE id=%s',(telegram_id if telegram_id else None,session['user_id']))
  conn.commit()
  conn.close()
  flash('Telegram ID saved! You will get payout notifications.')
  return redirect('/settings')
 conn=get_db()
 cur=conn.cursor()
 cur.execute('SELECT telegram_id FROM users WHERE id=%s',(session['user_id'],))
 user=cur.fetchone()
 conn.close()
 content=f'''<div class="card"><h1>⚙️ Settings</h1><h3>Telegram Notifications</h3><p class="small">Get instant DM when your withdrawal is paid.</p><p class="small">1. Open Telegram → Search @userinfobot → Send /start → Copy your ID</p><p class="small">2. Start a chat with @earnlink_payouts_bot → Send /start</p><form method="post"><input name="telegram_id" placeholder="Your Telegram ID: 123456789" value="{user['telegram_id'] or ''}"><button class="btn" type="submit">Save Telegram ID</button></form></div>'''
 return render_page(content)
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  email=request.form['email']
  password=request.form['password']
  conn=get_db()
  cur=conn.cursor()
  cur.execute('SELECT * FROM users WHERE email=%s',(email,))
  user=cur.fetchone()
  conn.close()
  if user and check_password_hash(user['password'],password):
   session['user_id']=user['id']
   return redirect('/')
  else:
   flash('Invalid email or password')
 content='''<div class="card"><h1>Login to EarnLink</h1><form method="post"><input name="email" type="email" placeholder="Email" required><input name="password" type="password" placeholder="Password" required><button class="btn" type="submit">Login</button></form><p><a href="/forgot">Forgot Password?</a></p><p>New here? <a href="/register">Create account</a></p></div>'''
 return render_page(content)
@app.route('/forgot',methods=['GET','POST'])
def forgot():
 if request.method=='POST':
  email=request.form['email']
  conn=get_db()
  cur=conn.cursor()
  cur.execute('SELECT id FROM users WHERE email=%s',(email,))
  user=cur.fetchone()
  if user:
   token=secrets.token_urlsafe(32)
   expires=datetime.utcnow()+timedelta(hours=RESET_TOKEN_EXPIRE_HOURS)
   cur.execute('UPDATE users SET reset_token=%s,reset_expires=%s WHERE id=%s',(token,expires,user['id']))
   conn.commit()
   reset_link=f"{request.host_url}reset/{token}"
   html=f'''<h2>EarnLink Password Reset</h2><p>Click below to reset your password. Link expires in {RESET_TOKEN_EXPIRE_HOURS} hour.</p><a href="{reset_link}" style="background:#0088cc;color:white;padding:10px 20px;text-decoration:none;border-radius:5px">Reset Password</a><p>If you didn't request this, ignore this email.</p>'''
   if send_email(email,'EarnLink Password Reset',html):flash('Reset link sent! Check your email.')
   else:flash('Email service error. Contact admin.')
  else:flash('If that email exists, a reset link was sent.')
  conn.close()
  return redirect('/login')
 content='''<div class="card"><h1>Forgot Password</h1><p>Enter your email to get a reset link.</p><form method="post"><input name="email" type="email" placeholder="Your email" required><button class="btn" type="submit">Send Reset Link</button></form><p><a href="/login">Back to Login</a></p></div>'''
 return render_page(content)
@app.route('/reset/<token>',methods=['GET','POST'])
def reset(token):
 conn=get_db()
 cur=conn.cursor()
 cur.execute('SELECT id,reset_expires FROM users WHERE reset_token=%s',(token,))
 user=cur.fetchone()
 if not user or user['reset_expires']<datetime.utcnow():
  conn.close()
  flash('Invalid or expired reset link.')
  return redirect('/login')
 if request.method=='POST':
  new_pw=request.form['password']
  hashed_pw=generate_password_hash(new_pw)
  cur.execute('UPDATE users SET password=%s,reset_token=NULL,reset_expires=NULL WHERE id=%s',(hashed_pw,user['id']))
  conn.commit()
  conn.close()
  flash('Password updated! Login with new password.')
  return redirect('/login')
 conn.close()
 content='''<div class="card"><h1>Set New Password</h1><form method="post"><input name="password" type="password" placeholder="New password" required><button class="btn" type="submit">Update Password</button></form></div>'''
 return render_page(content)
@app.route('/register',methods=['GET','POST'])
def register():
 if request.method=='POST':
  email=request.form['email']
  password=request.form['password']
  ref=request.args.get('ref')
  signup_ip=request.headers.get('X-Forwarded-For',request.remote_addr)
  hashed_pw=generate_password_hash(password)
  conn=get_db()
  try:
   cur=conn.cursor()
   cur.execute('INSERT INTO users (email,password,referred_by,signup_ip) VALUES (%s,%s,%s,%s) RETURNING id',(email,hashed_pw,ref,signup_ip))
   user_id=cur.fetchone()['id']
   code=make_code(user_id)
   cur.execute('UPDATE users SET referral_code=%s WHERE id=%s',(code,user_id))
   if ref:
    cur.execute('SELECT id,referred_by,signup_ip FROM users WHERE referral_code=%s',(ref,))
    level1=cur.fetchone()
    if level1:
     if level1['id']==user_id:pass
     elif level1['signup_ip']==signup_ip:pass
     else:
      cur.execute('UPDATE users SET points=points+%s WHERE id=%s',(LEVEL_1_REWARD,level1['id']))
      if level1['referred_by']:
       cur.execute('SELECT id FROM users WHERE referral_code=%s',(level1['referred_by'],))
       level2=cur.fetchone()
       if level2 and level2['id']!=user_id:cur.execute('UPDATE users SET points=points+%s WHERE id=%s',(LEVEL_2_REWARD,level2['id']))
   conn.commit()
   session['user_id']=user_id
   conn.close()
   return redirect('/')
  except psycopg2.IntegrityError:
   conn.close()
   flash('Email already exists')
 content='''<div class="card"><h1>Create EarnLink Account</h1><form method="post"><input name="email" type="email" placeholder="Email" required><input name="password" type="password" placeholder="Password" required><button class="btn" type="submit">Register</button></form><p>Have account? <a href="/login">Login</a></p></div>'''
 return render_page(content)
@app.route('/join/<code>')
def join(code):return redirect(f'/register?ref={code}')
@app.route('/withdraw',methods=['GET','POST'])
def withdraw():
 if 'user_id' not in session:return redirect('/login')
 conn=get_db()
 cur=conn.cursor()
 cur.execute('SELECT points,kyc_status FROM users WHERE id=%s',(session['user_id'],))
 user=cur.fetchone()
 cur.execute('''SELECT COUNT(*) as cnt FROM withdrawals WHERE user_id=%s AND request_date > NOW() - INTERVAL '24 hours' ''',(session['user_id'],))
 withdraw_count=cur.fetchone()['cnt']
 if request.method=='POST':
  if withdraw_count>=MAX_WITHDRAWS_PER_DAY:
   flash(f'Daily limit reached. Max {MAX_WITHDRAWS_PER_DAY} withdrawal per 24 hours.')
   conn.close()
   return redirect('/withdraw')
  try:amount=int(request.form['amount'])
  except:
   flash('Invalid amount')
   conn.close()
   return redirect('/withdraw')
  momo=request.form['momo']
  if amount<MIN_WITHDRAW:
   flash(f'Minimum withdrawal is {MIN_WITHDRAW} points')
   conn.close()
   return redirect('/withdraw')
  if amount>MAX_WITHDRAW:
   flash(f'Maximum withdrawal is {MAX_WITHDRAW} points')
   conn.close()
   return redirect('/withdraw')
  if user['points']<amount:
   flash(f'Not enough points. Balance: {user["points"]}')
   conn.close()
   return redirect('/withdraw')
  if amount>KYC_REQUIRED_ABOVE and user['kyc_status']!='approved':
   flash(f'KYC required for withdrawals over {KYC_REQUIRED_ABOVE} FCFA. Go to KYC page.')
   conn.close()
   return redirect('/withdraw')
  if not momo:
   flash('MTN MoMo number required')
   conn.close()
   return redirect('/withdraw')
  fee=(amount*WITHDRAWAL_FEE_PERCENT)//100
  net_amount=amount-fee
  cur.execute('UPDATE users SET points=points-%s,momo_number=%s WHERE id=%s',(amount,momo,session['user_id']))
  cur.execute('INSERT INTO withdrawals (user_id,amount,fee,net_amount,momo_number) VALUES (%s,%s,%s,%s,%s)',(session['user_id'],amount,fee,net_amount,momo))
  conn.commit()
  flash(f'Withdrawal of {net_amount} FCFA requested. Fee: {fee} FCFA. Auto-pay processing.')
  conn.close()
  return redirect('/withdraw')
 conn.close()
 limit_msg=f'<p class="small">Daily limit: {MAX_WITHDRAWS_PER_DAY} withdrawal. You have {MAX_WITHDRAWS_PER_DAY-withdraw_count} left today.</p>'
 kyc_warn=f'<p class="small" style="color:#dc3545">⚠️ KYC required for amounts over {KYC_REQUIRED_ABOVE} FCFA</p>' if user['kyc_status']!='approved' else ''
 content=f'''<div class="card"><h1>💰 Withdraw V9 - KYC + DASHBOARD</h1><p>Current Balance: <b>{user['points']} points</b></p><p class="small">Min: {MIN_WITHDRAW} | Max: {MAX_WITHDRAW} | Fee: {WITHDRAWAL_FEE_PERCENT}% | Auto-paid via MTN MoMo</p>{limit_msg}{kyc_warn}<form method="post"><input name="amount" type="number" placeholder="Amount ({MIN_WITHDRAW}-{MAX_WITHDRAW})" min="{MIN_WITHDRAW}" max="{min(MAX_WITHDRAW,user['points'])}" required {'disabled' if withdraw_count>=MAX_WITHDRAWS_PER_DAY else ''}><input name="momo" placeholder="MTN MoMo Number: 677123456" required {'disabled' if withdraw_count>=MAX_WITHDRAWS_PER_DAY else ''}><button class="btn btn-green" type="submit" {'disabled' if withdraw_count>=MAX_WITHDRAWS_PER_DAY else ''}>Request Auto-Payout</button></form><p><a href="/history">View history</a> | <a href="/kyc">Upload KYC</a></p></div>'''
 return render_page(content)
@app.route('/history')
def history():
 if 'user_id' not in session:return redirect('/login')
 conn=get_db()
 cur=conn.cursor()
 cur.execute('''SELECT amount,fee,net_amount,momo_number,status,request_date FROM withdrawals WHERE user_id=%s ORDER BY request_date DESC''',(session['user_id'],))
 withdrawals=cur.fetchall()
 conn.close()
 rows=''
 for w in withdrawals:
  if w['status']=='paid':badge='<span class="badge" style="background:#28a745">Paid</span>'
  else:badge='<span class="badge" style="background:#ffc107">Pending</span>'
  rows+=f'''<tr><td>{w['net_amount']} FCFA</td><td class="small">Fee: {w['fee']}</td><td>{w['momo_number']}</td><td>{badge}</td><td>{w['request_date'].strftime('%Y-%m-%d %H:%M')}</td></tr>'''
 content=f'''<div class="card"><h1>📋 Withdrawal History</h1><table><tr><th>Net Amount</th><th>Fee</th><th>MoMo</th><th>Status</th><th>Date</th></tr>{rows if rows else '<tr><td colspan="5">No withdrawals yet</td></tr>'}</table><p><a href="/withdraw" class="btn btn-green">New Withdrawal</a></p></div>'''
 return render_page(content)
@app.route('/leaderboard')
def leaderboard():
 conn=get_db()
 cur=conn.cursor()
 cur.execute('SELECT email,points FROM users ORDER BY points DESC LIMIT 10')
 top=cur.fetchall()
 conn.close()
 rows=''.join([f'<tr><td>{i+1}</td><td>{u["email"]}</td><td>{u["points"]}</td></tr>' for i,u in enumerate(top)])
 content=f'''<div class="card"><h1>🏆 Top 10 Earners</h1><table><tr><th>#</th><th>User</th><th>Points</th></tr>{rows if rows else '<tr><td colspan="3">No users yet</td></tr>'}</table></div>'''
 return render_page(content)
@app.route('/admin')
def admin():
 if 'user_id' not in session:return redirect('/login')
 conn=get_db()
 cur=conn.cursor()
 cur.execute('SELECT email FROM users WHERE id=%s',(session['user_id'],))
 user=cur.fetchone()
 if user['email']!='admin@test.com':
  conn.close()
  flash('Access denied')
  return redirect('/')
 cur.execute('SELECT COUNT(*) as cnt FROM users')
 total_users=cur.fetchone()['cnt']
 cur.execute("SELECT COUNT(*) as cnt FROM withdrawals WHERE status='pending'")
 pending_wd=cur.fetchone()['cnt']
 cur.execute("SELECT COALESCE(SUM(fee),0) as total_fees FROM withdrawals WHERE status='paid'")
 total_fees=cur.fetchone()['total_fees']
 cur.execute("SELECT COALESCE(SUM(net_amount),0) as paid_out FROM withdrawals WHERE status='paid'")
 paid_out=cur.fetchone()['paid_out']
 cur.execute('''SELECT DATE(join_date) as day,COUNT(*) as cnt FROM users WHERE join_date > NOW() - INTERVAL '7 days' GROUP BY DATE(join_date) ORDER BY day''')
 signups=cur.fetchall()
 signup_labels=[s['day'].strftime('%m-%d') for s in signups]
 signup_data=[s['cnt'] for s in signups]
 cur.execute('''SELECT w.id,w.amount,w.fee,w.net_amount,w.momo_number,w.status,w.request_date,w.momo_ref,u.email,u.kyc_status FROM withdrawals w JOIN users u ON w.user_id=u.id ORDER BY w.request_date DESC LIMIT 20''')
 withdrawals=cur.fetchall()
 conn.close()
 rows=''
 for w in withdrawals:
  status_color='#28a745' if w['status']=='paid' else '#ffc107'
  action=f'<a href="/pay/{w["id"]}" class="btn btn-green">Auto-Pay</a>' if w['status']=='pending' else 'Done'
  kyc=f'<span class="badge" style="background:#28a745">KYC</span>' if w['kyc_status']=='approved' else ''
  momo_status=f'<br><span class="small">Ref: {w["momo_ref"][:8] if w["momo_ref"] else ""}</span>' if w['momo_ref'] else ''
  rows+=f'''<tr><td>{w['id']}</td><td>{w['email']} {kyc}</td><td>{w['net_amount']} FCFA</td><td class="small">{w['fee']}</td><td>{w['momo_number']}</td><td><span class="badge" style="background:{status_color}">{w['status']}</span>{momo_status}</td><td>{w['request_date'].strftime('%m-%d %H:%M')}</td><td>{action}</td></tr>'''
 content=f'''<div class="card"><h1>🔒 Admin Dashboard V9</h1><div class="grid"><div class="stat"><div class="stat-num">{total_users}</div><div class="small">Total Users</div></div><div class="stat"><div class="stat-num">{pending_wd}</div><div class="small">Pending WD</div></div><div class="stat"><div class="stat-num">{total_fees}</div><div class="small">Fees Earned FCFA</div></div><div class="stat"><div class="stat-num">{paid_out}</div><div class="small">Paid Out FCFA</div></div></div></div><div class="card"><h3>📈 Signups Last 7 Days</h3><canvas id="signupChart"></canvas><script>new Chart(document.getElementById('signupChart'),{{type:'line',data:{{labels:{json.dumps(signup_labels)},datasets:[{{label:'New Users',data:{json.dumps(signup_data)},borderColor:'#0088cc',tension:0.1}}]}},options:{{responsive:true,maintainAspectRatio:true}}}});</script></div><div class="card"><h3>💰 Recent Withdrawals</h3><p class="small">MTN API: {MTN_TARGET_ENV.upper()} | Platform earns {WITHDRAWAL_FEE_PERCENT}%</p><table><tr><th>ID</th><th>User</th><th>Net Pay</th><th>Fee</th><th>MoMo</th><th>Status</th><th>Date</th><th>Action</th></tr>{rows if rows else '<tr><td colspan="8">No withdrawal requests yet</td></tr>'}</table></div>'''
 return render_page(content)
@app.route('/pay/<int:wid>')
def pay(wid):
 if 'user_id' not in session:return redirect('/login')
 conn=get_db()
 cur=conn.cursor()
 cur.execute('SELECT email FROM users WHERE id=%s',(session['user_id'],))
 user=cur.fetchone()
 if user['email']!='admin@test.com':
  conn.close()
  flash('Access denied')
  return redirect('/')
 cur.execute('''SELECT w.net_amount,w.momo_number,u.telegram_id,u.email,u.kyc_status FROM withdrawals w JOIN users u ON w.user_id=u.id WHERE w.id=%s AND w.status='pending' ''',(wid,))
 w_data=cur.fetchone()
 if not w_data:
  conn.close()
  flash('Withdrawal not found or already paid')
  return redirect('/admin')
 external_id=str(uuid.uuid4())
 success,msg=send_momo_payment(w_data['net_amount'],w_data['momo_number'],external_id)
 if success:
  cur.execute('UPDATE withdrawals SET status=%s,momo_ref=%s WHERE id=%s',('paid',external_id,wid))
  conn.commit()
  if w_data['telegram_id']:
   tg_msg=f"✅ <b>EarnLink Auto-Payout Complete</b>\n\n<b>{w_data['net_amount']} FCFA</b> sent to {w_data['momo_number']}.\n\nCheck your MoMo balance!"
   send_telegram(w_data['telegram_id'],tg_msg)
  flash(f'✅ Auto-paid {w_data["net_amount"]} FCFA to {w_data["momo_number"]}. Ref: {external_id[:8]}')
 else:
  flash(f'❌ MTN API failed: {msg}. Mark manually or retry.')
 conn.close()
 return redirect('/admin')
@app.route('/logout')
def logout():
 session.clear()
 return redirect('/login')
if __name__=='__main__':
 port=int(os.environ.get('PORT',5000))
 app.run(host='0.0.0.0',port=port)
