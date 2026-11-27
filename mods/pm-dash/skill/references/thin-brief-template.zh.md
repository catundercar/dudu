【任务：{title}。来自 PM（{pane}）】

工作位置：{where}

用户原话：
{ask}

附件：
{attachments}

最近对话出处（{conversation_path}）：
{conversation_pointers}

PM 补充：
{note}

调查与开工要求：
- 先从第一性原理查清代码与现场再动手，不要猜测。
- 需要产品拍板或用户确认时，立即报 `blocked` 并给出清晰选项，不要自行臆断。
- 严格控制在需求范围内，不加不需要的脚本、框架或抽象层。
- 跑完与改动相关的针对性检查并简明汇报。

红线：
- 不碰用户正在运行的应用或系统设置，测试一律用隔离目录。
- 不用 `git add -A`，不 push，不合并。

提交：1–3 个，conventional 风格。必要时在 `evidence/<topic>/README.md` 写简短证据说明。完成后按末尾追加的「汇报」一段写进台账，然后停下。
