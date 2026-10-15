# MeshConverter · ALPHA 1.0

在本地转换受支持的 Fallout 76 BS155 ↔ Fallout 4 BS130 NIF 结构。项目代码采用 GPL-3.0；作者为 private0516。原项目使用 GPT-6 Astra 辅助开发，代码与界面包含 AI 生成内容。本项目不代表 Bethesda、OpenAI 或依赖项目背书。

这是完整的源代码开发包，包含原包的 `ui.html`、字体、图标及救护车线框界面资源；这些资源的公开发布已获用户明确授权，内容按核对后的原始字节保留。包内没有预编译产品 EXE、Python runtime 或安装后的 vendor 依赖，也不提供用于转换的游戏样本或游戏资源库。第三方组件仍适用各自许可。

## Windows 下载

[MeshConverter.zip](downloads/MeshConverter.zip) · [SHA256 校验文件](downloads/MeshConverter.zip.sha256)

下载后先核对 ZIP 的 SHA256，再完整解压，并保留包内配套目录。Windows 分发包与源码开发包分别审核，文件布局以下载包内说明为准；下文的源码环境说明不描述 ZIP 内的组件。

ZIP 使用上面的独立校验文件。`SOURCE_MANIFEST.json` 仅记录源码文件身份，不是下载 ZIP 的校验清单。源码准备流程不生成 Windows ZIP，也不据这些链接声称已经重新构建产品、验证重新打包结果，或确认其与历史 B6 ZIP 逐字相同。下载包的内容与打包校验由独立分发审核负责。

## 安装源码依赖

在仓库根目录使用 Windows x64 与 Python 3.12，创建独立环境。以下是供开发者自行执行的命令；本次文档整理没有执行安装、产品或测试。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

依赖版本由 `requirements-runtime.txt` 固定。继续前，必须按 [UPSTREAM_DEPENDENCIES.md](UPSTREAM_DEPENDENCIES.md) 校验并部署 `vendor_patch/manifest.json` 指定的两个 pywebview 补丁文件；不能只安装上游包后把它当作本项目已审查的 GUI 依赖。补丁仅部署到这个独立 venv，保留上游 BSD 版权、许可和 `.dist-info` 元数据。

本仓库以源码根目录为工作目录，开发时不需要 `app/`、`runtime/`、`vendor/` 的发布包布局。Windows GUI 还需要 .NET Framework 和已安装的 Microsoft Edge WebView2 Runtime；本包不自动安装或修改这些系统组件。

## GUI 源码启动

完成固定依赖安装和两个 pywebview 补丁的核验部署后，在仓库根目录启动：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .\app.py
```

选择转换方向、输入目录和独立输出目录，再扫描并转换。带蒙皮的输入应选择匹配的目标骨架参考。救护车线框是界面资源，不是当前输入 NIF 的预览。完整保留逐文件结果和警告；本次没有重新运行此源码入口或验收 GUI。

## CLI

输入和输出必须分离。下列相对目录由使用者自行准备，仓库不提供游戏文件。先备份自己的资产，输出使用新目录；不要把游戏资源或运行结果提交到仓库。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .\batch_nif.py '..\assets-owned\mesh76' '..\results\mesh-preflight' --direction 76-to-4 --no-collision --preflight
.\.venv\Scripts\python.exe -B -X utf8 .\batch_nif.py '..\assets-owned\mesh76' '..\results\mesh-76-to-4' --direction 76-to-4 --no-collision
.\.venv\Scripts\python.exe -B -X utf8 .\batch_nif.py '..\assets-owned\mesh4' '..\results\mesh-4-to-76' --direction 4-to-76 --no-collision
```

`--preflight` 不写 NIF 输出，但会写 JSON 报告；它不是零写入操作。`--no-collision` 明确关闭碰撞输出，不能据此声称物理效果保留。带蒙皮的输入还需要匹配目标游戏、角色家族及第一/第三人称变体的骨架参考，可用 `--reference` 指定目标 Meshes 目录或 `skeleton.nif`。

检查每个文件的 `passed`、`rejected`、`skipped` 和具体原因。已有目标文件会跳过；支持的二进制结构通过校验，不等于已在游戏内验证。此工具不转换 BGSM、BGEM 或 DDS，也不提供通用骨骼重定向、完整 Havok 物理迁移或任意 NIF 支持。

## 已有验证与当前边界

既有 B6 工程记录中，Mesh 与 Texture 两个工具合计有 **166 项自动化合成检查：原批次 164 项，加独立夹具修正后的 2 项补充检查**；不是每个仓库各 166 项。两项补充针对 Mesh 调度测试，使用单独的修正夹具。原 T8 聚合报告仍保留失败状态，不改写成全通过。

准备包已按批准纳入 `tests/test_scheduling.py` 的夹具修正，原产品代码不因此改变。166 仍是上述历史检查记录的合计，不是本次准备包的新测试结果。本次未运行当前仓库的测试，不能承诺 `unittest discover` 全绿或得到 166 项。开发者可在完成依赖和补丁校验后自行检查：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

既有合成 CLI 记录覆盖 Mesh 两个转换方向，以及 Texture 两个方向的材质单独转换。这些历史记录不等于本次源码包重新测试通过。真实资产普适兼容性、游戏内效果、GUI 取消延迟、完整动态安全与杀毒软件放行均未由此确认。

## 构建、隐私与许可

`tools/legacy/` 中的旧构建器仅保留为本地工程参考，依赖原开发环境，不是新的通用公开构建流程。本包没有新生成或认证任何发布二进制。

正常 GUI 会在当前用户本地应用数据目录保存偏好、WebView2 数据和启动日志；CLI 报告也可能包含输入路径、文件名和哈希。分享报告前检查这些本地信息。此处不附原始审计报告、机器标识或私人路径。

项目代码见 [LICENSE](LICENSE)。PyNifly 的 Havok 代码及 pywebview 补丁保留各自原始版权和许可，见 [THIRD_PARTY.md](THIRD_PARTY.md)、`vendor_patch/LICENSE.pywebview.txt` 与 [UPSTREAM_DEPENDENCIES.md](UPSTREAM_DEPENDENCIES.md)。资源随包发布的范围已获用户确认；项目 GPL 不重新许可第三方字体、图标、依赖或其他人的游戏资产，也不构成对所有第三方许可的统一认证。

English: Complete source-development package with the original authorized UI HTML, fonts, icon and ambulance wireframe. Install pinned dependencies, verify/apply the two local pywebview overlays in an isolated venv, then run `python app.py` on Windows with .NET Framework and WebView2. Product EXEs and packaged runtimes are not included. Historical combined checks are not a fresh pass of this repository; game, security, cancellation-latency and release acceptance remain unverified.
