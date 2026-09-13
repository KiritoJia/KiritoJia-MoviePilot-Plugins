# KiritoJia MoviePilot 插件仓

收录 Kirito 字幕下载助手、Kirito Kirito Emby缺集自动订阅、Kirito 115网盘订阅追更和 Kirito 115网盘STRM助手四个 MoviePilot V2 插件。

> 自动刮削媒体库影片字幕，支持常见视频格式及 STRM 格式。

## 主要能力

- 整理完成后自动搜索字幕，或定时监控自定义媒体目录。
- 首次扫描处理已有媒体，后续使用持久化索引增量处理。
- 支持本地常见视频格式、相对/绝对本地 `.strm` 和 HTTP(S) `.strm`。
- 支持射手网、迅雷影音、MoviePilot 字幕站点、ASSRT、OpenSubtitles。
- 简中&英文双语优先，其次简中、繁中；每个媒体只落盘一个字幕。
- 字幕名称与目标媒体主文件名一致。
- 内置任务队列、匹配记录、手动搜索、来源诊断、批量恢复中断任务和批量清理终态任务。

## 仓库结构

```text
plugins.v2/subtitledownloadassistant/  Kirito 字幕下载助手
plugins.v2/kiritoembymissingsubscribe/       Kirito Emby 缺集自动订阅插件
plugins.v2/kiritop115strgmsub/        Kirito 115 网盘订阅追更插件
plugins.v2/kiritop115strmhelper/      Kirito 115 网盘 STRM 助手插件
icons/                                插件图标
package.json                          插件仓库元数据
```

## 安装

在 MoviePilot 的插件市场设置中添加第三方插件仓库：

```text
https://github.com/KiritoJia/KiritoJia-MoviePilot-Plugins
```

添加后可在插件市场安装“Kirito 字幕下载助手”“Kirito Kirito Emby缺集自动订阅”“Kirito 115网盘订阅追更”或“Kirito 115网盘STRM助手”。仓库根目录的 `package.json` 会提供版本信息；在线安装和更新使用 MoviePilot 规范的 Release ZIP，避免逐文件下载。

[GitHub Releases](https://github.com/KiritoJia/KiritoJia-MoviePilot-Plugins/releases) 同时提供可本地上传的 ZIP。手工安装时，把插件目录复制到：

```text
/app/app/plugins/subtitledownloadassistant
```

安装依赖：

```bash
/opt/venv/bin/python3 -m pip install -r /app/app/plugins/subtitledownloadassistant/requirements.txt
```

详细配置和运行要求见[插件说明](plugins.v2/subtitledownloadassistant/README.md)。

“Kirito 115网盘订阅追更”是本仓库维护的独立发行版，使用独立插件 ID 和配置空间，不会覆盖其他同类插件；它使用 `p115client 0.0.9.6.5.1`，不再需要手工修改容器内的 `requirements.txt`。

## 项目关系

这是一个具有独立插件 ID、配置和数据空间的 KiritoJia 独立发行版，不会覆盖其他字幕插件。项目遵循 GNU GPL v3；相关源代码和许可证信息保留在各插件目录中。射手/迅雷协议实现按公开协议重新实现。

## 许可证

[GNU General Public License v3.0](LICENSE)
