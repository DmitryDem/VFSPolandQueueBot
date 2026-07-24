# Создаёт темы форума для городов и закрывает их (readonly).
# Выводит JSON-карту {город: {категория: thread_id}}.
$token = (Get-Content "$PSScriptRoot\..\.env" | Where-Object { $_ -match '^BOT_TOKEN=' }) -replace '^BOT_TOKEN=', ''
$chatId = -1003983835902
$api = "https://api.telegram.org/bot$token"

$cities = @('Минск', 'Могилев', 'Барановичи', 'Пинск', 'Брест', 'Гродно', 'Лида', 'Витебск')
$categories = @(
    @{ key = 'D_OTHER';  suffix = '(D Other)';  color = 16766590 },
    @{ key = 'D_DRIVER'; suffix = '(D Driver)'; color = 16766590 },
    @{ key = 'C_OTHER';  suffix = '(C Other)';  color = 16478047 }
)

$map = [ordered]@{}
foreach ($city in $cities) {
    $cityMap = [ordered]@{}
    foreach ($cat in $categories) {
        $name = "$city $($cat.suffix)"
        $body = @{ chat_id = $chatId; name = $name; icon_color = $cat.color } | ConvertTo-Json
        $resp = Invoke-RestMethod -Method Post -Uri "$api/createForumTopic" -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
        if (-not $resp.ok) { throw "createForumTopic failed for '$name': $($resp | ConvertTo-Json)" }
        $threadId = $resp.result.message_thread_id
        $cityMap[$cat.key] = $threadId
        Write-Host "created: $name -> $threadId"
        Start-Sleep -Milliseconds 1200

        $closeBody = @{ chat_id = $chatId; message_thread_id = $threadId } | ConvertTo-Json
        $closeResp = Invoke-RestMethod -Method Post -Uri "$api/closeForumTopic" -ContentType 'application/json' -Body $closeBody
        if (-not $closeResp.ok) { Write-Warning "closeForumTopic failed for '$name'" }
        Start-Sleep -Milliseconds 1200
    }
    $map[$city] = $cityMap
}
$map | ConvertTo-Json -Depth 4
