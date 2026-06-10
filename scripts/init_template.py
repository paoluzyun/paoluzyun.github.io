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
PROMPT_VERSION = 2

HOME_PLACEHOLDERS = {
    "$brand",
    "$tagline",
    "$description",
    "$answer_summary",
    "$last_updated",
    "$notice",
    "$article_count",
    "$article_cards",
    "$friend_cards",
    "$trust_points",
    "$topic_cards",
    "$home_faq_html",
    "$hero_image",
    "$articles_url",
}
HOME_REQUIRED_PLACEHOLDERS = {
    "$brand",
    "$article_cards",
    "$home_faq_html",
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
ARTICLE_REQUIRED_PLACEHOLDERS = {
    "$article_title",
    "$article_body",
    "$faq_html",
    "$related_links",
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
    forbidden = ("<html", "<head", "<body", "<script", "<style", "<iframe", "<link")
    if any(fragment in lowered for fragment in forbidden):
        raise ValueError(f"{name} contains a forbidden executable or external element.")
    missing = sorted(required - {token for token in required if token in text})
    if missing:
        raise ValueError(f"{name} is missing placeholders: {', '.join(missing)}")
    if "<h1" not in lowered:
        raise ValueError(f"{name} must contain a semantic H1 heading.")


def lock_version() -> int:
    if not LOCK_FILE.exists():
        return 0
    try:
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    return int(lock.get("prompt_version", 0))


def generate() -> None:
    current_version = lock_version()
    if current_version >= PROMPT_VERSION:
        raise RuntimeError(
            f"Template v{current_version} is already locked. Regeneration is disabled."
        )
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is required.")

    config = read_config()
    prompt = f"""
为中文网站「{config['title']}」设计一套一次性静态页面模板。
网站定位：{config['description']}
内容方向：机场优惠码、折扣活动、套餐优惠和活动核验。

这是一次从不完整 v1 升级到最终 v2 的机会。你是这个项目的主设计师，
请独立决定视觉语言、版式、配色、字体层级、内容顺序和页面节奏。
返回严格 JSON，字段只有 home_template、article_template、theme_css。
v2 成功后永不自动重生成。

home_template 与 article_template 只负责 <main> 内部 HTML，不得包含 html、head、
body、script、style、link、iframe，不得引用外部字体或外部脚本。

首页必须使用这些原样占位符，它们是程序每天更新内容的接口：
{", ".join(sorted(HOME_REQUIRED_PLACEHOLDERS))}

首页还可以按你的设计自由选用这些占位符：
{", ".join(sorted(HOME_PLACEHOLDERS - HOME_REQUIRED_PLACEHOLDERS))}

文章页必须使用这些原样占位符，它们是程序每天更新内容的接口：
{", ".join(sorted(ARTICLE_REQUIRED_PLACEHOLDERS))}

文章页还可以按你的设计自由选用这些占位符：
{", ".join(sorted(ARTICLE_PLACEHOLDERS - ARTICLE_REQUIRED_PLACEHOLDERS))}

工作边界：
- 请做一套有明确审美判断、完成度高、适合「跑路云」品牌的原创设计，不要只给简单骨架。
- 不规定区块数量、排列顺序、Hero 形式、颜色或卡片样式；这些全部由你决定。
- 首页需让读者容易发现最新文章，并自然呈现程序提供的 FAQ 内容。
- 文章页需让正文、FAQ 和相关文章清晰可读。
- 每个模板使用一个语义明确的 h1，合理使用 section、article、nav、aside 等标签。
- theme_css 必须完整覆盖你创建的类，并包含适配手机的 @media 规则。
- SEO head、canonical、Open Graph 和 JSON-LD 由外层程序生成，不要在模板中重复。
- 所有交互只使用普通链接和 details/summary，不需要 JavaScript。
- 页面中不得出现“由 AI 生成”“SEO”“GEO”“模板”“占位符”等实现说明。
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
        "temperature": 0.85,
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
    validate_template("home_template", home, HOME_REQUIRED_PLACEHOLDERS)
    validate_template("article_template", article, ARTICLE_REQUIRED_PLACEHOLDERS)
    if not css or "{" not in css or "}" not in css:
        raise ValueError("theme_css is empty or invalid.")
    if "@media" not in css.lower():
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
                "prompt_version": PROMPT_VERSION,
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
