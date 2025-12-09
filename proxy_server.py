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
# Secret Login Path (e.g. /secure_login)
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
        'broadcast_msg': '',
        'broadcast_color': '#FF0000', # Default Red
        'latest_version': '1.0.0', # Default Version
        'update_desc': 'Initial Release' # Default Description
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
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: { sans: ['"Kantumruy Pro"', 'sans-serif'] },
                    colors: {
                        primary: '#4F46E5', secondary: '#64748b', success: '#10b981', 
                        danger: '#ef4444', warning: '#f59e0b', dark: '#1e293b'
                    }
                }
            }
        }
    </script>
    <style>
        .sidebar-link { transition: all 0.2s; }
        .sidebar-link:hover, .sidebar-link.active { background-color: #4F46E5; color: white; transform: translateX(5px); }
        .sidebar-link:hover i, .sidebar-link.active i { color: white; }
        .card-hover { transition: transform 0.2s, box-shadow 0.2s; }
        .card-hover:hover { transform: translateY(-2px); box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1); }
        /* Custom Scrollbar */
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #f1f1f1; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
    </style>
</head>
<body class="flex h-screen overflow-hidden bg-gray-50 text-slate-800">

    <!-- Sidebar -->
    <aside class="w-64 bg-white border-r border-gray-200 flex flex-col hidden md:flex z-50 shadow-lg">
        <div class="h-20 flex items-center px-6 border-b border-gray-50">
            <i class="fas fa-layer-group text-primary text-2xl mr-3"></i>
            <span class="text-xl font-bold text-slate-800 tracking-tight">SoraManager</span>
        </div>

        <nav class="flex-1 overflow-y-auto py-6 px-4 space-y-1.5">
            <p class="px-4 text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">ម៉ឺនុយចម្បង</p>
            <a href="/dashboard" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'users' else '' }}">
                <i class="fas fa-users w-6 {{ 'text-primary' if page != 'users' else 'text-white' }}"></i>
                <span class="font-medium">អ្នកប្រើប្រាស់</span>
            </a>
            <a href="/vouchers" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'vouchers' else '' }}">
                <i class="fas fa-ticket-alt w-6 {{ 'text-primary' if page != 'vouchers' else 'text-white' }}"></i>
                <span class="font-medium">ប័ណ្ណបញ្ចូលលុយ</span>
            </a>
            <a href="/logs" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'logs' else '' }}">
                <i class="fas fa-clipboard-list w-6 {{ 'text-primary' if page != 'logs' else 'text-white' }}"></i>
                <span class="font-medium">ប្រវត្តិសកម្មភាព</span>
            </a>
            
            <p class="px-4 text-xs font-bold text-slate-400 uppercase tracking-wider mt-8 mb-3">ប្រព័ន្ធ</p>
            <a href="/security" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'security' else '' }}">
                <i class="fas fa-shield-alt w-6 {{ 'text-primary' if page != 'security' else 'text-white' }}"></i>
                <span class="font-medium">សុវត្ថិភាព</span>
            </a>
            <a href="/settings" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'settings' else '' }}">
                <i class="fas fa-cog w-6 {{ 'text-primary' if page != 'settings' else 'text-white' }}"></i>
                <span class="font-medium">ការកំណត់</span>
            </a>
        </nav>

        <div class="p-4 border-t border-gray-100">
            <a href="/logout" class="flex items-center justify-center px-4 py-3 bg-red-50 text-red-600 hover:bg-red-100 rounded-xl transition-colors font-bold">
                <i class="fas fa-sign-out-alt mr-2"></i> ចាកចេញ
            </a>
        </div>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 overflow-y-auto h-full p-6 lg:p-10 relative">
        
        {% if page == 'users' %}
        <div class="max-w-7xl mx-auto">
            <div class="flex justify-between items-end mb-8">
                <div>
                    <h1 class="text-3xl font-bold text-slate-800">គ្រប់គ្រងអ្នកប្រើប្រាស់</h1>
                    <p class="text-slate-500 mt-1">មើលនិងគ្រប់គ្រងសិទ្ធិប្រើប្រាស់ និងក្រេឌីត</p>
                </div>
                <div class="bg-emerald-50 text-emerald-600 px-4 py-2 rounded-full text-sm font-bold flex items-center gap-2 border border-emerald-100">
                    <span class="relative flex h-3 w-3"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span></span>
                    System Online
                </div>
            </div>

            <!-- Stats -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="card-hover bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden">
                    <div class="flex justify-between items-start z-10 relative">
                        <div><p class="text-xs font-bold text-slate-400 uppercase tracking-wide">អ្នកប្រើសរុប</p><h3 class="text-3xl font-bold text-slate-800 mt-1">{{ total_users }}</h3></div>
                        <div class="p-3 bg-indigo-50 rounded-xl text-indigo-600"><i class="fas fa-users text-xl"></i></div>
                    </div>
                </div>
                <div class="card-hover bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden">
                    <div class="flex justify-between items-start z-10 relative">
                        <div><p class="text-xs font-bold text-slate-400 uppercase tracking-wide">គណនីសកម្ម</p><h3 class="text-3xl font-bold text-slate-800 mt-1">{{ active_users }}</h3></div>
                        <div class="p-3 bg-emerald-50 rounded-xl text-emerald-600"><i class="fas fa-user-check text-xl"></i></div>
                    </div>
                </div>
                <div class="card-hover bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden">
                    <div class="flex justify-between items-start z-10 relative">
                        <div><p class="text-xs font-bold text-slate-400 uppercase tracking-wide">ក្រេឌីតសរុប</p><h3 class="text-3xl font-bold text-slate-800 mt-1">{{ total_credits }}</h3></div>
                        <div class="p-3 bg-amber-50 rounded-xl text-amber-600"><i class="fas fa-coins text-xl"></i></div>
                    </div>
                </div>
            </div>

            <!-- Create User -->
            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 mb-8">
                <h3 class="text-lg font-bold text-slate-800 mb-5 flex items-center gap-2"><i class="fas fa-user-plus text-primary"></i> បង្កើតគណនីថ្មី</h3>
                <form action="/add_user" method="POST" class="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
                    <div class="col-span-1"><label class="block text-xs font-bold text-slate-500 mb-1.5">USERNAME</label><input type="text" name="username" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-medium" placeholder="Ex: User01" required></div>
                    <div class="col-span-1"><label class="block text-xs font-bold text-slate-500 mb-1.5">CREDITS</label><input type="number" name="credits" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-medium" placeholder="500" required></div>
                    <div class="col-span-1"><label class="block text-xs font-bold text-slate-500 mb-1.5">PLAN</label>
                        <select name="plan" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-medium cursor-pointer">
                            <option value="Mini">Mini (1)</option><option value="Basic">Basic (2)</option><option value="Standard" selected>Standard (3)</option>
                        </select>
                    </div>
                    <div class="col-span-1"><label class="block text-xs font-bold text-slate-500 mb-1.5">EXPIRY</label><input type="date" name="expiry" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-medium cursor-pointer" required></div>
                    <div class="col-span-1"><button type="submit" class="w-full bg-primary hover:bg-indigo-600 text-white font-bold py-2.5 rounded-lg transition shadow-lg shadow-indigo-500/30 flex items-center justify-center gap-2"><i class="fas fa-check"></i> បង្កើត</button></div>
                </form>
            </div>

            <!-- Table -->
            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-sm text-left">
                        <thead class="text-xs text-slate-500 uppercase bg-slate-50 border-b border-slate-100">
                            <tr><th class="px-6 py-4 font-bold">ឈ្មោះគណនី</th><th class="px-6 py-4 font-bold">License Key</th><th class="px-6 py-4 font-bold">កញ្ចប់</th><th class="px-6 py-4 font-bold text-center">ក្រេឌីត</th><th class="px-6 py-4 font-bold">ផុតកំណត់</th><th class="px-6 py-4 font-bold">ស្ថានភាព</th><th class="px-6 py-4 font-bold text-right">សកម្មភាព</th></tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            {% for user in users %}
                            <tr class="hover:bg-slate-50 transition-colors group">
                                <td class="px-6 py-4 font-bold text-slate-700">{{ user[0] }}</td>
                                <td class="px-6 py-4 font-mono text-slate-400 text-xs select-all">{{ user[1] }}</td>
                                <td class="px-6 py-4">
                                    {% if user[6] == 'Standard' %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-orange-100 text-orange-600 border border-orange-200">Standard</span>
                                    {% elif user[6] == 'Basic' %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-blue-100 text-blue-600 border border-blue-200">Basic</span>
                                    {% else %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-purple-100 text-purple-600 border border-purple-200">Mini</span>{% endif %}
                                </td>
                                <td class="px-6 py-4">
                                    <form action="/update_credits" method="POST" class="flex items-center justify-center gap-2">
                                        <input type="hidden" name="username" value="{{ user[0] }}">
                                        <span class="font-bold {{ 'text-emerald-500' if user[2] > 50 else 'text-red-500' }}">{{ user[2] }}</span>
                                        <input type="number" name="amount" placeholder="+/-" class="w-16 px-2 py-1 text-xs border rounded-md bg-white focus:ring-1 focus:ring-indigo-500 outline-none transition-all opacity-0 group-hover:opacity-100 focus:opacity-100">
                                    </form>
                                </td>
                                <td class="px-6 py-4 text-slate-500 text-xs">{{ user[3] }}</td>
                                <td class="px-6 py-4">
                                    {% if user[4] %}<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>Active</span>
                                    {% else %}<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-red-100 text-red-700"><span class="w-1.5 h-1.5 rounded-full bg-red-500"></span>Banned</span>{% endif %}
                                </td>
                                <td class="px-6 py-4 text-right">
                                    <div class="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                        <form action="/update_plan" method="POST" class="inline">
                                            <input type="hidden" name="username" value="{{ user[0] }}">
                                            <select name="plan" onchange="this.form.submit()" class="w-20 text-xs py-1 px-1 border rounded bg-white text-slate-600 cursor-pointer outline-none">
                                                <option value="" disabled selected>Plan</option><option value="Mini">Mini</option><option value="Basic">Basic</option><option value="Standard">Std</option>
                                            </select>
                                        </form>
                                        <a href="/toggle_status/{{ user[0] }}" class="p-1.5 bg-slate-100 rounded-md text-slate-500 hover:bg-slate-200 hover:text-slate-800 transition-colors" title="Toggle Status"><i class="fas fa-power-off"></i></a>
                                        <a href="/delete_user/{{ user[0] }}" class="p-1.5 bg-red-50 rounded-md text-red-400 hover:bg-red-100 hover:text-red-600 transition-colors" onclick="return confirm('Delete?')" title="Delete"><i class="fas fa-trash-alt"></i></a>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        {% elif page == 'vouchers' %}
        <div class="max-w-5xl mx-auto">
            <h1 class="text-2xl font-bold text-slate-800 mb-6">ប័ណ្ណបញ្ចូលលុយ (Vouchers)</h1>
            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 mb-8 flex gap-6 items-end">
                <div class="flex-1">
                    <h3 class="text-lg font-bold text-slate-800 mb-1"><i class="fas fa-magic text-primary"></i> បង្កើតកូដថ្មី</h3>
                    <p class="text-sm text-slate-400">បង្កើតកូដសម្រាប់ឱ្យអ្នកប្រើប្រាស់បញ្ចូលដោយខ្លួនឯង</p>
                </div>
                <form action="/generate_vouchers" method="POST" class="flex gap-4 items-end flex-[2]">
                    <div class="flex-1">
                        <label class="block text-xs font-bold text-slate-500 mb-1">ចំនួនក្រេឌីត</label>
                        <input type="number" name="amount" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none" placeholder="100" required>
                    </div>
                    <div class="flex-1">
                        <label class="block text-xs font-bold text-slate-500 mb-1">ចំនួនសន្លឹក</label>
                        <input type="number" name="count" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none" value="1" required>
                    </div>
                    <button class="bg-emerald-500 hover:bg-emerald-600 text-white font-bold py-2.5 px-6 rounded-lg transition shadow-lg shadow-emerald-500/30">បង្កើត</button>
                </form>
            </div>
            
            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                <table class="w-full text-sm text-left">
                    <thead class="text-xs text-slate-500 uppercase bg-slate-50 border-b"><tr><th class="px-6 py-4">Code</th><th class="px-6 py-4">Value</th><th class="px-6 py-4">Status</th><th class="px-6 py-4">Used By</th></tr></thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for v in vouchers %}
                        <tr class="hover:bg-slate-50">
                            <td class="px-6 py-4 font-mono font-bold text-slate-700 select-all">{{ v[0] }}</td>
                            <td class="px-6 py-4 text-emerald-600 font-bold">+{{ v[1] }}</td>
                            <td class="px-6 py-4">{% if v[2] %}<span class="px-2 py-1 rounded text-xs font-bold bg-red-100 text-red-600">Used</span>{% else %}<span class="px-2 py-1 rounded text-xs font-bold bg-green-100 text-green-600">Active</span>{% endif %}</td>
                            <td class="px-6 py-4 text-slate-500">{{ v[4] if v[4] else '-' }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        {% elif page == 'security' %}
        <div class="max-w-5xl mx-auto">
            <h1 class="text-2xl font-bold text-slate-800 mb-6">សុវត្ថិភាព (Security Shield)</h1>
            <div class="bg-white rounded-2xl shadow-sm border border-red-100 p-6 relative overflow-hidden">
                <div class="absolute top-0 right-0 p-4 opacity-10"><i class="fas fa-shield-alt text-9xl text-red-500"></i></div>
                <h4 class="text-lg font-bold text-red-600 mb-2 relative z-10"><i class="fas fa-ban"></i> IP ដែលត្រូវបានហាមឃាត់ (Banned IPs)</h4>
                <p class="text-sm text-slate-500 mb-6 relative z-10">IP ទាំងនេះត្រូវបានបិទដោយស្វ័យប្រវត្តិ ដោយសារសកម្មភាពមិនប្រក្រតី (Brute force/Scanning)។</p>
                <div class="overflow-x-auto relative z-10">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-red-50 text-red-700 text-xs uppercase rounded-lg"><tr><th class="px-6 py-3 rounded-l-lg">IP Address</th><th class="px-6 py-3">Reason</th><th class="px-6 py-3">Time</th><th class="px-6 py-3 rounded-r-lg">Action</th></tr></thead>
                        <tbody class="divide-y divide-red-100">
                            {% for ip in banned_ips %}
                            <tr>
                                <td class="px-6 py-4 font-mono font-bold">{{ ip[0] }}</td>
                                <td class="px-6 py-4">{{ ip[1] }}</td>
                                <td class="px-6 py-4 text-xs text-slate-400">{{ ip[2] }}</td>
                                <td class="px-6 py-4"><a href="/unban_ip/{{ ip[0] }}" class="px-3 py-1 bg-emerald-500 text-white rounded text-xs font-bold hover:bg-emerald-600 shadow-md shadow-emerald-200">Unban</a></td>
                            </tr>
                            {% else %}
                            <tr><td colspan="4" class="px-6 py-8 text-center text-slate-400">✅ មិនមាន IP ជាប់ Ban ទេ (System Clean)</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        {% elif page == 'settings' %}
        <div class="max-w-4xl mx-auto">
            <h1 class="text-2xl font-bold text-slate-800 mb-6">ការកំណត់ (Settings)</h1>
            
            <!-- Update System Config -->
            <div class="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-6 text-white shadow-xl shadow-blue-200 mb-8">
                <h4 class="font-bold text-lg mb-2 flex items-center gap-2"><i class="fas fa-sync-alt"></i> ប្រព័ន្ធអាប់ដេតកម្មវិធី (App Updates)</h4>
                <p class="text-white/80 text-sm mb-4">កំណត់កំណែថ្មី និងសារបង្ហាញទៅកាន់អ្នកប្រើប្រាស់។</p>
                <form action="/update_settings" method="POST" class="space-y-4">
                    <div class="flex gap-4">
                        <div class="w-1/3">
                            <label class="text-xs font-bold text-white/70 block mb-1">Latest Version</label>
                            <input type="text" name="latest_version" value="{{ latest_version }}" class="w-full bg-white/20 border border-white/30 rounded-lg px-3 py-2 text-white placeholder-white/60 focus:bg-white/30 outline-none backdrop-blur-sm" placeholder="Ex: 25.12.11">
                        </div>
                    </div>
                    <div>
                        <label class="text-xs font-bold text-white/70 block mb-1">Update Description (បង្ហាញលើផ្ទាំងអ្នកប្រើ)</label>
                        <textarea name="update_desc" class="w-full bg-white/20 border border-white/30 rounded-lg px-3 py-2 text-white placeholder-white/60 focus:bg-white/30 outline-none backdrop-blur-sm h-24" placeholder="សរសេរអំពីអ្វីដែលថ្មី...">{{ update_desc }}</textarea>
                    </div>
                    <button class="bg-white text-blue-600 font-bold px-6 py-2.5 rounded-lg hover:bg-blue-50 shadow-lg">Save Update Info</button>
                </form>
            </div>

            <!-- Broadcast -->
            <div class="bg-gradient-to-r from-indigo-600 to-purple-600 rounded-2xl p-6 text-white shadow-xl shadow-indigo-200 mb-8">
                <h4 class="font-bold text-lg mb-2 flex items-center gap-2"><i class="fas fa-bullhorn"></i> ផ្សព្វផ្សាយដំណឹង (Broadcast)</h4>
                <p class="text-white/80 text-sm mb-4">សារនេះនឹងលោតឡើងលើកម្មវិធីអ្នកប្រើប្រាស់ទាំងអស់។</p>
                <form action="/update_broadcast" method="POST" class="flex gap-2 items-center">
                    <input type="color" name="color" value="{{ broadcast_color }}" class="h-10 w-10 rounded border-none cursor-pointer shadow-lg" title="ពណ៌អក្សរ">
                    <input type="text" name="message" value="{{ broadcast_msg }}" class="flex-1 bg-white/20 border border-white/30 rounded-lg px-4 py-2.5 text-white placeholder-white/60 focus:bg-white/30 outline-none backdrop-blur-sm" placeholder="សរសេរសារ...">
                    <button class="bg-white text-indigo-600 font-bold px-6 py-2.5 rounded-lg hover:bg-indigo-50 shadow-lg">Send</button>
                    <a href="/clear_broadcast" class="bg-red-500/80 hover:bg-red-500 text-white font-bold px-4 py-2.5 rounded-lg backdrop-blur-sm">Clear</a>
                </form>
            </div>
            
            <form action="/update_settings" method="POST">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                    <!-- Costs -->
                    <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                        <h4 class="font-bold text-slate-700 mb-4 border-b pb-2 flex items-center gap-2"><i class="fas fa-tag text-amber-500"></i> តម្លៃ (Costs)</h4>
                        <div class="space-y-4">
                            <div><label class="text-xs font-bold text-slate-400">SORA-2 (Credits)</label><input type="number" name="cost_sora_2" value="{{ costs.sora_2 }}" class="w-full mt-1 p-2 border rounded-lg bg-slate-50 focus:bg-white focus:border-indigo-500 outline-none transition"></div>
                            <div><label class="text-xs font-bold text-slate-400">SORA-2 PRO (Credits)</label><input type="number" name="cost_sora_2_pro" value="{{ costs.sora_2_pro }}" class="w-full mt-1 p-2 border rounded-lg bg-slate-50 focus:bg-white focus:border-indigo-500 outline-none transition"></div>
                        </div>
                    </div>
                    <!-- Limits -->
                    <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                        <h4 class="font-bold text-slate-700 mb-4 border-b pb-2 flex items-center gap-2"><i class="fas fa-tachometer-alt text-blue-500"></i> ដែនកំណត់ (Limits)</h4>
                        <div class="space-y-4">
                            <div class="flex gap-3">
                                <div class="flex-1"><label class="text-xs font-bold text-slate-400">MINI</label><input type="number" name="limit_mini" value="{{ limits.mini }}" class="w-full mt-1 p-2 border rounded-lg bg-slate-50 text-center font-bold text-purple-600"></div>
                                <div class="flex-1"><label class="text-xs font-bold text-slate-400">BASIC</label><input type="number" name="limit_basic" value="{{ limits.basic }}" class="w-full mt-1 p-2 border rounded-lg bg-slate-50 text-center font-bold text-blue-600"></div>
                                <div class="flex-1"><label class="text-xs font-bold text-slate-400">STD</label><input type="number" name="limit_standard" value="{{ limits.standard }}" class="w-full mt-1 p-2 border rounded-lg bg-slate-50 text-center font-bold text-orange-600"></div>
                            </div>
                            <p class="text-xs text-slate-400 italic mt-2">* ចំនួនដំណើរការក្នុងពេលតែមួយ (Concurrent Processes)</p>
                        </div>
                    </div>
                </div>
                
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 mb-6">
                     <h4 class="font-bold text-slate-700 mb-4"><i class="fas fa-key text-slate-400"></i> API Configuration</h4>
                     <label class="text-xs font-bold text-slate-400 block mb-1">REAL SORA API KEY</label>
                     <input type="text" name="sora_api_key" value="{{ api_key }}" class="w-full p-3 border rounded-lg bg-slate-50 font-mono text-sm focus:bg-white focus:border-indigo-500 outline-none transition">
                </div>
                
                <div class="flex justify-between items-center bg-slate-50 p-4 rounded-xl border border-slate-200">
                    <a href="/download_db" class="text-slate-600 hover:text-slate-900 text-sm font-bold flex items-center gap-2 px-4 py-2 hover:bg-slate-200 rounded-lg transition"><i class="fas fa-download"></i> Backup Database</a>
                    <button class="bg-primary hover:bg-indigo-700 text-white font-bold py-3 px-8 rounded-xl shadow-lg shadow-indigo-500/30 transition transform hover:-translate-y-0.5">Save Changes</button>
                </div>
            </form>
        </div>
        
        {% elif page == 'logs' %}
        <div class="max-w-6xl mx-auto">
            <h1 class="text-2xl font-bold text-slate-800 mb-6">កំណត់ត្រា (Logs)</h1>
            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                <table class="w-full text-sm text-left">
                    <thead class="bg-slate-50 text-slate-500 text-xs uppercase border-b border-slate-100"><tr><th class="px-6 py-4">Time</th><th class="px-6 py-4">User</th><th class="px-6 py-4">Action</th><th class="px-6 py-4">Cost</th></tr></thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for l in logs %}
                        <tr class="hover:bg-slate-50">
                            <td class="px-6 py-3 text-slate-400 font-mono text-xs">{{ l[4] }}</td>
                            <td class="px-6 py-3 font-bold text-slate-700">{{ l[1] }}</td>
                            <td class="px-6 py-3">{{ l[2] }}</td>
                            <td class="px-6 py-3 font-bold text-red-500">-{{ l[3] }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        {% endif %}
    </main>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Secure Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@400;600&display=swap" rel="stylesheet">
</head>
<body class="bg-gray-100 h-screen flex items-center justify-center font-sans">
    <div class="bg-white p-10 rounded-2xl shadow-xl w-96 text-center border border-gray-100">
        <div class="mb-6 inline-flex items-center justify-center w-16 h-16 rounded-full bg-indigo-50 text-indigo-600">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
        </div>
        <h2 class="text-2xl font-bold text-gray-800 mb-2">Admin Portal</h2>
        <p class="text-sm text-gray-500 mb-8">Secure Gateway Access</p>
        
        <form method="POST" class="space-y-4">
            <input type="password" name="password" placeholder="Access Key" class="w-full px-4 py-3 rounded-lg border border-gray-300 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 outline-none transition" required>
            <button class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 rounded-lg transition duration-200 shadow-lg shadow-indigo-500/30">
                Unlock Dashboard
            </button>
        </form>
        <p class="mt-8 text-xs text-gray-400">System ID: 2025-SECURE-V2</p>
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
    clr = get_setting('broadcast_color', '#FF0000') 
    latest_ver = get_setting('latest_version', '1.0.0')
    update_desc = get_setting('update_desc', 'Initial Release')
    
    costs = {'sora_2': get_setting('cost_sora_2', 25), 'sora_2_pro': get_setting('cost_sora_2_pro', 35)}
    limits = {'mini': get_setting('limit_mini', 1), 'basic': get_setting('limit_basic', 2), 'standard': get_setting('limit_standard', 3)}
    
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', api_key=k, broadcast_msg=msg, broadcast_color=clr, 
                                  costs=costs, limits=limits, latest_version=latest_ver, update_desc=update_desc)

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
    set_setting('broadcast_color', request.form.get('color')) 
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
    
    # Get all global settings to send to client
    b = get_setting('broadcast_msg', '')
    bc = get_setting('broadcast_color', '#FF0000')
    lv = get_setting('latest_version', '1.0.0')
    ud = get_setting('update_desc', 'Initial Release')
    
    conn.close()
    
    if not u: return jsonify({"valid": False, "message": "Invalid Credentials"})
    if not u[2]: return jsonify({"valid": False, "message": "Banned"})
    if datetime.now() > datetime.strptime(u[1], "%Y-%m-%d"): return jsonify({"valid": False, "message": "Expired"})
    
    limit = int(get_setting(f"limit_{u[3].lower()}", 3))
    
    return jsonify({
        "valid": True, 
        "credits": u[0], 
        "expiry": u[1], 
        "plan": u[3], 
        "concurrency_limit": limit, 
        "broadcast": b, 
        "broadcast_color": bc,
        "latest_version": lv,
        "update_desc": ud
    })

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
