"""Downloading the raw match data.

- FotMob matchDetails JSON (xG, xGOT, colours, line-ups, momentum, stadium...)
- WhoScored matchCentreData (play-by-play events), with an anti-bot cascade:
  curl_cffi (real Chrome TLS) -> Playwright (challenge-aware) -> soccerdata -> FBref.
"""
import asyncio
import json
import os
import re

import requests

from .config import FOTMOB_URL, HEADERS, WHOSCORED_URL


def fetch_fotmob(match_id):
    """FotMob matchDetails JSON for `match_id` (raises on HTTP errors)."""
    response = requests.get(FOTMOB_URL.format(match_id), headers=HEADERS)
    response.raise_for_status()
    print("Success! Data retrieved.")
    return response.json()


# ------------------------------------------------------------------------------
# WhoScored
# ------------------------------------------------------------------------------
# Markers telling the REAL page apart from an Incapsula challenge
REAL_PAGE_MARKERS = ("require.config.params", "matchCentreData")
CHALLENGE_MARKERS = ("incapsula", "_incapsula", "request unsuccessful", "unusual traffic")


def looks_like_real_page(html: str) -> bool:
    return bool(html) and any(m in html for m in REAL_PAGE_MARKERS)


def looks_like_challenge(html: str) -> bool:
    low = (html or "").lower()
    return any(m in low for m in CHALLENGE_MARKERS)


# ------------------------------------------------------------------------------
# FALLBACK 1 — curl_cffi: a real Chrome TLS signature (+ optional proxy)
# ------------------------------------------------------------------------------
def fetch_with_curl_cffi(url, proxy=None):
    from curl_cffi import requests as cffi

    proxies = {"http": proxy, "https": proxy} if proxy else None
    session = cffi.Session(impersonate="chrome", headers=HEADERS)
    resp = session.get(url, timeout=25, proxies=proxies)
    resp.raise_for_status()

    if not looks_like_real_page(resp.text):
        raise RuntimeError(
            f"200 response but suspicious content ({len(resp.text)} chars) — probably an Incapsula challenge."
        )
    print(f"[curl_cffi] Success! {len(resp.text)} characters.")
    return resp.text


# ------------------------------------------------------------------------------
# FALLBACK 2 — Playwright async, conscient du challenge Incapsula (+ proxy optionnel)
# ------------------------------------------------------------------------------
async def _fetch_with_playwright_async(url, proxy=None, max_retries=4):
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
    except Exception:
        stealth = None

    launch_args = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
    launch_kwargs = {"headless": True, "args": launch_args}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1366, "height": 768},
            locale="fr-FR",
        )
        page = await context.new_page()
        if stealth is not None:
            try:
                await stealth.apply_stealth_async(page)
            except Exception:
                pass

        html = ""
        for attempt in range(1, max_retries + 1):
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(6000)  # let the challenge JS set its cookies
            html = await page.content()

            if looks_like_real_page(html):
                print(f"[playwright] Real page on attempt {attempt} ({len(html)} chars)")
                break

            print(f"[playwright] Essai {attempt}: challenge probable ({len(html)} car.), reload…")
            await page.wait_for_timeout(4000)
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            html = await page.content()
            if looks_like_real_page(html):
                print(f"[playwright] Real page after reload, attempt {attempt} ({len(html)} chars)")
                break

        await browser.close()

    if not looks_like_real_page(html):
        raise RuntimeError(
            f"Challenge not solved after {max_retries} attempts ({len(html)} chars) — "
            "datacenter IP block very likely."
        )
    return html


def fetch_with_playwright(url, proxy=None):
    return asyncio.get_event_loop().run_until_complete(
        _fetch_with_playwright_async(url, proxy=proxy)
    )


# ------------------------------------------------------------------------------
# Extraction du blob JS WhoScored (`matchCentreData`)
# ------------------------------------------------------------------------------
def parse_match_centre_data(html):
    if not html:
        return None
    m = re.search(r"require\.config\.params\['args'\]\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not m:
        m = re.search(r"matchCentreData\s*:\s*(\{.*?\}),\s*matchCentreEventTypeJson", html, re.DOTALL)
    if not m:
        print("[parse] Bloc matchCentreData introuvable.")
        return None
    raw = m.group(1)
    raw = re.sub(r"matchId:.*?,", "", raw)  # possible non-JSON keys
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("[parse] JSON non parsable directement — nettoyage manuel du blob requis.")
        return raw


# ------------------------------------------------------------------------------
# FALLBACK 3 — soccerdata WhoScored (needs a system Chrome + chromedriver)
# ------------------------------------------------------------------------------
def fetch_with_soccerdata(match_id, proxy=None, league="INT-World Cup", season="2026"):
    import soccerdata as sd

    ws = sd.WhoScored(leagues=league, seasons=season, proxy=proxy or None)
    print("[soccerdata] Available competitions:")
    print(ws.read_leagues())
    events = ws.read_events(match_id=match_id)
    print(f"[soccerdata] Success! {len(events)} events.")
    return events


# ------------------------------------------------------------------------------
# FALLBACK 4 — FBref via soccerdata: API-friendly source, little anti-bot
# (different data — aggregated stats rather than raw WhoScored events,
#  but it is what gets through most reliably from a datacenter IP)
# ------------------------------------------------------------------------------
def fetch_with_fbref(proxy=None, league="INT-World Cup", season="2026"):
    import soccerdata as sd

    fbref = sd.FBref(leagues=league, seasons=season, proxy=proxy or None)
    print("[fbref] Fetching schedule / stats…")
    schedule = fbref.read_schedule()
    print(f"[fbref] Success! {len(schedule)} matches in the schedule.")
    return schedule


# ==============================================================================
# MAIN CASCADE — only tries the next method if the previous one fails
# ==============================================================================
def fetch_whoscored(match_id, proxy=None):
    """WhoScored matchCentreData for `match_id`: curl_cffi -> Playwright -> soccerdata -> FBref."""
    url = WHOSCORED_URL.format(match_id)
    import nest_asyncio
    nest_asyncio.apply()  # asyncio inside an already-running loop (Colab / Jupyter)
    os.environ.setdefault("WEBDRIVER_CHROME_DRIVER", "/usr/bin/chromedriver")  # Chrome for soccerdata
    # 1) curl_cffi
    try:
        html = fetch_with_curl_cffi(url, proxy)
        data = parse_match_centre_data(html)
        if data:
            return data
    except Exception as e:
        print(f"[curl_cffi] Failed: {e}")

    # 2) Playwright challenge-aware
    try:
        html = fetch_with_playwright(url, proxy)
        data = parse_match_centre_data(html)
        if data:
            return data
    except Exception as e:
        print(f"[playwright] Failed: {e}")

    # 3) soccerdata WhoScored
    try:
        return fetch_with_soccerdata(match_id, proxy)
    except Exception as e:
        print(f"[soccerdata] Failed: {e}")

    # 4) FBref (fallback API-friendly)
    try:
        return fetch_with_fbref(proxy)
    except Exception as e:
        print(f"[fbref] Failed: {e}")

    print(
        "\nAll fallbacks failed.\n"
        "Diagnosis: Colab's datacenter IP is most likely blocked by Incapsula.\n"
        "Lasting fixes:\n"
        "  • Run it LOCALLY (residential IP) — curl_cffi alone is often enough.\n"
        "  • Pass a residential proxy (--proxy http://user:pass@host:port).\n"
        "  • Stick to FBref/FotMob, which are far less aggressive anti-bot-wise."
    )
    return None


