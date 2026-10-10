"""Prototip hrvatske pretrage nad spremljenim službenim cjenicima (stdlib)."""
import argparse, csv, difflib, io, json, re, unicodedata, zipfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent

@lru_cache(maxsize=100000)
def norm(text):
    text = text.lower().replace('đ', 'd')
    return re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))).strip()

CONCEPTS = {
    'mlijeko': (r'\b(mlijeko|mlijeka|mlijeku|mlijek|mleko|mleka)\b', ['mlijeko', 'mljeko', 'mleko']),
    'batak': (r'\b(batak\w*|batk\w*)', ['batak', 'bataci', 'batki', 'batci']),
    'vratina': (r'\bvratin\w*|\bsvinj\w*\s+vrat\b|\bsv\s+vrat\b|\bvrat\s+svinj\w*', ['vratina', 'svinjski vrat']),
    'svinjetina': (r'\b(svinj\w*|svinjsk\w*|sv\s+(but|vrat|lopat|kotlet)|pork)\b', ['svinjetina', 'svinjsko', 'svinjsko meso']),
    'jaja': (r'\b(jaj[aeo]|jajima|jaja)\b', ['jaja', 'jaje']),
    'kava': (r'\b(kav[aeu]|coffee)\b', ['kava', 'kafa']),
    'krumpir': (r'\b(krumpir\w*|krompir\w*)\b', ['krumpir', 'krompir']),
    'secer': (r'\b(secer|secera)\b', ['secer']),
    'ulje': (r'\bulj[aeu]\b', ['ulje']),
}
PET = r'\b(pas|pse|psa|psi|pseca|mack\w*|ljubim\w*|whiskas|pedigree|gourmet|felix|purina|friskies)\b'
BODY = r'\b(tijel\w*|losion\w*|sun can\w*|sunc\w*|ciscenj\w*|njeg\w*|kupk\w*|krema\w*|kozu|koze)\b'
PREPARED = r'\b(suh\w*|dimljen\w*|sus(en|ena|eni)\w*|salama\w*|kobasic\w*|pastet\w*|narez\w*|prsut\w*|mortadel\w*|hamburger\w*|cevap\w*|gotov\w*|gulas\w*|rag[uoa]\w*|mesni\s+dorucak|narezak\w*|delikates\w*|pecen\w*|pulled|kuhan\w*|dinstan\w*|hrenov\w*|hase|paprikas\w*|gyros|mast|crijev\w*|stapic\w*)\b'

@lru_cache(maxsize=200)
def intent(query):
    q = norm(query)
    for key, (_, aliases) in CONCEPTS.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if re.search(r'\b' + re.escape(alias) + r'\b', q):
                return key, re.sub(r'\b' + re.escape(alias) + r'\b', '', q).strip(), False
    first = q.split()[0] if q else ''
    near = difflib.get_close_matches(first, CONCEPTS, n=1, cutoff=.8)
    if near:
        return near[0], ' '.join(q.split()[1:]), True
    return None, q, False

