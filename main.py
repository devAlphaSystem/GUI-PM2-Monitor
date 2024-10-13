import paramiko
import tkinter as tk
from tkinter import messagebox
from ttkbootstrap import Style, Frame, Button, Entry, Label, Treeview, Scrollbar
from ttkbootstrap.constants import *
from tkinter import ttk 
import json
import threading
import time
from datetime import datetime
import re
import os
import platform
import locale
import sys

# -------------------- Constants and Globals -------------------- #

def get_appdata_directory():
    if platform.system() == 'Windows':
        return os.getenv('APPDATA')
    elif platform.system() == 'Darwin':
        return os.path.expanduser('~/Library/Application Support')
    else:
        return os.path.expanduser('~/.config')
    
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.abspath(".")

APP_NAME = 'GUI_PM2_Monitor'
APPDATA_DIR = os.path.join(get_appdata_directory(), APP_NAME)
os.makedirs(APPDATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(APPDATA_DIR, 'config.json')
TRANSLATIONS_DIR = os.path.join(base_path, 'translations')
SUPPORTED_LANGUAGES = ['en', 'pt_br', 'es', 'fr', 'de']
DEFAULT_AUTO_REFRESH_INTERVAL = 30
DEFAULT_THEME = 'superhero'
REQUIRED_COMMANDS = ['pm2', 'mpstat', 'free', 'top', 'awk', 'grep', 'tail']

# -------------------- Internationalization (i18n) -------------------- #

class Translator:
    def __init__(self):
        self.lang = self.detect_language()
        self.translations = self.load_translations(self.lang)
    
    def detect_language(self):
        lang, enc = locale.getlocale()
        if lang:
            lang = lang.lower()
            if lang.startswith('pt'):
                return 'pt_br'
            elif lang.startswith('es'):
                return 'es'
            elif lang.startswith('fr'):
                return 'fr'
            elif lang.startswith('de'):
                return 'de'
            elif lang.startswith('en'):
                return 'en'
        lang, _ = locale.getpreferredencoding(), None
        if lang:
            lang = lang.lower()
            if 'pt' in lang:
                return 'pt_br'
            elif 'es' in lang:
                return 'es'
            elif 'fr' in lang:
                return 'fr'
            elif 'de' in lang:
                return 'de'
            elif 'en' in lang:
                return 'en'
        return 'en'
    
    def load_translations(self, lang):
        translation_path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
        if not os.path.exists(translation_path):
            print(f"Translation file for '{lang}' not found. Falling back to English.")
            translation_path = os.path.join(TRANSLATIONS_DIR, "en.json")
            if not os.path.exists(translation_path):
                print("English translation file 'en.json' is missing. Please ensure it exists in the 'translations' directory.")
                sys.exit(1)
        try:
            with open(translation_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Failed to parse the translation file '{translation_path}'. Please check its format.")
            sys.exit(1)
    
    def translate(self, key, **kwargs):
        text = self.translations.get(key, key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError as e:
                print(f"Missing translation key: {e}")
        return text

translator = Translator()

# -------------------- Configuration Handling -------------------- #

class ConfigHandler:
    def __init__(self, config_file=CONFIG_FILE):
        self.config_file = config_file
        self.config = {}
        self.load_config()
    
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
                print("Configuration loaded successfully.")
            except json.JSONDecodeError:
                print("Failed to parse 'config.json'. It might be corrupted.")
                self.config = {}
        else:
            print("'config.json' not found. A new one will be created after entering server details.")
            self.config = {}
    
    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            print("Configuration saved successfully.")
        except Exception as e:
            print(f"Failed to save configuration: {e}")
    
    def is_configured(self):
        return all(key in self.config for key in ['host', 'port', 'username', 'password'])
    
    def get_server_details(self):
        return self.config.get('host'), self.config.get('port', 22), self.config.get('username'), self.config.get('password')
    
    def set_server_details(self, host, port, username, password):
        self.config['host'] = host
        self.config['port'] = port
        self.config['username'] = username
        self.config['password'] = password
        self.save_config()
    
    def get_preferences(self):
        return {
            'auto_refresh_interval': self.config.get('auto_refresh_interval', DEFAULT_AUTO_REFRESH_INTERVAL),
            'theme': self.config.get('theme', DEFAULT_THEME)
        }
    
    def set_preferences(self, auto_refresh_interval, theme):
        self.config['auto_refresh_interval'] = auto_refresh_interval
        self.config['theme'] = theme
        self.save_config()

config_handler = ConfigHandler()

# -------------------- SSH Client Wrapper -------------------- #

class SSHClientWrapper:
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client = None
        self.lock = threading.Lock()
        self.connect()
    
    def connect(self):
        try:
            print(f"Attempting to connect to {self.host}:{self.port} as {self.username}...")
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=10
            )
            self.client.get_transport().set_keepalive(30)
            print("SSH connection established.")
            self.check_required_commands()
        except paramiko.AuthenticationException:
            messagebox.showerror(translator.translate("authentication_error"), translator.translate("auth_error_message"))
            print("Authentication failed.")
        except paramiko.SSHException as ssh_err:
            messagebox.showerror(translator.translate("ssh_error"), translator.translate("ssh_error_message", error=ssh_err))
            print(f"SSH connection failed: {ssh_err}")
        except Exception as e:
            messagebox.showerror(translator.translate("error"), translator.translate("unexpected_error", error=e))
            print(f"An unexpected error occurred while connecting: {e}")
    
    def check_required_commands(self):
        missing_commands = []
        for cmd in REQUIRED_COMMANDS:
            check_cmd = f'command -v {cmd}'
            output = self.execute_command(check_cmd)
            if not output.strip():
                missing_commands.append(cmd)
        if missing_commands:
            message = translator.translate("missing_command_message", command=", ".join(missing_commands))
            messagebox.showwarning(translator.translate("missing_command"), message)
            print(f"Missing commands: {', '.join(missing_commands)}")
    
    def execute_command(self, command):
        with self.lock:
            try:
                if self.client is None or not self.client.get_transport().is_active():
                    print("SSH connection is not active. Attempting to reconnect...")
                    self.connect()
                if self.client is None or not self.client.get_transport().is_active():
                    print("Reconnection failed.")
                    return None
                print(f"Executing command: {command}")
                stdin, stdout, stderr = self.client.exec_command(command)
                output = stdout.read().decode()
                error = stderr.read().decode()
                if error and not command.startswith('pm2 '):
                    print(f"Error executing command '{command}': {error}")
                    raise Exception(error)
                print(f"Command output: {output.strip()}")
                return output
            except (paramiko.SSHException, Exception) as e:
                print(f"Error executing command '{command}': {e}")
                try:
                    print("Attempting to reconnect and retry the command...")
                    self.connect()
                    if self.client is None or not self.client.get_transport().is_active():
                        print("Reconnection failed.")
                        return None
                    stdin, stdout, stderr = self.client.exec_command(command)
                    output = stdout.read().decode()
                    error = stderr.read().decode()
                    if error and not command.startswith('pm2 '):
                        print(f"Error executing command '{command}' after reconnecting: {error}")
                        raise Exception(error)
                    print(f"Command output after reconnecting: {output.strip()}")
                    return output
                except Exception as e:
                    messagebox.showerror(translator.translate("ssh_error"), translator.translate("ssh_error_message", error=e))
                    print(f"SSH command execution failed after reconnecting: {e}")
                    return None
    
    def close(self):
        if self.client:
            self.client.close()
            self.client = None
            print("SSH connection closed.")

# -------------------- PM2 and System Resource Retrieval -------------------- #

PM2_LIST_COMMAND = 'pm2 jlist'
CPU_USAGE_COMMAND_MPSTAT = "mpstat 1 1 | awk '/Average/ {print 100 - $12}'"
CPU_USAGE_COMMAND_TOP = 'top -bn1 | grep -i "Cpu(s)"'
MEMORY_USAGE_COMMAND = 'free -m'

def get_pm2_services(ssh_client):
    output = ssh_client.execute_command(PM2_LIST_COMMAND)
    if output:
        try:
            services_json = json.loads(output)
            services = []
            for svc in services_json:
                memory_mb = round(svc.get('monit', {}).get('memory', 0) / (1024 * 1024), 2)
                services.append({
                    'ID': svc.get('pm_id'),
                    'App Name': svc.get('name'),
                    'Version': svc.get('pm2_env', {}).get('version', 'N/A'),
                    'Status': svc.get('pm2_env', {}).get('status'),
                    'CPU (%)': svc.get('monit', {}).get('cpu', 0),
                    'Memory (MB)': memory_mb,
                    'Uptime': format_uptime(svc.get('pm2_env', {}).get('pm_uptime')),
                    'Out Log Path': svc.get('pm2_env', {}).get('pm_out_log_path', ''),
                    'Error Log Path': svc.get('pm2_env', {}).get('pm_err_log_path', '')
                })
            print(f"Retrieved {len(services)} PM2 services.")
            return services
        except json.JSONDecodeError:
            messagebox.showerror(translator.translate("json_error"), translator.translate("json_error_message"))
            print("Failed to parse PM2 JSON output.")
    return []

def get_system_resources(ssh_client):
    cpu_usage = "N/A"
    cpu_command_mpstat = CPU_USAGE_COMMAND_MPSTAT
    cpu_output = ssh_client.execute_command(cpu_command_mpstat)
    if cpu_output:
        try:
            cpu_usage = round(float(cpu_output.strip()), 2)
            print(f"CPU Usage (mpstat): {cpu_usage}%")
        except ValueError:
            cpu_usage = "N/A"
            print("Failed to parse CPU usage from mpstat output.")

    if cpu_usage == "N/A":
        cpu_command_top = CPU_USAGE_COMMAND_TOP
        cpu_output = ssh_client.execute_command(cpu_command_top)
        if cpu_output:
            try:
                match = re.search(r'(\d+\.\d+)\s*%id', cpu_output, re.IGNORECASE)
                if match:
                    idle_percent = float(match.group(1))
                    cpu_usage = round(100 - idle_percent, 2)
                    print(f"CPU Usage (top): {cpu_usage}%")
            except Exception:
                print("Failed to parse CPU usage from top output.")
                pass

    mem_output = ssh_client.execute_command(MEMORY_USAGE_COMMAND)
    memory_usage = "N/A"
    if mem_output:
        try:
            lines = mem_output.split('\n')
            mem_line = next((line for line in lines if line.startswith('Mem:')), None)
            if mem_line:
                parts = mem_line.split()
                total = float(parts[1])
                used = float(parts[2])
                memory_usage = f"{used} MB / {total} MB"
                print(f"Memory Usage: {memory_usage}")
        except Exception:
            print("Failed to parse memory usage.")
            pass

    return {
        'CPU Usage (%)': cpu_usage,
        'Memory Usage (MB)': memory_usage
    }

def format_uptime(epoch_time):
    try:
        if not epoch_time:
            return "N/A"
        uptime_seconds = (time.time() - (epoch_time / 1000))
        if uptime_seconds < 0:
            return "N/A"
        days, remainder = divmod(int(uptime_seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m {seconds}s"
    except:
        return "N/A"

# -------------------- Service Control -------------------- #

def control_service(action, app_id=None, ssh_client=None, refresh_callback=None):
    if app_id is not None:
        if str(app_id).lower() == 'all':
            command = f'pm2 {action} all'
        else:
            command = f'pm2 {action} {app_id}'
    else:
        messagebox.showwarning(translator.translate("invalid_action"), translator.translate("no_service_selected"))
        return

    confirmation = messagebox.askyesno(translator.translate("confirm_action"), translator.translate("confirm_action_message", action=action))
    if not confirmation:
        return

    output = ssh_client.execute_command(command)
    if output is not None:
        messagebox.showinfo(translator.translate("action_successful"), translator.translate("action_success_message", action=action))
        if callable(refresh_callback):
            refresh_callback()
    else:
        messagebox.showerror(translator.translate("action_failed"), translator.translate("action_failed_message", action=action))

# -------------------- GUI Setup -------------------- #

class LogWindow:
    def __init__(self, master, app_name, app_id, ssh_client, out_log_path, error_log_path):
        self.master = master
        self.app_name = app_name
        self.app_id = app_id
        self.ssh_client = ssh_client
        self.out_log_path = out_log_path
        self.error_log_path = error_log_path

        self.window = tk.Toplevel(master)
        self.window.title(translator.translate("logs_for", app_name=self.app_name))
        self.window.geometry("800x600")

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.stdout_frame = Frame(self.notebook)
        self.stderr_frame = Frame(self.notebook)

        self.notebook.add(self.stdout_frame, text="STDOUT Logs")
        self.notebook.add(self.stderr_frame, text="STDERR Logs")

        self.stdout_text = tk.Text(self.stdout_frame, wrap=tk.NONE)
        self.stdout_text.pack(fill=tk.BOTH, expand=True)

        self.stdout_scrollbar_y = Scrollbar(self.stdout_frame, orient=tk.VERTICAL, command=self.stdout_text.yview)
        self.stdout_text.configure(yscrollcommand=self.stdout_scrollbar_y.set)
        self.stdout_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.stdout_scrollbar_x = Scrollbar(self.stdout_frame, orient=tk.HORIZONTAL, command=self.stdout_text.xview)
        self.stdout_text.configure(xscrollcommand=self.stdout_scrollbar_x.set)
        self.stdout_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.stderr_text = tk.Text(self.stderr_frame, wrap=tk.NONE)
        self.stderr_text.pack(fill=tk.BOTH, expand=True)

        self.stderr_scrollbar_y = Scrollbar(self.stderr_frame, orient=tk.VERTICAL, command=self.stderr_text.yview)
        self.stderr_text.configure(yscrollcommand=self.stderr_scrollbar_y.set)
        self.stderr_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.stderr_scrollbar_x = Scrollbar(self.stderr_frame, orient=tk.HORIZONTAL, command=self.stderr_text.xview)
        self.stderr_text.configure(xscrollcommand=self.stderr_scrollbar_x.set)
        self.stderr_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        threading.Thread(target=self.fetch_logs, args=('out', self.stdout_text, self.out_log_path), daemon=True).start()
        threading.Thread(target=self.fetch_logs, args=('error', self.stderr_text, self.error_log_path), daemon=True).start()

    def fetch_logs(self, log_type, text_widget, log_path):
        if log_path:
            command = f'tail -n 100 "{log_path}" | tac'
            output = self.ssh_client.execute_command(command)
            if output:
                text_widget.insert(tk.END, output)
                text_widget.config(state=tk.DISABLED)
            else:
                text_widget.insert(tk.END, translator.translate("no_logs"))
                text_widget.config(state=tk.DISABLED)
        else:
            text_widget.insert(tk.END, translator.translate("log_not_found", log_type=log_type.upper()))
            text_widget.config(state=tk.DISABLED)

class ConfigWindow:
    def __init__(self, master, app):
        self.master = master
        self.app = app

        self.window = tk.Toplevel(master)
        self.window.title(translator.translate("config_title"))
        self.window.geometry("400x350")
        self.window.grab_set()

        self.window.columnconfigure(1, weight=1)

        self.server_frame = Frame(self.window, padding=10)
        self.server_frame.pack(fill=tk.X)

        self.host_label = Label(self.server_frame, text=translator.translate("host"))
        self.host_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky='e')

        self.host_var = tk.StringVar(value=self.app.ssh_details['host'])
        self.host_entry = Entry(self.server_frame, textvariable=self.host_var)
        self.host_entry.grid(row=0, column=1, padx=10, pady=(10, 5), sticky='we')

        self.port_label = Label(self.server_frame, text=translator.translate("port"))
        self.port_label.grid(row=1, column=0, padx=10, pady=5, sticky='e')

        self.port_var = tk.IntVar(value=self.app.ssh_details['port'])
        self.port_entry = Entry(self.server_frame, textvariable=self.port_var)
        self.port_entry.grid(row=1, column=1, padx=10, pady=5, sticky='we')

        self.username_label = Label(self.server_frame, text=translator.translate("username"))
        self.username_label.grid(row=2, column=0, padx=10, pady=5, sticky='e')

        self.username_var = tk.StringVar(value=self.app.ssh_details['username'])
        self.username_entry = Entry(self.server_frame, textvariable=self.username_var)
        self.username_entry.grid(row=2, column=1, padx=10, pady=5, sticky='we')

        self.password_label = Label(self.server_frame, text=translator.translate("password"))
        self.password_label.grid(row=3, column=0, padx=10, pady=5, sticky='e')

        self.password_var = tk.StringVar(value=self.app.ssh_details['password'])
        self.password_entry = Entry(self.server_frame, textvariable=self.password_var, show='*')
        self.password_entry.grid(row=3, column=1, padx=10, pady=5, sticky='we')

        self.pref_frame = Frame(self.window, padding=10)
        self.pref_frame.pack(fill=tk.X)

        self.interval_label = Label(self.pref_frame, text=translator.translate("auto_refresh_interval"))
        self.interval_label.grid(row=0, column=0, padx=10, pady=(20, 5), sticky='e')

        self.interval_var = tk.IntVar(value=self.app.auto_refresh_interval)
        self.interval_entry = Entry(self.pref_frame, textvariable=self.interval_var)
        self.interval_entry.grid(row=0, column=1, padx=10, pady=(20, 5), sticky='we')

        self.theme_label = Label(self.pref_frame, text=translator.translate("theme"))
        self.theme_label.grid(row=1, column=0, padx=10, pady=5, sticky='e')

        self.theme_var = tk.StringVar(value=self.app.theme)
        self.theme_options = ['superhero', 'cyborg', 'darkly', 'flatly', 'journal', 'lumen', 'minty', 'pulse', 'sandstone', 'solar', 'united', 'yeti']
        self.theme_menu = ttk.Combobox(self.pref_frame, textvariable=self.theme_var, values=self.theme_options, state='readonly')
        self.theme_menu.grid(row=1, column=1, padx=10, pady=5, sticky='we')

        self.save_button = Button(self.window, text=translator.translate("save"), command=self.save_config)
        self.save_button.pack(pady=(10, 10))

    def save_config(self):
        host = self.host_var.get().strip()
        port = self.port_var.get()
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()

        if not host or not username or not password:
            messagebox.showerror(translator.translate("invalid_input"), translator.translate("invalid_input_message"))
            return
        if port <= 0 or port > 65535:
            messagebox.showerror(translator.translate("invalid_input"), translator.translate("invalid_input_message"))
            return

        try:
            interval = self.interval_var.get()
            if interval < 0:
                raise ValueError
        except (tk.TclError, ValueError):
            messagebox.showerror(translator.translate("invalid_input"), translator.translate("invalid_input_message"))
            return

        selected_theme = self.theme_var.get()
        if selected_theme not in self.theme_options:
            messagebox.showerror(translator.translate("invalid_theme"), translator.translate("invalid_theme_message"))
            return

        config_handler.set_server_details(host, port, username, password)
        config_handler.set_preferences(interval, selected_theme)
        self.app.apply_preferences()
        messagebox.showinfo(translator.translate("success"), translator.translate("save_success"))
        self.window.destroy()

class ConfigWindowInitial:
    def __init__(self, master, app):
        self.master = master
        self.app = app

        self.window = tk.Toplevel(master)
        self.window.title(translator.translate("enter_server_details"))
        self.window.geometry("400x350")
        self.window.grab_set()

        self.window.columnconfigure(1, weight=1)

        self.host_label = Label(self.window, text=translator.translate("host"))
        self.host_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky='e')

        self.host_var = tk.StringVar()
        self.host_entry = Entry(self.window, textvariable=self.host_var)
        self.host_entry.grid(row=0, column=1, padx=10, pady=(10, 5), sticky='we')

        self.port_label = Label(self.window, text=translator.translate("port"))
        self.port_label.grid(row=1, column=0, padx=10, pady=5, sticky='e')

        self.port_var = tk.IntVar(value=22)
        self.port_entry = Entry(self.window, textvariable=self.port_var)
        self.port_entry.grid(row=1, column=1, padx=10, pady=5, sticky='we')

        self.username_label = Label(self.window, text=translator.translate("username"))
        self.username_label.grid(row=2, column=0, padx=10, pady=5, sticky='e')

        self.username_var = tk.StringVar()
        self.username_entry = Entry(self.window, textvariable=self.username_var)
        self.username_entry.grid(row=2, column=1, padx=10, pady=5, sticky='we')

        self.password_label = Label(self.window, text=translator.translate("password"))
        self.password_label.grid(row=3, column=0, padx=10, pady=5, sticky='e')

        self.password_var = tk.StringVar()
        self.password_entry = Entry(self.window, textvariable=self.password_var, show='*')
        self.password_entry.grid(row=3, column=1, padx=10, pady=5, sticky='we')

        self.save_button = Button(self.window, text=translator.translate("save_and_connect"), command=self.save_and_connect)
        self.save_button.grid(row=4, column=0, columnspan=2, pady=(20, 10))

    def save_and_connect(self):
        host = self.host_var.get().strip()
        port = self.port_var.get()
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()

        if not host or not username or not password:
            messagebox.showerror(
                translator.translate("invalid_input"),
                translator.translate("invalid_input_message")
            )
            return
        if port <= 0 or port > 65535:
            messagebox.showerror(
                translator.translate("invalid_input"),
                translator.translate("invalid_input_message")
            )
            return

        interval = DEFAULT_AUTO_REFRESH_INTERVAL
        selected_theme = DEFAULT_THEME

        config_handler.set_server_details(host, port, username, password)
        config_handler.set_preferences(interval, selected_theme)

        self.app.initialize_application()

        if self.app.ssh_client.client is not None:
            messagebox.showinfo(
                translator.translate("success"),
                translator.translate("save_success")
            )
            self.window.destroy()
        else:
            messagebox.showerror(
                translator.translate("ssh_error"),
                translator.translate("ssh_error_message", error="SSH connection failed.")
            )

class PM2MonitorApp:
    def __init__(self, root):
        self.root = root
        self.initialized = False
        self.root.title(translator.translate("title"))
        self.root.geometry("1400x800")

        self.preferences = config_handler.get_preferences()
        self.auto_refresh_interval = self.preferences['auto_refresh_interval']
        self.theme = self.preferences['theme']

        self.style = Style(theme=self.theme)

        if not config_handler.is_configured():
            print("Server configuration not found. Prompting user to enter server details.")
            self.prompt_server_config()
        else:
            self.initialize_application()

    def initialize_application(self):
        self.ssh_details = {
            'host': config_handler.config.get('host'),
            'port': config_handler.config.get('port', 22),
            'username': config_handler.config.get('username'),
            'password': config_handler.config.get('password')
        }

        self.ssh_client = SSHClientWrapper(
            self.ssh_details['host'],
            self.ssh_details['port'],
            self.ssh_details['username'],
            self.ssh_details['password']
        )
        if self.ssh_client.client is None:
            print("SSH connection failed during initialization.")
            messagebox.showerror(
                translator.translate("error"),
                translator.translate("ssh_error_message", error="SSH connection failed during initialization.")
            )
            return

        self.initialized = True

        self.setup_ui()
        self.apply_preferences()
        self.refresh_services()

    def setup_ui(self):
        self.top_frame = Frame(self.root, padding=10)
        self.top_frame.pack(side=tk.TOP, fill=tk.X)

        self.search_var = tk.StringVar()
        self.placeholder_text = translator.translate("search") if "search" in translator.translations else "Search..."
        self.search_var.set(self.placeholder_text)
        self.search_entry = Entry(
            self.top_frame,
            textvariable=self.search_var,
            width=30
        )
        self.search_entry.pack(side=tk.LEFT, padx=(0, 10))
        self.search_entry.bind("<FocusIn>", self.clear_placeholder)
        self.search_entry.bind("<FocusOut>", self.add_placeholder)
        self.search_entry.config(foreground='grey')

        self.search_var.trace_add("write", lambda name, index, mode: self.filter_services())

        self.start_button = Button(
            self.top_frame,
            text=translator.translate("start_service"),
            command=lambda: self.service_control('start')
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_button = Button(
            self.top_frame,
            text=translator.translate("stop_service"),
            command=lambda: self.service_control('stop')
        )
        self.stop_button.pack(side=tk.LEFT, padx=(0, 5))

        self.restart_button = Button(
            self.top_frame,
            text=translator.translate("restart_service"),
            command=lambda: self.service_control('restart')
        )
        self.restart_button.pack(side=tk.LEFT, padx=(0, 5))

        self.view_logs_button = Button(
            self.top_frame,
            text=translator.translate("view_logs"),
            command=self.view_logs
        )
        self.view_logs_button.pack(side=tk.LEFT, padx=(0, 5))

        self.restart_all_button = Button(
            self.top_frame,
            text=translator.translate("restart_all"),
            command=lambda: self.control_all('restart')
        )
        self.restart_all_button.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_all_button = Button(
            self.top_frame,
            text=translator.translate("stop_all"),
            command=lambda: self.control_all('stop')
        )
        self.stop_all_button.pack(side=tk.LEFT, padx=(0, 5))

        self.start_all_button = Button(
            self.top_frame,
            text=translator.translate("start_all"),
            command=lambda: self.control_all('start')
        )
        self.start_all_button.pack(side=tk.LEFT, padx=(0, 5))

        self.config_button = Button(
            self.top_frame,
            text=translator.translate("config"),
            command=self.open_config_window
        )
        self.config_button.pack(side=tk.RIGHT, padx=(0, 10))

        self.middle_frame = Frame(self.root, padding=10)
        self.middle_frame.pack(fill=tk.BOTH, expand=True)

        self.columns = ('ID', 'App Name', 'Version', 'Status', 'CPU (%)', 'Memory (MB)', 'Uptime')
        self.tree = Treeview(
            self.middle_frame,
            columns=self.columns,
            show='headings',
            bootstyle="primary"
        )
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        for col in self.columns:
            self.tree.heading(
                col,
                text=translator.translate(col.lower().replace(" ", "_")),
                command=lambda _col=col: self.sort_column(_col, False)
            )
            self.tree.column(col, anchor='center', width=120)

        self.scrollbar = Scrollbar(
            self.middle_frame,
            orient=tk.VERTICAL,
            command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.resource_frame = Frame(self.root, padding=10)
        self.resource_frame.pack(fill=tk.X)

        self.cpu_var = tk.StringVar()
        self.cpu_label = Label(
            self.resource_frame,
            textvariable=self.cpu_var,
            font=("Helvetica", 12)
        )
        self.cpu_label.pack(side=tk.LEFT, padx=(0, 20))

        self.memory_var = tk.StringVar()
        self.memory_label = Label(
            self.resource_frame,
            textvariable=self.memory_var,
            font=("Helvetica", 12)
        )
        self.memory_label.pack(side=tk.LEFT, padx=(0, 20))

        self.bottom_frame = Frame(self.root, padding=10)
        self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.refresh_button = Button(
            self.bottom_frame,
            text=translator.translate("refresh"),
            command=self.refresh_services
        )
        self.refresh_button.pack(side=tk.LEFT, padx=(0, 10))

        self.status_var = tk.StringVar()
        self.status_var.set(translator.translate("last_updated", time="Never", host=self.ssh_details['host'], port=self.ssh_details['port']))
        self.status_label = Label(
            self.bottom_frame,
            textvariable=self.status_var
        )
        self.status_label.pack(side=tk.LEFT, padx=(0, 10))

        self.all_services = []
        self.filtered_services = []

        self.refresh_services()

        if self.auto_refresh_interval > 0:
            self.auto_refresh()

    def prompt_server_config(self):
        config_window = ConfigWindowInitial(self.root, self)
        self.root.wait_window(config_window.window)
    
    def open_config_window(self):
        ConfigWindow(self.root, self)
    
    def apply_preferences(self):
        self.auto_refresh_interval = config_handler.config.get('auto_refresh_interval', DEFAULT_AUTO_REFRESH_INTERVAL)
        self.theme = config_handler.config.get('theme', DEFAULT_THEME)
        self.style.theme_use(self.theme)
        self.refresh_services()
    
    def refresh_services(self):
        self.refresh_button.config(state='disabled')
        threading.Thread(target=self.fetch_and_display, daemon=True).start()
    
    def fetch_and_display(self):
        services = get_pm2_services(self.ssh_client)
        system_resources = get_system_resources(self.ssh_client)
        if services is not None:
            self.all_services = services
            self.filter_services()
            self.cpu_var.set(translator.translate("cpu_usage", cpu=system_resources['CPU Usage (%)']))
            self.memory_var.set(translator.translate("memory_usage", memory=system_resources['Memory Usage (MB)']))
            self.status_var.set(translator.translate("last_updated", time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'), host=self.ssh_details['host'], port=self.ssh_details['port']))
        self.refresh_button.config(state='normal')
    
    def filter_services(self):
        search_query = self.search_var.get().lower()
        if search_query == self.placeholder_text.lower():
            search_query = ""
        if not search_query:
            self.filtered_services = self.all_services
        else:
            self.filtered_services = [
                svc for svc in self.all_services 
                if search_query in svc['App Name'].lower()
            ]
        self.update_treeview()
    
    def update_treeview(self):
        self.tree.delete(*self.tree.get_children())
        for svc in self.filtered_services:
            self.tree.insert('', 'end', values=(
                svc['ID'],
                svc['App Name'],
                svc['Version'],
                svc['Status'],
                svc['CPU (%)'],
                svc['Memory (MB)'],
                svc['Uptime']
            ))
    
    def sort_column(self, col, reverse):
        try:
            if col in ['CPU (%)', 'Memory (MB)']:
                sorted_data = sorted(
                    self.filtered_services, 
                    key=lambda x: float(x[col]), 
                    reverse=reverse
                )
            elif col == 'ID':
                sorted_data = sorted(
                    self.filtered_services, 
                    key=lambda x: int(x[col]), 
                    reverse=reverse
                )
            elif col == 'Uptime':
                sorted_data = sorted(
                    self.filtered_services, 
                    key=lambda x: self.parse_uptime(x[col]), 
                    reverse=reverse
                )
            else:
                sorted_data = sorted(
                    self.filtered_services, 
                    key=lambda x: x[col].lower(), 
                    reverse=reverse
                )
            self.filtered_services = sorted_data
            self.update_treeview()
            self.tree.heading(col, command=lambda: self.sort_column(col, not reverse))
        except Exception as e:
            messagebox.showerror(translator.translate("error"), f"{translator.translate('sort_error')}: {e}")
            print(f"Error sorting column '{col}': {e}")
    
    def parse_uptime(self, uptime_str):
        try:
            days, hours, minutes, seconds = 0, 0, 0, 0
            if 'd' in uptime_str:
                days = int(uptime_str.split('d')[0])
                uptime_str = uptime_str.split('d')[1]
            if 'h' in uptime_str:
                hours = int(uptime_str.split('h')[0])
                uptime_str = uptime_str.split('h')[1]
            if 'm' in uptime_str:
                minutes = int(uptime_str.split('m')[0])
                uptime_str = uptime_str.split('m')[1]
            if 's' in uptime_str:
                seconds = int(uptime_str.split('s')[0])
            total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
            return total_seconds
        except:
            return 0
    
    def service_control(self, action):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning(translator.translate("no_selection"), translator.translate("select_service_warning"))
            return
        for item in selected_items:
            svc = self.tree.item(item, 'values')
            app_id = svc[0]
            threading.Thread(
                target=self.control_service_thread, 
                args=(action, app_id), 
                daemon=True
            ).start()
    
    def control_service_thread(self, action, app_id):
        control_service(
            action=action, 
            app_id=app_id, 
            ssh_client=self.ssh_client, 
            refresh_callback=self.refresh_services
        )
    
    def control_all(self, action):
        threading.Thread(
            target=self.control_all_thread, 
            args=(action,), 
            daemon=True
        ).start()
    
    def control_all_thread(self, action):
        control_service(
            action=action, 
            app_id='all', 
            ssh_client=self.ssh_client, 
            refresh_callback=self.refresh_services
        )
    
    def auto_refresh(self):
        if self.auto_refresh_interval > 0:
            self.refresh_services()
            self.root.after(self.auto_refresh_interval * 1000, self.auto_refresh)
    
    def on_closing(self):
        if messagebox.askokcancel(translator.translate("quit"), translator.translate("quit_message")):
            self.ssh_client.close()
            self.root.destroy()
    
    def clear_placeholder(self, event):
        if self.search_var.get() == self.placeholder_text:
            self.search_entry.delete(0, tk.END)
            self.search_entry.config(foreground='black')
    
    def add_placeholder(self, event):
        if not self.search_var.get():
            self.search_var.set(self.placeholder_text)
            self.search_entry.config(foreground='grey')
    
    def view_logs(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning(translator.translate("no_selection"), translator.translate("select_service_warning"))
            return
        svc = self.tree.item(selected_items[0], 'values')
        app_id = svc[0]
        app_name = svc[1]

        service = next((s for s in self.all_services if str(s['ID']) == str(app_id)), None)
        if service:
            out_log_path = service.get('Out Log Path', '')
            error_log_path = service.get('Error Log Path', '')
            LogWindow(self.root, app_name, app_id, self.ssh_client, out_log_path, error_log_path)
        else:
            messagebox.showerror(translator.translate("error"), translator.translate("service_not_found_message"))
            print("Selected service details could not be found.")

# -------------------- Main Execution -------------------- #

def main():
    if not os.path.exists(TRANSLATIONS_DIR):
        print(f"Translations directory '{TRANSLATIONS_DIR}' not found. Please create it and add the necessary translation JSON files.")
        sys.exit(1)
    
    en_translation_path = os.path.join(TRANSLATIONS_DIR, "en.json")
    if not os.path.exists(en_translation_path):
        print(f"English translation file 'en.json' not found in '{TRANSLATIONS_DIR}'. Please add it.")
        sys.exit(1)
    
    root = tk.Tk()
    app = PM2MonitorApp(root)
    if not app.initialized:
        print("Application failed to initialize. Exiting.")
        root.destroy()
        return
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
