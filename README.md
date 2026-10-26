# immoGui

Première version locale de gestion immobilière en français et en francs guinéens (GNF), sans dépendances à installer.

## Ouvrir le site

Lancer `python3 server.py` puis ouvrir http://127.0.0.1:8000. Une ouverture directe de `index.html` permet seulement la démonstration.

## Fonctions

- Tableau de bord mensuel : encaissements, dépenses, solde et loyers à recevoir.
- Biens : nom, adresse, type et capacité en logements.
- Locataires : coordonnées, logement unique par bien, loyer mensuel.
- Paiements partiels, prévention des versements supérieurs au loyer du mois.
- Dépenses par bien et par catégorie.
- Export CSV des encaissements et des dépenses du mois.
- Adaptation mobile et sauvegarde locale dans le navigateur.

## Limites de cette première étape

Les données initiales sont fictives, pour octobre 2026. Le graphique représente uniquement les opérations effectivement saisies. Chaque locataire représente un logement occupé. Les loyers sont calculés à partir de la liste actuelle des locataires, sans gestion de début et fin de bail à ce stade.

Le mode démonstration utilise le stockage du navigateur. Pour les comptes et la base de données, utiliser le serveur décrit ci-dessous.

## Comptes partenaires (serveur local)

Lancer `python3 server.py` et ouvrir http://127.0.0.1:8000. La page d'accueil propose l'inscription, la connexion et une démonstration. Chaque nouveau compte possède un espace vide, indépendant des autres utilisateurs. Les données sont conservées dans `immogui.sqlite3` (à sauvegarder). Les mots de passe sont hachés avec PBKDF2-SHA256 (600 000 itérations) ; la session HttpOnly expire après 24 heures. La déconnexion ferme les sessions du compte.

La création de comptes nécessite ce serveur : elle est désactivée lors d'une ouverture en `file://`. Le serveur écoute uniquement sur la machine locale. Le mode de déploiement HTTPS est décrit ci-dessous. La récupération de mot de passe, la validation des emails, la validation métier côté serveur et les sauvegardes automatisées restent à mettre en place avant un lancement public.

## Déploiement Railway (préparé, à déclencher manuellement)

Le dépôt contient un Dockerfile et railway.json. Railway construit l'image Python, démarre le serveur sur le port fourni et vérifie `/api/health`.

1. Créer un projet Railway depuis le dépôt `ibrahimsow239-ux/ImmoGui`, branche `main`.
2. Ajouter un volume persistant au service, monté sur `/data`, avant de créer des comptes.
3. Générer un domaine public HTTPS pour ce service.
4. Vérifier l'accueil, les deux images, l'inscription et la connexion.

L'image configure `HOST=0.0.0.0`, `APP_ENV=production` et `DATABASE_PATH=/data/immogui.sqlite3`. Les cookies de session sont Secure et HttpOnly en production. Les requêtes d'écriture exigent une origine identique au site. Les inscriptions et connexions sont limitées à 20 tentatives par adresse réseau sur 15 minutes.

Le disque persistant doit être sauvegardé régulièrement. Il ne remplace pas une sauvegarde. La récupération des mots de passe, la vérification des emails et la validation métier complète côté serveur restent à développer avant un lancement auprès du public.
