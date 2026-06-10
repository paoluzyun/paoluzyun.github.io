# 跑路云

跑路云官方网站，发布机场优惠码、折扣活动、套餐优惠和使用核验文章。

## 网站

- 首页：https://paoluzyun.github.io/
- 文章：https://paoluzyun.github.io/articles/
- Sitemap：https://paoluzyun.github.io/sitemap.xml

## 自动化

- DeepSeek 先以创意总监身份制定视觉方案，再实现页面，最后以设计总监身份复审成品。
- DeepSeek 可自由决定版式、配色、区块顺序和视觉风格，程序不写死美术方案。
- 程序只要求首页保留品牌、文章列表、FAQ、文章入口，文章页保留标题、正文、FAQ、相关文章等动态插槽。
- 程序会把真实的文章卡片、导航、页脚、FAQ 和文章正文结构交给 DeepSeek，确保这些动态内容也有完整样式。
- SEO head、canonical、Open Graph 和结构化数据由 Python 稳定生成，不受模板设计影响。
- 旧模板只允许升级一次到 v3。
- `templates/template.lock.json` 写入 `prompt_version: 3` 后不能再次生成。
- `Daily Coupon Publishing` 每天计划运行 10 次，每次领取一个未使用关键词。
- 关键词与使用记录保存在私密仓库，不出现在公开仓库。
- 文章生成后自动重建首页、文章列表、RSS、sitemap 和 robots。
- IndexNow 会提交新站 URL，并在被拒绝时让工作流明确失败。

## 必需配置

在仓库 `Settings → Secrets and variables → Actions` 配置：

Secrets：

- `DEEPSEEK_API_KEY`
- `INDEXNOW_KEY`
- `SEO_DATA_SSH_KEY`

Variables：

- `SITE_URL=https://paoluzyun.github.io`
- `SEO_DATA_REPO=paoluzyun/seo-private-data`
- `DEEPSEEK_MODEL=deepseek-chat`

配置完成后先手动运行一次 `Initialize DeepSeek Template`，成功后每日发布工作流才会运行。
