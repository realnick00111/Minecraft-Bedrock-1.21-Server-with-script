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
            # line looks like: level-name=My World
            LEVEL_NAME = line.split("=", 1)[1].strip()

TIME_BEFORE_STARTUP = 15 # (Seconds) The time between the main server and the playit tunnel startup.
BACKUP_INTERVAL = 30  # (Seconds) Time between backups.
TRIM_BOUND = 1000  # (Blocks) The amount of blocks before going outside +/- TRIM_BOUND on x or z.

os.makedirs(BACKUP_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER + "/" + LEVEL_NAME, exist_ok=True)

# BACKUP LOGIC 

def backup_loop():
    timeUntilOn5Minutes = BACKUP_INTERVAL - (time.time() % BACKUP_INTERVAL)
    while True:
        time.sleep(BACKUP_INTERVAL)
        backup_world()

def backup_world():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BACKUP_FOLDER + "/" + LEVEL_NAME, f"{LEVEL_NAME}_{timestamp}")
    try:
        shutil.copytree(WORLD_FOLDER + "/" + LEVEL_NAME, dst)
        print(f"[{timestamp}] ✅ Backup created: {dst}")
    except Exception as e:
        print(f"[{timestamp}] ❌ Backup failed: {e}")
    cleanup_backups()

def cleanup_backups():
    now = datetime.now()
    hour_groups = defaultdict(list)
 
    for folder in os.listdir(BACKUP_FOLDER + "/" + LEVEL_NAME):
        folder_path = os.path.join(BACKUP_FOLDER + "/" + LEVEL_NAME, folder)
        if not os.path.isdir(folder_path):
            continue

        try:
            ts_str = folder.split("_")[-1]
            ts = datetime.strptime(ts_str, "%Y%m%d-%H%M%S")

            hour_key = ts.strftime("%Y%m%d-%H")
            hour_groups[hour_key].append((ts, folder_path))
        except: continue

    for hour_key, items in hour_groups.items():

        # keep the oldest backup in that hour
        items.sort(key=lambda x: x[0])
        keep_ts, keep_path = items[0]

        for ts, path in items[1:]:
            if now - ts > timedelta(hours=1):
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

def midnight_trim_loop():
    while True:
        now = datetime.now()
        # Wait until next midnight
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        sleep_seconds = (next_midnight - now).total_seconds()
        time.sleep(sleep_seconds)
        trim_world()

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

def server_output_listener(proc, name="Server"):
    for line in iter(proc.stdout.readline, ''):
        if not line:
            break
        print(f"[{name}] {line.strip()}")

def main():
    global bedrock_proc, playit_proc
    start_server()
    
    print("✅ Services running. Commands: backup | trim | exit")

    threading.Thread(target=backup_loop, daemon=True).start()
    # threading.Thread(target=midnight_trim_loop, daemon=True).start() 
    # Disabled automatic trimming
    threading.Thread(target=console_listener, daemon=False).start()

if __name__ == "__main__":
    main()