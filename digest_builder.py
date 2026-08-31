#!/usr/bin/env python3
"""
Lakeland TN Custom News Digest - Builder
Fetches RSS feeds, filters noise, deduplicates, categorizes, and generates HTML email digests.
"""

import os
import sys
import re
import json
import html
import urllib.request
import urllib.parse
import email.utils
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

USER_AGENT = "python:lakeland.news.digest:v1.0 (by /u/lakeland_digest_bot; contact: admin@lakelanddigest.local)"


def clean_html_text(raw_html: str) -> str:
    """Strips HTML tags, decodes entities, and cleans whitespace."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'The post\s+.*?\s+appeared first on\s+.*?\.', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_date(date_str: str) -> datetime:
    """Parses various date string formats (RFC 822, ISO 8601) to UTC datetime."""
    if not date_str:
        return datetime.now(timezone.utc)
    date_str = date_str.strip()
    
    try:
        parsed_tuple = email.utils.parsedate_tz(date_str)
        if parsed_tuple:
            timestamp = email.utils.mktime_tz(parsed_tuple)
            return datetime.fromtimestamp(timestamp, timezone.utc)
    except Exception:
        pass

    iso_formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d"
    ]
    for fmt in iso_formats:
        try:
            if date_str.endswith("Z"):
                return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue

    return datetime.now(timezone.utc)


def fetch_url(url: str, timeout: int = 15) -> str:
    """Fetches text content from a URL with browser-like headers."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, application/atom+xml, text/html, */*"
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_feed_xml(xml_content: str, feed_meta: dict) -> list:
    """Parses RSS or Atom XML string and returns list of standardized article dicts."""
    articles = []
    try:
        clean_xml = re.sub(r' xmlns(:[a-zA-Z0-9_-]+)?="[^"]+"', '', xml_content, count=1)
        root = ET.fromstring(clean_xml)
    except Exception:
        return parse_feed_regex(xml_content, feed_meta)

    # RSS 2.0
    channel = root.find("channel")
    if channel is not None or root.tag in ("rss", "channel"):
        items = root.findall(".//item")
        for item in items:
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate") or item.find("date")
            desc_el = item.find("description") or item.find("summary")
            content_el = item.find("encoded") or item.find("content")
            source_el = item.find("source")

            title = clean_html_text(title_el.text if title_el is not None else "")
            link = (link_el.text or "").strip() if link_el is not None else ""
            pub_date_str = pub_el.text if pub_el is not None else ""
            desc = clean_html_text(desc_el.text if desc_el is not None else "")
            
            if not desc and content_el is not None and content_el.text:
                desc = clean_html_text(content_el.text)

            source_name = feed_meta.get("name", "Local News")
            if source_el is not None and source_el.text:
                source_name = source_el.text.strip()
            elif " - " in title and feed_meta.get("id") == "regional_google_news":
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                source_name = parts[1].strip()

            if title and link:
                articles.append({
                    "title": title,
                    "link": link,
                    "published_at": parse_date(pub_date_str),
                    "summary": desc[:300] + ("..." if len(desc) > 300 else ""),
                    "source_name": source_name,
                    "feed_id": feed_meta.get("id", "feed"),
                    "default_category": feed_meta.get("default_category", "local_news")
                })
        return articles

    # Atom
    if root.tag.endswith("feed") or root.find(".//entry") is not None:
        entries = root.findall(".//entry")
        for entry in entries:
            title_el = entry.find("title")
            link_el = entry.find("link")
            pub_el = entry.find("published") or entry.find("updated")
            summary_el = entry.find("summary") or entry.find("content")

            title = clean_html_text(title_el.text if title_el is not None else "")
            link = ""
            if link_el is not None:
                link = link_el.attrib.get("href", link_el.text or "").strip()

            pub_date_str = pub_el.text if pub_el is not None else ""
            desc = clean_html_text(summary_el.text if summary_el is not None else "")

            if title and link:
                articles.append({
                    "title": title,
                    "link": link,
                    "published_at": parse_date(pub_date_str),
                    "summary": desc[:300] + ("..." if len(desc) > 300 else ""),
                    "source_name": feed_meta.get("name", "Local News"),
                    "feed_id": feed_meta.get("id", "feed"),
                    "default_category": feed_meta.get("default_category", "local_news")
                })
        return articles

    return articles


