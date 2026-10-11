'use strict';
window.microsWifi = {
  async mount(root, device, api, setBusy) {
    const text = document.createElement('p');
    text.setAttribute('role','status'); root.append(text);
    if (!device.online) { text.textContent='Connect this board to edit its saved Wi-Fi networks.'; return; }
    if (device.status?.network?.profiles_api !== 1) {
      text.textContent='A compatible USB base update is required to edit Wi-Fi networks here.'; return;
    }
    const capacity=device.status?.network?.profiles_capacity||4;
    const single=capacity===1, dual=capacity===2;
    const backupIndex=dual?1:3;
    text.textContent='Reading saved networks from the board…';
    const path='/api/devices/'+device.device_id+'/wifi';
    let saved;
    try { saved=(await api(path)).networks; }
    catch(error) {
      if(!root.isConnected)return;
      text.textContent='Could not read saved networks. '+error.message;
      const retry=document.createElement('button');retry.textContent='Retry reading networks';
      retry.onclick=()=>{root.replaceChildren();window.microsWifi.mount(root,device,api,setBusy);};
      root.append(retry);return;
    }
    if (!root.isConnected) return;
    text.textContent=dual?'Try the primary network first, then the fallback. A working connection stays connected.':single?'This board stores one network. Saving keeps the current connection active; the saved network is used when it reconnects.':'Try the primary networks in order, then the iPhone hotspot if none connect. A working connection stays connected.';
    const form=document.createElement('form'); form.autocomplete='off';
    const primaries=saved.filter(n=>!n.fallback), fallback=saved.find(n=>n.fallback);
    const rows=[];
    for(let i=0;i<capacity;i++) {
      const network=i===backupIndex?fallback:primaries[i];
      const row=document.createElement('fieldset'); row.className='wifi-row';
      row.innerHTML=`<legend>${i===backupIndex?(dual?'Fallback network':'Backup · iPhone hotspot'):'Primary '+(i+1)}</legend><label>Network name (SSID)<input class="wifi-ssid" type="text" autocomplete="off" spellcheck="false" placeholder="${i===backupIndex&&!dual?'Your iPhone hotspot name':'Network name'}"></label><label>Password<input class="wifi-password" type="password" autocomplete="new-password" placeholder="New password, or leave unchanged"></label><label class="wifi-open"><input type="checkbox"> Open network (no password)</label><small class="wifi-hint"></small>`;
      const ssid=row.querySelector('.wifi-ssid'), password=row.querySelector('.wifi-password'), open=row.querySelector('[type=checkbox]'), hint=row.querySelector('.wifi-hint');
      ssid.value=network?.ssid||'';
      open.checked=Boolean(network&&!network.secured);
      const update=()=>{
        const existing=saved.find(n=>n.ssid===ssid.value);
        hint.textContent=existing?(existing.secured?'Password saved on board. Leave blank to keep it.':'Saved as an open network.'):'Enter a password for a new network, or select Open network. Leave the name empty to omit this slot.';
        password.disabled=open.checked;
        if(open.checked) password.value='';
      };
      ssid.addEventListener('input',update);open.addEventListener('change',update);update();
      form.append(row);rows.push({row,ssid,password,open,update});
    }
    let replaceExtra;
    if(primaries.length>3) {
      const warning=document.createElement('label');warning.className='wifi-extra';
      replaceExtra=document.createElement('input');replaceExtra.type='checkbox';replaceExtra.required=true;
      warning.append(replaceExtra,document.createTextNode(' Replace the existing four-primary list with these three primaries and the backup. The extra network “'+primaries[3].ssid+'” will be removed unless entered above.'));
      form.append(warning);
    }
    const note=document.createElement('p');note.className='caption';
    note.textContent=(single||dual)?'Passwords travel over TLS and are stored only on the board. Leave the password blank to retain it for the same network. Saving does not test a new password.':'Passwords are sent to the board over TLS and are not saved in console history or its database. The board stores credentials in NVS. Saving replaces the list; it does not test the new passwords. Turn on Personal Hotspot when you need the backup.';
    const button=document.createElement('button');button.type='submit';button.className='primary';button.textContent='Save networks';
    const result=document.createElement('p');result.setAttribute('role','status');
    const reload=document.createElement('button');reload.type='button';reload.textContent='Reload saved networks';
    reload.addEventListener('click',()=>{root.replaceChildren();window.microsWifi.mount(root,device,api,setBusy);});
    const actions=document.createElement('div');actions.className='actions';actions.append(button,reload);
    form.append(note,actions,result);root.append(form);
    form.addEventListener('submit',async event=>{
      event.preventDefault(); if(button.disabled)return;
      const networks=[]; const seen=new Set(); const encoder=new TextEncoder();
      for(const {ssid,password,open} of rows) {
        if(!ssid.value) {networks.push(null);continue;}
        const bytes=encoder.encode(ssid.value).length;
        if(bytes>32 || ssid.value.includes('\0') || seen.has(ssid.value)) {result.textContent='Use distinct network names of 1–32 UTF-8 bytes.';return;}
        seen.add(ssid.value);
        const existing=saved.find(n=>n.ssid===ssid.value);
        if(!open.checked&&!password.value&&!existing) {result.textContent='Enter a password or select Open network for each new network.';return;}
        const secret=open.checked?'':password.value||null;
        const length=secret===null?0:encoder.encode(secret).length;
        if(secret && (secret.includes('\0') || !(length>=8&&length<=63 || /^[0-9a-fA-F]{64}$/.test(secret)))) {result.textContent='Passwords must be 8–63 UTF-8 bytes, or a 64-character hex key.';return;}
        networks.push({ssid:ssid.value,password:secret});
      }
      if(!seen.size) {result.textContent='Keep at least one network.';return;}
      if(replaceExtra&&!replaceExtra.checked)return;
      button.disabled=true;reload.disabled=true;rows.forEach(({row})=>row.disabled=true);setBusy(true);
      result.textContent='Saving on the board…';
      try {
        const pending=api(path,{networks});
        rows.forEach(({password})=>password.value='');
        networks.forEach(n=>{if(n)n.password=null;});
        await pending;
        saved=(await api(path)).networks;
        const ordered=[...saved.filter(n=>!n.fallback)];
        rows.forEach(({ssid,open,update},i)=>{const network=i===backupIndex?saved.find(n=>n.fallback):ordered[i];ssid.value=network?.ssid||'';open.checked=Boolean(network&&!network.secured);update();});
        if(replaceExtra)replaceExtra.closest('label').remove();replaceExtra=null;
        result.textContent='Saved on the board. Its current connection stays active; the new order applies when it reconnects.';
      } catch(error) {result.textContent=error.message+' Read the saved list again before retrying if the outcome is unknown.';}
      finally {rows.forEach(({row,password})=>{password.value='';row.disabled=false;});button.disabled=false;reload.disabled=false;setBusy(false);}
    });
  }
};

window.addEventListener('pagehide',()=>document.querySelectorAll('.wifi-password').forEach(input=>input.value=''));
