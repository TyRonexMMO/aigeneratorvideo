from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file, abort
import requests
import os
import sqlite3
import uuid
import time
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "super_secret_admin_key")

# --- CONFIGURATION ---
DB_PATH = os.environ.get("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_LOGIN_PATH = os.environ.get("ADMIN_PATH", "secure_login")

# Security Config
MAX_SUSPICIOUS_ATTEMPTS = 5  # ចុចខុស ៥ ដង Ban ភ្លាម
BAN_DURATION_HOURS = 24      # Ban រយៈពេល ២៤ ម៉ោង (ឬរហូត)

# In-Memory tracker for suspicious activity (Reset on restart)
suspicious_tracker = {} 

DEFAULT_COSTS = {'sora_2': 25, 'sora_2_pro': 35}
DEFAULT_LIMITS = {'mini': 1, 'basic': 2, 'standard': 3}

# --- DATABASE SETUP ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Users
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, api_key TEXT, credits INTEGER, expiry_date TEXT, is_active INTEGER, created_at TEXT, plan TEXT DEFAULT 'Standard')''')
    # Logs
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, cost INTEGER, timestamp TEXT)''')
    # Settings
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    # Vouchers
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers
                 (code TEXT PRIMARY KEY, amount INTEGER, is_used INTEGER, created_at TEXT, used_by TEXT)''')
    # Tasks
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (task_id TEXT PRIMARY KEY, username TEXT, cost INTEGER, status TEXT, created_at TEXT)''')
    # NEW: Banned IPs Table
    c.execute('''CREATE TABLE IF NOT EXISTS banned_ips
                 (ip TEXT PRIMARY KEY, reason TEXT, banned_at TEXT)''')

    # Defaults
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

def get_client_ip():
    # Handle Render/Proxy IP forwarding
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

# --- SECURITY MIDDLEWARE (THE IRON DOME) ---
@app.before_request
def security_guard():
    ip = get_client_ip()
    
    # 1. Check if IP is already banned in Database
    conn = get_db()
    is_banned = conn.execute("SELECT 1 FROM banned_ips WHERE ip=?", (ip,)).fetchone()
    conn.close()
    
    if is_banned:
        # Stop request immediately with 403 Forbidden
        return jsonify({"code": 403, "message": "Access Denied: Your IP has been banned due to suspicious activity."}), 403

    # 2. Admin Immunity: If logged in, skip checks
    if 'logged_in' in session:
        return # Allow everything for authenticated admin

    # 3. Allow Valid Paths (Public API & The Secret Login)
    valid_starts = ['/api/', '/static/']
    if request.path == f'/{ADMIN_LOGIN_PATH}' or any(request.path.startswith(p) for p in valid_starts) or request.path == '/':
        return # Safe path

    # 4. Detect Suspicious Activity (Trying to access /admin, /dashboard without login, etc.)
    # If code reaches here, the path is invalid or protected and user is NOT logged in.
    
    current_count = suspicious_tracker.get(ip, 0) + 1
    suspicious_tracker[ip] = current_count
    
    print(f"⚠️ Suspicious activity from {ip}: Tried accessing {request.path} (Count: {current_count})")

    if current_count >= MAX_SUSPICIOUS_ATTEMPTS:
        # BAN HAMMER
        try:
            conn = get_db()
            conn.execute("INSERT OR IGNORE INTO banned_ips (ip, reason, banned_at) VALUES (?, ?, ?)", 
                         (ip, f"Excessive scanning: {request.path}", str(datetime.now())))
            conn.commit()
            conn.close()
            print(f"🚫 BANNED IP: {ip}")
        except: pass
        return jsonify({"code": 403, "message": "Access Denied"}), 403

    # Return Fake 404 to confuse scanners
    return "Not Found", 404

