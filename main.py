from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uvicorn
from playwright.async_api import async_playwright
import requests
import json

app = FastAPI()

# --- CONFIGURATION ---
MY_SECRET = "hemant_super_secret_key_2025" # Apni marzi ka secret rakho

class QuizTask(BaseModel):
    email: str
    secret: str
    url: str

# --- LOGIC: THE EYES (SCRAPING) ---
async def solve_quiz_logic(task: QuizTask):
    print(f"\n[Bot] Starting task for: {task.url}")
    
    try:
        async with async_playwright() as p:
            # 1. Launch Browser (Headless means bina UI ke)
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # 2. Go to URL
            print("[Bot] Navigating to URL...")
            await page.goto(task.url)
            
            # 3. Wait for Content (Handle JS Loading)
            # Problem statement ke hisab se kabhi kabhi content 'result' id mein hota hai
            # Hum thoda wait karenge taaki JS execute ho jaye
            try:
                await page.wait_for_selector("body", timeout=5000) 
            except:
                print("[Bot] Warning: Body load timeout, proceeding anyway.")

            # 4. Extract Visible Text (Clean Question)
            page_content = await page.inner_text("body")
            print(f"[Bot] SCRAPED CONTENT:\n{page_content}\n----------------")

            # --- Next Steps (Chunks 3 & 4) ---
            # Yahan hum LLM ko content bhejenge aur answer nikalenge.
            # Abhi ke liye hum fake answer bhej kar flow test karenge.
            
            # Maan lo LLM ne answer "12345" nikala
            fake_answer = 12345 
            
            # NOTE: Submission URL usually page par hi mention hota hai.
            # Filhal hum assume kar rahe hain ki submission url API response mein nahi mila
            # to hum hardcode kar rahe hain (Real logic Chunk 3 mein aayega).
            # Sample k hisab se: https://example.com/submit
            
            # Lekin abhi hum submit nahi karenge kyunki real URL nahi hai.
            # Hum bas logs mein print karke chod denge verify karne k liye.
            print(f"[Bot] Ready to submit answer: {fake_answer}")
            
            await browser.close()
            
    except Exception as e:
        print(f"[Bot] Error in processing: {e}")

# --- API ENDPOINT ---
@app.post("/quiz")
async def receive_task(task: QuizTask, background_tasks: BackgroundTasks):
    # 1. Verify Secret
    if task.secret != MY_SECRET:
        raise HTTPException(status_code=403, detail="Invalid Secret")

    # 2. Start Process
    background_tasks.add_task(solve_quiz_logic, task)
    
    # 3. Respond
    return {"message": "Task received, bot is working on it."}
