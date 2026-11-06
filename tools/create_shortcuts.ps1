param(
    [string]$ShortcutName = 'QuizChirp'
)
$ErrorActionPreference = 'Stop'

$appRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $appRoot 'Start.cmd'
$icon = Join-Path $appRoot 'quizchirp\assets\logo.ico'
if (!(Test-Path -LiteralPath $launcher) -or !(Test-Path -LiteralPath $icon)) {
    throw 'QuizChirp launcher or icon is missing.'
}

$shortcutShell = New-Object -ComObject WScript.Shell
$destinations = @(
    [Environment]::GetFolderPath('DesktopDirectory'),
    [Environment]::GetFolderPath('Programs')
)
foreach ($destination in $destinations) {
    if (!$destination) { throw 'Windows shortcut folder is unavailable.' }
    $shortcutPath = Join-Path $destination "$ShortcutName.lnk"
    $shortcut = $shortcutShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $launcher
    $shortcut.WorkingDirectory = $appRoot
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = $ShortcutName
    $shortcut.WindowStyle = 7
    $shortcut.Save()
    $saved = $shortcutShell.CreateShortcut($shortcutPath)
    if ($saved.TargetPath -ne $launcher -or $saved.WorkingDirectory -ne $appRoot) {
        throw "Shortcut verification failed: $shortcutPath"
    }
    Write-Output "Created: $shortcutPath"
}
