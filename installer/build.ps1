<#
.SYNOPSIS
    Construye el instalador de Latexinter: dist\Latexinter-<versión>-instalador.exe

.DESCRIPTION
    1. Prepara un entorno de Python 3.12 limpio en build\venv con las
       versiones exactas de installer\requirements-build.txt.
    2. Quita de PyQt5 su copia vieja de la biblioteca de C++ de Microsoft
       (msvcp140.dll 14.26): con ella onnxruntime, que usa pymupdf-layout,
       se cierra de golpe. Sin esa copia se usa la de Windows, más nueva.
    3. Pasa los tests.
    4. Empaqueta con PyInstaller (installer\latexinter.spec).
    5. Crea el instalador con Inno Setup (installer\latexinter.iss).

    La versión sale de __version__ en ui\__init__.py.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build.ps1
#>

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz

function Paso($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }
function Comprobar($que) { if ($LASTEXITCODE -ne 0) { throw "$que falló (código $LASTEXITCODE)." } }

$Venv = Join-Path $Raiz 'build\venv'
$Python = Join-Path $Venv 'Scripts\python.exe'

Paso 'Entorno de Python'
if (-not (Test-Path $Python)) {
    py -3.12 -m venv $Venv; Comprobar 'Crear el entorno con Python 3.12'
}
& $Python -m pip install --quiet --upgrade pip; Comprobar 'Actualizar pip'
& $Python -m pip install --quiet -r installer\requirements-build.txt; Comprobar 'Instalar las dependencias'

Paso 'Quitar la biblioteca de C++ vieja de PyQt5'
$QtBin = Join-Path $Venv 'Lib\site-packages\PyQt5\Qt5\bin'
Get-ChildItem -Path (Join-Path $QtBin '*') -Include 'concrt140.dll', 'msvcp140*.dll', 'vcruntime140*.dll' |
    ForEach-Object { Write-Host "  - $($_.Name)"; Remove-Item $_.FullName }

Paso 'Tests'
& $Python -m pytest tests -q; Comprobar 'Los tests'

$Version = (Select-String -Path 'ui\__init__.py' -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Paso "PyInstaller (versión $Version)"
& $Python -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build\pyinstaller installer\latexinter.spec
Comprobar 'PyInstaller'

Paso 'Inno Setup'
$Iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw 'No está Inno Setup. Instálalo con:  winget install JRSoftware.InnoSetup' }
& $Iscc /Q "/DVersion=$Version" installer\latexinter.iss; Comprobar 'Inno Setup'

$Instalador = Join-Path $Raiz "dist\Latexinter-$Version-instalador.exe"
Paso "Listo: $Instalador ($([math]::Round((Get-Item $Instalador).Length / 1MB)) MB)"
