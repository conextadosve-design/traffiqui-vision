; Instalador de Traffiqui (Inno Setup 6).
;   iscc packaging\installer.iss /DAppVersion=1.0.0
; Espera el programa ya empaquetado en dist\Traffiqui (ver traffiqui.spec).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B0F5D0B-6C0E-4C51-9C1F-7E2A9D3B1A10}
AppName=Traffiqui
AppVersion={#AppVersion}
AppPublisher=Traffiqui
DefaultDirName={autopf}\Traffiqui
DefaultGroupName=Traffiqui
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Traffiqui-Setup-{#AppVersion}
SetupIconFile=traffiqui.ico
UninstallDisplayIcon={app}\Traffiqui.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
CloseApplications=yes
WizardStyle=modern

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "autostart"; Description: "Abrir Traffiqui al encender el PC (recomendado)"

[Dirs]
; los datos quedan fuera de la carpeta del programa: actualizar o desinstalar no los borra
Name: "{commonappdata}\Traffiqui"; Permissions: users-modify

[Files]
Source: "..\dist\Traffiqui\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Traffiqui"; Filename: "{app}\Traffiqui.exe"
Name: "{autodesktop}\Traffiqui"; Filename: "{app}\Traffiqui.exe"
Name: "{commonstartup}\Traffiqui"; Filename: "{app}\Traffiqui.exe"; Parameters: "--no-abrir"; Tasks: autostart

[Run]
; sede principal: el puerto 9000 solo se abre a Tailscale (100.64.0.0/10) y a la red local
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Traffiqui Sede Principal"""; Flags: runhidden; Check: IsHQ
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Traffiqui Sede Principal"" dir=in action=allow protocol=TCP localport=9000 remoteip=100.64.0.0/10,LocalSubnet"; Flags: runhidden; Check: IsHQ
Filename: "{app}\Traffiqui.exe"; Description: "Abrir Traffiqui ahora"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Traffiqui Sede Principal"""; Flags: runhidden; RunOnceId: "fw"

[Code]
var
  ModePage: TInputOptionWizardPage;

function ModeFile: String;
begin
  Result := ExpandConstant('{commonappdata}\Traffiqui\modo.json');
end;

procedure InitializeWizard;
var
  Current: AnsiString;
begin
  ModePage := CreateInputOptionPage(wpSelectDir,
    '¿Qué es este PC?', 'Traffiqui funciona de forma distinta en una tienda y en la sede principal.',
    'Elige una opción. Podrás cambiarla volviendo a ejecutar este instalador.', True, False);
  ModePage.Add('Una tienda: tiene las cámaras y cuenta a las personas');
  ModePage.Add('La sede principal: recibe y muestra los datos de todas las tiendas');
  ModePage.Values[0] := True;
  if LoadStringFromFile(ModeFile, Current) and (Pos('sede-principal', Current) > 0) then
    ModePage.Values[1] := True;
end;

function IsHQ: Boolean;
begin
  Result := ModePage.Values[1];
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Mode: String;
begin
  if CurStep = ssPostInstall then
  begin
    if IsHQ then Mode := 'sede-principal' else Mode := 'tienda';
    SaveStringToFile(ModeFile, '{"modo": "' + Mode + '"}', False);
  end;
end;
