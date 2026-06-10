# Recherche dans les archives de la liste RGAA

Site statique de recherche plein texte dans les [archives publiques de la liste de discussion RGAA](https://groupes.renater.fr/sympa/arc/rgaa) (Renater), avec regroupement par fils de discussion et mise à jour automatique hebdomadaire via GitHub Actions.

## Comment ça marche

- `scraper/scrape.py` parcourt les archives Sympa mois par mois, extrait sujet, auteur, date et corps de chaque message, et produit `docs/data/messages.json`.
- `docs/index.html` est le site : recherche plein texte côté navigateur (insensible à la casse et aux accents), vue par fils de discussion ou par messages, lien vers chaque message original.
- `.github/workflows/update.yml` relance le scraper **tous les lundis matin**, committe les nouvelles données et GitHub Pages republie le site automatiquement.

Le scraper est incrémental : chaque semaine il ne récupère que les mois nouveaux et les deux derniers mois (un fichier JSON par mois dans `docs/data/months/`).

## Installation (une seule fois, ~10 minutes)

1. **Créer le dépôt GitHub.** Sur github.com : « New repository », par exemple `rgaa-archives` (public ou privé — il doit être public pour GitHub Pages gratuit, sauf compte Pro). Puis pousser ce dossier :

   ```bash
   cd rgaa-archives
   git init
   git add .
   git commit -m "Site de recherche des archives RGAA"
   git remote add origin https://github.com/VOTRE_COMPTE/rgaa-archives.git
   git push -u origin main
   ```

   (Ou plus simple sans ligne de commande : créer le dépôt sur github.com puis « uploading an existing file » et glisser-déposer tout le contenu du dossier.)

2. **Autoriser le workflow à écrire.** Dans le dépôt : Settings → Actions → General → Workflow permissions → cocher « Read and write permissions » → Save.

3. **Activer GitHub Pages.** Settings → Pages → Source : « Deploy from a branch » → Branch : `main`, dossier `/docs` → Save. L'adresse du site s'affiche au bout d'une minute ou deux (`https://VOTRE_COMPTE.github.io/rgaa-archives/`).

4. **Lancer la première récupération complète.** Onglet Actions → « Mise à jour des archives RGAA » → « Run workflow » → cocher « Récupération complète de l'historique » → Run. Comptez 30 à 45 minutes (~2 400 messages, avec une pause de politesse entre chaque requête). À la fin, le site affiche tout l'historique depuis juin 2022.

C'est tout. Ensuite, chaque lundi matin, le site se met à jour seul.

## Résumés IA des conversations (optionnel)

Si une clé API Anthropic est configurée, chaque fil de discussion affiche un résumé de 2 phrases (question posée + réponse retenue), généré par le modèle Claude Haiku. Seuls les fils nouveaux ou modifiés sont résumés à chaque mise à jour hebdomadaire (cache dans `docs/data/summaries.json`).

Pour l'activer :

1. Créer une clé API sur [console.anthropic.com](https://console.anthropic.com) (Settings → API keys) et y mettre quelques euros de crédit. Le premier passage sur ~450 fils coûte environ 2 €, puis quelques centimes par semaine.
2. Dans le dépôt GitHub : Settings → Secrets and variables → Actions → « New repository secret ». Nom : `ANTHROPIC_API_KEY`, valeur : la clé. Save.
3. Lancer le workflow manuellement (Actions → Run workflow) ou attendre le lundi suivant.

Sans clé, le site fonctionne normalement, simplement sans résumés.

## Lancer le scraper en local (optionnel)

```bash
pip install -r scraper/requirements.txt
python scraper/scrape.py --full          # tout l'historique
python scraper/scrape.py                 # incrémental
python scraper/scrape.py --months 2026-05 2026-06
```

Pour tester le site en local : `python3 -m http.server -d docs` puis ouvrir http://localhost:8000.

## Si le scraping casse un jour

Si Renater change la structure des pages, le scraper le détecte (plus de 20 % de messages sans corps lors d'un `--full`) et s'arrête sans rien committer. Le point d'entrée à ajuster est la fonction `parse_message()` dans `scraper/scrape.py`.

## Notes

- **Respect de la source** : une requête toutes les ~0,6 s, mise à jour une fois par semaine seulement. Les adresses email sont déjà masquées par Renater côté serveur.
- **Mention non officielle** : le site indique clairement qu'il n'est affilié ni à la DINUM ni à Renater, et chaque résultat renvoie vers le message original. Par courtoisie, vous pouvez prévenir les modérateurs de la liste de l'existence du site.
- Les données vivent dans le dépôt (`docs/data/`) : pas de base de données, pas de serveur, hébergement 100 % gratuit.
