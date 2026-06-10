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
BRIEF_FILE = TEMPLATE_DIR / "design-brief.json"
STYLE_FILE = ROOT / "assets" / "css" / "style.css"
PROMPT_VERSION = 3

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
CSS_REQUIRED_MARKERS = {
    "body",
    ".container",
    ".site-header",
    ".nav-wrap",
    ".brand",
    ".site-footer",
    ".footer-grid",
    ".post-card",
    ".post-meta",
    ".text-link",
    ".faq-item",
    ".side-link",
    ".page-header",
    ".post-list",
}

COMPONENT_CONTRACT = """
外层程序会生成以下固定结构，theme_css 必须把它们纳入同一视觉系统：
- body
- header.site-header > .container.nav-wrap > a.brand + nav > a
- footer.site-footer > .container.footer-grid
- 首页文章：article.post-card > .post-meta + h2 > a + p + a.text-link
- 首页 FAQ：details.faq-item > summary + p
- 主题入口：a.topic-card > h3 + p
- 友情链接：a.friend-card > strong + span + small
- 文章相关推荐：a.side-link > span + small
- 文章列表页：.page-header、.breadcrumb、.section、.post-list、.post-card
- Markdown 正文可能包含 h2、h3、p、ul、ol、blockquote、table、a、strong、code、pre、img

占位符会被替换成上述真实 HTML。请直接为这些类和正文元素设计样式，不要只装饰占位符外层。
"""


def read_config() -> dict:
    with SITE_FILE.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def write_config(config: dict) -> None:
    with SITE_FILE.open("w", encoding="utf-8") as file:
        yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)


def clean_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def validate_template(name: str, text: str, required: set[str]) -> None:
    lowered = text.lower()
    forbidden = (
        "<html",
        "<head",
        "<body",
        "<main",
        "<script",
        "<style",
        "<link",
        "<iframe",
    )
    if any(fragment in lowered for fragment in forbidden):
        raise ValueError(f"{name} contains a forbidden executable or external element.")
    missing = sorted(required - {token for token in required if token in text})
    if missing:
        raise ValueError(f"{name} is missing placeholders: {', '.join(missing)}")
    if "<h1" not in lowered:
        raise ValueError(f"{name} must contain a semantic H1 heading.")


def validate_css(css: str) -> None:
    lowered = css.lower()
    if not css or "{" not in css or "}" not in css:
        raise ValueError("theme_css is empty or invalid.")
    if "@media" not in lowered:
        raise ValueError("theme_css must include responsive media rules.")
    missing = sorted(marker for marker in CSS_REQUIRED_MARKERS if marker not in lowered)
    if missing:
        raise ValueError(
            "theme_css does not style program-generated components: "
            + ", ".join(missing)
        )


def lock_version() -> int:
    if not LOCK_FILE.exists():
        return 0
    try:
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    return int(lock.get("prompt_version", 0))


