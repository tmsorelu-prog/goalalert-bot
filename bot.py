# -*- coding: utf-8 -*-
"""
GoalAlert Railway Telegram Bot
- Paste a 365Scores match link to the bot
- It monitors and alerts:
  ⚽ GOAL  |  ⚠️ POSSIBLE GOAL in the next minutes
Environment:
  BOT_TOKEN  -> Telegram bot token from @BotFather
Optional env:
  PROFILE=agresiv|echilibrat|conservator (default echilibrat)
  MIN_POLL_SEC, MAX_POLL_SEC, WINDOW_MIN, COOLDOWN_MIN
"""
import os, re, time, random, asyncio, contextlib
from datetime import datetime
from collections import deque, defaultdict

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions

# ---- Config ----
MIN_POLL_SEC = int(os.getenv("MIN_POLL_SEC", "8"))
MAX_POLL_SEC = int(os.getenv("MAX_POLL_SEC", "14"))
WINDOW_MIN   = int(os.getenv("WINDOW_MIN", "5"))
COOLDOWN_MIN = int(os.getenv("COOLDOWN_MIN", "8"))
DEFAULT_PROFILE = os.getenv("PROFILE", "echilibrat")
HEADLESS = True

PROFILES = {"agresiv":{"TH":0.85},"echilibrat":{"TH":1.00},"conservator":{"TH":1.25}}

UA_LIST = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

SESSIONS = {}
PROFILES_PER_CHAT = defaultdict(lambda: DEFAULT_PROFILE)

def now(): return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

# ---- Browser (Chromium installed by Dockerfile) ----
def boot_browser():
    ua = random.choice(UA_LIST)
    opts = ChromeOptions()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--log-level=3")
    opts.add_argument(f"--user-agent={ua}")
    # Railway image installs chromium and chromium-driver
    for path in ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]:
        if os.path.exists(path):
            opts.binary_location = path
            break
    drv = webdriver.Chrome(options=opts)
    try: drv.set_window_size(1200, 800)
    except: pass
    return drv

# ---- Parsing helpers ----
_re_min = re.compile(r"(\d{1,2})\s*['′’]")
_re_score = re.compile(r"\b(\d+)\s*[-:]\s*(\d+)\b")

def parse_minute(text):
    if not text: return None
    t = text.replace("’","'").replace("′","'")
    m = _re_min.search(t)
    if m:
        try:
            v = int(m.group(1))
            if 0 <= v <= 130: return v
        except: pass
    if "PAUZ" in t.upper() or "HALF" in t.upper(): return 46
    return None

def _safe(el):
    try: return el.get_attribute("textContent").strip()
    except: 
        try: return el.text.strip()
        except: return ""

def read_score(drv):
    try:
        for e in drv.find_elements(By.XPATH, "//div[contains(@class,'score') or contains(@class,'Score') or contains(@class,'scores')]"):
            m = _re_score.search(_safe(e) or "")
            if m: return (int(m.group(1)), int(m.group(2)))
    except: pass
    try:
        body = _safe(drv.find_element(By.TAG_NAME, "body"))
        m = _re_score.search(body or "")
        if m: return (int(m.group(1)), int(m.group(2)))
    except: pass
    return None

def read_minute(drv):
    try:
        for e in drv.find_elements(By.XPATH, "//*[contains(text(),\"'\") or contains(text(),'Half') or contains(text(),'Pauz')]"):
            mi = parse_minute(_safe(e))
            if mi is not None: return mi
    except: pass
    try:
        return parse_minute(_safe(drv.find_element(By.TAG_NAME, "body")))
    except: return None

def read_stats(drv):
    stats = {"shots":0,"on_target":0,"dangerous":0,"corners":0}
    try:
        body = drv.find_element(By.TAG_NAME, "body")
        for e in body.find_elements(By.XPATH, ".//*"):
            t = (_safe(e) or "").lower()
            if not t: continue
            if any(k in t for k in ("shots on target","on target","pe poartă","șuturi pe poartă")):
                nums = re.findall(r"\b(\d+)\b", t); 
                if nums: stats["on_target"] = max(stats["on_target"], int(nums[-1]))
            if any(k in t for k in ("shots","total shots","șuturi")):
                nums = re.findall(r"\b(\d+)\b", t); 
                if nums: stats["shots"] = max(stats["shots"], int(nums[-1]))
            if any(k in t for k in ("big chance","dangerous attack","atacuri periculoase","ocaz")):
                nums = re.findall(r"\b(\d+)\b", t); 
                if nums: stats["dangerous"] = max(stats["dangerous"], int(nums[-1]))
            if "corner" in t or "cornere" in t:
                nums = re.findall(r"\b(\d+)\b", t); 
                if nums: stats["corners"] = max(stats["corners"], int(nums[-1]))
    except: pass
    return stats

def read_feed_events(drv):
    raw = []
    try:
        for e in drv.find_elements(By.XPATH, "//div[contains(@class,'comment') or contains(@class,'feed') or contains(@class,'row')]")[-60:]:
            txt = (_safe(e) or "").lower()
            if txt: raw.append(txt)
    except: pass
    counts = defaultdict(int)
    keys = {"shot on target":"sot","shots on target":"sot","big chance":"big","dangerous attack":"da","corner":"cor","penalty":"pen","goal":"goal","gol":"goal"}
    for t in raw:
        for k, tag in keys.items():
            if k in t: counts[tag] += 1
    return dict(counts)

