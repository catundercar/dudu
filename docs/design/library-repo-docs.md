# Library 纳入仓库设计稿与项目文档的统一机制

> **背景**：Fable 定稿提交进代码仓库的 `docs/design/auto-dream.md` 没有出现在 `pm-project` 右侧的 **Library** 面板里，面板中反而只看得到早期放进台账 `<PM_HOME>/projects/<slug>/docs/` 的旧草稿 `auto-dream-draft.md`。本文从第一性原理审视 Library 的信息架构，回答“台账文档与仓库设计稿是否两边都要、如何避免双份过时、如何跨项目无噪发现仓库文档、以及如何与现有分组/搜索/`@`/跨机查看无缝衔接”。撰写于 2026-11-24。
> **状态：设计方案，待拍板。** 按第 5 节分三步落地，每步附明确改动清单与验收标准。
> 文中“协调者”在代码标识符、路径与 CLI 中对应 `pm`。任何编码 agent（Claude Code、Codex、pi、agy……）都可以担任协调者或 worker。

---

## 0. 核心结论

1. **“两边都要”的直觉是对的，但两边不是平级副本，而是职责正交的上下游关系**：
   - **台账 `docs`（`<PM_HOME>/projects/<slug>/docs/`）是「私密工作夹」**：绑定项目主体、跨分支恒定、本机私有、支持面板内随时增删改与拖拽导入（带 `.history/` 快照回滚），适合放未定稿草稿、含隐私/内网信息的备忘、外部输入资料（PDF/截图），以及对仓库无写权限时的项目笔记。
   - **仓库文档（`<repo>/docs/design/` 等）是「版本化工程契约」**：绑定代码树提交、随分支审查（`review` → `land`）与代码同步演进、面向所有协作者与公开读者。
   - **现状之所以体验割裂**：`Store.library()`（`pmlib/store.py`）已经把 `<repo>/docs/research/` 接进了 `research` 组、把 `CLAUDE.md` / `AGENTS.md` 接进了 `instructions` 组，唯独漏掉了仓库设计稿与项目文档。结果造成**逆向淘汰**——越是没定稿的台账旧草稿越留在 Library 里，一旦通过审查定稿合入代码仓库，反而从 Library 消失。
2. **避免双份混乱不能照搬调研报告的去重方向，采用「显式毕业归档 + `superseded_by` 自动降权提示」双保险**：
   - 调研报告是“本地未脱敏原件优先、仓库公开件打标”；**设计稿的权威方向恰好相反——仓库定稿才是随代码演进的唯一真源，台账同名草稿是前身**。
   - **治本**：设计稿合入主分支后，协调者（或用户在面板一键点击）将台账前身草稿归档进已有的 `docs/.history/`（零数据丢失，随时可恢复）。
   - **防呆兜底**：若旧草稿未及时归档，后端通过显式 frontmatter 或归一化词干匹配（如 `auto-dream-draft.md` → `auto-dream` 命中 `docs/design/auto-dream.md`），为台账草稿附带只读计算字段 `superseded_by`。UI 将其沉底淡显并标 `已定稿` / `Superseded`、详情页顶部给出跳往仓库定稿与一键归档入口、搜索与 `@` 自动将其排在仓库定稿之后——**绝不静默删文件，也绝不会误引旧草稿**。
3. **新增第 4 个只读根 `repo_docs`（`Repo docs` / `仓库文档`），四层过滤保证任意项目开箱即用且不刷屏**：
   - 默认按 `git ls-files` 扫描仓库约定文档路径（`docs/` 或 `doc/`，以及根级 `design/`、`specs/`、`adr/`、`rfcs/`、`architecture/` 与 `ARCHITECTURE.md`、`DESIGN.md`），支持在台账 `library.json` 按项目覆盖或关闭，不污染目标代码仓库。
   - 严格只收文本文档扩展名（`.md` / `.markdown` / `.mdx` / `.rst` / `.adoc`），排除静态站点与构建/媒体/翻译目录、排除样板治理文件（`CHANGELOG.md` 等）、排除已归属 `research` 与 `instructions` 的路径，并设优先级分桶与 200 篇容量上限。在 `dudu` 自身 `docs/` 的 27 个文件中，精准滤掉 12 个 GitHub Pages 网页/图片/视频与 6 篇已归属 `research` 的报告，零配置命中全部 9 篇设计稿与指南。
4. **严格只读，全链路复用现有协议**：
   - `repo_docs` 在面板内严格只读（禁止直改主工作树产生未提交脏文件或绕过分支审查）；
   - 自动融入侧栏搜索、`Cmd+K` 全局搜索、`@Library` 提及（并在全局 `@` 搜索中自动消去与 `@Files` 的同路径重复项）、`[mentions]` 钩子路径解析与 `hc` 跨机远程查看；同时补上本地模式下任务合并（`merged`）与 `<repo>/docs` 变更触发 Library 刷新的链路。

---

## 1. 第一性原理审视：为什么“两边都要”，以及如何根治双份混乱

### 1.1 Library 的本质定位与现状缺口

在 `dudu` 已经确立的四平面信息架构（`docs/research/library-design.md`）中，项目数据按职责严格切分：

1. **调度与会话运行态**：在办线程、对话流、`handover.md`、投递游标——归看板与对话流，不进 Library；
2. **常驻规则与经验（Memory）**：产品拍板、协作规矩、参考指针与工程踩坑——独立为 Memory 页，按主题折叠并注入会话开场；
3. **合并门禁与调试原始材料**：`verify`、`.render-check`、探针脚本、过程截图——归验证与本地存证，不进 Library；
4. **项目知识书架（Library）**：**人类项目主与编码 agent 查阅项目规格、架构设计、调研结论与工程说明的统一入口**。

审视当前 `pmlib/store.py` 的 `Store.library(slug)`，三个现有根实际覆盖了：

