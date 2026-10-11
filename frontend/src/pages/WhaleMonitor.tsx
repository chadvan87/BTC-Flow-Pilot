import {useEffect,useState} from 'react';
import {api} from '../services/api';
import {Panel,Empty,fmt} from '../components/Panel';
const hcm=(ms:number)=>new Date(ms).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh'});
const pct=(v:number|null|undefined)=>v===null||v===undefined?'N/A':(v*100).toFixed(1)+'%';
const signedPct=(v:number|null|undefined)=>v===null||v===undefined?'N/A':(v>0?'+':'')+(v*100).toFixed(1)+'%';
const ago=(ms:number|null|undefined,now:number)=>ms?Math.max(0,Math.round((now-ms)/1000))+'s ago':'—';
const tone:Record<string,string>={bullish:'green',bearish:'pink',conflicting:'notice',neutral:'muted',unavailable:'muted'};
// Numeric thresholds editable from the dashboard. All are hypotheses that need validation.
const NUMERIC=['poll_seconds','stale_after_s','half_life_min','position_weight','reduce_weight','full_size_equity_frac','max_wallet_share','min_independent','min_fresh_wallets','bias_threshold','min_total_support','min_contribution','merge_window_s','discovery_min_wallets','discovery_min_quote_volume','discovery_max_spread_pct','discovery_max_abs_funding'];

