"""Expand the versioned MKR wire report into the common management schema."""
SERVICE_FIELDS = ('name version state result steps callbacks arena_reserved stack_reserved '
                  'stack_free_bytes handles_limit handles_open timers_limit timers_open '
                  'gpio_granted gpio_open publish_mask subscribe_mask hook_max_us '
                  'callback_max_us timer_late_max_us image_bytes').split()
CHANNEL_FIELDS = ('key policy depth payload_bytes publishers subscribers backlog published '
                  'missed age_us retained_bytes').split()
STATES = ('Unloaded', 'Loaded', 'Initializing', 'Starting', 'Running', 'Stopping', 'Stopped', 'Failed')


def expand(status, serial=False):
    if not isinstance(status, dict) or status.get('platform') != 'samd21' or not (status.get('samd_telemetry') == 1 or status.get('embedded_layout') == 1):
        return status
    if status.get('embedded_layout') == 1:
        status=dict(status)
        status['board']=dict(status.get('board',{}),profile='Arduino MKR WiFi 1010',flash_mb=0.25)
        return layout(status)
    from micros_tooling.platforms.embedded.telemetry import tables
    pins=status['gpio_rows'];status=tables(status,serial)
    status['board']=dict(profile='Arduino MKR WiFi 1010',flash_mb=0.25,recovery_pin=None,
        gpio=[dict(name='D'+str(pin),line=i,pin=pin,output=bool(output),level=level)
              for i,(pin,output,level) in enumerate(pins)])
    status['labels_source']='device_graph'
    return layout(status)


def layout(status):
    from micros_tooling.platforms.embedded.telemetry import validate_slots
    validate_slots(status)
    ab=status.get('layout_version')==2
    bank_bytes,slot_bytes,bank_base=(40960,9216,180224) if ab else (65536,15360,131072)
    parts=[dict(name='Arduino bootloader',offset=0,size=8192),
           dict(name='factory',offset=8192,size=114688),
           dict(name='activation',offset=122880,size=512),
           dict(name='Saved settings',offset=123392,size=1024),
           dict(name='Reserved',offset=124416,size=6656)]
    if ab:
        parts=[dict(name='Arduino bootloader',offset=0,size=8192),
               dict(name='Boot selector reservation',offset=8192,size=6144),
               dict(name='activation',offset=14336,size=512),
               dict(name='Base selection journal',offset=14848,size=512),
               dict(name='Saved settings',offset=15360,size=1024),
               dict(name='ota_0',offset=16384,size=81920),
               dict(name='ota_1',offset=98304,size=81920)]
    active=status.get('active',0xffffffff)
    indices=status.get('image_slots',list(range(len(status['services']))))
    slots=[dict(slot=i,name=s.get('name','Service slot '+str(i)),offset=active*bank_bytes+4096+i*slot_bytes,
                reserved_bytes=slot_bytes,**({'image_bytes':s['image_bytes']} if 'image_bytes' in s else {}))
           for i,s in zip(indices,status['services'])] if active in (0,1) else []
    for bank in (0,1):
        offset=bank_base+bank*bank_bytes
        if bank != active:
            parts.append(dict(name='Alternate service bank' if active in (0,1) else 'Service bank '+str(bank),
                offset=offset,size=bank_bytes,reservedCapacity=True,
                note='Reserved for application deployment and rollback. Stored contents are not measured; this is not base-firmware OTA storage.'))
            continue
        parts.append(dict(name='Active graph reservation',offset=offset,size=4096,
                          note='Reserved for the active application graph metadata.'))
        for i in range(4):
            slot=next((x for x in slots if x['slot']==i),None)
            region=dict(offset=offset+4096+i*slot_bytes,size=slot_bytes)
            if slot:
                region.update(name=slot['name'],image=slot,number=i+1)
            else:
                region.update(name='Unused service slot '+str(i),reservedCapacity=True,
                    note='No active service is assigned to this slot. Its capacity remains reserved; erased contents are not verified.')
            parts.append(region)
    status['flash']=dict(total_bytes=262144,partitions=parts,
                         services=dict(slot_bytes=slot_bytes,slots=slots))
    return status
