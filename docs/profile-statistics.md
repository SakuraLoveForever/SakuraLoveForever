# GitHub 主页统计

## 使用现成项目

- [Tokscale](https://github.com/junhoyeo/tokscale)：固定使用 4.20.0 原生解析器统计 Codex 与 DeepSeek Harness 的 token/会话活跃时长。assets/ai-usage.png 直接由 wrapped --clients 命令生成，未另做图表设计。
- [Shields.io](https://shields.io/badges/endpoint-badge)：读取 data/badges/*.json，采用现成徽章样式展示各工具累计 token 和会话活跃时长。额外的输入、输出、缓存分项端点也已生成，可直接引用。
- [lowlighter/metrics](https://github.com/lowlighter/metrics)：失效的外部 Activity Graph 模块改用仓库已有贡献日历 metrics.plugin.calendar.full.svg，继续由已有 metrics.yml 工作流更新，未另写活动图渲染器。

scripts/profile_stats.py 只调用现成 CLI、检查输出和历史是否下降、保留汇总，以及生成标准 Shields endpoint JSON。没有自制 token 解析、会话计时或 SVG 绘图算法。

## 历史覆盖范围

首次扫描遗漏了 DeepSeek 桌面端的独立目录，现已补充给 Tokscale 的 scanner.extraScanPaths.dsh：

- Codex：默认用户目录 .codex/sessions 和 .codex/archived_sessions。现存可统计记录从 **2026-08-20** 开始。
- PackyCode：自动补扫同一用户的 .codex-packy/sessions、.codex-packy/archived_sessions，以及当前 CODEX_HOME 下存在的会话目录。token 与会话活跃时长合并到 Codex 统计，定时任务不依赖 PackyCode 启动器的环境变量；重复日志交给 Tokscale 去重。
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
- PackyCode 的独立 Codex 配置也启用了 codex-cli-wakatime 插件，共用 ~/.wakatime.cfg 的账号。WakaTime 记录为 Codex 的 AI Coding 活动；本仓库的 Codex token/时间徽章由上述本地日志扫描生成，不能用 WakaTime 插件是否安装来判断徽章是否包含 PackyCode。

## 手动更新

需要 Python 3.12+、Node.js/npm 和 Git。薄适配脚本仅使用 Python 标准库；无需 Bun、数据库、Vercel 或另一个公开统计账号。

```powershell
python scripts/profile_stats.py collect
python scripts/profile_stats.py collect --codex-only
python -m unittest discover -s tests -v
```

仅更新 Shields 数据：python scripts/profile_stats.py render。迁移用户目录时可用 collect --home C:/old-user-home；其他历史目录可加入上述隔离配置中的 scanner.extraScanPaths.codex 或 scanner.extraScanPaths.dsh，保留原配置并重新运行。直接导入已保存的固定版本导出可用 collect --import-dir <目录>，目录内需要 codex.json、dsh.json；离线模式只更新 JSON/徽章，原生年度 PNG 需要本机日志。

## 持续自动同步

采用 **Windows 任务计划程序，每小时一次**。每小时任务执行 `collect --codex-only`，从本机 Codex 日志更新 token、使用时长和年度图。DeepSeek Harness 与百炼沿用已发布汇总，手动执行 `collect` 可采集全部工具。采集日期固定使用 Asia/Shanghai。电脑开机且用户登录时运行，错过的执行在恢复后补跑。每次运行都会读取本机仍保留的全部受支持 Codex 历史日志，补入两次运行之间的用量。采集后提交、推送 Codex 汇总 JSON、两个 Codex 徽章、采集时间和原生 PNG。先采集并保存本地提交，再拉取远程并推送，GitHub 暂时断网会保留本地采集结果。

```powershell
# 安装或更新每小时任务（普通用户权限，隐藏运行）。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -InstallTask -Publish

# 手动立即同步并发布。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -Publish

# 移除本机同步任务。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -RemoveTask
```

任务名 SakuraLoveForever-ProfileStats，日志 %LOCALAPPDATA%/SakuraLoveForever/profile-sync.log。本机两个同步任务均从专用检出目录 `%LOCALAPPDATA%/SakuraLoveForever/publisher` 启动，安装任务时在此目录执行上述命令。发布需要该目录处于干净的 main 分支和有效 Git 凭证。日常开发使用项目原目录，定时任务在专用目录采集和发布。采集失败保留旧图，推送失败保留本地提交以便下次重试。恢复后按每小时计划执行。

定时任务通过 `wscript.exe //B` 启动 `scripts/sync-profile-background.vbs`，从进程创建时隐藏 PowerShell；统计 CLI 子进程也使用 Windows 无窗口标志。后台不显示命令行窗口或托盘图标，错误仍保留在上述日志，任务计划程序保留失败退出码。已有任务需重新安装，或只将现有任务的操作更新为此入口；使用每小时触发器并保留原来的登录权限。

需要手动静默运行时可执行：

```powershell
wscript.exe //B //Nologo scripts/sync-profile-background.vbs -Publish
```

GitHub 的 Profile statistics checks 工作流运行测试并检查徽章数据一致性。GitHub 托管 runner 无法读取电脑日志，AI 用量由上述本机任务采集。README 的 Shields/GitHub 图片有缓存，新提交不会保证立刻出现在页面。

## Codex Profile Token 活动

主页的每日、每周和累计图使用 [Codex App Server 的账号用量接口](https://learn.chatgpt.com/docs/app-server#7-token-usage-chatgpt)。每天沿用接口提供的日期，每周从周一开始，累计折线相加图表窗口内的记录。累计图也会单独展示账号累计总量（若接口提供）。公开仓库仅保存三张汇总 SVG。点击每日图可打开原图，悬停格子显示接口返回的日期和按日用量。

本机任务 `SakuraLoveForever-CodexActivity` 每天北京时间 **00:00** 运行，在电脑开机并登录 Windows 后补跑错过的执行。使用本机 `codex` CLI 已登录的 ChatGPT 账号、网络和 Git 凭证，要求干净的 `main` 工作区。读取失败时保留已发布图表，日志位于 `%LOCALAPPDATA%/SakuraLoveForever/codex-activity-sync.log`。这个任务独立于上述每小时的日志统计。

```powershell
# 安装或更新每天 00:00 同步任务。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -CodexActivity -InstallTask -Publish

# 手动同步并发布。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -CodexActivity -Publish

# 移除每天 00:00 同步任务。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-profile.ps1 -CodexActivity -RemoveTask
```

## 验证

回归测试覆盖缓存/推理不重复计数、私有字段不进入汇总、无效导出不覆盖旧统计，以及 token/时间历史下降保护。首次接入已用 ccusage@20.0.26 独立校验 Codex 截至 **2026-10-07** 的历史：两者均为 **1,955,133,139 token**，差值为 0。当前日持续有新调用，不同采集时刻的当日总量可能不同。

Tokscale 和 ccusage 均为 MIT 项目。本仓库没有复制修改它们的展示代码，原生图保留 Tokscale 标识。

## 2026-10-21 更新修复

- Tokscale 从 4.18.0 升到固定的 4.20.0：实测旧版扫描漏掉压缩的 Codex rollout，新版能读取现存 .jsonl.zst，未绕过历史下降保护。部分日志没有受支持的 usage 记录，CLI 会报告遗漏；这些 token 无法凭空补齐。
- 新增非缓存 token、缓存读取和采集时间徽章。时间徽章表示成功采集时间，不表示推送或浏览器缓存刷新时间。非缓存分项不含缓存读取/写入。
- 删除 Issues/PR 与 Reactions 展示，并停止总图中的这两个插件。
- 原先 README 的独立 Star SVG 最后提交于 2026-04-28，总图更新不会更新它；新增独立 stars.yml，每 15 分钟生成它。GitHub Actions 的 schedule 可能排队延迟，并非秒级实时。
- token 任务依赖此电脑开机、登录和 main 工作区干净；联网后下轮重试发布。GitHub 与 Shields 缓存会有额外延迟。
