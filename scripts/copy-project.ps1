param(
    [Parameter(Mandatory = $true)][string]$Destination
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$source = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$sourceRoot = $source.TrimEnd('\')

if ($Destination.EndsWith('\') -or $Destination.EndsWith('/') -or (Test-Path -LiteralPath $Destination -PathType Container)) {
    $Destination = Join-Path $Destination "Agent1.zip"
}
if (-not $Destination.ToLowerInvariant().EndsWith(".zip")) {
    $Destination = "$Destination.zip"
}

$zipPath = [System.IO.Path]::GetFullPath($Destination)
$zipRoot = $zipPath.TrimEnd('\')

if ($zipRoot -eq $sourceRoot -or $zipRoot.StartsWith($sourceRoot + '\')) {
    Write-Output "FAILED: zip path is inside the project."
    exit 1
}

$parent = [System.IO.Path]::GetDirectoryName($zipPath)
if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

$mode = [System.IO.Compression.ZipArchiveMode]::Create
if (Test-Path -LiteralPath $zipPath) {
    $mode = [System.IO.Compression.ZipArchiveMode]::Update
}

function Get-ProjectFiles([string]$root) {
    $files = New-Object System.Collections.Generic.List[string]
    $pending = New-Object System.Collections.Generic.Stack[string]
    $pending.Push($root)
    while ($pending.Count -gt 0) {
        $dir = $pending.Pop()
        foreach ($child in [System.IO.Directory]::EnumerateDirectories($dir)) {
            $name = [System.IO.Path]::GetFileName($child)
            if ($name -eq ".venv") { continue }
            $attrs = [System.IO.File]::GetAttributes($child)
            if ($attrs.HasFlag([System.IO.FileAttributes]::ReparsePoint)) { continue }
            $pending.Push($child)
        }
        foreach ($file in [System.IO.Directory]::EnumerateFiles($dir)) {
            $files.Add($file)
        }
    }
    return $files
}

Write-Host "Scanning files..."
$files = Get-ProjectFiles $sourceRoot
$total = $files.Count
if ($total -eq 0) {
    Write-Host "No files to pack."
    exit 0
}
Write-Host "Packing $total files into $zipPath"

$updating = $mode -eq [System.IO.Compression.ZipArchiveMode]::Update
$archive = [System.IO.Compression.ZipFile]::Open($zipPath, $mode)
$count = 0
try {
    foreach ($file in $files) {
        $relative = $file.Substring($sourceRoot.Length).TrimStart('\')
        $entryName = $relative.Replace('\', '/')
        if ($updating) {
            $existing = $archive.GetEntry($entryName)
            if ($null -ne $existing) { $existing.Delete() }
        }
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $file,
            $entryName,
            [System.IO.Compression.CompressionLevel]::Fastest
        ) | Out-Null
        $count++
        $percent = [int](($count * 100) / $total)
        Write-Host ("[{0}/{1}] {2,3}%  {3}" -f $count, $total, $percent, $entryName)
    }
}
finally {
    $archive.Dispose()
}

Write-Host "Added $count files to $zipPath"
Write-Host "Skipped every .venv directory. Run uv sync in each agent after unzip."
exit 0
