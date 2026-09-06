# Open the current tested desktop build with the persistent Source QA profile.
# Existing default-profile projects are not changed.
$qaRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$qaExecutable = Join-Path $qaRoot 'desktop\out\DesignDNA-win32-x64\designdna.exe'
$qaProfile = Join-Path $qaRoot 'tmp\sites-source-qa-profile'
if (-not (Test-Path -LiteralPath $qaExecutable -PathType Leaf)) {
    throw "QA desktop package is missing: $qaExecutable"
}
$env:DESIGNDNA_ALLOW_MULTI_INSTANCE = '1'
Start-Process -FilePath $qaExecutable -ArgumentList @("--user-data-dir=`"$qaProfile`"")
