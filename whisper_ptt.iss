; whisper_ptt — инсталлятор (Inno Setup 6). Per-user: без админ-прав, ставит в
; %LOCALAPPDATA%\Programs\whisper_ptt, делает ярлык в Пуск (+ опц. рабочий стол),
; опц. автозапуск (на УСТАНОВЛЕННЫЙ exe) и деинсталлятор.
;
; Сборка:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" whisper_ptt.iss
; Требует заранее собранный dist\whisper_ptt\ (build.ps1) и app.ico.

#define MyAppName "whisper_ptt"
#define MyAppVersion "0.1.0"
#define MyAppExe "whisper_ptt.exe"
#define MyAppPublisher "Ruslan Kobernik"

[Setup]
AppId={{B7E3F2A1-9C4D-4E8B-A1F6-3D2C5E7A9B40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=whisper_ptt-setup
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
Source: "dist\whisper_ptt\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; автозапуск на УСТАНОВЛЕННЫЙ exe (перекрывает прежнюю portable-запись); чистится при удалении
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "whisper_ptt"; ValueData: """{app}\{#MyAppExe}"""; \
    Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Запустить {#MyAppName} сейчас"; \
    Flags: nowait postinstall skipifsilent