- `docs`：`<PM_HOME>/projects/<slug>/docs/**` + 归档 `decisions.md`（可编辑）；
- `research`：台账 `docs/research/**`、`evidence/<topic>/README.md`、以及 `<repo>/docs/research/**` 公开副本（只读）；
- `instructions`：`<repo>` 下的 `CLAUDE.md`、`AGENTS.md`、`GEMINI.md`、`.claude/*.md`、`.claude/rules/*.md`（只读）。

可以看到，Library 并非“只看台账不看仓库”——它早已读取了仓库里的 `instructions` 和 `docs/research/`，却唯独漏掉了代码仓库中最核心的**架构与机制设计文档（如 `docs/design/*.md`、`docs/guide.md`）**。这直接导致定稿越正式、越贴近代码（进了 Git），在项目面板里反而越“隐身”。

### 1.2 批判性评估：为什么任何一边都不能吞并另一边

在决定“两边都要”之前，先检验两个看似更简单的单边替代方案：

- **反方方案 A：废除台账 `docs/`，所有项目文档一律进代码仓库 `docs/`**
  - **为何不成立**：
    1. **隐私与开源边界不可逾越**：用户拖进项目的客户需求原件、带内网机器地址的部署拓扑、含商业数据的参考 PDF，不能随 `git push` 发往公开仓库或外部协作方（对应项目既定原则 `publish-design-docs`：不含隐私的进仓库公开，含隐私的留本地）。
    2. **仓库写权限未必归当前项目独占**：用户常对第三方开源仓库或跨团队只读/受限仓库建立跟进项目，不能为了记项目文档而在对方仓库制造未跟踪文件或提交个人文档。
    3. **早期探索的写入摩擦过高**：想法刚成型时的草稿需要面板内随手改几行（毫秒级原子写 + `.history/` 回滚）；若每次改几个字都必须派 worker 建 worktree、提 commit、过 review，会把轻量构思变成重型流水线。

- **反方方案 B：Library 只读台账 `docs/`，仓库定稿合并时自动复制一份进台账**
  - **为何不成立**：
    1. **破坏单一真源（Split-Brain）**：设计定稿进入代码仓库后，后续功能迭代的 worker 会在代码分支上同步修订 `docs/design/*.md`。如果台账还存一份脱离 Git 的静态拷贝，任何一次分支外修改或 `git pull` 都会让两边分叉。
    2. **丢失与代码树的版本绑定**：仓库设计稿描述的是当前代码树的实现契约，理应直接从项目主工作树读取，而不是靠脆弱的双向同步脚本搬运字节。

将两者的本质属性拉通对比，边界非常清晰：

| 维度 | 台账文档 `<PM_HOME>/projects/<slug>/docs/` | 仓库文档 `<repo>/docs/design/` 等 |
| :--- | :--- | :--- |
| **真源锚点** | **绑定项目（Project-scoped）**：跨分支、跨重建恒定存在，甚至无本地仓库时仍可读 | **绑定代码树（Tree-scoped）**：与代码同提交、同评审、随 Git 历史演进 |
| **可见性与隐私** | **本机私有**：永不随 `git push` 外泄，可放敏感上下文与外部原件 | **随仓共享/公开**：协作者、worktree 内所有 worker 与开源读者直接可见 |
| **变更治理契约** | **轻量直改**：用户在面板点编辑或拖入文件，乐观版本锁 + `docs/.history/` 留底 | **Git 分支治理**：经 worker 分支提交、独立审查、`pm.py land` 合入主分支 |
| **典型内容形态** | 早期方案草稿（`*-draft.md`）、外部参考 PDF/图片、私有环境备忘 | 架构定稿（`design/`、`adr/`、`specs/`、`rfcs/`）、使用指南（`guide.md`） |
| **生命周期位置** | **上游孵化区** + **长期私密资料夹** | **下游正式归宿（工程契约档案）** |

结论：**两边都要保留，但必须建立从“台账孵化草稿”到“仓库正式定稿”的单向毕业认知，而不是把两边当成无关系的平行列表。**

### 1.3 双份并存时的「草稿毕业」与防混淆机制

为什么 `auto-dream-draft.md`（台账）和 `docs/design/auto-dream.md`（仓库）撞车会造成困扰？因为两者讨论的是同一个机制，但**权威性发生了反转**。

这里必须指出一个关键差异：**设计稿的去重方向与调研报告（`research`）完全相反，绝不能照搬 `_research_items()` 的逻辑**：

- **调研报告（`research`）**：本地 `evidence/` 或台账 `docs/research/` 里的是**未删减完整原件**，仓库 `docs/research/` 里的是**删掉内网细节的公开脱敏件**。因此 `_research_items()` 保留本地原件为主条目，仅在右侧打上 `已公开`（`Published`）标记。
- **设计文档（`docs` vs `repo_docs`）**：台账里的 `auto-dream-draft.md` 是**审查前的早期草稿**（例如 `auto-dream.md` 第 0 节明确否决并修订了草稿里的 7 处设计！），仓库里的 `docs/design/auto-dream.md` 才是**唯一有效的定稿**。若照搬“有本地则隐藏仓库”，会把正确定稿藏起来、只把被否决的草稿喂给用户和 `@` 提及，完全颠倒黑白。

同时，也**不能仅凭文件名相似就静默删除或彻底隐藏台账文件**——用户完全可能在台账 `docs/billing-draft.md` 中保留了不便写入公开设计稿 `docs/design/billing.md` 的私密费率测算。

正确的做法是**「显式毕业归档（治本） + 确定性关联降权（防呆兜底）」**：

#### 第一层：显式毕业归档（复用 `docs/.history/`，零新存储概念）

台账草稿一旦演进为仓库正式设计稿并合入主分支，它的历史使命已经完成，应当从活跃 `Documents` 退入 `docs/.history/`：

1. **协调者收尾规矩（写入 `pm-playbook.md`）**：当某个设计或重构线程以台账 `docs/<draft>.md` 为蓝本，将最终方案提交进仓库 `docs/` 并完成 `land` 合并后，协调者顺手执行现有的 `pm.py project delete <slug> docs/<draft>.md --why "graduated to <repo-path>"`。`Store.delete_doc` 原生将其原子移入 `docs/.history/`，不丢失任何历史字节，需要对比初稿时随时可在 Library 的「历史归档（History）」中查看或恢复。
2. **面板内一键归档**：若草稿由用户手写、未经协调者清理，用户在面板点开该草稿即可一键归档（见下）。

