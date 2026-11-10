# DeepSeek-bridge til SecretAI. Startes automatisk af secretai.py (kræver Google Chrome eller Edge).
# Manuelt:  python -m uvicorn ds_server:app --host 127.0.0.1 --port 8000
# API: POST /ask · POST /ask/stream · GET /status · GET /health · POST /admin/mode · POST /admin/quit
import asyncio, json, os, shutil, subprocess, sys, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

URL        = "https://chat.deepseek.com"
INPUT_SEL  = os.getenv("DS_INPUT",  'textarea[placeholder="Message DeepSeek"]')   # kan ændre sig
SEND_SEL   = os.getenv("DS_SEND",   ".ds-button--primary.ds-button--filled.ds-button--circle")
ANSWER_SEL = os.getenv("DS_ANSWER", ".ds-assistant-message-main-content")   # kun selve svaret, ikke tænkeblokken
GEN_SEL    = os.getenv("DS_GEN",    '.ds-button--circle:has(path[d^="M2 4.88"])')  # stop-knap = svarer stadig
DONE_SEL   = os.getenv("DS_DONE",   ".ds-message + .ds-flex [role=button]")        # kopiér-linjen = svar færdigt
# DeepThink / Search: "keep" (lad stå som er), "on" eller "off". "off" giver hurtigere svar.
DEEPTHINK  = os.getenv("DS_DEEPTHINK", "keep")
SEARCH     = os.getenv("DS_SEARCH", "keep")
STABLE_SEC = float(os.getenv("DS_STABLE", "4"))   # uændret tekst i så lang tid = færdig
MAX_WAIT   = int(os.getenv("DS_MAX_WAIT", "180")) # hård grænse pr. svar (sek.)
QUEUE_WAIT = int(os.getenv("DS_QUEUE_WAIT", "300"))  # max ventetid på at komme til
DEBUG_DIR  = "./ds-debug"

state, lock = {}, asyncio.Lock()


