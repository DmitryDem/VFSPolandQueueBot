# Ставит иконку 📆 на все созданные ботом городские темы (с обработкой 429).
$token = (Get-Content "$PSScriptRoot\..\.env" | Where-Object { $_ -match '^BOT_TOKEN=' }) -replace '^BOT_TOKEN=', ''
$chatId = -1003983835902
$api = "https://api.telegram.org/bot$token"
$calendarEmojiId = '5433614043006903194'  # 📆

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

$ids = @(26,28,30,32,34,36,38,40,42,44,46,48,50,52,54,56,57,58,59,60,61,62,63,64)
foreach ($id in $ids) {
    Invoke-TgApi 'editForumTopic' @{ chat_id = $chatId; message_thread_id = $id; icon_custom_emoji_id = $calendarEmojiId } | Out-Null
    Write-Host "icon set: $id"
    Start-Sleep -Seconds 2
}
Write-Host "done"
