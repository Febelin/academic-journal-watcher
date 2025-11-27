# daily_academic_report.py
import os
import re
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import yaml
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

# 加载 .env 中的 DEEPSEEK_API_KEY、EMAIL_*
load_dotenv()

RAW_DIR = "data/raw"                # ← 现在只从这里读取最新原始数据
SETTINGS_PATH = "config/settings.yaml"
REPORT_DIR = "data/reports"
SEEN_PATH = "data/seen_items.csv"   # ← 已见条目列表

# ======================
# 基础配置与工具函数
# ======================

def load_settings():
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_recent_data(df: pd.DataFrame, days_window: int) -> pd.DataFrame:
    """
    取最近 days_window 天内的文章（按 published / fetched_at）。
    当前版本 main 里没有使用该函数，如果以后想再加时间窗口过滤可以重用。
    """
    df = df.copy()
    for col in ["published", "fetched_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    ts = df["published"].fillna(df["fetched_at"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_window)
    return df[ts >= cutoff]


def load_latest_raw() -> Optional[pd.DataFrame]:
    """
    从 data/raw 目录中找到「最新修改」的 CSV 文件并读取。
    只读这一个文件，视为本次抓取到的全部数据。
    """
    if not os.path.exists(RAW_DIR):
        print(f"[错误] RAW_DIR 不存在：{RAW_DIR}")
        return None

    # 只考虑 .csv 文件；如果你有别的格式（如 .parquet），可以在这里扩展
    candidates = []
    for name in os.listdir(RAW_DIR):
        if name.lower().endswith(".csv"):
            full = os.path.join(RAW_DIR, name)
            if os.path.isfile(full):
                candidates.append(full)

    if not candidates:
        print(f"[错误] data/raw 目录下没有找到任何 CSV 文件：{RAW_DIR}")
        return None

    # 按最后修改时间选最新的文件
    latest_path = max(candidates, key=os.path.getmtime)
    print(f"[信息] 正在读取最新原始数据文件：{latest_path}")

    try:
        df = pd.read_csv(latest_path)
        return df
    except Exception as e:
        print(f"[错误] 读取最新原始文件失败：{e}")
        return None


# =======================
# baseline / 新增条目记录
# =======================

def load_seen_keys() -> Optional[set]:
    """
    从 SEEN_PATH 读取已经见过的条目 key 集合。
    key 的设计：feed_id + '||' + link。
    如果文件不存在，返回 None，表示首次运行（baseline 模式）。
    """
    if not os.path.exists(SEEN_PATH):
        return None

    try:
        df_seen = pd.read_csv(SEEN_PATH)
        if "key" not in df_seen.columns:
            return None
        keys = set(df_seen["key"].astype(str).tolist())
        return keys
    except Exception as e:
        print(f"[警告] 读取已见列表 {SEEN_PATH} 失败，将视为首次运行: {e}")
        return None


def update_seen_keys(df: pd.DataFrame):
    """
    把当前 df 里的所有条目 key 写入 SEEN_PATH（追加去重）。
    """
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)

    if df.empty:
        return

    keys = df.apply(
        lambda r: f"{r.get('feed_id', '')}||{r.get('link', '')}",
        axis=1,
    ).astype(str)

    df_new = pd.DataFrame({"key": keys}).drop_duplicates()

    if os.path.exists(SEEN_PATH):
        try:
            df_old = pd.read_csv(SEEN_PATH)
        except Exception:
            df_old = pd.DataFrame(columns=["key"])
        df_all = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates()
    else:
        df_all = df_new

    df_all.to_csv(SEEN_PATH, index=False)


def filter_new_items(recent_df: pd.DataFrame):
    """
    根据 SEEN_PATH 里的已见 key，只保留“新增”的条目。

    返回：
      - new_df: 只包含从未见过的条目
                （首次运行时 = recent_df 全部）
      - is_baseline: 如果是第一次运行（刚建立 baseline），则为 True
    """
    seen_keys = load_seen_keys()

    # 第一次运行：建立 baseline，但本次也推送所有当前条目
    if seen_keys is None:
        update_seen_keys(recent_df)
        print("[信息] 首次运行：已记录当前所有条目作为 baseline，本次会推送全部当前条目，以后只推新增。\n")
        return recent_df, True

    if recent_df.empty:
        return recent_df, False

    tmp = recent_df.copy()
    tmp["_key"] = tmp.apply(
        lambda r: f"{r.get('feed_id', '')}||{r.get('link', '')}",
        axis=1,
    ).astype(str)

    mask_new = ~tmp["_key"].isin(seen_keys)
    new_df = tmp[mask_new].drop(columns=["_key"])

    # 无论是否有新增，都更新一下已见列表（把今天看到的都记上）
    update_seen_keys(recent_df)

    return new_df, False


