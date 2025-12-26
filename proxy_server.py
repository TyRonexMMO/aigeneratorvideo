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
app.secret_key = os.environ.get("FLASK_SECRET", "super_secret_admin_key_v3_premium")

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

# Default Settings
DEFAULT_COSTS = {'sora_2': 25, 'sora_2_pro': 35}
DEFAULT_LIMITS = {'mini': 1, 'basic': 2, 'standard': 3, 'premium': 5}

# --- DATABASE SETUP & MIGRATION ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, api_key TEXT, credits INTEGER, expiry_date TEXT, is_active INTEGER, created_at TEXT, plan TEXT DEFAULT 'Standard')''')
    
    # Check and Add New Columns for Users (Migration)
    try: c.execute("ALTER TABLE users ADD COLUMN custom_limit INTEGER")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN custom_cost_sora2 INTEGER")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN custom_cost_sora2_pro INTEGER")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN assigned_api_group TEXT")
    except: pass

    # Logs Table
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, cost INTEGER, timestamp TEXT)''')
    
    # Settings Table
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    # Vouchers Table (Enhanced)
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers
                 (code TEXT PRIMARY KEY, amount INTEGER, is_used INTEGER, created_at TEXT, used_by TEXT)''')
    try: c.execute("ALTER TABLE vouchers ADD COLUMN max_uses INTEGER DEFAULT 1")
    except: pass
    try: c.execute("ALTER TABLE vouchers ADD COLUMN current_uses INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE vouchers ADD COLUMN expiry_date TEXT")
    except: pass

    # Tasks Table
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (task_id TEXT PRIMARY KEY, username TEXT, cost INTEGER, status TEXT, created_at TEXT)''')
    
    # Banned IPs
    c.execute('''CREATE TABLE IF NOT EXISTS banned_ips
                 (ip TEXT PRIMARY KEY, reason TEXT, banned_at TEXT)''')

    # API Keys Management
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, key_value TEXT, label TEXT, group_name TEXT, is_active INTEGER DEFAULT 1)''')
    
    # User Activity / Heartbeat
    c.execute('''CREATE TABLE IF NOT EXISTS user_activity
                 (username TEXT PRIMARY KEY, last_seen TEXT, session_start TEXT, daily_success INTEGER DEFAULT 0, daily_fail INTEGER DEFAULT 0)''')

    # Default Settings
    defaults = {
        'cost_sora_2': '25', 'cost_sora_2_pro': '35',
        'limit_mini': '1', 'limit_basic': '2', 'limit_standard': '3', 'limit_premium': '5',
        'broadcast_msg': '', 'broadcast_color': '#FF0000',
        'latest_version': '1.0.0', 'update_desc': 'Initial Release',
        'update_is_live': '0', 'update_filename': ''
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
    return row['value'] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit(); conn.close()

def generate_voucher_code(amount):
    chars = string.ascii_uppercase + string.digits
    return f"SORA-{amount}-{''.join(random.choices(chars, k=8))}"

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_active_api_key(group_name=None):
    conn = get_db()
    if group_name and group_name != 'default':
        rows = conn.execute("SELECT key_value FROM api_keys WHERE is_active=1 AND group_name=?", (group_name,)).fetchall()
    else:
        rows = conn.execute("SELECT key_value FROM api_keys WHERE is_active=1").fetchall()
    conn.close()
    
    if not rows:
        # Fallback to legacy single key setting if table empty
        return get_setting('sora_api_key', 'sk-DEFAULT')
    
    return random.choice(rows)['key_value']

# --- AUTH DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return redirect(f'/{ADMIN_LOGIN_PATH}')
        return f(*args, **kwargs)
    return decorated_function

# --- MODERN DASHBOARD HTML ---
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
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        tailwind.config = { theme: { extend: { fontFamily: { sans: ['"Kantumruy Pro"', 'sans-serif'] }, colors: { primary: '#4F46E5', secondary: '#64748b' } } } }
    </script>
    <style>
        body { font-family: 'Kantumruy Pro', sans-serif; }
        .sidebar-link.active { background-color: #4F46E5; color: white; border-radius: 12px; }
        .sidebar-link:hover:not(.active) { background-color: #EEF2FF; color: #4F46E5; border-radius: 12px; }
        /* Modal */
        .modal { transition: opacity 0.25s ease; }
        body.modal-active { overflow-x: hidden; overflow-y: visible !important; }
        .switch { position: relative; display: inline-block; width: 40px; height: 20px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #cbd5e1; transition: .4s; border-radius: 34px; }
        .slider:before { position: absolute; content: ""; height: 16px; width: 16px; left: 2px; bottom: 2px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #4F46E5; }
        input:checked + .slider:before { transform: translateX(20px); }
    </style>
</head>
<body class="bg-slate-50 text-slate-800 flex h-screen overflow-hidden">

    <!-- Sidebar -->
    <aside class="w-64 bg-white border-r border-slate-200 hidden md:flex flex-col z-20">
        <div class="h-16 flex items-center px-6 border-b border-slate-100">
            <span class="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-purple-600">SoraAdmin <span class="text-xs text-slate-400">PRO</span></span>
        </div>
        <nav class="flex-1 overflow-y-auto p-4 space-y-1">
            <p class="px-4 text-xs font-bold text-slate-400 uppercase mb-2 mt-2">Core</p>
            <a href="/dashboard" class="sidebar-link flex items-center px-4 py-3 {{ 'active' if page == 'users' else 'text-slate-600' }}">
                <i class="fas fa-users w-6"></i> <span>អ្នកប្រើប្រាស់</span>
            </a>
            <a href="/tracking" class="sidebar-link flex items-center px-4 py-3 {{ 'active' if page == 'tracking' else 'text-slate-600' }}">
                <i class="fas fa-chart-line w-6"></i> <span>តាមដាន (Tracking)</span>
            </a>
            <a href="/vouchers" class="sidebar-link flex items-center px-4 py-3 {{ 'active' if page == 'vouchers' else 'text-slate-600' }}">
                <i class="fas fa-ticket-alt w-6"></i> <span>ប័ណ្ណ (Vouchers)</span>
            </a>
            
            <p class="px-4 text-xs font-bold text-slate-400 uppercase mb-2 mt-6">System</p>
            <a href="/api_manager" class="sidebar-link flex items-center px-4 py-3 {{ 'active' if page == 'api' else 'text-slate-600' }}">
                <i class="fas fa-key w-6"></i> <span>API Keys</span>
            </a>
            <a href="/settings" class="sidebar-link flex items-center px-4 py-3 {{ 'active' if page == 'settings' else 'text-slate-600' }}">
                <i class="fas fa-cogs w-6"></i> <span>ការកំណត់</span>
            </a>
            <a href="/security" class="sidebar-link flex items-center px-4 py-3 {{ 'active' if page == 'security' else 'text-slate-600' }}">
                <i class="fas fa-shield-alt w-6"></i> <span>សុវត្ថិភាព</span>
            </a>
        </nav>
        <div class="p-4 border-t border-slate-100">
            <a href="/logout" class="flex items-center justify-center w-full px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100"><i class="fas fa-sign-out-alt mr-2"></i> Log Out</a>
        </div>
    </aside>

    <!-- Main -->
    <main class="flex-1 h-full overflow-y-auto relative">
        <!-- Header -->
        <header class="bg-white/80 backdrop-blur-md sticky top-0 z-10 border-b border-slate-200 px-8 py-4 flex justify-between items-center">
            <h2 class="text-lg font-bold text-slate-800">{{ page_title }}</h2>
            <div class="flex items-center gap-4">
                <div class="flex items-center gap-2 px-3 py-1 bg-emerald-100 text-emerald-700 rounded-full text-xs font-bold">
                    <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span> Service Active
                </div>
            </div>
        </header>

        <div class="p-8 pb-20">
            {% if page == 'users' %}
            
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                    <p class="text-xs text-slate-400 font-bold uppercase">Total Users</p>
                    <h3 class="text-3xl font-bold text-slate-800">{{ users|length }}</h3>
                </div>
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                    <p class="text-xs text-slate-400 font-bold uppercase">Active Premium</p>
                    <h3 class="text-3xl font-bold text-purple-600">{{ users|selectattr('plan', 'equalto', 'Premium')|list|length }}</h3>
                </div>
            </div>

            <!-- Add User -->
            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 mb-8">
                <h3 class="text-lg font-bold mb-4">Add New User</h3>
                <form action="/add_user" method="POST" class="flex gap-4 items-end flex-wrap">
                    <div class="w-48">
                        <label class="block text-xs font-bold text-slate-500 mb-1">Username</label>
                        <input type="text" name="username" required class="w-full bg-slate-50 border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary outline-none">
                    </div>
                    <div class="w-32">
                        <label class="block text-xs font-bold text-slate-500 mb-1">Credits</label>
                        <input type="number" name="credits" value="500" class="w-full bg-slate-50 border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary outline-none">
                    </div>
                    <div class="w-40">
                        <label class="block text-xs font-bold text-slate-500 mb-1">Plan</label>
                        <select name="plan" class="w-full bg-slate-50 border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary outline-none">
                            <option value="Mini">Mini</option>
                            <option value="Basic">Basic</option>
                            <option value="Standard" selected>Standard</option>
                            <option value="Premium">Premium</option>
                        </select>
                    </div>
                    <div class="w-40">
                        <label class="block text-xs font-bold text-slate-500 mb-1">Expiry</label>
                        <input type="date" name="expiry" required class="w-full bg-slate-50 border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary outline-none">
                    </div>
                    <button class="bg-primary text-white font-bold px-6 py-2 rounded-lg hover:bg-indigo-600 transition">Create</button>
                </form>
            </div>

            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                <table class="w-full text-sm text-left">
                    <thead class="bg-slate-50 text-slate-500 uppercase text-xs">
                        <tr>
                            <th class="px-6 py-4">User</th>
                            <th class="px-6 py-4">Plan</th>
                            <th class="px-6 py-4">Limits (Cust)</th>
                            <th class="px-6 py-4">Cost (S/P)</th>
                            <th class="px-6 py-4">Credits</th>
                            <th class="px-6 py-4 text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for u in users %}
                        <tr class="hover:bg-slate-50 group">
                            <td class="px-6 py-4">
                                <div class="font-bold text-slate-700">{{ u.username }}</div>
                                <div class="text-xs text-slate-400 font-mono">{{ u.api_key[:10] }}...</div>
                            </td>
                            <td class="px-6 py-4">
                                <span class="px-2 py-1 rounded text-xs font-bold {{ 'bg-purple-100 text-purple-700' if u.plan == 'Premium' else 'bg-slate-100 text-slate-600' }}">{{ u.plan }}</span>
                            </td>
                            <td class="px-6 py-4">
                                {% if u.custom_limit %}
                                    <span class="text-orange-600 font-bold" title="Custom Limit">{{ u.custom_limit }}</span>
                                {% else %}
                                    <span class="text-slate-400" title="Plan Default">Default</span>
                                {% endif %}
                            </td>
                            <td class="px-6 py-4 text-xs">
                                {% if u.custom_cost_sora2 %}
                                    <span class="text-emerald-600 font-bold">{{ u.custom_cost_sora2 }}</span> / <span class="text-emerald-600 font-bold">{{ u.custom_cost_sora2_pro }}</span>
                                {% else %}
                                    <span class="text-slate-400">Global</span>
                                {% endif %}
                            </td>
                            <td class="px-6 py-4 font-bold {{ 'text-red-500' if u.credits < 50 else 'text-emerald-500' }}">{{ u.credits }}</td>
                            <td class="px-6 py-4 text-right flex justify-end gap-2">
                                <button onclick="openEditModal('{{ u.username }}', '{{ u.plan }}', '{{ u.custom_limit or '' }}', '{{ u.custom_cost_sora2 or '' }}', '{{ u.custom_cost_sora2_pro or '' }}', '{{ u.assigned_api_group or 'default' }}')" class="p-2 bg-blue-50 text-blue-600 rounded hover:bg-blue-100"><i class="fas fa-edit"></i></button>
                                <a href="/delete_user/{{ u.username }}" onclick="return confirm('Delete?')" class="p-2 bg-red-50 text-red-600 rounded hover:bg-red-100"><i class="fas fa-trash"></i></a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            <!-- Edit User Modal -->
            <div id="editModal" class="modal opacity-0 pointer-events-none fixed w-full h-full top-0 left-0 flex items-center justify-center z-50">
                <div class="modal-overlay absolute w-full h-full bg-black/50 backdrop-blur-sm" onclick="closeEditModal()"></div>
                <div class="modal-container bg-white w-11/12 md:max-w-md mx-auto rounded-2xl shadow-2xl z-50 overflow-y-auto">
                    <div class="modal-content py-4 text-left px-6">
                        <div class="flex justify-between items-center pb-3">
                            <p class="text-xl font-bold">Edit User: <span id="modalUser" class="text-primary"></span></p>
                            <div class="cursor-pointer z-50" onclick="closeEditModal()"><i class="fas fa-times"></i></div>
                        </div>
                        <form action="/update_user_details" method="POST" class="space-y-4">
                            <input type="hidden" name="username" id="editUsername">
                            
                            <div>
                                <label class="text-xs font-bold text-slate-500">Plan</label>
                                <select name="plan" id="editPlan" class="w-full border rounded-lg px-3 py-2 bg-slate-50">
                                    <option value="Mini">Mini</option><option value="Basic">Basic</option>
                                    <option value="Standard">Standard</option><option value="Premium">Premium</option>
                                </select>
                            </div>
                            
                            <div>
                                <label class="text-xs font-bold text-slate-500">Custom Limit (Leave empty for default)</label>
                                <input type="number" name="custom_limit" id="editLimit" class="w-full border rounded-lg px-3 py-2 bg-slate-50" placeholder="Ex: 10">
                            </div>

                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="text-xs font-bold text-slate-500">SORA-2 Cost</label>
                                    <input type="number" name="custom_cost_sora2" id="editCost2" class="w-full border rounded-lg px-3 py-2 bg-slate-50" placeholder="Default">
                                </div>
                                <div>
                                    <label class="text-xs font-bold text-slate-500">PRO Cost</label>
                                    <input type="number" name="custom_cost_sora2_pro" id="editCost2Pro" class="w-full border rounded-lg px-3 py-2 bg-slate-50" placeholder="Default">
                                </div>
                            </div>

                            <div>
                                <label class="text-xs font-bold text-slate-500">Assigned API Key Group</label>
                                <select name="api_group" id="editApiGroup" class="w-full border rounded-lg px-3 py-2 bg-slate-50">
                                    <option value="default">Default Pool</option>
                                    {% for g in api_groups %}
                                    <option value="{{ g }}">{{ g }}</option>
                                    {% endfor %}
                                </select>
                            </div>

                            <div class="pt-4">
                                <button type="submit" class="w-full bg-primary text-white font-bold py-3 rounded-xl shadow-lg hover:bg-indigo-600">Save Changes</button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>

            {% elif page == 'tracking' %}
            <div class="max-w-6xl mx-auto">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                     <!-- Online Users Card -->
                     <div class="bg-gradient-to-r from-emerald-500 to-teal-500 rounded-2xl p-6 text-white shadow-lg">
                         <div class="flex justify-between items-start">
                             <div>
                                 <p class="text-emerald-100 font-bold text-xs uppercase">Online Now</p>
                                 <h3 class="text-4xl font-bold mt-1">{{ online_users }}</h3>
                             </div>
                             <div class="p-3 bg-white/20 rounded-xl"><i class="fas fa-signal"></i></div>
                         </div>
                     </div>
                </div>

                <div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
                    <h3 class="font-bold text-lg mb-4">Live User Activity</h3>
                    <div class="overflow-x-auto">
                        <table class="w-full text-sm">
                            <thead class="bg-slate-50 text-xs uppercase text-slate-500">
                                <tr>
                                    <th class="px-6 py-3 text-left">User</th>
                                    <th class="px-6 py-3 text-left">Status</th>
                                    <th class="px-6 py-3 text-left">Session Duration</th>
                                    <th class="px-6 py-3 text-left">Today's Gen (Success/Fail)</th>
                                    <th class="px-6 py-3 text-left">Last Seen</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-slate-100">
                                {% for act in activity %}
                                <tr>
                                    <td class="px-6 py-4 font-bold">{{ act.username }}</td>
                                    <td class="px-6 py-4">
                                        {% if act.is_online %}
                                        <span class="inline-flex items-center gap-1 text-emerald-600 text-xs font-bold"><span class="w-2 h-2 rounded-full bg-emerald-500"></span> Online</span>
                                        {% else %}
                                        <span class="text-slate-400 text-xs">Offline</span>
                                        {% endif %}
                                    </td>
                                    <td class="px-6 py-4 font-mono text-xs">{{ act.duration }}</td>
                                    <td class="px-6 py-4">
                                        <span class="text-emerald-600 font-bold">{{ act.daily_success }}</span> / <span class="text-red-500 font-bold">{{ act.daily_fail }}</span>
                                    </td>
                                    <td class="px-6 py-4 text-xs text-slate-500">{{ act.last_seen }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            {% elif page == 'api' %}
            <div class="max-w-4xl mx-auto">
                <div class="flex justify-between items-end mb-6">
                    <h3 class="text-2xl font-bold">API Key Management</h3>
                </div>
                
                <!-- Add Key Form -->
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 mb-8">
                    <h4 class="font-bold text-sm text-slate-500 uppercase mb-4">Add New Key</h4>
                    <form action="/add_api_key" method="POST" class="grid grid-cols-1 md:grid-cols-4 gap-4">
                        <div class="md:col-span-2">
                            <input type="text" name="key_value" placeholder="sk-..." class="w-full border rounded-lg px-3 py-2 text-sm" required>
                        </div>
                        <input type="text" name="group_name" placeholder="Group (e.g. vip_pool)" class="w-full border rounded-lg px-3 py-2 text-sm" list="groups_list">
                        <datalist id="groups_list"><option value="default"><option value="vip"></datalist>
                        <button class="bg-indigo-600 text-white font-bold rounded-lg px-4 py-2 hover:bg-indigo-700">Add Key</button>
                    </form>
                </div>

                <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-slate-50 text-xs uppercase text-slate-500">
                            <tr><th class="px-6 py-3">Key (Preview)</th><th class="px-6 py-3">Group</th><th class="px-6 py-3">Status</th><th class="px-6 py-3 text-right">Action</th></tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            {% for key in api_keys %}
                            <tr>
                                <td class="px-6 py-4 font-mono text-xs text-slate-600">...{{ key.key_value[-8:] }}</td>
                                <td class="px-6 py-4"><span class="bg-slate-100 px-2 py-1 rounded text-xs font-bold">{{ key.group_name or 'default' }}</span></td>
                                <td class="px-6 py-4">
                                    {% if key.is_active %} <span class="text-emerald-600 text-xs font-bold">Active</span>
                                    {% else %} <span class="text-red-500 text-xs font-bold">Inactive</span> {% endif %}
                                </td>
                                <td class="px-6 py-4 text-right">
                                    <a href="/toggle_api_key/{{ key.id }}" class="text-slate-500 hover:text-primary"><i class="fas fa-power-off"></i></a>
                                    <a href="/delete_api_key/{{ key.id }}" class="text-red-400 hover:text-red-600 ml-3" onclick="return confirm('Delete?')"><i class="fas fa-trash"></i></a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            {% elif page == 'vouchers' %}
            <div class="max-w-5xl mx-auto">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 mb-8">
                    <h3 class="font-bold text-lg mb-4 flex items-center gap-2"><i class="fas fa-ticket-alt text-primary"></i> Create Advanced Vouchers</h3>
                    <form action="/generate_vouchers" method="POST" class="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
                        <div><label class="block text-xs font-bold text-slate-500 mb-1">Credits Amount</label><input type="number" name="amount" required class="w-full border rounded-lg px-3 py-2 bg-slate-50"></div>
                        <div><label class="block text-xs font-bold text-slate-500 mb-1">Max Users (Usage Limit)</label><input type="number" name="max_uses" value="1" min="1" class="w-full border rounded-lg px-3 py-2 bg-slate-50"></div>
                        <div><label class="block text-xs font-bold text-slate-500 mb-1">Expiry Date</label><input type="date" name="expiry" class="w-full border rounded-lg px-3 py-2 bg-slate-50"></div>
                        <div><label class="block text-xs font-bold text-slate-500 mb-1">Qty to Generate</label><input type="number" name="count" value="1" class="w-full border rounded-lg px-3 py-2 bg-slate-50"></div>
                        <button class="bg-primary text-white font-bold py-2 rounded-lg hover:bg-indigo-700">Generate</button>
                    </form>
                </div>

                <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-slate-50 text-xs uppercase text-slate-500"><tr><th class="px-6 py-3">Code</th><th class="px-6 py-3">Value</th><th class="px-6 py-3">Usage</th><th class="px-6 py-3">Expiry</th><th class="px-6 py-3 text-right">Status</th></tr></thead>
                        <tbody class="divide-y divide-slate-100">
                            {% for v in vouchers %}
                            <tr>
                                <td class="px-6 py-4 font-mono font-bold select-all">{{ v.code }}</td>
                                <td class="px-6 py-4 text-emerald-600 font-bold">+{{ v.amount }}</td>
                                <td class="px-6 py-4 text-xs font-bold text-slate-600">{{ v.current_uses }} / {{ v.max_uses }}</td>
                                <td class="px-6 py-4 text-xs text-slate-500">{{ v.expiry_date or 'No Expiry' }}</td>
                                <td class="px-6 py-4 text-right">
                                    {% if v.current_uses >= v.max_uses %}<span class="px-2 py-1 bg-red-100 text-red-600 rounded text-xs font-bold">Depleted</span>
                                    {% else %}<span class="px-2 py-1 bg-green-100 text-green-600 rounded text-xs font-bold">Active</span>{% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            {% elif page == 'settings' %}
            <div class="max-w-4xl mx-auto">
                 <h2 class="text-2xl font-bold mb-6">Global Settings</h2>
                 
                 <!-- Update System -->
                 <div class="bg-gradient-to-r from-blue-600 to-cyan-600 rounded-2xl p-6 text-white shadow-xl mb-8">
                    <h4 class="font-bold text-lg mb-4 flex items-center gap-2"><i class="fas fa-cloud-upload-alt"></i> App Update System (Zip Support)</h4>
                    <form action="/update_settings" method="POST" enctype="multipart/form-data" class="space-y-4">
                        <div class="flex items-center justify-between bg-white/10 p-4 rounded-lg">
                            <span>Enable Update Notification</span>
                            <label class="switch"><input type="checkbox" name="update_is_live" {% if update_is_live == '1' %}checked{% endif %}><span class="slider"></span></label>
                        </div>
                        <div class="grid grid-cols-2 gap-4">
                            <div><label class="text-xs opacity-70 block mb-1">Version</label><input type="text" name="latest_version" value="{{ latest_version }}" class="w-full bg-white/20 border-white/30 rounded px-3 py-2 text-white"></div>
                            <div>
                                <label class="text-xs opacity-70 block mb-1">Upload File (.zip for auto-update)</label>
                                <input type="file" name="update_file" class="w-full bg-white/20 border-white/30 rounded px-3 py-1.5 text-sm text-white">
                                {% if update_filename %}<p class="text-xs text-green-300 mt-1">Current: {{ update_filename }}</p>{% endif %}
                            </div>
                        </div>
                        <div><label class="text-xs opacity-70 block mb-1">Changelog</label><textarea name="update_desc" class="w-full bg-white/20 border-white/30 rounded px-3 py-2 text-white h-20">{{ update_desc }}</textarea></div>
                        <button class="bg-white text-blue-600 font-bold px-6 py-2 rounded shadow hover:bg-blue-50">Save Update Config</button>
                    </form>
                 </div>

                 <!-- Global Limits & Costs -->
                 <form action="/update_settings" method="POST" class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                     <h4 class="font-bold text-slate-700 mb-4 pb-2 border-b">Global Limits & Costs</h4>
                     <div class="grid grid-cols-2 gap-6 mb-6">
                         <div>
                             <label class="text-xs font-bold text-slate-400 mb-2 block">Costs (Credits)</label>
                             <div class="space-y-2">
                                 <input type="number" name="cost_sora_2" value="{{ costs.sora_2 }}" class="w-full border rounded px-3 py-2">
                                 <input type="number" name="cost_sora_2_pro" value="{{ costs.sora_2_pro }}" class="w-full border rounded px-3 py-2">
                             </div>
                         </div>
                         <div>
                             <label class="text-xs font-bold text-slate-400 mb-2 block">Concurrency Limits</label>
                             <div class="grid grid-cols-2 gap-2">
                                 <input type="number" name="limit_mini" value="{{ limits.mini }}" placeholder="Mini" class="border rounded px-2 py-2">
                                 <input type="number" name="limit_basic" value="{{ limits.basic }}" placeholder="Basic" class="border rounded px-2 py-2">
                                 <input type="number" name="limit_standard" value="{{ limits.standard }}" placeholder="Std" class="border rounded px-2 py-2">
                                 <input type="number" name="limit_premium" value="{{ limits.premium }}" placeholder="Prem" class="border rounded px-2 py-2">
                             </div>
                         </div>
                     </div>
                     <button class="bg-slate-800 text-white font-bold px-6 py-2 rounded hover:bg-slate-900">Save Globals</button>
                 </form>
            </div>
            {% endif %}
        </div>
    </main>

    <script>
        function openEditModal(user, plan, limit, cost2, cost2p, group) {
            document.getElementById('editUsername').value = user;
            document.getElementById('modalUser').innerText = user;
            document.getElementById('editPlan').value = plan;
            document.getElementById('editLimit').value = limit;
            document.getElementById('editCost2').value = cost2;
            document.getElementById('editCost2Pro').value = cost2p;
            document.getElementById('editApiGroup').value = group;
            
            const modal = document.getElementById('editModal');
            modal.classList.remove('opacity-0', 'pointer-events-none');
            document.body.classList.add('modal-active');
        }
        function closeEditModal() {
            const modal = document.getElementById('editModal');
            modal.classList.add('opacity-0', 'pointer-events-none');
            document.body.classList.remove('modal-active');
        }
    </script>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secure Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 h-screen flex items-center justify-center">
    <div class="bg-white p-8 rounded-2xl shadow-2xl w-96">
        <h2 class="text-2xl font-bold text-slate-800 mb-6 text-center">Admin Access</h2>
        <form method="POST" class="space-y-4">
            <input type="password" name="password" placeholder="Passkey" class="w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none">
            <button class="w-full bg-indigo-600 text-white font-bold py-3 rounded-lg hover:bg-indigo-700">Unlock</button>
        </form>
    </div>
</body>
</html>
"""

# --- ROUTES ---
@app.route('/')
def home():
    return jsonify({"status": "Sora Server Online", "version": "3.0.0"}), 200

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

# --- DASHBOARD PAGES ---
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    groups = conn.execute("SELECT DISTINCT group_name FROM api_keys WHERE group_name IS NOT NULL").fetchall()
    api_groups = [g['group_name'] for g in groups]
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='users', page_title="User Management", users=users, api_groups=api_groups)

@app.route('/tracking')
@login_required
def tracking():
    conn = get_db()
    # Calculate online status (active in last 5 mins)
    five_min_ago = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    activity = []
    rows = conn.execute("SELECT * FROM user_activity ORDER BY last_seen DESC").fetchall()
    online_count = 0
    
    for r in rows:
        is_online = r['last_seen'] > five_min_ago
        if is_online: online_count += 1
        
        # Calculate Duration
        duration = "0m"
        try:
            start = datetime.strptime(r['session_start'], "%Y-%m-%d %H:%M:%S")
            last = datetime.strptime(r['last_seen'], "%Y-%m-%d %H:%M:%S")
            diff = last - start
            mins = int(diff.total_seconds() / 60)
            duration = f"{mins}m"
        except: pass

        activity.append({
            "username": r['username'],
            "is_online": is_online,
            "last_seen": r['last_seen'],
            "duration": duration,
            "daily_success": r['daily_success'],
            "daily_fail": r['daily_fail']
        })
        
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='tracking', page_title="Live Tracking", activity=activity, online_users=online_count)

@app.route('/api_manager')
@login_required
def api_manager():
    conn = get_db()
    keys = conn.execute("SELECT * FROM api_keys ORDER BY id DESC").fetchall()
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='api', page_title="API Configuration", api_keys=keys)

@app.route('/vouchers')
@login_required
def vouchers():
    conn = get_db()
    vouchers = conn.execute("SELECT * FROM vouchers ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template_string(MODERN_DASHBOARD_HTML, page='vouchers', page_title="Vouchers", vouchers=vouchers)

@app.route('/settings')
@login_required
def settings():
    latest_ver = get_setting('latest_version', '1.0.0')
    update_desc = get_setting('update_desc', 'Initial Release')
    update_is_live = get_setting('update_is_live', '0')
    update_filename = get_setting('update_filename', '')
    
    costs = {'sora_2': get_setting('cost_sora_2', 25), 'sora_2_pro': get_setting('cost_sora_2_pro', 35)}
    limits = {
        'mini': get_setting('limit_mini', 1), 'basic': get_setting('limit_basic', 2), 
        'standard': get_setting('limit_standard', 3), 'premium': get_setting('limit_premium', 5)
    }
    
    return render_template_string(MODERN_DASHBOARD_HTML, page='settings', page_title="System Settings",
                                  costs=costs, limits=limits, latest_version=latest_ver, update_desc=update_desc,
                                  update_is_live=update_is_live, update_filename=update_filename)

# --- ACTIONS ---
@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    try:
        conn = get_db()
        conn.execute("INSERT INTO users (username, api_key, credits, expiry_date, is_active, created_at, plan) VALUES (?, ?, ?, ?, 1, ?, ?)", 
                     (request.form['username'], "sk-"+str(uuid.uuid4())[:18], int(request.form['credits']), request.form['expiry'], datetime.now().strftime("%Y-%m-%d"), request.form['plan']))
        conn.commit(); conn.close()
    except Exception as e: print(e)
    return redirect('/dashboard')

@app.route('/update_user_details', methods=['POST'])
@login_required
def update_user_details():
    u = request.form.get('username')
    conn = get_db()
    
    # Handle empty strings as None
    limit = request.form.get('custom_limit') or None
    c2 = request.form.get('custom_cost_sora2') or None
    c2p = request.form.get('custom_cost_sora2_pro') or None
    grp = request.form.get('api_group')
    
    conn.execute('''UPDATE users SET plan=?, custom_limit=?, custom_cost_sora2=?, custom_cost_sora2_pro=?, assigned_api_group=? 
                    WHERE username=?''', 
                 (request.form['plan'], limit, c2, c2p, grp, u))
    conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/delete_user/<username>')
@login_required
def delete_user(username):
    conn = get_db(); conn.execute("DELETE FROM users WHERE username=?", (username,)); conn.commit(); conn.close()
    return redirect('/dashboard')

@app.route('/add_api_key', methods=['POST'])
@login_required
def add_api_key():
    conn = get_db()
    conn.execute("INSERT INTO api_keys (key_value, group_name) VALUES (?, ?)", (request.form['key_value'], request.form['group_name'] or 'default'))
    conn.commit(); conn.close()
    return redirect('/api_manager')

@app.route('/toggle_api_key/<int:kid>')
@login_required
def toggle_api_key(kid):
    conn = get_db()
    conn.execute("UPDATE api_keys SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?", (kid,))
    conn.commit(); conn.close()
    return redirect('/api_manager')

@app.route('/delete_api_key/<int:kid>')
@login_required
def delete_api_key(kid):
    conn = get_db(); conn.execute("DELETE FROM api_keys WHERE id=?", (kid,)); conn.commit(); conn.close()
    return redirect('/api_manager')

@app.route('/generate_vouchers', methods=['POST'])
@login_required
def generate_vouchers():
    amt = int(request.form['amount'])
    qty = int(request.form['count'])
    max_use = int(request.form['max_uses'])
    expiry = request.form.get('expiry') or None
    
    conn = get_db()
    for _ in range(qty):
        conn.execute("INSERT INTO vouchers (code, amount, is_used, created_at, max_uses, current_uses, expiry_date) VALUES (?, ?, 0, ?, ?, 0, ?)", 
                     (generate_voucher_code(amt), amt, str(datetime.now()), max_use, expiry))
    conn.commit(); conn.close()
    return redirect('/vouchers')

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    # Update File logic
    if 'update_file' in request.files:
        file = request.files['update_file']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            set_setting('update_filename', filename)
    
    form_map = {
        'latest_version': 'latest_version', 'update_desc': 'update_desc',
        'cost_sora_2': 'cost_sora_2', 'cost_sora_2_pro': 'cost_sora_2_pro',
        'limit_mini': 'limit_mini', 'limit_basic': 'limit_basic', 'limit_standard': 'limit_standard', 'limit_premium': 'limit_premium'
    }
    
    for form_key, db_key in form_map.items():
        if form_key in request.form: set_setting(db_key, request.form[form_key])

    set_setting('update_is_live', '1' if request.form.get('update_is_live') else '0')
    return redirect('/settings')

# --- CLIENT API ---

@app.route('/api/verify', methods=['POST'])
def verify_user():
    d = request.json
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE username=? AND api_key=?", (d.get('username'), d.get('api_key'))).fetchone()
    
    # Get Global Settings
    b_msg = get_setting('broadcast_msg', '')
    b_col = get_setting('broadcast_color', '#FF0000')
    l_ver = get_setting('latest_version', '1.0.0')
    u_desc = get_setting('update_desc', 'Improvements')
    u_live = get_setting('update_is_live', '0')
    u_file = get_setting('update_filename', '')
    
    dl_url = f"{request.url_root}static/updates/{u_file}" if u_file else ""

    if not u: conn.close(); return jsonify({"valid": False, "message": "Invalid Credentials"})
    if not u['is_active']: conn.close(); return jsonify({"valid": False, "message": "Banned"})
    if datetime.now() > datetime.strptime(u['expiry_date'], "%Y-%m-%d"): conn.close(); return jsonify({"valid": False, "message": "Expired"})
    
    # Determine Limits
    if u['custom_limit']:
        limit = u['custom_limit']
    else:
        plan = u['plan'].lower()
        limit = int(get_setting(f"limit_{plan}", 3))
    
    conn.close()
    
    return jsonify({
        "valid": True, "credits": u['credits'], "expiry": u['expiry_date'], "plan": u['plan'], 
        "concurrency_limit": limit, "broadcast": b_msg, "broadcast_color": b_col,
        "latest_version": l_ver, "update_desc": u_desc, "update_is_live": u_live == '1', "download_url": dl_url
    })

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    d = request.json
    username = d.get('username')
    if not username: return jsonify({"status": "error"})
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    
    # Check if entry exists
    row = conn.execute("SELECT * FROM user_activity WHERE username=?", (username,)).fetchone()
    if row:
        # Check if session is "new" (e.g. absent for > 10 mins)
        last_seen = datetime.strptime(row['last_seen'], "%Y-%m-%d %H:%M:%S")
        if (datetime.now() - last_seen).total_seconds() > 600:
             conn.execute("UPDATE user_activity SET session_start=?, last_seen=? WHERE username=?", (now_str, now_str, username))
        else:
             conn.execute("UPDATE user_activity SET last_seen=? WHERE username=?", (now_str, username))
    else:
        conn.execute("INSERT INTO user_activity (username, last_seen, session_start) VALUES (?, ?, ?)", (username, now_str, now_str))
    
    conn.commit(); conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/redeem', methods=['POST'])
def redeem():
    d = request.json
    username = d.get('username')
    code = d.get('code')
    
    conn = get_db()
    v = conn.execute("SELECT * FROM vouchers WHERE code=?", (code,)).fetchone()
    
    if not v:
        conn.close(); return jsonify({"success": False, "message": "Invalid Code"})
    
    # Check Expiry
    if v['expiry_date'] and datetime.now() > datetime.strptime(v['expiry_date'], "%Y-%m-%d"):
        conn.close(); return jsonify({"success": False, "message": "Code Expired"})
        
    # Check Usage Limit
    if v['current_uses'] >= v['max_uses']:
        conn.close(); return jsonify({"success": False, "message": "Code Fully Used"})
        
    # Use Voucher
    conn.execute("UPDATE users SET credits=credits+? WHERE username=?", (v['amount'], username))
    conn.execute("UPDATE vouchers SET current_uses=current_uses+1, used_by = CASE WHEN used_by IS NULL THEN ? ELSE used_by || ',' || ? END WHERE code=?", (username, username, code))
    conn.commit(); conn.close()
    
    return jsonify({"success": True, "message": f"Added {v['amount']} Credits Successfully!"})

@app.route('/api/proxy/generate', methods=['POST'])
def proxy_gen():
    auth = request.headers.get("Client-Auth", "")
    if ":" not in auth: return jsonify({"code":-1}), 401
    u, k = auth.split(":")
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=? AND api_key=?", (u,k)).fetchone()
    
    if not user or not user['is_active']: conn.close(); return jsonify({"code":-1, "message": "Unauthorized"}), 403
    
    # Determine Cost based on user overrides or globals
    model = request.json.get('model', '')
    is_pro = "pro" in model
    
    if is_pro:
        cost = user['custom_cost_sora2_pro'] if user['custom_cost_sora2_pro'] else int(get_setting('cost_sora_2_pro', 35))
    else:
        cost = user['custom_cost_sora2'] if user['custom_cost_sora2'] else int(get_setting('cost_sora_2', 25))
        
    if user['credits'] < cost: conn.close(); return jsonify({"code":-1, "message": "Insufficient Credits"}), 402
    
    # Select API Key
    api_key = get_active_api_key(user['assigned_api_group'])
    
    try:
        r = requests.post("https://FreeSoraGenerator.com/api/v1/video/sora-video", json=request.json, headers={"Authorization": f"Bearer {api_key}"}, timeout=120)
        
        if r.json().get("code") == 0:
            tid = r.json().get('data', {}).get('taskId')
            if tid: 
                conn.execute("INSERT INTO tasks (task_id, username, cost, status, created_at) VALUES (?, ?, ?, ?, ?)", (tid, u, cost, 'pending', str(datetime.now())))
                # Log daily success attempt
                conn.execute("UPDATE user_activity SET daily_success = daily_success + 1 WHERE username=?", (u,))
                
            conn.execute("UPDATE users SET credits=credits-? WHERE username=?", (cost, u))
            conn.execute("INSERT INTO logs (username, action, cost, timestamp) VALUES (?, ?, ?, ?)", (u, f"Gen {model}", cost, str(datetime.now())))
            conn.commit()
            
            r_json = r.json()
            r_json['user_balance'] = user['credits'] - cost
            return jsonify(r_json), r.status_code
        else:
             # Log Fail
             conn.execute("UPDATE user_activity SET daily_fail = daily_fail + 1 WHERE username=?", (u,))
             conn.commit()

        return jsonify(r.json()), r.status_code
    except Exception as e: return jsonify({"code":-1, "message": str(e)}), 500
    finally: conn.close()

@app.route('/api/proxy/check-result', methods=['POST'])
def proxy_chk():
    try:
        # For checking, we can use a generic key or one from the pool. 
        # Ideally, we should use the same key, but for simplicity, we use a random active key.
        rk = get_active_api_key() 
        r = requests.post("https://FreeSoraGenerator.com/api/video-generations/check-result", json=request.json, headers={"Authorization": f"Bearer {rk}"}, timeout=30)
        
        data = r.json()
        if data.get('data', {}).get('status') == 'failed':
            task_id = request.json.get('taskId')
            conn = get_db()
            task = conn.execute("SELECT username, cost, status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task and task['status'] != 'refunded':
                conn.execute("UPDATE users SET credits = credits + ? WHERE username = ?", (task['cost'], task['username']))
                conn.execute("UPDATE tasks SET status = 'refunded' WHERE task_id = ?", (task_id,))
                conn.execute("INSERT INTO logs (username, action, cost, timestamp) VALUES (?, ?, ?, ?)", (task['username'], f"Refund {task_id}", 0, str(datetime.now())))
                # Update stats
                conn.execute("UPDATE user_activity SET daily_fail = daily_fail + 1 WHERE username=?", (task['username'],))
                conn.commit()
            conn.close()

        return jsonify(data), r.status_code
    except: return jsonify({"code":-1}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
