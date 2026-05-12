import requests
import json
import os
import time
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from threading import Lock
from datetime import datetime

# --- CONFIG ---
IGNORED = {
    '.git', '.devcontainer', '__pycache__',
    'requirements.txt', 'jazz_cookies.json', '.jazz_cookies.json',
    'upload.py', 'login.py', 'anikai.py', 'Direct.py', 'youtube.py',
    'bot.py', 'README.md', 'Guest_Sessions'
}
REAL_ROOT_ID = 1677237

# --- SPEED SETTINGS ---
MAX_WORKERS = 8   # Multiple files ke liye 8 connections
MAX_RETRIES = 5   # Retries badha diye
# Single file speed badhane ke liye buffer size
UPLOAD_CHUNK_SIZE = 8192 * 16  # 128KB chunks (Aggressive upload)

session = requests.Session()
adapter = HTTPAdapter(
    max_retries=Retry(total=5, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]), 
    pool_connections=50, 
    pool_maxsize=50
)
session.mount("https://", adapter)
bar_lock = Lock()

# --- COOKIE HELPERS ---
def get_cookie_file():
    if os.path.exists(".jazz_cookies.json"): return ".jazz_cookies.json"
    elif os.path.exists("jazz_cookies.json"): return "jazz_cookies.json"
    return None

def load_cookies():
    cookie_file = get_cookie_file()
    if not cookie_file: return None, None
    try:
        with open(cookie_file, 'r') as f: data = json.load(f)
        raw_cookies = data.get('cookies', [])
        cookies = {c['name']: c['value'] for c in raw_cookies}
        key = next((c['value'] for c in raw_cookies if c['name'] == 'validationKey'), None)
        return cookies, key
    except: return None, None