def pressure_score(now_stats, prev_stats, dt_min):
    dt = max(dt_min, 1e-6)
    def inc(k): return max(0.0, (now_stats.get(k,0)-prev_stats.get(k,0))/dt)
    return 0.7*inc("on_target") + 0.3*inc("dangerous") + 0.2*inc("corners")

# ---- Monitor loop ----
async def monitor(app, chat_id, link):
    profile = PROFILES_PER_CHAT[chat_id]
    TH = PROFILES.get(profile, PROFILES["echilibrat"])["TH"]
    await app.bot.send_message(chat_id, f"▶️ Monitor pornit.\nProfil: {profile} (prag {TH:.2f})")

    drv = boot_browser()
    with contextlib.suppress(Exception):
        drv.get(link)

    start = time.time(); ok=False
    while time.time() - start < 30:
        try:
            drv.find_element(By.TAG_NAME, "body"); ok=True; break
        except: await asyncio.sleep(1.0)
    if not ok:
        await app.bot.send_message(chat_id, "❌ Nu pot încărca pagina. Verifică linkul.")
        with contextlib.suppress(Exception): drv.quit()
        return

    prev_stats = {"shots":0,"on_target":0,"dangerous":0,"corners":0}
    last_score = None; last_goal_score = None
    last_possible_alert = 0.0
    hist = deque(maxlen=300); last_poll=time.time()

    while True:
        if chat_id not in SESSIONS or SESSIONS[chat_id].get("stop", False):
            break
        try:
            await asyncio.sleep(random.uniform(MIN_POLL_SEC, MAX_POLL_SEC))
            minute = read_minute(drv); score = read_score(drv)
            stats = read_stats(drv); feed = read_feed_events(drv)
            combined = stats.copy()
            if feed.get("sot"): combined["on_target"] = max(combined["on_target"], feed["sot"])
            if feed.get("da"):  combined["dangerous"] = max(combined["dangerous"], feed["da"])
            if feed.get("cor"): combined["corners"]   = max(combined["corners"],   feed["cor"])

            now_t = time.time(); dt_min = max((now_t-last_poll)/60.0, 1e-6); last_poll=now_t
            p = pressure_score(combined, prev_stats, dt_min); hist.append((now_t,p))

            m_out = minute if minute is not None else "?"
            sc_out = f"{score[0]}-{score[1]}" if score else "?-?"

            if score and last_score and score != last_score and score != last_goal_score:
                await app.bot.send_message(chat_id, f"⚽ GOOOL!\nScor: {score[0]} - {score[1]}\nMinut: {m_out}")
                last_goal_score = score
            last_score = score

            t_now = time.time()
            recent = [v for (ts, v) in hist if t_now - ts <= WINDOW_MIN*60]
            if recent:
                avg_p = sum(recent)/len(recent)
                if (t_now - last_possible_alert) >= COOLDOWN_MIN*60 and avg_p >= TH:
                    await app.bot.send_message(chat_id, f"⚠️ POSIBIL GOL ÎN URMĂTOARELE MINUTE\nMinut: {m_out}\nPresiune medie: {avg_p:.2f} (prag {TH:.2f})\nScor: {sc_out}")
                    last_possible_alert = t_now

            prev_stats = combined
        except Exception as e:
            await app.bot.send_message(chat_id, f"[WARN] {e!r}")
            await asyncio.sleep(3)
    with contextlib.suppress(Exception): drv.quit()
    await app.bot.send_message(chat_id, "⏹ Monitor oprit.")

# ---- Bot commands ----
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Salut! Trimite-mi linkul 365Scores sau folosește /link <URL>.\n"
        "Comenzi: /profile <agresiv|echilibrat|conservator>, /status, /stop"
    )

async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(f"Profil curent: {PROFILES_PER_CHAT[chat_id]}")
        return
    p = (context.args[0] or "").lower()
    if p not in PROFILES:
        await update.message.reply_text("Alege: agresiv | echilibrat | conservator")
        return
    PROFILES_PER_CHAT[chat_id] = p
    await update.message.reply_text(f"Setat profil: {p} (prag {PROFILES[p]['TH']:.2f})")

async def start_monitor(app, chat_id, link):
    if chat_id in SESSIONS and "task" in SESSIONS[chat_id]:
        SESSIONS[chat_id]["stop"] = True
        await SESSIONS[chat_id]["task"]
    SESSIONS[chat_id] = {"stop": False}
    task = asyncio.create_task(monitor(app, chat_id, link))
    SESSIONS[chat_id]["task"] = task

async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Folosește: /link <URL 365Scores>")
        return
    link = context.args[0].strip()
    await update.message.reply_text("✅ Link primit. Pornesc monitorizarea…")
    await start_monitor(context.application, chat_id, link)

async def any_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.startswith("http"):
        return await cmd_link(update, context)
    await update.message.reply_text("Trimite linkul 365Scores sau /link <URL>.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in SESSIONS:
        await update.message.reply_text("Nu monitorizez nimic. Trimite linkul.")
        return
    await update.message.reply_text("Monitorizare activă.")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in SESSIONS or "task" not in SESSIONS[chat_id]:
        await update.message.reply_text("Nu există un meci în monitorizare.")
        return
    SESSIONS[chat_id]["stop"] = True
    await update.message.reply_text("Opreșc monitorizarea…")

def main():
    token = os.environ.get("BOT_TOKEN","").strip()
    if not token:
        raise SystemExit("Set BOT_TOKEN env var.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_text))
    app.run_polling()

if __name__ == "__main__":
    main()
