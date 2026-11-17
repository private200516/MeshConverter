# 较早的 runtime-motion 验证记录（2026-11-17）

公开版本仍为 **ALPHA 1.0**，作者 **private0516**。此文档保留较早一轮本地修复和 315 项测试的历史记录；当前 323 项结果见 MOTION_REVISION_20261117.md。

- Mesh：96 项回归通过；真实 EXE 的扫描、转换、日志桥接和退出通过。合成节点与分区三角形双向 CLI、预检、已有输出保护和错误隔离通过。
- Texture：219 项回归通过；真实 EXE 的 BGSM/BGEM、DDS 编码、预检与重复转换通过。随附 texconv 实际生成 BC7/BC5 和 5 层 mipmap。
- Texture 便携应用文件使用原生 Windows Qt 窗口复测了启动、中英文、页面/About、17,750 条合成日志、最小化和关闭；普通及减少动效两种模式均通过。
- Mesh 同机 1.5s 测试：预览约 28.6fps → 60.6fps，后台及关闭旋转后无持续绘制；日志手动浏览位置保留。
- Qt 使用 16ms 精确计时器及实际耗时推进。便携版日志负载测试心跳中位数 15.82ms、p95 31.04ms，包含启动和截图的最大值 331.9ms。没有将其描述为稳定 60fps。
- 修复了预检混入上一轮转换事件/计数、按钮没有按下也触发，以及按钮键盘操作。更新了陈旧测试夹具，使其验证实际目标分支。

测试使用合成 NIF、BGSM/BGEM 和小尺寸 DDS；没有复测广泛游戏资产或游戏内表现。反向 Texture 仅验证材质。Mesh 预览帧率是同机 Chrome 测试结果，Qt 的 16ms 调度也不代表任何负载下都稳定达到 60fps。

独立的旧版本备份位于工作区 archive/before-runtime-motion-20261117/。完整本地证据位于 validation/runtime-motion-20261117/。该验证阶段尚未同步 GitHub 或 Nexus；后续 GitHub 同步以仓库提交记录为准。

English: 315 automated checks passed (Mesh 96; Texture 219), plus real launcher CLI checks, native WebView2 smoke and native Windows Qt tests against the synchronized portable application files. Fixtures were synthetic; game compatibility and in-game rendering were not revalidated. Original author, AI attribution and licenses remain with the tools.

## 完整动画设置更新 / Full-motion update — 2026-11-17

Mesh 已移除“减少动态效果”设置，清除旧的该项偏好，并完整播放程序动画。系统减少动画偏好不再锁定本程序的动画；后台、失焦及关闭预览旋转时的暂停机制保留。

The reduced-motion option has been removed from Mesh Converter. The old preference is cleared and full application animations remain enabled even when the operating system requests reduced motion. Background rendering pauses and the separate model-rotation setting continue to work.
