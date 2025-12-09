from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file, abort
import requests
import os
import sqlite3
import uuid
import time
import random
import string
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "super_secret_admin_key_v2")

# --- CONFIGURATION ---
DB_PATH = os.environ.get("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
# ផ្លូវចូលសម្ងាត់ (ឧទាហរណ៍: /secure_login)
ADMIN_LOGIN_PATH = os.environ.get("ADMIN_PATH", "secure_login")

# Security Config
MAX_SUSPICIOUS_ATTEMPTS = 5
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
    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, api_key TEXT, credits INTEGER, expiry_date TEXT, is_active INTEGER, created_at TEXT, plan TEXT DEFAULT 'Standard')''')
    # Logs Table
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, cost INTEGER, timestamp TEXT)''')
    # Settings Table
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    # Vouchers Table
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers
                 (code TEXT PRIMARY KEY, amount INTEGER, is_used INTEGER, created_at TEXT, used_by TEXT)''')
    # Tasks Table
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (task_id TEXT PRIMARY KEY, username TEXT, cost INTEGER, status TEXT, created_at TEXT)''')
    # Banned IPs Table
    c.execute('''CREATE TABLE IF NOT EXISTS banned_ips
                 (ip TEXT PRIMARY KEY, reason TEXT, banned_at TEXT)''')

    # Default Settings
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
    chars = string.ascii_uppercase + string.digits
    return f"SORA-{amount}-{''.join(random.choices(chars, k=6))}"

def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

# --- SECURITY MIDDLEWARE (IRON DOME) ---
@app.before_request
def security_guard():
    ip = get_client_ip()
    
    conn = get_db()
    is_banned = conn.execute("SELECT 1 FROM banned_ips WHERE ip=?", (ip,)).fetchone()
    conn.close()
    
    if is_banned:
        return jsonify({"code": 403, "message": "Access Denied: IP Banned."}), 403

    if 'logged_in' in session: return 

    valid_starts = ['/api/', '/static/']
    if request.path == f'/{ADMIN_LOGIN_PATH}' or any(request.path.startswith(p) for p in valid_starts) or request.path == '/':
        return 

    # Suspicious Activity Tracker
    current_count = suspicious_tracker.get(ip, 0) + 1
    suspicious_tracker[ip] = current_count
    
    if current_count >= MAX_SUSPICIOUS_ATTEMPTS:
        try:
            conn = get_db()
            conn.execute("INSERT OR IGNORE INTO banned_ips (ip, reason, banned_at) VALUES (?, ?, ?)", 
                         (ip, f"Excessive scanning: {request.path}", str(datetime.now())))
            conn.commit(); conn.close()
        except: pass
        return jsonify({"code": 403, "message": "Access Denied"}), 403

    return "Not Found", 404