# =======================
#   DeepSeek 客户端 & 打分/翻译
# =======================

def get_deepseek_client() -> Optional[OpenAI]:
    """
    初始化 DeepSeek 客户端。
    需要环境变量 DEEPSEEK_API_KEY。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[警告] 未检测到环境变量 DEEPSEEK_API_KEY，跳过个性化推荐/翻译部分。")
        return None

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )
    return client


def score_item_with_deepseek(client: OpenAI, user_profile: str, item: dict) -> float:
    """
    给单条学术文章打“兴趣/相关性分”（0-100），使用 DeepSeek。
    只返回一个数字；解析失败时返回 0。
    """
    title = item.get("title", "") or ""
    summary = item.get("summary", "") or ""
    feed_name = item.get("feed_name", "") or ""
    link = item.get("link", "") or ""
    # 新增：尝试读取 doi / DOI 字段
    doi = item.get("doi", "") or item.get("DOI", "") or ""

    content_snippet = summary if summary.strip() else title

    prompt = f"""
你是一个学术文献推荐助手，请严格按照下面要求打分：

[研究者画像]
{user_profile}

[学术文章信息]
- 期刊 / 来源: {feed_name}
- 标题: {title}
- 摘要或简介: {content_snippet}
- 链接: {link}
- DOI: {doi}

任务：从“与研究者当前研究兴趣的相关性”角度，
给出一个 0-100 的分数：
- 0 分：几乎完全不相关
- 50 分：有点关系，可以顺手看看
- 80 分以上：高度相关，值得重点关注和阅读

