"""
Web scraping and announcement detection logic.
"""

from __future__ import annotations

import ssl
import requests
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from urllib3.util.retry import Retry
from typing import Any, Dict

from .models import Announcement, Config
from .utils import debug_print, format_dt, now
import urllib3

# Suppress SSL warnings for sites with weak DH keys
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def fetch_page(url: str) -> str:
    """
    Fetch target page and return HTML text.

    Uses:
    - Relaxed SSL context (for weak DH keys on older servers)
    - Automatic retries with exponential backoff for transient failures
      (DNS errors, timeouts, connection resets, 5xx responses)
    """
    # ------------------------------------------------------------------
    # Retry strategy (handles transient DNS / connection issues)
    # ------------------------------------------------------------------
    retry_strategy = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=2,  # 2s, 4s, 8s, 16s...
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )

    # ------------------------------------------------------------------
    # Relaxed SSL context (for weak SSL configs)
    # ------------------------------------------------------------------
    ssl_context = ssl.create_default_context()
    ssl_context.set_ciphers("DEFAULT:@SECLEVEL=1")
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    class CustomHTTPAdapter(HTTPAdapter):
        def __init__(self, *args, **kwargs):
            super().__init__(max_retries=retry_strategy, *args, **kwargs)

        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = ssl_context
            return super().init_poolmanager(*args, **kwargs)

    # ------------------------------------------------------------------
    # Session with retry + custom SSL
    # ------------------------------------------------------------------
    session = requests.Session()
    adapter = CustomHTTPAdapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    resp = session.get(url, timeout=30, verify=False)
    resp.raise_for_status()
    return resp.text


