# Academic Journal Watcher / 学术期刊监测器

> Automatically monitors your selected academic journals every two weeks, using LLMs to filter and compile the articles most relevant to your interests for easy browsing and reading.  
> 每两周自动监测你自定义的学术期刊，借助大语言模型（LLM）筛选并整理你最感兴趣的文章与链接，方便快速浏览与学习。基于 GitHub Actions，实现全自动、零人工维护的更新流程。

---

## 📘 Overview / 项目简介

**Academic Journal Watcher** is an automated pipeline that:

- monitors selected academic journals via RSS,
- fetches and stores new articles,
- detects *newly appeared* items compared to previous runs,
- uses LLMs (DeepSeek via OpenAI SDK) to score relevance based on your research interests,
- generates a human-readable report (with optional Chinese translations),
- and (optionally) emails the report to you.

All of this is orchestrated by **GitHub Actions**, so it runs on a fixed schedule (e.g., every 14 days) with **zero manual effort**.

---

## ✨ Features / 功能亮点

- 🔄 **Bi-weekly scheduled runs** via GitHub Actions（默认每 14 天运行一次）
- 📰 **RSS-based journal monitoring** – configurable in `config/feeds.yaml`
- 🆕 **Incremental new-item detection** via `data/seen_items.csv` 去重
- 🤖 **LLM-powered relevance scoring** using DeepSeek（通过用户研究兴趣画像打分）
- 🌐 **Optional EN → ZH translation** for titles & abstracts（自动生成中文译文）
- 📄 **Plain-text reports** saved in `data/reports/academic_YYYY-MM-DD.txt`
- 💾 **Auto-commit of tracking & reports** back to the repository
- 📬 **Optional email delivery** via SMTP（可选邮件发送）

---

## 📁 Project Structure / 目录结构

```bash
academic-journal-watcher/
│
├── fetch_feeds.py                 # Fetch RSS feeds → raw CSV
├── daily_academic_report.py       # New-item detection + scoring + report generation
├── send_email.py                  # (Optional) Email delivery
│
├── config/
│   ├── feeds.yaml                 # Journal list & RSS URLs
│   └── settings.yaml              # Personalization & DeepSeek settings
│
├── data/
│   ├── raw/                       # Raw fetched data (auto-generated)
│   ├── reports/                   # Generated text reports (auto-generated & committed)
│   └── seen_items.csv             # Seen-item tracking for de-duplication
│
├── .github/
│   └── workflows/
│       └── academic_watcher.yml   # GitHub Actions workflow
│
├── requirements.txt
└── README.md
...
```

## ⚙️ Usage 使用方式

### 1. 安装依赖
```bash
pip install -r requirements.txt

### 2. 本地可选
python fetch_feeds.py
python daily_academic_report.py

### 3.配置 GitHub Secrets（必须）
DEEPSEEK_API_KEY
EMAIL_FROM
EMAIL_TO
EMAIL_PASSWORD
EMAIL_SMTP_SERVER
EMAIL_SMTP_PORT

## 💪🏻 Reproduce 复现方式（一步理解）
复制该仓库结构
写好 feeds.yaml（自定义或者不动也行） + settings.yaml（自定义或者不动也行）
填 GitHub Secrets
Push 到 GitHub
GitHub Actions 运行即可

## 📜 License
MIT License.
