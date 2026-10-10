"""Download official price lists and publish validated, immutable snapshots."""
import copy, hashlib, importlib.util, io, json, os, re, tempfile, time, uuid, zipfile
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from pretraga import ROOT, decode, parse, norm
from usporedba import build
from trgovci import download_files, download_studenac

PAGES={'Plodine':'https://www.plodine.hr/info-o-cijenama',
       'Eurospin':'https://www.eurospin.hr/cjenik/',
       'Lidl':'https://www.lidl.hr/c/cijene/s10073252',
       'SPAR / INTERSPAR':'https://www.spar.hr/usluge/cjenici',
       'Studenac':'https://www.studenac.hr/cjenici/PROIZVODI-{date}.zip',
       'Tommy':'https://www.tommy.hr/objava-cjenika',
       'Konzum':'https://www.konzum.hr/cjenici'}
STATE=ROOT/'cjenici-stanje.json'

def now():return datetime.now().astimezone().isoformat(timespec='seconds')

def atomic_write(path, content):
    path=Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        tmp=Path(f.name);f.write(content.encode('utf-8'));f.flush();os.fsync(f.fileno())
    try:os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def get(url, limit=300*1024*1024,progress=None):
    parts=urlsplit(url)
    if parts.scheme!='https':raise ValueError('Izvor mora koristiti HTTPS.')
    safe=urlunsplit((parts.scheme,parts.netloc,quote(unquote(parts.path),safe='/'),quote(parts.query,safe='=&%+,;/?:'),''))
    req=Request(safe,headers={'User-Agent':'LovacNaAkcije/0.2 (local price comparison)','Accept-Encoding':'identity'})
    with urlopen(req,timeout=60) as response:
        data=bytearray();started=time.monotonic();last=started
        total=response.headers.get('Content-Length')
        while chunk:=response.read(1024*1024):
            data.extend(chunk)
            if len(data)>limit:raise ValueError('Prevelika datoteka izvora.')
            if time.monotonic()-started>900:raise TimeoutError('Preuzimanje traje dulje od 15 minuta.')
            if progress and time.monotonic()-last>3:
                progress(f'Preuzimam cjenik: {len(data)//1048576} MB'+(f' od {int(total)//1048576} MB' if total else '')+'…')
                last=time.monotonic()
    return bytes(data)

def remote_version(url):
    parts=urlsplit(url)
    safe=urlunsplit((parts.scheme,parts.netloc,quote(unquote(parts.path),safe='/'),parts.query,''))
    try:
        with urlopen(Request(safe,method='HEAD'),timeout=30) as r:
            return dict(etag=r.headers.get('ETag'),modified=r.headers.get('Last-Modified'),length=r.headers.get('Content-Length'))
    except (URLError,TimeoutError):
        # HEAD is only an optimization: some official servers forbid it while GET works.
        return None

class Links(HTMLParser):
    def __init__(self):super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        value=a.get('href') if tag=='a' else a.get('value') if tag=='option' else None
        if value:self.urls.append(value)

def links(html,base):
    parser=Links();parser.feed(html)
    return list(dict.fromkeys(urljoin(base,u) for u in parser.urls))

def dated(url):
    s=unquote(url)
    for pattern,fmt in [(r'(\d{2}[._]\d{2}[._]\d{4})','%d.%m.%Y'),(r'(20\d{6})','%Y%m%d')]:
        m=re.search(pattern,s)
        if m:
            try:return datetime.strptime(m[1].replace('_','.'),fmt).date()
            except ValueError:pass
    return None

def newest(urls,today):
    valid=[(dated(u),u) for u in urls if dated(u) and dated(u)<=today]
    if not valid:raise ValueError('Nije pronađen datirani cjenik.')
    d,u=max(valid)
    return d.isoformat(),u

def discover(chain,today,fetch=get):
    page=PAGES[chain]
    if chain=='SPAR / INTERSPAR':
        # Endpoint is published by the official page; never invent a file URL.
        for offset in range(7):
            d=today-timedelta(days=offset)
            url=f'https://www.spar.hr/datoteke_cjenici/Cjenik{d:%Y%m%d}.json'
            try:index=json.loads(fetch(url).decode('utf-8-sig'))
            except HTTPError as e:
                if e.code==404:continue
                raise
            selected=[f for f in index['files'] if '_pula_rimske_centurijacije_101_' in f['name'].lower()]
            if not selected:continue
            f=selected[0]
            if dated(f['name'])!=d:raise ValueError('Datum SPAR datoteke ne odgovara indeksu.')
            return d.isoformat(),f['URL'],f.get('SHA')
        raise ValueError('Nema cjenika za odabranu INTERSPAR poslovnicu u zadnjih 7 dana.')
    html=fetch(page).decode('utf-8',errors='replace')
    urls=links(html,page)
    if chain in ('Plodine','Eurospin'):urls=[u for u in urls if u.lower().endswith('.zip')]
    else:urls=[u for u in urls if u.lower().endswith('.csv') and '_52100_' in unquote(u) and 'labinska' in unquote(u).lower()]
    d,u=newest(urls,today)
    return d,u,None

def validate_csv(chain,name,blob,source):
    text=decode(blob)
    header=norm(text.splitlines()[0]) if text.splitlines() else ''
    if not ('naziv' in header and ('mpc' in header or 'maloprod' in header)):
        raise ValueError('Neprepoznat format cjenika: '+name)
    count=sum(1 for row in parse(chain,name,blob,source) if row['price']>0)
    if count<100:raise ValueError('Cjenik nema dovoljno valjanih proizvoda: '+name)
    return count

