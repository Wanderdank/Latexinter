<#
.SYNOPSIS
    Latexinter - conversiones entre PDF, LaTeX y Word desde PowerShell.

.DESCRIPTION
    Envoltorio del conversor en Python (cli.py). Para el uso diario es más
    cómoda la interfaz gráfica:  .\build.ps1 gui

.PARAMETER Action
    gui       Abre la interfaz de escritorio (por defecto)
    pdf       Compila un .tex a PDF
    word      Convierte un .tex a Word
    frompdf   Convierte un PDF a LaTeX
    fromword  Convierte un .docx a LaTeX
    all       Compila a PDF y a Word
    clean     Borra los archivos auxiliares de LaTeX
    deps      Comprueba que estén instaladas las dependencias

.PARAMETER File
    Nombre del archivo sin extensión. Por defecto: "ejemplos/ejemplo"

.PARAMETER Pages
    Solo para frompdf. Rango de páginas: "1-5" o "1,3,8-10"

.EXAMPLE
    .\build.ps1 gui
    .\build.ps1 pdf  -File mi_documento
    .\build.ps1 frompdf -File articulo -Pages "1-6"
    .\build.ps1 fromword -File informe
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("gui", "pdf", "word", "frompdf", "fromword", "all", "clean", "deps")]
    [string]$Action = "gui",

    [string]$File = "ejemplos/ejemplo",
    [string]$Pages = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$cli = Join-Path $root "cli.py"

function Write-Title { param($msg)
    Write-Host "`n══════════════════════════════════════" -ForegroundColor Magenta
    Write-Host "  $msg" -ForegroundColor Magenta
    Write-Host "══════════════════════════════════════`n" -ForegroundColor Magenta
}
function Write-Ok  { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Err { param($msg) Write-Host "  ✗ $msg" -ForegroundColor Red }

function Resolve-Input {
    param([string]$Extension)
    $candidate = if ([System.IO.Path]::GetExtension($File)) { $File } else { "$File$Extension" }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $root $candidate
    }
    if (-not (Test-Path $candidate)) {
        Write-Err "No se encontró '$candidate'."
        return $null
    }
    return $candidate
}

function Invoke-Cli {
    param([string]$Command, [string]$Path, [string[]]$Extra = @())
    $arguments = @($cli, $Command, $Path) + $Extra
    python @arguments
    if ($LASTEXITCODE -ne 0) { Write-Err "La conversión falló."; return $false }
    return $true
}

function Clean-Aux {
    Write-Title "Limpiando archivos auxiliares"
    $extensions = @("*.aux", "*.log", "*.out", "*.toc", "*.synctex.gz",
                    "*.fls", "*.fdb_latexmk", "*.bbl", "*.blg", "*.bcf",
                    "*.run.xml", "*.nav", "*.snm", "*.lof", "*.lot",
                    "*.idx", "*.ilg", "*.ind")
    $count = 0
    foreach ($ext in $extensions) {
        foreach ($f in Get-ChildItem -Path $root -Filter $ext -ErrorAction SilentlyContinue) {
            Remove-Item $f.FullName -Force
            $count++
        }
    }
    Write-Ok "Se eliminaron $count archivos auxiliares."
}

switch ($Action) {
    "gui" {
        Write-Title "Latexinter"
        python $cli gui
    }
    "deps" {
        python $cli deps
    }
    "pdf" {
        $path = Resolve-Input ".tex"
        if ($path) { Invoke-Cli "tex2pdf" $path | Out-Null }
    }
    "word" {
        $path = Resolve-Input ".tex"
        if ($path) { Invoke-Cli "tex2docx" $path | Out-Null }
    }
    "frompdf" {
        $path = Resolve-Input ".pdf"
        if ($path) {
            $extra = @()
            if ($Pages) { $extra = @("--pages", $Pages) }
            Invoke-Cli "pdf2tex" $path $extra | Out-Null
        }
    }
    "fromword" {
        $path = Resolve-Input ".docx"
        if ($path) { Invoke-Cli "docx2tex" $path | Out-Null }
    }
    "all" {
        $path = Resolve-Input ".tex"
        if ($path) {
            $ok = Invoke-Cli "tex2pdf" $path
            Invoke-Cli "tex2docx" $path | Out-Null
            if ($ok) { Write-Ok "Listo: se generaron el PDF y el .docx" }
        }
    }
    "clean" { Clean-Aux }
}
