$procs = Get-Process -Name electron,designdna -ErrorAction SilentlyContinue
if (-not $procs) { Write-Output "DesignDNA processes not found"; exit 0 }
$before = $procs | Select-Object Id, ProcessName, CPU, WorkingSet64
Start-Sleep -Seconds 5
$after = Get-Process -Name electron,designdna -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, CPU, WorkingSet64
$result = foreach ($a in $after) {
  $b = $before | Where-Object { $_.Id -eq $a.Id }
  [pscustomobject]@{
    PID        = $a.Id
    Process    = $a.ProcessName
    RAM_MB     = [math]::Round($a.WorkingSet64 / 1MB)
    CPU_Total_s = [math]::Round($a.CPU, 1)
    CPU_Percent_5s = if ($b) { [math]::Round((($a.CPU - $b.CPU) / 5 / [Environment]::ProcessorCount) * 100, 1) } else { 'n/a' }
  }
}
$result | Format-Table -AutoSize
Write-Output ("TOTAL RAM_MB: " + [math]::Round(($after | Measure-Object WorkingSet64 -Sum).Sum / 1MB))