def ingest(chain,dt,url,blob,folder,expected_sha=None):
    if expected_sha and hashlib.sha256(blob).hexdigest()!=expected_sha.lower():
        raise ValueError('SPAR provjera SHA-256 nije prošla.')
    entries=[]
    if chain in ('Plodine','Eurospin'):
        pattern=r'_52\d{3}_|_UMAG_' if chain=='Plodine' else r'Pula|Pore|Labin|Pazin|52\d{3}'
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            selected=[x for x in z.infolist() if x.filename.lower().endswith('.csv') and re.search(pattern,x.filename,re.I)]
            if not selected:raise ValueError('Arhiva nema istarske poslovnice.')
            if sum(x.file_size for x in selected)>500*1024*1024:raise ValueError('Prevelika raspakirana arhiva.')
            for i,x in enumerate(selected):
                if dated(x.filename) and dated(x.filename).isoformat()!=dt:raise ValueError('Datum datoteke ne odgovara arhivi.')
                content=z.read(x);validate_csv(chain,x.filename,content,url)
                path=folder/f'{i}.csv';path.write_bytes(content)
                entries.append(dict(name=x.filename,path=path.relative_to(ROOT).as_posix(),source=url))
    else:
        name=unquote(urlsplit(url).path).split('/')[-1]
        validate_csv(chain,name,blob,url)
        path=folder/'0.csv';path.write_bytes(blob)
        entries=[dict(name=name,path=path.relative_to(ROOT).as_posix(),source=url,city='Pula',
                      address='Labinska ulica 2A' if chain=='Lidl' else 'Rimske centurijacije 101')]
    return dict(date=dt,url=url,sha256=hashlib.sha256(blob).hexdigest(),downloaded_at=now(),files=entries)

def read_state():
    return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'chains':{},'status':[]}

def update_one(chain,previous,folder,today,fetch=get):
    if chain in ('Konzum','Tommy'):
        fresh=download_files(chain,today,fetch,links,validate_csv,folder,ROOT,previous)
        fresh['downloaded_at']=now()
        return fresh,'Svi istarski cjenici iz indeksa preuzeti i provjereni.'
    if chain=='Studenac':
        fresh=download_studenac(today,fetch,validate_csv,folder,ROOT,previous)
        fresh['downloaded_at']=now()
        return fresh,'XML cjenici istarskih poslovnica preuzeti i provjereni.'
    dt,url,sha=discover(chain,today,fetch)
    if previous and dt<previous['date']:raise ValueError('Izvor nudi stariji cjenik; zadržan je noviji spremljeni.')
    version=remote_version(url) if not sha and (fetch is get or getattr(fetch,'official_fetch',False)) else None
    same_content=(sha and previous and sha.lower()==previous['sha256']) or (version and (version.get('etag') or version.get('modified')) and previous and version==previous.get('remote_version'))
    if previous and url==previous['url'] and same_content and all((ROOT/f['path']).is_file() for f in previous['files']):
        return previous,'Provjereno; posljednji objavljeni cjenik je već spremljen.'
    fresh=ingest(chain,dt,url,fetch(url),folder,sha)
    fresh['remote_version']=version
    return fresh,'Cjenik uspješno preuzet i provjeren.'

def refresh(progress=lambda message:None,fetch=get,today=None,build_screen=True):
    today=today or date.today();state=copy.deepcopy(read_state());statuses=[]
    if fetch is get:
        def download(url):return get(url,progress=progress)
        download.official_fetch=True
        fetch=download
    batch=ROOT/'cjenici'/uuid.uuid4().hex;batch.mkdir(parents=True)
    for index,chain in enumerate(PAGES):
        progress('Provjeravam '+chain+'…')
        folder=batch/str(index);folder.mkdir()
        old=state['chains'].get(chain)
        try:
            fresh,message=update_one(chain,old,folder,today,fetch)
            state['chains'][chain]=fresh
            statuses.append(dict(chain=chain,ok=True,message=message,date=fresh['date'],checked_at=now()))
        except Exception as e:
            statuses.append(dict(chain=chain,ok=False,message='Zadržani spremljeni podaci. '+str(e)[:220],date=old['date'] if old else '2026-10-10',checked_at=now()))
    state['status']=statuses;state['last_attempt']=now()
    if not build_screen:
        atomic_write(STATE,json.dumps(state,ensure_ascii=False,indent=2))
        progress('Cjenici spremljeni za Android katalog.')
        return statuses
    progress('Izrađujem usporedbu…')
    # Build everything before publishing. A parser/build failure leaves the served HTML intact.
    data=build(state,output=False)
    spec=importlib.util.spec_from_file_location('screen',ROOT/'izradi-ekran.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    html=module.render(data)
    atomic_write(ROOT/'usporedba-podaci.json',json.dumps(data,ensure_ascii=False,separators=(',',':')))
    atomic_write(STATE,json.dumps(state,ensure_ascii=False,indent=2))
    atomic_write(ROOT/'Lovac-na-akcije.html',html)
    progress('Osvježavanje završeno.')
    return statuses

if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(refresh(print),ensure_ascii=False,indent=2))
