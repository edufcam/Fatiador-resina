; Instalador do Fatiador Resina (Inno Setup 6)
#define MeuApp "Fatiador Resina"
#define MeuExe "FatiadorResina.exe"
#ifndef MinhaVersao
  #define MinhaVersao "0.0.0"
#endif

[Setup]
AppId={{8C1F3B7A-4E2D-4C9B-9A51-6F2E7D3B1A40}
AppName={#MeuApp}
AppVersion={#MinhaVersao}
AppVerName={#MeuApp} {#MinhaVersao}
AppPublisher=Eduardo
DefaultDirName={autopf}\{#MeuApp}
DefaultGroupName={#MeuApp}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=saida
OutputBaseFilename=FatiadorResina-Setup-{#MinhaVersao}
SetupIconFile=recursos\icone.ico
UninstallDisplayIcon={app}\{#MeuExe}
UninstallDisplayName={#MeuApp}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
ChangesAssociations=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalho"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\FatiadorResina\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MeuApp}"; Filename: "{app}\{#MeuExe}"
Name: "{autodesktop}\{#MeuApp}"; Filename: "{app}\{#MeuExe}"; Tasks: atalho

[Registry]
Root: HKA; Subkey: "Software\Classes\.resina"; ValueType: string; ValueName: ""; ValueData: "FatiadorResina.Projeto"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\FatiadorResina.Projeto"; ValueType: string; ValueName: ""; ValueData: "Projeto do Fatiador Resina"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\FatiadorResina.Projeto\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MeuExe},0"
Root: HKA; Subkey: "Software\Classes\FatiadorResina.Projeto\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MeuExe}"" ""%1"""

[Run]
Filename: "{app}\{#MeuExe}"; Description: "Abrir o {#MeuApp}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MeuExe}"; Flags: nowait; Check: WizardSilent
