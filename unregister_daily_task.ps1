param([switch]$Unregister)
if ($Unregister) { Unregister-ScheduledTask -TaskName 'NIHHS-Daily-Quality-Check' -Confirm:$false }
else { Get-ScheduledTask -TaskName 'NIHHS-Daily-Quality-Check' -ErrorAction SilentlyContinue | Select-Object TaskName,State }
