from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from string import Template

import markdown
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
ARTICLE_DIR = CONTENT_DIR / "articles"
LOCAL_DIR = ROOT / "local"
SITE_FILE = CONTENT_DIR / "site.yml"
DEFAULT_KEYWORDS = LOCAL_DIR / "keywords.txt"
LOCAL_DEEPSEEK_KEY = LOCAL_DIR / "deepseek.key"
LOCAL_INDEXNOW_KEY = LOCAL_DIR / "indexnow.key"
TEMPLATE_DIR = ROOT / "templates"
HOME_TEMPLATE = TEMPLATE_DIR / "home.html"
ARTICLE_TEMPLATE = TEMPLATE_DIR / "article.html"
TEMPLATE_LOCK = TEMPLATE_DIR / "template.lock.json"


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def write_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def site_url(config: dict, override: str | None = None) -> str:
    value = override or os.getenv("SITE_URL") or config.get("site_url") or "https://paoluzyun.github.io"
    return str(value).strip().rstrip("/")


def base_path_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.rstrip("/")
    return "" if path in ("", "/") else path


def site_path(config: dict, path: str) -> str:
    value = str(path or "")
    if not value or value.startswith(("#", "http://", "https://", "mailto:", "tel:")):
        return value
    if not value.startswith("/"):
        value = f"/{value}"
    prefix = config.get("_base_path", "")
    if value == "/":
        return f"{prefix}/" if prefix else "/"
    return f"{prefix}{value}"


def deepseek_key() -> str | None:
    if os.getenv("DEEPSEEK_API_KEY"):
        return os.getenv("DEEPSEEK_API_KEY", "").strip()
    if LOCAL_DEEPSEEK_KEY.exists():
        return LOCAL_DEEPSEEK_KEY.read_text(encoding="utf-8").strip()
    return None


def indexnow_key() -> str | None:
    if os.getenv("INDEXNOW_KEY"):
        return os.getenv("INDEXNOW_KEY", "").strip()
    if LOCAL_INDEXNOW_KEY.exists():
        return LOCAL_INDEXNOW_KEY.read_text(encoding="utf-8").strip()
    return None


def slugify(text: str) -> str:
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    if ascii_text:
        return ascii_text[:80]
    return "post-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def markdown_html(text: str) -> str:
    return markdown.markdown(text or "", extensions=["extra", "tables", "sane_lists"])


def article_url(article: dict) -> str:
    return f"/articles/{article['slug']}.html"


def article_path(article: dict) -> Path:
    return ROOT / "articles" / f"{article['slug']}.html"


