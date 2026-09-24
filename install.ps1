# install.ps1 — установка Reku одной командой.
#   irm https://raw.githubusercontent.com/Small-coder-AI/reku/main/install.ps1 | % TrimStart ([char]0xFEFF) | iex
#   (% TrimStart снимает BOM: под Windows PowerShell 5.1 irm отдаёт файл с ведущим
#    U+FEFF, из-за чего iex принимает первую строку-комментарий за команду «#».)
# По умолчанию ставится код последнего релиза (GitHub Releases). Другая версия —
# скачай файл и запусти локально с параметром:
#   .\install.ps1 -Ref v1.2.3      # конкретный релиз/тег
#   .\install.ps1 -Ref main        # ветка (голова, без релиза)
# Локальная отладка:  .\install.ps1 -SourcePath C:\path\to\reku
# Удаление:           .\install.ps1 -Uninstall
param(
    [string]$SourcePath = "",
    [string]$Ref = "",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1: .NET по умолчанию может жить без TLS 1.2, а GitHub без
# него рвёт соединение («Базовое соединение закрыто»). -bor сохраняет протоколы,
# уже включённые системой (например TLS 1.3), а не затирает их.
[Net.ServicePointManager]::SecurityProtocol = `
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$AppName    = "Reku"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$StartMenu  = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$RunKey     = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Stop-RekuProcesses {
    # Живой процесс держит DLL: удаление/обновление при нём молча оставляет
    # огрызки (боевой случай: «удалённый» Reku.exe пережил -Uninstall, потому
    # что был запущен, и пользователь месил кашу из двух установок). Убиваем
    # только процессы ИЗ нашего каталога ("$InstallDir\*" — с разделителем,
    # иначе шаблон зацепил бы соседей вроде Reku-models-backup), а не все
    # python на машине.
    $procs = Get-Process Reku, python, pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path -like "$InstallDir\*" }
    if ($procs) {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        # Stop-Process не ждёт реальной смерти: хэндлы DLL освобождаются только
        # после неё, иначе Remove-Item ниже по скрипту оставит залоченные огрызки
        $procs | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
    }
}

function Remove-ExeInstall {
    # Запасной путь дистрибуции — exe-инсталлятор (Inno Setup) — ставится В ЭТУ ЖЕ
    # папку. Его остатки (Reku.exe, _internal, ярлыки и автозапуск на Reku.exe)
    # уводили пользователя в старую сборку вместо свежей установки. Сносим штатно
    # его же деинсталлятором: тот уберёт и свои ярлыки, и свой автозапуск в HKCU.
    $unins = Join-Path $InstallDir "unins000.exe"
    if (Test-Path $unins) {
        Write-Step "Нашёл установку exe-инсталлятором — удаляю её штатно..."
        Start-Process $unins -ArgumentList "/VERYSILENT" -Wait
        # unins000 перезапускает свою копию из %TEMP% и возвращает управление
        # сразу — ждём, пока файлы реально исчезнут (до 30 с)
        $exe = Join-Path $InstallDir "Reku.exe"
        for ($i = 0; $i -lt 30 -and (Test-Path $exe); $i++) { Start-Sleep 1 }
    }
    # добиваем, что могло остаться (залоченные при деинсталляции файлы)
    foreach ($it in @("Reku.exe", "_internal", "unins000.exe", "unins000.dat")) {
        Remove-Item -Recurse -Force (Join-Path $InstallDir $it) -ErrorAction SilentlyContinue
    }
}

function Invoke-Uninstall {
    Write-Step "Удаляю $AppName..."
    Stop-RekuProcesses
    Remove-ExeInstall
    Remove-Item (Join-Path $StartMenu "$AppName.lnk") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk") -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $RunKey -Name $AppName -ErrorAction SilentlyContinue

    # До фикса data_dir() (reku/config.py) инсталляции из исходников хранили модели
    # (~3 ГБ) прямо в $InstallDir\models, а не в %APPDATA%\Reku. Спрашиваем отдельно,
    # чтобы бланкетный Remove-Item ниже не снёс их молча (guard для старых установок).
    $legacyModels = Join-Path $InstallDir "models"
    if (Test-Path $legacyModels) {
        $ans = Read-Host "Найдены модели старого формата в $legacyModels. Удалить вместе с программой? [y/N]"
        if ($ans -ne "y") {
            $backup = Join-Path (Split-Path $InstallDir -Parent) "$AppName-models-backup"
            Remove-Item -Recurse -Force $backup -ErrorAction SilentlyContinue
            Move-Item $legacyModels $backup
            Write-Host "    Модели сохранены: $backup"
        }
    }

    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
    $data = Join-Path $env:APPDATA $AppName
    if (Test-Path $data) {
        $ans = Read-Host "Удалить данные и скачанные модели ($data)? [y/N]"
        if ($ans -eq "y") { Remove-Item -Recurse -Force $data }
    }
    Write-Host "Удалено." -ForegroundColor Green
}
if ($Uninstall) { Invoke-Uninstall; return }

# Валидируем -SourcePath сразу: при кривом аргументе (опечатка, мусор из-за
# ошибки квотирования в cmd) скрипт иначе падал бы только на Copy-Item — уже
# после установки Python. Ключ нужен лишь для локальной отладки.
if ($SourcePath) {
    $SourcePath = $SourcePath.Trim()
    if (-not (Test-Path -LiteralPath (Join-Path $SourcePath "reku") -PathType Container)) {
        throw ("-SourcePath `"$SourcePath`" не похож на чекаут Reku (нет каталога reku\). " +
               "Этот ключ нужен только для локальной отладки; для обычной установки запусти скрипт без аргументов.")
    }
    $SourcePath = (Resolve-Path -LiteralPath $SourcePath).Path
}