#### 第二层：`superseded_by` 自动识别、视觉降权与互跳提示（未归档时的防呆兜底）

只要台账旧草稿还没归档，系统就在读取 `Store.library(slug)` 时用纯确定性规则识别“同题定稿”，不改盘上任何文件：

1. **匹配规则（优先级从高到低）**：
   - **显式声明优先**：台账 Markdown 顶部的 YAML frontmatter 若写有 `superseded_by: docs/design/auto-dream.md`（且该路径在 `repo_docs` 中存在），直接关联；
   - **归一化词干精确匹配（Normalized Stem）**：提取文件名去扩展名后的小写词干，剥离单层草稿词缀（前缀 `^(?:draft|wip|rfc|proposal)[-_]+`，后缀 `[-_]+(?:draft|wip|rfc|proposal|old|bak|v\d+)$`）。例如：
     - 台账 `auto-dream-draft.md` → 归一化词干 `auto-dream`；
     - 仓库 `docs/design/auto-dream.md` → 词干 `auto-dream`。
     两者词干精确相等（且词干长度 ≥ 3，排除 `readme`、`index`、`notes`、`todo` 等泛化词），即判定该台账草稿已有仓库定稿（若仓库存在多篇同词干文档，优先匹配 `design/specs/adr/rfcs/architecture` 目录下的定稿）。
2. **命中后的四处一致表现**：
   - **数据标记**：台账该条目附带只读字段 `"superseded_by": "docs/design/auto-dream.md"`。
   - **Library 侧栏列表**：仓库 `docs/design/auto-dream.md` 在 `仓库文档` 组正常全对比度展示；台账 `auto-dream-draft.md` 在 `项目文档` 组内自动排到活跃文档末尾（`decisions.md` 归档之前）、降低不透明度（`.opacity(.75)`），右侧标注 `已定稿` / `Superseded`。
   - **旧草稿详情页顶部提示条**：点开 `auto-dream-draft.md` 时，正文顶部渲染醒目提示条：
     > 已在仓库定稿：`docs/design/auto-dream.md` 　`[查看定稿]` · `[归档草稿]`
     点击「查看定稿」直接切到 `repo_docs/docs/design/auto-dream.md`；点击「归档草稿」调用 `projectDeleteArgv` 将旧草稿移入 `docs/.history/`。
   - **搜索与 `@` 提及自动降权**：在侧栏搜索、`Cmd+K` 全局搜索与 `@` 弹层中，带 `superseded_by` 的草稿排序优先级低于正常文档（`@` 弹层 `tieRank` 从 `1` 降为 `3.5`，搜索 `rank + 1`）。用户输入 `@auto-dream` 时，**排在第一位的永远是仓库定稿 `docs/design/auto-dream.md`**。

---

## 2. 仓库文档的发现、过滤与防刷屏机制

仓库目录不是专门为 dudu 准备的纯净空间：它可能像 `dudu` 一样把 GitHub Pages 静态站（`index.html`、`.mp4`、`.png`）混在 `docs/` 里，可能用单数 `doc/` 或根级 `rfcs/`，也可能是拥有几百页用户手册的 Docusaurus / VitePress 文档站。发现机制必须同时满足**零配置开箱即用**与**大仓库绝不刷屏**。

### 2.1 四阶段发现与过滤流水线

```mermaid
flowchart LR
    A["1. 确定扫描入口\n默认约定路径 或 library.json"] --> B["2. 枚举候选文件\ngit ls-files 优先 / 安全遍历兜底"]
    B --> C["3. 多维噪音过滤\n扩展名 + 静态站目录 + 样板文件 + 跨根去重"]
    C --> D["4. 优先级分桶与防刷屏截断\nTier 0-3 排序 + 200 篇硬上限 + lstat 校验"]
```

#### 第 1 阶段：扫描入口（默认约定 + 项目级配置覆盖）

1. **零配置默认约定（未配置 `repo_docs` 时生效）**：
   **绝不全仓通扫 `**/*.md`**（否则 monorepo 子包的 `CHANGELOG.md`、`testdata/*.md`、PR 模板会淹没面板），只扫描工程界公认的文档位置：
   - **主文档目录**：若 `<repo>/docs` 存在则扫描 `docs`；否则若 `<repo>/doc` 存在则扫描单数 `doc`（兼容 Rust、C/C++、Vim/Unix 等项目惯例）。
   - **根级架构与规格目录**：若仓库根直接存在 `design/`、`specs/`、`adr/`、`rfcs/`、`architecture/` 目录，一并纳入。
   - **根级核心架构单文件**：仓库根下精确匹配（大小写不敏感）`ARCHITECTURE.md`、`DESIGN.md`。
     - *为什么默认不收仓库根 `README.md`？* 几乎所有仓库都有根 `README.md`，它通常是安装徽章与对外门面，且容易与 `docs/README.md` 重名混淆；需要引用时 `@Files` 敲 `@README` 已能秒选，若用户希望放进 Library 也可通过下方配置一行加入。

2. **项目级配置覆盖（存于台账 `<PM_HOME>/projects/<slug>/library.json`）**：
   - **为什么配置存在台账 `library.json`，而不是要求往代码仓库提交 `.dudu.json`？**
     对公司公共仓库或第三方开源库，用户不应为了个人项目管理视图而往仓库提交工具专属配置文件；台账侧的 `library.json` 已经存在（现用于记录 `decisions.hidden`），自带文件锁与原子写（`Store.set_library_state`），跨分支恒定生效。
   - **可选配置字段**：
     ```json
     {
       "decisions": { "hidden": true, "at": "2026-11-20 14:00" },
       "repo_docs": {
         "enabled": true,
         "include": ["docs", "packages/core/docs", "README.md"],
         "exclude": ["docs/api-generated", "docs/legacy"]
       }
     }
     ```
     - `enabled: false`：对纯前端营销站或不需要展示仓库文档的项目一键关闭；
     - `include`：非空时替代默认扫描入口（支持仓库相对目录或单文件路径，例如 monorepo 指定 `packages/server/docs`）；
     - `exclude`：在内置过滤规则之上，额外排除指定仓库相对路径前缀。

