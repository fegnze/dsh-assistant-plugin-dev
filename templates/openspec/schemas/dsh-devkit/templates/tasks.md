## 实施与验收
<!-- 原生 OPSX 控制流程；按明确提案范围选择任务，不固定工具顺序；使用 guide 返回的包内 CLI 和外置配置。 -->
- [ ] 复核提案范围及有效工程事实，按需查询 guide / inspect，按当前 DSH Inspect 实施
- [ ] 审查脚本后运行 validate {{project}} --allow-project-scripts，完成适用真实宿主验收并说明未覆盖项
- [ ] 按交付范围使用 version-plan / version-bump；中间 checkpoint 不单独发版；使用 commit-plan / commit 精确保存改动

## 适用交付
<!-- 只保留提案明确包含的任务；首次公开/发布须获授权。已纳入范围但未获授权的任务应保留待办，不冒充完成。 -->
- [ ] 获准公开后使用 create-repo 建立独立仓库，核验归属与权限
- [ ] 获准导出后使用 sync-plan / sync 推送源码，核验远端 SHA 与导出树
- [ ] 使用 registry / npm-bootstrap-plan 核实身份与授权；需主人操作时用会话提问工具说明操作及确认次数，获准立即开始才执行认证
- [ ] 获准发布后使用 release / release-resume 核验 npm 精确版本和包字节，不以 CI 成功替代发布核验

<!-- 核对实际结果后由原生 OPSX 归档；归档不等于实际交付。后续修改新建小提案，不重开归档、不默认重复首发。 -->
