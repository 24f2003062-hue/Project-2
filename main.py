from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uvicorn
import time

# Initialize the App
app = FastAPI()

# --- CONFIGURATION ---
# Ye wo secret code hai jo tum Google Form mein bhi bharoge
MY_SECRET = "hemant_super_secret_key_2025"
MY_EMAIL = "tumhara_email@example.com"

# --- DATA MODEL ---
# Ye define karta hai ki request kaisi dikhni chahiye
class QuizTask(BaseModel):
    email: str
    secret: str
    url: str

# --- LOGIC ---
def solve_quiz_logic(task: QuizTask):
    """
    Ye function background mein chalega.
    Abhi hum bas print karenge, baad mein yahan AI logic aayega.
    """
    print(f"\n[Background] Task Started for URL: {task.url}")
    print("[Background] Processing... (yahan scraping aur AI ka kaam hoga)")
    
    # Simulate time taking process (ex: 3 seconds)
    time.sleep(3)
    
    print(f"[Background] Task Finished for {task.url}\n")
    # Future Step: Yahan se hum answer wapis POST karenge

# --- API ENDPOINT ---
@app.post("/quiz")
async def receive_task(task: QuizTask, background_tasks: BackgroundTasks):
    print(f"\n[Incoming Request] From: {task.email}")

    # 1. SECURITY CHECK: Kya secret sahi hai?
    if task.secret != MY_SECRET:
        print("--> Access Denied: Wrong Secret")
        # Agar galat hai to 403 error wapis bhejo
        raise HTTPException(status_code=403, detail="Invalid Secret Code")

    # 2. START BACKGROUND TASK
    # Hum server ko bol rahe hain: "Ye logic background mein chalao, user ko wait mat karao"
    background_tasks.add_task(solve_quiz_logic, task)

    # 3. IMMEDIATE RESPONSE
    print("--> Access Granted: 200 OK sent")
    return {"message": "Task received successfully, processing started."}

# --- RUN SERVER ---
# Is block ka matlab hai agar ye file direct run ho rahi hai to server start karo
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
