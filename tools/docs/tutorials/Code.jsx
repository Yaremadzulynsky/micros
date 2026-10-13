import { useEffect, useMemo, useState } from 'react';
import { highlightLines } from './highlight-code.js';

export function Code({text, language, highlights = [], annotations = [], copy = true}) {
  const coloredLines = useMemo(()=>highlightLines(text, language),[text,language]);
  const [copied,setCopied] = useState(false);
  const [error,setError] = useState(false);
  const [explain,setExplain] = useState(true);
  useEffect(()=>{setCopied(false);setError(false)},[text]);
  async function copyText(){try {await navigator.clipboard.writeText(text);setCopied(true)}catch{setError(true)}}
  return <div className="bt-code-wrap">
    <div className="bt-code-toolbar">
      {annotations.length>0 && <button aria-pressed={explain} onClick={()=>setExplain(!explain)}>{explain?'Hide added-line notes':'Explain added lines'}</button>}
      {copy && <button onClick={copyText}>{copied?'Copied':error?'Select text to copy':'Copy'}</button>}
    </div>
    <div className={`bt-code ${explain && annotations.length?'bt-code-annotated':''}`} tabIndex={0} aria-label="Code and line explanations">
      {text.split('\n').map((line,i)=>{
        const added=highlights.some(term=>line.includes(term));
        const note=explain && added?annotations.find(([match])=>line.trim().startsWith(match))?.[1]:null;
        return <div className={`bt-code-row ${added?'bt-row-highlight':''}`} key={i}>
          <div className="bt-source-line"><span className="bt-line-no" aria-hidden="true">{i+1}</span><code className={`language-${language}`}>{coloredLines[i]?.length ? coloredLines[i].map((token,j)=><span key={j} className={token.classes.map(name=>`bt-token-${name}`).join(' ')}>{token.text}</span>) : ' '}</code></div>
          {note && <div className="bt-line-explanation"><span aria-hidden="true">↳</span><p><span className="bt-sr-only">Line {i+1}: </span>{note}</p></div>}
        </div>;
      })}
    </div>
  </div>;
}
