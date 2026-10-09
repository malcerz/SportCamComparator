import sys,struct,tempfile,threading
from pathlib import Path
from datetime import datetime,timedelta,timezone
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from telemetry_dji_wire import varint,select,decode_sample,exposure_pair
from telemetry_mp4 import MP4Metadata,TelemetryError,boxes
from telemetry_dji import DJITelemetry
from telemetry_factory import create_telemetry,NullTelemetry


def vi(v):
    b=bytearray()
    while v>=128:b.append((v&127)|128);v>>=7
    b.append(v);return bytes(b)

def msg(field,b):return vi(field*8+2)+vi(len(b))+b

def sample(iso=100,exposure=(1,500),clip=False,frame=0,packed=True):
    camera=b''
    if iso is not None:camera+=msg(3,b'\x0d'+struct.pack('<f',iso))
    if exposure is not None:
        values=[v if v>=0 else v+(1<<64) for v in exposure]
        rational=msg(1,b''.join(vi(v) for v in values)) if packed else b''.join(b'\x08'+vi(v) for v in values)
        camera+=msg(4,rational)
    result=msg(3,msg(1,b'\x08'+vi(frame))+msg(2,camera))
    if clip:result=msg(1,msg(1,msg(1,b'dvtm_ac206.proto')+msg(10,b'DJI OsmoAction6')))+result
    return result

def box(tag,b,extended=False):
    return (struct.pack('>I4sQ',1,tag,len(b)+16) if extended else struct.pack('>I4s',len(b)+8,tag))+b

def table(tag,rows,fmt,version=0):return box(tag,bytes([version,0,0,0])+struct.pack('>I',len(rows))+b''.join(struct.pack(fmt,*r) for r in rows))

def movie(payloads,co64=False,ctts=None,edits=None,version=0,default_size=False,codec=b'djmd'):
    # 2 samples in first chunk, one in second: verifies stsc transitions.
    chunks=[payloads[:2],payloads[2:]] if len(payloads)>2 else [payloads]
    mdat=b'';offsets=[];positions=[]
    for chunk in chunks:
        offsets.append(8+len(mdat))
        for p in chunk:positions.append(8+len(mdat));mdat+=p
        mdat+=b'padding, not metadata'
    epoch=datetime(1904,1,1,tzinfo=timezone.utc)
    created=int((datetime(2026,9,28,4,42,18,tzinfo=timezone.utc)-epoch).total_seconds())
    clock=(bytes([version,0,0,0])+ (struct.pack('>QQIQ',created,created,30000,9009) if version else struct.pack('>IIII',created,created,30000,9009)))
    sizes=[len(p) for p in payloads]
    stsz=box(b'stsz',b'\0'*4+struct.pack('>II',sizes[0] if default_size else 0,len(sizes))+(b'' if default_size else b''.join(struct.pack('>I',s) for s in sizes)))
    mapping=[(1,len(chunks[0]),1)]
    if len(chunks)>1:mapping.append((2,len(chunks[1]),1))
    stbl=box(b'stsd',b'\0'*4+struct.pack('>I',1)+box(codec,b'\0'*12))
    stbl+=table(b'stts',[(1,3003),(len(payloads)-1,1001)],'>II')
    stbl+=table(b'stsc',mapping,'>III')+stsz+table(b'co64' if co64 else b'stco',[(o,) for o in offsets],'>Q' if co64 else '>I')
    if ctts:stbl+=table(b'ctts',ctts,'>Ii',1)
    mdia=box(b'mdhd',clock)+box(b'hdlr',b'\0'*8+b'meta'+b'\0'*12+b'CAM meta\0')+box(b'minf',box(b'stbl',stbl))
    tkhd=b'\0'*12+struct.pack('>I',3)
    trak=box(b'tkhd',tkhd)+box(b'mdia',mdia)
    if edits:trak+=box(b'edts',table(b'elst',edits,'>Iihh'))
    return box(b'mdat',mdat)+box(b'moov',box(b'mvhd',clock)+box(b'trak',trak),extended=True),positions


class WireTests(unittest.TestCase):
    def test_real_action6_first_sample(self):
        # Actual 277-byte sample from the supplied 14.98-GB Action 6 file.
        data=bytes.fromhex('0a670a570a106476746d5f61633230362e70726f746f120830322e30312e31391a05322e302e312a0e394b52585031563030424e375843320b31302e30302e33362e3631488df9aeab01520f444a49204f736d6f416374696f6e361204080110014a02080472007a0012240a071a05766964656f1a1308801e10f0101d8fc2ef412001280a3004400122002a0208031a83010a06108df9aeab01125d1a050d0000c84522050a030191012a050d0000803f32030887223a02080142004a140de827c23d157da37cbf1d656901be2599a4093d520f15a6c1cd3b1d379f333e25b41c7a3f5a0062006a0318fb0772050a03a7010a7a040a021c0a221a0a14080110012209444a492041433030362d8fc2ef4112021801')
        result=decode_sample(data)
        self.assertEqual(result[0:2],('DJI OsmoAction6','dvtm_ac206.proto'))
        self.assertEqual(result[3],6400)
        self.assertEqual(result[5],(1,145))
        self.assertAlmostEqual(result[4],1/145)

    def test_packed_unpacked_float_and_missing(self):
        for packed in [True,False]:
            result=decode_sample(sample(1251.0,(1,50),packed=packed))
            self.assertEqual(result[3:5],(1251,.02))
        for iso in [None,float('nan'),float('inf')]:
            self.assertIsNone(decode_sample(sample(iso,None))[3])
        for rational in [(1,0),(-1,50),(1,),None]:
            self.assertIsNone(decode_sample(sample(100,rational))[4])

    def test_wire_types_unknown_and_bounds(self):
        extra=b'\x80\x01'+vi(123)+b'\x89\x01'+b'12345678'+msg(99,b'opaque')+b'\x95\x01'+b'abcd'
        self.assertEqual(decode_sample(sample()+extra)[3],100)
        for bad in [b'\x80',b'\x0a\x09x',b'\x0d\0',b'\x09\0',b'\x00',b'\x0b']:
            with self.assertRaises(TelemetryError):select(bad,{1})
        with self.assertRaises(TelemetryError):varint(b'\xff'*10)


