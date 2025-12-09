from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file, abort
import requests
import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "super_secret_admin_key")

# --- CONFIGURATION ---
DB_PATH = os.environ.get("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
# NEW: កំណត់ផ្លូវចូល Admin សម្ងាត់ (អាចប្តូរតាមចិត្តក្នុង Environment Variable លើ Render)
# បើមិនកំណត់ទេ ផ្លូវលំនាំដើមគឺ /secure_login
ADMIN_LOGIN_PATH = os.environ.get("ADMIN_PATH", "secure_login")

# --- DATABASE SETUP ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, api_key TEXT, credits INTEGER, expiry_date TEXT, is_active INTEGER, created_at TEXT, plan TEXT DEFAULT 'Standard')''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, cost INTEGER, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers
                 (code TEXT PRIMARY KEY, amount INTEGER, is_used INTEGER, created_at TEXT, used_by TEXT)''')
    
    defaults = {
        'sora_api_key': os.environ.get("SORA_API_KEY", "sk-DEFAULT"),
        'cost_sora_2': '25', 'cost_sora_2_pro': '35',
        'limit_mini': '1', 'limit_basic': '2', 'limit_standard': '3',
        'broadcast_msg': ''
    }
    for k, v in defaults.items():
        try: c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
        except: pass
    conn.commit()
    conn.close()

init_db()

# --- HELPER FUNCTIONS ---
def get_setting(key, default=None):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone(); conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit(); conn.close()

def generate_voucher_code(amount):
    import random, string
    chars = string.ascii_uppercase + string.digits
    return f"SORA-{amount}-{''.join(random.choices(chars, k=6))}"

# --- HTML TEMPLATES ---
MODERN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sora Admin</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root { --primary: #6C5CE7; --bg: #f5f6fa; --white: #ffffff; }
        body { font-family: sans-serif; background: var(--bg); margin: 0; display: flex; height: 100vh; }
        .sidebar { width: 250px; background: var(--white); padding: 20px; display: flex; flex-direction: column; }
        .nav-link { padding: 12px; color: #333; text-decoration: none; display: block; margin-bottom: 5px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { background: var(--primary); color: white; }
        .main { flex: 1; padding: 30px; overflow-y: auto; }
        .card { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
        .btn { padding: 8px 12px; border: none; border-radius: 5px; cursor: pointer; color: white; text-decoration: none; }
        .btn-primary { background: var(--primary); }
        .btn-danger { background: #ff7675; }
        input, select { padding: 8px; border: 1px solid #ddd; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:var(--primary);"><i class="fas fa-robot"></i> Admin</h2>
        <a href="/dashboard" class="nav-link {{ 'active' if page == 'users' else '' }}">Users</a>
        <a href="/vouchers" class="nav-link {{ 'active' if page == 'vouchers' else '' }}">Vouchers</a>
        <a href="/logs" class="nav-link {{ 'active' if page == 'logs' else '' }}">Logs</a>
        <a href="/settings" class="nav-link {{ 'active' if page == 'settings' else '' }}">Settings</a>
        <a href="/logout" class="nav-link" style="color:red; margin-top:auto;">Logout</a>
    </div>
    <div class="main">
        {% if page == 'users' %}
            <h1>User Management</h1>
            <div class="card">
                <h3>Add User</h3>
                <form action="/add_user" method="POST">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="number" name="credits" placeholder="Credits" required>
                    <select name="plan"><option>Mini</option><option>Basic</option><option selected>Standard</option></select>
                    <input type="date" name="expiry" required>
                    <button class="btn btn-primary">Create</button>
                </form>
            </div>
            <div class="card">
                <table>
                    <thead><tr><th>User</th><th>Key</th><th>Plan</th><th>Credits</th><th>Status</th><th>Action</th></tr></thead>
                    <tbody>
                        {% for u in users %}
                        <tr>
                            <td>{{ u[0] }}</td><td>{{ u[1] }}</td><td>{{ u[6] }}</td><td>{{ u[2] }}</td>
                            <td>{{ 'Active' if u[4] else 'Banned' }}</td>
                            <td>
                                <a href="/toggle_status/{{ u[0] }}" class="btn btn-primary">Toggle</a>
                                <a href="/delete_user/{{ u[0] }}" class="btn btn-danger">Del</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% elif page == 'vouchers' %}
            <h1>Vouchers</h1>
            <div class="card">
                <form action="/generate_vouchers" method="POST">
                    <input type="number" name="amount" placeholder="Amount" required>
                    <input type="number" name="count" placeholder="Qty" value="1">
                    <button class="btn btn-primary">Generate</button>
                </form>
            </div>
            <div class="card">
                <table><thead><tr><th>Code</th><th>Amount</th><th>Status</th></tr></thead>
                <tbody>{% for v in vouchers %}<tr><td>{{ v[0] }}</td><td>{{ v[1] }}</td><td>{{ 'Used' if v[2] else 'Active' }}</td></tr>{% endfor %}</tbody></table>
            </div>
        {% elif page == 'settings' %}
            <h1>Settings</h1>
            <div class="card">
                <h3>Broadcast</h3>
                <form action="/update_broadcast" method="POST">
                    <input type="text" name="message" value="{{ broadcast_msg }}" style="width:300px;">
                    <button class="btn btn-primary">Update</button>
                    <a href="/clear_broadcast" class="btn btn-danger">Clear</a>
                </form>
            </div>
            <div class="card">
                <h3>System</h3>
                <p>Login Path: <code>/{{ login_path }}</code></p>
                <form action="/update_settings" method="POST">
                    <label>API Key:</label> <input type="text" name="sora_api_key" value="{{ api_key }}"><br><br>
                    <label>Sora-2 Cost:</label> <input type="number" name="cost_sora_2" value="{{ costs.sora_2 }}"><br><br>
                    <label>Pro Cost:</label> <input type="number" name="cost_sora_2_pro" value="{{ costs.sora_2_pro }}"><br><br>
                    <button class="btn btn-primary">Save</button>
                </form>
            </div>
            <div class="card"><a href="/download_db" class="btn btn-primary">Download DB Backup</a></div>
        {% else %}
            <h1>Logs</h1>
            <div class="card"><table><tbody>{% for l in logs %}<tr><td>{{ l[4] }}</td><td>{{ l[1] }}</td><td>{{ l[2] }}</td></tr>{% endfor %}</tbody></table></div>
        {% endif %}
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html><html><body style="background:#f0f2f5;height:100vh;display:flex;justify-content:center;align-items:center;font-family:sans-serif;">
<form method="POST" style="background:white;padding:40px;border-radius:10px;box-shadow:0 5px 15px rgba(0,0,0,0.1);text-align:center;">
    <h2>Admin Login</h2>
    <input type="password" name="password" placeholder="Enter Password" style="padding:10px;width:200px;margin-bottom:15px;border:1px solid #ddd;border-radius:5px;"><br>
    <button style="padding:10px 20px;background:#6C5CE7;color:white;border:none;border-radius:5px;cursor:pointer;">Login</button>
</form></body></html>
"""

# --- AUTH DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return redirect(f'/{ADMIN_LOGIN_PATH}')
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES ---

# 1. ROOT URL (Public) - Hides Admin Panel
@app.route('/')
def home():
    return jsonify({"status": "Server is running securely.", "version": "1.0"}), 200

# 2. SECRET LOGIN URL (Dynamic)
@app.route(f'/{ADMIN_LOGIN_PATH}', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/dashboard')
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(f'/{ADMIN_LOGIN_PATH}')

# --- ADMIN ROUTES ---
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = c.fetchall(); conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='users', users=users)

@app.route('/vouchers')
@login_required
def vouchers():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM vouchers ORDER BY created_at DESC LIMIT 50")
    v = c.fetchall(); conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='vouchers', vouchers=v)

@app.route('/logs')
@login_required
def view_logs():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
    l = c.fetchall(); conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='logs', logs=l)

@app.route('/settings')
@login_required
def settings():
    k = get_setting('sora_api_key', '')
    msg = get_setting('broadcast_msg', '')
    costs = {'sora_2': get_setting('cost_sora_2', 25), 'sora_2_pro': get_setting('cost_sora_2_pro', 35)}
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', api_key=k, broadcast_msg=msg, costs=costs, login_path=ADMIN_LOGIN_PATH)

# --- ACTION ROUTES ---
@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    try:
        conn = get_db()
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, 1, ?, ?)", 
                     (request.form['username'], "sk-"+str(uuid.uuid4())[:18], int(request.form['credits']), request.form['expiry'], datetime.now().strftime("%Y-%m-%d"), request.form['plan']))
        conn.commit(); conn.close()
    except: pass
    return redirect('/dashboard')

@app.route('/delete_user/<username>')
@login_required
def delete_user(username):
    conn = get_db(); conn.execute("DELETE FROM users WHERE username=?", (username,)); conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/toggle_status/<username>')
@login_required
def toggle_status(username):
    conn = get_db()
    conn.execute("UPDATE users SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE username=?", (username,))
    conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/generate_vouchers', methods=['POST'])
@login_required
def generate_vouchers():
    amt = int(request.form['amount']); qty = int(request.form['count'])
    conn = get_db()
    for _ in range(qty):
        conn.execute("INSERT INTO vouchers VALUES (?, ?, 0, ?, NULL)", (generate_voucher_code(amt), amt, str(datetime.now())))
    conn.commit(); conn.close()
    return redirect('/vouchers')

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    for k,v in request.form.items(): set_setting(k, v)
    return redirect('/settings')

@app.route('/update_broadcast', methods=['POST'])
@login_required
def update_broadcast():
    set_setting('broadcast_msg', request.form.get('message'))
    return redirect('/settings')

@app.route('/clear_broadcast')
@login_required
def clear_broadcast():
    set_setting('broadcast_msg', '')
    return redirect('/settings')

@app.route('/download_db')
@login_required
def download_db():
    if os.path.exists(DB_PATH): return send_file(DB_PATH, as_attachment=True)
    return "No DB"

# --- CLIENT API ROUTES (Unchanged) ---
@app.route('/api/verify', methods=['POST'])
def verify_user():
    d = request.json
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT credits, expiry_date, is_active, plan FROM users WHERE username=? AND api_key=?", (d.get('username'), d.get('api_key')))
    u = c.fetchone()
    b = get_setting('broadcast_msg', '')
    conn.close()
    if not u: return jsonify({"valid": False, "message": "Invalid Credentials"})
    if not u[2]: return jsonify({"valid": False, "message": "Banned"})
    if datetime.now() > datetime.strptime(u[1], "%Y-%m-%d"): return jsonify({"valid": False, "message": "Expired"})
    limit = int(get_setting(f"limit_{u[3].lower()}", 3))
    return jsonify({"valid": True, "credits": u[0], "expiry": u[1], "plan": u[3], "concurrency_limit": limit, "broadcast": b})

@app.route('/api/redeem', methods=['POST'])
def redeem():
    d = request.json
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT amount, is_used FROM vouchers WHERE code=?", (d.get('code'),))
    v = c.fetchone()
    if not v or v[1]: conn.close(); return jsonify({"success": False, "message": "Invalid/Used Code"})
    c.execute("UPDATE users SET credits=credits+? WHERE username=?", (v[0], d.get('username')))
    c.execute("UPDATE vouchers SET is_used=1, used_by=? WHERE code=?", (d.get('username'), d.get('code')))
    conn.commit(); conn.close()
    return jsonify({"success": True, "message": f"Added {v[0]} Credits"})

@app.route('/api/proxy/generate', methods=['POST'])
def proxy_gen():
    auth = request.headers.get("Client-Auth", ""); 
    if ":" not in auth: return jsonify({"code":-1}), 401
    u, k = auth.split(":")
    conn = get_db(); row = conn.execute("SELECT credits FROM users WHERE username=? AND api_key=?", (u,k)).fetchone()
    if not row: conn.close(); return jsonify({"code":-1}), 401
    
    model = request.json.get('model', '')
    cost = int(get_setting('cost_sora_2_pro', 35)) if "pro" in model else int(get_setting('cost_sora_2', 25))
    if row[0] < cost: conn.close(); return jsonify({"code":-1, "message": "No Credits"}), 402
    
    try:
        real_key = get_setting('sora_api_key')
        r = requests.post("https://FreeSoraGenerator.com/api/v1/video/sora-video", json=request.json, headers={"Authorization": f"Bearer {real_key}"}, timeout=120)
        if r.json().get("code") == 0:
            conn.execute("UPDATE users SET credits=credits-? WHERE username=?", (cost, u))
            conn.commit()
            r_json = r.json()
            r_json['user_balance'] = row[0] - cost
            return jsonify(r_json), r.status_code
        return jsonify(r.json()), r.status_code
    except Exception as e: return jsonify({"code":-1, "message": str(e)}), 500
    finally: conn.close()

@app.route('/api/proxy/check-result', methods=['POST'])
def proxy_chk():
    try:
        rk = get_setting('sora_api_key')
        r = requests.post("https://FreeSoraGenerator.com/api/video-generations/check-result", json=request.json, headers={"Authorization": f"Bearer {rk}"}, timeout=30)
        return jsonify(r.json()), r.status_code
    except: return jsonify({"code":-1}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
