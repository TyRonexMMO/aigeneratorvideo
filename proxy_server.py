from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file, abort, flash
import requests
import os
import sqlite3
import uuid
import time
import random
import string
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "super_secret_admin_key_v2")

# --- CONFIGURATION ---
DB_PATH = os.environ.get("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_LOGIN_PATH = os.environ.get("ADMIN_PATH", "secure_login")
UPLOAD_FOLDER = 'static/updates'
ALLOWED_EXTENSIONS = {'py', 'exe', 'zip'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

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
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, api_key TEXT, credits INTEGER, expiry_date TEXT, is_active INTEGER, status TEXT DEFAULT 'active', created_at TEXT, plan TEXT DEFAULT 'Standard')''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, cost INTEGER, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers
                 (code TEXT PRIMARY KEY, amount INTEGER, is_used INTEGER, created_at TEXT, used_by TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (task_id TEXT PRIMARY KEY, username TEXT, cost INTEGER, status TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS banned_ips
                 (ip TEXT PRIMARY KEY, reason TEXT, banned_at TEXT)''')

    defaults = {
        'sora_api_key': os.environ.get("SORA_API_KEY", "sk-DEFAULT"),
        'cost_sora_2': '25', 'cost_sora_2_pro': '35',
        'limit_mini': '1', 'limit_basic': '2', 'limit_standard': '3',
        'broadcast_msg': '',
        'broadcast_color': '#FF0000',
        'latest_version': '25.12.11',
        'update_desc': 'Initial Release',
        'update_is_live': '0',
        'update_filename': ''
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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- SECURITY MIDDLEWARE ---
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
    <title>Sora Admin - ផ្ទាំងគ្រប់គ្រង</title>
    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Kantumruy+Pro:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
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
        
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(function() {
                const Toast = Swal.mixin({
                    toast: true, position: 'top-end', showConfirmButton: false, timer: 3000, timerProgressBar: true,
                    didOpen: (toast) => { toast.addEventListener('mouseenter', Swal.stopTimer); toast.addEventListener('mouseleave', Swal.resumeTimer); }
                });
                Toast.fire({ icon: 'success', title: 'បានចម្លង License Key!' });
            });
        }
    </script>
    <style>
        .sidebar-link { transition: all 0.2s; }
        .sidebar-link:hover, .sidebar-link.active { background-color: #4F46E5; color: white; transform: translateX(5px); }
        .sidebar-link:hover i, .sidebar-link.active i { color: white; }
        .card-hover { transition: transform 0.2s, box-shadow 0.2s; }
        .card-hover:hover { transform: translateY(-2px); box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1); }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #f1f1f1; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
        .switch { position: relative; display: inline-block; width: 44px; height: 24px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #cbd5e1; transition: .4s; border-radius: 24px; }
        .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #10b981; }
        input:checked + .slider:before { transform: translateX(20px); }
    </style>
</head>
<body class="flex h-screen overflow-hidden bg-gray-50 text-slate-800 font-sans">
    
    <!-- Flash Messages (handled by SweetAlert now mainly, but kept for fallback) -->
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            <script>
                {% for category, message in messages %}
                    Swal.fire({
                        icon: '{{ "success" if category != "error" else "error" }}',
                        title: '{{ "ជោគជ័យ" if category != "error" else "បរាជ័យ" }}',
                        text: '{{ message }}',
                        timer: 3000,
                        showConfirmButton: false
                    });
                {% endfor %}
            </script>
        {% endif %}
    {% endwith %}
    
    <!-- Show New User Modal if created -->
    {% if new_user_data %}
    <script>
        Swal.fire({
            title: '<strong>បានបង្កើតគណនីថ្មី!</strong>',
            icon: 'success',
            html:
                '<div class="text-left bg-gray-100 p-4 rounded-lg border border-gray-300">' +
                '<p class="mb-2"><strong>ឈ្មោះគណនី:</strong> {{ new_user_data.username }}</p>' +
                '<p class="mb-1"><strong>License Key:</strong></p>' +
                '<div class="flex items-center gap-2">' +
                '<code class="bg-white px-2 py-1 rounded border flex-1 font-mono text-emerald-600 font-bold" id="newKey">{{ new_user_data.key }}</code>' +
                '<button onclick="copyToClipboard(\'{{ new_user_data.key }}\')" class="bg-blue-500 text-white px-3 py-1 rounded hover:bg-blue-600"><i class="fas fa-copy"></i></button>' +
                '</div>' +
                '</div>',
            showCloseButton: true,
            focusConfirm: false,
            confirmButtonText: '<i class="fa fa-thumbs-up"></i> យល់ព្រម',
        })
    </script>
    {% endif %}

    <!-- Sidebar -->
    <aside class="w-64 bg-white border-r border-gray-200 flex flex-col hidden md:flex z-50 shadow-lg">
        <div class="h-20 flex items-center px-6 border-b border-gray-50 bg-slate-900 text-white">
            <i class="fas fa-robot text-emerald-400 text-2xl mr-3"></i>
            <span class="text-xl font-bold tracking-tight">Sora Admin</span>
        </div>

        <nav class="flex-1 overflow-y-auto py-6 px-4 space-y-1.5">
            <p class="px-4 text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">ម៉ឺនុយចម្បង</p>
            <a href="/dashboard" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'users' else '' }}">
                <i class="fas fa-users w-6 {{ 'text-primary' if page != 'users' else 'text-white' }}"></i>
                <span class="font-medium">អ្នកប្រើប្រាស់ (Users)</span>
            </a>
            <a href="/vouchers" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'vouchers' else '' }}">
                <i class="fas fa-ticket-alt w-6 {{ 'text-primary' if page != 'vouchers' else 'text-white' }}"></i>
                <span class="font-medium">ប័ណ្ណបញ្ចូលលុយ (Vouchers)</span>
            </a>
            <a href="/logs" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'logs' else '' }}">
                <i class="fas fa-clipboard-list w-6 {{ 'text-primary' if page != 'logs' else 'text-white' }}"></i>
                <span class="font-medium">ប្រវត្តិសកម្មភាព (Logs)</span>
            </a>
            
            <p class="px-4 text-xs font-bold text-slate-400 uppercase tracking-wider mt-8 mb-3">ប្រព័ន្ធ</p>
            <a href="/security" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'security' else '' }}">
                <i class="fas fa-shield-alt w-6 {{ 'text-primary' if page != 'security' else 'text-white' }}"></i>
                <span class="font-medium">សុវត្ថិភាព (Security)</span>
            </a>
            <a href="/settings" class="sidebar-link flex items-center px-4 py-3 text-slate-600 rounded-xl {{ 'active' if page == 'settings' else '' }}">
                <i class="fas fa-cog w-6 {{ 'text-primary' if page != 'settings' else 'text-white' }}"></i>
                <span class="font-medium">ការកំណត់ (Settings)</span>
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
                    <p class="text-slate-500 mt-1">មើលនិងកែប្រែទិន្នន័យអ្នកប្រើប្រាស់ទាំងអស់</p>
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
                    <div class="col-span-1"><label class="block text-xs font-bold text-slate-500 mb-1.5">ឈ្មោះគណនី</label><input type="text" name="username" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-medium" placeholder="Ex: User01" required></div>
                    <div class="col-span-1"><label class="block text-xs font-bold text-slate-500 mb-1.5">ក្រេឌីត</label><input type="number" name="credits" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-medium" placeholder="500" required></div>
                    <div class="col-span-1"><label class="block text-xs font-bold text-slate-500 mb-1.5">កញ្ចប់ (Plan)</label>
                        <select name="plan" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-medium cursor-pointer">
                            <option value="Mini">Mini (1 Thread)</option><option value="Basic">Basic (2 Threads)</option><option value="Standard" selected>Standard (3 Threads)</option>
                        </select>
                    </div>
                    <div class="col-span-1"><label class="block text-xs font-bold text-slate-500 mb-1.5">ថ្ងៃផុតកំណត់</label><input type="date" name="expiry" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-medium cursor-pointer" required></div>
                    <div class="col-span-1"><button type="submit" class="w-full bg-primary hover:bg-indigo-600 text-white font-bold py-2.5 rounded-lg transition shadow-lg shadow-indigo-500/30 flex items-center justify-center gap-2"><i class="fas fa-check"></i> បង្កើត</button></div>
                </form>
            </div>

            <!-- Table -->
            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-sm text-left">
                        <thead class="text-xs text-slate-500 uppercase bg-slate-50 border-b border-slate-100">
                            <tr>
                                <th class="px-6 py-4 font-bold">ឈ្មោះ</th>
                                <th class="px-6 py-4 font-bold">License Key (ចុច Copy)</th>
                                <th class="px-6 py-4 font-bold">កញ្ចប់</th>
                                <th class="px-6 py-4 font-bold text-center">ក្រេឌីត</th>
                                <th class="px-6 py-4 font-bold">ស្ថានភាព (Status)</th>
                                <th class="px-6 py-4 font-bold text-right">សកម្មភាព</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            {% for user in users %}
                            <tr class="hover:bg-slate-50 transition-colors group">
                                <td class="px-6 py-4 font-bold text-slate-700">{{ user[0] }}</td>
                                <!-- License Key with Copy -->
                                <td class="px-6 py-4">
                                    <button onclick="copyToClipboard('{{ user[1] }}')" class="flex items-center gap-2 text-xs font-mono bg-slate-100 hover:bg-blue-50 text-slate-500 hover:text-blue-600 px-2 py-1 rounded border border-slate-200 transition-colors" title="ចុចដើម្បី Copy">
                                        <i class="fas fa-key"></i> {{ user[1][:10] }}...
                                    </button>
                                </td>
                                <td class="px-6 py-4">
                                    {% if user[6] == 'Standard' %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-orange-100 text-orange-600 border border-orange-200">Standard</span>
                                    {% elif user[6] == 'Basic' %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-blue-100 text-blue-600 border border-blue-200">Basic</span>
                                    {% else %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-purple-100 text-purple-600 border border-purple-200">Mini</span>{% endif %}
                                </td>
                                <!-- Credits Management -->
                                <td class="px-6 py-4">
                                    <div class="flex flex-col items-center gap-1">
                                        <span class="font-bold text-lg {{ 'text-emerald-500' if user[2] > 50 else 'text-red-500' }}">{{ user[2] }}</span>
                                        <div class="flex items-center gap-1 opacity-50 group-hover:opacity-100 transition-opacity">
                                            <a href="/adjust_credits/{{ user[0] }}/100" class="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded hover:bg-green-200">+100</a>
                                            <a href="/adjust_credits/{{ user[0] }}/-100" class="text-[10px] bg-red-100 text-red-700 px-1.5 py-0.5 rounded hover:bg-red-200">-100</a>
                                        </div>
                                        <form action="/update_credits" method="POST" class="flex items-center justify-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <input type="hidden" name="username" value="{{ user[0] }}">
                                            <input type="number" name="amount" placeholder="+/-" class="w-14 px-1 py-0.5 text-xs border rounded focus:ring-1 focus:ring-indigo-500 outline-none text-center">
                                            <button type="submit" class="text-xs bg-indigo-500 text-white px-2 py-0.5 rounded hover:bg-indigo-600">OK</button>
                                        </form>
                                    </div>
                                </td>
                                <!-- Status Toggle Dropdown -->
                                <td class="px-6 py-4">
                                    <form action="/set_status" method="POST">
                                        <input type="hidden" name="username" value="{{ user[0] }}">
                                        <select name="status" onchange="this.form.submit()" class="text-xs font-bold py-1 px-2 rounded border cursor-pointer outline-none 
                                            {% if user[5] == 'active' %}bg-emerald-100 text-emerald-700 border-emerald-200
                                            {% elif user[5] == 'inactive' %}bg-gray-100 text-gray-700 border-gray-200
                                            {% elif user[5] == 'suspended' %}bg-yellow-100 text-yellow-700 border-yellow-200
                                            {% else %}bg-red-100 text-red-700 border-red-200{% endif %}">
                                            <option value="active" {% if user[5] == 'active' %}selected{% endif %}>Active</option>
                                            <option value="inactive" {% if user[5] == 'inactive' %}selected{% endif %}>Inactive</option>
                                            <option value="suspended" {% if user[5] == 'suspended' %}selected{% endif %}>Suspend</option>
                                            <option value="banned" {% if user[5] == 'banned' %}selected{% endif %}>Banned</option>
                                        </select>
                                    </form>
                                </td>
                                <td class="px-6 py-4 text-right">
                                    <div class="flex items-center justify-end gap-2 opacity-50 group-hover:opacity-100 transition-opacity">
                                        <a href="/delete_user/{{ user[0] }}" class="p-1.5 bg-red-50 rounded-md text-red-400 hover:bg-red-100 hover:text-red-600 transition-colors" onclick="return confirm('តើអ្នកច្បាស់ទេថាចង់លុប?')" title="លុបចោល"><i class="fas fa-trash-alt"></i></a>
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
                            <td class="px-6 py-4 font-mono font-bold text-slate-700 select-all cursor-pointer" onclick="copyToClipboard('{{ v[0] }}')">{{ v[0] }}</td>
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
                <p class="text-sm text-slate-500 mb-6 relative z-10">IP ទាំងនេះត្រូវបានបិទដោយស្វ័យប្រវត្តិ។</p>
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
                <h4 class="font-bold text-lg mb-4 flex items-center gap-2"><i class="fas fa-sync-alt"></i> អាប់ដេតកម្មវិធី (App Updates)</h4>
                
                <form action="/update_settings" method="POST" enctype="multipart/form-data" class="space-y-4">
                    <div class="flex items-center justify-between bg-white/10 p-4 rounded-lg backdrop-blur-sm border border-white/20">
                        <div>
                            <h5 class="font-bold text-white">បង្ហាញផ្ទាំង Update</h5>
                            <p class="text-xs text-white/70">បើកមុខងារនេះដើម្បីឲ្យ User ឃើញថាមាន Version ថ្មី។</p>
                        </div>
                        <label class="switch">
                            <input type="checkbox" name="update_is_live" {% if update_is_live == '1' %}checked{% endif %}>
                            <span class="slider"></span>
                        </label>
                    </div>

                    <div class="flex gap-4">
                        <div class="w-1/3">
                            <label class="text-xs font-bold text-white/70 block mb-1">Latest Version</label>
                            <input type="text" name="latest_version" value="{{ latest_version }}" class="w-full bg-white/20 border border-white/30 rounded-lg px-3 py-2 text-white placeholder-white/60 focus:bg-white/30 outline-none backdrop-blur-sm" placeholder="Ex: 25.12.11">
                        </div>
                        <div class="flex-1">
                            <label class="text-xs font-bold text-white/70 block mb-1">Upload File (.py)</label>
                            <input type="file" name="update_file" class="w-full bg-white/20 border border-white/30 rounded-lg px-3 py-1.5 text-white text-sm focus:bg-white/30 outline-none backdrop-blur-sm">
                            {% if update_filename %}
                            <p class="text-xs text-emerald-300 mt-1"><i class="fas fa-check-circle"></i> Current: {{ update_filename }}</p>
                            {% endif %}
                        </div>
                    </div>
                    <div>
                        <label class="text-xs font-bold text-white/70 block mb-1">បរិយាយ (Description)</label>
                        <textarea name="update_desc" class="w-full bg-white/20 border border-white/30 rounded-lg px-3 py-2 text-white placeholder-white/60 focus:bg-white/30 outline-none backdrop-blur-sm h-20">{{ update_desc }}</textarea>
                    </div>
                    <button class="bg-white text-blue-600 font-bold px-6 py-2.5 rounded-lg hover:bg-blue-50 shadow-lg w-full">រក្សាទុក</button>
                </form>
            </div>

            <!-- Broadcast -->
            <div class="bg-gradient-to-r from-indigo-600 to-purple-600 rounded-2xl p-6 text-white shadow-xl shadow-indigo-200 mb-8">
                <h4 class="font-bold text-lg mb-2 flex items-center gap-2"><i class="fas fa-bullhorn"></i> ផ្សព្វផ្សាយដំណឹង (Broadcast)</h4>
                <p class="text-white/80 text-sm mb-4">សារនេះនឹងលោតរត់នៅខាងលើកម្មវិធីរបស់អ្នកប្រើប្រាស់។</p>
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
                    <thead class="bg-slate-50 text-slate-500 text-xs uppercase border-b border-slate-100"><tr><th class="px-6 py-4">ពេលវេលា</th><th class="px-6 py-4">អ្នកប្រើប្រាស់</th><th class="px-6 py-4">សកម្មភាព</th><th class="px-6 py-4">ចំណាយ</th></tr></thead>
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
        <h2 class="text-2xl font-bold text-gray-800 mb-2">Admin Portal</h2>
        <p class="text-sm text-gray-500 mb-8">Secure Gateway Access</p>
        
        <form method="POST" class="space-y-4">
            <input type="password" name="password" placeholder="Access Key" class="w-full px-4 py-3 rounded-lg border border-gray-300 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 outline-none transition" required>
            <button class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 rounded-lg transition duration-200 shadow-lg shadow-indigo-500/30">
                ចូលប្រព័ន្ធ
            </button>
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
    c.execute("SELECT username, api_key, credits, expiry_date, is_active, status, plan FROM users ORDER BY created_at DESC")
    users = c.fetchall(); conn.close()
    
    # Check if a new user was just added to show modal
    new_user_data = session.pop('new_user_data', None)
    
    return render_template_string(MODERN_DASHBOARD_HTML, page='users', users=users, total_users=len(users), 
                                  active_users=sum(1 for u in users if u[5] == 'active'), 
                                  total_credits=sum(u[2] for u in users),
                                  new_user_data=new_user_data)

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
    update_is_live = get_setting('update_is_live', '0')
    update_filename = get_setting('update_filename', '')
    
    costs = {'sora_2': get_setting('cost_sora_2', 25), 'sora_2_pro': get_setting('cost_sora_2_pro', 35)}
    limits = {'mini': get_setting('limit_mini', 1), 'basic': get_setting('limit_basic', 2), 'standard': get_setting('limit_standard', 3)}
    
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', api_key=k, broadcast_msg=msg, broadcast_color=clr, 
                                  costs=costs, limits=limits, latest_version=latest_ver, update_desc=update_desc,
                                  update_is_live=update_is_live, update_filename=update_filename)

# --- ACTION ROUTES ---
@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    try:
        conn = get_db()
        username = request.form['username']
        api_key = "sk-" + str(uuid.uuid4())
        
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, 1, 'active', ?, ?)", 
                     (username, api_key, int(request.form['credits']), request.form['expiry'], datetime.now().strftime("%Y-%m-%d"), request.form['plan']))
        conn.commit(); conn.close()
        
        # Store new user data in session to show modal on dashboard
        session['new_user_data'] = {'username': username, 'key': api_key}
        # No flash message needed, the modal covers it
    except Exception as e:
        flash(f"បរាជ័យ: {str(e)}", "error")
    return redirect('/dashboard')

@app.route('/delete_user/<username>')
@login_required
def delete_user(username):
    conn = get_db(); conn.execute("DELETE FROM users WHERE username=?", (username,)); conn.commit(); conn.close()
    flash(f"បានលុបអ្នកប្រើប្រាស់ '{username}' ដោយជោគជ័យ!")
    return redirect('/dashboard')

@app.route('/set_status', methods=['POST'])
@login_required
def set_status():
    username = request.form['username']
    status = request.form['status']
    conn = get_db()
    conn.execute("UPDATE users SET status = ? WHERE username=?", (status, username))
    conn.commit(); conn.close()
    flash(f"បានប្តូរស្ថានភាព '{username}' ទៅជា '{status}'")
    return redirect('/dashboard')

@app.route('/update_credits', methods=['POST'])
@login_required
def update_credits():
    try:
        amount = int(request.form['amount'])
        username = request.form['username']
        conn = get_db()
        conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", (amount, username))
        conn.execute("UPDATE users SET credits = 0 WHERE credits < 0 AND username = ?", (username,))
        conn.commit(); conn.close()
        action = "បន្ថែម" if amount > 0 else "ដក"
        flash(f"បាន{action} {abs(amount)} ក្រេឌីត ជូន '{username}'")
    except:
        flash("បញ្ហាក្នុងការកែប្រែក្រេឌីត", "error")
    return redirect('/dashboard')

@app.route('/adjust_credits/<username>/<int:amount>')
@login_required
def adjust_credits(username, amount):
    conn = get_db()
    conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", (amount, username))
    conn.execute("UPDATE users SET credits = 0 WHERE credits < 0 AND username = ?", (username,))
    conn.commit(); conn.close()
    action = "បន្ថែម" if amount > 0 else "ដក"
    flash(f"បាន{action} {abs(amount)} ក្រេឌីត ជូន '{username}'")
    return redirect('/dashboard')

@app.route('/generate_vouchers', methods=['POST'])
@login_required
def generate_vouchers():
    amt = int(request.form['amount']); qty = int(request.form['count'])
    conn = get_db()
    for _ in range(qty):
        conn.execute("INSERT INTO vouchers VALUES (?, ?, 0, ?, NULL)", (generate_voucher_code(amt), amt, str(datetime.now())))
    conn.commit(); conn.close()
    flash(f"បានបង្កើត Voucher ចំនួន {qty} សន្លឹក")
    return redirect('/vouchers')

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    if 'latest_version' in request.form: set_setting('latest_version', request.form.get('latest_version'))
    if 'update_desc' in request.form: set_setting('update_desc', request.form.get('update_desc'))
    
    is_live = '1' if request.form.get('update_is_live') else '0'
    set_setting('update_is_live', is_live)

    if 'update_file' in request.files:
        file = request.files['update_file']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            set_setting('update_filename', filename)

    if 'sora_api_key' in request.form: set_setting('sora_api_key', request.form.get('sora_api_key'))
    if 'cost_sora_2' in request.form: set_setting('cost_sora_2', request.form.get('cost_sora_2'))
    if 'cost_sora_2_pro' in request.form: set_setting('cost_sora_2_pro', request.form.get('cost_sora_2_pro'))
    
    if 'limit_mini' in request.form: set_setting('limit_mini', request.form.get('limit_mini'))
    if 'limit_basic' in request.form: set_setting('limit_basic', request.form.get('limit_basic'))
    if 'limit_standard' in request.form: set_setting('limit_standard', request.form.get('limit_standard'))

    flash("បានរក្សាទុកការកំណត់!", "success")
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
    c.execute("SELECT credits, expiry_date, is_active, plan, status FROM users WHERE username=? AND api_key=?", (d.get('username'), d.get('api_key')))
    u = c.fetchone()
    
    b = get_setting('broadcast_msg', '')
    bc = get_setting('broadcast_color', '#FF0000')
    lv = get_setting('latest_version', '1.0.0')
    ud = get_setting('update_desc', 'Improvements')
    live = get_setting('update_is_live', '0')
    fname = get_setting('update_filename', '')
    
    dl_url = ""
    if fname: dl_url = f"{request.url_root}static/updates/{fname}"
    conn.close()
    
    if not u: return jsonify({"valid": False, "message": "Invalid Credentials"})
    if not u[2]: return jsonify({"valid": False, "message": "Account Banned"})
    if u[4] == 'banned': return jsonify({"valid": False, "message": "Account Banned"})
    if u[4] == 'suspended': return jsonify({"valid": False, "message": "Account Suspended"})
    if u[4] == 'inactive': return jsonify({"valid": False, "message": "Account Inactive"})
    if datetime.now() > datetime.strptime(u[1], "%Y-%m-%d"): return jsonify({"valid": False, "message": "License Expired"})
    
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
        "update_desc": ud,
        "update_is_live": live == '1',
        "download_url": dl_url
    })

@app.route('/api/redeem', methods=['POST'])
def redeem():
    d = request.json
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT amount, is_used FROM vouchers WHERE code=?", (d.get('code'),))
    v = c.fetchone()
    if not v or v[1]: conn.close(); return jsonify({"success": False, "message": "កូដមិនត្រឹមត្រូវ ឬបានប្រើរួច"})
    c.execute("UPDATE users SET credits=credits+? WHERE username=?", (v[0], d.get('username')))
    c.execute("UPDATE vouchers SET is_used=1, used_by=? WHERE code=?", (d.get('username'), d.get('code')))
    conn.commit(); conn.close()
    return jsonify({"success": True, "message": f"បានបញ្ចូល {v[0]} ក្រេឌីត"})

@app.route('/api/proxy/generate', methods=['POST'])
def proxy_gen():
    auth = request.headers.get("Client-Auth", ""); 
    if ":" not in auth: return jsonify({"code":-1}), 401
    u, k = auth.split(":")
    conn = get_db(); row = conn.execute("SELECT credits, is_active, status FROM users WHERE username=? AND api_key=?", (u,k)).fetchone()
    if not row: conn.close(); return jsonify({"code":-1}), 401
    if row[2] != 'active': conn.close(); return jsonify({"code":-1, "message": "Account Not Active"}), 403
    
    model = request.json.get('model', '')
    cost = int(get_setting('cost_sora_2_pro', 35)) if "pro" in model else int(get_setting('cost_sora_2', 25))
    if row[0] < cost: conn.close(); return jsonify({"code":-1, "message": "ក្រេឌីតមិនគ្រប់គ្រាន់"}), 402
    
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
