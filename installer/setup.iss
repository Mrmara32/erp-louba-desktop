; Script Inno Setup pour l'ERP Compta & Logistique.
; Compiler ce fichier avec Inno Setup Compiler (ISCC.exe ou l'interface graphique)
; APRÈS avoir généré dist\ERP-Compta-Logistique.exe via "python build.py".
;
; Résultat : installer_output\ERP-Compta-Logistique-Setup.exe
; C'est CE fichier-là qu'on distribue aux utilisateurs finaux — un simple
; double-clic installe l'application avec raccourcis Bureau/Menu Démarrer
; et une désinstallation propre depuis "Applications et fonctionnalités".

#define MyAppName "ERP Compta & Logistique"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Louba Restaurant"
#define MyAppExeName "ERP-Compta-Logistique.exe"

[Setup]
AppId={{8F2C9B3A-7D4E-4A1B-9C5F-1E6D8A2B4C7F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Dossier de sortie de l'installeur généré, relatif à ce fichier .iss
OutputDir=..\installer_output
OutputBaseFilename=ERP-Compta-Logistique-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; Décommenter si un fichier .ico est ajouté au projet :
; SetupIconFile=icon.ico

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Icônes supplémentaires :"

[Files]
; L'exécutable généré par PyInstaller (build.py)
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; config.json : "onlyifdoesntexist" est important — si l'utilisateur a déjà
; personnalisé son URL de serveur lors d'une installation précédente, une
; mise à jour ne doit PAS écraser sa configuration.
Source: "..\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent
