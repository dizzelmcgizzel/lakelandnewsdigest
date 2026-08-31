#!/usr/bin/env python3
"""
Lakeland TN Custom News Digest - Main CLI
Usage:
    python3 main.py --preview        # Generate local HTML preview without sending
    python3 main.py --send           # Fetch, build, email digest, and update history
    python3 main.py --force --send   # Force fetch last 7 days regardless of history
"""

import os
import sys
import json
import argparse
import webbrowser
from datetime import datetime, timezone
from digest_builder import LakelandDigestBuilder
from mailer import send_digest_email

HISTORY_FILE = "history.json"
PREVIEW_FILE = "preview_digest.html"


def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sent_urls": [], "last_run_at": None}


def save_history(sent_urls: list):
    # Keep up to 500 recent URLs
    data = {
        "sent_urls": sent_urls[-500:],
        "last_run_at": datetime.now(timezone.utc).isoformat()
    }
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Lakeland TN Custom News Digest")
    parser.add_argument("--preview", action="store_true", help="Generate preview HTML and open locally")
    parser.add_argument("--send", action="store_true", help="Send email digest via configured SMTP")
    parser.add_argument("--force", action="store_true", help="Ignore sent history and pull all recent items")
    parser.add_argument("--lookback", type=int, default=None, help="Lookback window in days (default from config)")
    parser.add_argument("--output", type=str, default=PREVIEW_FILE, help="Custom output path for preview HTML")
    args = parser.parse_args()

    # Default to preview if neither --send nor --preview is specified
    is_send = args.send
    is_preview = args.preview or not is_send

    print("🚀 Initializing Lakeland TN News Digest Pipeline...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    builder = LakelandDigestBuilder(config_path="config.json")
    history = load_history()
    seen_urls = set(history.get("sent_urls", [])) if not args.force else set()

    print(f"📡 Fetching active news and notification feeds...")
    raw_articles = builder.fetch_all_feeds()
    print(f"📦 Total raw items fetched: {len(raw_articles)}")

    filtered_articles = builder.filter_and_deduplicate(
        raw_articles,
        lookback_days=args.lookback,
        seen_urls=seen_urls
    )
    print(f"✨ New relevant items after filtering & deduplication: {len(filtered_articles)}")

    grouped = builder.group_by_category(filtered_articles)

    # Print summary breakdown
    for cat_key, items in grouped.items():
        print(f"   • {cat_key}: {len(items)} item(s)")

    html_content = builder.generate_html_digest(grouped, len(filtered_articles))
    plain_content = builder.generate_plain_text(grouped, len(filtered_articles))

    # Save HTML output
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"📄 HTML digest saved to: {os.path.abspath(args.output)}")

    if is_send:
        if len(filtered_articles) == 0 and not args.force:
            print("ℹ️ No new articles found since last run. Skipping email dispatch.")
            return

        print("✉️ Dispatching digest email...")
        success = send_digest_email(html_content, plain_content, len(filtered_articles))
        if success:
            # Update history with newly sent URLs
            new_urls = list(seen_urls.union({a["link"] for a in filtered_articles}))
            save_history(new_urls)
            print("💾 Sent history updated.")
    elif is_preview:
        print(f"\n🌐 Preview generated successfully!")
        print(f"Open in browser: file://{os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