def template_body(path: Path, values: dict[str, object]) -> str:
    if not TEMPLATE_LOCK.exists() or not path.exists():
        raise RuntimeError(
            "Site templates are not initialized. Run the "
            "'Initialize DeepSeek Template' workflow once."
        )
    rendered = Template(path.read_text(encoding="utf-8")).safe_substitute(
        {key: str(value or "") for key, value in values.items()}
    )
    unresolved = sorted(set(re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*", rendered)))
    if unresolved:
        raise ValueError(f"Unresolved template placeholders: {', '.join(unresolved)}")
    return rendered


def load_articles() -> list[dict]:
    articles = []
    for path in ARTICLE_DIR.glob("*.json"):
        item = read_json(path)
        item["_source"] = path.name
        articles.append(item)
    articles.sort(key=lambda item: (item.get("date", ""), item.get("title", "")), reverse=True)
    return articles


def layout(
    config: dict,
    title: str,
    description: str,
    body: str,
    canonical: str,
    keywords: str = "",
    structured_data: list[dict] | None = None,
) -> str:
    nav = "".join(
        f'<a href="{esc(site_path(config, item["url"]))}">{esc(item["name"])}</a>'
        for item in config.get("nav", [])
    )
    full_title = title if title == config["title"] else f"{title} | {config['title']}"
    asset_version = urllib.parse.quote(str(config.get("_asset_version", "")))
    schemas = "".join(
        f'<script type="application/ld+json">{json.dumps(item, ensure_ascii=False)}</script>'
        for item in (structured_data or [])
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(full_title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="keywords" content="{esc(keywords or config.get("keywords", ""))}">
  <meta name="author" content="{esc(config.get("author"))}">
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:locale" content="zh_CN">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{esc(full_title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{esc(config.get("_base_url", site_url(config)) + config.get("default_image", ""))}">
  <link rel="stylesheet" href="{esc(site_path(config, "/assets/css/style.css"))}?v={asset_version}">
  <link rel="alternate" type="application/rss+xml" title="{esc(config['title'])}" href="{esc(site_path(config, "/feed.xml"))}">
  {schemas}
</head>
<body>
  <header class="site-header">
    <div class="container nav-wrap">
      <a class="brand" href="{esc(site_path(config, "/"))}"><span>跑</span>{esc(config['title'])}</a>
      <nav>{nav}</nav>
    </div>
  </header>
  <main>{body}</main>
  <footer class="site-footer">
    <div class="container footer-grid">
      <div><strong>{esc(config['title'])}</strong><p>{esc(config['description'])}</p></div>
      <div><a href="{esc(site_path(config, "/articles/"))}">文章列表</a><a href="{esc(site_path(config, "/sitemap.xml"))}">站点地图</a><a href="{esc(site_path(config, "/feed.xml"))}">RSS</a></div>
    </div>
  </footer>
  <script src="{esc(site_path(config, "/assets/js/main.js"))}?v={asset_version}"></script>
</body>
</html>
"""


def render_home(config: dict, articles: list[dict], base_url: str) -> None:
    latest = articles[:10]
    article_cards = "".join(
        f"""<article class="post-card">
          <div class="post-meta"><time datetime="{esc(item.get("date"))}">{esc(item.get("date"))}</time><span>{esc(item.get("category"))}</span></div>
          <h2><a href="{esc(site_path(config, article_url(item)))}">{esc(item.get("title"))}</a></h2>
          <p>{esc(item.get("description"))}</p>
          <a class="text-link" href="{esc(site_path(config, article_url(item)))}">查看优惠信息</a>
        </article>"""
        for item in latest
    )
    friends = "".join(
        f"""<a class="friend-card" href="{esc(item.get("url"))}" rel="nofollow noopener" target="_blank">
          <strong>{esc(item.get("name"))}</strong>
          <span>{esc(item.get("desc"))}</span>
          <small>核验：{esc(item.get("last_checked"))}</small>
        </a>"""
        for item in config.get("friends", [])
    )
    if not friends:
        friends = '<p class="empty-state">友情链接位置已预留，确认合作站点后再公开展示。</p>'
    body = template_body(
        HOME_TEMPLATE,
        {
            "brand": esc(config["title"]),
            "description": esc(config["description"]),
            "last_updated": esc(config.get("last_updated")),
            "notice": esc(config.get("notice")),
            "article_count": len(articles),
            "article_cards": article_cards,
            "friend_cards": friends,
            "hero_image": esc(site_path(config, config.get("hero_image"))),
            "articles_url": esc(site_path(config, "/articles/")),
        },
    )
    schemas = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": config["title"],
            "url": f"{base_url}/",
            "description": config["description"],
            "inLanguage": "zh-CN",
        },
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": config["title"],
            "url": f"{base_url}/",
            "logo": base_url + config.get("default_image", ""),
        },
    ]
    (ROOT / "index.html").write_text(
        layout(
            config,
            config["title"],
            config["description"],
            body,
            f"{base_url}/",
            config.get("keywords", ""),
            schemas,
        ),
        encoding="utf-8",
    )


def render_article(config: dict, article: dict, articles: list[dict], base_url: str) -> None:
    related = "".join(
        f'<a class="side-link" href="{esc(site_path(config, article_url(item)))}"><span>{esc(item["title"][:28])}</span><small>{esc(item.get("date"))}</small></a>'
        for item in [
            candidate
            for candidate in articles
            if candidate.get("slug") != article.get("slug")
        ][:6]
    )
    tag_html = "".join(f"<span>{esc(tag)}</span>" for tag in article.get("tags", []))
    body_html = markdown_html(article.get("body_markdown", ""))
    image = article.get("image") or config.get("default_image", "/assets/img/hero.png")
    faq_items = [
        item
        for item in article.get("faq", [])
        if isinstance(item, dict) and item.get("question") and item.get("answer")
    ]
    faq_html = "".join(
        f"<details><summary>{esc(item['question'])}</summary><p>{esc(item['answer'])}</p></details>"
        for item in faq_items
    )
    body = template_body(
        ARTICLE_TEMPLATE,
        {
            "article_title": esc(article["title"]),
            "article_description": esc(article.get("description")),
            "category": esc(article.get("category")),
            "date": esc(article.get("date")),
            "author": esc(config.get("author")),
            "article_body": body_html,
            "article_image": esc(site_path(config, image)),
            "article_image_alt": esc(article.get("image_alt", article["title"])),
            "article_image_caption": esc(article.get("image_caption", "")),
            "related_links": related,
            "tag_html": tag_html,
            "faq_html": faq_html,
            "home_url": esc(site_path(config, "/")),
            "articles_url": esc(site_path(config, "/articles/")),
        },
    )
    article_schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article["title"],
        "description": article.get("description", ""),
        "datePublished": article.get("date"),
        "dateModified": article.get("date"),
        "author": {"@type": "Organization", "name": config.get("author")},
        "publisher": {"@type": "Organization", "name": config["title"]},
        "mainEntityOfPage": f"{base_url}{article_url(article)}",
        "image": base_url + image,
        "inLanguage": "zh-CN",
    }
    schemas = [article_schema]
    if faq_items:
        schemas.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["answer"],
                        },
                    }
                    for item in faq_items
                ],
            }
        )
    path = article_path(article)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        layout(
            config,
            article["title"],
            article.get("description", article["title"]),
            body,
            f"{base_url}{article_url(article)}",
            article.get("keywords", ""),
            schemas,
        ),
        encoding="utf-8",
    )


def render_articles_index(config: dict, articles: list[dict], base_url: str) -> None:
    cards = "".join(
        f"""<article class="post-card">
          <div class="post-meta">{esc(item.get("date"))} · {esc(item.get("category"))}</div>
          <h2><a href="{esc(site_path(config, article_url(item)))}">{esc(item.get("title"))}</a></h2>
          <p>{esc(item.get("description"))}</p>
        </article>"""
        for item in articles
    )
    body = f"""<section class="page-header"><div class="container"><a class="breadcrumb" href="{esc(site_path(config, "/"))}">首页</a><h1>机场优惠码文章</h1><p>{esc(config["title"])}整理的机场优惠码、折扣活动与核验说明。</p></div></section>
<section class="section"><div class="container"><div class="post-list">{cards}</div></div></section>"""
    path = ROOT / "articles" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(layout(config, "文章列表", config["description"], body, f"{base_url}/articles/"), encoding="utf-8")


def update_site_dates(config: dict) -> dict:
    today = dt.date.today().strftime("%Y-%m-%d")
    config["last_updated"] = today
    for friend in config.get("friends", []):
        friend["last_checked"] = today
    write_yaml(SITE_FILE, config)
    return config


def build(args: argparse.Namespace) -> None:
    config = update_site_dates(read_yaml(SITE_FILE))
    base_url = site_url(config, args.site_url)
    config["_base_path"] = base_path_from_url(base_url)
    config["_base_url"] = base_url
    config["_asset_version"] = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    articles = load_articles()
    for article in articles:
        render_article(config, article, articles, base_url)
    render_articles_index(config, articles, base_url)
    render_home(config, articles, base_url)
    render_sitemap(config, articles, base_url)
    render_feed(config, articles, base_url)
    render_robots(config, base_url)
    write_indexnow_key()
    print(f"Built {len(articles)} articles.")


def render_sitemap(config: dict, articles: list[dict], base_url: str) -> None:
    today = dt.date.today().strftime("%Y-%m-%d")
    urls = [("/", today), ("/articles/", today)]
    urls.extend((article_url(item), item.get("date", today)) for item in articles)
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod in urls:
        body.append(f"<url><loc>{esc(base_url + loc)}</loc><lastmod>{esc(lastmod)}</lastmod></url>")
    body.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(body), encoding="utf-8")


def render_feed(config: dict, articles: list[dict], base_url: str) -> None:
    items = []
    for article in articles[:20]:
        pub = email.utils.format_datetime(dt.datetime.fromisoformat(article.get("date") + "T08:00:00+08:00"))
        items.append(
            f"""<item><title>{esc(article['title'])}</title><link>{esc(base_url + article_url(article))}</link><guid>{esc(base_url + article_url(article))}</guid><pubDate>{esc(pub)}</pubDate><description>{esc(article.get('description', ''))}</description></item>"""
        )
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{esc(config['title'])}</title><link>{esc(base_url)}/</link><description>{esc(config['description'])}</description>{''.join(items)}</channel></rss>"""
    (ROOT / "feed.xml").write_text(feed, encoding="utf-8")


def render_robots(config: dict, base_url: str) -> None:
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n", encoding="utf-8")


def clean_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def fallback_article(keyword: str, config: dict) -> dict:
    today = dt.date.today().strftime("%Y-%m-%d")
    return {
        "title": f"{keyword}：最新活动、使用方法与核验说明",
        "slug": slugify(keyword),
        "date": today,
        "category": "机场优惠码",
        "tags": ["机场优惠码", "机场折扣", "优惠核验"],
        "keywords": f"{keyword},{keyword}最新活动,{keyword}使用方法",
        "description": f"整理{keyword}的公开活动信息、使用步骤、适用范围和核验注意事项。",
        "image": config.get("default_image", "/assets/img/hero.png"),
        "image_alt": f"{keyword}优惠信息整理",
        "image_caption": f"{keyword}公开优惠信息，核验日期：{today}",
        "body_markdown": f"""## 直接结论

本文没有确认到可公开验证的固定优惠码时，不会编造代码。请以服务商结算页显示的活动为准。

## 优惠信息概览

本文围绕 **{keyword}** 整理公开活动、适用套餐、使用入口和有效期核验方法。

| 项目 | 内容 |
| --- | --- |
| 关键词 | {keyword} |
| 信息类型 | 优惠码 / 折扣活动 / 使用说明 |
| 核验日期 | {today} |

## 如何使用

进入服务商公开官网，在结算页面查找“优惠码”“兑换码”或“活动”输入框。提交前确认价格确实发生变化。

## 注意事项

- 优惠码可能限定新用户、套餐或支付方式。
- 无法验证的代码不会标记为有效。
- 活动规则以服务商官网和结算页面为准。
""",
        "faq": [
            {
                "question": f"{keyword}一定有效吗？",
                "answer": "不一定。优惠活动可能随时结束，应以结算页面实际减免结果为准。",
            },
            {
                "question": "没有优惠码输入框怎么办？",
                "answer": "部分活动会自动减价，或仅在指定套餐页面展示，不应在非官方页面输入账号信息。",
            },
        ],
    }


def generate_deepseek_article(keyword: str, config: dict) -> dict:
    key = deepseek_key()
    if not key:
        print("No DeepSeek key found, using fallback article.")
        return fallback_article(keyword, config)
    today = dt.date.today().strftime("%Y-%m-%d")
    prompt = f"""
围绕关键词「{keyword}」生成一篇中文 SEO/GEO 文章，主题只聚焦机场优惠码、折扣活动和使用核验。
要求：
- 开头先用 2-3 句话直接回答用户最关心的优惠结论，方便搜索摘要和 AI 引用。
- 不编造优惠码、折扣比例、价格、有效期、账号、订阅或 token。
- 如果无法确认具体代码，明确写“暂未确认到可公开验证的固定优惠码”，不要补造代码。
- 区分优惠码、自动折扣、新用户活动和套餐活动。
- 强调在官网结算页核验，不能承诺一定有效。
- 固定图片为站内图，只生成 image_alt 和 image_caption。
- 正文 Markdown，包含信息摘要表、使用步骤、适用限制、失败原因和核验注意事项。
- 提供 3 个简短 FAQ，答案必须能独立理解。
- 日期使用 {today}。
只输出 JSON，字段：
title, category, tags, keywords, description, image_alt, image_caption, body_markdown, faq
faq 格式为 [{{"question": "...", "answer": "..."}}]。
"""
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": "你只输出可解析 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API error {error.code}: {detail}") from error
    article = clean_json(result["choices"][0]["message"]["content"])
    article["date"] = today
    article["slug"] = slugify(keyword) + "-" + hashlib.sha1(article["title"].encode("utf-8")).hexdigest()[:8]
    article["image"] = config.get("default_image", "/assets/img/hero.png")
    return article


def save_article(article: dict) -> Path:
    ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
    source = ARTICLE_DIR / f"{article['date']}-{article['slug']}.json"
    counter = 2
    while source.exists():
        source = ARTICLE_DIR / f"{article['date']}-{article['slug']}-{counter}.json"
        counter += 1
    write_json(source, article)
    print(f"Created {source}")
    return source


def new_article(args: argparse.Namespace) -> None:
    config = read_yaml(SITE_FILE)
    article = fallback_article(args.keyword, config) if args.no_ai else generate_deepseek_article(args.keyword, config)
    if "slug" not in article:
        article["slug"] = slugify(args.keyword) + "-" + hashlib.sha1(article["title"].encode("utf-8")).hexdigest()[:8]
    if "date" not in article:
        article["date"] = dt.date.today().strftime("%Y-%m-%d")
    if "image" not in article:
        article["image"] = config.get("default_image", "/assets/img/hero.png")
    save_article(article)
    build(argparse.Namespace(site_url=args.site_url))


def keyword_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"keyword file not found: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#")]


def select_keywords(keywords: list[str], limit: int, rotate: bool = False) -> list[str]:
    if limit <= 0 or not keywords:
        return []
    count = min(limit, len(keywords))
    if not rotate:
        return keywords[:count]
    run_number = os.getenv("GITHUB_RUN_NUMBER", "")
    if run_number.isdigit():
        start = (int(run_number) - 1) % len(keywords)
    else:
        start = dt.date.today().toordinal() % len(keywords)
    return [keywords[(start + index) % len(keywords)] for index in range(count)]


def batch(args: argparse.Namespace) -> None:
    config = read_yaml(SITE_FILE)
    source = Path(args.file or DEFAULT_KEYWORDS)
    env_keywords = os.getenv("KEYWORDS")
    keywords = [line.strip() for line in env_keywords.splitlines() if line.strip()] if env_keywords else keyword_lines(source)
    selected = select_keywords(keywords, args.limit, rotate=bool(env_keywords))
    for keyword in selected:
        article = fallback_article(keyword, config) if args.no_ai else generate_deepseek_article(keyword, config)
        if "slug" not in article:
            article["slug"] = slugify(keyword) + "-" + hashlib.sha1(article["title"].encode("utf-8")).hexdigest()[:8]
        if "date" not in article:
            article["date"] = dt.date.today().strftime("%Y-%m-%d")
        if "image" not in article:
            article["image"] = config.get("default_image", "/assets/img/hero.png")
        save_article(article)
    build(argparse.Namespace(site_url=args.site_url))


def write_indexnow_key() -> None:
    key = indexnow_key()
    if key:
        (ROOT / f"{key}.txt").write_text(key, encoding="utf-8")


def indexnow(args: argparse.Namespace) -> None:
    config = read_yaml(SITE_FILE)
    base_url = site_url(config, args.site_url)
    key = indexnow_key()
    if not key:
        print("No INDEXNOW_KEY/local indexnow.key found, skip.")
        return
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", key):
        print("INDEXNOW_KEY must be 8-128 letters, numbers, or dashes. Skip IndexNow.")
        return
    key_location = f"{base_url}/{key}.txt"
    key_ready = False
    for attempt in range(1, 13):
        check_url = f"{key_location}?check={int(time.time())}"
        check_request = urllib.request.Request(
            check_url,
            headers={"User-Agent": "paoluzyun-indexnow/1.0", "Cache-Control": "no-cache"},
        )
        try:
            with urllib.request.urlopen(check_request, timeout=20) as response:
                content = response.read().decode("utf-8", errors="replace").strip()
                if response.status == 200 and content == key:
                    key_ready = True
                    print(f"IndexNow key file verified: {key_location}")
                    break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            pass
        print(f"Waiting for GitHub Pages to publish IndexNow key ({attempt}/12)...")
        time.sleep(10)
    if not key_ready:
        print(f"IndexNow key file is not available yet, skip this notification: {key_location}")
        return
    urls = [f"{base_url}/", f"{base_url}/articles/"]
    urls += [base_url + article_url(article) for article in load_articles()]
    failures: list[str] = []
    accepted = 0
    for url in sorted(set(urls)):
        query = urllib.parse.urlencode({"url": url, "key": key})
        request = urllib.request.Request(
            f"https://www.bing.com/indexnow?{query}",
            headers={"User-Agent": "paoluzyun-indexnow/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status in {200, 202}:
                    accepted += 1
                else:
                    failures.append(f"{url} (HTTP {response.status})")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            failures.append(f"{url} (HTTP {error.code}: {detail or error.reason})")
        except (urllib.error.URLError, TimeoutError) as error:
            failures.append(f"{url} ({error})")

    print(f"IndexNow accepted {accepted}/{len(set(urls))} URLs.")
    if failures:
        print("::error title=IndexNow submission failed::Bing rejected one or more URLs.")
        raise RuntimeError("IndexNow rejected URLs:\n" + "\n".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pure HTML builder for paoluzyun.github.io")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--site-url", default=None)
    p_build.set_defaults(func=build)

    p_new = sub.add_parser("new")
    p_new.add_argument("keyword")
    p_new.add_argument("--no-ai", action="store_true")
    p_new.add_argument("--site-url", default=None)
    p_new.set_defaults(func=new_article)

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("--file", default=None)
    p_batch.add_argument("--limit", type=int, default=1)
    p_batch.add_argument("--no-ai", action="store_true")
    p_batch.add_argument("--site-url", default=None)
    p_batch.set_defaults(func=batch)

    p_indexnow = sub.add_parser("indexnow")
    p_indexnow.add_argument("--site-url", default=None)
    p_indexnow.set_defaults(func=indexnow)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