def parse_feed_regex(raw_content: str, feed_meta: dict) -> list:
    """Fallback parser using regular expressions for resilient handling."""
    articles = []
    item_matches = re.findall(r'<item>(.*?)</item>', raw_content, flags=re.DOTALL | re.IGNORECASE)
    for block in item_matches:
        title_m = re.search(r'<title>(.*?)</title>', block, flags=re.DOTALL | re.IGNORECASE)
        link_m = re.search(r'<link>(.*?)</link>', block, flags=re.DOTALL | re.IGNORECASE)
        pub_m = re.search(r'<pubDate>(.*?)</pubDate>', block, flags=re.DOTALL | re.IGNORECASE)
        desc_m = re.search(r'<description>(.*?)</description>', block, flags=re.DOTALL | re.IGNORECASE)

        title = clean_html_text(title_m.group(1)) if title_m else ""
        link = clean_html_text(link_m.group(1)) if link_m else ""
        pub_str = pub_m.group(1).strip() if pub_m else ""
        desc = clean_html_text(desc_m.group(1)) if desc_m else ""

        source_name = feed_meta.get("name", "Local News")
        if " - " in title and feed_meta.get("id") == "regional_google_news":
            parts = title.rsplit(" - ", 1)
            title = parts[0].strip()
            source_name = parts[1].strip()

        if title and link:
            articles.append({
                "title": title,
                "link": link,
                "published_at": parse_date(pub_str),
                "summary": desc[:300] + ("..." if len(desc) > 300 else ""),
                "source_name": source_name,
                "feed_id": feed_meta.get("id", "feed"),
                "default_category": feed_meta.get("default_category", "local_news")
            })
    return articles