def match(query, name):
    key, rest, _ = intent(query)
    n = norm(name)
    if not key:
        return 1 if all(t in n for t in rest.split()) and rest else 0
    if not re.search(CONCEPTS[key][0], n) or re.search(PET, n): return 0
    if re.search(r'\b(lego|igrack\w*|hambone|boos|drzac\w*|posuda\w*|preslik\w*|folija|samp\w*|bec utan|becutan|afrodit\w*|nivea|palmolive|pronto|beckmann|sapun\w*|uskr\w*|porcul\w*)\b', n): return 0
    if key in ('mlijeko', 'ulje') and re.search(BODY, n): return 0
    # Broad category search: related prepared products stay in a separate section.
    secondary = False
    if key == 'mlijeko':
        if re.search(r'\b(dove|ziaja|medihelp|milka|alpia|gel|mask\w*|regener\w*|jogurt\w*|kefir\w*|mozzarell\w*|cok|dorina)\b', n): return 0
        if re.search(r'\b(spf\s*\d*|f\s*\d+|sun|solaire|olival|garnier|ambre|afro|afr|lice|lic[aeu]|pjenilic\w*|sisac\w*|vrc|loncic\w*|pralin\w*|croissant|tortina|vafel\w*|kakao|keramick\w*|set)\b', n): return 0
        if re.search(r'\b(cokolad\w*|coko\w*|keks\w*|bombon\w*|karamel\w*|kas\w*|puding\w*|sladoled\w*|biskvit\w*|namaz\w*|desert\w*|sir\w*|vrhnj\w*|kav\w*|riz[aeu]|napolit\w*|tij|kosa)\b', n): return 0
        secondary = bool(re.search(r'\b(kokos\w*|badem\w*|soj\w*|zob\w*|riz\w*|kondenz\w*|prah\w*|dojenc\w*|formula\w*|hipp\w*|apta\w*|apt\b|nan\w*|novalac\w*|bebim\w*|zam\w*|djecj\w*|acid\w*|kisel\w*)\b', n))
    if key in ('batak', 'vratina', 'svinjetina'):
        secondary = bool(re.search(PREPARED, n) or re.search(r'\b(sendvic\w*|gyoza|porcija|paniran\w*|varivo|cheeseburger|kobas\w*|sunka\w*)\b', n))
        if re.search(r'\b(juh\w*|temeljac\w*|zacin\w*|vegeta|cips\w*|hrsk\w*)\b', n): return 0
    if key == 'jaja' and (not re.search(r'^(bio |svjez\w* |domac\w* |svjez\w* bio )?jaj[ae]\b', n) or re.search(r'\b(cokolad\w*|coko\w*|kinder|tjesten\w*|rezanc\w*|majonez\w*|salat\w*|keks\w*)\b', n)): return 0
    if key == 'kava':
        if re.search(r'\b(salic\w*|aparat\w*|keks\w*|cokolad\w*|bombon\w*|sladoled\w*|vrhnj\w*)\b', n): return 0
        secondary = bool(re.search(r'\b(leden\w*|napit\w*)\b', n))
    if key == 'ulje':
        if re.search(r'\b(tuna|skusa|sardin\w*|kikirik\w*|sir|namjest\w*|koz\w*|baby|shell|helix|castrol|wd\s*40|masaz\w*)\b', n): return 0
        secondary = bool(re.search(r'\b(motorn\w*|motor\w*|eteric\w*|miris\w*|maziv\w*)\b', n))
    if key == 'secer':
        if not re.search(r'^(bijeli |smedi |smedji |bio |vanilin |vanilija |mljeveni |kristal )?secer\b', n): return 0
        secondary = bool(re.search(r'\bvanil\w*', n))
    if key == 'krumpir':
        if re.search(r'\b(bombon\w*|haribo|tjesten\w*|gulas\w*|pita|kobasic\w*|lignj\w*|orada|medaljon\w*|cordon|valjusc\w*)\b', n): return 0
        secondary = bool(re.search(r'\b(kroket\w*|pekar\w*|zacin\w*|pommes|pomfrit\w*|smrzn\w*|cips\w*)\b', n))
    if rest:
        for token in rest.split():
            if token in ('pileci', 'pileca', 'piletina'):
                if not re.search(r'\b(pile\w*|pilet\w*)', n): return 0
            elif token in ('svinjski', 'svinjska'):
                if not re.search(r'\bsvinj\w*', n): return 0
            elif token not in n: return 0
    return 2 if secondary else 1

def decode(blob):
    for enc in ('utf-8-sig', 'cp1250', 'iso8859-2'):
        try: return blob.decode(enc)
        except UnicodeDecodeError: pass
    raise ValueError('Nepoznato kodiranje')

def number(value):
    try: return float(value.replace(',', '.').strip())
    except (ValueError, AttributeError): return None

def toilet_paper(name):
    text=norm(name)
    if re.search(r'\b(kuhinj\w*|ubrusi)\b',text):return False
    return bool(re.search(r'^(tp|t p|t pap)\b',text) or
                (re.search(r'\b(toalet\w*|toal|wc)\b',text) and re.search(r'\bpap\w*',text)))

