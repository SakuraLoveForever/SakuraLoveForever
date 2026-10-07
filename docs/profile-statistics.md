# GitHub 主页统计

## 使用现成项目

- [Tokscale](https://github.com/junhoyeo/tokscale)：固定使用 4.18.0 原生解析器统计 Codex 与 DeepSeek Harness 的 token/会话活跃时长。assets/ai-usage.png 直接由 wrapped --clients 命令生成，未另做图表设计。
- [Shields.io](https://shields.io/badges/endpoint-badge)：读取 data/badges/*.json，采用现成徽章样式展示各工具累计 token 和会话活跃时长。额外的输入、输出、缓存分项端点也已生成，可直接引用。
- [lowlighter/metrics](https://github.com/lowlighter/metrics)：失效的外部 Activity Graph 模块改用仓库已有贡献日历 metrics.plugin.calendar.full.svg，继续由已有 metrics.yml 工作流更新，未另写活动图渲染器。

scripts/profile_stats.py 只调用现成 CLI、检查输出和历史是否下降、保留汇总，以及生成标准 Shields endpoint JSON。没有自制 token 解析、会话计时或 SVG 绘图算法。

## 历史覆盖范围

首次扫描遗漏了 DeepSeek 桌面端的独立目录，现已补充给 Tokscale 的 scanner.extraScanPaths.dsh：

- Codex：默认用户目录 .codex/sessions 和 .codex/archived_sessions。现存可统计记录从 **2026-08-20** 开始。
- DeepSeek Harness CLI：.dsh/sessions。
- DeepSeek Harness 桌面端：%APPDATA%/dsh-desktop/harness/sessions，并探测 %APPDATA%/@deepseek-ai/dsh-desktop/harness/sessions。合并后现存可统计记录从 **2026-09-10** 开始。

以上只是这台电脑现存日志的数据覆盖范围，**不是实际开始使用日期，也不是完整账号使用量**。用户记得 5、6 月已开始使用，但目前在当前用户日志、Codex 索引数据库、已检查的桌面数据目录和候选旧目录中未找到当时的可用记录。找到旧用户目录或备份后，可以交给 Tokscale 补扫；不能用记忆推算缺失的小时数或 token。

扫描配置隔离在 %LOCALAPPDATA%/SakuraLoveForever/usage-config/settings.json，不修改其他 Tokscale 安装的配置。Tokscale 自行处理重复目录、归档日志、DSH zstd 压缩日志和分叉历史。

## 统计口径

- 日期固定为 Asia/Shanghai，每次重新扫描全量可用历史，包含累计量与按天汇总。
- Tokscale 的非缓存输入、缓存读取、缓存写入、非推理输出、推理 token 是五个可相加的分桶。输入徽章包含缓存，输出徽章包含推理；缓存是输入的子集，不能再加到总量。
- 活跃时长按会话累计，默认排除超过 3 分钟的空闲间隔。并行会话可能重叠，因此它不是人工工作小时数，也不能与 WakaTime 时间直接相加。
- 原生 Wrapped 的 Cost 是按模型定价推算的 API 等价费用，可能有未覆盖的模型或价目差异，**不是实际账单或订阅扣费**。年度图展示当前年份，徽章与 JSON 包含全部可用历史。
- data/ai-usage.json 只保存按工具、日期汇总的数值，不包含提示词、回复、目录、会话 ID 或凭证。原生 Wrapped 会显示模型名称。Tokscale 临时 JSON 导出在读取后删除；不调用 login、submit 或订阅额度接口。
- 历史 token 或每日活跃时长下降会使采集报错并保留旧结果。先恢复日志；只有人工核对过的修正才使用 --allow-decrease。
- WakaTime 的编辑器统计保留，旧 Code Time、AI Code Time 和周 AI 区块已禁用，避免与本地工具统计混淆。

## 手动更新

需要 Python 3.12+、Node.js/npm 和 Git。薄适配脚本仅使用 Python 标准库；无需 Bun、数据库、Vercel 或另一个公开统计账号。

```powershell
python scripts/profile_stats.py collect
python -m unittest discover -s tests -v
```

仅更新 Shields 数据：python scripts/profile_stats.py render。迁移用户目录时可用 collect --home C:/old-user-home；其他历史目录可加入上述隔离配置中的 scanner.extraScanPaths.codex 或 scanner.extraScanPaths.dsh，保留原配置并重新运行。直接导入已保存的固定版本导出可用 collect --import-dir <目录>，目录内需要 codex.json、dsh.json；离线模式只更新 JSON/徽章，原生年度 PNG 需要本机日志。

## 每日自动同步

采用 **Windows 任务计划程序，每天北京时间 08:30 一次**。当前电脑时区为 Asia/Shanghai；任务按系统本地时间触发，若电脑以后切换时区，应重新核对执行时间。电脑开机且用户登录时运行；错过的执行在恢复后补跑。采集后只提交、推送汇总 JSON、Shields 数据和原生 PNG。

```powershell
# 安装每日任务（普通用户权限，隐藏运行）。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -InstallTask -Publish

# 手动立即同步并发布。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -Publish

# 移除本机每日任务。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -RemoveTask
```

任务名 SakuraLoveForever-ProfileStats；日志 %LOCALAPPDATA%/SakuraLoveForever/profile-sync.log。需要干净的 main 分支和有效 Git 凭证；工作区正在编辑或切换分支时跳过，避免处理其他工作。恢复干净的 main 后下次重试。采集失败保留旧图，推送失败保留本地提交以便下次重试。恢复后不会高频追赶每一次遗漏。

GitHub 的 Profile statistics checks 工作流运行测试并检查徽章数据一致性。GitHub 托管 runner 无法读取电脑日志，AI 用量由上述本机任务采集。README 的 Shields/GitHub 图片有缓存，新提交不会保证立刻出现在页面。

## 验证

回归测试覆盖缓存/推理不重复计数、私有字段不进入汇总、无效导出不覆盖旧统计，以及 token/时间历史下降保护。首次接入已用 ccusage@20.0.26 独立校验 Codex 截至 **2026-10-07** 的历史：两者均为 **1,955,133,139 token**，差值为 0。当前日持续有新调用，不同采集时刻的当日总量可能不同。

Tokscale 和 ccusage 均为 MIT 项目。本仓库没有复制修改它们的展示代码，原生图保留 Tokscale 标识。
