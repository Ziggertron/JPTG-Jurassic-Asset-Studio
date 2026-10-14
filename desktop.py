"""Windows desktop host with native save dialogs and an embedded 3D viewport."""
import sys,json,threading,traceback,zipfile,io,os
from pathlib import Path
from assets import DEFAULT,DATA_ROOT,ROOT
import server

class DesktopAPI:
    def __init__(self):self._window=None
    def report_ready(self,stage):
        (DATA_ROOT/'desktop-health.json').write_text(json.dumps({'version':7,'stage':stage,'assets':len(server.lib.items) if server.lib else 0}))
        return True
    def export_asset(self,key,fmt,animations):
        try:
            data,name,mime=server.export(key,fmt,animations)
            import webview
            paths=self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=name,file_types=(f'{fmt.upper()} (*{Path(name).suffix})', 'All files (*.*)'))
            if not paths:return {'cancelled':True}
            Path(paths[0]).write_bytes(data)
            return {'path':paths[0]}
        except Exception as ex:return {'error':str(ex)}
    def export_batch(self,ids,fmt):
        try:
            if not 1<=len(ids)<=500:raise ValueError('Select 1–500 assets per batch')
            import webview
            paths=self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename='Jurassic-assets.zip',file_types=('ZIP archive (*.zip)',))
            if not paths:return {'cancelled':True}
            errors=[]
            with zipfile.ZipFile(paths[0],'w',zipfile.ZIP_DEFLATED) as z:
                for key in ids:
                    try:
                        data,name,mime=server.export(key,fmt)
                        z.writestr(key[:8]+'/'+name,data)
                    except Exception as ex:errors.append({'asset':server.lib.get(key)['name'],'error':str(ex)})
                z.writestr('export-report.json',json.dumps({'requested':len(ids),'exported':len(ids)-len(errors),'errors':errors},indent=2))
            return {'path':paths[0],'errors':len(errors)}
        except Exception as ex:return {'error':str(ex)}
    def choose_game_folder(self):
        import webview
        paths=self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not paths:return {'cancelled':True}
        folder=Path(paths[0]);folder=folder/'GameData' if (folder/'GameData').is_dir() else folder
        if not any(folder.rglob('*.ttarch')):return {'error':'No TTARCH archives found. Choose the installed GameData folder.'}
        (DATA_ROOT/'settings.json').write_text(json.dumps({'game_data':str(folder)}))
        server.ready.clear();server.scan_error=None
        threading.Thread(target=server.scan,args=(str(folder),),daemon=True).start()
        return {'path':str(folder)}

def self_test(report):
    from assets import Library
    from converter import model,png,audio
    result={}
    try:
        server.lib=Library().scan();result['index']=server.lib.summary()
        item=server.lib.find('sk90_tyrannosaurus.d3dmesh');data=model(server.lib,item['id'])
        import struct
        g=json.loads(data[20:20+struct.unpack_from('<I',data,12)[0]])
        result['model']={'bytes':len(data),'bones':len(g['skins'][0]['joints']),'primitives':len(g['meshes'][0]['primitives'])}
        clips=[server.lib.find(name,item) for name in ['sk90_idle_tyrannosaurus.anm','sk90_tyrannosaurus_roarup.anm','sk90_move_tyrannosauruswalk.anm']]
        animated=model(server.lib,item['id'],[clip['id'] for clip in clips])
        ag=json.loads(animated[20:20+struct.unpack_from('<I',animated,12)[0]])
        result['animated_model']={'bytes':len(animated),'clips':[{'name':clip['name'],'channels':len(clip['channels'])} for clip in ag['animations']]}
        tx=server.lib.find('sk90_tyrannosaurusb.d3dtx');result['texture']={'png_bytes':len(png(server.lib.read(tx['id']))),'dds_bytes':len(server.export(tx['id'],'dds')[0])}
        for category in ['Music','Sounds','Voice']:
            x=next(x for x in server.lib.items.values() if x['category']==category)
            try:
                raw,ext,mime=audio(server.lib.read(x['id']));result[category]={'native':ext,'bytes':len(raw)}
                wav=server.export(x['id'],'wav')[0];result[category]['wav_bytes']=len(wav)
            except Exception as ex:result[category]={'error':str(ex)}
        result['ok']=True
    except Exception:result['error']=traceback.format_exc();result['ok']=False
    Path(report).write_text(json.dumps(result,indent=2))

def main():
    if '--self-test' in sys.argv:
        self_test(sys.argv[sys.argv.index('--self-test')+1]);return
    import webview
    path=DEFAULT
    try:path=json.loads((DATA_ROOT/'settings.json').read_text())['game_data']
    except (OSError,KeyError,ValueError):pass
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    threading.Thread(target=server.scan,args=(path,),daemon=True).start()
    bridge=DesktopAPI()
    window=webview.create_window('Jurassic Asset Studio',f'http://127.0.0.1:{http.server_port}',js_api=bridge,width=1440,height=920,min_size=(950,650),background_color='#111214')
    bridge._window=window
    window.events.closed+=lambda:http.shutdown()
    webview.settings['ALLOW_DOWNLOADS']=True
    webview.start(gui='edgechromium',private_mode=True)

if __name__=='__main__':
    try:main()
    except Exception:
        (DATA_ROOT/'startup-error.txt').write_text(traceback.format_exc())
        import ctypes
        ctypes.windll.user32.MessageBoxW(0,'The viewer could not start. See startup-error.txt beside the EXE for details.','Jurassic Asset Studio',16)






