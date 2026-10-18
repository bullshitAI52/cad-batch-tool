param(
    [string]$AcadPath = '',
    [ValidateRange(1,20)][int]$Passes = 4,
    [ValidateRange(30,7200)][int]$TimeoutSeconds = 600,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Files
)
$ErrorActionPreference = 'Stop'
if (!$Files) { Write-Host 'Drag DWG files onto Run-CAD.cmd, or pass file paths to this script.'; exit 1 }
if (!$AcadPath) {
    $AcadPath = Get-ChildItem "$env:ProgramFiles\Autodesk\AutoCAD*\accoreconsole.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (!$AcadPath -or !(Test-Path -LiteralPath $AcadPath -PathType Leaf)) { throw 'AutoCAD Core Console not found. Specify -AcadPath.' }
$template = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'process.lsp') -Raw
$results = @()
foreach ($inputPath in $Files) {
    $working = $null; $tempDir = $null; $output = $null; $proc = $null
    try {
        $source = Get-Item -LiteralPath $inputPath
        if ($source.PSIsContainer -or $source.Extension -ine '.dwg') { throw 'Only DWG files are supported.' }
        $tag = [guid]::NewGuid().ToString('N')
        # A private working copy in the original directory preserves relative Xref paths.
        $working = Join-Path $source.DirectoryName ('.cad-work-' + $tag + '.dwg')
        $output = Join-Path $source.DirectoryName ($source.BaseName + '_copy_' + $tag.Substring(0,8) + '.dwg')
        if (Test-Path -LiteralPath $output) { throw 'Output already exists; refusing overwrite.' }
        Copy-Item -LiteralPath $source.FullName -Destination $working
        (Get-Item -LiteralPath $working).IsReadOnly = $false
        $tempDir = Join-Path ([IO.Path]::GetTempPath()) ('cad-batch-' + $tag)
        New-Item -ItemType Directory -Path $tempDir | Out-Null
        $marker = Join-Path $tempDir 'success.txt'
        $scriptPath = Join-Path $tempDir 'process.scr'
        $logPath = $output + '.log'
        $errorPath = $output + '.stderr.log'
        $env:CAD_BATCH_OUTPUT = $output.Replace('\','/')
        $env:CAD_BATCH_MARKER = $marker.Replace('\','/')
        $env:CAD_BATCH_PASSES = [string]$Passes
        # ASCII script, Unicode paths supplied through environment variables.
        [IO.File]::WriteAllText($scriptPath, $template + "`r`n(cad:run)`r`n", [Text.Encoding]::ASCII)
        Write-Host ('Processing: ' + $source.FullName)
        $arguments = '/i "' + $working + '" /s "' + $scriptPath + '"'
        $proc = Start-Process -FilePath $AcadPath -ArgumentList $arguments -WorkingDirectory $source.DirectoryName -PassThru -RedirectStandardOutput $logPath -RedirectStandardError $errorPath
        if (!$proc.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $proc.Id -Force
            $proc.WaitForExit()
            throw 'Timed out; this job was stopped. Inspect the log.'
        }
        $proc.WaitForExit()
        if (!(Test-Path -LiteralPath $marker) -or !(Test-Path -LiteralPath $output)) { throw ('Processing failed; see ' + $logPath) }
        $stream = [IO.File]::OpenRead($output)
        try { $bytes = New-Object byte[] 6; $null = $stream.Read($bytes,0,6) } finally { $stream.Dispose() }
        if ([Text.Encoding]::ASCII.GetString($bytes) -ne 'AC1018') { throw 'Output is not DWG 2004 format; inspect before use.' }
        $results += [pscustomobject]@{Input=$source.FullName;Status='OK';Output=$output;Message='Check drawing appearance before delivery.'}
    } catch {
        Write-Warning $_.Exception.Message
        $results += [pscustomobject]@{Input=$inputPath;Status='FAILED';Output=$output;Message=$_.Exception.Message}
    } finally {
        if ($working -and (!$proc -or $proc.HasExited)) {
            # Delete only this job's scratch files. Retain output and logs even on failure.
            foreach ($ext in @('.dwg','.bak','.dwl','.dwl2')) {
                $scratch = [IO.Path]::ChangeExtension($working,$ext)
                if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Force -ErrorAction SilentlyContinue }
            }
        }
        if ($tempDir -and (Test-Path -LiteralPath $tempDir)) { Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
    }
}
Remove-Item Env:CAD_BATCH_OUTPUT,Env:CAD_BATCH_MARKER,Env:CAD_BATCH_PASSES -ErrorAction SilentlyContinue
$results | Format-Table -AutoSize
if ($results.Status -contains 'FAILED') { exit 1 }
