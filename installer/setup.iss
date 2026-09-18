; Script Inno Setup pour l'ERP Compta & Logistique — version offline.
; Compiler ce fichier avec Inno Setup Compiler (ISCC.exe ou l'interface
; graphique) APRÈS avoir généré dist\ERP-Compta-Logistique\ (un DOSSIER,
; pas un simple .exe) via "python build.py".
;
; Résultat : installer_output\ERP-Compta-Logistique-Setup.exe
; Un simple double-clic installe l'application (exécutable + serveur Django
; embarqué + frontend) avec raccourcis Bureau/Menu Démarrer, et une
; désinstallation propre depuis "Applications et fonctionnalités" —
; exactement le même vécu utilisateur qu'un installateur Sage.

#define MyAppName "ERP Compta & Logistique"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "Groupe Louba"
#define MyAppExeName "ERP-Compta-Logistique.exe"

[Setup]
AppId={{8F2C9B3A-7D4E-4A1B-9C5F-1E6D8A2B4C7F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
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
; Le dossier complet généré par build.py (--onedir) : l'exécutable, ses
; bibliothèques, ET erp_project/ (serveur Django embarqué) copiés dedans.
; "recursesubdirs" est indispensable ici — c'est la différence principale
; avec l'ancien script (onefile n'avait qu'un seul fichier à copier).
Source: "..\dist\{#MyAppExeName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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

[UninstallDelete]
; La base de données locale (SQLite) N'EST PAS ici : elle vit dans
; %APPDATA%\LoubaERP\ (voir config/settings_offline.py), donc une
; désinstallation ne supprime jamais les données comptables locales par
; erreur. Un COMPTABLE souhaitant repartir de zéro doit le faire
; manuellement en supprimant ce dossier APPDATA.