# ── 1. Железо ────────────────────────────────────────────────
Write-Step "Определяю железо..."
$gpus = (Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue).Name -join "; "
# порядок повторяет auto-цепочку backends.py: cuda -> amd -> igpu -> cpu
# (дискретный Radeon быстрее десктопных Intel-iGPU, поэтому AMD раньше Intel)
$hwProfile = "cpu"
if ($gpus -match "NVIDIA") { $hwProfile = "cuda" }
elseif ($gpus -match "AMD|Radeon") { $hwProfile = "amd" }
elseif ($gpus -match "Intel.*(Arc|Iris|Graphics)") { $hwProfile = "intel" }
Write-Host "    Видеоадаптеры: $gpus"
Write-Host "    Профиль установки: $hwProfile"

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
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget не найден — поставь Python 3.12 с python.org и запусти скрипт снова."
    }
    Write-Step "Python 3.12 не найден — ставлю через winget (тихо)..."
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget не смог поставить Python. Поставь Python 3.12 с python.org и запусти скрипт снова." }
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = "py -3.12"
}
Write-Host "    Python: $(& $py.Split()[0] $py.Split()[1..99] --version)"

# ── 3. Код ───────────────────────────────────────────────────
# -Ref не задан и не локальная отладка -> берём последний релиз (GitHub API).
# Офлайн/рейт-лимит/иной сбой API — не фатально, ставим main.
if (-not $SourcePath -and -not $Ref) {
    Write-Step "Ищу последний релиз..."
    try {
        $release = Invoke-RestMethod "https://api.github.com/repos/Small-coder-AI/reku/releases/latest" `
            -Headers @{ "User-Agent" = "reku-install.ps1" }
        # Служебные релизы движка (engine-whisper-cpp-*) публикуются с make_latest=false
        # и сюда попасть не должны — доп. страховка: тег обязан быть версийным (vX...).
        if ($release.tag_name -match '^v\d') {
            $Ref = $release.tag_name
        } else {
            Write-Warning "У /latest неожиданный тег '$($release.tag_name)' — ставлю main."
        }
    } catch {
        Write-Warning "Не удалось узнать последний релиз ($($_.Exception.Message)) — ставлю main."
    }
    if (-not $Ref) { $Ref = "main" }
}
if (-not $SourcePath) {
    # версийный тег (vX.Y.Z) -> архив тега, иначе Ref — имя ветки -> архив ветки
    $RepoZip = if ($Ref -match '^v\d') {
        "https://github.com/Small-coder-AI/reku/archive/refs/tags/$Ref.zip"
    } else {
        "https://github.com/Small-coder-AI/reku/archive/refs/heads/$Ref.zip"
    }
}

Write-Step "Получаю код в $InstallDir..."
if (-not $SourcePath) { Write-Host "    Ставлю: $Ref" }
Stop-RekuProcesses      # живые процессы держат DLL — обновление оставило бы огрызки
Remove-ExeInstall       # остатки установки exe-инсталлятором (общая папка)
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
# Copy-Item -Recurse при существующем каталоге СЛИВАЕТ дерево (перезаписывает
# одноимённые файлы, но не удаляет исчезнувшие в новой версии) — при обновлении
# старые модули reku/ иначе оставались бы висеть. Заменяем каталог целиком, а
# не сливаем; .venv и models — соседи $InstallDir\reku, их это не трогает.
Remove-Item -Recurse -Force (Join-Path $InstallDir "reku") -ErrorAction SilentlyContinue
$codeItems = @("reku", "scripts", "packaging", "requirements.txt")
# requirements.lock.txt — опционально: старые релизы (до этой фичи) могли его не содержать.
$optionalCodeItems = @("requirements.lock.txt")
if ($SourcePath) {
    foreach ($it in $codeItems) { Copy-Item -Recurse -Force (Join-Path $SourcePath $it) $InstallDir }
    foreach ($it in $optionalCodeItems) {
        $optSrc = Join-Path $SourcePath $it
        if (Test-Path $optSrc) { Copy-Item -Force $optSrc $InstallDir }
    }
} else {
    # НЕ %TEMP%: у профилей с не-ASCII именем (например, C:\Users\Иван) elevated-запуск
    # PowerShell получает TEMP коротким DOS-путём (C:\Users\ABCD~1\...), и
    # Windows PowerShell 5.1 спотыкается на «~» при разрешении пути — установка
    # валилась прямо здесь, SilentlyContinue не спасал (боевой случай 2026-07-26).
    # LOCALAPPDATA шелл всегда отдаёт длинным — строим времянку от него.
    $tmpParent = Join-Path $env:LOCALAPPDATA "Temp"
    New-Item -ItemType Directory -Force -Path $tmpParent | Out-Null
    $tmp = Join-Path $tmpParent "reku_dl"
    foreach ($p in @($tmp, "$tmp.zip")) {
        if (Test-Path -LiteralPath $p -ErrorAction SilentlyContinue) {
            Remove-Item -Recurse -Force -LiteralPath $p
        }
    }
    Invoke-WebRequest $RepoZip -OutFile "$tmp.zip"
    Expand-Archive "$tmp.zip" $tmp -Force
    # имя каталога внутри архива зависит от Ref (reku-main/ для ветки, reku-0.2.2/
    # для тега v0.2.2 и т.п.) — просто берём единственный подкаталог, не завязываясь на имя.
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    foreach ($it in $codeItems) { Copy-Item -Recurse -Force (Join-Path $src.FullName $it) $InstallDir }
    foreach ($it in $optionalCodeItems) {
        $optSrc = Join-Path $src.FullName $it
        if (Test-Path $optSrc) { Copy-Item -Force $optSrc $InstallDir }
    }
    Remove-Item -Recurse -Force -LiteralPath $tmp, "$tmp.zip" -ErrorAction SilentlyContinue
}

# ── 4. Окружение ─────────────────────────────────────────────
$venv = Join-Path $InstallDir ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Write-Step "Создаю виртуальное окружение..."
    & $py.Split()[0] $py.Split()[1..99] -m venv $venv
}
$vpy = Join-Path $venv "Scripts\python.exe"
Write-Step "Ставлю зависимости (профиль $hwProfile; это займёт несколько минут)..."
$req = Get-Content (Join-Path $InstallDir "requirements.txt")
if ($hwProfile -ne "cuda") { $req = $req | Where-Object { $_ -notmatch "^nvidia-" } }
# amd-путь работает через whisper.cpp (отдельный exe, качается ниже) — openvino не нужен.
# ИСКЛЮЧЕНИЕ: если рядом с Radeon есть Intel iGPU, openvino оставляем запасным путём —
# при нерабочем Vulkan (старый/битый драйвер) рантайм-цепочка auto тогда возьмёт igpu,
# а не провалится на CPU (замечание ревью PR #12).
$dropOpenvino = ($hwProfile -eq "cpu") -or
                ($hwProfile -eq "amd" -and $gpus -notmatch "Intel.*(Arc|Iris|Graphics)")
if ($dropOpenvino) { $req = $req | Where-Object { $_ -notmatch "^openvino" } }
$reqFile = Join-Path $InstallDir "requirements.effective.txt"
$req | Set-Content $reqFile -Encoding UTF8
# Полный проверенный срез (транзитивные версии) как constraints — не как requirements:
# -c только сужает версии пакетов, которые и так ставятся по $reqFile, лишние строки
# (например openvino на cuda-профиле) ни на что не влияют. Старые релизы (до этой
# фичи) могли не содержать файл — тогда просто ставим без constraints.
$lockFile = Join-Path $InstallDir "requirements.lock.txt"
$constraintArgs = @()
if (Test-Path $lockFile) {
    $constraintArgs = @("-c", $lockFile)
} else {
    Write-Host "    (requirements.lock.txt нет в исходниках — ставлю без constraints)"
}
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r $reqFile @constraintArgs
if ($LASTEXITCODE -ne 0) { throw "pip не смог поставить зависимости (см. вывод выше)." }

# Переход с полного PySide6 на PySide6-Essentials: pip не удаляет то, чего больше нет
# в requirements, и у обновлённой установки полный PySide6 с Addons (~0.4 ГБ) остался
# бы лежать. Удалять только вместе с переустановкой Essentials: RECORD метапакета и
# Addons числят за собой общие файлы (PySide6/__init__.py и др.), uninstall сносит и их.
# Старые исходники (-Ref на релиз с полным PySide6) не трогаем.
$essentialsReq = $req | Where-Object { $_ -match "^PySide6-Essentials==" } | Select-Object -First 1
if ($essentialsReq) {
    $qtLeftovers = @(& $vpy -m pip list --format=freeze 2>$null |
        Where-Object { $_ -match "^PySide6([_-]Addons)?==" } |
        ForEach-Object { ($_ -split "==")[0] })
    if ($qtLeftovers.Count -gt 0) {
        Write-Host "    Убираю полный PySide6 (Addons не нужны)..."
        & $vpy -m pip uninstall -y @qtLeftovers --quiet
        & $vpy -m pip install --force-reinstall --no-deps $essentialsReq --quiet
        if ($LASTEXITCODE -ne 0) { throw "pip не смог переустановить $essentialsReq (см. вывод выше)." }
    }
}

# ── 4б. Проверка окружения ───────────────────────────────────
# Битые файлы в venv для pip невидимы: пакет числится установленным, а импорт
# падает (боевой случай: null bytes в site-packages после сбоя — приложение
# «просто не запускалось»). Проверяем реальным импортом; при провале один раз
# пересоздаём окружение с нуля, без кэша pip.
# движок профиля тоже в проверку: openvino_genai ставится, когда openvino не
# вырезан из requirements — его порча дала бы «зелёный» health-check и падение
# уже в рантайме на Intel-пути (whisper.cpp для amd — отдельный exe, не импорт).
# pynput строго ПЕРВЫМ, до PySide6 — тот же обход six/shiboken-краша на
# Python 3.12.0, что и в gui.py (порядок проверки зеркалит порядок приложения):
# иначе на 3.12.0 проверка ложно «проваливается» на здоровом окружении и
# установка умирает с «не проходит и после пересоздания» (боевой случай 2026-07).
$checkImports = "pynput, PySide6.QtCore, numpy, sounddevice, pyperclip, faster_whisper"
if (-not $dropOpenvino) { $checkImports += ", openvino_genai" }
function Test-VenvHealth {
    & $vpy -c "import $checkImports"
    return ($LASTEXITCODE -eq 0)
}
Write-Step "Проверяю окружение..."
if (-not (Test-VenvHealth)) {
    Write-Warning "Импорт зависимостей падает (вывод выше) — пересоздаю окружение с нуля..."
    Remove-Item -Recurse -Force $venv
    & $py.Split()[0] $py.Split()[1..99] -m venv $venv
    & $vpy -m pip install --upgrade pip --quiet
    & $vpy -m pip install --no-cache-dir -r $reqFile @constraintArgs
    if ($LASTEXITCODE -ne 0) { throw "pip не смог поставить зависимости (см. вывод выше)." }
    if (-not (Test-VenvHealth)) {
        throw "Окружение не проходит проверку и после пересоздания — напиши: github.com/Small-coder-AI/reku/issues"
    }
    Write-Host "    Окружение пересоздано, проверка пройдена." -ForegroundColor Green
}

# Движок whisper.cpp для AMD — наш CI-билд из GitHub Release; URL и sha256
# приколочены в reku\whisper_cpp.py (единственный источник правды), поэтому
# качаем через него, а не дублируем пин здесь. Кладётся в %APPDATA%\Reku\engines.
if ($hwProfile -eq "amd") {
    Write-Step "Скачиваю движок whisper.cpp (Vulkan, ~45 МБ)..."
    & $vpy -c "import sys; sys.path.insert(0, r'$InstallDir'); from reku import whisper_cpp; whisper_cpp.ensure_engine()"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Движок не скачался — не страшно: приложение докачает его при первом запуске."
    }
}

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
    # HKCU Run стартует процесс с cwd=System32 (не $InstallDir), поэтому голый
    # "-m reku" не находит пакет (он скопирован, а не pip-installed — reku не
    # резолвится, если его родитель не в sys.path). Явно подставляем InstallDir
    # через -c, как dev-режим reku/autostart.py (_exe_command) — не зависит от
    # cwd процесса автозапуска. --minimized — ПОСЛЕ код-строки -c (отдельный
    # токен командной строки), поэтому попадает в sys.argv, а не в текст скрипта.
    $autostartCmd = '"{0}" -c "import sys; sys.path.insert(0, r''{1}''); from reku.gui import main; main()" --minimized' -f $pyw, $InstallDir
    Set-ItemProperty -Path $RunKey -Name $AppName -Value $autostartCmd
    Write-Host "    Автозапуск включён (можно выключить в настройках $AppName)."
}

Write-Host ""
Write-Host "Готово! Запускай $AppName из меню Пуск." -ForegroundColor Green
Write-Host "Модель распознавания скачается при первом запуске (1.5–3 ГБ, вопрос терпения)."
