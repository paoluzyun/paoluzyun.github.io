from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SITE_FILE = ROOT / "content" / "site.yml"
TEMPLATE_DIR = ROOT / "templates"
HOME_TEMPLATE = TEMPLATE_DIR / "home.html"
ARTICLE_TEMPLATE = TEMPLATE_DIR / "article.html"
LOCK_FILE = TEMPLATE_DIR / "template.lock.json"
STYLE_FILE = ROOT / "assets" / "css" / "style.css"

HOME_PLACEHOLDERS = {
    "$brand",
    "$description",
    "$last_updated",
    "$notice",
    "$article_count",
    "$article_cards",
    "$friend_cards",
    "$hero_image",
    "$articles_url",
}
ARTICLE_PLACEHOLDERS = {
    "$article_title",
    "$article_description",
    "$category",
    "$date",
    "$author",
    "$article_body",
    "$article_image",
    "$article_image_alt",
    "$article_image_caption",
    "$related_links",
    "$tag_html",
    "$faq_html",
    "$home_url",
    "$articles_url",
}


def read_config() -> dict:
    with SITE_FILE.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def clean_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def validate_template(name: str, text: str, required: set[str]) -> None:
    lowered = text.lower()
    if "<script" in lowered or "<iframe" in lowered or "<link" in lowered:
        raise ValueError(f"{name} contains a forbidden executable or external element.")
    missing = sorted(required - {token for token in required if token in text})
    if missing:
        raise ValueError(f"{name} is missing placeholders: {', '.join(missing)}")


def generate() -> None:
    if LOCK_FILE.exists():
        raise RuntimeError(
            "Template lock already exists. The one-time AI template cannot run again."
        )
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is required.")

    config = read_config()
    prompt = f"""
为中文网站「{config['title']}」设计一套一次性静态页面模板。
网站定位：{config['description']}
内容方向：机场优惠码、折扣活动、套餐优惠和活动核验。

返回严格 JSON，字段只有 home_template、article_template、theme_css。

home_template 与 article_template 只负责 <main> 内部 HTML，不得包含 html、head、
body、script、style、link、iframe，不得引用外部字体或外部脚本。

首页必须使用这些原样占位符：
{", ".join(sorted(HOME_PLACEHOLDERS))}

文章页必须使用这些原样占位符：
{", ".join(sorted(ARTICLE_PLACEHOLDERS))}

设计要求：
- 安静、可信、信息密度适中，适合 SEO 和 AI 搜索摘要抓取。
- 首页第一屏突出品牌、定位、更新时间和最新优惠文章，使用 $hero_image。
- 文章页强调标题、摘要、发布日期、正文、FAQ、相关内容和信息核验声明。
- 使用语义化 section、article、aside、h1-h3，移动端优先。
- 不要营销落地页式夸张大字，不要紫色渐变、装饰光球或卡片套卡片。
- 卡片圆角不超过 8px，文字不可溢出。
- 配色需要同时包含青绿色、珊瑚红、白色、炭黑和少量黄色点缀。
- theme_css 必须完整覆盖模板中的类，响应式，字距为 0。
- 不生成任何虚假优惠码、价格、用户数量或性能承诺。
"""
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是资深前端设计师，只输出可解析 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.65,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API error {error.code}: {detail}") from error

    generated = clean_json(result["choices"][0]["message"]["content"])
    home = str(generated.get("home_template", "")).strip()
    article = str(generated.get("article_template", "")).strip()
    css = str(generated.get("theme_css", "")).strip()
    validate_template("home_template", home, HOME_PLACEHOLDERS)
    validate_template("article_template", article, ARTICLE_PLACEHOLDERS)
    if len(css) < 2000:
        raise ValueError("theme_css is too short to be a complete responsive theme.")
    if "@media" not in css:
        raise ValueError("theme_css must include responsive media rules.")

    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOME_TEMPLATE.write_text(home + "\n", encoding="utf-8")
    ARTICLE_TEMPLATE.write_text(article + "\n", encoding="utf-8")
    STYLE_FILE.write_text(css + "\n", encoding="utf-8")
    LOCK_FILE.write_text(
        json.dumps(
            {
                "brand": config["title"],
                "model": model,
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "regeneration": "disabled",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("One-time DeepSeek templates generated and locked.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the site template once.")
    parser.parse_args()
    generate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
