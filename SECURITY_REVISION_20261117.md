# 安全修订 / Security revision — 2026-11-17

ALPHA 1.0 · private0516 · security-hardening-20261117

两款工具继续分别分发；界面、字体、中英排版、1400ms 启动与 650ms 关闭动效保留。本次重点修复文件读取、输出发布、进程和日志的安全边界。

- Mesh：同句柄有界 NIF 读取、头部及表项预算、四条转换路线独占创建、严格桥参数、选框并发检查及有界扫描。
- Texture：受保护有界读取、Windows 路径/句柄防护、PNG/DDS 格式限定、独占暂存与发布、texconv 输出安全复制、独立预览进程的取消/超时/内存预算，修复关闭后晚弹取消错误框；扫描有独立资源/目录/总条目/字节预算。
- 两启动器：单条输出 4096 字符、单次日志 8 MiB；显式隔离 Python 环境，固定入口与路径。应用先分配到 Job，再放行入口；正常或强制结束启动器时清理所拥有的子进程。
- Texture 使用 SHA-256 校验过的官方 Pillow 13.0.0 与 matched PySide6-Essentials/shiboken6 6.12.0 wheel；保留必要 Qt 模块、许可与部署清单。

## 验证

399 项回归全部通过：Mesh 122、Texture 277，无失败、错误或跳过。其中包含 16 项启动器测试。异常/超限输入、Windows junction/硬链接、并发替换保护、取消、超时、异常退出、内存拒绝和正常编解码均有合成 fixture。

最终 Mesh EXE 以真实 WebView2 完成辅助节点 NIF 的扫描、转换、回读及关闭，并通过启动中关闭。Texture 使用最终 EXE 的隔离测试入口，在 Windows Qt 上构建最终便携 app 的实际 MainWindow，验证中英文/页面/许可/日志/启动关闭动效，保留 19 张时间片；不是系统 UI 自动化或稳定 60fps 认证。正式 Texture EXE CLI 实际转换 BGSM/BGEM 并回读版本/参数；预览在启动器外层 Job 内再创建受限 worker 的正向验证也通过。

完整回归以各产品真实随包解释器与更新后的依赖运行；部署文件与测试源码逐文件核对。没有重新测试所有真实游戏资产或游戏内效果。公开可读的结果摘要在 SECURITY_VALIDATION.json，构建/依赖记录在 BUILD_PROVENANCE.json。

## 使用与边界

关闭旧窗口，完整解压对应 ZIP 到独立目录再运行；不要只替换 EXE 或把新旧 vendor 混在一起。原文件不在本次验证中修改；请使用独立输出目录。

这是加固，不是绝对安全承诺。Job Object 是同用户的资源/生命周期管理，非 OS 沙箱；Python 仍为 3.12.14，启动器仍未签名。没有外部安全认证、杀毒白名单或系统防护改动。具体限额、已知运行时维护事项和报告方式见 SECURITY.md。

English: This local ALPHA 1.0 revision strengthens bounded parsing, exclusive output publication, Windows path handling, preview fault isolation and launcher process/log handling. All 399 regression tests passed, together with targeted native Windows and installed CLI checks. Pillow and matched Qt bindings were updated from hash-verified official wheels. CPython remains 3.12.14 and custom launchers remain unsigned. This is not an OS sandbox or security certification. Extract the complete ZIP and restart; in-game compatibility was not revalidated.
