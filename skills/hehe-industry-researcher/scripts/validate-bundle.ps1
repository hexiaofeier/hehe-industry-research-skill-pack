param(
    [string]$SkillsRoot
)

$ErrorActionPreference = 'Stop'

$skillDir = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $skillDir 'package-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Find-SuiteRoot {
    param([string]$StartPath)

    $cursor = [System.IO.DirectoryInfo]::new((Resolve-Path -LiteralPath $StartPath).Path)
    $probeRelative = ([string]$manifest.required_specialty_skills[0].suite_path).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    while ($null -ne $cursor) {
        if ((Test-Path -LiteralPath (Join-Path $cursor.FullName 'CODEX.md')) -and
            (Test-Path -LiteralPath (Join-Path $cursor.FullName $probeRelative))) {
            return $cursor.FullName
        }
        $cursor = $cursor.Parent
    }
    return $null
}

$suiteRoot = Find-SuiteRoot -StartPath $skillDir
if ([string]::IsNullOrWhiteSpace($SkillsRoot)) {
    if ($null -ne $suiteRoot) {
        $SkillsRoot = $suiteRoot
        $layout = 'suite'
    }
    else {
        $SkillsRoot = Split-Path -Parent $skillDir
        $layout = 'flat'
    }
}
else {
    $SkillsRoot = (Resolve-Path -LiteralPath $SkillsRoot).Path
    $probeRelative = ([string]$manifest.required_specialty_skills[0].suite_path).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    $layout = if ((Test-Path -LiteralPath (Join-Path $SkillsRoot $probeRelative))) { 'suite' } else { 'flat' }
}

function Resolve-SkillPath {
    param($Item)

    if ($layout -eq 'suite') {
        return Join-Path $SkillsRoot ([string]$Item.suite_path).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    }
    return Join-Path $SkillsRoot ([string]$Item.name)
}

function Test-SkillPresent {
    param($Item)

    $path = Resolve-SkillPath -Item $Item
    $skillFile = Join-Path $path 'SKILL.md'
    $exists = Test-Path -LiteralPath $skillFile
    $nameMatches = $false
    if ($exists) {
        $head = Get-Content -LiteralPath $skillFile -Encoding UTF8 -TotalCount 12
        $nameMatches = [bool]($head | Where-Object { $_ -eq "name: $($Item.name)" })
    }
    [pscustomobject]@{
        Dependency  = [string]$Item.name
        Present     = $exists
        NameMatches = $nameMatches
        Path        = $path
    }
}

# The complete router bundle requires all 13 specialty skills. Specialty skills remain
# independently installable, but a partial set is not a complete router bundle.
$specialtyRows = @($manifest.required_specialty_skills) | ForEach-Object { Test-SkillPresent -Item $_ }
$specialtyPresentCount = @($specialtyRows | Where-Object { $_.Present -and $_.NameMatches }).Count
$specialtyTotal = @($manifest.required_specialty_skills).Count

$entryFile = Join-Path $skillDir 'SKILL.md'
$entryPresent = Test-Path -LiteralPath $entryFile
$entryNameMatches = $false
if ($entryPresent) {
    $entryHead = Get-Content -LiteralPath $entryFile -Encoding UTF8 -TotalCount 12
    $entryNameMatches = [bool]($entryHead | Where-Object { $_ -eq "name: $($manifest.entry_skill)" })
}

$sharedRows = @()
foreach ($item in @($manifest.shared_public_files)) {
    $sharedPath = Join-Path $SkillsRoot ([string]$item.suite_path).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    $requiredHere = ($layout -eq 'suite') -and [bool]$item.required_in_suite_layout
    $present = if ($requiredHere) { Test-Path -LiteralPath $sharedPath } else { $true }
    $sharedRows += [pscustomobject]@{
        SharedRule   = [string]$item.suite_path
        RequiredHere = $requiredHere
        Present      = $present
        Path         = $sharedPath
    }
}

Write-Output "Profile: $($manifest.profile)"
Write-Output "Layout: $layout"
Write-Output "Root: $SkillsRoot"

Write-Output "`nRequired specialty skills ($specialtyPresentCount/$specialtyTotal valid):"
$specialtyRows | Format-Table -AutoSize

$sharedRows | Format-Table -AutoSize

$passed = $entryPresent -and $entryNameMatches -and
    ($specialtyPresentCount -eq $specialtyTotal) -and
    -not ($sharedRows.Present -contains $false)

Write-Output "EntryPresent=$entryPresent"
Write-Output "EntryNameMatches=$entryNameMatches"
Write-Output "RequiredSpecialtySkillsValid=$specialtyPresentCount/$specialtyTotal"

if (-not $passed) {
    Write-Error 'Industry researcher complete bundle validation failed.'
    exit 1
}

Write-Output 'Industry researcher bundle validation passed.'
