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
PROMPT_VERSION = 4

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
    "$notice",
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
外层 Python 只提供真实内容接口，不提供版式方案。theme_css 必须把这些
程序生成的结构纳入同一套完整视觉系统：
- body
- header.site-header > .container.nav-wrap > a.brand + nav > a
- footer.site-footer > .container.footer-grid
- 首页文章流：article.post-card > .post-meta + h2 > a + p + a.text-link
- 首页 FAQ：details.faq-item > summary + p
- 主题入口：a.topic-card > h3 + p
- 友情链接：a.friend-card > strong + span + small
- 文章相关文章：a.side-link > span + small
- 文章列表页：.page-header、.breadcrumb、.section、.post-list、.post-card
- Markdown 正文可能包含 h2、h3、p、ul、ol、blockquote、table、a、strong、code、pre、img

占位符会被替换成真实 HTML，包括文章路径链接。请直接围绕这些接口做设计，
不要把页面做成占位符外面套几个普通卡片。
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
    if "<button" in lowered:
        raise ValueError(
            f"{name} contains a button, but this static theme has no button actions."
        )
    unsupported_claims = ("核验通过 日期戳", "点击弹出", "轮播")
    if any(claim in text for claim in unsupported_claims):
        raise ValueError(
            f"{name} describes an interaction or verification state not provided by the program."
        )


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


def design_brief_prompt(config: dict) -> str:
    return f"""
请担任中文内容网站「{config['title']}」的品牌创意总监，先制定完整视觉与内容方案，不写 HTML 或 CSS。

网站定位：{config['description']}
内容方向：机场优惠码、折扣活动、套餐优惠、使用说明和活动核验。
可使用的主视觉图片：{config.get('hero_image', '')}

你拥有完整创意决定权。请把它当成一个可以直接上线的官网/内容品牌来规划，而不是普通博客模板：
- 首页要有官网感：清晰首屏、价值主张、最新文章入口、主题导航、核验流程、用户关心的问题、风险提醒、友情链接区域。
- 文章页要像专业内容详情页：标题区、元信息、主图、正文阅读体验、重点提示、标签、相关文章、FAQ、返回入口。
- 设计需要成熟、可信、有辨识度，不能只是大标题加几张卡片。
- 可以自由决定版式、配色、区块顺序、视觉节奏和组件语言。
- 避免默认 AI 落地页风格、单一紫蓝渐变、三段式骨架、空洞装饰和模板感。

只返回严格 JSON：
{{
  "design_brief": {{
    "concept_name": "方案名称",
    "theme_color": "#用于浏览器主题栏的代表色",
    "brand_story": "视觉叙事",
    "visual_direction": "整体视觉方向",
    "palette": ["颜色及用途"],
    "typography": "字体层级和排版策略",
    "homepage_composition": "首页区块、构图、浏览节奏和官网感来源",
    "article_experience": "文章页阅读体验和信息层级",
    "component_language": "导航、卡片、链接、FAQ、正文、表格等组件语言",
    "responsive_strategy": "移动端策略",
    "signature_details": ["让网站有辨识度的细节"],
    "avoid": ["本方案要避免的俗套"]
  }}
}}
"""