**非常重要：你的回复只能包含一个阿拉伯数字（0 到 100 之间的整数），不要带任何解释和其他内容。**
"""

    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个只返回数字评分的学术推荐系统，不要输出解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
            stream=False,
        )
        content = resp.choices[0].message.content.strip()
        digits = re.findall(r"\d+", content)
        if not digits:
            return 0.0
        score = float(digits[0])
        return max(0.0, min(100.0, score))
    except Exception as e:
        print(f"[DeepSeek 错误] 打分失败: {e}")
        return 0.0


def translate_text_to_zh(client: OpenAI, text: str) -> str:
    """
    用 DeepSeek 把英文/其他语言的学术文本翻译成简体中文。
    翻译失败时返回原文。
    """
    text = (text or "").strip()
    if not text:
        return ""

    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一名专业的学术翻译，请把用户给出的学术标题或摘要翻译成自然、流畅的简体中文。"
                        "不要添加任何解释或前后缀，只输出译文本身。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            stream=False,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[DeepSeek 错误] 翻译失败: {e}")
        return text


# =======================
#   DeepSeek 个性化推荐
# =======================

def personalized_recommendations(recent_df: pd.DataFrame, settings: dict) -> Optional[pd.DataFrame]:
    """
    对“新增”的学术条目做个性化打分，返回 Top N 的 DataFrame。
    并发调用 DeepSeek，加速打分过程。
    """
    personalization = settings.get("personalization", {})
    enable = personalization.get("enable", False)
    if not enable:
        print("[提示] personalization.enable = false，未开启个性化推荐。")
        return None

    user_profile = personalization.get("user_profile", "").strip()
    if not user_profile:
        print("[提示] settings.yaml 中 personalization.user_profile 为空，跳过个性化推荐。")
        return None

    client = get_deepseek_client()
    if client is None:
        return None

    max_candidates = int(personalization.get("max_candidates", 80))
    top_n = int(personalization.get("top_n", 10))
    max_workers = int(personalization.get("max_workers", 20))

    if recent_df.empty:
        print("[提示] recent_df 为空，没有可以做个性化推荐的学术条目。")
        return None

    # 按时间排序，最新在前
    tmp = recent_df.copy()
    for col in ["published", "fetched_at"]:
        if col in tmp.columns:
            tmp[col] = pd.to_datetime(tmp[col], errors="coerce", utc=True)
    ts = tmp["published"].fillna(tmp["fetched_at"])
    tmp = tmp.assign(_ts=ts).sort_values("_ts", ascending=False)

    # 取前 max_candidates 条作为候选
    candidates = tmp.head(max_candidates).copy()

    print(f"[信息] 正在使用 DeepSeek 并发为最近 {len(candidates)} 条学术条目打相关性分（max_workers={max_workers}）...")

    items = list(candidates.to_dict(orient="records"))

    def _score(item_dict):
        return score_item_with_deepseek(client, user_profile, item_dict)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        scores = list(executor.map(_score, items))

    candidates = candidates.assign(_personal_score=scores)
    ranked = candidates.sort_values("_personal_score", ascending=False).head(top_n)

    return ranked


# ======================
# 报告生成 & 保存为 txt（含中英翻译 + DOI）
# ======================

def generate_and_save_report(personalized: pd.DataFrame, now: datetime) -> str:
    """
    把推荐结果打印到终端，同时保存到 data/reports/academic_YYYY-MM-DD.txt。
    会尝试用 DeepSeek 把标题和摘要翻译成中文一起写进去。
    同时输出 DOI 和 DOI 链接，方便下载。
    返回 txt 文件路径。
    """
    os.makedirs(REPORT_DIR, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    txt_path = os.path.join(REPORT_DIR, f"academic_{date_str}.txt")

    # 尝试拿一个 DeepSeek client 用来翻译；没有就只输出英文
    client = get_deepseek_client()

    lines = []
    lines.append("学术期刊监控日报（Academic Journal Watcher）")
    lines.append(f"生成时间：{now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("【个性化推荐】根据你的研究兴趣挑出的最新学术文章：")
    lines.append("")

    print("【个性化推荐】根据你的研究兴趣挑出的最新学术文章：\n")

    for _, row in personalized.iterrows():
        title = row.get("title", "") or ""
        feed_name = row.get("feed_name", "") or ""
        link = row.get("link", "") or ""
        score = row.get("_personal_score", 0)
        published = row.get("published", "")
        summary = row.get("summary", "") or ""
        # 新增：尝试读取 doi / DOI 字段
        doi = row.get("doi", "") or row.get("DOI", "") or ""
        doi = str(doi).strip()

        # 如果有 DeepSeek client，就翻译标题和摘要
        if client is not None:
            title_zh = translate_text_to_zh(client, title) if title else ""
            summary_zh = translate_text_to_zh(client, summary) if summary else ""
        else:
            title_zh = ""
            summary_zh = ""

        # ===== 打印到终端 =====
        print(f"- [{feed_name}] ({int(score)} 分)")
        if published is not None and str(published).strip():
            print(f"    时间: {published}")
        print(f"    标题: {title}")
        if title_zh:
            print(f"    标题: {title_zh}")
        if summary:
            print(f"    摘要: {summary}")
        if summary_zh:
            print(f"    摘要: {summary_zh}")
        if doi:
            print(f"    DOI: {doi}")
            # 如果不是完整链接，就顺手生成一个 doi.org 的链接
            if not doi.lower().startswith("http"):
                print(f"    DOI链接: https://doi.org/{doi}")
        print(f"    链接: {link}")
        print()

        # ===== 写入 txt 文本 =====
        lines.append(f"- [{feed_name}] ({int(score)} 分)")
        if published is not None and str(published).strip():
            lines.append(f"    时间: {published}")
        lines.append(f"    标题: {title}")
        if title_zh:
            lines.append(f"    标题: {title_zh}")
        if summary:
            lines.append(f"    摘要: {summary}")
        if summary_zh:
            lines.append(f"    摘要: {summary_zh}")
        if doi:
            lines.append(f"    DOI: {doi}")
            if not doi.lower().startswith("http"):
                lines.append(f"    DOI链接: https://doi.org/{doi}")
        lines.append(f"    链接: {link}")
        lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[信息] 已将学术推荐日报保存到：{txt_path}")
    return txt_path


# ======================
#         主程序
# ======================

def main():
    # 1. 从 data/raw 中读取最新原始数据文件
    df = load_latest_raw()
    if df is None or df.empty:
        print("未能从 data/raw 读取到任何数据，程序结束。")
        return

    settings = load_settings()

    now = datetime.now()
    print("=" * 80)
    print("学术期刊监控 - 个性化推荐日报")
    print("生成时间：", now.strftime("%Y-%m-%d %H:%M"))
    print("=" * 80, "\n")

    # 2. 只保留相对于 baseline 的“新增条目”（首次运行 = 全部）
    recent_new, is_baseline = filter_new_items(df)

    if is_baseline:
        print("【提示】首次运行：本次推送的是当前抓到的全部学术条目，以后每天只推新增。\n")

    if recent_new.empty:
        print("最近没有相对于 baseline 的新增学术文章。")
        print("结束。")
        return

    # 3. 用 DeepSeek 做个性化打分
    personalized = personalized_recommendations(recent_new, settings)

    if personalized is None or personalized.empty:
        print("当前没有可推荐的学术文章（可能是 personalization 未开启 / DeepSeek 出错）。")
        print("结束。")
        return

    # 4. 生成 txt 日报
    generate_and_save_report(personalized, now)
    print("结束。")


if __name__ == "__main__":
    main()
