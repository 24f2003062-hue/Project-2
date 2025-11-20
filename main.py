# --- OPTIMIZED MAIN LOGIC (Isse Copy-Paste karo) ---
async def process_quiz_loop(start_url: str, email: str, secret: str):
    current_url = start_url
    visited_urls = set()
    print(f"🚀 Starting Quiz Loop at: {current_url}")

    while current_url and current_url not in visited_urls:
        visited_urls.add(current_url)
        print(f"\n📍 Processing Level: {current_url}")
        try:
            # A. SCRAPE (OPTIMIZED FOR SPEED)
            async with async_playwright() as p:
                print("⏳ Launching Browser (Turbo Mode)...")
                # Ye flags browser ko crash hone se bachate hain aur fast karte hain
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--no-first-run",
                        "--no-zygote",
                        "--single-process",
                        "--disable-gpu"
                    ]
                )
                page = await browser.new_page()
                
                print(f"🌐 Navigating to {current_url}...")
                # Timeout set kiya taaki latke nahi (30 sec max)
                await page.goto(current_url, timeout=30000, wait_until="domcontentloaded")
                
                try: await page.wait_for_selector("body", timeout=5000)
                except: pass
                
                visible_text = await page.inner_text("body")
                links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a')).map(a => a.href);
                }""")
                await browser.close()
                print(f"✅ Page Scraped. Found {len(links)} links.")

            # B. ASK AI (STRICT MODE)
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
            - **DO NOT SUBMIT DATA**: Do NOT use `requests.post`. Only calculate.
            - **NO PLACEHOLDERS**: Use REAL links from the list.
            - **OUTPUT FORMAT**: JSON string: {{"answer": <value>, "submission_url": "<url>"}}
            - **ANSWER TYPE**: String or Number only.
            - Output ONLY raw Python code.
            """

            print(f"🤖 Asking AI Pipe...")
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini", 
                messages=[{"role": "user", "content": prompt}]
            )
            ai_code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
            print(f"📝 AI Code Generated.")

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
            
            if isinstance(answer, dict): answer = str(answer)

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
