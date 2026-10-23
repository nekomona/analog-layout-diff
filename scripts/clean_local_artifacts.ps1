[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPrefix = $taskRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'pyproject.toml'))) {
    throw 'Run this script from the Layout Diff source tree.'
}

$taskTargets = [Collections.Generic.List[string]]::new()
$taskPending = [Collections.Generic.Stack[string]]::new()
$taskPending.Push($taskRoot)
while ($taskPending.Count) {
    $taskDirectory = $taskPending.Pop()
    foreach ($taskChild in Get-ChildItem -Force -LiteralPath $taskDirectory -Directory) {
        if ($taskChild.Name -in @('.git', '.venv', '.local')) { continue }
        if ($taskChild.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        if ($taskChild.Name -in @('.cache', '.pytest_cache', '__pycache__', '.artifacts', 'evidence') -or
            $taskChild.Name -like '.test-tmp*' -or
            ($taskDirectory -eq $taskRoot -and $taskChild.Name -in @('artifacts', 'gui-workspace'))) {
            $taskResolved = (Resolve-Path -LiteralPath $taskChild.FullName).ProviderPath
            if (-not $taskResolved.StartsWith($taskPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove a directory outside the workdir: $taskResolved"
            }
            $taskTargets.Add($taskResolved)
        } else {
            $taskPending.Push($taskChild.FullName)
        }
    }
}

$taskFiles = 0
$taskBytes = 0L
$taskRemoved = 0
foreach ($taskTarget in $taskTargets) {
    $taskContents = @(Get-ChildItem -Force -Recurse -LiteralPath $taskTarget -File)
    $taskFiles += $taskContents.Count
    $taskBytes += ($taskContents | Measure-Object -Property Length -Sum).Sum
    if ($PSCmdlet.ShouldProcess($taskTarget, 'Remove generated local test artifacts')) {
        Remove-Item -LiteralPath $taskTarget -Recurse -Force
        $taskRemoved++
    }
}
Write-Output ('Removed {0} generated directories; selected {1} files, {2:N2} MiB.' -f
    $taskRemoved, $taskFiles, ($taskBytes / 1MB))
