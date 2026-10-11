import {useState} from 'react';
import {api} from '../services/api';
import {SYMBOLS} from '../services/symbols';
import {Panel,fmt} from '../components/Panel';
export default function ManualOrder({refresh,disabled}:{refresh:()=>void;disabled:boolean}){
 const [form,setForm]=useState({symbol:'BTCUSDT',side:'LONG',ideal:'',stop:'',target:'',tolerance_pct:'0.15'});
 const [id,setId]=useState(()=>crypto.randomUUID().replaceAll('-','').slice(0,24));
 const [preview,setPreview]=useState<any>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const payload=()=>({...form,ideal:Number(form.ideal),stop:Number(form.stop),target:Number(form.target),tolerance_pct:Number(form.tolerance_pct),request_id:id});
 function change(k:string,v:string){setForm({...form,[k]:v});setPreview(null);setId(crypto.randomUUID().replaceAll('-','').slice(0,24));}
 async function run(submit=false){setBusy(true);setError('');try{
  if(submit&&!window.confirm('Xác nhận đặt MỘT lệnh Binance DEMO. Có thể phát sinh vị thế chưa được bảo vệ nếu sàn/API lỗi. Tiếp tục?'))return;
  const result=await api(submit?'/orders/demo':'/orders/preview','POST',{...payload(),confirm:submit});
  if(submit){setError('Execution state: '+result.state);refresh();}else setPreview(result);
 }catch(e){setError(String(e))}finally{setBusy(false)}}
 return <Panel title="Manual DEMO test order" wide><p className="muted">Bỏ qua chọn signal; vẫn áp dụng risk, news/crash guard, account và feed checks. REAL luôn bị khóa.</p><div className="form-grid">
 <label>Symbol<select value={form.symbol} onChange={e=>change('symbol',e.target.value)}>{SYMBOLS.map(s=><option key={s}>{s}</option>)}</select></label>
 <label>Direction<select value={form.side} onChange={e=>change('side',e.target.value)}><option>LONG</option><option>SHORT</option></select></label>
 {(['ideal','stop','target','tolerance_pct'] as const).map(k=><label key={k}>{({ideal:'Ideal entry',stop:'Stop loss',target:'Take profit',tolerance_pct:'Tolerance (%)'})[k]}<input type="number" step="any" value={form[k]} onChange={e=>change(k,e.target.value)}/></label>)}
 </div>{preview&&<div className="metrics"><div>Quantity<strong>{preview.quantity}</strong></div><div>Estimated risk<strong>{fmt(preview.risk_usdt,4)} USDT</strong></div><div>Net R:R<strong>1 : {fmt(preview.net_rr)}</strong></div><div>Effective tolerance<strong>{fmt(preview.tolerance_pct,4)}%</strong></div></div>}{preview?.whale&&<p className="muted">Whale (monitored wallets): {preview.whale.state} → {preview.whale.effect} for this side. Context only — it does not change size, SL or TP.</p>}
 <div className="actions"><button disabled={busy||disabled} onClick={()=>run()}>Preview risk & checks</button><button className="primary" disabled={busy||disabled||!preview} onClick={()=>run(true)}>Submit one DEMO test order</button></div><p className="notice">{error}</p><small>Backend tính lại toàn bộ checks khi submit. Retry cùng setup giữ nguyên request ID để tránh entry trùng.</small></Panel>
}
