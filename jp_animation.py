"""Jurassic Park PC compressed transform keys and their time streams.

Derived from the installed game's CTK reader (ReadBlock / ComputeValue) and
CompressedTimeKeys reader. These streams use raw block counts and second-order
deltas. No game code is executed by this module.
"""
import math,struct
from dataclasses import dataclass

RANGES=(.01,.05,.1,.5,.7,.8,1.,1.5,2.,3.,4.,5.5,7.,8.5,10.,0.)
TIME_RANGES=(.1,1/6,1/3,.5,2/3,1.,2.,0.)

def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]

class Bits:
    def __init__(self,data):self.data=data;self.pos=0
    def at(self,pos,n):
        if n<0 or n>32 or pos+n>len(self.data)*8:raise ValueError('Truncated compressed animation stream')
        if not n:return 0
        first=pos//8;last=(pos+n+7)//8
        return (int.from_bytes(self.data[first:last],'little')>>(pos%8))&((1<<n)-1)
    def read(self,n):
        value=self.at(self.pos,n);self.pos+=n;return value
    def floating(self):
        # BitBuffer::ReadFloat reads 32 bits at the current bit position;
        # it does not align to a word boundary.
        value=struct.unpack('<f',struct.pack('<I',self.read(32)))[0]
        if not math.isfinite(value):raise ValueError('Non-finite compressed animation range')
        return value
    def range(self,bits,mode,table):
        if mode==len(table)-1:return self.floating()
        q=self.read(bits)
        # Zero range bits means the table value itself (q == mask == 0),
        # not a zero radius. This is common in fixed-rate time blocks.
        return f32(f32(table[mode])*q/((1<<bits)-1)) if bits else f32(table[mode])

@dataclass
class TransformKey:
    time:float
    quat:tuple
    vec3:tuple
    interpolation:int=1

def decode_transforms(data,return_bits=False):
    if not data:return ([],0) if return_bits else []
    b=Bits(data);count=b.at(0,14)
    widths=[b.at(14+3*i,3) for i in range(7)]
    range_width=b.at(35,4);range_mode=b.at(39,4);block_width=b.at(43,3)+1
    per_block_interpolation=b.at(48,1);b.pos=49
    interpolation=b.at(46,2)
    pose=[0.,0.,0.,1.,0.,0.,0.];velocity=[0.]*7
    remaining=0;keys=[]
    for index in range(count):
        if remaining==0:
            acceleration=b.read(1)
            sizes=[b.read(w) for w in widths]
            remaining=b.read(block_width)
            if not remaining:raise ValueError('Invalid zero-length transform block')
            radius=b.range(range_width,range_mode,RANGES) if any(sizes) else 0.
            if per_block_interpolation:interpolation=b.read(2)
        delta=[f32(radius*(2.*b.read(n)/((1<<n)-1)-1.)) if n else 0. for n in sizes]
        # Flag selects a velocity or a delta of velocity; the resulting velocity
        # always adds to the previous pose. Quaternion normalization happens per key.
        velocity=[f32(a+c) for a,c in zip(velocity,delta)] if acceleration else delta
        pose=[f32(a+c) for a,c in zip(pose,velocity)]
        norm=math.sqrt(sum(q*q for q in pose[:4]))
        pose[:4]=[f32(q/norm) for q in pose[:4]] if norm else [0.,0.,0.,1.]
        keys.append(TransformKey(float(index),tuple(pose[:4]),tuple(pose[4:]),interpolation))
        remaining-=1
    if len(data)*8-b.pos>7:raise ValueError('Compressed transform stream did not consume its payload')
    return (keys,b.pos) if return_bits else keys

def decode_times(data,count,return_bits=False,trace=None):
    if not data and count<=1:
        out=[0.]*count;return (out,0) if return_bits else out
    b=Bits(data);value_width=b.at(0,3);block_width=b.at(3,3)+1;range_width=b.at(6,4);range_mode=b.at(10,3);b.pos=13
    time=f32(-1/30);velocity=f32(1/30);remaining=0;times=[]
    for _ in range(count):
        if remaining==0:
            acceleration=b.read(1);size=b.read(value_width);remaining=b.read(block_width)
            if not remaining:raise ValueError('Invalid zero-length time block')
            radius=b.range(range_width,range_mode,TIME_RANGES) if size else 0.
        q=b.read(size)
        delta=f32(radius*((2.*q/((1<<size)-1)-1.) if acceleration else q/((1<<size)-1))) if size else 0.
        velocity=f32(velocity+delta) if acceleration else delta
        time=f32(time+velocity);times.append(time)
        if trace is not None:trace.append((b.pos,size,remaining,acceleration,radius,velocity))
        remaining-=1
    if len(data)*8-b.pos>7:raise ValueError('Compressed time stream did not consume its payload')
    if any(y<x-1e-5 for x,y in zip(times,times[1:])):raise ValueError('Compressed animation times are not monotonic')
    return (times,b.pos) if return_bits else times

def install_jp_decoders():
    import parse_anm_values as walker
    from parse_ctk import read_size_prefix
    original=walker._read_ctk_like_with_decode
    def read_value(data,pos,type_name):
        if type_name!='CompressedTransformKeys':return original(data,pos,type_name)
        size,start=read_size_prefix(data,pos)
        time_size,time_start=read_size_prefix(data,start+size)
        end=time_start+time_size
        if end>len(data):raise ValueError('Compressed animation payload exceeds file size')
        samples=decode_transforms(data[start:start+size])
        times=decode_times(data[time_start:end],len(samples))
        for sample,time in zip(samples,times):sample.time=time
        return end,samples
    walker._decode_ctk=decode_transforms
    walker._decode_time_keys=decode_times
    walker._read_ctk_like_with_decode=read_value
