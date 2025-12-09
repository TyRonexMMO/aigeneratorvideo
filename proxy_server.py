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
ADMIN_LOGIN_PATH = os.environ.get("ADMIN_PATH", "secure_login")

DEFAULT_COSTS = {'sora_2': 25, 'sora_2_pro': 35}
DEFAULT_LIMITS = {'mini': 1, 'basic': 2, 'standard': 3}

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
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (task_id TEXT PRIMARY KEY, username TEXT, cost INTEGER, status TEXT, created_at TEXT)''')
    
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

# --- MODERN KHMER DASHBOARD HTML ---
MODERN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="km">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sora Admin Dashboard</title>
    <!-- Import Kantumruy Pro Font -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@300;400;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    
    <style>
        :root {
            --primary: #4F46E5;
            --primary-dark: #4338ca;
            --secondary: #64748b;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --light: #f8fafc;
            --white: #ffffff;
            --dark: #1e293b;
            --border: #e2e8f0;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        }
        
        * { box-sizing: border-box; }
        
        body { 
            font-family: 'Kantumruy Pro', sans-serif; 
            background-color: #f1f5f9; 
            margin: 0; 
            display: flex; 
            height: 100vh; 
            color: var(--dark);
        }
        
        /* Sidebar */
        .sidebar { 
            width: 260px; 
            background-color: var(--white); 
            border-right: 1px solid var(--border); 
            display: flex; 
            flex-direction: column; 
            padding: 20px; 
            transition: all 0.3s ease;
        }
        
        .logo { 
            font-size: 24px; 
            font-weight: 700; 
            color: var(--primary); 
            margin-bottom: 40px; 
            display: flex; 
            align-items: center; 
            gap: 12px; 
        }
        
        .nav-link { 
            display: flex; 
            align-items: center; 
            gap: 12px; 
            padding: 14px 16px; 
            color: var(--secondary); 
            text-decoration: none; 
            border-radius: 12px; 
            margin-bottom: 8px; 
            font-weight: 600;
            transition: all 0.2s; 
        }
        
        .nav-link:hover, .nav-link.active { 
            background-color: #e0e7ff; 
            color: var(--primary); 
        }
        
        .nav-link i { width: 24px; font-size: 18px; }
        .spacer { flex-grow: 1; }
        
        /* Main Content */
        .main { flex-grow: 1; padding: 30px; overflow-y: auto; }
        
        .header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 30px; 
        }
        
        .title { font-size: 28px; font-weight: 700; color: var(--dark); }
        
        /* Stats Grid */
        .grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
            gap: 20px; 
            margin-bottom: 30px; 
        }
        
        .card { 
            background: var(--white); 
            padding: 25px; 
            border-radius: 16px; 
            box-shadow: var(--shadow); 
            border: 1px solid var(--border);
            display: flex; 
            align-items: center; 
            gap: 20px; 
        }
        
        .card-icon { 
            width: 54px; 
            height: 54px; 
            border-radius: 14px; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            font-size: 22px; 
        }
        
        .card-info h3 { margin: 0; font-size: 14px; color: var(--secondary); font-weight: 500; }
        .card-info p { margin: 5px 0 0; font-size: 26px; font-weight: 700; color: var(--dark); }
        
        /* Forms & Containers */
        .content-box { 
            background: var(--white); 
            padding: 25px; 
            border-radius: 16px; 
            box-shadow: var(--shadow); 
            border: 1px solid var(--border);
            margin-bottom: 30px;
        }
        
        .section-title { 
            margin-top: 0; 
            margin-bottom: 20px; 
            font-size: 18px; 
            font-weight: 700; 
            color: var(--dark); 
            border-bottom: 2px solid #f1f5f9; 
            padding-bottom: 10px; 
        }
        
        /* Inputs & Buttons */
        .input-row { display: flex; gap: 15px; align-items: flex-end; flex-wrap: wrap; }
        
        .form-group { flex: 1; min-width: 150px; }
        .form-group label { display: block; margin-bottom: 8px; font-size: 13px; font-weight: 600; color: var(--secondary); }
        
        .input-field { 
            width: 100%; 
            padding: 12px 15px; 
            border: 1px solid var(--border); 
            border-radius: 10px; 
            background: #f8fafc; 
            outline: none; 
            font-family: 'Kantumruy Pro', sans-serif;
            transition: 0.2s;
        }
        .input-field:focus { border-color: var(--primary); background: var(--white); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1); }
        
        .btn { 
            border: none; 
            padding: 12px 20px; 
            border-radius: 10px; 
            cursor: pointer; 
            transition: 0.2s; 
            text-decoration: none; 
            font-family: 'Kantumruy Pro', sans-serif;
            font-weight: 600; 
            font-size: 14px; 
            display: inline-flex; 
            align-items: center; 
            gap: 8px; 
            height: 45px;
            white-space: nowrap;
        }
        
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: var(--primary-dark); }
        .btn-danger { background: var(--danger); color: white; }
        .btn-success { background: var(--success); color: white; }
        
        /* Table */
        table { width: 100%; border-collapse: separate; border-spacing: 0; }
        th { text-align: left; padding: 16px; color: var(--secondary); font-weight: 600; font-size: 13px; border-bottom: 2px solid #f1f5f9; background: #fcfcfc; }
        td { padding: 16px; border-bottom: 1px solid #f1f5f9; color: var(--dark); vertical-align: middle; font-size: 14px; }
        tr:hover td { background-color: #f8fafc; }
        
        /* Custom Elements */
        .badge { padding: 6px 12px; border-radius: 30px; font-size: 12px; font-weight: 700; text-transform: uppercase; }
        .badge-active { background: #dcfce7; color: #15803d; }
        .badge-banned { background: #fee2e2; color: #b91c1c; }
        
        .plan-badge { padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: 600; border: 1px solid; }
        .plan-mini { background: #f3e8ff; color: #7e22ce; border-color: #d8b4fe; }
        .plan-basic { background: #e0f2fe; color: #0369a1; border-color: #bae6fd; }
        .plan-standard { background: #ffedd5; color: #c2410c; border-color: #fed7aa; }
        
        .action-row { display: flex; gap: 8px; }
        .icon-btn { 
            width: 32px; height: 32px; 
            border-radius: 8px; 
            display: flex; align-items: center; justify-content: center; 
            border: 1px solid var(--border); 
            background: white; color: var(--secondary); 
            cursor: pointer; transition: 0.2s; text-decoration: none;
        }
        .icon-btn:hover { background: #f1f5f9; color: var(--primary); }
        .icon-btn.delete:hover { background: #fee2e2; color: var(--danger); border-color: #fecaca; }

        /* Small inputs in table */
        .table-input { padding: 6px; border: 1px solid var(--border); border-radius: 6px; width: 70px; font-size: 13px; }
        .table-select { padding: 6px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; font-family: 'Kantumruy Pro'; }
        
    </style>
</head>
<body>
    <!-- Sidebar Menu -->
    <div class="sidebar">
        <div class="logo"><i class="fas fa-video"></i> SoraAdmin</div>
        <a href="/dashboard" class="nav-link {{ 'active' if page == 'users' else '' }}"><i class="fas fa-users-cog"></i> អ្នកប្រើប្រាស់</a>
        <a href="/vouchers" class="nav-link {{ 'active' if page == 'vouchers' else '' }}"><i class="fas fa-ticket-alt"></i> ប័ណ្ណបញ្ចូលលុយ</a>
        <a href="/logs" class="nav-link {{ 'active' if page == 'logs' else '' }}"><i class="fas fa-clipboard-list"></i> ប្រវត្តិសកម្មភាព</a>
        <a href="/settings" class="nav-link {{ 'active' if page == 'settings' else '' }}"><i class="fas fa-sliders-h"></i> ការកំណត់</a>
        <div class="spacer"></div>
        <a href="/logout" class="nav-link" style="color: var(--danger); background: #fef2f2;"><i class="fas fa-sign-out-alt"></i> ចាកចេញ</a>
    </div>

    <!-- Main Content Area -->
    <div class="main">
        {% if page == 'users' %}
        <div class="header"><div class="title">គ្រប់គ្រងអ្នកប្រើប្រាស់ (User Management)</div></div>
        
        <!-- Stats Cards -->
        <div class="grid">
            <div class="card">
                <div class="card-icon" style="background:#e0e7ff; color:#4f46e5;"><i class="fas fa-users"></i></div>
                <div class="card-info"><h3>ចំនួនអ្នកប្រើសរុប</h3><p>{{ total_users }}</p></div>
            </div>
            <div class="card">
                <div class="card-icon" style="background:#dcfce7; color:#10b981;"><i class="fas fa-user-check"></i></div>
                <div class="card-info"><h3>កំពុងសកម្ម</h3><p>{{ active_users }}</p></div>
            </div>
            <div class="card">
                <div class="card-icon" style="background:#fff7ed; color:#f97316;"><i class="fas fa-coins"></i></div>
                <div class="card-info"><h3>ក្រេឌីតសរុបក្នុងប្រព័ន្ធ</h3><p>{{ total_credits }}</p></div>
            </div>
        </div>

        <!-- Add User Form -->
        <div class="content-box">
            <h4 class="section-title"><i class="fas fa-user-plus"></i> បង្កើតគណនីថ្មី</h4>
            <form action="/add_user" method="POST" class="input-row">
                <div class="form-group">
                    <label>ឈ្មោះគណនី (Username)</label>
                    <input type="text" name="username" class="input-field" placeholder="Ex: User01" required>
                </div>
                <div class="form-group">
                    <label>ចំនួនក្រេឌីត</label>
                    <input type="number" name="credits" class="input-field" placeholder="Ex: 500" required>
                </div>
                <div class="form-group">
                    <label>ជ្រើសរើសកញ្ចប់ (Plan)</label>
                    <select name="plan" class="input-field">
                        <option value="Mini">Mini Plan (1 Process)</option>
                        <option value="Basic">Basic Plan (2 Processes)</option>
                        <option value="Standard" selected>Standard Plan (3 Processes)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>ថ្ងៃផុតកំណត់</label>
                    <input type="date" name="expiry" class="input-field" required>
                </div>
                <button type="submit" class="btn btn-primary" style="margin-bottom: 2px;"><i class="fas fa-check"></i> បង្កើតគណនី</button>
            </form>
        </div>

        <!-- Users Table -->
        <div class="content-box" style="padding:0; overflow:hidden;">
            <table style="width:100%;">
                <thead>
                    <tr>
                        <th>ឈ្មោះគណនី</th>
                        <th>License Key</th>
                        <th>កញ្ចប់</th>
                        <th>ក្រេឌីត</th>
                        <th>ថ្ងៃផុតកំណត់</th>
                        <th>ស្ថានភាព</th>
                        <th>កែប្រែ / លុប</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td style="font-weight:700;">{{ user[0] }}</td>
                        <td style="font-family:monospace; color:#64748b; font-size:12px;">{{ user[1] }}</td>
                        <td>
                            <span class="plan-badge plan-{{ user[6].lower() }}">{{ user[6] }}</span>
                        </td>
                        <td>
                            <form action="/update_credits" method="POST" style="display:flex; align-items:center; gap:5px;">
                                <input type="hidden" name="username" value="{{ user[0] }}">
                                <span style="font-weight:bold; color:var(--primary); width:40px;">{{ user[2] }}</span>
                                <input type="number" name="amount" class="table-input" placeholder="+/-">
                                <button class="icon-btn" style="background:var(--primary); color:white; border:none;"><i class="fas fa-check"></i></button>
                            </form>
                        </td>
                        <td>{{ user[3] }}</td>
                        <td>
                            {% if user[4] %}
                                <span class="badge badge-active">Active</span>
                            {% else %}
                                <span class="badge badge-banned">Banned</span>
                            {% endif %}
                        </td>
                        <td>
                            <div class="action-row">
                                <form action="/update_plan" method="POST" style="display:flex;">
                                    <input type="hidden" name="username" value="{{ user[0] }}">
                                    <select name="plan" class="table-select" onchange="this.form.submit()">
                                        <option value="" disabled selected>Plan</option>
                                        <option value="Mini">Mini</option>
                                        <option value="Basic">Basic</option>
                                        <option value="Standard">Standard</option>
                                    </select>
                                </form>
                                <a href="/toggle_status/{{ user[0] }}" class="icon-btn" title="បិទ/បើក"><i class="fas fa-power-off"></i></a>
                                <a href="/delete_user/{{ user[0] }}" class="icon-btn delete" onclick="return confirm('តើអ្នកពិតជាចង់លុបមែនទេ?')" title="លុប"><i class="fas fa-trash-alt"></i></a>
                            </div>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif page == 'vouchers' %}
        <div class="header"><div class="title">ប្រព័ន្ធប័ណ្ណបញ្ចូលលុយ (Voucher System)</div></div>
        
        <div class="content-box">
            <h4 class="section-title"><i class="fas fa-magic"></i> បង្កើតកូដថ្មី</h4>
            <form action="/generate_vouchers" method="POST" class="input-row">
                <div class="form-group">
                    <label>ចំនួនក្រេឌីតក្នុងមួយសន្លឹក</label>
                    <input type="number" name="amount" class="input-field" placeholder="Ex: 100" required>
                </div>
                <div class="form-group">
                    <label>ចំនួនសន្លឹកដែលចង់បង្កើត</label>
                    <input type="number" name="count" class="input-field" placeholder="Ex: 10" value="1" required>
                </div>
                <button type="submit" class="btn btn-success" style="margin-bottom: 2px;"><i class="fas fa-cogs"></i> បង្កើតឥឡូវនេះ</button>
            </form>
        </div>

        <div class="content-box" style="padding:0; overflow:hidden;">
            <table>
                <thead><tr><th>លេខកូដ (Code)</th><th>ចំនួនក្រេឌីត</th><th>ស្ថានភាព</th><th>អ្នកប្រើ</th><th>កាលបរិច្ឆេទ</th></tr></thead>
                <tbody>
                    {% for v in vouchers %}
                    <tr>
                        <td style="font-family:monospace; font-weight:bold; color:var(--primary);">{{ v[0] }}</td>
                        <td style="font-weight:bold; color:var(--success);">+{{ v[1] }}</td>
                        <td>{% if v[2] %}<span class="badge badge-banned">បានប្រើរួច</span>{% else %}<span class="badge badge-active">នៅទំនេរ</span>{% endif %}</td>
                        <td>{{ v[4] if v[4] else '-' }}</td>
                        <td style="color:#64748b; font-size:12px;">{{ v[3] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif page == 'logs' %}
        <div class="header"><div class="title">កំណត់ត្រាប្រព័ន្ធ (System Logs)</div></div>
        <div class="content-box" style="padding:0; overflow:hidden;">
            <table>
                <thead><tr><th>ពេលវេលា</th><th>ឈ្មោះគណនី</th><th>សកម្មភាព</th><th>ការចំណាយ</th></tr></thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                        <td style="color:#64748b;">{{ log[4] }}</td>
                        <td style="font-weight:bold;">{{ log[1] }}</td>
                        <td>{{ log[2] }}</td>
                        <td style="font-weight:bold; color:var(--danger);">-{{ log[3] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif page == 'settings' %}
        <div class="header"><div class="title">ការកំណត់ប្រព័ន្ធ (Settings)</div></div>
        
        <div class="content-box">
            <h4 class="section-title"><i class="fas fa-bullhorn"></i> ផ្សព្វផ្សាយដំណឹង (Broadcast)</h4>
            <form action="/update_broadcast" method="POST" style="display:flex; gap:10px;">
                <input type="text" name="message" class="input-field" placeholder="សរសេរសារជូនដំណឹងនៅទីនេះ..." value="{{ broadcast_msg }}">
                <button type="submit" class="btn btn-primary">ផ្ញើ</button>
                <a href="/clear_broadcast" class="btn btn-danger">លុប</a>
            </form>
        </div>

        <form action="/update_settings" method="POST">
            <div class="grid">
                <!-- Cost Settings -->
                <div class="content-box">
                    <h4 class="section-title"><i class="fas fa-tag"></i> តម្លៃក្រេឌីត (Video Cost)</h4>
                    <div class="form-group">
                        <label>Sora-2 Cost (10s)</label>
                        <input type="number" name="cost_sora_2" class="input-field" value="{{ costs.sora_2 }}">
                    </div>
                    <div class="form-group" style="margin-top:15px;">
                        <label>Sora-2 Pro Cost (15s)</label>
                        <input type="number" name="cost_sora_2_pro" class="input-field" value="{{ costs.sora_2_pro }}">
                    </div>
                </div>

                <!-- Limit Settings -->
                <div class="content-box">
                    <h4 class="section-title"><i class="fas fa-tachometer-alt"></i> កំណត់ដំណើរការ (Limits)</h4>
                    <div class="form-group"><label>Mini Plan Limit</label><input type="number" name="limit_mini" class="input-field" value="{{ limits.mini }}"></div>
                    <div class="form-group" style="margin-top:10px;"><label>Basic Plan Limit</label><input type="number" name="limit_basic" class="input-field" value="{{ limits.basic }}"></div>
                    <div class="form-group" style="margin-top:10px;"><label>Standard Plan Limit</label><input type="number" name="limit_standard" class="input-field" value="{{ limits.standard }}"></div>
                </div>
            </div>

            <div class="content-box">
                <h4 class="section-title"><i class="fas fa-key"></i> API Configuration</h4>
                <div class="form-group">
                    <label>Real Sora API Key</label>
                    <input type="text" name="sora_api_key" class="input-field" value="{{ api_key }}">
                </div>
                <div style="margin-top:20px; display:flex; justify-content:space-between;">
                    <button type="submit" class="btn btn-success"><i class="fas fa-save"></i> រក្សាទុកការកំណត់</button>
                    <a href="/download_db" class="btn btn-primary"><i class="fas fa-database"></i> ទាញយកទិន្នន័យ (Backup)</a>
                </div>
            </div>
        </form>
        {% endif %}
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Admin Login</title><link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@400;600&display=swap" rel="stylesheet"></head>
<body style="background:#f1f5f9;height:100vh;display:flex;justify-content:center;align-items:center;font-family:'Kantumruy Pro', sans-serif;">
<form method="POST" style="background:white;padding:40px;border-radius:16px;box-shadow:0 10px 25px rgba(0,0,0,0.1);text-align:center;width:350px;">
    <h2 style="color:#1e293b; margin-top:0;">Sora Admin</h2>
    <input type="password" name="password" placeholder="បញ្ចូលលេខកូដសម្ងាត់" style="width:100%;padding:12px;margin-bottom:20px;border:1px solid #e2e8f0;border-radius:10px;box-sizing:border-box;outline:none;">
    <button style="width:100%;padding:12px;background:#4F46E5;color:white;border:none;border-radius:10px;cursor:pointer;font-weight:bold;">ចូលប្រព័ន្ធ</button>
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
    return jsonify({"status": "Server Running", "version": "2.0"}), 200

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
    limits = {
        'mini': get_setting('limit_mini', 1),
        'basic': get_setting('limit_basic', 2),
        'standard': get_setting('limit_standard', 3)
    }
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', api_key=k, broadcast_msg=msg, costs=costs, limits=limits)

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

# --- CLIENT API ROUTES ---
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
        
        # Auto Refund Logic
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
