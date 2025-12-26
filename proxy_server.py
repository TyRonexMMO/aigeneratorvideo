# --- START OF FILE admin_dashboardnew26.py ---

from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file, abort
import requests
import os
import sqlite3
import uuid
import time
import random
import string
import json
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "super_secret_admin_key_v3")

# --- CONFIGURATION ---
DB_PATH = os.environ.get("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_LOGIN_PATH = os.environ.get("ADMIN_PATH", "secure_login")

# Security Config
MAX_SUSPICIOUS_ATTEMPTS = 5
suspicious_tracker = {} 

# --- DATABASE SETUP ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Updated Users Table: Added custom limits, costs, assigned_key, last_seen, session_time
    # Status: 1=Active, 0=Banned, 2=Suspended
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, api_key TEXT, credits INTEGER, expiry_date TEXT, 
                  is_active INTEGER, created_at TEXT, plan TEXT DEFAULT 'Standard',
                  custom_limit INTEGER DEFAULT NULL, 
                  custom_cost_2 INTEGER DEFAULT NULL, 
                  custom_cost_pro INTEGER DEFAULT NULL,
                  assigned_api_key TEXT DEFAULT NULL,
                  last_seen TEXT,
                  session_minutes INTEGER DEFAULT 0,
                  daily_stats TEXT DEFAULT '{}')''')

    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, cost INTEGER, timestamp TEXT, status TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # Updated Vouchers: max_uses, current_uses, expiry
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers
                 (code TEXT PRIMARY KEY, amount INTEGER, max_uses INTEGER DEFAULT 1, current_uses INTEGER DEFAULT 0, 
                  expiry_date TEXT, created_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS voucher_usage
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, username TEXT, used_at TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (task_id TEXT PRIMARY KEY, username TEXT, cost INTEGER, status TEXT, created_at TEXT, model TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS banned_ips
                 (ip TEXT PRIMARY KEY, reason TEXT, banned_at TEXT)''')
    
    # New: Multi API Keys
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                 (key_value TEXT PRIMARY KEY, label TEXT, is_active INTEGER DEFAULT 1, error_count INTEGER DEFAULT 0)''')

    defaults = {
        'cost_sora_2': '25', 'cost_sora_2_pro': '35',
        'limit_mini': '1', 'limit_basic': '2', 'limit_standard': '3', 'limit_premium': '5',
        'broadcast_msg': '',
        'broadcast_color': '#FF0000',
        'latest_version': '1.0.0',
        'update_desc': 'Initial Release',
        'update_is_live': '0',
        'update_url': '' # Changed from filename to URL
    }
    for k, v in defaults.items():
        try: c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
        except: pass
    
    # Migrate old tables if needed (simplistic migration check)
    try: c.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'Standard'")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN custom_limit INTEGER DEFAULT NULL")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN custom_cost_2 INTEGER DEFAULT NULL")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN custom_cost_pro INTEGER DEFAULT NULL")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN assigned_api_key TEXT DEFAULT NULL")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN session_minutes INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN daily_stats TEXT DEFAULT '{}'")
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
    return f"SORA-{amount}-{''.join(random.choices(chars, k=8))}"

def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

def get_active_api_key(username=None):
    conn = get_db()
    # 1. Check if user has assigned key
    if username:
        user = conn.execute("SELECT assigned_api_key FROM users WHERE username=?", (username,)).fetchone()
        if user and user[0]:
            conn.close()
            return user[0]
    
    # 2. Get random active key from pool
    keys = conn.execute("SELECT key_value FROM api_keys WHERE is_active=1 ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    return keys[0] if keys else None

# --- SECURITY MIDDLEWARE ---
@app.before_request
def security_guard():
    ip = get_client_ip()
    conn = get_db()
    is_banned = conn.execute("SELECT 1 FROM banned_ips WHERE ip=?", (ip,)).fetchone()
    conn.close()
    if is_banned: return jsonify({"code": 403, "message": "Access Denied: IP Banned."}), 403
    if 'logged_in' in session: return 
    valid_starts = ['/api/', '/static/']
    if request.path == f'/{ADMIN_LOGIN_PATH}' or any(request.path.startswith(p) for p in valid_starts) or request.path == '/': return 
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

# --- ADMIN DASHBOARD HTML ---
MODERN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="km">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sora Admin Ultimate</title>
    <link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: { extend: { fontFamily: { sans: ['"Kantumruy Pro"', 'sans-serif'] }, colors: { primary: '#6366f1', dark: '#0f172a' } } }
        }
    </script>
    <style>
        .sidebar-link.active { background-color: #6366f1; color: white; box-shadow: 0 4px 6px -1px rgba(99, 102, 241, 0.4); }
        .switch { position: relative; display: inline-block; width: 40px; height: 20px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #cbd5e1; transition: .4s; border-radius: 20px; }
        .slider:before { position: absolute; content: ""; height: 16px; width: 16px; left: 2px; bottom: 2px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #10b981; }
        input:checked + .slider:before { transform: translateX(20px); }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 3px; }
    </style>
</head>
<body class="flex h-screen bg-slate-50 text-slate-800 font-sans overflow-hidden">

    <!-- Sidebar -->
    <aside class="w-64 bg-white border-r border-slate-200 flex flex-col z-20 shadow-xl hidden md:flex">
        <div class="h-16 flex items-center px-6 border-b border-slate-100">
            <i class="fas fa-cube text-primary text-2xl mr-3"></i>
            <span class="text-xl font-bold tracking-tight text-slate-800">SoraAdmin <span class="text-xs bg-primary text-white px-1.5 py-0.5 rounded">PRO</span></span>
        </div>
        <nav class="flex-1 overflow-y-auto py-6 px-3 space-y-1">
            <p class="px-3 text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">ចាត់ចែង (Manage)</p>
            <a href="/dashboard" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'users' else '' }}">
                <i class="fas fa-users w-8 text-center"></i> <span class="font-medium">អ្នកប្រើប្រាស់</span>
            </a>
            <a href="/vouchers" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'vouchers' else '' }}">
                <i class="fas fa-ticket-alt w-8 text-center"></i> <span class="font-medium">ប័ណ្ណបញ្ចូលលុយ</span>
            </a>
            <a href="/api_keys" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'api_keys' else '' }}">
                <i class="fas fa-key w-8 text-center"></i> <span class="font-medium">API Keys</span>
            </a>
            
            <p class="px-3 text-xs font-bold text-slate-400 uppercase tracking-wider mt-6 mb-2">ប្រព័ន្ធ (System)</p>
            <a href="/logs" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'logs' else '' }}">
                <i class="fas fa-list-alt w-8 text-center"></i> <span class="font-medium">កំណត់ត្រា</span>
            </a>
            <a href="/settings" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'settings' else '' }}">
                <i class="fas fa-cogs w-8 text-center"></i> <span class="font-medium">ការកំណត់</span>
            </a>
        </nav>
        <div class="p-4 border-t border-slate-100">
            <a href="/logout" class="flex items-center justify-center w-full px-4 py-2 bg-red-50 text-red-600 rounded-lg font-bold hover:bg-red-100 transition"><i class="fas fa-sign-out-alt mr-2"></i> ចាកចេញ</a>
        </div>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 overflow-y-auto relative">
        <!-- Top Bar -->
        <header class="bg-white/80 backdrop-blur-md sticky top-0 z-10 border-b border-slate-200 px-8 py-4 flex justify-between items-center">
            <h2 class="text-xl font-bold text-slate-800">
                {% if page == 'users' %}👥 គ្រប់គ្រងអ្នកប្រើប្រាស់
                {% elif page == 'vouchers' %}🎫 ប័ណ្ណបញ្ចូលលុយ (Vouchers)
                {% elif page == 'api_keys' %}🔑 គ្រប់គ្រង API Keys
                {% elif page == 'settings' %}⚙️ ការកំណត់ប្រព័ន្ធ
                {% else %}📊 ផ្ទាំងគ្រប់គ្រង{% endif %}
            </h2>
            <div class="flex items-center gap-3">
                <span class="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
                <span class="text-xs font-bold text-emerald-600">System Live</span>
            </div>
        </header>

        <div class="p-8 max-w-7xl mx-auto">
            
            {% if page == 'users' %}
            <!-- Create User -->
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
                <h3 class="font-bold text-slate-700 mb-4 flex items-center gap-2"><i class="fas fa-user-plus text-primary"></i> បង្កើតគណនីថ្មី</h3>
                <form action="/add_user" method="POST" class="grid grid-cols-1 md:grid-cols-6 gap-4 items-end">
                    <div class="col-span-1"><label class="text-xs font-bold text-slate-500">Username</label><input type="text" name="username" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg focus:ring-2 focus:ring-primary outline-none" required></div>
                    <div class="col-span-1"><label class="text-xs font-bold text-slate-500">Credits</label><input type="number" name="credits" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg focus:ring-2 focus:ring-primary outline-none" value="100" required></div>
                    <div class="col-span-1"><label class="text-xs font-bold text-slate-500">Plan</label>
                        <select name="plan" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg focus:ring-2 focus:ring-primary outline-none">
                            <option value="Mini">Mini</option><option value="Basic">Basic</option><option value="Standard">Standard</option><option value="Premium" selected>Premium</option>
                        </select>
                    </div>
                    <div class="col-span-1"><label class="text-xs font-bold text-slate-500">Expiry Date</label><input type="date" name="expiry" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg focus:ring-2 focus:ring-primary outline-none" required></div>
                    <div class="col-span-1"><label class="text-xs font-bold text-slate-500">API Key (Optional)</label>
                        <select name="assigned_key" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg focus:ring-2 focus:ring-primary outline-none">
                            <option value="">Auto (Pool)</option>
                            {% for k in api_keys %}<option value="{{ k[0] }}">{{ k[1] }}</option>{% endfor %}
                        </select>
                    </div>
                    <div class="col-span-1"><button class="w-full bg-primary hover:bg-indigo-600 text-white font-bold py-2 rounded-lg shadow-lg shadow-indigo-500/30 transition">Create</button></div>
                </form>
            </div>

            <!-- Users Table -->
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-slate-50 text-slate-500 text-xs uppercase border-b">
                            <tr>
                                <th class="px-6 py-4">User Info</th>
                                <th class="px-6 py-4">Status & Activity</th>
                                <th class="px-6 py-4">Credits & Plan</th>
                                <th class="px-6 py-4">Limits (Custom)</th>
                                <th class="px-6 py-4 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            {% for user in users %}
                            <tr class="hover:bg-slate-50 group transition">
                                <td class="px-6 py-4">
                                    <div class="font-bold text-slate-700 text-base">{{ user.username }}</div>
                                    <div class="flex items-center gap-2 mt-1">
                                        <code class="text-xs bg-slate-100 px-2 py-1 rounded border font-mono text-slate-500 select-all" id="key-{{loop.index}}">{{ user.api_key }}</code>
                                        <button onclick="navigator.clipboard.writeText(document.getElementById('key-{{loop.index}}').innerText); alert('Copied!');" class="text-slate-400 hover:text-primary"><i class="fas fa-copy"></i></button>
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="mb-2">
                                        {% if user.is_active == 1 %}<span class="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-600 text-xs font-bold">Active</span>
                                        {% elif user.is_active == 2 %}<span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-600 text-xs font-bold">Suspended</span>
                                        {% else %}<span class="px-2 py-0.5 rounded-full bg-red-100 text-red-600 text-xs font-bold">Banned</span>{% endif %}
                                    </div>
                                    <div class="text-xs text-slate-500">
                                        Last seen: {{ user.last_seen if user.last_seen else 'Never' }}<br>
                                        Today: {{ user.session_minutes }} mins | Success: {{ user.stats.success }} | Fail: {{ user.stats.fail }}
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                    <form action="/update_credits" method="POST" class="flex items-center gap-2 mb-2">
                                        <input type="hidden" name="username" value="{{ user.username }}">
                                        <span class="font-bold text-lg {{ 'text-emerald-500' if user.credits > 0 else 'text-red-500' }}">{{ user.credits }}</span>
                                        <input type="number" name="amount" placeholder="+/-" class="w-16 px-1 py-0.5 text-xs border rounded bg-white opacity-0 group-hover:opacity-100 transition">
                                    </form>
                                    <span class="px-2 py-0.5 rounded border text-xs font-bold 
                                        {% if user.plan == 'Premium' %}bg-purple-100 text-purple-600 border-purple-200
                                        {% elif user.plan == 'Standard' %}bg-blue-100 text-blue-600 border-blue-200
                                        {% else %}bg-slate-100 text-slate-600 border-slate-200{% endif %}">{{ user.plan }}</span>
                                </td>
                                <td class="px-6 py-4">
                                    <form action="/update_user_config" method="POST" class="space-y-1">
                                        <input type="hidden" name="username" value="{{ user.username }}">
                                        <div class="flex items-center gap-2">
                                            <span class="text-xs text-slate-400 w-12">Limit:</span>
                                            <input type="number" name="custom_limit" value="{{ user.custom_limit or '' }}" placeholder="Default" class="w-16 px-1 py-0.5 text-xs border rounded bg-white">
                                        </div>
                                        <div class="flex items-center gap-2">
                                            <span class="text-xs text-slate-400 w-12">Cost V2:</span>
                                            <input type="number" name="custom_cost_2" value="{{ user.custom_cost_2 or '' }}" placeholder="Default" class="w-16 px-1 py-0.5 text-xs border rounded bg-white">
                                        </div>
                                        <button class="text-xs text-primary underline opacity-0 group-hover:opacity-100">Save</button>
                                    </form>
                                </td>
                                <td class="px-6 py-4 text-right space-x-1">
                                    <div class="flex justify-end gap-1">
                                        <a href="/toggle_status/{{ user.username }}/1" title="Activate" class="p-1.5 rounded bg-emerald-50 text-emerald-500 hover:bg-emerald-100"><i class="fas fa-check"></i></a>
                                        <a href="/toggle_status/{{ user.username }}/2" title="Suspend" class="p-1.5 rounded bg-amber-50 text-amber-500 hover:bg-amber-100"><i class="fas fa-pause"></i></a>
                                        <a href="/toggle_status/{{ user.username }}/0" title="Ban" class="p-1.5 rounded bg-red-50 text-red-500 hover:bg-red-100"><i class="fas fa-ban"></i></a>
                                        <a href="/delete_user/{{ user.username }}" onclick="return confirm('Delete?')" title="Delete" class="p-1.5 rounded bg-slate-100 text-slate-500 hover:bg-red-500 hover:text-white"><i class="fas fa-trash"></i></a>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            {% elif page == 'api_keys' %}
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div class="md:col-span-2">
                    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                        <h3 class="font-bold text-slate-700 mb-4">🔑 API Keys Pool (Multi-Key)</h3>
                        <div class="overflow-x-auto">
                            <table class="w-full text-sm text-left">
                                <thead class="bg-slate-50 text-slate-500 text-xs uppercase"><tr><th class="px-4 py-3">Label</th><th class="px-4 py-3">Key</th><th class="px-4 py-3">Status</th><th class="px-4 py-3">Errors</th><th class="px-4 py-3 text-right">Action</th></tr></thead>
                                <tbody class="divide-y divide-slate-100">
                                    {% for k in api_keys %}
                                    <tr>
                                        <td class="px-4 py-3 font-bold">{{ k[1] }}</td>
                                        <td class="px-4 py-3 font-mono text-xs text-slate-500">{{ k[0][:15] }}...</td>
                                        <td class="px-4 py-3">{% if k[2] %}<span class="text-emerald-500 text-xs font-bold">Active</span>{% else %}<span class="text-red-500 text-xs font-bold">Inactive</span>{% endif %}</td>
                                        <td class="px-4 py-3 text-slate-400">{{ k[3] }}</td>
                                        <td class="px-4 py-3 text-right"><a href="/delete_key/{{ k[0] }}" class="text-red-400 hover:text-red-600"><i class="fas fa-trash"></i></a></td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
                <div>
                    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                        <h3 class="font-bold text-slate-700 mb-4">Add New Key</h3>
                        <form action="/add_api_key" method="POST" class="space-y-3">
                            <div><label class="text-xs font-bold text-slate-500">Label (Name)</label><input type="text" name="label" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" placeholder="Account 1" required></div>
                            <div><label class="text-xs font-bold text-slate-500">Sora API Key</label><input type="text" name="key_value" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" required></div>
                            <button class="w-full bg-emerald-500 hover:bg-emerald-600 text-white font-bold py-2 rounded-lg shadow-lg shadow-emerald-500/30">Add Key</button>
                        </form>
                    </div>
                </div>
            </div>

            {% elif page == 'vouchers' %}
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
                <h3 class="font-bold text-slate-700 mb-4"><i class="fas fa-magic text-primary"></i> បង្កើតប័ណ្ណបញ្ចូលលុយ (Advanced Vouchers)</h3>
                <form action="/generate_vouchers" method="POST" class="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
                    <div><label class="text-xs font-bold text-slate-500">Credits Amount</label><input type="number" name="amount" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" required></div>
                    <div><label class="text-xs font-bold text-slate-500">Quantity (Cards)</label><input type="number" name="count" value="1" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" required></div>
                    <div><label class="text-xs font-bold text-slate-500">Max Uses (Users)</label><input type="number" name="max_uses" value="1" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" title="How many people can use this code"></div>
                    <div><label class="text-xs font-bold text-slate-500">Expiry Date</label><input type="date" name="expiry" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg"></div>
                    <button class="bg-primary hover:bg-indigo-600 text-white font-bold py-2 px-4 rounded-lg shadow-lg">Generate</button>
                </form>
            </div>
            
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <table class="w-full text-sm text-left">
                    <thead class="bg-slate-50 text-slate-500 text-xs uppercase"><tr><th class="px-6 py-3">Code</th><th class="px-6 py-3">Value</th><th class="px-6 py-3">Usage</th><th class="px-6 py-3">Expiry</th><th class="px-6 py-3">Action</th></tr></thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for v in vouchers %}
                        <tr>
                            <td class="px-6 py-3 font-mono font-bold select-all">{{ v[0] }}</td>
                            <td class="px-6 py-3 text-emerald-600 font-bold">+{{ v[1] }}</td>
                            <td class="px-6 py-3">
                                <div class="w-full bg-slate-100 rounded-full h-2.5 mb-1"><div class="bg-blue-600 h-2.5 rounded-full" style="width: {{ (v[3]/v[2])*100 }}%"></div></div>
                                <div class="text-xs text-slate-400">{{ v[3] }} / {{ v[2] }} used</div>
                            </td>
                            <td class="px-6 py-3 text-xs">{{ v[4] if v[4] else 'Never' }}</td>
                            <td class="px-6 py-3"><a href="/delete_voucher/{{ v[0] }}" class="text-red-400 hover:text-red-600"><i class="fas fa-trash"></i></a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            {% elif page == 'settings' %}
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Update System -->
                <div class="bg-gradient-to-br from-indigo-600 to-purple-700 rounded-xl p-6 text-white shadow-xl md:col-span-2">
                    <h4 class="font-bold text-lg mb-4 flex items-center gap-2"><i class="fas fa-cloud-upload-alt"></i> ប្រព័ន្ធអាប់ដេត (ZIP/URL Update)</h4>
                    <form action="/update_settings" method="POST" class="space-y-4">
                        <div class="flex items-center justify-between bg-white/10 p-4 rounded-lg border border-white/20">
                            <div><h5 class="font-bold">Enable Update Push</h5><p class="text-xs opacity-70">Client will auto-download and extract ZIP.</p></div>
                            <label class="switch"><input type="checkbox" name="update_is_live" {% if update_is_live == '1' %}checked{% endif %}><span class="slider"></span></label>
                        </div>
                        <div class="grid grid-cols-2 gap-4">
                            <div><label class="text-xs opacity-70 block mb-1">Latest Version</label><input type="text" name="latest_version" value="{{ latest_version }}" class="w-full bg-white/20 border border-white/30 rounded px-3 py-2 backdrop-blur outline-none"></div>
                            <div><label class="text-xs opacity-70 block mb-1">ZIP Download URL</label><input type="text" name="update_url" value="{{ update_url }}" class="w-full bg-white/20 border border-white/30 rounded px-3 py-2 backdrop-blur outline-none" placeholder="https://mysite.com/update.zip"></div>
                        </div>
                        <div><label class="text-xs opacity-70 block mb-1">Description</label><textarea name="update_desc" class="w-full bg-white/20 border border-white/30 rounded px-3 py-2 backdrop-blur outline-none h-16">{{ update_desc }}</textarea></div>
                        <button class="bg-white text-indigo-700 font-bold px-6 py-2 rounded shadow hover:bg-indigo-50 w-full">Save Update Config</button>
                    </form>
                </div>

                <!-- Costs & Limits -->
                <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                    <h4 class="font-bold text-slate-700 mb-4 pb-2 border-b">Global Limits (Concurrency)</h4>
                    <div class="grid grid-cols-2 gap-4">
                        <div><label class="text-xs font-bold text-slate-400">Mini</label><input type="number" name="limit_mini" value="{{ limits.mini }}" class="w-full mt-1 border rounded p-2"></div>
                        <div><label class="text-xs font-bold text-slate-400">Basic</label><input type="number" name="limit_basic" value="{{ limits.basic }}" class="w-full mt-1 border rounded p-2"></div>
                        <div><label class="text-xs font-bold text-slate-400">Standard</label><input type="number" name="limit_standard" value="{{ limits.standard }}" class="w-full mt-1 border rounded p-2"></div>
                        <div><label class="text-xs font-bold text-purple-500">Premium</label><input type="number" name="limit_premium" value="{{ limits.premium }}" class="w-full mt-1 border rounded p-2"></div>
                    </div>
                </div>

                <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                    <h4 class="font-bold text-slate-700 mb-4 pb-2 border-b">Global Costs (Credits)</h4>
                    <div class="space-y-3">
                        <div><label class="text-xs font-bold text-slate-400">Sora-2</label><input type="number" name="cost_sora_2" value="{{ costs.sora_2 }}" class="w-full mt-1 border rounded p-2"></div>
                        <div><label class="text-xs font-bold text-slate-400">Sora-2 Pro</label><input type="number" name="cost_sora_2_pro" value="{{ costs.sora_2_pro }}" class="w-full mt-1 border rounded p-2"></div>
                    </div>
                </div>
            </div>
            {% endif %}

        </div>
    </main>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Login</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-100 h-screen flex items-center justify-center">
    <div class="bg-white p-8 rounded-xl shadow-xl w-96 border border-slate-200">
        <h2 class="text-2xl font-bold text-slate-800 mb-6 text-center">Admin Access</h2>
        <form method="POST" class="space-y-4">
            <input type="password" name="password" placeholder="Password" class="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 outline-none" required>
            <button class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 rounded-lg">Login</button>
        </form>
    </div>
</body></html>
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
def home(): return jsonify({"status": "Server Running", "secure": True}), 200

@app.route(f'/{ADMIN_LOGIN_PATH}', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/dashboard')
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout(): session.pop('logged_in', None); return redirect(f'/{ADMIN_LOGIN_PATH}')

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db(); c = conn.cursor()
    
    # Fetch API Keys for dropdown
    keys = conn.execute("SELECT key_value, label FROM api_keys WHERE is_active=1").fetchall()
    
    # Fetch Users with details
    c.execute("SELECT * FROM users ORDER BY created_at DESC")
    raw_users = c.fetchall()
    
    users = []
    for r in raw_users:
        stats = json.loads(r[13]) if r[13] else {"success": 0, "fail": 0}
        users.append({
            "username": r[0], "api_key": r[1], "credits": r[2], "expiry": r[3],
            "is_active": r[4], "plan": r[6], 
            "custom_limit": r[7], "custom_cost_2": r[8], "custom_cost_pro": r[9],
            "last_seen": r[11], "session_minutes": r[12], "stats": stats
        })
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='users', users=users, api_keys=keys)

@app.route('/api_keys')
@login_required
def view_keys():
    conn = get_db()
    keys = conn.execute("SELECT * FROM api_keys").fetchall()
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='api_keys', api_keys=keys)

@app.route('/vouchers')
@login_required
def vouchers():
    conn = get_db()
    v = conn.execute("SELECT * FROM vouchers ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='vouchers', vouchers=v)

@app.route('/settings')
@login_required
def settings():
    latest_ver = get_setting('latest_version', '1.0.0')
    update_desc = get_setting('update_desc', 'Initial Release')
    update_is_live = get_setting('update_is_live', '0')
    update_url = get_setting('update_url', '')
    
    costs = {'sora_2': get_setting('cost_sora_2', 25), 'sora_2_pro': get_setting('cost_sora_2_pro', 35)}
    limits = {
        'mini': get_setting('limit_mini', 1), 'basic': get_setting('limit_basic', 2), 
        'standard': get_setting('limit_standard', 3), 'premium': get_setting('limit_premium', 5)
    }
    
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', costs=costs, limits=limits, 
                                  latest_version=latest_ver, update_desc=update_desc,
                                  update_is_live=update_is_live, update_url=update_url)

# --- ACTION ROUTES ---

@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    try:
        assigned_key = request.form.get('assigned_key') or None
        conn = get_db()
        conn.execute("INSERT INTO users (username, api_key, credits, expiry_date, is_active, created_at, plan, assigned_api_key) VALUES (?, ?, ?, ?, 1, ?, ?, ?)", 
                     (request.form['username'], "SK-"+str(uuid.uuid4())[:12].upper(), int(request.form['credits']), request.form['expiry'], datetime.now().strftime("%Y-%m-%d"), request.form['plan'], assigned_key))
        conn.commit(); conn.close()
    except Exception as e: print(e)
    return redirect('/dashboard')

@app.route('/add_api_key', methods=['POST'])
@login_required
def add_api_key():
    try:
        conn = get_db()
        conn.execute("INSERT INTO api_keys (key_value, label) VALUES (?, ?)", (request.form['key_value'], request.form['label']))
        conn.commit(); conn.close()
    except: pass
    return redirect('/api_keys')

@app.route('/delete_key/<path:k>')
@login_required
def delete_key(k):
    conn = get_db(); conn.execute("DELETE FROM api_keys WHERE key_value=?", (k,)); conn.commit(); conn.close()
    return redirect('/api_keys')

@app.route('/update_user_config', methods=['POST'])
@login_required
def update_user_config():
    u = request.form['username']
    cl = request.form.get('custom_limit') or None
    c2 = request.form.get('custom_cost_2') or None
    cp = request.form.get('custom_cost_pro') or None
    conn = get_db()
    conn.execute("UPDATE users SET custom_limit=?, custom_cost_2=?, custom_cost_pro=? WHERE username=?", (cl, c2, cp, u))
    conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/toggle_status/<username>/<int:status>')
@login_required
def toggle_status(username, status):
    conn = get_db()
    conn.execute("UPDATE users SET is_active = ? WHERE username=?", (status, username))
    conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/delete_user/<username>')
@login_required
def delete_user(username):
    conn = get_db(); conn.execute("DELETE FROM users WHERE username=?", (username,)); conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/update_credits', methods=['POST'])
@login_required
def update_credits():
    conn = get_db()
    conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", (int(request.form['amount']), request.form['username']))
    conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/generate_vouchers', methods=['POST'])
@login_required
def generate_vouchers():
    amt = int(request.form['amount']); qty = int(request.form['count'])
    max_uses = int(request.form.get('max_uses', 1))
    expiry = request.form.get('expiry') or None
    conn = get_db()
    for _ in range(qty):
        conn.execute("INSERT INTO vouchers (code, amount, max_uses, expiry_date, created_at) VALUES (?, ?, ?, ?, ?)", 
                     (generate_voucher_code(amt), amt, max_uses, expiry, str(datetime.now())))
    conn.commit(); conn.close()
    return redirect('/vouchers')

@app.route('/delete_voucher/<code>')
@login_required
def delete_voucher(code):
    conn = get_db(); conn.execute("DELETE FROM vouchers WHERE code=?", (code,)); conn.commit(); conn.close()
    return redirect('/vouchers')

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    form = request.form
    if 'latest_version' in form: set_setting('latest_version', form['latest_version'])
    if 'update_desc' in form: set_setting('update_desc', form['update_desc'])
    if 'update_url' in form: set_setting('update_url', form['update_url'])
    set_setting('update_is_live', '1' if form.get('update_is_live') else '0')
    
    # Generic loop for costs/limits settings if they exist in form
    for k in form:
        if k.startswith('cost_') or k.startswith('limit_'):
            set_setting(k, form[k])
            
    return redirect('/settings')

# --- CLIENT API ROUTES ---

@app.route('/api/verify', methods=['POST'])
def verify_user():
    d = request.json
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT credits, expiry_date, is_active, plan, custom_limit FROM users WHERE username=? AND api_key=?", (d.get('username'), d.get('api_key')))
    u = c.fetchone()
    
    if not u: conn.close(); return jsonify({"valid": False, "message": "Invalid Credentials"})
    if u[2] == 0: conn.close(); return jsonify({"valid": False, "message": "Account Banned"})
    if u[2] == 2: conn.close(); return jsonify({"valid": False, "message": "Account Suspended"})
    if datetime.now() > datetime.strptime(u[1], "%Y-%m-%d"): conn.close(); return jsonify({"valid": False, "message": "Expired"})
    
    # Update Last Seen
    conn.execute("UPDATE users SET last_seen = ? WHERE username=?", (str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")), d.get('username')))
    conn.commit()

    # Determine limit
    limit = u[4] # Custom limit
    if not limit:
        plan = u[3].lower()
        limit = int(get_setting(f"limit_{plan}", 3))
    
    update_info = {
        "latest_version": get_setting('latest_version', '1.0.0'),
        "update_desc": get_setting('update_desc', ''),
        "update_is_live": get_setting('update_is_live', '0') == '1',
        "download_url": get_setting('update_url', '')
    }
    
    return jsonify({
        "valid": True, "credits": u[0], "expiry": u[1], "plan": u[3], "concurrency_limit": limit,
        "broadcast": get_setting('broadcast_msg', ''), "broadcast_color": get_setting('broadcast_color', '#FF0000'),
        **update_info
    })

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    d = request.json
    u = d.get('username')
    k = d.get('api_key')
    if u and k:
        conn = get_db()
        # Increment session minutes, check if today is new
        conn.execute("UPDATE users SET session_minutes = session_minutes + 1 WHERE username=? AND api_key=?", (u, k))
        conn.commit(); conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/redeem', methods=['POST'])
def redeem():
    d = request.json
    code = d.get('code'); username = d.get('username')
    conn = get_db(); c = conn.cursor()
    
    v = c.execute("SELECT amount, max_uses, current_uses, expiry_date FROM vouchers WHERE code=?", (code,)).fetchone()
    
    if not v: conn.close(); return jsonify({"success": False, "message": "Invalid Code"})
    if v[2] >= v[1]: conn.close(); return jsonify({"success": False, "message": "Code Fully Used"})
    if v[3] and datetime.now() > datetime.strptime(v[3], "%Y-%m-%d"): conn.close(); return jsonify({"success": False, "message": "Code Expired"})
    
    # Check if user already used this specific code
    used = c.execute("SELECT 1 FROM voucher_usage WHERE code=? AND username=?", (code, username)).fetchone()
    if used: conn.close(); return jsonify({"success": False, "message": "Already Redeemed"})
    
    c.execute("UPDATE users SET credits=credits+? WHERE username=?", (v[0], username))
    c.execute("UPDATE vouchers SET current_uses=current_uses+1 WHERE code=?", (code,))
    c.execute("INSERT INTO voucher_usage (code, username, used_at) VALUES (?, ?, ?)", (code, username, str(datetime.now())))
    conn.commit(); conn.close()
    
    return jsonify({"success": True, "message": f"Added {v[0]} Credits"})

@app.route('/api/proxy/generate', methods=['POST'])
def proxy_gen():
    auth = request.headers.get("Client-Auth", ""); 
    if ":" not in auth: return jsonify({"code":-1}), 401
    u_name, u_key = auth.split(":")
    
    conn = get_db()
    user = conn.execute("SELECT credits, is_active, custom_cost_2, custom_cost_pro FROM users WHERE username=? AND api_key=?", (u_name, u_key)).fetchone()
    
    if not user: conn.close(); return jsonify({"code":-1}), 401
    if user[1] != 1: conn.close(); return jsonify({"code":-1, "message": "Account Invalid"}), 403
    
    model = request.json.get('model', '')
    is_pro = "pro" in model
    
    # Determine Cost
    cost = 0
    if is_pro: cost = user[3] if user[3] else int(get_setting('cost_sora_2_pro', 35))
    else: cost = user[2] if user[2] else int(get_setting('cost_sora_2', 25))
    
    if user[0] < cost: conn.close(); return jsonify({"code":-1, "message": "Insufficient Credits"}), 402
    
    real_key = get_active_api_key(u_name)
    if not real_key: conn.close(); return jsonify({"code":-1, "message": "System Busy (No Keys)"}), 503
    
    try:
        r = requests.post("https://FreeSoraGenerator.com/api/v1/video/sora-video", json=request.json, headers={"Authorization": f"Bearer {real_key}"}, timeout=120)
        
        if r.json().get("code") == 0:
            tid = r.json().get('data', {}).get('taskId')
            if tid: 
                conn.execute("INSERT INTO tasks (task_id, username, cost, status, created_at, model) VALUES (?, ?, ?, ?, ?, ?)", 
                             (tid, u_name, cost, 'pending', str(datetime.now()), model))
            
            # Deduct Credits
            conn.execute("UPDATE users SET credits=credits-? WHERE username=?", (cost, u_name))
            
            # Log
            conn.execute("INSERT INTO logs (username, action, cost, timestamp) VALUES (?, ?, ?, ?)", (u_name, "generate", cost, str(datetime.now())))
            conn.commit()
            
            r_json = r.json()
            r_json['user_balance'] = user[0] - cost
            return jsonify(r_json), r.status_code
        return jsonify(r.json()), r.status_code
    except Exception as e: return jsonify({"code":-1, "message": str(e)}), 500
    finally: conn.close()

@app.route('/api/proxy/check-result', methods=['POST'])
def proxy_chk():
    try:
        # We need a key to check, just grab any active one for checking
        real_key = get_active_api_key()
        r = requests.post("https://FreeSoraGenerator.com/api/video-generations/check-result", json=request.json, headers={"Authorization": f"Bearer {real_key}"}, timeout=30)
        
        data = r.json()
        task_id = request.json.get('taskId')
        
        conn = get_db()
        task = conn.execute("SELECT username, cost, status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        
        if task:
            username = task[0]
            # Handle Refund on Failure
            if data.get('data', {}).get('status') == 'failed' and task[2] != 'refunded':
                conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", (task[1], username))
                conn.execute("UPDATE tasks SET status = 'refunded' WHERE task_id = ?", (task_id,))
                conn.execute("INSERT INTO logs (username, action, cost, timestamp, status) VALUES (?, ?, ?, ?, ?)", (username, f"Refund {task_id}", 0, str(datetime.now()), 'Refund'))
                
                # Update Stats (Fail)
                user_stats = conn.execute("SELECT daily_stats FROM users WHERE username=?", (username,)).fetchone()
                stats = json.loads(user_stats[0]) if user_stats[0] else {"success": 0, "fail": 0}
                stats['fail'] += 1
                conn.execute("UPDATE users SET daily_stats=? WHERE username=?", (json.dumps(stats), username))
                conn.commit()

            # Handle Success Stats
            elif data.get('data', {}).get('status') == 'succeeded' and task[2] != 'succeeded':
                conn.execute("UPDATE tasks SET status = 'succeeded' WHERE task_id = ?", (task_id,))
                user_stats = conn.execute("SELECT daily_stats FROM users WHERE username=?", (username,)).fetchone()
                stats = json.loads(user_stats[0]) if user_stats[0] else {"success": 0, "fail": 0}
                stats['success'] += 1
                conn.execute("UPDATE users SET daily_stats=? WHERE username=?", (json.dumps(stats), username))
                conn.commit()

        conn.close()
        return jsonify(data), r.status_code
    except: return jsonify({"code":-1}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
