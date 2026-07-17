; Reku — инсталлятор (Inno Setup 6). Per-user: без админ-прав, ставит в
; %LOCALAPPDATA%\Programs\Reku, делает ярлык в Пуск (+ опц. рабочий стол),
; опц. автозапуск (на УСТАНОВЛЕННЫЙ exe) и деинсталлятор.
;
; Сборка (из корня репозитория):
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\reku.iss
; Требует заранее собранный dist\Reku\ (build.ps1) и packaging\app.ico.
; Этот файл лежит в packaging/ — все относительные пути ниже (Source/SetupIconFile/
; OutputDir) по умолчанию считаются от каталога СКРИПТА (SourceDir не задан), поэтому
; идут через ..\ до корня репозитория.

#define MyAppName "Reku"
; версию передаёт релизный CI (ISCC /DMyAppVersion=X.Y.Z); дефолт — для локальной сборки
#ifndef MyAppVersion
  #define MyAppVersion "0.2.0"
#endif
#define MyAppExe "Reku.exe"
#define MyAppPublisher "Ruslan Kobernik"

[Setup]
AppId={{BA875A63-A361-47A9-8AA6-6788BBDB646C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/Small-coder-AI/reku
AppSupportURL=https://github.com/Small-coder-AI/reku/issues
AppUpdatesURL=https://github.com/Small-coder-AI/reku/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\installer
OutputBaseFilename=Reku-setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"
Name: "autostart"; Description: "Запускать при старте Windows"; GroupDescription: "Автозапуск:"

[Files]
Source: "..\dist\Reku\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; автозапуск на УСТАНОВЛЕННЫЙ exe (перекрывает прежнюю portable-запись); чистится при удалении
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExe}"""; \
    Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Запустить {#MyAppName} сейчас"; \
    Flags: nowait postinstall skipifsilent
