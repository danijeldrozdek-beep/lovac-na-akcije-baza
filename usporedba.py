"""Conservative unit normalization; ambiguous offers stay out of ranking."""
import csv, json, re, zipfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from pretraga import ROOT, parse, match, norm

def dec(value):
    try: return Decimal(str(value).replace(',', '.')) if value is not None and str(value).strip() else None
    except Exception: return None

def money(value):
    return float(value.quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)) if value is not None else None

SIZE = re.compile(r'(?<![\d.,])(?:(\d+)\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*(kg|ml|lt|l|g)\b', re.I)
def size(text):
    sizes=[]
    for m in SIZE.finditer(text.lower()):
        count=Decimal(m[1] or '1'); amount=Decimal(m[2].replace(',','.')); u=m[3].lower()
        base='l' if u in ('ml','l','lt') else 'kg'
        quantity=count*amount/(1000 if u in ('ml','g') else 1)
        if quantity>0:sizes.append((quantity,base))
    distinct=list(dict.fromkeys(sizes))
    return distinct[0] if len(distinct)==1 else None

def normalize(row, category):
    r=dict(row); name=row['name']; n=norm(name); unit=row['unit'].strip().lower()
    expected='l' if category=='mlijeko' else 'kg'
    p=dec(row['price']); special=dec(row.get('special_price'))
    source=dec(row.get('source_unit_price'))
    if row['chain']=='Eurospin' and special and special>0:source=dec(row.get('special_unit_price'))
    uncertain=''; qty=None; mode='pakiranje'; basis=''; per=None
    if p is None or p<=0:uncertain='Cijena nije valjana.'
    elif re.search(r'\b(ca|cca|oko)\b', n+' '+norm(unit)):
        uncertain='Približna težina: nije potvrđeno odnosi li se cijena na kg ili na pakiranje.'
    elif unit in ('kg','g','l','lt','ml'):
        base='l' if unit in ('l','lt','ml') else 'kg'
        if base!=expected:uncertain='Jedinica nije usporediva s ovom vrstom proizvoda.'
        else:
            raw_quantity=row.get('quantity','')
            declared=size(raw_quantity)
            qty=declared[0] if declared and declared[1]==base else dec(raw_quantity)
            if qty is not None and qty>0:
                if not declared:qty=qty/(1000 if unit in ('g','ml') else 1)
                per=p/qty;basis='Neto količina iz cjenika'
            elif row['chain'] in ('Plodine','Studenac') and unit=='kg':
                mode='vaganje';per=p;basis='Prodajna jedinica KG u cjeniku'
            else:uncertain='Nedostaje neto količina.'
    else:
        found=size(unit) if row['chain']=='Lidl' else size(name) or size(row.get('quantity',''))
        if found and found[1]==expected:
            qty=found[0];per=p/qty;basis='Količina iz oznake jedinice' if row['chain']=='Lidl' else 'Količina iz naziva proizvoda'
        else:uncertain='Nije jednoznačno navedena količina u litrama ili kilogramima.'
    if per is not None and source and source>0 and abs(per-source)>max(Decimal('.03'),per*Decimal('.01')):
        # Do not silently reinterpret mismatched prices, density-based net amounts or multipacks.
        uncertain='Izračun i objavljena cijena po jedinici se razlikuju.';per=None
    if uncertain:per=None
    r.update(category=category,compare_unit=expected,normalized_price=money(per),pack_quantity=money(qty),
             sale_mode=mode,normalization_note=uncertain or basis,promotion_status='Akcija prema cjeniku' if (special and special>0) or norm(row.get('promotion_flag',''))=='da' else 'Posebni uvjeti nisu navedeni',
             available_status='nedostupno' if norm(row['available'])=='nedostupno' else 'dostupno' if norm(row['available'])=='dostupno' else 'nepoznato')
    r['species']='pileće' if re.search(r'\b(pile\w*|pil\b|pilet\w*)',n) else 'pureće' if re.search(r'\b(pur\w*|pure\w*)',n) else 'pačje' if re.search(r'\bpac\w*',n) else 'nepoznato'
    r['bone']='bez kosti' if re.search(r'\b(bez kost\w*|bk|bkk|b k|otk\w*|iskost\w*|otkost\w*|file\w*)\b',n) else 's kosti' if re.search(r'\b(s kost\w*|sk|skk|s k)\b',n) else 'nepoznato'
    r['milk_type']='trajno' if re.search(r'\b(trajn\w*|uht)\b',n) else 'svježe' if re.search(r'\b(svjez\w*|svj|esl|sv)\b',n) else 'nepoznato'
    fat=re.search(r'(\d+[.,]\d+)\s*%|(?<!\d)([0-9][.,][0-9])\s*(?:mm|m\.m)',name,re.I)
    r['fat']=(fat[1] or fat[2]).replace(',','.') if fat else 'nepoznato'
    r['lactose']='bez laktoze' if re.search(r'\b(bez lakt\w*|lactose free|lakt)\b',n) else 'nije navedeno'
    r['preparation']='marinirano' if re.search(r'\b(marin\w*|chili|chilly|mediter\w*)',n) else 'nije navedeno'
    r['frozen']='smrznuto' if re.search(r'\b(smrzn\w*|rfz)\b',n) else 'nije navedeno'
    return r

