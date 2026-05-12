import asyncio
from playwright.async_api import async_playwright

async def login_step():
    print("🚀 Initializing JazzDrive Login (Fast Mode)...")
    async with async_playwright() as p:
        # 1. Browser Launch Optimization (Faltu cheezein disable kardi hain taake foran khule)
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage', # Codespace memory fix
                '--disable-accelerated-2d-canvas',
                '--no-first-run'
            ]
        )
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = await context.new_page()

        print("🌐 Opening Login Page...")
        # 2. Sirf HTML load hone ka wait karega, puri images ka nahi (Time saved)
        await page.goto("https://cloud.jazzdrive.com.pk/login", wait_until="domcontentloaded")

        # Step 1: Number
        num = input("📱 Enter Jazz Number (03xxxxxxxxx): ")
        await page.fill('input[type="tel"]', num)
        await page.click('#signinbtn')

        # Step 2: OTP
        print("⏳ Waiting for OTP field...")
        # 2 Second ka wait hata diya, kyunke 'wait_for_selector' khud hi jab tak element nahi aata wait karega
        await page.wait_for_selector('#otp', state="attached")

        otp = input("🔢 Enter 4-digit PIN: ")

        # Direct Injection
        await page.evaluate(f'document.getElementById("otp").value = "{otp}"')
        
        print("⚙️ Verifying Login...")
        # Click karte hi check shuru
        await page.click('#signinbtn')

        # 3. 5 Second ka wait hata diya. Ab ye "Network" rukne ka wait karega (max 1-2 sec)
        try:
            await page.wait_for_load_state("networkidle") 
            # Ya agar URL change hoti hai to ye bhi fast hai:
            # await page.wait_for_url("**/drive", timeout=5000)

            # Save Cookies Immediately
            await context.storage_state(path="jazz_cookies.json")
            print("✅ LOGIN SUCCESS! 'jazz_cookies.json' saved instantly.")
        except Exception as e:
            print(f"❌ Verification warning (Check saved file): {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(login_step())
