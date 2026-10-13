"""MKR A/B base layout and initial selection record."""
import struct
import zlib
BASE_START=0x4000
BASE_BYTES=0x14000
SELECTOR_START=0x2000
BASE_JOURNAL=0x3a00
SETTINGS_START=0x3c00

def initial_record(base):
    if not 256<=len(base)<=BASE_BYTES or len(base)%4:raise ValueError('Invalid base size')
    sp,entry=struct.unpack_from('<II',base)
    if not 0x20000000<sp<=0x20008000 or sp%8 or not entry&1 or not BASE_START<=entry&~1<BASE_START+len(base):
        raise ValueError('Base must be linked for slot A')
    fields=[0x3242544d,1,0,0xffffffff,0xffffffff,0,len(base),0,zlib.crc32(base),0]+[0]*4
    data=struct.pack('<14I',*fields)
    return data+struct.pack('<II',zlib.crc32(data),0x54494d43)

def migration_image(base,selector,settings):
    if not 8<=len(selector)<=0x1800 or len(settings)!=1024:raise ValueError('Invalid migration geometry')
    sp,entry=struct.unpack_from('<II',selector)
    if sp!=0x20008000 or not entry&1 or not 0x2000<=entry&~1<0x2000+len(selector):raise ValueError('Invalid boot selector')
    record=initial_record(base)
    image=bytearray(b'\xff'*(BASE_START+len(base)-SELECTOR_START))
    image[:len(selector)]=selector
    start=BASE_JOURNAL-SELECTOR_START;image[start:start+len(record)]=record
    start=SETTINGS_START-SELECTOR_START;image[start:start+1024]=settings
    image[BASE_START-SELECTOR_START:]=base
    return image
