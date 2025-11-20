import os
import json
import requests
import uvicorn
import io
import sys
import traceback
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
from openai import OpenAI

# --- SETUP ---
app = FastAPI()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))  # Render Environment Variable se lega

# Tumhara Secret Code
MY_SECRET = os.environ.get("MY_SECRET", "default_secret_123") 

class QuizTask(BaseModel):
    email: str
    secret: str
    url: str

# --- HELPER: EXECUTE AI GENERATED CODE ---
def execute_python_code(code_str: str):
    """
    LLM dwara diye gaye code ko execute karta hai aur printed JSON output return karta hai.
    """
    # Capture standard output
    old_stdout = sys.stdout
    redirected_output = sys.stdout = io.StringIO()
    
    try:
        # Code execute karo
        exec(code_str, {'__name__': '__main__', 'requests': requests, 'json': json})
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
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(current_url)
                
                # Wait for potential JS rendering
                try:
                    await page.wait_for_selector("body", timeout=5000)
                except:
                    pass
                
                # Get content
                content = await page.content() # Full HTML
                visible_text = await page.inner_text("body") # Clean text
                await browser.close()

            # 2. ASK LLM TO SOLVE (The Brain)
            # Hum LLM ko bolenge: "Code likho jo answer nikal kar JSON print kare"
            prompt = f"""
            You are an autonomous data analyst agent.
            I have a task from a webpage. Here is the visible text and HTML content:
            
            --- CONTENT START ---
            {visible_text[:4000]} 
            --- CONTENT END ---
            
            Your Goal:
            1. Identify the Question.
            2. Identify the Submission URL (it is usually mentioned or inside a script tag).
            3. Write a PYTHON SCRIPT to calculate the answer.
            
            IMPORTANT INSTRUCTIONS FOR PYTHON SCRIPT:
            - If the task involves downloading a CSV/PDF, use `requests` to download it.
            - Perform the calculation (sum, filter, etc.).
            - PRINT the final output as a valid JSON string with keys: "answer" and "submission_url".
            - Do NOT use input().
            - Do NOT print anything else except the final JSON.
            - Example Output format: {{"answer": 123, "submission_url": "https://example.com/submit"}}
            
            Send ONLY the Python code block. No markdown like ```python.
            """

            chat_completion = client.chat.completions.create(
                messages=[{"role": "system", "content": "You are a Python coding assistant."},
                          {"role": "user", "content": prompt}],
                model="gpt-4o-mini", # Cost effective and smart
            )

            ai_code = chat_completion.choices[0].message.content.replace("```python", "").replace("```", "").strip()
            print(f"🤖 AI Generated Code Logic...")

            # 3. EXECUTE CODE (The Hands)
            execution_result = execute_python_code(ai_code)
            print(f"⚡ Execution Result: {execution_result}")

            # Parse JSON result from AI code
            try:
                result_data = json.loads(execution_result)
                answer = result_data.get("answer")
                submit_url = result_data.get("submission_url")
            except:
                print("❌ Failed to parse AI output as JSON.")
                break

            if not submit_url:
                print("❌ Submission URL not found.")
                break

            # 4. SUBMIT ANSWER
            payload = {
                "email": email,
                "secret": secret,
                "url": current_url,
                "answer": answer
            }
            
            print(f"📤 Submitting to {submit_url}: {payload}")
            response = requests.post(submit_url, json=payload)
            res_json = response.json()
            
            print(f"✅ Server Response: {res_json}")

            # 5. CHECK FOR NEXT LEVEL
            if res_json.get("correct") == True and "url" in res_json:
                current_url = res_json["url"]
                print("🎉 Correct! Moving to next level...")
            else:
                print("🏁 Quiz Finished or Wrong Answer.")
                current_url = None

        except Exception as e:
            print(f"🔥 Critical Error: {e}")
            traceback.print_exc()
            current_url = None

@app.post("/quiz")
async def receive_task(task: QuizTask, background_tasks: BackgroundTasks):
    # Security Check
    if task.secret != MY_SECRET:
        raise HTTPException(status_code=403, detail="Invalid Secret")

    # Start Logic in Background
    background_tasks.add_task(process_quiz_loop, task.url, task.email, task.secret)
    
    return {"message": "Agent started. I will solve this."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