async def snap(page, name):
    """Gem screenshot ved fejl, så du kan se hvad der gik galt."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        await page.screenshot(path=f"{DEBUG_DIR}/{name}-{int(time.time())}.png")
    except Exception:
        pass


PORT        = int(os.getenv("DS_PORT", "9222"))
PROFILE     = os.path.abspath("./ds-chrome")                 # Chrome-profil med dit login
RUN_VISIBLE = os.getenv("DS_RUN_VISIBLE", "0") == "1"        # 1 = kør med synligt vindue i stedet for usynligt


def find_chrome() -> str:
    """Find Google Chrome (eller Edge som reserve) på Windows / Mac / Linux."""
    if os.getenv("DS_CHROME"):
        return os.environ["DS_CHROME"]
    cands = []
    if sys.platform.startswith("win"):
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                cands += [rf"{base}\Google\Chrome\Application\chrome.exe",
                          rf"{base}\Microsoft\Edge\Application\msedge.exe"]
    elif sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    else:
        cands = [shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise RuntimeError("Fandt ikke Google Chrome. Installér Chrome, eller sæt DS_CHROME til stien.")


def alive() -> bool:
    p = state.get("proc")
    return bool(p) and p.poll() is None


async def stop_chrome():
    """Luk Chrome pænt (så login-cookies bliver gemt) og drop forbindelsen."""
    browser, proc = state.pop("browser", None), state.get("proc")
    if browser is None and alive():            # login-tilstand: forbind kortvarigt kun for at lukke pænt
        try:
            browser = await state["pw"].chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        except Exception:
            browser = None
    if browser is not None:
        try:
            cdp = await browser.new_browser_cdp_session()
            await cdp.send("Browser.close")
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass
    if proc:
        for _ in range(50):
            if proc.poll() is not None:
                break
            await asyncio.sleep(0.2)
        else:
            proc.terminate()
    state.update(proc=None, page=None, ctx=None)


async def launch(mode: str):
    """mode='login': normal Chrome UDEN automation (ingen verify-problemer).
    mode='run': Chrome (usynlig) som scriptet styrer via port 9222."""
    await stop_chrome()
    args = [find_chrome(), f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
            "--no-first-run", "--no-default-browser-check"]
    if mode == "run" and not RUN_VISIBLE:
        args.append("--headless=new")
    args.append(URL)
    state.update(proc=subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                 mode=mode, error=None)
    if mode != "run":
        return
    browser = None
    for _ in range(40):                        # vent op til 20 sek. på at Chrome er klar
        try:
            browser = await state["pw"].chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
            break
        except Exception:
            await asyncio.sleep(0.5)
    if browser is None:
        raise RuntimeError("Kunne ikke forbinde til Chrome (port optaget? sæt DS_PORT).")
    ctx = browser.contexts[0]
    page = next((p for p in ctx.pages if "deepseek" in p.url), None) or (
        ctx.pages[0] if ctx.pages else await ctx.new_page())
    state.update(browser=browser, ctx=ctx, page=page)


@asynccontextmanager
async def lifespan(app):
    state["pw"] = await async_playwright().start()
    state["mode"] = "starting"

    async def boot():                          # første gang (ingen profil endnu) → login-tilstand
        try:
            await launch("run" if os.path.isdir(PROFILE) else "login")
        except Exception as e:
            state["error"] = str(e)
    state["boot"] = asyncio.create_task(boot())   # serveren svarer med det samme, Chrome starter i baggrunden
    yield
    await state["boot"]
    await stop_chrome()
    await state["pw"].stop()


app = FastAPI(lifespan=lifespan)


async def get_page():
    """Returnér en levende fane – opret ny hvis den er lukket/crashet."""
    await state["boot"]                        # vent hvis Chrome stadig er ved at starte
    page = state.get("page")
    if page is None:
        raise HTTPException(409, "Browseren er i login-tilstand. Tryk «Jeg er logget ind» i SecretAI-vinduet.")
    if page.is_closed():
        page = await state["ctx"].new_page()
        state["page"] = page
    return page


async def set_toggle(page, name: str, want: str):
    """Sæt DeepThink/Search til 'on'/'off'; 'keep' rører dem ikke."""
    if want not in ("on", "off"):
        return
    btn = page.locator(".ds-toggle-button", has_text=name).first
    try:
        is_on = "ds-toggle-button--selected" in (await btn.get_attribute("class", timeout=3000) or "")
        if is_on != (want == "on"):
            await btn.click()
    except Exception:
        pass


async def ask_iter(q: str):
    """Async generator: yder hele svarteksten hver gang den vokser. Slutter når svaret er stabilt."""
    page = await get_page()
    await page.goto(URL, wait_until="domcontentloaded")

    # Login-tjek: findes tekstfeltet ikke, er du logget ud / der er captcha
    box = page.locator(INPUT_SEL)
    try:
        await box.wait_for(state="visible", timeout=20_000)
    except PWTimeout:
        await snap(page, "no-input")
        raise HTTPException(401, "Tekstfelt ikke fundet – logget ud, captcha eller ændret selector. "
                                 "Tryk «Åbn login-vindue» i SecretAI-vinduet.")

    await set_toggle(page, "DeepThink", DEEPTHINK)
    await set_toggle(page, "Search", SEARCH)

    answers = page.locator(ANSWER_SEL)
    gen, done = page.locator(GEN_SEL), page.locator(DONE_SEL)
    before = await answers.count()          # ny samtale hver gang → 0

    await box.fill(q)
    await box.press("Enter")
    await asyncio.sleep(1)
    try:                                    # hvis Enter ikke sendte: klik på send-knappen
        if await box.input_value() and await gen.count() == 0:
            await page.locator(SEND_SEL).last.click(timeout=3000)
    except Exception:
        pass

    # Vent på at et nyt svar-element dukker op
    deadline = time.monotonic() + MAX_WAIT
    while await answers.count() <= before:
        if time.monotonic() > deadline:
            await snap(page, "no-answer")
            raise HTTPException(504, "Intet svar startede inden for tidsgrænsen.")
        await asyncio.sleep(0.5)

    # Vent til teksten har stået uændret i STABLE_SEC sekunder
    prev, last_change = "", time.monotonic()
    while True:
        await asyncio.sleep(0.3)
        try:
            cur = await answers.last.inner_text()
        except Exception:
            continue                         # DOM re-renderes midt i svaret
        if cur != prev:
            prev, last_change = cur, time.monotonic()
            yield cur
        elif cur and time.monotonic() - last_change >= 1.0 and await gen.count() == 0 \
                and await done.count() > 0:
            return                           # stop-knap væk + kopiér-linje vist = færdig
        elif cur and time.monotonic() - last_change >= STABLE_SEC:
            return                           # reserve hvis selectors ændres
        if time.monotonic() > deadline:
            await snap(page, "timeout")
            raise HTTPException(504, "Timeout – svaret blev ikke færdigt.")


async def ask_once(q: str) -> str:
    last = ""
    async for last in ask_iter(q):
        pass
    return last


async def take_lock():
    """Ét spørgsmål ad gangen – men giv ikke op for evigt i køen."""
    try:
        await asyncio.wait_for(lock.acquire(), timeout=QUEUE_WAIT)
    except asyncio.TimeoutError:
        raise HTTPException(503, "Køen er for lang, prøv igen.")


def get_q(body: dict) -> str:
    q = (body.get("q") or "").strip()
    if not q:
        raise HTTPException(400, 'Send {"q": "dit spørgsmål"}')
    return q


def as_http(e: Exception) -> HTTPException:
    return e if isinstance(e, HTTPException) else HTTPException(500, f"{type(e).__name__}: {e}")


@app.post("/ask")
async def ask(body: dict):
    q = get_q(body)
    await take_lock()
    try:
        return {"answer": await ask_once(q)}
    except Exception as e:
        if not isinstance(e, HTTPException):
            await snap(state["page"], "error")
        raise as_http(e)
    finally:
        lock.release()


@app.post("/ask/stream")
async def ask_stream(body: dict):
    """Server-Sent Events: data: {"delta": "..."} løbende, til sidst data: [DONE]."""
    q = get_q(body)
    await take_lock()
    gen = ask_iter(q)
    try:                                      # hent første stykke FØR svaret startes,
        first = await gen.__anext__()         # så login-/timeout-fejl får rigtig HTTP-status
    except StopAsyncIteration:
        first = ""
    except Exception as e:
        lock.release()
        raise as_http(e)

    async def events():
        prev, cur = "", first
        try:
            while True:
                if cur.startswith(prev):
                    payload = {"delta": cur[len(prev):]}
                else:                         # siden omskrev teksten (fx markdown-rendering)
                    payload = {"replace": cur}
                prev = cur
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                try:
                    cur = await gen.__anext__()
                except StopAsyncIteration:
                    break
            yield "data: [DONE]\n\n"
        except Exception as e:
            err = as_http(e)
            yield f"event: error\ndata: {json.dumps({'error': err.detail}, ensure_ascii=False)}\n\n"
        finally:
            await gen.aclose()
            lock.release()

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"browser": alive(), "busy": lock.locked(), "mode": state.get("mode")}


# ---------------------------------------------------------------- Status / styring (bruges af SecretAI-vinduet)
@app.get("/status")
async def status():
    mode = state.get("mode")
    out = {"browser": alive(), "busy": lock.locked(), "mode": mode, "error": state.get("error"),
           "headless": mode == "run" and not RUN_VISIBLE, "login": "ukendt"}
    page = state.get("page")
    if mode == "run" and page is not None and not page.is_closed():
        if out["busy"]:
            out["login"] = "ja"
        else:
            try:                               # rør ikke siden mens et spørgsmål kører
                url = page.url
                if "chat.deepseek.com" in url:
                    if any(k in url for k in ("sign_in", "login")):
                        out["login"] = "nej"
                    elif await page.locator(INPUT_SEL).count() > 0:
                        out["login"] = "ja"
            except Exception:
                pass
    return out


@app.post("/admin/mode")
async def set_mode(body: dict):
    """headless=false → login-tilstand (normal Chrome). headless=true → kør (styret af scriptet)."""
    mode = "run" if body.get("headless") else "login"
    await state["boot"]
    await take_lock()
    try:
        await launch(mode)
    except Exception as e:
        state["error"] = str(e)
        raise HTTPException(500, str(e))
    finally:
        lock.release()
    return {"ok": True, "mode": mode}


@app.post("/admin/quit")
async def quit_server():
    """Luk Chrome pænt og afslut serveren (bruges af SecretAI ved Afslut). Kun lokalt: serveren lytter på 127.0.0.1."""
    async def _go():
        await asyncio.sleep(0.2)
        try:
            await stop_chrome()
        finally:
            os._exit(0)
    asyncio.create_task(_go())
    return {"ok": True}
