# MeshConverter 上游依赖

项目代码采用 GPL-3.0。依赖、格式参考和第三方资产各有自己的权利边界；保留原始版权和许可，不把项目许可套用于第三方资源。本包不捆绑完整 Python runtime 或安装后的 site-packages。

## 固定依赖

Windows x64、Python 3.12；安装版本由 `requirements-runtime.txt` 固定，并由 `requirements.txt` 引用：

| 包 | 版本 |
|---|---|
| pywebview | 6.2.1 |
| pythonnet | 3.1.0 |
| clr_loader | 0.3.1 |
| cffi | 2.1.1 |
| pycparser | 3.0 |
| proxy_tools | 0.1.0 |
| bottle | 0.13.4 |
| typing_extensions | 4.16.0 |

GUI 源码入口 `app.py` 需要 Windows .NET Framework 和 Microsoft Edge WebView2 Runtime。本包包含核对后的原始 `ui.html`、字体、图标和救护车线框界面资源；其公开发布已获用户明确授权。系统运行库仍须由使用者准备，不随源码自动安装。

## 必须部署的本地 pywebview 补丁

本地补丁基于 pywebview 6.2.1，包含以下两个文件。它不是新的上游版本，也不是安全认证。原始 BSD-3-Clause 版权和许可在 `vendor_patch/LICENSE.pywebview.txt`；详情和机器可读身份在 `vendor_patch/README.md`、`vendor_patch/manifest.json`。

| 相对 site-packages 路径 | 上游 SHA256 | 补丁 SHA256 |
|---|---|---|
| `webview/util.py` | `a652bd05bfb9a7a9521e8ab52f10425161fa6a84077a92ca5dcd255359b836a4` | `73829dd5ba5c18c25a01a1c727ddf254c67ce07397c329df6f9d53c0cae3be62` |
| `webview/platforms/edgechromium.py` | `f3f9168ecb39f7447566112fd14c5ec55830eddf02053eafef0d86fac509a3a4` | `96551b7d64d223faed8430c623d269a33f293545976c0f973f8f9927bc38d862` |

以下是手工部署命令，不会由仓库自动执行。先按 README 创建全新的 `.venv` 并安装固定依赖，再在源码根目录执行一次。两份原始文件及两份补丁都核对成功后才复制；任何不符立即停止，不修改全局 Python，也不修改上游 `.dist-info`。

```powershell
$ErrorActionPreference = 'Stop'
$patchManifest = Get-Content -LiteralPath .\vendor_patch\manifest.json -Raw | ConvertFrom-Json
if ($patchManifest.upstream_package -cne 'pywebview' -or $patchManifest.upstream_version -cne '6.2.1' -or @($patchManifest.files).Count -ne 2) { throw 'Unexpected patch manifest' }
$patchPaths = @('webview/util.py', 'webview/platforms/edgechromium.py')
foreach ($rel in $patchPaths) {
    $entry = @($patchManifest.files | Where-Object { $_.path -ceq $rel })
    if ($entry.Count -ne 1) { throw 'Unexpected patch member' }
    $upstream = Join-Path .\.venv\Lib\site-packages $rel
    $overlay = Join-Path .\vendor_patch $rel
    if ((Get-FileHash -LiteralPath $upstream -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry[0].upstream_sha256) { throw 'Upstream file differs; stop' }
    if ((Get-FileHash -LiteralPath $overlay -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry[0].patched_sha256) { throw 'Patch file differs; stop' }
}
Copy-Item -LiteralPath .\vendor_patch\webview\util.py -Destination .\.venv\Lib\site-packages\webview\util.py -Force -ErrorAction Stop
Copy-Item -LiteralPath .\vendor_patch\webview\platforms\edgechromium.py -Destination .\.venv\Lib\site-packages\webview\platforms\edgechromium.py -Force -ErrorAction Stop
foreach ($rel in $patchPaths) {
    $entry = @($patchManifest.files | Where-Object { $_.path -ceq $rel })[0]
    if ((Get-FileHash -LiteralPath (Join-Path .\.venv\Lib\site-packages $rel) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.patched_sha256) { throw 'Installed patch readback differs' }
}
```

保留 `vendor_patch` 记录。安装元数据的 `RECORD` 仍描述上游文件，补丁清单描述本地替换后的两个文件；不能声称打补丁后的目录仍逐字等于原始 wheel。

## 其他来源与未捆绑资源

- `havok/bhk_autopack.py`、`havok/bhk_autounpack.py`：PyNifly V28.2，保留原 GPL-3.0 版权和许可。来源：[PyNifly V28.2](https://github.com/BadDogSkyrim/PyNifly/releases/tag/V28.2)。
- NIF 格式参考：[niftools/nifxml](https://github.com/niftools/nifxml)。格式支持仍受本项目实现与验证范围限制。
- pywebview 上游：[pywebview](https://github.com/r0x0r/pywebview)；WebView2 官方入口：[Microsoft WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)。链接只供开发者查阅，本次未联网获取或安装。
- 原包字体、图标及 Mesh HTML/救护车线框资源已获用户明确授权公开发布，并按核对后的原始字节随包保留。第三方资源和依赖仍适用各自条款；资源授权不构成对全部第三方许可的统一认证。

`tools/legacy/` 旧构建器只是本地工程参考，不是可移植的构建保证。本包不提供完整依赖源码归档或预编译运行时，不能仅凭上述链接声称完成了未来二进制分发的全部许可工作。Python、pythonnet 及其依赖应保留各自官方包元数据和许可；见项目现有第三方说明。

English: Use the pinned Python 3.12 environment and manually verify both upstream files and both overlays before applying the local pywebview patch. Keep BSD notices and upstream metadata. PyNifly code retains GPL notices. Original UI HTML, fonts, icon and ambulance wireframe are included with confirmed user authorization. Legacy builders remain local references, not a new general-purpose release build.
