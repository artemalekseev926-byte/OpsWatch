param(
    [string]$Url = "http://127.0.0.1:8765/api/ingest/<TOKEN>",
    [string]$Title = "Диск D: заполнен на 95%",
    [string]$Severity = "critical"
)

$body = @{
    title       = $Title
    message     = "Проверка из планировщика заданий на $env:COMPUTERNAME"
    severity    = $Severity
    category    = "monitoring"
    external_id = "disk-d-$env:COMPUTERNAME"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri $Url -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
