# TikTok Automation Studio

Ce projet est une application de bureau complète (GUI) développée en Python pour automatiser la gestion, l'optimisation et la publication de vidéos sur TikTok.

Il utilise l'intelligence artificielle pour générer des titres et descriptions viraux, et Playwright pour simuler un navigateur humain, permettant de contourner les restrictions d'API classiques.

## Fonctionnalités

* **Interface Graphique (GUI)** : Interface moderne et sombre basée sur `customtkinter`.
* **Multi-Comptes** : Gestion de plusieurs profils TikTok (Chrome Profiles) avec basculement facile.
* **Intelligence Artificielle** :
    * **Transcription** : Utilise `OpenAI Whisper` pour écouter la vidéo et en extraire le texte.
    * **Génération de Contenu** : Utilise `Google Gemini` (avec rotation de clés API) pour créer un titre et des hashtags adaptés au contenu et au type de compte (Français ou Anglais selon le profil).
* **Planification (Scheduling)** : Possibilité de publier immédiatement ou de programmer la vidéo via l'interface native de TikTok Studio.
* **Mode Bulk (Masse)** : Assistant pour sélectionner plusieurs vidéos et les traiter à la chaîne automatiquement.
* **Archivage** : Déplacement automatique des fichiers traités vers un dossier d'archives.

## Prérequis

* Python 3.8+
* Google Chrome installé
* FFmpeg (requis pour Whisper)

## Installation

1.  Cloner le dépôt :
    ```bash
    git clone [https://github.com/votre-nom-utilisateur/tiktok-automation-studio.git](https://github.com/votre-nom-utilisateur/tiktok-automation-studio.git)
    cd tiktok-automation-studio
    ```

2.  Installer les dépendances :
    ```bash
    pip install customtkinter playwright openai-whisper google-generativeai
    ```

3.  Installer les navigateurs Playwright :
    ```bash
    playwright install
    ```

## Configuration

Avant de lancer le script, vous devez modifier certaines variables en haut du fichier `main.py` pour qu'elles correspondent à votre environnement :

### 1. Chemins Chrome
Le script utilise des profils Chrome existants pour conserver la connexion (cookies).
Modifiez la variable `CHROME_DATA` :
```python
CHROME_DATA = r"C:\Users\VotreNom\AppData\Local\Google\Chrome\User Data"