def request_design(
    key: str,
    model: str,
    prompt: str,
    *,
    system: str,
    temperature: float,
    max_tokens: int,
) -> dict:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system,
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
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
    choice = result["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError("DeepSeek output was truncated. Increase max_tokens.")
    content = choice.get("message", {}).get("content") or ""
    if not content.strip():
        raise RuntimeError("DeepSeek returned an empty JSON response.")
    return clean_json(content)


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
    brief_prompt = f"""
请担任中文内容网站「{config['title']}」的创意总监，先完成视觉设计方案，不写 HTML 或 CSS。
网站定位：{config['description']}
内容方向：机场优惠码、折扣活动、套餐优惠和活动核验。
可使用的主视觉图片：{config.get('hero_image', '')}

你拥有完整创意决定权。请从品牌语义、读者需求和内容属性出发，提出一套有辨识度、
可信、成熟、适合长期发布文章的原创视觉方案。不要套用常见 AI 落地页，不要为了省事
默认使用紫蓝渐变、三段式骨架或只有大标题加卡片的布局。

以严格 JSON 返回，格式为：
{{
    "design_brief": {{
    "concept_name": "方案名称",
    "theme_color": "#用于浏览器主题栏的代表色",
    "brand_story": "视觉叙事",
    "visual_direction": "整体视觉方向",
    "palette": ["颜色及用途"],
    "typography": "字体层级和排版策略",
    "homepage_composition": "首页构图与浏览节奏",
    "article_experience": "文章页阅读体验",
    "component_language": "导航、卡片、按钮、FAQ 等组件语言",
    "responsive_strategy": "移动端策略",
    "signature_details": ["使网站有辨识度的细节"],
    "avoid": ["本方案要避免的俗套"]
  }}
}}
"""
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
    brief_result = request_design(
        key,
        model,
        brief_prompt,
        system="你是有独立审美判断的品牌创意总监，只输出可解析 JSON。",
        temperature=1.0,
        max_tokens=5000,
    )
    design_brief = brief_result.get("design_brief", brief_result)
    if not isinstance(design_brief, dict) or not design_brief:
        raise ValueError("DeepSeek did not return a usable design brief.")

    implementation_prompt = f"""
请担任资深前端设计师，将以下创意总监方案完整实现为一次性静态网站主题。

网站：{config['title']}
定位：{config['description']}
创意方案：
{json.dumps(design_brief, ensure_ascii=False, indent=2)}

你仍可对实现细节作出专业判断，但不能把方案简化为骨架。首页和文章页必须像真正完成、
可以直接上线的内容网站，而不是 wireframe、组件示例或默认模板。

home_template 与 article_template 只负责外层 <main> 里面的内容，不要再次输出 main，
也不要包含 html、head、body、style、link、script 或 iframe。
SEO head、canonical、Open Graph 和 JSON-LD 由外层程序生成。

首页必须使用这些原样占位符，它们是程序每天更新内容的接口：
{", ".join(sorted(HOME_REQUIRED_PLACEHOLDERS))}

首页还可以按你的设计自由选用这些占位符：
{", ".join(sorted(HOME_PLACEHOLDERS - HOME_REQUIRED_PLACEHOLDERS))}

文章页必须使用这些原样占位符，它们是程序每天更新内容的接口：
{", ".join(sorted(ARTICLE_REQUIRED_PLACEHOLDERS))}

文章页还可以按你的设计自由选用这些占位符：
{", ".join(sorted(ARTICLE_PLACEHOLDERS - ARTICLE_REQUIRED_PLACEHOLDERS))}

程序组件结构：
{COMPONENT_CONTRACT}

实现标准：
- 由你决定区块数量、顺序、Hero 形式、配色、边框、阴影、卡片和排版，不接受固定美术指令。
- 视觉层级、留白、背景、导航、文章卡片、按钮、FAQ、文章正文、列表页和页脚都要经过设计。
- CSS 要形成完整设计系统，包含变量、基础排版、交互状态和手机端 @media 规则。
- 每个模板使用一个语义明确的 h1，合理使用 section、article、nav、aside 等标签。
- 所有交互只使用普通链接和 details/summary，不需要 JavaScript。
- 页面中不得出现“由 AI 生成”“SEO”“GEO”“模板”“占位符”等实现说明。
- 不生成任何虚假优惠码、价格、用户数量或性能承诺。

只返回严格 JSON，格式为：
{{
  "home_template": "<main> 内部的完整首页 HTML",
  "article_template": "<main> 内部的完整文章页 HTML",
  "theme_css": "覆盖模板与程序组件的完整 CSS"
}}
"""
    validation_error = ""
    for attempt in range(1, 4):
        attempt_prompt = implementation_prompt
        if validation_error:
            attempt_prompt += (
                "\n\n上次实现未通过接口完整性检查："
                f"{validation_error}\n"
                "保留创意方案和设计完成度，只修正缺失接口或未覆盖组件，并重新输出完整 JSON。"
            )
        generated = request_design(
            key,
            model,
            attempt_prompt,
            system="你是兼具审美和工程能力的资深前端设计师，只输出可解析 JSON。",
            temperature=0.8,
            max_tokens=12000,
        )
        home = str(generated.get("home_template", "")).strip()
        article = str(generated.get("article_template", "")).strip()
        css = str(generated.get("theme_css", "")).strip()
        try:
            validate_template("home_template", home, HOME_REQUIRED_PLACEHOLDERS)
            validate_template("article_template", article, ARTICLE_REQUIRED_PLACEHOLDERS)
            validate_css(css)
        except ValueError as error:
            validation_error = str(error)
            if attempt == 3:
                raise
            continue
        break

    review_prompt = f"""
请担任严格的网页设计总监，复审下面这套由设计师完成的网站主题。

原始创意方案：
{json.dumps(design_brief, ensure_ascii=False, indent=2)}

当前首页模板：
{home}

当前文章页模板：
{article}

当前 CSS：
{css}

程序组件结构：
{COMPONENT_CONTRACT}

请主动修正任何“像骨架、像默认模板、视觉单薄、层级不清、留白粗糙、组件未设计、
文章阅读体验不足、移动端处理敷衍”的问题。保留必要占位符，不要缩减现有完成度。
你可以重构 HTML 和 CSS，只要继续忠于创意方案并保持纯静态实现。

只返回严格 JSON：
{{
  "home_template": "复审后的完整首页 HTML",
  "article_template": "复审后的完整文章页 HTML",
  "theme_css": "复审后的完整 CSS"
}}
"""
    try:
        reviewed = request_design(
            key,
            model,
            review_prompt,
            system="你是要求很高的数字产品设计总监，只输出复审完成后的可解析 JSON。",
            temperature=0.65,
            max_tokens=14000,
        )
        reviewed_home = str(reviewed.get("home_template", "")).strip()
        reviewed_article = str(reviewed.get("article_template", "")).strip()
        reviewed_css = str(reviewed.get("theme_css", "")).strip()
        validate_template(
            "home_template", reviewed_home, HOME_REQUIRED_PLACEHOLDERS
        )
        validate_template(
            "article_template", reviewed_article, ARTICLE_REQUIRED_PLACEHOLDERS
        )
        validate_css(reviewed_css)
        home, article, css = reviewed_home, reviewed_article, reviewed_css
    except (KeyError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Design review was skipped; using the validated implementation: {error}")

    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    theme_color = str(design_brief.get("theme_color", "")).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", theme_color):
        config["theme_color"] = theme_color
        write_config(config)
    BRIEF_FILE.write_text(
        json.dumps(design_brief, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    HOME_TEMPLATE.write_text(home + "\n", encoding="utf-8")
    ARTICLE_TEMPLATE.write_text(article + "\n", encoding="utf-8")
    STYLE_FILE.write_text(css + "\n", encoding="utf-8")
    LOCK_FILE.write_text(
        json.dumps(
            {
                "brand": config["title"],
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "concept_name": design_brief.get("concept_name", ""),
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
