import os
import json
import requests
import uvicorn
import io
import sys
import traceback
import re
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
from openai import OpenAI

# --- SETUP ---
app = FastAPI()

# --- AI PIPE CONFIGURATION ---
# Render ke Environment Variables se token lenge
AIPIPE_TOKEN = os.environ.get("AIPIPE_TOKEN")

if not AIPIPE_TOKEN:
    print("⚠️ WARNING: AIPIPE_TOKEN not found!")

# AI Pipe ka URL (Docs se liya hai)
AIPIPE_BASE_URL = "https://aipipe.org/openrouter/v1"

# Client Setup (OpenAI library use kar rahe hain par AI Pipe ke server par)
client = OpenAI(
    api_key=AIPIPE_TOKEN,
    base_url=AIPIPE_BASE_URL
)

# Tumhara Secret Code
MY_SECRET = os.environ.get("MY_SECRET", "default_secret_123") 

class QuizTask(BaseModel):
    email: str
    secret: str
    url: str

# --- HELPER: EXECUTE CODE ---
def execute_python_code(code_str: str):
    old_stdout = sys.stdout
    redirected_output = sys.stdout = io.StringIO()
    try:
        print("🐍 Executing AI Code...")
        # Global imports pass kar rahe hain
        exec(code_str, {'__name__': '__main__', 'requests': requests, 'json': json, 're': re})
        return redirected_output.getvalue().strip()
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        sys.stdout = old_stdout

# --- CORE LOGIC ---
async def process_quiz_loop(start_url: str, email: str, secret: str):
    current_url = start_url
    visited_urls = set()

    print(f"🚀 Starting Quiz Loop at: {current_url}")

    while current_url and current_url not in visited_urls:
        visited_urls.add(current_url)
        print(f"\n📍 Processing Level: {current_url}")

        try:
            # 1. SCRAPE PAGE
            async with async_playwright() as p:
                print("Browser launching...")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(current_url)
                try: await page.wait_for_selector("body", timeout=5000)
                except: pass
                visible_text = await page.inner_text("body")
                await browser.close()
                print("✅ Page Scraped.")

            # 2. ASK AI PIPE (OpenRouter via AI Pipe)
            prompt = f"""
            You are a Python Expert.
            Webpage Content:
            ---
            {visible_text[:7000]}
            ---
            
            Goal:
            1. Identify Question.
            2. Find Submission URL.
            3. Write Python code to solve it.
            
            REQUIREMENTS:
            - Output valid JSON string with keys: "answer", "submission_url".
            - Output ONLY raw Python code.
            """

            print(f"🤖 Asking AI Pipe...")
            
            # Docs k hisab se 'openai/gpt-4.1-nano' ya 'openai/gpt-4o-mini' use kar sakte hain
            # Hum 'openai/gpt-4o-mini' try karenge jo OpenRouter par available hota hai
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini", 
                messages=[
                    {"role": "system", "content": "You are a coding assistant. Output only python code."},
                    {"role": "user", "content": prompt}
                ]
            )
            
            ai_code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
            print(f"🤖 AI Logic Generated.")

            # 3. EXECUTE CODE
            execution_result = execute_python_code(ai_code)
            print(f"⚡ Result: {execution_result}")

            # Parse & Submit
            submit_url = None
            answer = None
            try:
                json_match = re.search(r'\{.*\}', execution_result, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    answer = data.get("answer")
                    submit_url = data.get("submission_url")
                    if submit_url and not submit_url.startswith("http"):
                        from urllib.parse import urljoin
                        submit_url = urljoin(current_url, submit_url)
            except: pass

            if not submit_url:
                print("❌ URL not found.")
                break

            payload = {"email": email, "secret": secret, "url": current_url, "answer": answer}
            print(f"📤 Submitting to {submit_url}...")
            
            try:
                res = requests.post(submit_url, json=payload, timeout=10).json()
                print(f"✅ Response: {res}")
                if res.get("correct") == True and "url" in res:
                    current_url = res["url"]
                else:
                    current_url = None
            except Exception as e:
                print(f"❌ Fail: {e}")
                current_url = None

        except Exception as e:
            print(f"🔥 Error: {e}")
            current_url = None

@app.post("/quiz")
async def receive_task(task: QuizTask, background_tasks: BackgroundTasks):
    if task.secret != MY_SECRET:
        raise HTTPException(status_code=403, detail="Invalid Secret")
    background_tasks.add_task(process_quiz_loop, task.url, task.email, task.secret)
    return {"message": "AI Pipe Agent started."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
