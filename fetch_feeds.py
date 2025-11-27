# fetch_feeds.py
import os
import yaml
import feedparser
import pandas as pd
from datetime import datetime, timezone

CONFIG_FEEDS = "config/feeds.yaml"
DATA_DIR = "data/raw"


def load_feeds():
    with open(CONFIG_FEEDS, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    feeds = cfg.get("feeds", [])
    if not feeds:
        raise RuntimeError("config/feeds.yaml 中没有找到 feeds 配置。")
    return feeds


def fetch_feed(feed: dict, default_max_items: int = 200):
    """
    从单个 RSS 源抓取条目，按 max_items 上限截断。
    feed 可以在 feeds.yaml 中配置 max_items 字段；否则使用 default_max_items。
    """
    url = feed["url"]
    parsed = feedparser.parse(url)

    # 读取 per-feed 上限
    max_items = feed.get("max_items")
    if max_items is None:
        max_items = default_max_items

    entries = parsed.entries[:max_items]

    rows = []
    for e in entries:
        # 有些 RSS 没有 summary，用 description 或其它字段兜底
        summary = getattr(e, "summary", "") or getattr(e, "description", "")
        published = getattr(e, "published", "") or getattr(e, "updated", "")

        rows.append(
            {
                "feed_id": feed["id"],
                "feed_name": feed["name"],
                "tags": ",".join(feed.get("tags", [])),
                "title": getattr(e, "title", ""),
                "link": getattr(e, "link", ""),
                "summary": summary,
                "published": published,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return rows


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    feeds = load_feeds()
    all_rows = []

    for feed in feeds:
        try:
            rows = fetch_feed(feed)
            all_rows.extend(rows)
            print(f"Fetched {len(rows)} items from {feed['name']}")
        except Exception as e:
            print(f"Error fetching {feed['name']}: {e}")

    if not all_rows:
        print("No data fetched.")
        return

    df = pd.DataFrame(all_rows)
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.join(DATA_DIR, f"articles_{today}.csv")
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
