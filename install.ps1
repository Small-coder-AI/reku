# install.ps1 — установка Reku одной командой.
#   irm https://raw.githubusercontent.com/Small-coder-AI/reku/main/install.ps1 | iex
# Локальная отладка:  .\install.ps1 -SourcePath D:\Dev\Whisper_PTT\whisper_ptt
# Удаление:           .\install.ps1 -Uninstall
param(
    [string]$SourcePath = "",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$AppName    = "Reku"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$RepoZip    = "https://github.com/Small-coder-AI/reku/archive/refs/heads/main.zip"
$StartMenu  = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$RunKey     = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Invoke-Uninstall {
    Write-Step "Удаляю $AppName..."
    Remove-Item (Join-Path $StartMenu "$AppName.lnk") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk") -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $RunKey -Name $AppName -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
    $data = Join-Path $env:APPDATA $AppName
    if (Test-Path $data) {
        $ans = Read-Host "Удалить данные и скачанные модели ($data)? [y/N]"
        if ($ans -eq "y") { Remove-Item -Recurse -Force $data }
    }
    Write-Host "Удалено." -ForegroundColor Green
}
if ($Uninstall) { Invoke-Uninstall; return }

# ── 1. Железо ────────────────────────────────────────────────
Write-Step "Определяю железо..."
$gpus = (Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue).Name -join "; "
$profile = "cpu"
if ($gpus -match "NVIDIA") { $profile = "cuda" }
elseif ($gpus -match "Intel.*(Arc|Iris|Graphics)") { $profile = "intel" }
Write-Host "    Видеоадаптеры: $gpus"
Write-Host "    Профиль установки: $profile"

# ── 2. Python 3.12 ───────────────────────────────────────────
Write-Step "Ищу Python 3.12..."
$py = $null
foreach ($cand in @("py -3.12", "python")) {
    try {
        $v = & $cand.Split()[0] $cand.Split()[1..99] --version 2>$null
        if ($v -match "Python 3\.12\.") { $py = $cand; break }
    } catch {}
}
if (-not $py) {
    Write-Step "Python 3.12 не найден — ставлю через winget (тихо)..."
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget не смог поставить Python. Поставь Python 3.12 с python.org и запусти скрипт снова." }
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = "py -3.12"
}
Write-Host "    Python: $(& $py.Split()[0] $py.Split()[1..99] --version)"

# ── 3. Код ───────────────────────────────────────────────────
Write-Step "Получаю код в $InstallDir..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$codeItems = @("reku", "scripts", "packaging", "requirements.txt", "requirements.lock.txt")
if ($SourcePath) {
    foreach ($it in $codeItems) { Copy-Item -Recurse -Force (Join-Path $SourcePath $it) $InstallDir }
} else {
    $tmp = Join-Path $env:TEMP "reku_dl"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Invoke-WebRequest $RepoZip -OutFile "$tmp.zip"
    Expand-Archive "$tmp.zip" $tmp -Force
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1   # reku-main/
    foreach ($it in $codeItems) { Copy-Item -Recurse -Force (Join-Path $src.FullName $it) $InstallDir }
    Remove-Item -Recurse -Force $tmp, "$tmp.zip" -ErrorAction SilentlyContinue
}

# ── 4. Окружение ─────────────────────────────────────────────
$venv = Join-Path $InstallDir ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Write-Step "Создаю виртуальное окружение..."
    & $py.Split()[0] $py.Split()[1..99] -m venv $venv
}
$vpy = Join-Path $venv "Scripts\python.exe"
Write-Step "Ставлю зависимости (профиль $profile; это займёт несколько минут)..."
$req = Get-Content (Join-Path $InstallDir "requirements.txt")
if ($profile -ne "cuda") { $req = $req | Where-Object { $_ -notmatch "^nvidia-" } }
if ($profile -eq "cpu")  { $req = $req | Where-Object { $_ -notmatch "^openvino" } }
$reqFile = Join-Path $InstallDir "requirements.effective.txt"
$req | Set-Content $reqFile -Encoding UTF8
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r $reqFile
if ($LASTEXITCODE -ne 0) { throw "pip не смог поставить зависимости (см. вывод выше)." }

# ── 5. Ярлыки ────────────────────────────────────────────────
Write-Step "Создаю ярлыки..."
$pyw = Join-Path $venv "Scripts\pythonw.exe"
$ico = Join-Path $InstallDir "packaging\app.ico"
function New-Shortcut($path) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($path)
    $sc.TargetPath = $pyw; $sc.Arguments = "-m reku"
    $sc.WorkingDirectory = $InstallDir
    if (Test-Path $ico) { $sc.IconLocation = $ico }
    $sc.Save()
}
New-Shortcut (Join-Path $StartMenu "$AppName.lnk")
$desk = Read-Host "Ярлык на рабочий стол? [Y/n]"
if ($desk -ne "n") { New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk") }

# ── 6. Автозапуск ────────────────────────────────────────────
$auto = Read-Host "Запускать $AppName при старте Windows? [y/N]"
if ($auto -eq "y") {
    Set-ItemProperty -Path $RunKey -Name $AppName -Value "`"$pyw`" -m reku"
    Write-Host "    Автозапуск включён (можно выключить в настройках $AppName)."
}

Write-Host ""
Write-Host "Готово! Запускай $AppName из меню Пуск." -ForegroundColor Green
Write-Host "Модель распознавания скачается при первом запуске (1.5–3 ГБ, вопрос терпения)."