#### 第 2 阶段：枚举源（`git ls-files` 优先，非 Git 目录安全遍历兜底）

- **Git 仓库路径（主路径）**：一次执行 `git --literal-pathspecs -C <repo> ls-files -z -- <entry_paths>`（超时 10s）。
  - **优势**：单次子进程调用通常 < 10 ms；**天然遵守 `.gitignore`**，自动滤除未跟踪的本地构建产物（如 `docs/_site/`、`docs/.vitepress/dist/`、临时生成物）与未入库草稿。
- **非 Git 目录兜底**：若 `<repo>` 不是 Git 仓库或环境无 `git`，回退到 `Store._scan_tree` 安全目录遍历（跳过隐藏项与符号链接）。
- 所有候选最终统一经 `Store._walk_file(repo, parts, label)` 校验：必须是位于 `<repo>` 真实路径内部的常规文件（`S_ISREG`），拒绝任何符号链接（`S_ISLNK`）。

#### 第 3 阶段：多维噪音过滤（滤除静态站点、媒体与重叠职责）

1. **文本文档扩展名白名单**：
   - 默认仅收录：`REPO_DOC_EXTENSIONS = {".md", ".markdown", ".mdx", ".rst", ".adoc"}`（若用户在 `library.json` 的 `include` 中显式写明单个文本文件路径如 `"doc/rfc.txt"`，放宽至 `TEXT_EXTENSIONS`）。
   - 直接排除静态网页与配置（`index.html`、`*.css`、`*.js`、`sitemap.xml`、`robots.txt`、`.nojekyll`）以及图片/音视频/二进制资产（`*.png`、`*.jpg`、`*.svg`、`*.gif`、`*.mp4`、`*.webm`、`*.pdf`）。这些媒体在面板内本就无法按文本文档阅读（点击只会提示二进制文件），列出来纯属视觉噪音。
2. **目录段黑名单（大小写不敏感）**：
   - 任何以 `.` 或 `_` 开头的路径段：一次性排除 `.vitepress`、`.docusaurus`、`.github`、`.obsidian`、`_site`、`_build`、`_static`、`_templates`、`_includes`、`_layouts`、`__snapshots__` 等静态站框架内部目录；
   - 静态资源、构建输出、依赖、历史版本快照与多语言翻译镜像目录：
     ```text
     node_modules, vendor, dist, build, out, target,
     public, static, assets, images, img, media, videos, fonts, styles, stylesheets, scripts, theme, themes,
     versioned_docs, versioned_sidebars, i18n, locales, translations,
     fixtures, testdata
     ```
   - 扫描相对深度上限：`REPO_DOCS_DEPTH = 4`（与现有 `RESEARCH_DEPTH = 4` 一致）。
3. **开源治理样板文件名黑名单（大小写不敏感）**：
   - 排除 `changelog.md`、`history.md`、`releases.md`、`contributing.md`、`code_of_conduct.md`、`license.md`、`security.md`、`pull_request_template.md`、`issue_template.md`。
4. **跨 Root 职责去重（严禁同一文件在 Library 出现两次）**：
   - 排除 `<repo>/docs/research/**` 与 `<repo>/evidence/**`（已由 `research` 组管理）；
   - 排除 `INSTRUCTION_FILES` 与 `.claude/rules/*.md`（已由 `instructions` 组管理）。

> **在 `dudu` 自身仓库上的实测过滤结果**：
> 当前 `dudu/docs/` 下共有 27 个路径：
> - 静态站与媒体资产 12 个（`index.html`, `.nojekyll`, `robots.txt`, `sitemap.xml`, `dudu.svg`, `demo.gif`, `og.png`, `preview.png`, `shot-threads.png`, `shot-workspace.png`, `threads-lifecycle.png`, `library-memory.mp4`, `quote-and-at.mp4`, `threads-lifecycle.mp4` 等）→ **扩展名与前缀规则全部拦截**；
> - 公开调研报告 6 篇（`docs/research/*.md`）→ **跨 Root 去重规则拦截（留在 `调研报告` 组）**；
> - **最终进入 `仓库文档` 组：恰好 9 篇**——`docs/design/` 下全部 7 篇设计定稿（含 `auto-dream.md`）+ `docs/guide.md` + `docs/README.md`。**召回率 100%，噪音 0。**

#### 第 4 阶段：防刷屏容量闸门与折叠策略（面向大型文档仓库）

当用户将 dudu 挂在一个 `docs/` 下有数百篇终端用户教程或自动生成 API 参考的大型仓库时：

1. **四级优先级分桶与硬上限（`REPO_DOCS_MAX = 200`）**：
   - **Tier 0**：`library.json` 中显式指定的单文件；
   - **Tier 1（设计/架构核心区）**：路径段含 `design`、`specs`、`spec`、`adr`、`decisions`、`rfcs`、`rfc`、`architecture` 的文档，以及根级 `ARCHITECTURE.md` / `DESIGN.md`；
   - **Tier 2（顶层概览）**：扫描入口直接子文件（如 `docs/guide.md`、`docs/README.md`）；
   - **Tier 3（其余常规子目录）**：如 `docs/guides/**`、`docs/api/**`。
   若候选总数超过 `REPO_DOCS_MAX`（200 篇），按 Tier 0 → Tier 1 → Tier 2 → Tier 3 保序截断，确保核心设计稿绝不被海量教程挤掉，并在 `roots` 元数据中标记 `"truncated": true, "total": N`（其余任意文件仍可通过容量 20,000 的 `@Files` 检索）。
2. **元数据读取开销受控**：
   - 对入选的 ≤ `DOCUMENT_MAX`（1 MB）Markdown 文件复用 `_read_doc_meta()` 提取首标题（`title`）、首段摘要（`summary`）和关联任务（`task`）。200 篇上限下本地顺序读头部仅数毫秒，远程 `hc` 单次 JSON 返回体积控制在数十 KB 内。
