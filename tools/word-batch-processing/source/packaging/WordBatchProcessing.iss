#define MyAppName "Word 批量处理"
#define MyAppVersion "2.0.1"
#define MyAppExeName "Word批量处理.exe"

[Setup]
AppId={{3C6D90F9-9D07-4AE7-BF84-79F0B9569ECD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={localappdata}\Programs\WordBatchProcessing
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\release
OutputBaseFilename=Word批量处理-2.0.1-安装程序
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "..\dist\Word批量处理\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ClearAppDataCheckBox: TNewCheckBox;

procedure InitializeUninstallProgressForm();
begin
  ClearAppDataCheckBox := TNewCheckBox.Create(UninstallProgressForm);
  ClearAppDataCheckBox.Parent := UninstallProgressForm.InnerPage;
  ClearAppDataCheckBox.Left := 0;
  ClearAppDataCheckBox.Top := UninstallProgressForm.StatusLabel.Top + 42;
  ClearAppDataCheckBox.Width := UninstallProgressForm.InnerPage.ClientWidth;
  ClearAppDataCheckBox.Caption := '同时清除本机的批次状态和撤销缓存';
  ClearAppDataCheckBox.Checked := False;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and
     Assigned(ClearAppDataCheckBox) and ClearAppDataCheckBox.Checked then
  begin
    DelTree(ExpandConstant('{localappdata}\WordBatchProcessing'), True, True, True);
  end;
end;
