param([string]$Time = "09:00", [switch]$Register)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction Stop).Source
if ($Register) {
  $action = New-ScheduledTaskAction -Execute $python -Argument 'daily_batch.py' -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -Daily -At $Time
  Register-ScheduledTask -TaskName 'NIHHS-Daily-Quality-Check' -Action $action -Trigger $trigger -Description 'NIHHS local daily quality check' -Force
} else {
  [PSCustomObject]@{ TaskName='NIHHS-Daily-Quality-Check'; Time=$Time; Python=$python; WorkingDirectory=$root; Command='daily_batch.py'; Register=$false; Validation='No ScheduledTasks API calls were made' }
}