def store_info(chain,filename):
    if chain=='Plodine':
        m=re.match(r'(?:SUPER|HIPER)MARKET_(.+?)_(52\d{3}|51470)_(.+?)_\d+_\d+_\d+\.csv',filename,re.I)
        if m:return m[3].replace('_',' ').title(),m[1].replace('_',' ').title()
    if chain=='Eurospin':
        m=re.match(r'.+?-\d+-(.+?)-(.+?)-(52\d{3})-',filename,re.I)
        if m:return m[2].title(),m[1].replace('_',' ')
    return 'Pula',filename

def build(manifest=None, output=None):
    folder=ROOT/'istrazivanje'; offers=[];count=0;stores=[]
    registry=list(csv.DictReader((ROOT/'CJENICI-ISTRA-2026-10-10.csv').open(encoding='utf-8-sig'),delimiter=';'))
    urls={(r['Trgovac'],r['Datoteka']):r['Izvor'] for r in registry}
    def consume(chain,filename,blob,url,city=None,address=None,date='2026-10-10'):
        nonlocal count
        city0,address0=store_info(chain,filename);city=city or city0;address=address or address0
        stores.append(dict(chain=chain,city=city,address=address,date=date))
        for row in parse(chain,filename,blob,url):
            count+=1
            row['date']=date
            for category in ('mlijeko','batak','vratina','svinjetina'):
                kind=match(category,row['name'])
                if not kind:continue
                r=normalize(row,category);r.update(group='osnovno' if kind==1 else 'povezano',city=city,address=address)
                offers.append(r)
    if manifest is None and (ROOT/'cjenici-stanje.json').exists():
        manifest=json.loads((ROOT/'cjenici-stanje.json').read_text(encoding='utf-8'))
    live=(manifest or {}).get('chains',{})
    for chain,filename,pattern,fallback in [('Plodine','plodine.zip',r'_52\d{3}_|_UMAG_','https://www.plodine.hr/info-o-cijenama'),('Eurospin','eurospin.zip',r'Pula|Pore|Labin|Pazin|52\d{3}','https://www.eurospin.hr/cjenik/')]:
        if chain in live:continue
        with zipfile.ZipFile(folder/filename) as z:
            for entry in z.namelist():
                if re.search(pattern,entry):consume(chain,entry,z.read(entry),urls.get((chain,entry),fallback))
    if 'Lidl' not in live:consume('Lidl','Pula, Labinska ulica 2A',(folder/'lidl-uzorak.csv').read_bytes(),'https://www.lidl.hr/c/cijene/s10073252','Pula','Labinska ulica 2A')
    if 'SPAR / INTERSPAR' not in live:consume('SPAR / INTERSPAR','Pula, Rimske centurijacije 101',(folder/'spar-uzorak.csv').read_bytes(),'https://www.spar.hr/usluge/cjenici','Pula','Rimske centurijacije 101')
    for chain,info in live.items():
        for entry in info['files']:
            consume(chain,entry['name'],(ROOT/entry['path']).read_bytes(),entry['source'],entry.get('city'),entry.get('address'),info['date'])
    # Keep each location, but collapse genuinely identical rows within that location.
    dedup={}
    for r in offers:
        key=(r['category'],r['chain'],r['location'],r['barcode'],r['name'],r['price'],r['available'])
        dedup[key]=r
    from collections import Counter
    counts=Counter(r['chain'] for r in stores)
    dates=sorted(set(r['date'] for r in stores))
    result=dict(date=dates[-1],date_min=dates[0],rows_read=count,stores=stores,offers=list(dedup.values()),
                coverage=f'{len(stores)} poslovnica • '+', '.join(f'{k} {v}' for k,v in counts.items()),
                source_status=(manifest or {}).get('status',[]),
                conditions='Cjenici ne potvrđuju zalihu. Kuponi i članske cijene nisu zasebno provjereni. Datum je datum spremljenog cjenika.')
    if output is not False:
        (output or ROOT/'usporedba-podaci.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'rows_read':count,'stores':len(stores),'offers':len(dedup),'rankable':sum(r['normalized_price'] is not None for r in dedup.values())},ensure_ascii=False))

    return result

if __name__=='__main__':build()
