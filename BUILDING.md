# Build the launcher / 构建启动器

Windows x64，使用已安装 .NET Framework 的 C# 编译器，无需管理员权限：

```powershell
.\tools\build_launcher.ps1
```

此命令只编译可读 C# 启动器到 `build/MeshConverter.exe`，不下载依赖、不修改系统、不签名、不生成完整便携包。入口需要同目录 `app/`、`runtime/python.exe`、`vendor/` 的完整应用布局；不要把单个 EXE 当作独立程序。

源码运行使用 README 的 Python 3.12 独立 venv 流程及固定依赖。Mesh 还必须应用 `vendor_patch` 的两份已校验补丁。便携构建依赖来源与本地修改见 `BUILD_PROVENANCE.json`，安全边界见 `SECURITY.md`。官方上游 wheel 是依赖下载来源；清单不构成相同字节可重现构建的保证。

English: The script builds only the unsigned x64 .NET launcher. It does not create or fetch a Python distribution. Keep the complete portable layout, or run readable source using the pinned venv setup. No administrator privileges or security-setting changes are required.
