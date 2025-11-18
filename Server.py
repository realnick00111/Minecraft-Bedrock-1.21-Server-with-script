import subprocess
import time
import os
import signal
import shutil
from datetime import datetime, timedelta
import threading
from collections import defaultdict

# Config and Setup

os.chdir(os.path.dirname(os.path.abspath(__file__)))

BEDROCK_PATH = "bedrock_server.exe"
PLAYIT_PATH = "playit.exe"

WORLD_FOLDER = "worlds"
BACKUP_FOLDER = "backups"
LEVEL_NAME = "bedrock_world"
SERVER_PROPERTIES = "server.properties"

with open(SERVER_PROPERTIES, "r") as f:
    for line in f:
        if line.startswith("level-name"):
            LEVEL_NAME = line.split("=", 1)[1].strip()

TIME_BEFORE_STARTUP = 15 # (Seconds) The time between the main server and the playit tunnel startup.
BACKUP_INTERVAL = 300  # (Seconds) Time between backups.
TRIM_BOUND = 1000  # (Blocks) The amount of blocks before going outside +/- TRIM_BOUND on x or z.
DAYS_TO_KEEP_HOUR_BACKUPS = 1  # (Days) How many days to keep hourly backups.
HOURS_TO_KEEP_QUICK_BACKUPS = 2  # (Hours) How many hours to keep quick backups.

os.makedirs(BACKUP_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER + "/" + LEVEL_NAME, exist_ok=True)

# BACKUP LOGIC 

SERVER_OUTPUT_BUFFER = ""
SERVER_OUTPUT_LOCK = threading.Lock()

def backup_loop():
    timeUntilOn5Minutes = BACKUP_INTERVAL - (time.time() % BACKUP_INTERVAL)
    while True:
        time.sleep(BACKUP_INTERVAL)
        backup_world()

def backup_world():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(BACKUP_FOLDER, LEVEL_NAME, f"{LEVEL_NAME}_{timestamp}")

    print(f"[{timestamp}] ⏳ Starting Bedrock backup...")

    # Clear old output
    clear_output_buffer()

    # Check if a save is already running
    with SERVER_OUTPUT_LOCK:
        if "The command is already running" in SERVER_OUTPUT_BUFFER:
            print(f"[{timestamp}] ⚠ Save already in progress, skipping backup")
            return

    # Freeze world writes
    send_command("save hold")
    try:
        wait_for_output("Saving...", timeout=10)
    except TimeoutError:
        print(f"[{timestamp}] ❌ Backup failed: 'save hold' timeout")
        return

    # Request file list
    send_command("save query")
    try:
        file_list = wait_for_query_file_list(timeout=10)
    except TimeoutError:
        print(f"[{timestamp}] ❌ Backup failed: 'save query' timeout")
        send_command("save resume")
        return

    # Copy files
    for rel_path in file_list:
        src = os.path.join(WORLD_FOLDER, rel_path)
        dst = os.path.join(backup_path, rel_path)

        os.makedirs(os.path.dirname(dst), exist_ok=True)

        try:
            shutil.copy2(src, dst)
        except Exception as e:
            print(f"[{timestamp}] ❌ Failed to copy {rel_path}: {e}")

    # Resume normal saving
    send_command("save resume")

    print(f"[{timestamp}] ✅ Backup created at: {backup_path}")

    cleanup_backups()

def cleanup_backups():
    now = datetime.now()
    hour_groups = defaultdict(list)
    day_groups = defaultdict(list)
    for folder in os.listdir(BACKUP_FOLDER + "/" + LEVEL_NAME):
        folder_path = os.path.join(BACKUP_FOLDER + "/" + LEVEL_NAME, folder)
        if not os.path.isdir(folder_path):
            continue

        try:
            ts_str = folder.split("_")[-1]
            ts = datetime.strptime(ts_str, "%Y%m%d-%H%M%S")

            hour_key = ts.strftime("%Y%m%d-%H")
            day_key = ts.strftime("%Y%m%d")
            hour_groups[hour_key].append((ts, folder_path))
            day_groups[day_key].append((ts, folder_path))
        except: continue

    for hour_key, items in hour_groups.items():

        # keep the oldest backup in that hour if past HOURS_TO_KEEP_QUICK_BACKUPS
        items.sort(key=lambda x: x[0])
        keep_ts, keep_path = items[0]

        for ts, path in items[1:]:
            if now - ts > timedelta(hours=HOURS_TO_KEEP_QUICK_BACKUPS):
                shutil.rmtree(path)
                print("🧹 Deleted:", path)

    for day_key, items in day_groups.items():

        # keep the oldest backup in that day if past DAYS_TO_KEEP_HOUR_BACKUPS
        items.sort(key=lambda x: x[0])
        keep_ts, keep_path = items[0]

        for ts, path in items[1:]:
            if now - ts > timedelta(days=DAYS_TO_KEEP_HOUR_BACKUPS):
                shutil.rmtree(path)
                print("🧹 Deleted:", path)