# --- MODERN KHMER DASHBOARD HTML ---
MODERN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="km">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sora Admin Security</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root { --primary: #4F46E5; --danger: #ef4444; --bg: #f1f5f9; --white: #fff; --dark: #1e293b; }
        body { font-family: 'Kantumruy Pro', sans-serif; background: var(--bg); margin: 0; display: flex; height: 100vh; color: var(--dark); }
        .sidebar { width: 260px; background: var(--white); padding: 20px; display: flex; flex-direction: column; }
        .nav-link { padding: 14px; color: #64748b; text-decoration: none; display: block; margin-bottom: 8px; border-radius: 12px; font-weight: 600; }
        .nav-link:hover, .nav-link.active { background: #e0e7ff; color: var(--primary); }
        .main { flex: 1; padding: 30px; overflow-y: auto; }
        .card { background: var(--white); padding: 25px; border-radius: 16px; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 15px; color: #64748b; border-bottom: 2px solid #f1f5f9; }
        td { padding: 15px; border-bottom: 1px solid #f1f5f9; }
        .btn { padding: 8px 12px; border: none; border-radius: 8px; cursor: pointer; color: white; text-decoration: none; font-size: 13px; }
        .btn-danger { background: var(--danger); }
        .btn-primary { background: var(--primary); }
        .badge-banned { background: #fee2e2; color: #b91c1c; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
        h4 { margin-top: 0; border-bottom: 2px solid #f1f5f9; padding-bottom: 10px; color: var(--primary); }
        input { padding: 10px; border: 1px solid #e2e8f0; border-radius: 8px; width: 100%; box-sizing: border-box; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:var(--primary);"><i class="fas fa-shield-alt"></i> SoraAdmin</h2>
        <a href="/dashboard" class="nav-link {{ 'active' if page == 'users' else '' }}"><i class="fas fa-users"></i> អ្នកប្រើប្រាស់</a>
        <a href="/vouchers" class="nav-link {{ 'active' if page == 'vouchers' else '' }}"><i class="fas fa-ticket-alt"></i> ប័ណ្ណ</a>
        <a href="/security" class="nav-link {{ 'active' if page == 'security' else '' }}"><i class="fas fa-user-shield"></i> សុវត្ថិភាព (Security)</a>
        <a href="/settings" class="nav-link {{ 'active' if page == 'settings' else '' }}"><i class="fas fa-cogs"></i> ការកំណត់</a>
        <a href="/logout" class="nav-link" style="color:var(--danger); margin-top:auto;"><i class="fas fa-sign-out-alt"></i> ចាកចេញ</a>
    </div>

    <div class="main">
        {% if page == 'users' %}
            <h1>គ្រប់គ្រងអ្នកប្រើប្រាស់</h1>
            <div class="card">
                <h3>បន្ថែមថ្មី</h3>
                <form action="/add_user" method="POST" style="display:flex; gap:10px;">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="number" name="credits" placeholder="Credits" required>
                    <select name="plan" style="padding:10px; border-radius:8px; border:1px solid #e2e8f0;"><option>Mini</option><option>Basic</option><option selected>Standard</option></select>
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
                            <td><b>{{ u[0] }}</b></td><td style="font-family:monospace; color:#64748b;">{{ u[1] }}</td><td>{{ u[6] }}</td>
                            <td style="color:{{ '#ef4444' if u[2] < 50 else '#10b981' }}; font-weight:bold;">{{ u[2] }}</td>
                            <td>{{ 'Active' if u[4] else 'Banned' }}</td>
                            <td>
                                <form action="/update_credits" method="POST" style="display:inline;">
                                    <input type="hidden" name="username" value="{{ u[0] }}">
                                    <input type="number" name="amount" placeholder="+/-" style="width:60px; padding:5px;">
                                    <button class="btn btn-primary">Save</button>
                                </form>
                                <a href="/toggle_status/{{ u[0] }}" class="btn btn-primary" style="background:#64748b;">Block</a>
                                <a href="/delete_user/{{ u[0] }}" class="btn btn-danger" onclick="return confirm('Delete?')">Del</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% elif page == 'security' %}
            <h1>សុវត្ថិភាពប្រព័ន្ធ (Security)</h1>
            <div class="card">
                <h4><i class="fas fa-ban"></i> បញ្ជី IP ដែលត្រូវបាន Ban (Blacklist)</h4>
                <p style="color:#64748b; font-size:14px;">IP ទាំងនេះត្រូវបានបិទដោយស្វ័យប្រវត្តិ ដោយសារការព្យាយាមចូលមិនប្រក្រតី។</p>
                <table>
                    <thead><tr><th>IP Address</th><th>មូលហេតុ (Reason)</th><th>ពេលវេលា (Time)</th><th>សកម្មភាព</th></tr></thead>
                    <tbody>
                        {% for ip in banned_ips %}
                        <tr>
                            <td style="font-family:monospace; font-weight:bold;">{{ ip[0] }}</td>
                            <td>{{ ip[1] }}</td>
                            <td>{{ ip[2] }}</td>
                            <td><a href="/unban_ip/{{ ip[0] }}" class="btn btn-success" style="background:#10b981;">Unban (ដោះលែង)</a></td>
                        </tr>
                        {% else %}
                        <tr><td colspan="4" style="text-align:center;">មិនមាន IP ជាប់ Ban ទេ (Clean)</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% elif page == 'vouchers' %}
            <h1>ប័ណ្ណបញ្ចូលលុយ</h1>
            <div class="card">
                <form action="/generate_vouchers" method="POST" style="display:flex; gap:10px;">
                    <input type="number" name="amount" placeholder="Amount" required>
                    <input type="number" name="count" placeholder="Qty" value="1">
                    <button class="btn btn-primary">Generate</button>
                </form>
            </div>
            <div class="card">
                <table><thead><tr><th>Code</th><th>Amount</th><th>Status</th><th>Used By</th></tr></thead>
                <tbody>{% for v in vouchers %}<tr><td style="font-family:monospace; font-weight:bold;">{{ v[0] }}</td><td style="color:#10b981;">+{{ v[1] }}</td><td>{{ 'Used' if v[2] else 'Active' }}</td><td>{{ v[4] }}</td></tr>{% endfor %}</tbody></table>
            </div>
        {% elif page == 'settings' %}
            <h1>ការកំណត់</h1>
            <div class="card">
                <h4>Broadcast</h4>
                <form action="/update_broadcast" method="POST" style="display:flex; gap:10px;">
                    <input type="text" name="message" value="{{ broadcast_msg }}" placeholder="សរសេរសារ...">
                    <button class="btn btn-primary">Update</button>
                    <a href="/clear_broadcast" class="btn btn-danger">Clear</a>
                </form>
            </div>
            <div class="card">
                <h4>API & Costs</h4>
                <form action="/update_settings" method="POST">
                    <label>API Key:</label> <input type="text" name="sora_api_key" value="{{ api_key }}" style="margin-bottom:10px;">
                    <div style="display:flex; gap:10px;">
                        <input type="number" name="cost_sora_2" value="{{ costs.sora_2 }}" placeholder="Sora-2 Cost">
                        <input type="number" name="cost_sora_2_pro" value="{{ costs.sora_2_pro }}" placeholder="Pro Cost">
                    </div>
                    <button class="btn btn-primary" style="margin-top:10px;">Save Changes</button>
                </form>
            </div>
             <div class="card"><a href="/download_db" class="btn btn-primary">Download Backup</a></div>
        {% endif %}
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html><html><body style="background:#f0f2f5;height:100vh;display:flex;justify-content:center;align-items:center;font-family:sans-serif;">
<form method="POST" style="background:white;padding:40px;border-radius:16px;box-shadow:0 10px 25px rgba(0,0,0,0.1);text-align:center;width:350px;">
    <h2>Admin Access</h2>
    <p style="color:gray;font-size:12px;">Secure Gateway</p>
    <input type="password" name="password" placeholder="Password" style="width:100%;padding:12px;margin-bottom:20px;border:1px solid #ddd;border-radius:8px;box-sizing:border-box;">
    <button style="width:100%;padding:12px;background:#4F46E5;color:white;border:none;border-radius:8px;font-weight:bold;cursor:pointer;">Enter</button>
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
@app.route('/')
def home():
    # Stealth Mode: Return plain JSON to confuse scanners
    return jsonify({"status": "running", "uptime": "99.9%"}), 200

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

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = c.fetchall(); conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='users', users=users, total_users=len(users), active_users=sum(1 for u in users if u[4]), total_credits=sum(u[2] for u in users))

@app.route('/security')
@login_required
def security_page():
    conn = get_db()
    ips = conn.execute("SELECT * FROM banned_ips ORDER BY banned_at DESC").fetchall()
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='security', banned_ips=ips)

@app.route('/unban_ip/<path:ip>')
@login_required
def unban_ip(ip):
    conn = get_db()
    conn.execute("DELETE FROM banned_ips WHERE ip=?", (ip,))
    conn.commit()
    conn.close()
    # Also clear from memory tracker
    if ip in suspicious_tracker: del suspicious_tracker[ip]
    return redirect('/security')

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
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', api_key=k, broadcast_msg=msg, costs=costs)

# --- ACTION ROUTES (User Mgmt) ---
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

@app.route('/update_credits', methods=['POST'])
@login_required
def update_credits():
    conn = get_db()
    conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", (int(request.form['amount']), request.form['username']))
    conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/update_plan', methods=['POST'])
@login_required
def update_plan():
    conn = get_db()
    conn.execute("UPDATE users SET plan = ? WHERE username = ?", (request.form['plan'], request.form['username']))
    conn.commit(); conn.close()
    return redirect('/dashboard')

# --- SETTINGS ACTIONS ---
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

# --- CLIENT API ROUTES (SAME AS BEFORE) ---
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
    auth = request.headers.get("Client-Auth", "")
    if ":" not in auth: return jsonify({"code":-1}), 401
    u, k = auth.split(":")
    conn = get_db(); row = conn.execute("SELECT credits FROM users WHERE username=? AND api_key=?", (u,k)).fetchone()
    if not row: conn.close(); return jsonify({"code":-1}), 401
    
    model = request.json.get('model', '')
    cost = int(get_setting('cost_sora_2_pro', 35)) if "pro" in model else int(get_setting('cost_sora_2', 25))
    if row[0] < cost: conn.close(); return jsonify({"code":-1, "message": "Insufficient Credits"}), 402
    
    try:
        real_key = get_setting('sora_api_key')
        r = requests.post("https://FreeSoraGenerator.com/api/v1/video/sora-video", json=request.json, headers={"Authorization": f"Bearer {real_key}"}, timeout=120)
        
        if r.json().get("code") == 0:
            task_id = r.json().get('data', {}).get('taskId')
            if task_id:
                 conn.execute("INSERT INTO tasks (task_id, username, cost, status, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, u, cost, 'pending', str(datetime.now())))
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
        
        data = r.json()
        if data.get('data', {}).get('status') == 'failed':
            task_id = request.json.get('taskId')
            conn = get_db()
            task = conn.execute("SELECT username, cost, status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task and task[2] != 'refunded':
                conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", (task[1], task[0]))
                conn.execute("UPDATE tasks SET status = 'refunded' WHERE task_id = ?", (task_id,))
                conn.execute("INSERT INTO logs (username, action, cost, timestamp) VALUES (?, ?, ?, ?)", (task[0], f"Refund {task_id}", 0, str(datetime.now())))
                conn.commit()
            conn.close()

        return jsonify(data), r.status_code
    except: return jsonify({"code":-1}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
