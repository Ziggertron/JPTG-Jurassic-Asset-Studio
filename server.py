import argparse,json,threading,webbrowser,urllib.parse,zipfile,io,struct,subprocess,shutil
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from assets import Library,ROOT,DEFAULT
from converter import model,png,audio,parse_d3dmesh,parse_d3dtx,convert_to_dds

lib=None;ready=threading.Event();scan_error=None
def scan(path):
    global lib,scan_error
    try:lib=Library(path).scan()
    except Exception as ex:scan_error=str(ex)
    finally:ready.set()

def export(key,fmt,animations=()):
    item=lib.get(key);name=Path(item['name']).name;stem=Path(name).stem
    if fmt=='original':return lib.read(key),name,'application/octet-stream'
    if fmt=='glb':return model(lib,key,animations),stem+'.glb','model/gltf-binary'
    if fmt=='gltf':
        data=model(lib,key,animations);jlen=struct.unpack_from('<I',data,12)[0];g=json.loads(data[20:20+jlen]);g['buffers'][0]['uri']='model.bin'
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr(stem+'.gltf',json.dumps(g,indent=2));z.writestr('model.bin',data[28+jlen:])
        return buf.getvalue(),stem+'-gltf.zip','application/zip'
    if fmt=='png':return png(lib.read(key)),stem+'.png','image/png'
    if fmt=='dds':return convert_to_dds(parse_d3dtx(lib.read(key))),stem+'.dds','image/vnd-ms.dds'
    if fmt in ('jpg','bmp','tga'):
        from PIL import Image
        im=Image.open(io.BytesIO(png(lib.read(key))))
        if fmt=='jpg':im=im.convert('RGB')
        buf=io.BytesIO();im.save(buf,format={'jpg':'JPEG','bmp':'BMP','tga':'TGA'}[fmt])
        return buf.getvalue(),stem+'.'+fmt,{'jpg':'image/jpeg','bmp':'image/bmp','tga':'image/x-tga'}[fmt]
    if fmt=='audio':
        data,ext,mime=audio(lib.read(key));return data,stem+ext,mime
    if fmt in ('wav','mp3','ogg'):
        data,ext,mime=audio(lib.read(key))
        if ext=='.'+fmt:return data,stem+ext,mime
        ff=shutil.which('ffmpeg')
        if not ff:
            try:
                import imageio_ffmpeg
                ff=imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:raise ValueError('Audio conversion needs FFmpeg. Use Audio export for the native playable format.')
        source=lib.cache/(key+ext);target=lib.cache/(key+'.'+fmt);source.write_bytes(data)
        result=subprocess.run([ff,'-v','error','-y','-i',str(source),str(target)],capture_output=True,timeout=120,creationflags=0x08000000)
        if result.returncode:raise ValueError(result.stderr.decode(errors='replace')[:500])
        return target.read_bytes(),stem+'.'+fmt,{'wav':'audio/wav','mp3':'audio/mpeg','ogg':'audio/ogg'}[fmt]
    if fmt=='obj':
        mesh=parse_d3dmesh(lib.read(key));lines=['# Jurassic Asset Studio: static geometry','o '+stem]
        for v in mesh.all_vertices:lines.append('v '+' '.join(str(x) for x in v.position))
        for sm in mesh.submeshes:
            lines+=['g '+sm.name]
            for f in sm.faces:lines.append('f '+' '.join(str(x+1) for x in f))
        return '\n'.join(lines).encode(),stem+'.obj','text/plain'
    if fmt=='json':
        from dataclasses import asdict
        from telltale.skeleton import parse_skeleton
        if item['extension']=='.skl':obj=asdict(parse_skeleton(lib.read(key),version=2))
        else:obj=lib.public(item)
        return json.dumps(obj,indent=2).encode(),stem+'.json','application/json'
    raise ValueError('Unknown export format')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,data,mime='application/json',status=200,name=None):
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if name:self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+urllib.parse.quote(name))
        self.end_headers();self.wfile.write(data)
    def js(self,obj,status=200):self.send(json.dumps(obj).encode(),status=status)
    def do_GET(self):
        try:
            u=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(u.query);p=u.path
            if p=='/api/status':return self.js({'ready':ready.is_set(),'error':scan_error,**(lib.summary() if ready.is_set() and lib else {})})
            if p.startswith('/api/'):
                if not ready.is_set():return self.js({'error':'Indexing archives. Please wait.'},503)
                if scan_error:raise ValueError(scan_error)
                if p=='/api/theme':
                    themes={'slate-left':'ui_menu_main_slatel','slate-right':'ui_menu_main_slater','background':'ui_menu_background','logo':'ui_menu_main_jplogo','highlight':'ui_menu_hilightyellow'}
                    name=themes.get(q.get('name',[''])[0])
                    if not name:return self.js({'error':'Unknown menu texture'},404)
                    item=lib.find(name+'.d3dtx')
                    if not item:return self.js({'error':'Menu texture unavailable'},404)
                    cache=lib.cache/(item['id']+'-menu.png')
                    with lib.lock:
                        cached=cache.read_bytes() if cache.exists() else None
                    if cached is None:
                        cached=png(lib.read(item['id']))
                        with lib.lock:cache.write_bytes(cached)
                    return self.send(cached,'image/png')
                if p=='/api/assets':
                    category=q.get('category',['Models'])[0];search=q.get('q',[''])[0].lower();episode=q.get('episode',[''])[0]
                    items=[lib.public(x) for x in lib.items.values() if (category=='All' or x['category']==category) and search in x['name'].lower() and (not episode or episode in x['archive'])]
                    items.sort(key=lambda x:('Localized' in x['archive'],not x['name'].startswith('sk'),x['name'],x['archive']))
                    return self.js({'items':items,'total':len(items)})
                key=q.get('id',[''])[0]
                if p=='/api/related':
                    item=lib.get(key);stem=Path(item['name']).stem
                    # Exact character prefix avoids attaching unrelated camera/prop animations.
                    prefixes=[stem+'_']
                    family=stem.split('_',1)[-1]
                    aliases=[family]
                    if 'tyrannosaurus' in family:aliases.append('trex')
                    elif 'dilophosaurus' in family:aliases.append('dilo')
                    elif 'velociraptor' in family:aliases.append('raptor')
                    elif 'compsognathus' in family:aliases.append('compy')
                    generic=stem.split('_',1)[0]+'_'
                    names={x['name'] for x in lib.items.values() if x['extension']=='.anm' and (x['name'].startswith(stem+'_') or (x['name'].startswith(generic) and any(a in x['name'] for a in aliases)))}
                    clips=[lib.public(lib.find(name,item)) for name in sorted(names,key=str.lower)]
                    return self.js({'animations':clips,'skeleton':bool(lib.find(stem+'.skl',item))})
                if p in ('/api/export','/api/preview'):
                    fmt=q.get('format',['original'])[0];animations=q.get('animations',[''])[0].split(',');animations=[x for x in animations if x]
                    if p=='/api/preview' and fmt=='audio' and lib.get(key)['extension']=='.vox':fmt='wav'
                    data,name,mime=export(key,fmt,animations)
                    return self.send(data,mime,name=name if p=='/api/export' else None)
                raise ValueError('Unknown request')
            path=(ROOT/'web'/urllib.parse.unquote(p).lstrip('/')).resolve() if p!='/' else ROOT/'web'/'index.html'
            if not path.is_relative_to((ROOT/'web').resolve()):return self.js({'error':'Invalid path'},400)
            import mimetypes
            if not path.is_file():return self.js({'error':'Not found'},404)
            self.send(path.read_bytes(),mimetypes.guess_type(path)[0] or 'application/octet-stream')
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as ex:self.js({'error':str(ex)},422)
    def do_POST(self):
        try:
            if self.headers.get('Origin') and urllib.parse.urlsplit(self.headers['Origin']).netloc!=self.headers.get('Host'):return self.js({'error':'Invalid origin'},403)
            if urllib.parse.urlsplit(self.path).path!='/api/batch':raise ValueError('Unknown request')
            n=int(self.headers.get('Content-Length',0))
            if n>1000000:raise ValueError('Batch request too large')
            req=json.loads(self.rfile.read(n));ids=req.get('ids',[]);fmt=req.get('format','original')
            if not 1<=len(ids)<=500:raise ValueError('Select 1–500 assets per batch')
            buf=io.BytesIO();errors=[]
            with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                for key in ids:
                    try:
                        data,name,mime=export(key,fmt,req.get('animations',[]))
                        z.writestr(key[:8]+'/'+name,data)
                    except Exception as ex:errors.append({'asset':lib.get(key)['name'],'error':str(ex)})
                z.writestr('export-report.json',json.dumps({'format':fmt,'requested':len(ids),'exported':len(ids)-len(errors),'errors':errors},indent=2))
            self.send(buf.getvalue(),'application/zip',name='Jurassic-assets.zip')
        except Exception as ex:self.js({'error':str(ex)},422)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--game-data',default=DEFAULT);ap.add_argument('--port',type=int,default=8765);ap.add_argument('--no-browser',action='store_true');args=ap.parse_args()
    threading.Thread(target=scan,args=(args.game_data,),daemon=True).start()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print('Jurassic Asset Studio: http://127.0.0.1:'+str(args.port),flush=True)
    if not args.no_browser:webbrowser.open('http://127.0.0.1:'+str(args.port))
    server.serve_forever()


