# 段取りさんの Windows の通知。追加のインストールはいらない。
# notify.py から  notify.ps1 -File <UTF-8 の JSON>  で呼ぶ({"title": "...", "message": "..."})。
# 日本語が化けないよう、文字は引数ではなく UTF-8 のファイルで受け取る。
param([string]$File)

$data = Get-Content -Raw -Encoding UTF8 -Path $File | ConvertFrom-Json
Remove-Item -LiteralPath $File -ErrorAction SilentlyContinue  # 読んだら一時ファイルは消す
$title = [System.Security.SecurityElement]::Escape($data.title)
$message = [System.Security.SecurityElement]::Escape($data.message)

try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$message</text></binding></visual></toast>")
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
} catch {
    # 通知センターが使えないときは、昔ながらの吹き出しで出す
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $icon = New-Object System.Windows.Forms.NotifyIcon
    try {
        $icon.Icon = [System.Drawing.SystemIcons]::Information
        $icon.Visible = $true
        $icon.ShowBalloonTip(10000, $data.title, $data.message, [System.Windows.Forms.ToolTipIcon]::Info)
        Start-Sleep -Seconds 6
    } finally {
        $icon.Dispose()
    }
}
