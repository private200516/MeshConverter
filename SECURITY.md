# Security / 安全说明

Revision: v1.0 · Private0516

校验 NIF 行为图路径和标志，共享碰撞节点及动画控制器链受检查。

加强对特效着色器字段、节点布局和碰撞引用的结构校验，遇到不支持的数据会报告原因。

共享导出沿用路径和重名保护，关闭报告时命令行不保留启动器转录。

## Scope / 范围

这是本地文件转换工具。本次加固针对异常文件造成的过量读取、资源消耗、输出路径逃逸/意外覆盖、预览崩溃影响主界面、启动器日志失控及残留子进程。它不是安全沙箱或恶意软件检测器，也没有获得安全认证。请从项目公开仓库/发布页取得完整程序；保持普通用户权限，不需要管理员运行。

程序没有自动更新、遥测或云端推理。AI 标注描述开发过程，不表示运行时会上传模型、贴图或材质。Mesh 的 WebView2 桥只服务本机受控页面，外部导航及暴露方法有专门限制。依赖安全核验仅向公开服务提交公开包名/版本；没有上传 EXE 或用户资产。

## Implemented controls / 本轮措施

- 启动器使用固定的随包 Python 和入口、独立工作目录与 `-I`，清理子进程的 Python/Qt 搜索路径注入变量，不修改系统环境。
- 标准输出/错误按有界片段处理，单次启动日志限制为 8 MiB；Job Object 在启动器退出时清理归属子进程。启动器正常调用失败会报告错误，不提升权限。

- NIF 同一打开句柄有界读取，拒绝读取期间变化；单文件 512 MiB、头部 64 MiB，字符串/表项/块类型有明确上限。
- GUI、CLI、库存与骨骼参照扫描共用流式预算和取消检查：最多 250,000 个 NIF、250,000 个目录、2,000,000 个目录项、1 TiB 所选 NIF；骨骼参照最多 4096 个/8 GiB。
- 四种转换路线独占创建临时结果，已有文件/硬链接不能在创建时被截断；保留输出边界与禁止覆盖输入的检查。
- 桥参数严格校验；原生选框返回后再次检查忙碌状态。保留本机页面 Host+nonce、CSP、导航锁及七个可调用桥方法的边界。

## Verify your download / 校验下载

每个 ZIP 附 SHA-256；解压目录还有 SHA256SUMS.txt 和 PUBLIC_MANIFEST.json。下载哈希应与同一官方发布页公布值比较。在 PowerShell 中可运行 `Get-FileHash -Algorithm SHA256 -LiteralPath '.\MeshConverter.zip'`。

校验清单能发现相对所发布清单的损坏或变化；如果文件和清单同时被替换，它不能证明发布者身份。自编启动器目前没有受信任的 Authenticode 签名；Windows 的信誉提示仍可能出现。没有添加根证书、关闭杀毒软件或改变系统安全设置。

## Dependencies / 依赖维护

保留已固定的 Python 依赖与两个有来源记录的 pywebview 本地补丁。2026-11-17 对安装版本查询 OSV 并核对本地包；未因此添加新包或扩大 WebView 桥。用户系统上的 WebView2 由系统独立维护。详见 UPSTREAM_DEPENDENCIES.md。

Python 运行时保留 3.12.14，其版本及来源会记录在 BUILD_PROVENANCE.json；没有冒充升级到 3.12.16。上游 3.12 分支安全发行已是源码发行，不能把其他 ABI 的解释器直接覆盖 CP312 原生扩展。审计确认的 TemporaryDirectory 清理竞态涉及本地并发替换目录；Windows 上缺少相关 dir_fd 安全能力，上游新版也保留相应限制。本次没有拼接不兼容的标准库补丁。

已知数据库结果、原生组件及系统 WebView2/Windows 的覆盖范围不同。审计时“无返回漏洞”不等于不存在漏洞。应继续维护经验证的完整运行时；详见上游 [Python 3.12.16](https://www.python.org/downloads/release/python-31216/) 与 [TemporaryDirectory issue](https://github.com/python/cpython/issues/157579)。

## Remaining boundaries / 限制

- 转换器及其子进程以当前用户身份运行。Job Object 管理进程寿命/资源，不限制文件系统和网络权限；它不是 AppContainer。
- 路径检查、独占创建及 Windows 句柄保护降低意外覆盖和部分并发替换风险，不能防住已控制当前用户账户或可改程序目录的进程。不要让不可信进程同时修改输入、输出、程序或临时目录。
- 大小、计数及时间预算会拒绝超限资产。通过合成样本和回归测试不等于任意 NIF、DDS、BGSM/BGEM 均兼容，也不代替游戏内验证。
- 未进行外部渗透测试、完整原生编解码器源码审计或杀毒认证。仍有旧运行时和签名方面的维护工作。

## Reports / 问题报告

报告时注明工具名称、版本 1.0、上述 revision、操作步骤和预期/实际结果；优先提供不含游戏资源或私人路径的最小合成样本。日志、配置和转换报告可能包含本地路径，分享前请检查。不要把包含私人信息的文件直接贴到公开 issue。

English: This revision bounds untrusted input and resource use, strengthens output publication, isolates preview failures, and improves launcher process/log handling. Processes still run as the current user, not in an OS security sandbox. The custom launchers remain unsigned and the bundled CPython remains 3.12.14. Verified download hashes detect changes relative to the published manifest but do not authenticate a replaced manifest. Source, pinned dependencies and third-party notices are provided for review; no safety certification is claimed.