3. **自适应文件夹展开策略**：
   - 当 `repo_docs` 总文件数 ≤ 15 时，所有子目录（如 `design/`）默认展开，打开 Library 一眼看到 `auto-dream.md`；
   - 当总文件数 > 15 时，仅 Tier 1 设计类子目录默认展开，其余次级目录默认折叠，保持首屏紧凑。

---

## 3. 分组、权限与全链路交互兼容

### 3.1 侧栏分组：为什么独立为第 4 组 `repo_docs`，而不并入现有 `docs`

对比两种分组方式：

| 方案 | 做法 | 致命问题 / 优势 |
| :--- | :--- | :--- |
| **合并进现有 `Documents`（不采用）** | 把仓库文档塞进 `root: "docs"` 列表 | 1. **读写心智冲突**：`Documents` 组承接新建（`+`）与拖拽上传，若混入只读仓库文件，用户把文件拖进面板里的 `design/` 文件夹会误以为写进了代码仓库，实际却落进了台账私有目录。<br>2. **路径命名空间碰撞**：台账 `docs/guide.md` 与仓库 `docs/guide.md` 同名时，`library:docs/guide.md` 无法消歧。 |
| **复用现有预览根 `repo`（不采用）** | 把 `root: "repo"` 直接加入 `LIBRARY_ROOTS` | **破坏安全边界与现有契约**：`root: "repo"` 专供 `@Files`（`file:<path>`）全仓代码只读预览，`hooks.py` 与 `model.js`（及 `test_views.py`、`model.test.mjs`）明确禁止 `library:repo/...` 任意读取仓内敏感配置。 |
| **新增独立根 `repo_docs`（采用）** | `LIBRARY_ROOTS = ("docs", "repo_docs", "research", "instructions")` | 权限边界一目了然（组头统一带 `🔒 只读`）、路径零冲突（`library:repo_docs/docs/design/auto-dream.md`）、与既有 `research` / `instructions` 完全同构。 |

侧栏自上而下的四组结构：

```text
[ 搜索 Library…                ] [+] [↑] [↺]
──────────────────────────────────────────────
项目文档  1
  📄 auto-dream-draft.md            已定稿  11-22   ← 命中 superseded_by：沉底淡显
     autoDream 后台记忆整理草稿

仓库文档  9                                🔒 只读
  ▾ design                                   7 项
    📄 auto-dream.md                        11-24  ↗
       后台记忆整理（autoDream）：审查结论与可执行定稿
    📄 pm-py-pass-two.md                    11-23  ↗
       pm.py 第二轮重构方案
    …
  📄 guide.md                               11-20
     dudu 使用指南
  📄 README.md                              11-24
     dudu docs

调研报告  6                                🔒 只读
  📊 library-design · Project Library…  已公开 11-19  ↗
  …

仓库说明  3                                🔒 只读
  📄 CLAUDE.md                              11-21
  📄 AGENTS.md                              11-18
```

两个关键交互细节：

1. **视觉树剥离单层冗余 `docs/` 外壳，数据路径保持仓库真值**：
   - 当文件位于 `docs/...`（或 `doc/...`）下且用户未配多前缀 monorepo `include` 时，前端构建分组树（`buildRepoDocsRows`）自动省掉最外层多余的 `▾ docs` 文件夹行，直接展示 `▾ design`、`guide.md`，避免在「仓库文档」标题下再套一层无意义的 `docs` 缩进；
   - 但条目的规范 `path` 始终保持完整的仓库相对路径 `docs/design/auto-dream.md`（悬停提示、详情页顶部面包屑、`复制路径`、`@` 提及链接全部使用真实仓库相对路径）。若同时存在根级 `ARCHITECTURE.md` 或 `rfcs/0001.md`，则自然并列在同一层级。
2. **文件名作主标题 + H1 作副标题 + 来源线程一键回跳**：
   - 与 `research`（文件名全是 `README.md`，故用 H1 当主标题）不同，仓库设计稿拥有高辨识度的英文短文件名（`auto-dream.md`、`model-selection.md`）。主行显示文件名、第二行显示 `_read_doc_meta` 提取的 `# H1` 标题（若无 H1 则回退首段 `summary`），既方便一眼扫出文件名，又能在中英文关键词下直观理解内容。
   - 后端对 `docs/design/<stem>.md` 同样调用现有的 `_read_doc_meta`（识别正文/frontmatter 中的 `task`）与 `_task_for_topic(slug, stem, tasks)`（匹配分支 `dev/<stem>` 或任务 `<slug>-<stem>`），命中时在行尾渲染现成的 `↗`（`hook-up`）按钮，一键跳回产出这篇设计稿的线程。

### 3.2 为什么仓库文档在 Library 中严格只读

`repo_docs` 与 `research`、`instructions` 一样固定 `writable: False`（`WRITABLE_ROOTS` 保持 `("docs", "memory", "personal")` 不变），理由来自 dudu 的核心工程不变式：

1. **保护主工作树干净（Clean Main Checkout）**：`Store._repo_dir(slug)` 指向主工作树。所有代码与仓库文档修改在 dudu 中都通过独立 worktree 分支完成并由 `pm.py land` 合并；若允许在面板直改主工作树文件，会产生未提交脏改动，直接阻塞后续任务的 `git merge` 与分支切换，且绕过了代码/设计审查。
2. **避免双轨历史冲突**：台账 `docs` 靠 `docs/.history/` 存旧版；仓库文档的历史真源是 `git log`。在面板内直改既不产生 commit，也不应往仓库写 `.history/`。
3. **修改闭环依然顺畅**：`repo_docs` 详情页顶部栏复用 `root === 'repo'` 已有的「复制路径」按钮（复制 `docs/design/auto-dream.md`）；需要修订定稿时，用户在主输入框敲 `@auto-dream.md 把冷却改成 12 小时` 发给协调者即可派发线程完成修订与合入。

