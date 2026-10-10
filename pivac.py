"""Official catalogue dates and curated offers. Never fetch the blocked Issuu reader."""
import json,re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from trgovci import ISTRIA

PAGE='https://pivac.hr/hr/akcijski-katalozi'

def catalogues(html):
    result=[]
    for block in html.split('<div class="views-row">')[1:]:
        dates=re.findall(r'<time datetime="(\d{4}-\d{2}-\d{2})T[^\"]+">',block)
        if len(dates)!=2:continue
        start,end=map(date.fromisoformat,dates)
        if start>end:raise ValueError('Neispravan rok Pivac kataloga.')
        result.append(dict(valid_from=str(start),valid_until=str(end),source=PAGE))
    if not result:raise ValueError('Nije pronađen rok Pivac kataloga.')
    return result

def verified_offers(path):
    offers=json.loads(Path(path).read_text(encoding='utf-8')).get('offers',[])
    for o in offers:
        if not o['name'].strip() or not 0<float(o['price'])<10000:raise ValueError('Neispravna Pivac cijena.')
        if o['unit'] not in ('kg','l','pakiranje'):raise ValueError('Nedostaje prodajna jedinica Pivac ponude.')
        if date.fromisoformat(o['valid_from'])>date.fromisoformat(o['valid_until']):raise ValueError('Neispravan rok Pivac akcije.')
        if urlsplit(o['source']).hostname not in ('pivac.hr','www.pivac.hr'):raise ValueError('Nedostaje službeni izvor Pivac ponude.')
        if not o.get('locations'):raise ValueError('Pivac akcija nema potvrđene poslovnice.')
        for loc in o['locations']:
            if loc['city'] not in ISTRIA or not loc['address'].strip() or urlsplit(loc['source']).hostname not in ('pivac.hr','www.pivac.hr'):
                raise ValueError('Nije potvrđena istarska Pivac poslovnica.')
    return offers

def refresh(fetch,root):
    return dict(catalogues=catalogues(fetch(PAGE).decode('utf-8')),offers=verified_offers(Path(root)/'pivac-akcije.json'))
