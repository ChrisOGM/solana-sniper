# ============================================================
# twitter.py — KOL TWITTER MONITOR
# Priority accounts (Elon, CZ) checked every 10 seconds
# across ALL Nitter instances simultaneously
# Regular accounts checked every 30 seconds
# This is what catches the Elon/CZ pumps before anyone else
# ============================================================

import requests
import random
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime
from config import (
    WATCHED_INFLUENCERS,
    PRIORITY_INFLUENCERS,
    NITTER_INSTANCES
)
from database import log_kol_post

# Track last seen post per influencer — prevents duplicate alerts
last_seen_posts = {}

# Track last check time per influencer
last_check_time = {}

# Priority accounts poll every 10 seconds
PRIORITY_INTERVAL = 10
# Regular accounts poll every 30 seconds
REGULAR_INTERVAL  = 30


# ============================================================
# MAIN LOOP — two-speed polling
# ============================================================

async def monitor_influencers():
    print("[TWITTER] Starting KOL monitor...")
    print(f"[TWITTER] Priority accounts ({PRIORITY_INTERVAL}s): {PRIORITY_INFLUENCERS}")
    print(f"[TWITTER] Regular accounts ({REGULAR_INTERVAL}s): "
          f"{[a for a in WATCHED_INFLUENCERS if a not in PRIORITY_INFLUENCERS]}")

    while True:
        now = datetime.utcnow().timestamp()

        for username in WATCHED_INFLUENCERS:
            # Determine interval for this account
            interval = (PRIORITY_INTERVAL
                       if username in PRIORITY_INFLUENCERS
                       else REGULAR_INTERVAL)

            last = last_check_time.get(username, 0)
            if now - last < interval:
                continue  # Not time yet

            last_check_time[username] = now

            try:
                if username in PRIORITY_INFLUENCERS:
                    # Priority — check ALL instances simultaneously
                    # First one to return a new post wins
                    await check_priority_account(username)
                else:
                    # Regular — check one random instance
                    await check_influencer(username)
            except Exception as e:
                print(f"[TWITTER] Error @{username}: {e}")

        # Sleep 1 second between cycles
        # This allows 10-second priority checks without blocking
        await asyncio.sleep(1)


# ============================================================
# PRIORITY ACCOUNT — checks ALL instances simultaneously
# Catches posts faster than single-instance polling
# ============================================================

