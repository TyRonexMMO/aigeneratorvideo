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
# Check if persistent disk path is set, otherwise use local
DB_PATH = os.environ.get("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

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
                  created_at TEXT)''')
    # Logs Table
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  action TEXT,
                  cost INTEGER,
                  timestamp TEXT)''')
    # Settings Table (Stores Real API Key)
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    # Insert default API Key if not exists
    default_key = os.environ.get("SORA_API_KEY", "sk-DEFAULT_KEY")
    try:
        c.execute("INSERT INTO settings (key, value) VALUES ('sora_api_key', ?)", (default_key,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
        
    conn.commit()
    conn.close()

init_db()

# --- HELPER FUNCTIONS ---
def get_real_api_key():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='sora_api_key'")
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""

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
        
        /* Sidebar */
        .sidebar { width: 250px; background-color: var(--white); box-shadow: 2px 0 10px rgba(0,0,0,0.05); display: flex; flex-direction: column; padding: 20px; }
        .logo { font-size: 24px; font-weight: bold; color: var(--primary); margin-bottom: 40px; display: flex; align-items: center; gap: 10px; }
        .nav-link { display: flex; align-items: center; gap: 12px; padding: 12px 15px; color: var(--dark); text-decoration: none; border-radius: 10px; margin-bottom: 5px; transition: 0.3s; }
        .nav-link:hover, .nav-link.active { background-color: var(--primary); color: var(--white); }
        .nav-link i { width: 20px; }
        .spacer { flex-grow: 1; }
        
        /* Main Content */
        .main { flex-grow: 1; padding: 30px; overflow-y: auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .title { font-size: 28px; font-weight: bold; color: var(--dark); }
        
        /* Cards */
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card { background: var(--white); padding: 25px; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 20px; }
        .card-icon { width: 50px; height: 50px; border-radius: 12px; background: rgba(108, 92, 231, 0.1); color: var(--primary); display: flex; align-items: center; justify-content: center; font-size: 20px; }
        .card-info h3 { margin: 0; font-size: 14px; color: #888; }
        .card-info p { margin: 5px 0 0; font-size: 24px; font-weight: bold; color: var(--dark); }
        
        /* Tables */
        .table-container { background: var(--white); padding: 20px; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 15px; color: #888; font-weight: 600; border-bottom: 1px solid #eee; }
        td { padding: 15px; border-bottom: 1px solid #f5f5f5; color: var(--dark); vertical-align: middle; }
        tr:last-child td { border-bottom: none; }
        
        /* Badges & Buttons */
        .badge { padding: 5px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
        .badge-active { background: #e6fffa; color: #00b894; }
        .badge-banned { background: #fff5f5; color: #d63031; }
        
        .btn { border: none; padding: 8px 12px; border-radius: 8px; cursor: pointer; transition: 0.2s; text-decoration: none; font-size: 13px; display: inline-flex; align-items: center; gap: 5px; }
        .btn-primary { background: var(--primary); color: white; }
        .btn-danger { background: #ffecec; color: #d63031; }
        .btn-success { background: #00b894; color: white; }
        .btn-icon { background: transparent; color: #b2bec3; font-size: 16px; }
        .btn-icon:hover { color: var(--dark); }
        
        /* Forms */
        .input-group { margin-bottom: 15px; }
        .input-field { width: 100%; padding: 12px; border: 1px solid #eee; border-radius: 8px; background: #fafafa; outline: none; }
        .input-field:focus { border-color: var(--primary); background: white; }
        
        /* Settings Section */
        .settings-box { background: var(--white); padding: 30px; border-radius: 15px; max-width: 600px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <!-- Sidebar -->
    <div class="sidebar">
        <div class="logo"><i class="fas fa-robot"></i> SoraAdmin</div>
        <a href="/dashboard" class="nav-link {{ 'active' if page == 'users' else '' }}"><i class="fas fa-users"></i> Users</a>
        <a href="/logs" class="nav-link {{ 'active' if page == 'logs' else '' }}"><i class="fas fa-history"></i> Logs</a>
        <a href="/settings" class="nav-link {{ 'active' if page == 'settings' else '' }}"><i class="fas fa-cog"></i> Settings</a>
        <div class="spacer"></div>
        <a href="/logout" class="nav-link" style="color: #d63031;"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>

    <!-- Main Content -->
    <div class="main">
        {% if page == 'users' %}
        <div class="header">
            <div class="title">User Management</div>
        </div>
        
        <!-- Stats -->
        <div class="grid">
            <div class="card">
                <div class="card-icon"><i class="fas fa-user-friends"></i></div>
                <div class="card-info"><h3>Total Users</h3><p>{{ total_users }}</p></div>
            </div>
            <div class="card">
                <div class="card-icon" style="color:#00b894; background:rgba(0,184,148,0.1);"><i class="fas fa-check-circle"></i></div>
                <div class="card-info"><h3>Active</h3><p>{{ active_users }}</p></div>
            </div>
            <div class="card">
                <div class="card-icon" style="color:#0984e3; background:rgba(9,132,227,0.1);"><i class="fas fa-coins"></i></div>
                <div class="card-info"><h3>Total Credits</h3><p>{{ total_credits }}</p></div>
            </div>
        </div>

        <!-- Add User Form -->
        <div class="table-container" style="margin-bottom: 30px;">
            <h3 style="margin-top:0;">Add New User</h3>
            <form action="/add_user" method="POST" style="display: flex; gap: 15px;">
                <input type="text" name="username" class="input-field" placeholder="Username" required>
                <input type="number" name="credits" class="input-field" placeholder="Credits" required>
                <input type="date" name="expiry" class="input-field" required>
                <button type="submit" class="btn btn-primary"><i class="fas fa-plus"></i> Create</button>
            </form>
        </div>

        <!-- User Table -->
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>User</th>
                        <th>License Key</th>
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
                        <td>{{ user[2] }}</td>
                        <td>{{ user[3] }}</td>
                        <td>
                            {% if user[4] %}
                            <span class="badge badge-active">Active</span>
                            {% else %}
                            <span class="badge badge-banned">Banned</span>
                            {% endif %}
                        </td>
                        <td>
                            <form action="/update_credits" method="POST" style="display:inline-flex; gap:5px;">
                                <input type="hidden" name="username" value="{{ user[0] }}">
                                <input type="number" name="amount" placeholder="+/-" style="width:60px; padding:5px; border:1px solid #ddd; border-radius:4px;">
                                <button class="btn btn-primary" style="padding:5px 10px;"><i class="fas fa-save"></i></button>
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
        <div class="header"><div class="title">System Settings</div></div>
        
        <div class="settings-box">
            <h3>API Configuration</h3>
            <form action="/update_settings" method="POST">
                <div class="input-group">
                    <label style="display:block; margin-bottom:10px; font-weight:600;">Real Sora API Key</label>
                    <input type="text" name="sora_api_key" class="input-field" value="{{ current_key }}">
                    <p style="color:#888; font-size:12px; margin-top:5px;">This key is used by the backend to communicate with the provider.</p>
                </div>
                <button type="submit" class="btn btn-primary">Save Changes</button>
            </form>
        </div>

        <div class="settings-box">
            <h3>Data Management</h3>
            <p>Download a backup of your user database to prevent data loss during updates.</p>
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
    key = get_real_api_key()
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', current_key=key)

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    new_key = request.form.get('sora_api_key')
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('sora_api_key', ?)", (new_key,))
    conn.commit()
    conn.close()
    return redirect('/settings')

# --- NEW: Download Database Route ---
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
    api_key = "sk-" + str(uuid.uuid4())[:18]
    
    conn = get_db()
    try:
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, 1, ?)", 
                     (username, api_key, credits, expiry, datetime.now().strftime("%Y-%m-%d")))
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
    c.execute("SELECT credits, expiry_date, is_active FROM users WHERE username=? AND api_key=?", (username, api_key))
    user = c.fetchone()
    conn.close()
    
    if not user: return jsonify({"valid": False, "message": "Invalid Credentials"})
    credits, expiry, active = user
    if not active: return jsonify({"valid": False, "message": "Account Banned"})
    if datetime.now() > datetime.strptime(expiry, "%Y-%m-%d"): return jsonify({"valid": False, "message": "Expired"})
        
    return jsonify({"valid": True, "credits": credits, "expiry": expiry})

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
        
    cost = 30 if "pro" in request.json.get('model', '') else 20
    if credits < cost:
        conn.close()
        return jsonify({"code": -1, "message": "Insufficient Credits"}), 402

    # Call Real API
    real_key = get_real_api_key()
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
    real_key = get_real_api_key()
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