# --- MODERN KHMER DASHBOARD HTML ---
MODERN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="km">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sora Admin Pro</title>
    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    
    <style>
        :root {
            --primary: #4F46E5;
            --primary-hover: #4338ca;
            --bg-color: #F3F4F6;
            --card-bg: #FFFFFF;
            --text-main: #1F2937;
            --text-light: #6B7280;
            --success: #10B981;
            --danger: #EF4444;
            --warning: #F59E0B;
            --sidebar-width: 280px;
        }

        body {
            font-family: 'Kantumruy Pro', sans-serif;
            background-color: var(--bg-color);
            margin: 0;
            display: flex;
            height: 100vh;
            color: var(--text-main);
        }

        /* Sidebar Styling */
        .sidebar {
            width: var(--sidebar-width);
            background: #111827;
            color: white;
            display: flex;
            flex-direction: column;
            padding: 20px;
            transition: all 0.3s;
        }
        
        .logo {
            font-size: 24px;
            font-weight: 700;
            color: #818CF8;
            margin-bottom: 40px;
            display: flex;
            align-items: center;
            gap: 10px;
            padding-left: 10px;
        }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 14px 20px;
            color: #9CA3AF;
            text-decoration: none;
            border-radius: 12px;
            margin-bottom: 5px;
            transition: all 0.2s;
            font-weight: 500;
        }

        .nav-item:hover, .nav-item.active {
            background: rgba(255, 255, 255, 0.1);
            color: white;
        }

        .nav-item i { width: 24px; text-align: center; }

        /* Main Content */
        .main-content {
            flex: 1;
            padding: 30px;
            overflow-y: auto;
        }

        .header-title {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 25px;
            color: #111827;
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .stat-card {
            background: var(--card-bg);
            padding: 25px;
            border-radius: 16px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            display: flex;
            align-items: center;
            gap: 20px;
            border: 1px solid #E5E7EB;
        }

        .stat-icon {
            width: 50px;
            height: 50px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
        }

        .stat-info h4 { margin: 0; color: var(--text-light); font-size: 14px; font-weight: 500; }
        .stat-info p { margin: 5px 0 0; font-size: 24px; font-weight: 700; color: var(--text-main); }

        /* Content Box */
        .card-box {
            background: var(--card-bg);
            border-radius: 16px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            border: 1px solid #E5E7EB;
            padding: 25px;
            margin-bottom: 30px;
        }

        .section-header {
            margin-top: 0;
            margin-bottom: 20px;
            font-size: 18px;
            font-weight: 600;
            padding-bottom: 15px;
            border-bottom: 1px solid #F3F4F6;
            color: var(--primary);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        /* Forms */
        .form-row { display: flex; gap: 15px; flex-wrap: wrap; align-items: flex-end; }
        .form-group { flex: 1; min-width: 200px; }
        .form-group label { display: block; margin-bottom: 8px; font-size: 13px; color: var(--text-light); font-weight: 600; }
        
        .input-control {
            width: 100%;
            padding: 12px;
            border: 1px solid #D1D5DB;
            border-radius: 8px;
            font-family: 'Kantumruy Pro', sans-serif;
            background: #F9FAFB;
            outline: none;
            transition: 0.2s;
        }
        .input-control:focus { border-color: var(--primary); background: white; box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1); }

        /* Buttons */
        .btn {
            padding: 12px 20px;
            border-radius: 8px;
            border: none;
            font-family: 'Kantumruy Pro', sans-serif;
            font-weight: 600;
            cursor: pointer;
            transition: 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            text-decoration: none;
        }
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-danger { background: var(--danger); color: white; }
        .btn-success { background: var(--success); color: white; }
        
        .icon-action {
            width: 35px; height: 35px;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
            background: white;
            color: var(--text-light);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: 0.2s;
            text-decoration: none;
        }
        .icon-action:hover { background: #F3F4F6; color: var(--primary); }
        .icon-action.delete:hover { background: #FEF2F2; color: var(--danger); border-color: #FECACA; }

        /* Table */
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 15px; color: var(--text-light); font-weight: 600; font-size: 13px; border-bottom: 1px solid #E5E7EB; background: #F9FAFB; }
        td { padding: 15px; border-bottom: 1px solid #F3F4F6; font-size: 14px; vertical-align: middle; }
        tr:hover td { background: #F9FAFB; }

        /* Badges */
        .badge { padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; }
        .badge-active { background: #D1FAE5; color: #065F46; }
        .badge-banned { background: #FEE2E2; color: #991B1B; }
        .plan-mini { background: #F3E8FF; color: #6B21A8; border: 1px solid #E9D5FF; }
        .plan-basic { background: #DBEAFE; color: #1E40AF; border: 1px solid #BFDBFE; }
        .plan-standard { background: #FFEDD5; color: #9A3412; border: 1px solid #FED7AA; }

        /* Small Inputs in Table */
        .mini-input { padding: 6px; border: 1px solid #D1D5DB; border-radius: 6px; width: 70px; text-align: center; }
        .mini-select { padding: 6px; border: 1px solid #D1D5DB; border-radius: 6px; font-family: 'Kantumruy Pro'; }
    </style>
</head>
<body>
    <!-- Sidebar -->
    <div class="sidebar">
        <div class="logo"><i class="fas fa-layer-group"></i> Sora Manager</div>
        <a href="/dashboard" class="nav-item {{ 'active' if page == 'users' else '' }}"><i class="fas fa-users"></i> អ្នកប្រើប្រាស់</a>
        <a href="/vouchers" class="nav-item {{ 'active' if page == 'vouchers' else '' }}"><i class="fas fa-ticket-alt"></i> ប័ណ្ណបញ្ចូលលុយ</a>
        <a href="/security" class="nav-item {{ 'active' if page == 'security' else '' }}"><i class="fas fa-shield-alt"></i> សុវត្ថិភាព</a>
        <a href="/logs" class="nav-item {{ 'active' if page == 'logs' else '' }}"><i class="fas fa-history"></i> កំណត់ត្រា</a>
        <a href="/settings" class="nav-item {{ 'active' if page == 'settings' else '' }}"><i class="fas fa-cog"></i> ការកំណត់</a>
        <div style="flex-grow:1;"></div>
        <a href="/logout" class="nav-item" style="color:#EF4444; background: rgba(239, 68, 68, 0.1);"><i class="fas fa-sign-out-alt"></i> ចាកចេញ</a>
    </div>

    <!-- Content -->
    <div class="main-content">
        {% if page == 'users' %}
        <div class="header-title">គ្រប់គ្រងអ្នកប្រើប្រាស់ (User Management)</div>
        
        <!-- Stats -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon" style="background:#EEF2FF; color:#4F46E5;"><i class="fas fa-users"></i></div>
                <div class="stat-info"><h4>អ្នកប្រើសរុប</h4><p>{{ total_users }}</p></div>
            </div>
            <div class="stat-card">
                <div class="stat-icon" style="background:#ECFDF5; color:#10B981;"><i class="fas fa-user-check"></i></div>
                <div class="stat-info"><h4>កំពុងសកម្ម</h4><p>{{ active_users }}</p></div>
            </div>
            <div class="stat-card">
                <div class="stat-icon" style="background:#FFF7ED; color:#F97316;"><i class="fas fa-coins"></i></div>
                <div class="stat-info"><h4>ក្រេឌីតសរុប</h4><p>{{ total_credits }}</p></div>
            </div>
        </div>

        <!-- Add User -->
        <div class="card-box">
            <h4 class="section-header"><i class="fas fa-user-plus"></i> បង្កើតគណនីថ្មី</h4>
            <form action="/add_user" method="POST" class="form-row">
                <div class="form-group"><label>ឈ្មោះគណនី (Username)</label><input type="text" name="username" class="input-control" placeholder="Ex: User01" required></div>
                <div class="form-group"><label>ក្រេឌីត (Credits)</label><input type="number" name="credits" class="input-control" placeholder="500" required></div>
                <div class="form-group"><label>កញ្ចប់ (Plan)</label>
                    <select name="plan" class="input-control">
                        <option value="Mini">Mini (1 Process)</option>
                        <option value="Basic">Basic (2 Processes)</option>
                        <option value="Standard" selected>Standard (3 Processes)</option>
                    </select>
                </div>
                <div class="form-group"><label>ថ្ងៃផុតកំណត់</label><input type="date" name="expiry" class="input-control" required></div>
                <div class="form-group"><button class="btn btn-primary" style="width:100%; height:46px; margin-top:2px;">បង្កើត</button></div>
            </form>
        </div>

        <!-- User Table -->
        <div class="card-box" style="padding:0; overflow:hidden;">
            <table style="width:100%;">
                <thead>
                    <tr>
                        <th>ឈ្មោះគណនី</th>
                        <th>License Key</th>
                        <th>កញ្ចប់ (Plan)</th>
                        <th>ក្រេឌីត</th>
                        <th>ផុតកំណត់</th>
                        <th>ស្ថានភាព</th>
                        <th>គ្រប់គ្រង</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td style="font-weight:700;">{{ user[0] }}</td>
                        <td style="font-family:monospace; color:var(--text-light);">{{ user[1] }}</td>
                        <td>
                            <form action="/update_plan" method="POST">
                                <input type="hidden" name="username" value="{{ user[0] }}">
                                <select name="plan" class="mini-select" onchange="this.form.submit()">
                                    <option value="Mini" {% if user[6]=='Mini' %}selected{% endif %}>Mini</option>
                                    <option value="Basic" {% if user[6]=='Basic' %}selected{% endif %}>Basic</option>
                                    <option value="Standard" {% if user[6]=='Standard' %}selected{% endif %}>Standard</option>
                                </select>
                            </form>
                        </td>
                        <td>
                            <form action="/update_credits" method="POST" style="display:flex; align-items:center; gap:5px;">
                                <input type="hidden" name="username" value="{{ user[0] }}">
                                <span style="font-weight:bold; color:{{ '#10B981' if user[2] > 50 else '#EF4444' }}; min-width:30px;">{{ user[2] }}</span>
                                <input type="number" name="amount" class="mini-input" placeholder="+/-">
                                <button class="icon-action" style="background:#10B981; color:white; border:none; width:28px; height:28px;"><i class="fas fa-check"></i></button>
                            </form>
                        </td>
                        <td>{{ user[3] }}</td>
                        <td>{% if user[4] %}<span class="badge badge-active">Active</span>{% else %}<span class="badge badge-banned">Banned</span>{% endif %}</td>
                        <td>
                            <div style="display:flex; gap:5px;">
                                <a href="/toggle_status/{{ user[0] }}" class="icon-action" title="Block/Unblock"><i class="fas fa-power-off"></i></a>
                                <a href="/delete_user/{{ user[0] }}" class="icon-action delete" title="Delete" onclick="return confirm('Confirm delete?')"><i class="fas fa-trash"></i></a>
                            </div>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif page == 'vouchers' %}
        <div class="header-title">ប្រព័ន្ធប័ណ្ណបញ្ចូលលុយ (Vouchers)</div>
        <div class="card-box">
            <h4 class="section-header"><i class="fas fa-magic"></i> បង្កើតកូដថ្មី</h4>
            <form action="/generate_vouchers" method="POST" class="form-row">
                <div class="form-group"><label>ចំនួនក្រេឌីត (Credit Amount)</label><input type="number" name="amount" class="input-control" placeholder="100" required></div>
                <div class="form-group"><label>ចំនួនសន្លឹក (Quantity)</label><input type="number" name="count" class="input-control" value="1" required></div>
                <div class="form-group"><button class="btn btn-success" style="height:46px;">បង្កើតកូដ</button></div>
            </form>
        </div>
        <div class="card-box" style="padding:0; overflow:hidden;">
            <table>
                <thead><tr><th>កូដ (Code)</th><th>តម្លៃ</th><th>ស្ថានភាព</th><th>អ្នកប្រើ</th><th>កាលបរិច្ឆេទ</th></tr></thead>
                <tbody>
                    {% for v in vouchers %}
                    <tr>
                        <td style="font-family:monospace; font-weight:bold; color:var(--primary);">{{ v[0] }}</td>
                        <td style="color:var(--success); font-weight:bold;">+{{ v[1] }}</td>
                        <td>{% if v[2] %}<span class="badge badge-banned">ប្រើរួច</span>{% else %}<span class="badge badge-active">នៅទំនេរ</span>{% endif %}</td>
                        <td>{{ v[4] if v[4] else '-' }}</td>
                        <td style="color:gray; font-size:12px;">{{ v[3] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif page == 'security' %}
        <div class="header-title">សុវត្ថិភាពប្រព័ន្ធ (Security Shield)</div>
        <div class="card-box">
            <h4 class="section-header" style="color:var(--danger);"><i class="fas fa-ban"></i> IP ដែលត្រូវបានហាមឃាត់ (Banned IPs)</h4>
            <p style="margin-bottom:20px; color:gray;">IP ទាំងនេះត្រូវបានបិទដោយស្វ័យប្រវត្តិ ដោយសារសកម្មភាពមិនប្រក្រតី (Brute force/Scanning)។</p>
            <table>
                <thead><tr><th>IP Address</th><th>មូលហេតុ (Reason)</th><th>ពេលវេលា</th><th>សកម្មភាព</th></tr></thead>
                <tbody>
                    {% for ip in banned_ips %}
                    <tr>
                        <td style="font-family:monospace; font-weight:bold;">{{ ip[0] }}</td>
                        <td>{{ ip[1] }}</td>
                        <td>{{ ip[2] }}</td>
                        <td><a href="/unban_ip/{{ ip[0] }}" class="btn btn-success" style="padding:6px 12px; font-size:12px;">ដោះលែង (Unban)</a></td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4" style="text-align:center; padding:30px;">✅ មិនមាន IP ជាប់ Ban ទេ (Clean)</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif page == 'settings' %}
        <div class="header-title">ការកំណត់ប្រព័ន្ធ (System Settings)</div>
        
        <div class="card-box">
            <h4 class="section-header"><i class="fas fa-bullhorn"></i> ផ្សព្វផ្សាយដំណឹង (Broadcast)</h4>
            <form action="/update_broadcast" method="POST" style="display:flex; gap:10px;">
                <input type="text" name="message" class="input-control" placeholder="សរសេរសារជូនដំណឹងទៅកាន់អ្នកប្រើប្រាស់ទាំងអស់..." value="{{ broadcast_msg }}">
                <button class="btn btn-primary">Update</button>
                <a href="/clear_broadcast" class="btn btn-danger">Clear</a>
            </form>
        </div>

        <form action="/update_settings" method="POST">
            <div class="form-row" style="margin-bottom:20px;">
                <!-- Costs -->
                <div class="card-box" style="flex:1; margin-bottom:0;">
                    <h4 class="section-header"><i class="fas fa-tag"></i> តម្លៃបង្កើតវីដេអូ</h4>
                    <div class="form-group" style="margin-bottom:15px;"><label>Sora-2 Cost (10s)</label><input type="number" name="cost_sora_2" class="input-control" value="{{ costs.sora_2 }}"></div>
                    <div class="form-group"><label>Sora-2 Pro Cost (15s)</label><input type="number" name="cost_sora_2_pro" class="input-control" value="{{ costs.sora_2_pro }}"></div>
                </div>
                <!-- Limits -->
                <div class="card-box" style="flex:1; margin-bottom:0;">
                    <h4 class="section-header"><i class="fas fa-tachometer-alt"></i> កំណត់ចំនួនដំណើរការ (Limits)</h4>
                    <div class="form-group" style="margin-bottom:10px;"><label>Mini Plan</label><input type="number" name="limit_mini" class="input-control" value="{{ limits.mini }}"></div>
                    <div class="form-group" style="margin-bottom:10px;"><label>Basic Plan</label><input type="number" name="limit_basic" class="input-control" value="{{ limits.basic }}"></div>
                    <div class="form-group"><label>Standard Plan</label><input type="number" name="limit_standard" class="input-control" value="{{ limits.standard }}"></div>
                </div>
            </div>
            
            <div class="card-box">
                <h4 class="section-header"><i class="fas fa-key"></i> API Configuration</h4>
                <div class="form-group">
                    <label>Real Sora API Key</label>
                    <input type="text" name="sora_api_key" class="input-control" value="{{ api_key }}">
                </div>
                <div style="margin-top:20px; display:flex; justify-content:space-between;">
                    <button class="btn btn-success"><i class="fas fa-save"></i> រក្សាទុកការកំណត់ទាំងអស់</button>
                    <a href="/download_db" class="btn btn-primary" style="background:#0F172A;"><i class="fas fa-database"></i> Backup Database</a>
                </div>
            </div>
        </form>

        {% elif page == 'logs' %}
        <div class="header-title">កំណត់ត្រា (System Logs)</div>
        <div class="card-box" style="padding:0; overflow:hidden;">
            <table>
                <thead><tr><th>ពេលវេលា</th><th>ឈ្មោះគណនី</th><th>សកម្មភាព</th><th>ការចំណាយ</th></tr></thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                        <td style="color:#6B7280;">{{ log[4] }}</td>
                        <td style="font-weight:bold;">{{ log[1] }}</td>
                        <td>{{ log[2] }}</td>
                        <td style="font-weight:bold; color:var(--danger);">-{{ log[3] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Admin Login</title>
    <link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body { background: #F3F4F6; height: 100vh; display: flex; justify-content: center; align-items: center; font-family: 'Kantumruy Pro', sans-serif; margin: 0; }
        .login-card { background: white; padding: 40px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); width: 350px; text-align: center; }
        h2 { color: #111827; margin-top: 0; }
        input { width: 100%; padding: 12px; margin-bottom: 20px; border: 1px solid #D1D5DB; border-radius: 8px; box-sizing: border-box; outline: none; transition: 0.2s; }
        input:focus { border-color: #4F46E5; box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1); }
        button { width: 100%; padding: 12px; background: #4F46E5; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 16px; transition: 0.2s; }
        button:hover { background: #4338ca; }
        .secure-badge { background: #ECFDF5; color: #047857; padding: 5px 10px; border-radius: 20px; font-size: 12px; display: inline-block; margin-bottom: 20px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="secure-badge">🔒 Secure Gateway</div>
        <h2>Sora Admin</h2>
        <form method="POST">
            <input type="password" name="password" placeholder="បញ្ចូលលេខកូដសម្ងាត់" required>
            <button>ចូលប្រព័ន្ធ</button>
        </form>
    </div>
</body>
</html>
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
    return jsonify({"status": "Server Running", "secure": True}), 200

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
    conn.commit(); conn.close()
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
    limits = {'mini': get_setting('limit_mini', 1), 'basic': get_setting('limit_basic', 2), 'standard': get_setting('limit_standard', 3)}
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
    conn = get_db(); row = conn.execute("SELECT credits, is_active FROM users WHERE username=? AND api_key=?", (u,k)).fetchone()
    if not row: conn.close(); return jsonify({"code":-1}), 401
    if not row[1]: conn.close(); return jsonify({"code":-1, "message": "Banned"}), 403
    
    model = request.json.get('model', '')
    cost = int(get_setting('cost_sora_2_pro', 35)) if "pro" in model else int(get_setting('cost_sora_2', 25))
    if row[0] < cost: conn.close(); return jsonify({"code":-1, "message": "Insufficient Credits"}), 402
    
    try:
        real_key = get_setting('sora_api_key')
        r = requests.post("https://FreeSoraGenerator.com/api/v1/video/sora-video", json=request.json, headers={"Authorization": f"Bearer {real_key}"}, timeout=120)
        
        if r.json().get("code") == 0:
            tid = r.json().get('data', {}).get('taskId')
            if tid: conn.execute("INSERT INTO tasks (task_id, username, cost, status, created_at) VALUES (?, ?, ?, ?, ?)", (tid, u, cost, 'pending', str(datetime.now())))
            conn.execute("UPDATE users SET credits=credits-? WHERE username=?", (cost, u))
            conn.execute("INSERT INTO logs (username, action, cost, timestamp) VALUES (?, ?, ?, ?)", (u, "generate", cost, str(datetime.now())))
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
