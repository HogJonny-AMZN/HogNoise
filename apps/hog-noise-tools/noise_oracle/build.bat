@echo off
rem LargeWorlds: build fnl_oracle.exe with MSVC. The exe is gitignored.
rem Probes the standard vcvars64.bat locations for Visual Studio 2022 and 2019 (any edition, and the
rem Build Tools); no vswhere, whose "Program Files (x86)" path breaks a for /f set.
setlocal
set "HERE=%~dp0"
set "VCVARS="
for %%y in (2022 2019) do (
    for %%e in (Community Professional Enterprise BuildTools Preview) do (
        if not defined VCVARS if exist "%ProgramFiles%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvars64.bat"
        if not defined VCVARS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvars64.bat"
    )
)
if not defined VCVARS goto :novs
echo using "%VCVARS%"
call "%VCVARS%" >nul
if errorlevel 1 exit /b 1
pushd "%HERE%"
cl /nologo /O2 /EHsc /std:c++17 /W3 /D_CRT_SECURE_NO_WARNINGS fnl_oracle.cpp /Fe:fnl_oracle.exe
set "RC=%errorlevel%"
if exist fnl_oracle.obj del fnl_oracle.obj
popd
exit /b %RC%

:novs
echo no Visual Studio C++ tools found under Program Files; install Visual Studio 2022 with the C++ workload
exit /b 1
