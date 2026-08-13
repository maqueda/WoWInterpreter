#ifndef StageRoot
#define StageRoot "C:\\WI21\\stage"
#endif

#define MyAppName "WoWInterpreter"
#define MyAppVersion "2.1.34"
#define MyAppExeName "WoWInterpreter.exe"

[Setup]
AppId={{8B46F42D-6E3B-4B6E-9A7D-2C8D8C01D210}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\WoWInterpreter
DefaultGroupName=WoWInterpreter
OutputDir=installer
OutputBaseFilename=WoWInterpreter-2.1.34-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
SetupIconFile=assets\WoWInterpreter.ico
UninstallDisplayIcon={app}\WoWInterpreter.exe
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "installer-languages\ChineseSimplified.isl"

[CustomMessages]
english.AddonsPageTitle=World of Warcraft AddOns folder
english.AddonsPageDescription=Select the AddOns folder where WoWInterpreter will be installed.
english.AddonsPageSubCaption=Choose your World of Warcraft Classic Era AddOns directory, for example:%nC:\Program Files (x86)\World of Warcraft\_classic_era_\Interface\AddOns
english.AddonsFolderMissing=The selected folder does not exist.%n%nPlease select the World of Warcraft AddOns folder.
english.AddonsFolderHint=WoWInterpreter will be installed inside:%n%1\WoWInterpreter
english.StartWithWindows=Start WoWInterpreter when Windows starts
english.DesktopShortcut=Create a desktop shortcut

chinesesimplified.AddonsPageTitle=魔兽世界 AddOns 文件夹
chinesesimplified.AddonsPageDescription=请选择要安装 WoWInterpreter 的 AddOns 文件夹。
chinesesimplified.AddonsPageSubCaption=请选择《魔兽世界》经典怀旧服的 AddOns 目录，例如：%nC:\Program Files (x86)\World of Warcraft\_classic_era_\Interface\AddOns
chinesesimplified.AddonsFolderMissing=所选文件夹不存在。%n%n请选择《魔兽世界》的 AddOns 文件夹。
chinesesimplified.AddonsFolderHint=WoWInterpreter 将安装到：%n%1\WoWInterpreter
chinesesimplified.StartWithWindows=Windows 启动时运行 WoWInterpreter
chinesesimplified.DesktopShortcut=创建桌面快捷方式

[Files]
Source: "Documentation\WoWInterpreter-2.1.34-User-Guide-English.docx"; DestDir: "{app}\Documentation"; Flags: ignoreversion
Source: "Documentation\WoWInterpreter-2.1.34-User-Guide-Chinese-Simplified.docx"; DestDir: "{app}\Documentation"; Flags: ignoreversion
Source: "{#StageRoot}\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageRoot}\addon\*"; DestDir: "{code:GetAddonInstallDir}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "autostart"; Description: "{cm:StartWithWindows}"; GroupDescription: "Startup:"; Flags: unchecked

[Icons]
Name: "{group}\User Guide - English"; Filename: "{app}\Documentation\WoWInterpreter-2.1.34-User-Guide-English.docx"
Name: "{group}\用户指南 - 简体中文"; Filename: "{app}\Documentation\WoWInterpreter-2.1.34-User-Guide-Chinese-Simplified.docx"
Name: "{group}\WoWInterpreter"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\WoWInterpreter"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\WoWInterpreter"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "WoWInterpreter"; Flags: nowait postinstall skipifsilent

[Code]
var
  AddonsPage: TInputDirWizardPage;

procedure InitializeWizard;
begin
  AddonsPage :=
    CreateInputDirPage(
      wpSelectDir,
      CustomMessage('AddonsPageTitle'),
      CustomMessage('AddonsPageDescription'),
      CustomMessage('AddonsPageSubCaption'),
      False,
      ''
    );
  AddonsPage.Add('');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = AddonsPage.ID then
  begin
    if (Trim(AddonsPage.Values[0]) = '') or
       (not DirExists(AddonsPage.Values[0])) then
    begin
      MsgBox(CustomMessage('AddonsFolderMissing'), mbError, MB_OK);
      Result := False;
      exit;
    end;
  end;
end;

function GetAddonInstallDir(Param: String): String;
begin
  Result := AddBackslash(AddonsPage.Values[0]) + 'WoWInterpreter';
end;
