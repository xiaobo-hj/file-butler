# File Butler

个人知识库 Agent / 个人文件管家项目。

用户上传文件后，Agent 分析内容并给出整理建议；用户确认后，再执行移动、重命名、打标签等操作，并维护目录结构、文件元数据和个人知识库。

## Current Scope

当前只包含规范的空项目结构，不实现具体业务逻辑。

## Project Layout

```text
file-butler/
  server/                  # Python backend managed by uv
  client/                  # Vue frontend
```

## Directories

- `server`: backend API, Agent orchestration, file operations, metadata, and tests.
- `client`: frontend pages, components, stores, services, assets, and tests.
