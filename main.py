# main.py — IITM-ready final version (AIPIPE transcription + SSRF medium + minimal logging)
import os
import re
import io
import time
import json
import traceback
import requests
import asyncio
from urllib.parse import urlparse, urljoin
from typing import List, Tuple, Optional, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Playwright & LLM client
from playwright.async_api import async_playwright, Page

# Optional libs
from bs4 import BeautifulSoup
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

# ---------- CONFIG ----------
MY_SECRET = os.environ.get("MY_SECRET")
AIPIPE_TOKEN = os.environ.get("AIPIPE_TOKEN")  # preferred for transcription (OpenRouter / AIPipe)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # fallback if AIPIPE not present
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "")  # comma-separated allowed hosts to bypass SSRF private-check
DEFAULT_BUDGET_SECONDS = int(os.environ.get("DEFAULT_BUDGET_SECONDS", "110"))
MAX_PAYLOAD_BYTES = 1_000_000  # 1MB

# Minimal logger (redacted)
def redact(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    if MY_SECRET:
        return s.replace(MY_SECRET, "<REDACTED>")
    return s

def log(msg: str):
    # minimal log output: one-line, short; do not print secrets
    print(msg)

app = FastAPI(title="llm-analysis-agent")

class QuizTask(BaseModel):
    email: str
    secret: str
    url: str

# ---------- Utilities ----------
def is_private_ip(hostname: str) -> bool:
    # medium SSRF: reject bare IPv4/IPv6 private/local ranges
    try:
        import ipaddress
        # if hostname is a raw IP
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        except ValueError:
            # not an IP — resolve only when necessary; skip DNS resolution to avoid network delay
            return False
    except Exception:
        return False

def host_allowed(hostname: str) -> bool:
    if not hostname:
        return False
    # allow explicit ALLOWED_HOSTS
    if ALLOWED_HOSTS:
        allowed = [h.strip().lower() for h in ALLOWED_HOSTS.split(",") if h.strip()]
        if hostname.lower() in allowed:
            return True
    # else medium policy: block private raw IPs, allow public hostnames
    if is_private_ip(hostname):
        return False
    # additional basic check to block 'localhost' and plain IPs in private ranges
    if hostname.lower() in ("localhost", "127.0.0.1"):
        return False
    return True

def safe_fetch_url_check(url: str):
    p = urlparse(url)
    scheme = p.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("Invalid URL scheme")
    hostname = p.hostname or ""
    if not host_allowed(hostname):
        raise ValueError(f"Blocked host by SSRF policy: {hostname}")

def safe_post_json(url: str, payload: dict, timeout: int = 10):
    safe_fetch_url_check(url)
    # enforce payload size
    raw = json.dumps(payload, default=str)
    if len(raw.encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("Payload too large")
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw_text": r.text, "status_code": r.status_code}

# ---------- Heuristics & validators ----------
def is_bad_answer(ans) -> bool:
    if ans is None:
        return True
    if isinstance(ans, bool):
        return False
    if isinstance(ans, (int, float)):
        return False
    if isinstance(ans, str):
        s = ans.strip()
        if s == "":
            return True
        if MY_SECRET and MY_SECRET in s:
            return True
        if len(s) > 1000:
            return True
    return False

def looks_like_secret(s: str) -> bool:
    if not isinstance(s, str):
        return False
    st = s.strip()
    if st == "":
        return False
    if len(st) <= 64 and re.fullmatch(r'[A-Za-z0-9_\-]{3,64}', st):
        return True
    if re.search(r'\b(secret|code|token|key|pass|pwd)\b', st, flags=re.I):
        return True
    if len(st) <= 4:
        return True
    return False

def find_submission_url_from_page(html: str, links: List[str], base_url: str) -> Optional[str]:
    # minimal but effective: prefer explicit submit-like links or form actions
    for l in links or []:
        if not l:
            continue
        low = l.lower()
        if any(k in low for k in ("submit", "answer", "response", "/submit")):
            return urljoin(base_url, l)
    m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, flags=re.I)
    if m:
        return urljoin(base_url, m.group(1))
    m2 = re.search(r'https?://[^\s\'"<>]+/(?:submit|answer|response)[^\s\'"<>]*', html, flags=re.I)
    if m2:
        return m2.group(0)
    for l in links or []:
        if l and l.startswith("http"):
            return l
    return None

# ---------- Transcription (AIPipe / OpenAI fallback) ----------
def transcribe_audio_bytes(audio_bytes: bytes, filename: str = "audio.mp3") -> Optional[str]:
    """
    Try AIPIPE OpenRouter transcription endpoint (if AIPIPE_TOKEN set).
    Fallback: OpenAI's v1/audio/transcriptions (if OPENAI_API_KEY set).
    Returns string transcript or None.
    """
    # attempt AIPIPE/OpenRouter first
    headers = {}
    if AIPIPE_TOKEN:
        try:
            safe_url = "https://aipipe.org/openrouter/v1/audio/transcriptions"
            files = {"file": (filename, audio_bytes)}
            # model param typical: whisper-1 ; adjust if needed
            data = {"model": "whisper-1"}
            headers = {"Authorization": f"Bearer {AIPIPE_TOKEN}"}
            resp = requests.post(safe_url, headers=headers, data=data, files=files, timeout=30)
            if resp.status_code == 200:
                j = resp.json()
                # try common fields
                if isinstance(j, dict) and "text" in j:
                    return j["text"]
                if isinstance(j, dict) and "transcript" in j:
                    return j["transcript"]
                # try raw text fallback
                return resp.text
        except Exception:
            pass

    # fallback to OpenAI API (v1/audio/transcriptions)
    if OPENAI_API_KEY:
        try:
            safe_url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            files = {"file": (filename, audio_bytes)}
            data = {"model": "whisper-1"}
            resp = requests.post(safe_url, headers=headers, data=data, files=files, timeout=30)
            if resp.status_code == 200:
                j = resp.json()
                # official response may include 'text'
                if isinstance(j, dict):
                    if "text" in j:
                        return j["text"]
                    if "transcript" in j:
                        return j["transcript"]
                return resp.text
        except Exception:
            pass

    return None

# ---------- Scraping helpers ----------
async def scrape_page(page: Page, url: str) -> Tuple[str, str, List[str]]:
    # minimal safe navigation
    try:
        safe_fetch_url_check(url)
    except Exception as e:
        raise

    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(600)
        except Exception:
            pass

    try:
        html = await page.content()
    except Exception:
        html = ""

    visible_text = ""
    try:
        sel = await page.query_selector("body")
        if sel:
            visible_text = await sel.inner_text()
    except Exception:
        visible_text = ""

    links = []
    try:
        links = await page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.href)")
    except Exception:
        links = []

    # decode any atob(...) in script tags (client side)
    try:
        decoded = await page.evaluate("""
            () => {
                const out = [];
                const re = /atob\\((?:`|['"])([^`'"]+)(?:`|['"])\\)/g;
                const scripts = Array.from(document.querySelectorAll('script'));
                for (const s of scripts) {
                    let m;
                    while ((m = re.exec(s.textContent || '')) !== null) {
                        try { out.push(atob(m[1])); } catch(e) {}
                    }
                }
                return out;
            }
        """)
        if decoded:
            joined = "\n\n".join(decoded)
            html += "\n\n<!--DECODED-->\n" + joined
            visible_text += "\n\n" + joined
    except Exception:
        pass

    return html, visible_text, links

