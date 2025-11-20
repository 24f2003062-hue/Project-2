import os
import json
import requests
import uvicorn
import io
import sys
import traceback
import re
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
import google.generativeai as genai

# --- SETUP ---
app = FastAPI()

# Gemini API Setup
# Render ke Environment Variable se Key uthayega
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("⚠️ WARNING: GEMINI_API_KEY not found in environment variables!")

genai.configure(api_key=api_key)

# Model Configuration
# Hum 'gemini-1.5-flash' use kar rahe hain.
# Agar requirements.txt updated hai to ye pakka chalega.
model = genai.GenerativeModel('gemini-1.5-flash')

# Tumhara Secret Code
MY_SECRET = os.environ.get("MY_SECRET", "default_secret_123") 

class QuizTask(BaseModel):
    email: str
    secret: str
    url: str

# --- HELPER: EXECUTE AI GENERATED CODE ---
def execute_python_code(code_str: str):
    """
    Gemini dwara diye gaye code ko execute karta hai.
    """
    # Capture standard output
    old_stdout = sys.stdout
    redirected_output = sys.stdout = io.StringIO()
    
    try:
        print("🐍 Executing AI Code...")
        # Code execute karo
        exec(code_str, {'__name__': '__main__', 'requests': requests, 'json': json, 're': re})
        result = redirected_output.getvalue()
        return result.strip()
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        sys.stdout = old_stdout

# --- CORE LOGIC: THE AGENT ---
async def process_quiz_loop(start_url: str, email: str, secret: str):
    current_url = start_url
    visited_urls = set()

    print(f"🚀 Starting Quiz Loop at: {current_url}")

    while current_url and current_url not in visited_urls:
        visited_urls.add(current_url)
        print(f"\n📍 Processing Level: {current_url}")

        try:
            # 1. SCRAPE PAGE (The Eyes)
            async with async_playwright() as p:
                print("browser launching...")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(current_url)
                
                # Thoda wait taaki JS load ho jaye
                try:
                    await page.wait_for_selector("body", timeout=5000)
                except:
                    pass
                
                visible_text = await page.inner_text("body") # Visible text
                # Kabhi kabhi hidden links script tags mein hote hain
                page_content = await page.content() 
                await browser.close()
                print("✅ Page Scraped Successfully.")

            # 2. ASK GEMINI TO SOLVE (The Brain)
            prompt = f"""
            You are an expert Python developer and Data Analyst.
            Here is the raw text content from a web page quiz:
            
            --- START CONTENT ---
            {visible_text[:6000]}
            --- END CONTENT ---
            
            Your Goal:
            1. Understand the Question asking for a specific answer.
            2. Find the JSON submission URL (it might be relative or absolute).
            3. Write a PYTHON SCRIPT to solve the question.
            
            IMPORTANT REQUIREMENTS FOR YOUR PYTHON CODE:
            - The code must calculate the answer.
            - The code must PRINT the final output as a valid JSON string.
            - The JSON must have keys: "answer" (the calculated value) and "submission_url" (the url to post to).
            - Do not use input().
            - Output ONLY valid Python code. No markdown backticks.
            - Example of what your code should print: {{"answer": 42, "submission_url": "https://example.com/submit"}}
            """

            print("🤖 Asking Gemini...")
            # Gemini se response mango
            response = model.generate_content(prompt)
            
            # Response clean karo (Markdown hatana)
            ai_code = response.text.replace("```python", "").replace("```", "").strip()
            print(f"🤖 Gemini Logic Generated.")

            # 3. EXECUTE CODE (The Hands)
            execution_result = execute_python_code(ai_code)
            print(f"⚡ Execution Result: {execution_result}")

            # Parse JSON result
            submit_url = None
            answer = None
            
            try:
                # Kabhi kabhi extra text aa jata hai, sirf JSON wala part dhundte hain
                json_match = re.search(r'\{.*\}', execution_result, re.DOTALL)
                if json_match:
                    result_data = json.loads(json_match.group())
                    answer = result_data.get("answer")
                    submit_url = result_data.get("submission_url")
                    
                    # Agar URL relative hai (e.g. /submit), to full banao
                    if submit_url and not submit_url.startswith("http"):
                        # Base URL logic
                        from urllib.parse import urljoin
                        submit_url = urljoin(current_url, submit_url)
                else:
                    print("⚠️ No JSON found in output")

            except Exception as parse_error:
                print(f"❌ JSON Parsing Failed: {parse_error}")
                break

            if not submit_url:
                print("❌ Submission URL not found. Stopping.")
                break

            # 4. SUBMIT ANSWER
            payload = {
                "email": email,
                "secret": secret,
                "url": current_url,
                "answer": answer
            }
            
            print(f"📤 Submitting to {submit_url}...")
            # Timeout add kiya taaki latak na jaye
            try:
                response = requests.post(submit_url, json=payload, timeout=10)
                res_json = response.json()
                print(f"✅ Server Response: {res_json}")

                # 5. CHECK FOR NEXT LEVEL
                if res_json.get("correct") == True and "url" in res_json:
                    current_url = res_json["url"]
                    print("🎉 Correct! Next level loading...")
                else:
                    print("🏁 Quiz Finished or Wrong Answer.")
                    current_url = None
            except Exception as req_err:
                print(f"❌ Submission Failed: {req_err}")
                current_url = None

        except Exception as e:
            print(f"🔥 Critical Error: {e}")
            traceback.print_exc()
            current_url = None

@app.post("/quiz")
async def receive_task(task: QuizTask, background_tasks: BackgroundTasks):
    print(f"Incoming Request from: {task.email}")
    
    # Security Check
    if task.secret != MY_SECRET:
        raise HTTPException(status_code=403, detail="Invalid Secret")

    # Start Logic in Background
    background_tasks.add_task(process_quiz_loop, task.url, task.email, task.secret)
    
    return {"message": "Gemini Agent started. I will solve this."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