def get_cloud_folders(cookies, key, parent_id=REAL_ROOT_ID):
    url = f"https://cloud.jazzdrive.com.pk/sapi/media/folder?action=list&parentid={parent_id}&limit=100&validationkey={key}"
    try:
        res = session.get(url, cookies=cookies, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        data = res.json()
        folders = []
        items = data.get('data', {}).get('folders', []) or data.get('metadata', {}).get('folders', [])
        for item in items:
            folders.append((item['name'], item['id']))
        return folders
    except: return []

def create_cloud_folder(name, parent_id, cookies, key):
    url = f"https://cloud.jazzdrive.com.pk/sapi/media/folder?action=save&validationkey={key}"
    payload = {"data": {"magic": False, "offline": False, "name": name, "parentid": int(parent_id)}}
    try:
        res = session.post(url, cookies=cookies, json=payload, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        d = res.json()
        new_id = d.get('id') or d.get('data', {}).get('id')
        return new_id if new_id else parent_id
    except: return parent_id

def upload_worker(args):
    path, cookies, key, folder_id, pbar = args
    fname = os.path.basename(path)
    fsize = os.path.getsize(path)
    mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    
    metadata = {
        "name": fname,
        "size": str(fsize),
        "folderid": str(folder_id),
        "contenttype": mime,
        "modificationdate": datetime.now().strftime("%Y%m%dT%H%M%SZ")
    }

    # Custom Header for Speed
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Connection': 'keep-alive'
    }

    for attempt in range(MAX_RETRIES):
        try:
            with open(path, 'rb') as f:
                # Seek start
                f.seek(0)
                previous_chunk = 0
                
                def callback(monitor):
                    nonlocal previous_chunk
                    chunk = monitor.bytes_read - previous_chunk
                    previous_chunk = monitor.bytes_read
                    with bar_lock: pbar.update(chunk)

                m = MultipartEncoder(fields={
                    'data': (None, json.dumps({"data": metadata}), 'application/json'), 
                    'file': (fname, f, mime)
                })
                
                monitor = MultipartEncoderMonitor(m, callback)
                headers['Content-Type'] = monitor.content_type
                
                # Streaming upload with larger chunk size
                res = session.post(
                    f"https://cloud.jazzdrive.com.pk/sapi/upload?action=save&acceptasynchronous=true&validationkey={key}",
                    data=monitor, 
                    headers=headers, 
                    cookies=cookies,
                    timeout=600  # Long timeout for big files
                )
                
                if res.status_code == 200:
                    break
                else:
                    raise Exception(f"HTTP {res.status_code}")

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
            else:
                with bar_lock: tqdm.write(f"❌  FAILED: {fname} - {e}")

def main():
    cookies, key = load_cookies()
    if not key:
        print("❌  Login missing! Run 'login.py'")
        return
    
    # 1. LIST FILES
    all_files = os.listdir('.')
    targets = sorted([f for f in all_files if f not in IGNORED and not f.startswith('.')])
    
    print("\n📂 --- FILES TO UPLOAD ---")
    if not targets: print("⚠️ No files found."); return
        
    for i, t in enumerate(targets):
        tag = "📁" if os.path.isdir(t) else "📄"
        print(f"{i}: {tag} {t}")
        
    try:
        sel_idx = int(input("\n👉 Select Number: "))
        sel = targets[sel_idx]
    except:
        print("❌  Invalid Selection"); return

    # 2. SELECT DESTINATION
    cloud_folders = get_cloud_folders(cookies, key, REAL_ROOT_ID)
    
    print("\n☁️ --- DESTINATION ---")
    print(f"0: [🏠 ROOT]")
    for i, (name, fid) in enumerate(cloud_folders):
        print(f"{i+1}: [📁 {name}]")
    
    dest_choice_raw = input("\n👉 Number OR Folder Name: ").strip()
    
    dest_id = REAL_ROOT_ID
    dest_name = "ROOT"

    if dest_choice_raw.isdigit():
        choice_idx = int(dest_choice_raw)
        if choice_idx > 0 and choice_idx <= len(cloud_folders):
            dest_name, dest_id = cloud_folders[choice_idx-1]
    else:
        found = False
        for name, fid in cloud_folders:
            if name.lower() == dest_choice_raw.lower():
                dest_id = fid
                dest_name = name
                found = True
                print(f"🎯 Found: {name}")
                break
        if not found:
            print(f"⚠️ Not found. Using ROOT.")

    # 3. PROCESSING
    full_path = os.path.abspath(sel)
    tasks = []
    total_size = 0
    
    print(f"\n📦 Target: {dest_name}")

    if os.path.isfile(full_path):
        # Single File Logic
        tasks.append((full_path, cookies, key, dest_id))
        total_size += os.path.getsize(full_path)
    else:
        # Folder Logic
        base_name = os.path.basename(full_path)
        
        print(f"🔎 Checking duplicates in '{dest_name}'...")
        
        items_in_dest = get_cloud_folders(cookies, key, dest_id)
        existing_match_id = None
        
        for name, fid in items_in_dest:
            if name == base_name:
                existing_match_id = fid
                break
        
        main_cloud_id = None
        
        if existing_match_id:
            print(f"\n⚠️  Folder '{base_name}' already exists!")
            print(f"1. MERGE (Upload files INSIDE existing '{base_name}')")
            print(f"2. NEW (Create '{base_name}_New')")
            
            # Auto-prompt logic
            while True:
                choice = input("👉 Choice (1=Merge / 2=New): ").strip()
                if choice == '1':
                    print(f"✅ MERGING files directly into existing folder...")
                    main_cloud_id = existing_match_id
                    break
                elif choice == '2':
                    ts = datetime.now().strftime("%H%M")
                    new_name = f"{base_name}_New_{ts}"
                    print(f"✅ Creating NEW folder: '{new_name}'")
                    main_cloud_id = create_cloud_folder(new_name, dest_id, cookies, key)
                    break
        else:
            print(f"✅ Creating folder: '{base_name}'")
            main_cloud_id = create_cloud_folder(base_name, dest_id, cookies, key)

        # File Mapping
        # Yahan hum folder_map ko initialize karte hain
        folder_map = {full_path: main_cloud_id}
        
        for root, dirs, files in os.walk(full_path):
            files = [f for f in files if f not in IGNORED]
            current_cloud_id = folder_map.get(root, main_cloud_id)
            
            for d in dirs:
                if d in IGNORED: continue
                # Sub-folders humesha create honge, chahe merge ho ya new
                # Kyunki hum chahte hain structure same rahe
                new_cloud_id = create_cloud_folder(d, current_cloud_id, cookies, key)
                folder_map[os.path.join(root, d)] = new_cloud_id
                
            for f in files:
                fp = os.path.join(root, f)
                tasks.append((fp, cookies, key, current_cloud_id))
                total_size += os.path.getsize(fp)

    if not tasks: print("❌  Empty!"); return

    print(f"\n🚀 Uploading {len(tasks)} files...")
    print(f"⚡ Parallel Connections: {MAX_WORKERS}")

    with tqdm(total=total_size, unit='B', unit_scale=True, unit_divisor=1024, ncols=80, colour='green') as pbar:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            list(pool.map(upload_worker, [(t[0], t[1], t[2], t[3], pbar) for t in tasks]))

    print("\n🏁 **Completed.**")

if __name__ == "__main__":
    main()
