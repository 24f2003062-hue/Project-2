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

app = FastAPI()

# --- CONFIGURATION ---
# Render Environment se Token uthayega
AIPIPE_TOKEN = os.environ.get("AIPIPE_TOKEN")
MY_SECRET = os.environ.get("MY_SECRET", "hemant_secret_123")

if not AIPIPE_TOKEN:
    print("⚠️ WARNING: AIPIPE_TOKEN not found! Check Render Environment Variables.")

# Client Setup pointing to AI Pipe
client = OpenAI(
    api_key=AIPIPE_TOKEN,
    base_url="https://aipipe.org/openrouter/v1"
)

class QuizTask(BaseModel):
    email: str
    secret: str
    url: str

def execute_python_code(code_str: str):
    old_stdout = sys.stdout
    redirected_output = sys.stdout = io.StringIO()
    try:
        exec(code_str, {'__name__': '__main__', 'requests': requests, 'json': json, 're': re})
        return redirected_output.getvalue().strip()
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        sys.stdout = old_stdout

async def process_quiz_loop(start_url: str, email: str, secret: str):
    current_url = start_url
    visited_urls = set()
    print(f"🚀 Starting Quiz Loop at: {current_url}")

    while current_url and current_url not in visited_urls:
        visited_urls.add(current_url)
        print(f"\n📍 Processing Level: {current_url}")
        try:
            # 1. SCRAPE
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(current_url)
                try: await page.wait_for_selector("body", timeout=5000)
                except: pass
                visible_text = await page.inner_text("body")
                await browser.close()
                print("✅ Page Scraped.")

            # 2. ASK AI PIPE
            prompt = f"""
            You are a Python Expert. Page Content: {visible_text[:7000]}
            Goal: Find Question, Find Submission URL, Write Python code to solve.
            REQUIREMENTS: Output JSON string {{ "answer": ..., "submission_url": ... }}. Output ONLY raw Python code.
            """
            print(f"🤖 Asking AI Pipe...")
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini", 
                messages=[{"role": "user", "content": prompt}]
            )
            ai_code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
            
            # 3. EXECUTE
            execution_result = execute_python_code(ai_code)
            print(f"⚡ Result: {execution_result}")

            # 4. SUBMIT
            submit_url = None
            answer = None
            try:
                data = json.loads(re.search(r'\{.*\}', execution_result, re.DOTALL).group())
                answer = data.get("answer")
                submit_url = data.get("submission_url")
                if submit_url and not submit_url.startswith("http"):
                    from urllib.parse import urljoin
                    submit_url = urljoin(current_url, submit_url)
            except: pass

            if not submit_url:
                print("❌ URL not found."); break

            payload = {"email": email, "secret": secret, "url": current_url, "answer": answer}
            print(f"📤 Submitting to {submit_url}...")
            res = requests.post(submit_url, json=payload, timeout=10).json()
            print(f"✅ Response: {res}")
            
            if res.get("correct") == True and "url" in res:
                current_url = res["url"]
            else:
                current_url = None

        except Exception as e:
            print(f"🔥 Error: {e}"); current_url = None

@app.post("/quiz")
async def receive_task(task: QuizTask, background_tasks: BackgroundTasks):
    if task.secret != MY_SECRET: raise HTTPException(status_code=403, detail="Invalid Secret")
    background_tasks.add_task(process_quiz_loop, task.url, task.email, task.secret)
    return {"message": "AI Pipe Agent started."}
