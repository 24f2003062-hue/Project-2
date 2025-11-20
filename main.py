# --- 4. MAIN LOGIC (Copy paste only this function inside main.py) ---
async def process_quiz_loop(start_url: str, email: str, secret: str):
    current_url = start_url
    visited_urls = set()
    print(f"🚀 Starting Quiz Loop at: {current_url}")

    while current_url and current_url not in visited_urls:
        visited_urls.add(current_url)
        print(f"\n📍 Processing Level: {current_url}")
        try:
            # A. SCRAPE
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(current_url)
                try: await page.wait_for_selector("body", timeout=5000)
                except: pass
                visible_text = await page.inner_text("body")
                links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a')).map(a => a.href);
                }""")
                await browser.close()
                print(f"✅ Page Scraped. Found {len(links)} links.")

            # B. ASK AI (STRICT MODE: NO SUBMISSION)
            prompt = f"""
            You are an expert Python Data Analyst.
            
            PAGE CONTENT:
            ---
            {visible_text[:6000]}
            ---
            AVAILABLE LINKS: {links}
            
            YOUR TASK:
            1. Identify the Question.
            2. Write Python code to CALCULATE the answer.
            3. Identify the Submission URL.
            
            CRITICAL RULES:
            - **DO NOT SUBMIT DATA**: Do NOT use `requests.post` in your code. Only calculate the value.
            - **NO PLACEHOLDERS**: Do not use strings like 'your_email' or 'your_secret'.
            - **OUTPUT FORMAT**: The code must print a JSON string: {{"answer": <calculated_value>, "submission_url": "<url>"}}
            - **ANSWER TYPE**: The "answer" value must be a String, Number, or List. It CANNOT be a Dictionary/Object.
            - Use `pd` for CSVs and `pypdf` for PDFs.
            - Output ONLY raw Python code.
            """

            print(f"🤖 Asking AI Pipe (Strict Mode)...")
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini", 
                messages=[{"role": "user", "content": prompt}]
            )
            ai_code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
            
            print(f"📝 AI Generated Code (Snippet):\n{ai_code[:200]}...\n----------------")

            # C. EXECUTE
            execution_result = execute_python_code(ai_code)
            print(f"⚡ Result: {execution_result}")

            # D. PARSE & SUBMIT
            submit_url = None
            answer = None
            try:
                match = re.search(r'\{.*\}', execution_result, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                    answer = data.get("answer")
                    submit_url = data.get("submission_url")
                    
                    if submit_url and not submit_url.startswith("http"):
                        from urllib.parse import urljoin
                        submit_url = urljoin(current_url, submit_url)
            except: pass

            if not submit_url:
                print("❌ Submission URL not found."); break
            
            # Check if answer is an object (Dictionary) - prevent recursion error
            if isinstance(answer, dict):
                print("⚠️ AI returned a dictionary as answer. Extracting 'message' or converting to string.")
                answer = str(answer)

            payload = {"email": email, "secret": secret, "url": current_url, "answer": answer}
            print(f"📤 Submitting to {submit_url} with answer: {answer}")
            
            res = requests.post(submit_url, json=payload, timeout=10).json()
            print(f"✅ Response: {res}")
            
            if res.get("correct") == True and "url" in res:
                current_url = res["url"]
            else:
                print("🏁 Quiz Finished.")
                current_url = None

        except Exception as e:
            print(f"🔥 Error: {e}"); traceback.print_exc(); current_url = None
