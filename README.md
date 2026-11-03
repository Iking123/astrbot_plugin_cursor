# AstrBot Cursor 插件

把 Cursor Agent 接到 AstrBot，用作 QQ 私聊和群聊的聊天模型。认证方式遵循 [Cursor Python SDK](https://cursor.com/docs/sdk/python)：使用用户 API Key 或服务账号 Key，不使用 Codex 那套 OAuth。

Cursor SDK 跑的是 Agent，不是独立的对话补全接口。每一轮 AstrBot 消息都会新开一个 Agent，把当前人设和上下文交给它，再把助手文本流式交回 AstrBot。

默认是本地、只回复文字。Agent 看不到、也改不了 AstrBot 的配置、令牌、聊天记录和记忆库。

## 安装

插件目录：

```text
data/plugins/astrbot_plugin_cursor
```

可以从 AstrBot 插件市场安装，也可以把这个仓库放到 `data/plugins/astrbot_plugin_cursor`。启用后，AstrBot 会按 `requirements.txt` 安装 `cursor-sdk`。需要 Python 3.10 或更高版本。

## 配置

打开插件配置，填写 **Cursor API Key**：

1. 打开 [Cursor Dashboard → API Keys](https://cursor.com/dashboard)。
2. 创建用户 API Key，或在团队设置里创建服务账号 Key。
3. 团队 Admin Key 不能用于 SDK。

密钥留在插件配置里。添加模型提供商时，Key 保持占位值 `cursor-plugin` 即可。

| 配置 | 作用 |
| --- | --- |
| 运行位置 `local` | 在这台电脑上运行。默认。 |
| 运行位置 `cloud` | 在 Cursor 托管的虚拟机上运行。 |
| 模型列表 | 在线目录失败时的备用列表。首行是默认模型，当前文档默认是 `composer-2.5`。 |
| 本地工作目录 | 留空使用插件自己的空目录。不要指向 AstrBot 安装目录或 `data/`。 |
| 本地内置工具 | 留空表示只聊天。`default` 使用 Cursor 默认工具。也可以写 `read,grep,glob,ls`。 |
| 仓库地址 | 仅 cloud 使用。留空时尝试无仓库的 Cloud Agent。 |

本地工作目录里的 `.cursor/hooks.json` 会被 Cursor 执行。空目录没有钩子。Cloud Agent 会执行仓库里提交的项目钩子。

对话内容会发送到 Cursor，并按 Cursor 的额度和隐私规则计费。`/cursor_test` 和管理页里的模型测试都会真实跑一次 Agent。

## 添加模型

确认插件已启用，并且「启用插件提供商」是打开的。修改这项后需要重载插件。

在模型提供商页面新增，搜索 **cursor_sdk**（插件通过 AstrBot 的提供商注册接口登记模板，模板名就是提供商类型名）。保存后获取模型列表，添加要用的模型，再把它选成当前会话或默认模型。在线列表来自 `Cursor.models.list()`；拉不到时使用插件配置里的列表。

管理员可以在私聊里发送：

```text
/cursor_test
/cursor_models
```

`/cursor_test composer-2.5` 可以指定模型。测试通过会返回模型、耗时和 `run_id`。

## 和 Codex OAuth 插件的差别

Codex 插件用 OpenAI 账号做 OAuth，然后走 Codex 的聊天接口，所以能直接承接 AstrBot 的函数工具、图片生成和音频。

Cursor 官方给 Python 的入口是 `cursor-sdk`：

- 认证是 API Key，Python SDK 没有对应的浏览器 OAuth 绑定流程。
- 一次调用是一个 Agent 运行，结束时要关掉 Agent。插件使用异步 bridge，并在每轮结束后关闭 Agent。
- 启动失败和运行中失败是两类错误。只有 SDK 标记为可重试、且运行还没开始的错误才会重试。
- 本地默认 `tools=[]`，模型只能回文字。这是为了避免 QQ 消息触发改文件或跑命令。
- AstrBot 的函数工具依赖当前消息事件，提供商接口拿不到这个事件，所以不会转成 Cursor 的自定义工具。人设、上下文压缩和记忆插件写进上下文的内容仍然会放进本轮提示。
- 图片会随本轮消息发给 Agent。纯音频会直接拒绝，请继续用 AstrBot 的语音转文字。

Cloud 模式的 Agent 有自己的工具。自动创建 PR 默认关闭，并跳过把调用者加为审查者。不要把本机的令牌写进 Cloud 环境变量。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 找不到 `cursor_sdk` 提供商模板 | 确认插件已启用，并且「启用插件提供商」打开，然后重载插件、刷新模型页。 |
| 提示还没有 API Key | 把用户密钥或服务账号密钥填进插件配置。占位值 `cursor-plugin` 不会被拿去请求。 |
| 提示还没有安装 cursor-sdk | 重载插件，让 AstrBot 安装 `requirements.txt`。 |
| 工作目录被拒绝 | 留空，或改成 AstrBot 目录以外的项目目录。 |
| 测试成功但聊天仍走别的模型 | 在会话或默认模型里改选刚添加的 Cursor 提供商。 |
| 连接超时 | 把提供商超时或插件的「单次运行超时」调大。Agent 通常比普通聊天补全慢，第一次还要启动本机 bridge。 |
