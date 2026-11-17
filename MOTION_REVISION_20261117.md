# Toolkit 动效重做 — 2026-11-17

参考：https://www.pinterest.com/pin/968273988657956593/

两款工具以代码原生绘制红点定位、圆形放大擦入、遮罩文字、工作区分组展开和阶梯遮罩关闭。程序没有捆绑参考视频、作者标识或新字体。公开版本仍为 ALPHA 1.0，作者 private0516，原有 AI 与许可说明保留。

- 启动约 1400ms：红点与弧线、橙圆擦入、标题揭示、奶白画面及实际工作区分组展开。
- 关闭约 650ms：内容退景、六层交错墨色遮罩、橙标收束，最后 80ms 淡出。
- 配套页面、对话框、按钮、胶囊和日志动画；保留后台暂停、有界日志与手动滚动位置。
- Mesh 的“减少动态效果”选项保持移除；两款工具默认播放完整动画。没有修改 Windows 系统设置。
- 首次许可弹窗在完整启动结束后显示。关闭期间不会晚弹 About；启动中关闭、重复关闭、忙碌取消和失败恢复均有测试。

## 已完成验证

323 项回归全部通过：Mesh 96 项、Texture 227 项，无失败、错误或跳过。转换引擎、运行库和已有原生依赖没有改动。

Mesh 以真实 EXE/WebView2 验证扫描、合成模型转换、原生动画关闭以及启动中关闭。首次并行冷启动测试未就绪，失败记录保留；最终使用隔离的串行实例，两种情况均通过并记录最终 UI/主机哈希。隐藏测试窗口的关闭总耗时包含后台计时器和原生销毁，不能当作可见窗口的动画帧时长。

Texture 以原生 Windows Qt 验证便携 app 文件，普通及显式测试减少动效两种模式均通过。19 张时间片覆盖启动、页面/About 及关闭阶段；最小化停止帧计时，空闲无亚秒级计时器，高频合成日志仍有界。数据不是稳定 60fps 的承诺。

本轮没有重跑真实游戏素材或游戏内验证；原有合成 NIF、材质及 DDS 测试不能证明任意资产兼容。Windows/字体/第三方组件的既有许可仍单独适用。

## 使用更新

关闭旧窗口，完整解压新版 ZIP 或重新打开已更新的恢复目录。保留 app/、runtime/、vendor/ 和许可证目录。两款程序仍分别下载、独立运行。启动器 EXE 为原有入口，更新由配套应用源文件提供。

English: Native geometric motion inspired by the linked reference, with 1400ms startup and 650ms shutdown plus matching UI transitions. All 323 regression tests passed, together with isolated native WebView2 and Windows Qt checks against the final portable files. No reference video, new runtime dependencies or game fixtures are bundled. In-game compatibility was not revalidated. Extract the complete application directory and restart any older window.
