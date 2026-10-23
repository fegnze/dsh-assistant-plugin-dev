# 插件开发领域规范

## OpenSpec 轻量开发流程

使用用户配置的 workspace 作为唯一 OpenSpec 根，PROJECT 是目标插件。原生 OPSX 负责探索、提案、实施指令、规范同步与归档；本包不维护平行阶段、计划数据库或完成证明。用 affected_areas 绑定目标；instructions/status/归档直接使用官方 CLI。现验明版本为 OpenSpec 1.8.0，其他版本先审查兼容性。

保留原生 proposal/specs/design/tasks DAG。行为变化编写真正 delta（ADDED/MODIFIED/REMOVED/RENAMED），MODIFIED 保留完整 requirement/scenarios；无规范变化才 skip_specs，不与 delta 并存。原生没有 skip_design；不生成空设计假装跳过。已有配置和符号链接不覆盖；归档后的修改新建小变更。

提案明确本地修复、源码同步或发布范围。只把实际完成勾选；暂未获授权不是完成，已纳入范围的待办保留。按需复用有效 guide/inspect 上下文，不强制调用顺序。

## 工程身份与实现

使用 dsh-* lower-kebab 短名，配置键/目录/GitHub末段一致；npm 可用显式scope，既有无scope包不自动改名。create 只接受官方 registry HTTP404，其余响应与网络失败一律拒绝且先于写入；名称预检不保留名称或授予scope发布权限。

编辑前通过当前 DSH Inspect 获取 Service/Event/Slot/Config 的真实契约；遵循官方 lifecycle、subprocess/webServer、tools/skills/系统提示与UI接缝。不要写profile原始文件、开启第二HTTP宿主、复制预设、重造调度或DOM注入。源码编辑仍由会话执行者完成。

## 插件图标视觉规范

使用原创或许可再分发的图标并保留版权；不可用模板默认图冒充成品。声明icon、导出locale/icon资源并核对打包文件。按官方大小、格式和路径限制检查，实际宿主中核验明暗主题与双语展示；仅文件存在不是视觉验收。

英文 README.md 为 GitHub/npm默认入口，中文全文放 docs/zh.md，头十行互链。不得留竞争性根README或旧readme/readmeFilename元数据。保持功能、安装、配置、限制、示例对等；结构校验不证明翻译质量。

## 发布前检查

审查npm scripts后执行 validate，分别报告真实本地测试、静态payload检查和Host/UI验收。只纳入必要源码/资源，不发布缓存、凭据、个人配置、恢复状态或依赖目录。当前扫描只查禁用路径及私钥头，不声称找出全部凭据。

版本使用内容/权限/HEAD基线计划；prerelease、回退及重大版本须显式决定。commit拒绝既有暂存、symlink和过期基线；脚本/hook执行须处于授权范围。阶段性提交不要求发布完成，co-author由用户策略决定。源码同步保留远端父提交、精确tree/SHA、不强推；远端独有改动需先审查，不自动合并或覆盖授权范围之外资产。

## 发布结果与故障恢复

公开仓库、导出、npm发布均遵循明确范围和官方批准机制。配置账号不证明认证；检查实际gh身份、仓库和权限、npm归属与精确版本。首次人工登录/2FA先用会话提问工具说明做什么及确认次数，获准立即开始再执行；失败后不得自动重试。Host工具不启动认证；CLI意图flags不替代权限证明。

相同已发布版本必须下载tarball核对SHA512和全部文件字节，一致才判已完成。CI成功、registry可见、字节相同与OIDC实际发布证据分别判定。provenanceAdvertised仅声明存在，不是签名验证。首次bootstrap及Trusted Publisher绑定仍需主人授权的实际OIDC完成版本验证路径，不自动制造版本。

发布先持久化独占dispatch intent；异常或超时不删除意图盲重发。用已有run ID、工作流、精确SHA恢复核验；waiting_registry可以有界等待但不重派发。迁移/升级保留全部外置恢复证据，不能把“状态没迁过来”当成从未发布。release-status/resume也会写状态，不属于严格只读。

## 重命名与退役

明确授权后核对旧包依赖、组件ID、配置命名空间、安装来源和用户数据。目录迁移不代表发布；避免新旧bundle重复安装。单一权威迁移须先完成替代测试与真实desktop验收，再迁移规则/文档/钩子并退役旧入口；保留不可重建数据与未决发布证据。
