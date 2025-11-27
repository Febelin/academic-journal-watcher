# send_email.py
import os
import smtplib
import yaml
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header

EMAIL_CONFIG_PATH = "config/email.yaml"
REPORT_DIR = "data/reports"


def load_report():
    """
    从 daily_academic_report.py 生成的文本文件中读取学术日报内容。
    文件命名约定：
      data/reports/academic_YYYY-MM-DD.txt
    日期优先从环境变量 REPORT_DATE 读取（YYYY-MM-DD），否则用今天日期。
    """
    date_str = os.environ.get("REPORT_DATE") or datetime.now().strftime("%Y-%m-%d")
    filename = f"academic_{date_str}.txt"
    path = os.path.join(REPORT_DIR, filename)

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found. 请先运行 daily_academic_report.py 生成当天的学术日报。"
        )

    with open(path, "r", encoding="utf-8") as f:
        body = f.read()

    return body, date_str


def load_email_config():
    """
    优先用环境变量；如果不全，则从 config/email.yaml 读取。
    """
    cfg = {}

    for key in [
        "EMAIL_FROM",
        "EMAIL_TO",
        "EMAIL_PASSWORD",
        "EMAIL_SMTP_SERVER",
        "EMAIL_SMTP_PORT",
    ]:
        val = os.environ.get(key)
        if val:
            cfg[key] = val

    required_keys = ["EMAIL_FROM", "EMAIL_TO", "EMAIL_PASSWORD"]
    if not all(k in cfg for k in required_keys):
        if not os.path.exists(EMAIL_CONFIG_PATH):
            raise RuntimeError(
                "环境变量和 config/email.yaml 都不完整，无法发送邮件。"
            )
        with open(EMAIL_CONFIG_PATH, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        for k, v in y.items():
            if v is not None and k not in cfg:
                cfg[k] = str(v)

    if not all(k in cfg for k in required_keys):
        raise RuntimeError(
            "EMAIL_FROM / EMAIL_TO / EMAIL_PASSWORD 未设置，请检查环境变量或 config/email.yaml。"
        )

    cfg.setdefault("EMAIL_SMTP_SERVER", "smtp.gmail.com")
    cfg.setdefault("EMAIL_SMTP_PORT", "587")

    return cfg


def send_email(subject: str, body: str):
    cfg = load_email_config()

    email_from = cfg["EMAIL_FROM"]
    email_to = cfg["EMAIL_TO"]
    smtp_server = cfg["EMAIL_SMTP_SERVER"]
    smtp_port = int(cfg["EMAIL_SMTP_PORT"])
    raw_pwd = str(cfg["EMAIL_PASSWORD"])
    email_password = "".join(raw_pwd.split())

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = Header(email_from, "utf-8")
    msg["To"] = Header(email_to, "utf-8")
    msg["Subject"] = Header(subject, "utf-8")

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(email_from, email_password)
        server.sendmail(email_from, [email_to], msg.as_string())
        print("学术日报邮件已发送至：", email_to)


def main():
    body, date_str = load_report()
    subject = f"学术期刊监控日报 - {date_str}"
    send_email(subject, body)


if __name__ == "__main__":
    main()
