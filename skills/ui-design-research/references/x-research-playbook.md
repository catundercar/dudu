# X（Twitter）顶级设计师一手调研手册

本手册解决一个核心问题：**如何在 X（Twitter）上快速找到真正高信噪比的一手 UI/产品设计思路，并把它们转化为可迁移的设计原理，而不是盲目抄概念图。**

---

## 1. 问题词转译表（先转译，再检索）

不要搜宽泛词（如 `"best dashboard UI"`），先将现状痛点映射成一线设计师在 X 上真正使用的术语：

| 常见界面痛点 | 高信噪比检索词（中 / 英） |
| :--- | :--- |
| 顶栏 / 侧栏太重、导航叠罗汉 | `chrome reduction`, `minimal toolbar`, `inspector header`, `recessed segmented control`, `toolbar hierarchy`, `Chrome 减法` |
| 列表像后台线框图、到处是框 | `tonal layering`, `borderless list`, `surface hierarchy`, `dark mode elevation`, `no borders`, `去边框`, `微表面` |
| 圆角嵌套生硬、间距散乱 | `concentric border radius`, `nested radius`, `optical alignment`, `4px grid`, `同心圆角`, `视觉对齐` |
| 树形/子项显得老土杂乱 | `sub-issues UI`, `nested list without tree lines`, `progressive disclosure`, `hierarchy indentation` |
| 搜索栏/筛选栏常驻占空间 | `on-demand search`, `command palette`, `collapsible filter`, `inline search bar`, `cmdk` |
| 悬停弹窗乱闪、交互毛糙 | `hover intent`, `safe triangle`, `tooltip delay`, `popover anchoring`, `spring physics`, `micro-interactions` |
| AI 生成感重、像套模板 | `AI slop UI`, `generic SaaS`, `design craft`, `design details`, `去 AI 味`, `vibe design tips` |

---

## 2. X 精准检索策略与标杆索引

### 2.1 高效检索组合

```text
# 组合 1：X 原帖定向（主题词 + 设计师 / 团队）
site:x.com ("Rauno" OR "Emil Kowalski" OR "Paco" OR "Linear") "segmented control" OR "toolbar" OR "chrome"

# 组合 2：中文高质感独立设计师与实践笔记
site:x.com ("枯白" OR "@kubai087") (设计 OR 圆角 OR 搜索 OR 列表 OR 质感)

# 组合 3：延伸到设计师个人站 / 开源组件 / 设计原则库（常含完整原理与 CSS/交互细节）
("rauno.me" OR "emilkowal.ski" OR "kubai.design" OR "vibedesign.tips" OR "linear.app/now") <问题词>
```

### 2.2 按问题域分层的标杆观察名单（起点，非封闭集合）

每次调研优先挑 **2–3 个与当前界面形态最匹配的标杆**深挖，而不必面面俱到：

| 关注维度 | 优先检索的设计师 / 团队 / 公开站点 | 擅长亮点 |
| :--- | :--- | :--- |
| **中文桌面质感、同心圆角、去 AI 味、暗色微表面** | 枯白 Kubai（`@kubai087` / `kubai.design` / `vibedesign.tips` / Lumno / Glasswork） | 无框索引列表、同心圆角公式、悬停宽限节奏、暗色明度阶梯、去 AI 味自检 |
| **交互物理感、微动效、原生级细节** | Rauno Freiberg（`@raunofreiberg` / `rauno.me` / `interfaces.rauno.me`）、Emil Kowalski（`@emilkowalski_` / `emilkowal.ski` / Sonner / Vaul） | 交互阻尼、克制动效、弹窗锚定、触摸与键盘直觉、克制边界 |
| **极简列表、命令面板与单行信息密度** | Paco Coursey（`@pacocoursey` / `paco.me` / `cmdk`）、Raycast 团队 | 无冗余边框列表、键盘优先单行扫描、右侧附属信息对齐 |
| **高密度效率软件与 Chrome 减法** | Linear（Karri Saarinen `@karrisaarinen` 及 Linear UI Redesign 文章）、Zed、Cursor、Superhuman | “结构被感知而非被看见”、低噪点侧栏、无树线子任务嵌套、多上下文切换 |
| **窗口结构、标签与低频面板收放** | Arc / Dia（The Browser Company）、Things 3、Craft、Apple macOS HIG | 折叠侧栏、按需唤起入口、内容优先画布、工具栏克制化 |

> 若当前任务属于特定垂类（如数据可视化、代码编辑器、移动端表单、音频/视频时间轴），主动追加该垂类在 X 上活跃的一线设计师与代表产品。

---

## 3. 一手真实性核查与“去概念滤镜”法则

### 3.1 反编造 4 条底线
1. **必须实查实读**：只写本次真实检索并打开阅读过的公开帖子、文章、代码或产品公开页面。
2. **不补全记忆**：绝不凭印象编造某条推文的 URL、日期、数字或引语；若某线索无法打开原文（如 X 登录墙），明确注明仅基于可访问的摘要或转向作者个人站/公开文档核实。
3. **来源与推论分层**：标注哪些是作者明确写出的手法/数值，哪些是设计师基于画面归纳出的设计原则。
4. **尊重公开边界**：引用第三方产品只基于公开资料与可见交互，不依赖反编译或未公开拆包内容。

### 3.2 过滤 X 概念稿的“三问”
在 X 上看到高赞 UI 演示时，纳入参考前先过三问：
- **长文本压力**：把演示里的 2 个英文单词换成 30 字中英混排标题，布局还成立吗？
- **高频日常耐看度**：如果用户每天盯这个界面 6 小时，炫技玻璃/强发光/高频动效是加分还是干扰？
- **工程可行性**：该效果在当前产品的真实渲染引擎与性能预算内能稳定落地吗？

---

## 4. 一手调研提炼表（写入报告第 2 节）

每条保留的调研结果统一压成下面四列，确保直接服务于方案设计：

| 来源（设计师 / 产品 + 可核验出处） | 具体手法与参数 | 底层感知 / 交互原理 | 反模式 & 对本界面的迁移点 |
| :--- | :--- | :--- | :--- |
| 例：枯白 `vibedesign.tips`（同心圆角） | 外容器圆角 $R$ 与内边距 $p$ 满足 $r = R - p$ | 内外弧线共享圆心，消除“拼贴塑料感” | 反模式：外 8px 内 6px 配 3px 边距；迁移：统一所有分段槽与嵌套卡片圆角 |
| 例：Linear UI Redesign | 侧栏压低半档明度、去分割线、子任务靠缩进/微底块而非树线 | 减少边缘高频几何噪点，让视线直达内容 | 反模式：每层画 `1px` 闭合框 + 文件树弯钩线；迁移：用明度阶梯和排版对齐替代线框 |