class LakelandDigestBuilder:
    def __init__(self, config_path: str = "config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def fetch_all_feeds(self) -> list:
        """Fetches all active feeds in parallel."""
        all_articles = []
        feeds = [f for f in self.config.get("feeds", []) if f.get("enabled", True)]

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_feed = {
                executor.submit(fetch_url, feed["url"]): feed
                for feed in feeds
            }
            for future in as_completed(future_to_feed):
                feed = future_to_feed[future]
                try:
                    xml_content = future.result()
                    parsed = parse_feed_xml(xml_content, feed)
                    all_articles.extend(parsed)
                    print(f"✓ [{feed['name']}] fetched {len(parsed)} items")
                except Exception as e:
                    print(f"✗ [{feed['name']}] fetch failed: {e}", file=sys.stderr)

        return all_articles

    def filter_and_deduplicate(self, articles: list, lookback_days: int = None, seen_urls: set = None) -> list:
        """Filters out noise/irrelevant keywords, duplicates, and out-of-date articles."""
        if lookback_days is None:
            lookback_days = self.config.get("lookback_days", 7)
        if seen_urls is None:
            seen_urls = set()

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        exclude_kws = [k.lower() for k in self.config.get("filter_exclude_keywords", [])]

        filtered = []
        collected_titles = []

        for item in articles:
            # Date filter
            if item["published_at"] < cutoff_date:
                continue

            # Check seen URL
            if item["link"] in seen_urls:
                continue

            # Exclude keywords check
            content_lower = f"{item['title']} {item['summary']} {item['source_name']}".lower()
            if any(kw in content_lower for kw in exclude_kws):
                continue

            # Fuzzy deduplication by title similarity
            is_dup = False
            for existing_title in collected_titles:
                similarity = SequenceMatcher(None, item["title"].lower(), existing_title.lower()).ratio()
                if similarity > 0.75:
                    is_dup = True
                    break

            if not is_dup:
                collected_titles.append(item["title"])
                filtered.append(item)

        filtered.sort(key=lambda x: x["published_at"], reverse=True)
        return filtered

    def categorize_article(self, article: dict) -> str:
        """Assigns the best matching category key to an article."""
        categories = self.config.get("categories", {})
        text_to_search = f"{article['title']} {article['summary']}".lower()

        sorted_cats = sorted(categories.items(), key=lambda x: x[1].get("priority", 99))
        for cat_key, cat_info in sorted_cats:
            keywords = cat_info.get("keywords", [])
            for kw in keywords:
                if kw.lower() in text_to_search:
                    return cat_key

        return article.get("default_category", "local_news")

    def group_by_category(self, articles: list) -> dict:
        """Groups filtered articles into configured categories."""
        categories = self.config.get("categories", {})
        max_per_cat = self.config.get("max_items_per_category", 8)
        grouped = {k: [] for k in categories.keys()}

        for art in articles:
            cat = self.categorize_article(art)
            if cat not in grouped:
                grouped[cat] = []
            if len(grouped[cat]) < max_per_cat:
                grouped[cat].append(art)

        active_grouped = {
            k: v for k, v in grouped.items()
            if len(v) > 0
        }
        sorted_grouped = dict(
            sorted(
                active_grouped.items(),
                key=lambda x: categories.get(x[0], {}).get("priority", 99)
            )
        )
        return sorted_grouped

    def generate_html_digest(self, grouped_articles: dict, total_count: int) -> str:
        """Renders an inline-styled, responsive HTML newsletter."""
        today_str = datetime.now().strftime("%A, %B %d, %Y")
        categories_cfg = self.config.get("categories", {})

        sections_html = ""
        for cat_key, items in grouped_articles.items():
            cat_cfg = categories_cfg.get(cat_key, {"title": cat_key.title(), "icon": "📌"})
            cat_title = cat_cfg.get("title", cat_key.title())
            cat_icon = cat_cfg.get("icon", "📌")

            items_cards = ""
            for item in items:
                pub_fmt = item["published_at"].strftime("%b %d, %Y")
                summary_p = f'<p style="margin: 6px 0 0 0; color: #4b5563; font-size: 14px; line-height: 1.5;">{html.escape(item["summary"])}</p>' if item.get("summary") else ""
                
                items_cards += f"""
                <div style="background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                        <span style="display: inline-block; background-color: #eff6ff; color: #1e40af; font-weight: 700; font-size: 11px; padding: 3px 8px; border-radius: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
                            {html.escape(item['source_name'])}
                        </span>
                        <span style="color: #9ca3af; font-size: 12px;">{pub_fmt}</span>
                    </div>
                    <a href="{html.escape(item['link'])}" target="_blank" style="color: #1e3a8a; text-decoration: none; font-size: 16px; font-weight: 700; line-height: 1.35; display: block; margin-top: 4px;">
                        {html.escape(item['title'])}
                    </a>
                    {summary_p}
                    <div style="margin-top: 10px;">
                        <a href="{html.escape(item['link'])}" target="_blank" style="display: inline-block; color: #2563eb; font-size: 13px; font-weight: 600; text-decoration: none;">
                            Read Full Story &rarr;
                        </a>
                    </div>
                </div>
                """

            sections_html += f"""
            <div style="margin-top: 24px;">
                <div style="border-bottom: 2px solid #1e3a8a; padding-bottom: 6px; margin-bottom: 14px;">
                    <h2 style="margin: 0; color: #1e3a8a; font-size: 18px; font-weight: 800; display: flex; align-items: center;">
                        <span style="margin-right: 8px; font-size: 20px;">{cat_icon}</span> {html.escape(cat_title)}
                    </h2>
                </div>
                {items_cards}
            </div>
            """

        empty_notice = ""
        if total_count == 0:
            empty_notice = """
            <div style="background-color: #ffffff; border-radius: 8px; padding: 30px; text-align: center; color: #6b7280; border: 1px dashed #d1d5db; margin: 30px 0;">
                <p style="font-size: 16px; margin: 0;">No new Lakeland updates were published in this window.</p>
                <p style="font-size: 13px; margin-top: 8px; color: #9ca3af;">All active municipal, news, and community sources are being monitored.</p>
            </div>
            """

        full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lakeland, TN Community Digest</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 24px 12px;">
        <tr>
            <td align="center">
                <table role="presentation" width="100%" style="max-width: 640px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border: 1px solid #e2e8f0;" cellspacing="0" cellpadding="0">
                    <!-- HEADER -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); padding: 32px 24px; text-align: center; color: #ffffff;">
                            <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #93c5fd; margin-bottom: 6px;">
                                📍 Shelby County, Tennessee
                            </div>
                            <h1 style="margin: 0 0 10px 0; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; color: #ffffff;">
                                Lakeland Community News Digest
                            </h1>
                            <div style="display: inline-block; background-color: rgba(255, 255, 255, 0.15); padding: 4px 12px; border-radius: 9999px; font-size: 13px; color: #ffffff; font-weight: 500;">
                                📅 {today_str} • {total_count} Updates
                            </div>
                        </td>
                    </tr>

                    <!-- CONTENT -->
                    <tr>
                        <td style="padding: 24px; background-color: #f8fafc;">
                            {sections_html}
                            {empty_notice}
                        </td>
                    </tr>

                    <!-- FOOTER -->
                    <tr>
                        <td style="background-color: #f1f5f9; padding: 20px 24px; text-align: center; border-top: 1px solid #e2e8f0; color: #64748b; font-size: 12px; line-height: 1.5;">
                            <p style="margin: 0 0 6px 0; font-weight: 600; color: #475569;">
                                Automated Lakeland, TN Custom News Digest
                            </p>
                            <p style="margin: 0;">
                                Sources: City of Lakeland (lakelandtn.gov), Lakeland Currents, Regional News & Community Feeds.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
        return full_html

    def generate_plain_text(self, grouped_articles: dict, total_count: int) -> str:
        """Generates a clean plain-text fallback version."""
        today_str = datetime.now().strftime("%A, %B %d, %Y")
        categories_cfg = self.config.get("categories", {})
        
        lines = [
            f"LAKELAND, TN COMMUNITY NEWS DIGEST",
            f"{today_str} | {total_count} Updates",
            "=" * 45,
            ""
        ]

        if total_count == 0:
            lines.append("No new Lakeland updates were published in this window.")
            return "\n".join(lines)

        for cat_key, items in grouped_articles.items():
            cat_cfg = categories_cfg.get(cat_key, {"title": cat_key.title()})
            cat_title = cat_cfg.get("title", cat_key.title()).upper()
            
            lines.append(f"\n--- {cat_title} ---")
            for item in items:
                pub_fmt = item["published_at"].strftime("%b %d, %Y")
                lines.append(f"\n• {item['title']} [{item['source_name']} - {pub_fmt}]")
                if item.get("summary"):
                    lines.append(f"  {item['summary']}")
                lines.append(f"  Link: {item['link']}")

        lines.append("\n" + "=" * 45)
        lines.append("Automated Lakeland News Digest | Shelby County, TN")
        return "\n".join(lines)
