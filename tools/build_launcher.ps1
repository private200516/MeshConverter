param([string]$OutputPath)
$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$compiler = Join-Path ([Environment]::GetFolderPath('Windows')) 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) { throw 'The Windows .NET Framework x64 C# compiler was not found.' }
if (-not $OutputPath) { $OutputPath = Join-Path $sourceRoot 'build/MeshConverter.exe' }
$resolvedOutput = [IO.Path]::GetFullPath($OutputPath)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($resolvedOutput)) | Out-Null
$buildArgs = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/reference:System.Windows.Forms.dll',
    ('/out:' + $resolvedOutput), ('/win32icon:' + (Join-Path $sourceRoot 'app.ico')),
    ('/win32manifest:' + (Join-Path $sourceRoot 'launcher.manifest')), (Join-Path $sourceRoot 'Launcher.cs'))
& $compiler @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Get-FileHash -LiteralPath $resolvedOutput -Algorithm SHA256
