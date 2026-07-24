# Создаёт темы "(D Work)" для 8 городов: создать -> закрыть -> иконка 📆 (с обработкой 429).
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

$cities = @('Минск', 'Могилев', 'Барановичи', 'Пинск', 'Брест', 'Гродно', 'Лида', 'Витебск')
$map = [ordered]@{}
foreach ($city in $cities) {
    $name = "$city (D Work)"
    $resp = Invoke-TgApi 'createForumTopic' @{ chat_id = $chatId; name = $name; icon_color = 16766590 }
    $id = $resp.result.message_thread_id
    $map[$city] = $id
    Write-Host "created: $name -> $id"
    Start-Sleep -Seconds 3
    Invoke-TgApi 'closeForumTopic' @{ chat_id = $chatId; message_thread_id = $id } | Out-Null
    Start-Sleep -Seconds 2
    Invoke-TgApi 'editForumTopic' @{ chat_id = $chatId; message_thread_id = $id; icon_custom_emoji_id = $calendarEmojiId } | Out-Null
    Write-Host "closed + icon: $id"
    Start-Sleep -Seconds 2
}
$map | ConvertTo-Json
