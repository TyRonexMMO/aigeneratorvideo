from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file
import requests
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "super_secret_admin_key")

# --- CONFIGURATION ---
DB_PATH = os.environ.get("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# Default Configs (Will be saved to DB)
DEFAULT_COSTS = {
    'sora_2': 25,
    'sora_2_pro': 35
}
DEFAULT_LIMITS = {
    'mini': 1,
    'basic': 2,
    'standard': 3
}

# --- DATABASE SETUP ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, 
                  api_key TEXT, 
                  credits INTEGER, 
                  expiry_date TEXT, 
                  is_active INTEGER,
                  created_at TEXT,
                  plan TEXT DEFAULT 'Standard')''') # Added plan column
    
    # Logs Table
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  action TEXT,
                  cost INTEGER,
                  timestamp TEXT)''')
    
    # Settings Table
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    # Initialize Default Settings
    defaults = {
        'sora_api_key': os.environ.get("SORA_API_KEY", "sk-DEFAULT_KEY"),
        'cost_sora_2': str(DEFAULT_COSTS['sora_2']),
        'cost_sora_2_pro': str(DEFAULT_COSTS['sora_2_pro']),
        'limit_mini': str(DEFAULT_LIMITS['mini']),
        'limit_basic': str(DEFAULT_LIMITS['basic']),
        'limit_standard': str(DEFAULT_LIMITS['standard'])
    }

    for key, val in defaults.items():
        try:
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, val))
        except sqlite3.IntegrityError:
            pass # Already exists
            
    conn.commit()
    conn.close()

def migrate_db():
    """Ensure existing DB has new columns"""
    conn = get_db()
    try:
        # Try to select the 'plan' column
        conn.execute("SELECT plan FROM users LIMIT 1")
    except sqlite3.OperationalError:
        # If missing, add it
        print("Migrating DB: Adding 'plan' column...")
        conn.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'Standard'")
        conn.commit()
    conn.close()

init_db()
migrate_db()

