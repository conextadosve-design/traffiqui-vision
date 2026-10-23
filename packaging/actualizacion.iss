; Actualización de Traffiqui: solo reemplaza la carpeta "codigo" (pocos MB). Inno Setup 6.
;   iscc packaging\actualizacion.iss /DAppVersion=1.2.3 /DBaseVersion=1
; Necesita una instalación previa con la misma base (packaging\BASE_VERSION); si no, pide el instalador completo.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef BaseVersion
  #define BaseVersion "1"
#endif

[Setup]
AppId={{6B0F5D0B-6C0E-4C51-9C1F-7E2A9D3B1A10}
AppName=Traffiqui
AppVersion={#AppVersion}
AppPublisher=Traffiqui
DefaultDirName={autopf}\Traffiqui
UsePreviousAppDir=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
OutputDir=..\dist
OutputBaseFilename=Traffiqui-Actualizacion-{#AppVersion}
SetupIconFile=traffiqui.ico
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
CloseApplications=yes
WizardStyle=modern
Uninstallable=no
CreateUninstallRegKey=no
UpdateUninstallLogAppName=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
WelcomeLabel2=Esto actualizará Traffiqui a la versión {#AppVersion}. Tus datos, cámaras y configuración se conservan.

[InstallDelete]
; código anterior fuera: así no quedan archivos viejos
Type: filesandordirs; Name: "{app}\codigo"

[Files]
Source: "..\dist\Traffiqui\codigo\*"; DestDir: "{app}\codigo"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "{app}\Traffiqui.exe"; Description: "Abrir Traffiqui"; Flags: postinstall nowait

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Base: AnsiString;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\Traffiqui.exe')) then
    Result := 'Traffiqui no está instalado en este PC. Usa el instalador completo (Traffiqui-Setup).'
  else if not LoadStringFromFile(ExpandConstant('{app}\_internal\base_version.txt'), Base) then
    Result := 'Esta instalación es antigua. Usa el instalador completo (Traffiqui-Setup); tus datos se conservan.'
  else if Trim(String(Base)) <> '{#BaseVersion}' then
    Result := 'Esta actualización necesita una base nueva. Usa el instalador completo (Traffiqui-Setup); tus datos se conservan.';
end;
