function Enable-PSScriptBlockLogging
{
    $basePath = “HKLM:\Software\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging”

    if(-not (Test-Path $basePath))
    {
        $null = New-Item $basePath -Force
    }
    
    Set-ItemProperty $basePath -Name EnableScriptBlockLogging -Value “1”
}

function Disable-PSScriptBlockLogging
{
    Remove-Item HKLM:\Software\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging -Force -Recurse
}

function Enable-PSScriptBlockInvocationLogging
{
    $basePath = “HKLM:\Software\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging”

    if(-not (Test-Path $basePath))
    {
        $null = New-Item $basePath -Force
    }

    Set-ItemProperty $basePath -Name EnableScriptBlockInvocationLogging -Value “1”
}
