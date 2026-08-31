#!/usr/bin/env python3
"""
Lakeland TN Custom News Digest - Builder
Fetches RSS feeds, filters noise, deduplicates, generates 3-4 sentence summaries,
and produces HTML email digests.
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

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def clean_html_text(raw_html: str) -> str:
    """Strips HTML tags, decodes entities, and cleans whitespace."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'The post\s+.*?\s+appeared first on\s+.*?\.', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[\.\.\.\]|\[&#8230;\]|\.\.\.', ' ', text)
    text = re.sub(r'Create a Website Account.*?Contact Us', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Search autocomplete is currently not responding.*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Phone:\s*901-867-\d+', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_3_to_4_sentences(text: str, target_sentences: int = 3) -> str:
    """Extracts 3-4 full, coherent, deduplicated sentences from a text snippet."""
    if not text:
        return ""
    cleaned = clean_html_text(text)
    sentence_candidates = re.split(r'(?<=[.!?])\s+', cleaned)
    seen = set()
    clean_sentences = []
    
    for s in sentence_candidates:
        s_clean = s.strip()
        s_lower = s_clean.lower()
        if len(s_clean) < 18 or s_lower in seen:
            continue
        if s_lower.startswith("the post") or s_lower.startswith("read more") or "cookie policy" in s_lower:
            continue
        seen.add(s_lower)
        clean_sentences.append(s_clean)
        if len(clean_sentences) >= 4:
            break

    if len(clean_sentences) >= 3:
        return " ".join(clean_sentences[:4])
    elif clean_sentences:
        return " ".join(clean_sentences)
    return cleaned[:350].strip()


def parse_date(date_str: str) -> datetime:
    """Parses RFC 822 or ISO 8601 date strings to UTC datetime."""
    if not date_str:
        return None
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

    return None


def fetch_url(url: str, timeout: int = 15) -> str:
    """Fetches text content from a URL with browser headers."""
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


def fetch_article_lead_sentences(url: str) -> str:
    """Fetches article page to extract the lead paragraph (3-4 sentences) when RSS is brief."""
    if not url or "reddit.com" in url or "google.com" in url or "google.co" in url:
        return ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            html_doc = resp.read().decode("utf-8", errors="replace")
            
            # Try Open Graph description or Meta Description
            og_match = re.search(r'<meta\s+(?:property="og:description"|name="description")\s+content="([^"]+)"', html_doc, re.I)
            if not og_match:
                og_match = re.search(r'<meta\s+content="([^"]+)"\s+(?:property="og:description"|name="description")', html_doc, re.I)
            
            meta_desc = ""
            if og_match:
                meta_desc = clean_html_text(og_match.group(1))

            # Extract first 3 paragraph texts
            p_matches = re.findall(r'<p[^>]*>(.*?)</p>', html_doc, re.DOTALL | re.I)
            p_texts = [clean_html_text(p) for p in p_matches if len(clean_html_text(p)) > 40]
            
            combined = meta_desc + " " + " ".join(p_texts[:3]) if meta_desc else " ".join(p_texts[:3])
            summary = extract_3_to_4_sentences(combined, target_sentences=3)
            return summary
    except Exception:
        return ""


def parse_feed_xml(xml_content: str, feed_meta: dict) -> list:
    """Parses RSS or Atom XML string and returns list of standardized article dicts."""
    articles = []
    try:
        # Strip all namespace prefixes like <prefix:tag> -> <tag>
        clean_xml = re.sub(r'<(/)?([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+)', r'<\1\3', xml_content)
        clean_xml = re.sub(r'\s+xmlns(:[a-zA-Z0-9_-]+)?="[^"]+"', '', clean_xml)
        root = ET.fromstring(clean_xml)
    except Exception:
        return []

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
            event_date_el = item.find("EventDate") or item.find("eventDate")

            title = clean_html_text(title_el.text if title_el is not None else "")
            link = (link_el.text or "").strip() if link_el is not None else ""
            pub_date_str = pub_el.text if pub_el is not None else ""
            parsed_dt = parse_date(pub_date_str)
            
            raw_desc = ""
            if content_el is not None and content_el.text:
                raw_desc = clean_html_text(content_el.text)
            elif desc_el is not None and desc_el.text:
                raw_desc = clean_html_text(desc_el.text)

            if event_date_el is not None and event_date_el.text:
                event_date_str = event_date_el.text.strip()
                raw_desc = f"Event Date: {event_date_str}. {raw_desc}"
                # For calendar events, treat upcoming/recent events as current
                if not parsed_dt:
                    parsed_dt = datetime.now(timezone.utc)

            summary = extract_3_to_4_sentences(raw_desc, target_sentences=3)

            source_name = feed_meta.get("name", "Local News")
            if source_el is not None and source_el.text:
                source_name = source_el.text.strip()
            elif " - " in title and "google" in feed_meta.get("url", "").lower():
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                source_name = parts[1].strip()

            if title and link:
                articles.append({
                    "title": title,
                    "link": link,
                    "published_at": parsed_dt,
                    "summary": summary,
                    "raw_desc": raw_desc,
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
            parsed_dt = parse_date(pub_date_str)
            raw_desc = clean_html_text(summary_el.text if summary_el is not None else "")
            summary = extract_3_to_4_sentences(raw_desc, target_sentences=3)

            if title and link:
                articles.append({
                    "title": title,
                    "link": link,
                    "published_at": parsed_dt,
                    "summary": summary,
                    "raw_desc": raw_desc,
                    "source_name": feed_meta.get("name", "Local News"),
                    "feed_id": feed_meta.get("id", "feed"),
                    "default_category": feed_meta.get("default_category", "local_news")
                })
        return articles

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
        """Enforces strict recent-date cutoff, exclusions, and fuzzy deduplication."""
        if lookback_days is None:
            lookback_days = self.config.get("lookback_days", 7)
        if seen_urls is None:
            seen_urls = set()

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        exclude_kws = [k.lower() for k in self.config.get("filter_exclude_keywords", [])]

        filtered = []
        collected_titles = []

        for item in articles:
            # Strict Date Cutoff: Reject anything older than lookback_days
            if item["published_at"] is not None and item["published_at"] < cutoff_date:
                continue

            # Check persistent history
            if item["link"] in seen_urls:
                continue

            # Exclude keywords check
            content_lower = f"{item['title']} {item['summary']} {item['source_name']}".lower()
            if any(kw in content_lower for kw in exclude_kws):
                continue

            # Fuzzy deduplication by headline similarity (>75% match)
            is_dup = False
            for existing_title in collected_titles:
                similarity = SequenceMatcher(None, item["title"].lower(), existing_title.lower()).ratio()
                if similarity > 0.75:
                    is_dup = True
                    break

            if not is_dup:
                collected_titles.append(item["title"])
                filtered.append(item)

        # Fallback date if None was parsed
        for item in filtered:
            if item["published_at"] is None:
                item["published_at"] = datetime.now(timezone.utc)

        # Enrich brief summaries to ensure 3-4 sentences
        self._enrich_short_summaries(filtered)

        filtered.sort(key=lambda x: x["published_at"], reverse=True)
        return filtered

    def _enrich_short_summaries(self, articles: list):
        """Asynchronously fetches lead paragraphs for articles with brief summaries."""
        articles_to_enrich = []
        for art in articles:
            # If summary has fewer than 2 sentences or under 100 characters
            sentence_count = len(re.split(r'(?<=[.!?])\s+', art["summary"].strip()))
            if sentence_count < 2 or len(art["summary"]) < 100:
                articles_to_enrich.append(art)

        if not articles_to_enrich:
            return

        print(f"🔍 Enriching {len(articles_to_enrich)} brief article summaries...")
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_art = {
                executor.submit(fetch_article_lead_sentences, art["link"]): art
                for art in articles_to_enrich
            }
            for future in as_completed(future_to_art):
                art = future_to_art[future]
                try:
                    lead = future.result()
                    if lead and len(lead) > len(art["summary"]):
                        art["summary"] = lead
                except Exception:
                    pass

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
        max_per_cat = self.config.get("max_items_per_category", 6)
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
        """Renders an inline-styled, responsive HTML newsletter with 3-4 sentence summaries."""
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
                summary_text = item.get("summary", "")
                
                summary_p = f'<p style="margin: 8px 0 0 0; color: #374151; font-size: 14px; line-height: 1.6;">{html.escape(summary_text)}</p>' if summary_text else ""
                
                items_cards += f"""
                <div style="background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 18px; margin-bottom: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                        <span style="display: inline-block; background-color: #eff6ff; color: #1e40af; font-weight: 700; font-size: 11px; padding: 3px 8px; border-radius: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
                            {html.escape(item['source_name'])}
                        </span>
                        <span style="color: #9ca3af; font-size: 12px; font-weight: 500;">{pub_fmt}</span>
                    </div>
                    <a href="{html.escape(item['link'])}" target="_blank" style="color: #1e3a8a; text-decoration: none; font-size: 16px; font-weight: 700; line-height: 1.35; display: block;">
                        {html.escape(item['title'])}
                    </a>
                    {summary_p}
                    <div style="margin-top: 12px; border-top: 1px solid #f3f4f6; padding-top: 10px;">
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
                <p style="font-size: 16px; margin: 0; font-weight: 600;">No new Lakeland updates were published in the last 7 days.</p>
                <p style="font-size: 13px; margin-top: 8px; color: #9ca3af;">All active municipal, news, and community sources are being actively monitored.</p>
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
        """Generates a clean plain-text fallback version with 3-4 sentence summaries."""
        today_str = datetime.now().strftime("%A, %B %d, %Y")
        categories_cfg = self.config.get("categories", {})
        
        lines = [
            f"LAKELAND, TN COMMUNITY NEWS DIGEST",
            f"{today_str} | {total_count} Updates",
            "=" * 45,
            ""
        ]

        if total_count == 0:
            lines.append("No new Lakeland updates were published in the last 7 days.")
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
