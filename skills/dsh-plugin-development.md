# DSH 插件开发

用原生 OpenSpec OPSX 作为唯一流程来源；读取当前变更的 proposal、specs、适用 design 和 tasks 后实施，按已批准范围验收。不要为助理复制预设或另建流程状态。

## 发现与路由

使用 `dsh_dev_query` 的 guide 获取包内 CLI、规范文档和依赖说明；按需查询 projects、inspect、readiness 及操作预检，不强制固定先后。完整标准见本资源目录的 `../docs/standards.md`，外部命令用法见 `../docs/commands.md`。委派任务模板见 `../prompts/delegation.md`。

## 执行边界

- 修改插件 API 前读取当前 DSH Inspect；不把旧模板视为宿主契约。
- 用原生 CLI 读取 instructions/status、同步规范和归档；领域工具不包装归档。保留工作区唯一 OpenSpec 根，用 affected_areas 标记目标。
- 审查工程脚本后才 validate；准确区分静态检查、真实本地测试、真实宿主/UI 验收、模拟发布和远端发布。
- 提交/升版/同步绑定精确内容基线；不能替换为 HEAD+dirty。保持不相关暂存区和远端独有改动，不强推。
- 首次公开、发布、登录或二次验证按已批准范围执行；安装与绑定不是授权。需主人操作时先用会话提问工具说明操作与次数；获准立即开始才进行，失败后重新确认，不自动重试。
- `dsh_dev_operate` 使用官方执行策略/批准，不传确认布尔冒充许可。bootstrap 认证仅提供手动 CLI 路径，不能由 Host 自动开启。
- 保留外置配置与恢复状态；包升级/卸载不删用户数据，不丢未决 dispatch intent，不重复派发不确定发布。
- 本地修复、源码同步、发布按提案分别收口；未完成或未授权保持待办，不把 artifact 就绪或归档当作完成。
