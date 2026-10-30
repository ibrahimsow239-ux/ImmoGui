"""Export Excel mensuel, produit côté serveur uniquement pour le compte connecté.

XlsxWriter est utilisé à l'exécution dans le conteneur Python (sans runtime
Node/artifact-tool). Les cellules contenant des saisies utilisateur sont du texte.
"""
import datetime as dt
import io
import xlsxwriter
from domain import normalize as normalize_data, month_valid as valid_month, rent_for_month as expected

def active(t,month):
    return month >= (t.get('leaseStart','')[:7] or t.get('trackingStart',month)) and (not t.get('leaseEnd') or month <= t['leaseEnd'][:7])

def rent_at(t,month):
    applicable=[r for r in t.get('rentHistory',[]) if r['month']<=month]
    return max(applicable,key=lambda r:r['month'])['amount'] if applicable else 0


def monthly_workbook(raw, month, manager):
    if not valid_month(month):
        raise ValueError('Choisissez un mois valide.')
    data=normalize_data(raw)
    props={p['id']:p for p in data['properties']}
    tenants={t['id']:t for t in data['tenants']}
    attributed=[p for p in data['payments'] if p['month']==month]
    received=[p for p in data['payments'] if p['date'].startswith(month)]
    costs=[e for e in data['expenses'] if e['date'].startswith(month)]
    paid=lambda tid:sum(p['amount'] for p in attributed if p['tenant']==tid)
    due=lambda t:max(0,expected(t,month)-paid(t['id']))
    billed=[t for t in data['tenants'] if active(t,month) or paid(t['id'])]
    stream=io.BytesIO()
    wb=xlsxwriter.Workbook(stream,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
    wb.set_properties({'title':'immoGui - Bilan locatif '+month,'author':manager,'comments':'Export des données du compte connecté. Montants en GNF.'})
    formats={
      'title':wb.add_format({'font_name':'Calibri','font_size':22,'bold':True,'font_color':'#A6503C'}),
      'meta':wb.add_format({'font_color':'#6E6256','font_size':11,'text_wrap':True,'valign':'top'}),
      'head':wb.add_format({'bg_color':'#A6503C','font_color':'#FFFFFF','bold':True,'text_wrap':True,'valign':'vcenter','border':0}),
      'text':wb.add_format({'font_size':11,'valign':'top','text_wrap':True}),
      'amount':wb.add_format({'num_format':'#,##0 "GNF";[Red](#,##0) "GNF";0 "GNF"','valign':'top'}),
      'number':wb.add_format({'num_format':'0','valign':'top'}),
      'date':wb.add_format({'num_format':'dd/mm/yyyy','valign':'top'}),
      'total':wb.add_format({'bold':True,'bg_color':'#F2E5D9','num_format':'#,##0 "GNF";[Red](#,##0) "GNF";0 "GNF"','top':1,'top_color':'#D9C5B2'}),
      'label':wb.add_format({'bold':True,'bg_color':'#F2E5D9','text_wrap':True}),
      'bad':wb.add_format({'font_color':'#963E2E','bg_color':'#FBECE7'}),
    }
    totals={}
    def sheet(name,title,headers,rows,numeric=(),dates=(),money=(),note='',totals_enabled=True):
        ws=wb.add_worksheet(name);ws.hide_gridlines(2);ws.set_tab_color('#A6503C');ws.set_landscape();ws.fit_to_pages(1,0);ws.repeat_rows(5);ws.set_margins(.3,.3,.4,.4)
        last=len(headers)-1
        ws.merge_range(0,0,0,max(1,last),title,formats['title']);ws.set_row(0,34)
        ws.merge_range(1,0,1,max(1,last),'Partenaire : '+manager+' · Mois : '+month,formats['meta']);ws.set_row(1,30)
        ws.merge_range(2,0,3,max(1,last),note or 'Source : données enregistrées sur immoGui. Exporté le '+dt.datetime.now(dt.timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')+'.',formats['meta'])
        ws.set_row(5,34);ws.write_row(5,0,headers,formats['head']);ws.freeze_panes(6,0)
        for col,header in enumerate(headers):ws.set_column(col,col,19 if col in numeric else 28)
        for i,row in enumerate(rows,6):
            ws.set_row(i,32)
            for col,value in enumerate(row):
                if col in dates and value:
                    ws.write_datetime(i,col,dt.datetime.strptime(value,'%Y-%m-%d'),formats['date'])
                elif col in numeric:
                    ws.write_number(i,col,value,formats['amount'] if col in money else formats['number'])
                else:ws.write_string(i,col,str(value or ''),formats['text'])
        if rows:ws.autofilter(5,0,5+len(rows),last)
        totalrow=6+len(rows)
        if totals_enabled:ws.write(totalrow,0,'TOTAL',formats['label'])
        for col in money if totals_enabled else ():
            letter=xlsxwriter.utility.xl_col_to_name(col)
            formula=f'=SUM({letter}7:{letter}{6+len(rows)})' if rows else '=0'
            value=sum(row[col] for row in rows)
            ws.write_formula(totalrow,col,formula,formats['total'],value)
            totals[(name,col)]=(f"'{name}'!{letter}{totalrow+1}",value)
        ws.print_area(0,0,totalrow,last)
        return ws
    summary=wb.add_worksheet('Synthese');summary.hide_gridlines(2);summary.set_tab_color('#A6503C');summary.set_column('A:A',49);summary.set_column('B:B',26);summary.set_column('C:C',65)
    summary.merge_range('A1:C1','immoGui · Bilan locatif mensuel',formats['title']);summary.set_row(0,38)
    summary.merge_range('A2:C2','Partenaire : '+manager+' · Mois : '+month,formats['meta'])
    summary.merge_range('A3:C3','Export du '+dt.datetime.now(dt.timezone.utc).strftime('%d/%m/%Y à %H:%M UTC'),formats['meta'])
    summary.write_row('A5',['INDICATEUR','MONTANT / NOMBRE','LECTURE'],formats['head']);summary.set_row(4,32)
    rentalrows=[]
    for t in billed:
        expected_amount=expected(t,month);collected=paid(t['id']);remaining=due(t)
        status='Hors bail' if not active(t,month) else 'Partiel' if remaining and collected else 'À recevoir' if remaining else 'Réglé'
        rentalrows.append([t['name'],t.get('phone',''),props[t['property']]['name'],t.get('rentalType',''),t.get('unit',''),expected_amount,collected,remaining,max(0,collected-expected_amount),status])
    ws=sheet('Loyers','Loyers du mois de '+month,['Locataire','Téléphone','Bien','Type loué','Logement / local','Loyer attendu','Affecté au mois','Reste à recevoir','Excédent affecté','Situation'],rentalrows,numeric=(5,6,7,8),money=(5,6,7,8),note='Paiements rattachés au MOIS DE LOYER sélectionné, quelle que soit la date du versement. Mois commencés dus en entier, sans prorata. Les dates d’entrée inconnues utilisent le début de suivi connu.')
    if rentalrows:ws.conditional_format(6,7,5+len(rentalrows),7,{'type':'cell','criteria':'>','value':0,'format':formats['bad']})
    receiptrows=[]
    for p in sorted(received,key=lambda p:p['date']):
        t=tenants[p['tenant']];snap=p.get('receipt',{})
        receiptrows.append([p['date'],snap.get('tenant',t['name']),snap.get('property',props[t['property']]['name']),p['month'],p['amount'],p['id']])
    sheet('Encaissements','Encaissements reçus pendant '+month,['Date du versement','Locataire','Bien','Mois de loyer concerné','Montant reçu','Référence paiement'],receiptrows,numeric=(4,),money=(4,),dates=(0,),note='Flux de trésorerie : versements dont la DATE est dans le mois sélectionné, y compris les loyers d’un autre mois.')
    costrows=[[e['date'],props[e['property']]['name'],e['category'],e['label'],e['amount']] for e in sorted(costs,key=lambda e:e['date'])]
    sheet('Depenses','Dépenses du mois de '+month,['Date','Bien','Catégorie','Libellé','Montant'],costrows,numeric=(4,),money=(4,),dates=(0,))
    propertyrows=[]
    for p in data['properties']:
        ids={t['id'] for t in data['tenants'] if t['property']==p['id']};occupied=sum(active(t,month) for t in data['tenants'] if t['property']==p['id'])
        income=sum(v['amount'] for v in received if v.get('receipt',{}).get('propertyId',tenants[v['tenant']]['property'])==p['id'])
        out=sum(v['amount'] for v in costs if v['property']==p['id'])
        propertyrows.append([p['name'],p['address'],p['type'],p['units'],occupied,max(0,p['units']-occupied),income,out,income-out])
    sheet('Biens','Situation des biens pour '+month,['Bien','Adresse','Composition / type','Capacité','Occupés','Disponibles','Encaissements reçus','Dépenses','Solde de trésorerie'],propertyrows,numeric=(3,4,5,6,7,8),money=(6,7,8),note='Occupation calculée sur les baux du mois sélectionné. Les finances sont fondées sur les dates de versement et de dépense. Les cautions ne sont pas incluses dans les recettes.')
    tenantrows=[[t['name'],t.get('phone',''),props[t['property']]['name'],t.get('rentalType',''),t.get('unit',''),t.get('leaseStart',''),t.get('leaseEnd',''),t['trackingStart'],t['dueDay'],t['deposit'],rent_at(t,month),'Actif sur le mois' if active(t,month) else 'Hors bail'] for t in data['tenants']]
    sheet('Locataires','Locataires et baux',['Nom','Téléphone','Bien','Type','Logement / local','Début du bail','Fin du bail','Début de suivi connu','Jour échéance','Caution prévue','Tarif du mois','Situation'],tenantrows,numeric=(8,9,10),money=(9,10),dates=(5,6),note='Les dates d’entrée laissées vides ne sont pas inventées. La caution prévue est une condition du bail, pas une preuve d’encaissement.')
    historyrows=[[t['name'],props[t['property']]['name'],h['month'],h['amount']] for t in data['tenants'] for h in sorted(t['rentHistory'],key=lambda h:h['month'])]
    sheet('Tarifs','Historique des tarifs',['Locataire','Bien','Mois de prise d’effet','Loyer mensuel'],historyrows,numeric=(3,),money=(3,),totals_enabled=False,note='Tous les tarifs connus, y compris les tarifs futurs. Un changement de montant ne modifie pas le tarif des mois précédents.')
    billed_total=sum(expected(t,month) for t in billed)
    remaining=sum(due(t) for t in billed)
    entries=[
      ('Loyers attendus pour le mois',('Loyers',5),'Selon les baux et les tarifs applicables au mois.'),
      ('Paiements affectés au mois de loyer',('Loyers',6),'Peuvent avoir été reçus à une autre date.'),
      ('Reste à recevoir sur ce mois',('Loyers',7),'Somme des soldes positifs des locataires, pas des impayés de tous les mois.'),
      ('Excédents affectés au mois',('Loyers',8),'Présentés séparément des montants à recevoir.'),
      ('Encaissements reçus dans le mois',('Encaissements',4),'Versements dont la date se situe dans le mois.'),
      ('Dépenses payées dans le mois',('Depenses',4),'Selon la date des dépenses enregistrées.'),
    ]
    for i,(label,key,note) in enumerate(entries,5):
        ref,value=totals[key];summary.write(i,0,label,formats['text']);summary.write_formula(i,1,'='+ref,formats['amount'],value);summary.write(i,2,note,formats['meta']);summary.set_row(i,34)
    income=totals[('Encaissements',4)][1];out=totals[('Depenses',4)][1]
    summary.write(11,0,'Solde de trésorerie du mois',formats['label']);summary.write_formula(11,1,'=B10-B11',formats['total'],income-out);summary.write(11,2,'Encaissements reçus moins dépenses du mois.',formats['meta']);summary.set_row(11,34)
    for row,label,value in [(13,'Biens enregistrés',len(data['properties'])),(14,'Unités locatives au total',sum(p['units'] for p in data['properties'])),(15,'Baux actifs sur le mois',sum(active(t,month) for t in data['tenants'])),(16,'Locataires avec un reste dû',sum(due(t)>0 for t in billed))]:summary.write(row,0,label,formats['text']);summary.write_number(row,1,value,formats['number']);summary.set_row(row,26)
    summary.merge_range('A20:C21','IMPORTANT : les cautions ne sont pas des loyers. Ce classeur présente les données saisies à la date d’export ; il ne remplace pas les justificatifs ni une comptabilité complète.',formats['meta'])
    summary.merge_range('A23:C24','Lecture : Synthese = indicateurs ; Loyers = situation par mois de loyer ; Encaissements = argent reçu par date ; Depenses = charges ; Biens et Locataires = parc et baux ; Tarifs = historique.',formats['meta'])
    summary.freeze_panes(5,0);summary.set_landscape();summary.fit_to_pages(1,1);summary.print_area('A1:C24')
    wb.close()
    return stream.getvalue()