def parse(chain, location, blob, source):
    text = decode(blob)
    delimiter = max((';',',','\t'),key=text.splitlines()[0].count)
    for raw in csv.DictReader(io.StringIO(text), delimiter=delimiter):
        r = {norm(k): (v or '').strip() for k, v in raw.items() if k}
        def get(*keys): return next((r[norm(k)] for k in keys if r.get(norm(k))), '')
        name = get('naziv', 'naziv proizvoda','NAZIV_ARTIKLA')
        if not name: continue
        regular = number(get('MPC', 'MPC EUR', 'maloprodajna cijena', 'maloprod cijena eur'))
        special = number(get('MPC za vrijeme posebnog oblika prodaje', 'MPC za vrijeme posebnog oblika prodaje EUR', 'MPC poseb oblik prod','MPC_POSEBNA_PRODAJA'))
        price = special if special and special > 0 else regular
        if price is None: continue
        unitprice = number(get('cijena po JM', 'cijena za jedinicu mjere', 'cijena za jedinicu mjere EUR','cijena jed.mj.(EUR)'))
        unit = get('jedinica mjere')
        quantity = get('neto kolicina')
        # Kaufland declares net weight even for liquids; use this only for KG sales.
        if chain=='Kaufland' and norm(unit)=='kg':quantity=get('neto količina(KG)')
        # Lidl embeds quantity in its unit string. Plodine KOM does not identify kg/l basis.
        base = 'kg' if re.search(r'\bkg\b', norm(unit)) else 'l' if re.search(r'\bl\b', norm(unit)) else None
        if chain == 'Eurospin' and special and special > 0:
            unitprice = number(get('poseb oblik prod za jedinicu mjere')) or None
        if chain in ('Lidl', 'SPAR / INTERSPAR') and special and special > 0:
            qty = number(quantity)
            if qty and base: unitprice = price / qty
        available = get('dostupno nedostupno','dostupan nedostupan')
        yield dict(chain=chain, location=location, name=name, brand=get('marka', 'marka proizvoda','BRAND'), price=price,
                   unit_price=unitprice, base=base, unit=unit, quantity=quantity, available=available or 'nepoznato',
                   source=source, date='2026-10-10', barcode=get('barkod','BARKOD_ARTIKLA'),
                   regular_price=regular, special_price=special,
                   source_unit_price=number(get('cijena po JM', 'cijena za jedinicu mjere', 'cijena za jedinicu mjere EUR','cijena jed.mj.(EUR)')),
                   special_unit_price=number(get('poseb oblik prod za jedinicu mjere')),
                   promotion=get('naziv posebnog oblika prodaje'), promotion_flag=get('poseban oblik prodaje'))

def load():
    folder = ROOT / 'istrazivanje'
    archives = [('Plodine','plodine.zip',r'_52\d{3}_|_UMAG_', 'https://www.plodine.hr/info-o-cijenama'),
                ('Eurospin','eurospin.zip',r'Pula|Pore|Labin|Pazin|52\d{3}', 'https://www.eurospin.hr/cjenik/')]
    rows=[]; stores=[]
    for chain, filename, pattern, url in archives:
        with zipfile.ZipFile(folder / filename) as z:
            for entry in z.namelist():
                if re.search(pattern, entry):
                    stores.append((chain,entry)); rows.extend(parse(chain, entry, z.read(entry), url))
    for chain, filename, location, url in [
        ('Lidl','lidl-uzorak.csv','Pula, Labinska ulica 2A','https://www.lidl.hr/c/cijene/s10073252'),
        ('SPAR / INTERSPAR','spar-uzorak.csv','Pula, Rimske centurijacije 101','https://www.spar.hr/usluge/cjenici')]:
        stores.append((chain,location));rows.extend(parse(chain,location,(folder/filename).read_bytes(),url))
    return rows,stores