export default function WhaleMonitor(){
 const [d,setD]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [walletText,setWalletText]=useState(''),[cfg,setCfg]=useState<any>(null);
 async function load(initial=false){try{const r=await api('/whales');setD(r);setError('');if(initial){setCfg(r.config);setWalletText(r.config.wallets.map((w:any)=>[w.address,w.label,w.cluster,w.quality].join(',')).join('\n'));}}catch(e){setError(String(e))}}
 useEffect(()=>{void load(true);const t=setInterval(()=>void load(),10000);return()=>clearInterval(t)},[]);
 async function run(fn:()=>Promise<unknown>){setBusy(true);setError('');try{await fn();await load()}catch(e){setError(String(e))}finally{setBusy(false)}}
 function wallets(){return walletText.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>{const [address,label='',cluster='',quality='1']=l.split(',').map(x=>x.trim());return {address,label,cluster,quality:Number(quality||1)}})}
 async function save(){
  if(cfg.require_confirmation!==d.config.require_confirmation&&!window.confirm('Changing whale-confirmation mode STOPS the bot. When ON, every entry (manual and AUTO) is blocked unless monitored whales SUPPORT the setup. Continue?'))return;
  await api('/whales/config','PUT',{...cfg,wallets:wallets()});
 }
 if(!d)return <div className="grid"><Panel title="Whale Confirmation Engine" wide>{error?<p className="notice">{error}</p>:<Empty>Loading…</Empty>}</Panel></div>;
 const now=d.now_ms;
 return <div className="grid">
  <Panel title="Whale Confirmation Engine · Hyperliquid" wide>
   <div className="warning"><b>{d.label}.</b> {d.hypothesis} Whale data only re-ranks setups that already passed trend, structure, order flow and the Risk Engine. It never opens, flips or closes positions, never increases risk and never moves stop losses.</div>
   <p>Collector: <b className={d.running?'green':'pink'}>{d.running?'running':'not running'}</b> · WebSocket: {d.ws.connected?<b className="green">connected</b>:<b className="muted">disconnected</b>} ({d.ws.users}/{d.ws.max_users} wallets streamed; others polled by REST) · Market context {ago(d.context_ms,now)} · Confirmation mode: <b className={d.config.require_confirmation?'notice':'muted'}>{d.config.require_confirmation?'REQUIRED (blocks entries unless whales support)':'advisory (ranking only)'}</b></p>
   {Object.keys(d.errors||{}).length>0&&<p className="notice">Errors: {Object.entries(d.errors).map(([k,v])=>k+': '+v).join(' · ')}</p>}
   {error&&<p className="notice">{error}</p>}
  </Panel>

  <Panel title="Whale bias by coin · monitored wallets" wide>
   {d.coins.length?<table><thead><tr><th>Coin</th><th>List</th><th>State</th><th>Net</th><th>Long / short support</th><th>Independent L / S</th><th>Actions 15m · 1h · 4h</th><th>Last action</th><th>Why</th></tr></thead><tbody>
    {d.coins.map((c:any)=>{const b=c.bias;return <tr key={c.coin}><td>{c.coin}<br/><small className="muted">{c.symbol||'no Binance map'}</small></td><td>{c.watch}</td><td><b className={tone[b.state]}>{b.state.toUpperCase()}</b></td><td>{signedPct(b.net)}</td><td>{fmt(b.long_support,3)} / {fmt(b.short_support,3)}</td><td>{b.supporting_long} / {b.supporting_short}</td><td>{b.windows['15m'].actions} · {b.windows['1h'].actions} · {b.windows['4h'].actions}</td><td>{ago(b.last_action_ms,now)}</td><td><details><summary>{b.fresh_wallets} fresh{b.stale_wallets?` · ${b.stale_wallets} stale`:''}</summary>{b.reasons.map((r:string,i:number)=><div key={i}>{r}</div>)}</details></td></tr>})}
   </tbody></table>:<Empty>Add wallets below to start monitoring</Empty>}
   <small>Net = (long − short) / (long + short) of decayed, equity-scaled support; ADD/OPEN raise their own side, REDUCE/CLOSE only lower their own side. One cluster is capped at {pct(d.config.max_wallet_share)} of a side, so a single whale cannot create a bias alone.</small>
  </Panel>

  <Panel title="Long / Short cohort · monitored wallets" wide>
   {d.coins.length?<table><thead><tr><th>Coin</th><th>Wallets L / S</th><th>Long % (wallets)</th><th>Net bias (wallets)</th><th>Gross long / short</th><th>Long % (exposure)</th><th>Long % (weighted)</th><th>Size Δ 1h L / S</th><th>Size Δ 4h L / S</th><th>Funding · OI (context)</th></tr></thead><tbody>
    {d.coins.map((c:any)=>{const k=c.cohort,ch=(w:string)=>k.exposure_change[w]?fmt(k.exposure_change[w].long_usd,0)+' / '+fmt(k.exposure_change[w].short_usd,0):'N/A';return <tr key={c.coin}><td>{c.coin}</td><td>{k.wallets_long} / {k.wallets_short}</td><td>{pct(k.long_pct_wallets)}</td><td>{signedPct(k.net_bias_wallets)}</td><td>{fmt(k.gross_long_usd,0)} / {fmt(k.gross_short_usd,0)}</td><td>{pct(k.long_pct_exposure)}</td><td>{pct(k.long_pct_weighted)}</td><td>{ch('1h')}</td><td>{ch('4h')}</td><td>{c.context?.funding!=null?(c.context.funding*100).toFixed(4)+'%':'—'} · {fmt(c.context?.open_interest,0)}</td></tr>})}
   </tbody></table>:<Empty>No monitored positions</Empty>}
   <small>Counts only the wallets you monitor — not exchange-wide long/short ratios. Size Δ = traded size × current mark, so price moves alone never appear as exposure change. N/A when the denominator is zero. Hyperliquid funding/OI is context only.</small>
  </Panel>

  <Panel title="Whale action timeline (24h)" wide>
   {d.timeline.length?<table><thead><tr><th>Time (HCMC)</th><th>Wallet</th><th>Coin</th><th>Action</th><th>Size</th><th>Notional</th><th>Fills merged</th><th>Source</th></tr></thead><tbody>
    {d.timeline.map((a:any)=><tr key={a.id}><td>{hcm(a.time)}</td><td title={a.user}>{a.wallet}</td><td>{a.coin}</td><td className={a.action==='OPEN'||a.action==='ADD'?(a.side==='LONG'?'green':'pink'):'muted'}>{a.action} {a.side}</td><td>{fmt(a.qty,6)}</td><td>{fmt(a.notional,0)}</td><td>{a.fills||'—'}</td><td>{a.source==='snapshot_reconcile'?'reconciled (fills missing)':'fills'}</td></tr>)}
   </tbody></table>:<Empty>No actions since monitoring began. The first snapshot of each wallet is a baseline, not a trade.</Empty>}
  </Panel>

  <Panel title="Monitored wallets · freshness">
   {d.wallets.length?<table><thead><tr><th>Wallet</th><th>Status</th><th>Source</th><th>Updated</th><th>Equity</th><th>Gross exposure</th><th>Weight</th></tr></thead><tbody>
    {d.wallets.map((w:any)=><tr key={w.address}><td title={w.address}>{w.label||w.address.slice(0,8)+'…'+w.address.slice(-4)}{w.cluster&&<small className="muted">cluster {w.cluster}</small>}</td><td className={w.fresh?'green':'pink'}>{w.error?'ERROR '+w.error:w.fresh?'FRESH':w.baseline_ms?'STALE':'WAITING BASELINE'}</td><td>{w.source}</td><td>{w.age_s!=null?w.age_s+'s ago':'—'}</td><td>{fmt(w.account_value,0)}</td><td>{fmt(w.gross_usd,0)}</td><td title={'quality '+w.quality+' × history '+fmt(w.history,2)}>{fmt(w.weight,2)}</td></tr>)}
   </tbody></table>:<Empty>No wallets configured</Empty>}
   <small>Weight = your quality tier × recent realised-PnL/equity factor (heuristic, not a win probability). Stale or missing wallets contribute nothing.</small>
  </Panel>

  <Panel title="Coin discovery → research watchlist">
   {d.suggestions.length?d.suggestions.map((s:any)=><div key={s.coin+s.side} className="check"><span><b>{s.coin}</b> {s.side} · {s.independent_wallets} independent wallets{s.opposing_wallets?` (${s.opposing_wallets} opposing)`:''}<br/><small>{s.checks.map((c:any)=><span key={c.name} className={c.ok?'green':'pink'}>{c.ok?'✓':'✗'} {c.name}: {c.detail}<br/></span>)}</small></span><button disabled={busy||!s.passed} onClick={()=>void run(()=>api('/whales/research','POST',{symbol:s.symbol,approve:true}))}>Add to research</button></div>):<Empty>No coin outside the watchlist has enough independent whale opens/adds in the last hour.</Empty>}
   <h2 style={{marginTop:20}}>Research watchlist</h2>
   {d.research.length?d.research.map((r:any)=><div key={r.symbol} className="check"><span>{r.symbol} ({r.coin}) · added {hcm(r.approved_ms)}</span><button disabled={busy} onClick={()=>void run(()=>api('/whales/research','POST',{symbol:r.symbol,approve:false}))}>Remove</button></div>):<p className="muted">Empty</p>}
   <small>Research only: whale bias is shown for these coins but they cannot be traded. Enabling trading needs your review and a code change to the trading symbol list.</small>
  </Panel>

  {cfg&&<Panel title="Settings · hypotheses to validate" wide>
   <label>Wallets — one per line: address, label, cluster, quality (0–2). Wallets in the same cluster count as one.<textarea className="code" value={walletText} onChange={e=>setWalletText(e.target.value)} placeholder="0xabc…,whale-1,fundA,1"/></label>
   <label><input type="checkbox" style={{width:'auto',marginRight:8}} checked={cfg.require_confirmation} onChange={e=>setCfg({...cfg,require_confirmation:e.target.checked})}/>Require whale confirmation — block entries unless whales SUPPORT the setup (also blocks when data is unavailable)</label>
   <label><input type="checkbox" style={{width:'auto',marginRight:8}} checked={cfg.history_factor} onChange={e=>setCfg({...cfg,history_factor:e.target.checked})}/>Use recent realised PnL as a wallet weight factor</label>
   <div className="form-grid">{NUMERIC.map(k=><label key={k}>{k}<input type="number" step="any" value={cfg[k]} onChange={e=>setCfg({...cfg,[k]:Number(e.target.value)})}/></label>)}</div>
   <div className="actions"><button className="primary" disabled={busy} onClick={()=>void run(save)}>Save whale settings</button></div>
   <small>Max 30 wallets. The first 10 stream over WebSocket (Hyperliquid limit); the rest are polled by REST. Defaults are starting hypotheses, not tuned values.</small>
  </Panel>}
 </div>
}
