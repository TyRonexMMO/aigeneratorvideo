from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session
import requests
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = "super_secret_admin_key" # Change this in production

# --- CONFIGURATION ---
# API Key របស់ Sora ពិតប្រាកដ (Admin ដាក់នៅទីនេះតែមួយគត់)
REAL_SORA_API_KEY = os.environ.get("SORA_API_KEY", "sk-Tqf7FzTrlEZxfD8EUd5tD9cqSn2D5IAS")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123") # Password សម្រាប់ចូល Dashboard

DB_FILE = "users.db"

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, 
                  api_key TEXT, 
                  credits INTEGER, 
                  expiry_date TEXT, 
                  is_active INTEGER,
                  created_at TEXT)''')
    # Create logs table
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  action TEXT,
                  cost INTEGER,
                  timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- ADMIN DASHBOARD HTML ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Sora Admin Dashboard</title>
    <style>
        body { font-family: sans-serif; background: #f0f2f5; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #1a73e8; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 12px; border-bottom: 1px solid #ddd; text-align: left; }
        th { background: #f8f9fa; }
        .btn { padding: 8px 15px; border: none; border-radius: 4px; cursor: pointer; color: white; text-decoration: none; font-size: 14px;}
        .btn-add { background: #28a745; }
        .btn-edit { background: #ffc107; color: black; }
        .btn-del { background: #dc3545; }
        .form-group { margin-bottom: 15px; }
        input { padding: 8px; border: 1px solid #ddd; border-radius: 4px; width: 200px; }
        .stat-card { display: inline-block; background: #e8f0fe; padding: 15px; border-radius: 8px; margin-right: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <h1>Sora User Management</h1>
            <a href="/logout" class="btn btn-del">Logout</a>
        </div>
        
        <div style="margin-bottom: 20px;">
            <div class="stat-card">Total Users: {{ total_users }}</div>
            <div class="stat-card">Total Usage (Logs): {{ total_logs }}</div>
        </div>

        <h3>Create New User</h3>
        <form action="/add_user" method="POST" style="background: #eee; padding: 15px; border-radius: 8px;">
            <input type="text" name="username" placeholder="Username" required>
            <input type="number" name="credits" placeholder="Credits (e.g. 500)" required>
            <input type="date" name="expiry" required>
            <button type="submit" class="btn btn-add">Create User</button>
        </form>

        <h3>User List</h3>
        <table>
            <thead>
                <tr>
                    <th>Username</th>
                    <th>API Key (License)</th>
                    <th>Credits</th>
                    <th>Expiry</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr>
                    <td>{{ user[0] }}</td>
                    <td>{{ user[1] }}</td>
                    <td style="font-weight:bold; color: {% if user[2] < 50 %}red{% else %}green{% endif %};">{{ user[2] }}</td>
                    <td>{{ user[3] }}</td>
                    <td>{% if user[4] %}Active{% else %}Banned{% endif %}</td>
                    <td>
                        <form action="/update_credits" method="POST" style="display:inline;">
                            <input type="hidden" name="username" value="{{ user[0] }}">
                            <input type="number" name="amount" placeholder="+/-" style="width:60px;">
                            <button class="btn btn-edit">Add</button>
                        </form>
                        <a href="/toggle_status/{{ user[0] }}" class="btn" style="background:grey;">Toggle</a>
                        <a href="/delete_user/{{ user[0] }}" class="btn btn-del" onclick="return confirm('Delete?')">X</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<form method="POST" style="text-align:center; margin-top:100px;">
    <h2>Admin Login</h2>
    <input type="password" name="password" placeholder="Admin Password">
    <button type="submit">Login</button>
</form>
"""

# --- HELPERS ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_db():
    conn = sqlite3.connect(DB_FILE)
    return conn

# --- ROUTES (ADMIN) ---

# 1. Main Login Route (Home)
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/dashboard')
        else:
            return "Wrong Password"
    return render_template_string(LOGIN_HTML)

# 2. Redirect /admin to / (NEW FIX)
@app.route('/admin')
def admin_redirect():
    return redirect(url_for('login'))

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
    c.execute("SELECT COUNT(*) FROM logs")
    total_logs = c.fetchone()[0]
    conn.close()
    return render_template_string(DASHBOARD_HTML, users=users, total_users=len(users), total_logs=total_logs)

@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    username = request.form['username']
    credits = int(request.form['credits'])
    expiry = request.form['expiry']
    # Generate a random License Key
    api_key = "sk-" + str(uuid.uuid4())[:18]
    
    conn = get_db()
    try:
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, 1, ?)", 
                     (username, api_key, credits, expiry, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
    except:
        pass # Username exists
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
    # Flip between 0 and 1
    conn.execute("UPDATE users SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return redirect('/dashboard')

# --- ROUTES (CLIENT API) ---

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
    
    if not user:
        return jsonify({"valid": False, "message": "Invalid Credentials"})
    
    credits, expiry, active = user
    if not active:
        return jsonify({"valid": False, "message": "Account Deactivated"})
    
    # Check Expiry
    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    if datetime.now() > exp_date:
        return jsonify({"valid": False, "message": "Account Expired"})
        
    return jsonify({
        "valid": True, 
        "credits": credits, 
        "expiry": expiry,
        "message": "Login Successful"
    })

@app.route('/api/proxy/generate', methods=['POST'])
def proxy_generate():
    # 1. Validate Client
    client_auth = request.headers.get("Client-Auth") # Format: "username:apikey"
    if not client_auth or ":" not in client_auth:
        return jsonify({"code": -1, "message": "Unauthorized"}), 401
    
    username, api_key = client_auth.split(":")
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT credits, expiry_date, is_active FROM users WHERE username=? AND api_key=?", (username, api_key))
    user = c.fetchone()
    
    if not user:
        conn.close()
        return jsonify({"code": -1, "message": "Invalid User"}), 401
        
    credits, expiry, active = user
    
    # 2. Check Constraints
    model = request.json.get('model', 'sora-2')
    cost = 30 if 'pro' in model else 20
    
    if credits < cost:
        conn.close()
        return jsonify({"code": -1, "message": f"មិនមាន Credit គ្រប់គ្រាន់ទេ។ ត្រូវការ {cost} តែមាន {credits}។"}), 402
        
    if not active:
        conn.close()
        return jsonify({"code": -1, "message": "Account banned"}), 403

    # 3. Call Real Sora API
    real_url = "https://FreeSoraGenerator.com/api/v1/video/sora-video"
    headers = {
        "Authorization": f"Bearer {REAL_SORA_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(real_url, headers=headers, json=request.json, timeout=120)
        resp_data = response.json()
        
        if resp_data.get("code") == 0:
            # 4. Deduct Credits ONLY on success
            c.execute("UPDATE users SET credits = credits - ? WHERE username=?", (cost, username))
            c.execute("INSERT INTO logs (username, action, cost, timestamp) VALUES (?, ?, ?, ?)", 
                      (username, "generate", cost, str(datetime.now())))
            conn.commit()
            
            # Return new balance info in headers or body if needed
            resp_data['user_balance'] = credits - cost
            
        conn.close()
        return jsonify(resp_data), response.status_code
        
    except Exception as e:
        conn.close()
        return jsonify({"code": -1, "message": f"Server Error: {str(e)}"}), 500

@app.route('/api/proxy/check-result', methods=['POST'])
def proxy_check():
    # Simple pass-through, no cost
    url = "https://FreeSoraGenerator.com/api/video-generations/check-result"
    headers = {
        "Authorization": f"Bearer {REAL_SORA_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, headers=headers, json=request.json, timeout=30)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"code": -1, "message": str(e)}), 500

if __name__ == '__main__':
    # Run using: gunicorn admin_server:app
    app.run(host='0.0.0.0', port=5000, debug=True)

