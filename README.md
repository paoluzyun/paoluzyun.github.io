# 跑路云

跑路云官方网站，发布机场优惠码、折扣活动、套餐优惠和使用核验文章。

## 网站

- 首页：https://paoluzyun.github.io/
- 文章：https://paoluzyun.github.io/articles/
- Sitemap：https://paoluzyun.github.io/sitemap.xml

## 自动化

- DeepSeek 是页面主体和 CSS 的主设计师，可自由决定版式、配色、区块顺序和视觉风格。
- 程序只要求首页保留品牌、文章列表、FAQ、文章入口，文章页保留标题、正文、FAQ、相关文章等动态插槽。
- SEO head、canonical、Open Graph 和结构化数据由 Python 稳定生成，不受模板设计影响。
- 早期不完整的 v1 只允许升级一次到 v2。
- `templates/template.lock.json` 写入 `prompt_version: 2` 后不能再次生成。
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
