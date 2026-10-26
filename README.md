# immoGui

Première version locale de gestion immobilière en français et en francs guinéens (GNF), sans dépendances à installer.

## Ouvrir le site

Ouvrir `index.html` dans un navigateur, ou lancer `python3 -m http.server 8000` depuis ce dossier puis visiter http://localhost:8000.

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

La création de comptes nécessite ce serveur : elle est désactivée lors d'une ouverture en `file://`. Le serveur écoute uniquement sur la machine locale. Avant publication : hébergement HTTPS, limitation des tentatives de connexion, récupération de mot de passe, validation des emails, validation métier côté serveur et sauvegardes automatisées restent à mettre en place. Cette version locale ne doit pas être exposée directement sur Internet.
