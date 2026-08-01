# 字幕下载助手

自动刮削媒体库影片字幕，支持常见视频格式及 STRM 格式。

## 功能

- 监听 MoviePilot 整理完成事件，自动搜索并落盘一个合格字幕。
- 递归扫描多个容器内媒体目录，支持本地视频与 `.strm` 文件。
- 保存增量扫描索引，只处理新增、变更或人工重试的媒体。
- 支持射手网、迅雷影音、MoviePilot 字幕站点、ASSRT 和 OpenSubtitles。
- 自动候选优先级为简中&英文、简中、繁中，多字幕包直接放弃。
- 字幕文件沿用媒体完整主文件名，例如 `影片 (2026) - 2160p.strm` 对应 `影片 (2026) - 2160p.ass`。
- 提供任务、匹配记录、手动搜索、字幕源状态、批量恢复中断任务和一键清理终态任务工作台。

## 安装

推荐在 MoviePilot 插件市场设置中添加在线仓库：

```text
https://github.com/KiritoJia/SubtitleDownloadAssistant
```

添加后可在插件市场安装和更新“字幕下载助手”。也可以从 [GitHub Releases](https://github.com/KiritoJia/SubtitleDownloadAssistant/releases) 下载 ZIP 本地安装，或把 `subtitledownloadassistant` 目录放入：

```text
/app/app/plugins/subtitledownloadassistant
```

然后安装依赖：

```bash
/opt/venv/bin/python3 -m pip install -r /app/app/plugins/subtitledownloadassistant/requirements.txt
```

首次手工放置插件目录后需重启 MoviePilot 完成插件发现。

## 使用要求

- MoviePilot `>= 2.15.1`
- 自定义目录必须是 MoviePilot 容器内可见且可写的绝对路径。
- 射手查询必须读取真实视频内容指纹；远程 `.strm` 的播放地址需支持 HTTP Range。
- 迅雷对 `.strm` 直接按文件名搜索且不读取内部地址；本地真实视频会额外使用 CID 标记精确匹配。

## 独立身份

插件类名为 `SubtitleDownloadAssistant`，目录为 `subtitledownloadassistant`，并使用独立配置前缀、PluginData、缓存区、搜索会话和 Vue 联邦名。它可以与 `SubtitleAssistant` 或其他修改版并存，不会读取原插件保存的账号凭据和任务记录。

## 来源与许可证

本项目基于 yubanmeiqin9048 的 `SubtitleAssistant 1.0.1` 修改，并继续使用 GNU GPL v3 许可证。射手 Hash、迅雷 CID 与公开接口协议参考 [91270/MeiamSubtitles](https://github.com/91270/MeiamSubtitles) 重新实现；项目不嵌入 Emby DLL，也不依赖 .NET 运行时。
