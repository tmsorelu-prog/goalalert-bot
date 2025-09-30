GoalAlert Telegram Bot – Railway
=================================

Ce face:
- Îi trimiți linkul 365Scores în Telegram (/link <URL> sau direct lipit).
- Botul monitorizează și îți trimite alerte: ⚽ GOAL, ⚠️ POSIBIL GOL.

Deploy pe Railway (Docker)
--------------------------
1) Creează un repo cu fișierele: Dockerfile, requirements.txt, bot.py.
2) Pe https://railway.app → New Project → Deploy from GitHub → alege repo-ul.
3) La Variables adaugă: BOT_TOKEN = token-ul botului tău (de la @BotFather).
4) Deploy. Serviciul va porni containerul și botul va fi online.

Comenzi în bot
--------------
/start – ajutor
/link <URL> – începe monitorizarea linkului 365Scores
/profile <agresiv|echilibrat|conservator> – setează pragul de alertă
/status – vezi statusul
/stop – oprește monitorul

Opțional (env vars)
-------------------
PROFILE=agresiv|echilibrat|conservator (default: echilibrat)
MIN_POLL_SEC, MAX_POLL_SEC (ex: 10 și 18 pentru a fi mai „uman”)
WINDOW_MIN (implicit 5), COOLDOWN_MIN (implicit 8)

Notă anti-blocare:
------------------
- Folosește interval random 8–14s și user-agent de browser.
- Dacă site-ul limitează scrapingul, crește intervalele sau folosește alt IP.