### 3.3 搜索、`@` 提及、文内链接、跨机 `hc` 与实时刷新兼容

1. **侧栏搜索与 `Cmd+K` 全局项目搜索（`search.js`）**：
   - `LIBRARY_ROOTS` 加入 `'repo_docs'` 后，`searchLibrary()` 与 `searchProjectLibrary()` 自动覆盖 `repo_docs` 的文件名、仓库路径、H1 标题、首段摘要、来源任务标题及已缓存全文。
   - **预取优化（`prefetchLibraryDocs`）**：当前 `main.js` 仅预取最多 6 篇 ≤ 64 KB 的 `root === 'docs'` 文档；扩展为在**本机模式（`!this.machine`）**下按修改时间倒序预取前 8 篇 ≤ 64 KB 的活跃 `docs` + `repo_docs` 文本，使未点开过的核心设计稿也能命中正文全文搜索。远程机器（`this.machine`）不批量发预取子进程，直接利用 `library` 接口已带回的 `title` + `summary` 检索，按需点开再读全文。

2. **`@` 提及与跨分类去重（`buildMentionMenu` + `hooks.py`）**：
   - `@` → `Library` 二级菜单自动列出 `repo_docs` 条目（右侧类型标签显示 `仓库文档` / `Repo doc`），选中后生成行内胶囊，底层序列化为标准格式：
     `[@auto-dream.md](library:repo_docs/docs/design/auto-dream.md)`
   - **消除全局 `@` 搜索的双重候选（关键细节）**：仓库文档同时存在于 `libraryItems`（`library:repo_docs/...`）和 `git ls-files` 产出的 `repoFiles`（`file:...`）中。在 `buildMentionMenu` 的**全局平铺搜索模式（`category === 'all'` 且有输入词）**下，收集 `repo_docs` 与 `instructions` 已收录的仓库相对路径集合，跳过 `indexedFiles` 中的同路径条目——敲 `@auto-dream` 只出现一条带完整标题摘要的 Library 候选，点击胶囊直接在 Library 面板打开 Markdown 视图（进入显式的 `@` → `Files` 子菜单时仍保留完整仓库文件列表）。
   - **协调者上下文解析（`pmlib/hooks.py:mention_hints`）**：由于 `"repo_docs"` 在 `DOCUMENT_ROOTS` 中且 `Store.document_path(slug, "repo_docs", rel)` 返回 `(<repo>/<rel>, stat)`，用户发出含 `[@auto-dream.md](library:repo_docs/docs/design/auto-dream.md)` 的消息时，提交钩子无需新增特判即自动输出：
     `library:repo_docs/docs/design/auto-dream.md -> <repo>/docs/design/auto-dream.md`

3. **文档内相对链接跨根跳转（`resolveContextLink` 增强）**：
   - 仓库文档（如 `docs/README.md` 索引表或 `docs/design/auto-dream.md`）常含相对链接（如 `[pm-py-refactor.md](pm-py-refactor.md)`、`[../research/library-design.md](../research/library-design.md)` 或指向源码的 `[pmlib/store.py](../../mods/...)`）。
   - 扩展 `resolveContextLink` 与 `followDocLink`：当 `currentDoc.root === 'repo_docs'` 时，先计算出仓库相对目标路径 `resolved`：
     1. 命中 `repo_docs` 条目 → 直接在 Library 打开该仓库文档；
     2. 形如 `docs/research/<rel>` 且命中 `research` 组条目（`published === "published/<rel>"` 或 `path === "published/<rel>"`）→ 直接切到对应的调研报告；
     3. 其他非逃逸仓库相对路径 → 回退调用 `openRepoFile(resolved)`（走 `root: "repo"` Git 跟踪校验预览源码），让 `docs/README.md` 真正成为面板内可点击浏览的项目总目录。

4. **跨机器远程查看（`hc`）与新旧版本斜交兼容**：
   - `repo_docs` 元数据随原有的单次 `pm.py project library <slug>` JSON 一并返回，点击正文走原有的 `pm.py project file --root repo_docs -- <slug> <path>`，在 `this.machine` 模式下经 `remotePmArgv` 在远端机器本地完成读取，**零新增 `hc` 往返**。
   - **双向向后兼容**（适配 `dev` 机按需更新策略）：
     - 新桌面端连旧远端 `pm.py`：返回 JSON 无 `repo_docs` 条目，前端自然不显示 `仓库文档` 分组，无报错；
     - 旧桌面端连新远端 `pm.py`：旧版 `validLibraryPayload` 按旧 `LIBRARY_ROOTS` 过滤，自动忽略不认识的 `root: "repo_docs"`，不崩不乱；
     - 本地无仓库目录（`_repo_dir(slug) is None`）：`_repo_docs_items` 返回空数组，台账 `docs` 与 `research` 正常展示。

5. **修复本地合并后的刷新盲区（`PmProject.arm` & `refresh`）**：
   - **现状隐患**：目前本地模式下 `libraryStale` 仅由 `watchFolder(<ledgerHome>/projects)` 触发；当 worker 分支合入主工作树新增 `docs/design/xxx.md` 时，台账 `projects/<slug>/docs/` 并未变动，已打开过 Library 的视图不会重读 `library`。
   - **轻量修复**：
     1. 本地模式下若主工作树存在 `docs/`（或 `doc/`）子目录，在 `arm(cx)` 中对其单独挂载一个 `watchFolder`（**绝不监听整个 `<repo>` 根目录**，避开编译产物与 `node_modules` 事件风暴），变动时清空 `repo_docs/` 缓存并触发 `onLocalLibraryChange`；
     2. 在 `refresh(cx)` 中记录当前项目已 `merged` 任务集合签名（或任务状态跃迁），一旦检测到新合并任务，同步将 `libraryStale = true`（以及 `repoFilesRead = false`），保证设计线程一经 `land` 合并，Library 与 `@` 立即刷出新定稿。

---

## 4. 数据结构与接口契约

### 4.1 `pm.py project library <slug>` 返回结构

