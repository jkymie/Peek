# Cria um atalho "Peek" na Área de Trabalho que abre a janela do Peek sem terminal.
# Só para desenvolvimento: quem não programa vai usar o Peek.exe (Fase 9).
#
# Uso (na raiz do repositório):
#   powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Error "Não encontrei $pythonw. Crie o ambiente com: python -m venv .venv"
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$path = Join-Path $desktop "Peek.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($path)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m host"
$shortcut.WorkingDirectory = $repo
$shortcut.Description = "Transmitir a tela para os amigos"
$shortcut.Save()
Write-Output "Atalho criado: $path"
