const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process');
// Playwright est un outil de développement facultatif. Le serveur n'en dépend pas.

(async()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'immogui-browser-'));
 const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
 const base='http://127.0.0.1:'+port;
 const env=Object.fromEntries(Object.entries(process.env).filter(([k])=>!k.startsWith('IMMOGUI_ACCOUNT_IMPORT')));
 Object.assign(env,{HOST:'127.0.0.1',PORT:String(port),APP_ENV:'development',DATABASE_PATH:path.join(tmp,'test.sqlite3')});
 const server=spawn(process.env.IMMOGUI_TEST_PYTHON||'python3',['server.py'],{cwd:path.join(__dirname,'..'),env,stdio:'ignore'});
 let browser;
 try{
 let ready=false;for(let i=0;i<100;i++){try{const response=await fetch(base+'/api/health');if(response.ok){ready=true;break}}catch{}await new Promise(resolve=>setTimeout(resolve,50))}
 assert.equal(ready,true,'Le serveur de test doit démarrer');
 const executablePath=process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||(fs.existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined);
 browser=await chromium.launch({executablePath,headless:true});
 const page=await browser.newPage({viewport:{width:390,height:844}});page.setDefaultTimeout(7000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const route=async name=>{await page.evaluate(name=>{location.hash=name},name);await page.waitForFunction(name=>location.hash==='#'+name,name)};
 const submit=async()=>{await page.locator('#form button[type=submit]').click();await page.locator('#dialog').waitFor({state:'hidden'})};
 try{
  await page.goto(base+'/#signup');await page.locator('#account-form').waitFor();
  await page.getByLabel('Nom complet',{exact:true}).fill('Validation Mobile');await page.getByLabel('Adresse email').fill('mobile-'+Date.now()+'@example.invalid');await page.getByLabel('Mot de passe',{exact:true}).fill('validation-mobile-1234');await page.locator('#account-form button').click();await page.locator('body:not(.public-page)').waitFor();
  await route('properties');await page.getByRole('button',{name:'Ajouter un bien',exact:true}).first().click();
  await page.getByLabel('Nom du bien',{exact:true}).fill('Résidence test');await page.getByLabel('Quartier, commune et ville').fill('Kipé, Conakry');await page.getByLabel('Appartements',{exact:true}).check();await page.getByLabel('Nombre : Appartements',{exact:true}).fill('2');await submit();console.log('Bien enregistré');
  await route('tenants');await page.getByRole('button',{name:'Ajouter un locataire',exact:true}).click();await page.getByLabel('Nom complet',{exact:true}).fill('Locataire test');await page.getByLabel('Téléphone',{exact:true}).fill('620123456');await page.getByLabel('Bien immobilier',{exact:true}).selectOption({label:'Résidence test'});await page.getByLabel('Type de bien loué',{exact:true}).selectOption('Appartement');await page.getByLabel('Numéro ou nom').fill('A01');await page.getByLabel('Loyer mensuel en GNF',{exact:true}).fill('3000');await page.getByLabel('Date d’entrée').fill('2026-10-20');await page.getByLabel('Caution en GNF').fill('6000');await page.getByLabel('Jour d’échéance').fill('31');await submit();
  await page.locator('#month').fill('2026-10');assert.match(await page.locator('tbody').innerText(),/3\s?000/);console.log('Bail : mois commencé dû en entier');
  await page.locator('#search').fill('INEXISTANT');await page.getByText('Aucun élément à afficher pour cette sélection.',{exact:true}).waitFor();await page.locator('#clear-filters').click();await page.locator('tbody').waitFor();
  await route('payments');await page.getByRole('button',{name:'Enregistrer un loyer',exact:true}).click();await page.getByLabel('Locataire',{exact:true}).selectOption({label:'Locataire test — Résidence test'});await page.getByLabel('Mois du loyer').fill('2026-10');await page.getByLabel('Montant en francs guinéens (GNF)').fill('1000');await submit();
  const [receipt]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'Reçu PDF ↓'}).click()]);assert.match(receipt.suggestedFilename(),/\.pdf$/);console.log('Reçu PDF téléchargé');
  await page.locator('#status-filter').selectOption('unpaid');assert.match(await page.locator('#main').innerText(),/Partiel/);
  await page.locator('[data-edit-tenant]').click();await page.getByLabel('Loyer mensuel en GNF',{exact:true}).fill('4000');await page.getByLabel('Nouveau loyer applicable').fill('2026-11');await submit();await page.locator('#month').fill('2026-10');assert.equal(await page.evaluate(()=>rentForMonth(db.tenants[0],'2026-10')),3000);assert.equal(await page.evaluate(()=>rentForMonth(db.tenants[0],'2026-11')),4000);console.log('Historique conservé après changement de loyer');
  await page.screenshot({path:path.join(tmp,'mobile-payments.png'),fullPage:true});
  await route('properties');await page.getByRole('link',{name:'Voir le détail',exact:true}).click();await page.getByRole('heading',{name:'Logements et locaux identifiés'}).waitFor();assert.match(await page.locator('#main').innerText(),/A01/);await page.getByRole('button',{name:'Modifier',exact:true}).click();await page.locator('#cancel').click();console.log('Fiche détaillée et modification du bail');
  await route('account');await page.locator('#download-backup').waitFor();const [backup]=await Promise.all([page.waitForEvent('download'),page.locator('#download-backup').click()]);const backupPath=await backup.path();const document=JSON.parse(fs.readFileSync(backupPath));assert.equal(document.format,'immogui-backup');await page.locator('#restore-file').setInputFiles({name:'sauvegarde.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(document))});await page.locator('#confirm-restore').click();await page.getByText('Restauration effectuée. L’état précédent a été sauvegardé.',{exact:true}).waitFor();console.log('Sauvegarde et restauration depuis le fichier');
  await page.getByRole('link',{name:'Vérification de mon email',exact:true}).click();await page.getByText('L’envoi d’emails n’est pas encore activé. Aucun message n’a été envoyé.',{exact:true}).waitFor();await page.getByRole('link',{name:'← Retour à mon compte',exact:true}).click();await page.locator('#download-backup').waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
  await page.setViewportSize({width:1440,height:1000});await route('payments');await page.screenshot({path:path.join(tmp,'desktop-payments.png'),fullPage:true});console.log('Parcours mobile et affichage bureau : OK, aucune erreur JavaScript');
 }catch(error){await page.screenshot({path:path.join(tmp,'failure.png'),fullPage:true});console.error('Page:',await page.locator('body').innerText());throw error}finally{await browser.close()}
 }finally{server.kill();console.log('Captures de test : '+tmp)}
})().catch(e=>{console.error(e);process.exit(1)});
