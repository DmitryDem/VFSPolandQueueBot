# Досоздаёт недостающие темы с обработкой 429 и закрывает все темы городов.
$token = (Get-Content "$PSScriptRoot\..\.env" | Where-Object { $_ -match '^BOT_TOKEN=' }) -replace '^BOT_TOKEN=', ''
$chatId = -1003983835902
$api = "https://api.telegram.org/bot$token"

function Invoke-TgApi($method, $body) {
    while ($true) {
        try {
            $json = [System.Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json))
            return Invoke-RestMethod -Method Post -Uri "$api/$method" -ContentType 'application/json; charset=utf-8' -Body $json -ErrorAction Stop
        } catch {
            $err = $null
            try { $err = $_.ErrorDetails.Message | ConvertFrom-Json } catch {}
            if ($err -and $err.error_code -eq 429) {
                $wait = [int]$err.parameters.retry_after + 1
                Write-Host "429, ждём $wait сек..."
                Start-Sleep -Seconds $wait
                continue
            }
            if ($err -and $err.description -match 'TOPIC_NOT_MODIFIED') { return $null }
            throw
        }
    }
}

$missing = @(
    @{ name = 'Пинск (C Other)';   color = 16478047 },
    @{ name = 'Брест (D Other)';   color = 16766590 },
    @{ name = 'Брест (D Driver)';  color = 16766590 },
    @{ name = 'Брест (C Other)';   color = 16478047 },
    @{ name = 'Гродно (D Other)';  color = 16766590 },
    @{ name = 'Гродно (D Driver)'; color = 16766590 },
    @{ name = 'Гродно (C Other)';  color = 16478047 },
    @{ name = 'Лида (D Other)';    color = 16766590 },
    @{ name = 'Лида (D Driver)';   color = 16766590 }
)

$created = [ordered]@{}
foreach ($t in $missing) {
    $resp = Invoke-TgApi 'createForumTopic' @{ chat_id = $chatId; name = $t.name; icon_color = $t.color }
    $created[$t.name] = $resp.result.message_thread_id
    Write-Host "created: $($t.name) -> $($resp.result.message_thread_id)"
    Start-Sleep -Seconds 3
}

Write-Host "`n--- закрываем все темы городов ---"
$allIds = @(26,28,30,32,34,36,38,40,42,44,46,48,50,52,54) + @($created.Values)
foreach ($id in $allIds) {
    $r = Invoke-TgApi 'closeForumTopic' @{ chat_id = $chatId; message_thread_id = $id }
    Write-Host "closed: $id $(if ($null -eq $r) { '(уже закрыта)' })"
    Start-Sleep -Seconds 2
}

Write-Host "`n--- новые темы ---"
$created | ConvertTo-Json
