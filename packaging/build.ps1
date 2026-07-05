# packaging\build.ps1 — сборка переносимого Reku.exe (PyInstaller --onedir --windowed)
# Запуск (из корня репозитория):  .\packaging\build.ps1            (обычная сборка)
#                                 .\packaging\build.ps1 -Shortcut  (ещё и ярлык на рабочий стол)
param(
    [switch]$Shortcut,
    [switch]$Clean,
    [switch]$Installer   # ещё и собрать setup.exe через Inno Setup (ISCC)
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot   # этот файл лежит в packaging/ — корень репо на уровень выше
$py   = Join-Path $root ".venv\Scripts\python.exe"
$pyi  = Join-Path $root ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $py)) { throw "venv не найден: $py" }

# 0) PyInstaller в venv (ставим, если нет)
& $py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ставлю PyInstaller в venv..." -ForegroundColor Cyan
    & $py -m pip install pyinstaller
}

# 1) чистка прошлой сборки
if ($Clean) { Remove-Item -Recurse -Force (Join-Path $root "build"),(Join-Path $root "dist") -ErrorAction SilentlyContinue }

# 2) иконка из make_icon()
Write-Host "Генерирую app.ico..." -ForegroundColor Cyan
Push-Location $root
& $py (Join-Path $root "scripts\make_ico.py")

# 3) сборка по спеку
Write-Host "Собираю .exe..." -ForegroundColor Cyan
& $pyi (Join-Path $root "packaging\reku.spec") --noconfirm --clean
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "PyInstaller вернул код $LASTEXITCODE" }

$exe = Join-Path $root "dist\Reku\Reku.exe"
if (-not (Test-Path $exe)) { throw "Ожидаемый .exe не найден: $exe" }
Write-Host "Готово: $exe" -ForegroundColor Green

# 3b) опциональный инсталлятор (Inno Setup, per-user, без админ-прав)
if ($Installer) {
    $iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) {
        throw "ISCC не найден: $iscc  (поставь: winget install JRSoftware.InnoSetup)"
    }
    Write-Host "Собираю инсталлятор..." -ForegroundColor Cyan
    Push-Location $root
    & $iscc (Join-Path $root "packaging\reku.iss")
    Pop-Location
    if ($LASTEXITCODE -ne 0) { throw "ISCC вернул код $LASTEXITCODE" }
    Write-Host "Инсталлятор: $(Join-Path $root 'installer\Reku-setup.exe')" -ForegroundColor Green
}

# 4) опциональный ярлык на рабочем столе
if ($Shortcut) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnk = Join-Path $desktop "Reku.lnk"
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = $exe
    $sc.WorkingDirectory = (Split-Path $exe)
    $sc.IconLocation = $exe
    $sc.Save()
    Write-Host "Ярлык: $lnk" -ForegroundColor Green
}