```json
{
  "project": "dudu",
  "roots": [
    {
      "id": "docs",
      "writable": true,
      "accepts": {
        "extensions": [".adoc", ".avif", "..."],
        "max_bytes": 20971520,
        "edit_max_bytes": 1000000
      }
    },
    {
      "id": "repo_docs",
      "writable": false,
      "truncated": false,
      "total": 9
    },
    { "id": "research", "writable": false },
    { "id": "instructions", "writable": false }
  ],
  "files": [
    {
      "root": "docs",
      "path": "auto-dream-draft.md",
      "kind": "md",
      "size": 14280,
      "modified": "2026-11-22T16:10:00Z",
      "version": "180bc9a12f0-37c8",
      "writable": true,
      "show": "text",
      "title": "autoDream 后台记忆整理草稿",
      "superseded_by": "docs/design/auto-dream.md"
    },
    {
      "root": "repo_docs",
      "path": "docs/design",
      "kind": "folder",
      "size": 0,
      "modified": "2026-11-24T09:30:00Z",
      "writable": false
    },
    {
      "root": "repo_docs",
      "path": "docs/design/auto-dream.md",
      "kind": "md",
      "size": 24890,
      "modified": "2026-11-24T09:30:00Z",
      "version": "180c5102a10-613a",
      "writable": false,
      "show": "text",
      "title": "后台记忆整理（autoDream）：审查结论与可执行定稿",
      "summary": "语义判断交给一个只读 helper，校验、备份、写文件、重建索引全部由 pm.py 的确定性代码完成……",
      "task": "dudu-auto-dream-design",
      "task_title": "autoDream 后台记忆整理设计定稿"
    }
  ]
}
```

- **单文件读取**：`pm.py project file <slug> --root repo_docs -- docs/design/auto-dream.md`（或 `pm.py project file <slug> repo_docs/docs/design/auto-dream.md`）。`Store._locate` 校验该路径必须属于当前项目的允许仓库文档集合（即通过发现与过滤规则，或显式 `include` 且位于 `<repo>` 内非隐藏、非符号链接常规文件），越权路径一律抛 `FileNotFoundError`，绝不成为任意文件读取口。
- **可选配置 CLI**：
  ```bash
  pm.py project repo-docs <slug>                          # 查看当前生效的扫描入口与过滤配置（JSON）
  pm.py project repo-docs <slug> --include docs --include packages/core/docs --exclude docs/api
  pm.py project repo-docs <slug> --off                    # 关闭该项目的 repo_docs 扫描（--on 重新开启）
  pm.py project repo-docs <slug> --reset                  # 清除自定义配置，恢复默认约定
  ```

### 4.2 界面双语文案表（`mods/pm-project/model.js` `STRINGS`）

遵循 `ui-labels-i18n` 规则，所有新增标签中英成对定义：

| Key | `en` | `zh` |
| :--- | :--- | :--- |
| `libraryGroupRepoDocs` | `'Repo docs'` | `'仓库文档'` |
| `mentionTypeRepoDoc` | `'Repo doc'` | `'仓库文档'` |
| `supersededLabel` | `'Superseded'` | `'已定稿'` |
| `supersededBanner` | `path => \`Finalized in repo: ${path}\`` | `path => \`已在仓库定稿：${path}\`` |
| `openSupersededTarget` | `'Open repo doc'` | `'查看定稿'` |
| `archiveDraft` | `'Archive draft (kept in history)'` | `'归档草稿（留存历史）'` |
| `repoDocsTruncated` | `(shown, total) => \`Showing ${shown} of ${total} repo docs (use @Files for the rest)\`` | `(shown, total) => \`已展示 ${shown} / ${total} 篇仓库文档（其余可用 @Files 检索）\`` |

---

## 5. 分步落地方案、改动清单与验收标准

严格遵守 `pmlib` 分层架构（`tests/test_layers.py`）与五个零容忍 AST 棘轮（禁止函数内延迟 import、禁止业务层 `print` / `sys.exit` / `argparse.Namespace` / 直接调 `hc`；复用已加入 `INTERNAL_PROJECT_FILES` 的 `library.json`，不新增内部元数据文件名）。

### 第 1 步：后端发现、过滤、`superseded_by` 关联与 CLI（`pmlib`）

- **改动文件**：
  1. `mods/pm-dash/skill/scripts/pmlib/store.py`（第 1 层）：
     - `DOCUMENT_ROOTS` 与 `LIBRARY_ROOTS` 加入 `"repo_docs"`；新增常量 `REPO_DOC_EXTENSIONS`、`REPO_DOCS_SKIP_DIRS`、`REPO_DOCS_SKIP_FILES`、`REPO_DOCS_MAX = 200`、`REPO_DOCS_DEPTH = 4`、`DRAFT_AFFIX_RE`。
     - 新增 `_repo_docs_config(slug)`（读取 `library_state(slug).get("repo_docs")`）、`_repo_docs_files(slug)`（按第 2 节四阶段流水线枚举与过滤，返回仓库相对路径与文件夹行）及 `_repo_docs_items(slug)`（补充 `_read_doc_meta` 与 `_task_for_topic` 来源线程关联）。
     - 在 `_docs_items(slug)`（或 `library(slug)` 组装处）计算归一化词干映射，为命中仓库定稿的台账草稿打上 `superseded_by`（及 frontmatter `superseded_by:` 显式覆盖）。
     - 在 `_locate(slug, root, parts, label)` 中增加 `root == "repo_docs"` 分支：校验目标位于 `_repo_dir(slug)` 下且属于允许的仓库文档路径集合，复用 `_walk_file` 防符号链接与目录穿越。
  2. `mods/pm-dash/skill/scripts/pmlib/commands/project.py`（第 4 层）：
     - 更新 `project file --root` 与 `project library` 帮助说明；
     - 新增子命令 `pm.py project repo-docs <slug> [--include ...] [--exclude ...] [--on | --off] [--reset]`，通过 `ctx.store.set_library_state(slug, repo_docs=...)` 原子持久化。
