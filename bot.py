import os
import asyncio
from pyrogram import Client, filters
from playwright.async_api import async_playwright

# Aapki existing upload.py yahan import hogi
import upload 

API_ID = os.environ.get("API_ID", "YOUR_API_ID")
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")

app = Client("railway_bot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

user_state = {}

# ════════════════════════════════════════════════════════════
# 🔐 INTERACTIVE LOGIN SYSTEM
# ════════════════════════════════════════════════════════════
@app.on_message(filters.command("login"))
async def start_login(client, message):
    if len(message.command) < 2:
        await message.reply("❌ Number bhi likhein. Example: `/login 03001234567`")
        return
    
    number = message.command[1]
    chat_id = message.chat.id
    user_state[chat_id] = {'otp': None, 'files': [], 'folder': 'ROOT'}
    
    status_msg = await message.reply(f"🚀 JazzDrive Login start kar raha hoon number: `{number}` par...")
    
    # Playwright ko background task mein chalayenge taake bot hang na ho
    asyncio.create_task(run_playwright_login(chat_id, number, status_msg))

@app.on_message(filters.command("otp"))
async def receive_otp(client, message):
    chat_id = message.chat.id
    if chat_id in user_state and len(message.command) == 2:
        user_state[chat_id]['otp'] = message.command[1]
        await message.reply("✅ OTP receive ho gaya, browser mein enter kar raha hoon...")
    else:
        await message.reply("❌ Pehle `/login` karein, ya format sahi rakhein: `/otp 1234`")

async def run_playwright_login(chat_id, number, status_msg):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            page = await context.new_page()

            await page.goto("https://cloud.jazzdrive.com.pk/login", wait_until="domcontentloaded")
            await page.fill('input[type="tel"]', number)
            await page.click('#signinbtn')

            await status_msg.edit_text("⏳ Number submit ho gaya! Ab SMS check karein aur jaldi se OTP is tarah bhejein:\n`/otp 1234`")

            # Bot OTP ka wait karega (Max 60 seconds)
            wait_time = 0
            while user_state[chat_id]['otp'] is None:
                await asyncio.sleep(1)
                wait_time += 1
                if wait_time > 60:
                    await status_msg.edit_text("❌ OTP timeout! Dobara `/login` karein.")
                    await browser.close()
                    return
            
            # OTP milte hi direct inject karega
            otp = user_state[chat_id]['otp']
            await page.evaluate(f'document.getElementById("otp").value = "{otp}"')
            await page.click('#signinbtn')

            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
                await context.storage_state(path="jazz_cookies.json")
                await status_msg.edit_text("✅ **LOGIN SUCCESS!** Cookies save ho gayi hain. Ab aap `/Mu` se uploading start kar sakte hain.")
            except Exception as e:
                await status_msg.edit_text(f"❌ Verification fail (Check saved file): {e}")

            await browser.close()
    except Exception as e:
         await status_msg.edit_text(f"❌ Playwright Error: {str(e)}")

# ════════════════════════════════════════════════════════════
# 📂 UPLOAD SYSTEM
# ════════════════════════════════════════════════════════════
@app.on_message(filters.command("Mu"))
async def start_batch(client, message):
    user_state[message.chat.id] = {'files': [], 'state': 'COLLECTING'}
    await message.reply("📂 Batch mode start! Files forward karein. Done hone pe `/end` type karein.")

@app.on_message(filters.document | filters.video)
async def collect_files(client, message):
    chat_id = message.chat.id
    if chat_id in user_state and user_state[chat_id].get('state') == 'COLLECTING':
        user_state[chat_id]['files'].append(message)
        await message.reply(f"✅ File #{len(user_state[chat_id]['files'])} added in queue.")

@app.on_message(filters.command("end"))
async def process_upload(client, message):
    chat_id = message.chat.id
    if chat_id not in user_state or not user_state[chat_id].get('files'):
        await message.reply("⚠️ Koi file nahi mili!")
        return
    
    if not os.path.exists("jazz_cookies.json"):
        await message.reply("❌ Pehle `/login` command se login save karein!")
        return

    status_msg = await message.reply("⏳ Downloading files to Railway server...")
    
    # 1. Download Files locally
    downloaded_paths = []
    for msg in user_state[chat_id]['files']:
        file_path = await msg.download()
        downloaded_paths.append(file_path)
    
    await status_msg.edit_text("🚀 Uploading to JazzDrive...")

    # 2. Upload using your original module
    try:
        cookies, key = upload.load_cookies()
        
        class DummyPbar:
            def update(self, n): pass
            
        for path in downloaded_paths:
            # Apke upload_worker ko directly call kar raha hai
            args = (path, cookies, key, upload.REAL_ROOT_ID, DummyPbar())
            upload.upload_worker(args)
            os.remove(path) # Clean up after upload

        await status_msg.edit_text("🏁 **All files uploaded successfully to ROOT folder!**")
    except Exception as e:
        await status_msg.edit_text(f"❌ Upload Error: {e}")

    user_state[chat_id]['state'] = None
    user_state[chat_id]['files'] = []

app.run()