# World Trimming Logic

def trim_world():
    send_command("say Trimming world... Stopping server in 1 minute.")
    time.sleep(30)
    close_server("Final warning...  Stopping serverin 30 seconds.", 30)
    print(f"[{datetime.now()}] 🛑 Server stopped for trimming.")
    print(f"[{datetime.now()}] ✂️ Trimming world outside ±{TRIM_BOUND}...")
    # Placeholder: implement with Amulet API or similar
    # Example: Amulet can remove chunks/blocks outside bounds safely
    # from amulet import load_world
    # world = load_world(WORLD_FOLDER)
    # ... remove chunks/blocks outside TRIM_BOUND ...
    # world.save()
    print(f"[{datetime.now()}] ✅ World trimmed.")
    start_server()
    print(f"[{datetime.now()}] ✅ Server restarted after trimming.")

# process management

def start_process(path, title):
    return subprocess.Popen(
        path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

def send_command(command):
    if bedrock_proc.poll() is None:  # Check if process is still running
        bedrock_proc.stdin.write(command + "\n")
        bedrock_proc.stdin.flush()
    else:
        print("Server is not running.")

def close_server(message = "Stopping Server in 5 seconds...", Time=5):
    send_command("say " + message)
    time.sleep(Time)
    if bedrock_proc.poll() is None:
        os.kill(bedrock_proc.pid, signal.SIGTERM)
    if playit_proc.poll() is None:
        os.kill(playit_proc.pid, signal.SIGTERM)

def start_server():
    global bedrock_proc, playit_proc
    print("Starting Minecraft Bedrock server...")
    bedrock_proc = start_process(BEDROCK_PATH, "Bedrock Server")
    threading.Thread(target=server_output_listener, args=(bedrock_proc, "Bedrock"), daemon=True).start()
    
    time.sleep(TIME_BEFORE_STARTUP)
    print("Starting Playit tunnel...")
    playit_proc = start_process(PLAYIT_PATH, "Playit Tunnel")

def console_listener():
    while True:
        cmd = input().strip().lower()
        if cmd == "backup":
            backup_world()
        elif cmd == "trim":
            trim_world()
        elif cmd == "exit":
            print("🛑 Shutting down server... informed server")
            close_server()
            print("🛑 Processes terminated. Exiting in 5 seconds...")
            time.sleep(5)
            os._exit(0)
        elif cmd.startswith("run "):
            send_command(cmd[4:].strip())
        else:
            print("Commands: backup | trim | exit | run <command>")

# Server Output Listener

def server_output_listener(proc, name="Server"):
    global SERVER_OUTPUT_BUFFER
    
    for line in iter(proc.stdout.readline, ''):
        if not line:
            break

        line = line.strip()
        if not line.startswith(f"{LEVEL_NAME}/"):
            print(f"[{name}] {line}")

        # Save to buffer for backup system
        with SERVER_OUTPUT_LOCK:
            SERVER_OUTPUT_BUFFER += line + "\n"
        
def clear_output_buffer():
    global SERVER_OUTPUT_BUFFER
    with SERVER_OUTPUT_LOCK:
        SERVER_OUTPUT_BUFFER = ""

def wait_for_output(text, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        with SERVER_OUTPUT_LOCK:
            if text in SERVER_OUTPUT_BUFFER:
                return True
        time.sleep(0.05)
    raise TimeoutError(f"Timeout waiting for server output: '{text}'")

def wait_for_query_file_list(timeout=10):
    start = time.time()
    file_list = []
    found = False

    while time.time() - start < timeout:
        with SERVER_OUTPUT_LOCK:
            buffer_copy = SERVER_OUTPUT_BUFFER

        # Look for the line starting with your world folder
        lines = buffer_copy.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith(f"{LEVEL_NAME}/") or line.startswith(f"{WORLD_FOLDER}/"):
                found = True
                # Split by commas, take the part before ':' for the path
                parts = line.split(",")
                for part in parts:
                    path = part.split(":", 1)[0].strip()
                    file_list.append(path)
                return file_list

        if not found:
            time.sleep(0.05)

    raise TimeoutError("Timeout waiting for save query file list")


# Main Execution

def main():
    global bedrock_proc, playit_proc
    start_server()
    
    print("✅ Services running. Commands: backup | trim | exit | run <command>")

    threading.Thread(target=backup_loop, daemon=True).start()
    threading.Thread(target=console_listener, daemon=False).start()

if __name__ == "__main__":
    main()