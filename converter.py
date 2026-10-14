from pathlib import Path
import struct,json,math,io,zipfile
from assets import ROOT
from telltale.d3dmesh import parse_d3dmesh
from telltale.skeleton import parse_skeleton
from telltale.metastream import parse_header as meta_header
from telltale.d3dtx import parse_d3dtx,convert_to_dds
from decode_d3dtx import decode_d3dtx,pixels_to_png
from export_rigged_glb import mat4_identity,trs_to_mat4,mat4_mul,mat4_invert_rigid
from parse_anm import parse_header
from parse_anm_values import walk_anm
from jp_animation import install_jp_decoders
install_jp_decoders()

def multiply_quat(a,b):
    x,y,z,w=a;u,v,s,t=b
    return [w*u+x*t+y*s-z*v,w*v-x*s+y*t+z*u,w*s+x*v-y*u+z*t,w*t-x*u-y*v-z*s]

def slerp(a,b,t):
    dot=sum(x*y for x,y in zip(a,b))
    if dot<0:b=[-x for x in b];dot=-dot
    if dot>.9995:
        q=[x+(y-x)*t for x,y in zip(a,b)];norm=math.sqrt(sum(x*x for x in q))
        return [x/norm for x in q] if norm else [0,0,0,1]
    angle=math.acos(max(-1.,min(1.,dot)));den=math.sin(angle)
    return [(math.sin((1-t)*angle)*x+math.sin(t*angle)*y)/den for x,y in zip(a,b)]

def bound_keys(rows,duration,rotation=False,step=False):
    """Evaluate boundary poses before clipping quantized time keys to clip time."""
    def at(time):
        if time<=rows[0][0]:return rows[0][1]
        for (t,a),(u,b) in zip(rows,rows[1:]):
            if time<=u:
                if step:return a
                weight=(time-t)/(u-t)
                return slerp(a,b,weight) if rotation else [x+(y-x)*weight for x,y in zip(a,b)]
        return rows[-1][1]
    duration=max(0.,duration)
    out=[(0.,at(0.))]+[(t,v) for t,v in rows if 0.<t<duration]
    if duration>0:out.append((duration,at(duration)))
    return out

def png(data):
    w,h,fmt,pixels=decode_d3dtx(data)
    import zlib
    def chunk(t,d):return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
    raw=b''.join(b'\0'+bytes(c for pix in pixels[y*w:(y+1)*w] for c in pix) for y in range(h))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')

def audio(data):
    # Telltale AUD wraps standard streams; preserve the payload's actual encoding.
    if data[:4]==b'RIFF':return data,'.wav','audio/wav'
    if data[:4]==b'OggS':return data,'.ogg','audio/ogg'
    if data[:3]==b'ID3':return data,'.mp3','audio/mpeg'
    if data[:4]==b'ERTM' and data[8:16]==struct.pack('<Q',0x338E4BAD4D941F67):
        return vox_ogg(data),'.spx','audio/ogg'
    for marker,ext,mime in [(b'RIFF','.wav','audio/wav'),(b'OggS','.ogg','audio/ogg'),(b'ID3','.mp3','audio/mpeg'),(b'FSB4','.fsb','application/octet-stream'),(b'FSB5','.fsb','application/octet-stream')]:
        off=data.find(marker,0,65536)
        if off>=0:
            out=data[off:]
            if marker==b'RIFF':out=out[:struct.unpack_from('<I',out,4)[0]+8]
            return out,ext,mime
    # MPEG audio headers require consecutive coherent frames, not an arbitrary sync byte.
    def frame(p):
        if p+4>len(data):return None
        x=int.from_bytes(data[p:p+4],'big')
        if x>>21!=2047:return None
        ver=(x>>19)&3;layer=(x>>17)&3;bi=(x>>12)&15;si=(x>>10)&3
        if ver==1 or layer!=1 or bi in (0,15) or si==3:return None
        rate=[44100,48000,32000][si]//(1 if ver==3 else 2 if ver==2 else 4)
        bit=([0,32,40,48,56,64,80,96,112,128,160,192,224,256,320] if ver==3 else [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160])[bi]*1000
        return (144 if ver==3 else 72)*bit//rate+((x>>9)&1)
    for p in range(min(len(data)-8,65536)):
        n=frame(p)
        if n and frame(p+n) and frame(p+n+frame(p+n)):return data[p:],'.mp3','audio/mpeg'
    raise ValueError('This audio encoding is not yet decoded. Export Original to preserve the complete game file.')

