# Project 模型与交互升级设计：Remote Machine 创建、Space 一对一与平权多文件夹关联

> **关联任务**：`#375 dudu-project-remote-machine-space`  
> **状态**：**最终定稿（Final Approved Spec）** —— 用户已确认 D1–D4 全部按方案 A 锁定，并拍板定稿「平权关联文件夹（取消 Primary 概念，支持 0/1/N 个）」、「Library 与代码仓彻底解耦」及「全量升级 1.5px Linear/Lucide 极简文件夹图标」，可直接进入实施。

---

## 0. 定稿总览与已拍板决策记录（Locked Decisions）

### 0.1 三大核心架构定稿

1. **Remote Machine + `agy` 一体化创建**：
   - `New project` 弹窗新增 `Machine` 选择（`Local` / 已连接 `hc` 远端机器如 `dev`；若当前聚焦远端 Space 则自动预选该机器，无远端机器时自动隐藏该行）。
   - 远端支持路径输入、单次探针校验（目录存在性 + 是否 Git + 不存在时一键 `Create folder`）与内联轻量远端目录浏览弹层；采用**「远端 `pm.py start --no-app-space --json` 起受守护 Seat + 本机客户端挂载 `machine` 专属 Space」**两阶段幂等协议。
   - `Manager` 内置补齐 `agy`（对齐 `Claude Code / agy / Codex / pi` 四大运行时，遵循目标机器 `config.json` 默认配置与可用性探测），并解除远端项目的桌面端 `Archive` / `Restore` 限制。
2. **确立 `1 Project = 1 Dedicated Space` 一对一关系**：
   - **移除 `New project` 弹窗中的 `Where: [ New space | Current space ]` 选择行**，消灭多项目混塞同一 Space 或跨机错绑。
   - 在 `pms/<slug>.json` 中持久化显式字段 `space_id`（配合 `space_name` 重建兜底）；存量项目在 `state` / `claim` / `rotate` 时自动从运行中 PM 终端的 `herdr.space` 标签无感回填 `space_id`。
3. **平权多文件夹关联（Workspace Folders，支持 `0 / 1 / N` 个，彻底取消 Primary 概念）+ Library 彻底解耦**：
   - **产品与 UI 完全平权**：取消所有 `Primary` / `主目录` 徽章、`Make primary` 操作与主副角色区分；一个 Project 可关联 **0 个、1 个或多个完全平等的文件夹**，任意文件夹均可随时添加或移除（包括解绑到 0 个文件夹）。
   - **底层 100% 向后兼容**：项目身份 `slug` 在创建时固化于 `pms/<slug>.json`；底层 JSON 仅保留可选镜像字段 `repo = folders[0].path`（0 文件夹时为 `""`）供旧脚本兼容；PM 终端启动 `cwd` 取首个关联文件夹（0 文件夹时取 `~/.dudu/projects/<slug>/`），对用户完全透明。
   - **Library 彻底解耦**：Library **只管理项目自有台账文档（`~/.dudu/projects/<slug>/docs/`）**，不再扫描或聚合任何关联文件夹/代码仓库内的文档；查阅或引用仓库文件统一走 `@` 多目录文件检索。
   - **文件夹图标全面焕新**：废弃笨重的 `2px` 折角描边图标，统一升级为 **Linear / Lucide 风格 `1.5px` 双圆弧肩线细描边 SVG**（同步替换 `mods/pm-dash/folder.svg` 与 `mods/pm-project/folder.svg`）。

### 0.2 已拍板锁定的全部设计决策（无需再问，直接按此实现）

