"""Règles de gestion partagées par les sauvegardes et les reçus."""
from copy import deepcopy
from datetime import date, datetime, timezone
import re
import textwrap

COLLECTIONS = ('properties', 'tenants', 'payments', 'expenses')
MAX_AMOUNT = 10**12


def month_valid(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', value)) and value[:4] != '0000'


def date_valid(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def integer(value, minimum=1, maximum=MAX_AMOUNT):
    return type(value) is int and minimum <= value <= maximum


def normalize(data, today=None):
    """Ne pas inventer de date d'entrée ; fixer uniquement le début du suivi."""
    result = deepcopy(data)
    today = today or date.today().isoformat()
    for tenant in result['tenants']:
        if not tenant.get('trackingStart'):
            known = sorted(p['month'] for p in result['payments'] if p.get('tenant') == tenant['id'])
            tenant['trackingStart'] = (tenant.get('leaseStart', '')[:7] or (known[0] if known else today[:7]))
        tenant.setdefault('rentHistory', [{'month': tenant['trackingStart'], 'amount': tenant['rent']}])
        tenant.setdefault('deposit', 0)
        tenant.setdefault('dueDay', 1)
    return result


def rent_for_month(tenant, month):
    if not tenant or month < tenant.get('trackingStart', ''):
        return 0
    if tenant.get('leaseStart', '')[:7] > month or tenant.get('leaseEnd') and tenant['leaseEnd'][:7] < month:
        return 0
    history = tenant.get('rentHistory') or [{'month': '', 'amount': tenant['rent']}]
    eligible = [r for r in history if r['month'] <= month]
    return max(eligible, key=lambda r: r['month'])['amount'] if eligible else 0


def validate_data(data):
    """Valider les fichiers et leurs références avant toute modification du compte."""
    if not isinstance(data, dict) or set(data) != set(COLLECTIONS):
        raise ValueError('Format de données invalide.')
    indexed = {}
    for key in COLLECTIONS:
        if not isinstance(data[key], list) or len(data[key]) > 50000:
            raise ValueError('Collection invalide ou trop volumineuse.')
        indexed[key] = {}
        for item in data[key]:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not 1 <= len(item['id']) <= 150 or item['id'] in indexed[key]:
                raise ValueError('Identifiant manquant ou dupliqué.')
            indexed[key][item['id']] = item
    def text(item, key, limit, required=True):
        value = item.get(key, '')
        if not isinstance(value, str) or len(value) > limit or required and not value.strip():
            raise ValueError('Champ invalide : ' + key)
    for item in data['properties']:
        text(item, 'name', 100)
        text(item, 'address', 200)
        text(item, 'type', 200)
        if not integer(item.get('units'), maximum=10000):
            raise ValueError('Capacité du bien invalide.')
        photo = item.get('photo', '')
        if not isinstance(photo, str) or len(photo) > 350000 or photo and not re.fullmatch(r'data:image/jpeg;base64,[A-Za-z0-9+/=]+', photo):
            raise ValueError('Photo invalide.')
        if 'composition' in item:
            parts = item['composition']
            if not isinstance(parts, list) or not parts or len(parts) > 5 or any(not isinstance(p, dict) or not isinstance(p.get('type'), str) or not integer(p.get('count'), maximum=10000) for p in parts) or sum(p['count'] for p in parts) != item['units']:
                raise ValueError('Composition du bien invalide.')
    for item in data['tenants']:
        text(item, 'name', 100)
        text(item, 'phone', 30, False)
        text(item, 'unit', 60, False)
        text(item, 'rentalType', 60, False)
        if not isinstance(item.get('property'), str) or item['property'] not in indexed['properties'] or not integer(item.get('rent')):
            raise ValueError('Bien ou loyer du locataire invalide.')
        start, end = item.get('leaseStart', ''), item.get('leaseEnd', '')
        if not isinstance(start, str) or not isinstance(end, str) or start and not date_valid(start) or end and not date_valid(end) or start and end and start > end:
            raise ValueError('Dates de bail invalides.')
        if not integer(item.get('deposit', 0), 0) or not integer(item.get('dueDay', 1), 1, 31):
            raise ValueError('Caution ou échéance invalide.')
        if 'trackingStart' in item and not month_valid(item['trackingStart']):
            raise ValueError('Début du suivi invalide.')
        if 'rentHistory' in item:
            history = item['rentHistory']
            if not isinstance(history, list) or not history or len(history) > 1000:
                raise ValueError('Historique des loyers invalide.')
            previous = None
            for rate in history:
                if not isinstance(rate, dict) or not isinstance(rate.get('month'), str) or rate['month'] != '' and not month_valid(rate['month']) or not integer(rate.get('amount')):
                    raise ValueError('Tarif invalide.')
                if previous is not None and rate['month'] <= previous:
                    raise ValueError('Les tarifs doivent suivre un ordre chronologique sans doublon.')
                previous = rate['month']
            if history[-1]['amount'] != item['rent']:
                raise ValueError('Le dernier tarif ne correspond pas au loyer.')
    for key in ('payments', 'expenses'):
        for item in data[key]:
            if not integer(item.get('amount')) or not date_valid(item.get('date')):
                raise ValueError('Montant ou date invalide.')
            if key == 'payments':
                if not isinstance(item.get('tenant'), str) or item['tenant'] not in indexed['tenants'] or not month_valid(item.get('month')):
                    raise ValueError('Locataire ou mois de paiement invalide.')
                if 'receipt' in item:
                    receipt = item['receipt']
                    if not isinstance(receipt, dict) or any(not isinstance(receipt.get(k), str) or len(receipt[k]) > 200 for k in ('reference', 'date', 'month', 'tenant', 'property', 'unit')) or any(not integer(receipt.get(k), 0) for k in ('amount', 'rent', 'remaining')):
                        raise ValueError('Informations de reçu invalides.')
                    if (receipt['reference'], receipt['month'], receipt['date'], receipt['amount']) != (item['id'], item['month'], item['date'], item['amount']):
                        raise ValueError('Le reçu ne correspond pas au paiement.')
            else:
                text(item, 'label', 150)
                text(item, 'category', 60)
                if not isinstance(item.get('property'), str) or item['property'] not in indexed['properties']:
                    raise ValueError('Bien de la dépense invalide.')
    return data


def prepare_update(data, previous):
    """Protéger les paiements et les tarifs connus hors restauration explicite."""
    validate_data(data)
    data = normalize(data)
    old = normalize(previous)
    old_tenants = {t['id']: t for t in old['tenants']}
    new_tenants = {t['id']: t for t in data['tenants']}
    new_payments = {p['id']: p for p in data['payments']}
    old_payments = {p['id']: p for p in old['payments']}
    if [p['id'] for p in data['payments'][:len(old['payments'])]] != [p['id'] for p in old['payments']]:
        raise ValueError('L’ordre des paiements enregistrés doit être conservé.')
    for payment_id, payment in old_payments.items():
        if payment_id not in new_payments or any(new_payments[payment_id].get(k) != payment.get(k) for k in ('tenant', 'month', 'date', 'amount')):
            raise ValueError('Les paiements enregistrés ne peuvent pas être modifiés ou supprimés.')
        if 'receipt' in payment:
            new_payments[payment_id]['receipt'] = deepcopy(payment['receipt'])
        t = new_tenants[payment['tenant']]
        before = rent_for_month(old_tenants[payment['tenant']], payment['month'])
        if rent_for_month(t, payment['month']) != before:
            raise ValueError('Ce bail modifierait un mois avec un paiement enregistré.')
        original = old_tenants[payment['tenant']]
        if (t['property'], t.get('unit', '')) != (original['property'], original.get('unit', '')):
            raise ValueError('Un bail avec paiements ne peut pas changer de logement.')
    for t in data['tenants']:
        original = old_tenants.get(t['id'])
        if original:
            history = original['rentHistory']
            if t['rentHistory'][:len(history)] != history:
                raise ValueError('Les anciens tarifs doivent être conservés.')
            added = t['rentHistory'][len(history):]
            if added and any(p['tenant'] == t['id'] and p['month'] >= added[0]['month'] for p in old['payments']):
                raise ValueError('Un nouveau tarif ne peut pas modifier un mois déjà encaissé.')
    for p in data['payments']:
        if p['id'] in old_payments:
            continue
        total = sum(v['amount'] for v in data['payments'] if v['tenant'] == p['tenant'] and v['month'] == p['month'])
        if total > rent_for_month(new_tenants[p['tenant']], p['month']):
            raise ValueError('Le paiement dépasse le loyer restant dû pour ce mois.')
        p.pop('receipt', None)
        p['receipt'] = receipt_details(data, p['id'])
    return data


def receipt_details(data, payment_id):
    payment = next((p for p in data['payments'] if p['id'] == payment_id), None)
    if payment is None:
        raise KeyError(payment_id)
    if isinstance(payment.get('receipt'), dict):
        return deepcopy(payment['receipt'])
    tenant = next(t for t in data['tenants'] if t['id'] == payment['tenant'])
    prop = next(p for p in data['properties'] if p['id'] == tenant['property'])
    # L'ordre d'enregistrement, et non la date saisie, définit le solde du reçu.
    through = data['payments'][:data['payments'].index(payment) + 1]
    collected = sum(p['amount'] for p in through if p['tenant'] == payment['tenant'] and p['month'] == payment['month'])
    rent = rent_for_month(tenant, payment['month'])
    return {'reference': payment['id'], 'date': payment['date'], 'month': payment['month'],
            'tenant': tenant['name'], 'property': prop['name'], 'unit': tenant.get('unit', ''),
            'amount': payment['amount'], 'rent': rent, 'remaining': max(0, rent - collected)}


def backup_document(data, email):
    return {'format': 'immogui-backup', 'version': 1, 'owner': email,
            'createdAt': datetime.now(timezone.utc).isoformat(), 'data': deepcopy(data)}


def restore_document(document, email):
    if document.get('format') != 'immogui-backup' or document.get('version') != 1 or document.get('owner') != email:
        raise ValueError('Cette sauvegarde ne correspond pas à votre compte ou son format est invalide.')
    return normalize(validate_data(document.get('data')))


def receipt_pdf(receipt, issuer):
    """PDF A4 autonome, sans service externe ni dépendance à installer."""
    money = lambda n: f'{n:,}'.replace(',', ' ') + ' GNF'
    lines = ['immoGui - Reçu de paiement',
             'Paiement partiel' if receipt['remaining'] else 'Solde du mois réglé',
             'Gestionnaire : ' + issuer, 'Référence : ' + receipt['reference'],
             'Date du versement : ' + receipt['date'], 'Locataire : ' + receipt['tenant'],
             'Bien : ' + receipt['property'], 'Logement / local : ' + (receipt['unit'] or 'Non renseigné'),
             'Mois de loyer : ' + receipt['month'], 'Loyer du mois : ' + money(receipt['rent']),
             'Montant de ce versement : ' + money(receipt['amount']),
             'Solde restant après ce versement : ' + money(receipt['remaining']),
             'Ce reçu atteste uniquement le versement indiqué ci-dessus.']
    wrapped = [part for line in lines for part in textwrap.wrap(line, 66)]
    commands = [b'BT /F1 12 Tf 50 790 Td 21 TL']
    for line in wrapped:
        escaped = line.encode('cp1252', 'replace').replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
        commands.append(b'(' + escaped + b') Tj T*')
    commands.append(b'ET')
    stream = b'\n'.join(commands)
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    result = b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    start = len(result)
    result += b'xref\n0 6\n0000000000 65535 f \n'
    result += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return result + b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF\n'
