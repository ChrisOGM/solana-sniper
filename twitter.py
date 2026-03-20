# ============================================================
# twitter.py — KOL TWITTER MONITOR
# Watches influencers via Nitter — free, no API key needed
# ============================================================

import requests
import random
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime
from config import (
    WATCHED_INFLUENCERS,
    TWITTER_POLL_INTERVAL,
    NITTER_INSTANCES
)
from database import log_kol_post

# Track last seen post per influencer — prevents duplicate alerts
last_seen_posts = {}


# ============================================================
# MAIN LOOP — runs forever alongside other engines
# ============================================================

async def monitor_influencers():
    print("[TWITTER] Starting KOL monitor...")
    print(f"[TWITTER] Watching: {', '.join(['@'+i for i in WATCHED_INFLUENCERS])}")

    while True:
        for influencer in WATCHED_INFLUENCERS:
            try:
                await check_influencer(influencer)
            except Exception as e:
                print(f"[TWITTER] Error checking @{influencer}: {e}")
            # Small delay between each influencer check
            await asyncio.sleep(2)

        print(f"[TWITTER] Cycle complete — sleeping {TWITTER_POLL_INTERVAL}s")
        await asyncio.sleep(TWITTER_POLL_INTERVAL)


# ============================================================
# CHECK ONE INFLUENCER
# ============================================================

async def check_influencer(username):
    # Try up to 3 different Nitter instances
    for attempt in range(3):
        instance = random.choice(NITTER_INSTANCES)
        try:
            url      = f"{instance}/{username}"
            headers  = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, timeout=8, headers=headers)

            if response.status_code != 200:
                continue  # Try next instance

            soup   = BeautifulSoup(response.text, "html.parser")
            tweets = soup.find_all("div", class_="tweet-content")

            if not tweets:
                return  # No tweets found — not an error

            latest_text = tweets[0].get_text(strip=True)
            tweet_id    = get_tweet_id(soup)

            # Already seen this post — skip
            if last_seen_posts.get(username) == tweet_id:
                return

            # New post detected
            last_seen_posts[username] = tweet_id
            keywords = extract_keywords(latest_text)

            if not keywords:
                return

            print(f"[TWITTER] 🚨 New post @{username}: {latest_text[:80]}...")

            # Save to database
            log_kol_post(
                influencer=username,
                post_text=latest_text,
                post_url=f"https://twitter.com/{username}",
                keywords=keywords
            )

            # Send Telegram alert
            # Import here to avoid circular imports on startup
            from telegram_bot import alert_kol_post
            await alert_kol_post(username, latest_text, keywords)
            return  # Success — no need to try more instances

        except Exception as e:
            print(f"[TWITTER] @{username} attempt {attempt+1} failed: {e}")
            await asyncio.sleep(1)

    print(f"[TWITTER] @{username} — all instances failed, skipping this cycle")


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
    "they", "them", "their", "would", "could", "should", "also"
}

def extract_keywords(text):
    words    = text.lower().split()
    keywords = []

    for word in words:
        # Always capture ticker symbols like $BTC $SOL
        if word.startswith("$") and len(word) > 1:
            clean = word[1:].strip(".,!?")
            if clean:
                keywords.append(clean)
            continue

        # Clean punctuation
        clean = ''.join(c for c in word if c.isalnum())

        # Keep meaningful words only
        if len(clean) > 2 and clean not in IGNORE_WORDS:
            keywords.append(clean)

    # Deduplicate, max 10 keywords
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
        if len(unique) >= 10:
            break

    return unique


# ============================================================
# TWEET ID EXTRACTOR — detects new posts
# ============================================================

def get_tweet_id(soup):
    try:
        # Nitter tweet links contain the tweet ID
        link = soup.find("a", class_="tweet-link")
        if link:
            href = link.get("href", "")
            if href:
                return href
        # Fallback — use current minute as pseudo-ID
        return f"fallback_{datetime.utcnow().strftime('%Y%m%d%H%M')}"
    except Exception:
        return f"fallback_{datetime.utcnow().strftime('%Y%m%d%H%M')}"
