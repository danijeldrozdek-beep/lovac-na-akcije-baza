"""Daily cloud job: refresh, validate a complete feed, then bound cached files."""
import gzip, hashlib, html, importlib.util, json, os, re, sqlite3, tempfile
from contextlib import closing
from pathlib import Path
from pretraga import ROOT
from osvjezi import read_state, atomic_write

def verify_feed(folder):
    folder=Path(folder);m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    name=m['file']
    if m['schema']!=1 or not re.fullmatch(r'katalog-[a-f0-9]{64}\.bin',name):raise ValueError('Neispravan manifest.')
    packed=folder/name
    if not packed.is_file() or packed.stat().st_size!=m['compressed_bytes']:raise ValueError('Nedostaje cijela datoteka baze.')
    with packed.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=m['sha256']:raise ValueError('Pogrešan SHA-256.')
    with tempfile.TemporaryDirectory() as directory:
        dbfile=Path(directory)/'check.sqlite';total=0
        with gzip.open(packed,'rb') as stream,dbfile.open('wb') as output:
            while chunk:=stream.read(1024*1024):
                total+=len(chunk)
                if total>m['database_bytes'] or total>500_000_000:raise ValueError('Prevelika baza.')
                output.write(chunk)
        if total!=m['database_bytes']:raise ValueError('Nepotpuna baza.')
        with closing(sqlite3.connect(dbfile)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Neispravna baza.')
            meta=dict(db.execute('SELECT key,value FROM metadata'))
            if meta['schema']!='1' or any(meta[k]!=m[k] for k in ('date_min','date_max')):raise ValueError('Datum/shema nisu sukladni.')
            for table in ('products','stores','offers'):
                n=db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                if n<1 or n!=m[table]:raise ValueError('Neispravan broj '+table)
    return m

def compact(root,state):
    root=Path(root).resolve();prices=(root/'cjenici').resolve()
    keep=set()
    # Validate all reference paths before removing any generated files.
    for info in state['chains'].values():
        for item in info['files']:
            path=(root/item['path'].replace('\\','/')).resolve()
            if not path.is_relative_to(prices) or not path.is_file():raise ValueError('Neispravna putanja spremljenog cjenika.')
            keep.add(path)
    if prices.exists():
        for path in prices.rglob('*.csv'):
            resolved=path.resolve()
            if not resolved.is_relative_to(prices):raise ValueError('Putanja izlazi iz direktorija cjenika.')
            if resolved not in keep:path.unlink()
        for path in sorted(prices.rglob('*'),key=lambda p:len(p.parts),reverse=True):
            if path.is_dir() and not path.is_symlink() and path.resolve().is_relative_to(prices) and not any(path.iterdir()):
                try:path.rmdir()
                except PermissionError:pass  # Empty ReadOnly Windows folders do not affect the cache/feed.
    feed=root/'internet-katalog'
    manifest=json.loads((feed/'manifest.json').read_text(encoding='utf-8'))
    old=sorted((p for p in feed.glob('katalog-*.bin') if re.fullmatch(r'katalog-[a-f0-9]{64}\.bin',p.name) and p.name!=manifest['file']),key=lambda p:p.stat().st_mtime,reverse=True)
    # Keep two older snapshots for clients that received a cached manifest during deployment.
    for path in old[2:]:path.unlink()

def run(update=True):
    spec=importlib.util.spec_from_file_location('publisher',ROOT/'objavi-katalog.py')
    publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
    publisher.publish(update)
    feed=ROOT/'internet-katalog';manifest=verify_feed(feed);state=read_state()
    status=dict(checked_at=state.get('last_attempt'),sources=state.get('status',[]),catalogue=manifest)
    atomic_write(feed/'status.json',json.dumps(status,ensure_ascii=False,indent=2))
    rows=''.join('<li>'+html.escape(s['chain']+': '+s['message']+' (cjenik '+s['date']+')')+'</li>' for s in status['sources'])
    page='<!doctype html><html lang="hr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Lovac na akcije — baza</title><body><h1>Lovac na akcije — Istra</h1><p>Internetski izvor za Android aplikaciju.</p>'
    page+=f'<p>Cjenici: {html.escape(manifest["date_min"])} – {html.escape(manifest["date_max"])}. Artikli: {manifest["products"]}; poslovnice: {manifest["stores"]}.</p>'
    page+='<p><a href="manifest.json">Manifest za aplikaciju</a> · <a href="status.json">Status provjere</a></p><ul>'+rows+'</ul><p>Cjenici ne potvrđuju zalihu na polici. Zadnja provjera ne znači da su svi lanci objavili nove cijene.</p></body></html>'
    atomic_write(feed/'index.html',page)
    compact(ROOT,state)
    print('Paket provjeren. Spreman za objavu.',flush=True)

if __name__=='__main__':
    import argparse,sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--bez-osvjezavanja',action='store_true')
    run(not parser.parse_args().bez_osvjezavanja)
