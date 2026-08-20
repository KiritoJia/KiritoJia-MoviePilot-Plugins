# 115网盘订阅追更（依赖修复版）

结合 MoviePilot 订阅功能，自动搜索 115 网盘资源并转存缺失的电影和剧集。

本版本基于 [`mrtian2016/MoviePilot-Plugins`](https://github.com/mrtian2016/MoviePilot-Plugins) 的 `P115StrgmSub 1.5.3`，保留原插件 ID 和配置空间。`1.5.4` 将已从 PyPI 下架的 `p115client 0.0.8.5.1.1` 更新为经过 Python 3.12 安装与导入验证的 `p115client 0.0.9.6.5.1`；`1.5.5` 兼容新版 MoviePilot 的带来源媒体键，修复缺失剧集被误判为空的问题；`1.5.6` 增加详情页备用渲染，避免历史数据异常时无法打开插件详情；`1.5.8` 兼容 MoviePilot V3 的订阅媒体身份字段；`1.5.9` 兼容 V3 的 `recognize_media(media_source, media_id)` 调用和下载历史字段，同时保留 V2 的旧接口。

本项目遵循 GNU General Public License v3.0，原作者为 `mrtian2016`。
