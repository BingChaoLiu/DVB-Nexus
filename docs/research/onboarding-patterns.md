# 观测 / 排障类工具新人引导模式外部参考(onboarding patterns)

- **对应 Issue**: BingChaoLiu/DVB-Nexus #85(wayfinder research 子票);服务地图 #84
- **日期**: 2026-11-16
- **调研方式**: Web 调研一手来源为主——Wireshark User's Guide(wsug)、developer.chrome.com 发布说明、grafana.com 官方文档 + grafana/grafana 公开源码(GetStarted.tsx / Guide.tsx)、learning.postman.com 官方文档、labs.play-with-k8s.com 落地页实测抓取;每条结论附来源链接。个别无法从一手来源核实的事实(如 PWK 会话 4 小时时限)明确标注二级来源。
- **性质**: 纯调研;产出供「旅程起点原型票」「示例数据原型票」「三模块细裁票」参考。未改动任何代码 / issue / git 状态(本文档本身落在一次性研究分支)。
- **既定偏好基线**(地图 #84 Notes,本调研在其约束下评估): 静态路标式引导(起点 + 每页路标 + 空态三问)、不做弹窗 tour、中文为主文案、需一键示例数据能力、首要用户 = 新入职工程师、验收 = 30 分钟不看文档独立走通八步闭环拿 PASS。

---

## 0. 结论摘要(TL;DR)

1. **五参照无一使用模态弹窗 coach-mark tour**。主旅程全部以「常驻静态路标」呈现:Wireshark Welcome screen、Grafana 首页 "Recommended getting started guides" 卡片网格(源码证实,可折叠且折叠状态按用户持久化)、Postman Launchpad、PWK 落地页 + 同屏分步指令。这与 #84 既定「静态路标式」偏好完全同向,属于业界默认做法而非保守选择。
2. **空态 = 一句话 + 恰好一个动作按钮,且按钮直接消除空态成因**。Chrome DevTools 135 官方发布说明"Improved empty states…let you know exactly what to do to start working with them",Network 空态直接给 "Reload page" 按钮;Grafana 空面板上的大按钮 "+ Add visualization" 既是空态也是入口。这是 #84「空态三问」的业界成熟形态:三问不必三段文字,一句话 + 一个按钮即可承载。
3. **示例数据靠三层标注做到不与真实数据混淆**:命名层(与真实数据同列但名字自证——Grafana 内置源就叫 "-- Grafana --",Postman 用独立域名 postman-echo.com,Wireshark 样例文件名 + 格式 + 一句话描述,合成数据明写 "fake")、入口层(独立专区/空态/起步卡提供,不掺进真实数据流)、生命层(边界可见且整段可弃——PWK 会话 4 小时时限可见)。五参照无一把 sample 混入真实数据流。
4. **最小闭环先行**:Postman 第一个请求刻意设计成「不需要自己的 API、不需要认证配置」,约 1 分钟看到响应,再教保存与断言;Wireshark 为「刚装好、自己网络没流量」的人备好 SampleCaptures 样例库。对应到八步闭环:应在八步之前(或之中)设一个 60 秒级「看到第一条数据流动」的预热里程碑,先给一次 PASS 反馈,再展开完整旅程。
5. **一条反例教训**:Wireshark 把示例数据放在产品外 wiki,新人不看文档根本不知道它存在——这正是「示例数据必须产品内一键可达」(地图既定)的直接论据。

---

## 1. 五个参照逐一分析

### 1.1 Wireshark(教学流程 + 显示过滤器助手)

**主旅程呈现:**

- **Welcome screen(起点页)**:启动即列出本机捕获接口(Capture 区),不设任何线性向导;欢迎页可显示最近打开的文件——偏好项源码注释原文 "If true, show recent files on the welcome page"([Wireshark API 文档 `_e_prefs`](https://www.wireshark.org/docs/wsar_html/struct__e__prefs.html))。起点页的语义是「从这里开始抓」,不是「带你逛一圈」。
- **过滤器助手(WSUG §3.17)**:过滤输入框带即时语法校验——"The background will turn red if you enter an incomplete or invalid string, and will become green when you enter a valid string.";显式 Apply / Enter 才生效;Bookmarks 菜单保存常用过滤;Recent 下拉;一键 Filter buttons(标签用 `//` 分组折叠)。([WSUG "The Filter Toolbar"](https://www.wireshark.org/docs/wsug_html_chunked/ChUseFilterToolbarSection.html))
- **不记语法用户的退路(WSUG §6.5)**:"Display Filter Expression" 对话框用 GUI 选字段 / 操作符 / 值构建过滤器,完全不碰语法。([WSUG 目录](https://www.wireshark.org/docs/wsug_html_chunked/))

**空态与首跑:**

- 产品内不含示例数据;示例库在 [wiki SampleCaptures](https://wiki.wireshark.org/SampleCaptures) 页,开篇定位即给「刚装好、自己网络没意思流量」的人:"Here's some goodies to try."
- **标注实践(值得抄的模板)**:文件名按「协议 + 场景」(`tftp_rrq.pcap`、`arp-storm.pcap`);每条附格式标注(libpcap / pcapng / snoop)+ 一句话描述 + 关注包号;合成数据明写 "fake" / "scripted (SIPp)";真实抓包标注 "anon" / "redacted";还有版本 caveat(如某 PANA 样例 "requires Wireshark 0.99.5 or before to view it correctly")。

**对 DVB-Nexus**:红绿即时校验 + 保存书签 + GUI 构建器三件套可平移到 Monitor 的查询 / 过滤输入(若该票裁走查询 DSL 路线);「名称 + 格式 + 一句话 + 关注点」是示例数据条目的现成标注模板。**不适用**:示例数据放产品外 wiki 的部署方式——违反「30 分钟不看文档」验收;着色语义与其过滤 DSL 绑定,只借模式不借实现。

### 1.2 Chrome DevTools(首次打开体验)

**主旅程呈现:**

- 无向导,面板化(顶部 tab = panels);官方文档自己承认复杂度:"The DevTools UI can be a little overwhelming…there are so many tabs!"([DevTools Overview](https://developer.chrome.com/docs/devtools/overview)),消化方式是文档与视频,不是产品内 tour。
- **一次性指路**:Chrome 58 起官方记载 "the first time you open a new version of Chrome, DevTools opens the What's New drawer with a link to the release notes"([Chrome 58 发布说明](https://developer.chrome.com/blog/devtools-release-notes))——是**抽屉(drawer)不是模态弹窗**,看完即关,不拦路。

**空态与首跑:**

- Chrome 135 发布说明 "Improved empty states for various panels":空态 "streamlined to let you know exactly what to do to start working with them",部分空态带动作按钮——Network 面板空态直接给 **"Reload page"** 按钮,点按即开始采集([Chrome 135 发布说明](https://developer.chrome.com/blog/new-in-devtools-135))。这是「空态按钮直接消除空态成因」的教科书案例:空态的原因是没有网络活动,解法按钮就是制造一次网络活动。

**对 DVB-Nexus**:空态 = 一句话 + 单动作按钮,且按钮直接执行(开始实验 / 一键示例数据),不是「去看文档」;「一次性 What's New 抽屉」可留作未来版本变更指路通道(本 effort 不做)。**不适用**:DevTools 没有示例数据——它附着在真实网页上,「数据」天然存在;DVB-Nexus 空装系统必须自带示例;「复杂度交给文档消化」与首要用户「不看文档」目标直接冲突。

### 1.3 Grafana(onboarding 与示例 dashboard)

**主旅程呈现:**

- 官方首跑路径([Build your first dashboard](https://grafana.com/docs/grafana/latest/fundamentals/getting-started/first-dashboards)):主菜单 **Dashboards → New → New dashboard** → 空面板上的大按钮 **"+ Add visualization"**(空态即入口)→ 选数据源 → Time series → **Refresh** → **Save**。
- **首页起步卡(源码证实,一手)**:[GetStarted.tsx](https://github.com/grafana/grafana/blob/main/public/app/features/home/Overview/GetStarted.tsx) 渲染 "Recommended getting started guides" 标题 + 3 列 Guide 卡片;[Guide.tsx](https://github.com/grafana/grafana/blob/main/public/app/features/home/Overview/Guide.tsx) 卡片结构 = icon + title + description + cta + href;折叠状态存 localStorage(`grafana.home.get-started.expanded`)——**静态、可折叠、按用户持久化,不是弹窗**。

**空态与首跑:**

- 空面板 "+ Add visualization" 即空态 CTA(同一文档页)。
- **示例数据 = 产品内置数据源**:数据源下拉里名字就叫 **"-- Grafana --"**,选中它 "generates the Random Walk dashboard";FAQ 原文:用它 "create your first dashboard without connecting an external data source"、"learn the dashboard creation workflow before connecting your own data"(同上文档页)。
- 外部沙盘 [Grafana Play](https://play.grafana.org):官方博客原文 "a free, publicly accessible sandbox environment where anyone can explore and learn about Grafana, no setup or sign-in required"、"preloaded with sample dashboards demonstrating how to connect to data sources, build visualizations"([Grafana Play 博客](https://grafana.com/blog/grafana-play-updates-a-redesigned-homepage-to-celebrate-our-community))。

**对 DVB-Nexus**:示例数据做成与真实数据源**并列可选但命名自证**的一等公民,并且在用户要做选择的那一刻**就近**出现在空态 / 起步卡里;「先学会工作流、再接真实数据」的顺序与地图「一键示例数据让新工程师最快看到数据流动」完全同构;起步卡网格形态可直接作为旅程起点页的原型参考。**不适用**:Grafana Play 是独立公网站点——我们要求示例内嵌产品一键可达;AI 生成标题、Grafana Arcade 游戏化超出 30 分钟验收需要。

### 1.4 Postman(API 客户端新手引导)

**主旅程呈现:**

- Quick start 全程 UI 内完成([Postman quick start](https://learning.postman.com/docs/getting-started/quick-start)):点 "Add" 开新请求 tab → 填 `postman-echo.com/get` → GET → **"Send"** → 下半屏 **"Response"** 立即出 JSON → "Save" 进 "New Collection" → Scripts/Snippets 点内置断言 **"Status code: Code is 200"** → 再 Send → 看 "Test Results"。
- 第一旅程刻意设计成**不需要自己的 API、不需要认证配置**的最小完整闭环(请求 → 响应 → 保存 → 断言),约 1 分钟看到第一个真实结果。

**空态与首跑:**

- 示例后端有独立身份:Echo API 文档原文 "provides a quick way to send a request without worrying about authentication or request configuration"、让初学者 "learn how to do something in Postman without connecting to a 'real' API"([Echo API 文档](https://learning.postman.com/docs/reference/developer-resources/echo-api))。
- **标注方式**:独立命名服务——`postman-echo.com` 域名本身写明 echo,与真实 API 无混淆可能。

**对 DVB-Nexus**:「Echo 模式」= 专门命名的示例后端,一次请求即看到域内真实形状的响应——对应一键示例数据应生成**结构真实**的 session/run 数据;最小闭环先于完整闭环;Snippets 式一键插入现成断言,对应 Verify 表单的一键填充。**不适用**:账号 / 工作区 / 云同步类 onboarding(本地即用,无此环节);其「域名即标注」依赖外部服务命名,内嵌示例数据仍需显式 UI 标注(示例徽标 / 前缀)。

### 1.5 Play with K8s(沙盘类)

**主旅程呈现:**

- 落地页原文(本调研实测抓取 [labs.play-with-k8s.com](https://labs.play-with-k8s.com)):"a playground which allows users to run K8s clusters in a matter of seconds…free Alpine Linux Virtual Machine in browser…Docker-in-Docker (DinD)";并指路 "the Play with Kubernetes Classroom which provides more directed learning using an integrated Play with Kubernetes commandline"——**双轨制**:自由沙盘(playground)+ 分步课堂(Classroom,指令面板与终端同屏、步骤即复制粘贴命令)。
- 一键 Start 开会话;会话限时约 4 小时、到期环境销毁(多个二级来源一致记载,如 [freeCodeCamp K8s Handbook](https://www.freecodecamp.org/news/learn-kubernetes-handbook/) "about 4 hours of play time, after which the environment is destroyed"。注意:PWK 原 GitHub 组织已 404,站点在线但此细节只能以二级来源佐证)。

**空态与首跑:**

- 整个环境就是 sandbox,「示例性」由产品形态本身声明,与生产混淆风险为零;时效边界用可见倒计时 / 横幅表达。

**对 DVB-Nexus**:双轨制正好对应既定边界「Topologies = 进阶自由工具 / Lab = 场景语境引导」,获得外部证据支持;步骤与操作区**同屏**(不跳文档)值得 Lab 步骤卡借鉴;会话生命期可见 + 整段可弃,可温和地用于示例会话(标注「示例」+ 一键清理)。**不适用**:4 小时强制销毁机制本身(本地单机无共享资源压力);云端多实例部署形态;其自由沙盘没有任何引导路标——直接照搬会让 Lab 退化成 Monitor 式自由观测,与地图「Lab = 场景语境引导」既裁边界冲突。

---

## 2. 三个问题汇答

### 2.1 主旅程在 UI 上如何呈现

| 工具 | 起点页 | 引导形式 | 弹窗 tour? |
| --- | --- | --- | --- |
| Wireshark | Welcome screen(接口列表 + recent files) | 静态起点页 + 过滤器三件套助手 | 否 |
| Chrome DevTools | 无(附着于页面) | 一次性 What's New 抽屉 + 各面板空态 | 否(抽屉) |
| Grafana | 首页 "Recommended getting started guides" 卡片网格 | 静态卡片 + 空面板大按钮 + 文档步骤 | 否 |
| Postman | Launchpad | 最小闭环教程内联 UI(Echo) | 否 |
| Play with K8s | 落地页 | 一键会话 + 同屏分步指令(Classroom) | 否 |

共性:**常驻静态路标 + 空态 CTA**;没有一家用模态弹窗 coach-mark tour。Grafana 起步卡折叠状态按用户持久化,即「走过的路标会安静下去」,这是静态路标式的成熟细化。

### 2.2 空态与首跑最佳实践(示例数据如何标注)

- **空态**:一句话说明「这是什么 / 为什么空」+ 恰好一个按钮「下一步去哪」,且按钮**直接执行动作**(Chrome 135 Network 空态 "Reload page";Grafana "+ Add visualization"),不是「去读文档」。
- **示例数据三层标注**(五参照无一违反):
  1. **命名层**:与真实数据同列但名字自证——Grafana "-- Grafana --" 前缀;Postman 独立域名;Wireshark 文件名 + 格式 + 一句话描述,合成数据明写 "fake"。
  2. **入口层**:从独立入口提供(SampleCaptures 专区、Launchpad、起步卡、空态按钮),不掺进真实数据列表。
  3. **生命层**:边界可见且整段可弃(PWK 4 小时时限可见;样例文件版本 caveat;PWK 会话整体销毁)。
- **反例教训**:Wireshark 示例数据在产品外 wiki → 新人不看文档就找不到。「示例必须产品内一键可达」由此从偏好升级为有外部证据的设计结论。

### 2.3 可直接借鉴清单 / 不适用清单

**可直接借鉴(给原型票的候选模式):**

1. **旅程起点页 = 静态卡片网格**(Grafana 首页形态):每卡片一句话 + CTA,可折叠、按用户持久化——承载「起点 + 每页路标」。
2. **空态三问落成「一句话 + 单按钮」**,按钮直接执行动作(开始实验 / 一键示例数据),空态按钮消除空态成因(Chrome "Reload page" 模式)。
3. **示例数据 = 产品内置、命名带「示例」标识、与真实数据并列可选**(Grafana "-- Grafana --" 模式);入口放起步卡与空态,不放真实列表;数据内容结构真实(Postman Echo「形状真实」)。
4. **最小闭环先行**:八步闭环之前(或第一步内)设 60 秒级「看到第一条数据流动」预热里程碑(Postman first request);八步 Stepper 补「当前步 → 下一步」静态路标,步骤与操作同屏(PWK Classroom)。
5. **Monitor 查询输入三件套助手**(Wireshark):即时红绿校验 + 保存书签 + GUI 构建;**Verify 表单 Snippets 式一键填充**(Postman)。
6. **示例会话生命期可见 + 一键丢弃**(PWK 时效可见的温和版):示例 session 带明显标识、可整体清理,不进真实列表。
7. **双轨制外部证据**(PWK playground / Classroom):支持「Topologies = 进阶自由工具 / Lab = 场景语境引导」既定边界,无需重裁。
8. **一次性 What's New 抽屉**(Chrome):留作未来版本变更指路通道;本 effort 不做。

**明确不适用(及原因):**

1. **模态弹窗 coach-mark tour**(Pendo 式):五参照无一使用;直接违反既定「静态路标式、不做弹窗 tour」。
2. **游戏化 / 积分 / Arcade**(Grafana Arcade):超出 30 分钟验收目标,维护成本高。
3. **独立演示站点**(Grafana Play 部署形态):示例必须内嵌产品一键可达,外部站点是「看文档」的变体。
4. **云端限时强制销毁沙盒**(PWK 4 小时到期销毁):本地单机无共享资源压力;仅保留「示例可弃、生命期可见」的温和版。
5. **示例数据外包给外部 wiki**(Wireshark SampleCaptures 部署方式):违反「30 分钟不看文档」验收。
6. **DevTools 式「复杂度交给文档消化」**:与首要用户「不看文档」目标直接冲突。
7. **账号 / 工作区 / 云同步 onboarding**(Postman 云特性):本地即用,无此环节。

---

## 3. 来源清单

- Wireshark:
  - WSUG(v5.1.0)目录与 "The Filter Toolbar":https://www.wireshark.org/docs/wsug_html_chunked/ 、https://www.wireshark.org/docs/wsug_html_chunked/ChUseFilterToolbarSection.html
  - 偏好项源码注释(欢迎页 recent files):https://www.wireshark.org/docs/wsar_html/struct__e__prefs.html
  - SampleCaptures wiki:https://wiki.wireshark.org/SampleCaptures
- Chrome DevTools:
  - Overview:https://developer.chrome.com/docs/devtools/overview
  - Chrome 58 发布说明(What's New drawer 首开):https://developer.chrome.com/blog/devtools-release-notes
  - Chrome 135 发布说明(Improved empty states、Network "Reload page"):https://developer.chrome.com/blog/new-in-devtools-135
- Grafana:
  - Build your first dashboard(内置 "-- Grafana --" 源、"+ Add visualization"):https://grafana.com/docs/grafana/latest/fundamentals/getting-started/first-dashboards
  - GetStarted.tsx / Guide.tsx 源码(grafana/grafana main 分支):https://github.com/grafana/grafana/blob/main/public/app/features/home/Overview/GetStarted.tsx 、https://github.com/grafana/grafana/blob/main/public/app/features/home/Overview/Guide.tsx
  - Grafana Play 官方博客:https://grafana.com/blog/grafana-play-updates-a-redesigned-homepage-to-celebrate-our-community
- Postman:
  - Quick start:https://learning.postman.com/docs/getting-started/quick-start
  - Echo API:https://learning.postman.com/docs/reference/developer-resources/echo-api
- Play with Kubernetes:
  - 落地页(实测抓取,本调研直接引用):https://labs.play-with-k8s.com/
  - 4 小时会话时限(二级来源佐证):https://www.freecodecamp.org/news/learn-kubernetes-handbook/
- 调研局限:PWK 原 GitHub 组织(play-with-k8s)已 404,会话时限等运行期细节无法一手核实,已标注二级来源;training.play-with-k8s.com 在本次调研中网络不可达,课堂步骤结构依据落地页指向与二级来源转述。
