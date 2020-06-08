$out=".\Output.csv" 
$Totaloutput=@() 
foreach($server in $servers){ 
 
try{ 
 
    if(Test-Connection -Count 1 $server -Quiet) 
        { 
            $reg=[Microsoft.Win32.RegistryKey]::OpenRemoteBaseKey('LocalMachine',$server) 
            $regkey = $reg.OpenSubkey("SYSTEM\\CurrentControlSet\\Control\\CrashControl") 
            $page = $reg.OpenSubkey("SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Memory Management") 
            if((-not $regkey) -or (-not $page)) { 
                    write-host Required registery key not found on $server -ForegroundColor DarkGreen 
                    $output=""|select MachineName,Comment,DumpRegValue,DumpConfiguration,AutoReboot,DumpDirectory,PagefileInfo 
                    $output.MachineName=$server 
                    $output.Comment="REACHABLE ON NETWORK BUT REQUIRED REGISTRY KEY NOT FOUND" 
                    $output.DumpConfiguration="" 
                    $Output.DumpRegValue="" 
                    $Output.AutoReboot="" 
                    $Output.DumpDirectory="" 
                    $Output.PagefileInfo="" 
                    $Totaloutput+=$output 
                    } 
            else{write-host GETTING INFO FROM $server -ForegroundColor Cyan 
                    $cd=$regKey.GetValue("CrashDumpEnabled") 
                    $ar=$regKey.GetValue("AutoReboot") 
                    $pinfo=$page.GetValue("PagingFiles") -join "" 
                    Switch ($cd) 
                    { 
                    0{$dumpConf="Memory Dump is NOT configured"} 
                    1{$dumpConf=“Complete memory dump is configured”} 
                    2{$dumpConf=“Kernel memory dump is configured”} 
                    3{$dumpConf=“Small memory dump”} 
                    7{$dumpConf=“Default/Automatic memory dump”} 
                    } 
                    Switch ($ar) 
                    { 
                    0{$Reboot="FALSE"} 
                    1{$Reboot=“TRUE”} 
                    } 
                    $output=""|select MachineName,Comment,DumpRegValue,DumpConfiguration,AutoReboot,DumpDirectory,PagefileInfo 
                    $output.MachineName=$server 
                    $output.Comment="REACHABLE ON NETWORK" 
                    $output.DumpConfiguration=$dumpConf 
                    $Output.DumpRegValue=$cd 
                    $Output.AutoReboot=$Reboot 
                    $Output.DumpDirectory=$regKey.GetValue("DumpFile") 
                    $Output.PagefileInfo=$pinfo 
                    $Totaloutput+=$output 
                    } 
                } 
                else{ 
                    $output=""|select MachineName,Comment,DumpRegValue,DumpConfiguration,AutoReboot,DumpDirectory,PagefileInfo 
                    $output.MachineName=$server 
                    $output.Comment="NOT REACHABLE ON NETWORK" 
                    $output.DumpConfiguration="" 
                    $Output.DumpRegValue="" 
                    $Output.AutoReboot="" 
                    $Output.DumpDirectory="" 
                    $Output.PagefileInfo="" 
                    $Totaloutput+=$output 
                    Write-Host $server NOT REACHABLE -ForegroundColor Red  
                    } 
                    } 
                    
                 
catch{ 
                     
                    $FailedItem = $_.Exception.ItemName 
                    $output=""|select MachineName,Comment,DumpRegValue,DumpConfiguration,AutoReboot,DumpDirectory,PagefileInfo 
                    $output.MachineName=$server 
                    $output.Comment=$_.Exception.Message 
                    $output.DumpConfiguration="" 
                    $Output.DumpRegValue="" 
                    $Output.AutoReboot="" 
                    $Output.DumpDirectory="" 
                    $Output.PagefileInfo="" 
                    $Totaloutput+=$output 
                    echo $_.Exception|format-list -force  
    } 
} 
$Totaloutput|Export-Csv $out -NoTypeInformation -Append