async def check_priority_account(username):
    """
    For Elon, CZ and other priority accounts —
    checks all Nitter instances in parallel.
    The fastest one to return a new post wins.
    """
    tasks = [
        asyncio.create_task(fetch_latest_post(username, instance))
        for instance in NITTER_INSTANCES
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Find first valid new post across all instances
    for result in results:
        if isinstance(result, Exception) or not result:
            continue
        tweet_text, tweet_id = result
        if not tweet_text or not tweet_id:
            continue

        # Check if this is a new post
        if last_seen_posts.get(username) == tweet_id:
            continue  # Already seen

        # New post found — process it
        last_seen_posts[username] = tweet_id
        print(f"[TWITTER] 🚨 PRIORITY: New post @{username}: {tweet_text[:80]}...")
        await process_new_post(username, tweet_text, tweet_id)
        return  # Stop after first new post found


# ============================================================
# REGULAR ACCOUNT — checks one Nitter instance
# ============================================================

async def check_influencer(username):
    """Checks a single random Nitter instance for new posts"""
    for attempt in range(3):
        instance = random.choice(NITTER_INSTANCES)
        try:
            result = await fetch_latest_post(username, instance)
            if not result:
                continue

            tweet_text, tweet_id = result
            if not tweet_text or not tweet_id:
                continue

            if last_seen_posts.get(username) == tweet_id:
                return  # No new post

            # New post
            last_seen_posts[username] = tweet_id
            print(f"[TWITTER] New post @{username}: {tweet_text[:80]}...")
            await process_new_post(username, tweet_text, tweet_id)
            return

        except Exception as e:
            print(f"[TWITTER] @{username} attempt {attempt+1} failed: {e}")
            await asyncio.sleep(1)


# ============================================================
# FETCH LATEST POST FROM ONE NITTER INSTANCE
# ============================================================

async def fetch_latest_post(username, instance):
    """
    Returns (tweet_text, tweet_id) or None if failed/no post.
    Runs in thread pool to avoid blocking the event loop.
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _fetch_sync(username, instance)
        )
        return result
    except Exception:
        return None


def _fetch_sync(username, instance):
    """Synchronous Nitter fetch — runs in thread pool"""
    try:
        url      = f"{instance}/{username}"
        headers  = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, timeout=6, headers=headers)

        if response.status_code != 200:
            return None

        soup   = BeautifulSoup(response.text, "html.parser")
        tweets = soup.find_all("div", class_="tweet-content")

        if not tweets:
            return None

        tweet_text = tweets[0].get_text(strip=True)
        tweet_id   = _extract_tweet_id(soup)

        return tweet_text, tweet_id

    except Exception:
        return None


def _extract_tweet_id(soup):
    """Extracts tweet ID from Nitter page to detect new posts"""
    try:
        # Try tweet link first (most reliable)
        link = soup.find("a", class_="tweet-link")
        if link:
            href = link.get("href", "")
            if href:
                return href

        # Try tweet permalink
        perm = soup.find("a", class_="tweet-date")
        if perm:
            href = perm.get("href", "")
            if href:
                return href

        # Fallback — use current minute as pseudo-ID
        return f"fb_{datetime.utcnow().strftime('%Y%m%d%H%M')}"
    except Exception:
        return f"fb_{datetime.utcnow().strftime('%Y%m%d%H%M')}"


# ============================================================
# PROCESS NEW POST
# ============================================================

async def process_new_post(username, tweet_text, tweet_id):
    """
    Handles a newly detected post from any KOL.
    Extracts keywords, saves to DB, sends alert,
    opens watch window on Solana chain.
    """
    keywords = extract_keywords(tweet_text)

    if not keywords:
        print(f"[TWITTER] @{username} — no meaningful keywords, skipping")
        return

    # Save to database
    try:
        log_kol_post(
            influencer=username,
            post_text=tweet_text,
            post_url=f"https://twitter.com/{username}",
            keywords=keywords
        )
    except Exception as e:
        print(f"[TWITTER] DB log error: {e}")

    # Send Telegram alert
    try:
        from telegram_bot import alert_kol_post
        await alert_kol_post(username, tweet_text, keywords)
    except Exception as e:
        print(f"[TWITTER] Alert error: {e}")

    print(f"[TWITTER] ✅ Processed @{username} | Keywords: {keywords}")


# ============================================================
# KEYWORD EXTRACTOR
# ============================================================

IGNORE_WORDS = {
    "the", "a", "an", "is", "in", "on", "at", "to", "for",
    "of", "and", "or", "but", "with", "this", "that", "it",
    "we", "i", "you", "my", "our", "are", "was", "be", "will",
    "have", "has", "been", "just", "so", "very", "now", "new",
    "from", "by", "as", "up", "out", "about", "more", "when",
    "can", "get", "all", "do", "not", "time", "great", "good",
    "let", "its", "im", "rt", "via", "today", "here", "there",
    "they", "them", "their", "would", "could", "should", "also",
    "https", "http", "com", "www", "twitter", "pic", "goo",
    "make", "want", "think", "know", "see", "look", "say",
    "need", "use", "way", "day", "back", "just", "like", "got"
}

def extract_keywords(text):
    """
    Extracts meaningful keywords from tweet text.
    Prioritises ticker symbols ($GHIBLI, $CHIBIS etc).
    Filters common words.
    Returns max 10 unique keywords.
    """
    words    = text.split()
    keywords = []
    seen     = set()

    for word in words:
        # Always capture ticker symbols like $GHIBLI $CHIBIS
        if word.startswith("$") and len(word) > 1:
            clean = word[1:].strip(".,!?:;\"'").upper()
            if clean and len(clean) > 1 and clean not in seen:
                seen.add(clean)
                keywords.insert(0, clean.lower())  # Tickers go first
            continue

        # Clean punctuation
        clean = ''.join(c for c in word if c.isalnum()).lower()

        # Keep meaningful words
        if (len(clean) > 2 and
                clean not in IGNORE_WORDS and
                clean not in seen and
                not clean.isdigit()):
            seen.add(clean)
            keywords.append(clean)

        if len(keywords) >= 10:
            break

    return keywords