def implementation_prompt(config: dict, design_brief: dict) -> str:
    return f"""
请担任资深前端设计师，把下面创意方案完整实现为一次性静态网站主题。

网站：{config['title']}
定位：{config['description']}
创意方案：
{json.dumps(design_brief, ensure_ascii=False, indent=2)}

核心原则：
- Python 程序只给你真实动态内容接口，包括文章路径链接；其它首页内容、文章页结构、官网式板块、视觉文案和设计细节由你补充完整。
- 你不能把页面做成死板博客列表。首页必须像官网一样完整，至少包含首屏、信任/核验说明、内容主题入口、最新文章区、流程/方法、FAQ、提醒或友情链接等区域。
- 文章页必须像成熟内容详情页，包含标题区、元信息、主图、正文阅读区、重点提示/目录感区块、标签、相关文章、FAQ、返回入口等。
- 所有模板只负责 <main> 内部内容，不要输出 main、html、head、body、style、link、script 或 iframe。
- SEO head、canonical、Open Graph、JSON-LD、导航和页脚由外层 Python 稳定生成。

首页必须原样使用这些占位符，它们是程序每天更新内容和文章路径的接口：
{", ".join(sorted(HOME_REQUIRED_PLACEHOLDERS))}

首页可以按你的设计自由使用这些占位符：
{", ".join(sorted(HOME_PLACEHOLDERS - HOME_REQUIRED_PLACEHOLDERS))}

文章页必须原样使用这些占位符，它们是程序每天更新正文、FAQ、相关文章和文章路径的接口：
{", ".join(sorted(ARTICLE_REQUIRED_PLACEHOLDERS))}

文章页可以按你的设计自由使用这些占位符：
{", ".join(sorted(ARTICLE_PLACEHOLDERS - ARTICLE_REQUIRED_PLACEHOLDERS))}

程序生成组件结构：
{COMPONENT_CONTRACT}

实现标准：
- 由你决定区块数量、顺序、Hero 形式、配色、边框、阴影、卡片、背景层次和排版。
- CSS 要形成完整设计系统，包含变量、基础排版、链接状态、卡片状态、Markdown 正文、表格、移动端 @media。
- 每个模板使用一个语义明确的 h1，并合理使用 section、article、nav、aside。
- 所有交互只使用普通链接和 details/summary；不要输出 button、轮播、弹窗或需要 JavaScript 才能工作的控件。
- 不要擅自显示“核验通过”等程序没有提供的状态；只能展示程序提供的日期、提醒和文章内容。
- 页面文案不要出现“由 AI 生成”“SEO”“GEO”“模板”“占位符”等实现说明。
- 不生成任何虚假优惠码、价格、用户数量或性能承诺。

只返回严格 JSON：
{{
  "home_template": "<main 内部的完整首页 HTML>",
  "article_template": "<main 内部的完整文章页 HTML>",
  "theme_css": "覆盖模板与程序组件的完整 CSS"
}}
"""


def review_prompt(design_brief: dict, home: str, article: str, css: str) -> str:
    return f"""
请担任严格的网页设计总监，复审下面这套网站主题。

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

请主动修正任何“像骨架、像默认模板、官网感不足、区块不完整、视觉单薄、层级不清、留白粗糙、组件未设计、文章阅读体验不足、移动端处理敷衍”的问题。
保留必要占位符，不要缩减完成度。你可以重构 HTML 和 CSS，只要继续忠于创意方案并保持纯静态实现。
不要输出无功能按钮、轮播、弹窗，也不要显示程序没有提供的核验状态。

只返回严格 JSON：
{{
  "home_template": "复审后的完整首页 HTML",
  "article_template": "复审后的完整文章页 HTML",
  "theme_css": "复审后的完整 CSS"
}}
"""


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
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
    brief_result = request_design(
        key,
        model,
        design_brief_prompt(config),
        system="你是有独立审美判断的品牌创意总监，只输出可解析 JSON。",
        temperature=1.0,
        max_tokens=5000,
    )
    design_brief = brief_result.get("design_brief", brief_result)
    if not isinstance(design_brief, dict) or not design_brief:
        raise ValueError("DeepSeek did not return a usable design brief.")

    base_prompt = implementation_prompt(config, design_brief)
    validation_error = ""
    for attempt in range(1, 4):
        attempt_prompt = base_prompt
        if validation_error:
            attempt_prompt += (
                "\n\n上次实现未通过接口完整性检查："
                f"{validation_error}\n"
                "保留官网感、完整板块和设计完成度，只修正缺失接口或未覆盖组件，并重新输出完整 JSON。"
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

    try:
        reviewed = request_design(
            key,
            model,
            review_prompt(design_brief, home, article, css),
            system="你是要求很高的数字产品设计总监，只输出复审完成后的可解析 JSON。",
            temperature=0.65,
            max_tokens=14000,
        )
        reviewed_home = str(reviewed.get("home_template", "")).strip()
        reviewed_article = str(reviewed.get("article_template", "")).strip()
        reviewed_css = str(reviewed.get("theme_css", "")).strip()
        validate_template("home_template", reviewed_home, HOME_REQUIRED_PLACEHOLDERS)
        validate_template("article_template", reviewed_article, ARTICLE_REQUIRED_PLACEHOLDERS)
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
