# ERP Compta & Logistique — Application desktop

Coquille desktop (pywebview) qui ouvre l'application web React dans une
fenêtre native, avec icône et sans barre de navigateur. **Il n'y a pas de
base de données locale** : l'application se connecte toujours à l'API Django
distante (serveur/cloud), ce qui garantit que tous les postes travaillent sur
les mêmes données en temps réel — cohérent avec un accès multi-sites.

Testé et validé dans cet environnement : la fenêtre s'ouvre, charge
effectivement l'application React buildée, et se ferme proprement.

## Installation (pour développer / tester)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

### Linux uniquement — backend de rendu

pywebview a besoin d'un backend graphique :
- **GTK + WebKit2** (recommandé, déjà présent sur la plupart des environnements de bureau Linux) :
  ```bash
  sudo apt install python3-gi gir1.2-webkit2-4.1   # Debian/Ubuntu
  ```
- **Ou repli Qt** (si GTK indisponible, ex: certains environnements minimalistes/serveurs) :
  ```bash
  pip install -r requirements-linux-qt.txt
  ```

Windows et macOS n'ont besoin d'aucune dépendance système supplémentaire
(EdgeWebView2 sur Windows 10/11 à jour, WKWebView natif sur macOS).

## Configuration

Modifier `config.json` :
```json
{
  "url": "https://erp.monentreprise.com",
  "title": "ERP Comptabilité & Logistique",
  "width": 1400,
  "height": 900
}
```
`url` doit pointer vers l'endroit où le frontend React est déployé (voir
`../erp-frontend`). On peut aussi surcharger sans reconstruire l'exécutable
via la variable d'environnement `ERP_URL` (pratique pour basculer entre un
environnement de test et la production).

## Lancer en développement

```bash
python app.py
```

## Générer l'exécutable

### Méthode recommandée : GitHub Actions (automatique, sans machine Windows)

Le fichier `.github/workflows/build.yml` est déjà prêt. Il suffit de :

1. Pousser ce dossier `erp-desktop` dans un dépôt GitHub :
   ```bash
   cd erp-desktop
   git init
   git add .
   git commit -m "ERP Desktop"
   git remote add origin https://github.com/<ton-compte>/erp-desktop.git
   git push -u origin main
   ```
2. Déclencher le build : soit en créant un tag (`git tag v1.0.0 && git push --tags`),
   soit manuellement depuis l'onglet **Actions** du dépôt GitHub → sélectionner
   le workflow **"Build ERP Desktop"** → **"Run workflow"**.
3. Une fois le job terminé (2-5 minutes), les 3 exécutables sont téléchargeables
   dans l'onglet **Actions → [le run] → Artifacts** :
   - `ERP-Compta-Logistique-Windows.exe`
   - `ERP-Compta-Logistique-macOS`
   - `ERP-Compta-Logistique-Linux`

C'est la méthode la plus simple : **aucune machine Windows n'est nécessaire**,
GitHub fournit lui-même un runner Windows, macOS et Linux, et compile le
`.exe` natif sur son propre Windows.

### Méthode manuelle (si tu as accès à un PC Windows)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python build.py
```
Le fichier `dist\ERP-Compta-Logistique.exe` est généré directement.

### Important : pas de compilation croisée

PyInstaller ne peut pas fabriquer un `.exe` Windows depuis Linux ou macOS
(et inversement) : l'outil doit tourner sur la plateforme cible. Le workflow
GitHub Actions ci-dessus contourne cette limite en utilisant un vrai runner
Windows fourni par GitHub.

## Créer un vrai installeur Windows (.exe d'installation) avec Inno Setup

Plutôt que de distribuer juste `ERP-Compta-Logistique.exe` à copier-coller,
Inno Setup fabrique un installeur classique (raccourcis Bureau/Menu Démarrer,
désinstallation propre depuis "Applications et fonctionnalités").

### 1. Générer d'abord l'exécutable

```powershell
python build.py
```
(voir la section précédente — nécessaire avant de pouvoir créer l'installeur)

### 2. Installer Inno Setup Compiler

Télécharger et installer depuis : https://jrsoftware.org/isdl.php
(version gratuite, "Inno Setup Compiler")

### 3. Ouvrir et compiler le script

Le fichier `installer\setup.iss` est déjà prêt. Deux façons de le compiler :

**Interface graphique** :
1. Ouvrir Inno Setup Compiler
2. Fichier → Ouvrir → sélectionner `installer\setup.iss`
3. Cliquer sur **Compiler** (ou appuyer sur **F9** / **Ctrl+F9**)

**Ligne de commande** (plus rapide si on refait ça souvent) :
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
```

### 4. Résultat

L'installeur est généré dans `installer_output\ERP-Compta-Logistique-Setup.exe`.
C'est **ce fichier-là** qu'on distribue — double-clic dessus installe
l'application avec ses raccourcis, pas besoin de manipuler `dist\` manuellement.

### Notes

- Le script copie automatiquement `config.json` mais **ne l'écrase pas** lors
  d'une réinstallation/mise à jour (flag `onlyifdoesntexist`), pour préserver
  l'URL du serveur déjà configurée par l'utilisateur.
- Pour changer le nom d'éditeur (`Louba Restaurant`) ou la version, éditer les
  lignes `#define` en haut de `installer\setup.iss`.
- Pour ajouter une icône personnalisée : mettre un fichier `icon.ico` dans
  `installer\`, puis décommenter la ligne `SetupIconFile=icon.ico` dans le script.

## Mise à jour de l'application

Comme la coquille ne fait qu'afficher l'URL distante, **il n'y a jamais besoin
de redistribuer l'exécutable** pour livrer une nouvelle version de l'ERP :
il suffit de redéployer le frontend React (`../erp-frontend`) et le backend
Django (`../erp_project`). L'exécutable desktop reste valable indéfiniment,
sauf changement de configuration (nouvelle URL, etc.).
