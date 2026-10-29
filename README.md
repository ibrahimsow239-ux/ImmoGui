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

Les données initiales sont fictives, pour octobre 2026. Le graphique représente uniquement les opérations effectivement saisies. Chaque locataire représente un logement occupé. Les dates de bail et les historiques de loyers sont décrits ci-dessous.

Le mode démonstration utilise le stockage du navigateur. Pour les comptes et la base de données, utiliser le serveur décrit ci-dessous.

## Comptes partenaires (serveur local)

Lancer `python3 server.py` et ouvrir http://127.0.0.1:8000. La page d'accueil propose l'inscription, la connexion et une démonstration. Chaque nouveau compte possède un espace vide, indépendant des autres utilisateurs. Les données sont conservées dans `immogui.sqlite3` (à sauvegarder). Les mots de passe sont hachés avec PBKDF2-SHA256 (600 000 itérations) ; la session HttpOnly expire après 24 heures. La déconnexion ferme les sessions du compte.

La création de comptes nécessite ce serveur : elle est désactivée lors d'une ouverture en `file://`. Le serveur écoute uniquement sur la machine locale. Le mode de déploiement HTTPS est décrit ci-dessous. La récupération de mot de passe, la validation des emails, la validation métier complète et les sauvegardes externes automatisées du volume restent à mettre en place avant un lancement public.

## Déploiement Railway (préparé, à déclencher manuellement)

Le dépôt contient un Dockerfile et railway.json. Railway construit l'image Python, démarre le serveur sur le port fourni et vérifie `/api/health`.

1. Créer un projet Railway depuis le dépôt `ibrahimsow239-ux/ImmoGui`, branche `main`.
2. Ajouter un volume persistant au service, monté sur `/data`, avant de créer des comptes.
3. Générer un domaine public HTTPS pour ce service.
4. Vérifier l'accueil, les deux images, l'inscription et la connexion.

L'image configure `HOST=0.0.0.0`, `APP_ENV=production` et `DATABASE_PATH=/data/immogui.sqlite3`. Les cookies de session sont Secure et HttpOnly en production. Les requêtes d'écriture exigent une origine identique au site. Les inscriptions et connexions sont limitées à 20 tentatives par adresse réseau sur 15 minutes.

Le disque persistant doit être sauvegardé régulièrement. Il ne remplace pas une sauvegarde. La récupération des mots de passe, la vérification des emails et la validation métier complète côté serveur restent à développer avant un lancement auprès du public.

## Baux et historique des loyers

La fiche locataire permet de saisir l’entrée, le dernier jour d’occupation, la caution (distincte des encaissements) et le jour d’échéance. Les dates sont inclusives ; chaque mois commencé pendant le bail est dû en entier, sans prorata. Une échéance fixée au 31 tombe le dernier jour des mois plus courts. L’occupation affichée correspond à la date du jour. Un logement peut être réattribué après la fin du bail précédent.

Les anciens locataires sont conservés sans inventer leur date d’entrée : leur suivi débute au premier mois de paiement connu, ou au mois de migration si aucun paiement n’existe. Ce début de suivi est enregistré et ne se décale pas au fil des mois. Renseignez leurs dates réelles si vous les connaissez. Leur loyer actuel sert de référence initiale ; les anciens tarifs inconnus ne sont pas reconstitués. Lors d’un changement de loyer, renseignez le mois d’application. Chaque nouveau tarif doit suivre le dernier changement enregistré ; un mois ayant déjà un encaissement, ainsi que les mois précédents, est protégé contre une révision. L’historique est visible dans la modification du locataire. Une modification de bail qui changerait le loyer d’un mois déjà encaissé est refusée.

Vérifications des calculs : `node tests/leases.cjs`. Les montants, dates, références, tarifs historiques et nouveaux paiements sont également contrôlés par le serveur. Les paiements existants sont conservés en dehors d’une restauration explicite.

## Recherche, fiches de biens et reçus

Les écrans Locataires et Loyers proposent une recherche par nom, téléphone, logement ou bien, un filtre par bien et un filtre des impayés. Les dépenses proposent une recherche par libellé/catégorie et un filtre par bien. Les exports CSV respectent la sélection. Les totaux du tableau de bord restent ceux du mois complet.

Cliquer sur le nom d’un bien ou sur « Voir le détail » affiche les unités identifiées, leur disponibilité actuelle, les baux et les dépenses du mois choisi. La capacité sans numéro de logement reste comptée sans inventer des unités.

Chaque encaissement d’un compte connecté possède un lien « Reçu PDF ». Le reçu indique le versement, le mois de loyer, la référence et le solde après ce versement, avec une mention de paiement partiel. Pour les nouveaux versements, les informations du reçu sont figées au moment de l’enregistrement. Les anciens reçus sont reconstitués à partir des données connues et de l’ordre d’enregistrement. Aucun service externe n’est utilisé.

## Compte, sauvegardes et restauration

« Compte & sauvegardes » permet de télécharger un export JSON du compte connecté et de restaurer un fichier du même compte ou une version précédente. Le serveur conserve les 50 dernières versions avant modification. Avant toute restauration, l’état actuel est sauvegardé dans la même transaction SQLite. L’opération ne modifie que les données du partenaire connecté ; les identifiants et fichiers d’un autre compte sont refusés. Les sessions, mots de passe et rôles ne sont pas importés par ces fichiers.

Ces versions sont stockées dans la même base : elles ne protègent pas contre la perte du disque. Conservez les exports sur un autre appareil et sauvegardez le volume Railway séparément. La démonstration conserve son fonctionnement local ; restauration et reçus PDF nécessitent un compte sur le serveur.

Les pages « Mot de passe oublié » et « Vérification de l’email » sont préparées, mais l’envoi est désactivé. Aucun email n’est envoyé et aucun écran n’annonce un envoi réussi. Un fournisseur d’emails et les flux de jetons sécurisés devront être ajoutés pour activer ces fonctions.

Validation : `node tests/leases.cjs` puis `python3 -m unittest discover -s tests -p 'test_*.py' -v`. Les tests HTTP démarrent un serveur et deux comptes dans une base temporaire ; l’inspection du PDF utilise `pdftotext` (outil de développement, pas une dépendance du serveur).

Test facultatif du parcours mobile/bureau : avec Playwright et Chromium disponibles dans l’environnement de développement, lancer `node tests/browser.cjs`. Il utilise aussi une base temporaire et des comptes fictifs, télécharge un reçu PDF, change le tarif et restaure un fichier exporté. `PLAYWRIGHT_CHROMIUM_EXECUTABLE` permet d’indiquer un navigateur installé.
