Try {
    Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
    Write-Host "Execution Policy set to RemoteSigned."
} Catch {
    Write-Host "Failed to change Execution Policy. Please run as Administrator."
    exit
}

$repoUrl = "https://github.com/dangkhoa2806/LMS_bypassV3"
$installPath = "$HOME\LMS_bypassV3"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is not installed. Installing Git..."
    
    winget install --id Git.Git -e --source winget

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "Git installation failed. Exiting..."
        exit
    }
}

if (Test-Path $installPath) {
    Write-Host "Repository already exists. Updating..."
    Set-Location $installPath
    git pull
} else {
    Write-Host "Cloning repository to $installPath..."
    git clone $repoUrl $installPath
}

Set-Location $installPath

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python is not installed. Installing Python..."
    
    winget install --id Python.Python.3 -e --source winget

    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "Python installation failed. Exiting..."
        exit
    }
}

if (Test-Path "$installPath\requirements.txt") {
    Write-Host "Installing dependencies from requirements.txt..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
} else {
    Write-Host "requirements.txt not found."
}

if (Test-Path "$installPath\LMS_bypass.pyw") {
    Write-Host "Launching LMS_bypass.pyw..."
    Start-Process pythonw -ArgumentList "LMS_bypass.pyw"
} else {
    Write-Host "LMS_bypass.pyw not found."
}
