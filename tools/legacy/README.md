# 历史本机构建脚本 / Historical local builders

此目录保留原有构建脚本，供阅读和追溯。它们依赖原开发环境的 Python 运行库、依赖缓存、工作目录及 Windows 编译器，不能作为新克隆仓库的通用构建入口。

移入本目录后，原有 `SOURCE` / `PROJECT` 相对路径推导也不适用于当前源码根布局。不要直接运行这些脚本。仓库未提供替代的通用打包构建器。

开发启动方式、固定依赖和 Mesh 补丁部署见根目录 `README.md` 与 `UPSTREAM_DEPENDENCIES.md`。源码启动、既有 B6 工程记录和重新构建可分发二进制属于不同范围；整理本目录时未执行构建或测试。

These historical machine-local builders are source references. Their cache paths and relative-root assumptions are not portable after relocation. Do not run them as a generic build command. See the root documentation for source development; no replacement packaging builder is supplied or validated here.
