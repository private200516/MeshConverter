# MeshConverter — ALPHA 1.0 / 2026-11-17 motion revision

作者：private0516。项目包含使用 GPT-6 Astra 辅助开发的 AI 生成代码与界面。

- 启动 1400ms：红点、弧线、圆形擦入、遮罩标题与工作区分组展开。
- 关闭 650ms：交错阶梯遮罩、橙标收束与末段淡出。
- 统一页签、弹窗、按钮与日志动效，覆盖中断启动、重复关闭、忙碌取消及失败恢复。
- 两款工具合计 323 项回归通过；另验证原生 WebView2 与 Windows Qt。

完整范围见 [MOTION_REVISION_20261117.md](MOTION_REVISION_20261117.md)。测试使用合成素材，未复测广泛游戏资产或游戏内效果。转换引擎与运行依赖保持已验证版本。

English: New coordinated 1400ms startup and 650ms shutdown, plus page, dialog, button and log motion. All 323 automated checks passed, with separate native WebView2 and Windows Qt smoke checks. See the linked validation scope; no in-game acceptance is claimed.
