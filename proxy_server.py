# --- START OF FILE admin_dashboard.py ---

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
app.secret_key = os.environ.get("FLASK_SECRET", "super_secret_admin_key_v6_fix")

# --- CONFIGURATION ---
DB_PATH = os.environ.get("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_LOGIN_PATH = os.environ.get("ADMIN_PATH", "secure_login")

# Security Config
MAX_SUSPICIOUS_ATTEMPTS = 5
suspicious_tracker = {} 

# --- DATABASE SETUP & AUTO-REPAIR ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Allow accessing columns by name
    return conn

def init_and_migrate_db():
    conn = get_db()
    c = conn.cursor()
    
    # 1. Create Base Tables if not exist
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers (code TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS voucher_usage (id INTEGER PRIMARY KEY AUTOINCREMENT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS banned_ips (ip TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys (key_value TEXT PRIMARY KEY)''')

    # 2. Define Schema Requirements (Table, Column, Type, Default)
    required_columns = [
        # Users
        ("users", "api_key", "TEXT"), ("users", "credits", "INTEGER"), ("users", "expiry_date", "TEXT"),
        ("users", "is_active", "INTEGER"), ("users", "created_at", "TEXT"), ("users", "plan", "TEXT DEFAULT 'Standard'"),
        ("users", "custom_limit", "INTEGER DEFAULT NULL"), ("users", "custom_cost_2", "INTEGER DEFAULT NULL"),
        ("users", "custom_cost_pro", "INTEGER DEFAULT NULL"), ("users", "assigned_api_key", "TEXT DEFAULT NULL"),
        ("users", "last_seen", "TEXT"), ("users", "session_minutes", "INTEGER DEFAULT 0"), ("users", "daily_stats", "TEXT DEFAULT '{}'"),
        
        # Logs - ADD task_id HERE
        ("logs", "username", "TEXT"), ("logs", "action", "TEXT"), ("logs", "cost", "INTEGER"), 
        ("logs", "timestamp", "TEXT"), ("logs", "status", "TEXT"), ("logs", "task_id", "TEXT"),
        
        # Vouchers
        ("vouchers", "amount", "INTEGER"), ("vouchers", "max_uses", "INTEGER DEFAULT 1"), 
        ("vouchers", "current_uses", "INTEGER DEFAULT 0"), ("vouchers", "expiry_date", "TEXT"), ("vouchers", "created_at", "TEXT"),
        
        # Voucher Usage
        ("voucher_usage", "code", "TEXT"), ("voucher_usage", "username", "TEXT"), ("voucher_usage", "used_at", "TEXT"),
        
        # Tasks
        ("tasks", "username", "TEXT"), ("tasks", "cost", "INTEGER"), ("tasks", "status", "TEXT"), 
        ("tasks", "created_at", "TEXT"), ("tasks", "model", "TEXT"),
        
        # Banned IPs
        ("banned_ips", "reason", "TEXT"), ("banned_ips", "banned_at", "TEXT"),
        
        # API Keys
        ("api_keys", "label", "TEXT"), ("api_keys", "is_active", "INTEGER DEFAULT 1"), ("api_keys", "error_count", "INTEGER DEFAULT 0")
    ]

    # 3. Check and Add Missing Columns (Safe Migration)
    for table, col, dtype in required_columns:
        try:
            # Check if column exists
            c.execute(f"SELECT {col} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            try:
                print(f"Migrating: Adding {col} to {table}...")
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            except Exception as e:
                print(f"Migration failed for {table}.{col}: {e}")

    # 4. Insert Default Settings
    defaults = {
        'cost_sora_2': '25', 'cost_sora_2_pro': '35',
        'limit_mini': '1', 'limit_basic': '2', 'limit_standard': '3', 'limit_premium': '5',
        'broadcast_msg': '', 'broadcast_color': '#FF0000',
        'latest_version': '1.0.0', 'update_desc': 'Initial Release',
        'update_is_live': '0', 'update_url': ''
    }
    for k, v in defaults.items():
        try: 
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        except: 
            pass

    conn.commit()
    conn.close()

# Run Auto-Repair on Start
init_and_migrate_db()

# --- HELPER FUNCTIONS ---
def get_setting(key, default=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def generate_voucher_code(amount):
    chars = string.ascii_uppercase + string.digits
    return f"SORA-{amount}-{''.join(random.choices(chars, k=8))}"

def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

def get_active_api_key(username=None):
    conn = get_db()
    if username:
        user = conn.execute("SELECT assigned_api_key FROM users WHERE username=?", (username,)).fetchone()
        if user and user['assigned_api_key']:
            conn.close()
            return user['assigned_api_key']
    keys = conn.execute("SELECT key_value FROM api_keys WHERE is_active=1 ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    return keys['key_value'] if keys else None

# --- SECURITY ---
@app.before_request
def security_guard():
    ip = get_client_ip()
    conn = get_db()
    is_banned = conn.execute("SELECT 1 FROM banned_ips WHERE ip=?", (ip,)).fetchone()
    conn.close()
    if is_banned: 
        return jsonify({"code": 403, "message": "Access Denied: IP Banned."}), 403
    
    if 'logged_in' in session: 
        return 
    
    valid_starts = ['/api/', '/static/']
    if request.path == f'/{ADMIN_LOGIN_PATH}' or any(request.path.startswith(p) for p in valid_starts) or request.path == '/': 
        return 
    
    current_count = suspicious_tracker.get(ip, 0) + 1
    suspicious_tracker[ip] = current_count
    
    if current_count >= MAX_SUSPICIOUS_ATTEMPTS:
        try:
            conn = get_db()
            conn.execute("INSERT OR IGNORE INTO banned_ips (ip, reason, banned_at) VALUES (?, ?, ?)", 
                        (ip, f"Excessive scanning: {request.path}", str(datetime.now())))
            conn.commit()
            conn.close()
        except: 
            pass
        return jsonify({"code": 403, "message": "Access Denied"}), 403
    
    return "Not Found", 404

# --- DASHBOARD HTML ---
MODERN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="km">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sora Admin Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = { theme: { extend: { fontFamily: { sans: ['"Kantumruy Pro"', 'sans-serif'] }, colors: { primary: '#6366f1', dark: '#0f172a' } } } }
    </script>
    <style>
        .sidebar-link.active { background-color: #6366f1; color: white; }
        .modal { transition: opacity 0.25s ease; }
        body.modal-active { overflow: hidden; }
        .switch { position: relative; display: inline-block; width: 40px; height: 20px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #cbd5e1; transition: .4s; border-radius: 20px; }
        .slider:before { position: absolute; content: ""; height: 16px; width: 16px; left: 2px; bottom: 2px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #10b981; }
        input:checked + .slider:before { transform: translateX(20px); }
        
        /* Toast Notification */
        #toast-container { position: fixed; bottom: 20px; right: 20px; z-index: 100; transform: translateY(100px); opacity: 0; transition: all 0.5s ease; }
        #toast-container.show { transform: translateY(0); opacity: 1; }
        
        /* Mobile sidebar styles */
        @media (max-width: 767px) {
            #sidebarOverlay {
                transition: opacity 0.3s ease;
            }
        }
        
        /* Refund status styling */
        .refund-status { color: #10b981; font-weight: bold; background-color: #d1fae5; padding: 2px 6px; border-radius: 4px; }
    </style>
</head>
<body class="flex h-screen bg-slate-50 text-slate-800 font-sans overflow-hidden">

    <!-- Toast Notification -->
    <div id="toast-container" class="bg-slate-900 text-white px-6 py-4 rounded-xl shadow-2xl flex items-center gap-4 border border-slate-700 min-w-[300px]">
        <div class="bg-emerald-500 rounded-full p-1"><i class="fas fa-check text-white text-xs"></i></div>
        <div>
            <h4 class="font-bold text-sm">ជោគជ័យ (Success)</h4>
            <p class="text-xs text-slate-400" id="toast-message">ប្រតិបត្តិការបានជោគជ័យ!</p>
        </div>
    </div>

    <!-- Sidebar -->
    <aside id="sidebar" class="w-64 bg-white border-r border-slate-200 flex flex-col z-30 shadow-xl fixed md:relative h-full -translate-x-full md:translate-x-0 transition-transform duration-300">
        <div class="h-16 flex items-center px-6 border-b border-slate-100 justify-between">
            <div class="flex items-center">
                <i class="fas fa-cube text-primary text-2xl mr-3"></i>
                <span class="text-xl font-bold text-slate-800">SoraAdmin</span>
            </div>
            <!-- Close button for mobile -->
            <button id="closeSidebar" class="md:hidden text-slate-500 hover:text-red-500">
                <i class="fas fa-times text-lg"></i>
            </button>
        </div>
        <nav class="flex-1 overflow-y-auto py-6 px-3 space-y-1">
            <a href="/dashboard" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'users' else '' }}"><i class="fas fa-users w-8 text-center"></i> <span class="font-medium">អ្នកប្រើប្រាស់</span></a>
            <a href="/vouchers" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'vouchers' else '' }}"><i class="fas fa-ticket-alt w-8 text-center"></i> <span class="font-medium">ប័ណ្ណបញ្ចូនលុយ</span></a>
            <a href="/api_keys" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'api_keys' else '' }}"><i class="fas fa-key w-8 text-center"></i> <span class="font-medium">API Keys</span></a>
            <a href="/logs" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'logs' else '' }}"><i class="fas fa-list-alt w-8 text-center"></i> <span class="font-medium">កំណត់ត្រា</span></a>
            <a href="/settings" class="sidebar-link flex items-center px-3 py-2.5 text-slate-600 rounded-lg hover:bg-slate-50 transition {{ 'active' if page == 'settings' else '' }}"><i class="fas fa-cogs w-8 text-center"></i> <span class="font-medium">ការកំណត់</span></a>
        </nav>
        <div class="p-4 border-t border-slate-100">
            <a href="/logout" class="flex items-center justify-center w-full px-4 py-2 bg-red-50 text-red-600 rounded-lg font-bold hover:bg-red-100 transition"><i class="fas fa-sign-out-alt mr-2"></i> ចាកចេញ</a>
        </div>
    </aside>

    <!-- Mobile overlay -->
    <div id="sidebarOverlay" class="fixed inset-0 bg-black/50 z-20 md:hidden hidden"></div>

    <!-- Main Content -->
    <main class="flex-1 overflow-y-auto relative bg-slate-50">
        <header class="bg-white/80 backdrop-blur-md sticky top-0 z-10 border-b border-slate-200 px-4 md:px-8 py-4 flex justify-between items-center">
            <!-- Hamburger button for mobile -->
            <button id="mobileMenuButton" class="md:hidden text-slate-600 hover:text-primary focus:outline-none p-2 rounded-lg hover:bg-slate-100 transition">
                <i class="fas fa-bars text-lg"></i>
            </button>
            
            <h2 class="text-lg md:text-xl font-bold text-slate-800 ml-2 md:ml-0">
                {% if page == 'users' %}👥 គ្រប់គ្រងអ្នកប្រើប្រាស់ (User Management)
                {% elif page == 'vouchers' %}🎫 ប័ណ្ណបញ្ចូនលុយ (Vouchers)
                {% elif page == 'api_keys' %}🔑 គ្រប់គ្រង API Keys
                {% elif page == 'logs' %}📜 កំណត់ត្រាសកម្មភាព
                {% else %}⚙️ ការកំណត់ប្រព័ន្ធ{% endif %}
            </h2>
            <div class="flex items-center gap-3"><span class="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span><span class="text-xs font-bold text-emerald-600">System Live</span></div>
        </header>

        <div class="p-4 md:p-8 max-w-7xl mx-auto">
            {% if page == 'users' %}
            
            <!-- Plan Stats Cards (NEW) -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                <div class="bg-white p-4 rounded-xl shadow-sm border border-l-4 border-purple-500 hover:shadow-md transition">
                    <p class="text-xs text-slate-400 font-bold uppercase mb-1">Premium Users</p>
                    <h3 class="text-2xl font-bold text-slate-800">{{ stats.Premium }} <span class="text-xs font-normal text-slate-400">users</span></h3>
                </div>
                <div class="bg-white p-4 rounded-xl shadow-sm border border-l-4 border-blue-500 hover:shadow-md transition">
                    <p class="text-xs text-slate-400 font-bold uppercase mb-1">Standard Users</p>
                    <h3 class="text-2xl font-bold text-slate-800">{{ stats.Standard }} <span class="text-xs font-normal text-slate-400">users</span></h3>
                </div>
                <div class="bg-white p-4 rounded-xl shadow-sm border border-l-4 border-emerald-500 hover:shadow-md transition">
                    <p class="text-xs text-slate-400 font-bold uppercase mb-1">Basic Users</p>
                    <h3 class="text-2xl font-bold text-slate-800">{{ stats.Basic }} <span class="text-xs font-normal text-slate-400">users</span></h3>
                </div>
                <div class="bg-white p-4 rounded-xl shadow-sm border border-l-4 border-slate-400 hover:shadow-md transition">
                    <p class="text-xs text-slate-400 font-bold uppercase mb-1">Mini Users</p>
                    <h3 class="text-2xl font-bold text-slate-800">{{ stats.Mini }} <span class="text-xs font-normal text-slate-400">users</span></h3>
                </div>
            </div>

            <!-- Add User Form -->
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4 md:p-6 mb-8">
                <h3 class="font-bold text-slate-700 mb-4 flex items-center gap-2"><i class="fas fa-user-plus text-primary"></i> បង្កើតគណនីថ្មី</h3>
                <form action="/add_user" method="POST" class="grid grid-cols-1 md:grid-cols-6 gap-4 items-end">
                    <div class="col-span-1 md:col-span-1"><label class="text-xs font-bold text-slate-500">Username</label><input type="text" name="username" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" required></div>
                    <div class="col-span-1 md:col-span-1"><label class="text-xs font-bold text-slate-500">Credits</label><input type="number" name="credits" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" value="100" required></div>
                    <div class="col-span-1 md:col-span-1"><label class="text-xs font-bold text-slate-500">Plan</label>
                        <select name="plan" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg">
                            <option value="Mini">Mini</option><option value="Basic">Basic</option><option value="Standard">Standard</option><option value="Premium" selected>Premium</option>
                        </select>
                    </div>
                    <div class="col-span-1 md:col-span-1"><label class="text-xs font-bold text-slate-500">Expiry</label><input type="date" name="expiry" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" required></div>
                    <div class="col-span-1 md:col-span-1"><label class="text-xs font-bold text-slate-500">API Key Assign</label>
                        <select name="assigned_key" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg">
                            <option value="">Auto (Pool)</option>
                            {% for k in api_keys %}<option value="{{ k.key_value }}">{{ k.label }}</option>{% endfor %}
                        </select>
                    </div>
                    <div class="col-span-1 md:col-span-1"><button class="w-full bg-primary hover:bg-indigo-600 text-white font-bold py-2 rounded-lg shadow-lg">Create</button></div>
                </form>
            </div>

            <!-- Users Table -->
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-slate-50 text-slate-500 text-xs uppercase border-b"><tr><th class="px-4 md:px-6 py-4">User Info</th><th class="px-4 md:px-6 py-4">Status & Activity</th><th class="px-4 md:px-6 py-4">Plan & Credits</th><th class="px-4 md:px-6 py-4 text-right">Actions</th></tr></thead>
                        <tbody class="divide-y divide-slate-100">
                            {% for user in users %}
                            <tr class="hover:bg-slate-50 group transition cursor-pointer" onclick="openUserModal({{ user | tojson | forceescape }})">
                                <td class="px-4 md:px-6 py-4">
                                    <div class="font-bold text-slate-700 text-base flex items-center gap-2">
                                        {{ user.username }} 
                                        <button onclick="event.stopPropagation(); copyUserInfo('{{user.username}}', '{{user.api_key}}', '{{user.plan}}', '{{user.credits}}', '{{user.expiry_date}}')" class="text-slate-400 hover:text-primary p-1 bg-slate-100 rounded text-xs transition" title="Copy Info"><i class="fas fa-copy"></i></button>
                                    </div>
                                    <div class="font-mono text-xs text-slate-400 mt-1 truncate">{{ user.api_key }}</div>
                                </td>
                                <td class="px-4 md:px-6 py-4">
                                    <div class="flex items-center gap-2 mb-1">
                                        {% if user.is_active == 1 %}<span class="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-600 text-xs font-bold">Active</span>
                                        {% elif user.is_active == 2 %}<span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-600 text-xs font-bold">Suspended</span>
                                        {% else %}<span class="px-2 py-0.5 rounded-full bg-red-100 text-red-600 text-xs font-bold">Banned</span>{% endif %}
                                    </div>
                                    <div class="text-xs text-slate-500">Last seen: {{ user.last_seen if user.last_seen else 'Never' }}</div>
                                </td>
                                <td class="px-4 md:px-6 py-4">
                                    <div class="flex items-center gap-2">
                                        <span class="font-bold text-lg {{ 'text-red-600 animate-pulse' if user.credits < 50 else 'text-emerald-600' }}">{{ user.credits }}</span>
                                        <span class="text-xs text-slate-400">credits</span>
                                    </div>
                                    <span class="px-2 py-0.5 rounded border text-xs font-bold 
                                        {% if user.plan == 'Premium' %}bg-purple-100 text-purple-600 border-purple-200
                                        {% elif user.plan == 'Standard' %}bg-blue-100 text-blue-600 border-blue-200
                                        {% else %}bg-slate-50 text-slate-600 border-slate-200{% endif %}">{{ user.plan }}</span>
                                </td>
                                <td class="px-4 md:px-6 py-4 text-right"><button class="px-3 py-1.5 bg-indigo-50 text-indigo-600 rounded hover:bg-indigo-100 font-bold text-xs">Manage</button></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            {% elif page == 'vouchers' %}
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4 md:p-6 mb-8">
                <h3 class="font-bold text-slate-700 mb-4">Generate Vouchers</h3>
                <form action="/generate_vouchers" method="POST" class="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
                    <div><label class="text-xs font-bold text-slate-500">Amount</label><input type="number" name="amount" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" required></div>
                    <div><label class="text-xs font-bold text-slate-500">Qty</label><input type="number" name="count" value="1" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg" required></div>
                    <div><label class="text-xs font-bold text-slate-500">Max Uses</label><input type="number" name="max_uses" value="1" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg"></div>
                    <div><label class="text-xs font-bold text-slate-500">Expiry</label><input type="date" name="expiry" class="w-full mt-1 px-3 py-2 bg-slate-50 border rounded-lg"></div>
                    <button class="bg-primary text-white font-bold py-2 rounded-lg hover:bg-indigo-600">Generate</button>
                </form>
            </div>
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-slate-50 text-slate-500 text-xs uppercase"><tr><th class="px-4 md:px-6 py-3">Code</th><th class="px-4 md:px-6 py-3">Value</th><th class="px-4 md:px-6 py-3">Usage</th><th class="px-4 md:px-6 py-3">Expiry</th><th class="px-4 md:px-6 py-3">Action</th></tr></thead>
                        <tbody class="divide-y divide-slate-100">
                            {% for v in vouchers %}
                            <tr>
                                <td class="px-4 md:px-6 py-3 font-mono font-bold select-all text-xs md:text-sm">{{ v.code }}</td>
                                <td class="px-4 md:px-6 py-3 font-bold text-emerald-600">+{{ v.amount }}</td>
                                <td class="px-4 md:px-6 py-3">{{ v.current_uses }} / {{ v.max_uses }}</td>
                                <td class="px-4 md:px-6 py-3 text-xs">{{ v.expiry_date if v.expiry_date else '-' }}</td>
                                <td class="px-4 md:px-6 py-3"><a href="/delete_voucher/{{ v.code }}" class="text-red-400 hover:text-red-600"><i class="fas fa-trash"></i></a></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            {% elif page == 'api_keys' %}
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div class="md:col-span-2 bg-white rounded-xl shadow-sm border border-slate-200 p-4 md:p-6">
                    <h3 class="font-bold text-slate-700 mb-4">API Keys Pool</h3>
                    <div class="overflow-x-auto">
                        <table class="w-full text-sm text-left">
                            <thead class="bg-slate-50 text-slate-500 text-xs uppercase"><tr><th class="px-4 py-3">Label</th><th class="px-4 py-3">Key</th><th class="px-4 py-3">Status</th><th class="px-4 py-3">Errors</th><th class="px-4 py-3">Action</th></tr></thead>
                            <tbody class="divide-y divide-slate-100">
                                {% for k in api_keys %}
                                <tr>
                                    <td class="px-4 py-3 font-bold">{{ k.label }}</td>
                                    <td class="px-4 py-3 font-mono text-xs">{{ k.key_value[:15] }}...</td>
                                    <td class="px-4 py-3">{% if k.is_active %}<span class="text-emerald-500 text-xs font-bold">Active</span>{% else %}<span class="text-red-500">Inactive</span>{% endif %}</td>
                                    <td class="px-4 py-3">{{ k.error_count }}</td>
                                    <td class="px-4 py-3"><a href="/delete_key/{{ k.key_value }}" class="text-red-400"><i class="fas fa-trash"></i></a></td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
                <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4 md:p-6 h-fit">
                    <h3 class="font-bold text-slate-700 mb-4">Add Key</h3>
                    <form action="/add_api_key" method="POST" class="space-y-3">
                        <input type="text" name="label" placeholder="Label Name" class="w-full px-3 py-2 bg-slate-50 border rounded-lg" required>
                        <input type="text" name="key_value" placeholder="sk-..." class="w-full px-3 py-2 bg-slate-50 border rounded-lg" required>
                        <button class="w-full bg-emerald-500 text-white font-bold py-2 rounded-lg hover:bg-emerald-600">Add Key</button>
                    </form>
                </div>
            </div>

            {% elif page == 'logs' %}
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-slate-50 text-slate-500 text-xs uppercase">
                            <tr>
                                <th class="px-4 md:px-6 py-3">Time</th>
                                <th class="px-4 md:px-6 py-3">User</th>
                                <th class="px-4 md:px-6 py-3">Action</th>
                                <th class="px-4 md:px-6 py-3">Cost</th>
                                <th class="px-4 md:px-6 py-3">Status</th>
                                <th class="px-4 md:px-6 py-3">Details</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            {% for l in logs %}
                            <tr>
                                <td class="px-4 md:px-6 py-3 text-xs text-slate-400 font-mono">{{ l.timestamp }}</td>
                                <td class="px-4 md:px-6 py-3 font-bold">{{ l.username }}</td>
                                <td class="px-4 md:px-6 py-3">{{ l.action }}</td>
                                <td class="px-4 md:px-6 py-3 font-bold {{ 'text-red-500' if l.cost > 0 else 'text-green-500' }}">
                                    {% if 'Refund' in l.action or 'refund' in l.action %}
                                        +{{ l.cost if l.cost else 0 }}
                                    {% else %}
                                        -{{ l.cost }}
                                    {% endif %}
                                </td>
                                <td class="px-4 md:px-6 py-3 text-xs">
                                    {% if 'Refund' in l.action or 'refund' in l.action %}
                                        <span class="refund-status">បង្វិលក្រេឌីត</span>
                                    {% else %}
                                        {{ l.status }}
                                    {% endif %}
                                </td>
                                <td class="px-4 md:px-6 py-3 text-xs text-slate-500">
                                    {% if l.task_id %}
                                        Task: {{ l.task_id[:8] }}...
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            {% elif page == 'settings' %}
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Update System (Restored) -->
                <div class="bg-gradient-to-br from-indigo-600 to-purple-700 rounded-xl p-4 md:p-6 text-white shadow-xl md:col-span-2">
                    <h4 class="font-bold text-lg mb-4 flex items-center gap-2"><i class="fas fa-cloud-upload-alt"></i> ប្រព័ន្ធអាប់ដេត (ZIP/URL Update)</h4>
                    <form action="/update_settings" method="POST" class="space-y-4">
                        <div class="flex items-center justify-between bg-white/10 p-4 rounded-lg border border-white/20">
                            <div><h5 class="font-bold">Enable Update Push</h5><p class="text-xs opacity-70">Client will auto-download and extract ZIP.</p></div>
                            <label class="switch">
                                <input type="checkbox" name="update_is_live" value="1" {% if update_is_live == '1' %}checked{% endif %}>
                                <span class="slider"></span>
                            </label>
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div><label class="text-xs opacity-70 block mb-1">Latest Version</label><input type="text" name="latest_version" value="{{ latest_version }}" class="w-full bg-white/20 border border-white/30 rounded px-3 py-2 backdrop-blur outline-none"></div>
                            <div><label class="text-xs opacity-70 block mb-1">ZIP Download URL</label><input type="text" name="update_url" value="{{ update_url }}" class="w-full bg-white/20 border border-white/30 rounded px-3 py-2 backdrop-blur outline-none" placeholder="https://mysite.com/update.zip"></div>
                        </div>
                        <div><label class="text-xs opacity-70 block mb-1">Description</label><textarea name="update_desc" class="w-full bg-white/20 border border-white/30 rounded px-3 py-2 backdrop-blur outline-none h-16">{{ update_desc }}</textarea></div>
                        <button class="bg-white text-indigo-700 font-bold px-6 py-2 rounded shadow hover:bg-indigo-50 w-full">Save Update Config</button>
                    </form>
                </div>

                 <!-- Broadcast (Restored) -->
                <div class="bg-white p-4 md:p-6 rounded-xl shadow-sm border border-slate-200">
                    <h4 class="font-bold text-slate-700 mb-4 pb-2 border-b">📢 ផ្សព្វផ្សាយដំណឹង (Broadcast)</h4>
                    <form action="/update_broadcast" method="POST" class="space-y-3">
                        <div class="flex gap-2">
                            <input type="color" name="color" value="{{ broadcast_color }}" class="h-10 w-12 rounded border cursor-pointer">
                            <input type="text" name="message" value="{{ broadcast_msg }}" placeholder="សរសេរដំណឹងនៅទីនេះ..." class="flex-1 border rounded px-3 outline-none">
                        </div>
                        <div class="flex gap-2">
                            <button class="flex-1 bg-indigo-600 text-white font-bold py-2 rounded">Send Message</button>
                            <a href="/clear_broadcast" class="px-4 py-2 bg-red-100 text-red-600 rounded font-bold">Clear</a>
                        </div>
                    </form>
                </div>

                <!-- Costs -->
                <div class="bg-white p-4 md:p-6 rounded-xl shadow-sm border border-slate-200">
                     <h4 class="font-bold text-slate-700 mb-4 pb-2 border-b">System Costs & Limits</h4>
                     <form action="/update_settings" method="POST" class="space-y-4">
                         <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                             <div><label class="text-xs font-bold text-slate-500">Sora-2 Cost</label><input type="number" name="cost_sora_2" value="{{ costs.sora_2 }}" class="w-full mt-1 border rounded p-2"></div>
                             <div><label class="text-xs font-bold text-slate-500">Sora-2 Pro Cost</label><input type="number" name="cost_sora_2_pro" value="{{ costs.sora_2_pro }}" class="w-full mt-1 border rounded p-2"></div>
                         </div>
                         <button class="w-full bg-primary text-white font-bold px-6 py-2 rounded">Save Changes</button>
                     </form>
                </div>
            </div>
            {% endif %}
        </div>
    </main>

    <!-- User Management Modal -->
    <div id="userModal" class="modal opacity-0 pointer-events-none fixed w-full h-full top-0 left-0 flex items-center justify-center z-50">
        <div class="modal-overlay absolute w-full h-full bg-gray-900 opacity-50" onclick="closeUserModal()"></div>
        <div class="modal-container bg-white w-11/12 md:max-w-2xl mx-auto rounded-xl shadow-2xl z-50 overflow-y-auto max-h-[90vh]">
            <div class="modal-content py-6 px-4 md:px-8 text-left">
                <div class="flex justify-between items-center pb-3 border-b">
                    <p class="text-xl md:text-2xl font-bold text-slate-800" id="modalUsername">User Settings</p>
                    <div class="cursor-pointer z-50" onclick="closeUserModal()"><i class="fas fa-times text-slate-500 hover:text-red-500 text-xl"></i></div>
                </div>
                <form action="/update_user_full" method="POST" class="mt-4 space-y-6">
                    <input type="hidden" name="username" id="modalHiddenUsername">
                    <div class="flex gap-2">
                        <a id="btnActive" href="#" class="flex-1 py-2 text-center rounded bg-emerald-50 text-emerald-600 hover:bg-emerald-100 font-bold text-sm">Active</a>
                        <a id="btnSuspend" href="#" class="flex-1 py-2 text-center rounded bg-amber-50 text-amber-600 hover:bg-amber-100 font-bold text-sm">Suspend</a>
                        <a id="btnBan" href="#" class="flex-1 py-2 text-center rounded bg-red-50 text-red-600 hover:bg-red-100 font-bold text-sm">Ban</a>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div><label class="block text-xs font-bold text-slate-500 mb-1">User Plan</label><select name="plan" id="modalPlan" class="w-full px-3 py-2 bg-slate-50 border rounded-lg"><option value="Mini">Mini</option><option value="Basic">Basic</option><option value="Standard">Standard</option><option value="Premium">Premium</option></select></div>
                        <div><label class="block text-xs font-bold text-slate-500 mb-1">Add/Remove Credits</label><input type="number" name="credit_adj" placeholder="+/- Amount" class="w-full px-3 py-2 bg-slate-50 border rounded-lg"></div>
                    </div>
                    <div class="bg-slate-50 p-4 rounded-lg border border-slate-200">
                        <h5 class="font-bold text-sm text-slate-700 mb-3">Custom Override</h5>
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                            <div><label class="text-[10px] font-bold text-slate-400">Concurrency</label><input type="number" name="custom_limit" id="modalLimit" class="w-full mt-1 border rounded p-1.5 text-sm"></div>
                            <div><label class="text-[10px] font-bold text-slate-400">Cost (Sora-2)</label><input type="number" name="custom_cost_2" id="modalCost2" class="w-full mt-1 border rounded p-1.5 text-sm"></div>
                            <div><label class="text-[10px] font-bold text-slate-400">Cost (Pro)</label><input type="number" name="custom_cost_pro" id="modalCostPro" class="w-full mt-1 border rounded p-1.5 text-sm"></div>
                        </div>
                    </div>
                    <div><label class="block text-xs font-bold text-slate-500 mb-1">Assigned API Key</label><select name="assigned_key" id="modalAssignedKey" class="w-full px-3 py-2 bg-slate-50 border rounded-lg"><option value="">-- Use Pool (Default) --</option>{% if api_keys %}{% for k in api_keys %}<option value="{{ k.key_value }}">{{ k.label }}</option>{% endfor %}{% endif %}</select></div>
                    <div class="flex justify-end pt-4 border-t gap-3"><a id="btnDelete" href="#" onclick="return confirm('Delete user?')" class="px-4 py-2 text-red-500 hover:bg-red-50 rounded font-bold text-sm">Delete User</a><button type="submit" class="px-6 py-2 bg-primary text-white rounded hover:bg-indigo-600 font-bold shadow">Save Changes</button></div>
                </form>
            </div>
        </div>
    </div>

    <script>
        // Toggle sidebar for mobile
        const mobileMenuButton = document.getElementById('mobileMenuButton');
        const sidebar = document.getElementById('sidebar');
        const sidebarOverlay = document.getElementById('sidebarOverlay');
        const closeSidebarBtn = document.getElementById('closeSidebar');

        if (mobileMenuButton) {
            mobileMenuButton.addEventListener('click', () => {
                sidebar.classList.remove('-translate-x-full');
                sidebarOverlay.classList.remove('hidden');
                document.body.classList.add('overflow-hidden');
            });
        }

        if (closeSidebarBtn) {
            closeSidebarBtn.addEventListener('click', closeSidebar);
        }

        if (sidebarOverlay) {
            sidebarOverlay.addEventListener('click', closeSidebar);
        }

        function closeSidebar() {
            sidebar.classList.add('-translate-x-full');
            sidebarOverlay.classList.add('hidden');
            document.body.classList.remove('overflow-hidden');
        }

        // Close sidebar when clicking on a menu link (mobile)
        document.querySelectorAll('.sidebar-link').forEach(link => {
            link.addEventListener('click', () => {
                if (window.innerWidth < 768) {
                    closeSidebar();
                }
            });
        });

        // Close sidebar on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeSidebar();
            }
        });

        // Existing functions
        function showToast(message) {
            const toast = document.getElementById('toast-container');
            const msg = document.getElementById('toast-message');
            msg.innerText = message;
            toast.classList.add('show');
            setTimeout(() => { toast.classList.remove('show'); }, 3000);
        }

        function copyUserInfo(user, key, plan, credits, expiry) {
            const text = "ឈ្មោះគណនីអ្នកប្រើប្រាស់: " + user + "\\n" +
                         "លេដកូដសម្រាប់បើកដំណើរការ: " + key + "\\n" +
                         "ប្រភេទគណនី: " + plan + "\\n" +
                         "ចំនួនក្រេដីត: " + credits + "\\n" +
                         "រយៈពេលប្រើប្រាស់: " + expiry;
            
            navigator.clipboard.writeText(text).then(() => { showToast("បានចម្លងព័ត៌មានគណនីរួចរាល់!"); });
        }

        function openUserModal(user) {
            document.getElementById('modalUsername').innerText = "Manage: " + user.username;
            document.getElementById('modalHiddenUsername').value = user.username;
            document.getElementById('modalPlan').value = user.plan;
            document.getElementById('modalLimit').value = user.custom_limit || "";
            document.getElementById('modalCost2').value = user.custom_cost_2 || "";
            document.getElementById('modalCostPro').value = user.custom_cost_pro || "";
            document.getElementById('modalAssignedKey').value = user.assigned_api_key || "";
            document.getElementById('btnActive').href = "/toggle_status/" + user.username + "/1";
            document.getElementById('btnSuspend').href = "/toggle_status/" + user.username + "/2";
            document.getElementById('btnBan').href = "/toggle_status/" + user.username + "/0";
            document.getElementById('btnDelete').href = "/delete_user/" + user.username;
            const modal = document.getElementById('userModal');
            modal.classList.remove('opacity-0', 'pointer-events-none');
            document.body.classList.add('modal-active');
        }

        function closeUserModal() {
            const modal = document.getElementById('userModal');
            modal.classList.add('opacity-0', 'pointer-events-none');
            document.body.classList.remove('modal-active');
        }
    </script>
</body>
</html>
"""

# --- AUTH & ROUTES ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: 
            return redirect(f'/{ADMIN_LOGIN_PATH}')
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home(): 
    return jsonify({"status": "Server Running", "secure": True}), 200

@app.route(f'/{ADMIN_LOGIN_PATH}', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/dashboard')
    
    return render_template_string("""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Login</title><script src="https://cdn.tailwindcss.com"></script></head><body class="bg-slate-100 h-screen flex items-center justify-center"><div class="bg-white p-8 rounded-xl shadow-xl w-96 border border-slate-200"><h2 class="text-2xl font-bold text-slate-800 mb-6 text-center">Admin Access</h2><form method="POST" class="space-y-4"><input type="password" name="password" placeholder="Password" class="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 outline-none" required><button class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 rounded-lg">Login</button></form></div></body></html>""")

@app.route('/logout')
def logout(): 
    session.pop('logged_in', None)
    return redirect(f'/{ADMIN_LOGIN_PATH}')

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    api_keys = conn.execute("SELECT key_value, label FROM api_keys WHERE is_active=1").fetchall()
    users_raw = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    users = [dict(u) for u in users_raw]
    
    stats = {'Premium': 0, 'Standard': 0, 'Basic': 0, 'Mini': 0}
    for u in users:
        p = u.get('plan', 'Standard')
        if p in stats: 
            stats[p] += 1
            
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='users', users=users, api_keys=api_keys, stats=stats)

@app.route('/vouchers')
@login_required
def vouchers():
    try:
        conn = get_db()
        v = conn.execute("SELECT code, amount, max_uses, current_uses, expiry_date FROM vouchers ORDER BY created_at DESC").fetchall()
        conn.close()
        return render_template_string(MODERN_DASHBOARD_HTML, page='vouchers', vouchers=v)
    except Exception as e: 
        return f"DB Error: {e}", 500

@app.route('/api_keys')
@login_required
def view_keys():
    try:
        conn = get_db()
        keys = conn.execute("SELECT key_value, label, is_active, error_count FROM api_keys").fetchall()
        conn.close()
        return render_template_string(MODERN_DASHBOARD_HTML, page='api_keys', api_keys=keys)
    except Exception as e: 
        return f"DB Error: {e}", 500

@app.route('/logs')
@login_required
def view_logs():
    try:
        conn = get_db()
        # Check if task_id column exists
        try:
            l = conn.execute("SELECT timestamp, username, action, cost, status, task_id FROM logs ORDER BY id DESC LIMIT 100").fetchall()
        except sqlite3.OperationalError as e:
            # If column doesn't exist yet, select without it
            if "no such column" in str(e) and "task_id" in str(e):
                l = conn.execute("SELECT timestamp, username, action, cost, status FROM logs ORDER BY id DESC LIMIT 100").fetchall()
                # Add empty task_id to each row
                l = [list(row) + [''] for row in l]
            else:
                raise e
        
        conn.close()
        return render_template_string(MODERN_DASHBOARD_HTML, page='logs', logs=l)
    except Exception as e: 
        return f"DB Error: {e}", 500

@app.route('/settings')
@login_required
def settings():
    latest_ver = get_setting('latest_version', '1.0.0')
    update_desc = get_setting('update_desc', 'Initial Release')
    update_is_live = get_setting('update_is_live', '0')
    update_url = get_setting('update_url', '')
    broadcast_msg = get_setting('broadcast_msg', '')
    broadcast_color = get_setting('broadcast_color', '#FF0000')
    costs = {'sora_2': get_setting('cost_sora_2', 25), 'sora_2_pro': get_setting('cost_sora_2_pro', 35)}
    
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', costs=costs,
                                  latest_version=latest_ver, update_desc=update_desc,
                                  update_is_live=update_is_live, update_url=update_url,
                                  broadcast_msg=broadcast_msg, broadcast_color=broadcast_color)

# --- ACTION ROUTES ---
@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    try:
        assigned_key = request.form.get('assigned_key') or None
        conn = get_db()
        conn.execute("INSERT INTO users (username, api_key, credits, expiry_date, is_active, created_at, plan, assigned_api_key) VALUES (?, ?, ?, ?, 1, ?, ?, ?)", 
                     (request.form['username'], "SK-"+str(uuid.uuid4())[:12].upper(), int(request.form['credits']), request.form['expiry'], datetime.now().strftime("%Y-%m-%d"), request.form['plan'], assigned_key))
        conn.commit()
        conn.close()
    except Exception as e: 
        print(e)
    return redirect('/dashboard')

@app.route('/update_user_full', methods=['POST'])
@login_required
def update_user_full():
    u = request.form['username']
    plan = request.form.get('plan')
    credit_adj = request.form.get('credit_adj')
    cl = request.form.get('custom_limit') or None
    c2 = request.form.get('custom_cost_2') or None
    cp = request.form.get('custom_cost_pro') or None
    ak = request.form.get('assigned_key') or None
    conn = get_db()
    conn.execute('''UPDATE users SET plan=?, custom_limit=?, custom_cost_2=?, custom_cost_pro=?, assigned_api_key=? WHERE username=?''', 
                 (plan, cl, c2, cp, ak, u))
    if credit_adj:
        try: 
            conn.execute("UPDATE users SET credits = credits + ? WHERE username=?", (int(credit_adj), u))
        except: 
            pass
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/add_api_key', methods=['POST'])
@login_required
def add_api_key():
    try:
        conn = get_db()
        conn.execute("INSERT INTO api_keys (key_value, label) VALUES (?, ?)", 
                    (request.form['key_value'], request.form['label']))
        conn.commit()
        conn.close()
    except: 
        pass
    return redirect('/api_keys')

@app.route('/delete_key/<path:k>')
@login_required
def delete_key(k):
    conn = get_db()
    conn.execute("DELETE FROM api_keys WHERE key_value=?", (k,))
    conn.commit()
    conn.close()
    return redirect('/api_keys')

@app.route('/toggle_status/<username>/<int:status>')
@login_required
def toggle_status(username, status):
    conn = get_db()
    conn.execute("UPDATE users SET is_active = ? WHERE username=?", (status, username))
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/delete_user/<username>')
@login_required
def delete_user(username):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    return redirect('/dashboard')

@app.route('/generate_vouchers', methods=['POST'])
@login_required
def generate_vouchers():
    amt = int(request.form['amount'])
    qty = int(request.form['count'])
    max_uses = int(request.form.get('max_uses', 1))
    expiry = request.form.get('expiry') or None
    conn = get_db()
    for _ in range(qty): 
        conn.execute("INSERT INTO vouchers (code, amount, max_uses, expiry_date, created_at) VALUES (?, ?, ?, ?, ?)", 
                    (generate_voucher_code(amt), amt, max_uses, expiry, str(datetime.now())))
    conn.commit()
    conn.close()
    return redirect('/vouchers')

@app.route('/delete_voucher/<code>')
@login_required
def delete_voucher(code):
    conn = get_db()
    conn.execute("DELETE FROM vouchers WHERE code=?", (code,))
    conn.commit()
    conn.close()
    return redirect('/vouchers')

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    form = request.form
    
    # កំណត់តម្លៃសម្រាប់ 'update_is_live' (checkbox)
    if 'update_is_live' in form:
        set_setting('update_is_live', '1')
        # កំណត់ update timestamp ថ្មី
        set_setting('update_timestamp', datetime.now().isoformat())
    else:
        set_setting('update_is_live', '0')
    
    # រក្សាទុកការកំណត់ផ្សេងៗទៀត
    keys_to_save = ['latest_version', 'update_desc', 'update_url', 
                    'cost_sora_2', 'cost_sora_2_pro']
    for key in keys_to_save:
        if key in form:
            set_setting(key, form[key])
    
    # បង្កើត log សម្រាប់ការអាប់ដេត
    conn = get_db()
    conn.execute("INSERT INTO logs (username, action, cost, timestamp, status) VALUES (?, ?, ?, ?, ?)", 
                 ('SYSTEM', f'UPDATE_PUSH: v{form.get("latest_version", "")} enabled', 0, str(datetime.now()), 'Update'))
    conn.commit()
    conn.close()
    
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

# --- API ---
@app.route('/api/verify', methods=['POST'])
def verify_user():
    d = request.json
    conn = get_db()
    u = conn.execute("SELECT credits, expiry_date, is_active, plan, custom_limit, custom_cost_2, custom_cost_pro FROM users WHERE username=? AND api_key=?", 
                     (d.get('username'), d.get('api_key'))).fetchone()
    if not u: 
        conn.close()
        return jsonify({"valid": False, "message": "Invalid Credentials"})
    
    if u['is_active'] == 0: 
        conn.close()
        return jsonify({"valid": False, "message": "Banned"})
    
    if u['is_active'] == 2: 
        conn.close()
        return jsonify({"valid": False, "message": "Suspended"})
    
    if datetime.now() > datetime.strptime(u['expiry_date'], "%Y-%m-%d"): 
        conn.close()
        return jsonify({"valid": False, "message": "Expired"})
    
    conn.execute("UPDATE users SET last_seen = ? WHERE username=?", 
                 (str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")), d.get('username')))
    conn.commit()
    
    limit = u['custom_limit'] if u['custom_limit'] else int(get_setting(f"limit_{u['plan'].lower()}", 3))
    
    # យកតម្លៃ Custom Costs ពី user record ឬតម្លៃ default
    custom_cost_2 = u['custom_cost_2'] if u['custom_cost_2'] is not None else int(get_setting('cost_sora_2', 25))
    custom_cost_pro = u['custom_cost_pro'] if u['custom_cost_pro'] is not None else int(get_setting('cost_sora_2_pro', 35))
    
    return jsonify({
        "valid": True, 
        "credits": u['credits'], 
        "expiry": u['expiry_date'], 
        "plan": u['plan'], 
        "concurrency_limit": limit,
        "broadcast": get_setting('broadcast_msg', ''), 
        "broadcast_color": get_setting('broadcast_color', '#FF0000'),
        "latest_version": get_setting('latest_version', '1.0.0'), 
        "update_desc": get_setting('update_desc', ''), 
        "update_is_live": get_setting('update_is_live', '0') == '1', 
        "download_url": get_setting('update_url', ''),
        # បន្ថែមតម្លៃ Custom Costs
        "custom_cost_2": custom_cost_2,
        "custom_cost_pro": custom_cost_pro,
        # រក្សាទុកតម្លៃ default ផងដែរ
        "default_cost_sora_2": int(get_setting('cost_sora_2', 25)),
        "default_cost_sora_2_pro": int(get_setting('cost_sora_2_pro', 35))
    })
    
@app.route('/api/check-update-status', methods=['GET'])
def check_update_status():
    """API សម្រាប់ client ពិនិត្យស្ថានភាពអាប់ដេតថ្មី"""
    return jsonify({
        "latest_version": get_setting('latest_version', '1.0.0'),
        "update_is_live": get_setting('update_is_live', '0') == '1',
        "update_desc": get_setting('update_desc', ''),
        "download_url": get_setting('update_url', ''),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    d = request.json
    u = d.get('username')
    k = d.get('api_key')
    if u and k:
        conn = get_db()
        conn.execute("UPDATE users SET session_minutes = session_minutes + 1 WHERE username=? AND api_key=?", (u, k))
        conn.commit()
        conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/redeem', methods=['POST'])
def redeem():
    d = request.json
    code = d.get('code')
    username = d.get('username')
    conn = get_db()
    v = conn.execute("SELECT amount, max_uses, current_uses, expiry_date FROM vouchers WHERE code=?", (code,)).fetchone()
    if not v: 
        conn.close()
        return jsonify({"success": False, "message": "Invalid Code"})
    
    if v['current_uses'] >= v['max_uses']: 
        conn.close()
        return jsonify({"success": False, "message": "Fully Used"})
    
    if v['expiry_date'] and datetime.now() > datetime.strptime(v['expiry_date'], "%Y-%m-%d"): 
        conn.close()
        return jsonify({"success": False, "message": "Expired"})
    
    if conn.execute("SELECT 1 FROM voucher_usage WHERE code=? AND username=?", (code, username)).fetchone(): 
        conn.close()
        return jsonify({"success": False, "message": "Already Redeemed"})
    
    conn.execute("UPDATE users SET credits=credits+? WHERE username=?", (v['amount'], username))
    conn.execute("UPDATE vouchers SET current_uses=current_uses+1 WHERE code=?", (code,))
    conn.execute("INSERT INTO voucher_usage (code, username, used_at) VALUES (?, ?, ?)", (code, username, str(datetime.now())))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Added {v['amount']} Credits"})

@app.route('/api/proxy/generate', methods=['POST'])
def proxy_gen():
    auth = request.headers.get("Client-Auth", "")
    if ":" not in auth: 
        return jsonify({"code":-1}), 401
    
    u_name, u_key = auth.split(":")
    conn = get_db()
    user = conn.execute("SELECT credits, is_active, custom_cost_2, custom_cost_pro FROM users WHERE username=? AND api_key=?", (u_name, u_key)).fetchone()
    
    if not user or user['is_active'] != 1: 
        conn.close()
        return jsonify({"code":-1}), 403
    
    client_data = request.json
    client_model = client_data.get('model', '')
    
    # Determine cost based on custom costs or default
    if "pro" in client_model and user['custom_cost_pro']:
        cost = user['custom_cost_pro']
    elif user['custom_cost_2']:
        cost = user['custom_cost_2']
    else:
        cost = int(get_setting('cost_sora_2_pro' if "pro" in client_model else 'cost_sora_2', 25))
    
    if user['credits'] < cost: 
        conn.close()
        return jsonify({"code":-1, "message": "Insufficient Credits"}), 402
    
    real_key = get_active_api_key(u_name)
    if not real_key: 
        conn.close()
        return jsonify({"code":-1, "message": "System Busy"}), 503
    
    try:
        # ✅ បម្លែង model ពី client ទៅកាន់ API model
        model_map = {
            "sora-2": "sora-2-text-to-video",
            "sora-2-pro": "sora-2-text-to-video"
        }
        
        api_model = model_map.get(client_model, "sora-2-text-to-video")
        
        # ✅ បម្លែង aspect ratio
        aspect_ratio = client_data.get('aspectRatio', '16:9')
        if aspect_ratio == '9:16':
            api_aspect_ratio = 'portrait'
        else:
            api_aspect_ratio = 'landscape'
        
        # ✅ បង្កើត payload សម្រាប់ API
        api_payload = {
            "model": api_model,
            "prompt": client_data.get('prompt', ''),
            "aspectRatio": api_aspect_ratio,
            "removeWatermark": True
        }
        
        # ✅ បន្ថែម nFrames និង size សម្រាប់ Pro model
        if "pro" in client_model:
            api_payload["nFrames"] = "15"  # Default for Pro
        else:
            api_payload["nFrames"] = "10"  # Default for non-Pro
        
        api_endpoint = "https://freesoragenerator.com/api/v1/video/sora-pro"
        
        print(f"[DEBUG] API Call to: {api_endpoint}")
        print(f"[DEBUG] API Model: {api_model}")
        print(f"[DEBUG] API Payload: {api_payload}")
        print(f"[DEBUG] Using API Key: {real_key[:15]}...")
        
        r = requests.post(api_endpoint, 
                         json=api_payload, 
                         headers={
                             "Authorization": f"Bearer {real_key}",
                             "Content-Type": "application/json",
                             "User-Agent": "Mozilla/5.0"
                         }, 
                         timeout=120)
        
        print(f"[DEBUG] Response status: {r.status_code}")
        print(f"[DEBUG] Response: {r.text[:500]}")
        
        if r.status_code == 200:
            data = r.json()
            
            if data.get("code") == 0:
                task_data = data.get('data', {})
                tid = task_data.get('taskId')
                
                print(f"[DEBUG] Task ID received: {tid}")
                
                if tid: 
                    conn.execute("INSERT INTO tasks (task_id, username, cost, status, created_at, model) VALUES (?, ?, ?, ?, ?, ?)", 
                               (tid, u_name, cost, 'pending', str(datetime.now()), client_model))
                
                # Deduct credits immediately
                conn.execute("UPDATE users SET credits=credits-? WHERE username=?", (cost, u_name))
                
                # Log the generation with task_id
                conn.execute("INSERT INTO logs (username, action, cost, timestamp, status, task_id) VALUES (?, ?, ?, ?, ?, ?)", 
                            (u_name, "generate", cost, str(datetime.now()), 'Pending', tid or ''))
                
                conn.commit()
                
                # Return response in expected format
                response_data = {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "taskId": tid
                    },
                    "user_balance": user['credits'] - cost
                }
                return jsonify(response_data), 200
            else:
                # If API returns error, refund credits
                conn.execute("UPDATE users SET credits=credits+? WHERE username=?", (cost, u_name))
                conn.commit()
                error_msg = data.get('message', 'API Error')
                print(f"[ERROR] API returned error: {error_msg}")
                return jsonify({
                    "code": -1,
                    "message": error_msg
                }), 400
        
        # Handle other status codes
        print(f"[ERROR] API returned status {r.status_code}: {r.text}")
        return jsonify({"code":-1, "message": f"API Error: {r.status_code}"}), r.status_code
    
    except requests.exceptions.Timeout:
        print(f"[ERROR] Request timeout for user: {u_name}")
        return jsonify({"code":-1, "message": "Request timeout"}), 504
        
    except Exception as e: 
        print(f"[ERROR] in proxy_gen: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"code":-1, "message": str(e)}), 500
    
    finally: 
        conn.close()

@app.route('/api/proxy/check-result', methods=['POST'])
def proxy_chk():
    try:
        real_key = get_active_api_key()
        task_id = request.json.get('taskId')

        if not task_id:
            return jsonify({"code": -1, "message": "Missing taskId"}), 400

        print(f"[DEBUG] Checking result for taskId: {task_id}")
        print(f"[DEBUG] Using API Key: {real_key[:15]}...")
        
        # Call the actual API
        r = requests.post("https://freesoragenerator.com/api/video-generations/check-result", 
                         json={"taskId": task_id}, 
                         headers={
                             "Authorization": f"Bearer {real_key}",
                             "Content-Type": "application/json"
                         }, 
                         timeout=60)

        print(f"[DEBUG] Check result response: {r.status_code}")
        print(f"[DEBUG] Response data: {r.text[:500]}")

        if r.status_code != 200:
            return jsonify({
                "code": -1,
                "message": f"API Error: {r.status_code}"
            }), r.status_code
        
        data = r.json()
        
        # Update our database based on task status
        conn = get_db()
        task = conn.execute("SELECT username, cost, status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        
        if task:
            data_info = data.get('data', {})
            status = data_info.get('status')
            current_status = task['status']
            
            # If task failed and not already refunded, refund credits
            if status == 'failed' and current_status != 'refunded':
                conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", 
                           (task['cost'], task['username']))
                
                conn.execute("UPDATE tasks SET status = 'refunded' WHERE task_id = ?", (task_id,))
                
                conn.execute("INSERT INTO logs (username, action, cost, timestamp, status, task_id) VALUES (?, ?, ?, ?, ?, ?)", 
                           (task['username'], f"Refund {task_id}", task['cost'], str(datetime.now()), 'Refunded', task_id))
                
                # Update the response to indicate refund
                if 'data' in data:
                    data['data']['credits_refunded'] = True
                else:
                    data['data'] = {'credits_refunded': True}
                
                conn.commit()
                
            # If task succeeded, update status
            elif status == 'succeeded' and current_status != 'succeeded':
                conn.execute("UPDATE tasks SET status = 'succeeded' WHERE task_id = ?", (task_id,))
                
                conn.execute("INSERT INTO logs (username, action, cost, timestamp, status, task_id) VALUES (?, ?, ?, ?, ?, ?)", 
                           (task['username'], f"Success {task_id}", task['cost'], str(datetime.now()), 'Success', task_id))
                
                conn.commit()
        
        conn.close()
        return jsonify(data), 200
    
    except Exception as e:
        print(f"[ERROR] in proxy_chk: {e}")
        return jsonify({"code":-1, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)