| 编号 | 决策主题 | 已锁定方案（Final Decision） |
| :--- | :--- | :--- |
| **D1** | **归档项目（Archive）时的专属 Space 处置** | **智能条件关闭（Clean-close when idle）**：停止 PM 会话后，若专属 Space 内仅剩 PM 标签页或无前台任务的空闲默认 Shell，自动关闭该 Space；若用户在其中手开了未退出的进程（如 `nvim`/编译/独立会话），仅关 PM 标签页并保留 Space。恢复（Restore）时优先复用仍在的原 `space_id`，已关则按原名重建。 |
| **D2** | **远端机器（如 `dev`）下的文件夹选择交互** | **路径输入框 + 轻量远端目录浏览弹层（Input + Remote Subfolder Picker）**：支持直接粘贴路径失焦即时探针校验，同时点击右侧目录按钮可通过 `hc exec --on <machine>` 展开远端非隐藏子目录列表（标出 `git` 徽章，单击下钻或回车添加）。 |
| **D3** | **多文件夹下的 `dispatch` 规则与权限边界** | **平权文件夹 + 单 Git 仓自动选、多 Git 仓显式 `--folder`**：PM 会话对全部关联文件夹拥有免确认只读权限；`dispatch` 在项目**仅有 1 个 Git 仓库时自动选用该仓**，存在 **≥2 个 Git 仓库时必须传 `--folder <alias>` 显式指定**（绝不暗自偏袒列表第 1 项）；`1 Thread = 1 目标仓库`，同项目其余关联文件夹自动加入 Worker `outside_reads` 供跨仓联调只读查阅。 |
| **D4** | **创建/切换项目时的底层 Space 同步策略** | **静默绑定 `space_id`，按需聚焦终端**：创建或切换项目时直接秒切 `pm-project` 对话视图，不抢占底层 `space.select` 终端焦点（彻底杜绝误触发 `pm-nav` 跳回纯终端页的 bug）；仅当点击顶栏 `>_`（打开 PM 终端）或主动切回终端工作区时精准切入该项目绑定的 `space_id`。 |
| **D5** | **文件夹角色模型与数量边界** | **彻底取消 Primary（主仓库）概念**：所有关联文件夹在产品与 UI 上 100% 平等，支持 `0 / 1 / 多个` 文件夹；去掉一切 Primary 标签与删改限制；底层仅保留可选 `repo = folders[0].path` 兼容旧脚本。 |
| **D6** | **Library 与关联文件夹的关系** | **彻底解耦**：Library 只负责项目自有文档 `~/.dudu/projects/<slug>/docs/`（含台账调研报告与历史决策归档），**不扫描关联文件夹/代码仓库内的文档**（同步清理旧版单仓 `repo_docs` / `instructions` 仓库扫描耦合）。 |
| **D7** | **文件夹图标视觉规范** | **统一采用 Linear / Lucide 风格 `1.5px` 细圆角描边 SVG**，落地时直接替换 `mods/pm-dash/folder.svg` 与 `mods/pm-project/folder.svg`，并配套 `folder-plus.svg`。 |

---

## 1. 现状核查：单仓假定与 Space 错配根因审计

