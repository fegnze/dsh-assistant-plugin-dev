# Host configuration / Host 配置

## Supported routes / 可用入口

The installed Host plugin's `Config` declares `pythonExecutable`, `configPath` and `stateDir`. It is not a configuration UI. In DSH **0.2.1-rc.2**, the Settings service projects only `.volatile()` fields, and no shipped client automatically generates plugin pages from those descriptors. Adding display metadata or marking fields volatile does not create a page. This package registers neither `plugins.bundle.config` nor `plugins.row.config`.

本包声明三个 Host 配置字段，但没有配置页面。DSH **0.2.1-rc.2** 不从普通 `Config` 自动生成表单；不要把 Plugins 详情页的启用开关当作配置入口，也不要为此改变字段的生命周期。

Two supported choices:

1. **Owner-operated native document editing:** Settings offers **Open configuration file** on a loopback browser only when the Host can prepare its provider-owned document. `settings.openSettingsDocument()` opens that document with the native text editor; it is not a structured form and accepts no browser-supplied path. Remote browsers do not expose this action. The owner may use this explicit official entry; an Agent must not bypass it by directly rewriting profile files.
2. **No manual profile editing:** keep a separate, local, private configuration-only bundle outside this distributable package and install it through the official Plugins page or `plugin_manager`. The manager owns profile composition and persistence. This bundle carries an override, not another Host implementation.

可由主人使用官方“打开配置文件”入口；若不手改 profile，采用第二种独立私有覆盖包。它不启动进程、不复制助理、不更改已安装助理资源，也不授予任何任务权限。

## Portable private override example / 可移植私有覆盖示例

Create a local directory such as `config/plugin-development/host-settings/`. The following are example files to create there, not assets to add to the distributable assistant. Every `/absolute/...` value is a placeholder to replace locally; neither environment variables nor `~` are expanded by these YAML strings.

`package.json`:

```json
{
  "name": "@local/dsh-plugin-development-host-settings",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "description": "Local Host configuration for the plugin development assistant",
  "files": ["cordis.patch.yml"],
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
}
```

`cordis.patch.yml`:

```yaml
- id: dsh-assistant-plugin-dev
  name: '@fegnze/dsh-assistant-plugin-dev'
  config:
    pythonExecutable: /absolute/venv/bin/python
    configPath: /absolute/user/config.json
    stateDir: /absolute/user/releases
```

- Install the assistant first, then install this private bundle by its absolute directory path using the official plugin manager. No executable entry point or package dependencies are required. The minimal configuration-only bundle intentionally uses the manager's default icon rather than adding unrelated artwork.
- The target is the inspected **patch id** `dsh-assistant-plugin-dev`, not the diagnostic entry id `include:dsh-assistant-plugin-dev`. `name` asserts the target package identity; it does not rename it. Do not insert a second assistant row.
- A patch replaces the entire `config`; it does **not** deep-merge. Restate all three fields. A missing target is warned about and skipped. Profile, home or invocation overrides may have higher precedence; do not infer success merely from installation.
- `configPath` names the external engineering configuration illustrated in [config.example.json](<config.example.json>), not the Host patch itself. That document's `workspace` is relative to the document. `stateDir` is the releases directory itself, outside both the assistant package and publishable projects. Preserve existing release records when configuring an existing installation.
- Keep this local bundle private and outside public payloads; it holds machine-specific paths. Installing, selecting or configuring the assistant does not install prerequisites, authenticate accounts, authorize publishing, migrate data or change a session's preset.

先安装助理，再经官方插件管理器安装私有覆盖包。`config` 是完整替换，三个字段都要提供；`stateDir` 指向 releases 目录本身。安装结果可能要求重启或被更高层覆盖，须按官方结果处理并重新检查 readiness，不把“包已安装”当成“已可执行”。

## Verification and exact binding / 验证与精确绑定

After applying the configuration through an approved route, follow the official installation/reconciliation result, confirm the intended entry, and recheck local readiness before selecting or retrying the assistant. A blocked explicit selection is retained for an exact retry; do not silently substitute another package or preset.

The assistant's resource digest includes its README, documentation, Skill and prompts as well as implementation and templates. Updating any of these packaged resources changes the next installation's identity even when the package version is unchanged. Existing bindings must not automatically upgrade to that different digest. Preserve or restore the exact bound package, or use an explicitly selected compatible assistant in a new session. Never patch the installed directory to make an existing binding appear current.

外置配置与发布恢复数据不属于包资源摘要；它们仍受配置校验、操作配置修订校验和权限检查约束。文档修正只在下次正式安装相应包时生效，不能借此自动升级旧绑定。
