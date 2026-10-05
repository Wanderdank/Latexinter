; latexinter.iss - Instalador de Latexinter para Windows (Inno Setup 6).
;
; No se compila a mano: installer\build.ps1 empaqueta el programa con
; PyInstaller y luego llama a ISCC con la versión.
;
; Se instala para el usuario actual, sin pedir permisos de administrador. Si
; faltan MiKTeX o pandoc, ofrece instalarlos con winget.

#ifndef Version
  #define Version "0.0.0"
#endif
#define AppName "Latexinter"
#define AppExe "Latexinter.exe"

[Setup]
AppId={{8F3C5B2E-6A4D-4C1B-9E7F-2D5A1C3B4E6F}
AppName={#AppName}
AppVersion={#Version}
AppVerName={#AppName} {#Version}
AppPublisher=Wanderdank
AppPublisherURL=https://github.com/Wanderdank/Latexinter
AppSupportURL=https://github.com/Wanderdank/Latexinter/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Latexinter-{#Version}-instalador
SetupIconFile=..\assets\latexinter.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Al actualizar, cierra el programa si está abierto.
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "abrircon"; Description: "Añadir «Abrir con Latexinter» a los archivos .tex"; GroupDescription: "Archivos:"
Name: "miktex"; Description: "MiKTeX, para compilar LaTeX (unos 200 MB)"; GroupDescription: "Programas que faltan (se descargan e instalan solos):"; Check: FaltaLatex
Name: "pandoc"; Description: "pandoc, para convertir entre PDF, LaTeX y Word"; GroupDescription: "Programas que faltan (se descargan e instalan solos):"; Check: FaltaPandoc

[Files]
Source: "..\dist\Latexinter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[InstallDelete]
; Al actualizar, que no queden bibliotecas de la versión anterior.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: escritorio

[Registry]
; «Abrir con» sin quitarle los .tex al programa que ya los abra por defecto.
Root: HKA; Subkey: "Software\Classes\.tex\OpenWithProgids"; ValueType: string; ValueName: "Latexinter.tex"; ValueData: ""; Flags: uninsdeletevalue; Tasks: abrircon
Root: HKA; Subkey: "Software\Classes\Latexinter.tex"; ValueType: string; ValueName: ""; ValueData: "Documento LaTeX"; Flags: uninsdeletekey; Tasks: abrircon
Root: HKA; Subkey: "Software\Classes\Latexinter.tex\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: abrircon
Root: HKA; Subkey: "Software\Classes\Latexinter.tex\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: abrircon

[Run]
Filename: "{code:Winget}"; Parameters: "install --id MiKTeX.MiKTeX --exact --silent --accept-package-agreements --accept-source-agreements"; StatusMsg: "Instalando MiKTeX… puede tardar varios minutos."; Flags: runhidden waituntilterminated; Tasks: miktex
Filename: "{code:Winget}"; Parameters: "install --id JohnMacFarlane.Pandoc --exact --silent --accept-package-agreements --accept-source-agreements"; StatusMsg: "Instalando pandoc…"; Flags: runhidden waituntilterminated; Tasks: pandoc
Filename: "{app}\{#AppExe}"; Description: "Abrir Latexinter"; Flags: nowait postinstall skipifsilent

[Code]
function Winget(Param: String): String;
begin
  Result := ExpandConstant('{localappdata}\Microsoft\WindowsApps\winget.exe');
end;

function HayWinget: Boolean;
begin
  Result := FileExists(Winget(''));
end;

function EstaEnPath(Exe: String): Boolean;
var
  Rutas, Carpeta: String;
  P: Integer;
begin
  Result := False;
  Rutas := GetEnv('PATH') + ';';
  while (not Result) and (Rutas <> '') do
  begin
    P := Pos(';', Rutas);
    Carpeta := Trim(Copy(Rutas, 1, P - 1));
    Delete(Rutas, 1, P);
    if Carpeta <> '' then
      Result := FileExists(AddBackslash(Carpeta) + Exe);
  end;
end;

function FaltaLatex: Boolean;
begin
  Result := HayWinget and not (
    EstaEnPath('pdflatex.exe') or
    FileExists(ExpandConstant('{localappdata}\Programs\MiKTeX\miktex\bin\x64\pdflatex.exe')) or
    FileExists(ExpandConstant('{commonpf64}\MiKTeX\miktex\bin\x64\pdflatex.exe')));
end;

function FaltaPandoc: Boolean;
begin
  Result := HayWinget and not (
    EstaEnPath('pandoc.exe') or
    FileExists(ExpandConstant('{localappdata}\Pandoc\pandoc.exe')) or
    FileExists(ExpandConstant('{commonpf64}\Pandoc\pandoc.exe')));
end;