def search(rows,query):
    result=[]
    for row in rows:
        kind=match(query,row['name'])
        if kind: result.append({**row,'group':'povezano' if kind==2 else 'osnovno'})
    return result

def unique(results):
    grouped={}
    for row in results:
        key=(row['chain'],row['name'],row['price'],row['unit_price'],row['base'],row['available'],row['group'])
        if key not in grouped: grouped[key]={**row,'locations':[]}
        grouped[key]['locations'].append(row['location'])
    return list(grouped.values())

def report(rows,stores):
    queries=['mlijeko','mljeko','batak','pileći batak','vratina','svinjetina','jaja','kava','krumpir','šećer','ulje']
    output=['# Pokus svakodnevne pretrage','', 'Izvorni cjenici: 10.10.2026. Pretraženo '+str(len(rows))+' redaka iz '+str(len(stores))+' poslovnica: Plodine 22, Eurospin 5, Lidl Pula 1 i INTERSPAR Pula 1. Ovo nije usporedba svih trgovaca u Istri.', '',
            'Ovo je prototip s rječnikom svakodnevnih naziva, oblicima riječi i odvojenim povezanim proizvodima. Nije opće razumijevanje hrvatskog jezika. Cijena i zaliha nisu provjerene na blagajni.', '',
            'Tablice su primjeri prepoznavanja, ne rang najjeftinijih proizvoda. Cjenici različito označavaju pakiranje i jedinicu; Plodine često imaju KOM pa cijena po kg/l nije sigurna bez dodatnog čitanja naziva. Stavke označene NEDOSTUPNO ostaju u pretrazi radi provjere prepoznavanja, ali nisu preporuka za kupnju.', '']
    payload={}
    for query in queries:
        found=unique(search(rows,query));payload[query]=found
        basic=[r for r in found if r['group']=='osnovno'];secondary=[r for r in found if r['group']=='povezano']
        output += ['## '+query,'',f'Različite ponude: {len(basic)} osnovnih, {len(secondary)} povezanih (duplikati istog naziva i cijene unutar lanca spojeni).','', '| Trgovac | Izvorni naziv | Cijena iz cjenika | Jedinica / količina | Dostupnost |', '|---|---|---:|---|---|']
        # Diversify across chains; inspect real original names instead of assuming semantic success.
        examples=[]
        for chain in sorted(set(r['chain'] for r in basic)):
            examples.extend([r for r in basic if r['chain']==chain][:4])
        for r in examples:
            output.append(f"| {r['chain']} | {r['name'].replace('|','/')} | {r['price']:.2f} € | {r['quantity']} {r['unit']} | {r['available']} |")
        if secondary: output += ['', 'Primjeri odvojenih povezanih proizvoda: '+ '; '.join(r['name'] for r in secondary[:6])+'.']
        output += ['']
    output += ['## Izvori','', '[Plodine](https://www.plodine.hr/info-o-cijenama), [Eurospin](https://www.eurospin.hr/cjenik/), [Lidl](https://www.lidl.hr/c/cijene/s10073252), [SPAR](https://www.spar.hr/usluge/cjenici).','',
               'Ponovi: `python pretraga.py --report`. Pojedinačno: `python pretraga.py "pileći batak"`.']
    (ROOT/'POKUS-PRETRAGE.md').write_text('\n'.join(output),encoding='utf-8')
    (ROOT/'REZULTATI-PRETRAGE.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({q:{'osnovno':sum(r['group']=='osnovno' for r in rs),'povezano':sum(r['group']=='povezano' for r in rs)} for q,rs in payload.items()},ensure_ascii=False))

if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    ap=argparse.ArgumentParser();ap.add_argument('query',nargs='?',default='mlijeko');ap.add_argument('--report',action='store_true');args=ap.parse_args()
    rows,stores=load()
    if args.report: report(rows,stores)
    else:
        results=unique(search(rows,args.query))
        print(json.dumps({'query':args.query,'interpretation':intent(args.query),'rows':len(rows),'stores':len(stores),'results':results},ensure_ascii=False,indent=2))