# ---------- Heuristics for answers (simple) ----------
def extract_from_visible_numbers(text: str) -> Optional[float]:
    nums = re.findall(r'-?\d+\.?\d*', text)
    if not nums:
        return None
    # if many numbers, sum them if plausible (<200 numbers)
    if 1 < len(nums) <= 200:
        vals = [float(n) for n in nums]
        return float(sum(vals))
    # else return first
    n = nums[0]
    return float(n) if '.' in n else int(n)

# ---------- Main quiz loop ----------
async def process_quiz_loop(start_url: str, email: str, secret: str, total_budget_seconds: int = DEFAULT_BUDGET_SECONDS):
    if not MY_SECRET:
        raise RuntimeError("Server MY_SECRET not configured")
    if secret != MY_SECRET:
        raise RuntimeError("Invalid secret provided by caller")

    overall_start = time.time()
    current_url = start_url
    visited = set()
    log(f"START {redact(current_url)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        while current_url and current_url not in visited:
            visited.add(current_url)
            if time.time() - overall_start > total_budget_seconds:
                log("TIME_BUDGET_EXHAUSTED")
                break

            log(f"PROCESS {redact(current_url)}")
            try:
                html, visible_text, links = await scrape_page(page, current_url)
            except Exception as e:
                log(f"BLOCKED_URL {redact(str(e))}")
                break

            # quick heuristic: numbers in visible text
            heuristic = extract_from_visible_numbers(visible_text)
            submission_url = find_submission_url_from_page(html, links or [], current_url)

            # 1) If heuristic numeric and safe -> submit
            if heuristic is not None and submission_url:
                if is_bad_answer(heuristic) or looks_like_secret(str(heuristic)):
                    log("HEURISTIC_REJECTED")
                else:
                    payload = {"email": email, "secret": secret, "url": current_url, "answer": heuristic}
                    try:
                        res = safe_post_json(submission_url, payload, timeout=8)
                        log("HEURISTIC_SUBMITTED")
                        # follow chain if url provided
                        if isinstance(res, dict) and res.get("url"):
                            current_url = res.get("url")
                            continue
                        else:
                            break
                    except Exception as e:
                        log(f"HEURISTIC_SUBMIT_FAIL {redact(str(e))}")
                        # fallthrough to LLM/file/audio handling

            # 2) file links (pdf/csv) — quick attempt
            file_link = None
            for l in links or []:
                if l and any(l.lower().endswith(ext) for ext in (".pdf", ".csv", ".xlsx", ".xls")):
                    file_link = l; break

            if file_link:
                try:
                    safe_fetch_url_check(file_link)
                    r = requests.get(file_link, timeout=12)
                    if r.status_code == 200 and file_link.lower().endswith(".pdf") and PdfReader:
                        reader = PdfReader(io.BytesIO(r.content))
                        text = ""
                        for pg in reader.pages:
                            try:
                                text += pg.extract_text() or ""
                            except Exception:
                                pass
                        val = extract_from_visible_numbers(text)
                        if val is not None and submission_url:
                            if not (is_bad_answer(val) or looks_like_secret(str(val))):
                                payload = {"email": email, "secret": secret, "url": current_url, "answer": val}
                                try:
                                    res = safe_post_json(submission_url, payload, timeout=10)
                                    log("PDF_SUBMITTED")
                                    if isinstance(res, dict) and res.get("url"):
                                        current_url = res.get("url")
                                        continue
                                    else:
                                        break
                                except Exception as e:
                                    log(f"PDF_SUBMIT_FAIL {redact(str(e))}")
                    # if pdf not processed -> fallthrough
                except Exception as e:
                    log(f"FILE_FETCH_BLOCKED {redact(str(e))}")

            # 3) audio handling: find audio src or links to typical audio files
            audio_url = None
            # try audio tags via page evaluation (safer to detect via links already)
            for l in links or []:
                if l and any(l.lower().endswith(ext) for ext in (".mp3", ".wav", ".m4a", ".ogg")):
                    audio_url = l; break

            if audio_url:
                try:
                    safe_fetch_url_check(audio_url)
                    ar = requests.get(audio_url, timeout=20)
                    if ar.status_code == 200:
                        transcript = transcribe_audio_bytes(ar.content, filename=os.path.basename(audio_url))
                        if transcript:
                            # try to extract number answer or short string
                            val = extract_from_visible_numbers(transcript) or transcript.strip()[:1000]
                            if not (is_bad_answer(val) or looks_like_secret(str(val))):
                                if submission_url:
                                    payload = {"email": email, "secret": secret, "url": current_url, "answer": val}
                                    try:
                                        res = safe_post_json(submission_url, payload, timeout=12)
                                        log("AUDIO_SUBMITTED")
                                        if isinstance(res, dict) and res.get("url"):
                                            current_url = res.get("url")
                                            continue
                                        else:
                                            break
                                    except Exception as e:
                                        log(f"AUDIO_SUBMIT_FAIL {redact(str(e))}")
                    # else fallthrough
                except Exception as e:
                    log(f"AUDIO_FETCH_BLOCKED {redact(str(e))}")

            # 4) LLM fallback is expensive — minimal logs and only if AIPIPE/OPENAI creds are present
            # Build a compact prompt (visible_text + links) and call external LLM via AIPipe/OpenAI using server-side tools
            # For minimal setup we avoid building heavy LLM wrapper here (use AIPipe via REST if available)
            # If no transcription client available, we stop to avoid hallucination.
            if not (AIPIPE_TOKEN or OPENAI_API_KEY):
                log("NO_TRANSCRIPTION_CLIENT_SKIP_LLM")
                break

            # Build a short prompt
            prompt_text = {
                "visible_text": visible_text[:8000],
                "links": (links or [])[:40],
                "instructions": "Return JSON: {\"answer\": <number|string|null>, \"submission_url\": \"<url_or_null>\"}. If unsure return answer:null"
            }

            # Call AIPipe/OpenAI Chat API (minimal wrapper using requests to OpenRouter if AIPIPE_TOKEN present)
            answer = None
            submission_url = None
            try:
                if AIPIPE_TOKEN:
                    url = "https://aipipe.org/openrouter/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {AIPIPE_TOKEN}", "Content-Type": "application/json"}
                    payload = {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "You are a data analyst. Output ONLY compact JSON."},
                            {"role": "user", "content": json.dumps(prompt_text)}
                        ],
                        "max_tokens": 600,
                        "temperature": 0.0
                    }
                    r = requests.post(url, headers=headers, json=payload, timeout=25)
                    if r.status_code == 200:
                        resp = r.json()
                        # try extracting text
                        raw = ""
                        try:
                            raw = resp["choices"][0]["message"]["content"]
                        except Exception:
                            raw = r.text
                        # parse JSON from raw
                        jm = re.search(r'(\{.*\})', raw, flags=re.S)
                        if jm:
                            data = json.loads(jm.group(1))
                            answer = data.get("answer")
                            submission_url = data.get("submission_url")
                elif OPENAI_API_KEY:
                    # fallback to OpenAI chat completions REST (simple)
                    url = "https://api.openai.com/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
                    payload = {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "You are a data analyst. Output ONLY compact JSON."},
                            {"role": "user", "content": json.dumps(prompt_text)}
                        ],
                        "max_tokens": 600,
                        "temperature": 0.0
                    }
                    r = requests.post(url, headers=headers, json=payload, timeout=25)
                    if r.status_code == 200:
                        resp = r.json()
                        raw = ""
                        try:
                            raw = resp["choices"][0]["message"]["content"]
                        except Exception:
                            raw = r.text
                        jm = re.search(r'(\{.*\})', raw, flags=re.S)
                        if jm:
                            data = json.loads(jm.group(1))
                            answer = data.get("answer")
                            submission_url = data.get("submission_url")
            except Exception as e:
                log(f"LLM_CALL_FAIL {redact(str(e))}")

            # normalize submission_url
            if isinstance(submission_url, str) and submission_url:
                try:
                    submission_url = urljoin(current_url, submission_url)
                except Exception:
                    pass

            if is_bad_answer(answer) or looks_like_secret(str(answer) if answer is not None else "") or not submission_url:
                log("LLM_ANSWER_REJECTED_OR_MISSING_SUBMIT")
                break

            # final submit
            try:
                payload = {"email": email, "secret": secret, "url": current_url, "answer": answer}
                res = safe_post_json(submission_url, payload, timeout=12)
                log("LLM_SUBMITTED")
                if isinstance(res, dict) and res.get("url"):
                    current_url = res.get("url")
                    continue
                else:
                    break
            except Exception as e:
                log(f"FINAL_SUBMIT_FAIL {redact(str(e))}")
                break

        try:
            await context.close()
            await browser.close()
        except Exception:
            pass

    log(f"END elapsed={round(time.time()-overall_start,2)}")
    return

# ---------- Endpoint ----------
@app.post("/quiz")
async def receive_task(task: QuizTask):
    if not MY_SECRET:
        raise HTTPException(status_code=503, detail="Server not configured with MY_SECRET")
    if task.secret != MY_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    try:
        await process_quiz_loop(task.url, task.email, task.secret, total_budget_seconds=DEFAULT_BUDGET_SECONDS)
    except Exception as e:
        # minimal error returned to caller
        raise HTTPException(status_code=500, detail="processing_failed")
    return {"message": "Processed"}

@app.get("/")
def health():
    return {"status": "ok", "service": "llm-analysis", "version": "1.0"}