- **单测与验收标准（`tests/test_views.py`、`tests/test_layers.py`）**：
  - 构造混有 `docs/index.html`、`docs/.nojekyll`、`docs/demo.gif`、`docs/library.mp4`、`docs/.vitepress/config.js`、`docs/i18n/zh/a.md`、`docs/CHANGELOG.md`、`docs/research/r1.md`、`CLAUDE.md` 与 `docs/design/auto-dream.md`、`docs/guide.md` 的仓库夹具：验证 `store.library(slug)` 的 `repo_docs` **仅返回** `docs/design`（folder）、`docs/design/auto-dream.md`、`docs/guide.md`，无跨根重复、无静态站杂物；
  - 验证单数 `doc/` 目录、根级 `rfcs/`、`ARCHITECTURE.md` 以及非 Git 目录兜底均能正确发现；
  - 验证超过 `REPO_DOCS_MAX` 时 Tier 1（`docs/design/*`）100% 保留且 `roots` 标记 `truncated: true`；
  - 验证台账存在 `docs/auto-dream-draft.md` 时自动获得 `"superseded_by": "docs/design/auto-dream.md"`，而 `docs/notes.md` / `docs/README.md` 等泛化名不误标；
  - 验证 `project file --root repo_docs` 可正常读取 `docs/design/auto-dream.md`，而读取 `docs/index.html`、`.git/config`、符号链接或 `project save/delete --root repo_docs` 一律按契约拒绝；
  - `python3 mods/pm-dash/skill/scripts/tests/test_layers.py` 全绿。

### 第 2 步：前端分组树、定稿提示条、搜索/`@` 去重与合并刷新（`mods/pm-project`）

- **改动文件**：
  1. `mods/pm-project/model.js`：
     - `LIBRARY_ROOTS` 与 `ALL_DOC_ROOTS` 加入 `'repo_docs'`；`STRINGS.en` / `STRINGS.zh` 补齐 4.2 节词条；
     - `validDocItem` 保留 `superseded_by`；`validLibraryPayload` 保留 `roots` 上的 `truncated` / `total`；
     - `docRank` 将带 `superseded_by` 的台账草稿排在普通文档之后、`archive`（`decisions.md`）之前；
     - 新增 `buildRepoDocsRows` 并在 `libraryGroups` 中输出 `id: 'repo_docs'` 只读分组（自动剥离单层公共 `docs/` 或 `doc/` 视觉前缀，<= 15 篇时默认展开，> 15 篇时仅展开设计类子目录）；
     - `documentView` 暴露 `supersededBy`；`resolveContextLink` 支持 `repo_docs` 同根跳转、跳往 `research` 公开报告、以及返回 `{ root: 'repo', path }` 交由源码预览兜底；
     - `searchLibrary` 与 `buildMentionMenu`：纳入 `repo_docs`，对 `superseded_by` 草稿降权；在 `buildMentionMenu` 的全局搜索模式（`activeCat === 'all'`）下按路径消去 `repoFiles` 中与 `repo_docs` / `instructions` 重复的条目。
  2. `mods/pm-project/search.js`：
     - Library 搜索结果行的图标适配 `repo_docs`（文档图标 + 只读路径提示），对 `superseded_by` 行应用淡显与低优先级排序。
  3. `mods/pm-project/main.js`：
     - `libraryPanel` / `libraryRow`：渲染 `仓库文档` 分组、`已定稿` 标签与超限截断提示；
     - `docDetailView`：为 `repo_docs` 启用顶部「复制路径」按钮；当打开带 `superseded_by` 的台账草稿时，顶部渲染「已在仓库定稿」提示条（含「查看定稿」跳转与「归档草稿」按钮）；
     - `prefetchLibraryDocs`：在 `!this.machine` 下将预取范围扩至前 8 篇 ≤ 64 KB 的活跃 `docs` + `repo_docs`；
     - `arm(cx)` 与 `refresh(cx)`：本机若 `<repo>/docs`（或 `doc`）目录存在则挂载轻量 `watchFolder` 清理 `repo_docs/` 缓存并刷新；`refresh` 检测到项目 `merged` 任务集合变化时置 `libraryStale = true` 与 `repoFilesRead = false`。
- **单测与验收标准（`node --test mods/pm-project/model.test.mjs`）**：
  - 覆盖 `libraryGroups` 四分组排序、单层 `docs/` 视觉剥离、大目录默认折叠、`superseded_by` 沉底淡显；
  - 覆盖 `@auto-dream` 全局提及搜索中 `library:repo_docs/docs/design/auto-dream.md` 排第一、`docs/auto-dream-draft.md` 排其后、且不出现重复的 `file:docs/design/auto-dream.md`；
  - 覆盖 `resolveContextLink` 从 `docs/README.md` 跳往 `docs/design/*.md`、`docs/research/*.md` 及仓内代码路径；
  - 覆盖旧远端无 `repo_docs` 返回时的优雅降级。

### 第 3 步：协调者工作流规矩与全链路渲染验收

- **改动文件**：
  - `mods/pm-dash/skill/references/pm-playbook.md`、`mods/pm-dash/skill/SKILL.md`：
    - 在 `library:<root>/<path>` 说明中补充 `repo_docs` 根；
    - 在合并收尾章节补充“台账草稿毕业规矩”：当设计/方案任务将原先存于台账 `docs/` 的草稿定稿提交进仓库并完成 `land` 后，顺手归档台账中的旧草稿（移入 `docs/.history/`）。
  - `docs/README.md`：将本文档与后续实现状态收入 `design/` 索引表。
- **端到端验收标准**：
  - 在 `dudu` 项目上打开 `pm-project` → `Library`，无需任何配置即可在「仓库文档（Repo docs）」下看到 `design/auto-dream.md` 等全部设计定稿（含中文 H1 标题与来源线程跳转），而 `index.html`、`*.png`、`*.mp4` 零混入；
  - 台账中若仍存有 `auto-dream-draft.md`，自动淡显标出「已定稿」，点开可一键跳到 `docs/design/auto-dream.md` 或一键归档进 `.history/`；
  - 运行 `python3 tests/run_checks.py` 与 `python3 tests/render_check.py` 全部通过。