def extract_announcements(html: str) -> list[Dict[str, Any]]:
    """
    Extract candidate announcement blocks from the HTML.

    Primary strategy (college-specific):
    - Look for <a> elements with class "active" that are nested anywhere inside
      a <div> with class "owl-item".
    - Ignore any "owl-item" elements that also have class "cloned" to avoid
      duplicates created by carousel libraries.

    Fallback strategy:
    - If nothing is found using the structure above, fall back to a more
      generic heuristic based on <li> and <a> tags so the script still works
      even if the page structure changes.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[Dict[str, Any]] = []

    def add_candidate(text: str, pdf_url: Any) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        candidates.append({"text": cleaned, "pdf_url": pdf_url})

    # ------------------------------------------------------------------
    # Primary (college-specific): notifications ticker
    # All notifications are inside a div with BOTH classes:
    #   tg-ticker owl-carousel
    # ------------------------------------------------------------------
    ticker = soup.select_one("div.tg-ticker.owl-carousel")
    if ticker:
        debug_print("[extract] Found ticker container: div.tg-ticker.owl-carousel")

        # PSG-style ticker: notifications are direct children (often <section>).
        # We parse direct children first to avoid accidentally grabbing unrelated
        # nested markup.
        direct_items = ticker.find_all(recursive=False)
        debug_print(f"[extract] Ticker direct children found: {len(direct_items)}")
        for item in direct_items:
            classes = item.get("class", [])
            if isinstance(classes, list) and "cloned" in classes:
                continue

            text = item.get_text(strip=True)
            pdf_url = None
            for link in item.select("a"):
                href = (link.get("href") or "").strip()
                if href.lower().endswith(".pdf"):
                    pdf_url = href
                    break
            add_candidate(text, pdf_url)

        # Generic ticker rule (if direct-children parsing yields nothing):
        # Look for anchors with class 'active' anywhere inside the ticker and
        # ignore duplicates that are part of a 'cloned' element.
        if not candidates:
            anchors = ticker.select("a.active")
            debug_print(f"[extract] Ticker active anchors found: {len(anchors)}")
            for a_tag in anchors:
                cloned = False
                for parent in a_tag.parents:
                    if not hasattr(parent, "get"):
                        continue
                    classes = parent.get("class", [])
                    if isinstance(classes, list) and "cloned" in classes:
                        cloned = True
                        break
                if cloned:
                    continue

                text = a_tag.get_text(strip=True)
                href = (a_tag.get("href") or "").strip()
                pdf_url = href if href.lower().endswith(".pdf") else None
                add_candidate(text, pdf_url)

        # Final ticker fallback: common OwlCarousel item wrappers.
        if not candidates:
            items = ticker.select(".owl-item, .item")
            debug_print(f"[extract] Ticker item blocks found: {len(items)}")
            for item in items:
                classes = item.get("class", [])
                if isinstance(classes, list) and "cloned" in classes:
                    continue
                text = item.get_text(strip=True)
                pdf_url = None
                for link in item.select("a"):
                    href = (link.get("href") or "").strip()
                    if href.lower().endswith(".pdf"):
                        pdf_url = href
                        break
                add_candidate(text, pdf_url)

    # ------------------------------------------------------------------
    # Fallback: scan other owl-carousel containers (best-effort resilience)
    # ------------------------------------------------------------------
    if not candidates:
        debug_print("[extract] No ticker candidates; scanning other owl-carousel containers")
        for carousel in soup.select("div.owl-carousel"):
            for item in carousel.select("div.owl-item, div.item"):
                classes = item.get("class", [])
                if isinstance(classes, list) and "cloned" in classes:
                    continue
                text = item.get_text(strip=True)
                pdf_url = None
                for link in item.select("a"):
                    href = (link.get("href") or "").strip()
                    if href.lower().endswith(".pdf"):
                        pdf_url = href
                        break
                add_candidate(text, pdf_url)

    # ------------------------------------------------------------------
    # Last resort: whole-page scan (can include navigation items)
    # ------------------------------------------------------------------
    if not candidates:
        debug_print("[extract] No carousel candidates; falling back to generic scanning")
        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if not text:
                continue
            link = li.find("a")
            pdf_url = None
            if link and link.get("href"):
                href = (link.get("href") or "").strip()
                if href.lower().endswith(".pdf"):
                    pdf_url = href
            add_candidate(text, pdf_url)

    if not candidates:
        for a in soup.find_all("a"):
            text = a.get_text(strip=True)
            if not text:
                continue
            href = (a.get("href") or "").strip()
            pdf_url = href if href.lower().endswith(".pdf") else None
            add_candidate(text, pdf_url)

    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped: list[Dict[str, Any]] = []
    for cand in candidates:
        key = f"{(cand.get('text') or '').lower()}|{cand.get('pdf_url') or ''}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cand)
    return deduped


def fuzzy_matches(text: str, keywords: str, threshold: float) -> bool:
    """
    Check if any keyword fuzzy-matches the given text above the threshold.

    Keywords are comma-separated. We perform case-insensitive matching using:
    1. Substring check: if keyword appears anywhere in the text, it's a match
    2. Fuzzy similarity: if substring check fails, use SequenceMatcher ratio

    This handles both exact substring matches (e.g., "reappearance" in a longer
    announcement text) and fuzzy matches for typos/variations.
    """
    text_norm = text.lower()
    for raw_kw in keywords.split(","):
        kw = raw_kw.strip().lower()
        if not kw:
            continue
        
        # First check: if keyword appears as substring, it's definitely a match
        if kw in text_norm:
            return True
        
        # Second check: fuzzy similarity for partial matches and typos
        ratio = SequenceMatcher(None, text_norm, kw).ratio()
        if ratio >= threshold:
            return True
    return False


def detect_announcements(
    candidates: list[Dict[str, Any]],
    cfg: Config
) -> list[Announcement]:
    """
    Return all candidates that match the fuzzy keyword criteria.

    The 'id' for de-duplication is based on the text (and PDF URL if present).
    """
    now_iso = format_dt(now())
    debug_print(f"[detect] Checking {len(candidates)} candidates for {cfg.match_keywords!r}")

    matches: list[Announcement] = []

    for cand in candidates:
        text = cand.get("text") or ""
        pdf_url = cand.get("pdf_url")

        if not text:
            continue

        if fuzzy_matches(text, cfg.match_keywords, cfg.similarity_threshold):
            ann_id = text
            if pdf_url:
                ann_id = f"{text}|{pdf_url}"

            debug_print(f"[detect] Match: {text[:120]!r}")

            matches.append(
                Announcement(
                    id=ann_id,
                    text=text,
                    pdf_url=pdf_url,
                    first_detected=now_iso,
                )
            )

    return matches