def vox_ogg(data):
    """Wrap JP VoiceData's wideband Speex packet table in a standard Ogg stream."""
    block_size,frame_size,byte_rate,channels=struct.unpack_from('<4I',data,25)
    if channels not in (1,2):raise ValueError('Invalid VOX channel count')
    extra=struct.unpack_from('<I',data,49)[0]==0
    count_pos=45 if extra else 41
    count=struct.unpack_from('<I',data,count_pos)[0];table=count_pos+4
    if not 1<count<1000000 or table+count*4>len(data):raise ValueError('Invalid VOX packet table')
    offsets=list(struct.unpack_from('<'+'I'*count,data,table));start=table+count*4
    if offsets[0]!=0 or offsets!=sorted(offsets) or offsets[-1]>len(data)-start:raise ValueError('Invalid VOX packet offsets')
    packets=[data[start+a:start+b] for a,b in zip(offsets,offsets[1:]+[len(data)-start])]
    # Ogg Speex bitstream version 4, WB mode, 320 samples per frame at 16 kHz.
    header=b'Speex   '+b'speex-1.2.1'.ljust(20,b'\0')+struct.pack('<13i',1,80,16000,1,4,channels,-1,320,1,1,0,0,0)
    comment=packets[0]
    if len(comment)<8 or struct.unpack_from('<I',comment)[0]>len(comment)-8:
        vendor=b'Jurassic Asset Studio';comment=struct.pack('<I',len(vendor))+vendor+struct.pack('<I',0)
    table_crc=[]
    for value in range(256):
        x=value<<24
        for _ in range(8):x=((x<<1)^0x04c11db7 if x&0x80000000 else x<<1)&0xffffffff
        table_crc.append(x)
    def page(packet,seq,flags,granule):
        laces=[255]*(len(packet)//255)+[len(packet)%255]
        if len(laces)>255:raise ValueError('VOX packet exceeds an Ogg page')
        out=bytearray(b'OggS'+bytes([0,flags])+struct.pack('<QIII',granule,0x4a50564f,seq,0)+bytes([len(laces)])+bytes(laces)+packet)
        crc=0
        for value in out:crc=((crc<<8)^table_crc[((crc>>24)^value)&255])&0xffffffff
        struct.pack_into('<I',out,22,crc);return out
    out=page(header,0,2,0)+page(comment,1,0,0)
    for i,p in enumerate(packets[1:],2):out+=page(p,i,4 if i==len(packets) else 0,(i-1)*320)
    return bytes(out)

class GLB:
    def __init__(self):
        self.bin=bytearray(); self.g={'asset':{'version':'2.0','generator':'Jurassic Asset Studio'},'scene':0,'scenes':[{'nodes':[]}],'nodes':[],'meshes':[],'materials':[],'buffers':[{}],'bufferViews':[],'accessors':[]}
    def view(self,b,target=None):
        self.bin.extend(b'\0'*((-len(self.bin))%4));v={'buffer':0,'byteOffset':len(self.bin),'byteLength':len(b)}
        if target:v['target']=target
        self.bin.extend(b);self.g['bufferViews'].append(v);return len(self.g['bufferViews'])-1
    def acc(self,values,kind='VEC3',component=5126,target=None,bounds=False):
        widths={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16};n=widths[kind]
        rows=[(v,) if n==1 else v for v in values];flat=[x for row in rows for x in row]
        blob=struct.pack('<'+{5126:'f',5123:'H',5125:'I'}[component]*len(flat),*flat)
        a={'bufferView':self.view(blob,target),'componentType':component,'count':len(rows),'type':kind}
        if bounds:a.update(min=[min(r[i] for r in rows) for i in range(n)],max=[max(r[i] for r in rows) for i in range(n)])
        self.g['accessors'].append(a);return len(self.g['accessors'])-1
    def write(self):
        self.bin.extend(b'\0'*((-len(self.bin))%4)); self.g['buffers'][0]['byteLength']=len(self.bin)
        j=json.dumps(self.g,separators=(',',':')).encode();j+=b' '*((-len(j))%4)
        return struct.pack('<4sII',b'glTF',2,28+len(j)+len(self.bin))+struct.pack('<I4s',len(j),b'JSON')+j+struct.pack('<I4s',len(self.bin),b'BIN\0')+self.bin

def anim_values(data):
    base=meta_header(data).data_offset
    # Jurassic Park adds ToolProps (empty u32 + bool) before the animation block.
    size=struct.unpack_from('<I',data,base+24)[0]
    if size==0 and data[base+28:base+29] in (b'0',b'1'):
        data=data[:base+24]+data[base+29:]
    h=parse_header(data)
    values=walk_anm(data)
    if len(values)!=h.total_interfaces:raise ValueError('Unsupported animation channel layout. Original ANM export is available.')
    return h,values

def model(lib,key,animation_ids=()):
    item=lib.get(key);mesh=parse_d3dmesh(lib.read(key));b=GLB();g=b.g;notes=[]
    stem=Path(item['name']).stem;skitem=lib.find(stem+'.skl',item)
    bones=[];hashmap={}
    if skitem:
        bones=parse_skeleton(lib.read(skitem['id']),version=2).bones
        hashmap={x.hash_value:i for i,x in enumerate(bones)}
        for x in bones:g['nodes'].append({'name':x.name,'translation':list(x.local_position),'rotation':list(x.local_rotation)})
        for i,x in enumerate(bones):
            if x.parent_index>=0:g['nodes'][x.parent_index].setdefault('children',[]).append(i)
            else:g['scenes'][0]['nodes'].append(i)
        world=[None]*len(bones)
        def matrix(i):
            if world[i] is None:
                x=bones[i];local=trs_to_mat4(x.local_position,x.local_rotation)
                world[i]=mat4_mul(matrix(x.parent_index),local) if x.parent_index>=0 else local
            return world[i]
        ibm=b.acc([mat4_invert_rigid(matrix(i)) for i in range(len(bones))],'MAT4')
        g['skins']=[{'joints':list(range(len(bones))),'inverseBindMatrices':ibm}]
    primitives=[];base=0;texture_cache={}
    for sm in mesh.submeshes:
        vs=sm.vertices;faces=[tuple(i-base for i in f) for f in sm.faces];base+=len(vs)
        if not vs or not faces:continue
        if any(i<0 or i>=len(vs) for f in faces for i in f):raise ValueError('Mesh indices exceed vertex bounds')
        a={'POSITION':b.acc([v.position for v in vs],target=34962,bounds=True)}
        if all(v.normal for v in vs):a['NORMAL']=b.acc([v.normal for v in vs],target=34962)
        # The mesh reader converts Direct3D UVs to bottom-origin coordinates.
        # glTF's embedded images and UVs both use a top-left origin, so undo
        # that conversion here rather than flipping the texture pixels.
        if all(v.uv for v in vs):a['TEXCOORD_0']=b.acc([(v.uv[0],1.0-v.uv[1]) for v in vs],'VEC2',target=34962)
        if bones and all(v.bone_indices is not None and v.bone_weights is not None for v in vs):
            palette=mesh.bone_names[sm.bone_set_index] if 0<=sm.bone_set_index<len(mesh.bone_names) else []
            joints=[];weights=[]
            for v in vs:
                w=[max(0,float(x)) for x in v.bone_weights];total=sum(w)
                w=[x/total for x in w] if total else [1,0,0,0]
                ids=[]
                for j,weight in zip(v.bone_indices,w):
                    h=int(palette[j],16) if j<len(palette) else None
                    if weight>0 and h not in hashmap:raise ValueError('Unresolved weighted bone palette entry')
                    ids.append(hashmap.get(h,0))
                joints.append(ids);weights.append(w)
            a['JOINTS_0']=b.acc(joints,'VEC4',5123,34962);a['WEIGHTS_0']=b.acc(weights,'VEC4',target=34962)
        mat={'name':sm.material_name or sm.name,'doubleSided':True,'pbrMetallicRoughness':{'metallicFactor':0,'roughnessFactor':0.85,'baseColorFactor':[0.55,0.65,0.45,1]}}
        tname=(sm.material_name or sm.name)+'.d3dtx';tx=lib.find(tname,item)
        if tx:
            try:
                if tx['id'] not in texture_cache:
                    image=png(lib.read(tx['id']));g.setdefault('images',[]).append({'bufferView':b.view(image),'mimeType':'image/png'})
                    g.setdefault('textures',[]).append({'source':len(g['images'])-1});texture_cache[tx['id']]=len(g['textures'])-1
                mat['pbrMetallicRoughness'].update(baseColorTexture={'index':texture_cache[tx['id']]},baseColorFactor=[1,1,1,1])
            except Exception as ex:notes.append('Texture '+tname+': '+str(ex))
        if mat['name'].startswith('color_'):
            try:mat['pbrMetallicRoughness']['baseColorFactor']=[int(mat['name'][6:][i:i+2],16)/255 for i in (0,2,4)]+[1]
            except ValueError:pass
        # JP uses an outer eye shell with the shared eye normal map. Its
        # flat grey diffuse is a reflection tint, not an opaque eyeball.
        if (sm.texture_names.get('bump','').lower()=='sharedparts_eye_nm'
                and mat['name'].lower() in ('color_cccccc','color_ffffff')):
            mat['pbrMetallicRoughness'].update(baseColorFactor=[1,1,1,1],roughnessFactor=0.03)
            mat['extensions']={'KHR_materials_transmission':{'transmissionFactor':1.0},'KHR_materials_ior':{'ior':1.38}}
            for extension in mat['extensions']:
                if extension not in g.setdefault('extensionsUsed',[]):g['extensionsUsed'].append(extension)
        g['materials'].append(mat)
        primitives.append({'attributes':a,'indices':b.acc([i for f in faces for i in f],'SCALAR',5125,34963),'material':len(g['materials'])-1})
    if not primitives:raise ValueError('No mesh geometry was decoded')
    g['meshes'].append({'name':stem,'primitives':primitives});node={'name':stem,'mesh':0}
    if bones and any('JOINTS_0' in p['attributes'] for p in primitives):node['skin']=0
    g['nodes'].append(node);g['scenes'][0]['nodes'].append(len(g['nodes'])-1)
    for aid in animation_ids:
        if not bones:raise ValueError('This model has no matching skeleton')
        ah,values=anim_values(lib.read(aid));anim={'name':Path(lib.get(aid)['name']).stem,'samplers':[],'channels':[]}
        for value in values:
            ji=hashmap.get(value.name_hash)
            if ji is None:continue
            samples=value.samples
            if samples is None:raise ValueError('Could not decode skeletal channel '+value.type_name)
            if not samples:continue
            compressed=value.type_name=='CompressedTransformKeys'
            step=compressed and all(s.interpolation==0 for s in samples)
            if compressed:
                samples=[{'time':s.time,'qx':s.quat[0],'qy':s.quat[1],'qz':s.quat[2],'qw':s.quat[3],'x':s.vec3[0],'y':s.vec3[1],'z':s.vec3[2]} for s in samples]
            for path,fields in [('rotation',('qx','qy','qz','qw')),('translation',('x','y','z'))]:
                if path=='rotation' and 'Quaternion' in value.type_name:fields=('x','y','z','w')
                if any(not isinstance(s,dict) or not all(f in s for f in fields) for s in samples):continue
                clean=[]
                for s in sorted(samples,key=lambda s:s.get('time',0)):
                    time=s.get('time',0);vec=[s[f] for f in fields]
                    if path=='translation':
                        # Skeletal animation positions encode a direction times
                        # the bone's bind-pose length, rather than absolute meters.
                        length=math.sqrt(sum(x*x for x in bones[ji].local_position))
                        vec=[x*length for x in vec]
                        if value.flags&0x10000:vec=[x+y for x,y in zip(bones[ji].local_position,vec)]
                    if not all(math.isfinite(x) for x in vec):raise ValueError('Non-finite animation keyframe')
                    if path=='rotation':
                        if value.flags&0x10000:vec=multiply_quat(bones[ji].local_rotation,vec)
                        norm=math.sqrt(sum(x*x for x in vec));vec=[x/norm for x in vec] if norm else [0,0,0,1]
                        if clean and sum(x*y for x,y in zip(vec,clean[-1][1]))<0:vec=[-x for x in vec]
                    if clean and time==clean[-1][0]:clean[-1]=(time,vec)
                    else:clean.append((time,vec))
                clean=bound_keys(clean,ah.length,path=='rotation',step)
                input_id=b.acc([x[0] for x in clean],'SCALAR',bounds=True);out_id=b.acc([x[1] for x in clean],'VEC4' if path=='rotation' else 'VEC3')
                anim['samplers'].append({'input':input_id,'output':out_id,'interpolation':'STEP' if step else 'LINEAR'})
                anim['channels'].append({'sampler':len(anim['samplers'])-1,'target':{'node':ji,'path':path}})
        if not anim['channels']:raise ValueError('Animation has no supported channels matching this skeleton')
        g.setdefault('animations',[]).append(anim)
    g['extras']={'source':item['name'],'notes':notes,'bones':len(bones),'animationCount':len(animation_ids)}
    return bytes(b.write())