# --- HELPER FUNCTIONS ---
def get_setting(key, default=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# --- MODERN DASHBOARD HTML TEMPLATE ---
MODERN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sora Admin</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root { --primary: #6C5CE7; --secondary: #a29bfe; --dark: #2d3436; --light: #dfe6e9; --bg: #f5f6fa; --white: #ffffff; }
        body { font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: var(--bg); margin: 0; display: flex; height: 100vh; overflow: hidden; }
        
        .sidebar { width: 250px; background-color: var(--white); box-shadow: 2px 0 10px rgba(0,0,0,0.05); display: flex; flex-direction: column; padding: 20px; }
        .logo { font-size: 24px; font-weight: bold; color: var(--primary); margin-bottom: 40px; display: flex; align-items: center; gap: 10px; }
        .nav-link { display: flex; align-items: center; gap: 12px; padding: 12px 15px; color: var(--dark); text-decoration: none; border-radius: 10px; margin-bottom: 5px; transition: 0.3s; }
        .nav-link:hover, .nav-link.active { background-color: var(--primary); color: var(--white); }
        
        .main { flex-grow: 1; padding: 30px; overflow-y: auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .title { font-size: 28px; font-weight: bold; color: var(--dark); }
        
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card { background: var(--white); padding: 25px; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 20px; }
        .card-icon { width: 50px; height: 50px; border-radius: 12px; background: rgba(108, 92, 231, 0.1); color: var(--primary); display: flex; align-items: center; justify-content: center; font-size: 20px; }
        .card-info h3 { margin: 0; font-size: 14px; color: #888; }
        .card-info p { margin: 5px 0 0; font-size: 24px; font-weight: bold; color: var(--dark); }
        
        .table-container { background: var(--white); padding: 20px; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 15px; color: #888; font-weight: 600; border-bottom: 1px solid #eee; }
        td { padding: 15px; border-bottom: 1px solid #f5f5f5; color: var(--dark); vertical-align: middle; }
        
        .badge { padding: 5px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
        .badge-active { background: #e6fffa; color: #00b894; }
        .badge-banned { background: #fff5f5; color: #d63031; }
        .badge-plan { background: #f0f3ff; color: #6C5CE7; border: 1px solid #dcd6f7; }
        
        .btn { border: none; padding: 8px 12px; border-radius: 8px; cursor: pointer; transition: 0.2s; text-decoration: none; font-size: 13px; display: inline-flex; align-items: center; gap: 5px; color: white; }
        .btn-primary { background: var(--primary); }
        .btn-danger { background: #d63031; }
        .btn-success { background: #00b894; }
        .btn-icon { background: transparent; color: #b2bec3; font-size: 16px; padding: 5px; }
        .btn-icon:hover { color: var(--dark); }

        .input-group { margin-bottom: 15px; }
        .input-field { width: 100%; padding: 12px; border: 1px solid #eee; border-radius: 8px; background: #fafafa; outline: none; box-sizing: border-box; }
        .input-field:focus { border-color: var(--primary); background: white; }
        
        .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .settings-box { background: var(--white); padding: 30px; border-radius: 15px; margin-bottom: 20px; }
        h4 { margin-top: 0; color: var(--primary); margin-bottom: 15px; border-bottom: 2px solid #f5f5fa; padding-bottom: 10px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo"><i class="fas fa-robot"></i> SoraAdmin</div>
        <a href="/dashboard" class="nav-link {{ 'active' if page == 'users' else '' }}"><i class="fas fa-users"></i> Users</a>
        <a href="/logs" class="nav-link {{ 'active' if page == 'logs' else '' }}"><i class="fas fa-history"></i> Logs</a>
        <a href="/settings" class="nav-link {{ 'active' if page == 'settings' else '' }}"><i class="fas fa-sliders-h"></i> Settings</a>
        <div class="spacer"></div>
        <a href="/logout" class="nav-link" style="color: #d63031;"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>

    <div class="main">
        {% if page == 'users' %}
        <div class="header"><div class="title">User Management</div></div>
        
        <div class="grid">
            <div class="card"><div class="card-icon"><i class="fas fa-user-friends"></i></div><div class="card-info"><h3>Users</h3><p>{{ total_users }}</p></div></div>
            <div class="card"><div class="card-icon" style="color:#00b894; background:rgba(0,184,148,0.1);"><i class="fas fa-check-circle"></i></div><div class="card-info"><h3>Active</h3><p>{{ active_users }}</p></div></div>
            <div class="card"><div class="card-icon" style="color:#0984e3; background:rgba(9,132,227,0.1);"><i class="fas fa-coins"></i></div><div class="card-info"><h3>Total Credits</h3><p>{{ total_credits }}</p></div></div>
        </div>

        <div class="table-container" style="margin-bottom: 30px;">
            <h3 style="margin-top:0;">Add New User</h3>
            <form action="/add_user" method="POST" style="display: flex; gap: 15px; align-items: center;">
                <input type="text" name="username" class="input-field" placeholder="Username" required style="flex:1;">
                <input type="number" name="credits" class="input-field" placeholder="Credits" required style="width:120px;">
                <select name="plan" class="input-field" style="width:150px;">
                    <option value="Mini">Mini Plan</option>
                    <option value="Basic">Basic Plan</option>
                    <option value="Standard" selected>Standard Plan</option>
                </select>
                <input type="date" name="expiry" class="input-field" required style="width:160px;">
                <button type="submit" class="btn btn-primary" style="height: 42px;"><i class="fas fa-plus"></i> Create</button>
            </form>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>User</th>
                        <th>License Key</th>
                        <th>Plan</th>
                        <th>Credits</th>
                        <th>Expiry</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td style="font-weight:600;">{{ user[0] }}</td>
                        <td style="font-family:monospace; color:#666;">{{ user[1] }}</td>
                        <td><span class="badge badge-plan">{{ user[6] }}</span></td>
                        <td style="font-weight:bold; color: {% if user[2] < 50 %}#d63031{% else %}#00b894{% endif %};">{{ user[2] }}</td>
                        <td>{{ user[3] }}</td>
                        <td>
                            {% if user[4] %}<span class="badge badge-active">Active</span>{% else %}<span class="badge badge-banned">Banned</span>{% endif %}
                        </td>
                        <td>
                            <form action="/update_credits" method="POST" style="display:inline-flex; gap:5px;">
                                <input type="hidden" name="username" value="{{ user[0] }}">
                                <input type="number" name="amount" placeholder="+/-" style="width:60px; padding:5px; border:1px solid #ddd; border-radius:4px;">
                                <button class="btn btn-primary" style="padding:5px 10px;" title="Update Credits"><i class="fas fa-save"></i></button>
                            </form>
                            <form action="/update_plan" method="POST" style="display:inline-flex; gap:5px; margin-left: 5px;">
                                <input type="hidden" name="username" value="{{ user[0] }}">
                                <select name="plan" style="padding:5px; border:1px solid #ddd; border-radius:4px;" onchange="this.form.submit()">
                                    <option value="" disabled selected>Change Plan</option>
                                    <option value="Mini">Mini</option>
                                    <option value="Basic">Basic</option>
                                    <option value="Standard">Standard</option>
                                </select>
                            </form>
                            <a href="/toggle_status/{{ user[0] }}" class="btn-icon" title="Toggle Status"><i class="fas fa-ban"></i></a>
                            <a href="/delete_user/{{ user[0] }}" class="btn-icon" style="color:#d63031;" onclick="return confirm('Delete?')" title="Delete"><i class="fas fa-trash"></i></a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif page == 'logs' %}
        <div class="header"><div class="title">System Logs</div></div>
        <div class="table-container">
            <table>
                <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Cost</th></tr></thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                        <td>{{ log[4] }}</td>
                        <td><strong>{{ log[1] }}</strong></td>
                        <td>{{ log[2] }}</td>
                        <td style="color:#d63031;">-{{ log[3] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif page == 'settings' %}
        <div class="header"><div class="title">System Configuration</div></div>
        
        <form action="/update_settings" method="POST">
            <div class="settings-grid">
                <!-- Credit Costs -->
                <div class="settings-box">
                    <h4><i class="fas fa-tags"></i> Video Credit Costs</h4>
                    <div class="input-group">
                        <label>Sora-2 Cost (10s)</label>
                        <input type="number" name="cost_sora_2" class="input-field" value="{{ costs.sora_2 }}">
                    </div>
                    <div class="input-group">
                        <label>Sora-2 Pro Cost (15s)</label>
                        <input type="number" name="cost_sora_2_pro" class="input-field" value="{{ costs.sora_2_pro }}">
                    </div>
                </div>

                <!-- Plan Limits -->
                <div class="settings-box">
                    <h4><i class="fas fa-tachometer-alt"></i> Concurrent Process Limits</h4>
                    <div class="input-group">
                        <label>Mini Plan Limit</label>
                        <input type="number" name="limit_mini" class="input-field" value="{{ limits.mini }}">
                    </div>
                    <div class="input-group">
                        <label>Basic Plan Limit</label>
                        <input type="number" name="limit_basic" class="input-field" value="{{ limits.basic }}">
                    </div>
                    <div class="input-group">
                        <label>Standard Plan Limit</label>
                        <input type="number" name="limit_standard" class="input-field" value="{{ limits.standard }}">
                    </div>
                </div>

                <!-- API Key -->
                <div class="settings-box" style="grid-column: 1 / -1;">
                    <h4><i class="fas fa-key"></i> Backend API Key</h4>
                    <div class="input-group">
                        <input type="text" name="sora_api_key" class="input-field" value="{{ api_key }}">
                    </div>
                </div>
            </div>
            <button type="submit" class="btn btn-primary" style="padding: 12px 24px; font-size: 16px;">Save All Changes</button>
        </form>

        <div class="settings-box" style="margin-top: 20px;">
            <h4>Data Backup</h4>
            <a href="/download_db" class="btn btn-success"><i class="fas fa-download"></i> Download Database Backup</a>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""

# --- LOGIN HTML ---
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; font-family: sans-serif; }
        .login-box { background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); width: 350px; text-align: center; }
        h2 { color: #2d3436; margin-bottom: 30px; }
        input { width: 100%; padding: 12px; margin-bottom: 15px; border: 1px solid #ddd; border-radius: 8px; box-sizing: border-box; }
        button { width: 100%; padding: 12px; background: #6C5CE7; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; }
        button:hover { background: #5649c0; }
    </style>
</head>
<body>
    <div class="login-box">
        <h2><i class="fas fa-lock"></i> Admin Panel</h2>
        <form method="POST">
            <input type="password" name="password" placeholder="Enter Admin Password" required>
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>
"""

# --- AUTH DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/dashboard')
    return render_template_string(LOGIN_HTML)

@app.route('/admin')
def admin_redir(): return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = c.fetchall()
    
    # Stats
    active = sum(1 for u in users if u[4] == 1)
    total_credits = sum(u[2] for u in users)
    
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='users', users=users, total_users=len(users), active_users=active, total_credits=total_credits)

@app.route('/logs')
@login_required
def view_logs():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
    logs = c.fetchall()
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='logs', logs=logs)

@app.route('/settings')
@login_required
def settings():
    api_key = get_setting('sora_api_key', '')
    costs = {
        'sora_2': get_setting('cost_sora_2', 25),
        'sora_2_pro': get_setting('cost_sora_2_pro', 35)
    }
    limits = {
        'mini': get_setting('limit_mini', 1),
        'basic': get_setting('limit_basic', 2),
        'standard': get_setting('limit_standard', 3)
    }
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', api_key=api_key, costs=costs, limits=limits)

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    set_setting('sora_api_key', request.form.get('sora_api_key'))
    set_setting('cost_sora_2', request.form.get('cost_sora_2'))
    set_setting('cost_sora_2_pro', request.form.get('cost_sora_2_pro'))
    set_setting('limit_mini', request.form.get('limit_mini'))
    set_setting('limit_basic', request.form.get('limit_basic'))
    set_setting('limit_standard', request.form.get('limit_standard'))
    return redirect('/settings')

@app.route('/download_db')
@login_required
def download_db():
    if os.path.exists(DB_PATH):
        return send_file(DB_PATH, as_attachment=True)
    return "Database not found."

@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    username = request.form['username']
    credits = int(request.form['credits'])
    expiry = request.form['expiry']
    plan = request.form['plan']
    api_key = "sk-" + str(uuid.uuid4())[:18]
    
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (username, api_key, credits, expiry_date, is_active, created_at, plan) VALUES (?, ?, ?, ?, 1, ?, ?)", 
                     (username, api_key, credits, expiry, datetime.now().strftime("%Y-%m-%d"), plan))
        conn.commit()
    except: pass
    conn.close()
    return redirect('/dashboard')

@app.route('/update_credits', methods=['POST'])
@login_required
def update_credits():
    username = request.form['username']
    amount = int(request.form['amount'])
    conn = get_db()
    conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", (amount, username))
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/update_plan', methods=['POST'])
@login_required
def update_plan():
    username = request.form['username']
    plan = request.form['plan']
    if plan:
        conn = get_db()
        conn.execute("UPDATE users SET plan = ? WHERE username = ?", (plan, username))
        conn.commit()
        conn.close()
    return redirect('/dashboard')

@app.route('/delete_user/<username>')
@login_required
def delete_user(username):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/toggle_status/<username>')
@login_required
def toggle_status(username):
    conn = get_db()
    conn.execute("UPDATE users SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return redirect('/dashboard')

# --- API ENDPOINTS (For Client) ---

@app.route('/api/verify', methods=['POST'])
def verify_user():
    data = request.json
    username = data.get('username')
    api_key = data.get('api_key')
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT credits, expiry_date, is_active, plan FROM users WHERE username=? AND api_key=?", (username, api_key))
    user = c.fetchone()
    conn.close()
    
    if not user: return jsonify({"valid": False, "message": "Invalid Credentials"})
    credits, expiry, active, plan = user
    if not active: return jsonify({"valid": False, "message": "Account Banned"})
    if datetime.now() > datetime.strptime(expiry, "%Y-%m-%d"): return jsonify({"valid": False, "message": "Expired"})
    
    # Get dynamic limits based on plan
    limit_key = f"limit_{plan.lower()}"
    concurrency_limit = int(get_setting(limit_key, 3))
    
    # Get costs
    cost_sora_2 = int(get_setting('cost_sora_2', 25))
    cost_sora_2_pro = int(get_setting('cost_sora_2_pro', 35))

    return jsonify({
        "valid": True, 
        "credits": credits, 
        "expiry": expiry,
        "plan": plan,
        "concurrency_limit": concurrency_limit,
        "costs": {"sora_2": cost_sora_2, "sora_2_pro": cost_sora_2_pro}
    })

@app.route('/api/proxy/generate', methods=['POST'])
def proxy_generate():
    auth = request.headers.get("Client-Auth", "")
    if ":" not in auth: return jsonify({"code": -1, "message": "Auth missing"}), 401
    
    user, key = auth.split(":")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT credits, is_active FROM users WHERE username=? AND api_key=?", (user, key))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"code": -1, "message": "Invalid User"}), 401
    
    credits, active = row
    if not active: 
        conn.close()
        return jsonify({"code": -1, "message": "Banned"}), 403
        
    # Calculate Cost Dynamically
    model = request.json.get('model', '')
    if "pro" in model:
        cost = int(get_setting('cost_sora_2_pro', 35))
    else:
        cost = int(get_setting('cost_sora_2', 25))

    if credits < cost:
        conn.close()
        return jsonify({"code": -1, "message": f"Insufficient Credits. Cost: {cost}"}), 402

    # Call Real API
    real_key = get_setting('sora_api_key')
    try:
        resp = requests.post("https://FreeSoraGenerator.com/api/v1/video/sora-video", 
                             json=request.json, 
                             headers={"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"},
                             timeout=120)
        
        data = resp.json()
        if data.get("code") == 0:
            c.execute("UPDATE users SET credits = credits - ? WHERE username=?", (cost, user))
            c.execute("INSERT INTO logs (username, action, cost, timestamp) VALUES (?, ?, ?, ?)", (user, "generate", cost, str(datetime.now())))
            conn.commit()
            data['user_balance'] = credits - cost
            
        conn.close()
        return jsonify(data), resp.status_code
    except Exception as e:
        conn.close()
        return jsonify({"code": -1, "message": str(e)}), 500

@app.route('/api/proxy/check-result', methods=['POST'])
def proxy_check():
    real_key = get_setting('sora_api_key')
    try:
        resp = requests.post("https://FreeSoraGenerator.com/api/video-generations/check-result", 
                             json=request.json,
                             headers={"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"},
                             timeout=30)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"code": -1, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