class MP4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'not-a-DJI-name.mp4'
    def tearDown(self):self.tmp.cleanup()
    def save(self,**kwargs):
        payloads=[sample(100,(1,1000),True),sample(200,(1,500),frame=1),sample(400,(1,50),frame=2)]
        data,positions=movie(payloads,**kwargs);self.path.write_bytes(data);return positions

    def test_offsets_stsc_stco_co64_clocks_and_timeline(self):
        for wide in [False,True]:
            for version in [0,1]:
                positions=self.save(co64=wide,version=version)
                metadata=MP4Metadata(self.path)
                offsets,sizes,times,_=metadata.sample_table(metadata.tracks[0])
                self.assertEqual(offsets,positions)
                self.assertEqual(times,[0,.1001,.13346666666666668])
                self.assertEqual(metadata.created.astimezone(timezone.utc),datetime(2026,9,28,4,42,18,tzinfo=timezone.utc))
                self.assertEqual(metadata.tracks[0].track_id,3)

    def test_ctts_signed_and_edits(self):
        self.save(ctts=[(1,-1001),(2,1001)],edits=[(3000,-1,1,0),(9009,1001,1,0)])
        m=MP4Metadata(self.path)
        times=m.sample_table(m.tracks[0])[2]
        self.assertAlmostEqual(times[0],.1-2*1001/30000)
        self.assertAlmostEqual(times[1],.2001)

    def test_default_size_and_bad_tables(self):
        data,pos=movie([sample(),sample()],default_size=True);self.path.write_bytes(data)
        m=MP4Metadata(self.path);self.assertEqual(m.sample_table(m.tracks[0])[0],pos)
        m.tracks[0].stbl[b'stts']=b'\0'*4+struct.pack('>III',1,1000,1001)
        with self.assertRaises(TelemetryError):m.sample_table(m.tracks[0])
        self.path.write_bytes(struct.pack('>I4s',999,b'moov'))
        with self.assertRaises(TelemetryError):MP4Metadata(self.path)

    def test_native_provider_overlay_ass_no_subprocess(self):
        self.save()
        with patch('subprocess.Popen',side_effect=AssertionError('External decoder used')):
            p=create_telemetry(self.path)
        self.assertIsInstance(p,DJITelemetry)
        self.assertEqual(p.camera_name,'DJI Osmo Action 6')
        self.assertEqual(p.get_at(.125).iso,400)
        self.assertEqual(p.get_at(-1).iso,100)
        self.assertEqual(p.get_at(99).iso,400)
        self.assertEqual(p.get_datetime_at(2),p.get_datetime_at(0)+timedelta(seconds=2))
        text=p.get_overlay_text(.125)
        self.assertEqual(len(text.splitlines()),5)
        self.assertNotIn('WB',text)
        self.assertIn('EXP  : 1/50',text)
        self.assertIn(text.replace('\n','\\N'),p.generate_ass(.25,fps=8))

    def test_factory_gopro_and_null(self):
        self.save(codec=b'gpmd')
        with patch('telemetry_factory.GPMFTelemetry',return_value='unchanged') as gopro:
            self.assertEqual(create_telemetry(self.path),'unchanged')
            gopro.assert_called_once_with(self.path, cancel_event=None)
        self.save(codec=b'dbgi');self.assertIsInstance(create_telemetry(self.path),NullTelemetry)

    def test_missing_fields_and_cancel(self):
        data,_=movie([sample(None,None,True)]);self.path.write_bytes(data)
        p=DJITelemetry(self.path)
        self.assertIsNone(p.samples[0].iso)
        self.assertNotIn('None',p.get_overlay_text(0))
        event=threading.Event();event.set()
        with self.assertRaisesRegex(TelemetryError,'Anulowano'):DJITelemetry(self.path,cancel_event=event)

    def test_action4_5_and_malformed_sample(self):
        for schema in [b'ac203',b'ac204',b'ac206']:
            first=sample(100,(1,500),True).replace(b'ac206',schema)
            data,_=movie([first,b'\x0a\x80'])
            self.path.write_bytes(data)
            p=DJITelemetry(self.path)
            self.assertEqual(p.protocol,'dvtm_'+schema.decode()+'.proto')
            self.assertEqual(p.benchmark['malformed_samples'],1)
            self.assertIsNone(p.samples[1].iso)
            self.assertIsNone(p.samples[1].exposure)

    def test_fragmented_and_complex_edits_rejected(self):
        self.path.write_bytes(box(b'moof',b''))
        with self.assertRaisesRegex(TelemetryError,'Fragmented'):MP4Metadata(self.path)
        self.save(edits=[(9009,0,2,0)])
        m=MP4Metadata(self.path)
        with self.assertRaisesRegex(TelemetryError,'rate'):m.sample_table(m.tracks[0])

if __name__=='__main__':unittest.main()
