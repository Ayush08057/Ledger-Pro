@echo off
title Ledger Pro - Create Desktop Shortcut
echo Creating desktop shortcut for Ledger Pro...
set SCRIPT="%TEMP%\ledgerpro_shortcut.vbs"
echo Set oWS = WScript.CreateObject("WScript.Shell") > %SCRIPT%
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\Ledger Pro Offline Accounting.lnk" >> %SCRIPT%
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> %SCRIPT%
echo oLink.TargetPath = "%~dp0start_tally.bat" >> %SCRIPT%
echo oLink.WorkingDirectory = "%~dp0" >> %SCRIPT%
echo oLink.Description = "Launch Ledger Pro Offline Accounting System" >> %SCRIPT%
echo oLink.Save >> %SCRIPT%
cscript /nologo %SCRIPT%
del %SCRIPT%
echo.
echo ========================================================
echo   Desktop shortcut created successfully!
echo   Location: Desktop \ "Ledger Pro Offline Accounting"
echo ========================================================
pause