| 模块与文件位置 | 现状实现与隐式假定 | 引发的真实问题与改造落点 |
| :--- | :--- | :--- |
| **新建弹窗与列表交互**<br>[projects.js](../../mods/pm-dash/projects.js#L282-L420)<br>[model.js](../../mods/pm-dash/model.js#L1097-L1108) | 1. `v.form = { repo, name, kind: 'claude', space: 'new' }` 无 `machine` 与 `folders[]`，且强制 `Boolean(f.repo)` 才能提交；<br>2. `chooseFolder()` 仅调本机 `pickFolder()`；<br>3. `KINDS = ['claude', 'codex', 'pi']` 漏掉 `agy`；<br>4. `Where` 展示 `New space` 与 `Current space`；<br>5. `&& local` 禁用了远端项目的归档与恢复。 | 1. 升级为 `form = { machine, folders: [], name, kind }`，支持 `0..N` 个平权文件夹（只要 `name` 非空即可创建）；<br>2. 增加 `Machine` 选择与远端探针/目录选取；<br>3. 补齐 `agy`、移除 `Where` 行、放开远端归档/恢复。 |
| **Agent 注册表与 PM 启动**<br>[agents/base.py](../../mods/pm-dash/skill/scripts/pmlib/agents/base.py#L23-L33)<br>[manager/launch.py](../../mods/pm-dash/skill/scripts/pmlib/manager/launch.py#L484-L586)<br>[manager/service.py](../../mods/pm-dash/skill/scripts/pmlib/manager/service.py#L359-L601) | 1. `AGENT_KINDS` 未内置 `agy`；<br>2. `pms/<slug>.json` 只存 `space_name` 不存 `space_id`；<br>3. `start` 强绑定单一物理目录 `repo` 派生 `slug`，且远端主机无本地 `herdr-app` GUI；<br>4. `restore()` 固定新建 Space。 | 1. `AGENT_KINDS` 内置 `agy`；<br>2. 支持按 `--name` / `--slug` + `0..N` 个 `--folder` 启动（0 文件夹时 `cwd` 透明落于 `projects/<slug>/`）；<br>3. 落地 `space_id` 持久化、存量回填、归档空闲关 Space 与恢复复用。 |
| **项目身份与任务归属**<br>[home.py](../../mods/pm-dash/skill/scripts/pmlib/home.py#L15-L18)<br>[project/project.py](../../mods/pm-dash/skill/scripts/pmlib/project/project.py#L240-L357)<br>[project/readmodel.py](../../mods/pm-dash/skill/scripts/pmlib/project/readmodel.py#L81-L104)<br>[ledger/ledger.py](../../mods/pm-dash/skill/scripts/pmlib/ledger/ledger.py#L55-L110) | 1. `owner_of(task, pms)` 与 `store._reg_index()` 仅比对单一 `pm["repo"]`；<br>2. `Ledger.project_tasks()` 硬要求 `t["repo"] == repo`；<br>3. `Change.note_on()` 用 `raw["repo"]` 反查 `projects/<slug>/conversation.jsonl`。 | **关键解耦**：项目以 `slug` 为唯一恒定身份；任务新增显式 `project_slug` 锁定对话流与任务序号，而 `task["repo"]` 记录该线程实际操作的目标文件夹，彻底消除多仓任务写串对话流或变成 `unclaimed` 的隐患。 |
| **Worker 派发与跨仓只读**<br>[workers/service.py](../../mods/pm-dash/skill/scripts/pmlib/workers/service.py#L553-L825)<br>[agents/reads.py](../../mods/pm-dash/skill/scripts/pmlib/agents/reads.py#L63-L135) | 1. `dispatch` 仅接受单一 `repo` 且把 `task["project"]` 写成目录名；<br>2. `outside_reads` 未包含同项目其余关联目录。 | 1. 新增 `--folder <alias|path>`：单 Git 仓自动选，多 Git 仓强制显式指定；<br>2. 同项目所有关联 `folders[]` 自动加入 PM 与 Worker 的免确认 `Read` 范围。 |
| **Library 与 `@` 检索**<br>[store.py](../../mods/pm-dash/skill/scripts/pmlib/store.py#L1961-L2532)<br>[pm-project/model.js](../../mods/pm-project/model.js#L8808-L9060) | 1. `Store.library()` 耦合了代码仓库的 `repo_docs` 与 `instructions` 扫描；<br>2. `Store.repo_files()` 只扫单个 Git 目录。 | 1. **Library 解耦瘦身**：只返回项目台账目录 `~/.dudu/projects/<slug>/docs/` 下的自有文档（及台账调研报告/历史归档）；<br>2. **`@` 文件检索升级**：遍历全部平权 `folders[]`（含非 Git 目录安全扫描），多目录时冠以 `<alias>/` 命名空间。 |
| **Token 统计 & 图标资源**<br>[views/tokens.py](../../mods/pm-dash/skill/scripts/pmlib/views/tokens.py#L161-L571)<br>[pm-dash/folder.svg](../../mods/pm-dash/folder.svg)<br>[pm-project/folder.svg](../../mods/pm-project/folder.svg) | 1. `_build_project_index` 只索引单一 `repo`；<br>2. 现有 `folder.svg` 线宽 `1.9–2.0px` 且折角生硬。 | 1. `tokens.py` 纳入全部 `folders[]` 与对应 worktree，维持单文件全局唯一归属去重；<br>2. 替换双端 `folder.svg` 为 `1.5px` Linear/Lucide 圆弧描边图标。 |

---

## 2. 核心设计 A：Remote Machine 创建项目 + Manager 补齐 `agy`

### 2.1 `New project` 弹窗交互流程

1. **`Machine` 选择器**：
   - 并行读取 `hc machine ls --json` 与 `spaces()`：列出 `Local` 与已添加的远端机器（`connected` 可选；`unreachable` / `needs_login` 灰显不可选并悬停提示恢复命令）。若未配置任何远端机器，自动隐藏 `Machine` 行。
   - **上下文智能预选**：若用户当前激活的 Space 属于某台 `connected` 远端机器（如停留在 `dev` 的 Space 点 `+`），默认自动选中 `dev`。
2. **`Folders`（平权可选列表，`0..N` 个）**：
   - **Local 态**：点击 `+ Add folder…` 调起原生 `pickFolder()`（亦支持直接粘贴路径），每次添加一行平权文件夹；若 `Name` 尚为空，第一次添加文件夹时自动以其目录名预填 `Name`（之后增删文件夹不再篡改已填的 `Name`）。
   - **Remote 态（如 `dev`）**：
     - 点击 `+ Add folder on dev…` 展开等宽路径输入行（支持 `~/...` 与绝对路径），右侧带目录浏览图标按钮；
     - **轻量远端目录浏览弹层（Remote Subfolder Picker）**：通过 `exec('sh', ['-c', REMOTE_LIST_DIRS_SH, 'sh', prefix], { on: machine, timeout: 4000 })` 列出远端子目录（标注 `git · <branch>` 徽章），单击下钻、回车或点 `Add` 加入列表；
     - **单次探针校验（`<150ms`）**：一次性校验远端 `$HOME`、`pm.py` 是否就绪、各路径是否存在及是否为 Git 仓库；若某路径尚不存在，行内提供 **`[Create folder]`** 一键 `mkdir -p`。
   - **零文件夹直建**：即使 `Folders` 为空（`0` 个），只要填写了 `Name`（如 `Q3 Planning`），提交按钮即就绪可创建！
3. **`Manager` 四引擎（含 `agy`）**：
   - 内置 `KINDS = ['claude', 'agy', 'codex', 'pi']`，`AGENT_KINDS` 在 `pmlib/agents/base.py` 补齐内置项：
     ```python
     "agy": {"argv": ["agy"], "model": ["--model", "{}"], "effort": [], "prompt_arg": False}
     ```
     （用户 `config.json` 中自定义的 `agents.agy` 如 `["agy", "--dangerously-skip-permissions"]` 仍优先覆盖内置默认）。
   - 默认选中目标机 `config.json` 配置的 `pm.kind`（或 `pm.profile` 对应 `kind`，缺省 `claude`），并通过 `knownAgents({ on: machine || null })` 灰显目标机未安装的 CLI。

### 2.2 两阶段远端创建与归档/恢复闭环

1. **阶段 1（目标机启动 PM Seat 并写注册表）**：
   - 本机或通过 `exec(...remotePmArgv(['start', '--name', name, ...folderFlags, '--kind', kind, '--no-app-space', '--json']), { on: machine, timeout: 120000 })` 在目标机执行：
     - 确定项目唯一 `slug`（新项目取 `slugify(name)`），确保 `~/.dudu/projects/<slug>/` 存在；
     - PM Seat 启动工作目录 `cwd`：若 `folders` 非空则取 `folders[0].path`，若 `folders` 为空则取 `~/.dudu/projects/<slug>/`（对用户透明）；
     - 在目标机 `herdr-core` 启动 `pm.py seat` 终端 `tXX`（打标 `pm=<slug>`, `pm.seat=1`），写入 `pms/<slug>.json` 并拉起 `deliver` 守护进程，输出 JSON：`{"ok": true, "slug": "...", "name": "pm-...", "terminal": "tXX", "cwd": "..."}`。
2. **阶段 2（本机桌面端绑定 1:1 Space 并直开对话）**：
   - 本机收到 `terminal`（远端拼为 `<machine>/<tXX>`），后台创建或收编专属 Space（`machine`, `name`, `folder: cwd`, `focus: false`），将 PM 终端挂入 `PM-<name>` 标签页，把 `space_id` 写回目标机 `pms/<slug>.json`；
   - 刷新状态缓存后立即调用 `openProject(qualifiedPmName, machine)` 进入项目对话视图。
3. **远端项目 Archive / Restore 解禁**：
   - `mods/pm-dash/projects.js` 与 `mods/pm-list/main.js` 去掉 `!c.machine` / `!row.machine` 限制，统一通过 `exec(...remotePmArgv(['archive' | 'restore', slug]), { on: machine })` 执行远端归档与恢复，并联动管理本机对应的 `dev/sp...` Space。

---

## 3. 核心设计 B：Project ↔ Space 一对一强绑定模型

### 3.1 核心不变量

1. **1 Project = 1 Dedicated Space**：任一活跃 Project 在其所属 `machine` 上拥有唯一专属的 `space_id`，绝不与其他活跃 Project 混用；弹窗彻底删除 `Where` 行。
2. **双向持久化锚定**：`pms/<slug>.json` 显式存储 `"space_id": "sp..."` 与 `"space_name": "..."`。
3. **对话与终端焦点解耦（根治切屏只显终端不显对话）**：
   - 创建或切换项目时，仅切换 `pm-stage` 到 `pm-project` 对话视图，不抢占底层终端焦点；
   - 仅当用户点击顶栏 `>_`（Open PM terminal）时，按 `space_id` 精准切入该项目专属 Space（若用户此前手动关掉了该 Space，自动以 `space_name` + `cwd` + `machine` 原地重建并更新 `space_id`）。

### 3.2 归档、恢复与存量自愈

- **归档（Archive，锁定 D1 方案 A）**：结束 PM 会话并暂停未结任务；检查 `space_id` 内标签页——若仅剩已退出的 PM 标签页或无前台子进程的空闲默认 Shell，自动 `space.close` 关闭该 Space；若存在用户手开的活跃进程，仅关 PM 标签页并保留 `space_id`。
- **恢复（Restore）**：若原 `space_id` 仍在且未被占用，直接复用该 Space 启动新 PM 标签页；否则新建同名专属 Space 并更新 `space_id`（杜绝重复创建同名 Space）。
- **存量项目无感回填**：对现有尚无 `space_id` 的项目（如本机 `dudu`、`app` 与 `dev` 上的 `web-i18n`），在 `pm.py state` / `claim` / `rotate` 读到存活 PM 终端时自动提取 `labels["herdr.space"]` 原子回填至 `pms/<slug>.json`。

---

## 4. 核心设计 C：平权多文件夹关联与全链路契约

### 4.1 台账数据模型（平权 `folders[]` + 兼容镜像 `repo` + 任务 `project_slug`）

#### 1) 项目注册表 `pms/<slug>.json`（支持 `0 / 1 / N` 个平权文件夹）

```json
{
  "slug": "dudu",
  "name": "pm-dudu",
  "project": "dudu",
  "space_id": "sp49745294ebb489c32b5babebe641b041",
  "space_name": "dudu",
  "agent": "agy",
  "runtime": "hc",
  "terminal": "t1k6",
  "seat": true,
  "folders": [
    {
      "path": "/Users/dev/project/repos/dudu",
      "alias": "dudu",
      "git": true,
      "default_branch": "main"
    },
    {
      "path": "/Users/dev/project/repos/herdr",
      "alias": "herdr",
      "git": true,
      "default_branch": "main"
    }
  ],
  "repo": "/Users/dev/project/repos/dudu"
}
```

- **完全平权**：`folders[]` 中不设 `role` 或 `primary` 字段，每一项都是平等的 `{ path, alias, git, default_branch? }`；`alias` 默认取目录名（同项目内重名时自动加父目录前缀消歧如 `v1-api` / `v2-api`，支持手动改别名）。
- **0 文件夹项目**：`"folders": []`，`"repo": ""`，项目的台账、对话、记忆、Library 全部天然存于 `~/.dudu/projects/<slug>/`，无任何路径缺失问题。
- **100% 向后兼容读取器 `project_folders(rec)`**：
  - 若存量 `pms/<slug>.json` 无 `folders` 字段但有非空 `repo`，自动归一化返回 `[{"path": rec["repo"], "alias": Path(rec["repo"]).name, ...}]`；
  - 每次写入 `folders[]` 时自动同步底层兼容键 `rec["repo"] = folders[0]["path"] if folders else ""`，使旧脚本与未升级组件零感知。

#### 2) 任务记录 `tasks/<id>.json`（项目归属与代码仓检出解耦）

```json
{
  "id": "dudu-fix-pty-resize",
  "number": 376,
  "title": "修复 PTY 窗口尺寸同步竞态",
  "project": "dudu",
  "project_slug": "dudu",
  "repo": "/Users/dev/project/repos/herdr",
  "folder_alias": "herdr",
  "branch": "fix/pty-resize",
  "base": "main",
  "worktree": "/Users/dev/.herdr/worktrees/herdr/fix-pty-resize",
  "status": "in_progress"
}
```

- **项目级路由走 `project_slug`**：`Change.note_on()`（写 `projects/<slug>/conversation.jsonl`）、`allocate_task_number()`（读 `projects/<slug>/task-seq.json`）、`owner_of()`、`Ledger.project_tasks()`、`Delivery` 与 `MemoryLayer` 均优先以 `project_slug`（兼容回退 `folders[].path` 匹配）定位项目。
- **代码树操作走 `task["repo"]`**：`git worktree add`、`pm.py review`、`pm.py land`、右侧 `Change` Diff 视图继续直接操作 `task["repo"]`（`/Users/dev/project/repos/herdr`），零侵入复用全部现有 Git 逻辑。

---

### 4.2 全链路行为边界（6 大环节）

1. **PM 启动透明目录、平权只读授权与上下文同步**：
   - **透明 `cwd`**：PM 进程启动在 `folders[0].path`（0 文件夹时为 `~/.dudu/projects/<slug>/`）；后续即使解绑了 `folders[0]`，运行中的 PM 会话也无需中断（下次重启/轮换自动切至剩余首目录或项目台账目录）。
   - **平权免确认只读授权**：`launch.py:lean_pm()` 将全部 `folders[]`（排除 `wide_folder`）平等写入 `projects/<slug>/pm-settings.json` 的 `permissions.allow: ["Read(//path/**)"]` 与 `blockReadsExemptPaths`。
   - **`handover` 与热更新通知**：`pm.py handover` 平等列出全部 `Workspace folders (N)`（含 `alias`、路径、是否 Git）；运行中动态增删文件夹时立即重写 `pm-settings.json` 并向 PM 投递一条轻量 `[workspace]` 变更通知。
2. **`pm.py dispatch` 平权目标解析**：
   - 新增 `--folder <alias|path>`（兼容 `--repo`）：
   - **未传 `--folder` 时**：
     - 若带 `--branch`（分支 worktree 模式）：统计 `folders[]` 中 `git == true` 的仓库数——**恰好 1 个时自动选中该 Git 仓**；**0 个时提示先关联 Git 仓库或改用 `--here`**；**≥2 个时明确拒绝并列出全部可选 `--folder <alias>`**（绝不暗中默认选第 1 个，贯彻完全平权防呆！）；
     - 若带 `--here`（原地模式）：`len(folders) == 1` 时自动选该目录，`len(folders) == 0` 时在 `projects/<slug>/` 原地执行，`len(folders) >= 2` 时要求传 `--folder <alias>` 显式指定。
   - **跨仓只读联调**：派往某一文件夹的 Worker 自动获得同项目其余关联 `folders[]` 的 `outside_reads` 只读权限，任务书附带关联目录清单供跨仓查阅接口。
   - **门禁检查 `verify`**：支持按文件夹配置 `projects/<slug>/verify.<alias>`（单仓项目兼容原有的 `projects/<slug>/verify`）。
3. **Library 彻底解耦（仅管项目自有文档 `~/.dudu/projects/<slug>/docs/`）**：
   - `Store.library(slug)` 彻底与关联代码仓解耦，仅服务项目自身的知识沉淀：
     - `docs`：`~/.dudu/projects/<slug>/docs/**`（支持面板内直接新建、编辑、拖拽导入文件、`.history/` 版本回滚）+ 历史归档 `decisions.md`；
     - `research`：项目台账调研报告 `~/.dudu/projects/<slug>/docs/research/**`（及兼容读取历史未迁移报告）。
   - 不再扫描各关联文件夹里的 `repo_docs` 或 `instructions`：0 文件夹、单文件夹与多文件夹项目的 Library 永远同样干净快速，彻底消除台账草稿与仓库文档双份冲突。
4. **`@` 文件检索多目录平权聚合（`Store.repo_files` & Mention Menu）**：
   - `pm.py project files <slug>` 平权遍历全部 `folders[]`：
     - `git == true` 目录走 `git -C <path> ls-files -z`；
     - `git == false` 目录走安全树遍历 `_scan_tree`（跳过隐藏目录与 `node_modules`/`dist`/`target` 等构建产物，单非 Git 目录上限 `2,000` 文件）；
   - `len(folders) == 0` 返回空列表；`len(folders) == 1` 保持无前缀相对路径（100% 兼容现状）；`len(folders) >= 2` 统一采用 `<alias>/<rel_path>` 命名空间并在 `REPO_FILES_MAX = 20,000` 内按目录均衡配额。
   - 输入框敲 `@pty.rs` 或 `@herdr/pty` 均可命中，候选副标题标出所属文件夹 `herdr`，点击行内胶囊通过 `_locate(root="repo")` 按 `alias` 解析打开只读代码预览。
5. **Token 统计平权归属与全局严格去重（`views/tokens.py`）**：
   - `_build_project_index` 将每个项目的全部 `folders[].path` 及其 `worktree_home` 纳入扫描 `scopes` 与 `pinfo["roots"]`；
   - `_attribute_files` 按确定性漏斗确保**每个会话文件全局最多归属 1 个项目**：
     1. 显式 PM 会话注册表（`pms/*.json`、`agy-transcript.json`、`taken-in.json`、`pm-turn.json`、`seat.json`）→ 归属该 PM；
     2. 显式 Task Session ID（`session.id` / `prior_sessions`）→ 归属 `task["project_slug"]`；
     3. 验证过的 PM 开场 / 任务首句 Hint / 专属 Worktree → 归属对应 `project_slug`；
     4. 未登记 Ad-hoc 会话按 `cwd` 回退：按 `(最长匹配根路径长度, 非归档优先, 最近活跃优先, slug 字典序)` 唯一决出归属，跨项目共享目录零双算。
6. **项目内动态增删关联文件夹（顶栏原位胶囊 + `Workspace folders` 浮层 + CLI）**：
   - 顶栏项目名旁原位触发器（零右侧新增按钮）：
     - `0` 个文件夹：淡显 `[ 🗂+ Add folder… ]`；
     - `1` 个文件夹：显示 `[ 🗂 ~/project/repos/dudu ]`；
     - `≥2` 个文件夹：显示 `[ 🗂 ~/project/repos/dudu  +1 ▾ ]`（或短别名并列）。
   - 点击弹出无描边微表面 **`Workspace folders (N)`** 浮层：所有目录平权排列，每行均可内联改 `alias` 或点 `×` 解除关联（无“主目录不可删”限制；若有在途活跃线程运行在该目录下，内联二次确认后即可解绑，绝不删盘上文件），底部提供 `+ Add folder…`。
   - 对等 CLI：`pm.py project folders <slug> [add <path> [--alias <a>] | rm <alias|path> [--force] | alias <old> <new>]`。

---

## 5. 文件夹图标重设计与双语文案规范

### 5.1 Linear / Lucide 风格 `1.5px` 极简文件夹 SVG 规范

落地时同步替换 [mods/pm-dash/folder.svg](../../mods/pm-dash/folder.svg) 与 [mods/pm-project/folder.svg](../../mods/pm-project/folder.svg)（原图标使用 `stroke-width="1.9~2.0"` 与 `l2 2` 尖折角，小字号下显得粗糙厚重），统一升级为双圆弧过渡肩线 + `1.5px` 精细描边：

```xml
<!-- mods/pm-dash/folder.svg & mods/pm-project/folder.svg -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="#000" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>
</svg>
```

```xml
<!-- mods/pm-dash/folder-plus.svg & mods/pm-project/folder-plus.svg（空态 / 添加目录按钮专用） -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="#000" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 10v6M9 13h6"/>
  <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>
</svg>
```

### 5.2 新增/更新双语文案表（`STRINGS.en` / `STRINGS.zh`）

| Key | English (`lang = "en"`) | 中文 (`lang = "zh"`) |
| :--- | :--- | :--- |
| `machine` | `Machine` | `机器` |
| `localMachine` | `Local` | `本机` |
| `machineOfflineTip` | `(m, st) => \`${m} is ${st}; connect with hc machine login\`` | `(m, st) => \`${m} 当前 ${st}；请用 hc machine login 连接\`` |
| `folders` | `Folders` | `文件夹` |
| `optionalFoldersHint` | `Optional · link 0 or more folders` | `可选 · 支持关联 0 或多个文件夹` |
| `addFolder` | `Add folder…` | `添加文件夹…` |
| `noFoldersLinked` | `No folders linked yet` | `暂未关联文件夹` |
| `enterRemotePath` | `m => \`Path on ${m}, e.g. ~/project/repo…\`` | `m => \`${m} 上的路径，如 ~/project/repo…\`` |
| `browseRemoteTip` | `m => \`Browse folders on ${m}\`` | `m => \`浏览 ${m} 上的文件夹\`` |
| `folderNotFoundRemote` | `m => \`Directory does not exist on ${m}\`` | `m => \`${m} 上不存在该目录\`` |
| `createRemoteFolder` | `Create folder` | `新建此目录` |
| `dedicatedSpaceHint` | `(name, m) => m ? \`Starts PM on ${m} in space “${name}” and opens conversation.\` : \`Starts PM in space “${name}” and opens conversation.\`` | `(name, m) => m ? \`在 ${m} 的专属空间「${name}」启动 PM 并打开对话。\` : \`在专属空间「${name}」启动 PM 并打开对话。\`` |
| `workspaceFolders` | `n => \`Workspace folders (${n})\`` | `n => \`关联文件夹（${n}）\`` |
| `unlinkFolderActiveWarn` | `(alias, n) => \`${n} active threads still run in “${alias}”. Unlink anyway?\`` | `(alias, n) => \`「${alias}」下仍有 ${n} 个进行中线程，确定解除关联？\`` |

---

## 6. 分阶段实施拆解与验证矩阵

1. **Slice 1 · 平权多文件夹台账模型、Library 解耦与 CLI（后端 `pmlib`）**：
   - `AGENT_KINDS["agy"]` 内置注册；`pms/<slug>.json` 支持 `slug`、`space_id`、平权 `folders[]`（`0..N` 个）与兼容镜像 `repo`；新增 `pm.py project folders` 子命令；
   - `tasks/<id>.json` 引入 `project_slug` 与目标检出仓 `repo` / `folder_alias` 解耦；`dispatch --folder <alias>` 实现「单 Git 仓自动选、多 Git 仓显式指定」及跨仓 `outside_reads`；
   - `Store.library` 解耦移除代码仓扫描（仅管 `~/.dudu/projects/<slug>/docs/` 自有文档与调研/归档）；`Store.repo_files` 与 `views/tokens.py` 完成多目录 `<alias>/` 聚合与五级去重；
   - **检查**：相关单测全绿。
2. **Slice 2 · Space 1:1 生命周期、新版 `New project` 弹窗与远端全闭环（`manager` + `pm-dash` + `pm-list`）**：
   - `pm.py start` 支持 `--no-app-space` / `--json` 与 `0` 文件夹启动、存量 `space_id` 惰性回填、归档空闲自动关 Space（D1）与恢复优先复用；
   - 替换 `mods/pm-dash/folder.svg`（+ `folder-plus.svg`），升级 `projects.js` 新版 `New project` 弹窗（`Machine` 选择、远端探针与目录浏览、平权 `0..N` 文件夹、`agy` 四引擎、移除 `Where`），解禁远端项目 `Archive` / `Restore`；
   - **检查**：`SimHc` 远端创建/归档/恢复单测 + `pm-dash` 单测。
3. **Slice 3 · 项目内平权 `Workspace folders` 原位管理浮层与 `@` 多仓体验（`pm-project`）**：
   - 替换 `mods/pm-project/folder.svg`（+ `folder-plus.svg`），落地顶栏路径微胶囊（支持 `0 / 1 / N` 态）与平权 `Workspace folders` 增删改别名浮层；
   - 落地 `@` 提及多目录副标题与 Threads 面板跨仓 `folder_alias` 微标，按 D4 确保切换项目不触发终端抢焦点；
   - **检查**：`mods/pm-project/model.test.mjs` + 全量 `tests/run_checks.py` + `render_check`。
