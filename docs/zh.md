# 插件开发助理

[English](<../README.md>) | 中文

独立可分发 DSH 助理包：自带 Python 领域工具、原生 OpenSpec 资源、会话级 Skill 与委派模板。依赖 `@fegnze/dsh-capability-manager` ≥0.2.0 <0.3.0，要求官方创造模式真实 preset ID `cordis`。不复制预设、不另起调度、HTTP/MCP服务。

## 安装与配置

通过官方插件管理器先安装兼容的能力管理器，再安装本包；当前源码存在不意味着 npm 已发布。以官方安装结果要求的重启/生效状态为准。

Host 插件接受三项配置：

- `pythonExecutable`：明确的 Python 解释器绝对路径或可执行名，无个人路径默认。
- `configPath`：外置用户配置文件绝对路径，示例见[配置示例](<config.example.json>)。
- `stateDir`：外置发布恢复目录（是 releases 目录本身，不是父目录），不得在本包或可发布工程中。

DSH 0.2.1-rc.2 不会从普通 `Config` 自动生成表单；本包也没有注册配置页面。本地宿主可用时，官方设置中的“打开配置文件”会用原生编辑器打开 provider 管理的配置文档。若不希望手动编辑 profile，通过官方插件管理器安装独立的 private 配置-only override bundle；个人路径仅保留在本地配置包，不放进本通用包。入口边界与可移植示例见 [Host 配置说明](<host-configuration.md>)。

workspace 相对配置文件解析，不相对包目录。projects 只读取明确登记，不自动扫描个人工作区。可用 executables 明确 git/node/npm/gh/openspec/tar 路径或名称，coAuthor 是可选用户策略。包内没有账号默认值、凭证或用户配置。激活不自动拷贝旧数据。

从会话输入框选择助理，兼容性/绑定/恢复由基座管理；已开始的不兼容会话应新建，不切换或复制预设。配置或基础本地依赖不可用时不能激活；明确选择保留为 blocked，供原样重试；发布权限单独逐操作检查。安装、选择、readiness不授予发布权限。

## 依赖与就绪

Python ≥3.10，所选解释器显式安装[依赖声明](<../requirements.txt>)（PyYAML ≥6,<7）。本地开发需 git、Node ≥22、npm、官方 OpenSpec **1.8.0**（已验证契约）；GitHub能力需 gh 与主人授权账户，真实身份/仓库/权限按操作复核。首次发布需 POSIX PTY/进程组、tar、明确安装的 npm ≥11.21.1；锁相关配置/版本操作也需 POSIX fcntl。Windows 不支持这部分操作。

readiness/安装/激活不下载依赖、不启动登录、不调用 npm exec 安装器。配置账号与CLI存在不等于真实认证。基础依赖成功探测缓存60秒，配置和资源的提供者版本每次复核；工具调用仍逐操作检查。

## 工具及其他 Agent 入口

- `dsh_dev_query`：guide/projects/inspect/readiness、registry/remote及精确操作预检。
- `dsh_dev_operate`：创建、validate、版本、提交、建仓、同步、发布和恢复、明确原生 OpenSpec init/new 辅助。
- `dsh-plugin-development`：按需加载的会话级 Skill，不复制到个人技能目录。

普通副作用操作依官方 sandboxPolicy，非full权限需当前turn实际批准。公开导出及发布**即使full权限也需独立当前turn批准**；拒绝/never则停止并提供手动CLI。批准绑定参数和配置hash；不使用模型confirm布尔充当权限。非full查询要求完整进程隔离，不允许静默无沙箱降级。release-status/resume也写外置状态，不是严格只读。

认证bootstrap仅手动CLI：先通过会话提问工具说明操作、确认次数，经主人同意立即开始后才运行；失败不能自动重试。Host不会开认证网页。

其他Agent使用其获授权的执行工具直接调用包内短命CLI：

```sh
"$PYTHON" -B /absolute/package/src/cli.py --config /absolute/user/config.json --state-dir /absolute/user/releases guide
"$PYTHON" -B /absolute/package/src/cli.py --config /absolute/user/config.json readiness local
"$PYTHON" -B /absolute/package/src/cli.py --config /absolute/user/config.json projects
```

详见[命令参考](<commands.md>)与[领域规范](<standards.md>)。intent flags 不替代权限证据。源码编辑仍由Agent完成；OPSX是instructions/status/spec sync/archive唯一权威，无平行流程数据库/归档包装。

## 验证与打包

```sh
npm test
DSH_ASSISTANT_PYTHON=/absolute/venv/bin/python npm run test:python
```

Python用隔离临时工程与模拟发布，真实Git/PTY/native OpenSpec切片单列；真实npm README回归需 `DSH_TEST_NPM_ROOT=/absolute/npm/package`。跳过不等于验证通过；测试不认证、不发布。Node契约和进程/生命周期测试不替代真实desktop验收。

发布源码、模板、测试和原创MIT图标，不包含个人配置、凭证、恢复记录、虚拟环境、依赖或缓存。SHA256资源摘要检测普通漂移，不是供应链签名或授权证明。

## 迁移与限制

`migration-preview OLD_CONFIG OLD_RELEASES` 只读清点源名和hash、workspace转换方案；主人另行审查目的地、复核hash并完整迁移所有dispatch intent/run记录。升级/移除本包不删除外置数据。替代测试、clean包和真实desktop验收通过前不能退役旧权威。

静态检查不证明UI验收、翻译质量或密码学provenance。CI成功、registry可见、tarball字节一致是不同证据；不确定发布按run/SHA核对，绝不盲重派发。首次发布和Trusted Publisher绑定后，仍需在npm实际验证窗口内完成明确授权的真实OIDC完成版本。

基座在安装时能阻断不可用精确绑定；完全移除基座后不存在未来拦截点。本工具也不能约束任意shell或外部MCP。恢复基座/包或另开会话，不宣称永久全覆盖。
