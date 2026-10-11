import {ReactNode} from 'react';
export function Panel({title,children,wide=false}:{title:string;children:ReactNode;wide?:boolean}){return <section className={'panel '+(wide?'wide':'')}><h2>{title}</h2>{children}</section>}
export function Empty({children}:{children:ReactNode}){return <div className="empty">{children}</div>}
// Price precision scales with magnitude so low-priced coins (TRX, DOGE) stay readable.
export const pfmt=(v:unknown)=>{const a=Math.abs(Number(v));return fmt(v,a>=1000?2:a>=10?3:a>=1?4:6)};
export const fmt=(v:unknown,n=2)=>v===null||v===undefined?'—':Number(v).toLocaleString('en-US',{maximumFractionDigits:n});
